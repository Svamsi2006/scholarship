# TASK: Build "scholarshipstar", a CrewAI Multi-Agent Scholarship Finder

> You are the coding agent. Read this entire file before writing any code. Work milestone by milestone (Section 14). Do not claim anything is done without showing command output that proves it (Section 3).

---

## 1. Context and Goal

This is for the **TetraNoodle AI Hackathon 2026** (individual, LPU students). **Deadline: Oct 23, 2026, 11:59 PM IST.** Today is Oct 20, so there are about 3 working days.

**The brief:** a fictional student, Rahul (final-year B.Tech CSE, 8.2 CGPA, AI projects, GitHub profile, wants to study abroad but cannot afford fees), has a resume, a marksheet, and a GitHub profile. Build an AI agent swarm that:

1. Understands the student from resume, marksheet, GitHub, and other supplied links.
2. Searches the real internet and finds **at least 10** real university programs or scholarships.
3. Checks eligibility by visiting official pages, comparing requirements with the profile, and flagging missing information.
4. Recommends the **top 5** with why they fit, funding, deadlines, and how to apply.
5. Drafts a statement of purpose (SOP) or application draft for **one** opportunity.
6. Provides a simple website: upload documents, enter profile, click a button, watch the agents work.

**Hard requirements from the brief:** at least 4 agent roles that exchange information, use real APIs or web tools, and **recover when something goes wrong**. Not a chatbot. Real public opportunities with **visible sources**. Never invent scholarships or student achievements. Drafts only; never submit applications.

**The hidden test ("Final Surprise"):** shortlisted students get a **different, unseen student profile** during a live demo. The system must adapt **without code changes**. Nothing may be hardcoded to Rahul.

### Scoring (design decisions must serve this)

| Criterion | Marks | What it means for the build |
|---|---|---|
| Agents working together autonomously | 30 | Distinct agents, structured hand-offs, a feedback loop between agents, visible in the UI |
| Real internet research and profile enrichment | 25 | Real search and page fetching, GitHub API enrichment |
| Correct results with trustworthy sources | 20 | Every claim has a source URL and a verbatim evidence quote that is programmatically checked |
| Working website and demo | 10 | Simple, reliable, live agent log |
| Creativity, problem-solving, failure handling | 15 | Explicit retry/fallback paths, all visible in the event log |

---

## 2. Non-Negotiable Principles

1. **No hallucinated facts.** Any deadline, amount, or requirement shown to the user must carry an `evidence_quote` that exists verbatim (whitespace-normalized) in the fetched page text. This is checked in code, not by the LLM. If the check fails, the field becomes `null` and is flagged "unverified".
2. **No hardcoding to any student.** No names, countries, universities, or scholarship lists in product code. Everything derives from the `StudentProfile`. Test fixtures live only in `tests/fixtures/`.
3. **No fake data in product code.** No mocked search results or placeholder scholarships outside `tests/`.
4. **Fallbacks only where this PRD specifies them** (Section 9), and every fallback emits a visible event. Never write `except Exception: pass` or silently return empty results.
5. **Simple, minimal code.** No unused functions, imports, parameters, or config. No speculative abstractions. No class where a function suffices. Delete dead code as you go.
6. **Verify library APIs against the installed package, not memory** (Section 3, rule 2).
7. **Today's date is injected from the system clock** into prompts and logic. Closed deadlines must be handled (see 8.4).

---

## 3. Agent Operating Rules (How You Must Work)

1. **Plan first.** Before each milestone, write a 5-10 line plan to `docs/dev_log.md`. After it, append what worked, what broke, and how you fixed it. This log becomes the hackathon note on "most interesting experiment and biggest technical challenge", so be honest and specific.
2. **Check real APIs before using them.** CrewAI, Tavily, trafilatura, and others change between versions. Before using any library call: run `pip show <pkg>`, then inspect the real signature (`python -c "import inspect, X; print(inspect.signature(X.f))"` or read the installed source). If docs are available via an MCP/docs tool, use it. Never write a call from memory and assume it works.
3. **Run everything you write.** After every file or feature: run it. A feature is not done until you have executed it and seen the expected output.
4. **Quality gate before declaring any milestone done**, run all of these and paste the output into `docs/dev_log.md`:
   - `ruff check .` and `ruff format --check .`
   - `mypy app/` (strict enough to catch Optional/None errors)
   - `vulture app/` (dead code; remove everything it flags unless it is a framework entry point)
   - `pytest -q`
   - The milestone's runtime check from Section 14 (actually start the server or script and exercise it)
