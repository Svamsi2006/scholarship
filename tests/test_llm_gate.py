"""Tests for LLMGate – backoff, fallback on rate limits, concurrency, and token bucket."""

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import litellm
import pytest

from app.events import EventBus
from app.llm_gate import LLMGate, TokenBucket


@pytest.mark.asyncio
async def test_token_bucket_rate_limiter():
    """Verify TokenBucket acquires tokens according to RPM."""
    bucket = TokenBucket(rpm=120)  # 2 tokens/sec
    t0 = asyncio.get_event_loop().time()
    for _ in range(3):
        await bucket.acquire()
    # Initial bucket is full, so should be instantaneous
    assert asyncio.get_event_loop().time() - t0 < 0.2


@pytest.mark.asyncio
async def test_llm_gate_429_triggers_retry_and_fallback():
    """TASK v2 3.1: 429 triggers backoff, then fails over to fallback model, never dropping candidate."""
    gate = LLMGate(rpm=600, concurrency=5, fallback_model="fallback/model-v2")
    bus = EventBus()

    attempt_models = []

    async def mock_acompletion(*args, **kwargs):
        model = kwargs.get("model", "")
        attempt_models.append(model)
        if len(attempt_models) < 3:
            raise litellm.RateLimitError(
                message="Resource exhausted 429",
                llm_provider="test",
                model=model,
            )
        resp = MagicMock()
        resp.choices = [MagicMock()]
        resp.choices[0].message.content = "Success response from fallback"
        resp.usage = MagicMock(prompt_tokens=10, completion_tokens=5)
        return resp

    with patch("litellm.acompletion", side_effect=mock_acompletion):
        with patch("asyncio.sleep", new_callable=AsyncMock):  # Speed up backoff in tests
            result = await gate.complete(
                messages=[{"role": "user", "content": "hi"}],
                model="primary/model-v1",
                bus=bus,
                agent_name="TestAgent",
            )
            assert result == "Success response from fallback"
            assert "fallback/model-v2" in attempt_models
            assert gate.total_429s >= 2
            assert gate.total_fallbacks >= 1
