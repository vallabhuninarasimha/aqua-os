"""Dashboard aggregation routes and real-time Server-Sent Events (SSE) streaming."""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel

from apps.api.src.config import settings
from apps.api.src.dependencies import (
    get_db_session,
    get_pond_repository,
    get_telemetry_repository,
    get_water_repository,
)
from apps.api.src.domain.interfaces import (
    IPondRepository,
    ITelemetryRepository,
)
from apps.api.src.domain.water_interfaces import IWaterRepository
from apps.api.src.security.dependencies import (
    require_permission,
    verify_farm_access,
)
from apps.api.src.security.models import Permission, UserIdentity
from apps.api.src.services.telemetry_broadcaster import broadcaster
from apps.api.src.services.water_service import WaterManagementService
from packages.telemetry_schema.models import MetricType
from sqlalchemy.orm import Session

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])


class MetricSummary(BaseModel):
    value: float
    unit: str
    quality: str


class PondCard(BaseModel):
    pond_id: str
    name: str
    status: str  # NORMAL, WARNING, CRITICAL, DEGRADED, UNKNOWN
    is_safe: bool
    is_simulated: bool
    timestamp: Optional[datetime] = None
    freshness_seconds: Optional[float] = None
    is_stale: bool = False
    metrics: Dict[str, MetricSummary] = {}
    aerator_status: str  # ON, OFF, FAULT, UNKNOWN
    battery_level_pct: Optional[float] = None
    mains_power_ok: Optional[bool] = None
    active_alerts: List[str] = []
    recommended_action: Optional[str] = None
    # Water Management additions
    water_level_m: Optional[float] = None
    water_level_target_m: Optional[float] = 1.22
    water_level_min_m: Optional[float] = 0.95
    water_level_max_m: Optional[float] = 1.40
    water_level_status: Optional[str] = "NORMAL"
    normal_outlet_state: Optional[str] = "CLOSED"
    full_drain_outlet_state: Optional[str] = "CLOSED"
    full_drain_locked: Optional[bool] = True
    drain_lock_reason: Optional[str] = "Active batch biological containment"


class DashboardSummary(BaseModel):
    total_ponds: int
    normal_ponds: int
    warning_ponds: int
    critical_ponds: int
    degraded_ponds: int
    unknown_ponds: int
    active_alerts_count: int


class EdgeGatewayStatus(BaseModel):
    gateway_id: str
    is_connected: bool
    sovereign_mode_active: bool
    sync_queue_depth: int
    last_sync: Optional[datetime] = None


class DashboardOverviewResponse(BaseModel):
    farm_id: str
    farm_name: str
    evaluated_at: datetime
    summary: DashboardSummary
    ponds: List[PondCard]
    edge_status: EdgeGatewayStatus
    biological_notice: str
    intake_pump_summary: Optional[Dict[str, Any]] = None


