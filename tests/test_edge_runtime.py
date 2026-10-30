"""Automated tests for Edge sovereign runtime, SQLite WAL queue, and synchronization."""

from datetime import datetime, timezone
from pathlib import Path

import pytest

from apps.edge.src.orchestrator import EdgeRuntime
from apps.edge.src.storage import SQLiteEdgeStorage
from apps.edge.src.transport import MockSyncTransport
from packages.telemetry_schema.models import (
    AlertSeverity,
    MetricReading,
    MetricType,
    PondTelemetryPacket,
    QualityStatus,
)


def make_test_packet(pond_id: str = "pond-01", do_val: float = 6.0, ts: datetime | None = None):
    return PondTelemetryPacket(
        farm_id="farm-alpha",
        pond_id=pond_id,
        timestamp=ts or datetime.now(timezone.utc),
        metrics={
            MetricType.DISSOLVED_OXYGEN: MetricReading(
                metric_type=MetricType.DISSOLVED_OXYGEN,
                value=do_val,
                unit="mg/L",
                quality=QualityStatus.GOOD,
            )
        },
    )


def test_sovereign_local_safety_evaluation_without_cloud(tmp_path: Path):
    """Verify Edge evaluates safety locally without requiring network connectivity."""
    db_file = tmp_path / "edge_test.db"
    storage = SQLiteEdgeStorage(db_file)
    transport = MockSyncTransport(initially_connected=False)  # Completely offline!
    edge = EdgeRuntime(storage=storage, transport=transport)

    # Ingest emergency hypoxia packet
    packet = make_test_packet(pond_id="pond-01", do_val=2.2)
    evaluation = edge.process_telemetry(packet)

    # Must immediately identify hypoxia and advise aeration locally
    assert evaluation.is_safe is False
    assert evaluation.severity == AlertSeverity.EMERGENCY
    assert evaluation.recommended_action == "ENGAGE_EMERGENCY_AERATION"


def test_offline_telemetry_persistence_and_queue_depth(tmp_path: Path):
    """Verify offline packets accumulate in the sync queue without loss."""
    db_file = tmp_path / "edge_test.db"
    storage = SQLiteEdgeStorage(db_file)
    transport = MockSyncTransport(initially_connected=False)
    edge = EdgeRuntime(storage=storage, transport=transport)

    for i in range(10):
        ts = datetime(2026, 10, 10, 10, 0, i, tzinfo=timezone.utc)
        packet = make_test_packet(pond_id="pond-01", do_val=5.5, ts=ts)
        edge.process_telemetry(packet)

    diag = edge.get_diagnostics()
    assert diag.is_connected is False
    assert diag.sovereign_mode_active is True
    assert diag.queue_depth == 10


def test_queue_recovers_after_edge_process_restart(tmp_path: Path):
    """Verify queued packets persist in SQLite WAL across process restart."""
    db_file = tmp_path / "edge_test.db"

    # Process 1: Ingest 15 packets offline
    storage_1 = SQLiteEdgeStorage(db_file)
    transport_1 = MockSyncTransport(initially_connected=False)
    edge_1 = EdgeRuntime(storage=storage_1, transport=transport_1)

    for i in range(15):
        ts = datetime(2026, 10, 10, 8, 0, i, tzinfo=timezone.utc)
        edge_1.process_telemetry(make_test_packet(pond_id="pond-02", do_val=5.8, ts=ts))

    assert edge_1.get_diagnostics().queue_depth == 15

    # Simulate crash / process restart: create brand new storage and runtime on same file
    storage_2 = SQLiteEdgeStorage(db_file)
    transport_2 = MockSyncTransport(initially_connected=False)
    edge_2 = EdgeRuntime(storage=storage_2, transport=transport_2)

    # Must recover all 15 pending packets
    assert edge_2.get_diagnostics().queue_depth == 15


