"""In-memory asynchronous broadcaster for Server-Sent Events (SSE) telemetry."""

import asyncio
import json
import logging
from typing import Any, Dict, Set

logger = logging.getLogger(__name__)


class TelemetryBroadcaster:
    """Manages active SSE client subscriber queues and broadcasts real-time telemetry events."""

    def __init__(self) -> None:
        self._subscribers: Set[asyncio.Queue] = set()

    @property
    def subscriber_count(self) -> int:
        """Number of currently connected SSE clients."""
        return len(self._subscribers)

    def subscribe(self) -> asyncio.Queue:
        """Register a new SSE client queue."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        self._subscribers.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue) -> None:
        """Unregister an SSE client queue upon disconnection."""
        self._subscribers.discard(queue)

    async def broadcast(self, event: str, data: Dict[str, Any]) -> None:
        """Broadcast an SSE event frame to all active client queues."""
        if not self._subscribers:
            return

        payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        dead_queues = []
        for q in list(self._subscribers):
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead_queues.append(q)

        for q in dead_queues:
            self._subscribers.discard(q)


broadcaster = TelemetryBroadcaster()

