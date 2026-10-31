"""Read-only aerator status synchronization for the farm visual monitor.

This service reports persisted controller feedback only. It never issues actuator
commands and never treats desired_state as proof that a motor is running.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from sqlalchemy.orm import Session

from apps.api.src.infrastructure.models import AeratorUnitORM

DEFAULT_STALE_AFTER_SECONDS = 30


class AeratorStatusSyncService:
    """Build a farm-scoped, freshness-aware snapshot of registered aerators."""

    def __init__(self, stale_after_seconds: int = DEFAULT_STALE_AFTER_SECONDS) -> None:
        if stale_after_seconds < 1:
            raise ValueError("stale_after_seconds must be positive")
        self._stale_after_seconds = stale_after_seconds

    def get_snapshot(self, session: Session, farm_id: str) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        rows = (
            session.query(AeratorUnitORM)
            .filter(AeratorUnitORM.farm_id == farm_id)
            .order_by(AeratorUnitORM.pond_id, AeratorUnitORM.aerator_id)
            .all()
        )
        devices = []
        for row in rows:
            updated_at = row.updated_at
            if updated_at and updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            age_seconds = (now - updated_at).total_seconds() if updated_at else None
            fresh = age_seconds is not None and age_seconds <= self._stale_after_seconds

            # A desired command is not physical feedback. Without a fresh
            # controller update the visual monitor must show UNKNOWN.
            reported = (row.verified_physical_state or "").upper()
            valid_state = reported in {"ON", "OFF", "FAULT", "MANUAL_OVERRIDE"}
            state = reported if fresh and valid_state else "UNKNOWN"
            devices.append({
                "aerator_id": row.aerator_id,
                "name": row.name,
                "farm_id": row.farm_id,
                "tank_id": row.pond_id,
                "desired_state": (row.desired_state or "UNKNOWN").upper(),
                "reported_state": state,
                "state_quality": "FRESH_FEEDBACK" if state != "UNKNOWN" else "STALE_OR_UNVERIFIED",
                "last_update_at": updated_at.isoformat() if updated_at else None,
                "age_seconds": round(age_seconds, 1) if age_seconds is not None else None,
                "current_draw_amps": row.current_draw_amps,
                "power_kw": row.power_kw,
                "fault_reason": row.fault_reason,
                "visual_is_simulated": True,
            })

        return {
            "schema_version": "1.0",
            "farm_id": farm_id,
            "generated_at": now.isoformat(),
            "refresh_hint_seconds": 10,
            "stale_after_seconds": self._stale_after_seconds,
            "equipment_count": len(devices),
            "on_count": sum(d["reported_state"] == "ON" for d in devices),
            "off_count": sum(d["reported_state"] == "OFF" for d in devices),
            "unknown_count": sum(d["reported_state"] == "UNKNOWN" for d in devices),
            "devices": devices,
            "physical_execution_enabled": False,
            "note": "Visual output is simulated. Only fresh verified controller feedback is shown as ON/OFF; desired_state is never treated as proof of operation.",
        }