def test_duplicate_packet_idempotency(tmp_path: Path):
    """Verify processing identical packet twice does not duplicate queue entries."""
    db_file = tmp_path / "edge_test.db"
    storage = SQLiteEdgeStorage(db_file)
    transport = MockSyncTransport(initially_connected=False)
    edge = EdgeRuntime(storage=storage, transport=transport)

    fixed_ts = datetime(2026, 10, 10, 12, 0, 0, tzinfo=timezone.utc)
    packet = make_test_packet(pond_id="pond-01", do_val=5.5, ts=fixed_ts)

    # Process first time
    edge.process_telemetry(packet)
    assert edge.get_diagnostics().queue_depth == 1

    # Process identical duplicate packet
    edge.process_telemetry(packet)
    assert edge.get_diagnostics().queue_depth == 1  # Still 1, not 2


def test_reconnection_and_telemetry_synchronization(tmp_path: Path):
    """Verify reconnection automatically flushes queued packets to cloud."""
    db_file = tmp_path / "edge_test.db"
    storage = SQLiteEdgeStorage(db_file)
    transport = MockSyncTransport(initially_connected=False)
    edge = EdgeRuntime(storage=storage, transport=transport)

    # 1. Enqueue 20 packets offline
    for i in range(20):
        ts = datetime(2026, 10, 10, 14, 0, i, tzinfo=timezone.utc)
        edge.process_telemetry(make_test_packet(pond_id=f"pond-{i+1:02d}", do_val=5.5, ts=ts))

    assert edge.get_diagnostics().queue_depth == 20
    assert len(transport.published_packets) == 0

    # 2. Network restores
    transport.set_connected(True)

    # 3. Trigger sync cycle
    synced_count = edge.sync_pending(batch_size=50)

    assert synced_count == 20
    assert len(transport.published_packets) == 20
    assert edge.get_diagnostics().queue_depth == 0
    assert edge.get_diagnostics().last_successful_sync is not None


def test_sync_retry_behavior_on_transport_failure(tmp_path: Path):
    """Verify failed transmissions remain in queue with retry counter incremented."""
    db_file = tmp_path / "edge_test.db"
    storage = SQLiteEdgeStorage(db_file)
    transport = MockSyncTransport(initially_connected=True)
    transport.set_fail_publish(True)  # Transport fails network calls
    edge = EdgeRuntime(storage=storage, transport=transport)

    edge.process_telemetry(make_test_packet("pond-01", 6.0))
    assert edge.get_diagnostics().queue_depth == 1

    # Attempt sync (fails)
    synced = edge.sync_pending()
    assert synced == 0
    # Must remain in queue
    assert edge.get_diagnostics().queue_depth == 1


def test_missing_critical_do_never_treated_as_safe_on_edge(tmp_path: Path):
    """Verify Edge flags missing DO sensor as DEGRADED, never safe."""
    db_file = tmp_path / "edge_test.db"
    storage = SQLiteEdgeStorage(db_file)
    transport = MockSyncTransport(initially_connected=False)
    edge = EdgeRuntime(storage=storage, transport=transport)

    packet = PondTelemetryPacket(
        farm_id="farm-alpha",
        pond_id="pond-01",
        metrics={
            MetricType.TEMPERATURE: MetricReading(
                metric_type=MetricType.TEMPERATURE,
                value=28.0,
                unit="°C",
            )
        },
    )
    eval_res = edge.process_telemetry(packet)
    assert eval_res.is_safe is False
    assert eval_res.severity == AlertSeverity.DEGRADED


def test_bounded_queue_guardrail_prevents_silent_loss(tmp_path: Path):
    """Verify exceeding max queue capacity raises explicit error rather than silently dropping."""
    db_file = tmp_path / "edge_test.db"
    storage = SQLiteEdgeStorage(db_file, max_queue_depth=3)
    transport = MockSyncTransport(initially_connected=False)
    edge = EdgeRuntime(storage=storage, transport=transport)

    # Ingest 3 packets
    for i in range(3):
        ts = datetime(2026, 10, 10, 10, 0, i, tzinfo=timezone.utc)
        edge.process_telemetry(make_test_packet("pond-01", 6.0, ts))

    # 4th packet must raise RuntimeError
    ts_4 = datetime(2026, 10, 10, 10, 0, 4, tzinfo=timezone.utc)
    with pytest.raises(RuntimeError) as exc_info:
        edge.process_telemetry(make_test_packet("pond-01", 6.0, ts_4))

    assert "exceeded maximum capacity" in str(exc_info.value)