5. **Self-review pass.** Before finishing a milestone, re-read your own diff and answer: Is any code unused? Is any fallback silent? Is anything hardcoded to a student? Does any claim lack a source? Fix, then re-run the gate.
6. **When something fails**, read the actual error and traceback, form a hypothesis, test it, and fix the root cause. Do not paper over failures with try/except or retries unless the retry is in Section 9.
7. **Keep dependencies minimal.** Pin versions in `requirements.txt` after confirming the install works.
8. **Secrets** only via environment variables and `.env` (git-ignored). Provide `.env.example`. Never commit keys.

---

## 4. Tech Stack

| Layer | Choice | Notes |
|---|---|---|
| Language | Python 3.11 | |
| Orchestration | **CrewAI** (Flows + Crews/Agents/Tasks) | Primary framework. Use `Flow` with `@start`, `@listen`, `@router` for the feedback loop. Verify the exact import paths for the installed version. |
| LLM | Configurable via env `LLM_MODEL` | Use a current fast Gemini Flash model through CrewAI's `LLM` class (LiteLLM-style name like `gemini/<model>`) because of the free tier. Verify the model name against current docs. Must be swappable by env var only. |
| Search | **Tavily** primary; **DuckDuckGo (`ddgs`)** fallback | Fallback needs no key |
| Page fetch | `httpx` + `trafilatura` (HTML to text); `pypdf` for PDF pages | Tavily Extract as a second fallback if available |
| Documents | `pypdf` for resume/marksheet PDFs; also accept `.txt` and pasted text | |
| GitHub | GitHub REST API via `httpx`; optional `GITHUB_TOKEN` | Unauthenticated is limited to 60 requests/hour, so keep calls few |
| Models/validation | **Pydantic v2** | Every agent output is a Pydantic model (`output_pydantic`) |
| Backend | **FastAPI** + `uvicorn` | One streaming endpoint |
| Frontend | Single `static/index.html` with vanilla JS and CSS | No build step |
| Tests | `pytest`, `pytest-asyncio` if needed, `respx` or `unittest.mock` for HTTP | |
| Lint/type/dead code | `ruff`, `mypy`, `vulture` | Section 3 |
| Deploy | Docker to **Google Cloud Run** (region `asia-south1`) | Section 12 |

---

## 5. Repository Layout

```
scholarshipstar/
├── task.md                      # this file
├── README.md                    # setup, run, architecture diagram (Mermaid), sources policy
├── requirements.txt
├── .env.example
├── Dockerfile
├── app/
│   ├── main.py                  # FastAPI app, streaming endpoint, static mount
│   ├── config.py                # env settings (LLM_MODEL, keys, limits)
│   ├── models.py                # all Pydantic models (Section 6)
│   ├── events.py                # EventBus: emit() + async iterator for streaming
│   ├── flow.py                  # CrewAI Flow: the orchestration + feedback loop
│   ├── agents.py                # the 5 agent definitions
│   ├── tasks.py                 # task prompts/templates (profile-driven, no hardcoding)
│   ├── tools/
│   │   ├── search.py            # web_search tool (Tavily -> ddgs fallback)
│   │   ├── fetch.py             # fetch_page tool (httpx -> trafilatura/pypdf, fallbacks)
│   │   ├── github.py            # github_profile tool
│   │   ├── documents.py         # parse_document (pdf/txt) 
│   │   └── evidence.py          # verify_evidence() programmatic quote checker
│   └── util/retry.py            # backoff helper that emits retry events
├── static/index.html
├── tests/
│   ├── fixtures/                # profile_a.json, profile_b.json, sample pages
│   ├── test_evidence.py
│   ├── test_fetch.py
│   ├── test_search_fallback.py
│   ├── test_flow_router.py
│   └── test_adaptability.py
├── scripts/smoke_run.py         # runs the whole flow headless on a fixture profile
└── docs/
    ├── dev_log.md
    └── architecture.md          # diagram + explanation
```

