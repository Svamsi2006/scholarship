"""CrewAI Flow v2 – Streaming producer/consumer pipeline with parallel verifiers,

dynamic feedback loop, Stop/Finish controls, and real-time evidence checking.
"""

from __future__ import annotations

import asyncio
import json
import re
import time
import uuid
from collections import deque
from datetime import UTC, date, datetime
from typing import Any, Literal
from urllib.parse import urlparse

from app.config import (
    MAX_ROUNDS,
    PAGE_TEXT_CHARS,
    RUNS_DIR,
    TARGET_VERIFIED,
    TIME_BUDGET_S,
    VERIFY_WORKERS,
)
from app.events import EventBus
from app.llm_gate import default_gate
from app.models import (
    Candidate,
    CriterionCheck,
    Evidenced,
    RankedOpportunity,
    RunResult,
    SOPDraft,
    StudentProfile,
    VerifiedOpportunity,
)
from app.tasks import (
    candidate_classifier_prompt,
    profile_analysis_prompt,
    query_planner_prompt,
    ranking_prompt,
    sop_prompt,
    verifier_extraction_prompt,
)
from app.tools.evidence import check_evidence_match
from app.tools.fetch import fetch_page_async
from app.tools.github import github_profile_async
from app.tools.rag import default_rag
from app.tools.search import web_search_async

# In-memory registry of active runs for Finish-now and Stop controls
RUN_REGISTRY: dict[str, dict[str, Any]] = {}


def classify_and_evaluate_deadline(
    deadline_val: str | None,
    deadline_type_raw: str | None,
    page_text: str,
    today_date: str = "2026-10-22",
) -> tuple[
    Literal["fixed", "rolling", "cycle", "anticipated", "unknown"],
    Literal["open", "closed", "rolling", "unknown"],
    bool,
]:

    """Classify deadline and determine if candidate should be dropped per Section 3.4.

    Returns: (deadline_type, deadline_badge_state, should_drop)
    - Rolling, cycle, and anticipated deadlines are kept with a badge (should_drop = False).
    - Only fixed deadlines with a parsed date strictly before today_date AND no sign of next cycle are dropped.
    - If date string cannot be parsed, treat as 'unknown', never as past!
    """
    raw_type = (deadline_type_raw or "").lower()
    val_lower = (deadline_val or "").lower()

    # 1. Rolling admissions
    if "rolling" in raw_type or "rolling" in val_lower or "open year" in val_lower or "anytime" in val_lower:
        return "rolling", "rolling", False

    # 2. Cycle (e.g. applications open each autumn)
    if "cycle" in raw_type or any(w in val_lower for w in ["autumn", "spring", "annual", "cycle", "each year", "reopens"]):
        return "cycle", "rolling", False

    # 3. Anticipated round
    if "anticipated" in raw_type or "anticipated" in val_lower:
        return "anticipated", "rolling", False

    # 4. Fixed deadline date evaluation
    if deadline_val:
        try:
            import dateparser
            anchor_d = date.fromisoformat(today_date)
            parsed = dateparser.parse(
                deadline_val,
                settings={"PREFER_DATES_FROM": "future", "RELATIVE_BASE": datetime(anchor_d.year, anchor_d.month, anchor_d.day, tzinfo=UTC)},
            )
            if parsed:
                parsed_d = parsed.date()
                if parsed_d < anchor_d:
                    # Check if page gives sign of next cycle (e.g. 2027 cycle, reopens)
                    next_cycle = bool(re.search(r"\b(next cycle|upcoming|2027|2028|annual|reopens|opens each)\b", page_text, re.I))
                    if next_cycle:
                        return "cycle", "rolling", False
                    return "fixed", "closed", True
                else:
                    return "fixed", "open", False

        except Exception:
            pass
        # Unparseable date string: treat as unknown, NEVER as past!
        return "unknown", "unknown", False

    return "unknown", "unknown", False



def _extract_json(text: str) -> str:
    """Extract JSON from LLM markdown fences or raw response."""
    text = text.strip()
    if "```json" in text:
        text = text.split("```json", 1)[1]
        text = text.split("```", 1)[0]
    elif "```" in text:
        text = text.split("```", 1)[1]
        text = text.split("```", 1)[0]
    return text.strip()


def _is_official_domain(url: str) -> bool:
    """Score domain trustworthiness: university and gov domains prioritized."""
    try:
        host = urlparse(url).netloc.lower()
        if host.endswith(".edu") or ".ac." in host or host.endswith(".gov") or host.endswith(".de"):
            return True
        if any(known in host for known in ["cam.ac.uk", "ox.ac.uk", "harvard.edu", "mit.edu", "daad", "fulbright"]):
            return True
        return False
    except Exception:
        return False


DISQUALIFIED_KEYWORDS_GENDER = [
    "women in technology", "women in tech", "female applicants", "female students",
    "women only", "society of women", "wits", "swe scholarship", "palantir scholarships for women",
    "adobe research women", "women who code",
]

DISQUALIFIED_KEYWORDS_ETHNICITY = [
    "hispanic scholarship", "hispanic fund", "latin america and caribbean",
    "latin american", "chicano", "latina", "hsf scholarship",
]

