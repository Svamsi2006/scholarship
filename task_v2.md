# TASK v2: Speed, Parallelism, Stand-out Features and UI (patch on task.md)

> **Precedence:** `task.md` is the base PRD. This file **overrides it wherever they conflict**. Everything not mentioned here stays as in `task.md` (models, evidence checking, no hardcoding, quality gate, deployment).
> **Deadline:** Oct 23, 2026, 11:59 PM IST. Work in priority order (Section 9). **P0 and P1 are mandatory. P2/P3 only if time remains.**
> **Follow the skills:** `verify-before-done`, `simplify`, `frontend-design` (UI work), `web-design-guidelines` (UI review). Use the docs-lookup MCP (Context7) before touching any CrewAI / Tavily / LiteLLM / MCP API.

---

## 1. What the real run showed (treat as the bug report)

A real run on a real profile (`docs/run_log_2026-10-21.txt`, started 7:49:51 pm) was still running after 13+ minutes. Findings, with evidence:

| # | Finding | Evidence in the log |
|---|---|---|
| 1 | **LLM turns take about 60 seconds each.** The Researcher spent 3m12s to run only 2 searches; the searches themselves took about 4 s each. | 7:50:35 to 7:51:40 before the first search; 7:51:44 to 7:52:43 before the second |
| 2 | **429s from Vertex AI cause candidates to be dropped.** 12 of 19 candidates in round 1 were "Skipping ... RateLimitError", and 3 more in round 2. This violates the recovery table in `task.md` (backoff and retry, never drop). | 7:54:33 to 7:54:42; 8:02:32 to 8:02:34 |
| 3 | **The app is calling Vertex AI** (`VertexAIException`), not the Gemini API. New or trial GCP projects commonly get a tiny dynamic quota there. | Error text |
| 4 | **Silent 4-minute gap** inside Verifier work (almost certainly an LLM call retrying a 429 inside LiteLLM). We have no visibility into LLM calls. | 7:56:41 to 8:00:35, no events |
| 5 | **Dead URLs are expensive.** One SSL-timeout URL cost about 50 s (3 attempts of 16-19 s). A **404 was retried twice**, which is pointless. | 7:55:26 to 7:56:18; 8:03:05 to 8:03:13 |
| 6 | **Researcher round 2 returned 0 new candidates** (wasted 32 s). | 8:01:18 to 8:01:50 |
| 7 | **Verifier uses LLM turns for web searches** to find official pages (Max Planck, WashU), each taking minutes. | 7:56:24 to 8:01:03 |
| 8 | **Aggregator blog used as a source** (`iefg.org`). Hurts the trust score. | 8:03:05 |
| 9 | **GitHub shows 6 repos and 1 language for an account with 20+ repos.** That cap came from our `task.md` ("top ~6"). It was a design mistake, not an API limit. | 7:49:58 |

**Root cause in one sentence:** each agent runs as a slow, multi-turn tool-using loop (about 5-8 LLM calls per task), phases run strictly one after another, and rate-limit errors are handled by dropping work. A run needs 100+ LLM calls when it should need about 40.

**Key insight:** wall time is about `max(network time, LLM_calls / LLM_RPM)`. Parallel workers do not help if every worker is rate-limited. **The biggest lever is cutting the number of LLM calls**, then parallelizing what remains.

---

## 2. Measurable Targets (Definition of Done for P0/P1)

Measure with `scripts/perf_report.py` (Section 8). Targets are for profile A and profile B, live APIs.

| Metric | Now | Target |
|---|---|---|
| End-to-end time | 13+ min, unfinished | **typical under 4 min, hard cap 7 min** |
| First verified result visible in UI | none until about 11 min | **within 90 s of research start** |
| LLM calls per run | 100+ (estimated) | **45 or fewer** |
| Candidates dropped because of 429 | 15 | **0** (backoff, then provider fallback) |
| Wasted retry on 4xx (except 408/429) | yes | **none** |
| Max wait on a dead URL | about 50 s | **10 s or less** |
| GitHub coverage | 6 repos, 1 language | **all repos counted; languages aggregated** |
| LLM calls with no logged start/end/duration | all | **none** |

