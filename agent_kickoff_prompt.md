# ScholarSwarm: Agent Kickoff Prompt (paste this into Antigravity)

## 0. Role and reading order
You are the lead engineer for ScholarSwarm (CrewAI multi-agent scholarship finder, individual hackathon, deadline Oct 23 2026 11:59 PM IST).

Read in this order before writing any code:
1. `task.md` (v1 PRD)
2. `task_v2.md` (overrides v1 where they conflict)
3. This file (overrides both where they conflict)

Then write your plan to `docs/dev_log.md` and start Milestone 1. Do not ask me questions you can answer from these files.

## 1. Non-negotiables
- **No invented facts.** Every eligibility, deadline and amount claim needs a verbatim `evidence_quote`, checked in code to exist inside THAT candidate's own fetched text. A claim without a passing quote is shown as `unknown`, never as fact.
- **No hardcoding to any student.** The judges will swap in an unseen profile live. Zero "Rahul" strings, zero fixed scholarship lists, zero fixed countries or degrees in logic or prompts. Test with at least 3 different synthetic profiles.
- **No copied code.** Use only libraries already in our stack (CrewAI, LiteLLM, Pydantic v2, FastAPI, httpx, trafilatura, pypdf, Tavily, DuckDuckGo fallback). Do not add `curl_cffi` or other packages unless a real failure proves we need them, and log why.
- **Verify APIs, don't recall them.** Use the Context7 MCP and the installed package source/`help()` before using any CrewAI, LiteLLM, Tavily or MCP call. Record the signature you verified in `docs/dev_log.md`.
- **Root-cause fixes only.** No bare try/except to hide errors. Every failure must emit a visible event.
- Secrets only via env vars. Current date is Oct 22 2026. Deadlines are classified, not blindly dropped (see 3.4).

## 2. Mistakes from the real failed run that you must fix
1. ~60s per LLM turn, 100+ calls per run. Cause: agent tool-loops per candidate. Fix: "plan once, run tools in parallel in code, one LLM judgment call".
2. 15 candidates dropped on 429 from Vertex AI (fresh project, tiny dynamic quota). Fix: use the **Gemini API** (`GEMINI_API_KEY`), and the LLMGate below. Rate-limit drops are forbidden: work items are retried, never discarded.
3. Silent multi-minute gaps. Fix: every LLM call and tool call emits an event with `duration_ms`.
4. Retries on 404/410 pages. Fix: retry only on timeout, 408, 429, 5xx.
5. Round 2 returned 0 new candidates. Fix: pass `tried_urls` and `failed_reasons` into the planner, require new angles.
6. Aggregator blog used as a source. Fix: prefer official domains, label aggregators as "lead only" and follow through to the official page.
7. GitHub showed 6 repos and 1 language for a 20+ repo account. Fix: paginate all repos, aggregate languages across all, pick top 8 "notable" by a signal score.

## 3. Architecture (build exactly this)

### 3.1 LLMGate (P0, build first)
One module every LLM call goes through: semaphore (max concurrency from env), token bucket, exponential backoff with jitter on 429/5xx, provider failover, `litellm.drop_params = True` so failover does not crash on unsupported params. Never drops a work item. Emits `llm_call` events (model, duration, tokens). Two tiers: `LLM_FAST` (extraction, minimal reasoning budget) and `LLM_SMART` (ranking, SOP).

### 3.2 Agents (4+ distinct roles, keep them distinct)
1. **Profile Analyst**: resume, marksheet, GitHub to `StudentProfile`. Includes `citizenship` and `residency_status`. If unknown, store `null` and add it to `profile_gaps`. Never infer citizenship from target countries and never default it. Eligibility checks that depend on it become `unknown` and the UI asks the user.
2. **Opportunity Researcher**: LLM plans queries once, code runs searches in parallel. Queries describe degree level, domain, funding type, demographic and country. They must NEVER contain tool or tech names (Jupyter, HTML, TypeScript, etc.).
3. **Eligibility Verifier**: micro-batch design (3.3).
4. **Ranker/Advisor**: separate step and separate agent from the Verifier. Ranks only verified/eligible-or-unknown candidates, explains fit, lists gaps.
5. **SOP Writer**: uses the real GitHub projects, skills and academics (section 3.5).

### 3.3 Verification: micro-batches, not one giant call
- 3 to 4 candidates per LLM call, about 5 to 6k characters of page text each, each tagged with an ID.
- Output is structured JSON keyed by candidate ID. For each criterion return `status` (`met` / `not_met` / `unknown`) and `evidence_quote`.
- Code checks each quote against **only that candidate's own text**. If it is not found there, the criterion is downgraded to `unknown`. This makes cross-contamination fail automatically.
- Matching must survive formatting noise. Normalize BOTH the quote and the page text the same way: Unicode NFKC, curly quotes and dashes to ASCII, strip markdown syntax (`*`, `_`, `#`, `>`, `|`, link brackets), collapse all whitespace, casefold. Step 1: exact substring on normalized text. Step 2, only if step 1 fails: fuzzy window match with stdlib `difflib` at ratio 0.92 or higher, quote at least 25 characters. Record which method matched in the event. Quotes must still come from that candidate's own text only.
- Parse failures retry only that micro-batch, never the whole run.
- Stream it, but let the framework own execution. The CrewAI Flow is the single orchestrator. Do not wrap CrewAI inside your own thread or queue layer. Run verification workers as async tasks inside the Flow (`VERIFY_WORKERS`), each calling a one-task crew via native `akickoff()` (verify the exact signature with Context7 and the installed source), official-domain candidates first. If an `asyncio.Queue` is used, it only hands candidates between Flow steps. Never call blocking `kickoff()` inside an event loop and never mix thread-based `kickoff_async()` with your own pool. If you find a real conflict, document it in `docs/dev_log.md` and pick the simplest option that keeps agent roles visible. First verified result must be visible within 90s.