---

## 6. Data Models (`app/models.py`)

Define with Pydantic v2. Field names are a contract between agents; keep them exactly.

```python
class Education(BaseModel):
    degree: str; field: str | None; institution: str
    cgpa: float | None; cgpa_scale: float | None; year: int | None

class Project(BaseModel):
    name: str; description: str; tech: list[str]; url: str | None

class TestScore(BaseModel):
    name: str            # e.g. IELTS, GRE, TOEFL
    score: str | None    # None means not taken / not provided

class GithubSummary(BaseModel):
    username: str; profile_url: str
    top_languages: list[str]
    notable_repos: list[Project]
    public_repo_count: int

class StudentProfile(BaseModel):
    name: str
    education: list[Education]
    skills: list[str]
    projects: list[Project]
    achievements: list[str]            # only what is in the documents/links
    test_scores: list[TestScore]
    github: GithubSummary | None
    target_level: str                  # e.g. Masters, PhD (from user input, else inferred and marked)
    target_fields: list[str]
    target_countries: list[str]
    funding_need: Literal["full", "partial", "none"]
    gaps: list[str]                    # missing info that would affect eligibility (e.g. no English test)
    field_sources: dict[str, str]      # field name -> "resume" | "marksheet" | "github" | "form"

class Candidate(BaseModel):
    id: str; name: str; institution: str | None; country: str | None
    kind: Literal["scholarship", "program", "program_with_funding"]
    source_url: str
    found_by_query: str

class CriterionCheck(BaseModel):
    criterion: str
    student_value: str | None
    result: Literal["met", "not_met", "unknown"]
    evidence_quote: str | None

class Evidenced(BaseModel):
    value: str | None
    evidence_quote: str | None
    verified: bool = False             # set by verify_evidence(), never by the LLM

class VerifiedOpportunity(BaseModel):
    candidate: Candidate
    status: Literal["verified", "partial", "rejected", "unreachable"]
    official_url: str | None
    source_tier: Literal["official", "aggregator", "other"]
    deadline: Evidenced
    deadline_state: Literal["open", "closed", "rolling", "unknown"]
    funding: Evidenced
    requirements: list[CriterionCheck]
    how_to_apply: Evidenced
    missing_info: list[str]
    fetched_at: str                    # ISO timestamp

class RankedOpportunity(BaseModel):
    rank: int; score: float
    score_breakdown: dict[str, float]
    opportunity: VerifiedOpportunity
    why_fit: str                       # must reference concrete profile facts
    next_steps: list[str]
    risks: list[str]

class SOPDraft(BaseModel):
    target_name: str
    text: str
    facts_used: list[str]              # every profile fact referenced
    placeholders: list[str]            # things the student must fill in

class Event(BaseModel):
    ts: str
    agent: str
    type: Literal["start", "tool_call", "tool_result", "retry", "fallback",
                  "info", "warning", "handoff", "done", "error"]
    message: str
    data: dict | None = None

class RunResult(BaseModel):
    profile: StudentProfile
    ranked: list[RankedOpportunity]    # top 5
    all_checked: list[VerifiedOpportunity]
    sop: SOPDraft | None
    rounds_used: int
    events_count: int
```

---

## 7. The Tools (what each does and exactly how)

All tools are CrewAI tools (subclass `BaseTool` or use the `@tool` decorator, per the installed version). Each tool: validates input, **emits events** via `EventBus`, returns compact text/JSON the LLM can use, and raises clear errors.

### 7.1 `web_search(query: str, max_results: int = 8)`
- Calls Tavily search. Returns list of `{title, url, snippet}`.
- On Tavily failure (network error, 429, 5xx, missing key): retry per Section 9, then **fallback to `ddgs`** and emit a `fallback` event.
- Dedupe by normalized URL. Drop obviously irrelevant domains (social media, Quora-style Q&A) via a small domain denylist in `config.py`.
- Does not interpret results. It only searches.