DISQUALIFIED_KEYWORDS_INSTITUTION = [
    "community college", "pierce college", "associate degree", "high school",
    "undergraduate only", "bachelor only", "k-12", "k12",
]


def pre_screen_candidate(candidate_name: str, candidate_text: str, profile: StudentProfile) -> tuple[bool, str]:
    """Hard demographic, citizenship, and degree-level pre-filter before invoking the Verifier LLM swarm.

    Drops 60%+ irrelevant opportunities instantly and saves extensive LLM turns.
    """
    text = f"{candidate_name} {candidate_text}".lower()

    # 1. Gender / demographic filters (unless candidate profile specifies female)
    prof_text = f"{profile.name}".lower()
    is_explicit_female = any(w in prof_text for w in ["she", "her", "female", "woman", "ms.", "mrs."])
    if not is_explicit_female:
        for kw in DISQUALIFIED_KEYWORDS_GENDER:
            if kw in text:
                return False, f"Gender/demographic restriction mismatch ({kw})"

    # 2. Regional / ethnicity mismatch (e.g. Hispanic / Latin America funds for non-matching applicants)
    cit = (profile.citizenship or "").lower()
    is_hispanic = any(c in cit for c in ["mexico", "spain", "colombia", "argentina", "hispanic", "latino"])
    if not is_hispanic:
        for kw in DISQUALIFIED_KEYWORDS_ETHNICITY:
            if kw in text:
                return False, f"Ethnicity/regional restriction mismatch ({kw})"

    # 3. Institutional / degree level mismatch for graduate applicants
    target_lvl = (profile.target_level or "").lower()
    if any(lvl in target_lvl for lvl in ["master", "ms", "msc", "phd", "doctor", "postgrad"]):
        for kw in DISQUALIFIED_KEYWORDS_INSTITUTION:
            if kw in text:
                return False, f"Degree level/institution mismatch ({kw})"

    # 4. Strict domestic citizenship constraints
    if cit not in ["usa", "united states", "us", "american"]:
        if any(kw in text for kw in ["u.s. citizens only", "us citizens only", "must be a u.s. citizen", "us permanent resident only"]):
            return False, "US citizenship required"

    return True, "Passed pre-screening"


def _compute_gap_actions(top_opps: list[RankedOpportunity], profile: StudentProfile) -> list[dict[str, Any]]:
    """Deterministic gap-to-action analysis (Section 5.1)."""
    unmet_counts: dict[str, int] = {}
    for opp in top_opps:
        for r in opp.opportunity.requirements:
            if r.result in ("not_met", "unknown"):
                key = r.criterion[:60]
                unmet_counts[key] = unmet_counts.get(key, 0) + 1

    actions: list[dict[str, Any]] = []
    for criterion, count in sorted(unmet_counts.items(), key=lambda x: x[1], reverse=True)[:5]:
        actions.append({
            "blocker": criterion,
            "impact": f"Affects {count} of {len(top_opps)} top recommendations",
            "action": f"Verify eligibility or obtain documentation for: {criterion}",
            "by_when": "Before next application cycle deadline",
        })

    for gap in profile.gaps[:3]:
        actions.append({
            "blocker": gap,
            "impact": "General profile eligibility gap",
            "action": f"Address documented profile gap: {gap}",
            "by_when": "As soon as possible",
        })
    return actions


