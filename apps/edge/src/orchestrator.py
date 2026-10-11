"""Edge sovereign runtime orchestrator.

Coordinates local safety evaluation, SQLite WAL persistence, store-and-forward queueing,
and synchronization to central cloud/platform.
"""

from dataclasses import dataclass
from datetime import datetime
from typing import Dict, Optional

from apps.api.src.domain.interfaces import ISafetyEvaluator
from apps.api.src.domain.safety import ThresholdSafetyEvaluator
from apps.edge.src.storage import SQLiteEdgeStorage
from apps.edge.src.transport import ISyncTransport
from packages.telemetry_schema.config import PondConfig, get_default_20_pond_farm_config
from packages.telemetry_schema.models import (
    PondTelemetryPacket,
    SafetyEvaluationResult,
)
from tools.simulators.clock import IClock, SystemClock


@dataclass
class EdgeDiagnostics:
    """Operational health diagnostics reported by Edge runtime."""

    gateway_id: str
    farm_id: str
    is_connected: bool
    sovereign_mode_active: bool
    queue_depth: int
    last_successful_sync: Optional[datetime]
    sensor_freshness_seconds: Dict[str, float]


class EdgeRuntime:
    """Sovereign edge daemon responsible for local telemetry survival and offline control."""

    def __init__(
        self,
        storage: SQLiteEdgeStorage,
        transport: ISyncTransport,
        gateway_id: str = "edge-gw-01",
        farm_id: str = "farm-alpha",
        evaluator: Optional[ISafetyEvaluator] = None,
        clock: Optional[IClock] = None,
        ponds_config: Optional[Dict[str, PondConfig]] = None,
    ) -> None:
        self.storage = storage
        self.transport = transport
        self.gateway_id = gateway_id
        self.farm_id = farm_id
        self.evaluator = evaluator or ThresholdSafetyEvaluator()
        self.clock = clock or SystemClock()

        # Local sovereign pond configuration registry (20 ponds by default)
        if ponds_config is None:
            default_farm = get_default_20_pond_farm_config(farm_id=farm_id)
            self.ponds_config = default_farm.ponds
        else:
            self.ponds_config = ponds_config

    def process_telemetry(self, packet: PondTelemetryPacket) -> SafetyEvaluationResult:
        """Process incoming sensor reading entirely at the edge without cloud dependency.

        1. Evaluates biological thresholds deterministically.
        2. Persists packet and evaluation to local SQLite WAL.
        3. Enqueues packet into store-and-forward queue for platform synchronization.
        """
        # Local configuration lookup
        pond_config = self.ponds_config.get(packet.pond_id)

        # Deterministic safety evaluation
        evaluation = self.evaluator.evaluate(packet=packet, pond_config=pond_config)

        # Local atomic persistence and enqueue
        self.storage.save_telemetry_and_enqueue(packet=packet, evaluation=evaluation)

        return evaluation

    def sync_pending(self, batch_size: int = 50) -> int:
        """Attempt to flush pending telemetry queue to central platform.

        Safe against duplicate delivery (idempotent hashes) and retries on failure.
        """
        if not self.transport.is_connected():
            return 0

        pending_batch = self.storage.get_pending_sync_batch(limit=batch_size)
        if not pending_batch:
            return 0

        successful_hashes = []
        failed_hashes = []

        for pkt_hash, packet in pending_batch:
            ok = self.transport.publish_packet(packet)
            if ok:
                successful_hashes.append(pkt_hash)
            else:
                failed_hashes.append(pkt_hash)

        if successful_hashes:
            self.storage.mark_synced(successful_hashes)

        if failed_hashes:
            self.storage.mark_sync_failed(
                failed_hashes,
                error="Transport publish failed or timed out",
            )

        return len(successful_hashes)

    def get_diagnostics(self) -> EdgeDiagnostics:
        """Inspect edge health, queue depth, connectivity, and telemetry freshness."""
        now = self.clock.now()
        connected = self.transport.is_connected()
        queue_depth = self.storage.get_queue_depth()
        last_sync = self.storage.get_last_successful_sync()
        freshness = self.storage.get_sensor_freshness(current_time=now)

        return EdgeDiagnostics(
            gateway_id=self.gateway_id,
            farm_id=self.farm_id,
            is_connected=connected,
            sovereign_mode_active=not connected,  # Sovereign when running offline
            queue_depth=queue_depth,
            last_successful_sync=last_sync,
            sensor_freshness_seconds=freshness,
        )

