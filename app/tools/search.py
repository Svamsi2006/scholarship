"""web_search – Tavily primary with AsyncTavilyClient, DuckDuckGo fallback, disk caching, denylist filtering."""

from __future__ import annotations

import asyncio
import random
import time
from urllib.parse import urlparse

from duckduckgo_search import DDGS
from tavily import AsyncTavilyClient, TavilyClient

from app.cache import get_cache, set_cache
from app.config import (
    CHAOS_RATE,
    DOMAIN_DENYLIST,
    TAVILY_API_KEY,
)
from app.events import EventBus, global_bus


def _is_denied(url: str) -> bool:
    try:
        host = urlparse(url).netloc.lower()
        return any(host == d or host.endswith("." + d) for d in DOMAIN_DENYLIST)
    except Exception:
        return False


def _dedup(results: list[dict]) -> list[dict]:
    seen: set[str] = set()
    out: list[dict] = []
    for r in results:
        norm = r.get("url", "").rstrip("/").lower()
        if norm and norm not in seen and not _is_denied(r.get("url", "")):
            seen.add(norm)
            out.append(r)
    return out


# Standard chrome124 browser impersonation headers and valid impersonate identifiers
CHROME124_HEADERS: dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
}

# Standardize DDGS impersonate targets to prevent "Invalid impersonate" BuilderErrors
VALID_CURL_IMPERSONATES = ["chrome124", "chrome120", "safari17_0", "edge101"]
try:
    setattr(DDGS, "_impersonates", ("chrome", "firefox", "safari", "edge"))
    setattr(DDGS, "_impersonates_os", ("windows", "macos", "linux"))
except Exception:
    pass


def _tavily_search(query: str, max_results: int = 8) -> list[dict]:
    """Synchronous Tavily search helper with safe key validation."""
    if not TAVILY_API_KEY or not TAVILY_API_KEY.strip():
        return []
    try:
        client = TavilyClient(api_key=TAVILY_API_KEY)
        resp = client.search(
            query=query,
            max_results=max_results,
            search_depth="basic",
            exclude_domains=list(DOMAIN_DENYLIST),
        )
        raw_results = resp.get("results", [])
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "snippet": r.get("content", ""),
            }
            for r in raw_results
        ]
    except Exception:
        return []


def _ddgs_search(query: str, max_results: int = 8) -> list[dict]:
    """Synchronous DuckDuckGo search helper with pinned valid browser impersonation."""
    # Ensure valid browser impersonates are set on every call
    try:
        setattr(DDGS, "_impersonates", ("chrome", "firefox", "safari", "edge"))
        setattr(DDGS, "_impersonates_os", ("windows", "macos", "linux"))
    except Exception:
        pass

    with DDGS(headers=CHROME124_HEADERS) as ddgs:
        raw = list(ddgs.text(query, max_results=max_results))
    return [
        {
            "title": r.get("title", ""),
            "url": r.get("href", ""),
            "snippet": r.get("body", ""),
        }
        for r in raw
    ]


