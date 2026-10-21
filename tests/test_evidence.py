"""Tests for verify_evidence – the plain Python quote checker."""

from app.tools.evidence import verify_evidence


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
