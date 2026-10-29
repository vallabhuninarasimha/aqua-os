"""Daily Operations Planner Service for Aqua OS.

Translates cross-domain farm records into a prioritized pond-wise work queue
and farm daily operational summary.

Operates purely in read-only derivation mode:
- No automated equipment actuation or chemical dosing.
- Clearly distinguishes advisories from confirmed incidents.
- Explicitly flags missing evidence as data-quality tasks, never assumed incidents.
- Scoped strictly to authorized tenant farm.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from apps.api.src.domain.hardware_interfaces import PhysicalRunningState
from apps.api.src.infrastructure.models import AlertRecordORM, MortalityRecordORM, TelemetryORM
from apps.api.src.infrastructure.repositories.sql_pond_repository import SQLPondRepository
from apps.api.src.infrastructure.repositories.sql_telemetry_repository import SQLTelemetryRepository
from apps.api.src.infrastructure.repositories.sql_alert_repository import SQLAlertRepository
from apps.api.src.infrastructure.repositories.sql_pond_records_repository import SQLPondRecordsRepository
from apps.api.src.infrastructure.repositories.sql_feed_plan_repository import SQLFeedPlanRepository
from apps.api.src.infrastructure.repositories.sql_feed_inventory_repository import SQLFeedInventoryRepository
from apps.api.src.infrastructure.repositories.sql_aerator_repository import SQLAeratorRepository
from apps.api.src.infrastructure.repositories.sql_water_repository import SQLWaterRepository
from apps.api.src.services.growth_production_service import GrowthProductionService
from apps.api.src.services.health_service import HealthService
from apps.api.src.services.power_service import PowerMonitoringService
from apps.api.src.services.water_service import WaterManagementService


CONFIDENCE_EXPLANATIONS = {
    "MEASURED": "Direct telemetry sensor reading or physical scale weigh-in.",
    "RECORDED": "Operator-logged field event or delivery record submitted in farm registry.",
    "PLANNED": "Scheduled operational intent derived from approved management plans.",
    "CALCULATED_ESTIMATE": "Mathematical derivation based on recent field sampling (<= 10 days) and population estimates.",
    "STALE": "Data point exceeds standard freshness window (> 60s for telemetry, > 10 days for biological sampling).",
    "SIMULATED": "Synthetic edge test generator; not connected to physical pond hardware.",
    "BASELINE_ESTIMATE": "Derived strictly from initial stocking model assumptions without recent cast-net sampling.",
    "NEEDS_DATA": "Insufficient field measurements or unrecorded logs to verify actual state.",
    "UNVERIFIED": "Physical field condition is unverified on-site; software intent only.",
    "UNCONFIGURED": "Equipment or parameter has not been configured in farm database.",
    "UNAVAILABLE": "Historical records or telemetry data unavailable for the specified date.",
}


class DailyWorkItem(BaseModel):
    """Derived actionable task for daily operations personnel."""
    work_item_id: str
    farm_id: str
    pond_id: Optional[str] = None
    scope: str = "POND"  # "POND" or "FARM_WIDE"
    category: str  # ACTIVE_ALERT, TELEMETRY_DATA_QUALITY, HEALTH_MORTALITY, FEEDING_MANAGEMENT, GROWTH_SAMPLING, INFRASTRUCTURE_VERIFICATION, WATER_MANAGEMENT, CONTAINMENT_SAFETY
    priority: str  # EMERGENCY, CRITICAL, WARNING, INFO
    priority_score: int  # 4: EMERGENCY, 3: CRITICAL, 2: WARNING, 1: INFO
    title: str
    reason: str
    source_timestamp: Optional[str] = None
    recommended_action: str
    confidence_label: str
    confidence_tooltip: str
    status: str = "OPEN"
    is_advisory: bool = True
    physical_state_confirmed: bool = False


class DailyOperationsSummary(BaseModel):
    """Farm-level rollup of operational health, feeding completion, mortalities, and data quality."""
    evaluated_at: str
    farm_id: str
    target_date: str
    is_historical: bool
    total_open_items: int
    critical_items_count: int
    warning_items_count: int
    info_items_count: int
    feeding_summary: Dict[str, Any]
    health_summary: Dict[str, Any]
    telemetry_summary: Dict[str, Any]
    infrastructure_summary: Dict[str, Any]


class DailyOperationsPlan(BaseModel):
    """Comprehensive daily operations plan response bundle."""
    farm_id: str
    evaluated_at: str
    target_date: str
    is_historical: bool
    summary: DailyOperationsSummary
    work_items: List[DailyWorkItem]
    pond_work_queues: Dict[str, List[DailyWorkItem]]
    farm_directives: List[DailyWorkItem] = Field(default_factory=list)
    filter_options: Dict[str, Any]
    confidence_definitions: Dict[str, str] = Field(default_factory=lambda: CONFIDENCE_EXPLANATIONS)


class DailyOperationsPlannerService:
    """Coordinates derivation of daily operational tasks and progress summaries."""

    def __init__(self, session: Session):
        self._session = session
        self._pond_repo = SQLPondRepository(session)
        self._telemetry_repo = SQLTelemetryRepository(session)
        self._alert_repo = SQLAlertRepository(session)
        self._records_repo = SQLPondRecordsRepository(session)
        self._feed_plan_repo = SQLFeedPlanRepository(session)
        self._feed_inv_repo = SQLFeedInventoryRepository(session)
        self._aerator_repo = SQLAeratorRepository(session)
        self._water_repo = SQLWaterRepository(session)
        self._growth_service = GrowthProductionService(session)
        self._health_service = HealthService(session)
        self._power_service = PowerMonitoringService(session)
        self._water_service = WaterManagementService(session=session, water_repo=self._water_repo)

    def generate_daily_plan(self, farm_id: str, target_date: Optional[datetime] = None) -> DailyOperationsPlan:
        """Derive farm-scoped pond work queue and operational summary without mutating historical data."""
        now_utc = datetime.now(timezone.utc)
        if target_date is not None:
            target = target_date if target_date.tzinfo else target_date.replace(tzinfo=timezone.utc)
        else:
            target = now_utc

        day_start = target.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        is_historical = day_start.date() < now_utc.date()

        now_iso = now_utc.isoformat()
        target_iso = target.isoformat()
        date_str = day_start.strftime("%Y-%m-%d")

        all_ponds = self._pond_repo.list(farm_id=farm_id)
        real_pond_ids = {p.pond_id for p in all_ponds}

        outlets_map = {o["pond_id"]: o for o in self._water_repo.list_pond_outlet_statuses(farm_id=farm_id)}
        feed_plans_overview = self._feed_plan_repo.get_daily_farm_plan_overview(farm_id=farm_id, target_date=target)

        work_items: List[DailyWorkItem] = []
        severity_weight = {"EMERGENCY": 4, "CRITICAL": 3, "WARNING": 2, "ALERT": 2, "INFO": 1}

        # Index feed plans for target date by pond_id
        today_plans_by_pond: Dict[str, Dict[str, Any]] = {}
        for p in feed_plans_overview.get("plans", []):
            today_plans_by_pond[p["pond_id"]] = p

        # ---------------------------------------------------------------------
        # 1. Active Alerts / Historical Alerts Work Items
        # ---------------------------------------------------------------------
        if not is_historical:
            raw_alerts = self._alert_repo.get_active_alerts(farm_id=farm_id)
            latest_telemetry = self._telemetry_repo.get_all_latest_with_evaluations(farm_id=farm_id)
            for a in raw_alerts:
                raw_p_id = a.get("pond_id")
                if raw_p_id and raw_p_id in real_pond_ids:
                    item_pond_id = raw_p_id
                    item_scope = "POND"
                    title_prefix = f"Pond {raw_p_id}"
                else:
                    item_pond_id = None
                    item_scope = "FARM_WIDE"
                    title_prefix = "Farm-Wide Directives"

                rec = latest_telemetry.get(raw_p_id) if raw_p_id else None
                alert_conf = "UNVERIFIED"
                if rec:
                    pkt, _ = rec
                    pkt_time = pkt.timestamp if pkt.timestamp.tzinfo else pkt.timestamp.replace(tzinfo=timezone.utc)
                    if (now_utc - pkt_time).total_seconds() > 60.0:
                        alert_conf = "STALE"
                    elif pkt.is_simulated:
                        alert_conf = "SIMULATED"
                    else:
                        alert_conf = "MEASURED"

                sev = a.get("severity", "WARNING")
                raw_rec = a.get("recommended_action") or "Inspect pond condition and verify sensor reading"

                work_items.append(
                    DailyWorkItem(
                        work_item_id=f"item-{farm_id}-{item_pond_id or 'farm'}-alert-{a['alert_id']}",
                        farm_id=farm_id,
                        pond_id=item_pond_id,
                        scope=item_scope,
                        category="ACTIVE_ALERT",
                        priority=sev,
                        priority_score=severity_weight.get(sev, 2),
                        title=f"{title_prefix}: {a.get('alert_code', 'Active Alert')}",
                        reason=a.get("message", "Operational threshold alert triggered"),
                        source_timestamp=a.get("last_triggered_at"),
                        recommended_action=f"ADVISORY: {raw_rec}",
                        confidence_label=alert_conf,
                        confidence_tooltip=CONFIDENCE_EXPLANATIONS.get(alert_conf, ""),
                        status="OPEN",
                        is_advisory=True,
                        physical_state_confirmed=False,
                    )
                )
        else:
            # Historical date: Query alerts that were triggered or active on that specific date
            # Do NOT mix current live alerts into historical dates!
            hist_alerts_orm = (
                self._session.query(AlertRecordORM)
                .filter(
                    AlertRecordORM.farm_id == farm_id,
                    AlertRecordORM.first_triggered_at <= day_end,
                    (AlertRecordORM.resolved_at.is_(None) | (AlertRecordORM.resolved_at >= day_start)),
                    AlertRecordORM.first_triggered_at >= day_start - timedelta(days=1),
                )
                .all()
            )
            for a_orm in hist_alerts_orm:
                raw_p_id = a_orm.pond_id
                if raw_p_id and raw_p_id in real_pond_ids:
                    item_pond_id = raw_p_id
                    item_scope = "POND"
                    title_prefix = f"Pond {raw_p_id}"
                else:
                    item_pond_id = None
                    item_scope = "FARM_WIDE"
                    title_prefix = "Farm-Wide Directives"

                sev = a_orm.severity or "WARNING"
                raw_rec = a_orm.recommended_action or "Review historical incident response logs"

                work_items.append(
                    DailyWorkItem(
                        work_item_id=f"item-{farm_id}-{item_pond_id or 'farm'}-alert-{a_orm.alert_id}-{date_str}",
                        farm_id=farm_id,
                        pond_id=item_pond_id,
                        scope=item_scope,
                        category="ACTIVE_ALERT",
                        priority=sev,
                        priority_score=severity_weight.get(sev, 2),
                        title=f"{title_prefix}: Historical Alert ({a_orm.alert_code})",
                        reason=a_orm.message or "Historical threshold alert recorded on this date",
                        source_timestamp=a_orm.first_triggered_at.isoformat() if a_orm.first_triggered_at else date_str,
                        recommended_action=f"ADVISORY: {raw_rec}",
                        confidence_label="RECORDED",
                        confidence_tooltip=CONFIDENCE_EXPLANATIONS["RECORDED"],
                        status="OPEN",
                        is_advisory=True,
                        physical_state_confirmed=False,
                    )
                )

        # ---------------------------------------------------------------------
        # 2. Per-Pond Work Item Derivations
        # ---------------------------------------------------------------------
        live_telemetry_ponds_count = 0
        stale_or_missing_telemetry_count = 0
        total_mortalities_target_date = 0
        ponds_with_mortalities = 0
        active_withdrawals_count = 0

        # Query historical telemetry archive for pond presence if historical
        if is_historical:
            hist_telem_ponds_query = (
                self._session.query(TelemetryORM.pond_id)
                .filter(
                    TelemetryORM.farm_id == farm_id,
                    TelemetryORM.timestamp >= day_start,
                    TelemetryORM.timestamp < day_end,
                )
                .distinct()
                .all()
            )
            ponds_with_hist_telem = {r[0] for r in hist_telem_ponds_query}
            latest_telemetry = {}
        else:
            ponds_with_hist_telem = set()
            latest_telemetry = self._telemetry_repo.get_all_latest_with_evaluations(farm_id=farm_id)

        for pond in all_ponds:
            p_id = pond.pond_id
            rec = latest_telemetry.get(p_id) if not is_historical else None
            outlet_info = outlets_map.get(p_id, {})

            # -----------------------------------------------------------------
            # 2a. Telemetry & Data Quality
            # -----------------------------------------------------------------
            if is_historical:
                if p_id in ponds_with_hist_telem:
                    live_telemetry_ponds_count += 1
                else:
                    stale_or_missing_telemetry_count += 1
                    work_items.append(
                        DailyWorkItem(
                            work_item_id=f"item-{farm_id}-{p_id}-telem-hist-unavailable-{date_str}",
                            farm_id=farm_id,
                            pond_id=p_id,
                            scope="POND",
                            category="TELEMETRY_DATA_QUALITY",
                            priority="INFO",
                            priority_score=1,
                            title=f"Pond {p_id}: Historical Telemetry Unavailable for {date_str}",
                            reason=f"No sensor telemetry logs were archived for pond {p_id} on {date_str}",
                            source_timestamp=day_start.isoformat(),
                            recommended_action="ADVISORY: Historical date query. Telemetry archive is empty for this date.",
                            confidence_label="UNAVAILABLE",
                            confidence_tooltip=CONFIDENCE_EXPLANATIONS["UNAVAILABLE"],
                            status="OPEN",
                            is_advisory=True,
                            physical_state_confirmed=False,
                        )
                    )
            else:
                if not rec:
                    stale_or_missing_telemetry_count += 1
                    work_items.append(
                        DailyWorkItem(
                            work_item_id=f"item-{farm_id}-{p_id}-telem-missing",
                            farm_id=farm_id,
                            pond_id=p_id,
                            scope="POND",
                            category="TELEMETRY_DATA_QUALITY",
                            priority="WARNING",
                            priority_score=2,
                            title=f"Pond {p_id}: Missing Edge Telemetry",
                            reason="No sensor telemetry packets have been received for this pond in edge gateway logs",
                            source_timestamp=now_iso,
                            recommended_action="ADVISORY: Inspect physical multi-parameter probe, RS-485 Modbus RTU bus, and gateway power",
                            confidence_label="NEEDS_DATA",
                            confidence_tooltip=CONFIDENCE_EXPLANATIONS["NEEDS_DATA"],
                            status="OPEN",
                            is_advisory=True,
                            physical_state_confirmed=False,
                        )
                    )
                else:
                    packet, _ = rec
                    pkt_time = packet.timestamp if packet.timestamp.tzinfo else packet.timestamp.replace(tzinfo=timezone.utc)
                    freshness_s = max(0.0, (now_utc - pkt_time).total_seconds())
                    if freshness_s > 60.0:
                        stale_or_missing_telemetry_count += 1
                        work_items.append(
                            DailyWorkItem(
                                work_item_id=f"item-{farm_id}-{p_id}-telem-stale",
                                farm_id=farm_id,
                                pond_id=p_id,
                                scope="POND",
                                category="TELEMETRY_DATA_QUALITY",
                                priority="WARNING",
                                priority_score=2,
                                title=f"Pond {p_id}: Stale Telemetry ({int(freshness_s)}s old)",
                                reason=f"Last telemetry packet received {int(freshness_s)}s ago; exceeds the standard 60-second freshness window",
                                source_timestamp=pkt_time.isoformat(),
                                recommended_action="ADVISORY: Verify edge polling cycle, RS-485 transceiver termination, and solar battery voltage",
                                confidence_label="STALE",
                                confidence_tooltip=CONFIDENCE_EXPLANATIONS["STALE"],
                                status="OPEN",
                                is_advisory=True,
                                physical_state_confirmed=False,
                            )
                        )
                    else:
                        live_telemetry_ponds_count += 1

            # -----------------------------------------------------------------
            # 2b. Health, Mortalities & Biosecurity
            # -----------------------------------------------------------------
            mort_records = (
                self._session.query(MortalityRecordORM)
                .filter(
                    MortalityRecordORM.farm_id == farm_id,
                    MortalityRecordORM.pond_id == p_id,
                    MortalityRecordORM.timestamp >= day_start,
                    MortalityRecordORM.timestamp < day_end,
                )
                .all()
            )
            mort_day = sum(r.dead_count for r in mort_records)

            if mort_day > 0:
                total_mortalities_target_date += mort_day
                ponds_with_mortalities += 1
                mort_pri = "CRITICAL" if mort_day >= 100 else ("WARNING" if mort_day >= 20 else "INFO")
                work_items.append(
                    DailyWorkItem(
                        work_item_id=f"item-{farm_id}-{p_id}-health-mortality-{date_str}",
                        farm_id=farm_id,
                        pond_id=p_id,
                        scope="POND",
                        category="HEALTH_MORTALITY",
                        priority=mort_pri,
                        priority_score=severity_weight.get(mort_pri, 2),
                        title=f"Pond {p_id}: {mort_day} Dead Shrimp Recorded ({date_str})",
                        reason=f"Mortality records on {date_str} indicate {mort_day} specimens removed via drain pit siphoning.",
                        source_timestamp=day_start.isoformat(),
                        recommended_action="ADVISORY: Siphon central drain pit, inspect hepatopancreas and gut fullness, verify bottom DO level",
                        confidence_label="RECORDED",
                        confidence_tooltip=CONFIDENCE_EXPLANATIONS["RECORDED"],
                        status="OPEN",
                        is_advisory=True,
                        physical_state_confirmed=False,
                    )
                )

            health_summary = self._health_service.get_pond_health_summary(farm_id, p_id)
            restrictions = health_summary.get("active_harvest_restrictions", [])
            if restrictions and not is_historical:
                active_withdrawals_count += len(restrictions)
                work_items.append(
                    DailyWorkItem(
                        work_item_id=f"item-{farm_id}-{p_id}-biosecurity-withdrawal",
                        farm_id=farm_id,
                        pond_id=p_id,
                        scope="POND",
                        category="HEALTH_MORTALITY",
                        priority="WARNING",
                        priority_score=2,
                        title=f"Pond {p_id}: Active Chemical Withdrawal Notice ({len(restrictions)} products)",
                        reason="Harvest is strictly held due to unexpired substance clearance window",
                        source_timestamp=now_iso,
                        recommended_action="ADVISORY: Enforce pond harvest hold until lab residue test certifies clearance",
                        confidence_label="CALCULATED_ESTIMATE",
                        confidence_tooltip=CONFIDENCE_EXPLANATIONS["CALCULATED_ESTIMATE"],
                        status="OPEN",
                        is_advisory=True,
                        physical_state_confirmed=False,
                    )
                )

            # -----------------------------------------------------------------
            # 2c. Feeding Management & Execution (Evidence-based distinction)
            # -----------------------------------------------------------------
            plan = today_plans_by_pond.get(p_id)
            prod_intel = self._growth_service.get_pond_production_intelligence(farm_id, p_id)
            has_active_batch = prod_intel.get("has_active_batch", False)

            if plan:
                planned_kg = plan.get("planned_daily_kg", 0.0)
                actual_fed_kg = plan.get("actual_fed_kg", 0.0)
                remaining_kg = plan.get("remaining_planned_kg", planned_kg)
                logs_count = plan.get("feed_logs_count", 0)

                # Missing feeding logs must produce a missing-record/data-quality task;
                # never assert that feed was definitely not delivered.
                if logs_count == 0 and planned_kg > 0:
                    work_items.append(
                        DailyWorkItem(
                            work_item_id=f"item-{farm_id}-{p_id}-feed-unlogged-{date_str}",
                            farm_id=farm_id,
                            pond_id=p_id,
                            scope="POND",
                            category="FEEDING_MANAGEMENT",
                            priority="WARNING",
                            priority_score=2,
                            title=f"Pond {p_id}: Unrecorded Feeding Logs ({planned_kg:.1f} kg planned)",
                            reason=f"Approved feed plan exists for {date_str} ({plan['plan_id']}) with {planned_kg:.1f} kg scheduled, but 0 feeding delivery logs have been submitted. Delivery unverified.",
                            source_timestamp=target_iso,
                            recommended_action="ADVISORY: Verify physical feed distribution, inspect feeding tray consumption, and record actual delivered kg in feeding log",
                            confidence_label="NEEDS_DATA",
                            confidence_tooltip=CONFIDENCE_EXPLANATIONS["NEEDS_DATA"],
                            status="OPEN",
                            is_advisory=True,
                            physical_state_confirmed=False,
                        )
                    )
                elif remaining_kg > 0.5:
                    work_items.append(
                        DailyWorkItem(
                            work_item_id=f"item-{farm_id}-{p_id}-feed-pending-{date_str}",
                            farm_id=farm_id,
                            pond_id=p_id,
                            scope="POND",
                            category="FEEDING_MANAGEMENT",
                            priority="INFO",
                            priority_score=1,
                            title=f"Pond {p_id}: Feed Delivery in Progress ({actual_fed_kg:.1f}/{planned_kg:.1f} kg recorded)",
                            reason=f"Recorded {actual_fed_kg:.1f} kg of {planned_kg:.1f} kg scheduled across {logs_count} logged session(s)",
                            source_timestamp=target_iso,
                            recommended_action="ADVISORY: Deliver remaining scheduled feeding sessions and record delivery in feed logs",
                            confidence_label="RECORDED",
                            confidence_tooltip=CONFIDENCE_EXPLANATIONS["RECORDED"],
                            status="OPEN",
                            is_advisory=True,
                            physical_state_confirmed=False,
                        )
                    )
            elif has_active_batch:
                work_items.append(
                    DailyWorkItem(
                        work_item_id=f"item-{farm_id}-{p_id}-feed-noplan-{date_str}",
                        farm_id=farm_id,
                        pond_id=p_id,
                        scope="POND",
                        category="FEEDING_MANAGEMENT",
                        priority="INFO",
                        priority_score=1,
                        title=f"Pond {p_id}: Missing Daily Feed Plan ({date_str})",
                        reason=f"Active production batch is stocked but has no approved feed plan registered for {date_str}",
                        source_timestamp=target_iso,
                        recommended_action="ADVISORY: Open Feed Planning, run biomass ration calculator, and generate today's feed plan",
                        confidence_label="NEEDS_DATA",
                        confidence_tooltip=CONFIDENCE_EXPLANATIONS["NEEDS_DATA"],
                        status="OPEN",
                        is_advisory=True,
                        physical_state_confirmed=False,
                    )
                )

            # -----------------------------------------------------------------
            # 2d. Growth Sampling Freshness (Live / current date only)
            # -----------------------------------------------------------------
            if has_active_batch and not is_historical:
                days_since_sample = prod_intel.get("days_since_sample")
                latest_sample = prod_intel.get("latest_sample")

                if latest_sample is None:
                    work_items.append(
                        DailyWorkItem(
                            work_item_id=f"item-{farm_id}-{p_id}-sample-missing",
                            farm_id=farm_id,
                            pond_id=p_id,
                            scope="POND",
                            category="GROWTH_SAMPLING",
                            priority="WARNING",
                            priority_score=2,
                            title=f"Pond {p_id}: Cast-Net Sampling Overdue (No Physical Samples)",
                            reason="Batch biomass estimates currently rely on stocking model baselines; zero physical cast-net samples are recorded",
                            source_timestamp=now_iso,
                            recommended_action="ADVISORY: Conduct cast-net sampling (sample size 30-50 pcs) to verify current body weight (ABW)",
                            confidence_label="BASELINE_ESTIMATE",
                            confidence_tooltip=CONFIDENCE_EXPLANATIONS["BASELINE_ESTIMATE"],
                            status="OPEN",
                            is_advisory=True,
                            physical_state_confirmed=False,
                        )
                    )
                elif days_since_sample is not None and days_since_sample > 10:
                    work_items.append(
                        DailyWorkItem(
                            work_item_id=f"item-{farm_id}-{p_id}-sample-stale",
                            farm_id=farm_id,
                            pond_id=p_id,
                            scope="POND",
                            category="GROWTH_SAMPLING",
                            priority="WARNING",
                            priority_score=2,
                            title=f"Pond {p_id}: Growth Sampling Stale ({days_since_sample} days old)",
                            reason=f"Last cast-net sampling occurred {days_since_sample} days ago, exceeding the 10-day operational freshness window",
                            source_timestamp=str(latest_sample.get("sample_date")),
                            recommended_action="ADVISORY: Perform weekly cast-net sampling to recalibrate ADG, biomass gain, and production FCR",
                            confidence_label="STALE",
                            confidence_tooltip=CONFIDENCE_EXPLANATIONS["STALE"],
                            status="OPEN",
                            is_advisory=True,
                            physical_state_confirmed=False,
                        )
                    )

            # -----------------------------------------------------------------
            # 2e. Infrastructure & Biological Containment (Live operations only)
            # -----------------------------------------------------------------
            if not is_historical:
                drain_outlet = outlet_info.get("full_drain_outlet_state")
                drain_locked = outlet_info.get("full_drain_locked")
                norm_outlet = outlet_info.get("normal_outlet_state", "CLOSED")

                if drain_outlet is None or drain_locked is None:
                    work_items.append(
                        DailyWorkItem(
                            work_item_id=f"item-{farm_id}-{p_id}-monk-unverified",
                            farm_id=farm_id,
                            pond_id=p_id,
                            scope="POND",
                            category="INFRASTRUCTURE_VERIFICATION",
                            priority="WARNING",
                            priority_score=2,
                            title=f"Pond {p_id}: Drainage Monk Status Unverified",
                            reason="Drainage outlet monk gate position and padlock records are unverified in registry",
                            source_timestamp=now_iso,
                            recommended_action="ADVISORY: Conduct physical on-site inspection of drainage monk and verify padlock is secure",
                            confidence_label="UNVERIFIED",
                            confidence_tooltip=CONFIDENCE_EXPLANATIONS["UNVERIFIED"],
                            status="OPEN",
                            is_advisory=True,
                            physical_state_confirmed=False,
                        )
                    )
                elif drain_outlet in ("OPEN", "PARTIALLY_OPEN"):
                    work_items.append(
                        DailyWorkItem(
                            work_item_id=f"item-{farm_id}-{p_id}-monk-breach",
                            farm_id=farm_id,
                            pond_id=p_id,
                            scope="POND",
                            category="CONTAINMENT_SAFETY",
                            priority="CRITICAL",
                            priority_score=3,
                            title=f"Pond {p_id}: Full-Drain Outlet Gate {drain_outlet}",
                            reason="Full-drain monk gate is open; active biological containment is compromised",
                            source_timestamp=now_iso,
                            recommended_action="ADVISORY: Immediately close physical monk gate boards and lock padlock. Software indicates open gate.",
                            confidence_label="MEASURED",
                            confidence_tooltip=CONFIDENCE_EXPLANATIONS["MEASURED"],
                            status="OPEN",
                            is_advisory=True,
                            physical_state_confirmed=False,
                        )
                    )
                elif not drain_locked:
                    work_items.append(
                        DailyWorkItem(
                            work_item_id=f"item-{farm_id}-{p_id}-monk-unlocked",
                            farm_id=farm_id,
                            pond_id=p_id,
                            scope="POND",
                            category="CONTAINMENT_SAFETY",
                            priority="WARNING",
                            priority_score=2,
                            title=f"Pond {p_id}: Full-Drain Monk Padlock Unlocked",
                            reason="Drain monk gate lock register is marked unlocked in farm database",
                            source_timestamp=now_iso,
                            recommended_action="ADVISORY: Inspect physical padlock on monk structure and lock with authorized key",
                            confidence_label="MEASURED",
                            confidence_tooltip=CONFIDENCE_EXPLANATIONS["MEASURED"],
                            status="OPEN",
                            is_advisory=True,
                            physical_state_confirmed=False,
                        )
                    )

                # Aerator motor verification (with strict farm_id scoping)
                aerators = self._aerator_repo.list_by_pond(p_id, farm_id=farm_id)
                unknown_aerators = [a for a in aerators if a.verified_physical_state == PhysicalRunningState.UNKNOWN]
                if unknown_aerators:
                    work_items.append(
                        DailyWorkItem(
                            work_item_id=f"item-{farm_id}-{p_id}-aerators-unknown",
                            farm_id=farm_id,
                            pond_id=p_id,
                            scope="POND",
                            category="INFRASTRUCTURE_VERIFICATION",
                            priority="WARNING",
                            priority_score=2,
                            title=f"Pond {p_id}: Aerator State Unknown ({len(unknown_aerators)} units)",
                            reason="One or more aerators report unknown physical running state from starter panel sensors",
                            source_timestamp=now_iso,
                            recommended_action="ADVISORY: Inspect motor control center (MCC) starter contactor, thermal overload, and auxiliary CT",
                            confidence_label="UNVERIFIED",
                            confidence_tooltip=CONFIDENCE_EXPLANATIONS["UNVERIFIED"],
                            status="OPEN",
                            is_advisory=True,
                            physical_state_confirmed=False,
                        )
                    )

                if not pond.transformer_id:
                    work_items.append(
                        DailyWorkItem(
                            work_item_id=f"item-{farm_id}-{p_id}-feeder-unassigned",
                            farm_id=farm_id,
                            pond_id=p_id,
                            scope="POND",
                            category="INFRASTRUCTURE_VERIFICATION",
                            priority="INFO",
                            priority_score=1,
                            title=f"Pond {p_id}: Transformer Feeder Unassigned",
                            reason="Pond is not mapped to an electrical feeder transformer; capacity headroom cannot be verified",
                            source_timestamp=now_iso,
                            recommended_action="ADVISORY: Assign transformer feeder (tx-1 or tx-2) in pond configuration",
                            confidence_label="UNCONFIGURED",
                            confidence_tooltip=CONFIDENCE_EXPLANATIONS["UNCONFIGURED"],
                            status="OPEN",
                            is_advisory=True,
                            physical_state_confirmed=False,
                        )
                    )

                # -----------------------------------------------------------------
                # 2f. Water Level & Outlets Operating Band (Live operations only)
                # -----------------------------------------------------------------
                wl_m = outlet_info.get("water_level_m")
                min_m = outlet_info.get("water_level_min_m", 0.95)
                max_m = outlet_info.get("water_level_max_m", 1.40)
                if wl_m is not None:
                    if wl_m < min_m:
                        work_items.append(
                            DailyWorkItem(
                                work_item_id=f"item-{farm_id}-{p_id}-water-low",
                                farm_id=farm_id,
                                pond_id=p_id,
                                scope="POND",
                                category="WATER_MANAGEMENT",
                                priority="WARNING",
                                priority_score=2,
                                title=f"Pond {p_id}: Water Depth Low ({wl_m:.2f}m < {min_m:.2f}m)",
                                reason=f"Water level ({wl_m:.2f}m) has dropped below minimum operating limit ({min_m:.2f}m)",
                                source_timestamp=now_iso,
                                recommended_action="ADVISORY: Open intake canal sluice gate or initiate low-salinity top-up to restore water level",
                                confidence_label="MEASURED",
                                confidence_tooltip=CONFIDENCE_EXPLANATIONS["MEASURED"],
                                status="OPEN",
                                is_advisory=True,
                                physical_state_confirmed=False,
                            )
                        )
                    elif wl_m > max_m:
                        work_items.append(
                            DailyWorkItem(
                                work_item_id=f"item-{farm_id}-{p_id}-water-high",
                                farm_id=farm_id,
                                pond_id=p_id,
                                scope="POND",
                                category="WATER_MANAGEMENT",
                                priority="WARNING",
                                priority_score=2,
                                title=f"Pond {p_id}: Water Depth High ({wl_m:.2f}m > {max_m:.2f}m)",
                                reason=f"Water level ({wl_m:.2f}m) exceeds safe freeboard threshold ({max_m:.2f}m)",
                                source_timestamp=now_iso,
                                recommended_action="ADVISORY: Adjust normal surface overflow monk boards to maintain required dyke freeboard",
                                confidence_label="MEASURED",
                                confidence_tooltip=CONFIDENCE_EXPLANATIONS["MEASURED"],
                                status="OPEN",
                                is_advisory=True,
                                physical_state_confirmed=False,
                            )
                        )

        # ---------------------------------------------------------------------
        # 3. Farm Intake Pump Advisory (Live only - never mix into historical dates)
        # ---------------------------------------------------------------------
        if not is_historical:
            pump_info = self._water_service.get_pump_info(farm_id=farm_id)
            if pump_info:
                pump_advisory = self._water_service.evaluate_pump_advisory(farm_id=farm_id)
                if pump_advisory and pump_advisory.proposed_action != "HOLD":
                    work_items.append(
                        DailyWorkItem(
                            work_item_id=f"item-{farm_id}-farm-pump-advisory",
                            farm_id=farm_id,
                            pond_id=None,
                            scope="FARM_WIDE",
                            category="WATER_MANAGEMENT",
                            priority="WARNING",
                            priority_score=2,
                            title=f"Farm Intake Pump: Advisory {pump_advisory.proposed_action}",
                            reason=pump_advisory.reason,
                            source_timestamp=now_iso,
                            recommended_action=f"ADVISORY: Inspect intake canal salinity and verify transformer headroom ({pump_advisory.transformer_headroom_kw:.1f} kW) before starting pump",
                            confidence_label="CALCULATED_ESTIMATE",
                            confidence_tooltip=CONFIDENCE_EXPLANATIONS["CALCULATED_ESTIMATE"],
                            status="OPEN",
                            is_advisory=True,
                            physical_state_confirmed=False,
                        )
                    )

        # ---------------------------------------------------------------------
        # 4. Sort and Group Work Items
        # ---------------------------------------------------------------------
        # Sort by priority score descending, then pond_id (FARM_WIDE items at end of score tier)
        work_items.sort(key=lambda x: (x.priority_score, x.pond_id or "zzz"), reverse=True)

        real_pond_list = sorted([p.pond_id for p in all_ponds])
        pond_work_queues: Dict[str, List[DailyWorkItem]] = {p: [] for p in real_pond_list}
        farm_directives: List[DailyWorkItem] = []

        for item in work_items:
            if item.scope == "FARM_WIDE" or item.pond_id is None:
                farm_directives.append(item)
            elif item.pond_id in pond_work_queues:
                pond_work_queues[item.pond_id].append(item)

        # Summary Metrics
        critical_cnt = sum(1 for w in work_items if w.priority in ("EMERGENCY", "CRITICAL"))
        warning_cnt = sum(1 for w in work_items if w.priority == "WARNING")
        info_cnt = sum(1 for w in work_items if w.priority == "INFO")

        # Feeding Progress Rollup
        feed_plans_list = feed_plans_overview.get("plans", [])
        planned_ponds_count = len(feed_plans_list)
        logged_ponds_count = sum(1 for p in feed_plans_list if p.get("feed_logs_count", 0) > 0)
        total_planned_kg = feed_plans_overview.get("total_planned_kg", 0.0)
        total_actual_fed_kg = feed_plans_overview.get("total_actual_fed_kg", 0.0)
        net_variance_kg = feed_plans_overview.get("net_variance_kg", 0.0)

        summary = DailyOperationsSummary(
            evaluated_at=now_iso,
            farm_id=farm_id,
            target_date=date_str,
            is_historical=is_historical,
            total_open_items=len(work_items),
            critical_items_count=critical_cnt,
            warning_items_count=warning_cnt,
            info_items_count=info_cnt,
            feeding_summary={
                "planned_ponds_count": planned_ponds_count,
                "logged_ponds_count": logged_ponds_count,
                "unlogged_planned_ponds_count": max(0, planned_ponds_count - logged_ponds_count),
                "total_planned_kg": total_planned_kg,
                "total_actual_fed_kg": total_actual_fed_kg,
                "net_variance_kg": net_variance_kg,
            },
            health_summary={
                "total_mortalities_last_24h": total_mortalities_target_date,
                "total_mortalities_recorded": total_mortalities_target_date,
                "ponds_with_mortalities": ponds_with_mortalities,
                "active_withdrawals_count": active_withdrawals_count,
            },
            telemetry_summary={
                "total_ponds": len(all_ponds),
                "live_ponds_count": live_telemetry_ponds_count,
                "stale_or_missing_count": stale_or_missing_telemetry_count,
                "historical_data_available": live_telemetry_ponds_count > 0 if is_historical else True,
            },
            infrastructure_summary={
                "unverified_monk_gates_count": sum(1 for w in work_items if w.category == "INFRASTRUCTURE_VERIFICATION" and "Monk" in w.title),
                "containment_breaches_count": sum(1 for w in work_items if w.category == "CONTAINMENT_SAFETY"),
                "total_infrastructure_tasks": sum(1 for w in work_items if w.category in ("INFRASTRUCTURE_VERIFICATION", "CONTAINMENT_SAFETY")),
            },
        )

        categories = sorted(list({w.category for w in work_items}))
        priorities = ["CRITICAL", "WARNING", "INFO"]
        has_farm_tasks = len(farm_directives) > 0

        return DailyOperationsPlan(
            farm_id=farm_id,
            evaluated_at=now_iso,
            target_date=date_str,
            is_historical=is_historical,
            summary=summary,
            work_items=work_items,
            pond_work_queues=pond_work_queues,
            farm_directives=farm_directives,
            filter_options={
                "categories": categories,
                "priorities": priorities,
                "ponds": real_pond_list,  # Strictly real ponds belonging to the authorized farm!
                "has_farm_tasks": has_farm_tasks,
            },
            confidence_definitions=CONFIDENCE_EXPLANATIONS,
        )
