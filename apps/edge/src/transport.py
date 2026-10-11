"""Sync transport abstractions and implementations for Edge to Platform communication."""

from typing import List, Optional, Protocol

import httpx

from packages.telemetry_schema.models import PondTelemetryPacket


class ISyncTransport(Protocol):
    """Abstract transport protocol for synchronizing telemetry from Edge to Cloud."""

    def is_connected(self) -> bool:
        """Check whether network transport is available."""
        ...

    def connect(self) -> bool:
        """Initiate network connection."""
        ...

    def disconnect(self) -> None:
        """Terminate network connection."""
        ...

    def publish_packet(self, packet: PondTelemetryPacket) -> bool:
        """Publish a single telemetry packet with at-least-once delivery semantics."""
        ...


class MockSyncTransport(ISyncTransport):
    """In-memory mock transport for testing network dropouts, offline buffering, and retries."""

    def __init__(self, initially_connected: bool = True) -> None:
        self._connected = initially_connected
        self._fail_publish = False
        self.published_packets: List[PondTelemetryPacket] = []

    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def set_connected(self, status: bool) -> None:
        self._connected = status

    def set_fail_publish(self, fail: bool) -> None:
        self._fail_publish = fail

    def publish_packet(self, packet: PondTelemetryPacket) -> bool:
        if not self._connected or self._fail_publish:
            return False
        self.published_packets.append(packet)
        return True


class HttpSyncTransport(ISyncTransport):
    """HTTP REST transport using FastAPI /api/v1/telemetry endpoint."""

    def __init__(
        self,
        endpoint_url: str,
        auth_token: Optional[str] = None,
        timeout_seconds: float = 5.0,
    ) -> None:
        self.endpoint_url = endpoint_url
        self.auth_token = auth_token
        self.timeout_seconds = timeout_seconds
        self._connected = True

    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> bool:
        self._connected = True
        return True

    def disconnect(self) -> None:
        self._connected = False

    def publish_packet(self, packet: PondTelemetryPacket) -> bool:
        if not self._connected:
            return False
        headers = {}
        if self.auth_token:
            headers["Authorization"] = f"Bearer {self.auth_token}"

        try:
            with httpx.Client(timeout=self.timeout_seconds) as client:
                resp = client.post(
                    self.endpoint_url,
                    json=packet.model_dump(mode="json"),
                    headers=headers,
                )
                return resp.status_code in (200, 201, 202)
        except Exception:
            return False
