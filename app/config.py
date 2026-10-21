"""Configuration – all settings from env vars, no hardcoded student data."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(override=True)

# ── Paths ────────────────────────────────────────────────────────────
BASE_DIR: Path = Path(__file__).resolve().parent.parent
RUNS_DIR: Path = BASE_DIR / "runs"
RUNS_DIR.mkdir(exist_ok=True)
CACHE_DIR: Path = BASE_DIR / ".cache"

# ── Google Cloud / Vertex AI & Gemini API ────────────────────────────
GOOGLE_APPLICATION_CREDENTIALS: str = os.getenv("GOOGLE_APPLICATION_CREDENTIALS", "")
if not GOOGLE_APPLICATION_CREDENTIALS and (BASE_DIR / "service_account.json").exists():
    GOOGLE_APPLICATION_CREDENTIALS = str(BASE_DIR / "service_account.json")

if GOOGLE_APPLICATION_CREDENTIALS:
    creds_path = Path(GOOGLE_APPLICATION_CREDENTIALS)
    if not creds_path.is_absolute():
        creds_path = BASE_DIR / creds_path
    if creds_path.exists():
        os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = str(creds_path)

VERTEXAI_PROJECT: str = os.getenv("VERTEXAI_PROJECT", "ai-video-462714")
VERTEXAI_LOCATION: str = os.getenv("VERTEXAI_LOCATION", "us-central1")
VERTEXAI_FALLBACK_LOCATION: str = os.getenv("VERTEXAI_FALLBACK_LOCATION", "us-east4")
if VERTEXAI_PROJECT:
    os.environ["VERTEXAI_PROJECT"] = VERTEXAI_PROJECT
if VERTEXAI_LOCATION:
    os.environ["VERTEXAI_LOCATION"] = VERTEXAI_LOCATION

GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
if GEMINI_API_KEY:
    os.environ["GEMINI_API_KEY"] = GEMINI_API_KEY

# ── Model Tiers & LLM Gate ──────────────────────────────────────────
# Default preference: gemini/gemini-2.5-flash if GEMINI_API_KEY is active and valid,
# otherwise use Google Cloud Vertex AI service account credentials.
has_gemini_key = bool(GEMINI_API_KEY and GEMINI_API_KEY.strip() and GEMINI_API_KEY != "placeholder")
default_fast = "gemini/gemini-2.5-flash" if has_gemini_key else "vertex_ai/gemini-2.5-flash"
default_smart = "gemini/gemini-2.5-flash" if has_gemini_key else "vertex_ai/gemini-2.5-flash"
# When using Vertex AI without an AI Studio key, failover within Vertex AI to secondary region (us-east4)
default_fallback = "gemini/gemini-2.0-flash" if has_gemini_key else "vertex_ai/gemini-2.5-flash"

LLM_FAST: str = os.getenv("LLM_FAST", os.getenv("LLM_MODEL", default_fast))
LLM_SMART: str = os.getenv("LLM_SMART", os.getenv("LLM_MODEL", default_smart))
LLM_FALLBACK_MODEL: str = os.getenv("LLM_FALLBACK_MODEL", default_fallback)

LLM_RPM: int = int(os.getenv("LLM_RPM", "60"))
LLM_TPM: int = int(os.getenv("LLM_TPM", "100000"))  # Tokens Per Minute quota
LLM_CONCURRENCY: int = int(os.getenv("LLM_CONCURRENCY", "6"))
LLM_MODEL: str = LLM_FAST  # backwards compatibility

# ── Search & Extraction ──────────────────────────────────────────────
TAVILY_API_KEY: str = os.getenv("TAVILY_API_KEY", "")
GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")

# ── Flow & Pipeline Constants ────────────────────────────────────────
TARGET_VERIFIED: int = int(os.getenv("TARGET_VERIFIED", "10"))
MAX_ROUNDS: int = int(os.getenv("MAX_ROUNDS", "3"))
CANDIDATES_PER_ROUND: int = int(os.getenv("CANDIDATES_PER_ROUND", "15"))
VERIFY_WORKERS: int = int(os.getenv("VERIFY_WORKERS", "6"))
TIME_BUDGET_S: int = int(os.getenv("TIME_BUDGET_S", "360"))  # 6 min hard cap
AGGREGATOR_POLICY: str = os.getenv("AGGREGATOR_POLICY", "drop")  # drop | resolve

# ── Upload limits ────────────────────────────────────────────────────
MAX_UPLOAD_MB: int = 10

# ── Tool & Page Limits ───────────────────────────────────────────────
PAGE_TEXT_CHARS: int = int(os.getenv("PAGE_TEXT_CHARS", "12000"))
FETCH_TIMEOUT: int = 10
FETCH_MAX_TOTAL_S: int = 12
MAX_RETRIES: int = 2
RETRY_DELAYS: list[float] = [1.0, 3.0]


# ── Chaos & Testing ──────────────────────────────────────────────────
CHAOS_RATE: float = float(os.getenv("CHAOS_RATE", "0.0"))
CACHE_ENABLED: bool = os.getenv("CACHE", "1") != "0"
TOOLS_VIA_MCP: bool = os.getenv("TOOLS_VIA_MCP", "false").lower() == "true"

# ── Ranker weights ───────────────────────────────────────────────────
RANK_WEIGHTS: dict[str, float] = {
    "eligibility_fit": 0.35,
    "funding_coverage": 0.25,
    "field_alignment": 0.15,
    "deadline_feasibility": 0.15,
    "source_trust": 0.10,
}

# ── Domain denylist ──────────────────────────────────────────────────
DOMAIN_DENYLIST: set[str] = {
    "quora.com",
    "reddit.com",
    "facebook.com",
    "twitter.com",
    "x.com",
    "instagram.com",
    "tiktok.com",
    "pinterest.com",
    "linkedin.com",
    "iefg.org",
    "scholarshipportal.com",
    "scholars4dev.com",
    "wemakescholars.com",
}
