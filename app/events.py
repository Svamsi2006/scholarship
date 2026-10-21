"""EventBus – thread-safe emit() + async iterator for NDJSON streaming with schema v2."""

from __future__ import annotations

import asyncio
import queue
import threading
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from app.models import Event, ProgressInfo

_SENTINEL = object()


class EventBus:
    """Thread-safe event bus supporting Event schema v2."""

    def __init__(self, run_id: str = "") -> None:
        self.run_id = run_id
        self._q: queue.Queue[Event | object] = queue.Queue()
        self._events: list[Event] = []
        self._lock = threading.Lock()
        self._seq = 0

    def emit(
        self,
        event_or_agent: dict[str, Any] | str = "",
        event_type: str = "info",
        message: str = "",
        data: dict[str, Any] | None = None,
        phase: str = "",
        worker: int | None = None,
        duration_ms: int | None = None,
        progress: dict[str, Any] | ProgressInfo | None = None,
        agent: str = "",
    ) -> Event:
        with self._lock:
            self._seq += 1
            seq = self._seq
            ts = datetime.now(UTC).isoformat()

            if not event_or_agent and agent:
                event_or_agent = agent

            if isinstance(event_or_agent, dict):
                d = dict(event_or_agent)
                evt_seq = d.get("seq", seq)
                evt_ts = d.get("ts", ts)
                evt_run_id = d.get("run_id", self.run_id)
                evt_agent = d.get("agent", "System")
                evt_type = d.get("type", "info")
                evt_message = d.get("message", "")
                evt_phase = d.get("phase", phase)
                evt_worker = d.get("worker", worker)
                evt_duration = d.get("duration_ms", duration_ms)
                evt_progress = d.get("progress", progress)
                evt_data = d.get("data")

                if isinstance(evt_progress, dict):
                    prog_obj = ProgressInfo(**evt_progress)
                elif isinstance(evt_progress, ProgressInfo):
                    prog_obj = evt_progress
                else:
                    prog_obj = None

                evt = Event(
                    seq=evt_seq,
                    ts=evt_ts,
                    run_id=evt_run_id,
                    agent=evt_agent,
                    worker=evt_worker,
                    type=evt_type,  # type: ignore[arg-type]
                    phase=evt_phase,
                    message=evt_message,
                    duration_ms=evt_duration,
                    progress=prog_obj,
                    data=evt_data,
                )
            else:
                prog_obj = ProgressInfo(**progress) if isinstance(progress, dict) else progress
                evt = Event(
                    seq=seq,
                    ts=ts,
                    run_id=self.run_id,
                    agent=str(event_or_agent),
                    worker=worker,
                    type=event_type,  # type: ignore[arg-type]
                    phase=phase,
                    message=message,
                    duration_ms=duration_ms,
                    progress=prog_obj,
                    data=data,
                )

            self._events.append(evt)

        self._q.put(evt)
        return evt

    def finish(self) -> None:
        self._q.put(_SENTINEL)

    @property
    def events(self) -> list[Event]:
        with self._lock:
            return list(self._events)

    @property
    def count(self) -> int:
        with self._lock:
            return len(self._events)

    async def stream(self) -> AsyncIterator[Event]:
        loop = asyncio.get_running_loop()
        while True:
            item = await loop.run_in_executor(None, self._q.get)
            if item is _SENTINEL:
                return
            yield item  # type: ignore[misc]


# Global bus fallback
global_bus = EventBus()