### 7.2 `fetch_page(url: str)`
- `httpx.get` with a browser-like User-Agent, 15s timeout, redirects on.
- If `content-type` is PDF: extract text with `pypdf`. Otherwise extract main text with `trafilatura`; if that returns very little, fall back to a basic BeautifulSoup text pass.
- Truncate to a configurable character limit (e.g. 20k) **after** extraction, keeping the raw full text available in memory for evidence checking.
- On 403/429/timeouts: retry per Section 9; then try Tavily Extract if available; else return a structured `{"status": "unreachable", "reason": ...}`. The Verifier must treat unreachable as such and must not guess.
- Returns `{url, final_url, status, text, fetched_at}`. The full `text` is stored in a per-run `PageCache` keyed by URL so `verify_evidence()` can check against it later.

### 7.3 `github_profile(username_or_url: str)`
- Parses the username. Calls GitHub REST: user, then repos sorted by recent/stars (top ~6), languages per repo, and the first ~1500 characters of README for the top ~4 repos.
- Returns a `GithubSummary`-shaped JSON. Handles 404 (user not found) and rate limit (403 with reset header) by returning a clear error; the Profile Analyst then records a gap, not a crash.
- Optional `GITHUB_TOKEN` raises the rate limit.

### 7.4 `parse_document(path: str)`
- PDF via `pypdf`; `.txt` read as UTF-8.
- If extracted text is under about 200 characters (likely a scanned PDF), return an explicit error: "No extractable text; ask the user to paste text." Do not fake OCR.

### 7.5 `verify_evidence(page_text: str, quote: str) -> bool` (plain function, not an LLM tool)
- Normalizes whitespace and case, checks the quote is a substring of the page text. Also rejects quotes shorter than ~12 characters (too easy to match).
- Called by code **after** the Verifier agent returns its structured output, not by the agent. For every `Evidenced` field it sets `verified`. If False: set `value = None`, keep a note in `missing_info`.

---

## 8. The Five Agents

Each agent: distinct role, goal, backstory, its own tools, a Pydantic output, `max_iter` capped (e.g. 5-8), and `max_rpm` set to respect LLM free-tier limits. Prompts live in `tasks.py` as templates filled from the profile and run state, with no student-specific text.

### 8.1 Agent 1: Profile Analyst
- **Tools:** `parse_document`, `github_profile`
- **Input:** uploaded resume/marksheet text, GitHub URL, extra links, and the form fields (target level, countries, fields, funding need).
- **Job:** build a `StudentProfile` using only information present in the inputs. For each field, record its source in `field_sources`. Compute `gaps`: things that commonly decide eligibility but are missing (e.g. no English test score, unknown graduation year, no stated target country).
- **Rules:** never infer achievements. If something is not in the inputs, it is a gap, not a guess. Form fields override document-derived values.
- **Output:** `StudentProfile`.
- **Failure handling:** GitHub unreachable or user not found, so continue with `github=None` and add a gap + `warning` event. Unreadable document, so emit an `error` event telling the UI to request pasted text.

### 8.2 Agent 2: Opportunity Researcher
- **Tools:** `web_search`
- **Input:** `StudentProfile`, `exclude_ids/urls` (already tried), `round_number`, and optional `feedback` from the router (e.g. "need more opportunities in country X" or "too many closed deadlines").
- **Job:** generate **diverse** queries derived from the profile (field + level + country + funding need + notable strengths), run searches, and return **at least 15 candidates per round** (more than needed because verification will reject many). Mix kinds: scholarships, funded programs, and government schemes, across the student's target countries. If target countries are empty, choose reasonable ones from the profile and say so in an `info` event.
- **Rules:** every candidate needs a `source_url` from a real search result; never emit a URL that did not come from a tool result. Prefer official domains, but aggregators may serve as leads that the Verifier follows to the official page.
- **Output:** `list[Candidate]`.
- **Failure handling:** a search returning nothing means reformulate (different keywords, broader/narrower country, add "scholarship for international students in <field>"), logged as `retry` events. On round 2+, queries must differ from earlier rounds.

