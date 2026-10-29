"""Domain definitions, models, and categorization rules for Aqua OS Farm Action & Decision Engine.

Clean Architecture domain entity models:
- Encapsulates action items, categories, severities, and prioritization logic.
- Pure domain models without direct framework dependencies.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class ActionCategory(str, Enum):
    SENSOR_DATA_UNAVAILABLE = "SENSOR_DATA_UNAVAILABLE"
    WATER_QUALITY_REVIEW = "WATER_QUALITY_REVIEW"
    AERATION_REVIEW = "AERATION_REVIEW"
    FEEDING_REVIEW = "FEEDING_REVIEW"
    FEED_INVENTORY_REVIEW = "FEED_INVENTORY_REVIEW"
    MORTALITY_REVIEW = "MORTALITY_REVIEW"
    GROWTH_SAMPLE_REQUIRED = "GROWTH_SAMPLE_REQUIRED"
    HARVEST_READINESS = "HARVEST_READINESS"
    CHEMICAL_WITHDRAWAL_BLOCK = "CHEMICAL_WITHDRAWAL_BLOCK"
    POWER_CONFIGURATION_REQUIRED = "POWER_CONFIGURATION_REQUIRED"
    EQUIPMENT_STATUS_UNKNOWN = "EQUIPMENT_STATUS_UNKNOWN"


class ActionSeverity(str, Enum):
    EMERGENCY = "EMERGENCY"
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


SEVERITY_SCORES: Dict[str, int] = {
    ActionSeverity.EMERGENCY.value: 4,
    ActionSeverity.CRITICAL.value: 3,
    ActionSeverity.WARNING.value: 2,
    ActionSeverity.INFO.value: 1,
}

CONFIDENCE_EXPLANATIONS: Dict[str, str] = {
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
    "THEORETICAL_ESTIMATE": "Theoretical calculation based on 80% continuous rating minus estimated load.",
}


class FarmActionItem(BaseModel):
    """Evidence-backed operational action item for farm managers."""
    action_id: str
    farm_id: str
    pond_id: Optional[str] = None
    scope: str = "POND"  # "POND" or "FARM_WIDE"
    category: str
    severity: str
    priority_score: int = 1
    title: str
    reason: str
    supporting_evidence: Dict[str, Any] = Field(default_factory=dict)
    confidence: str
    confidence_tooltip: str
    recommended_next_step: str
    source_data_timestamp: Optional[str] = None
    generated_timestamp: str
    is_advisory: bool = True
    physical_state_confirmed: bool = False


class FarmActionsSummary(BaseModel):
    """High-level summary rollup of all active actionable items across farm."""
    total_actions: int
    emergency_count: int
    critical_count: int
    warning_count: int
    info_count: int
    category_counts: Dict[str, int] = Field(default_factory=dict)


class FarmActionsResponse(BaseModel):
    """Complete bundle returned by the Farm-wide Action & Decision Engine."""
    farm_id: str
    evaluated_at: str
    data_status: str  # "COMPLETE", "DEGRADED", "UNAVAILABLE"
    partial_failures: List[str] = Field(default_factory=list)
    summary: FarmActionsSummary
    actions: List[FarmActionItem]
    filter_options: Dict[str, Any]
    confidence_definitions: Dict[str, str] = Field(default_factory=lambda: CONFIDENCE_EXPLANATIONS)
    advisory_disclaimer: str = (
        "Recommendations are evidence-backed operational advisories derived strictly from recorded "
        "farm records. Actuators operate in DRY_RUN mode. Biological assumptions or prices are never fabricated."
    )

