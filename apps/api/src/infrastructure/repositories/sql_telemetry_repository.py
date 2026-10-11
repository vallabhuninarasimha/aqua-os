"""SQL-backed implementation of ITelemetryRepository."""

import json
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

from sqlalchemy.orm import Session

from apps.api.src.domain.interfaces import ITelemetryRepository
from apps.api.src.infrastructure.models import LatestTelemetryORM, TelemetryORM
from packages.telemetry_schema.models import (
    PondTelemetryPacket,
    SafetyEvaluationResult,
)


class SQLTelemetryRepository(ITelemetryRepository):
    """Telemetry persistence repository backed by SQLAlchemy."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def save(
        self,
        packet: PondTelemetryPacket,
        evaluation: Optional[SafetyEvaluationResult] = None,
    ) -> None:
        # 1. Historical Telemetry Insertion (with duplicate idempotency)
        existing_hist = (
            self._session.query(TelemetryORM)
            .filter(
                TelemetryORM.farm_id == packet.farm_id,
                TelemetryORM.pond_id == packet.pond_id,
                TelemetryORM.timestamp == packet.timestamp,
            )
            .first()
        )
        if not existing_hist:
            orm_record = TelemetryORM.from_domain(packet)
            self._session.add(orm_record)

        # 2. Latest State Cache Upsert
        existing_latest = (
            self._session.query(LatestTelemetryORM)
            .filter(
                LatestTelemetryORM.farm_id == packet.farm_id,
                LatestTelemetryORM.pond_id == packet.pond_id,
            )
            .first()
        )

        raw_metrics = {
            m_type.value: reading.model_dump(mode="json")
            for m_type, reading in packet.metrics.items()
        }
        hw_json = (
            json.dumps(packet.hardware_status.model_dump(mode="json"))
            if packet.hardware_status
            else None
        )
        safety_json = (
            json.dumps(evaluation.model_dump(mode="json"))
            if evaluation
            else None
        )

        if existing_latest:
            # Update only if incoming packet is equal or newer
            if packet.timestamp >= existing_latest.timestamp.replace(tzinfo=timezone.utc):
                existing_latest.timestamp = packet.timestamp
                existing_latest.metrics_json = json.dumps(raw_metrics)
                existing_latest.hardware_status_json = hw_json
                existing_latest.safety_result_json = safety_json
                existing_latest.is_simulated = packet.is_simulated
        else:
            new_latest = LatestTelemetryORM(
                farm_id=packet.farm_id,
                pond_id=packet.pond_id,
                timestamp=packet.timestamp,
                metrics_json=json.dumps(raw_metrics),
                hardware_status_json=hw_json,
                safety_result_json=safety_json,
                is_simulated=packet.is_simulated,
            )
            self._session.add(new_latest)

        self._session.commit()

    def get_latest(
        self,
        farm_id: str,
        pond_id: str,
    ) -> Optional[Tuple[PondTelemetryPacket, Optional[SafetyEvaluationResult]]]:
        record = (
            self._session.query(LatestTelemetryORM)
            .filter(
                LatestTelemetryORM.farm_id == farm_id,
                LatestTelemetryORM.pond_id == pond_id,
            )
            .first()
        )
        if not record:
            return None
        return record.to_domain()

    def get_all_latest(self, farm_id: str) -> Dict[str, PondTelemetryPacket]:
        records = (
            self._session.query(LatestTelemetryORM)
            .filter(LatestTelemetryORM.farm_id == farm_id)
            .all()
        )
        results: Dict[str, PondTelemetryPacket] = {}
        for r in records:
            packet, _ = r.to_domain()
            results[packet.pond_id] = packet
        return results

    def get_all_latest_with_evaluations(
        self, farm_id: str
    ) -> Dict[str, Tuple[PondTelemetryPacket, Optional[SafetyEvaluationResult]]]:
        records = (
            self._session.query(LatestTelemetryORM)
            .filter(LatestTelemetryORM.farm_id == farm_id)
            .all()
        )
        results: Dict[str, Tuple[PondTelemetryPacket, Optional[SafetyEvaluationResult]]] = {}
        for r in records:
            packet, evaluation = r.to_domain()
            results[packet.pond_id] = (packet, evaluation)
        return results

    def get_history(
        self,
        farm_id: str,
        pond_id: str,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        limit: int = 100,
    ) -> List[PondTelemetryPacket]:
        query = (
            self._session.query(TelemetryORM)
            .filter(
                TelemetryORM.farm_id == farm_id,
                TelemetryORM.pond_id == pond_id,
            )
        )
        if start_time:
            query = query.filter(TelemetryORM.timestamp >= start_time)
        if end_time:
            query = query.filter(TelemetryORM.timestamp <= end_time)

        records = query.order_by(TelemetryORM.timestamp.asc()).limit(limit).all()
        return [r.to_domain() for r in records]

    def total_ingested_count(self) -> int:
        return self._session.query(TelemetryORM).count()