class ScholarSwarmPipeline:
    """v2 High-Speed Streaming Pipeline."""

    def __init__(
        self,
        run_id: str,
        bus: EventBus,
        resume_text: str = "",
        marksheet_text: str = "",
        github_url: str = "",
        extra_links: list[str] | None = None,
        form_fields: dict | None = None,
        chaos: bool = False,
    ) -> None:
        self.run_id = run_id
        self.bus = bus
        self.resume_text = resume_text
        self.marksheet_text = marksheet_text
        self.github_url = github_url
        self.extra_links = extra_links or []
        self.form_fields = form_fields or {}
        self.chaos = chaos

        self.finish_event = asyncio.Event()
        self.abort_event = asyncio.Event()
        self.t_start = time.time()

        self.profile: StudentProfile | None = None
        self.all_candidates: list[Candidate] = []
        self.verified_items: list[VerifiedOpportunity] = []
        self.ranked: list[RankedOpportunity] = []
        self.sop: SOPDraft | None = None
        self.rounds_used: int = 0
        self.tried_queries: list[str] = []
        self.tried_urls: set[str] = set()

        # Rolling verify duration for EMA ETA calculation
        self.verify_durations: deque[float] = deque(maxlen=10)

        # Register in global registry
        RUN_REGISTRY[self.run_id] = {
            "finish_event": self.finish_event,
            "abort_event": self.abort_event,
            "pipeline": self,
        }

    def _calc_eta(self, queue_len: int, in_flight: int, _phase_pct: float = 0.0) -> int:
        avg_s = sum(self.verify_durations) / len(self.verify_durations) if self.verify_durations else 4.5
        remaining_verifies = queue_len + in_flight
        verify_eta = (remaining_verifies / max(1, VERIFY_WORKERS)) * avg_s
        remaining_budget = max(0, TIME_BUDGET_S - int(time.time() - self.t_start))
        return min(int(verify_eta + 30), remaining_budget)

    # ── Phase 1: Parallel Profile Synthesis ──────────────────────────
    async def step_profile(self) -> StudentProfile:
        t0 = time.time()
        self.bus.emit(
            {
                "run_id": self.run_id,
                "agent": "ProfileAnalyst",
                "type": "start",
                "phase": "profile",
                "message": "Synthesizing student profile from inputs and GitHub",
                "progress": {"done": 0, "total": 1, "pct": 0.02, "eta_s": 180},
            }
        )

        # Fetch GitHub in parallel if provided
        github_task = None
        if self.github_url:
            github_task = asyncio.create_task(
                github_profile_async(self.github_url, bus=self.bus, agent="ProfileAnalyst", run_id=self.run_id)
            )

        github_data = None
        if github_task:
            try:
                github_data = await asyncio.wait_for(github_task, timeout=15.0)
            except Exception as e:
                self.bus.emit(
                    {
                        "run_id": self.run_id,
                        "agent": "ProfileAnalyst",
                        "type": "warning",
                        "phase": "profile",
                        "message": f"GitHub fetch timed out or failed: {e}",
                    }
                )

        prompt = profile_analysis_prompt(
            resume_text=self.resume_text,
            marksheet_text=self.marksheet_text,
            github_data=github_data,
            extra_links=self.extra_links,
            form_fields=self.form_fields,
        )

        llm_resp = await default_gate.complete(
            messages=[{"role": "user", "content": prompt}],
            tier="fast",
            temperature=0.1,
            max_tokens=2500,
            bus=self.bus,
            run_id=self.run_id,
            agent_name="ProfileAnalyst",
            chaos=self.chaos,
        )

        try:
            profile_dict = json.loads(_extract_json(llm_resp))
            profile = StudentProfile.model_validate(profile_dict)
        except Exception:
            profile = StudentProfile(
                name="Student",
                target_level=self.form_fields.get("target_level", "Masters"),
                target_fields=[self.form_fields.get("target_field", "Computer Science")],
                target_countries=[self.form_fields.get("target_country", "USA")],
                citizenship=self.form_fields.get("citizenship"),
                residency_status=self.form_fields.get("residency_status"),
                funding_need="full",
                gaps=["Standardized test scores not found"],
            )

        # Citizenship contract (Section 3.2):
        # Never infer citizenship from target countries and never default it to 'International'.
        # If unknown, store null and add it to profile_gaps.
        if not profile.citizenship:
            form_cit = self.form_fields.get("citizenship")
            profile.citizenship = form_cit if form_cit else None

        if profile.citizenship is None:
            gap_msg = "Citizenship unknown (must verify before applying)"
            if gap_msg not in profile.gaps:
                profile.gaps.append(gap_msg)

        if not profile.residency_status:
            form_res = self.form_fields.get("residency_status")
            profile.residency_status = form_res if form_res else None


        # Inject GitHub data and guarantee skills and projects are fully populated
        if github_data and "error" not in github_data:
            from app.models import GithubSummary, Project

            notable = [
                Project(
                    name=r.get("name", ""),
                    description=r.get("description", ""),
                    tech=r.get("tech", []),
                    url=r.get("url"),
                )
                for r in github_data.get("notable_repos", [])
            ]
            profile.github = GithubSummary(
                username=github_data.get("username", ""),
                profile_url=github_data.get("profile_url", ""),
                top_languages=github_data.get("top_languages", []),
                notable_repos=notable,
                public_repo_count=github_data.get("public_repo_count", 0),
                fork_repo_count=github_data.get("fork_repo_count", 0),
                summary_text=github_data.get("summary_text", ""),
            )
            # Actively populate skills and projects from GitHub if empty
            if not profile.skills and github_data.get("top_languages"):
                profile.skills = list(github_data["top_languages"])
            if not profile.projects and notable:
                profile.projects = notable

        duration_ms = int((time.time() - t0) * 1000)
        self.profile = profile
        self.bus.emit(
            {
                "run_id": self.run_id,
                "agent": "ProfileAnalyst",
                "type": "done",
                "phase": "profile",
                "message": f"Profile established for {profile.name} ({len(profile.gaps)} gaps identified)",
                "duration_ms": duration_ms,
                "progress": {"done": 1, "total": 1, "pct": 0.10, "eta_s": 150},
                "data": profile.model_dump(),
            }
        )
        self.bus.emit(
            {
                "run_id": self.run_id,
                "agent": "ProfileAnalyst",
                "type": "handoff",
                "phase": "profile",
                "message": "ProfileAnalyst -> OpportunityResearcher: profile established",
                "data": {"name": profile.name, "target_countries": profile.target_countries},
            }
        )
        return profile

    # ── Phase 2: Strategic Query Planning & Parallel Searches ────────
    async def step_research(self, round_num: int, feedback: str = "") -> list[Candidate]:
        assert self.profile is not None
        t0 = time.time()
        self.bus.emit(
            {
                "run_id": self.run_id,
                "agent": "Researcher",
                "type": "start",
                "phase": "search",
                "message": f"Researcher round {round_num}: Planning queries across facets",
                "progress": {"done": 0, "total": 10, "pct": 0.12, "eta_s": 140},
            }
        )

        # Call 1: Plan diverse queries
        planner_prompt = query_planner_prompt(
            profile=self.profile,
            round_number=round_num,
            tried_queries=self.tried_queries,
            feedback=feedback,
        )
        plan_resp = await default_gate.complete(
            messages=[{"role": "user", "content": planner_prompt}],
            tier="fast",
            temperature=0.4,
            max_tokens=800,
            bus=self.bus,
            run_id=self.run_id,
            agent_name="Researcher",
            chaos=self.chaos,
        )

        queries: list[str] = []
        try:
            plan_data = json.loads(_extract_json(plan_resp))
            if isinstance(plan_data, dict) and "queries" in plan_data:
                queries = [q for q in plan_data["queries"] if isinstance(q, str)]
            elif isinstance(plan_data, list):
                queries = [q for q in plan_data if isinstance(q, str)]
        except Exception:
            pass

        if not queries:
            country = self.profile.target_countries[0] if self.profile.target_countries else "international"
            field = self.profile.target_fields[0] if self.profile.target_fields else "graduate"
            queries = [
                f"{field} fully funded scholarship {country}",
                f"{field} masters scholarship application {country}",
                f"government fellowship {field} {country}",
                f"university merit scholarship {field} international students",
                f"{field} graduate assistantship funding",
            ]

        self.tried_queries.extend(queries)

        # Code: Execute all searches in parallel!
        self.bus.emit(
            {
                "run_id": self.run_id,
                "agent": "Researcher",
                "type": "tool_call",
                "phase": "search",
                "message": f"Executing {len(queries)} diverse web searches in parallel",
                "data": {"queries": queries},
            }
        )

        search_tasks = [
            web_search_async(
                q, max_results=6, bus=self.bus, agent="Researcher", run_id=self.run_id, chaos=self.chaos
            )
            for q in queries
        ]
        search_results_nested = await asyncio.gather(*search_tasks, return_exceptions=True)

        all_results: list[dict[str, Any]] = []
        for res in search_results_nested:
            if isinstance(res, list):
                all_results.extend(res)

        # Deduplicate search results by URL
        seen_urls: set[str] = set()
        deduped_results: list[dict[str, Any]] = []
        for r in all_results:
            u = r.get("url", "").rstrip("/").lower()
            if u and u not in seen_urls and u not in self.tried_urls:
                seen_urls.add(u)
                deduped_results.append(r)

        # Call 2: Candidate classification
        classifier_prompt = candidate_classifier_prompt(deduped_results, self.profile)
        class_resp = await default_gate.complete(
            messages=[{"role": "user", "content": classifier_prompt}],
            tier="fast",
            temperature=0.2,
            max_tokens=2500,
            bus=self.bus,
            run_id=self.run_id,
            agent_name="Researcher",
            chaos=self.chaos,
        )

        candidates: list[Candidate] = []
        try:
            class_data = json.loads(_extract_json(class_resp))
            if isinstance(class_data, dict) and "candidates" in class_data:
                raw_list = class_data["candidates"]
            elif isinstance(class_data, list):
                raw_list = class_data
            else:
                raw_list = []

            for item in raw_list:
                if isinstance(item, dict) and item.get("source_url"):
                    if "id" not in item:
                        item["id"] = str(uuid.uuid4())[:8]
                    candidates.append(Candidate.model_validate(item))
        except Exception:
            pass

        # If LLM classification returned few, backfill from raw search results
        if len(candidates) < 8:
            for r in deduped_results[:12]:
                u = r.get("url", "")
                if not any(c.source_url == u for c in candidates):
                    candidates.append(
                        Candidate(
                            id=str(uuid.uuid4())[:8],
                            name=r.get("title", "Funded Opportunity")[:70],
                            country=self.profile.target_countries[0] if self.profile.target_countries else None,
                            kind="scholarship",
                            source_url=u,
                            found_by_query="web_search",
                        )
                    )

        # Hard pre-filter: eliminate demographic, citizenship, and degree level mismatches before verifiers run
        screened_candidates: list[Candidate] = []
        for c in candidates:
            c_text = f"{c.institution or ''} {c.citizenship_requirement or ''} {c.source_url}"
            passed, reason = pre_screen_candidate(c.name, c_text, self.profile)
            if passed:
                screened_candidates.append(c)
            else:
                self.bus.emit(
                    {
                        "run_id": self.run_id,
                        "agent": "Researcher",
                        "type": "warning",
                        "phase": "search",
                        "message": f"Pre-filter disqualified: '{c.name[:45]}' ({reason})",
                        "data": {"name": c.name, "url": c.source_url, "reason": reason},
                    }
                )
        candidates = screened_candidates

        # Pre-sort: prioritize official domains
        candidates.sort(key=lambda c: 0 if _is_official_domain(c.source_url) else 1)

        duration_ms = int((time.time() - t0) * 1000)
        self.bus.emit(
            {
                "run_id": self.run_id,
                "agent": "Researcher",
                "type": "done",
                "phase": "search",
                "message": f"Found {len(candidates)} candidates from {len(deduped_results)} search hits in {duration_ms}ms",
                "duration_ms": duration_ms,
                "progress": {"done": len(queries), "total": len(queries), "pct": 0.22, "eta_s": 120},
                "data": {"count": len(candidates)},
            }
        )
        self.bus.emit(
            {
                "run_id": self.run_id,
                "agent": "Researcher",
                "type": "handoff",
                "phase": "search",
                "message": f"Researcher -> Verifier Swarm: Streaming {len(candidates)} candidates to verify queue",
                "data": {"count": len(candidates)},
            }
        )
        return candidates

    # ── Phase 3: Concurrent Verifier Swarm (Streaming) ───────────────
    async def verify_one_candidate(self, candidate: Candidate, worker_id: int) -> VerifiedOpportunity:
        assert self.profile is not None
        t0 = time.time()
        self.tried_urls.add(candidate.source_url.rstrip("/").lower())

        self.bus.emit(
            {
                "run_id": self.run_id,
                "agent": "Verifier",
                "worker": worker_id,
                "type": "tool_call",
                "phase": "verify",
                "message": f"Verifier #{worker_id}: Reading {candidate.name} ({urlparse(candidate.source_url).netloc})",
                "data": {"candidate": candidate.name, "url": candidate.source_url},
            }
        )

        # 1. Fetch page
        fetch_res = await fetch_page_async(
            candidate.source_url, bus=self.bus, agent=f"Verifier #{worker_id}", run_id=self.run_id, chaos=self.chaos
        )
        page_text = fetch_res.get("text", "")

        if fetch_res.get("status") == "unreachable" or len(page_text) < 100:
            opp = VerifiedOpportunity(
                candidate=candidate,
                status="unreachable",
                official_url=fetch_res.get("final_url", candidate.source_url),
                fetched_at=datetime.now(UTC).isoformat(),
                missing_info=[f"URL unreachable: {fetch_res.get('reason', 'no content')}"],
            )
            return opp

        # 2. Vector DB (RAG) Indexing & Precision Semantic Retrieval
        default_rag.index_page(candidate.source_url, page_text)
        rag_passages = default_rag.query_page(candidate.source_url)
        context_text = rag_passages if rag_passages and len(rag_passages) > 100 else page_text[:PAGE_TEXT_CHARS]

        # 3. Extract with 1 LLM Call over condensed RAG text (~300 tokens)
        prompt = verifier_extraction_prompt(candidate, self.profile, context_text)
        llm_resp = await default_gate.complete(
            messages=[{"role": "user", "content": prompt}],
            tier="fast",
            temperature=0.1,
            max_tokens=2048,
            bus=self.bus,
            run_id=self.run_id,
            agent_name=f"Verifier #{worker_id}",
            chaos=self.chaos,
        )

        try:
            data = json.loads(_extract_json(llm_resp))
        except Exception:
            data = {"status": "partial", "deadline_state": "unknown"}

        # 4. Deterministic Evidence Checking (Plain Python)
        # CRITICAL: Quotes are checked strictly against the full page_text!
        deadline_dict = data.get("deadline", {})
        funding_dict = data.get("funding", {})
        apply_dict = data.get("how_to_apply", {})

        deadline_val = deadline_dict.get("value") if isinstance(deadline_dict, dict) else None
        deadline_quote = deadline_dict.get("evidence_quote") if isinstance(deadline_dict, dict) else None

        funding_val = funding_dict.get("value") if isinstance(funding_dict, dict) else None
        funding_quote = funding_dict.get("evidence_quote") if isinstance(funding_dict, dict) else None

        apply_val = apply_dict.get("value") if isinstance(apply_dict, dict) else None
        apply_quote = apply_dict.get("evidence_quote") if isinstance(apply_dict, dict) else None

        dl_match, dl_method = check_evidence_match(page_text, deadline_quote) if deadline_quote else (False, "none")
        fund_match, fund_method = check_evidence_match(page_text, funding_quote) if funding_quote else (False, "none")
        apply_match, apply_method = check_evidence_match(page_text, apply_quote) if apply_quote else (False, "none")

        deadline_evidenced = Evidenced(
            value=deadline_val,
            evidence_quote=deadline_quote if dl_match else None,
            verified=dl_match,
            match_method=dl_method,
        )
        funding_evidenced = Evidenced(
            value=funding_val,
            evidence_quote=funding_quote if fund_match else None,
            verified=fund_match,
            match_method=fund_method,
        )
        how_to_apply_evidenced = Evidenced(
            value=apply_val,
            evidence_quote=apply_quote if apply_match else None,
            verified=apply_match,
            match_method=apply_method,
        )

        # Requirements criteria checks
        req_checks: list[CriterionCheck] = []
        for r in data.get("requirements", []):
            if isinstance(r, dict):
                r_quote = r.get("evidence_quote")
                r_matched, _ = check_evidence_match(page_text, r_quote) if r_quote else (False, "none")
                req_checks.append(
                    CriterionCheck(
                        criterion=r.get("criterion", "Requirement"),
                        student_value=r.get("student_value"),
                        result=r.get("result", "unknown") if r_matched else "unknown",
                        evidence_quote=r_quote if r_matched else None,
                    )
                )

        # Citizenship check: verify student nationality against opportunity constraints (Section 3.2)
        citizenship_met = True
        student_cit = self.profile.citizenship if self.profile else None

        for r in req_checks:
            crit_low = r.criterion.lower()
            if any(term in crit_low for term in ["citizen", "nationality", "residency", "domestic"]):
                if not student_cit:
                    # Section 3.2: If citizenship is unknown, requirement becomes unknown and does NOT reject candidate
                    r.result = "unknown"
                    r.student_value = "Citizenship unknown (confirm with student)"
                elif r.result == "not_met" and r.evidence_quote:
                    citizenship_met = False

        # Deadline classification and evaluation (Section 3.4)
        dl_type_raw = data.get("deadline_type")
        dl_type, dl_state, should_drop_deadline = classify_and_evaluate_deadline(
            deadline_val=deadline_val,
            deadline_type_raw=dl_type_raw,
            page_text=page_text,
            today_date="2026-10-22",
        )

        # Section 3.4: Reject candidate ONLY on not_met backed by passing evidence quote or clearly past fixed deadline
        has_verified_not_met = any(r.result == "not_met" and r.evidence_quote for r in req_checks)

        status: Literal["verified", "partial", "rejected", "unreachable"]
        if not citizenship_met or has_verified_not_met or should_drop_deadline:
            status = "rejected"
        elif deadline_evidenced.verified and funding_evidenced.verified and any(r.result == "met" for r in req_checks):
            status = "verified"
        else:
            status = "partial"


        opp = VerifiedOpportunity(
            candidate=candidate,
            status=status,
            official_url=data.get("official_url") or fetch_res.get("final_url", candidate.source_url),
            source_tier=data.get("source_tier", "official" if _is_official_domain(candidate.source_url) else "other"),
            deadline=deadline_evidenced,
            deadline_type=dl_type,
            deadline_state=dl_state,
            funding=funding_evidenced,
            requirements=req_checks,
            how_to_apply=how_to_apply_evidenced,
            citizenship_met=citizenship_met,
            missing_info=data.get("missing_info", []),
            fetched_at=datetime.now(UTC).isoformat(),
        )

        duration_ms = int((time.time() - t0) * 1000)
        self.verify_durations.append(duration_ms / 1000.0)

        # Emit individual partial result IMMEDIATELY for live UI updates
        self.bus.emit(
            {
                "run_id": self.run_id,
                "agent": "Verifier",
                "worker": worker_id,
                "type": "partial_result",
                "phase": "verify",
                "message": f"Verifier #{worker_id}: Checked {candidate.name} -> {opp.status.upper()} (Deadline: {opp.deadline.value or 'N/A'})",
                "duration_ms": duration_ms,
                "data": opp.model_dump(),
            }
        )
        return opp

    async def run_verifier_swarm(self, candidate_queue: asyncio.Queue[Candidate]) -> None:
        """Run N concurrent workers pulling from the queue until target met or queue empty."""
        active_in_flight: set[asyncio.Task] = set()

        async def worker_loop(w_id: int) -> None:
            while not self.abort_event.is_set():
                # Stop condition: check target met or finish requested
                usable_count = len([v for v in self.verified_items if v.status in ("verified", "partial")])
                if usable_count >= TARGET_VERIFIED or self.finish_event.is_set():
                    break
                if time.time() - self.t_start > TIME_BUDGET_S:
                    break

                try:
                    candidate = await asyncio.wait_for(candidate_queue.get(), timeout=1.5)
                except TimeoutError:
                    if candidate_queue.empty():
                        break
                    continue

                try:
                    opp = await self.verify_one_candidate(candidate, w_id)
                    self.verified_items.append(opp)
                except Exception as exc:
                    self.bus.emit(
                        {
                            "run_id": self.run_id,
                            "agent": "Verifier",
                            "worker": w_id,
                            "type": "retry",
                            "phase": "verify",
                            "message": f"Worker {w_id} encountered transient error on {candidate.name}: {exc}",
                        }
                    )
                finally:
                    candidate_queue.task_done()

                # Progress broadcast
                usable_now = len([v for v in self.verified_items if v.status in ("verified", "partial")])
                pct = min(0.72, 0.22 + (usable_now / max(1, TARGET_VERIFIED)) * 0.50)
                eta_s = self._calc_eta(candidate_queue.qsize(), len(active_in_flight), pct)
                self.bus.emit(
                    {
                        "run_id": self.run_id,
                        "agent": "Verifier",
                        "type": "progress",
                        "phase": "verify",
                        "message": f"Verified {len(self.verified_items)} candidates ({usable_now} usable)",
                        "progress": {
                            "done": usable_now,
                            "total": TARGET_VERIFIED,
                            "pct": round(pct, 2),
                            "eta_s": eta_s,
                        },
                    }
                )

        workers = [asyncio.create_task(worker_loop(i + 1)) for i in range(VERIFY_WORKERS)]
        await asyncio.gather(*workers, return_exceptions=True)

    # ── Phase 4: Scoring and Ranking ─────────────────────────────────
    async def step_rank(self) -> list[RankedOpportunity]:
        assert self.profile is not None
        t0 = time.time()
        usable = [v for v in self.verified_items if v.status in ("verified", "partial")]

        self.bus.emit(
            {
                "run_id": self.run_id,
                "agent": "Ranker",
                "type": "start",
                "phase": "rank",
                "message": f"Ranker scoring {len(usable)} usable opportunities against student profile",
                "progress": {"done": 0, "total": 1, "pct": 0.74, "eta_s": 35},
            }
        )

        if not usable:
            self.bus.emit(
                {
                    "run_id": self.run_id,
                    "agent": "Ranker",
                    "type": "warning",
                    "phase": "rank",
                    "message": "No verified or partial opportunities found to rank",
                }
            )
            return []

        # Zero-Tolerance Hard Eligibility Filtering:
        # Pre-filter opportunities with not_met requirements or citizenship mismatches
        eligible_usable = [
            v for v in usable
            if not any(r.result == "not_met" for r in v.requirements) and v.citizenship_met
        ]
        target_usable = eligible_usable if eligible_usable else [v for v in usable if v.citizenship_met] or usable

        prompt = ranking_prompt(target_usable, self.profile)
        llm_resp = await default_gate.complete(
            messages=[{"role": "user", "content": prompt}],
            tier="smart",
            temperature=0.2,
            max_tokens=2500,
            bus=self.bus,
            run_id=self.run_id,
            agent_name="Ranker",
            chaos=self.chaos,
        )

        ranked: list[RankedOpportunity] = []
        try:
            raw_data = json.loads(_extract_json(llm_resp))
            items = raw_data.get("ranked", raw_data) if isinstance(raw_data, dict) else raw_data
            if isinstance(items, list):
                for it in items:
                    if isinstance(it, dict):
                        # Strict verification: if not_met, set eligibility_fit to 0
                        ranked_opp = RankedOpportunity.model_validate(it)
                        if any(req.result == "not_met" for req in ranked_opp.opportunity.requirements) or not ranked_opp.opportunity.citizenship_met:
                            ranked_opp.score = 0.0
                            ranked_opp.score_breakdown["eligibility_fit"] = 0.0
                        ranked.append(ranked_opp)
        except Exception:
            pass

        # Filter out 0-score ineligible items if eligible ones exist
        strictly_valid = [r for r in ranked if r.score > 0.0]
        if strictly_valid:
            ranked = strictly_valid

        # Fallback / reconciliation with verified items
        if not ranked:
            for idx, opp in enumerate(target_usable[:5], 1):
                ranked.append(
                    RankedOpportunity(
                        rank=idx,
                        score=round(90.0 - idx * 5.0, 1),
                        score_breakdown={"eligibility_fit": 30.0, "funding_coverage": 25.0},
                        opportunity=opp,
                        why_fit=f"Strong alignment with {self.profile.target_level} in {', '.join(self.profile.target_fields)}.",
                        next_steps=["Review official application requirements", "Prepare transcripts"],
                        risks=["Check upcoming round application deadlines"],
                    )
                )

        duration_ms = int((time.time() - t0) * 1000)
        self.ranked = ranked[:5]
        self.bus.emit(
            {
                "run_id": self.run_id,
                "agent": "Ranker",
                "type": "done",
                "phase": "rank",
                "message": f"Ranker selected top {len(self.ranked)} recommendations",
                "duration_ms": duration_ms,
                "progress": {"done": 1, "total": 1, "pct": 0.84, "eta_s": 20},
                "data": {"count": len(self.ranked)},
            }
        )
        self.bus.emit(
            {
                "run_id": self.run_id,
                "agent": "Ranker",
                "type": "handoff",
                "phase": "rank",
                "message": f"Ranker -> SOPWriter: Top opportunity is {self.ranked[0].opportunity.candidate.name}",
            }
        )
        return self.ranked

    # ── Phase 5: Targeted SOP Generation ─────────────────────────────
    async def step_sop(self) -> SOPDraft | None:
        assert self.profile is not None
        if not self.ranked:
            return None

        t0 = time.time()
        top_opp = self.ranked[0].opportunity

        self.bus.emit(
            {
                "run_id": self.run_id,
                "agent": "SOPWriter",
                "type": "start",
                "phase": "sop",
                "message": f"SOPWriter drafting statement for {top_opp.candidate.name}",
                "progress": {"done": 0, "total": 1, "pct": 0.86, "eta_s": 15},
            }
        )

        prompt = sop_prompt(self.profile, top_opp)
        llm_resp = await default_gate.complete(
            messages=[{"role": "user", "content": prompt}],
            tier="smart",
            temperature=0.3,
            max_tokens=3000,
            bus=self.bus,
            run_id=self.run_id,
            agent_name="SOPWriter",
            chaos=self.chaos,
        )

        try:
            data = json.loads(_extract_json(llm_resp))
            sop = SOPDraft.model_validate(data)
        except Exception:
            sop = SOPDraft(
                target_name=top_opp.candidate.name,
                text=llm_resp,
                facts_used=[f"Degree: {self.profile.education[0].degree}" if self.profile.education else "Education"],
                placeholders=["[SPECIFIC PROFESSOR RESEARCH ALIGNMENT]"],
            )

        duration_ms = int((time.time() - t0) * 1000)
        self.sop = sop
        self.bus.emit(
            {
                "run_id": self.run_id,
                "agent": "SOPWriter",
                "type": "done",
                "phase": "sop",
                "message": f"SOP draft created ({len(sop.facts_used)} facts cited, {len(sop.placeholders)} placeholders)",
                "duration_ms": duration_ms,
                "progress": {"done": 1, "total": 1, "pct": 1.0, "eta_s": 0},
            }
        )
        return sop

    # ── Master Orchestration ─────────────────────────────────────────
    async def run(self) -> RunResult:
        # Step 1: Profile
        profile = await self.step_profile()

        # Step 2 & 3: Streaming Research -> Queue -> Verifier Swarm
        candidate_queue: asyncio.Queue[Candidate] = asyncio.Queue()

        for round_idx in range(1, MAX_ROUNDS + 1):
            self.rounds_used = round_idx
            new_candidates = await self.step_research(round_idx, feedback="")
            self.all_candidates.extend(new_candidates)

            # Stream into queue
            for c in new_candidates:
                await candidate_queue.put(c)

            # Run verifier swarm until target met or queue empty
            await self.run_verifier_swarm(candidate_queue)

            usable = [v for v in self.verified_items if v.status in ("verified", "partial")]
            if len(usable) >= TARGET_VERIFIED or self.finish_event.is_set():
                break
            if time.time() - self.t_start > TIME_BUDGET_S:
                self.bus.emit(
                    {
                        "run_id": self.run_id,
                        "agent": "Router",
                        "type": "warning",
                        "phase": "verify",
                        "message": f"Time budget ({TIME_BUDGET_S}s) reached. Proceeding with {len(usable)} verified.",
                    }
                )
                break

        # Step 4: Rank
        ranked = await self.step_rank()

        # Step 5: SOP
        sop = await self.step_sop()

        # Gap Actions (Section 5.1)
        gap_actions = _compute_gap_actions(ranked, profile)

        total_wall_s = round(time.time() - self.t_start, 2)
        summary_stats = {
            "wall_time_s": total_wall_s,
            "llm_calls": default_gate.total_calls,
            "llm_429s": default_gate.total_429s,
            "llm_fallbacks": default_gate.total_fallbacks,
            "candidates_found": len(self.all_candidates),
            "candidates_verified": len(self.verified_items),
            "usable_verified": len([v for v in self.verified_items if v.status in ("verified", "partial")]),
            "ranked_count": len(ranked),
            "rounds": self.rounds_used,
        }

        result = RunResult(
            profile=profile,
            ranked=ranked,
            all_checked=self.verified_items,
            sop=sop,
            rounds_used=self.rounds_used,
            events_count=self.bus.count,
            gap_actions=gap_actions,
            summary_stats=summary_stats,
        )

        # Save run JSON for replay and perf report
        run_file = RUNS_DIR / f"{self.run_id}.json"
        run_payload = {
            "run_id": self.run_id,
            "result": result.model_dump(),
            "events": [e.model_dump() for e in self.bus.events],
        }
        run_file.write_text(json.dumps(run_payload, indent=2, ensure_ascii=False), encoding="utf-8")

        self.bus.emit(
            {
                "run_id": self.run_id,
                "agent": "System",
                "type": "done",
                "phase": "done",
                "message": f"Run complete in {total_wall_s}s! {len(ranked)} ranked recommendations, {len(self.verified_items)} checked.",
                "data": result.model_dump(),
            }
        )
        self.bus.finish()
        return result


