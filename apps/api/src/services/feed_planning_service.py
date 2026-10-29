"""Feed Planning & Ration Intelligence Service for Aqua OS.

Coordinates:
- Modular domain ration intelligence calculation with environmental & tray feedback
- Feed stock availability validation using inventory ledgers
- Plan CRUD, multi-session schedules, and operator approval lifecycle
- Planned vs actual feeding variance and FCR monitoring
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from apps.api.src.domain.ration_engine import (
    calculate_feed_ration,
    RationRecommendationResult,
)
from apps.api.src.domain.growth_engine import (
    calculate_dynamic_doc,
    calculate_fcr,
)
from apps.api.src.infrastructure.repositories.sql_feed_plan_repository import SQLFeedPlanRepository
from apps.api.src.infrastructure.repositories.sql_feed_inventory_repository import SQLFeedInventoryRepository
from apps.api.src.infrastructure.repositories.sql_pond_records_repository import SQLPondRecordsRepository
from apps.api.src.infrastructure.repositories.sql_telemetry_repository import SQLTelemetryRepository
from apps.api.src.infrastructure.repositories.sql_pond_repository import SQLPondRepository
from packages.telemetry_schema.models import MetricType


class FeedPlanningService:
    """Application service for feed ration calculation, plan scheduling, and stock checks."""

    def __init__(self, session: Session):
        self._session = session
        self._plan_repo = SQLFeedPlanRepository(session)
        self._inventory_repo = SQLFeedInventoryRepository(session)
        self._records_repo = SQLPondRecordsRepository(session)
        self._telemetry_repo = SQLTelemetryRepository(session)
        self._pond_repo = SQLPondRepository(session)

    # =========================================================================
    # Ration Recommendation Engine
    # =========================================================================

    def get_ration_recommendation(
        self,
        farm_id: str,
        pond_id: str,
        custom_sessions_count: int = 4,
        custom_session_times: Optional[List[str]] = None,
    ) -> Dict[str, Any]:
        """Compute advisory daily feed ration based on latest biomass, water quality, and tray consumption."""
        pond = self._pond_repo.get(farm_id, pond_id)
        if not pond:
            raise ValueError(f"Pond '{pond_id}' not found on farm '{farm_id}'.")

        # 1. Fetch active stocking batch
        active_batch = self._records_repo.get_active_batch(pond_id)
        if not active_batch:
            # Seed default if pond exists to maintain consistent operational workflow
            self._records_repo.seed_default_stocking_for_pond(
                farm_id=farm_id,
                pond_id=pond_id,
                initial_count=pond.stocking_count,
                doc=pond.days_of_culture,
            )
            active_batch = self._records_repo.get_active_batch(pond_id)

        # 2. Fetch latest physical sampling or baseline
        latest_sampling = self._records_repo.get_latest_growth_sample(pond_id)
        stocking_date_dt = (
            datetime.fromisoformat(active_batch["stocking_date"].replace("Z", "+00:00"))
            if active_batch and active_batch.get("stocking_date")
            else datetime.now(timezone.utc)
        )
        doc = calculate_dynamic_doc(stocking_date_dt)

        if latest_sampling:
            abw_g = latest_sampling["abw_g"]
            abw_source = "PHYSICAL_SAMPLING"
            sample_date = (
                datetime.fromisoformat(latest_sampling["sample_date"].replace("Z", "+00:00"))
                if latest_sampling.get("sample_date")
                else None
            )
            survival_pct = latest_sampling.get("estimated_survival_pct") or active_batch.get("estimated_survival_pct", 80.0)
        elif active_batch:
            abw_g = active_batch.get("avg_body_weight_g", 0.0)
            abw_source = "PL_BASELINE" if abw_g <= 0.1 else "MANUAL"
            sample_date = None
            survival_pct = active_batch.get("estimated_survival_pct", 80.0)
        else:
            abw_g = 0.0
            abw_source = "NEEDS_DATA"
            sample_date = None
            survival_pct = 0.0

        stocking_count = active_batch.get("initial_count", 0) if active_batch else 0
        batch_id = active_batch.get("batch_id") if active_batch else None

        # 3. Fetch latest telemetry (DO & Temp)
        telemetry_pkt, _ = self._telemetry_repo.get_latest(farm_id, pond_id) or (None, None)
        do_val = None
        temp_val = None
        telemetry_ts = None
        if telemetry_pkt and telemetry_pkt.metrics:
            if MetricType.DISSOLVED_OXYGEN in telemetry_pkt.metrics:
                do_val = telemetry_pkt.metrics[MetricType.DISSOLVED_OXYGEN].value
            if MetricType.TEMPERATURE in telemetry_pkt.metrics:
                temp_val = telemetry_pkt.metrics[MetricType.TEMPERATURE].value
            telemetry_ts = telemetry_pkt.timestamp

        # 4. Fetch latest check tray observation from feeding history
        feeding_logs = self._records_repo.list_feeding_logs(farm_id, pond_id, limit=3)
        latest_tray = feeding_logs[0]["tray_observation"] if feeding_logs else None

        # 5. Run Domain Engine
        rec = calculate_feed_ration(
            farm_id=farm_id,
            pond_id=pond_id,
            batch_id=batch_id,
            batch_doc=doc,
            stocking_count=stocking_count,
            estimated_survival_pct=survival_pct,
            abw_g=abw_g,
            abw_sample_date=sample_date,
            abw_source=abw_source,
            do_mg_l=do_val,
            temp_c=temp_val,
            telemetry_time=telemetry_ts,
            tray_observation=latest_tray,
            custom_sessions_count=custom_sessions_count,
            custom_session_times=custom_session_times,
        )

        res_dict = rec.model_dump()

        # 6. Check stock availability for active feed products
        products = self._inventory_repo.list_products(farm_id, active_only=True)
        recommended_kg = res_dict.get("recommended_daily_kg") or 0.0
        stock_assessment = []
        for p in products:
            bal = self._inventory_repo.get_product_balance(farm_id, p["product_id"])
            stock_assessment.append({
                "product_id": p["product_id"],
                "product_name": p["product_name"],
                "available_balance_kg": bal["available_balance_kg"],
                "is_low_stock": bal["is_low_stock"],
                "can_fulfill_ration": bal["available_balance_kg"] >= recommended_kg,
            })
        res_dict["available_feed_products"] = stock_assessment

        # 7. Add batch FCR context if available
        if batch_id:
            cum_feed = self._records_repo.get_cumulative_feed_kg(batch_id)
            initial_biomass = active_batch.get("initial_biomass_kg", 0.0)
            cur_biomass = res_dict["inputs_snapshot"].get("estimated_biomass_kg", 0.0)
            fcr_res = calculate_fcr(
                cumulative_feed_kg=cum_feed,
                initial_biomass_kg=initial_biomass,
                current_biomass_kg=cur_biomass,
                harvested_biomass_kg=0.0,
            )
            res_dict["fcr_context"] = {
                "cumulative_feed_kg": cum_feed,
                "production_fcr": fcr_res.production_fcr,
                "apparent_fcr": fcr_res.apparent_fcr,
                "is_calculable": fcr_res.is_calculable,
            }

        return res_dict

    # =========================================================================
    # Plan Management Workflows
    # =========================================================================

    def create_feed_plan(
        self,
        farm_id: str,
        pond_id: str,
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
        auto_approve: bool = False,
    ) -> Dict[str, Any]:
        """Create a pond- and batch-specific feeding plan."""
        # Find active batch for pond
        active_batch = self._records_repo.get_active_batch(pond_id)
        if not active_batch:
            raise ValueError(f"No active stocking batch found for pond '{pond_id}'. Please configure batch before planning.")

        # Check stock balance warning if product_id is specified
        if product_id:
            bal = self._inventory_repo.get_product_balance(farm_id, product_id)
            if bal["available_balance_kg"] < planned_daily_kg:
                # Do not reject plan creation per specification (plan creates advisory target without reserving/deducting),
                # but append stock shortage warning to notes
                shortage_kg = round(planned_daily_kg - bal["available_balance_kg"], 2)
                stock_warn = f" [WARNING: Projected stock shortage of {shortage_kg} kg for '{bal['product_name']}']"
                notes = (notes or "") + stock_warn

        status = "APPROVED" if auto_approve else "DRAFT"

        plan = self._plan_repo.create_plan(
            farm_id=farm_id,
            pond_id=pond_id,
            batch_id=active_batch["batch_id"],
            plan_date=plan_date,
            planned_daily_kg=planned_daily_kg,
            feeding_sessions_count=feeding_sessions_count,
            session_times=session_times,
            planned_kg_per_session=planned_kg_per_session,
            product_id=product_id,
            feed_type=feed_type,
            recommendation_basis=recommendation_basis,
            ration_inputs=ration_inputs,
            notes=notes,
            created_by=created_by,
            status=status,
        )

        if auto_approve:
            plan = self._plan_repo.update_plan_status(
                farm_id=farm_id,
                plan_id=plan["plan_id"],
                new_status="APPROVED",
                operator=created_by,
            )

        return plan

    def get_feed_plan(self, farm_id: str, plan_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve feed plan by ID."""
        return self._plan_repo.get_plan(farm_id, plan_id)

    def list_feed_plans(
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
        return self._plan_repo.list_plans(
            farm_id=farm_id,
            pond_id=pond_id,
            batch_id=batch_id,
            status=status,
            date_from=date_from,
            date_to=date_to,
            limit=limit,
        )

    def update_feed_plan(
        self,
        farm_id: str,
        plan_id: str,
        planned_daily_kg: Optional[float] = None,
        feeding_sessions_count: Optional[int] = None,
        session_times: Optional[List[str]] = None,
        product_id: Optional[str] = None,
        notes: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Update draft or pending plan."""
        return self._plan_repo.update_plan(
            farm_id=farm_id,
            plan_id=plan_id,
            planned_daily_kg=planned_daily_kg,
            feeding_sessions_count=feeding_sessions_count,
            session_times=session_times,
            product_id=product_id,
            notes=notes,
        )

    def approve_feed_plan(
        self,
        farm_id: str,
        plan_id: str,
        operator: str,
    ) -> Dict[str, Any]:
        """Approve a feed plan for execution."""
        plan = self._plan_repo.get_plan(farm_id, plan_id)
        if not plan:
            raise ValueError(f"Feed plan '{plan_id}' not found.")
        if plan["status"] != "DRAFT":
            raise ValueError(f"Cannot approve feed plan in '{plan['status']}' status (must be DRAFT).")

        return self._plan_repo.update_plan_status(
            farm_id=farm_id,
            plan_id=plan_id,
            new_status="APPROVED",
            operator=operator,
        )

    def cancel_feed_plan(
        self,
        farm_id: str,
        plan_id: str,
        operator: str,
    ) -> Dict[str, Any]:
        """Cancel a feed plan."""
        return self._plan_repo.update_plan_status(
            farm_id=farm_id,
            plan_id=plan_id,
            new_status="CANCELLED",
            operator=operator,
        )

    def get_daily_farm_plan_overview(
        self,
        farm_id: str,
        target_date: Optional[datetime] = None,
    ) -> Dict[str, Any]:
        """Get farm-wide daily feed planning overview."""
        return self._plan_repo.get_daily_farm_plan_overview(farm_id, target_date)
