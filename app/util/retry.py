"""Retry helper with exponential backoff that emits events."""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any, TypeVar

from app.config import MAX_RETRIES, RETRY_DELAYS
from app.events import EventBus

T = TypeVar("T")


def with_retries(
    fn: Callable[..., T],
    *args: Any,
    bus: EventBus,
    agent: str,
    description: str,
    max_retries: int = MAX_RETRIES,
    delays: list[float] | None = None,
    **kwargs: Any,
) -> T:
    """Call *fn* up to 1 + max_retries times with backoff. Emits retry events."""
    delays = delays or RETRY_DELAYS
    last_err: Exception | None = None
    for attempt in range(1 + max_retries):
        try:
            return fn(*args, **kwargs)
        except Exception as exc:
            last_err = exc
            if attempt < max_retries:
                delay = delays[min(attempt, len(delays) - 1)]
                bus.emit(
                    agent=agent,
                    event_type="retry",
                    message=f"{description}: attempt {attempt + 1} failed ({exc}), retrying in {delay}s",
                )
                time.sleep(delay)
    raise last_err  # type: ignore[misc]
