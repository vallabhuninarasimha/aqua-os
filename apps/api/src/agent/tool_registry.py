"""Permission-bounded, read-only tool registry for the Farm Operations Agent.

Only explicitly registered tools can be invoked. This registry intentionally has
no write/actuation tools; all physical control remains in the local safety layer.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from sqlalchemy.orm import Session

from datetime import datetime, timezone

from apps.api.src.services.farm_action_service import FarmActionDecisionService
from apps.api.src.services.feed_inventory_service import FeedInventoryService
from apps.api.src.services.finance_service import FinanceService
from apps.api.src.services.growth_production_service import GrowthProductionService
from apps.api.src.services.health_service import HealthService
from apps.api.src.services.power_service import PowerMonitoringService
from apps.api.src.services.water_service import WaterManagementService
from apps.api.src.infrastructure.repositories.sql_pond_repository import SQLPondRepository
from apps.api.src.infrastructure.repositories.sql_telemetry_repository import SQLTelemetryRepository
from packages.telemetry_schema.models import MetricType


@dataclass(frozen=True)
class AgentTool:
    name: str
    description: str
    data_class: str


class ReadOnlyFarmToolRegistry:
    """Expose selected existing domain services as scoped read-only agent tools."""

    def __init__(self, session: Session) -> None:
        self._session = session

    @staticmethod
    def definitions() -> list[AgentTool]:
        return [
            AgentTool("farm_overview", "Summarize pond states from latest authorized telemetry", "MEASURED_AND_EVALUATED"),
            AgentTool("pond_status", "Inspect latest telemetry and status for a requested pond", "MEASURED_AND_EVALUATED"),
            AgentTool("low_oxygen_risk", "Find ponds with low measured DO or missing/stale evidence", "DERIVED_ADVISORY"),
            AgentTool("telemetry_health", "Find ponds with missing or stale telemetry", "MEASURED_QUALITY"),
            AgentTool("farm_actions", "Prioritized cross-module action items and evidence", "DERIVED_ADVISORY"),
            AgentTool("production_summary", "Recorded and calculated farm production summary", "CALCULATED_ESTIMATE"),
            AgentTool("feed_inventory", "Feed inventory balance and low-stock summary", "RECORDED_INVENTORY"),
            AgentTool("water_status", "Pond water-level and outlet software status", "SOFTWARE_STATE_UNCONFIRMED_PHYSICALLY"),
            AgentTool("power_status", "Configured transformer load and estimated headroom", "ESTIMATE_REQUIRES_FIELD_VERIFICATION"),
            AgentTool("working_capital", "Recorded cash and working-capital summary", "RECORDED_FINANCIALS"),
            AgentTool("pond_health", "Health summary for a requested pond", "RECORDED_AND_ADVISORY"),
        ]

    def run(self, name: str, *, farm_id: str, pond_id: str | None = None) -> dict[str, Any]:
        # No caller-provided service names, imports, SQL, or arbitrary method dispatch.
        if name == "farm_overview":
            pond_configs = SQLPondRepository(self._session).list(farm_id=farm_id)
            latest = SQLTelemetryRepository(self._session).get_all_latest_with_evaluations(farm_id=farm_id)
            now = datetime.now(timezone.utc)
            pond_summaries = []
            counts = {"CRITICAL": 0, "WARNING": 0, "DEGRADED": 0, "UNKNOWN": 0, "NORMAL": 0}
            for pond in pond_configs:
                record = latest.get(pond.pond_id)
                if not record:
                    counts["UNKNOWN"] += 1
                    pond_summaries.append({
                        "pond_id": pond.pond_id,
                        "name": pond.name,
                        "status": "UNKNOWN",
                        "source": "NO_TELEMETRY",
                        "age_seconds": None,
                        "alerts": ["No telemetry recorded"],
                    })
                    continue
                packet, evaluation = record
                ts = packet.timestamp if packet.timestamp.tzinfo else packet.timestamp.replace(tzinfo=timezone.utc)
                age = max(0.0, (now - ts).total_seconds())
                is_stale = age > 60.0
                severity = evaluation.severity.value if evaluation else "UNKNOWN"
                status = "DEGRADED" if is_stale else (severity if severity in {"CRITICAL", "WARNING", "DEGRADED"} else "NORMAL")
                counts[status] = counts.get(status, 0) + 1
                metrics = {k.value: v.value for k, v in packet.metrics.items() if v.quality.value in {"GOOD", "SUSPECT_DRIFT"}}
                pond_summaries.append({
                    "pond_id": pond.pond_id,
                    "name": pond.name,
                    "status": status,
                    "source": "SIMULATED" if packet.is_simulated else "MEASURED_TELEMETRY",
                    "age_seconds": round(age, 1),
                    "metrics": metrics,
                    "alerts": list(evaluation.messages) if evaluation else [],
                })
            return {
                "farm_id": farm_id,
                "total_ponds": len(pond_configs),
                "status_counts": counts,
                "ponds": pond_summaries,
            }
        if name == "pond_status":
            if not pond_id:
                raise ValueError("pond_id is required for pond_status")
            pond = SQLPondRepository(self._session).get(farm_id, pond_id)
            if pond is None:
                raise ValueError("pond not found in authorized farm")
            record = SQLTelemetryRepository(self._session).get_latest(farm_id, pond_id)
            now = datetime.now(timezone.utc)
            if not record:
                return {
                    "farm_id": farm_id,
                    "pond_id": pond_id,
                    "name": pond.name,
                    "status": "UNKNOWN",
                    "source": "NO_TELEMETRY",
                    "telemetry": None,
                    "safety_evaluation": None,
                }
            packet, evaluation = record
            ts = packet.timestamp if packet.timestamp.tzinfo else packet.timestamp.replace(tzinfo=timezone.utc)
            age = max(0.0, (now - ts).total_seconds())
            return {
                "farm_id": farm_id,
                "pond_id": pond_id,
                "name": pond.name,
                "status": evaluation.severity.value if evaluation else "NORMAL",
                "source": "SIMULATED" if packet.is_simulated else "MEASURED_TELEMETRY",
                "timestamp": ts.isoformat(),
                "age_seconds": round(age, 1),
                "metrics": {k.value: {"value": v.value, "quality": v.quality.value} for k, v in packet.metrics.items()},
                "safety_evaluation": evaluation.model_dump(mode="json") if evaluation else None,
            }
        if name == "low_oxygen_risk":
            pond_configs = SQLPondRepository(self._session).list(farm_id=farm_id)
            latest = SQLTelemetryRepository(self._session).get_all_latest_with_evaluations(farm_id=farm_id)
            now = datetime.now(timezone.utc)
            at_risk = []
            for pond in pond_configs:
                record = latest.get(pond.pond_id)
                if not record:
                    at_risk.append({
                        "pond_id": pond.pond_id,
                        "name": pond.name,
                        "risk_type": "NO_TELEMETRY",
                        "do_mg_l": None,
                        "age_seconds": None,
                        "advisory": "No dissolved oxygen telemetry available to verify safety",
                    })
                    continue
                packet, evaluation = record
                ts = packet.timestamp if packet.timestamp.tzinfo else packet.timestamp.replace(tzinfo=timezone.utc)
                age = max(0.0, (now - ts).total_seconds())
                do_reading = packet.metrics.get(MetricType.DISSOLVED_OXYGEN)
                do_val = do_reading.value if (do_reading and do_reading.quality.value in {"GOOD", "SUSPECT_DRIFT"}) else None
                if do_val is not None and do_val < 4.0:
                    at_risk.append({
                        "pond_id": pond.pond_id,
                        "name": pond.name,
                        "risk_type": "LOW_DO",
                        "do_mg_l": do_val,
                        "age_seconds": round(age, 1),
                        "advisory": f"Critical dissolved oxygen depletion ({do_val} mg/L < 4.0 mg/L minimum)",
                    })
                elif age > 60.0:
                    at_risk.append({
                        "pond_id": pond.pond_id,
                        "name": pond.name,
                        "risk_type": "STALE_TELEMETRY",
                        "do_mg_l": do_val,
                        "age_seconds": round(age, 1),
                        "advisory": f"Dissolved oxygen telemetry is stale ({int(age)}s old)",
                    })
            return {"farm_id": farm_id, "at_risk_count": len(at_risk), "ponds": at_risk}
        if name == "telemetry_health":
            pond_configs = SQLPondRepository(self._session).list(farm_id=farm_id)
            latest = SQLTelemetryRepository(self._session).get_all_latest_with_evaluations(farm_id=farm_id)
            now = datetime.now(timezone.utc)
            health_issues = []
            for pond in pond_configs:
                record = latest.get(pond.pond_id)
                if not record:
                    health_issues.append({
                        "pond_id": pond.pond_id,
                        "name": pond.name,
                        "issue": "NO_DATA",
                        "age_seconds": None,
                    })
                    continue
                packet, _ = record
                ts = packet.timestamp if packet.timestamp.tzinfo else packet.timestamp.replace(tzinfo=timezone.utc)
                age = max(0.0, (now - ts).total_seconds())
                if age > 60.0:
                    health_issues.append({
                        "pond_id": pond.pond_id,
                        "name": pond.name,
                        "issue": "STALE",
                        "age_seconds": round(age, 1),
                        "last_seen": ts.isoformat(),
                    })
            return {
                "farm_id": farm_id,
                "healthy_count": len(pond_configs) - len(health_issues),
                "issue_count": len(health_issues),
                "issues": health_issues,
            }
        if name == "farm_actions":
            result = FarmActionDecisionService(self._session).generate_farm_actions(farm_id)
            return self._serialize(result)
        if name == "production_summary":
            return GrowthProductionService(self._session).get_farm_production_summary(farm_id)
        if name == "feed_inventory":
            return FeedInventoryService(self._session).get_farm_inventory_summary(farm_id)
        if name == "water_status":
            service = WaterManagementService(self._session)
            return {"ponds": service.list_farm_water_status(farm_id)}
        if name == "power_status":
            items = PowerMonitoringService(self._session).get_farm_power_summary(farm_id)
            return {"transformers": [self._serialize(item) for item in items]}
        if name == "working_capital":
            return FinanceService(self._session).get_working_capital_summary(farm_id)
        if name == "pond_health":
            if not pond_id:
                raise ValueError("pond_id is required for pond_health")
            # Verify that the requested pond belongs to the selected farm before
            # asking a domain service for its health summary.
            pond = SQLPondRepository(self._session).get(farm_id, pond_id)
            if pond is None:
                raise ValueError("pond not found in authorized farm")
            return HealthService(self._session).get_pond_health_summary(farm_id, pond_id)
        raise ValueError("Unknown agent tool")

    @classmethod
    def _serialize(cls, value: Any) -> Any:
        if hasattr(value, "model_dump"):
            return value.model_dump(mode="json")
        if hasattr(value, "dict") and callable(value.dict):
            return value.dict()
        if isinstance(value, list):
            return [cls._serialize(item) for item in value]
        if isinstance(value, dict):
            return {str(k): cls._serialize(v) for k, v in value.items()}
        if hasattr(value, "__dict__") and not isinstance(value, type):
            return {k: cls._serialize(v) for k, v in vars(value).items() if not k.startswith("_")}
        return value
