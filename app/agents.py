"""Agent definitions – 5 distinct agents with model tiering and configured LLMs."""

from __future__ import annotations

from crewai import LLM, Agent

from app.config import (
    GEMINI_API_KEY,
    LLM_FAST,
    LLM_SMART,
)


def _get_llm(model: str) -> LLM:
    if GEMINI_API_KEY and not model.startswith("vertex_ai/"):
        return LLM(model=model, api_key=GEMINI_API_KEY)
    return LLM(model=model)


def profile_analyst() -> Agent:
    return Agent(
        role="Profile Analyst",
        goal=(
            "Synthesize student documents, GitHub repositories, and form inputs "
            "into a structured StudentProfile. Record sources and identify eligibility gaps."
        ),
        backstory=(
            "You are an expert academic evaluator who extracts student achievements, "
            "skills, and education strictly from factual evidence without inventing credentials."
        ),
        llm=_get_llm(LLM_FAST),
        verbose=False,
        max_iter=1,
    )


def opportunity_researcher() -> Agent:
    return Agent(
        role="Opportunity Researcher",
        goal=(
            "Plan strategic search queries and classify search results into "
            "viable scholarship and funded program candidates."
        ),
        backstory=(
            "You are a scholarship strategist who knows international scholarship databases, "
            "fellowships, and university portals across target countries."
        ),
        llm=_get_llm(LLM_FAST),
        verbose=False,
        max_iter=1,
    )


def eligibility_verifier() -> Agent:
    return Agent(
        role="Eligibility Verifier",
        goal=(
            "Extract official deadlines, funding levels, and eligibility criteria "
            "with verbatim quotes from official pages."
        ),
        backstory=(
            "You are a meticulous compliance officer who cross-references official terms "
            "against student profiles. You never assume or guess missing criteria."
        ),
        llm=_get_llm(LLM_FAST),
        verbose=False,
        max_iter=1,
    )


def ranker_advisor() -> Agent:
    return Agent(
        role="Ranker & Advisor",
        goal=(
            "Score and rank verified opportunities using the 5-point rubric, "
            "citing concrete profile evidence and flagging cycle risks."
        ),
        backstory=(
            "You are a seasoned international admissions dean who matches students "
            "with high-probability, high-impact funded opportunities."
        ),
        llm=_get_llm(LLM_SMART),
        verbose=False,
        max_iter=1,
    )


def sop_writer() -> Agent:
    return Agent(
        role="SOP Writer",
        goal=(
            "Draft targeted, highly authentic Statements of Purpose based strictly "
            "on documented profile facts with clear draft banners."
        ),
        backstory=(
            "You are an elite academic writing mentor who creates tailored application "
            "essays without fabricating unverified achievements."
        ),
        llm=_get_llm(LLM_SMART),
        verbose=False,
        max_iter=1,
    )
