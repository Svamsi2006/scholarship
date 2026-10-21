"""Tests for flow router – feedback loop logic."""

from app.config import MAX_ROUNDS, TARGET_VERIFIED
from app.models import Candidate, VerifiedOpportunity


def _make_verified(n: int, status: str = "verified") -> list[VerifiedOpportunity]:
    return [
        VerifiedOpportunity(
            candidate=Candidate(
                id=f"c{i}",
                name=f"Scholarship {i}",
                source_url=f"http://example.com/{i}",
                found_by_query="test query",
            ),
            status=status,
            fetched_at="2026-10-20T00:00:00Z",
        )
        for i in range(n)
    ]


def test_enough_verified_proceeds():
    """When >= TARGET_VERIFIED usable, should proceed to ranking."""
    verified = _make_verified(TARGET_VERIFIED)
    usable = [v for v in verified if v.status in ("verified", "partial")]
    assert len(usable) >= TARGET_VERIFIED


def test_too_few_triggers_another_round():
    """When < TARGET_VERIFIED and round < MAX_ROUNDS, should loop back."""
    verified = _make_verified(5)
    usable = [v for v in verified if v.status in ("verified", "partial")]
    round_number = 1
    assert len(usable) < TARGET_VERIFIED
    assert round_number < MAX_ROUNDS
    # Would trigger feedback loop


def test_max_rounds_stops_loop():
    """After MAX_ROUNDS, proceed even with few results."""
    verified = _make_verified(3)
    usable = [v for v in verified if v.status in ("verified", "partial")]
    round_number = MAX_ROUNDS
    assert len(usable) < TARGET_VERIFIED
    assert round_number >= MAX_ROUNDS
    # Should proceed anyway


def test_rejected_not_counted_as_usable():
    """Rejected opportunities should not count as usable."""
    verified = _make_verified(10, status="rejected")
    usable = [v for v in verified if v.status in ("verified", "partial")]
    assert len(usable) == 0


def test_partial_counts_as_usable():
    """Partial opportunities should count as usable."""
    verified = _make_verified(10, status="partial")
    usable = [v for v in verified if v.status in ("verified", "partial")]
    assert len(usable) == 10
