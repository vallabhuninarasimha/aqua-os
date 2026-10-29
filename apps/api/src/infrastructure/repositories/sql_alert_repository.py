"""SQL repository for alert lifecycle management (ACTIVE, ACKNOWLEDGED, RESOLVED)."""

from datetime import datetime, timezone
import uuid
from typing import Any, Dict, List, Optional

from sqlalchemy.orm import Session

from apps.api.src.domain.hardware_interfaces import IAlertService
from apps.api.src.infrastructure.models import AlertRecordORM
from packages.telemetry_schema.models import SeverityLevel


class SQLAlertRepository(IAlertService):
    """SQL-backed alert service with lifecycle state machine and deduplication."""

    def __init__(self, session: Session) -> None:
        self._session = session

    def raise_or_update(
        self,
        farm_id: str,
        pond_id: str,
        alert_code: str,
        severity: SeverityLevel,
        message: str,
        recommended_action: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Raise alert or update existing active/acknowledged record to avoid spamming."""
        now = datetime.now(timezone.utc)
        existing = (
            self._session.query(AlertRecordORM)
            .filter(
                AlertRecordORM.farm_id == farm_id,
                AlertRecordORM.pond_id == pond_id,
                AlertRecordORM.alert_code == alert_code,
                AlertRecordORM.status.in_(["ACTIVE", "ACKNOWLEDGED"]),
            )
            .first()
        )

        if existing:
            existing.last_triggered_at = now
            existing.message = message
            existing.severity = severity.value
            if recommended_action:
                existing.recommended_action = recommended_action
            self._session.commit()
            return self._to_dict(existing)

        # Create new active alert
        alert_id = f"alt-{uuid.uuid4().hex[:10]}"
        orm = AlertRecordORM(
            alert_id=alert_id,
            farm_id=farm_id,
            pond_id=pond_id,
            alert_code=alert_code,
            severity=severity.value,
            status="ACTIVE",
            message=message,
            recommended_action=recommended_action,
            first_triggered_at=now,
            last_triggered_at=now,
        )
        self._session.add(orm)
        self._session.commit()
        return self._to_dict(orm)

    def acknowledge(
        self, alert_id: str, acknowledged_by: str, farm_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Transition alert to ACKNOWLEDGED state with tenant scoping."""
        query = self._session.query(AlertRecordORM).filter(AlertRecordORM.alert_id == alert_id)
        if farm_id:
            query = query.filter(AlertRecordORM.farm_id == farm_id)
        orm = query.first()
        if not orm:
            return None

        now = datetime.now(timezone.utc)
        orm.status = "ACKNOWLEDGED"
        orm.acknowledged_at = now
        orm.acknowledged_by = acknowledged_by
        self._session.commit()
        return self._to_dict(orm)

    def resolve(
        self, alert_id: str, resolved_by: str, farm_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Transition alert to RESOLVED state with tenant scoping."""
        query = self._session.query(AlertRecordORM).filter(AlertRecordORM.alert_id == alert_id)
        if farm_id:
            query = query.filter(AlertRecordORM.farm_id == farm_id)
        orm = query.first()
        if not orm:
            return None

        now = datetime.now(timezone.utc)
        orm.status = "RESOLVED"
        orm.resolved_at = now
        orm.resolved_by = resolved_by
        self._session.commit()
        return self._to_dict(orm)

    def auto_recover(self, farm_id: str, pond_id: str, alert_code: str, reason: str = "Parameters returned to normal") -> Optional[Dict[str, Any]]:
        """Auto-resolve an active or acknowledged alert when healthy telemetry resumes."""
        orm = (
            self._session.query(AlertRecordORM)
            .filter(
                AlertRecordORM.farm_id == farm_id,
                AlertRecordORM.pond_id == pond_id,
                AlertRecordORM.alert_code == alert_code,
                AlertRecordORM.status.in_(["ACTIVE", "ACKNOWLEDGED"]),
            )
            .first()
        )
        if not orm:
            return None

        now = datetime.now(timezone.utc)
        orm.status = "RESOLVED"
        orm.resolved_at = now
        orm.resolved_by = f"AUTO_RECOVERY: {reason}"
        self._session.commit()
        return self._to_dict(orm)

    def get_alert(self, alert_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve alert by ID without farm filtering for authorization checks."""
        orm = (
            self._session.query(AlertRecordORM)
            .filter(AlertRecordORM.alert_id == alert_id)
            .first()
        )
        return self._to_dict(orm) if orm else None

    def list(
        self,
        farm_id: str,
        pond_id: Optional[str] = None,
        status: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        query = self._session.query(AlertRecordORM).filter(AlertRecordORM.farm_id == farm_id)
        if pond_id:
            query = query.filter(AlertRecordORM.pond_id == pond_id)
        if status:
            query = query.filter(AlertRecordORM.status == status)
        records = query.order_by(AlertRecordORM.last_triggered_at.desc()).limit(limit).all()
        return [self._to_dict(r) for r in records]

    def get_active_alerts(self, farm_id: str, pond_id: Optional[str] = None) -> List[Dict[str, Any]]:
        query = (
            self._session.query(AlertRecordORM)
            .filter(
                AlertRecordORM.farm_id == farm_id,
                AlertRecordORM.status.in_(["ACTIVE", "ACKNOWLEDGED"]),
            )
        )
        if pond_id:
            query = query.filter(AlertRecordORM.pond_id == pond_id)
        records = query.order_by(AlertRecordORM.last_triggered_at.desc()).all()
        return [self._to_dict(r) for r in records]

    def _to_dict(self, orm: AlertRecordORM) -> Dict[str, Any]:
        return {
            "alert_id": orm.alert_id,
            "farm_id": orm.farm_id,
            "pond_id": orm.pond_id,
            "alert_code": orm.alert_code,
            "severity": orm.severity,
            "status": orm.status,
            "message": orm.message,
            "recommended_action": orm.recommended_action,
            "first_triggered_at": orm.first_triggered_at.isoformat() if orm.first_triggered_at else None,
            "last_triggered_at": orm.last_triggered_at.isoformat() if orm.last_triggered_at else None,
            "acknowledged_at": orm.acknowledged_at.isoformat() if orm.acknowledged_at else None,
            "acknowledged_by": orm.acknowledged_by,
            "resolved_at": orm.resolved_at.isoformat() if orm.resolved_at else None,
            "resolved_by": orm.resolved_by,
        }