@router.get("/overview", response_model=DashboardOverviewResponse)
async def get_dashboard_overview(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
    pond_repo: IPondRepository = Depends(get_pond_repository),
    telemetry_repo: ITelemetryRepository = Depends(get_telemetry_repository),
    water_repo: IWaterRepository = Depends(get_water_repository),
    session: Session = Depends(get_db_session),
) -> DashboardOverviewResponse:
    """Retrieve full 20-pond operational overview with metrics, alerts, freshness, and water management."""
    verify_farm_access(user, farm_id)

    now = datetime.now(timezone.utc)
    all_ponds = pond_repo.list(farm_id=farm_id)
    latest_records = telemetry_repo.get_all_latest_with_evaluations(farm_id=farm_id)
    outlets_map = {o["pond_id"]: o for o in water_repo.list_pond_outlet_statuses(farm_id=farm_id)}

    pond_cards: List[PondCard] = []
    normal_cnt = 0
    warning_cnt = 0
    critical_cnt = 0
    degraded_cnt = 0
    unknown_cnt = 0
    active_alerts_cnt = 0

    for pond in all_ponds:
        outlet_info = outlets_map.get(pond.pond_id, {})
        target_m = outlet_info.get("water_level_target_m", 1.22)
        min_m = outlet_info.get("water_level_min_m", 0.95)
        max_m = outlet_info.get("water_level_max_m", 1.40)
        norm_outlet = outlet_info.get("normal_outlet_state", "CLOSED")
        drain_outlet = outlet_info.get("full_drain_outlet_state", "CLOSED")
        drain_locked = outlet_info.get("full_drain_locked", True)
        drain_reason = outlet_info.get("drain_lock_reason", "Active batch containment")

        record = latest_records.get(pond.pond_id)
        if not record:
            # No telemetry received yet
            unknown_cnt += 1
            pond_cards.append(
                PondCard(
                    pond_id=pond.pond_id,
                    name=pond.name,
                    status="UNKNOWN",
                    is_safe=False,
                    is_simulated=True,
                    timestamp=None,
                    freshness_seconds=None,
                    is_stale=True,
                    metrics={},
                    aerator_status="UNKNOWN",
                    battery_level_pct=None,
                    mains_power_ok=None,
                    active_alerts=["No sensor telemetry received yet"],
                    recommended_action="START_TELEMETRY_FEED",
                    water_level_m=None,
                    water_level_target_m=target_m,
                    water_level_min_m=min_m,
                    water_level_max_m=max_m,
                    water_level_status="UNKNOWN",
                    normal_outlet_state=norm_outlet,
                    full_drain_outlet_state=drain_outlet,
                    full_drain_locked=drain_locked,
                    drain_lock_reason=drain_reason,
                )
            )
            continue

        packet, evaluation = record

        # Freshness calculation
        packet_time = packet.timestamp.replace(tzinfo=timezone.utc)
        freshness = max(0.0, (now - packet_time).total_seconds())
        is_stale = freshness > 60.0  # 60s without update is considered stale

        # Status classification
        if evaluation:
            sev = evaluation.severity.value
            is_safe = evaluation.is_safe
            alerts = list(evaluation.messages)
            action = evaluation.recommended_action
        else:
            sev = "NORMAL"
            is_safe = True
            alerts = []
            action = None

        if is_stale:
            current_status = "DEGRADED"
            degraded_cnt += 1
            alerts.append(f"Telemetry stale ({int(freshness)}s elapsed since last reading)")
        elif sev in ("CRITICAL", "EMERGENCY"):
            current_status = "CRITICAL"
            critical_cnt += 1
        elif sev == "WARNING":
            current_status = "WARNING"
            warning_cnt += 1
        elif sev == "DEGRADED":
            current_status = "DEGRADED"
            degraded_cnt += 1
        else:
            current_status = "NORMAL"
            normal_cnt += 1

        # Water level measurement & bounds check
        wl_reading = packet.metrics.get(MetricType.WATER_LEVEL)
        curr_wl = None
        if wl_reading and wl_reading.quality.value == "GOOD":
            curr_wl = round(wl_reading.value, 3)

        if curr_wl is None or is_stale:
            wl_status = "DEGRADED" if curr_wl is not None else "UNKNOWN"
            is_safe = False
        elif curr_wl < min_m:
            wl_status = "LOW"
            is_safe = False
            if "Water level low" not in " ".join(alerts):
                alerts.append(f"Water depth {curr_wl:.2f}m is below safe minimum ({min_m:.2f}m)")
        elif curr_wl > max_m:
            wl_status = "HIGH"
            is_safe = False
            if "Water level high" not in " ".join(alerts):
                alerts.append(f"Water depth {curr_wl:.2f}m exceeds freeboard limit ({max_m:.2f}m)")
        else:
            wl_status = "NORMAL"

        if drain_outlet in ("OPEN", "PARTIALLY_OPEN"):
            current_status = "CRITICAL"
            is_safe = False
            drain_breach_msg = f"CRITICAL: Full-drain outlet is {drain_outlet}! Active batch biological containment breached."
            if drain_breach_msg not in alerts:
                alerts.append(drain_breach_msg)
        elif not drain_locked:
            if "Full-drain outlet is unlocked" not in " ".join(alerts):
                alerts.append("NOTICE: Full-drain outlet monk is unlocked.")

        if alerts:
            active_alerts_cnt += len(alerts)

        # Aerator state determination from hardware status or simulation
        aerator_state = "ON"
        battery_pct = None
        mains_ok = None
        if packet.hardware_status:
            battery_pct = packet.hardware_status.battery_level_pct
            mains_ok = packet.hardware_status.mains_power_ok
            if not packet.hardware_status.mains_power_ok:
                aerator_state = "FAULT"

        metrics_summary: Dict[str, MetricSummary] = {}
        for m_type, m_val in packet.metrics.items():
            metrics_summary[m_type.value] = MetricSummary(
                value=round(m_val.value, 2),
                unit=m_val.unit,
                quality=m_val.quality.value,
            )

        pond_cards.append(
            PondCard(
                pond_id=pond.pond_id,
                name=pond.name,
                status=current_status,
                is_safe=is_safe,
                is_simulated=packet.is_simulated,
                timestamp=packet_time,
                freshness_seconds=round(freshness, 1),
                is_stale=is_stale,
                metrics=metrics_summary,
                aerator_status=aerator_state,
                battery_level_pct=battery_pct,
                mains_power_ok=mains_ok,
                active_alerts=alerts,
                recommended_action=action,
                water_level_m=curr_wl,
                water_level_target_m=target_m,
                water_level_min_m=min_m,
                water_level_max_m=max_m,
                water_level_status=wl_status,
                normal_outlet_state=norm_outlet,
                full_drain_outlet_state=drain_outlet,
                full_drain_locked=drain_locked,
                drain_lock_reason=drain_reason,
            )
        )

    summary = DashboardSummary(
        total_ponds=len(all_ponds),
        normal_ponds=normal_cnt,
        warning_ponds=warning_cnt,
        critical_ponds=critical_cnt,
        degraded_ponds=degraded_cnt,
        unknown_ponds=unknown_cnt,
        active_alerts_count=active_alerts_cnt,
    )

    edge_status = EdgeGatewayStatus(
        gateway_id="edge-gw-01",
        is_connected=True,
        sovereign_mode_active=True,
        sync_queue_depth=0,
        last_sync=now,
    )

    water_service = WaterManagementService(session=session, water_repo=water_repo)
    pump = water_service.get_pump_info(farm_id=farm_id)
    advisory = water_service.evaluate_pump_advisory(farm_id=farm_id) if pump else None
    intake_pump_summary = {
        "pump": pump,
        "advisory": advisory.model_dump(mode="json") if advisory else None,
    }

    return DashboardOverviewResponse(
        farm_id=farm_id,
        farm_name="Aqua OS Core Farm",
        evaluated_at=now,
        summary=summary,
        ponds=pond_cards,
        edge_status=edge_status,
        biological_notice=(
            "Provisional baseline standards for Litopenaeus vannamei. "
            "Biological thresholds must be calibrated against on-site water chemistry "
            "and local stocking density before physical actuation is activated."
        ),
        intake_pump_summary=intake_pump_summary,
    )