### 8.3 Agent 3: Eligibility Verifier
- **Tools:** `fetch_page`, `web_search` (to find the official page when the candidate came from an aggregator)
- **Input:** one `Candidate` + `StudentProfile` + today's date.
- **Job:**
  1. Fetch the page. If it is an aggregator, locate and fetch the official page (search `site:`/name queries or follow the official link in the text).
  2. Extract deadline, funding (what is covered and the amount), eligibility requirements, and how to apply, **each with a verbatim `evidence_quote`** copied from the fetched text.
  3. For each requirement, compare it to the profile and emit a `CriterionCheck` (`met`, `not_met`, `unknown`).
  4. Set `deadline_state` using today's date.
  5. Set `status`: `verified` (official source, key fields evidenced, no `not_met`), `partial` (some fields missing), `rejected` (clearly not eligible, or no such program), `unreachable` (page could not be fetched).
- **Rules:** if the page does not say it, the value is `null`. Never fill from memory. Quotes must be copied exactly.
- **Post-processing in code (not the agent):** run `verify_evidence()` on every `Evidenced` field against the cached page text. Unverified fields are nulled.
- **Execution:** run candidates concurrently with a small cap (e.g. 4 workers) to respect rate limits. One candidate's failure must not stop the others.
- **Output:** `VerifiedOpportunity` per candidate.

### 8.4 Agent 4: Ranker / Advisor
- **Tools:** none (pure reasoning over verified data)
- **Input:** all `VerifiedOpportunity` with status `verified` or `partial`, plus the `StudentProfile` and today's date.
- **Job:** score and select the **top 5** using this rubric (weights in `config.py`):

  | Factor | Weight |
  |---|---|
  | Eligibility fit (met criteria, no `not_met`) | 35 |
  | Funding coverage relative to `funding_need` | 25 |
  | Alignment with target field/level/country | 15 |
  | Deadline feasibility (open, with enough time to apply) | 15 |
  | Source trust (official > aggregator) | 10 |

- **Closed deadlines:** many deadlines will have passed. Do not drop good opportunities silently. Rank open ones above closed ones; for a strong but closed opportunity, mark the deadline as closed and note "check next cycle" in `risks`. Never present a closed deadline as open.
- **Rules:** `why_fit` must cite concrete profile facts (e.g. a specific project, the CGPA, a skill). `next_steps` come from `how_to_apply` evidence only. If fewer than 5 qualify, return fewer and say why. Do not pad the list.
- **Output:** `list[RankedOpportunity]` (up to 5).

### 8.5 Agent 5: SOP Writer
- **Tools:** none
- **Input:** `StudentProfile` + the #1 ranked opportunity (or the one the user selects).
- **Job:** draft a statement of purpose tailored to that opportunity's stated focus and requirements.
- **Rules:** use **only** facts present in the profile. List every fact used in `facts_used`. Where the SOP needs information the profile lacks (a personal story, a specific professor, a research interest), insert `[PLACEHOLDER: ...]` and list it in `placeholders`. Never invent achievements. Include a visible banner: "DRAFT only. Review and edit before use; nothing has been submitted."
- **Output:** `SOPDraft`.
- **Code check:** after generation, verify every entry in `facts_used` is traceable to the profile (substring or field match); otherwise flag a `warning` event.

---

## 9. Orchestration and Failure Recovery (`app/flow.py`)

Use a CrewAI **Flow**. Each step runs a small Crew (one agent, one task, `output_pydantic`). Steps hand off via typed state on the Flow, and each hand-off emits a `handoff` event.

```
ingest -> profile_analyst -> researcher(round 1) -> verifier(all candidates)
      -> router: verified_count >= TARGET (10) or round >= MAX_ROUNDS (3)?
            no  -> researcher(round+1, feedback, exclude) -> verifier(new only) -> router
            yes -> ranker -> sop_writer -> finish
```

**The feedback loop is the key autonomy demo.** When the router sees too few verified/partial opportunities, it builds specific `feedback` (e.g. "only 6 usable; none in <country>; 4 had closed deadlines") and sends it back to the Researcher. The UI must show this loop happening.

**Constants (`config.py`):** `TARGET_VERIFIED = 10`, `MAX_ROUNDS = 3`, `CANDIDATES_PER_ROUND >= 15`, `VERIFY_WORKERS = 4`.

If after `MAX_ROUNDS` fewer than 10 are usable, proceed anyway and report the true count. Honesty beats padding.

