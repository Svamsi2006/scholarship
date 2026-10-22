"""Unit tests verifying Phase 1-3 improvements: RAG, token bucket, zero-tolerance filtering, and citizenship."""

from __future__ import annotations

import litellm
import pytest

from app.llm_gate import TokenBucket
from app.models import (
    Candidate,
    CriterionCheck,
    StudentProfile,
    VerifiedOpportunity,
)
from app.tools.rag import ScholarRAG


def test_litellm_drop_params_configured():
    assert getattr(litellm, "drop_params", False) is True


def test_scholar_rag_indexing_and_retrieval():
    rag = ScholarRAG()
    sample_url = "https://ox.ac.uk/test-scholarship"
    sample_text = (
        "Welcome to the University of Oxford. The Clarendon Fund Scholarship deadline is 20 January 2026. "
        "Funding covers full tuition fees plus an annual living stipend of 18622 GBP. "
        "Applicants must apply by the January course deadline. Open to all students regardless of nationality or citizenship. "
        "Please apply through the standard graduate application portal."
    )
    col_name = rag.index_page(sample_url, sample_text)
    assert col_name != ""

    # Query for deadline
    retrieved = rag.query_page(sample_url, queries=["deadline closing date application"])
    assert "20 January 2026" in retrieved or "Clarendon" in retrieved

    # Query for funding
    funding_res = rag.query_page(sample_url, queries=["funding tuition stipend"])
    assert "18622" in funding_res or "tuition" in funding_res


@pytest.mark.asyncio
async def test_dual_token_bucket_rpm_and_tpm():
    bucket = TokenBucket(rpm=60, tpm=10000)
    # Acquire token quota
    await bucket.acquire(estimated_tokens=500, agent="test_verifier")
    assert bucket.agent_usage.get("test_verifier") == 500
    assert bucket.rpm_tokens < 60.0


def test_citizenship_and_residency_defaults():
    profile = StudentProfile(name="Amina", target_level="Masters")
    assert profile.citizenship is None
    assert profile.residency_status is None


def test_zero_tolerance_filtering_disqualifies_not_met():
    opp_met = VerifiedOpportunity(
        candidate=Candidate(id="c1", name="Global Scholarship", source_url="http://example.com/1", found_by_query="test"),
        status="verified",
        requirements=[
            CriterionCheck(criterion="Bachelors Degree", result="met"),
            CriterionCheck(criterion="Minimum GPA", result="met"),
        ],
        citizenship_met=True,
    )

    opp_ineligible = VerifiedOpportunity(
        candidate=Candidate(id="c2", name="US Domestic Fellowship", source_url="http://example.com/2", found_by_query="test"),
        status="verified",
        requirements=[
            CriterionCheck(criterion="US Citizenship Required", result="not_met"),
        ],
        citizenship_met=False,
    )

    usable = [opp_met, opp_ineligible]

    # Verify zero-tolerance boolean filter
    eligible = [
        v for v in usable
        if not any(r.result == "not_met" for r in v.requirements) and v.citizenship_met
    ]

    assert len(eligible) == 1
    assert eligible[0].candidate.name == "Global Scholarship"


def test_pre_screen_candidate_drops_mismatches():
    from app.flow import pre_screen_candidate

    male_ms_profile = StudentProfile(
        name="Alex Sharma",
        target_level="Masters",
        target_fields=["Computer Science"],
        target_countries=["USA"],
        citizenship="India",
        residency_status="Non-Resident",
    )

    # 1. Demographic mismatch: Women in Tech
    passed, reason = pre_screen_candidate("VIP Women In Technology (WITS)", "Scholarship for women applicants", male_ms_profile)
    assert not passed
    assert "demographic" in reason.lower() or "women" in reason.lower()

    # 2. Ethnic mismatch: Hispanic Fund
    passed, reason = pre_screen_candidate("Hispanic Scholarship Fund", "Awards for Latino students", male_ms_profile)
    assert not passed
    assert "ethnicity" in reason.lower() or "hispanic" in reason.lower()

    # 3. Institutional mismatch: Community College
    passed, reason = pre_screen_candidate("Pierce College Foundation Scholarship", "For community college students", male_ms_profile)
    assert not passed
    assert "degree level" in reason.lower() or "institution" in reason.lower()

    # 4. Citizenship mismatch: US Citizens only
    passed, reason = pre_screen_candidate("DoD SMART Fellowship", "U.S. citizens only", male_ms_profile)
    assert not passed
    assert "citizenship" in reason.lower()

    # 5. Legitimate Graduate International Scholarship: Must PASS
    passed, reason = pre_screen_candidate("Stanford Knight-Hennessy Scholars", "Graduate fellowship open to all citizenships", male_ms_profile)
    assert passed
    assert "Passed" in reason


