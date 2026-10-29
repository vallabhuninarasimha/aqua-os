"""Feed Plan Repository for Aqua OS.

Handles daily pond- and batch-specific feeding plan persistence, approval workflows,
session schedules, and planned-vs-actual variance calculations with inventory awareness.
"""

from datetime import datetime, timezone, timedelta
import json
from typing import Any, Dict, List, Optional
import uuid

from sqlalchemy import func
from sqlalchemy.orm import Session

from apps.api.src.infrastructure.models import (
    FeedingLogORM,
    FeedPlanORM,
    FeedProductORM,
    PondORM,
    StockingBatchORM,
)


class SQLFeedPlanRepository:
    """SQLAlchemy implementation of feed plan management and planned-vs-actual tracking."""

    def __init__(self, session: Session):
        self._session = session

    # =========================================================================
    # Plan Lifecycle
    # =========================================================================

    def create_plan(
        self,
        farm_id: str,
        pond_id: str,
        batch_id: str,
        plan_date: datetime,
        planned_daily_kg: float,
        feeding_sessions_count: int = 4,
        session_times: Optional[List[str]] = None,
        planned_kg_per_session: Optional[float] = None,
        product_id: Optional[str] = None,
        feed_type: str = "Grower Pellet 38%",
        recommendation_basis: str = "MANUAL",
        ration_inputs: Optional[Dict[str, Any]] = None,
        notes: Optional[str] = None,
        created_by: str = "operator",
        plan_id: Optional[str] = None,
        status: str = "DRAFT",
    ) -> Dict[str, Any]:
        """Create a pond- and batch-specific feed plan with validation against cross-pond mismatches."""
        if planned_daily_kg <= 0:
            raise ValueError("Planned daily feed must be strictly greater than 0 kg.")
        if feeding_sessions_count < 1:
            raise ValueError("Feeding sessions count must be at least 1.")

        # 1. Validate Pond existence on Farm
        pond = (
            self._session.query(PondORM)
            .filter(PondORM.farm_id == farm_id, PondORM.pond_id == pond_id)
            .first()
        )
        if not pond:
            raise ValueError(f"Pond '{pond_id}' does not exist on farm '{farm_id}'.")

        # 2. Validate Batch association (strict cross-pond and cross-farm isolation)
        batch = (
            self._session.query(StockingBatchORM)
            .filter(StockingBatchORM.batch_id == batch_id)
            .first()
        )
        if not batch:
            raise ValueError(f"Stocking batch '{batch_id}' does not exist.")
        if batch.farm_id != farm_id:
            raise ValueError(f"Batch '{batch_id}' belongs to farm '{batch.farm_id}', not '{farm_id}'.")
        if batch.pond_id != pond_id:
            raise ValueError(
                f"Cross-pond mismatch: Batch '{batch_id}' belongs to pond '{batch.pond_id}', not '{pond_id}'."
            )

        # 3. Validate product if specified
        resolved_feed_type = feed_type
        if product_id:
            prod = (
                self._session.query(FeedProductORM)
                .filter(FeedProductORM.farm_id == farm_id, FeedProductORM.product_id == product_id)
                .first()
            )
            if not prod:
                raise ValueError(f"Feed product '{product_id}' not found on farm '{farm_id}'.")
            if not prod.is_active:
                raise ValueError(f"Feed product '{prod.product_name}' ({product_id}) is marked inactive.")
            resolved_feed_type = prod.product_name

        # 4. Standardize session schedule
        kg_per_session = planned_kg_per_session or round(planned_daily_kg / feeding_sessions_count, 2)
        default_times = {
            1: ["08:00"],
            2: ["07:00", "17:00"],
            3: ["06:30", "12:00", "17:30"],
            4: ["06:00", "11:00", "16:00", "21:00"],
            5: ["06:00", "10:00", "14:00", "18:00", "22:00"],
            6: ["06:00", "09:30", "13:00", "16:30", "20:00", "23:00"],
        }
        resolved_times = session_times or default_times.get(feeding_sessions_count, ["06:00", "11:00", "16:00", "21:00"])

        pid = plan_id or f"plan-{uuid.uuid4().hex[:8]}"

        # Normalize plan_date to start of UTC day
        if isinstance(plan_date, str):
            plan_date = datetime.fromisoformat(plan_date.replace("Z", "+00:00"))
        if plan_date.tzinfo is None:
            plan_date = plan_date.replace(tzinfo=timezone.utc)
        normalized_date = plan_date.replace(hour=0, minute=0, second=0, microsecond=0)

        # Check if plan already exists for this pond and date
        existing = (
            self._session.query(FeedPlanORM)
            .filter(
                FeedPlanORM.farm_id == farm_id,
                FeedPlanORM.pond_id == pond_id,
                FeedPlanORM.plan_date == normalized_date,
                FeedPlanORM.status.in_(["DRAFT", "APPROVED", "IN_PROGRESS"]),
            )
            .first()
        )
        if existing:
            raise ValueError(
                f"An active feed plan '{existing.plan_id}' already exists for pond '{pond_id}' on {normalized_date.strftime('%Y-%m-%d')} (Status: {existing.status})."
            )

        now = datetime.now(timezone.utc)
        orm = FeedPlanORM(
            plan_id=pid,
            farm_id=farm_id,
            pond_id=pond_id,
            batch_id=batch_id,
            plan_date=normalized_date,
            product_id=product_id,
            feed_type=resolved_feed_type,
            planned_daily_kg=round(float(planned_daily_kg), 2),
            feeding_sessions_count=int(feeding_sessions_count),
            session_times_json=json.dumps(resolved_times),
            planned_kg_per_session=round(float(kg_per_session), 2),
            status=status.upper(),
            recommendation_basis=recommendation_basis,
            ration_inputs_json=json.dumps(ration_inputs) if ration_inputs else None,
            notes=notes.strip() if notes else None,
            created_by=created_by,
            approved_by=None,
            approved_at=None,
            created_at=now,
            updated_at=now,
        )
        self._session.add(orm)
        self._session.commit()
        return self.get_plan(farm_id, pid)

    def get_plan(self, farm_id: str, plan_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve feed plan with actual feeding logs and planned-vs-actual variance."""
        orm = (
            self._session.query(FeedPlanORM)
            .filter(FeedPlanORM.farm_id == farm_id, FeedPlanORM.plan_id == plan_id)
            .first()
        )
        if not orm:
            return None
        return self._plan_to_dict_with_actuals(orm)

    def list_plans(
        self,
        farm_id: str,
        pond_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        status: Optional[str] = None,
        date_from: Optional[datetime] = None,
        date_to: Optional[datetime] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List feed plans with filters."""
        query = self._session.query(FeedPlanORM).filter(FeedPlanORM.farm_id == farm_id)
        if pond_id:
            query = query.filter(FeedPlanORM.pond_id == pond_id)
        if batch_id:
            query = query.filter(FeedPlanORM.batch_id == batch_id)
        if status:
            query = query.filter(FeedPlanORM.status == status.upper())
        if date_from:
            if date_from.tzinfo is None:
                date_from = date_from.replace(tzinfo=timezone.utc)
            query = query.filter(FeedPlanORM.plan_date >= date_from)
        if date_to:
            if date_to.tzinfo is None:
                date_to = date_to.replace(tzinfo=timezone.utc)
            query = query.filter(FeedPlanORM.plan_date <= date_to)

        records = query.order_by(FeedPlanORM.plan_date.desc(), FeedPlanORM.created_at.desc()).limit(limit).all()
        return [self._plan_to_dict_with_actuals(r) for r in records]

    def update_plan_status(
        self,
        farm_id: str,
        plan_id: str,
        new_status: str,
        operator: str = "operator",
    ) -> Dict[str, Any]:
        """Transition plan status (DRAFT -> APPROVED -> IN_PROGRESS -> COMPLETED / CANCELLED)."""
        valid_statuses = {"DRAFT", "APPROVED", "IN_PROGRESS", "COMPLETED", "CANCELLED"}
        target = new_status.upper()
        if target not in valid_statuses:
            raise ValueError(f"Invalid plan status '{new_status}'. Allowed: {', '.join(sorted(valid_statuses))}")

        orm = (
            self._session.query(FeedPlanORM)
            .filter(FeedPlanORM.farm_id == farm_id, FeedPlanORM.plan_id == plan_id)
            .first()
        )
        if not orm:
            raise ValueError(f"Feed plan '{plan_id}' not found for farm '{farm_id}'.")

        now = datetime.now(timezone.utc)
        orm.status = target
        orm.updated_at = now
        if target == "APPROVED":
            orm.approved_by = operator
            orm.approved_at = now

        self._session.commit()
        return self.get_plan(farm_id, plan_id)

    def update_plan(
        self,
        farm_id: str,
        plan_id: str,
        planned_daily_kg: Optional[float] = None,
        feeding_sessions_count: Optional[int] = None,
        session_times: Optional[List[str]] = None,
        product_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update draft or approved plan parameters before significant execution."""
        orm = (
            self._session.query(FeedPlanORM)
            .filter(FeedPlanORM.farm_id == farm_id, FeedPlanORM.plan_id == plan_id)
            .first()
        )
        if not orm:
            raise ValueError(f"Feed plan '{plan_id}' not found for farm '{farm_id}'.")
        if orm.status in ("COMPLETED", "CANCELLED"):
            raise ValueError(f"Cannot modify feed plan in '{orm.status}' status.")

        if planned_daily_kg is not None:
            if planned_daily_kg <= 0:
                raise ValueError("Planned daily feed must be strictly greater than 0 kg.")
            orm.planned_daily_kg = round(float(planned_daily_kg), 2)

        if feeding_sessions_count is not None:
            if feeding_sessions_count < 1:
                raise ValueError("Feeding sessions count must be at least 1.")
            orm.feeding_sessions_count = int(feeding_sessions_count)

        if session_times is not None:
            orm.session_times_json = json.dumps(session_times)

        # Recalculate kg per session
        orm.planned_kg_per_session = round(orm.planned_daily_kg / orm.feeding_sessions_count, 2)

        if product_id is not None:
            if product_id.strip():
                prod = (
                    self._session.query(FeedProductORM)
                    .filter(FeedProductORM.farm_id == farm_id, FeedProductORM.product_id == product_id)
                    .first()
                )
                if not prod:
                    raise ValueError(f"Product '{product_id}' not found on farm '{farm_id}'.")
                orm.product_id = prod.product_id
                orm.feed_type = prod.product_name
            else:
                orm.product_id = None

        if notes is not None:
            orm.notes = notes.strip() if notes else None

        orm.updated_at = datetime.now(timezone.utc)
        self._session.commit()
        return self.get_plan(farm_id, plan_id)

    # =========================================================================
    # Planned vs Actual Calculations & Daily Overview
    # =========================================================================

    def _plan_to_dict_with_actuals(self, orm: FeedPlanORM) -> Dict[str, Any]:
        """Serialize plan ORM and compute actual recorded feedings, variance, and remaining kg."""
        plan_date = orm.plan_date
        if plan_date.tzinfo is None:
            plan_date = plan_date.replace(tzinfo=timezone.utc)
        day_start = plan_date.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)

        # Query actual feedings matching plan_id or matching pond/date
        feeding_logs = (
            self._session.query(FeedingLogORM)
            .filter(
                FeedingLogORM.farm_id == orm.farm_id,
                FeedingLogORM.pond_id == orm.pond_id,
                (
                    (FeedingLogORM.plan_id == orm.plan_id)
                    | (
                        (FeedingLogORM.plan_id.is_(None))
                        & (FeedingLogORM.timestamp >= day_start)
                        & (FeedingLogORM.timestamp < day_end)
                    )
                ),
            )
            .order_by(FeedingLogORM.timestamp.asc())
            .all()
        )

        actual_fed_kg = round(sum(f.feed_kg for f in feeding_logs), 2)
        actual_sessions_count = len(feeding_logs)
        variance_kg = round(actual_fed_kg - orm.planned_daily_kg, 2)
        remaining_planned_kg = max(0.0, round(orm.planned_daily_kg - actual_fed_kg, 2))
        completion_pct = (
            min(100.0, round((actual_fed_kg / orm.planned_daily_kg) * 100.0, 1))
            if orm.planned_daily_kg > 0
            else 0.0
        )

        # Auto-update status to COMPLETED if all planned kg fed or sessions reached
        current_status = orm.status
        if current_status == "IN_PROGRESS" and (actual_fed_kg >= orm.planned_daily_kg or actual_sessions_count >= orm.feeding_sessions_count):
            current_status = "COMPLETED"

        session_times = []
        if orm.session_times_json:
            try:
                session_times = json.loads(orm.session_times_json)
            except Exception:
                session_times = []

        ration_inputs = None
        if orm.ration_inputs_json:
            try:
                ration_inputs = json.loads(orm.ration_inputs_json)
            except Exception:
                ration_inputs = None

        # Check product inventory balance if product_id is associated
        stock_info = None
        if orm.product_id:
            from apps.api.src.infrastructure.repositories.sql_feed_inventory_repository import SQLFeedInventoryRepository
            inv_repo = SQLFeedInventoryRepository(self._session)
            bal = inv_repo.get_product_balance(orm.farm_id, orm.product_id)
            stock_info = {
                "product_id": bal["product_id"],
                "product_name": bal["product_name"],
                "available_balance_kg": bal["available_balance_kg"],
                "is_low_stock": bal["is_low_stock"],
                "has_sufficient_stock": bal["available_balance_kg"] >= remaining_planned_kg,
            }

        return {
            "plan_id": orm.plan_id,
            "farm_id": orm.farm_id,
            "pond_id": orm.pond_id,
            "batch_id": orm.batch_id,
            "plan_date": orm.plan_date.strftime("%Y-%m-%d"),
            "product_id": orm.product_id,
            "feed_type": orm.feed_type,
            "planned_daily_kg": orm.planned_daily_kg,
            "feeding_sessions_count": orm.feeding_sessions_count,
            "session_times": session_times,
            "planned_kg_per_session": orm.planned_kg_per_session,
            "status": current_status,
            "recommendation_basis": orm.recommendation_basis,
            "ration_inputs": ration_inputs,
            "notes": orm.notes,
            "created_by": orm.created_by,
            "approved_by": orm.approved_by,
            "approved_at": orm.approved_at.isoformat() if orm.approved_at else None,
            "created_at": orm.created_at.isoformat() if orm.created_at else None,
            "updated_at": orm.updated_at.isoformat() if orm.updated_at else None,
            # Execution / Planned vs Actual Metrics
            "actual_fed_kg": actual_fed_kg,
            "actual_sessions_count": actual_sessions_count,
            "variance_kg": variance_kg,
            "remaining_planned_kg": remaining_planned_kg,
            "completion_pct": completion_pct,
            "feed_logs_count": len(feeding_logs),
            "stock_info": stock_info,
        }

    def get_daily_farm_plan_overview(
        self,
        farm_id: str,
        target_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Aggregate daily feeding plan status, total planned vs actual fed, and stock requirements across farm."""
        date_target = target_date or datetime.now(timezone.utc)
        if isinstance(date_target, str):
            date_target = datetime.fromisoformat(date_target.replace("Z", "+00:00"))
        if date_target.tzinfo is None:
            date_target = date_target.replace(tzinfo=timezone.utc)
        norm_date = date_target.replace(hour=0, minute=0, second=0, microsecond=0)

        # Retrieve all plans for this farm and date
        plans = (
            self._session.query(FeedPlanORM)
            .filter(FeedPlanORM.farm_id == farm_id, FeedPlanORM.plan_date == norm_date)
            .all()
        )
        plan_dicts = [self._plan_to_dict_with_actuals(p) for p in plans]

        # Calculate totals
        total_planned_kg = round(sum(p["planned_daily_kg"] for p in plan_dicts), 2)
        total_actual_fed_kg = round(sum(p["actual_fed_kg"] for p in plan_dicts), 2)
        total_remaining_kg = round(sum(p["remaining_planned_kg"] for p in plan_dicts), 2)
        net_variance_kg = round(total_actual_fed_kg - total_planned_kg, 2)
        plans_count = len(plan_dicts)
        completed_count = sum(1 for p in plan_dicts if p["status"] == "COMPLETED")
        in_progress_count = sum(1 for p in plan_dicts if p["status"] == "IN_PROGRESS")
        approved_count = sum(1 for p in plan_dicts if p["status"] == "APPROVED")
        draft_count = sum(1 for p in plan_dicts if p["status"] == "DRAFT")

        return {
            "farm_id": farm_id,
            "target_date": norm_date.strftime("%Y-%m-%d"),
            "total_planned_kg": total_planned_kg,
            "total_actual_fed_kg": total_actual_fed_kg,
            "total_remaining_kg": total_remaining_kg,
            "net_variance_kg": net_variance_kg,
            "plans_count": plans_count,
            "completed_count": completed_count,
            "in_progress_count": in_progress_count,
            "approved_count": approved_count,
            "draft_count": draft_count,
            "plans": plan_dicts,
        }

