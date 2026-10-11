"""Dashboard aggregation routes and real-time Server-Sent Events (SSE) streaming."""

import asyncio
import json
from datetime import datetime, timezone
from typing import Any, AsyncGenerator, Dict, List, Optional

from fastapi import APIRouter, Depends, Query, Request
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
from apps.api.src.services.simulator_service import simulator_service
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
    simulator_status: dict
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
        simulator_status=simulator_service.get_status(),
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
    queue = broadcaster.subscribe()

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
            broadcaster.unsubscribe(queue)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