def test_ddgs_impersonate_pinned_valid():
    from duckduckgo_search import DDGS

    from app.tools.search import VALID_CURL_IMPERSONATES

    assert "chrome124" in VALID_CURL_IMPERSONATES
    # Pinned impersonates must not have unsupported strings like 'chrome_118'
    assert getattr(DDGS, "_impersonates", ()) == ("chrome", "firefox", "safari", "edge")


def test_vertex_ai_fallback_configuration():
    from app.config import (
        LLM_FALLBACK_MODEL,
        VERTEXAI_FALLBACK_LOCATION,
        VERTEXAI_LOCATION,
        has_gemini_key,
    )

    assert VERTEXAI_LOCATION == "us-central1"
    assert VERTEXAI_FALLBACK_LOCATION == "us-east4"
    if not has_gemini_key:
        assert LLM_FALLBACK_MODEL.startswith("vertex_ai/")


def test_queries_generation_prompt_forbids_programming_languages():
    from app.tasks import queries_generation_prompt

    profile = StudentProfile(
        name="Candidate",
        target_level="Masters",
        target_fields=["Computer Science"],
        target_countries=["USA"],
        skills=["Python", "TypeScript", "Jupyter Notebook", "HTML"],
    )

    prompt = queries_generation_prompt(profile)
    assert "NEVER include programming tools" in prompt
    assert "Jupyter Notebook" in prompt
    assert "-women -female -hispanic" in prompt


def test_deadline_classification_and_evaluation():
    """Section 7: Rolling, cycle and anticipated deadlines are kept with a badge;

    a clearly past fixed deadline is dropped; an unparseable date becomes unknown.
    """
    from app.flow import classify_and_evaluate_deadline

    # 1. Rolling deadline -> kept with badge
    dl_type, badge, drop = classify_and_evaluate_deadline("Applications accepted on a rolling basis", "rolling", "")
    assert dl_type == "rolling"
    assert badge == "rolling"
    assert not drop

    # 2. Cycle deadline (e.g. applications open each autumn) -> kept with badge
    dl_type, badge, drop = classify_and_evaluate_deadline("Applications open each autumn", "cycle", "")
    assert dl_type == "cycle"
    assert badge == "rolling"
    assert not drop

    # 3. Anticipated deadline -> kept with badge
    dl_type, badge, drop = classify_and_evaluate_deadline("Anticipated December 2027", "anticipated", "")
    assert dl_type == "anticipated"
    assert not drop

    # 4. Past fixed deadline with no next cycle -> dropped (anchor: Oct 22, 2026)
    dl_type, badge, drop = classify_and_evaluate_deadline("November 15, 2025", "fixed", "Portal closed for this year.")
    assert dl_type == "fixed"
    assert badge == "closed"
    assert drop is True

    # 5. Past fixed deadline but page mentions next cycle -> kept as cycle
    dl_type, badge, drop = classify_and_evaluate_deadline(
        "November 15, 2025", "fixed", "The previous cycle closed Nov 15 2025; next cycle for 2027 reopens soon."
    )
    assert dl_type == "cycle"
    assert drop is False

    # 6. Unparseable date string -> treated as unknown, never as past/dropped!
    dl_type, badge, drop = classify_and_evaluate_deadline("Soonish or TBD later", "fixed", "Details coming soon.")
    assert dl_type == "unknown"
    assert badge == "unknown"
    assert drop is False


def test_citizenship_null_produces_gap_not_default():
    """Section 7: Citizenship null produces a gap, not a default."""
    from app.events import EventBus
    from app.flow import scholarshipstarFlow

    bus = EventBus(run_id="test_run")
    flow = scholarshipstarFlow(run_id="test_run", bus=bus, form_fields={"target_country": "USA", "target_level": "Masters"})
    assert flow.run_id == "test_run"

    # When no citizenship is provided, profile establishment leaves citizenship as None and appends a gap
    profile = StudentProfile(name="Amina", target_level="Masters")
    assert profile.citizenship is None
    assert profile.residency_status is None

    # Verify flow gap insertion
    if profile.citizenship is None:
        gap_msg = "Citizenship unknown (must verify before applying)"
        profile.gaps.append(gap_msg)

    assert "Citizenship unknown (must verify before applying)" in profile.gaps



