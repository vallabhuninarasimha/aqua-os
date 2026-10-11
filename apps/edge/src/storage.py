"""Edge storage engine using SQLite in Write-Ahead Logging (WAL) mode.

Guarantees:
1. Sovereign local persistence independent of network availability.
2. Store-and-forward sync queue surviving process restarts.
3. Idempotent duplicate-packet handling.
4. Bounded queue guardrails preventing silent data loss.
"""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from packages.telemetry_schema.models import (
    PondTelemetryPacket,
    SafetyEvaluationResult,
)


def compute_packet_hash(packet: PondTelemetryPacket) -> str:
    """Generate SHA-256 idempotency hash for a packet."""
    raw = f"{packet.farm_id}:{packet.pond_id}:{packet.timestamp.isoformat()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


class SQLiteEdgeStorage:
    """Manages local SQLite WAL persistence and queueing on edge gateways."""

    def __init__(self, db_path: Path, max_queue_depth: int = 50_000) -> None:
        self.db_path = Path(db_path)
        self.max_queue_depth = max_queue_depth
        self._init_db()

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path))
        conn.row_factory = sqlite3.Row
        # Enable Write-Ahead Logging (WAL) mode for concurrency and crash-resilience
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA synchronous=NORMAL;")
        return conn

    def _init_db(self) -> None:
        with self._get_connection() as conn:
            # 1. Local telemetry archive
            conn.execute("""
                CREATE TABLE IF NOT EXISTS edge_telemetry (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    farm_id TEXT NOT NULL,
                    pond_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    packet_json TEXT NOT NULL,
                    evaluation_json TEXT NOT NULL,
                    is_synced INTEGER NOT NULL DEFAULT 0,
                    created_at TEXT NOT NULL,
                    UNIQUE(farm_id, pond_id, timestamp)
                );
            """)

            # 2. Store-and-forward sync queue
            conn.execute("""
                CREATE TABLE IF NOT EXISTS sync_queue (
                    idempotency_hash TEXT PRIMARY KEY,
                    farm_id TEXT NOT NULL,
                    pond_id TEXT NOT NULL,
                    timestamp TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'PENDING',
                    retry_count INTEGER NOT NULL DEFAULT 0,
                    last_attempt TEXT,
                    error_message TEXT,
                    created_at TEXT NOT NULL
                );
            """)

            # 3. Edge metadata table
            conn.execute("""
                CREATE TABLE IF NOT EXISTS edge_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );
            """)

            conn.commit()

    def save_telemetry_and_enqueue(
        self,
        packet: PondTelemetryPacket,
        evaluation: SafetyEvaluationResult,
    ) -> str:
        """Persist telemetry locally and enqueue for cloud synchronization."""
        pkt_hash = compute_packet_hash(packet)
        now_iso = datetime.now(timezone.utc).isoformat()
        packet_json = json.dumps(packet.model_dump(mode="json"))
        eval_json = json.dumps(evaluation.model_dump(mode="json"))

        with self._get_connection() as conn:
            # Check queue depth bounds
            cursor = conn.execute("SELECT COUNT(*) FROM sync_queue WHERE status = 'PENDING';")
            depth = cursor.fetchone()[0]
            if depth >= self.max_queue_depth:
                raise RuntimeError(
                    f"Edge sync queue exceeded maximum capacity ({self.max_queue_depth}). "
                    "Halting enqueue to prevent uncontrolled memory/disk exhaustion."
                )

            # Insert into local telemetry log (ignore duplicate)
            conn.execute(
                """
                INSERT OR IGNORE INTO edge_telemetry
                (farm_id, pond_id, timestamp, packet_json, evaluation_json, is_synced, created_at)
                VALUES (?, ?, ?, ?, ?, 0, ?);
                """,
                (
                    packet.farm_id,
                    packet.pond_id,
                    packet.timestamp.isoformat(),
                    packet_json,
                    eval_json,
                    now_iso,
                ),
            )

            # Insert into sync queue (idempotent ignore on duplicate hash)
            conn.execute(
                """
                INSERT OR IGNORE INTO sync_queue
                (idempotency_hash, farm_id, pond_id, timestamp, payload_json, status, created_at)
                VALUES (?, ?, ?, ?, ?, 'PENDING', ?);
                """,
                (
                    pkt_hash,
                    packet.farm_id,
                    packet.pond_id,
                    packet.timestamp.isoformat(),
                    packet_json,
                    now_iso,
                ),
            )
            conn.commit()

        return pkt_hash

    def get_pending_sync_batch(self, limit: int = 50) -> List[Tuple[str, PondTelemetryPacket]]:
        """Retrieve a batch of pending telemetry items from queue."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                """
                SELECT idempotency_hash, payload_json
                FROM sync_queue
                WHERE status = 'PENDING'
                ORDER BY timestamp ASC
                LIMIT ?;
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            results = []
            for row in rows:
                pkt_dict = json.loads(row["payload_json"])
                packet = PondTelemetryPacket(**pkt_dict)
                results.append((row["idempotency_hash"], packet))
            return results

    def mark_synced(self, packet_hashes: List[str]) -> None:
        """Mark items as successfully synchronized and remove from active queue."""
        if not packet_hashes:
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        placeholders = ",".join("?" for _ in packet_hashes)

        with self._get_connection() as conn:
            # Delete from queue
            conn.execute(
                f"DELETE FROM sync_queue WHERE idempotency_hash IN ({placeholders});",
                packet_hashes,
            )
            # Update metadata
            conn.execute(
                """
                INSERT INTO edge_metadata (key, value) VALUES ('last_successful_sync', ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value;
                """,
                (now_iso,),
            )
            conn.commit()

    def mark_sync_failed(self, packet_hashes: List[str], error: str) -> None:
        """Increment retry count and record error."""
        if not packet_hashes:
            return
        now_iso = datetime.now(timezone.utc).isoformat()
        placeholders = ",".join("?" for _ in packet_hashes)

        with self._get_connection() as conn:
            conn.execute(
                f"""
                UPDATE sync_queue
                SET retry_count = retry_count + 1,
                    last_attempt = ?,
                    error_message = ?
                WHERE idempotency_hash IN ({placeholders});
                """,
                [now_iso, error] + packet_hashes,
            )
            conn.commit()

    def get_queue_depth(self) -> int:
        """Return count of unsynchronized pending packets."""
        with self._get_connection() as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM sync_queue WHERE status = 'PENDING';")
            return cursor.fetchone()[0]

    def get_last_successful_sync(self) -> Optional[datetime]:
        """Return timestamp of last successful cloud upload."""
        with self._get_connection() as conn:
            cursor = conn.execute(
                "SELECT value FROM edge_metadata WHERE key = 'last_successful_sync';"
            )
            row = cursor.fetchone()
            if row:
                return datetime.fromisoformat(row["value"])
            return None

    def get_sensor_freshness(self, current_time: datetime) -> Dict[str, float]:
        """Return freshness (age in seconds) of latest reading per pond."""
        with self._get_connection() as conn:
            cursor = conn.execute("""
                SELECT pond_id, MAX(timestamp) as latest_ts
                FROM edge_telemetry
                GROUP BY pond_id;
            """)
            rows = cursor.fetchall()
            freshness = {}
            for row in rows:
                pond_id = row["pond_id"]
                ts = datetime.fromisoformat(row["latest_ts"])
                if ts.tzinfo is None:
                    ts = ts.replace(tzinfo=timezone.utc)
                age = (current_time - ts).total_seconds()
                freshness[pond_id] = max(0.0, age)
            return freshness

