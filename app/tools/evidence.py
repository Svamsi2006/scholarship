"""verify_evidence – plain Python quote checker, no LLM involvement."""

from __future__ import annotations

import re

_MIN_QUOTE_LEN = 12


def _normalize(text: str) -> str:
    """Collapse whitespace and lower-case for comparison."""
    return re.sub(r"\s+", " ", text).strip().lower()


def verify_evidence(page_text: str, quote: str) -> bool:
    """Return True if *quote* appears (whitespace-normalised) in *page_text*.

    Rejects quotes shorter than _MIN_QUOTE_LEN characters.
    """
    if not quote or len(quote.strip()) < _MIN_QUOTE_LEN:
        return False
    return _normalize(quote) in _normalize(page_text)
