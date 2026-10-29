"""Growth and Production Intelligence Service.

Coordinates:
- Multi-batch tracking per pond without overwriting historical batches
- Growth sampling recording and trend analysis
- Unit-safe ADG and True Production Net-Gain FCR vs Apparent FCR
- Harvest projections and revenue estimation
- Farm-level production summary rollups with stale-sample indicators
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from apps.api.src.domain.growth_engine import (
    calculate_adg,
    calculate_dynamic_doc,
    calculate_estimated_biomass,
    calculate_fcr,
    calculate_harvest_projections,
    calculate_sgr,
    calculate_surviving_population_detail,
    calculate_detailed_biomass,
    calculate_advanced_harvest_forecast,
)
from apps.api.src.infrastructure.repositories.sql_pond_records_repository import SQLPondRecordsRepository
from apps.api.src.infrastructure.repositories.sql_pond_repository import SQLPondRepository


class GrowthProductionService:
    """Application service for shrimp production intelligence, growth tracking, and harvest planning."""

    def __init__(self, session: Session) -> None:
        self._session = session
        self._records_repo = SQLPondRecordsRepository(session)
        self._pond_repo = SQLPondRepository(session)

    # -------------------------------------------------------------------------
    # Batch Management
    # -------------------------------------------------------------------------

    def create_or_update_batch(self, batch_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a new batch or update existing parameters."""
        return self._records_repo.save_batch(batch_data)

    def close_or_harvest_batch(
        self,
        batch_id: str,
        status: str = "HARVESTED",
        harvested_biomass_kg: Optional[float] = None,
        harvest_notes: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """Transition batch to HARVESTED or CLOSED preserving historical records."""
        return self._records_repo.close_or_harvest_batch(
            batch_id=batch_id,
            status=status,
            harvested_biomass_kg=harvested_biomass_kg,
            harvest_notes=harvest_notes,
        )

    def list_batches(
        self, farm_id: str, pond_id: Optional[str] = None, status: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Retrieve batches history for authorized farm."""
        return self._records_repo.list_batches(farm_id=farm_id, pond_id=pond_id, status=status)

    # -------------------------------------------------------------------------
    # Sampling & Growth
    # -------------------------------------------------------------------------

    def record_sampling(self, sample_data: Dict[str, Any]) -> Dict[str, Any]:
        """Record physical or manual sampling entry with automatic ADG calculation."""
        return self._records_repo.record_growth_sample(sample_data)

    def list_samplings(
        self,
        batch_id: Optional[str] = None,
        pond_id: Optional[str] = None,
        farm_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Retrieve chronological sampling data for growth charts scoped by farm."""
        return self._records_repo.list_growth_samples(batch_id=batch_id, pond_id=pond_id, farm_id=farm_id)

    def get_pond_production_intelligence(self, farm_id: str, pond_id: str) -> Dict[str, Any]:
        """Get comprehensive intelligence bundle for single pond."""
        summary = self._records_repo.get_pond_production_summary(farm_id=farm_id, pond_id=pond_id)
        if not summary.get("has_active_batch"):
            # Seed default if uninitialized
            pond = self._pond_repo.get(farm_id, pond_id)
            initial_count = pond.stocking_count if pond else 150_000
            doc = pond.days_of_culture if pond else 35
            self._records_repo.seed_default_stocking_for_pond(farm_id, pond_id, initial_count=initial_count, doc=doc)
            summary = self._records_repo.get_pond_production_summary(farm_id=farm_id, pond_id=pond_id)

        # Check stale sampling indicator (sample older than 10 days)
        now = datetime.now(timezone.utc)
        is_sample_stale = False
        days_since_sample = None
        latest = summary.get("latest_sample")
        if latest and latest.get("sample_date"):
            sample_date_raw = str(latest["sample_date"]).replace("Z", "+00:00")
            sample_dt = datetime.fromisoformat(sample_date_raw)
            if sample_dt.tzinfo is None:
                sample_dt = sample_dt.replace(tzinfo=timezone.utc)
            days_since_sample = (now - sample_dt).days
            if days_since_sample > 10:
                is_sample_stale = True
        elif not latest:
            is_sample_stale = True

        summary["is_sample_stale"] = is_sample_stale
        summary["days_since_sample"] = days_since_sample
        return summary

    # -------------------------------------------------------------------------
    # Feeding Management & Advisories
    # -------------------------------------------------------------------------

    def record_feeding(
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
    ) -> Dict[str, Any]:
        """Record manual feeding application with validations and duplicate protection."""
        return self._records_repo.log_feeding(
            farm_id=farm_id,
            pond_id=pond_id,
            feed_kg=feed_kg,
            feed_type=feed_type,
            feed_time_label=feed_time_label,
            tray_observation=tray_observation,
            notes=notes,
            recorded_by=recorded_by,
            batch_id=batch_id,
            feeding_event_count=feeding_event_count,
            timestamp=timestamp,
            product_id=product_id,
        )

    def list_feeding_history(
        self,
        farm_id: str,
        pond_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List feeding logs with optional date-range and batch filters."""
        return self._records_repo.list_feeding_logs(
            farm_id=farm_id,
            pond_id=pond_id,
            batch_id=batch_id,
            start_date=start_date,
            end_date=end_date,
            limit=limit,
        )

    def get_pond_feeding_summary(
        self,
        farm_id: str,
        pond_id: str,
        batch_id: Optional[str] = None,
        days: int = 14,
    ) -> Dict[str, Any]:
        """Get daily feeding summary, cumulative feed, moving averages, FCR, and operational advisories."""
        return self._records_repo.get_daily_feeding_summary(
            farm_id=farm_id,
            pond_id=pond_id,
            batch_id=batch_id,
            days=days,
        )

    def get_pond_feeding_advisories(
        self,
        farm_id: str,
        pond_id: str,
        batch_id: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """Get operational feeding advisories using validated data only."""
        return self._records_repo.evaluate_feeding_advisories(
            farm_id=farm_id,
            pond_id=pond_id,
            batch_id=batch_id,
        )

    # -------------------------------------------------------------------------
    # Farm-Level Production Summary Rollup
    # -------------------------------------------------------------------------

    def get_farm_production_summary(self, farm_id: str) -> Dict[str, Any]:
        """Aggregate production metrics across all active ponds on the farm.
        
        Isolates active production batches and computes total biomass, cumulative feed,
        weighted average ABW, and overall production FCR.
        """
        all_ponds = self._pond_repo.list(farm_id=farm_id)
        total_biomass_kg = 0.0
        total_initial_biomass_kg = 0.0
        total_cumulative_feed_kg = 0.0
        total_harvested_biomass_kg = 0.0
        total_live_shrimp = 0
        sum_abw = 0.0
        sum_doc = 0
        active_batch_count = 0
        stale_sampling_ponds = []
        pond_summaries = []

        for p in all_ponds:
            summary = self.get_pond_production_intelligence(farm_id, p.pond_id)
            if summary.get("has_active_batch"):
                batch = summary["batch"]
                active_batch_count += 1
                b_kg = batch.get("estimated_biomass_kg", 0.0)
                init_b = batch.get("initial_biomass_kg", 7.5)
                feed_kg = summary.get("cumulative_feed_kg", 0.0)
                harvested_b = summary.get("harvest_summary", {}).get("total_harvested_kg", 0.0) or (batch.get("harvested_biomass_kg") or 0.0)
                abw = batch.get("avg_body_weight_g", 0.0)
                doc = batch.get("days_of_culture", 1)
                pop = summary.get("biomass_detail", {}).get("surviving_count") or int(batch.get("initial_count", 150000) * (batch.get("estimated_survival_pct", 82) / 100.0))

                total_biomass_kg += b_kg
                total_initial_biomass_kg += init_b
                total_cumulative_feed_kg += feed_kg
                total_harvested_biomass_kg += harvested_b
                total_live_shrimp += pop
                sum_abw += abw
                sum_doc += doc

                if summary.get("is_sample_stale"):
                    stale_sampling_ponds.append(p.pond_id)

                pond_summaries.append({
                    "pond_id": p.pond_id,
                    "batch_id": batch.get("batch_id"),
                    "doc": doc,
                    "abw_g": abw,
                    "adg_g_per_day": summary.get("adg_g_per_day"),
                    "sgr_pct_per_day": summary.get("sgr_pct_per_day"),
                    "estimated_survival_pct": batch.get("estimated_survival_pct"),
                    "estimated_biomass_kg": b_kg,
                    "cumulative_feed_kg": feed_kg,
                    "harvested_biomass_kg": harvested_b,
                    "production_fcr": summary.get("fcr_analysis", {}).get("production_fcr"),
                    "is_sample_stale": summary.get("is_sample_stale"),
                    "quality_status": summary.get("biomass_detail", {}).get("status_quality", "UNVALIDATED_BASELINE"),
                })

        avg_abw = round(sum_abw / active_batch_count, 2) if active_batch_count > 0 else 0.0
        avg_doc = int(round(sum_doc / active_batch_count)) if active_batch_count > 0 else 0

        # Farm-wide FCR
        farm_fcr_res = calculate_fcr(
            cumulative_feed_kg=total_cumulative_feed_kg,
            current_biomass_kg=total_biomass_kg,
            initial_biomass_kg=total_initial_biomass_kg,
            harvested_biomass_kg=total_harvested_biomass_kg,
            calculation_period_label="Farm Active Batches Aggregated",
        )

        return {
            "farm_id": farm_id,
            "active_batch_count": active_batch_count,
            "total_estimated_biomass_kg": round(total_biomass_kg, 2),
            "total_live_shrimp_count": total_live_shrimp,
            "total_cumulative_feed_kg": round(total_cumulative_feed_kg, 2),
            "total_harvested_biomass_kg": round(total_harvested_biomass_kg, 2),
            "farm_average_abw_g": avg_abw,
            "farm_average_doc": avg_doc,
            "farm_production_fcr": farm_fcr_res.model_dump(),
            "stale_sampling_pond_count": len(stale_sampling_ponds),
            "stale_sampling_ponds": stale_sampling_ponds,
            "ponds": pond_summaries,
            "biomass_estimation_notice": "All biomass figures are mathematical estimates derived from sample ABW and survival fraction, not direct whole-pond weigh-ins.",
        }

    # -------------------------------------------------------------------------
    # Dedicated Biomass & Harvest Forecasting
    # -------------------------------------------------------------------------

    def get_biomass_estimation(self, farm_id: str, pond_id: str) -> Dict[str, Any]:
        """Dedicated biomass estimation service with quality status and bounds checking."""
        summary = self.get_pond_production_intelligence(farm_id, pond_id)
        if not summary.get("has_active_batch"):
            return {
                "pond_id": pond_id,
                "has_active_batch": False,
                "status_quality": "NEEDS_DATA",
                "biomass_detail": None,
                "notice": "No active batch for this pond.",
            }
        return {
            "pond_id": pond_id,
            "has_active_batch": True,
            "batch_id": summary.get("batch", {}).get("batch_id"),
            "status_quality": summary.get("biomass_detail", {}).get("status_quality", "UNVALIDATED_BASELINE"),
            "biomass_detail": summary.get("biomass_detail"),
            "latest_sample": summary.get("latest_sample"),
            "days_since_sample": summary.get("days_since_sample"),
            "is_sample_stale": summary.get("is_sample_stale"),
        }

    def get_harvest_forecast(self, farm_id: str, pond_id: str) -> Dict[str, Any]:
        """Advisory harvest forecasting using validated batch data and growth trajectory."""
        summary = self.get_pond_production_intelligence(farm_id, pond_id)
        if not summary.get("has_active_batch"):
            return {
                "pond_id": pond_id,
                "has_active_batch": False,
                "status_label": "NEEDS_DATA",
                "forecast": None,
                "advisory_notes": ["No active batch found for pond."],
            }
        return {
            "pond_id": pond_id,
            "has_active_batch": True,
            "batch_id": summary.get("batch", {}).get("batch_id"),
            "forecast": summary.get("advanced_harvest_forecast"),
            "adg_g_per_day": summary.get("adg_g_per_day"),
            "sgr_pct_per_day": summary.get("sgr_pct_per_day"),
            "harvest_summary": summary.get("harvest_summary"),
        }

    # -------------------------------------------------------------------------
    # Harvest Recording & Ledger Workflows
    # -------------------------------------------------------------------------

    def record_harvest(self, harvest_data: Dict[str, Any]) -> Dict[str, Any]:
        """Record partial or final harvest with yield, grading, revenue, and idempotency protection."""
        return self._records_repo.record_harvest(harvest_data)

    def list_harvests(
        self,
        farm_id: str,
        pond_id: Optional[str] = None,
        batch_id: Optional[str] = None,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """List historical harvest event records."""
        return self._records_repo.list_harvest_records(
            farm_id=farm_id, pond_id=pond_id, batch_id=batch_id, limit=limit
        )

    def get_batch_lifecycle(self, batch_id: str) -> Optional[Dict[str, Any]]:
        """Get comprehensive lifecycle tracking for a specific batch."""
        return self._records_repo.get_batch_lifecycle(batch_id)

    def list_batches_readiness(
        self,
        farm_id: str,
        pond_id: Optional[str] = None,
        status: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """List batches across farm or pond with calculated harvest readiness and confidence states."""
        return self._records_repo.list_batches_readiness(farm_id=farm_id, pond_id=pond_id, status=status)

    def get_batch_economics(self, batch_id: str, farm_id: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Retrieve verified batch economics, attributable costs, and profitability completeness status."""
        return self._records_repo.get_batch_economics(batch_id=batch_id, farm_id=farm_id)

    def get_farm_economics_summary(
        self, farm_id: str, pond_id: Optional[str] = None
    ) -> Dict[str, Any]:
        """Retrieve farm-level economics and attributable profitability rollup."""
        return self._records_repo.get_farm_economics_summary(farm_id=farm_id, pond_id=pond_id)