### 3.4 Eligibility logic
- Reject a candidate only on `not_met` backed by a passing evidence quote (example: page says "first-year PhD only", profile is Masters).
- `unknown` is NOT rejected. Keep it, flag it visibly, and let the Ranker penalise it.
- Hard rules like degree level are enforced in code, not left to the LLM.
- Deadlines are classified, not just parsed. Extract `deadline_type`: `fixed`, `rolling`, `cycle` (for example "applications open each autumn"), `anticipated`, or `unknown`, plus the quote. Drop a candidate for deadline only when it is `fixed`, the parsed date is clearly before today (Oct 22 2026), and the page gives no sign of a next cycle. Everything else is kept and shown with a visible badge such as "rolling" or "deadline unverified". If the date string cannot be parsed, treat it as `unknown`, never as past.

### 3.5 SOP rules
- Weave in all real facts available (projects, skills, academics, achievements from the profile).
- Never invent achievements, numbers or motivations. Where a needed fact is genuinely missing, keep an explicit `[ADD: ...]` placeholder and list those in the response. Do not remove placeholders to look polished.

### 3.6 Page fetching tiers (in order)
1. Tavily Extract in small batches of about 5 URLs (the API allows more, but one hung domain stalls the whole call). Each batch runs concurrently under its own `asyncio.wait_for` timeout. URLs missing from a timed-out or partial response drop to tier 2 individually, in parallel. Never block on the slowest URL.
2. `httpx` + `trafilatura`, strict timeouts.
3. Jina Reader (`https://r.jina.ai/<url>`, header `X-Return-Format: markdown`) for JS-heavy pages only.
4. Search snippet: allowed only as a "lead", labeled **unverified**, never counted toward the 10 verified, never used as evidence.

Cap page text at about 12k chars, chosen around deadline/eligibility/amount keywords. Cache fetches on disk.

### 3.7 Documents
`pypdf` first. If extracted text is under 50 characters, fall back to Gemini vision OCR. Marksheets are often scanned. Keep memory bounded: render ONE page at a time at about 100 to 120 DPI, cap at 5 pages, encode as JPEG, send, then free the buffer before the next page. Only one OCR job at a time (semaphore of 1). Log peak memory in the run summary.

### 3.8 Loop and recovery
Targets: `TARGET_VERIFIED=10`, `MAX_ROUNDS=3`, 15 or more candidates per round. If under target after a round, run a fresh planning round using `tried_urls` and `failed_reasons`. Support `CHAOS_RATE` (random injected transient failures) so recovery is visible in the demo.

## 4. UI (use the frontend-design skill)
Mission-control look. Agent swarm graph, collapsible agent conversation feed with tool-call chips (normal / retry / fallback / error / chaos), evidence chips (hover shows verbatim quote, source URL, fetch time), progressive result streaming, Stop / Finish-now / ETA controls, end-of-run phase timeline. Event schema as in `task_v2.md` section 6.

## 5. Work protocol
1. Milestones in order: (1) LLMGate + tools with tests, (2) agents + verifier micro-batching, (3) Flow + streaming + loop, (4) API + UI, (5) Dockerfile and Cloud Run deploy, (6) polish and demo safety.
2. After each milestone, run `ruff`, `mypy`, `pytest`. Do not claim done if any fail. `vulture` is advisory only: run it with `--min-confidence 80` at milestones 5 and 6, and keep a whitelist file for FastAPI routes, Pydantic validators and event callbacks. Never delete code just to silence it without checking it is truly unused.
3. After each milestone, do a self-review against section 1, then simplify: delete dead code, no speculative abstractions.
4. Each milestone ends with a real run on a synthetic profile. Paste the event log summary (time, LLM calls, verified count, 429s) into `docs/dev_log.md`.
5. If blocked for more than 2 attempts on the same issue, write the root cause and options in `docs/dev_log.md` and pick the simplest safe one.

## 6. Targets (measure and report)
| Metric | Target |
|---|---|
| End-to-end time | under 4 min typical, 7 min hard cap |
| LLM calls per run | 45 or fewer |
| First verified result visible | under 90s |
| Candidates dropped on 429 | 0 |
| GitHub coverage | all repos and languages |
| Verified opportunities | 10 or more, top 5 ranked |
| Claims without a passing evidence quote | 0 |
| Peak memory (including an OCR run) | under 1.5 GiB |

## 7. Required tests
- Quote-must-appear-in-own-text (including a planted cross-contamination case).
- Quote matching passes despite smart quotes, extra whitespace and markdown markup, and still fails on a quote taken from a different candidate's text.
- Rolling, cycle and anticipated deadlines are kept with a badge; a clearly past fixed deadline is dropped; an unparseable date becomes `unknown`.
- A hung URL in a Tavily batch does not delay the other URLs beyond the batch timeout.
- `unknown` is kept, `not_met` with a quote is rejected.
- Citizenship `null` produces a gap, not a default.
- 429 injection: all work items complete, none dropped.
- Three different synthetic profiles produce different, profile-relevant queries and results.
- GitHub account with more than 20 repos aggregates all of them.
- Scanned-PDF OCR fallback triggers under 50 characters.

## 8. Definition of Done
All section 6 targets met on 3 profiles, all section 7 tests passing, quality gate clean, deployed on Cloud Run (`--timeout 600 --max-instances 1 --memory 2Gi --concurrency 4`; 2 GiB leaves headroom for OCR plus parallel fetches, and low concurrency stops several runs from stacking memory on one instance), live URL tested with a fresh profile, `README` explains agents, tools, failure recovery and sources.
