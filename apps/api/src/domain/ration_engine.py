"""Shrimp Feed Planning & Ration Intelligence Engine.

Domain models and calculation rules for pond- and batch-specific feed recommendations:
- Unit-safe daily ration estimation based on live biomass and ABW
- Environmental factor adjustments (Dissolved Oxygen, Water Temperature)
- Feeding tray consumption feedback
- Data completeness checking and provenance tracking (NEEDS_DATA vs ADVISORY)
- Multi-session distribution and schedule splits
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field


class RationInputSnapshot(BaseModel):
    """Snapshot of inputs used to calculate feed ration for auditability."""
    farm_id: str
    pond_id: str
    batch_id: str
    batch_doc: int
    stocking_count: int
    estimated_survival_pct: float
    estimated_population: int
    avg_body_weight_g: float
    abw_sample_date: Optional[str] = None
    abw_source: str = "ESTIMATE"  # PHYSICAL_SAMPLING, PL_BASELINE, MANUAL
    is_sample_stale: bool = False
    estimated_biomass_kg: float
    current_do_mg_l: Optional[float] = None
    current_temp_c: Optional[float] = None
    telemetry_timestamp: Optional[str] = None
    latest_tray_observation: Optional[str] = None
    base_feed_rate_pct: float
    guidance_source: str = "Standard P. vannamei manufacturer feeding rate guidelines"


class RationRecommendationResult(BaseModel):
    """Result of feed ration intelligence calculation."""
    status: str  # RECOMMENDED, REDUCED_ADVISORY, HOLD_WATER_QUALITY, NEEDS_DATA
    recommended_daily_kg: Optional[float] = None
    recommended_sessions_count: int = 4
    recommended_session_times: List[str] = Field(default_factory=lambda: ["06:00", "11:00", "16:00", "21:00"])
    confidence_label: str  # CALCULATED_RECENT_SAMPLE, PROVISIONAL_BASELINE_ADVISORY, PROVISIONAL_STALE_SAMPLE, NEEDS_DATA
    recommendation_basis: str  # ADVISORY, REDUCED_DO, REDUCED_TEMP, REDUCED_TRAYS, HOLD_ANOXIA, NEEDS_DATA
    inputs_snapshot: Dict[str, Any] = Field(default_factory=dict)
    adjustment_factors: Dict[str, float] = Field(default_factory=dict)
    warnings: List[str] = Field(default_factory=list)
    action_guidance: str


def get_manufacturer_base_feed_rate_pct(abw_g: float) -> float:
    """Standard manufacturer feeding guideline rate (% body weight per day) for P. vannamei.
    
    Ref: FAO & Commercial Shrimp Feeds standard bodyweight feeding curves:
    - PL to early juvenile (< 3.0g): 5.5% - 6.5%
    - Small juvenile (3.0g - 7.0g): 4.5% - 5.5%
    - Sub-adult (7.0g - 12.0g): 3.8% - 4.5%
    - Developing adult (12.0g - 18.0g): 3.2% - 3.8%
    - Market size (18.0g - 25.0g): 2.6% - 3.2%
    - Large adult (> 25.0g): 2.1% - 2.5%
    """
    if abw_g <= 0.0:
        return 0.0
    if abw_g < 3.0:
        return 5.8
    elif abw_g < 7.0:
        return 4.6
    elif abw_g < 12.0:
        return 3.8
    elif abw_g < 18.0:
        return 3.1
    elif abw_g < 25.0:
        return 2.6
    else:
        return 2.2


def calculate_feed_ration(
    farm_id: str,
    pond_id: str,
    batch_id: Optional[str],
    batch_doc: int,
    stocking_count: int,
    estimated_survival_pct: float,
    abw_g: float,
    abw_sample_date: Optional[datetime] = None,
    abw_source: str = "PHYSICAL_SAMPLING",
    do_mg_l: Optional[float] = None,
    temp_c: Optional[float] = None,
    telemetry_time: Optional[datetime] = None,
    tray_observation: Optional[str] = None,
    custom_sessions_count: int = 4,
    custom_session_times: Optional[List[str]] = None,
) -> RationRecommendationResult:
    """Calculate daily feed ration recommendation with water quality & tray adjustments.
    
    Adheres strictly to domain safety:
    - Never fabricates unknown biomass: returns NEEDS_DATA if batch or ABW is missing.
    - Labels output as ADVISORY until farm manager verification.
    - Applies safety reductions for hypoxic water quality (< 4.0 mg/L DO) or temperature extremes.
    - Captures complete provenance in inputs_snapshot.
    """
    warnings: List[str] = []
    adjustments: Dict[str, float] = {}

    # Check essential inputs
    if not batch_id or stocking_count <= 0 or abw_g <= 0.0:
        missing_reasons = []
        if not batch_id:
            missing_reasons.append("No active stocking batch associated with pond.")
        if stocking_count <= 0:
            missing_reasons.append("Invalid or zero initial stocked population.")
        if abw_g <= 0.0:
            missing_reasons.append("Missing or non-positive Average Body Weight (ABW).")

        return RationRecommendationResult(
            status="NEEDS_DATA",
            recommended_daily_kg=None,
            recommended_sessions_count=custom_sessions_count,
            recommended_session_times=custom_session_times or ["06:00", "11:00", "16:00", "21:00"],
            recommended_kg_per_session=None,
            confidence_label="NEEDS_DATA",
            recommendation_basis="NEEDS_DATA",
            inputs_snapshot={
                "farm_id": farm_id,
                "pond_id": pond_id,
                "batch_id": batch_id,
                "stocking_count": stocking_count,
                "abw_g": abw_g,
            },
            adjustment_factors={},
            warnings=missing_reasons,
            action_guidance="Log a recent biomass sampling or configure active stocking batch to enable ration intelligence.",
        )

    # Population & Biomass estimation
    clamped_survival = max(0.0, min(100.0, estimated_survival_pct))
    if estimated_survival_pct > 100.0:
        warnings.append(f"Survival percentage ({estimated_survival_pct:.1f}%) clamped to 100%.")
    elif estimated_survival_pct <= 0.0:
        warnings.append("Survival percentage is 0% or negative; cannot calculate live feeding ration.")
        return RationRecommendationResult(
            status="NEEDS_DATA",
            recommended_daily_kg=None,
            recommended_sessions_count=custom_sessions_count,
            recommended_session_times=custom_session_times or ["06:00", "11:00", "16:00", "21:00"],
            recommended_kg_per_session=None,
            confidence_label="NEEDS_DATA",
            recommendation_basis="NEEDS_DATA",
            inputs_snapshot={"survival_pct": estimated_survival_pct},
            adjustment_factors={},
            warnings=warnings,
            action_guidance="Verify surviving population estimate. Stocking records report 0% survival.",
        )

    estimated_population = int(round(stocking_count * (clamped_survival / 100.0)))
    estimated_biomass_kg = round((estimated_population * abw_g) / 1000.0, 2)

    # Check sample freshness
    is_sample_stale = False
    now_utc = datetime.now(timezone.utc)
    if abw_sample_date:
        if abw_sample_date.tzinfo is None:
            abw_sample_date = abw_sample_date.replace(tzinfo=timezone.utc)
        days_since_sample = (now_utc - abw_sample_date).total_seconds() / 86400.0
        if days_since_sample > 10.0:
            is_sample_stale = True
            warnings.append(
                f"Sampling data is {int(days_since_sample)} days old (> 10 days). Ration recommendation is provisional."
            )
    else:
        if abw_source != "PHYSICAL_SAMPLING":
            warnings.append("Using baseline stocking PL estimate. Physical weight sampling strongly recommended.")

    # Base ration calculation from body weight percentage
    base_rate_pct = get_manufacturer_base_feed_rate_pct(abw_g)
    base_ration_kg = estimated_biomass_kg * (base_rate_pct / 100.0)

    # Environmental Adjustments
    net_multiplier = 1.0

    # 1. Dissolved Oxygen adjustment
    if do_mg_l is not None:
        if do_mg_l < 3.0:
            # Critical low DO - Hold or severe emergency cut
            net_multiplier *= 0.0
            adjustments["do_factor"] = 0.0
            warnings.append(f"Critical low DO ({do_mg_l:.2f} mg/L < 3.0 mg/L). Immediate feeding hold advised to avert mortality.")
        elif do_mg_l < 3.8:
            # Sub-optimal DO - 35% reduction
            net_multiplier *= 0.65
            adjustments["do_factor"] = 0.65
            warnings.append(f"Low DO ({do_mg_l:.2f} mg/L < 3.8 mg/L). Ration reduced by 35% to limit benthic BOD.")
        elif do_mg_l < 4.5:
            # Marginal DO - 15% reduction
            net_multiplier *= 0.85
            adjustments["do_factor"] = 0.85
            warnings.append(f"Marginal DO ({do_mg_l:.2f} mg/L < 4.5 mg/L). Ration reduced by 15%.")
        else:
            adjustments["do_factor"] = 1.0
    else:
        warnings.append("Real-time DO telemetry not available. Environmental safety check bypassed.")
        adjustments["do_factor"] = 1.0

    # 2. Water Temperature adjustment
    if temp_c is not None:
        if temp_c < 24.0:
            net_multiplier *= 0.75
            adjustments["temp_factor"] = 0.75
            warnings.append(f"Low water temperature ({temp_c:.1f}°C < 24.0°C) slows shrimp digestion. 25% ration cut applied.")
        elif temp_c > 33.0:
            net_multiplier *= 0.80
            adjustments["temp_factor"] = 0.80
            warnings.append(f"High water temperature ({temp_c:.1f}°C > 33.0°C) increases biological stress. 20% ration cut applied.")
        else:
            adjustments["temp_factor"] = 1.0
    else:
        adjustments["temp_factor"] = 1.0

    # 3. Check Tray Observation adjustment
    if tray_observation:
        tray_lower = tray_observation.lower()
        if "leftover" in tray_lower or "> 20%" in tray_lower or ">25%" in tray_lower:
            net_multiplier *= 0.80
            adjustments["tray_factor"] = 0.80
            warnings.append("Unconsumed feed detected in check trays from previous cycle. 20% ration reduction applied.")
        elif "empty" in tray_lower or "100% consumed" in tray_lower:
            adjustments["tray_factor"] = 1.0
        else:
            adjustments["tray_factor"] = 1.0
    else:
        adjustments["tray_factor"] = 1.0

    final_daily_kg = round(max(0.0, base_ration_kg * net_multiplier), 2)
    sessions_count = max(1, custom_sessions_count)
    kg_per_session = round(final_daily_kg / sessions_count, 2) if final_daily_kg > 0 else 0.0

    default_times_by_sessions = {
        1: ["08:00"],
        2: ["07:00", "17:00"],
        3: ["06:30", "12:00", "17:30"],
        4: ["06:00", "11:00", "16:00", "21:00"],
        5: ["06:00", "10:00", "14:00", "18:00", "22:00"],
        6: ["06:00", "09:30", "13:00", "16:30", "20:00", "23:00"],
    }
    session_times = custom_session_times or default_times_by_sessions.get(
        sessions_count, ["06:00", "11:00", "16:00", "21:00"]
    )

    # Determine status & recommendation label
    if do_mg_l is not None and do_mg_l < 3.0:
        status = "HOLD_WATER_QUALITY"
        rec_basis = "HOLD_ANOXIA"
        action = "DO NOT FEED. Initiate emergency aeration and verify dissolved oxygen before resumption."
    elif net_multiplier < 0.95:
        status = "REDUCED_ADVISORY"
        rec_basis = "REDUCED_ENVIRONMENTAL"
        action = "Advisory ration adjusted downward due to ambient DO, temperature, or feeding tray residue."
    else:
        status = "RECOMMENDED"
        rec_basis = "ADVISORY"
        action = "Advisory baseline daily ration calculated from active biomass and standard feeding curves."

    # Determine confidence level (visibly distinguishing recent samples from provisional baselines)
    if is_sample_stale:
        confidence = "PROVISIONAL_STALE_SAMPLE"
    elif abw_source == "PHYSICAL_SAMPLING":
        confidence = "CALCULATED_RECENT_SAMPLE"
    else:
        confidence = "PROVISIONAL_BASELINE_ADVISORY"

    snapshot = RationInputSnapshot(
        farm_id=farm_id,
        pond_id=pond_id,
        batch_id=batch_id,
        batch_doc=batch_doc,
        stocking_count=stocking_count,
        estimated_survival_pct=clamped_survival,
        estimated_population=estimated_population,
        avg_body_weight_g=round(abw_g, 2),
        abw_sample_date=abw_sample_date.isoformat() if abw_sample_date else None,
        abw_source=abw_source,
        is_sample_stale=is_sample_stale,
        estimated_biomass_kg=estimated_biomass_kg,
        current_do_mg_l=round(do_mg_l, 2) if do_mg_l is not None else None,
        current_temp_c=round(temp_c, 2) if temp_c is not None else None,
        telemetry_timestamp=telemetry_time.isoformat() if telemetry_time else None,
        latest_tray_observation=tray_observation,
        base_feed_rate_pct=base_rate_pct,
    )

    return RationRecommendationResult(
        status=status,
        recommended_daily_kg=final_daily_kg,
        recommended_sessions_count=sessions_count,
        recommended_session_times=session_times,
        recommended_kg_per_session=kg_per_session,
        confidence_label=confidence,
        recommendation_basis=rec_basis,
        inputs_snapshot=snapshot.model_dump(),
        adjustment_factors=adjustments,
        warnings=warnings,
        action_guidance=action,
    )