@router.get("/stream")
async def stream_dashboard_events(
    request: Request,
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    max_events: Optional[int] = Query(
        default=None, description="Max events to yield before closing (useful for tests)"
    ),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
) -> StreamingResponse:
    """Server-Sent Events (SSE) real-time streaming endpoint for live pond updates."""
    verify_farm_access(user, farm_id)
    queue = broadcaster.subscribe(farm_id=farm_id)

    async def event_generator() -> AsyncGenerator[str, None]:
        events_yielded = 0
        try:
            # Initial connection confirmation
            welcome = {
                "message": "Connected to Aqua OS Live Stream",
                "farm_id": farm_id,
                "connected_at": datetime.now(timezone.utc).isoformat(),
            }
            yield f"event: connected\ndata: {json.dumps(welcome)}\n\n"
            events_yielded += 1
            if max_events and events_yielded >= max_events:
                return

            while True:
                # Wait for next broadcast event or yield periodic heartbeat
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=15.0)
                    yield payload
                    events_yielded += 1
                    if max_events and events_yielded >= max_events:
                        return
                except asyncio.TimeoutError:
                    heartbeat = {
                        "type": "heartbeat",
                        "timestamp": datetime.now(timezone.utc).isoformat(),
                    }
                    yield f"event: heartbeat\ndata: {json.dumps(heartbeat)}\n\n"
                    events_yielded += 1
                    if max_events and events_yielded >= max_events:
                        return

                if await request.is_disconnected():
                    break
        finally:
            broadcaster.unsubscribe(queue, farm_id=farm_id)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ============================================================================