async def web_search_async(
    query: str,
    max_results: int = 8,
    bus: EventBus | None = None,
    agent: str = "Researcher",
    run_id: str = "",
    chaos: bool = False,
) -> list[dict]:
    """Asynchronously search the web with caching, Tavily primary, and DuckDuckGo fallback."""
    event_bus = bus or global_bus
    t0 = time.time()

    # 1. Check disk cache
    cached = get_cache("search", query)
    if cached and isinstance(cached, list):
        event_bus.emit(
            {
                "run_id": run_id,
                "agent": agent,
                "type": "cache_hit",
                "phase": "search",
                "message": f"Cache hit for query: {query}",
                "data": {"query": query, "count": len(cached)},
            }
        )
        return cached

    event_bus.emit(
        {
            "run_id": run_id,
            "agent": agent,
            "type": "tool_call",
            "phase": "search",
            "message": f"web_search: {query!r}",
            "data": {"query": query},
        }
    )

    # 2. Chaos failure injection
    if chaos or (CHAOS_RATE > 0 and random.random() < CHAOS_RATE):
        if random.random() < 0.25:
            event_bus.emit(
                {
                    "run_id": run_id,
                    "agent": agent,
                    "type": "chaos_injected",
                    "phase": "search",
                    "message": f"Simulating transient search timeout on {query!r}",
                    "data": {"query": query},
                }
            )

    # 3. Tavily Search
    if TAVILY_API_KEY and not (chaos and random.random() < 0.25):
        try:
            client = AsyncTavilyClient(api_key=TAVILY_API_KEY)
            resp = await asyncio.wait_for(
                client.search(
                    query=query,
                    max_results=max_results,
                    search_depth="basic",
                    exclude_domains=list(DOMAIN_DENYLIST),
                ),
                timeout=8.0,
            )
            raw_results = resp.get("results", [])
            results = [
                {
                    "title": r.get("title", ""),
                    "url": r.get("url", ""),
                    "snippet": r.get("content", ""),
                }
                for r in raw_results
            ]
            deduped = _dedup(results)
            duration_ms = int((time.time() - t0) * 1000)
            set_cache("search", query, deduped)

            event_bus.emit(
                {
                    "run_id": run_id,
                    "agent": agent,
                    "type": "tool_result",
                    "phase": "search",
                    "message": f"Tavily returned {len(deduped)} results in {duration_ms}ms",
                    "duration_ms": duration_ms,
                    "data": {"query": query, "count": len(deduped)},
                }
            )
            return deduped
        except Exception as exc:
            event_bus.emit(
                {
                    "run_id": run_id,
                    "agent": agent,
                    "type": "fallback",
                    "phase": "search",
                    "message": f"Tavily search failed ({exc}), falling back to DuckDuckGo",
                    "data": {"query": query, "error": str(exc)},
                }
            )

    # 4. DuckDuckGo fallback
    try:
        results = await asyncio.to_thread(_ddgs_search, query, max_results)
        deduped = _dedup(results)
        duration_ms = int((time.time() - t0) * 1000)
        set_cache("search", query, deduped)

        event_bus.emit(
            {
                "run_id": run_id,
                "agent": agent,
                "type": "tool_result",
                "phase": "search",
                "message": f"DuckDuckGo returned {len(deduped)} results in {duration_ms}ms",
                "duration_ms": duration_ms,
                "data": {"query": query, "count": len(deduped)},
            }
        )
        return deduped
    except Exception as exc:
        event_bus.emit(
            {
                "run_id": run_id,
                "agent": agent,
                "type": "error",
                "phase": "search",
                "message": f"All search backends failed: {exc}",
                "data": {"query": query, "error": str(exc)},
            }
        )
        return []


def web_search(
    query: str,
    max_results: int = 8,
    bus: EventBus | None = None,
    agent: str = "Researcher",
    run_id: str = "",
    chaos: bool = False,
) -> list[dict]:
    """Synchronous search function compatible with unit tests and sync callers."""
    event_bus = bus or global_bus
    event_bus.emit(agent=agent, event_type="tool_call", message=f"web_search: {query!r}")

    if TAVILY_API_KEY:
        try:
            results = _tavily_search(query, max_results)
            deduped = _dedup(results)
            event_bus.emit(
                agent=agent,
                event_type="tool_result",
                message=f"Tavily returned {len(deduped)} results",
            )
            return deduped
        except Exception as exc:
            event_bus.emit(
                agent=agent,
                event_type="fallback",
                message=f"Tavily failed ({exc}), falling back to DuckDuckGo",
            )

    try:
        results = _ddgs_search(query, max_results)
        deduped = _dedup(results)
        event_bus.emit(
            agent=agent,
            event_type="tool_result",
            message=f"DuckDuckGo returned {len(deduped)} results",
        )
        return deduped
    except Exception as exc:
        event_bus.emit(agent=agent, event_type="error", message=f"All search backends failed: {exc}")
        return []