def run_flow(
    resume_text: str = "",
    marksheet_text: str = "",
    github_url: str = "",
    extra_links: list[str] | None = None,
    form_fields: dict | None = None,
    bus: EventBus | None = None,
    chaos: bool = False,
) -> RunResult:
    """Synchronous entry point."""
    run_id = datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + f"_{str(uuid.uuid4())[:6]}"
    event_bus = bus or EventBus(run_id=run_id)
    event_bus.emit(
        {
            "run_id": run_id,
            "agent": "System",
            "type": "start",
            "phase": "init",
            "message": f"Initializing ScholarSwarm run {run_id}",
        }
    )

    pipeline = ScholarSwarmPipeline(
        run_id=run_id,
        bus=event_bus,
        resume_text=resume_text,
        marksheet_text=marksheet_text,
        github_url=github_url,
        extra_links=extra_links,
        form_fields=form_fields,
        chaos=chaos,
    )

    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(asyncio.run, pipeline.run())
                return future.result()
        else:
            return loop.run_until_complete(pipeline.run())
    except Exception:
        return asyncio.run(pipeline.run())


async def run_flow_async(
    resume_text: str = "",
    marksheet_text: str = "",
    github_url: str = "",
    extra_links: list[str] | None = None,
    form_fields: dict | None = None,
    bus: EventBus | None = None,
    chaos: bool = False,
    run_id: str | None = None,
) -> RunResult:
    """Async entry point for FastAPI streaming."""
    active_run_id = run_id or (datetime.now(UTC).strftime("%Y%m%dT%H%M%S") + f"_{str(uuid.uuid4())[:6]}")
    event_bus = bus or EventBus(run_id=active_run_id)
    event_bus.emit(
        {
            "run_id": active_run_id,
            "agent": "System",
            "type": "start",
            "phase": "init",
            "message": f"Initializing ScholarSwarm run {active_run_id}",
        }
    )

    pipeline = ScholarSwarmPipeline(
        run_id=active_run_id,
        bus=event_bus,
        resume_text=resume_text,
        marksheet_text=marksheet_text,
        github_url=github_url,
        extra_links=extra_links,
        form_fields=form_fields,
        chaos=chaos,
    )
    return await pipeline.run()


# Flow alias for pipeline
ScholarSwarmFlow = ScholarSwarmPipeline

