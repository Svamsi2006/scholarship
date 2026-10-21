# ScholarSwarm Architecture

## System Overview

ScholarSwarm is a multi-agent AI system built on CrewAI's Flow framework. Five specialized agents collaborate to find, verify, and rank real scholarship opportunities for any student profile.

## Agent Pipeline

```
User Input → Profile Analyst → Researcher → Verifier → Router
                                                          ↓
                                              (need more?) → Researcher (loop)
                                              (enough?)   → Ranker → SOP Writer → Results
```

### Feedback Loop

The Router is the key autonomy mechanism:
1. After verification, it counts usable opportunities (verified + partial)
2. If count < TARGET_VERIFIED (10) and round < MAX_ROUNDS (3):
   - Builds specific feedback ("need more from Germany", "too many closed deadlines")
   - Sends it back to the Researcher with exclusions
3. If enough or max rounds reached: proceed to ranking

## Data Flow

All data flows through typed Pydantic v2 models:

```
StudentProfile → list[Candidate] → list[VerifiedOpportunity] → list[RankedOpportunity] → SOPDraft
```

## Evidence Verification

The evidence pipeline ensures honesty:
1. Verifier agent extracts quotes from fetched pages
2. `verify_evidence()` (plain Python) checks each quote exists in the page text
3. Failed quotes: field nulled, marked "unverified" in missing_info
4. The LLM never self-certifies facts

## Streaming Architecture

```
Worker Thread (CrewAI Flow)
    ↓ emit events
EventBus (thread-safe queue)
    ↓ async iterator
FastAPI StreamingResponse (NDJSON)
    ↓ fetch ReadableStream
Browser JS (event-by-event parsing)
```

This keeps the CPU active during the Cloud Run request (CPU throttled outside active requests).

## Failure Recovery

All failures are handled per the recovery table with visible events:
- Search: Tavily → DuckDuckGo (fallback event)
- Fetch: retry 2x → mark unreachable (retry + warning events)
- LLM: backoff retry (retry event)
- GitHub: continue without (warning event)
- Evidence: null the field (warning event)

Every fallback emits a visible event so the demo shows failure handling working.