If a target is missed, report the measured number and the reason in `docs/dev_log.md`. Do not claim success without the measurement.

---

## 3. P0: Core Speed Fixes

### 3.1 LLM gate and provider (replaces ad-hoc retrying)

1. **Stop using Vertex AI.** Use the Gemini API (AI Studio key) through the CrewAI/LiteLLM `gemini/<model>` route. Model is set by env var. Verify the exact model string and parameters against current docs before use.
2. **Two model tiers via env**: `LLM_FAST` (extraction, classification, planning, per-candidate verification) and `LLM_SMART` (ranker and SOP only). For `LLM_FAST`, **disable or minimize the model's "thinking"/reasoning budget** if the model supports it (verify the parameter name in the installed LiteLLM/CrewAI version). Extraction does not need reasoning, and this is a large latency win.
3. **One `LLMGate` in `app/llm_gate.py`** that every LLM call goes through:
   - `asyncio.Semaphore(LLM_CONCURRENCY)` (default 6)
   - A token bucket for `LLM_RPM` (read from env; check the current limits for the chosen model/key in AI Studio)
   - On 429/503/timeout: exponential backoff with jitter (honor `Retry-After` if present), up to 4 attempts
   - If still failing: **fail over to the secondary model/provider** set by `LLM_FALLBACK_MODEL` (any second provider the user has a key for), emitting a `fallback` event
   - **Never drop a candidate because of a rate limit.** A work item stays in the queue until it succeeds, fails over, or the run's time budget ends (then mark it `unreachable` with reason `llm_unavailable`).
   - Emits `llm_call` events: `{start, end, duration_ms, model, attempt, tokens_in, tokens_out, ok}`
4. Add `LLM_RPM`, `LLM_CONCURRENCY`, `LLM_FALLBACK_MODEL` to `.env.example`.

### 3.2 Replace tool-loop agents with "plan, execute in parallel, one judgment call"

