"""In-memory asynchronous broadcaster for Server-Sent Events (SSE) telemetry."""

import asyncio
import json
import logging
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)


class TelemetryBroadcaster:
    """Manages active SSE client subscriber queues and broadcasts real-time telemetry events."""

    def __init__(self) -> None:
        self._subscribers: Dict[str, Set[asyncio.Queue]] = {}

    @property
    def subscriber_count(self) -> int:
        """Total number of currently connected SSE clients across all farms."""
        return sum(len(queues) for queues in self._subscribers.values())

    def subscribe(self, farm_id: str) -> asyncio.Queue:
        """Register a new SSE client queue scoped to a specific farm."""
        queue: asyncio.Queue = asyncio.Queue(maxsize=100)
        if farm_id not in self._subscribers:
            self._subscribers[farm_id] = set()
        self._subscribers[farm_id].add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue, farm_id: Optional[str] = None) -> None:
        """Unregister an SSE client queue upon disconnection."""
        if farm_id and farm_id in self._subscribers:
            self._subscribers[farm_id].discard(queue)
            if not self._subscribers[farm_id]:
                del self._subscribers[farm_id]
        else:
            # Fallback search across all farms
            for f_id in list(self._subscribers.keys()):
                self._subscribers[f_id].discard(queue)
                if not self._subscribers[f_id]:
                    del self._subscribers[f_id]

    async def broadcast(self, event: str, data: Dict[str, Any], farm_id: Optional[str] = None) -> None:
        """Broadcast an SSE event frame strictly to authorized client queues.

        If farm_id is omitted or None, inspects data for a 'farm_id' key.
        If no farm_id is present, broadcasts to all active subscriber queues (e.g., system messages).
        """
        target_farm = farm_id or data.get("farm_id")
        if target_farm:
            target_queues = list(self._subscribers.get(target_farm, set()))
        else:
            target_queues = [q for queues in self._subscribers.values() for q in queues]

        if not target_queues:
            return

        payload = f"event: {event}\ndata: {json.dumps(data)}\n\n"
        dead_queues = []
        for q in target_queues:
            try:
                q.put_nowait(payload)
            except asyncio.QueueFull:
                dead_queues.append(q)

        for q in dead_queues:
            self.unsubscribe(q, farm_id=target_farm)


broadcaster = TelemetryBroadcaster()