# Unified Farm Operations Intelligence
# ============================================================================

@router.get("/operations", response_model=Dict[str, Any])
async def get_farm_operations_intelligence(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
    session: Session = Depends(get_db_session),
    pond_repo: IPondRepository = Depends(get_pond_repository),
    telemetry_repo: ITelemetryRepository = Depends(get_telemetry_repository),
    water_repo: IWaterRepository = Depends(get_water_repository),
) -> Dict[str, Any]:
    """Retrieve unified farm operations intelligence: integrated pond states, prioritized action center, feed/growth insights, and water/aeration advisory context."""
    from apps.api.src.infrastructure.repositories.sql_alert_repository import SQLAlertRepository
    from apps.api.src.infrastructure.repositories.sql_aerator_repository import SQLAeratorRepository
    from apps.api.src.infrastructure.repositories.sql_feed_inventory_repository import SQLFeedInventoryRepository
    from apps.api.src.services.growth_production_service import GrowthProductionService
    from apps.api.src.services.feed_planning_service import FeedPlanningService
    from apps.api.src.services.health_service import HealthService
    from apps.api.src.services.power_service import PowerMonitoringService
    from apps.api.src.services.water_service import WaterManagementService

    verify_farm_access(user, farm_id)

    now = datetime.now(timezone.utc)
    all_ponds = pond_repo.list(farm_id=farm_id)
    latest_records = telemetry_repo.get_all_latest_with_evaluations(farm_id=farm_id)
    outlets_map = {o["pond_id"]: o for o in water_repo.list_pond_outlet_statuses(farm_id=farm_id)}

    alert_repo = SQLAlertRepository(session)
    aerator_repo = SQLAeratorRepository(session)
    inv_repo = SQLFeedInventoryRepository(session)
    growth_service = GrowthProductionService(session)
    feed_service = FeedPlanningService(session)
    health_service = HealthService(session)
    power_service = PowerMonitoringService(session)
    water_service = WaterManagementService(session=session, water_repo=water_repo)

    # 1. Farm-level inventory rollup
    # 1. Farm-level inventory rollup
    inv_summary = inv_repo.get_farm_inventory_summary(farm_id)

    # 2. Farm-level feed plan rollup for today
    today_plan_overview = feed_service.get_daily_farm_plan_overview(farm_id=farm_id, target_date=now)

    # Confidence terminology explanations
    CONFIDENCE_EXPLANATIONS = {
        "MEASURED": "Direct telemetry sensor reading or physical scale weigh-in.",
        "CALCULATED_ESTIMATE": "Mathematical derivation based on recent field sampling (<= 10 days) and population estimates.",
        "STALE": "Data point exceeds standard freshness window (> 60s for telemetry, > 10 days for biological sampling).",
        "SIMULATED": "Synthetic edge test generator; not connected to physical pond hardware.",
        "BASELINE_ESTIMATE": "Derived strictly from initial stocking model assumptions without recent cast-net sampling.",
        "NEEDS_DATA": "Insufficient field measurements or unconfigured batch parameters to compute estimate.",
    }

    # 3. Action Center: Prioritize active alerts and unverified containment conditions
    raw_alerts = alert_repo.get_active_alerts(farm_id)
    action_items: List[Dict[str, Any]] = []

    severity_weight = {"EMERGENCY": 4, "CRITICAL": 3, "WARNING": 2, "ALERT": 2, "INFO": 1}

    for a in raw_alerts:
        p_id_alert = a.get("pond_id")
        p_rec = latest_records.get(p_id_alert) if p_id_alert else None
        alert_evidence_conf = "UNVERIFIED"
        if p_rec:
            pkt, _ = p_rec
            p_time = pkt.timestamp if pkt.timestamp.tzinfo else pkt.timestamp.replace(tzinfo=timezone.utc)
            if (now - p_time).total_seconds() > 60.0:
                alert_evidence_conf = "STALE"
            elif pkt.is_simulated:
                alert_evidence_conf = "SIMULATED"
            else:
                alert_evidence_conf = "MEASURED"

        raw_rec = a.get("recommended_action") or "Inspect pond condition and verify sensor reading"
        action_items.append({
            "item_id": a["alert_id"],
            "farm_id": farm_id,
            "item_type": "ALERT",
            "pond_id": p_id_alert,
            "severity": a.get("severity", "WARNING"),
            "priority_score": severity_weight.get(a.get("severity", "WARNING"), 2),
            "title": f"Pond {p_id_alert or 'Farm'}: {a.get('alert_code', 'Alert')}",
            "reason": a.get("message", "Operational threshold alert"),
            "recommended_next_step": f"ADVISORY: {raw_rec}",
            "physical_state_confirmed": False,
            "is_advisory": True,
            "source_timestamp": a.get("last_triggered_at"),
            "status": a.get("status", "ACTIVE"),
            "confidence_label": alert_evidence_conf,
            "confidence_tooltip": CONFIDENCE_EXPLANATIONS.get(alert_evidence_conf, ""),
        })

    # 4. Integrate per-pond operational state
    pond_states: List[Dict[str, Any]] = []
    feed_growth_insights: List[Dict[str, Any]] = []
    water_aeration_insights: List[Dict[str, Any]] = []

    for pond in all_ponds:
        p_id = pond.pond_id
        record = latest_records.get(p_id)
        outlet_info = outlets_map.get(p_id, {})

        # Telemetry & Freshness
        latest_metrics = {}
        freshness_sec = None
        is_stale = True
        is_simulated = True
        telemetry_confidence = "NEEDS_DATA"

        if record:
            packet, evaluation = record
            pkt_time = packet.timestamp if packet.timestamp.tzinfo else packet.timestamp.replace(tzinfo=timezone.utc)
            freshness_sec = max(0.0, (now - pkt_time).total_seconds())
            is_stale = freshness_sec > 60.0
            is_simulated = bool(packet.is_simulated)
            for m_type, m_val in packet.metrics.items():
                latest_metrics[m_type.value] = {
                    "value": round(m_val.value, 2),
                    "unit": m_val.unit,
                    "quality": m_val.quality.value,
                }
            if is_stale:
                telemetry_confidence = "STALE"
            elif is_simulated:
                telemetry_confidence = "SIMULATED"
            else:
                telemetry_confidence = "MEASURED"

        # Growth & Biomass context
        prod_intel = growth_service.get_pond_production_intelligence(farm_id, p_id)
        batch_info = None
        biomass_info = None

        if prod_intel.get("has_active_batch"):
            b = prod_intel.get("batch", {})
            b_detail = prod_intel.get("biomass_detail", {})
            latest_samp = prod_intel.get("latest_sample")
            days_samp = prod_intel.get("days_since_sample")
            sample_date_val = latest_samp.get("sample_date") if latest_samp else None
            sample_type_val = latest_samp.get("measurement_type") if latest_samp else None

            # Standardized confidence terminology
            raw_quality = b_detail.get("status_quality", "")
            if raw_quality in ("CALCULATED_ESTIMATE", "CURRENT_VALIDATED") or (days_samp is not None and days_samp <= 10):
                biomass_confidence = "CALCULATED_ESTIMATE"
            elif raw_quality in ("STALE", "PROVISIONAL_STALE") or (days_samp is not None and days_samp > 10):
                biomass_confidence = "STALE"
            elif raw_quality in ("BASELINE_ESTIMATE", "UNVALIDATED_BASELINE") or days_samp is None:
                biomass_confidence = "BASELINE_ESTIMATE"
            elif raw_quality == "NEEDS_DATA":
                biomass_confidence = "NEEDS_DATA"
            else:
                biomass_confidence = "BASELINE_ESTIMATE"

            batch_info = {
                "batch_id": b.get("batch_id"),
                "doc": b.get("days_of_culture"),
                "initial_count": b.get("initial_count"),
                "species": b.get("species"),
                "status": b.get("status"),
            }
            biomass_info = {
                "abw_g": b.get("avg_body_weight_g"),
                "adg_g_per_day": prod_intel.get("adg_g_per_day"),
                "sgr_pct_per_day": prod_intel.get("sgr_pct_per_day"),
                "estimated_biomass_kg": b_detail.get("net_remaining_biomass_kg", b.get("estimated_biomass_kg")),
                "is_estimate": True,
                "surviving_count": b_detail.get("surviving_count"),
                "survival_pct": b_detail.get("survival_pct"),
                "biomass_confidence": biomass_confidence,
                "status_quality": biomass_confidence,
                "legacy_status_quality": raw_quality,
                "sample_measurement_type": sample_type_val,
                "last_sample_date": str(sample_date_val) if sample_date_val else None,
                "days_since_sampling": days_samp,
                "confidence_tooltip": CONFIDENCE_EXPLANATIONS.get(biomass_confidence, ""),
            }

            # Feed & Growth insight pair
            fcr_data = prod_intel.get("fcr_analysis")
            feed_growth_insights.append({
                "pond_id": p_id,
                "batch_id": b.get("batch_id"),
                "doc": b.get("days_of_culture"),
                "abw_g": b.get("avg_body_weight_g"),
                "adg_g_per_day": prod_intel.get("adg_g_per_day"),
                "sgr_pct_per_day": prod_intel.get("sgr_pct_per_day"),
                "cumulative_feed_kg": prod_intel.get("cumulative_feed_kg", 0.0),
                "standing_biomass_kg": b_detail.get("net_remaining_biomass_kg", b.get("estimated_biomass_kg")),
                "is_estimate": True,
                "fcr_calculable": fcr_data.get("is_calculable") if fcr_data else False,
                "production_fcr": fcr_data.get("production_fcr") if fcr_data else None,
                "apparent_fcr": fcr_data.get("apparent_fcr") if fcr_data else None,
                "biomass_confidence": biomass_confidence,
                "confidence_label": biomass_confidence,
                "legacy_status_quality": raw_quality,
                "sample_measurement_type": sample_type_val,
                "last_sample_date": str(sample_date_val) if sample_date_val else None,
                "days_since_sampling": days_samp,
                "confidence_tooltip": CONFIDENCE_EXPLANATIONS.get(biomass_confidence, ""),
            })

        # Feeding status today
        feeding_today = {
            "today_feed_kg": prod_intel.get("feeding_summary", {}).get("today_feed_kg", 0.0) if prod_intel.get("feeding_summary") else 0.0,
            "days_recorded": prod_intel.get("feeding_summary", {}).get("days_recorded", 0) if prod_intel.get("feeding_summary") else 0,
            "average_daily_feed_kg": prod_intel.get("feeding_summary", {}).get("average_daily_feed_kg", 0.0) if prod_intel.get("feeding_summary") else 0.0,
        }

        # Health & Mortalities
        health_summary = health_service.get_pond_health_summary(farm_id, p_id)
        mortality_info = {
            "mortalities_last_24h": health_summary.get("mortalities_last_24h", 0),
            "active_withdrawals_count": len(health_summary.get("active_withdrawal_restrictions", [])),
            "latest_observation": health_summary.get("latest_observation"),
        }

        # Aeration & Electrical Feeder
        aerators = aerator_repo.list_by_pond(p_id)
        running_aerators = sum(1 for a in aerators if a.verified_physical_state.value == "RUNNING")
        tx_id = pond.transformer_id
        if tx_id:
            tx_status = power_service.get_transformer_status(farm_id, tx_id)
            feeder_status = tx_status.capacity_status
            headroom_kw = tx_status.headroom_kw
            tx_load_confidence = tx_status.load_confidence
            tx_headroom_confidence = tx_status.headroom_confidence
            tx_overload_warning = tx_status.overload_warning
        else:
            tx_id = None
            feeder_status = "UNCONFIGURED"
            headroom_kw = None
            tx_load_confidence = "UNKNOWN"
            tx_headroom_confidence = "UNCONFIGURED"
            tx_overload_warning = False

        # Water level and Outlets
        wl_curr = outlet_info.get("water_level_m")
        norm_outlet = outlet_info.get("normal_outlet_state", "CLOSED")
        drain_outlet = outlet_info.get("full_drain_outlet_state")
        drain_locked = outlet_info.get("full_drain_locked")

        aeration_advisory = {
            "aerator_count": len(aerators),
            "running_count": running_aerators,
            "transformer_id": tx_id,
            "feeder_status": feeder_status,
            "transformer_headroom_kw": headroom_kw,
            "headroom_confidence": tx_headroom_confidence,
            "load_confidence": tx_load_confidence,
            "is_field_verified": False,
            "overload_warning": tx_overload_warning,
            "normal_outlet": norm_outlet,
            "full_drain_outlet": drain_outlet or "UNKNOWN",
            "full_drain_locked": drain_locked if drain_locked is not None else "UNKNOWN",
        }

        water_aeration_insights.append({
            "pond_id": p_id,
            "transformer_id": tx_id,
            "feeder_status": feeder_status,
            "aerators_total": len(aerators),
            "aerators_running": running_aerators,
            "transformer_headroom_kw": headroom_kw,
            "headroom_confidence": tx_headroom_confidence,
            "load_confidence": tx_load_confidence,
            "is_field_verified": False,
            "headroom_type": "THEORETICAL_ESTIMATE",
            "water_level_m": wl_curr,
            "water_level_target_m": outlet_info.get("water_level_target_m", 1.22),
            "normal_outlet": norm_outlet,
            "full_drain_outlet": drain_outlet or "UNKNOWN",
            "full_drain_locked": drain_locked if drain_locked is not None else "UNKNOWN",
            "confidence_label": telemetry_confidence,
        })

        # Action center addition if containment breach or unverified drain occurs
        if drain_outlet is None or drain_locked is None:
            action_items.append({
                "item_id": f"act-drain-unverified-{p_id}",
                "farm_id": farm_id,
                "item_type": "WATER_CONTAINMENT",
                "pond_id": p_id,
                "severity": "WARNING",
                "priority_score": 2,
                "title": f"Pond {p_id}: Drain Outlet State Unverified",
                "reason": "Outlet monk gate position or lock evidence is unavailable in farm records",
                "recommended_next_step": "ADVISORY: Conduct manual on-site inspection of drainage monk and verify physical padlock",
                "physical_state_confirmed": False,
                "is_advisory": True,
                "source_timestamp": now.isoformat(),
                "status": "ACTIVE",
                "confidence_label": "UNVERIFIED",
                "confidence_tooltip": "Physical state has not been verified on-site.",
            })
        elif drain_outlet in ("OPEN", "PARTIALLY_OPEN"):
            action_items.append({
                "item_id": f"act-drain-breach-{p_id}",
                "farm_id": farm_id,
                "item_type": "WATER_CONTAINMENT",
                "pond_id": p_id,
                "severity": "CRITICAL",
                "priority_score": 3,
                "title": f"Pond {p_id}: Full-Drain Outlet {drain_outlet}",
                "reason": "Active batch biological containment breached by open drainage monk gate",
                "recommended_next_step": "ADVISORY: Immediately close physical monk boards and secure padlock. Software register indicates open drain.",
                "physical_state_confirmed": False,
                "is_advisory": True,
                "source_timestamp": now.isoformat(),
                "status": "ACTIVE",
                "confidence_label": telemetry_confidence,
                "confidence_tooltip": CONFIDENCE_EXPLANATIONS.get(telemetry_confidence, ""),
            })
        elif not drain_locked:
            action_items.append({
                "item_id": f"act-drain-unlocked-{p_id}",
                "farm_id": farm_id,
                "item_type": "WATER_CONTAINMENT",
                "pond_id": p_id,
                "severity": "WARNING",
                "priority_score": 2,
                "title": f"Pond {p_id}: Full-Drain Outlet Unlocked",
                "reason": "Full-drain monk gate padlock is reported unlocked in records",
                "recommended_next_step": "ADVISORY: Inspect physical padlock on monk structure and lock with authorized key",
                "physical_state_confirmed": False,
                "is_advisory": True,
                "source_timestamp": now.isoformat(),
                "status": "ACTIVE",
                "confidence_label": telemetry_confidence,
                "confidence_tooltip": CONFIDENCE_EXPLANATIONS.get(telemetry_confidence, ""),
            })

        pond_states.append({
            "pond_id": p_id,
            "name": pond.name,
            "latest_metrics": latest_metrics,
            "freshness_seconds": round(freshness_sec, 1) if freshness_sec is not None else None,
            "is_stale": is_stale,
            "is_simulated": is_simulated,
            "data_confidence": telemetry_confidence,
            "telemetry_confidence": telemetry_confidence,
            "telemetry_tooltip": CONFIDENCE_EXPLANATIONS.get(telemetry_confidence, ""),
            "batch": batch_info,
            "biomass": biomass_info,
            "feeding": feeding_today,
            "health": mortality_info,
            "aeration_water": aeration_advisory,
        })

    # Sort Action Center items by priority score descending
    action_items.sort(key=lambda x: x.get("priority_score", 1), reverse=True)

    return {
        "farm_id": farm_id,
        "evaluated_at": now.isoformat(),
        "pond_states": pond_states,
        "action_center": {
            "total_actionable_items": len(action_items),
            "critical_count": sum(1 for a in action_items if a.get("severity") in ("CRITICAL", "EMERGENCY")),
            "warning_count": sum(1 for a in action_items if a.get("severity") in ("WARNING", "ALERT")),
            "items": action_items,
        },
        "inventory_status": inv_summary,
        "feed_growth_insights": feed_growth_insights,
        "water_aeration_insights": water_aeration_insights,
        "confidence_definitions": CONFIDENCE_EXPLANATIONS,
        "biological_disclaimer": "All growth, FCR, and biomass values are mathematical estimates. Equipment operates strictly in DRY_RUN mode.",
    }


