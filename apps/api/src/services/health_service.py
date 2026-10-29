"""Application service orchestrating health records, observations, water quality context, and treatments."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from apps.api.src.domain.health_engine import (
    calculate_population_metrics,
    evaluate_health_risks,
)
from apps.api.src.infrastructure.models import PondORM, StockingBatchORM
from apps.api.src.infrastructure.repositories.sql_alert_repository import SQLAlertRepository
from apps.api.src.infrastructure.repositories.sql_health_repository import SQLHealthRepository
from apps.api.src.infrastructure.repositories.sql_telemetry_repository import SQLTelemetryRepository
from packages.telemetry_schema.models import MetricType


class HealthService:
    """Coordinates pond health tracking, mortality audits, water telemetry context, and treatments."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._health_repo = SQLHealthRepository(session)
        self._telemetry_repo = SQLTelemetryRepository(session)
        self._alert_repo = SQLAlertRepository(session)

    # -------------------------------------------------------------------------
    # Context Helpers
    # -------------------------------------------------------------------------
    def get_water_quality_snapshot(self, farm_id: str, pond_id: str) -> Dict[str, Any]:
        """Fetch current water quality telemetry snapshot with freshness and provenance."""
        latest_tuple = self._telemetry_repo.get_latest(farm_id, pond_id)
        if latest_tuple and latest_tuple[0]:
            packet = latest_tuple[0]
            now = datetime.now(timezone.utc)
            ts = packet.timestamp if packet.timestamp.tzinfo else packet.timestamp.replace(tzinfo=timezone.utc)
            freshness_sec = max(0, int((now - ts).total_seconds()))
            return {
                "dissolved_oxygen": packet.get_metric_value(MetricType.DISSOLVED_OXYGEN),
                "temperature": packet.get_metric_value(MetricType.TEMPERATURE),
                "ph": packet.get_metric_value(MetricType.PH),
                "salinity": packet.get_metric_value(MetricType.SALINITY),
                "telemetry_timestamp": ts.isoformat(),
                "freshness_seconds": freshness_sec,
                "is_stale": freshness_sec > 120,
                "is_simulated": packet.is_simulated,
                "data_source": "SIMULATED_PROBE" if packet.is_simulated else "PHYSICAL_RS485",
            }

        return {
            "dissolved_oxygen": None,
            "temperature": None,
            "ph": None,
            "salinity": None,
            "telemetry_timestamp": None,
            "freshness_seconds": None,
            "is_stale": True,
            "is_simulated": False,
            "data_source": "NO_TELEMETRY_AVAILABLE",
        }

    # -------------------------------------------------------------------------
    # Mortality Operations
    # -------------------------------------------------------------------------
    def record_mortality(
        self,
        farm_id: str,
        pond_id: str,
        dead_count: int,
        collection_method: str = "Central drain siphon",
        suspected_reason: str = "Unknown",
        doc: Optional[int] = None,
        notes: Optional[str] = None,
        recorded_by: str = "operator",
        recorded_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Record dead shrimp removal, evaluate mortality spike alerts, and update active batch."""
        active_batch = self._health_repo.get_active_batch(farm_id, pond_id)
        batch_id = active_batch.batch_id if active_batch else f"batch-{pond_id}-default"
        batch_doc = getattr(active_batch, "days_of_culture", None) if active_batch else None
        calc_doc = doc if doc is not None else (batch_doc if batch_doc is not None else 30)

        record = self._health_repo.log_mortality(
            farm_id=farm_id,
            pond_id=pond_id,
            batch_id=batch_id,
            dead_count=dead_count,
            doc=calc_doc,
            collection_method=collection_method,
            suspected_reason=suspected_reason,
            recorded_by=recorded_by,
            notes=notes,
            recorded_at=recorded_at,
        )

        # Trigger health risk evaluation
        pop = active_batch.initial_count if active_batch else 150_000
        mort_24h = self._health_repo.get_mortalities_last_24h_count(farm_id, pond_id)
        recent_feeds = self._health_repo.get_recent_feed_responses(farm_id, pond_id, count=3)
        latest_obs = self._health_repo.get_latest_observation(farm_id, pond_id)
        wq = self.get_water_quality_snapshot(farm_id, pond_id)

        alerts = evaluate_health_risks(
            mortalities_24h_count=mort_24h,
            latest_single_mortality=dead_count,
            population=pop,
            recent_feed_responses=recent_feeds,
            latest_observation=latest_obs,
            water_quality=wq,
        )

        raised_alerts = []
        for alert_desc in alerts:
            res = self._alert_repo.raise_or_update(
                farm_id=farm_id,
                pond_id=pond_id,
                alert_code=alert_desc["alert_code"],
                severity=alert_desc["severity"],
                message=alert_desc["message"],
                recommended_action=alert_desc.get("recommended_action"),
            )
            raised_alerts.append(res)

        return {
            "record": record,
            "mortalities_last_24h": mort_24h,
            "raised_alerts": raised_alerts,
        }

    def get_mortality(self, mortality_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve mortality record by ID without farm filtering for authorization checks."""
        return self._health_repo.get_mortality(mortality_id)

    def correct_mortality(
        self,
        farm_id: str,
        mortality_id: str,
        corrected_dead_count: int,
        correction_notes: str,
        corrected_by: str,
    ) -> Optional[Dict[str, Any]]:
        """Audit-logged modification of a past mortality entry."""
        return self._health_repo.correct_mortality(
            farm_id=farm_id,
            mortality_id=mortality_id,
            corrected_dead_count=corrected_dead_count,
            correction_notes=correction_notes,
            corrected_by=corrected_by,
        )

    def list_mortalities(
        self,
        farm_id: str,
        pond_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        return self._health_repo.list_mortalities(farm_id, pond_id, limit=limit)

    # -------------------------------------------------------------------------
    # Health Observations
    # -------------------------------------------------------------------------
    def record_health_observation(
        self,
        farm_id: str,
        pond_id: str,
        sample_count: int = 20,
        observation_method: str = "Feeding tray inspection",
        swimming_activity: str = "NORMAL",
        feed_response: str = "NORMAL",
        shell_body_condition: str = "NORMAL_CLEAN",
        gill_condition: str = "CLEAN_TRANSLUCENT",
        gut_condition: str = "FULL_CONTINUOUS",
        coloration: str = "NORMAL_TRANSLUCENT",
        visible_lesions: str = "NONE",
        severity: str = "NORMAL",
        doc: Optional[int] = None,
        notes: Optional[str] = None,
        photo_reference_url: Optional[str] = None,
        recorded_by: str = "operator",
        recorded_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Record health check with real-time water quality snapshot and evaluate alerts."""
        active_batch = self._health_repo.get_active_batch(farm_id, pond_id)
        batch_id = active_batch.batch_id if active_batch else f"batch-{pond_id}-default"
        batch_doc = getattr(active_batch, "days_of_culture", None) if active_batch else None
        calc_doc = doc if doc is not None else (batch_doc if batch_doc is not None else 30)

        wq_context = self.get_water_quality_snapshot(farm_id, pond_id)

        obs = self._health_repo.log_health_observation(
            farm_id=farm_id,
            pond_id=pond_id,
            batch_id=batch_id,
            doc=calc_doc,
            sample_count=sample_count,
            observation_method=observation_method,
            swimming_activity=swimming_activity,
            feed_response=feed_response,
            shell_body_condition=shell_body_condition,
            gill_condition=gill_condition,
            gut_condition=gut_condition,
            coloration=coloration,
            visible_lesions=visible_lesions,
            severity=severity,
            notes=notes,
            photo_reference_url=photo_reference_url,
            water_quality_context=wq_context,
            recorded_by=recorded_by,
            recorded_at=recorded_at,
        )

        # Risk evaluations
        pop = active_batch.initial_count if active_batch else 150_000
        mort_24h = self._health_repo.get_mortalities_last_24h_count(farm_id, pond_id)
        recent_feeds = self._health_repo.get_recent_feed_responses(farm_id, pond_id, count=3)

        alerts = evaluate_health_risks(
            mortalities_24h_count=mort_24h,
            latest_single_mortality=0,
            population=pop,
            recent_feed_responses=recent_feeds,
            latest_observation=obs,
            water_quality=wq_context,
        )

        raised_alerts = []
        for alert_desc in alerts:
            res = self._alert_repo.raise_or_update(
                farm_id=farm_id,
                pond_id=pond_id,
                alert_code=alert_desc["alert_code"],
                severity=alert_desc["severity"],
                message=alert_desc["message"],
                recommended_action=alert_desc.get("recommended_action"),
            )
            raised_alerts.append(res)

        return {
            "observation": obs,
            "raised_alerts": raised_alerts,
        }

    def list_health_observations(
        self,
        farm_id: str,
        pond_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        return self._health_repo.list_health_observations(farm_id, pond_id, limit=limit)

    # -------------------------------------------------------------------------
    # Treatments
    # -------------------------------------------------------------------------
    def record_treatment(
        self,
        farm_id: str,
        pond_id: str,
        product_name: str,
        dosage_amount: float,
        reason_for_treatment: str,
        dosage_unit: str = "kg/ha",
        active_ingredient: Optional[str] = None,
        withdrawal_period_days: int = 0,
        product_label_info: Optional[str] = None,
        doc: Optional[int] = None,
        notes: Optional[str] = None,
        recorded_by: str = "operator",
        applied_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Record product application with withdrawal restriction enforcement."""
        active_batch = self._health_repo.get_active_batch(farm_id, pond_id)
        batch_id = active_batch.batch_id if active_batch else f"batch-{pond_id}-default"
        calc_doc = doc if doc is not None else (active_batch.current_doc if active_batch else 30)

        return self._health_repo.log_treatment(
            farm_id=farm_id,
            pond_id=pond_id,
            batch_id=batch_id,
            product_name=product_name,
            dosage_amount=dosage_amount,
            reason_for_treatment=reason_for_treatment,
            doc=calc_doc,
            dosage_unit=dosage_unit,
            active_ingredient=active_ingredient,
            withdrawal_period_days=withdrawal_period_days,
            product_label_info=product_label_info,
            notes=notes,
            recorded_by=recorded_by,
            applied_at=applied_at,
        )

    def list_treatments(
        self,
        farm_id: str,
        pond_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        return self._health_repo.list_treatments(farm_id, pond_id, limit=limit)

    # -------------------------------------------------------------------------
    # Pond Health Summary Bundle
    # -------------------------------------------------------------------------
    def get_pond_health_summary(self, farm_id: str, pond_id: str) -> Dict[str, Any]:
        """Comprehensive health status bundle for UI cards and detailed analytics."""
        batch = self._health_repo.get_active_batch(farm_id, pond_id)
        pond = (
            self._session.query(PondORM)
            .filter(PondORM.farm_id == farm_id, PondORM.pond_id == pond_id)
            .first()
        )

        initial_count = batch.initial_count if batch else (getattr(pond, "stocking_count", 150_000) or 150_000)
        cum_mort = getattr(batch, "cumulative_recorded_mortality", 0) if batch else 0
        sampling_survival = getattr(pond, "survival_rate_pct", 85.0) or 85.0

        pop_metrics = calculate_population_metrics(
            initial_count=initial_count,
            cumulative_recorded_mortality=cum_mort or 0,
            sampling_survival_pct=sampling_survival,
        )

        mortalities_24h = self._health_repo.get_mortalities_last_24h_count(farm_id, pond_id)
        recent_mortalities = self._health_repo.list_mortalities(farm_id, pond_id, limit=20)
        recent_observations = self._health_repo.list_health_observations(farm_id, pond_id, limit=20)
        recent_treatments = self._health_repo.list_treatments(farm_id, pond_id, limit=20)
        active_restrictions = self._health_repo.get_active_harvest_restrictions(farm_id, pond_id)
        wq_snapshot = self.get_water_quality_snapshot(farm_id, pond_id)

        # Health status evaluation badge
        if mortalities_24h >= 200:
            health_status = "CRITICAL"
        elif mortalities_24h >= 50 or len(active_restrictions) > 0:
            health_status = "CAUTION"
        elif any(obs.get("severity") in ("MODERATE", "SEVERE") for obs in recent_observations[:3]):
            health_status = "WATCH"
        else:
            health_status = "GOOD"

        return {
            "farm_id": farm_id,
            "pond_id": pond_id,
            "health_status": health_status,
            "active_batch": {
                "batch_id": batch.batch_id if batch else None,
                "species": batch.species if batch else "Litopenaeus vannamei",
                "doc": getattr(batch, "days_of_culture", None) if batch else (getattr(pond, "days_of_culture", 35) or 35),
                "stocking_date": batch.stocking_date.isoformat() if batch and batch.stocking_date else None,
            },
            "population_metrics": pop_metrics,
            "mortalities_last_24h": mortalities_24h,
            "recent_mortalities": recent_mortalities,
            "recent_observations": recent_observations,
            "recent_treatments": recent_treatments,
            "active_harvest_restrictions": active_restrictions,
            "is_harvest_blocked": len(active_restrictions) > 0,
            "water_quality_snapshot": wq_snapshot,
        }

