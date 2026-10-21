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
    assert profile.citizenship == "International"
    assert profile.residency_status == "Non-Resident"


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
        name="Rahul Sharma",
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
