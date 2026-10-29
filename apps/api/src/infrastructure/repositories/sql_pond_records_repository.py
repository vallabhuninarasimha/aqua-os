"""SQL repository for stocking batches, sampling records, and batch-associated feeding logs."""

from datetime import datetime, timedelta, timezone
import uuid
from typing import Any, Dict, List, Optional
from sqlalchemy import func
from sqlalchemy.orm import Session

from apps.api.src.domain.growth_engine import (
    calculate_adg,
    calculate_dynamic_doc,
    calculate_estimated_biomass,
    calculate_estimated_population,
    calculate_fcr,
    calculate_harvest_projections,
    calculate_sgr,
    calculate_surviving_population_detail,
    calculate_detailed_biomass,
    calculate_advanced_harvest_forecast,
    evaluate_harvest_readiness,
    calculate_batch_financial_summary,
    calculate_farm_economics_summary,
    BatchFinancialSummary,
    FarmEconomicsSummary,
    FinancialCompletenessStatus,
)
from apps.api.src.infrastructure.models import (
    FeedingLogORM,
    FeedInventoryTransactionORM,
    GrowthSamplingORM,
    HarvestRecordORM,
    MortalityRecordORM,
    StockingBatchORM,
    FarmExpenseORM,
)


class SQLPondRecordsRepository:
    """Repository for pond biological records: multiple batches, sampling, biomass, and feeding."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # -------------------------------------------------------------------------
    # Batch Lifecycle & Multiple Batches Management
    # -------------------------------------------------------------------------

    def get_active_batch(self, pond_id: str, farm_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieve current active (ACTIVE or PARTIALLY_HARVESTED) stocking batch for a pond."""
        query = self._session.query(StockingBatchORM).filter(
            StockingBatchORM.pond_id == pond_id,
            StockingBatchORM.status.in_(["ACTIVE", "PARTIALLY_HARVESTED"]),
        )
        if farm_id:
            query = query.filter(StockingBatchORM.farm_id == farm_id)
        orm = query.order_by(StockingBatchORM.stocking_date.desc()).first()
        return self._batch_to_dict(orm) if orm else None

    def get_batch(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific batch by ID."""
        orm = (
            self._session.query(StockingBatchORM)
            .filter(StockingBatchORM.batch_id == batch_id)
            .first()
        )
        return self._batch_to_dict(orm) if orm else None

    def list_batches(
        self,
        farm_id: str,
        pond_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List production batches across time (active, harvested, closed) preserving history."""
        query = self._session.query(StockingBatchORM).filter(StockingBatchORM.farm_id == farm_id)
        if pond_id:
            query = query.filter(StockingBatchORM.pond_id == pond_id)
        if status:
            query = query.filter(StockingBatchORM.status == status)
        records = query.order_by(StockingBatchORM.stocking_date.desc()).all()
        return [self._batch_to_dict(r) for r in records]

    def save_batch(self, batch_data: Dict[str, Any]) -> Dict[str, Any]:
        """Insert or update a stocking batch."""
        batch_id = batch_data.get("batch_id")
        existing = (
            self._session.query(StockingBatchORM)
            .filter(StockingBatchORM.batch_id == batch_id)
            .first()
            if batch_id
            else None
        )

        initial_count = int(batch_data.get("initial_count", 150_000))
        survival_pct = float(batch_data.get("estimated_survival_pct", 82.0))
        abw_g = float(batch_data.get("avg_body_weight_g", 0.05))
        pl_weight_g = float(batch_data.get("initial_pl_weight_g", 0.05))
        initial_biomass = round((initial_count * pl_weight_g) / 1000.0, 2)

        now = datetime.now(timezone.utc)
        stocking_date = batch_data.get("stocking_date") or now
        if isinstance(stocking_date, str):
            stocking_date = datetime.fromisoformat(stocking_date.replace("Z", "+00:00"))

        doc = calculate_dynamic_doc(stocking_date, now)
        biomass_res = calculate_estimated_biomass(initial_count, survival_pct, abw_g)

        if existing:
            existing.species = batch_data.get("species", existing.species)
            existing.initial_count = initial_count
            existing.initial_pl_weight_g = pl_weight_g
            existing.initial_biomass_kg = initial_biomass
            existing.seed_supplier = batch_data.get("seed_supplier", existing.seed_supplier)
            existing.seed_quality_notes = batch_data.get("seed_quality_notes", existing.seed_quality_notes)
            existing.days_of_culture = int(batch_data.get("days_of_culture", doc))
            existing.estimated_survival_pct = survival_pct
            existing.avg_body_weight_g = abw_g
            existing.estimated_biomass_kg = biomass_res.estimated_biomass_kg
            existing.target_abw_g = float(batch_data.get("target_abw_g", existing.target_abw_g or 25.0))
            existing.projected_sale_price_per_kg = float(
                batch_data.get("projected_sale_price_per_kg", existing.projected_sale_price_per_kg or 5.50)
            )
            if "status" in batch_data:
                existing.status = batch_data["status"]
            self._session.commit()
            return self._batch_to_dict(existing)

        # If creating a new ACTIVE batch for a pond, ensure any previously active batch is archived to CLOSED
        if batch_data.get("status", "ACTIVE") == "ACTIVE":
            self._session.query(StockingBatchORM).filter(
                StockingBatchORM.pond_id == batch_data["pond_id"],
                StockingBatchORM.status == "ACTIVE",
            ).update({"status": "CLOSED"})

        new_batch_id = batch_id or f"batch-{uuid.uuid4().hex[:8]}"
        orm = StockingBatchORM(
            batch_id=new_batch_id,
            farm_id=batch_data["farm_id"],
            pond_id=batch_data["pond_id"],
            stocking_date=stocking_date,
            species=batch_data.get("species", "Litopenaeus vannamei"),
            initial_count=initial_count,
            initial_pl_weight_g=pl_weight_g,
            initial_biomass_kg=initial_biomass,
            seed_supplier=batch_data.get("seed_supplier", "Aquaculture SPF Hatchery"),
            seed_quality_notes=batch_data.get("seed_quality_notes", "SPF certified, active swimming, stress-test passed 100%"),
            days_of_culture=int(batch_data.get("days_of_culture", doc)),
            estimated_survival_pct=survival_pct,
            avg_body_weight_g=abw_g,
            estimated_biomass_kg=biomass_res.estimated_biomass_kg,
            target_abw_g=float(batch_data.get("target_abw_g", 25.0)),
            projected_sale_price_per_kg=float(batch_data.get("projected_sale_price_per_kg", 5.50)),
            status=batch_data.get("status", "ACTIVE"),
        )
        self._session.add(orm)
        self._session.commit()
        return self._batch_to_dict(orm)

    def close_or_harvest_batch(
        self,
        batch_id: str,
        status: str = "HARVESTED",
        harvested_biomass_kg: Optional[float] = None,
        harvest_notes: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Mark a production batch as HARVESTED or CLOSED without deleting historical data."""
        orm = (
            self._session.query(StockingBatchORM)
            .filter(StockingBatchORM.batch_id == batch_id)
            .first()
        )
        if not orm:
            return None

        now = datetime.now(timezone.utc)
        orm.status = status
        orm.harvested_date = now
        if harvested_biomass_kg is not None:
            orm.harvested_biomass_kg = float(harvested_biomass_kg)
        if harvest_notes:
            orm.harvest_notes = harvest_notes

        self._session.commit()
        return self._batch_to_dict(orm)

    # -------------------------------------------------------------------------
    # Shrimp Growth Sampling Records
    # -------------------------------------------------------------------------

    def record_growth_sample(self, sample_data: Dict[str, Any]) -> Dict[str, Any]:
        """Record pond-specific growth sampling point and update batch metrics.
        
        Preserves complete history for growth trend charts and calculates ADG against
        the prior sample in this batch.
        """
        now = datetime.now(timezone.utc)
        farm_id = sample_data["farm_id"]
        pond_id = sample_data["pond_id"]
        batch_id = sample_data.get("batch_id")

        # Resolve active batch if not explicitly given
        batch = self.get_batch(batch_id) if batch_id else self.get_active_batch(pond_id)
        if not batch:
            raise ValueError(f"No active or valid batch found for pond '{pond_id}'.")

        batch_id = batch["batch_id"]
        initial_pl_count = batch["initial_count"]
        stocking_date = datetime.fromisoformat(batch["stocking_date"].replace("Z", "+00:00"))

        sample_date = sample_data.get("sample_date") or now
        if isinstance(sample_date, str):
            sample_date = datetime.fromisoformat(sample_date.replace("Z", "+00:00"))

        doc = calculate_dynamic_doc(stocking_date, sample_date)
        abw_g = float(sample_data["abw_g"])
        sample_count = int(sample_data.get("sample_count", 50))
        measurement_type = sample_data.get("measurement_type", "MEASURED")  # MEASURED, ESTIMATED, MANUAL_ENTRY
        sampling_method = sample_data.get("sampling_method", "Cast net")
        observations = sample_data.get("observations")
        survival_pct = float(sample_data.get("estimated_survival_pct") or batch["estimated_survival_pct"])

        # Find prior sample for this batch to compute ADG
        prior_sample = (
            self._session.query(GrowthSamplingORM)
            .filter(GrowthSamplingORM.batch_id == batch_id)
            .order_by(GrowthSamplingORM.sample_date.desc())
            .first()
        )

        adg_val = None
        if prior_sample:
            elapsed_days = (sample_date - prior_sample.sample_date.replace(tzinfo=timezone.utc)).days
            if elapsed_days > 0:
                adg_res = calculate_adg(abw_g, prior_sample.abw_g, elapsed_days)
                if adg_res.is_valid:
                    adg_val = adg_res.adg_g_per_day
        else:
            # First sample compared to PL stocking (0.05g at DOC 1)
            elapsed_days = max(1, doc - 1)
            adg_res = calculate_adg(abw_g, batch.get("initial_pl_weight_g", 0.05), elapsed_days)
            if adg_res.is_valid:
                adg_val = adg_res.adg_g_per_day

        biomass_res = calculate_estimated_biomass(
            initial_stocked_pl_count=initial_pl_count,
            estimated_survival_pct=survival_pct,
            abw_g=abw_g,
            is_measured_abw=(measurement_type == "MEASURED"),
        )

        sample_id = sample_data.get("sample_id") or f"smp-{uuid.uuid4().hex[:8]}"
        orm = GrowthSamplingORM(
            sample_id=sample_id,
            farm_id=farm_id,
            pond_id=pond_id,
            batch_id=batch_id,
            sample_date=sample_date,
            doc=doc,
            sample_count=sample_count,
            abw_g=round(abw_g, 2),
            measurement_type=measurement_type,
            sampling_method=sampling_method,
            observations=observations,
            estimated_survival_pct=survival_pct,
            estimated_biomass_kg=biomass_res.estimated_biomass_kg,
            is_biomass_estimated=True,  # Always explicitly an estimate
            adg_g_per_day=adg_val,
            recorded_by=sample_data.get("recorded_by", "operator"),
        )
        self._session.add(orm)

        # Update current batch metrics to reflect latest sampling
        batch_orm = (
            self._session.query(StockingBatchORM)
            .filter(StockingBatchORM.batch_id == batch_id)
            .first()
        )
        if batch_orm:
            batch_orm.days_of_culture = doc
            batch_orm.avg_body_weight_g = round(abw_g, 2)
            batch_orm.estimated_survival_pct = survival_pct
            batch_orm.estimated_biomass_kg = biomass_res.estimated_biomass_kg

        self._session.commit()
        return self._sampling_to_dict(orm)

    def list_growth_samples(
        self,
        batch_id: Optional[str] = None,
        pond_id: Optional[str] = None,
        farm_id: Optional[str] = None,
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List historical sampling points sorted chronologically with tenant scoping."""
        query = self._session.query(GrowthSamplingORM)
        if farm_id:
            query = query.filter(GrowthSamplingORM.farm_id == farm_id)
        if batch_id:
            query = query.filter(GrowthSamplingORM.batch_id == batch_id)
        if pond_id:
            query = query.filter(GrowthSamplingORM.pond_id == pond_id)
        records = query.order_by(GrowthSamplingORM.sample_date.asc()).limit(limit).all()
        return [self._sampling_to_dict(r) for r in records]

    def get_latest_growth_sample(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Get the most recent sampling record for a batch."""
        orm = (
            self._session.query(GrowthSamplingORM)
            .filter(GrowthSamplingORM.batch_id == batch_id)
            .order_by(GrowthSamplingORM.sample_date.desc())
            .first()
        )
        return self._sampling_to_dict(orm) if orm else None

    # -------------------------------------------------------------------------
    # Manual Feeding Logs with Batch Tracking, Daily Summaries & Advisories
    # -------------------------------------------------------------------------

    def log_feeding(
        self,
        farm_id: str,
        pond_id: str,
        feed_kg: float,
        feed_type: str = "Grower Pellet 38%",
        feed_time_label: str = "06:00 Morning",
        tray_observation: str = "Clean / 100% Consumed",
        notes: Optional[str] = None,
        recorded_by: str = "operator",
        batch_id: Optional[str] = None,
        feeding_event_count: int = 1,
        timestamp: Optional[datetime] = None,
        product_id: Optional[str] = None,
        plan_id: Optional[str] = None,
    ) -> Dict[str, Any]:
        """Record manual feeding application associated with the active batch.

        Validates positive feed weight, non-zero event count, batch association,
        and prevents accidental duplicate submissions within a 5-minute window.
        When product_id is specified, verifies sufficient inventory and atomically
        deducts stock via an immutable CONSUMPTION ledger transaction.
        """
        if feed_kg <= 0:
            raise ValueError("Feed quantity must be strictly greater than 0 kg.")

        if feeding_event_count < 1:
            raise ValueError("Number of feeding events must be at least 1.")

        now = timestamp or datetime.now(timezone.utc)
        if isinstance(now, str):
            now = datetime.fromisoformat(now.replace("Z", "+00:00"))
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)

        # Validate or resolve batch association
        if batch_id:
            batch = self.get_batch(batch_id)
            if not batch:
                raise ValueError(f"Specified production batch '{batch_id}' does not exist.")
            if batch["pond_id"] != pond_id or batch["farm_id"] != farm_id:
                raise ValueError(
                    f"Production batch '{batch_id}' belongs to pond '{batch['pond_id']}' on farm '{batch['farm_id']}', not pond '{pond_id}'."
                )
        else:
            active_batch = self.get_active_batch(pond_id, farm_id)
            batch_id = active_batch["batch_id"] if active_batch else None

        # Duplicate submission protection: check for identical submission within a 5-minute window
        window_start = now - timedelta(minutes=5)
        window_end = now + timedelta(minutes=5)
        dup_query = self._session.query(FeedingLogORM).filter(
            FeedingLogORM.farm_id == farm_id,
            FeedingLogORM.pond_id == pond_id,
            FeedingLogORM.batch_id == batch_id,
            FeedingLogORM.feed_time_label == feed_time_label,
            FeedingLogORM.feed_type == feed_type,
            FeedingLogORM.feed_kg == feed_kg,
            FeedingLogORM.timestamp >= window_start,
            FeedingLogORM.timestamp <= window_end,
        )
        if product_id:
            dup_query = dup_query.filter(FeedingLogORM.product_id == product_id)
        duplicate = dup_query.first()
        if duplicate:
            raise ValueError(
                f"Accidental duplicate feeding submission detected: an identical {feed_kg} kg entry for slot '{feed_time_label}' was logged at {duplicate.timestamp.isoformat()}."
            )

        # Feed Inventory deduction validation if product_id is provided
        from apps.api.src.infrastructure.models import FeedProductORM, FeedInventoryTransactionORM
        product_orm = None
        if product_id:
            product_orm = (
                self._session.query(FeedProductORM)
                .filter(FeedProductORM.farm_id == farm_id, FeedProductORM.product_id == product_id)
                .first()
            )
            if not product_orm:
                raise ValueError(f"Feed inventory product '{product_id}' does not exist on farm '{farm_id}'.")
            if not product_orm.is_active:
                raise ValueError(f"Feed inventory product '{product_orm.product_name}' ({product_id}) is inactive.")

            # Compute current stock balance
            from apps.api.src.infrastructure.repositories.sql_feed_inventory_repository import SQLFeedInventoryRepository
            inv_repo = SQLFeedInventoryRepository(self._session)
            balance = inv_repo.get_product_balance(farm_id, product_id)
            available = balance["available_balance_kg"]
            if feed_kg > available + 1e-6:
                raise ValueError(
                    f"Insufficient feed inventory for '{product_orm.product_name}'. "
                    f"Ration requested: {feed_kg} kg, Available stock: {available} kg. Cannot permit negative stock."
                )

        # Validate feed plan association if plan_id is provided
        from apps.api.src.infrastructure.models import FeedPlanORM
        plan_orm = None
        if plan_id:
            plan_orm = (
                self._session.query(FeedPlanORM)
                .filter(FeedPlanORM.plan_id == plan_id)
                .first()
            )
            if not plan_orm:
                raise ValueError(f"Specified feed plan '{plan_id}' does not exist.")
            if plan_orm.farm_id != farm_id or plan_orm.pond_id != pond_id:
                raise ValueError(
                    f"Feed plan '{plan_id}' belongs to pond '{plan_orm.pond_id}' on farm '{plan_orm.farm_id}', not pond '{pond_id}'."
                )

        try:
            orm = FeedingLogORM(
                farm_id=farm_id,
                pond_id=pond_id,
                batch_id=batch_id,
                product_id=product_id,
                plan_id=plan_id,
                timestamp=now,
                feed_type=product_orm.product_name if product_orm else feed_type,
                feed_kg=feed_kg,
                feeding_event_count=feeding_event_count,
                feed_time_label=feed_time_label,
                tray_observation=tray_observation,
                notes=notes,
                recorded_by=recorded_by,
                created_at=datetime.now(timezone.utc),
                updated_at=datetime.now(timezone.utc),
            )
            self._session.add(orm)
            self._session.flush()  # Obtain orm.id for inventory transaction linkage

            # Update plan status to IN_PROGRESS if currently DRAFT or APPROVED
            if plan_orm and plan_orm.status in ("DRAFT", "APPROVED"):
                plan_orm.status = "IN_PROGRESS"
                plan_orm.updated_at = datetime.now(timezone.utc)

            # If product_id specified, record consumption transaction atomically
            if product_id and product_orm:
                import uuid
                inv_tx = FeedInventoryTransactionORM(
                    transaction_id=f"tx-feed-{uuid.uuid4().hex[:8]}",
                    farm_id=farm_id,
                    product_id=product_id,
                    transaction_type="CONSUMPTION",
                    quantity_kg=-round(feed_kg, 2),
                    unit_of_measure=product_orm.unit_of_measure or "kg",
                    unit_price=None,
                    total_cost=None,
                    feeding_log_id=orm.id,
                    pond_id=pond_id,
                    batch_id=batch_id,
                    reason=f"Pond ration consumption ({pond_id})",
                    notes=f"Feeding log #{orm.id} for {feed_time_label}",
                    idempotency_key=f"feed-log-deduct-{farm_id}-{orm.id}",
                    recorded_by=recorded_by,
                    timestamp=now,
                    created_at=datetime.now(timezone.utc),
                )
                self._session.add(inv_tx)

            self._session.commit()
            return self._feeding_to_dict(orm)
        except Exception:
            self._session.rollback()
            raise

    def get_cumulative_feed_kg(self, batch_id: str) -> float:
        """Sum cumulative feed administered to a specific batch."""
        val = (
            self._session.query(func.sum(FeedingLogORM.feed_kg))
            .filter(FeedingLogORM.batch_id == batch_id)
            .scalar()
        )
        return round(float(val or 0.0), 2)

    def list_feeding_logs(
        self,
        farm_id: str,
        pond_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List feeding logs filtered by pond, batch, or date range."""
        query = self._session.query(FeedingLogORM).filter(FeedingLogORM.farm_id == farm_id)
        if pond_id:
            query = query.filter(FeedingLogORM.pond_id == pond_id)
        if batch_id:
            query = query.filter(FeedingLogORM.batch_id == batch_id)
        if start_date:
            if isinstance(start_date, str):
                start_date = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
            if start_date.tzinfo is None:
                start_date = start_date.replace(tzinfo=timezone.utc)
            query = query.filter(FeedingLogORM.timestamp >= start_date)
        if end_date:
            if isinstance(end_date, str):
                end_date = datetime.fromisoformat(end_date.replace("Z", "+00:00"))
            if end_date.tzinfo is None:
                end_date = end_date.replace(tzinfo=timezone.utc)
            query = query.filter(FeedingLogORM.timestamp <= end_date)
        records = query.order_by(FeedingLogORM.timestamp.desc()).limit(limit).all()
        return [self._feeding_to_dict(r) for r in records]

    def get_daily_feeding_summary(
        self,
        farm_id: str,
        pond_id: str,
        batch_id: Optional[str] = None,
        days: int = 14,
    ) -> Dict[str, Any]:
        """Aggregate daily feeding totals, tray observations, moving averages, FCR, and advisories."""
        active_batch = self.get_active_batch(pond_id)
        target_batch_id = batch_id or (active_batch["batch_id"] if active_batch else None)

        # Retrieve all feeding logs for pond (and batch if specified) ordered by timestamp desc
        query = self._session.query(FeedingLogORM).filter(
            FeedingLogORM.farm_id == farm_id,
            FeedingLogORM.pond_id == pond_id,
        )
        if target_batch_id:
            query = query.filter(FeedingLogORM.batch_id == target_batch_id)

        all_logs = query.order_by(FeedingLogORM.timestamp.desc()).all()
        cumulative_feed_kg = round(sum(log.feed_kg for log in all_logs), 2)

        # Group by calendar date (YYYY-MM-DD)
        daily_groups: Dict[str, Dict[str, Any]] = {}
        for log in all_logs:
            date_str = log.timestamp.strftime("%Y-%m-%d") if log.timestamp else "Unknown"
            if date_str not in daily_groups:
                daily_groups[date_str] = {
                    "date": date_str,
                    "total_feed_kg": 0.0,
                    "feeding_event_count": 0,
                    "records_count": 0,
                    "feed_types": [],
                    "tray_observations": [],
                    "records": [],
                }
            group = daily_groups[date_str]
            group["total_feed_kg"] = round(group["total_feed_kg"] + log.feed_kg, 2)
            group["feeding_event_count"] += getattr(log, "feeding_event_count", 1) or 1
            group["records_count"] += 1
            if log.feed_type and log.feed_type not in group["feed_types"]:
                group["feed_types"].append(log.feed_type)
            if log.tray_observation and log.tray_observation not in group["tray_observations"]:
                group["tray_observations"].append(log.tray_observation)
            group["records"].append(self._feeding_to_dict(log))

        sorted_daily = [daily_groups[k] for k in sorted(daily_groups.keys(), reverse=True)]
        limited_daily = sorted_daily[:days]

        days_recorded = len(daily_groups)
        avg_daily_feed_kg = round(cumulative_feed_kg / days_recorded, 2) if days_recorded > 0 else 0.0

        # Today's feed in UTC
        today_str = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        today_data = daily_groups.get(today_str)
        today_feed_kg = today_data["total_feed_kg"] if today_data else 0.0
        today_event_count = today_data["feeding_event_count"] if today_data else 0

        # Recent 3-day average excluding today if today is incomplete or just started
        recent_days = [d["total_feed_kg"] for d in sorted_daily if d["date"] != today_str][:3]
        if not recent_days and sorted_daily:
            recent_days = [d["total_feed_kg"] for d in sorted_daily[:3]]
        recent_avg_feed_kg = round(sum(recent_days) / len(recent_days), 2) if recent_days else 0.0

        # Evaluate Advisories
        advisories = self.evaluate_feeding_advisories(
            farm_id=farm_id,
            pond_id=pond_id,
            batch_id=target_batch_id,
            today_feed_kg=today_feed_kg,
            recent_avg_feed_kg=recent_avg_feed_kg,
            all_logs=all_logs,
            active_batch=active_batch,
        )

        # FCR Analysis
        fcr_result = None
        if active_batch and target_batch_id == active_batch["batch_id"]:
            fcr_result = calculate_fcr(
                cumulative_feed_kg=cumulative_feed_kg,
                current_biomass_kg=active_batch.get("estimated_biomass_kg", 0.0),
                initial_biomass_kg=active_batch.get("initial_biomass_kg", 7.5),
                harvested_biomass_kg=active_batch.get("harvested_biomass_kg") or 0.0,
                calculation_period_label=f"DOC 1 to DOC {active_batch.get('days_of_culture', 1)}",
            ).model_dump()

        return {
            "farm_id": farm_id,
            "pond_id": pond_id,
            "batch_id": target_batch_id,
            "batch_cumulative_feed_kg": cumulative_feed_kg,
            "days_recorded": days_recorded,
            "average_daily_feed_kg": avg_daily_feed_kg,
            "today_feed_kg": today_feed_kg,
            "today_event_count": today_event_count,
            "recent_3day_avg_feed_kg": recent_avg_feed_kg,
            "daily_summaries": limited_daily,
            "advisories": advisories,
            "fcr_analysis": fcr_result,
            "has_active_batch": bool(active_batch),
            "batch_doc": active_batch.get("days_of_culture") if active_batch else None,
        }

    def evaluate_feeding_advisories(
        self,
        farm_id: str,
        pond_id: str,
        batch_id: Optional[str] = None,
        today_feed_kg: float = 0.0,
        recent_avg_feed_kg: float = 0.0,
        all_logs: Optional[List[FeedingLogORM]] = None,
        active_batch: Optional[Dict[str, Any]] = None,
    ) -> List[Dict[str, Any]]:
        """Evaluate operational feeding advisories using validated data only.

        No automatic feed quantities or unvalidated species tables are invented.
        """
        advisories: List[Dict[str, Any]] = []

        if active_batch is None:
            active_batch = self.get_active_batch(pond_id)

        target_batch_id = batch_id or (active_batch["batch_id"] if active_batch else None)

        if all_logs is None:
            query = self._session.query(FeedingLogORM).filter(
                FeedingLogORM.farm_id == farm_id,
                FeedingLogORM.pond_id == pond_id,
            )
            if target_batch_id:
                query = query.filter(FeedingLogORM.batch_id == target_batch_id)
            all_logs = query.order_by(FeedingLogORM.timestamp.desc()).all()

        # 1. No feeding records entered for batch
        if not all_logs:
            advisories.append({
                "code": "NO_FEED_DATA_FOR_BATCH",
                "severity": "INFO",
                "title": "No Feeding Records on File",
                "message": f"Feed consumption is unavailable for batch '{target_batch_id or 'Unassigned'}'.",
                "reason": "No manual feed application logs have been recorded yet for this production cycle.",
                "recommendation": "Begin logging daily rations, feed product type, and check tray observations as feed is applied.",
            })
            return advisories

        # 2. No feeding record entered today
        if today_feed_kg <= 0:
            advisories.append({
                "code": "NO_FEED_LOGGED_TODAY",
                "severity": "WARNING",
                "title": "No Feeding Logged Today",
                "message": f"No feeding record has been entered for today (Pond {pond_id}).",
                "reason": "Shrimp require consistent daily ration intervals to maintain metabolic health and prevent starvation stress.",
                "recommendation": "Confirm whether scheduled feeding was administered and record the feed quantity and check tray condition.",
            })

        # 3. Feed quantity differs significantly from recent recorded pattern
        if today_feed_kg > 0 and recent_avg_feed_kg > 0:
            diff_ratio = (today_feed_kg - recent_avg_feed_kg) / recent_avg_feed_kg
            diff_pct = abs(diff_ratio) * 100
            if diff_pct >= 25.0:
                direction = "higher" if diff_ratio > 0 else "lower"
                advisories.append({
                    "code": "FEED_RATION_VARIANCE",
                    "severity": "WARNING",
                    "title": f"Ration Divergence ({diff_pct:.0f}% {direction.capitalize()})",
                    "message": f"Today's feed quantity ({today_feed_kg:.1f} kg) is {diff_pct:.1f}% {direction} than the recent 3-day average ({recent_avg_feed_kg:.1f} kg/day).",
                    "reason": "A significant deviation from standard ration patterns was detected. Large jumps can cause overfeeding or sudden growth deficits.",
                    "recommendation": "Verify check tray consumption, water DO, and temperature to confirm if this change was intentional.",
                })

        # 4. Check tray unconsumed leftover advisory
        latest_log = all_logs[0] if all_logs else None
        if latest_log and latest_log.tray_observation:
            obs = latest_log.tray_observation.lower()
            if "heavy leftover" in obs or "slow" in obs or "70%" in obs or "reduced" in obs:
                advisories.append({
                    "code": "CHECK_TRAY_LEFTOVER_ALERT",
                    "severity": "ALERT",
                    "title": "Check Tray Leftovers Detected",
                    "message": f"Latest check tray observation indicates unconsumed feed: '{latest_log.tray_observation}'.",
                    "reason": "Unconsumed pellet feed decays rapidly on the pond bottom, promoting vibrio growth, benthic sludge, and nocturnal DO crashes.",
                    "recommendation": "Reduce next scheduled feeding ration by 20% to 30%. Re-check tray before restoring normal ration.",
                })

        # 5. Biomass / sampling data missing or outdated
        latest_sample = self.get_latest_growth_sample(target_batch_id) if target_batch_id else None
        if not latest_sample:
            advisories.append({
                "code": "MISSING_BIOMASS_SAMPLING",
                "severity": "INFO",
                "title": "Physical Sampling Data Missing",
                "message": "No physical growth sampling records exist for this production batch.",
                "reason": "Biomass calculation currently relies entirely on initial stocking estimates rather than measured sample ABW.",
                "recommendation": "Conduct a cast net sampling event to establish measured Average Body Weight (ABW) and verify survival.",
            })
        else:
            sample_date_raw = str(latest_sample["sample_date"]).replace("Z", "+00:00")
            sample_dt = datetime.fromisoformat(sample_date_raw)
            if sample_dt.tzinfo is None:
                sample_dt = sample_dt.replace(tzinfo=timezone.utc)
            days_since = (datetime.now(timezone.utc) - sample_dt).days
            if days_since > 10:
                advisories.append({
                    "code": "OUTDATED_BIOMASS_SAMPLING",
                    "severity": "INFO",
                    "title": "Biomass Sampling Outdated",
                    "message": f"Latest growth sample is {days_since} days old (recorded on {sample_dt.strftime('%Y-%m-%d')}).",
                    "reason": "Shrimp grow rapidly; an outdated ABW reduces the reliability of biomass estimates and FCR calculations.",
                    "recommendation": "Schedule routine weekly growth sampling to calibrate shrimp weight and feeding rates.",
                })

        return advisories

    # -------------------------------------------------------------------------
    # Comprehensive Pond Growth & Production Intelligence Bundle
    # -------------------------------------------------------------------------

    def get_pond_production_summary(self, farm_id: str, pond_id: str) -> Dict[str, Any]:
        """Compile complete growth intelligence, sampling trend, FCR, and harvest projections."""
        batch = self.get_active_batch(pond_id, farm_id)
        if not batch:
            return {"has_active_batch": False, "pond_id": pond_id}

        batch_id = batch["batch_id"]
        samples = self.list_growth_samples(batch_id=batch_id)
        latest_sample = samples[-1] if samples else None
        prev_sample = samples[-2] if len(samples) >= 2 else None

        cumulative_feed = self.get_cumulative_feed_kg(batch_id)
        harvest_summary = self.get_batch_harvest_summary(batch_id)

        # ADG and SGR
        current_adg = latest_sample["adg_g_per_day"] if latest_sample else None
        current_sgr = None
        if latest_sample and prev_sample:
            s_date_cur = datetime.fromisoformat(str(latest_sample["sample_date"]).replace("Z", "+00:00"))
            s_date_prev = datetime.fromisoformat(str(prev_sample["sample_date"]).replace("Z", "+00:00"))
            elapsed_days = (s_date_cur - s_date_prev).days
            sgr_calc = calculate_sgr(latest_sample["abw_g"], prev_sample["abw_g"], elapsed_days)
            if sgr_calc.is_valid:
                current_sgr = sgr_calc.sgr_pct_per_day
        elif latest_sample and batch.get("initial_pl_weight_g") and batch.get("stocking_date"):
            s_date_cur = datetime.fromisoformat(str(latest_sample["sample_date"]).replace("Z", "+00:00"))
            stock_dt = datetime.fromisoformat(str(batch["stocking_date"]).replace("Z", "+00:00"))
            elapsed_days = (s_date_cur - stock_dt).days
            if elapsed_days > 0:
                sgr_calc = calculate_sgr(latest_sample["abw_g"], batch["initial_pl_weight_g"], elapsed_days)
                if sgr_calc.is_valid:
                    current_sgr = sgr_calc.sgr_pct_per_day

        # Days since sampling freshness
        now = datetime.now(timezone.utc)
        days_since_sample = None
        if latest_sample and latest_sample.get("sample_date"):
            sample_dt = datetime.fromisoformat(str(latest_sample["sample_date"]).replace("Z", "+00:00"))
            if sample_dt.tzinfo is None:
                sample_dt = sample_dt.replace(tzinfo=timezone.utc)
            days_since_sample = (now - sample_dt).days

        # Detailed biomass estimation
        biomass_detail = calculate_detailed_biomass(
            pond_id=pond_id,
            batch_id=batch_id,
            has_active_batch=True,
            initial_count=batch["initial_count"],
            avg_body_weight_g=batch["avg_body_weight_g"],
            cumulative_recorded_mortality=batch.get("cumulative_recorded_mortality", 0),
            cumulative_harvested_count=harvest_summary.get("total_harvested_pieces", 0),
            estimated_survival_pct=batch.get("estimated_survival_pct"),
            days_since_sampling=days_since_sample,
            is_measured_abw=(latest_sample.get("measurement_type") == "MEASURED") if latest_sample else False,
            cumulative_partial_harvest_kg=harvest_summary["partial_harvest_kg"],
            documented_losses_kg=harvest_summary.get("total_documented_losses_kg", 0.0),
        )

        # Advanced harvest forecasting (strictly uses batch configurations without invented values)
        adv_forecast = calculate_advanced_harvest_forecast(
            pond_id=pond_id,
            batch_id=batch_id,
            has_active_batch=True,
            current_doc=batch["days_of_culture"],
            current_abw_g=batch["avg_body_weight_g"],
            surviving_count=biomass_detail.surviving_count,
            target_abw_g=batch.get("target_abw_g"),
            adg_g_per_day=current_adg,
            sgr_pct_per_day=current_sgr,
            cumulative_partial_harvest_kg=harvest_summary["partial_harvest_kg"],
            projected_sale_price_per_kg=batch.get("projected_sale_price_per_kg"),
            days_since_sampling=days_since_sample,
        )

        # FCR calculation
        fcr_result = calculate_fcr(
            cumulative_feed_kg=cumulative_feed,
            current_biomass_kg=biomass_detail.net_remaining_biomass_kg,
            initial_biomass_kg=batch.get("initial_biomass_kg", 7.5),
            harvested_biomass_kg=harvest_summary["total_harvested_kg"],
            calculation_period_label=f"DOC 1 to DOC {batch['days_of_culture']}",
        )

        # Legacy harvest projection for compatibility
        harvest_proj = calculate_harvest_projections(
            current_doc=batch["days_of_culture"],
            current_abw_g=batch["avg_body_weight_g"],
            current_estimated_biomass_kg=biomass_detail.net_remaining_biomass_kg,
            current_estimated_population=biomass_detail.surviving_count,
            target_abw_g=batch.get("target_abw_g") or 25.0,
            adg_g_per_day=current_adg,
            projected_sale_price_per_kg=batch.get("projected_sale_price_per_kg") or 5.50,
        )

        return {
            "has_active_batch": True,
            "pond_id": pond_id,
            "batch": batch,
            "latest_sample": latest_sample,
            "previous_sample": prev_sample,
            "sample_count": len(samples),
            "samples_history": samples,
            "adg_g_per_day": current_adg,
            "sgr_pct_per_day": current_sgr,
            "cumulative_feed_kg": cumulative_feed,
            "biomass_detail": biomass_detail.model_dump(),
            "advanced_harvest_forecast": adv_forecast.model_dump(),
            "harvest_summary": harvest_summary,
            "fcr_analysis": fcr_result.model_dump(),
            "harvest_projection": harvest_proj.model_dump(),
        }


    def seed_default_stocking_for_pond(
        self,
        farm_id: str,
        pond_id: str,
        initial_count: int = 150_000,
        doc: int = 35,
        abw_g: float = 8.5,
    ) -> None:
        """Seed initial stocking record and baseline growth sampling points for realistic trends."""
        existing = self.get_active_batch(pond_id)
        if existing:
            return

        from datetime import timedelta
        now = datetime.now(timezone.utc)
        stocking_date = now - timedelta(days=doc - 1)

        batch_id = f"batch-{pond_id}-01"
        saved = self.save_batch({
            "batch_id": batch_id,
            "farm_id": farm_id,
            "pond_id": pond_id,
            "species": "Litopenaeus vannamei",
            "initial_count": initial_count,
            "initial_pl_weight_g": 0.05,
            "seed_supplier": "Aquaculture SPF Hatchery",
            "seed_quality_notes": "SPF certified postlarvae, 100% active swimming, formalin test passed",
            "stocking_date": stocking_date,
            "days_of_culture": doc,
            "estimated_survival_pct": 82.0,
            "avg_body_weight_g": abw_g,
            "target_abw_g": 25.0,
            "projected_sale_price_per_kg": 5.50,
            "status": "ACTIVE",
        })

        # Seed realistic progressive sampling points so growth charts & ADG are populated
        # Sample 1 at DOC 14: ABW = 2.1g
        s1_date = stocking_date + timedelta(days=13)
        self.record_growth_sample({
            "sample_id": f"smp-{pond_id}-01",
            "farm_id": farm_id,
            "pond_id": pond_id,
            "batch_id": batch_id,
            "sample_date": s1_date,
            "sample_count": 60,
            "abw_g": 2.1,
            "measurement_type": "MEASURED",
            "sampling_method": "Cast net",
            "observations": "Uniform size distribution, clear gut, active feeding",
            "estimated_survival_pct": 88.0,
            "recorded_by": "lead_biologist",
        })

        # Sample 2 at DOC 25: ABW = 5.2g
        s2_date = stocking_date + timedelta(days=24)
        self.record_growth_sample({
            "sample_id": f"smp-{pond_id}-02",
            "farm_id": farm_id,
            "pond_id": pond_id,
            "batch_id": batch_id,
            "sample_date": s2_date,
            "sample_count": 75,
            "abw_g": 5.2,
            "measurement_type": "MEASURED",
            "sampling_method": "Cast net",
            "observations": "Firm exoskeleton, hepatopancreas dark and full, good vigor",
            "estimated_survival_pct": 85.0,
            "recorded_by": "lead_biologist",
        })

        # Sample 3 at current DOC (DOC 35): ABW = 8.5g
        self.record_growth_sample({
            "sample_id": f"smp-{pond_id}-03",
            "farm_id": farm_id,
            "pond_id": pond_id,
            "batch_id": batch_id,
            "sample_date": now,
            "sample_count": 80,
            "abw_g": abw_g,
            "measurement_type": "MEASURED",
            "sampling_method": "Cast net",
            "observations": "Healthy molt cycle observed, no gill fouling, vigorous swimming",
            "estimated_survival_pct": 82.0,
            "recorded_by": "lead_biologist",
        })

        # Seed baseline feeding history for the batch (~1,285 kg feed total)
        for i, days_ago in enumerate([10, 8, 5, 3, 1, 0]):
            feed_time = now - timedelta(days=days_ago)
            orm_f = FeedingLogORM(
                farm_id=farm_id,
                pond_id=pond_id,
                batch_id=batch_id,
                timestamp=feed_time,
                feed_type="Grower Pellet 38%",
                feed_kg=18.5 + (i * 2.0),
                feed_time_label="06:00 Morning",
                tray_observation="Clean / 100% Consumed",
                notes=f"DOC {doc - days_ago} regular feeding application",
                recorded_by="operator",
            )
            self._session.add(orm_f)
        self._session.commit()

    # -------------------------------------------------------------------------
    # Dict serializers
    # -------------------------------------------------------------------------

    def _batch_to_dict(self, orm: StockingBatchORM) -> Dict[str, Any]:
        return {
            "batch_id": orm.batch_id,
            "farm_id": orm.farm_id,
            "pond_id": orm.pond_id,
            "stocking_date": orm.stocking_date.isoformat() if orm.stocking_date else None,
            "species": orm.species,
            "initial_count": orm.initial_count,
            "initial_pl_weight_g": orm.initial_pl_weight_g or 0.05,
            "initial_biomass_kg": orm.initial_biomass_kg or 7.5,
            "seed_supplier": orm.seed_supplier,
            "seed_quality_notes": orm.seed_quality_notes,
            "days_of_culture": orm.days_of_culture,
            "estimated_survival_pct": orm.estimated_survival_pct,
            "avg_body_weight_g": orm.avg_body_weight_g,
            "estimated_biomass_kg": orm.estimated_biomass_kg,
            "target_abw_g": orm.target_abw_g or 25.0,
            "target_harvest_date": orm.target_harvest_date.isoformat() if orm.target_harvest_date else None,
            "target_harvest_biomass_kg": orm.target_harvest_biomass_kg,
            "projected_sale_price_per_kg": orm.projected_sale_price_per_kg or 5.50,
            "harvested_date": orm.harvested_date.isoformat() if orm.harvested_date else None,
            "harvested_biomass_kg": orm.harvested_biomass_kg,
            "harvest_notes": orm.harvest_notes,
            "cumulative_recorded_mortality": getattr(orm, "cumulative_recorded_mortality", 0) or 0,
            "status": orm.status,
            "created_at": orm.created_at.isoformat() if orm.created_at else None,
            "updated_at": orm.updated_at.isoformat() if orm.updated_at else None,
        }

    def _sampling_to_dict(self, orm: GrowthSamplingORM) -> Dict[str, Any]:
        return {
            "sample_id": orm.sample_id,
            "farm_id": orm.farm_id,
            "pond_id": orm.pond_id,
            "batch_id": orm.batch_id,
            "sample_date": orm.sample_date.isoformat() if orm.sample_date else None,
            "doc": orm.doc,
            "sample_count": orm.sample_count,
            "abw_g": orm.abw_g,
            "measurement_type": orm.measurement_type,
            "sampling_method": orm.sampling_method,
            "observations": orm.observations,
            "estimated_survival_pct": orm.estimated_survival_pct,
            "estimated_biomass_kg": orm.estimated_biomass_kg,
            "is_biomass_estimated": bool(orm.is_biomass_estimated),
            "adg_g_per_day": orm.adg_g_per_day,
            "recorded_by": orm.recorded_by,
            "created_at": orm.created_at.isoformat() if orm.created_at else None,
        }

    def _feeding_to_dict(self, orm: FeedingLogORM) -> Dict[str, Any]:
        return {
            "id": orm.id,
            "farm_id": orm.farm_id,
            "pond_id": orm.pond_id,
            "batch_id": orm.batch_id,
            "product_id": getattr(orm, "product_id", None),
            "plan_id": getattr(orm, "plan_id", None),
            "timestamp": orm.timestamp.isoformat() if orm.timestamp else None,
            "feed_type": orm.feed_type,
            "feed_kg": orm.feed_kg,
            "feeding_event_count": getattr(orm, "feeding_event_count", 1) or 1,
            "feed_time_label": orm.feed_time_label,
            "tray_observation": orm.tray_observation,
            "notes": orm.notes,
            "recorded_by": orm.recorded_by,
            "created_at": orm.created_at.isoformat() if getattr(orm, "created_at", None) else (orm.timestamp.isoformat() if orm.timestamp else None),
            "updated_at": orm.updated_at.isoformat() if getattr(orm, "updated_at", None) else (orm.timestamp.isoformat() if orm.timestamp else None),
        }

    def _harvest_to_dict(self, orm: HarvestRecordORM) -> Dict[str, Any]:
        return {
            "id": orm.id,
            "harvest_id": orm.harvest_id,
            "farm_id": orm.farm_id,
            "pond_id": orm.pond_id,
            "batch_id": orm.batch_id,
            "harvest_type": orm.harvest_type,
            "harvest_date": orm.harvest_date.isoformat() if orm.harvest_date else None,
            "harvested_weight_kg": orm.harvested_weight_kg,
            "count_pieces": orm.count_pieces,
            "count_per_kg": orm.count_per_kg,
            "avg_body_weight_g": orm.avg_body_weight_g,
            "grade": orm.grade,
            "selling_price_per_kg": orm.selling_price_per_kg,
            "total_revenue": orm.total_revenue,
            "documented_losses_kg": orm.documented_losses_kg,
            "buyer": orm.buyer,
            "notes": orm.notes,
            "idempotency_key": orm.idempotency_key,
            "recorded_by": orm.recorded_by,
            "created_at": orm.created_at.isoformat() if orm.created_at else None,
        }

    # -------------------------------------------------------------------------
    # Harvest Management & Batch Lifecycle Tracking
    # -------------------------------------------------------------------------

    def record_harvest(self, harvest_data: Dict[str, Any]) -> Dict[str, Any]:
        """Record partial or final harvest with yield, grading, revenue, and batch lifecycle transition."""
        weight_kg = float(harvest_data["harvested_weight_kg"])
        if weight_kg <= 0:
            raise ValueError("Harvested weight must be strictly greater than 0 kg.")

        farm_id = harvest_data["farm_id"]
        pond_id = harvest_data["pond_id"]
        batch_id = harvest_data.get("batch_id")

        # 1. Farm-level pond isolation and ownership verification
        pond_orm = (
            self._session.query(PondORM)
            .filter(PondORM.pond_id == pond_id, PondORM.farm_id == farm_id)
            .first()
        )
        if not pond_orm:
            raise ValueError(f"Pond '{pond_id}' does not exist on farm '{farm_id}'.")

        # 2. Idempotency protection with farm-isolation
        idempotency_key = harvest_data.get("idempotency_key")
        if idempotency_key:
            existing = (
                self._session.query(HarvestRecordORM)
                .filter(
                    HarvestRecordORM.farm_id == farm_id,
                    HarvestRecordORM.idempotency_key == idempotency_key,
                )
                .first()
            )
            if existing:
                return self._harvest_to_dict(existing)

        # 3. Batch ownership and lifecycle eligibility
        batch_orm = None
        if batch_id:
            batch_orm = (
                self._session.query(StockingBatchORM)
                .filter(StockingBatchORM.batch_id == batch_id)
                .first()
            )
            if not batch_orm:
                raise ValueError(f"Batch '{batch_id}' not found.")
            if batch_orm.farm_id != farm_id:
                raise ValueError(f"Batch '{batch_id}' belongs to farm '{batch_orm.farm_id}', not '{farm_id}'.")
            if batch_orm.pond_id != pond_id:
                raise ValueError(f"Batch '{batch_id}' belongs to pond '{batch_orm.pond_id}', not '{pond_id}'.")
            if batch_orm.status not in ["ACTIVE", "PARTIALLY_HARVESTED"]:
                raise ValueError(
                    f"Cannot record harvest for batch '{batch_id}' with lifecycle status '{batch_orm.status}'. "
                    "Only ACTIVE or PARTIALLY_HARVESTED batches can be harvested."
                )
        else:
            batch_orm = (
                self._session.query(StockingBatchORM)
                .filter(
                    StockingBatchORM.farm_id == farm_id,
                    StockingBatchORM.pond_id == pond_id,
                    StockingBatchORM.status.in_(["ACTIVE", "PARTIALLY_HARVESTED"]),
                )
                .order_by(StockingBatchORM.stocking_date.desc())
                .first()
            )

        if not batch_orm:
            raise ValueError(f"No active or partially harvested batch found for pond '{pond_id}' on farm '{farm_id}'.")

        batch_id = batch_orm.batch_id
        harvest_type = str(harvest_data.get("harvest_type", "FINAL")).upper()
        if harvest_type not in ["PARTIAL", "FINAL"]:
            harvest_type = "FINAL"

        # 4. Biomass exceedance check with auditable operator override
        remaining_est_biomass = batch_orm.estimated_biomass_kg
        allow_override = bool(harvest_data.get("allow_biomass_override", False))
        if remaining_est_biomass is not None and remaining_est_biomass > 0:
            if weight_kg > remaining_est_biomass:
                if not allow_override:
                    raise ValueError(
                        f"Harvested weight ({weight_kg:.1f} kg) exceeds estimated remaining biomass ({remaining_est_biomass:.1f} kg). "
                        f"To confirm exceptional harvest or batch clearing, provide 'allow_biomass_override=true' with documented reason."
                    )
                else:
                    audit_note = f"[AUDIT OVERRIDE: Harvested {weight_kg:.1f} kg exceeds estimated {remaining_est_biomass:.1f} kg]"
                    prior_notes = harvest_data.get("notes")
                    harvest_data["notes"] = (prior_notes + " | " if prior_notes else "") + audit_note

        now = datetime.now(timezone.utc)
        harvest_date = harvest_data.get("harvest_date") or now
        if isinstance(harvest_date, str):
            harvest_date = datetime.fromisoformat(harvest_date.replace("Z", "+00:00"))
        if harvest_date.tzinfo is None:
            harvest_date = harvest_date.replace(tzinfo=timezone.utc)

        # Body weight / count calculations
        abw_g = harvest_data.get("avg_body_weight_g")
        count_per_kg = harvest_data.get("count_per_kg")
        count_pieces = harvest_data.get("count_pieces")
        if abw_g and not count_per_kg and float(abw_g) > 0:
            count_per_kg = round(1000.0 / float(abw_g), 1)
        elif count_per_kg and not abw_g and float(count_per_kg) > 0:
            abw_g = round(1000.0 / float(count_per_kg), 2)
        if count_per_kg and not count_pieces and float(count_per_kg) > 0:
            count_pieces = int(round(weight_kg * float(count_per_kg)))
        elif abw_g and not count_pieces and float(abw_g) > 0:
            count_pieces = int(round((weight_kg * 1000.0) / float(abw_g)))

        # Revenue calculation
        price_per_kg = harvest_data.get("selling_price_per_kg")
        total_rev = harvest_data.get("total_revenue")
        if price_per_kg is not None and float(price_per_kg) > 0 and total_rev is None:
            total_rev = round(weight_kg * float(price_per_kg), 2)

        try:
            harvest_id = harvest_data.get("harvest_id") or f"hrv-{uuid.uuid4().hex[:8]}"
            orm = HarvestRecordORM(
                harvest_id=harvest_id,
                farm_id=farm_id,
                pond_id=pond_id,
                batch_id=batch_id,
                harvest_type=harvest_type,
                harvest_date=harvest_date,
                harvested_weight_kg=weight_kg,
                count_pieces=int(count_pieces) if count_pieces else None,
                count_per_kg=float(count_per_kg) if count_per_kg else None,
                avg_body_weight_g=float(abw_g) if abw_g else None,
                grade=harvest_data.get("grade"),
                selling_price_per_kg=float(price_per_kg) if price_per_kg is not None else None,
                total_revenue=float(total_rev) if total_rev is not None else None,
                documented_losses_kg=float(harvest_data.get("documented_losses_kg", 0.0) or 0.0),
                buyer=harvest_data.get("buyer"),
                notes=harvest_data.get("notes"),
                idempotency_key=idempotency_key,
                recorded_by=harvest_data.get("recorded_by", "operator"),
            )
            self._session.add(orm)
            self._session.flush()

            # Update cumulative harvested biomass on the batch from database aggregation (prevents double-counting)
            prior_sum = (
                self._session.query(func.sum(HarvestRecordORM.harvested_weight_kg))
                .filter(HarvestRecordORM.batch_id == batch_id)
                .scalar()
                or 0.0
            )
            batch_orm.harvested_biomass_kg = round(float(prior_sum), 2)

            # Batch lifecycle state transition
            if harvest_type == "FINAL":
                batch_orm.status = "HARVESTED"
                batch_orm.harvested_date = harvest_date
                batch_orm.estimated_biomass_kg = 0.0
                if harvest_data.get("notes"):
                    batch_orm.harvest_notes = (
                        (batch_orm.harvest_notes + " | " if batch_orm.harvest_notes else "") + harvest_data["notes"]
                    )
            elif harvest_type == "PARTIAL":
                if batch_orm.status == "ACTIVE":
                    batch_orm.status = "PARTIALLY_HARVESTED"
                # Deduct harvested weight from remaining estimated biomass
                if batch_orm.estimated_biomass_kg:
                    batch_orm.estimated_biomass_kg = max(
                        0.0, round(batch_orm.estimated_biomass_kg - weight_kg, 2)
                    )

            self._session.commit()
            return self._harvest_to_dict(orm)
        except Exception:
            self._session.rollback()
            raise

    def list_harvest_records(
        self,
        farm_id: str,
        pond_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List historical harvest event records."""
        query = self._session.query(HarvestRecordORM).filter(HarvestRecordORM.farm_id == farm_id)
        if pond_id:
            query = query.filter(HarvestRecordORM.pond_id == pond_id)
        if batch_id:
            query = query.filter(HarvestRecordORM.batch_id == batch_id)
        records = query.order_by(HarvestRecordORM.harvest_date.desc()).limit(limit).all()
        return [self._harvest_to_dict(r) for r in records]

    def get_batch_harvest_summary(self, batch_id: str) -> Dict[str, Any]:
        """Aggregate total harvested biomass, revenue, pieces, losses, and event counts for a batch."""
        harvests = (
            self._session.query(HarvestRecordORM)
            .filter(HarvestRecordORM.batch_id == batch_id)
            .order_by(HarvestRecordORM.harvest_date.asc())
            .all()
        )
        total_kg = sum(h.harvested_weight_kg for h in harvests)
        total_revenue = sum(h.total_revenue or 0.0 for h in harvests)
        partial_kg = sum(h.harvested_weight_kg for h in harvests if h.harvest_type == "PARTIAL")
        final_kg = sum(h.harvested_weight_kg for h in harvests if h.harvest_type == "FINAL")
        total_pieces = sum(h.count_pieces or 0 for h in harvests)
        total_losses = sum(h.documented_losses_kg or 0.0 for h in harvests)
        return {
            "batch_id": batch_id,
            "total_harvested_kg": round(total_kg, 2),
            "total_revenue": round(total_revenue, 2) if total_revenue > 0 else None,
            "harvest_count": len(harvests),
            "partial_harvest_kg": round(partial_kg, 2),
            "final_harvest_kg": round(final_kg, 2),
            "total_harvested_pieces": total_pieces,
            "total_documented_losses_kg": round(total_losses, 2),
            "is_final_harvested": any(h.harvest_type == "FINAL" for h in harvests),
            "records": [self._harvest_to_dict(h) for h in harvests],
        }

    def get_batch_lifecycle(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Compile complete batch lifecycle tracking including stocking, growth, feed, mortalities, harvest readiness, and financial actuals."""
        batch = self.get_batch(batch_id)
        if not batch:
            return None

        farm_id = batch["farm_id"]
        pond_id = batch["pond_id"]
        now = datetime.now(timezone.utc)

        # 1. Growth samplings & consecutive ADG / SGR calculation
        samples = self.list_growth_samples(batch_id=batch_id)
        enhanced_samples = []
        latest_sample = None
        for i, s in enumerate(samples):
            s_dict = dict(s)
            s_dt = datetime.fromisoformat(str(s["sample_date"]).replace("Z", "+00:00"))
            if s_dt.tzinfo is None:
                s_dt = s_dt.replace(tzinfo=timezone.utc)
            days_ago = max(0, (now - s_dt).days)
            s_dict["days_ago"] = days_ago
            s_dict["confidence_label"] = "MEASURED" if days_ago <= 10 else "STALE"

            if i > 0:
                prev = samples[i - 1]
                prev_dt = datetime.fromisoformat(str(prev["sample_date"]).replace("Z", "+00:00"))
                if prev_dt.tzinfo is None:
                    prev_dt = prev_dt.replace(tzinfo=timezone.utc)
                t_diff = max(1, (s_dt - prev_dt).days)
                sgr_res = calculate_sgr(s["abw_g"], prev["abw_g"], t_diff)
                adg_res = calculate_adg(prev["abw_g"], s["abw_g"], t_diff)
                s_dict["sgr_pct_per_day"] = sgr_res.sgr_pct_per_day if sgr_res.is_valid else None
                s_dict["adg_g_per_day"] = adg_res.adg_g_per_day if adg_res.is_valid else None
            else:
                s_dict["sgr_pct_per_day"] = None
                s_dict["adg_g_per_day"] = None

            enhanced_samples.append(s_dict)
            latest_sample = s_dict

        # 2. Mortalities records for this batch
        mortality_orms = (
            self._session.query(MortalityRecordORM)
            .filter(
                MortalityRecordORM.farm_id == farm_id,
                MortalityRecordORM.batch_id == batch_id,
            )
            .order_by(MortalityRecordORM.timestamp.asc())
            .all()
        )
        total_mortality_count = sum(m.dead_count for m in mortality_orms)
        mortality_events = [
            {
                "mortality_id": m.mortality_id,
                "timestamp": m.timestamp.isoformat() if m.timestamp else None,
                "doc": m.doc,
                "dead_count": m.dead_count,
                "collection_method": m.collection_method,
                "suspected_reason": m.suspected_reason,
                "recorded_by": m.recorded_by,
                "notes": m.notes,
            }
            for m in mortality_orms
        ]

        cum_feed = self.get_cumulative_feed_kg(batch_id)
        harvest_summary = self.get_batch_harvest_summary(batch_id)

        # 3. Dynamic DOC calculation
        stock_dt_raw = str(batch["stocking_date"]).replace("Z", "+00:00")
        stock_dt = datetime.fromisoformat(stock_dt_raw)
        if stock_dt.tzinfo is None:
            stock_dt = stock_dt.replace(tzinfo=timezone.utc)
        as_of_date = None
        if batch.get("harvested_date"):
            hrv_dt_raw = str(batch["harvested_date"]).replace("Z", "+00:00")
            as_of_date = datetime.fromisoformat(hrv_dt_raw)
            if as_of_date.tzinfo is None:
                as_of_date = as_of_date.replace(tzinfo=timezone.utc)
        doc = calculate_dynamic_doc(stock_dt, as_of_date)

        # Determine lifecycle stage
        status = batch.get("status", "ACTIVE")
        if status == "CLOSED":
            stage = "CLOSED"
        elif status == "HARVESTED":
            stage = "HARVESTED"
        elif status == "PARTIALLY_HARVESTED":
            stage = "PARTIALLY_HARVESTED"
        elif doc <= 15:
            stage = "PL_ACCLIMATION"
        elif doc <= 45:
            stage = "NURSERY_JUVENILE"
        else:
            stage = "GROWOUT"

        # 4. Population & Biomass estimation
        pop_res = calculate_surviving_population_detail(
            initial_count=batch["initial_count"],
            cumulative_recorded_mortality=total_mortality_count or batch.get("cumulative_recorded_mortality", 0),
            cumulative_harvested_count=harvest_summary.get("total_harvested_pieces", 0),
            estimated_survival_pct=batch.get("estimated_survival_pct", 85.0),
        )

        current_abw_g = latest_sample["abw_g"] if latest_sample else batch.get("avg_body_weight_g", 0.05)
        biomass_detail = calculate_detailed_biomass(
            pond_id=pond_id,
            batch_id=batch_id,
            has_active_batch=status in ("ACTIVE", "PARTIALLY_HARVESTED"),
            initial_count=batch["initial_count"],
            avg_body_weight_g=current_abw_g,
            cumulative_recorded_mortality=total_mortality_count or batch.get("cumulative_recorded_mortality", 0),
            estimated_survival_pct=batch.get("estimated_survival_pct", 85.0),
            cumulative_partial_harvest_kg=harvest_summary["partial_harvest_kg"],
            days_since_sampling=latest_sample.get("days_ago") if latest_sample else None,
        )

        # 5. FCR
        fcr_res = calculate_fcr(
            cumulative_feed_kg=cum_feed,
            current_biomass_kg=biomass_detail.net_remaining_biomass_kg,
            initial_biomass_kg=batch.get("initial_biomass_kg", 7.5),
            harvested_biomass_kg=harvest_summary["total_harvested_kg"],
            calculation_period_label=f"Lifecycle DOC 1 to DOC {doc}",
        )

        # 6. Biosecurity Chemical Withdrawal Restrictions
        from apps.api.src.infrastructure.repositories.sql_health_repository import SQLHealthRepository
        health_repo = SQLHealthRepository(self._session)
        active_restrictions = health_repo.get_active_harvest_restrictions(farm_id, pond_id)
        is_withdrawal_held = len(active_restrictions) > 0

        # 7. Harvest Readiness Evaluation (strictly based on recorded samples and user targets)
        latest_sample_date_str = str(latest_sample["sample_date"]) if latest_sample else None
        days_since_samp = latest_sample.get("days_ago") if latest_sample else None
        latest_adg = latest_sample.get("adg_g_per_day") if latest_sample else None
        target_abw = batch.get("target_abw_g", 25.0)
        target_hrv_date_str = str(batch.get("target_harvest_date")) if batch.get("target_harvest_date") else None

        readiness = evaluate_harvest_readiness(
            batch_id=batch_id,
            pond_id=pond_id,
            status=status,
            target_abw_g=target_abw,
            current_abw_g=latest_sample["abw_g"] if latest_sample else None,
            latest_sample_date=latest_sample_date_str,
            days_since_sampling=days_since_samp,
            adg_g_per_day=latest_adg,
            target_harvest_date=target_hrv_date_str,
            is_withdrawal_held=is_withdrawal_held,
            withdrawal_hold_count=len(active_restrictions),
        )

        # 8. Financial Summary (Actual recorded sale prices, harvested quantities, and feed ledger costs only)
        feeding_logs = (
            self._session.query(FeedingLogORM)
            .filter(FeedingLogORM.farm_id == farm_id, FeedingLogORM.batch_id == batch_id)
            .all()
        )
        feed_costs_by_product: Dict[str, Optional[float]] = {}
        for flog in feeding_logs:
            if flog.product_id and flog.product_id not in feed_costs_by_product:
                receipts = (
                    self._session.query(
                        FeedInventoryTransactionORM.quantity_kg,
                        FeedInventoryTransactionORM.unit_price,
                    )
                    .filter(
                        FeedInventoryTransactionORM.farm_id == farm_id,
                        FeedInventoryTransactionORM.product_id == flog.product_id,
                        FeedInventoryTransactionORM.transaction_type == "RECEIPT",
                        FeedInventoryTransactionORM.unit_price.isnot(None),
                    )
                    .all()
                )
                tot_q = sum(r[0] for r in receipts if r[0] > 0)
                tot_c = sum(r[0] * r[1] for r in receipts if r[0] > 0 and r[1] is not None)
                if tot_q > 0:
                    feed_costs_by_product[flog.product_id] = tot_c / tot_q
                else:
                    feed_costs_by_product[flog.product_id] = None

        calc_feed_cost = 0.0
        costed_feed_kg = 0.0
        logs_with_cost_count = 0
        for flog in feeding_logs:
            cost_per_kg = feed_costs_by_product.get(flog.product_id)
            if cost_per_kg is not None:
                calc_feed_cost += flog.feed_kg * cost_per_kg
                costed_feed_kg += flog.feed_kg
                logs_with_cost_count += 1

        recorded_feed_cost = calc_feed_cost if logs_with_cost_count > 0 else None

        # Attributable recorded expense actuals from expense ledger
        batch_expenses = (
            self._session.query(FarmExpenseORM)
            .filter(
                FarmExpenseORM.farm_id == farm_id,
                FarmExpenseORM.batch_id == batch_id,
                FarmExpenseORM.status == "ACTIVE",
            )
            .all()
        )
        seed_costs = [e.amount for e in batch_expenses if e.category == "SEED_PL"]
        rec_seed_cost = sum(seed_costs) if seed_costs else None

        treatment_costs = [e.amount for e in batch_expenses if e.category == "CHEMICAL_AND_TREATMENT"]
        rec_treatment_cost = sum(treatment_costs) if treatment_costs else None

        energy_costs = [e.amount for e in batch_expenses if e.category == "ELECTRICITY_ENERGY"]
        rec_energy_cost = sum(energy_costs) if energy_costs else None

        other_costs = [e.amount for e in batch_expenses if e.category in ("LABOUR", "MAINTENANCE_REPAIR", "OTHER")]
        rec_other_cost = sum(other_costs) if other_costs else None

        financial_summary = calculate_batch_financial_summary(
            batch_id=batch_id,
            total_harvested_kg=harvest_summary["total_harvested_kg"],
            partial_harvest_kg=harvest_summary["partial_harvest_kg"],
            final_harvest_kg=harvest_summary["final_harvest_kg"],
            harvest_events_count=harvest_summary["harvest_count"],
            total_revenue=harvest_summary.get("total_revenue"),
            total_documented_losses_kg=harvest_summary.get("total_documented_losses_kg", 0.0),
            cumulative_feed_kg=cum_feed,
            costed_feed_kg=costed_feed_kg,
            recorded_feed_cost=recorded_feed_cost,
            recorded_seed_cost=rec_seed_cost,
            recorded_treatment_cost=rec_treatment_cost,
            recorded_energy_cost=rec_energy_cost,
            other_recorded_costs=rec_other_cost,
            is_active_crop=status in ("ACTIVE", "GROWOUT", "PARTIALLY_HARVESTED"),
        )

        return {
            "batch": batch,
            "lifecycle_stage": stage,
            "status": status,
            "days_of_culture": doc,
            "stocking": {
                "species": batch["species"],
                "initial_count": batch["initial_count"],
                "stocking_date": batch["stocking_date"],
                "initial_biomass_kg": batch["initial_biomass_kg"],
                "seed_supplier": batch["seed_supplier"],
                "seed_quality_notes": batch["seed_quality_notes"],
                "confidence_label": "RECORDED",
            },
            "population": {
                **pop_res.model_dump(),
                "confidence_label": "MEASURED" if total_mortality_count > 0 else "CALCULATED_ESTIMATE",
            },
            "biomass_detail": {
                **biomass_detail.model_dump(),
                "confidence_label": biomass_detail.status_quality,
            },
            "cumulative_feed_kg": cum_feed,
            "feed_confidence_label": "RECORDED",
            "fcr_analysis": fcr_res.model_dump(),
            "growth_samplings": enhanced_samples,
            "mortality_summary": {
                "total_recorded_dead": total_mortality_count,
                "mortality_events_count": len(mortality_events),
                "events": mortality_events,
                "confidence_label": "RECORDED" if total_mortality_count > 0 else "MEASURED",
            },
            "harvest_readiness": readiness.model_dump(),
            "harvest_summary": harvest_summary,
            "attributed_expenses": [
                {
                    "expense_id": e.expense_id,
                    "category": e.category,
                    "amount": e.amount,
                    "supplier": e.supplier,
                    "invoice_number": e.invoice_number,
                    "transaction_date": e.transaction_date.isoformat() if e.transaction_date else None,
                }
                for e in batch_expenses
            ],
            "financial_summary": financial_summary.model_dump(),
        }

    def list_batches_readiness(
        self,
        farm_id: str,
        pond_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List all batches across a farm with lifecycle progress, stocking counts, mortality, and harvest readiness."""
        query = self._session.query(StockingBatchORM).filter(StockingBatchORM.farm_id == farm_id)
        if pond_id:
            query = query.filter(StockingBatchORM.pond_id == pond_id)
        if status:
            query = query.filter(StockingBatchORM.status == status)

        batches = query.order_by(StockingBatchORM.stocking_date.desc()).all()
        results: List[Dict[str, Any]] = []

        now = datetime.now(timezone.utc)
        from apps.api.src.infrastructure.repositories.sql_health_repository import SQLHealthRepository
        health_repo = SQLHealthRepository(self._session)

        for b_orm in batches:
            b_id = b_orm.batch_id
            p_id = b_orm.pond_id

            # Dynamic DOC
            stock_dt = b_orm.stocking_date if b_orm.stocking_date.tzinfo else b_orm.stocking_date.replace(tzinfo=timezone.utc)
            as_of = b_orm.harvested_date if b_orm.harvested_date else None
            if as_of and as_of.tzinfo is None:
                as_of = as_of.replace(tzinfo=timezone.utc)
            doc = calculate_dynamic_doc(stock_dt, as_of)

            # Mortalities
            mort_records = (
                self._session.query(MortalityRecordORM.dead_count)
                .filter(MortalityRecordORM.farm_id == farm_id, MortalityRecordORM.batch_id == b_id)
                .all()
            )
            total_mort = sum(m[0] for m in mort_records) if mort_records else (b_orm.cumulative_recorded_mortality or 0)

            # Harvests
            harvests = (
                self._session.query(HarvestRecordORM)
                .filter(HarvestRecordORM.farm_id == farm_id, HarvestRecordORM.batch_id == b_id)
                .all()
            )
            part_kg = sum(h.harvested_weight_kg for h in harvests if h.harvest_type == "PARTIAL")
            final_kg = sum(h.harvested_weight_kg for h in harvests if h.harvest_type == "FINAL")
            total_hrv_kg = round(part_kg + final_kg, 2)
            total_hrv_pieces = sum(h.count_pieces or 0 for h in harvests)
            total_rev = sum(h.total_revenue or 0.0 for h in harvests)

            # Surviving Population
            pop_res = calculate_surviving_population_detail(
                initial_count=b_orm.initial_count,
                cumulative_recorded_mortality=total_mort,
                cumulative_harvested_count=total_hrv_pieces,
                estimated_survival_pct=b_orm.estimated_survival_pct or 85.0,
            )

            # Latest sample
            latest_sample = self.get_latest_growth_sample(b_id)
            latest_abw = latest_sample["abw_g"] if latest_sample else None
            days_since_sample = None
            sample_freshness = "NEEDS_DATA"
            if latest_sample and latest_sample.get("sample_date"):
                s_dt_raw = str(latest_sample["sample_date"]).replace("Z", "+00:00")
                s_dt = datetime.fromisoformat(s_dt_raw)
                if s_dt.tzinfo is None:
                    s_dt = s_dt.replace(tzinfo=timezone.utc)
                days_since_sample = max(0, (now - s_dt).days)
                sample_freshness = "MEASURED" if days_since_sample <= 10 else "STALE"

            # Growth metrics
            adg = latest_sample.get("adg_g_per_day") if latest_sample else None
            current_biomass_kg = round(
                max(0.0, (pop_res.surviving_count * (latest_abw or b_orm.avg_body_weight_g or 0.05)) / 1000.0)
                - part_kg,
                2
            )

            # Withdrawal check
            active_holds = health_repo.get_active_harvest_restrictions(farm_id, p_id)
            is_held = len(active_holds) > 0

            # Readiness
            target_abw = b_orm.target_abw_g or 25.0
            target_hrv_str = b_orm.target_harvest_date.strftime("%Y-%m-%d") if b_orm.target_harvest_date else None
            readiness = evaluate_harvest_readiness(
                batch_id=b_id,
                pond_id=p_id,
                status=b_orm.status,
                target_abw_g=target_abw,
                current_abw_g=latest_abw,
                latest_sample_date=str(latest_sample["sample_date"]) if latest_sample else None,
                days_since_sampling=days_since_sample,
                adg_g_per_day=adg,
                target_harvest_date=target_hrv_str,
                is_withdrawal_held=is_held,
                withdrawal_hold_count=len(active_holds),
            )

            # Feed
            cum_feed = self.get_cumulative_feed_kg(b_id)

            # Lifecycle Stage
            st = b_orm.status
            if st in ("CLOSED", "HARVESTED", "PARTIALLY_HARVESTED"):
                stage = st
            elif doc <= 15:
                stage = "PL_ACCLIMATION"
            elif doc <= 45:
                stage = "NURSERY_JUVENILE"
            else:
                stage = "GROWOUT"

            results.append({
                "batch_id": b_id,
                "farm_id": farm_id,
                "pond_id": p_id,
                "species": b_orm.species,
                "status": st,
                "lifecycle_stage": stage,
                "stocking_date": b_orm.stocking_date.isoformat() if b_orm.stocking_date else None,
                "days_of_culture": doc,
                "initial_count": b_orm.initial_count,
                "cumulative_recorded_mortality": total_mort,
                "surviving_count": pop_res.surviving_count,
                "survival_pct": pop_res.survival_pct,
                "population_estimation_method": pop_res.estimation_method,
                "latest_abw_g": latest_abw,
                "latest_sample_date": str(latest_sample["sample_date"]) if latest_sample else None,
                "days_since_sample": days_since_sample,
                "sample_freshness_label": sample_freshness,
                "adg_g_per_day": adg,
                "estimated_biomass_kg": max(0.0, current_biomass_kg),
                "biomass_confidence_label": "CALCULATED_ESTIMATE" if sample_freshness == "MEASURED" else ("STALE" if sample_freshness == "STALE" else "BASELINE_ESTIMATE"),
                "target_abw_g": target_abw,
                "target_harvest_date": target_hrv_str,
                "harvest_readiness": readiness.model_dump(),
                "partial_harvest_kg": part_kg,
                "final_harvest_kg": final_kg,
                "total_harvested_kg": total_hrv_kg,
                "total_revenue": round(total_rev, 2) if total_rev > 0 else None,
                "cumulative_feed_kg": cum_feed,
                "is_withdrawal_held": is_held,
            })

        return results

    def get_batch_economics(self, batch_id: str, farm_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieve verified batch economics, attributable costs, and profitability completeness status."""
        batch = self.get_batch(batch_id)
        if not batch:
            return None
        if farm_id and batch.get("farm_id") != farm_id:
            return None

        actual_farm_id = batch["farm_id"]
        pond_id = batch["pond_id"]
        status = batch.get("status", "ACTIVE")
        is_active = status in ("ACTIVE", "GROWOUT", "PARTIALLY_HARVESTED")

        # 1. Harvest Actuals
        harvest_summary = self.get_batch_harvest_summary(batch_id)

        # 2. Cumulative Feed and Feed Cost Attribution
        cum_feed = self.get_cumulative_feed_kg(batch_id)
        feeding_logs = (
            self._session.query(FeedingLogORM)
            .filter(FeedingLogORM.farm_id == actual_farm_id, FeedingLogORM.batch_id == batch_id)
            .all()
        )

        feed_costs_by_product: Dict[str, Optional[float]] = {}
        for flog in feeding_logs:
            if flog.product_id and flog.product_id not in feed_costs_by_product:
                receipts = (
                    self._session.query(
                        FeedInventoryTransactionORM.quantity_kg,
                        FeedInventoryTransactionORM.unit_price,
                    )
                    .filter(
                        FeedInventoryTransactionORM.farm_id == actual_farm_id,
                        FeedInventoryTransactionORM.product_id == flog.product_id,
                        FeedInventoryTransactionORM.transaction_type == "RECEIPT",
                        FeedInventoryTransactionORM.unit_price.isnot(None),
                    )
                    .all()
                )
                tot_q = sum(r[0] for r in receipts if r[0] > 0)
                tot_c = sum(r[0] * r[1] for r in receipts if r[0] > 0 and r[1] is not None)
                if tot_q > 0:
                    feed_costs_by_product[flog.product_id] = tot_c / tot_q
                else:
                    feed_costs_by_product[flog.product_id] = None

        calc_feed_cost = 0.0
        costed_feed_kg = 0.0
        logs_with_cost_count = 0
        for flog in feeding_logs:
            cost_per_kg = feed_costs_by_product.get(flog.product_id)
            if cost_per_kg is not None:
                calc_feed_cost += flog.feed_kg * cost_per_kg
                costed_feed_kg += flog.feed_kg
                logs_with_cost_count += 1

        recorded_feed_cost = calc_feed_cost if logs_with_cost_count > 0 else None

        # 3. Attributable recorded expense actuals from expense ledger
        batch_expenses = (
            self._session.query(FarmExpenseORM)
            .filter(
                FarmExpenseORM.farm_id == actual_farm_id,
                FarmExpenseORM.batch_id == batch_id,
                FarmExpenseORM.status == "ACTIVE",
            )
            .all()
        )
        seed_costs = [e.amount for e in batch_expenses if e.category == "SEED_PL"]
        rec_seed_cost = sum(seed_costs) if seed_costs else None

        treatment_costs = [e.amount for e in batch_expenses if e.category == "CHEMICAL_AND_TREATMENT"]
        rec_treatment_cost = sum(treatment_costs) if treatment_costs else None

        energy_costs = [e.amount for e in batch_expenses if e.category == "ELECTRICITY_ENERGY"]
        rec_energy_cost = sum(energy_costs) if energy_costs else None

        other_costs = [e.amount for e in batch_expenses if e.category in ("LABOUR", "MAINTENANCE_REPAIR", "OTHER")]
        rec_other_cost = sum(other_costs) if other_costs else None

        # 4. Financial Summary & Completeness Calculation
        financial_summary = calculate_batch_financial_summary(
            batch_id=batch_id,
            total_harvested_kg=harvest_summary["total_harvested_kg"],
            partial_harvest_kg=harvest_summary["partial_harvest_kg"],
            final_harvest_kg=harvest_summary["final_harvest_kg"],
            harvest_events_count=harvest_summary["harvest_count"],
            total_revenue=harvest_summary.get("total_revenue"),
            total_documented_losses_kg=harvest_summary.get("total_documented_losses_kg", 0.0),
            cumulative_feed_kg=cum_feed,
            costed_feed_kg=costed_feed_kg,
            recorded_feed_cost=recorded_feed_cost,
            recorded_seed_cost=rec_seed_cost,
            recorded_treatment_cost=rec_treatment_cost,
            recorded_energy_cost=rec_energy_cost,
            other_recorded_costs=rec_other_cost,
            is_active_crop=is_active,
        )

        return {
            "batch_id": batch_id,
            "farm_id": actual_farm_id,
            "pond_id": pond_id,
            "species": batch.get("species"),
            "status": status,
            "stocking_date": batch.get("stocking_date"),
            "initial_count": batch.get("initial_count"),
            "initial_biomass_kg": batch.get("initial_biomass_kg"),
            "seed_supplier": batch.get("seed_supplier"),
            "harvest_summary": harvest_summary,
            "attributed_expenses": [
                {
                    "expense_id": e.expense_id,
                    "category": e.category,
                    "amount": e.amount,
                    "supplier": e.supplier,
                    "invoice_number": e.invoice_number,
                    "transaction_date": e.transaction_date.isoformat() if e.transaction_date else None,
                }
                for e in batch_expenses
            ],
            "financial_summary": financial_summary.model_dump(),
        }

    def get_farm_economics_summary(
        self, farm_id: str, pond_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Aggregate verified economics across farm or pond batches without assuming unrecorded expenses."""
        query = self._session.query(StockingBatchORM).filter(StockingBatchORM.farm_id == farm_id)
        if pond_id:
            query = query.filter(StockingBatchORM.pond_id == pond_id)

        batches = query.order_by(StockingBatchORM.stocking_date.desc()).all()
        summaries: List[BatchFinancialSummary] = []
        batch_details: List[Dict[str, Any]] = []

        for b in batches:
            econ = self.get_batch_economics(b.batch_id, farm_id=farm_id)
            if econ:
                fin_dict = econ["financial_summary"]
                summaries.append(BatchFinancialSummary(**fin_dict))
                batch_details.append(econ)

        rollup = calculate_farm_economics_summary(
            farm_id=farm_id,
            pond_id=pond_id,
            batch_summaries=summaries,
        )
        res = rollup.model_dump()
        res["batch_details"] = batch_details

        # Farm-wide expenses distribution (strictly distinct from batch-attributable costs)
        exp_query = self._session.query(FarmExpenseORM).filter(
            FarmExpenseORM.farm_id == farm_id,
            FarmExpenseORM.status == "ACTIVE",
        )
        if pond_id:
            exp_query = exp_query.filter(FarmExpenseORM.pond_id == pond_id)
        farm_expenses = exp_query.all()

        unattributed_exp_amount = sum(e.amount for e in farm_expenses if e.batch_id is None)
        attributed_exp_amount = sum(e.amount for e in farm_expenses if e.batch_id is not None)
        total_farm_exp_amount = sum(e.amount for e in farm_expenses)

        res["unattributed_farm_wide_expenses_amount"] = round(unattributed_exp_amount, 2)
        res["attributed_batch_expenses_amount"] = round(attributed_exp_amount, 2)
        res["total_farm_recorded_expenses_amount"] = round(total_farm_exp_amount, 2)
        res["expenses_recorded_count"] = len(farm_expenses)
        return res



