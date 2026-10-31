"""Farm-wide Action & Decision Engine Service for Aqua OS.

Coordinates cross-domain operational evidence collection and generates
prioritized, evidence-backed action directives for farm operators and managers.

Clean Architecture Principles:
- Read-only synthesis across telemetry, water, aeration, feed, health, and growth subsystems.
- All hardware controls remain strictly in DRY_RUN advisory mode.
- Strict multi-tenant isolation via farm_id scoping and ownership verification.
- Explicit data-confidence states (MEASURED, RECORDED, CALCULATED_ESTIMATE, STALE, NEEDS_DATA, etc.).
- Gracefully handles partial source-service degradation without masking missing data as healthy.
"""

from datetime import datetime, timezone
import logging
from typing import Any, Dict, List, Optional
from sqlalchemy.orm import Session

from apps.api.src.domain.action_engine import (
    ActionCategory,
    ActionSeverity,
    CONFIDENCE_EXPLANATIONS,
    FarmActionItem,
    FarmActionsResponse,
    FarmActionsSummary,
    SEVERITY_SCORES,
)
from apps.api.src.infrastructure.repositories.sql_pond_repository import SQLPondRepository
from apps.api.src.infrastructure.repositories.sql_telemetry_repository import SQLTelemetryRepository
from apps.api.src.infrastructure.repositories.sql_alert_repository import SQLAlertRepository
from apps.api.src.infrastructure.repositories.sql_aerator_repository import SQLAeratorRepository
from apps.api.src.infrastructure.repositories.sql_water_repository import SQLWaterRepository
from apps.api.src.infrastructure.repositories.sql_pond_records_repository import SQLPondRecordsRepository
from apps.api.src.infrastructure.repositories.sql_feed_plan_repository import SQLFeedPlanRepository
from apps.api.src.infrastructure.repositories.sql_feed_inventory_repository import SQLFeedInventoryRepository
from apps.api.src.services.growth_production_service import GrowthProductionService
from apps.api.src.services.health_service import HealthService
from apps.api.src.services.power_service import PowerMonitoringService
from apps.api.src.services.water_service import WaterManagementService

logger = logging.getLogger(__name__)


