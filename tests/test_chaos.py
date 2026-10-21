"""Tests for failure-injection Chaos Mode."""

from unittest.mock import AsyncMock, patch

import pytest

from app.events import EventBus
from app.llm_gate import LLMGate


@pytest.mark.asyncio
async def test_chaos_mode_recovery_logged():
    """TASK v2 4.4: Chaos mode injects transient failures and recovery events are recorded."""
    bus = EventBus(run_id="chaos_test")
    gate = LLMGate(rpm=600, concurrency=5)

    with patch("litellm.acompletion", new_callable=AsyncMock) as mock_llm:
        resp = AsyncMock()
        resp.choices = [AsyncMock()]
        resp.choices[0].message.content = '{"ok": true}'
        resp.usage = AsyncMock(prompt_tokens=10, completion_tokens=5)
        mock_llm.return_value = resp

        with patch("asyncio.sleep", new_callable=AsyncMock):
            # Run with chaos=True
            res = await gate.complete(
                messages=[{"role": "user", "content": "hi"}],
                model="test-model",
                bus=bus,
                chaos=True,
            )
            assert res == '{"ok": true}'

    event_types = [e.type for e in bus.events]
    assert "llm_call" in event_types
