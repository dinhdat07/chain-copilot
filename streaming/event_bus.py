from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import AsyncGenerator

from streaming.schemas import ThinkingEvent


class RunEventBus:
    """
    In-memory pub/sub bus, keyed by run_id.

    Workflow:
        1. Background task (sync, in threadpool) calls publish() whenever a graph
           node emits a ThinkingEvent.
        2. WebSocket handler (async) calls subscribe() to yield each event to
           the Next.js client via WS frames.
        3. When the graph completes, the background task calls close() to signal the end.

    Thread safety:
        asyncio.Queue.put_nowait() is safe to call from non-async threads
        (see docs: https://docs.python.org/3/library/asyncio-queue.html).
        This is why we use asyncio.Queue instead of queue.Queue.
    """

    def __init__(self) -> None:
        # dict[run_id → list of subscriber queues]
        self._queues: dict[str, list[asyncio.Queue]] = defaultdict(list)
        # sequence counter per run_id
        self._seq: dict[str, int] = defaultdict(int)

    # ------------------------------------------------------------------ #
    # Producer side — called from sync thread (graph node or background task)
    # ------------------------------------------------------------------ #

    def publish(self, run_id: str, event: ThinkingEvent) -> None:
        """
        Assigns run_id and sequence number, then pushes the event to all
        subscriber queues for that run_id.

        Safe to call from any thread.
        """
        event.run_id = run_id
        self._seq[run_id] += 1
        event.sequence = self._seq[run_id]
        for q in list(self._queues.get(run_id, [])):
            try:
                q.put_nowait(event)
            except asyncio.QueueFull:
                # If subscriber is too slow — discard instead of blocking
                pass

    def close(self, run_id: str) -> None:
        """
        Sends sentinel None into each queue to signal end-of-stream.
        Subscribers will exit the loop upon receiving None.
        """
        for q in list(self._queues.get(run_id, [])):
            try:
                q.put_nowait(None)
            except asyncio.QueueFull:
                pass
        # Clean up sequence counter
        self._seq.pop(run_id, None)

    # ------------------------------------------------------------------ #
    # Consumer side — called from async WebSocket handler
    # ------------------------------------------------------------------ #

    async def subscribe(self, run_id: str) -> AsyncGenerator[ThinkingEvent, None]:
        """
        Async generator — yields each ThinkingEvent for run_id.

        Exits when:
          - Sentinel None received (graph completed)
          - Timeout 120s (client disconnected or graph stalled)

        Automatically cleans up the queue upon exit.
        """
        q: asyncio.Queue[ThinkingEvent | None] = asyncio.Queue(maxsize=512)
        self._queues[run_id].append(q)
        try:
            while True:
                try:
                    event = await asyncio.wait_for(q.get(), timeout=120.0)
                except asyncio.TimeoutError:
                    # Graph stalled or client stopped reading — end gracefully
                    break
                if event is None:
                    # Sentinel — stream ended normally
                    break
                yield event
        finally:
            # Cleanup: remove queue from subscriber list
            queues = self._queues.get(run_id)
            if queues is not None:
                try:
                    queues.remove(q)
                except ValueError:
                    pass
                if not queues:
                    self._queues.pop(run_id, None)

    # ------------------------------------------------------------------ #
    # Diagnostics
    # ------------------------------------------------------------------ #

    def active_runs(self) -> list[str]:
        """Returns a list of run_ids currently having subscribers (debug only)."""
        return list(self._queues.keys())

    def subscriber_count(self, run_id: str) -> int:
        """Number of subscribers currently listening on a run_id (debug only)."""
        return len(self._queues.get(run_id, []))


# Singleton — import and use directly from any module
event_bus = RunEventBus()