**Principle: agentic where judgment is needed, deterministic where it is plumbing.** The five agents stay as CrewAI `Agent` + `Task` + `output_pydantic`, but their tools are executed by code in parallel instead of the LLM deciding each step in a slow loop. Reference pattern: planner generates questions, executors run in parallel, then results are aggregated (the pattern used by GPT Researcher and by Anthropic's multi-agent research system).

| Agent | v1 (slow) | v2 (target LLM calls) |
|---|---|---|
| Profile Analyst | agent loop with parse + GitHub tools | **Parse documents and fetch GitHub in parallel in code** (`asyncio.gather`), then **1 LLM call** to build `StudentProfile` (about 1-2 calls) |
| Researcher | loop: think, search, think, search | **Call 1:** plan 8-10 diverse queries (facets: country x kind x field x funding). **Code:** run all searches in parallel. **Call 2:** classify and dedupe results into `Candidate` objects (about 2 calls) |
| Verifier | loop per candidate: fetch, think, maybe search | Per candidate: **code** fetches the page (Section 3.4), **1 LLM call** extracts fields and criteria checks, **code** runs `verify_evidence()`. Optional single follow-up hop if the page is an aggregator (about 1 call per candidate; cap 30 candidates) |
| Ranker | 1 call | 1 call (`LLM_SMART`) |
| SOP Writer | 1 call | 1 call (`LLM_SMART`) |

Use CrewAI's native async: `Crew.akickoff()` (true async) or `kickoff_for_each_async()`. **Verify these in the installed version first.** Run Verifier items concurrently through the `LLMGate`. In the UI the Verifier appears as "Verifier x N workers" (a visible swarm).

### 3.3 Streaming pipeline (agents work simultaneously)

Replace strict phases with a producer/consumer pipeline in `flow.py`:

```
Profile (parallel: resume | marksheet | GitHub) -> StudentProfile
        |
Query planner (1 call) -> N queries
        |   asyncio.gather (parallel searches)
Researcher classify (1 call) -> candidates --stream--> asyncio.Queue
                                                          |
                                   Verifier worker pool (VERIFY_WORKERS) consumes the queue
                                   each result is emitted to the UI the moment it is verified
                                                          |
Router (anytime): stop when ANY is true:
   verified >= TARGET_VERIFIED (10)  |  TIME_BUDGET_S reached  |  user clicked "Finish now"
   if not met and candidates exhausted and rounds < MAX_ROUNDS: Researcher round+1 with feedback
                                                          |
Ranker (1 call) -> top 5 --handoff--> SOP Writer (1 call)
```

- Verification starts as soon as the first candidates exist. It does not wait for all research.
- **Candidate ordering:** verify official-domain candidates first (pre-score by TLD/domain: `.edu`, `.ac.*`, `.gov`, `.de`, known funders like DAAD, Chevening, Fulbright style domains from config).
- **Aggregator policy (default `drop` for speed and trust):** exclude aggregator/blog domains via Tavily `exclude_domains` and a denylist in `config.py`. Optional `AGGREGATOR_POLICY=resolve` allows one hop to find the official page.
- **Fix the round-2 bug:** the Researcher must receive `tried_urls`, `failed_reasons`, and `feedback` (for example "need more in country X; 4 closed deadlines") and must generate queries on **new facets**. Candidates that failed only because of rate limits or timeouts are **re-queued**, never marked as tried.
- Stop launching new verifications once the target is met; let in-flight ones finish (max 15 s grace).

### 3.4 Page fetching rules

- Prefer **Tavily Extract** (batch up to 20 URLs per call, `AsyncTavilyClient`) for clean text; fall back to `httpx` + `trafilatura`, then `pypdf` for PDFs. Verify parameters (`urls`, `extract_depth`, `query`, `chunks_per_source`) against current Tavily docs.
- **Timeouts:** connect 5 s, read 10 s, **total per URL 12 s including retries**.
- **Retry policy by status:** retry only on timeouts, connection errors, 408, 429, 5xx (max 2). **Never retry 404, 410, 401, 451.** On 403 try the Tavily Extract fallback once. TLS handshake timeout: one retry at most.
- **Prompt size:** keep page text under `PAGE_TEXT_CHARS` (default 12000) by selecting passages around keywords (deadline, funding, stipend, eligibility, apply, requirements). The evidence check must run against **exactly the text given to the LLM**.
- Cache fetched text on disk (Section 3.6).

### 3.5 GitHub completeness fix

In `tools/github.py`:
- Paginate `GET /users/{u}/repos?per_page=100&type=owner&sort=pushed` until exhausted. `public_repo_count` = the true count.
- Aggregate languages from the `language` field across **all** non-fork repos (zero extra API calls), weighted by stars and recency.
- Notable repos: top 8 by a signal score (stars, recency, has description/README). Fetch READMEs and per-repo `/languages` for those 8 **in parallel**.
- Forks are counted separately and ranked below originals.
- Surface in the profile: "Analyzed 8 of 23 repos (top by signal); 23 public repos total; languages: ...". Optional `GITHUB_TOKEN` for higher rate limits; optional GraphQL pinned repos when a token exists.
- Test: mocked GitHub responses with 25 repos must yield `public_repo_count == 25` and at least 3 aggregated languages.

### 3.6 Cache

`app/cache.py`: disk cache (JSON) for search results and page text, key = hash of normalized query/URL, TTL 24 h, disabled with `CACHE=0`. Emit a `cache_hit` info event. This makes rehearsals and the demo recording fast and cheap. Never cache LLM judgments across different profiles.

### 3.7 Observability

Every phase, LLM call, search, and fetch emits an event with `duration_ms`. `scripts/perf_report.py` reads a saved run JSON and prints: per-phase wall time, LLM call count, 429 count, retries, fallbacks, cache hits, slowest 5 steps.

---

## 4. P1: Controls, Trust and Visible Resilience

### 4.1 Stop, Finish-now, ETA
- `run_id` is the first event emitted. The UI keeps it.
- **Stop:** `AbortController.abort()` on the stream; the server detects disconnect (`request.is_disconnected()`), cancels all tasks, and **keeps everything verified so far** in the final partial result (UI shows "Stopped, showing N verified results").
- **Finish now:** `POST /api/run/{run_id}/finish` sets the run's `finish_event`; the Router stops verification and proceeds to Ranker and SOP with what is verified. Needs a small in-memory run registry (single Cloud Run instance, `--max-instances 1`).
- **ETA:** phase weights for the progress bar `[profile 10%, plan+search 12%, verify 50%, rank 10%, sop 18%]`. Within verification, `remaining = (queue_len + in_flight) / workers * rolling_avg_verify_s` (EMA). Show ETA only after 10% progress, as "about 1m 20s left", and always show elapsed time. Emit `progress` events: `{phase, done, total, pct, eta_s}`.

### 4.2 Evidence chips (trust differentiator)
Every deadline, funding figure, and requirement in the UI shows a small chip. Hover or tap opens a popover with the **verbatim quote** from the official page, the source URL, and the fetch time. Unverified fields render as "unverified" in muted style. No quote means no claim. This directly serves the 20-mark trust criterion.

### 4.3 Progressive results
Verified opportunities appear in the results area **the moment they are verified**, as cards (with skeleton shimmer placeholders for pending slots). When the Ranker finishes, the top 5 animate into a highlighted "Top 5" section and the rest move to the "All checked" table. Show a **provisional** badge on cards until ranking completes.

### 4.4 Failure-injection demo mode ("Chaos mode")
Env `CHAOS_RATE` (default 0) and a UI toggle "Simulate failures" that sends `chaos=true`. When on, a wrapper randomly (about 25%) raises transient failures (timeout, 429, 503) in search, fetch, and LLM calls and emits a `chaos_injected` event. The recovery code from Section 3 handles them, and the UI shows the retries/fallbacks live. Purpose: let judges **see** failure recovery (15 marks). Off by default; clearly labeled in the UI. Test: with chaos on, a full run still completes with the same number of usable results (within +/-2).

---

## 5. P2: Differentiators (only after P0 and P1 are verified)

### 5.1 Gap-to-action plan
Deterministic code aggregates, across the top-5 verified opportunities, the `CriterionCheck`s with `unknown` or `not_met` and the profile `gaps`. Example output: "English test missing: affects 4 of 5 recommendations." The Ranker adds, per opportunity, `readiness` (`score`, `blockers`) and `actions` (`action`, `why`, `by_when` from evidence only). The UI shows a "What's blocking you" board. The LLM only phrases the actions; the counts come from code.

### 5.2 Replay mode
Every run is saved as `runs/<id>.json` with all events. `GET /api/replay/<id>` streams the saved events with original relative timing (x1, x2, x4 speed). The UI labels it clearly "Replay of a recorded run". Use it for the 5-minute screen recording and as a safety net if an API is down during judging. Never present a replay as live.

### 5.3 MCP tool server (latest-tech signal)
Expose the three tools (`web_search`, `fetch_page`, `github_profile`) as an **MCP server** in `mcp_server/server.py` (Python MCP SDK / FastMCP). CrewAI consumes them via `crewai_tools.MCPServerAdapter` (install `crewai-tools[mcp]`; transports: stdio, SSE, streamable-http; verify in the installed version). Switch with `TOOLS_VIA_MCP=true`; the default stays in-process for speed. Events show `via: mcp`. Bonus: the same server can be added to any MCP-capable client for a live demo. **If this threatens the deadline, skip it; document it as future work.**

---

## 6. UI v2 Specification

Use the `frontend-design` skill: pick a distinctive, intentional aesthetic (for example a dark "mission control" look with a strong type pairing), not generic template styling. Use `web-design-guidelines` to review accessibility and detail issues at the end. Files: `static/index.html`, `static/app.js`, `static/styles.css` (no build step; this overrides the single-file rule in `task.md`).

### 6.1 Layout
1. **Top bar:** app name, run state, **elapsed timer**, **ETA**, phase progress bar with labels ("Reading GitHub", "Searching 10 queries", "Verifying 14/24", "Ranking", "Drafting SOP"), **Stop** and **Finish now** buttons, "Simulate failures" toggle.
2. **Left: Agent swarm graph** (SVG): 5 nodes with role icons. States: idle / working (pulsing ring) / done (check) / retrying (amber). Edges animate a traveling pulse on each `handoff` event. The Verifier node shows N worker dots lighting up while active. Live counters: LLM calls, searches, pages read, retries, fallbacks, cache hits.
3. **Center: Agent conversation feed** (ChatGPT-style structured stream): see 6.2.
4. **Right or below: Live results:** progressive cards, then Top 5, then all checked, then SOP draft (with DRAFT banner, copy and download), then the "What's blocking you" board and the run summary.

On narrow screens stack the zones vertically; the app must be usable on a phone.

### 6.2 Structured agent communication feed
- Group events into **collapsible blocks per agent**. Each block header: agent icon, name, status, and a "Worked for 14s" duration (like ChatGPT's "Thought for 12s").
- **Handoffs render as message bubbles:** "Researcher to Verifier: 24 candidates" with an expandable, typed payload summary (counts and names, not raw JSON dumps).
- **Tool calls render as chips:** search chip (query text), page chip (domain + status), LLM chip (model + duration), with colors: normal, amber for `retry`, purple for `fallback`, red for `error`, and a distinct style for `chaos_injected`.
- New items slide in; important messages reveal with a short typing effect; the feed auto-scrolls unless the user scrolls up.
- A filter to show only handoffs / only failures and recoveries.

### 6.3 Loading and motion
- Skeleton shimmer for result slots, animated progress bar with moving highlight, count-up numbers, pulsing node rings, edge pulse on handoff.
- Respect `prefers-reduced-motion`.
- Never leave a blank screen: if the stream stalls for more than 15 s, show "Still working: waiting on <agent/tool>" using the last event.

### 6.4 End-of-run summary
Show: total time, LLM calls, searches, pages read, retries, fallbacks, cache hits, and a **phase timeline bar** (horizontal segments per phase built from event timestamps). This is the "agents in action" proof for the video.

### 6.5 Event schema v2 (backend and frontend contract)
```json
{
  "seq": 42, "ts": "ISO-8601", "run_id": "abc",
  "agent": "Verifier", "worker": 3,
  "type": "start|handoff|tool_call|tool_result|llm_call|retry|fallback|cache_hit|chaos_injected|progress|info|warning|error|partial_result|done",
  "phase": "verify",
  "message": "human readable",
  "duration_ms": 1830,
  "progress": {"done": 14, "total": 24, "pct": 0.46, "eta_s": 80},
  "data": {}
}
```
`partial_result` carries one `VerifiedOpportunity`; the final `result` event carries `RunResult`. Keep field names stable; update `models.py` and the frontend together.

---

## 7. Prompt Quality Rules (applies to all agents)

Prompts live in `tasks.py`, are filled from the profile and run state, and contain **no student-specific text**. Keep each prompt short and structured. Required elements:

**Query planner:** "Given this profile (JSON), produce N search queries. Cover different facets: each target country, funding type (scholarship, funded program, government scheme), and the student's field and strengths. No two queries may differ only by word order. Prefer official-site phrasing. Return JSON only."

**Candidate classifier:** "From these search results, return only real, specific opportunities (not listicles or blog posts). Each needs name, institution, country, kind, and the source_url copied exactly from a result. Do not add any URL that is not in the results."

**Verifier (per candidate):** "Today is {today}. Below is the text of one page. Extract deadline, funding, how to apply, and eligibility criteria. **Every value must be accompanied by a quote copied exactly from the text.** If the text does not state it, return null. Compare each criterion to the profile as met / not_met / unknown. If the page is a listing or aggregator, say so in `source_tier`. Never use outside knowledge."

**Ranker:** "Score using this rubric and weights. `why_fit` must cite at least two concrete profile facts. Rank open deadlines above closed ones; label closed ones as 'check next cycle'. If fewer than 5 qualify, return fewer."

**SOP Writer:** "Use only facts from the profile. List each fact used. Insert [PLACEHOLDER: ...] where information is missing. No invented achievements. Start with the DRAFT banner."

Add **few-shot examples** (one good, one bad) of the Verifier output in `tests/fixtures/` and in the prompt only if they measurably improve extraction; otherwise omit to keep prompts small.

---

## 8. Tests and Measurement Additions

- `test_llm_gate.py`: 429 triggers backoff and then fallback; **no item is dropped**; concurrency and RPM caps are respected (use a fake clock/model).
- `test_fetch.py` additions: 404 is not retried; total per-URL time cap holds; TLS timeout retried at most once.
- `test_github.py`: 25 mocked repos yields true count, aggregated languages, 8 notable repos.
- `test_pipeline.py`: with stubbed LLM and tools, verification starts before research finishes; `Finish now` produces a ranking from partial results; `Stop` returns partial results.
- `test_chaos.py`: chaos on, run completes, recovery events present.
- `scripts/perf_report.py`: described in 3.7.
- `scripts/smoke_run.py`: runs profile A then profile B live, prints the perf report for each, and checks the Section 2 targets.

---

## 9. Work Order

**P0 (do first, verify each before moving on):**
1. `LLMGate`, provider switch, model tiers, `llm_call` events (3.1, 3.7)
2. Fetch rules + timeouts + retry-by-status (3.4)
3. GitHub fix (3.5)
4. Agents converted to plan, parallel execute, one judgment call (3.2)
5. Streaming pipeline, router, round-2 fix (3.3)
6. Cache (3.6)
Runtime check after P0: `scripts/smoke_run.py` on profile A shows the Section 2 targets or an honest explanation of the gap.

**P1:**
7. Event schema v2 + backend controls (Stop, Finish now, ETA) (4.1, 6.5)
8. UI v2 (Section 6), progressive results, evidence chips (4.2, 4.3)
9. Chaos mode (4.4)
Runtime check: run in a real browser (use the browser tool), screenshot the swarm graph, feed, progressive cards, an evidence popover, and a chaos run showing retries.

**P2 (only if P0 and P1 are done and verified):** 5.1 gap-to-action, 5.2 replay, 5.3 MCP.

**P3 (final):** README with Mermaid diagram updated to this architecture, `docs/architecture.md`, deploy, draft the hackathon note from `docs/dev_log.md` (the most interesting experiment is likely the 100-call to 40-call refactor, with the measured before/after).

---

## 10. Additions to the Definition of Done

- [ ] Section 2 targets met on profile A and B, with `perf_report` output pasted in `docs/dev_log.md`
- [ ] No candidate is ever dropped because of a rate limit
- [ ] Verification visibly overlaps with research in the event log (timestamps prove it)
- [ ] Stop, Finish now, and ETA work in the browser
- [ ] Every displayed deadline/funding/requirement has an evidence chip or an "unverified" label
- [ ] Chaos mode demonstrates recovery without losing results
- [ ] GitHub repo count and languages are correct for an account with 20+ repos
- [ ] `ruff`, `mypy`, `vulture`, `pytest` clean; no dead code from the old sequential flow remains
