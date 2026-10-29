"""Pond Monitoring Service.

Orchestrates pond-specific monitoring:
- Hardware sensor registry & calibration
- Aerator status (desired command vs verified physical feedback)
- Advisory dry-run aeration evaluation with anti-cycling hysteresis
- Alert lifecycle (ACTIVE, ACKNOWLEDGED, RESOLVED)
- Stocking batch & biomass estimation (DOC, survival, ABW)
- Manual feeding logs and feed tray consumption observations
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from apps.api.src.domain.aeration_engine import AerationDecisionEngine
from apps.api.src.domain.hardware_interfaces import (
    AerationDecisionResult,
    AeratorStatus,
    PhysicalRunningState,
    SensorMetadata,
)
from apps.api.src.infrastructure.repositories.sql_aerator_repository import SQLAeratorRepository
from apps.api.src.infrastructure.repositories.sql_alert_repository import SQLAlertRepository
from apps.api.src.infrastructure.repositories.sql_pond_records_repository import SQLPondRecordsRepository
from apps.api.src.infrastructure.repositories.sql_pond_repository import SQLPondRepository
from apps.api.src.infrastructure.repositories.sql_sensor_repository import SQLSensorRepository
from apps.api.src.infrastructure.repositories.sql_telemetry_repository import SQLTelemetryRepository
from apps.api.src.services.power_service import PowerMonitoringService
from packages.telemetry_schema.models import MetricType, SeverityLevel


class PondMonitoringService:
    """Coordinates pond telemetry, hardware abstraction, safety state machine, and logs."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._pond_repo = SQLPondRepository(session)
        self._telemetry_repo = SQLTelemetryRepository(session)
        self._sensor_repo = SQLSensorRepository(session)
        self._aerator_repo = SQLAeratorRepository(session)
        self._alert_repo = SQLAlertRepository(session)
        self._records_repo = SQLPondRecordsRepository(session)
        self._power_service = PowerMonitoringService(session)
        self._aeration_engine = AerationDecisionEngine()

    def get_pond_detail(self, farm_id: str, pond_id: str) -> Optional[Dict[str, Any]]:
        """Fetch comprehensive pond monitoring data."""
        pond_config = self._pond_repo.get(farm_id, pond_id)
        if not pond_config:
            return None

        # 1. Latest Telemetry
        latest_packet, safety_eval = self._telemetry_repo.get_latest(farm_id, pond_id) or (None, None)
        telemetry_dict = latest_packet.model_dump(mode="json") if latest_packet else None
        safety_dict = safety_eval.model_dump(mode="json") if safety_eval else None

        # 2. Sensors Registry
        sensors = self._sensor_repo.list_by_pond(farm_id, pond_id)
        if not sensors:
            self._sensor_repo.seed_defaults_for_pond(farm_id, pond_id)
            sensors = self._sensor_repo.list_by_pond(farm_id, pond_id)

        # 3. Aerators Status
        aerators = self._aerator_repo.list_by_pond(pond_id)
        if not aerators:
            self._aerator_repo.seed_defaults_for_pond(
                pond_id, transformer_id=pond_config.transformer_id, count=pond_config.aerator_count
            )
            aerators = self._aerator_repo.list_by_pond(pond_id)

        # 4. Dry-run Aeration Decision
        latest_do = None
        now = datetime.now(timezone.utc)
        freshness_sec = None
        is_simulated = True
        if latest_packet and MetricType.DISSOLVED_OXYGEN in latest_packet.metrics:
            latest_do = latest_packet.metrics[MetricType.DISSOLVED_OXYGEN].value
            ts = latest_packet.timestamp if latest_packet.timestamp.tzinfo else latest_packet.timestamp.replace(tzinfo=timezone.utc)
            freshness_sec = max(0.0, (now - ts).total_seconds())
            is_simulated = bool(latest_packet.is_simulated)

        # Sensor health check: true if recent reading (< 60s)
        sensor_healthy = (latest_do is not None) and (freshness_sec is not None and freshness_sec <= 60.0)

        tx_status = self._power_service.get_transformer_status(farm_id, pond_config.transformer_id)
        decision = self._aeration_engine.evaluate_pond(
            farm_id=farm_id,
            pond_id=pond_id,
            current_do_mg_l=latest_do,
            sensor_healthy=sensor_healthy,
            pond_config=pond_config,
            aerators=aerators,
            transformer_status=tx_status,
            sensor_freshness_seconds=freshness_sec,
            is_simulated=is_simulated,
        )

        # 4b. Aerator Runtime History and Daily Summary
        runtime_summary = self._aerator_repo.get_daily_runtime_summary(pond_id)
        runtime_history = self._aerator_repo.list_runtime_history(pond_id, limit=30)
        recent_decisions = [d.model_dump(mode="json") for d in self._aerator_repo.list_recent_decisions(pond_id, limit=20)]

        # 5. Stocking Batch & Biomass
        stocking = self._records_repo.get_active_batch(pond_id)
        if not stocking:
            self._records_repo.seed_default_stocking_for_pond(
                farm_id,
                pond_id,
                initial_count=pond_config.stocking_count,
                doc=pond_config.days_of_culture,
            )
            stocking = self._records_repo.get_active_batch(pond_id)

        # 6. Production Intelligence, Growth Samples & FCR
        prod_intel = self._records_repo.get_pond_production_summary(farm_id, pond_id)

        # 7. Manual Feeding Logs
        feeding_logs = self._records_repo.list_feeding_logs(farm_id, pond_id, limit=20)

        # 8. Active Alerts
        active_alerts = self._alert_repo.get_active_alerts(farm_id, pond_id)

        return {
            "config": pond_config.model_dump(mode="json"),
            "telemetry": telemetry_dict,
            "safety_evaluation": safety_dict,
            "sensors": [s.model_dump(mode="json") for s in sensors],
            "aerators": [a.model_dump(mode="json") for a in aerators],
            "aeration_decision": decision.model_dump(mode="json"),
            "aeration_runtime_summary": runtime_summary,
            "aeration_runtime_history": runtime_history,
            "aeration_decision_history": recent_decisions,
            "stocking": stocking,
            "production_intelligence": prod_intel,
            "feeding_logs": feeding_logs,
            "active_alerts": active_alerts,
            "transformer_status": tx_status.model_dump(mode="json"),
        }

    def evaluate_aeration_dry_run(
        self, farm_id: str, pond_id: str, operator_id: Optional[str] = None
    ) -> AerationDecisionResult:
        """Run safe dry-run aeration decision engine and persist log."""
        pond_config = self._pond_repo.get(farm_id, pond_id)
        latest_packet, _ = self._telemetry_repo.get_latest(farm_id, pond_id) or (None, None)
        latest_do = (
            latest_packet.metrics[MetricType.DISSOLVED_OXYGEN].value
            if latest_packet and MetricType.DISSOLVED_OXYGEN in latest_packet.metrics
            else None
        )
        now = datetime.now(timezone.utc)
        freshness_sec = None
        is_simulated = True
        if latest_packet:
            ts = latest_packet.timestamp if latest_packet.timestamp.tzinfo else latest_packet.timestamp.replace(tzinfo=timezone.utc)
            freshness_sec = max(0.0, (now - ts).total_seconds())
            is_simulated = bool(latest_packet.is_simulated)

        sensor_healthy = (latest_do is not None) and (freshness_sec is not None and freshness_sec <= 60.0)
        aerators = self._aerator_repo.list_by_pond(pond_id)
        tx_id = pond_config.transformer_id if pond_config else "tx-1"
        tx_status = self._power_service.get_transformer_status(farm_id, tx_id)

        decision = self._aeration_engine.evaluate_pond(
            farm_id=farm_id,
            pond_id=pond_id,
            current_do_mg_l=latest_do,
            sensor_healthy=sensor_healthy,
            pond_config=pond_config,
            aerators=aerators,
            transformer_status=tx_status,
            operator_id=operator_id,
            sensor_freshness_seconds=freshness_sec,
            is_simulated=is_simulated,
        )

        self._aerator_repo.log_decision(decision)
        return decision

    def log_manual_feeding(
        self,
        farm_id: str,
        pond_id: str,
        feed_kg: float,
        feed_type: str,
        feed_time_label: str,
        tray_observation: str,
        notes: Optional[str],
        recorded_by: str,
        batch_id: Optional[str] = None,
        feeding_event_count: int = 1,
        timestamp: Optional[datetime] = None,
        product_id: Optional[str] = None,
        plan_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record manual feeding entry."""
        return self._records_repo.log_feeding(
            farm_id=farm_id,
            pond_id=pond_id,
            feed_kg=feed_kg,
            feed_type=feed_type,
            feed_time_label=feed_time_label,
            tray_observation=tray_observation,
            notes=notes,
            recorded_by=recorded_by,
            batch_id=batch_id,
            feeding_event_count=feeding_event_count,
            timestamp=timestamp,
            product_id=product_id,
            plan_id=plan_id,
        )

    def update_stocking_batch(self, batch_data: Dict[str, Any]) -> Dict[str, Any]:
        """Update stocking count, survival, or ABW."""
        return self._records_repo.save_batch(batch_data)

    def calibrate_sensor(
        self,
        sensor_id: str,
        calibration_offset: float,
        calibration_slope: float,
    ) -> Optional[SensorMetadata]:
        """Update calibration parameters for a sensor probe."""
        sensor = self._sensor_repo.get(sensor_id)
        if not sensor:
            return None
        from datetime import datetime, timezone
        sensor.calibration_offset = calibration_offset
        sensor.calibration_slope = calibration_slope
        sensor.calibration_date = datetime.now(timezone.utc)
        return self._sensor_repo.register(sensor)