### Recovery table (the only sanctioned fallbacks; each emits an event)

| Failure | Response | Event |
|---|---|---|
| Tavily error/429/missing key | Retry 2x with exponential backoff (1s, 3s), then fall back to `ddgs` | `retry`, `fallback` |
| Page fetch 403/429/timeout | Retry 2x, then Tavily Extract, then mark `unreachable` | `retry`, `fallback` |
| LLM rate limit/transient error | Backoff retry up to 3x; keep `max_rpm` conservative | `retry` |
| LLM returns invalid structure | One re-ask with the validation error included, then mark that item failed | `retry`, `warning` |
| GitHub missing/rate-limited | Continue without it, record a gap | `warning` |
| Search returns nothing useful | Reformulate queries (max 2 times per round) | `retry` |
| Evidence quote not found in page | Null the field, mark unverified | `warning` |
| One candidate fails in verification | Skip it, continue with others | `warning` |

Retry logic lives once in `util/retry.py` and emits events; do not duplicate it across tools.

---

## 10. Backend API (`app/main.py`)

- `GET /health` returns `{"ok": true}`.
- `POST /api/run` (multipart form): fields `resume` (file, optional), `marksheet` (file, optional), `resume_text` / `marksheet_text` (optional pasted text), `github_url` (optional), `extra_links` (optional, comma/newline separated), `target_level`, `target_fields`, `target_countries`, `funding_need`, `name` (optional).
  - The response is a **streaming response** (SSE-style `text/event-stream` or NDJSON) that emits `Event` objects as they happen and a final `{"type": "result", "data": RunResult}` event.
  - **Why one streaming request:** on Cloud Run, CPU is throttled outside active requests, so background work started after a response returns can stall. Keeping the run inside the open streaming request avoids that.
- The flow runs in a worker thread so the event loop keeps streaming. `EventBus` bridges thread to async via a queue.
- Save each finished `RunResult` to `runs/<timestamp>.json` for reproducibility; the demo and diagram can use these.
- Validate uploads (size limit, extensions `.pdf`/`.txt`). Return clear 4xx errors.

---

## 11. Frontend (`static/index.html`)

Simple and clean. No framework.

- **Input panel:** name, resume upload (or paste), marksheet upload (or paste), GitHub URL, extra links, target level, fields, countries, funding need. Two buttons: "Load sample profile A" and "Load sample profile B" that fill the form from fixtures (this makes the live demo and the adaptability test fast).
- **Run button:** "Find my opportunities".
- **Live agent panel:** five agent cards (idle / working / done / retrying) updated from events; below them a scrolling event log with timestamps. `retry`, `fallback`, and `warning` events are visually distinct, because failure recovery is scored.
- **Results:**
  - Extracted profile summary, including the **gaps** flagged
  - **Top 5** cards: name, institution/country, why it fits, funding, deadline (with open/closed badge), how to apply, source links, a "verified" badge
  - Table of all checked opportunities (10+) with status and source
  - SOP draft with the DRAFT banner, a copy button, and a download button
- Show a clear error message if the stream fails; never leave a spinner with no explanation.

---

## 12. Docker and Deployment

- `Dockerfile`: `python:3.11-slim`, install requirements, copy the app, `CMD uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8080}`.
- Deploy: `gcloud run deploy scholarshipstar --source . --region asia-south1 --allow-unauthenticated --timeout 600 --max-instances 1 --memory 1Gi` with env vars (or Secret Manager) for `TAVILY_API_KEY`, `GEMINI_API_KEY` (or whichever LLM key), and `LLM_MODEL`.
- Local demo must also work: `uvicorn app.main:app --reload`. The hackathon explicitly allows a local demo, so Cloud Run is a bonus. Do not let deployment block the core build.
- Deploy a minimal hello-world version of this container early (Milestone 1) to catch deployment problems before the last night.

---

## 13. Tests (what "correct" means)

Write these; they must pass before the final milestone.

