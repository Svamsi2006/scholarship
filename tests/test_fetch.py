"""Tests for fetch_page – retry policy by status, timeouts, and extraction."""

from unittest.mock import MagicMock, patch

import httpx
import pytest

from app.events import EventBus
from app.tools.fetch import fetch_page_async, select_relevant_passages


def _mock_async_response(status_code=200, text="", content=b"", headers=None, url="http://example.com"):
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    resp.text = text
    resp.content = content
    resp.headers = headers or {"content-type": "text/html"}
    resp.url = url
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            message=f"{status_code}", request=MagicMock(), response=resp
        )
    return resp


@pytest.mark.asyncio
async def test_404_is_never_retried():
    """TASK v2 3.4: Never retry 404, 410, 401, 451."""
    bus = EventBus()
    call_count = 0

    async def mock_get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        return _mock_async_response(status_code=404, url=url)

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        res = await fetch_page_async("http://example.com/notfound", bus=bus)
        assert res["status"] == "unreachable"
        assert "404" in res["reason"]
        assert call_count == 1  # Exactly 1 attempt, zero retries!


@pytest.mark.asyncio
async def test_tls_timeout_retried_at_most_once():
    """TASK v2 3.4: TLS handshake timeout: one retry at most."""
    bus = EventBus()
    call_count = 0

    async def mock_get(url, **kwargs):
        nonlocal call_count
        call_count += 1
        raise httpx.ConnectError("SSL: TLS handshake timeout")

    with patch("httpx.AsyncClient.get", side_effect=mock_get):
        res = await fetch_page_async("http://example.com/badtls", bus=bus)
        assert res["status"] == "unreachable"
        assert call_count <= 2  # At most 2 calls (1 initial + 1 retry)


def test_passage_pruning():
    """Test that text exceeding limit selects keyword passages."""
    long_text = "\n\n".join([f"Paragraph {i}: Some irrelevant text about campus trees." for i in range(200)])
    long_text += "\n\nDeadline for applications is March 31, 2027. Full funding and stipend provided."
    pruned = select_relevant_passages(long_text, max_chars=1000)
    assert len(pruned) <= 1000
    assert "Deadline" in pruned or "funding" in pruned
