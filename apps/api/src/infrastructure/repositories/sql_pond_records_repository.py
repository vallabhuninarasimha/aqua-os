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
)
from apps.api.src.infrastructure.models import FeedingLogORM, GrowthSamplingORM, StockingBatchORM


class SQLPondRecordsRepository:
    """Repository for pond biological records: multiple batches, sampling, biomass, and feeding."""

    def __init__(self, session: Session) -> None:
        self._session = session

    # -------------------------------------------------------------------------
    # Batch Lifecycle & Multiple Batches Management
    # -------------------------------------------------------------------------

    def get_active_batch(self, pond_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve current ACTIVE stocking batch for a pond."""
        orm = (
            self._session.query(StockingBatchORM)
            .filter(StockingBatchORM.pond_id == pond_id, StockingBatchORM.status == "ACTIVE")
            .order_by(StockingBatchORM.stocking_date.desc())
            .first()
        )
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
        limit: int = 100,
    ) -> List[Dict[str, Any]]:
        """List historical sampling points sorted chronologically."""
        query = self._session.query(GrowthSamplingORM)
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
    ) -> Dict[str, Any]:
        """Record manual feeding application associated with the active batch.

        Validates positive feed weight, non-zero event count, batch association,
        and prevents accidental duplicate submissions within a 5-minute window.
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
            active_batch = self.get_active_batch(pond_id)
            batch_id = active_batch["batch_id"] if active_batch else None

        # Duplicate submission protection: check for identical submission within a 5-minute window
        window_start = now - timedelta(minutes=5)
        window_end = now + timedelta(minutes=5)
        duplicate = (
            self._session.query(FeedingLogORM)
            .filter(
                FeedingLogORM.farm_id == farm_id,
                FeedingLogORM.pond_id == pond_id,
                FeedingLogORM.batch_id == batch_id,
                FeedingLogORM.feed_time_label == feed_time_label,
                FeedingLogORM.feed_type == feed_type,
                FeedingLogORM.feed_kg == feed_kg,
                FeedingLogORM.timestamp >= window_start,
                FeedingLogORM.timestamp <= window_end,
            )
            .first()
        )
        if duplicate:
            raise ValueError(
                f"Accidental duplicate feeding submission detected: an identical {feed_kg} kg entry for slot '{feed_time_label}' was logged at {duplicate.timestamp.isoformat()}."
            )

        orm = FeedingLogORM(
            farm_id=farm_id,
            pond_id=pond_id,
            batch_id=batch_id,
            timestamp=now,
            feed_type=feed_type,
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
        self._session.commit()
        return self._feeding_to_dict(orm)

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
        batch = self.get_active_batch(pond_id)
        if not batch:
            return {"has_active_batch": False, "pond_id": pond_id}

        batch_id = batch["batch_id"]
        samples = self.list_growth_samples(batch_id=batch_id)
        latest_sample = samples[-1] if samples else None
        prev_sample = samples[-2] if len(samples) >= 2 else None

        cumulative_feed = self.get_cumulative_feed_kg(batch_id)

        # ADG
        current_adg = latest_sample["adg_g_per_day"] if latest_sample else None

        # FCR calculation
        fcr_result = calculate_fcr(
            cumulative_feed_kg=cumulative_feed,
            current_biomass_kg=batch["estimated_biomass_kg"],
            initial_biomass_kg=batch.get("initial_biomass_kg", 7.5),
            harvested_biomass_kg=batch.get("harvested_biomass_kg") or 0.0,
            calculation_period_label=f"DOC 1 to DOC {batch['days_of_culture']}",
        )

        # Harvest projection
        harvest_proj = calculate_harvest_projections(
            current_doc=batch["days_of_culture"],
            current_abw_g=batch["avg_body_weight_g"],
            current_estimated_biomass_kg=batch["estimated_biomass_kg"],
            current_estimated_population=int(batch["initial_count"] * (batch["estimated_survival_pct"] / 100.0)),
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
            "cumulative_feed_kg": cumulative_feed,
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
