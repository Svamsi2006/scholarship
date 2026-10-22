"""Tests for verify_evidence and check_evidence_match – plain Python quote checker."""

from app.tools.evidence import check_evidence_match, verify_evidence


def test_quote_present():
    page = "The deadline for applications is December 31, 2026. Full tuition waiver provided."
    assert verify_evidence(page, "deadline for applications is December 31, 2026") is True


def test_quote_absent():
    page = "The deadline for applications is December 31, 2026."
    assert verify_evidence(page, "deadline for applications is January 15, 2027") is False


def test_whitespace_normalization():
    page = "The  deadline   for\napplications  is  December  31, 2026."
    assert verify_evidence(page, "deadline for applications is December 31, 2026") is True


def test_case_insensitive():
    page = "The Deadline For Applications Is December 31, 2026."
    assert verify_evidence(page, "the deadline for applications is december 31, 2026") is True


def test_too_short_quote_rejected():
    page = "The deadline for applications is December 31, 2026."
    assert verify_evidence(page, "deadline") is False  # < 12 chars


def test_empty_quote_rejected():
    page = "Some text here."
    assert verify_evidence(page, "") is False


def test_none_quote_rejected():
    page = "Some text here."
    assert verify_evidence(page, None) is False  # type: ignore[arg-type]


def test_exact_minimum_length():
    page = "applications open now for students worldwide"
    assert verify_evidence(page, "applications open now") is True  # > 12 chars


def test_quote_must_appear_in_own_text_cross_contamination():
    """Section 7: Quote-must-appear-in-own-text including a planted cross-contamination case."""
    candidate_a_text = (
        "Welcome to the Oxford Clarendon Fund. All graduate applicants are automatically considered. "
        "The award provides a full tuition fee waiver plus living costs of 18,622 GBP."
    )
    candidate_b_text = (
        "Welcome to the Gates Cambridge Scholarship. Open to citizens of all countries outside the UK. "
        "The award covers the full cost of studying at Cambridge including university fees."
    )

    quote_a = "provides a full tuition fee waiver plus living costs of 18,622 GBP"
    quote_b = "covers the full cost of studying at Cambridge including university fees"

    # Candidate A's quote matches Candidate A's page
    assert verify_evidence(candidate_a_text, quote_a) is True
    # Candidate B's quote matches Candidate B's page
    assert verify_evidence(candidate_b_text, quote_b) is True

    # Planted cross-contamination: Candidate A's quote evaluated against Candidate B's text MUST FAIL
    assert verify_evidence(candidate_b_text, quote_a) is False
    # Planted cross-contamination: Candidate B's quote evaluated against Candidate A's text MUST FAIL
    assert verify_evidence(candidate_a_text, quote_b) is False


def test_quote_normalization_survives_formatting_noise():
    """Section 7: Quote matching passes despite smart quotes, dashes, extra whitespace and markdown markup."""
    page_text = (
        "Scholarship criteria: All candidates must possess an undergraduate degree - first class honors - "
        "and have submitted an 'official transcript' before the October 31 deadline."
    )

    # Quote extracted with markdown syntax (**bold**, _italic_), smart quotes (‘, ’), em-dash (—), and extra spaces
    noisy_quote = (
        "**All candidates** must possess an _undergraduate degree_ — first class honors — "
        "and have submitted an ‘official transcript’ before the October 31 deadline."
    )

    matched, method = check_evidence_match(page_text, noisy_quote)
    assert matched is True
    assert method in ("exact", "fuzzy")
    assert verify_evidence(page_text, noisy_quote) is True


def test_fuzzy_window_match_step_two():
    """difflib fuzzy window match triggers when exact normalized fails, quote >= 25 chars, ratio >= 0.92."""
    page_text = (
        "The department provides twenty thousand dollars in living allowances and academic stipends each academic semester."
    )
    # Slight single-word typo/variation ("twenty-thousand" vs "twenty thousand", "allowances" vs "allowance")
    slight_variation_quote = (
        "twenty thousand dollars in living allowance and academic stipends each academic semester"
    )

    matched, method = check_evidence_match(page_text, slight_variation_quote)
    assert matched is True
    assert method == "fuzzy"

