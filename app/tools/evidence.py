"""verify_evidence – plain Python quote checker, no LLM involvement.

Strict matching normalization:
1. Unicode NFKC normalization
2. Curly quotes and dashes to ASCII
3. Strip markdown syntax (*, _, #, >, |, [, ], `, ~)
4. Collapse all whitespace
5. Casefold

Step 1: exact substring on normalized text.
Step 2 (only if step 1 fails): fuzzy window match with stdlib difflib at ratio >= 0.92, quote >= 25 chars.
"""

from __future__ import annotations

import difflib
import re
import unicodedata
from typing import Literal

_MIN_QUOTE_LEN = 12
_MIN_FUZZY_QUOTE_LEN = 25
_FUZZY_THRESHOLD = 0.92


# Curly quotes, apostrophes, and primes to ASCII
_QUOTE_MAP = str.maketrans({
    "‘": "'",
    "’": "'",
    "‚": "'",
    "‛": "'",
    "“": '"',
    "”": '"',
    "„": '"',
    "‟": '"',
    "«": '"',
    "»": '"',
    "‹": "'",
    "›": "'",
    "`": "'",
})

# Dashes to ASCII hyphen
_DASH_MAP = str.maketrans({
    "–": "-",  # en dash
    "—": "-",  # em dash
    "−": "-",  # minus sign
    "‐": "-",  # hyphen
    "‑": "-",  # non-breaking hyphen
})

_MARKDOWN_STRIP_REGEX = re.compile(r"[*_#>`|\[\]~]")


def normalize_text(text: str) -> str:
    """Normalize text to survive formatting noise across quotes and fetched pages."""
    if not text:
        return ""
    # Unicode NFKC normalization
    nfkc = unicodedata.normalize("NFKC", text)
    # Translate curly quotes and dashes to ASCII
    trans = nfkc.translate(_QUOTE_MAP).translate(_DASH_MAP)
    # Strip markdown syntax
    no_md = _MARKDOWN_STRIP_REGEX.sub(" ", trans)
    # Collapse whitespace and casefold
    collapsed = re.sub(r"\s+", " ", no_md).strip()
    return collapsed.casefold()


def check_evidence_match(page_text: str, quote: str) -> tuple[bool, Literal["exact", "fuzzy", "none"]]:
    """Check if quote appears in page_text, returning (matched, method).

    Method is one of 'exact', 'fuzzy', or 'none'.
    """

    if not quote or not page_text:
        return False, "none"

    raw_quote = quote.strip()
    if len(raw_quote) < _MIN_QUOTE_LEN:
        return False, "none"

    norm_quote = normalize_text(raw_quote)
    norm_page = normalize_text(page_text)

    if not norm_quote or not norm_page:
        return False, "none"

    # Step 1: exact substring on normalized text
    if norm_quote in norm_page:
        return True, "exact"

    # Step 2: fuzzy window match only if step 1 fails, quote at least 25 chars, ratio >= 0.92
    if len(norm_quote) >= _MIN_FUZZY_QUOTE_LEN:
        q_len = len(norm_quote)
        page_len = len(norm_page)
        step = max(1, q_len // 4)
        matcher = difflib.SequenceMatcher(None, norm_quote, "")

        # Test windows with exact length and slightly expanded length
        for window_size in (q_len, min(page_len, q_len + 8)):
            if window_size > page_len:
                continue
            for start in range(0, page_len - window_size + 1, step):
                sub = norm_page[start : start + window_size]
                matcher.set_seq2(sub)
                if matcher.quick_ratio() >= _FUZZY_THRESHOLD and matcher.ratio() >= _FUZZY_THRESHOLD:
                    return True, "fuzzy"

    return False, "none"


def verify_evidence(page_text: str, quote: str) -> bool:
    """Return True if quote appears in page_text via exact or fuzzy normalized match."""
    matched, _ = check_evidence_match(page_text, quote)
    return matched

