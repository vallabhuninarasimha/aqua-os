"""SQL repository for water management: pumps, pond outlets, and exchange logs."""

from datetime import datetime, timezone
import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from apps.api.src.domain.water_interfaces import (
    GateState,
    PondOutletStatus,
    PumpOperationalState,
    WaterManagementMode,
    WaterPumpInfo,
)
from apps.api.src.infrastructure.models import (
    PondORM,
    WaterExchangeLogORM,
    WaterPumpORM,
)


class SQLWaterRepository:
    """Repository handling persistence for farm pumps, outlets, and exchange logs."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # -------------------------------------------------------------------------
    # Pump Operations
    # -------------------------------------------------------------------------
    def get_pump(self, farm_id: str, pump_id: str = "pump-river-intake-01") -> Optional[Dict[str, Any]]:
        """Fetch intake pump details."""
        orm = (
            self._session.query(WaterPumpORM)
            .filter(WaterPumpORM.farm_id == farm_id, WaterPumpORM.pump_id == pump_id)
            .first()
        )
        return self._pump_to_dict(orm) if orm else None

    def list_pumps(self, farm_id: str) -> List[Dict[str, Any]]:
        """List all pumps belonging to a farm."""
        pumps = (
            self._session.query(WaterPumpORM)
            .filter(WaterPumpORM.farm_id == farm_id)
            .all()
        )
        return [self._pump_to_dict(p) for p in pumps]

    def update_pump_config(
        self,
        farm_id: str,
        pump_id: str,
        transformer_id: str,
        motor_hp: Optional[float] = None,
        rating_kw: Optional[float] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update configurable pump specs and electrical transformer assignment."""
        orm = (
            self._session.query(WaterPumpORM)
            .filter(WaterPumpORM.farm_id == farm_id, WaterPumpORM.pump_id == pump_id)
            .first()
        )
        if not orm:
            return None
        orm.transformer_id = transformer_id
        if motor_hp is not None:
            orm.motor_hp = motor_hp
        if rating_kw is not None:
            orm.rating_kw = rating_kw
        self._session.commit()
        return self._pump_to_dict(orm)

    def update_pump_state(
        self,
        farm_id: str,
        pump_id: str,
        desired_state: str,
        physical_state: str,
        current_draw_amps: float = 0.0,
        power_kw: float = 0.0,
    ) -> Optional[Dict[str, Any]]:
        """Update running electrical measurements and desired command state."""
        orm = (
            self._session.query(WaterPumpORM)
            .filter(WaterPumpORM.farm_id == farm_id, WaterPumpORM.pump_id == pump_id)
            .first()
        )
        if not orm:
            return None
        orm.desired_state = desired_state
        orm.physical_state = physical_state
        orm.current_draw_amps = current_draw_amps
        orm.power_kw = power_kw
        if physical_state == PumpOperationalState.RUNNING.value:
            orm.last_run_timestamp = datetime.now(timezone.utc)
        self._session.commit()
        return self._pump_to_dict(orm)

    # -------------------------------------------------------------------------
    # Pond Outlets & Level Targets
    # -------------------------------------------------------------------------
    def get_pond_outlet_status(self, farm_id: str, pond_id: str) -> Optional[Dict[str, Any]]:
        """Get dual outlet positions, lock status, and level targets for a pond."""
        pond = (
            self._session.query(PondORM)
            .filter(PondORM.farm_id == farm_id, PondORM.pond_id == pond_id)
            .first()
        )
        if not pond:
            return None
        return self._outlet_to_dict(pond)

    def list_pond_outlet_statuses(self, farm_id: str) -> List[Dict[str, Any]]:
        """List outlet statuses across all configured ponds."""
        ponds = (
            self._session.query(PondORM)
            .filter(PondORM.farm_id == farm_id)
            .order_by(PondORM.pond_id.asc())
            .all()
        )
        return [self._outlet_to_dict(p) for p in ponds]

    def update_pond_outlet_state(
        self,
        farm_id: str,
        pond_id: str,
        normal_outlet_state: Optional[str] = None,
        full_drain_outlet_state: Optional[str] = None,
        full_drain_locked: Optional[bool] = None,
        drain_lock_reason: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Update mechanical outlet gates and lock state."""
        pond = (
            self._session.query(PondORM)
            .filter(PondORM.farm_id == farm_id, PondORM.pond_id == pond_id)
            .first()
        )
        if not pond:
            return None

        if normal_outlet_state is not None:
            pond.normal_outlet_state = normal_outlet_state
        if full_drain_outlet_state is not None:
            pond.full_drain_outlet_state = full_drain_outlet_state
        if full_drain_locked is not None:
            pond.full_drain_locked = full_drain_locked
        if drain_lock_reason is not None:
            pond.drain_lock_reason = drain_lock_reason

        self._session.commit()
        return self._outlet_to_dict(pond)

    def update_pond_level_targets(
        self,
        farm_id: str,
        pond_id: str,
        target_m: float,
        min_m: float,
        max_m: float,
    ) -> Optional[Dict[str, Any]]:
        """Update configurable target depth and safe level boundaries."""
        pond = (
            self._session.query(PondORM)
            .filter(PondORM.farm_id == farm_id, PondORM.pond_id == pond_id)
            .first()
        )
        if not pond:
            return None
        pond.water_level_target_m = max(0.2, target_m)
        pond.water_level_min_m = max(0.1, min_m)
        pond.water_level_max_m = max(pond.water_level_min_m, max_m)
        self._session.commit()
        return self._outlet_to_dict(pond)

    # -------------------------------------------------------------------------
    # Water Exchange Logs
    # -------------------------------------------------------------------------
    def log_water_exchange(
        self,
        farm_id: str,
        pond_id: str,
        mode: str,
        initial_level_m: float,
        operator_id: str,
        final_level_m: Optional[float] = None,
        notes: Optional[str] = None,
        completed_at: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Record manual or advisory water exchange activity."""
        exchange_id = f"wex-{uuid.uuid4().hex[:10]}"
        orm = WaterExchangeLogORM(
            exchange_id=exchange_id,
            farm_id=farm_id,
            pond_id=pond_id,
            mode=mode,
            initial_level_m=initial_level_m,
            final_level_m=final_level_m,
            started_at=datetime.now(timezone.utc),
            completed_at=completed_at,
            operator_id=operator_id,
            notes=notes,
        )
        self._session.add(orm)
        self._session.commit()
        return self._exchange_to_dict(orm)

    def list_water_exchange_logs(
        self,
        farm_id: str,
        pond_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List historical exchange and drainage records."""
        query = self._session.query(WaterExchangeLogORM).filter(WaterExchangeLogORM.farm_id == farm_id)
        if pond_id:
            query = query.filter(WaterExchangeLogORM.pond_id == pond_id)
        records = query.order_by(WaterExchangeLogORM.started_at.desc()).limit(limit).all()
        return [self._exchange_to_dict(r) for r in records]

    def complete_water_exchange(
        self,
        farm_id: str,
        exchange_id: str,
        final_level_m: float,
        notes: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Mark an ongoing water exchange as completed with final level."""
        orm = (
            self._session.query(WaterExchangeLogORM)
            .filter(
                WaterExchangeLogORM.farm_id == farm_id,
                WaterExchangeLogORM.exchange_id == exchange_id,
            )
            .first()
        )
        if not orm:
            return None
        orm.final_level_m = final_level_m
        orm.completed_at = datetime.now(timezone.utc)
        if notes:
            orm.notes = f"{orm.notes}; {notes}" if orm.notes else notes
        self._session.commit()
        return self._exchange_to_dict(orm)

    # -------------------------------------------------------------------------
    # Serializers
    # -------------------------------------------------------------------------
    def _pump_to_dict(self, orm: WaterPumpORM) -> Dict[str, Any]:
        is_configured = bool(orm.rating_kw is not None and orm.rating_kw > 0 and orm.transformer_id)
        return {
            "pump_id": orm.pump_id,
            "farm_id": orm.farm_id,
            "name": orm.name,
            "motor_hp": orm.motor_hp,
            "rating_kw": orm.rating_kw,
            "transformer_id": orm.transformer_id,
            "is_configured": is_configured,
            "desired_state": orm.desired_state,
            "physical_state": orm.physical_state,
            "current_draw_amps": orm.current_draw_amps,
            "power_kw": orm.power_kw,
            "last_run_timestamp": orm.last_run_timestamp.isoformat() if orm.last_run_timestamp else None,
            "updated_at": orm.updated_at.isoformat() if orm.updated_at else None,
        }

    def _outlet_to_dict(self, pond: PondORM) -> Dict[str, Any]:
        return {
            "pond_id": pond.pond_id,
            "farm_id": pond.farm_id,
            "name": pond.name,
            "water_level_target_m": getattr(pond, "water_level_target_m", 1.22) or 1.22,
            "water_level_min_m": getattr(pond, "water_level_min_m", 0.95) or 0.95,
            "water_level_max_m": getattr(pond, "water_level_max_m", 1.40) or 1.40,
            "limits_provisional": True,
            "normal_outlet_state": getattr(pond, "normal_outlet_state", "CLOSED") or "CLOSED",
            "full_drain_outlet_state": getattr(pond, "full_drain_outlet_state", "CLOSED") or "CLOSED",
            "full_drain_locked": getattr(pond, "full_drain_locked", True) if getattr(pond, "full_drain_locked", True) is not None else True,
            "drain_lock_reason": getattr(pond, "drain_lock_reason", "Active batch containment") or "Active batch containment",
            "physical_position_confirmed": False,
            "software_intent_only": True,
        }

    def _exchange_to_dict(self, orm: WaterExchangeLogORM) -> Dict[str, Any]:
        return {
            "exchange_id": orm.exchange_id,
            "farm_id": orm.farm_id,
            "pond_id": orm.pond_id,
            "mode": orm.mode,
            "initial_level_m": orm.initial_level_m,
            "final_level_m": orm.final_level_m,
            "started_at": orm.started_at.isoformat() if orm.started_at else None,
            "completed_at": orm.completed_at.isoformat() if orm.completed_at else None,
            "operator_id": orm.operator_id,
            "notes": orm.notes,
        }