# ============================================================================
# Daily Operations Planner
# ============================================================================

@router.get("/planner", response_model=Dict[str, Any])
async def get_daily_operations_plan(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    target_date: Optional[str] = Query(default=None, description="Target planning date (YYYY-MM-DD), defaults to today"),
    user: UserIdentity = Depends(require_permission(Permission.TELEMETRY_READ)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve daily operations plan: prioritized pond work queue, task list, and operational summary."""
    from apps.api.src.services.daily_planner_service import DailyOperationsPlannerService

    verify_farm_access(user, farm_id)

    parsed_date = None
    if target_date:
        try:
            target_clean = target_date.strip().replace("Z", "+00:00")
            if len(target_clean) == 10 and target_clean.count("-") == 2:
                parsed_date = datetime.strptime(target_clean, "%Y-%m-%d").replace(tzinfo=timezone.utc)
            else:
                parsed_date = datetime.fromisoformat(target_clean)
                if parsed_date.tzinfo is None:
                    parsed_date = parsed_date.replace(tzinfo=timezone.utc)
        except Exception:
            parsed_date = None

    service = DailyOperationsPlannerService(session)
    plan = service.generate_daily_plan(farm_id=farm_id, target_date=parsed_date)
    return plan.model_dump(mode="json")


# ============================================================================
# Farm-wide Action & Decision Engine
# ============================================================================

@router.get("/actions", response_model=Dict[str, Any])
async def get_farm_actions(
    farm_id: str = Query(default=settings.default_farm_id, description="Farm identifier"),
    pond_id: Optional[str] = Query(default=None, description="Optional pond filter"),
    category: Optional[str] = Query(default=None, description="Optional action category filter"),
    severity: Optional[str] = Query(default=None, description="Optional action severity filter"),
    user: UserIdentity = Depends(require_permission(Permission.PONDS_READ)),
    session: Session = Depends(get_db_session),
) -> Dict[str, Any]:
    """Retrieve evidence-backed operational decisions and prioritized action center items."""
    from apps.api.src.services.farm_action_service import FarmActionDecisionService
    from apps.api.src.infrastructure.repositories.sql_pond_repository import SQLPondRepository

    verify_farm_access(user, farm_id)

    # Verify pond ownership if pond_id filter is requested
    if pond_id and pond_id.upper() != "FARM_WIDE":
        pond_repo = SQLPondRepository(session)
        pond = pond_repo.get_by_id(pond_id)
        if not pond:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Pond '{pond_id}' not found.",
            )
        if pond.farm_id != farm_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: Pond '{pond_id}' does not belong to farm '{farm_id}'.",
            )

    service = FarmActionDecisionService(session)
    response = service.generate_farm_actions(
        farm_id=farm_id,
        pond_id_filter=pond_id,
        category_filter=category,
        severity_filter=severity,
    )
    return response.model_dump(mode="json")

