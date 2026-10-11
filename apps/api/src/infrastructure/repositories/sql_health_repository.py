"""SQL repository for shrimp pond mortality, health observations, and treatment records."""

from datetime import datetime, timedelta, timezone
import json
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from apps.api.src.domain.health_engine import calculate_withdrawal_status
from apps.api.src.infrastructure.models import (
    HealthObservationORM,
    MortalityRecordORM,
    StockingBatchORM,
    TreatmentRecordORM,
)


class SQLHealthRepository:
    """Repository handling persistence for mortality, health checks, and treatments."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # -------------------------------------------------------------------------
    # Batch helper
    # -------------------------------------------------------------------------
    def get_active_batch(self, farm_id: str, pond_id: str) -> Optional[StockingBatchORM]:
        """Fetch the current ACTIVE stocking batch for a pond."""
        return (
            self._session.query(StockingBatchORM)
            .filter(
                StockingBatchORM.farm_id == farm_id,
                StockingBatchORM.pond_id == pond_id,
                StockingBatchORM.status == "ACTIVE",
            )
            .first()
        )

    # -------------------------------------------------------------------------
    # Mortality Records
    # -------------------------------------------------------------------------
    def log_mortality(
        self,
        farm_id: str,
        pond_id: str,
        batch_id: str,
        dead_count: int,
        doc: int,
        collection_method: str = "Central drain siphon",
        suspected_reason: str = "Unknown",
        recorded_by: str = "operator",
        notes: Optional[str] = None,
        recorded_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Record physical dead shrimp collection and update batch cumulative mortality."""
        ts = recorded_at or datetime.now(timezone.utc)
        record_id = f"mor-{uuid.uuid4().hex[:10]}"

        orm = MortalityRecordORM(
            mortality_id=record_id,
            farm_id=farm_id,
            pond_id=pond_id,
            batch_id=batch_id,
            timestamp=ts,
            doc=max(0, doc),
            dead_count=max(0, dead_count),
            collection_method=collection_method,
            suspected_reason=suspected_reason,
            notes=notes,
            recorded_by=recorded_by,
            is_corrected=False,
        )
        self._session.add(orm)

        # Update cumulative mortality on active batch
        batch = (
            self._session.query(StockingBatchORM)
            .filter(
                StockingBatchORM.farm_id == farm_id,
                StockingBatchORM.batch_id == batch_id,
            )
            .first()
        )
        if batch:
            current_cum = getattr(batch, "cumulative_recorded_mortality", 0) or 0
            batch.cumulative_recorded_mortality = current_cum + max(0, dead_count)

        self._session.commit()
        return self._mortality_to_dict(orm)

    def list_mortalities(
        self,
        farm_id: str,
        pond_id: str,
        batch_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List mortality records for a pond sorted by newest first."""
        query = (
            self._session.query(MortalityRecordORM)
            .filter(
                MortalityRecordORM.farm_id == farm_id,
                MortalityRecordORM.pond_id == pond_id,
            )
        )
        if batch_id:
            query = query.filter(MortalityRecordORM.batch_id == batch_id)
        records = query.order_by(MortalityRecordORM.timestamp.desc()).limit(limit).all()
        return [self._mortality_to_dict(r) for r in records]

    def correct_mortality(
        self,
        farm_id: str,
        mortality_id: str,
        corrected_dead_count: int,
        correction_notes: str,
        corrected_by: str,
    ) -> Optional[Dict[str, Any]]:
        """Audit-compliant correction for an inaccurate dead count entry."""
        rec = (
            self._session.query(MortalityRecordORM)
            .filter(
                MortalityRecordORM.farm_id == farm_id,
                MortalityRecordORM.mortality_id == mortality_id,
            )
            .first()
        )
        if not rec:
            return None

        old_count = rec.dead_count
        new_count = max(0, corrected_dead_count)
        diff = new_count - old_count

        rec.dead_count = new_count
        rec.is_corrected = True
        audit_note = f"[Corrected by {corrected_by}]: {correction_notes}"
        rec.correction_notes = (
            f"{rec.correction_notes}\n{audit_note}" if rec.correction_notes else audit_note
        )

        # Update batch cumulative
        batch = (
            self._session.query(StockingBatchORM)
            .filter(
                StockingBatchORM.farm_id == farm_id,
                StockingBatchORM.batch_id == rec.batch_id,
            )
            .first()
        )
        if batch:
            current_cum = getattr(batch, "cumulative_recorded_mortality", 0) or 0
            batch.cumulative_recorded_mortality = max(0, current_cum + diff)

        self._session.commit()
        return self._mortality_to_dict(rec)

    def get_mortalities_last_24h_count(self, farm_id: str, pond_id: str) -> int:
        """Calculate total dead shrimp retrieved in the last 24 hours."""
        since = datetime.now(timezone.utc) - timedelta(hours=24)
        records = (
            self._session.query(MortalityRecordORM)
            .filter(
                MortalityRecordORM.farm_id == farm_id,
                MortalityRecordORM.pond_id == pond_id,
                MortalityRecordORM.timestamp >= since,
            )
            .all()
        )
        return sum(r.dead_count for r in records)

    def _mortality_to_dict(self, orm: MortalityRecordORM) -> Dict[str, Any]:
        return {
            "mortality_id": orm.mortality_id,
            "farm_id": orm.farm_id,
            "pond_id": orm.pond_id,
            "batch_id": orm.batch_id,
            "timestamp": orm.timestamp.isoformat() if orm.timestamp else None,
            "doc": orm.doc,
            "dead_count": orm.dead_count,
            "collection_method": orm.collection_method,
            "suspected_reason": orm.suspected_reason,
            "notes": orm.notes,
            "recorded_by": orm.recorded_by,
            "is_corrected": orm.is_corrected,
            "correction_notes": orm.correction_notes,
        }

    # -------------------------------------------------------------------------
    # Health Observations
    # -------------------------------------------------------------------------
    def log_health_observation(
        self,
        farm_id: str,
        pond_id: str,
        batch_id: str,
        doc: int,
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
        notes: Optional[str] = None,
        photo_reference_url: Optional[str] = None,
        water_quality_context: Optional[Dict[str, Any]] = None,
        recorded_by: str = "operator",
        recorded_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Record observational physical signs with timestamped water quality context."""
        ts = recorded_at or datetime.now(timezone.utc)
        obs_id = f"obs-{uuid.uuid4().hex[:10]}"

        wq_json = json.dumps(water_quality_context) if water_quality_context else None

        orm = HealthObservationORM(
            observation_id=obs_id,
            farm_id=farm_id,
            pond_id=pond_id,
            batch_id=batch_id,
            timestamp=ts,
            doc=max(0, doc),
            sample_count=max(1, sample_count),
            observation_method=observation_method,
            swimming_activity=swimming_activity,
            feed_response=feed_response,
            shell_body_condition=shell_body_condition,
            gill_condition=gill_condition,
            gut_condition=gut_condition,
            coloration=coloration,
            visible_lesions=visible_lesions,
            severity=severity,
            water_quality_context_json=wq_json,
            photo_reference_url=photo_reference_url,
            notes=notes,
            recorded_by=recorded_by,
        )
        self._session.add(orm)
        self._session.commit()
        return self._observation_to_dict(orm)

    def list_health_observations(
        self,
        farm_id: str,
        pond_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List health observation records for a pond sorted by newest first."""
        records = (
            self._session.query(HealthObservationORM)
            .filter(
                HealthObservationORM.farm_id == farm_id,
                HealthObservationORM.pond_id == pond_id,
            )
            .order_by(HealthObservationORM.timestamp.desc())
            .limit(limit)
            .all()
        )
        return [self._observation_to_dict(r) for r in records]

    def get_latest_observation(self, farm_id: str, pond_id: str) -> Optional[Dict[str, Any]]:
        """Return the most recent health observation."""
        rec = (
            self._session.query(HealthObservationORM)
            .filter(
                HealthObservationORM.farm_id == farm_id,
                HealthObservationORM.pond_id == pond_id,
            )
            .order_by(HealthObservationORM.timestamp.desc())
            .first()
        )
        return self._observation_to_dict(rec) if rec else None

    def get_recent_feed_responses(self, farm_id: str, pond_id: str, count: int = 5) -> List[str]:
        """Return the sequence of feed responses from recent observations."""
        records = (
            self._session.query(HealthObservationORM.feed_response)
            .filter(
                HealthObservationORM.farm_id == farm_id,
                HealthObservationORM.pond_id == pond_id,
            )
            .order_by(HealthObservationORM.timestamp.desc())
            .limit(count)
            .all()
        )
        return [r[0] for r in records]

    def _observation_to_dict(self, orm: HealthObservationORM) -> Dict[str, Any]:
        wq = None
        if orm.water_quality_context_json:
            try:
                wq = json.loads(orm.water_quality_context_json)
            except Exception:
                pass

        return {
            "observation_id": orm.observation_id,
            "farm_id": orm.farm_id,
            "pond_id": orm.pond_id,
            "batch_id": orm.batch_id,
            "timestamp": orm.timestamp.isoformat() if orm.timestamp else None,
            "doc": orm.doc,
            "sample_count": orm.sample_count,
            "observation_method": orm.observation_method,
            "swimming_activity": orm.swimming_activity,
            "feed_response": orm.feed_response,
            "shell_body_condition": orm.shell_body_condition,
            "gill_condition": orm.gill_condition,
            "gut_condition": orm.gut_condition,
            "coloration": orm.coloration,
            "visible_lesions": orm.visible_lesions,
            "severity": orm.severity,
            "water_quality_context": wq,
            "photo_reference_url": orm.photo_reference_url,
            "notes": orm.notes,
            "recorded_by": orm.recorded_by,
        }

    # -------------------------------------------------------------------------
    # Treatment & Chemical Records
    # -------------------------------------------------------------------------
    def log_treatment(
        self,
        farm_id: str,
        pond_id: str,
        batch_id: str,
        product_name: str,
        dosage_amount: float,
        reason_for_treatment: str,
        doc: int,
        dosage_unit: str = "kg/ha",
        active_ingredient: Optional[str] = None,
        withdrawal_period_days: int = 0,
        product_label_info: Optional[str] = None,
        notes: Optional[str] = None,
        recorded_by: str = "operator",
        applied_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Record product/chemical application and calculate harvest restriction window."""
        ts = applied_at or datetime.now(timezone.utc)
        treat_id = f"trt-{uuid.uuid4().hex[:10]}"

        withdrawal_status = calculate_withdrawal_status(
            application_time=ts,
            withdrawal_period_days=withdrawal_period_days,
        )
        restriction_until = withdrawal_status["harvest_restriction_until"] if withdrawal_period_days > 0 else None

        # Flag missing label info if critical label documentation is absent
        has_missing_label = bool(
            not product_label_info
            or not product_label_info.strip()
            or not active_ingredient
            or not active_ingredient.strip()
        )

        orm = TreatmentRecordORM(
            treatment_id=treat_id,
            farm_id=farm_id,
            pond_id=pond_id,
            batch_id=batch_id,
            timestamp=ts,
            doc=max(0, doc),
            product_name=product_name.strip(),
            active_ingredient=active_ingredient.strip() if active_ingredient else None,
            reason_for_treatment=reason_for_treatment.strip(),
            dosage_amount=max(0.0, float(dosage_amount)),
            dosage_unit=dosage_unit.strip(),
            withdrawal_period_days=max(0, int(withdrawal_period_days)),
            harvest_restriction_until=restriction_until,
            product_label_info=product_label_info.strip() if product_label_info else None,
            has_missing_label_info=has_missing_label,
            notes=notes,
            recorded_by=recorded_by,
        )
        self._session.add(orm)
        self._session.commit()
        return self._treatment_to_dict(orm)

    def list_treatments(
        self,
        farm_id: str,
        pond_id: str,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List treatment records for a pond sorted by newest first."""
        records = (
            self._session.query(TreatmentRecordORM)
            .filter(
                TreatmentRecordORM.farm_id == farm_id,
                TreatmentRecordORM.pond_id == pond_id,
            )
            .order_by(TreatmentRecordORM.timestamp.desc())
            .limit(limit)
            .all()
        )
        return [self._treatment_to_dict(r) for r in records]

    def get_active_harvest_restrictions(
        self,
        farm_id: str,
        pond_id: str,
    ) -> List[Dict[str, Any]]:
        """Return any treatments whose withdrawal period is currently active."""
        now = datetime.now(timezone.utc)
        records = (
            self._session.query(TreatmentRecordORM)
            .filter(
                TreatmentRecordORM.farm_id == farm_id,
                TreatmentRecordORM.pond_id == pond_id,
                TreatmentRecordORM.harvest_restriction_until > now,
            )
            .order_by(TreatmentRecordORM.harvest_restriction_until.desc())
            .all()
        )
        return [self._treatment_to_dict(r) for r in records]

    def _treatment_to_dict(self, orm: TreatmentRecordORM) -> Dict[str, Any]:
        now = datetime.now(timezone.utc)
        withdrawal_info = calculate_withdrawal_status(
            application_time=orm.timestamp,
            withdrawal_period_days=orm.withdrawal_period_days,
            current_time=now,
        )

        return {
            "treatment_id": orm.treatment_id,
            "farm_id": orm.farm_id,
            "pond_id": orm.pond_id,
            "batch_id": orm.batch_id,
            "timestamp": orm.timestamp.isoformat() if orm.timestamp else None,
            "doc": orm.doc,
            "product_name": orm.product_name,
            "active_ingredient": orm.active_ingredient,
            "reason_for_treatment": orm.reason_for_treatment,
            "dosage_amount": orm.dosage_amount,
            "dosage_unit": orm.dosage_unit,
            "withdrawal_period_days": orm.withdrawal_period_days,
            "harvest_restriction_until": (
                orm.harvest_restriction_until.isoformat()
                if orm.harvest_restriction_until
                else None
            ),
            "is_harvest_restricted": withdrawal_info["is_harvest_restricted"],
            "remaining_restriction_days": withdrawal_info["remaining_restriction_days"],
            "remaining_restriction_hours": withdrawal_info["remaining_restriction_hours"],
            "product_label_info": orm.product_label_info,
            "has_missing_label_info": orm.has_missing_label_info,
            "notes": orm.notes,
            "recorded_by": orm.recorded_by,
        }