class FarmActionDecisionService:
    """Evaluates farm operational status across modules to generate actionable decision items."""

    def __init__(self, session: Session):
        self.session = session
        self.pond_repo = SQLPondRepository(session)
        self.telemetry_repo = SQLTelemetryRepository(session)
        self.alert_repo = SQLAlertRepository(session)
        self.aerator_repo = SQLAeratorRepository(session)
        self.water_repo = SQLWaterRepository(session)
        self.records_repo = SQLPondRecordsRepository(session)
        self.feed_plan_repo = SQLFeedPlanRepository(session)
        self.inventory_repo = SQLFeedInventoryRepository(session)

        # Domain service adapters
        self.growth_service = GrowthProductionService(session)
        self.health_service = HealthService(session)
        self.power_service = PowerMonitoringService(session)
        self.water_service = WaterManagementService(session=session, water_repo=self.water_repo)

    def generate_farm_actions(
        self,
        farm_id: str,
        pond_id_filter: Optional[str] = None,
        category_filter: Optional[str] = None,
        severity_filter: Optional[str] = None,
    ) -> FarmActionsResponse:
        """Derive all actionable decision items for a farm with safe partial-error tolerance."""
        now = datetime.now(timezone.utc)
        now_str = now.isoformat()
        actions: List[FarmActionItem] = []
        partial_failures: List[str] = []

        # 1. Fetch authorized ponds
        try:
            ponds = self.pond_repo.list(farm_id=farm_id) if hasattr(self.pond_repo, "list") else self.pond_repo.list_by_farm(farm_id)
        except Exception as e:
            logger.error("Failed to list ponds for farm %s: %s", farm_id, e)
            return FarmActionsResponse(
                farm_id=farm_id,
                evaluated_at=now_str,
                data_status="UNAVAILABLE",
                partial_failures=[f"Pond registry unreachable: {str(e)}"],
                summary=FarmActionsSummary(
                    total_actions=0,
                    emergency_count=0,
                    critical_count=0,
                    warning_count=0,
                    info_count=0,
                    category_counts={},
                ),
                actions=[],
                filter_options={"ponds": [], "categories": [], "severities": []},
            )

        # 2. Feed Inventory Evaluation (Farm-Wide)
        try:
            products = self.inventory_repo.list_products(farm_id, active_only=True)
            for prod in products:
                if prod.is_low_stock or (prod.available_balance_kg <= prod.reorder_threshold_kg):
                    is_zero_or_negative = prod.available_balance_kg <= 0
                    sev = ActionSeverity.CRITICAL.value if is_zero_or_negative else ActionSeverity.WARNING.value
                    actions.append(
                        FarmActionItem(
                            action_id=f"act-inv-{prod.product_id}",
                            farm_id=farm_id,
                            pond_id=None,
                            scope="FARM_WIDE",
                            category=ActionCategory.FEED_INVENTORY_REVIEW.value,
                            severity=sev,
                            priority_score=SEVERITY_SCORES[sev],
                            title=f"Feed Stock Critical: '{prod.product_name}' at Reorder Point",
                            reason=(
                                f"Warehouse available stock of {prod.available_balance_kg:.1f} {prod.unit_of_measure} "
                                f"is at or below reorder threshold ({prod.reorder_threshold_kg:.1f} {prod.unit_of_measure})."
                            ),
                            supporting_evidence={
                                "product_id": prod.product_id,
                                "product_name": prod.product_name,
                                "available_balance_kg": prod.available_balance_kg,
                                "reorder_threshold_kg": prod.reorder_threshold_kg,
                                "unit_of_measure": prod.unit_of_measure,
                                "brand": prod.brand,
                            },
                            confidence="RECORDED",
                            confidence_tooltip=CONFIDENCE_EXPLANATIONS["RECORDED"],
                            recommended_next_step=(
                                f"ADVISORY: Issue purchase requisition for '{prod.product_name}' to maintain "
                                "uninterrupted feeding schedules. Check feed distributor lead times."
                            ),
                            source_data_timestamp=prod.updated_at.isoformat() if prod.updated_at else now_str,
                            generated_timestamp=now_str,
                            is_advisory=True,
                            physical_state_confirmed=True,
                        )
                    )
        except Exception as e:
            logger.warning("Feed inventory evaluation failed for farm %s: %s", farm_id, e)
            partial_failures.append(f"Feed inventory check unavailable: {str(e)}")

        # 3. Transformer Feeder Evaluation (Farm-Wide)
        try:
            for tx_id in ("tx-1", "tx-2"):
                tx_status = self.power_service.get_transformer_status(farm_id, tx_id)
                if tx_status.overload_warning:
                    sev = ActionSeverity.CRITICAL.value
                    actions.append(
                        FarmActionItem(
                            action_id=f"act-power-overload-{tx_id}",
                            farm_id=farm_id,
                            pond_id=None,
                            scope="FARM_WIDE",
                            category=ActionCategory.POWER_CONFIGURATION_REQUIRED.value,
                            severity=sev,
                            priority_score=SEVERITY_SCORES[sev],
                            title=f"Transformer {tx_id.upper()}: Continuous Load Headroom Warning",
                            reason=(
                                f"Transformer load ({tx_status.current_load_kw:.1f} kW) exceeds 80% continuous "
                                f"safe operating rating ({tx_status.continuous_rating_80pct_kw:.1f} kW)."
                            ),
                            supporting_evidence={
                                "transformer_id": tx_id,
                                "current_load_kw": tx_status.current_load_kw,
                                "headroom_kw": tx_status.headroom_kw,
                                "continuous_rating_kw": tx_status.continuous_rating_80pct_kw,
                                "running_aerators": tx_status.running_aerator_count,
                            },
                            confidence=tx_status.load_confidence or "THEORETICAL_ESTIMATE",
                            confidence_tooltip=CONFIDENCE_EXPLANATIONS.get(
                                tx_status.load_confidence, CONFIDENCE_EXPLANATIONS["THEORETICAL_ESTIMATE"]
                            ),
                            recommended_next_step=(
                                "ADVISORY: Defer non-critical pumping and review running aerators on this feeder. "
                                "Physical circuit breaker trip risk if continuous load is sustained."
                            ),
                            source_data_timestamp=now_str,
                            generated_timestamp=now_str,
                            is_advisory=True,
                            physical_state_confirmed=False,
                        )
                    )
        except Exception as e:
            logger.warning("Transformer power evaluation failed for farm %s: %s", farm_id, e)
            partial_failures.append(f"Transformer load check unavailable: {str(e)}")

        # 4. River Intake Pump Evaluation (Farm-Wide)
        try:
            pump = self.water_service.get_pump_info(farm_id)
            if pump and (not pump.get("transformer_id") or (pump.get("rating_kw") or 0.0) <= 0.0):
                sev = ActionSeverity.WARNING.value
                actions.append(
                    FarmActionItem(
                        action_id="act-pump-unconfigured",
                        farm_id=farm_id,
                        pond_id=None,
                        scope="FARM_WIDE",
                        category=ActionCategory.POWER_CONFIGURATION_REQUIRED.value,
                        severity=sev,
                        priority_score=SEVERITY_SCORES[sev],
                        title="River Intake Pump: Electrical Configuration Incomplete",
                        reason="Intake pump electrical nameplate kW rating or assigned transformer feeder is unconfigured.",
                        supporting_evidence={
                            "pump_id": pump.get("pump_id"),
                            "transformer_id": pump.get("transformer_id"),
                            "rating_kw": pump.get("rating_kw"),
                            "physical_state": pump.get("physical_state", "UNKNOWN"),
                        },
                        confidence="UNCONFIGURED",
                        confidence_tooltip=CONFIDENCE_EXPLANATIONS["UNCONFIGURED"],
                        recommended_next_step=(
                            "ADVISORY: Enter verified nameplate electrical ratings (kW and FLA) and assign transformer feeder "
                            "in farm infrastructure settings before enabling pumping advisories."
                        ),
                        source_data_timestamp=now_str,
                        generated_timestamp=now_str,
                        is_advisory=True,
                        physical_state_confirmed=False,
                    )
                )
        except Exception as e:
            logger.warning("Intake pump evaluation failed for farm %s: %s", farm_id, e)
            partial_failures.append(f"Intake pump check unavailable: {str(e)}")

        # 5. Pond-Specific Evaluations
        for pond in ponds:
            p_id = pond.pond_id

            # A. Telemetry & Sensor Availability
            try:
                record = self.telemetry_repo.get_latest(farm_id, p_id)
                if not record:
                    sev = ActionSeverity.CRITICAL.value
                    actions.append(
                        FarmActionItem(
                            action_id=f"act-telem-none-{p_id}",
                            farm_id=farm_id,
                            pond_id=p_id,
                            scope="POND",
                            category=ActionCategory.SENSOR_DATA_UNAVAILABLE.value,
                            severity=sev,
                            priority_score=SEVERITY_SCORES[sev],
                            title=f"Pond {p_id.upper()}: Zero Telemetry Data Received",
                            reason=f"No telemetry packets recorded in database for pond {p_id}. Field sensors are offline or unlinked.",
                            supporting_evidence={"pond_id": p_id, "sensors_count": len(pond.sensors)},
                            confidence="UNAVAILABLE",
                            confidence_tooltip=CONFIDENCE_EXPLANATIONS["UNAVAILABLE"],
                            recommended_next_step=(
                                f"ADVISORY: Inspect physical power and RS-485 Modbus wiring on Pond {p_id.upper()}. "
                                "Do NOT assume dissolved oxygen is safe in the absence of active telemetry."
                            ),
                            source_data_timestamp=None,
                            generated_timestamp=now_str,
                            is_advisory=True,
                            physical_state_confirmed=False,
                        )
                    )
                else:
                    packet, evaluation = record
                    pkt_dt = packet.timestamp if packet.timestamp.tzinfo else packet.timestamp.replace(tzinfo=timezone.utc)
                    freshness_sec = max(0.0, (now - pkt_dt).total_seconds())

                    if freshness_sec > 60.0:
                        sev = ActionSeverity.WARNING.value
                        actions.append(
                            FarmActionItem(
                                action_id=f"act-telem-stale-{p_id}",
                                farm_id=farm_id,
                                pond_id=p_id,
                                scope="POND",
                                category=ActionCategory.SENSOR_DATA_UNAVAILABLE.value,
                                severity=sev,
                                priority_score=SEVERITY_SCORES[sev],
                                title=f"Pond {p_id.upper()}: Telemetry Stream Stale ({int(freshness_sec)}s)",
                                reason=f"Telemetry packet received {int(freshness_sec)}s ago exceeds the 60-second real-time window.",
                                supporting_evidence={
                                    "pond_id": p_id,
                                    "freshness_seconds": round(freshness_sec, 1),
                                    "last_timestamp": pkt_dt.isoformat(),
                                    "is_simulated": bool(packet.is_simulated),
                                },
                                confidence="STALE",
                                confidence_tooltip=CONFIDENCE_EXPLANATIONS["STALE"],
                                recommended_next_step=(
                                    f"ADVISORY: Check edge gateway local sync queue and radio link for Pond {p_id.upper()}. "
                                    "Take manual probe reading if delay persists."
                                ),
                                source_data_timestamp=pkt_dt.isoformat(),
                                generated_timestamp=now_str,
                                is_advisory=True,
                                physical_state_confirmed=False,
                            )
                        )

                    # B. Water Quality Review
                    do_metric = packet.metrics.get("dissolved_oxygen") or packet.metrics.get("DO")
                    temp_metric = packet.metrics.get("temperature") or packet.metrics.get("TEMP")
                    do_val = do_metric.value if do_metric else None
                    temp_val = temp_metric.value if temp_metric else None

                    if do_val is not None:
                        if do_val < 3.0:
                            sev = ActionSeverity.EMERGENCY.value
                            actions.append(
                                FarmActionItem(
                                    action_id=f"act-wq-hypoxia-{p_id}",
                                    farm_id=farm_id,
                                    pond_id=p_id,
                                    scope="POND",
                                    category=ActionCategory.WATER_QUALITY_REVIEW.value,
                                    severity=sev,
                                    priority_score=SEVERITY_SCORES[sev],
                                    title=f"Pond {p_id.upper()}: Severe Hypoxia Detected ({do_val:.2f} mg/L)",
                                    reason=f"Dissolved oxygen level is critically below lethal threshold of 3.0 mg/L.",
                                    supporting_evidence={
                                        "dissolved_oxygen_mg_l": do_val,
                                        "temperature_c": temp_val,
                                        "is_simulated": bool(packet.is_simulated),
                                        "quality": do_metric.quality.value if do_metric else "UNKNOWN",
                                    },
                                    confidence="SIMULATED" if packet.is_simulated else "MEASURED",
                                    confidence_tooltip=CONFIDENCE_EXPLANATIONS["SIMULATED" if packet.is_simulated else "MEASURED"],
                                    recommended_next_step=(
                                        f"ADVISORY: Engage all emergency aerators on Pond {p_id.upper()} immediately. "
                                        "Suspend all feeding until DO recovers above 4.5 mg/L."
                                    ),
                                    source_data_timestamp=pkt_dt.isoformat(),
                                    generated_timestamp=now_str,
                                    is_advisory=True,
                                    physical_state_confirmed=False,
                                )
                            )
                        elif do_val < 4.0:
                            sev = ActionSeverity.WARNING.value
                            actions.append(
                                FarmActionItem(
                                    action_id=f"act-wq-lowdo-{p_id}",
                                    farm_id=farm_id,
                                    pond_id=p_id,
                                    scope="POND",
                                    category=ActionCategory.WATER_QUALITY_REVIEW.value,
                                    severity=sev,
                                    priority_score=SEVERITY_SCORES[sev],
                                    title=f"Pond {p_id.upper()}: Sub-Optimal Dissolved Oxygen ({do_val:.2f} mg/L)",
                                    reason=f"Dissolved oxygen ({do_val:.2f} mg/L) is below target minimum of 4.0 mg/L.",
                                    supporting_evidence={
                                        "dissolved_oxygen_mg_l": do_val,
                                        "temperature_c": temp_val,
                                        "is_simulated": bool(packet.is_simulated),
                                    },
                                    confidence="SIMULATED" if packet.is_simulated else "MEASURED",
                                    confidence_tooltip=CONFIDENCE_EXPLANATIONS["SIMULATED" if packet.is_simulated else "MEASURED"],
                                    recommended_next_step=(
                                        f"ADVISORY: Increase aeration runtimes on Pond {p_id.upper()} and reduce upcoming feed ration."
                                    ),
                                    source_data_timestamp=pkt_dt.isoformat(),
                                    generated_timestamp=now_str,
                                    is_advisory=True,
                                    physical_state_confirmed=False,
                                )
                            )

                    # Temperature extremes check
                    if temp_val is not None and (temp_val > 33.0 or temp_val < 22.0):
                        sev = ActionSeverity.WARNING.value
                        actions.append(
                            FarmActionItem(
                                action_id=f"act-wq-temp-{p_id}",
                                farm_id=farm_id,
                                pond_id=p_id,
                                scope="POND",
                                category=ActionCategory.WATER_QUALITY_REVIEW.value,
                                severity=sev,
                                priority_score=SEVERITY_SCORES[sev],
                                title=f"Pond {p_id.upper()}: Temperature Boundary Warning ({temp_val:.1f}°C)",
                                reason=f"Water temperature ({temp_val:.1f}°C) is outside safe biological comfort range (22°C - 33°C).",
                                supporting_evidence={"temperature_c": temp_val, "dissolved_oxygen_mg_l": do_val},
                                confidence="SIMULATED" if packet.is_simulated else "MEASURED",
                                confidence_tooltip=CONFIDENCE_EXPLANATIONS["SIMULATED" if packet.is_simulated else "MEASURED"],
                                recommended_next_step="ADVISORY: Monitor thermal stratification. Maintain surface water circulation.",
                                source_data_timestamp=pkt_dt.isoformat(),
                                generated_timestamp=now_str,
                                is_advisory=True,
                                physical_state_confirmed=False,
                            )
                        )
            except Exception as e:
                logger.warning("Telemetry review failed for pond %s: %s", p_id, e)
                partial_failures.append(f"Pond {p_id} telemetry review failed: {str(e)}")

            # C. Aeration & Feeder Review
            try:
                aerators = self.aerator_repo.list_by_pond(p_id)
                running_aerators = sum(1 for a in aerators if a.verified_physical_state.value == "RUNNING")
                faulty_aerators = [a for a in aerators if a.verified_physical_state.value == "FAULT"]

                if faulty_aerators:
                    sev = ActionSeverity.CRITICAL.value
                    actions.append(
                        FarmActionItem(
                            action_id=f"act-aer-fault-{p_id}",
                            farm_id=farm_id,
                            pond_id=p_id,
                            scope="POND",
                            category=ActionCategory.AERATION_REVIEW.value,
                            severity=sev,
                            priority_score=SEVERITY_SCORES[sev],
                            title=f"Pond {p_id.upper()}: Aerator Hardware Fault ({len(faulty_aerators)} unit)",
                            reason=f"Aerator unit(s) {', '.join(a.aerator_id for a in faulty_aerators)} reported electrical fault.",
                            supporting_evidence={
                                "faulty_aerator_ids": [a.aerator_id for a in faulty_aerators],
                                "running_count": running_aerators,
                                "total_count": len(aerators),
                            },
                            confidence="RECORDED",
                            confidence_tooltip=CONFIDENCE_EXPLANATIONS["RECORDED"],
                            recommended_next_step=(
                                f"ADVISORY: Dispatch maintenance to inspect circuit breaker and motor thermal overload relay "
                                f"for aerators on Pond {p_id.upper()}."
                            ),
                            source_data_timestamp=now_str,
                            generated_timestamp=now_str,
                            is_advisory=True,
                            physical_state_confirmed=True,
                        )
                    )

                if not pond.transformer_id:
                    sev = ActionSeverity.WARNING.value
                    actions.append(
                        FarmActionItem(
                            action_id=f"act-power-unassigned-{p_id}",
                            farm_id=farm_id,
                            pond_id=p_id,
                            scope="POND",
                            category=ActionCategory.POWER_CONFIGURATION_REQUIRED.value,
                            severity=sev,
                            priority_score=SEVERITY_SCORES[sev],
                            title=f"Pond {p_id.upper()}: Transformer Feeder Unassigned",
                            reason=f"Pond {p_id} is not mapped to an electrical supply transformer (TX-1 or TX-2).",
                            supporting_evidence={"pond_id": p_id, "transformer_id": None},
                            confidence="UNCONFIGURED",
                            confidence_tooltip=CONFIDENCE_EXPLANATIONS["UNCONFIGURED"],
                            recommended_next_step=(
                                f"ADVISORY: Configure dedicated transformer feeder in Pond {p_id.upper()} settings "
                                "(TX-1 for North ponds 1-4, TX-2 for South ponds 5-8)."
                            ),
                            source_data_timestamp=now_str,
                            generated_timestamp=now_str,
                            is_advisory=True,
                            physical_state_confirmed=False,
                        )
                    )
            except Exception as e:
                logger.warning("Aeration review failed for pond %s: %s", p_id, e)
                partial_failures.append(f"Pond {p_id} aeration review failed: {str(e)}")

            # D. Water Outlets & Containment Safety
            try:
                water_status = self.water_service.get_pond_water_status(farm_id, p_id)
                outlets = water_status.get("outlets", {})
                drain_state = outlets.get("full_drain_outlet_state")
                drain_locked = outlets.get("full_drain_locked")

                if drain_state in ("OPEN", "PARTIALLY_OPEN"):
                    sev = ActionSeverity.EMERGENCY.value
                    actions.append(
                        FarmActionItem(
                            action_id=f"act-containment-breach-{p_id}",
                            farm_id=farm_id,
                            pond_id=p_id,
                            scope="POND",
                            category=ActionCategory.EQUIPMENT_STATUS_UNKNOWN.value,
                            severity=sev,
                            priority_score=SEVERITY_SCORES[sev],
                            title=f"Pond {p_id.upper()}: Monk Drain Gate OPEN &mdash; Containment Breach",
                            reason=f"Full-drain monk outlet register reports {drain_state}. Active batch containment breached.",
                            supporting_evidence={
                                "drain_state": drain_state,
                                "drain_locked": drain_locked,
                                "water_level_m": water_status.get("water_level_m"),
                            },
                            confidence="UNVERIFIED",
                            confidence_tooltip=CONFIDENCE_EXPLANATIONS["UNVERIFIED"],
                            recommended_next_step=(
                                f"ADVISORY: Physically inspect drainage monk on Pond {p_id.upper()} immediately! "
                                "Close stop-logs and padlock gate to prevent biomass loss."
                            ),
                            source_data_timestamp=now_str,
                            generated_timestamp=now_str,
                            is_advisory=True,
                            physical_state_confirmed=False,
                        )
                    )
                elif drain_locked is False:
                    sev = ActionSeverity.WARNING.value
                    actions.append(
                        FarmActionItem(
                            action_id=f"act-drain-unlocked-{p_id}",
                            farm_id=farm_id,
                            pond_id=p_id,
                            scope="POND",
                            category=ActionCategory.EQUIPMENT_STATUS_UNKNOWN.value,
                            severity=sev,
                            priority_score=SEVERITY_SCORES[sev],
                            title=f"Pond {p_id.upper()}: Monk Drain Padlock Unlocked",
                            reason="Full-drain monk gate padlock is reported unlocked in farm registers.",
                            supporting_evidence={"drain_locked": False, "drain_state": drain_state},
                            confidence="UNVERIFIED",
                            confidence_tooltip=CONFIDENCE_EXPLANATIONS["UNVERIFIED"],
                            recommended_next_step=(
                                f"ADVISORY: Verify physical padlock on Pond {p_id.upper()} monk structure and secure lock."
                            ),
                            source_data_timestamp=now_str,
                            generated_timestamp=now_str,
                            is_advisory=True,
                            physical_state_confirmed=False,
                        )
                    )
            except Exception as e:
                logger.warning("Water outlet check failed for pond %s: %s", p_id, e)
                partial_failures.append(f"Pond {p_id} water outlet check failed: {str(e)}")

            # E. Health, Mortalities & Chemical Withdrawal Restrictions
            try:
                health_summary = self.health_service.get_pond_health_summary(farm_id, p_id)
                m_count = health_summary.get("mortalities_last_24h", 0)

                if m_count > 0:
                    sev = ActionSeverity.CRITICAL.value if m_count > 10 else ActionSeverity.WARNING.value
                    actions.append(
                        FarmActionItem(
                            action_id=f"act-mort-{p_id}",
                            farm_id=farm_id,
                            pond_id=p_id,
                            scope="POND",
                            category=ActionCategory.MORTALITY_REVIEW.value,
                            severity=sev,
                            priority_score=SEVERITY_SCORES[sev],
                            title=f"Pond {p_id.upper()}: {m_count} Dead Shrimp Logged in Past 24h",
                            reason=f"Elevated mortality record of {m_count} pieces retrieved from monk screen in last 24 hours.",
                            supporting_evidence={
                                "mortalities_last_24h": m_count,
                                "health_status": health_summary.get("health_status"),
                                "latest_observation": health_summary.get("latest_observation"),
                            },
                            confidence="RECORDED",
                            confidence_tooltip=CONFIDENCE_EXPLANATIONS["RECORDED"],
                            recommended_next_step=(
                                f"ADVISORY: Inspect dead specimens on Pond {p_id.upper()} for gut fullness and hepatopancreas condition. "
                                "Submit health observation record in app."
                            ),
                            source_data_timestamp=now_str,
                            generated_timestamp=now_str,
                            is_advisory=True,
                            physical_state_confirmed=True,
                        )
                    )

                active_withdrawals = health_summary.get("active_withdrawal_restrictions", [])
                if active_withdrawals or health_summary.get("is_harvest_blocked"):
                    sev = ActionSeverity.CRITICAL.value
                    prod_names = [w.get("product_name", "Chemical Treatment") for w in active_withdrawals]
                    actions.append(
                        FarmActionItem(
                            action_id=f"act-withdrawal-{p_id}",
                            farm_id=farm_id,
                            pond_id=p_id,
                            scope="POND",
                            category=ActionCategory.CHEMICAL_WITHDRAWAL_BLOCK.value,
                            severity=sev,
                            priority_score=SEVERITY_SCORES[sev],
                            title=f"Pond {p_id.upper()}: Harvest Blocked &mdash; Withdrawal Active",
                            reason=(
                                f"Active chemical treatment withdrawal restriction: {', '.join(prod_names)}. "
                                "Harvest is strictly prohibited under biosecurity regulations."
                            ),
                            supporting_evidence={
                                "active_withdrawal_restrictions": active_withdrawals,
                                "is_harvest_blocked": True,
                            },
                            confidence="RECORDED",
                            confidence_tooltip=CONFIDENCE_EXPLANATIONS["RECORDED"],
                            recommended_next_step=(
                                f"ADVISORY: Enforce harvest embargo on Pond {p_id.upper()}. "
                                "Maintain ban until withdrawal period expires to avoid chemical residue violations."
                            ),
                            source_data_timestamp=now_str,
                            generated_timestamp=now_str,
                            is_advisory=True,
                            physical_state_confirmed=True,
                        )
                    )
            except Exception as e:
                logger.warning("Health review failed for pond %s: %s", p_id, e)
                partial_failures.append(f"Pond {p_id} health review failed: {str(e)}")

            # F. Growth Kinetics, Sampling Stale & Harvest Readiness
            try:
                prod_intel = self.growth_service.get_pond_production_intelligence(farm_id, p_id)
                if prod_intel.get("has_active_batch"):
                    b = prod_intel.get("batch", {})
                    b_id = b.get("batch_id")
                    b_status = b.get("status")
                    days_samp = prod_intel.get("days_since_sample")
                    current_abw = b.get("avg_body_weight_g")
                    target_abw = b.get("target_abw_g")

                    # Growth Sample Stale Check
                    if b_status in ("GROWOUT", "NURSERY_JUVENILE") and (days_samp is None or days_samp > 10):
                        sev = ActionSeverity.WARNING.value
                        actions.append(
                            FarmActionItem(
                                action_id=f"act-sample-stale-{p_id}",
                                farm_id=farm_id,
                                pond_id=p_id,
                                scope="POND",
                                category=ActionCategory.GROWTH_SAMPLE_REQUIRED.value,
                                severity=sev,
                                priority_score=SEVERITY_SCORES[sev],
                                title=f"Pond {p_id.upper()}: Cast-Net Sampling Overdue ({days_samp or 'No'}d)",
                                reason=(
                                    f"Batch '{b_id}' has not had physical growth sampling in {days_samp or '>10'} days. "
                                    "Biomass is running on stale unvalidated estimates."
                                ),
                                supporting_evidence={
                                    "batch_id": b_id,
                                    "days_since_sample": days_samp,
                                    "current_abw_g": current_abw,
                                    "status_quality": prod_intel.get("biomass_detail", {}).get("status_quality"),
                                },
                                confidence="STALE" if days_samp else "NEEDS_DATA",
                                confidence_tooltip=CONFIDENCE_EXPLANATIONS["STALE" if days_samp else "NEEDS_DATA"],
                                recommended_next_step=(
                                    f"ADVISORY: Conduct 30-shrimp cast-net sampling on Pond {p_id.upper()} to measure ABW "
                                    "and recalculate standing biomass."
                                ),
                                source_data_timestamp=now_str,
                                generated_timestamp=now_str,
                                is_advisory=True,
                                physical_state_confirmed=False,
                            )
                        )

                    # Harvest Readiness Indicator
                    readiness = prod_intel.get("harvest_readiness")
                    if not readiness:
                        # Fallback evaluation via batch lifecycle
                        lifecycle = self.records_repo.get_batch_lifecycle(b_id)
                        readiness = lifecycle.get("harvest_readiness") if lifecycle else None

                    if readiness:
                        r_status = readiness.get("readiness_status")
                        if r_status == "READY":
                            sev = ActionSeverity.INFO.value
                            actions.append(
                                FarmActionItem(
                                    action_id=f"act-hrv-ready-{p_id}",
                                    farm_id=farm_id,
                                    pond_id=p_id,
                                    scope="POND",
                                    category=ActionCategory.HARVEST_READINESS.value,
                                    severity=sev,
                                    priority_score=SEVERITY_SCORES[sev],
                                    title=f"Pond {p_id.upper()}: Crop Reached Target ABW ({current_abw:.1f}g / {target_abw:.1f}g)",
                                    reason=f"Batch '{b_id}' shrimp weight meets target harvest specifications with no withdrawal holds.",
                                    supporting_evidence={
                                        "batch_id": b_id,
                                        "current_abw_g": current_abw,
                                        "target_abw_g": target_abw,
                                        "readiness_status": r_status,
                                        "estimated_biomass_kg": prod_intel.get("biomass_detail", {}).get("net_remaining_biomass_kg"),
                                    },
                                    confidence=readiness.get("confidence", "MEASURED"),
                                    confidence_tooltip=CONFIDENCE_EXPLANATIONS.get(readiness.get("confidence", "MEASURED"), ""),
                                    recommended_next_step=(
                                        f"ADVISORY: Plan partial or final crop harvest for Pond {p_id.upper()}. "
                                        "Confirm ice slurry cold-chain logistics."
                                    ),
                                    source_data_timestamp=now_str,
                                    generated_timestamp=now_str,
                                    is_advisory=True,
                                    physical_state_confirmed=False,
                                )
                            )
                        elif r_status == "APPROACHING":
                            sev = ActionSeverity.INFO.value
                            days_est = readiness.get("estimated_days_to_target")
                            actions.append(
                                FarmActionItem(
                                    action_id=f"act-hrv-approaching-{p_id}",
                                    farm_id=farm_id,
                                    pond_id=p_id,
                                    scope="POND",
                                    category=ActionCategory.HARVEST_READINESS.value,
                                    severity=sev,
                                    priority_score=SEVERITY_SCORES[sev],
                                    title=f"Pond {p_id.upper()}: Approaching Target Harvest Weight (≥85%)",
                                    reason=f"Batch '{b_id}' ABW ({current_abw:.1f}g) is ≥85% of target ({target_abw:.1f}g).",
                                    supporting_evidence={
                                        "batch_id": b_id,
                                        "current_abw_g": current_abw,
                                        "target_abw_g": target_abw,
                                        "estimated_days_to_target": days_est,
                                    },
                                    confidence=readiness.get("confidence", "MEASURED"),
                                    confidence_tooltip=CONFIDENCE_EXPLANATIONS.get(readiness.get("confidence", "MEASURED"), ""),
                                    recommended_next_step=(
                                        f"ADVISORY: Track ADG trajectory for Pond {p_id.upper()}; estimated {days_est or '--'} days to target harvest."
                                    ),
                                    source_data_timestamp=now_str,
                                    generated_timestamp=now_str,
                                    is_advisory=True,
                                    physical_state_confirmed=False,
                                )
                            )
            except Exception as e:
                logger.warning("Growth review failed for pond %s: %s", p_id, e)
                partial_failures.append(f"Pond {p_id} growth review failed: {str(e)}")

            # G. Feeding Review
            try:
                today_plans = self.feed_plan_repo.list_plans(
                    farm_id=farm_id,
                    pond_id=p_id,
                    date_from=now.date().isoformat(),
                    date_to=now.date().isoformat(),
                )
                feeding_summary = prod_intel.get("feeding_summary") if "prod_intel" in locals() else None
                today_fed_kg = feeding_summary.get("today_feed_kg", 0.0) if feeding_summary else 0.0

                if today_plans:
                    plan = today_plans[0]
                    planned_kg = plan.planned_daily_kg or 0.0
                    if planned_kg > 0 and today_fed_kg == 0.0 and now.hour >= 12:
                        sev = ActionSeverity.WARNING.value
                        actions.append(
                            FarmActionItem(
                                action_id=f"act-feed-missing-{p_id}",
                                farm_id=farm_id,
                                pond_id=p_id,
                                scope="POND",
                                category=ActionCategory.FEEDING_REVIEW.value,
                                severity=sev,
                                priority_score=SEVERITY_SCORES[sev],
                                title=f"Pond {p_id.upper()}: Zero Fed Logs vs {planned_kg:.1f} kg Planned",
                                reason=(
                                    f"Feed plan schedules {planned_kg:.1f} kg across {plan.feeding_sessions_count} sessions, "
                                    "but 0.0 kg has been logged in farm records past midday."
                                ),
                                supporting_evidence={
                                    "plan_id": plan.plan_id,
                                    "planned_daily_kg": planned_kg,
                                    "actual_fed_kg": today_fed_kg,
                                    "sessions_planned": plan.feeding_sessions_count,
                                },
                                confidence="NEEDS_DATA",
                                confidence_tooltip=CONFIDENCE_EXPLANATIONS["NEEDS_DATA"],
                                recommended_next_step=(
                                    f"ADVISORY: Verify whether morning feed was physically applied on Pond {p_id.upper()} "
                                    "and ensure feeding log is submitted in app."
                                ),
                                source_data_timestamp=now_str,
                                generated_timestamp=now_str,
                                is_advisory=True,
                                physical_state_confirmed=False,
                            )
                        )
            except Exception as e:
                logger.warning("Feeding review failed for pond %s: %s", p_id, e)
                partial_failures.append(f"Pond {p_id} feeding review failed: {str(e)}")

        # 6. Sort all action items by priority score descending
        actions.sort(key=lambda a: a.priority_score, reverse=True)

        # 7. Collect all available filter options before applying filters
        available_ponds = sorted(list(set(p.pond_id for p in ponds if p.pond_id)))
        available_categories = sorted(list(set(a.category for a in actions)))
        available_severities = sorted(list(set(a.severity for a in actions)))

        # 8. Apply Filters if requested
        filtered_actions = actions
        if pond_id_filter:
            if pond_id_filter.upper() == "FARM_WIDE":
                filtered_actions = [a for a in filtered_actions if a.scope == "FARM_WIDE" or not a.pond_id]
            else:
                filtered_actions = [a for a in filtered_actions if a.pond_id == pond_id_filter]
        if category_filter:
            filtered_actions = [a for a in filtered_actions if a.category == category_filter]
        if severity_filter:
            filtered_actions = [a for a in filtered_actions if a.severity == severity_filter]

        # 9. Compute category counts and summary
        category_counts: Dict[str, int] = {}
        for a in filtered_actions:
            category_counts[a.category] = category_counts.get(a.category, 0) + 1

        summary = FarmActionsSummary(
            total_actions=len(filtered_actions),
            emergency_count=sum(1 for a in filtered_actions if a.severity == ActionSeverity.EMERGENCY.value),
            critical_count=sum(1 for a in filtered_actions if a.severity == ActionSeverity.CRITICAL.value),
            warning_count=sum(1 for a in filtered_actions if a.severity == ActionSeverity.WARNING.value),
            info_count=sum(1 for a in filtered_actions if a.severity == ActionSeverity.INFO.value),
            category_counts=category_counts,
        )

        data_status = "DEGRADED" if partial_failures else "COMPLETE"

        return FarmActionsResponse(
            farm_id=farm_id,
            evaluated_at=now_str,
            data_status=data_status,
            partial_failures=partial_failures,
            summary=summary,
            actions=filtered_actions,
            filter_options={
                "ponds": available_ponds,
                "categories": available_categories,
                "severities": available_severities,
            },
        )

