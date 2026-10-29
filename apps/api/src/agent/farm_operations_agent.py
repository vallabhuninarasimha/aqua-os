"""Read-only, evidence-grounded Farm Operations Agent MVP.

The first milestone deliberately uses deterministic intent routing and existing
repositories. A model provider can be added behind this boundary later; safety
and physical control decisions must never depend on an unconstrained LLM.
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from apps.api.src.domain.interfaces import IPondRepository, ITelemetryRepository
from apps.api.src.agent.tool_registry import ReadOnlyFarmToolRegistry
from apps.api.src.agent.llm_provider import synthesize_grounded_answer
from apps.api.src.agent.decision_engine import build_decision_review
from sqlalchemy.orm import Session
from packages.telemetry_schema.models import MetricType


class FarmOperationsAgent:
    """Turn operator questions into scoped, read-only farm intelligence."""

    def __init__(
        self,
        pond_repository: IPondRepository,
        telemetry_repository: ITelemetryRepository,
        *,
        session: Session | None = None,
        allowed_tool_names: set[str] | None = None,
        stale_after_seconds: int = 60,
    ) -> None:
        self._ponds = pond_repository
        self._telemetry = telemetry_repository
        self._stale_after_seconds = stale_after_seconds
        self._tools = ReadOnlyFarmToolRegistry(session) if session is not None else None
        self._allowed_tool_names = allowed_tool_names or set()

    def answer(self, *, farm_id: str, question: str) -> dict[str, Any]:
        """Run deterministic retrieval first, then optionally synthesize a grounded answer."""
        result = self._answer_deterministic(farm_id=farm_id, question=question)
        # Explicit opt-in only: authorized farm data is sent to the configured LLM provider.
        try:
            synthesized = synthesize_grounded_answer(question, result)
        except Exception:
            synthesized = None
        if synthesized:
            result["answer"] = synthesized
            result["mode"] = "READ_ONLY_TOOL_ROUTED_LLM_ASSISTED"
            result.setdefault("limitations", []).append(
                "The wording was synthesized by an optional external LLM from authorized evidence; "
                "verify source records for operational decisions. LLM output cannot execute actions."
            )
        else:
            result["llm_status"] = "DISABLED_OR_UNAVAILABLE_DETERMINISTIC_FALLBACK"
        return result

    def _answer_deterministic(self, *, farm_id: str, question: str) -> dict[str, Any]:
        normalized = " ".join(question.lower().strip().split())
        if not normalized:
            return self._response(
                answer="Ask me about farm status, pond conditions, low dissolved oxygen, or stale/offline sensors.",
                intent="HELP",
                evidence=[],
                limitations=["No question was provided."],
            )

        pond_configs = self._ponds.list(farm_id=farm_id)
        latest = self._telemetry.get_all_latest_with_evaluations(farm_id=farm_id)
        now = datetime.now(timezone.utc)
        snapshots: list[dict[str, Any]] = []

        for pond in pond_configs:
            record = latest.get(pond.pond_id)
            if not record:
                snapshots.append({
                    "pond_id": pond.pond_id,
                    "name": pond.name,
                    "status": "UNKNOWN",
                    "source": "NO_TELEMETRY",
                    "is_simulated": None,
                    "age_seconds": None,
                    "dissolved_oxygen_mg_l": None,
                    "temperature_c": None,
                    "ph": None,
                    "salinity_ppt": None,
                    "alerts": ["No telemetry record available"],
                })
                continue

            packet, evaluation = record
            timestamp = packet.timestamp
            if timestamp.tzinfo is None:
                timestamp = timestamp.replace(tzinfo=timezone.utc)
            age_seconds = max(0.0, (now - timestamp.astimezone(timezone.utc)).total_seconds())
            is_stale = age_seconds > self._stale_after_seconds
            severity = evaluation.severity.value if evaluation else "UNKNOWN"
            if is_stale:
                status = "DEGRADED"
            elif severity in {"EMERGENCY", "CRITICAL"}:
                status = "CRITICAL"
            elif severity == "WARNING":
                status = "WARNING"
            elif severity == "DEGRADED":
                status = "DEGRADED"
            elif evaluation is None:
                status = "UNKNOWN"
            else:
                status = "NORMAL"

            def metric(metric_type: MetricType) -> float | None:
                reading = packet.metrics.get(metric_type)
                if not reading or reading.quality.value not in {"GOOD", "SUSPECT_DRIFT"}:
                    return None
                return reading.value

            alerts = list(evaluation.messages) if evaluation else []
            if is_stale:
                alerts.append(f"Telemetry is stale ({int(age_seconds)} seconds old)")
            snapshots.append({
                "pond_id": pond.pond_id,
                "name": pond.name,
                "status": status,
                "source": "SIMULATED" if packet.is_simulated else "MEASURED_TELEMETRY",
                "is_simulated": packet.is_simulated,
                "timestamp": timestamp.isoformat(),
                "age_seconds": round(age_seconds, 1),
                "dissolved_oxygen_mg_l": metric(MetricType.DISSOLVED_OXYGEN),
                "temperature_c": metric(MetricType.TEMPERATURE),
                "ph": metric(MetricType.PH),
                "salinity_ppt": metric(MetricType.SALINITY),
                "alerts": alerts,
            })

        # Explicit farm-wide/cross-module questions use several fixed read-only
        # tools so evidence can be correlated without allowing arbitrary tool calls.
        cross_module_tools = self._select_cross_module_tools(normalized)
        if cross_module_tools and self._tools is not None:
            selected = [name for name in cross_module_tools if name in self._allowed_tool_names]
            evidence = []
            summaries = []
            for tool_name in selected:
                try:
                    tool_result = self._tools.run(tool_name, farm_id=farm_id)
                    data_class = next((t.data_class for t in self._tools.definitions() if t.name == tool_name), "UNKNOWN")
                    evidence.append({"tool": tool_name, "data_class": data_class, "result": tool_result})
                    summaries.append(self._domain_answer(tool_name, tool_result))
                except Exception:
                    evidence.append({"tool": tool_name, "data_class": "UNAVAILABLE", "error": "Domain data could not be retrieved."})
                    summaries.append(f"{tool_name.replace('_', ' ')}: unavailable; no result inferred.")
            missing_permissions = [name for name in cross_module_tools if name not in self._allowed_tool_names]
            if missing_permissions:
                summaries.append("Some requested domains were omitted because your role lacks permission to retrieve them: " + ", ".join(missing_permissions) + ".")
            if evidence:
                response = self._response(
                    answer="Cross-module review completed from the current authorized services. " + " ".join(summaries),
                    intent="CROSS_MODULE_REVIEW", evidence=evidence,
                    limitations=[
                        "Each domain is retrieved independently; a missing subsystem result is not interpreted as a healthy state.",
                        "Calculated estimates and software states are not equivalent to physical measurements or confirmed equipment state.",
                        "This review is read-only and does not execute operations.",
                    ], evaluated_at=now.isoformat(),
                )
                response["decision_review"] = build_decision_review(evidence, evaluated_at=now.isoformat())
                review = response["decision_review"]
                response["answer"] += (
                    f" Decision review: {review['finding_count']} source-backed action findings; "
                    f"review status {review['status']}."
                )
                if review["source_tools_unavailable"]:
                    response["answer"] += " Unavailable sources: " + ", ".join(review["source_tools_unavailable"]) + "."
                return response

        # Route single-domain questions only to a fixed allow-list of read-only tools.
        # The model/user never supplies executable function names or code.
        tool_intent = self._select_domain_tool(normalized)
        if tool_intent and self._tools is not None:
            tool_name, tool_pond_id = tool_intent
            if tool_name not in self._allowed_tool_names:
                return self._response(
                    answer="Your account does not have permission to retrieve that module's data through the agent.",
                    intent=tool_name.upper(), evidence=[],
                    limitations=["No domain data was retrieved and no action was taken. Ask a farm administrator to review your role permissions."],
                    evaluated_at=now.isoformat(),
                )
            try:
                tool_result = self._tools.run(tool_name, farm_id=farm_id, pond_id=tool_pond_id)
                return self._response(
                    answer=self._domain_answer(tool_name, tool_result),
                    intent=tool_name.upper(),
                    evidence=[{"tool": tool_name, "data_class": next((t.data_class for t in self._tools.definitions() if t.name == tool_name), "UNKNOWN"), "result": tool_result}],
                    limitations=[
                        "Read-only summary from existing Aqua OS domain services; it does not perform operations.",
                        "Calculated estimates and software-reported states are not equivalent to physical measurements or confirmed equipment state.",
                        "Review the underlying module records before making high-impact farm, treatment, harvest, or financial decisions.",
                    ],
                    evaluated_at=now.isoformat(),
                )
            except (ValueError, KeyError) as exc:
                return self._response(
                    answer="I could not retrieve that domain summary from the authorized farm records.",
                    intent=tool_name.upper(),
                    evidence=[],
                    limitations=[str(exc), "No operational action was taken."],
                    evaluated_at=now.isoformat(),
                )
            except Exception:
                # A domain subsystem may be unavailable; do not make up a result.
                return self._response(
                    answer=f"The {tool_name.replace('_', ' ')} subsystem is currently unavailable. Please open that module to inspect its status.",
                    intent=tool_name.upper(),
                    evidence=[],
                    limitations=["The tool failed to retrieve data; no result has been inferred and no action was taken."],
                    evaluated_at=now.isoformat(),
                )

        pond_match = re.search(r"\bpond[- ]?(\d{1,3})\b", normalized)
        selected_pond = None
        if pond_match:
            requested_id = f"pond-{int(pond_match.group(1)):02d}"
            selected_pond = next(
                (item for item in snapshots if item["pond_id"].lower() == requested_id),
                None,
            )
            if selected_pond is None:
                selected_pond = next(
                    (item for item in snapshots if item["pond_id"].lower() in {normalized, normalized.replace(" ", "-")}),
                    None,
                )

        if any(term in normalized for term in ("low oxygen", "low do", "dissolved oxygen", "hypoxia", "oxygen")):
            intent = "LOW_OXYGEN_RISK"
            relevant = [
                item for item in snapshots
                if item["dissolved_oxygen_mg_l"] is not None
                and item["dissolved_oxygen_mg_l"] < 4.0
            ]
            relevant.extend(
                item for item in snapshots
                if item["dissolved_oxygen_mg_l"] is None and item["status"] in {"UNKNOWN", "DEGRADED"}
            )
            relevant = self._unique(relevant)
            if not relevant:
                answer = "No low-DO condition is evidenced by the latest available readings. This does not prove every pond is safe; check data freshness and sensor coverage."
            else:
                answer = self._pond_summary(relevant, "Low-oxygen review is needed for")
                answer += " Treat this as an advisory: verify the physical sensor and aerator locally."
        elif any(term in normalized for term in ("offline", "stale", "sensor", "not reporting", "no data")):
            intent = "TELEMETRY_HEALTH"
            relevant = [item for item in snapshots if item["status"] in {"UNKNOWN", "DEGRADED"}]
            answer = self._pond_summary(relevant, "Telemetry needs attention for") if relevant else "All configured ponds have recent telemetry according to the current freshness rule. Verify sensor calibration and physical connectivity where needed."
        elif selected_pond:
            intent = "POND_STATUS"
            relevant = [selected_pond]
            answer = self._pond_summary(relevant, "Latest status")
        else:
            intent = "FARM_OVERVIEW"
            relevant = sorted(
                snapshots,
                key=lambda item: ({"CRITICAL": 0, "DEGRADED": 1, "WARNING": 2, "UNKNOWN": 3, "NORMAL": 4}.get(item["status"], 5), item["pond_id"]),
            )
            counts = {key: sum(1 for item in snapshots if item["status"] == key) for key in ("CRITICAL", "WARNING", "DEGRADED", "UNKNOWN", "NORMAL")}
            answer = (
                f"Farm {farm_id}: {len(snapshots)} configured ponds; "
                f"{counts['CRITICAL']} critical, {counts['WARNING']} warning, "
                f"{counts['DEGRADED']} degraded/stale, {counts['UNKNOWN']} unknown, "
                f"{counts['NORMAL']} normal based on latest telemetry and safety evaluations."
            )
            if counts["CRITICAL"] or counts["DEGRADED"] or counts["UNKNOWN"]:
                answer += " Review critical and missing/stale-data ponds first."

        return self._response(
            answer=answer,
            intent=intent,
            evidence=relevant,
            limitations=[
                "Read-only advisory; this agent does not operate pumps, aerators, feeders, or dosing equipment.",
                "A missing or stale reading is unknown/degraded, not evidence that the pond is safe.",
                "Thresholds are inherited from the farm's configured safety evaluator and must be validated for the actual farm.",
            ],
            evaluated_at=now.isoformat(),
        )

    @staticmethod
    def _select_cross_module_tools(question: str) -> list[str] | None:
        cross_domain_cues = ("across modules", "cross module", "cross-module", "compare", "correlate", "overall farm operations", "complete farm review", "whole farm", "farm health and finances", "all modules")
        if any(cue in question for cue in cross_domain_cues):
            if any(cue in question for cue in ("finance", "financial", "cash", "profit", "cost")):
                return ["farm_actions", "production_summary", "feed_inventory", "water_status", "power_status", "working_capital"]
            if any(cue in question for cue in ("feed", "growth", "production", "biomass")):
                return ["farm_actions", "production_summary", "feed_inventory", "water_status"]
            return ["farm_actions", "production_summary", "feed_inventory", "water_status", "power_status"]
        return None

    @staticmethod
    def _select_domain_tool(question: str) -> tuple[str, str | None] | None:
        pond_match = re.search(r"\bpond[- ]?(\d{1,3})\b", question)
        pond_id = f"pond-{int(pond_match.group(1)):02d}" if pond_match else None
        if any(term in question for term in ("action center", "priority action", "what should i do", "what needs attention", "farm actions", "recommendations", "urgent action")):
            return ("farm_actions", None)
        if any(term in question for term in ("feed inventory", "feed stock", "stock balance", "feed available", "reorder", "inventory")):
            return ("feed_inventory", None)
        if any(term in question for term in ("production summary", "farm biomass", "total biomass", "growth summary", "production status", "fcr")):
            return ("production_summary", None)
        if any(term in question for term in ("water level", "water status", "outlet status", "drain status", "water management")):
            return ("water_status", None)
        if any(term in question for term in ("transformer", "power load", "power status", "electrical load", "power capacity")):
            return ("power_status", None)
        if any(term in question for term in ("cash flow", "working capital", "cash position", "farm finances", "financial summary", "receivables", "payables")):
            return ("working_capital", None)
        if pond_id and any(term in question for term in ("health", "mortality", "disease", "treatment", "health status")):
            return ("pond_health", pond_id)
        if any(term in question for term in ("telemetry health", "sensor health", "offline sensor", "stale sensor", "sensor status", "sensor reporting")):
            return ("telemetry_health", None)
        if any(term in question for term in ("low oxygen risk", "hypoxia risk", "oxygen risk", "critical oxygen", "suffocation risk")):
            return ("low_oxygen_risk", None)
        return None

    @staticmethod
    def _domain_answer(tool_name: str, result: dict[str, Any]) -> str:
        summaries = {
            "farm_overview": "Retrieved latest telemetry and health states across all configured ponds.",
            "pond_status": "Retrieved latest telemetry packet and biological safety evaluation for the pond.",
            "low_oxygen_risk": "Retrieved ponds flagged with dissolved oxygen depletion or missing/stale telemetry.",
            "telemetry_health": "Retrieved telemetry data freshness and communication health report across all ponds.",
            "farm_actions": "Retrieved the current prioritized farm action list from the Action Engine. Review each item's severity, evidence, confidence and suggested next step; this agent has not executed any action.",
            "production_summary": "Retrieved the farm production summary. Biomass, growth and FCR values may be calculated estimates; check each field's confidence and data status before using it for harvest decisions.",
            "feed_inventory": "Retrieved recorded feed inventory balances and stock warnings. Confirm physical stock before ordering or changing a feeding plan.",
            "water_status": "Retrieved water-level and outlet software states. These do not prove the physical valve or water level without commissioned sensors/limit switches.",
            "power_status": "Retrieved configured transformer load estimates. Ratings and headroom require field verification; this result does not authorize switching equipment.",
            "working_capital": "Retrieved the recorded cash/working-capital summary. Missing or unrecorded transactions may make the summary incomplete.",
            "pond_health": "Retrieved the pond health summary. This is decision support, not a confirmed diagnosis or treatment prescription.",
        }
        return summaries.get(tool_name, "Retrieved data from the selected farm module.")

    @staticmethod
    def _unique(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        return list({item["pond_id"]: item for item in items}.values())

    @staticmethod
    def _pond_summary(items: list[dict[str, Any]], prefix: str) -> str:
        if not items:
            return "No matching ponds were found in the authorized farm data."
        parts = []
        for item in items:
            do_value = item.get("dissolved_oxygen_mg_l")
            do_text = f", DO {do_value:.2f} mg/L" if do_value is not None else ", DO unavailable"
            age = item.get("age_seconds")
            age_text = f", reading age {int(age)}s" if age is not None else ", no reading timestamp"
            parts.append(f"{item['pond_id']} ({item['status']}{do_text}{age_text}; {item['source']})")
        return f"{prefix}: " + "; ".join(parts) + "."

    @staticmethod
    def _response(
        *,
        answer: str,
        intent: str,
        evidence: list[dict[str, Any]],
        limitations: list[str],
        evaluated_at: str | None = None,
    ) -> dict[str, Any]:
        return {
            "agent": "farm_operations_agent",
            "agent_version": "0.6.0",
            "mode": "READ_ONLY_TOOL_ROUTED_MVP",
            "intent": intent,
            "answer": answer,
            "evidence": evidence,
            "limitations": limitations,
            "evaluated_at": evaluated_at,
        }
