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

        # Optimization: Anchor chunk filtering (Pigeonhole principle)
        # If similarity >= 0.92, at least one 1/4th chunk of the quote MUST match verbatim in the page.
        max_errors = int(q_len * (1 - _FUZZY_THRESHOLD)) + 1
        num_chunks = max_errors + 1
        chunk_size = q_len // num_chunks
        if chunk_size < 4:
            chunk_size = 4
            num_chunks = max(2, q_len // chunk_size)

        candidate_starts: set[int] = set()
        for i in range(num_chunks):
            c_start = i * chunk_size
            c_end = c_start + chunk_size if i < num_chunks - 1 else q_len
            chunk = norm_quote[c_start:c_end]
            if len(chunk) < 4:
                continue
            pos = norm_page.find(chunk)
            while pos != -1:
                win_start = max(0, pos - c_start - 6)
                candidate_starts.add(win_start)
                pos = norm_page.find(chunk, pos + len(chunk))

        if not candidate_starts:
            return False, "none"

        matcher = difflib.SequenceMatcher(None, norm_quote, "")
        for start in candidate_starts:
            for delta in (-4, -2, 0, 2, 4):
                w_start = max(0, start + delta)
                for w_len in (q_len, q_len - 2, q_len + 2, q_len + 4):
                    if w_start + w_len > page_len:
                        continue
                    sub = norm_page[w_start : w_start + w_len]
                    matcher.set_seq2(sub)
                    if matcher.quick_ratio() >= _FUZZY_THRESHOLD and matcher.ratio() >= _FUZZY_THRESHOLD:
                        return True, "fuzzy"

    return False, "none"


def verify_evidence(page_text: str, quote: str) -> bool:
    """Return True if quote appears in page_text via exact or fuzzy normalized match."""
    matched, _ = check_evidence_match(page_text, quote)
    return matched