1. `test_evidence.py`: quote present, quote absent, whitespace/case differences, too-short quote rejected.
2. `test_fetch.py` (mocked HTTP): HTML extraction, PDF extraction, 403 then retry then fallback, unreachable result shape.
3. `test_search_fallback.py` (mocked): Tavily failure leads to `ddgs` fallback with `fallback` event emitted.
4. `test_flow_router.py` (stubbed crews): fewer than 10 verified triggers a second round with feedback and exclusions; `MAX_ROUNDS` stops the loop; honest count reported.
5. `test_adaptability.py`: **runs the query-generation step for `profile_a.json` and `profile_b.json`** (profile B: different field, different countries, low CGPA, no GitHub, funding need differs) and asserts (a) generated queries differ materially, (b) no product code under `app/` contains hardcoded student names or scholarship names (grep test), (c) a profile with no GitHub still runs.
6. `scripts/smoke_run.py`: the full real flow against both fixtures with live APIs. Print the event log, the top 5 with URLs, and a pass/fail check that **every shown deadline/funding value has `verified=True`**. This is a manual live check (it costs API calls), not part of `pytest`.

---

## 14. Milestones (3 days)

**Milestone 1: Skeleton and deploy smoke test (Day 1, morning)**
- Repo layout, `config.py`, `models.py`, `events.py`, FastAPI `/health`, Dockerfile.
- Deploy hello-world to Cloud Run (or confirm local run if blocked; do not burn more than an hour).
- *Runtime check:* `curl /health` works locally and on the deployed URL.

**Milestone 2: Tools (Day 1)**
- `search.py`, `fetch.py`, `github.py`, `documents.py`, `evidence.py`, `retry.py` with tests 1-3.
- *Runtime check:* run each tool against a real query/URL/GitHub user and show real output, including one forced failure that triggers the fallback.

**Milestone 3: Agents and Flow (Day 2)**
- `agents.py`, `tasks.py`, `flow.py` with the feedback loop; test 4.
- *Runtime check:* `scripts/smoke_run.py` on profile A. Show 10+ checked opportunities, each with source URLs and verified evidence.

**Milestone 4: API and UI (Day 2, evening)**
- Streaming `/api/run`, `index.html` with live agent panel and results.
- *Runtime check:* run it in the browser end to end (use a browser tool if available) and screenshot the live agent log and the results.

**Milestone 5: Adaptability and hardening (Day 3, morning)**
- Test 5; run profile B live; fix whatever was accidentally hardcoded; tune prompts using real failures from `dev_log.md`.
- *Runtime check:* profile B produces clearly different, correct, sourced results with no code changes.

**Milestone 6: Deliverables (Day 3, afternoon)**
- Final deploy; `README.md` with Mermaid agent diagram; `docs/architecture.md`; clean-up pass (`vulture`, `ruff`); draft the hackathon note from `dev_log.md`.
- Leave time for the 5-minute screen recording (done by the human).

---

## 15. Definition of Done

- [ ] 5 distinct agents, each with its own tools and structured output, passing data through a CrewAI Flow
- [ ] Feedback loop visibly triggers when too few verified results exist
- [ ] 10+ real opportunities checked from real search results; top 5 with funding, deadline, how to apply, and sources
- [ ] Every displayed deadline/funding/requirement has a verified evidence quote, or is shown as "unverified/unknown"
- [ ] Closed deadlines are labeled, never presented as open
- [ ] SOP draft uses only profile facts, with placeholders where facts are missing, and the DRAFT banner
- [ ] Failure paths from Section 9 all emit visible events and are covered by tests
- [ ] Profile B runs with no code changes; grep test confirms nothing is hardcoded
- [ ] UI works locally; deployed URL works (or is documented as not deployed)
- [ ] `ruff`, `mypy`, `vulture`, and `pytest` all clean, with output recorded in `docs/dev_log.md`
- [ ] `README.md` with a Mermaid agent diagram, setup steps, and API-key instructions
- [ ] No secrets in the repo

## 16. Out of Scope

Submitting real applications, user accounts, a database, OCR for scanned PDFs, payment features, and anything beyond the five agents. Do not add features that are not in this document.

## 17. Required Environment Variables (`.env.example`)

```
LLM_MODEL=            # e.g. a Gemini Flash model name, per current docs
GEMINI_API_KEY=       # or the key for whichever LLM provider is used
TAVILY_API_KEY=
GITHUB_TOKEN=         # optional, raises GitHub rate limit
```
