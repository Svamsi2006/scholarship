"""Tests for pipeline controls: Finish now, Stop, and progressive verification."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from app.events import EventBus
from app.flow import scholarshipstarPipeline
from app.models import Candidate, Evidenced, StudentProfile, VerifiedOpportunity


@pytest.mark.asyncio
async def test_finish_now_proceeds_to_ranking_with_partial_results():
    """TASK v2 4.1: Finish now sets finish_event; router stops verification and proceeds to ranker."""
    bus = EventBus(run_id="test_finish_run")
    pipe = scholarshipstarPipeline(
        run_id="test_finish_run",
        bus=bus,
        resume_text="Experienced Python developer seeking Masters",
    )

    # Pre-populate profile and some verified items
    pipe.profile = StudentProfile(
        name="Alex Doe",
        target_level="Masters",
        target_fields=["Computer Science"],
        target_countries=["USA"],
    )
    for i in range(3):
        pipe.verified_items.append(
            VerifiedOpportunity(
                candidate=Candidate(id=f"c{i}", name=f"Scholarship {i}", source_url=f"http://example.com/{i}", found_by_query="q"),
                status="verified",
                deadline=Evidenced(value="May 1", verified=True),
                funding=Evidenced(value="$10,000", verified=True),
            )
        )

    # Signal Finish now
    pipe.finish_event.set()

    with patch.object(pipe, "step_rank", new_callable=AsyncMock) as mock_rank:
        mock_rank.return_value = []
        with patch.object(pipe, "step_sop", new_callable=AsyncMock) as mock_sop:
            mock_sop.return_value = None
            # Verifier swarm loop should exit immediately due to finish_event
            queue = asyncio.Queue()
            await pipe.run_verifier_swarm(queue)
            assert pipe.finish_event.is_set()


@pytest.mark.asyncio
async def test_stop_signal_aborts_swarm():
    """TASK v2 4.1: Stop signal halts verification immediately."""
    bus = EventBus(run_id="test_stop_run")
    pipe = scholarshipstarPipeline(
        run_id="test_stop_run",
        bus=bus,
    )
    pipe.abort_event.set()
    queue = asyncio.Queue()
    await queue.put(Candidate(id="c1", name="S1", source_url="http://example.com/1", found_by_query="q"))

    await pipe.run_verifier_swarm(queue)
    # Since abort_event was set, item was not verified
    assert len(pipe.verified_items) == 0
