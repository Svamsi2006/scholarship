"""Pydantic v2 data models – the contract between agents, pipeline, and UI."""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class Education(BaseModel):
    degree: str
    field: str | None = None
    institution: str
    cgpa: float | None = None
    cgpa_scale: float | None = None
    year: int | None = None


class Project(BaseModel):
    name: str
    description: str
    tech: list[str] = Field(default_factory=list)
    url: str | None = None


class TestScore(BaseModel):
    name: str
    score: str | None = None


class GithubSummary(BaseModel):
    username: str
    profile_url: str
    top_languages: list[str] = Field(default_factory=list)
    notable_repos: list[Project] = Field(default_factory=list)
    public_repo_count: int = 0
    fork_repo_count: int = 0
    summary_text: str = ""


class StudentProfile(BaseModel):
    name: str
    education: list[Education] = Field(default_factory=list)
    skills: list[str] = Field(default_factory=list)
    projects: list[Project] = Field(default_factory=list)
    achievements: list[str] = Field(default_factory=list)
    test_scores: list[TestScore] = Field(default_factory=list)
    github: GithubSummary | None = None
    linkedin_url: str | None = None
    portfolio_url: str | None = None
    citizenship: str | None = None
    residency_status: str | None = None
    target_level: str = ""
    target_fields: list[str] = Field(default_factory=list)
    target_countries: list[str] = Field(default_factory=list)
    funding_need: Literal["full", "partial", "none"] = "full"
    gaps: list[str] = Field(default_factory=list)
    field_sources: dict[str, str] = Field(default_factory=dict)


class Candidate(BaseModel):
    id: str
    name: str
    institution: str | None = None
    country: str | None = None
    kind: Literal["scholarship", "program", "program_with_funding"] = "scholarship"
    source_url: str
    found_by_query: str
    citizenship_requirement: str | None = None
    residency_requirement: str | None = None


class CriterionCheck(BaseModel):
    criterion: str
    student_value: str | None = None
    result: Literal["met", "not_met", "unknown"] = "unknown"
    evidence_quote: str | None = None


class Evidenced(BaseModel):
    value: str | None = None
    evidence_quote: str | None = None
    verified: bool = False
    match_method: Literal["exact", "fuzzy", "none"] = "none"


class VerifiedOpportunity(BaseModel):
    candidate: Candidate
    status: Literal["verified", "partial", "rejected", "unreachable"] = "partial"
    official_url: str | None = None
    source_tier: Literal["official", "aggregator", "other"] = "other"
    deadline: Evidenced = Field(default_factory=Evidenced)
    deadline_type: Literal["fixed", "rolling", "cycle", "anticipated", "unknown"] = "unknown"
    deadline_state: Literal["open", "closed", "rolling", "unknown"] = "unknown"
    funding: Evidenced = Field(default_factory=Evidenced)
    requirements: list[CriterionCheck] = Field(default_factory=list)
    how_to_apply: Evidenced = Field(default_factory=Evidenced)
    citizenship_met: bool = True
    missing_info: list[str] = Field(default_factory=list)
    fetched_at: str = ""


class ChatMessage(BaseModel):
    role: Literal["user", "assistant", "system"]
    content: str
    timestamp: str = ""
    data: dict[str, Any] | None = None


class RankedOpportunity(BaseModel):
    rank: int
    score: float
    score_breakdown: dict[str, float] = Field(default_factory=dict)
    opportunity: VerifiedOpportunity
    why_fit: str = ""
    next_steps: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    readiness: dict[str, Any] = Field(default_factory=dict)
    actions: list[dict[str, Any]] = Field(default_factory=list)


class SOPDraft(BaseModel):
    target_name: str
    text: str
    facts_used: list[str] = Field(default_factory=list)
    placeholders: list[str] = Field(default_factory=list)


class ProgressInfo(BaseModel):
    done: int = 0
    total: int = 0
    pct: float = 0.0
    eta_s: int = 0


EventType = Literal[
    "start",
    "handoff",
    "tool_call",
    "tool_result",
    "llm_call",
    "retry",
    "fallback",
    "cache_hit",
    "chaos_injected",
    "progress",
    "info",
    "warning",
    "error",
    "partial_result",
    "done",
]


class Event(BaseModel):
    seq: int = 0
    ts: str
    run_id: str = ""
    agent: str = ""
    worker: int | None = None
    type: EventType
    phase: str = ""
    message: str
    duration_ms: int | None = None
    progress: ProgressInfo | None = None
    data: dict[str, Any] | None = None


class RunResult(BaseModel):
    profile: StudentProfile
    ranked: list[RankedOpportunity] = Field(default_factory=list)
    all_checked: list[VerifiedOpportunity] = Field(default_factory=list)
    sop: SOPDraft | None = None
    rounds_used: int = 0
    events_count: int = 0
    gap_actions: list[dict[str, Any]] = Field(default_factory=list)
    summary_stats: dict[str, Any] = Field(default_factory=dict)
