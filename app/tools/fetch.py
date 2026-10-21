"""fetch_page – Tavily Extract preferred, httpx + trafilatura/pypdf fallback, strict retry policies."""

from __future__ import annotations

import asyncio
import io
import random
import re
import time
from datetime import UTC, datetime
from typing import Any

import httpx
import trafilatura
from bs4 import BeautifulSoup
from pypdf import PdfReader
from tavily import AsyncTavilyClient

from app.cache import get_cache, set_cache
from app.config import (
    CHAOS_RATE,
    FETCH_MAX_TOTAL_S,
    PAGE_TEXT_CHARS,
    TAVILY_API_KEY,
)
from app.events import EventBus, global_bus

# Standard chrome124 browser impersonation headers
CHROME124_HEADERS: dict[str, str] = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
    "Sec-Ch-Ua": '"Chromium";v="124", "Google Chrome";v="124", "Not-A.Brand";v="99"',
    "Sec-Ch-Ua-Mobile": "?0",
    "Sec-Ch-Ua-Platform": '"Windows"',
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "none",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}
_UA = CHROME124_HEADERS["User-Agent"]

# Status codes that should NEVER be retried
NO_RETRY_STATUSES = {401, 403, 404, 410, 451}

# In-memory page cache for verification
_page_cache: dict[str, str] = {}


def get_page_cache() -> dict[str, str]:
    return _page_cache


def clear_page_cache() -> None:
    _page_cache.clear()


def select_relevant_passages(text: str, max_chars: int = PAGE_TEXT_CHARS) -> str:
    """Select passages around scholarship-related keywords if text exceeds limit."""
    if len(text) <= max_chars:
        return text

    keywords = [
        "deadline",
        "funding",
        "stipend",
        "eligibility",
        "apply",
        "requirements",
        "criteria",
        "citizenship",
        "tuition",
        "award",
        "scholarship",
        "fellowship",
        "procedure",
        "selection",
    ]
    pattern = re.compile(r"\b(" + "|".join(keywords) + r")\b", re.IGNORECASE)

    # Split text into paragraphs
    paragraphs = [p.strip() for p in text.split("\n") if p.strip()]
    selected: list[str] = []
    current_chars = 0

    # Always keep intro (first 2 paragraphs)
    for p in paragraphs[:2]:
        selected.append(p)
        current_chars += len(p) + 2

    # Grep paragraphs matching keywords
    for p in paragraphs[2:]:
        if pattern.search(p):
            if current_chars + len(p) + 4 > max_chars:
                break
            selected.append(p)
            current_chars += len(p) + 4

    # If still small, fill with subsequent paragraphs
    if current_chars < max_chars // 2:
        for p in paragraphs[2:]:
            if p not in selected:
                if current_chars + len(p) + 4 > max_chars:
                    break
                selected.append(p)
                current_chars += len(p) + 4

    result = "\n\n[...]\n\n".join(selected)
    return result[:max_chars]


def _extract_html(html: str) -> str:
    try:
        text = trafilatura.extract(html) or ""
        if len(text) > 200:
            return text
    except Exception:
        pass
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    return soup.get_text(separator="\n", strip=True)


def _extract_pdf(content: bytes) -> str:
    reader = PdfReader(io.BytesIO(content))
    parts = [page.extract_text() or "" for page in reader.pages]
    return "\n".join(parts).strip()