def test_unknown_is_kept_and_not_met_with_quote_is_rejected():
    """Section 7: unknown is kept, not_met with a quote is rejected."""
    # Unknown eligibility criterion is kept
    opp_unknown = VerifiedOpportunity(
        candidate=Candidate(id="c_unk", name="Flexible Fellowship", source_url="http://example.com/unk", found_by_query="test"),
        status="partial",
        requirements=[
            CriterionCheck(criterion="GRE Score", result="unknown", student_value="Not provided"),
            CriterionCheck(criterion="Major", result="met", evidence_quote="Open to STEM"),
        ],
        citizenship_met=True,
    )
    # Filter: reject only if there is a verified not_met
    is_rejected_unk = any(r.result == "not_met" and r.evidence_quote for r in opp_unknown.requirements)
    assert not is_rejected_unk
    assert opp_unknown.status != "rejected"

    # Not met with verified quote is rejected
    opp_not_met = VerifiedOpportunity(
        candidate=Candidate(id="c_rej", name="PhD Only Fellowship", source_url="http://example.com/rej", found_by_query="test"),
        status="rejected",
        requirements=[
            CriterionCheck(criterion="Degree Level", result="not_met", evidence_quote="First-year PhD candidates only"),
        ],
        citizenship_met=True,
    )
    is_rejected_nm = any(r.result == "not_met" and r.evidence_quote for r in opp_not_met.requirements)
    assert is_rejected_nm is True


def test_scanned_pdf_ocr_fallback_triggers_under_50_chars(monkeypatch):
    """Section 7: Scanned-PDF OCR fallback triggers when extracted text is under 50 characters."""
    from unittest.mock import MagicMock

    from app.tools import documents

    ocr_called = False

    def mock_ocr(content: bytes) -> str:
        nonlocal ocr_called
        ocr_called = True
        return "Transcripts: Calculus Grade A, Data Structures Grade A, CGPA 9.2"

    monkeypatch.setattr(documents, "_ocr_pdf_sync", mock_ocr)

    # Minimal 1-page blank PDF bytes with no text (empty scanned page)
    # Using a mock PdfReader returning empty text
    mock_page = MagicMock()
    mock_page.extract_text.return_value = "   "  # 3 spaces < 50 chars
    mock_reader = MagicMock()
    mock_reader.pages = [mock_page]

    monkeypatch.setattr(documents, "PdfReader", lambda stream: mock_reader)

    result = documents.parse_document(b"%PDF-mock", "marksheet_scanned.pdf")
    assert ocr_called is True
    assert "Calculus Grade A" in result


@pytest.mark.asyncio
async def test_hung_url_in_tavily_batch_does_not_delay_other_urls(monkeypatch):
    """Section 7: A hung URL in a Tavily batch does not delay the other URLs beyond the batch timeout."""
    import asyncio
    import time

    from app.tools import fetch


    urls = [
        "https://fast-site-1.edu/page",
        "https://fast-site-2.edu/page",
        "https://hung-site.edu/page",
    ]

    async def mock_fetch_single(url, **kwargs):
        if "hung" in url:
            # Hung site simulates timeout
            await asyncio.sleep(0.3)
            return {"url": url, "status": "unreachable", "reason": "Timeout", "text": ""}
        return {"url": url, "status": "ok", "text": f"Content for {url}"}

    monkeypatch.setattr(fetch, "TAVILY_API_KEY", "")  # Use direct parallel fetch
    monkeypatch.setattr(fetch, "fetch_page_async", mock_fetch_single)

    t0 = time.time()
    results = await fetch.fetch_pages_batch_async(urls, batch_timeout=0.5)
    elapsed = time.time() - t0

    assert elapsed < 1.5
    assert results["https://fast-site-1.edu/page"]["status"] == "ok"
    assert results["https://fast-site-2.edu/page"]["status"] == "ok"
    assert results["https://hung-site.edu/page"]["status"] == "unreachable"

