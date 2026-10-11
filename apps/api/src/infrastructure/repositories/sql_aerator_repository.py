"""SQL repository for aerator units and safe dry-run aeration decisions."""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from apps.api.src.domain.hardware_interfaces import (
    AerationDecisionResult,
    AeratorStatus,
    DesiredEquipmentState,
    PhysicalRunningState,
)
from apps.api.src.infrastructure.models import AeratorDecisionORM, AeratorUnitORM


class SQLAeratorRepository:
    """SQL storage for aerator units, power feedback, and advisory decisions."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def get(self, aerator_id: str) -> Optional[AeratorStatus]:
        orm = (
            self._session.query(AeratorUnitORM)
            .filter(AeratorUnitORM.aerator_id == aerator_id)
            .first()
        )
        return self._to_domain(orm) if orm else None

    def list_by_pond(self, pond_id: str) -> List[AeratorStatus]:
        orms = (
            self._session.query(AeratorUnitORM)
            .filter(AeratorUnitORM.pond_id == pond_id)
            .order_by(AeratorUnitORM.aerator_id)
            .all()
        )
        return [self._to_domain(o) for o in orms]

    def list_by_transformer(self, transformer_id: str) -> List[AeratorStatus]:
        orms = (
            self._session.query(AeratorUnitORM)
            .filter(AeratorUnitORM.transformer_id == transformer_id)
            .order_by(AeratorUnitORM.aerator_id)
            .all()
        )
        return [self._to_domain(o) for o in orms]

    def save(self, aerator: AeratorStatus) -> AeratorStatus:
        existing = (
            self._session.query(AeratorUnitORM)
            .filter(AeratorUnitORM.aerator_id == aerator.aerator_id)
            .first()
        )
        now = datetime.now(timezone.utc)
        if existing:
            existing.desired_state = aerator.desired_state.value
            existing.verified_physical_state = aerator.verified_physical_state.value
            existing.current_draw_amps = aerator.current_draw_amps
            existing.power_kw = aerator.power_kw
            existing.runtime_minutes_today = aerator.runtime_minutes_today
            existing.last_state_change = aerator.last_state_change or now
            existing.fault_reason = aerator.fault_reason
            existing.updated_at = now
        else:
            orm = AeratorUnitORM(
                farm_id=getattr(aerator, "farm_id", None) or "farm-alpha",
                aerator_id=aerator.aerator_id,
                name=f"Paddlewheel {aerator.aerator_id}",
                pond_id=aerator.pond_id,
                rating_kw=aerator.rating_kw,
                transformer_id=aerator.transformer_id,
                desired_state=aerator.desired_state.value,
                verified_physical_state=aerator.verified_physical_state.value,
                current_draw_amps=aerator.current_draw_amps,
                power_kw=aerator.power_kw,
                runtime_minutes_today=aerator.runtime_minutes_today,
                last_state_change=aerator.last_state_change or now,
                fault_reason=aerator.fault_reason,
            )
            self._session.add(orm)

        self._session.commit()
        return aerator

    def log_decision(self, decision: AerationDecisionResult) -> None:
        """Persist a dry-run aeration decision audit entry."""
        orm = AeratorDecisionORM(
            decision_id=decision.decision_id,
            farm_id=decision.farm_id,
            pond_id=decision.pond_id,
            timestamp=decision.timestamp,
            do_value=decision.do_value_mg_l,
            proposed_action=decision.proposed_action,
            reason=decision.reason,
            interlocks_ok=decision.interlocks_ok,
            execution_mode=decision.execution_mode,
            operator_id=decision.operator_id,
        )
        self._session.add(orm)
        self._session.commit()

    def list_recent_decisions(self, pond_id: str, limit: int = 20) -> List[AerationDecisionResult]:
        orms = (
            self._session.query(AeratorDecisionORM)
            .filter(AeratorDecisionORM.pond_id == pond_id)
            .order_by(AeratorDecisionORM.timestamp.desc())
            .limit(limit)
            .all()
        )
        return [
            AerationDecisionResult(
                decision_id=o.decision_id,
                farm_id=o.farm_id,
                pond_id=o.pond_id,
                timestamp=o.timestamp,
                do_value_mg_l=o.do_value,
                do_sensor_healthy=True,
                proposed_action=o.proposed_action,
                reason=o.reason,
                interlocks_ok=o.interlocks_ok,
                transformer_headroom_kw=15.0,
                execution_mode=o.execution_mode,
                operator_id=o.operator_id,
            )
            for o in orms
        ]

    def log_runtime_entry(
        self,
        farm_id: str,
        pond_id: str,
        aerator_id: str,
        start_time: datetime,
        end_time: Optional[datetime],
        duration_minutes: float,
        energy_kwh: float,
        trigger_reason: str = "Automated DO Advisory",
        is_simulated: bool = True,
    ) -> None:
        """Record an operational run interval for an aerator."""
        import uuid
        from apps.api.src.infrastructure.models import AeratorRuntimeLogORM
        
        log_id = f"run-{uuid.uuid4().hex[:10]}"
        orm = AeratorRuntimeLogORM(
            log_id=log_id,
            farm_id=farm_id,
            pond_id=pond_id,
            aerator_id=aerator_id,
            start_time=start_time,
            end_time=end_time,
            duration_minutes=round(duration_minutes, 1),
            energy_kwh=round(energy_kwh, 2),
            trigger_reason=trigger_reason,
            is_simulated=is_simulated,
        )
        self._session.add(orm)
        self._session.commit()

    def list_runtime_history(self, pond_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """List historical operational runtime logs for all aerators in a pond."""
        from apps.api.src.infrastructure.models import AeratorRuntimeLogORM
        
        orms = (
            self._session.query(AeratorRuntimeLogORM)
            .filter(AeratorRuntimeLogORM.pond_id == pond_id)
            .order_by(AeratorRuntimeLogORM.start_time.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                "log_id": o.log_id,
                "farm_id": o.farm_id,
                "pond_id": o.pond_id,
                "aerator_id": o.aerator_id,
                "start_time": o.start_time.isoformat() if o.start_time else None,
                "end_time": o.end_time.isoformat() if o.end_time else None,
                "duration_minutes": o.duration_minutes,
                "energy_kwh": o.energy_kwh,
                "trigger_reason": o.trigger_reason,
                "is_simulated": bool(o.is_simulated),
            }
            for o in orms
        ]

    def get_daily_runtime_summary(self, pond_id: str) -> Dict[str, Any]:
        """Compute aggregated daily runtime summary across all aerators in a pond."""
        from apps.api.src.infrastructure.models import AeratorRuntimeLogORM
        from sqlalchemy import func
        
        now = datetime.now(timezone.utc)
        today_start = datetime(now.year, now.month, now.day, tzinfo=timezone.utc)
        
        aerators = self.list_by_pond(pond_id)
        total_runtime_today = sum(a.runtime_minutes_today for a in aerators)
        total_power_kw = sum(a.power_kw for a in aerators)
        running_count = sum(1 for a in aerators if a.verified_physical_state == PhysicalRunningState.RUNNING)

        # Historical log aggregation for today
        res = (
            self._session.query(
                func.sum(AeratorRuntimeLogORM.duration_minutes),
                func.sum(AeratorRuntimeLogORM.energy_kwh),
            )
            .filter(
                AeratorRuntimeLogORM.pond_id == pond_id,
                AeratorRuntimeLogORM.start_time >= today_start,
            )
            .first()
        )
        log_duration = float(res[0] or 0.0) if res else 0.0
        log_kwh = float(res[1] or 0.0) if res else 0.0

        # Combine unit runtime meters and logged sessions
        effective_runtime_min = max(total_runtime_today, log_duration)
        effective_energy_kwh = round(log_kwh if log_kwh > 0 else (effective_runtime_min / 60.0) * 1.5 * max(1, running_count), 2)

        return {
            "pond_id": pond_id,
            "total_aerators": len(aerators),
            "running_aerators": running_count,
            "total_power_kw": round(total_power_kw, 2),
            "runtime_minutes_today": round(effective_runtime_min, 1),
            "runtime_hours_today": round(effective_runtime_min / 60.0, 2),
            "energy_kwh_today": effective_energy_kwh,
            "aerator_units": [
                {
                    "aerator_id": a.aerator_id,
                    "rating_kw": a.rating_kw,
                    "transformer_id": a.transformer_id,
                    "desired_state": a.desired_state.value,
                    "verified_physical_state": a.verified_physical_state.value,
                    "current_draw_amps": round(a.current_draw_amps, 1),
                    "power_kw": round(a.power_kw, 2),
                    "runtime_minutes_today": round(a.runtime_minutes_today, 1),
                    "fault_reason": a.fault_reason,
                }
                for a in aerators
            ],
        }

    def seed_defaults_for_pond(self, pond_id: str, transformer_id: str, count: int = 2) -> None:
        """Seed default 1.5 kW paddlewheel aerators for a pond."""
        existing = self.list_by_pond(pond_id)
        if existing:
            return

        for i in range(1, count + 1):
            aerator = AeratorStatus(
                aerator_id=f"{pond_id}-aero-{i:02d}",
                pond_id=pond_id,
                transformer_id=transformer_id,
                rating_kw=1.5,
                desired_state=DesiredEquipmentState.AUTO,
                verified_physical_state=PhysicalRunningState.STOPPED,
                current_draw_amps=0.0,
                power_kw=0.0,
                runtime_minutes_today=180.0,  # 3 hrs simulated initial baseline
                fault_reason=None,
            )
            self.save(aerator)

    def _to_domain(self, orm: AeratorUnitORM) -> AeratorStatus:
        return AeratorStatus(
            aerator_id=orm.aerator_id,
            pond_id=orm.pond_id,
            transformer_id=orm.transformer_id,
            rating_kw=orm.rating_kw,
            desired_state=DesiredEquipmentState(orm.desired_state),
            verified_physical_state=PhysicalRunningState(orm.verified_physical_state),
            current_draw_amps=orm.current_draw_amps or 0.0,
            power_kw=orm.power_kw or 0.0,
            runtime_minutes_today=orm.runtime_minutes_today or 0.0,
            last_state_change=orm.last_state_change,
            fault_reason=orm.fault_reason,
        )

