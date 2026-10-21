"""Tests for search fallback – Tavily failure triggers DuckDuckGo."""

from unittest.mock import patch

from app.events import EventBus
from app.tools.search import web_search


@patch("app.tools.search.TAVILY_API_KEY", "fake-key")
@patch("app.tools.search._tavily_search")
@patch("app.tools.search._ddgs_search")
def test_tavily_failure_triggers_ddgs_fallback(mock_ddgs, mock_tavily):
    mock_tavily.side_effect = Exception("Tavily 429 rate limit")
    mock_ddgs.return_value = [
        {"title": "Test Scholarship", "url": "http://example.com/scholarship", "snippet": "Test"}
    ]

    bus = EventBus()
    results = web_search("test scholarship query", bus=bus, agent="Researcher")

    assert len(results) == 1
    assert results[0]["title"] == "Test Scholarship"

    # Check fallback event was emitted
    events = bus.events
    fallback_events = [e for e in events if e.type == "fallback"]
    assert len(fallback_events) >= 1
    assert "DuckDuckGo" in fallback_events[0].message


@patch("app.tools.search.TAVILY_API_KEY", "fake-key")
@patch("app.tools.search._tavily_search")
def test_tavily_success_no_fallback(mock_tavily):
    mock_tavily.return_value = [
        {"title": "Result 1", "url": "http://example.com/1", "snippet": "Test 1"},
        {"title": "Result 2", "url": "http://example.com/2", "snippet": "Test 2"},
    ]

    bus = EventBus()
    results = web_search("scholarships for CS students", bus=bus, agent="Researcher")

    assert len(results) == 2
    fallback_events = [e for e in bus.events if e.type == "fallback"]
    assert len(fallback_events) == 0


@patch("app.tools.search.TAVILY_API_KEY", "")
@patch("app.tools.search._ddgs_search")
def test_no_tavily_key_uses_ddgs_directly(mock_ddgs):
    mock_ddgs.return_value = [
        {"title": "DDG Result", "url": "http://ddg.com/result", "snippet": "Found via DDG"}
    ]

    bus = EventBus()
    results = web_search("test query", bus=bus, agent="Researcher")
    assert len(results) == 1
    assert results[0]["title"] == "DDG Result"