async def fetch_page_async(
    url: str,
    bus: EventBus | None = None,
    agent: str = "Verifier",
    run_id: str = "",
    chaos: bool = False,
) -> dict[str, Any]:
    """Asynchronously fetch a page respecting timeouts, caching, and retry policies."""
    event_bus = bus or global_bus
    t_start = time.time()

    # 1. Check disk cache
    cached = get_cache("fetch", url)
    if cached and isinstance(cached, dict):
        event_bus.emit(
            {
                "run_id": run_id,
                "agent": agent,
                "type": "cache_hit",
                "phase": "fetch",
                "message": f"Cache hit for URL: {url}",
                "data": {"url": url},
            }
        )
        _page_cache[url] = cached.get("text", "")
        return cached

    event_bus.emit(
        {
            "run_id": run_id,
            "agent": agent,
            "type": "tool_call",
            "phase": "fetch",
            "message": f"fetch_page: {url}",
            "data": {"url": url},
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
                    "phase": "fetch",
                    "message": f"Simulating transient timeout on {url}",
                    "data": {"url": url},
                }
            )
            # Will trigger standard retry logic below

    # 3. Prefer Tavily Extract if API key is present
    if TAVILY_API_KEY:
        try:
            client = AsyncTavilyClient(api_key=TAVILY_API_KEY)
            extract_resp = await asyncio.wait_for(
                client.extract(urls=[url], extract_depth="basic", timeout=8),
                timeout=9.0,
            )
            results = extract_resp.get("results", [])
            if results and results[0].get("raw_content"):
                raw_text = results[0]["raw_content"]
                final_text = select_relevant_passages(raw_text)
                _page_cache[url] = final_text
                duration_ms = int((time.time() - t_start) * 1000)

                res = {
                    "url": url,
                    "final_url": url,
                    "status": "ok",
                    "text": final_text,
                    "source": "tavily_extract",
                    "fetched_at": datetime.now(UTC).isoformat(),
                }
                set_cache("fetch", url, res)
                event_bus.emit(
                    {
                        "run_id": run_id,
                        "agent": agent,
                        "type": "tool_result",
                        "phase": "fetch",
                        "message": f"Tavily Extract fetched {url} ({len(final_text)} chars in {duration_ms}ms)",
                        "duration_ms": duration_ms,
                        "data": {"url": url, "chars": len(final_text)},
                    }
                )
                return res
        except Exception as tavily_exc:
            event_bus.emit(
                {
                    "run_id": run_id,
                    "agent": agent,
                    "type": "retry",
                    "phase": "fetch",
                    "message": f"Tavily Extract failed for {url} ({tavily_exc}); falling back to httpx",
                    "data": {"url": url, "error": str(tavily_exc)},
                }
            )

    # 4. Fallback to httpx with strict timeout and status code policy
    timeout_cfg = httpx.Timeout(connect=5.0, read=10.0, write=5.0, pool=5.0)
    max_attempts = 2
    last_err: Exception | None = None
    tls_retries = 0

    for attempt in range(1, max_attempts + 1):
        elapsed_so_far = time.time() - t_start
        if elapsed_so_far >= FETCH_MAX_TOTAL_S:
            break

        remaining_time = max(1.0, FETCH_MAX_TOTAL_S - elapsed_so_far)
        attempt_timeout = min(10.0, remaining_time)

        try:
            async with httpx.AsyncClient(
                follow_redirects=True,
                timeout=timeout_cfg,
                headers={"User-Agent": _UA},
                verify=False,  # Avoid broken SSL certs on academic sites
            ) as client:
                resp = await asyncio.wait_for(client.get(url), timeout=attempt_timeout)

                # Check HTTP status code
                if resp.status_code in NO_RETRY_STATUSES:
                    # Never retry 401, 403, 404, 410, 451
                    event_bus.emit(
                        {
                            "run_id": run_id,
                            "agent": agent,
                            "type": "warning",
                            "phase": "fetch",
                            "message": f"HTTP {resp.status_code} on {url} (no retry)",
                            "data": {"url": url, "status_code": resp.status_code},
                        }
                    )
                    return {
                        "url": url,
                        "final_url": str(resp.url),
                        "status": "unreachable",
                        "reason": f"HTTP {resp.status_code}",
                        "text": "",
                        "fetched_at": datetime.now(UTC).isoformat(),
                    }

                resp.raise_for_status()

                # Extraction
                ct = resp.headers.get("content-type", "")
                if "pdf" in ct.lower():
                    raw_text = _extract_pdf(resp.content)
                else:
                    raw_text = _extract_html(resp.text)

                final_text = select_relevant_passages(raw_text)
                _page_cache[url] = final_text
                final_url = str(resp.url)
                if final_url != url:
                    _page_cache[final_url] = final_text

                duration_ms = int((time.time() - t_start) * 1000)
                res = {
                    "url": url,
                    "final_url": final_url,
                    "status": "ok",
                    "text": final_text,
                    "source": "httpx",
                    "fetched_at": datetime.now(UTC).isoformat(),
                }
                set_cache("fetch", url, res)
                event_bus.emit(
                    {
                        "run_id": run_id,
                        "agent": agent,
                        "type": "tool_result",
                        "phase": "fetch",
                        "message": f"Fetched {url} ({len(final_text)} chars in {duration_ms}ms)",
                        "duration_ms": duration_ms,
                        "data": {"url": url, "chars": len(final_text)},
                    }
                )
                return res

        except (httpx.ConnectTimeout, httpx.ReadTimeout, httpx.ConnectError, TimeoutError) as exc:
            last_err = exc
            if "ssl" in str(exc).lower() or "tls" in str(exc).lower():
                tls_retries += 1
                if tls_retries > 1:
                    break

            if attempt < max_attempts and (time.time() - t_start) < FETCH_MAX_TOTAL_S - 2:
                event_bus.emit(
                    {
                        "run_id": run_id,
                        "agent": agent,
                        "type": "retry",
                        "phase": "fetch",
                        "message": f"Fetch {url} attempt {attempt} failed ({type(exc).__name__}). Retrying...",
                        "data": {"url": url, "attempt": attempt, "error": str(exc)},
                    }
                )
                await asyncio.sleep(0.5)
            else:
                break
        except Exception as exc:
            last_err = exc
            break

    # Unreachable
    duration_ms = int((time.time() - t_start) * 1000)
    reason = str(last_err) if last_err else "Timeout or network failure"
    event_bus.emit(
        {
            "run_id": run_id,
            "agent": agent,
            "type": "warning",
            "phase": "fetch",
            "message": f"Unreachable URL: {url} ({reason})",
            "duration_ms": duration_ms,
            "data": {"url": url, "reason": reason},
        }
    )
    return {
        "url": url,
        "final_url": url,
        "status": "unreachable",
        "reason": reason,
        "text": "",
        "fetched_at": datetime.now(UTC).isoformat(),
    }


def fetch_page(
    url: str,
    bus: EventBus | None = None,
    agent: str = "Verifier",
    run_id: str = "",
    chaos: bool = False,
) -> dict[str, Any]:
    """Synchronous wrapper for fetch_page_async."""
    try:
        loop = asyncio.get_event_loop()
        if loop.is_running():
            # In a running loop, use nest_asyncio or runner
            import concurrent.futures

            with concurrent.futures.ThreadPoolExecutor(max_workers=1) as executor:
                future = executor.submit(
                    asyncio.run, fetch_page_async(url, bus=bus, agent=agent, run_id=run_id, chaos=chaos)
                )
                return future.result(timeout=FETCH_MAX_TOTAL_S + 2)
        else:
            return loop.run_until_complete(
                fetch_page_async(url, bus=bus, agent=agent, run_id=run_id, chaos=chaos)
            )
    except Exception:
        return asyncio.run(
            fetch_page_async(url, bus=bus, agent=agent, run_id=run_id, chaos=chaos)
        )
