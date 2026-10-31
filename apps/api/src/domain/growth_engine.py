"""Shrimp Growth & Production Intelligence Engine.

Unit-safe domain calculations for:
- Dynamic DOC (Days of Culture)
- Estimated live shrimp population (with survival bounds validation)
- Estimated biomass in kg (explicitly labeled as estimate)
- Average Daily Growth (ADG in g/day)
- True Production Net-Gain FCR vs Apparent FCR (with input validation and warnings)
- Harvest planning projections (configurable target ABW, harvest date, projected revenue)
"""

from datetime import datetime, timezone
from enum import Enum
import math
from typing import Any, Dict, List, Optional, Tuple
from pydantic import BaseModel, Field


class BiomassCalculationResult(BaseModel):
    """Result of unit-safe shrimp biomass estimation."""
    estimated_population: int
    avg_body_weight_g: float
    estimated_biomass_kg: float
    is_estimate: bool = True
    estimation_basis: str
    warning: Optional[str] = None


class ADGCalculationResult(BaseModel):
    """Result of Average Daily Growth (ADG) calculation between sampling points."""
    previous_abw_g: float
    current_abw_g: float
    elapsed_days: int
    adg_g_per_day: Optional[float]
    is_valid: bool
    status_label: str  # e.g. "NORMAL_GROWTH", "NEGATIVE_GROWTH", "INVALID_INTERVAL"
    warning: Optional[str] = None


class FCRCalculationResult(BaseModel):
    """Result of Feed Conversion Ratio (FCR) calculation distinguishing true production from apparent."""
    is_calculable: bool
    production_fcr: Optional[float] = None
    apparent_fcr: Optional[float] = None
    cumulative_feed_kg: float
    initial_biomass_kg: float
    current_biomass_kg: float
    harvested_biomass_kg: float
    net_biomass_gain_kg: Optional[float] = None
    formula_used: str
    calculation_period_label: str
    warnings: list[str] = Field(default_factory=list)


class HarvestProjectionResult(BaseModel):
    """Harvest planning foundation with configurable targets and projected revenue."""
    target_abw_g: float
    current_abw_g: float
    current_doc: int
    adg_g_per_day: Optional[float]
    estimated_days_to_harvest: Optional[int]
    estimated_harvest_doc: Optional[int]
    estimated_harvest_date: Optional[str]
    estimated_harvest_biomass_kg: Optional[float]
    projected_sale_price_per_kg: float
    projected_gross_revenue: Optional[float]
    is_projection_reliable: bool
    projection_notice: str = "PROJECTION ONLY: Based on configurable target ABW and current ADG. Not guaranteed production."
    warnings: list[str] = Field(default_factory=list)


# ============================================================================
# Reusable Domain Calculation Functions
# ============================================================================

def calculate_dynamic_doc(stocking_date: datetime, as_of_date: Optional[datetime] = None) -> int:
    """Calculate Days of Culture (DOC) from stocking date.
    
    DOC is 1 on the day of stocking, increasing by 1 for each elapsed calendar day.
    """
    now = as_of_date or datetime.now(timezone.utc)
    if isinstance(stocking_date, str):
        stocking_date = datetime.fromisoformat(stocking_date.replace("Z", "+00:00"))
    if isinstance(now, str):
        now = datetime.fromisoformat(now.replace("Z", "+00:00"))
    if stocking_date.tzinfo is None:
        stocking_date = stocking_date.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    delta_seconds = (now - stocking_date).total_seconds()
    if delta_seconds < 0:
        return 0
    days = int(delta_seconds // 86400)
    return max(1, days + 1)


def calculate_estimated_population(
    initial_stocked_pl_count: int,
    estimated_survival_pct: float,
) -> Tuple[int, Optional[str]]:
    """Calculate estimated live shrimp population: initial PL * (survival_pct / 100)."""
    warning = None

    if initial_stocked_pl_count <= 0:
        return 0, "Initial stocked PL count must be greater than zero."

    if estimated_survival_pct < 0.0:
        return 0, "Survival percentage cannot be negative."

    if estimated_survival_pct > 100.0:
        warning = f"Survival percentage exceeds 100% ({estimated_survival_pct:.1f}%). Clamped to 100%."
        estimated_survival_pct = 100.0

    pop = int(round(initial_stocked_pl_count * (estimated_survival_pct / 100.0)))
    return pop, warning


def calculate_estimated_biomass(
    initial_stocked_pl_count: int,
    estimated_survival_pct: float,
    abw_g: float,
    is_measured_abw: bool = True,
) -> BiomassCalculationResult:
    """Calculate estimated biomass in kg: live population * ABW (g) / 1000.
    
    Explicitly flags the result as an estimate and identifies estimation basis.
    """
    warnings = []
    if abw_g <= 0:
        return BiomassCalculationResult(
            estimated_population=0,
            avg_body_weight_g=0.0,
            estimated_biomass_kg=0.0,
            is_estimate=True,
            estimation_basis="INVALID_INPUT",
            warning="Average body weight (ABW) must be strictly greater than zero grams.",
        )

    population, pop_warn = calculate_estimated_population(
        initial_stocked_pl_count, estimated_survival_pct
    )
    if pop_warn:
        warnings.append(pop_warn)

    biomass_kg = round((population * abw_g) / 1000.0, 2)
    basis = (
        "Derived from physical sampling ABW and estimated survival fraction"
        if is_measured_abw
        else "Derived from manual entry ABW and estimated survival fraction"
    )

    return BiomassCalculationResult(
        estimated_population=population,
        avg_body_weight_g=round(abw_g, 2),
        estimated_biomass_kg=biomass_kg,
        is_estimate=True,  # Always explicitly an estimate
        estimation_basis=basis,
        warning="; ".join(warnings) if warnings else None,
    )


def calculate_adg(
    current_abw_g: float,
    previous_abw_g: float,
    elapsed_days: int,
) -> ADGCalculationResult:
    """Calculate Average Daily Growth (ADG): (ABW2 - ABW1) / elapsed_days.
    
    Guards against zero elapsed days, negative intervals, and invalid weights.
    """
    if elapsed_days <= 0:
        return ADGCalculationResult(
            previous_abw_g=previous_abw_g,
            current_abw_g=current_abw_g,
            elapsed_days=elapsed_days,
            adg_g_per_day=None,
            is_valid=False,
            status_label="INVALID_INTERVAL",
            warning="Elapsed days between sampling points must be greater than zero.",
        )

    if previous_abw_g <= 0 or current_abw_g <= 0:
        return ADGCalculationResult(
            previous_abw_g=previous_abw_g,
            current_abw_g=current_abw_g,
            elapsed_days=elapsed_days,
            adg_g_per_day=None,
            is_valid=False,
            status_label="INVALID_WEIGHT",
            warning="Shrimp average body weight (ABW) must be positive non-zero values.",
        )

    weight_diff = current_abw_g - previous_abw_g
    adg = round(weight_diff / elapsed_days, 3)

    if weight_diff < 0:
        return ADGCalculationResult(
            previous_abw_g=previous_abw_g,
            current_abw_g=current_abw_g,
            elapsed_days=elapsed_days,
            adg_g_per_day=adg,
            is_valid=True,
            status_label="NEGATIVE_GROWTH",
            warning=(
                f"Negative growth observed ({adg:.3f} g/day). "
                "Possible causes: sampling error, net bias, feeding deficit, or population variance."
            ),
        )

    return ADGCalculationResult(
        previous_abw_g=previous_abw_g,
        current_abw_g=current_abw_g,
        elapsed_days=elapsed_days,
        adg_g_per_day=adg,
        is_valid=True,
        status_label="NORMAL_GROWTH",
        warning=None,
    )


def calculate_fcr(
    cumulative_feed_kg: float,
    current_biomass_kg: float,
    initial_biomass_kg: float,
    harvested_biomass_kg: float = 0.0,
    calculation_period_label: str = "Batch-to-Date",
) -> FCRCalculationResult:
    """Calculate True Production Net-Gain FCR and Apparent FCR.
    
    IMPORTANT:
    Production FCR is defined as:
        Cumulative Feed (kg) / Net Biomass Gain (kg)
    where Net Biomass Gain = Current Biomass - Initial Stocked Biomass + Harvested Biomass.

    Apparent FCR is:
        Cumulative Feed (kg) / Current Biomass (kg)
    (labeled as apparent ratio only, never as production FCR).

    Preconditions for Production FCR:
    1. Cumulative feed > 0
    2. Net Biomass Gain > 0 (strictly positive gain)
    3. Valid biomass figures
    """
    warnings = []
    formula_desc = (
        "Production FCR = Cumulative Feed (kg) / [Current Biomass (kg) - Initial Biomass (kg) + Harvested Biomass (kg)]"
    )

    # Calculate net gain
    net_gain = round((current_biomass_kg - initial_biomass_kg) + harvested_biomass_kg, 2)

    # Apparent FCR calculation (if current biomass > 0 and feed > 0)
    apparent_fcr = None
    if current_biomass_kg > 0 and cumulative_feed_kg > 0:
        apparent_fcr = round(cumulative_feed_kg / current_biomass_kg, 2)

    # Validation checks for Production FCR
    if cumulative_feed_kg <= 0:
        warnings.append("Cumulative feed is zero. Feed conversion ratio cannot be evaluated.")
        return FCRCalculationResult(
            is_calculable=False,
            production_fcr=None,
            apparent_fcr=apparent_fcr,
            cumulative_feed_kg=cumulative_feed_kg,
            initial_biomass_kg=initial_biomass_kg,
            current_biomass_kg=current_biomass_kg,
            harvested_biomass_kg=harvested_biomass_kg,
            net_biomass_gain_kg=net_gain,
            formula_used=formula_desc,
            calculation_period_label=calculation_period_label,
            warnings=warnings,
        )

    if net_gain <= 0:
        warnings.append(
            f"Net biomass gain ({net_gain:.2f} kg) is non-positive (Current: {current_biomass_kg}kg, Initial: {initial_biomass_kg}kg). "
            "Production FCR requires positive biomass gain."
        )
        return FCRCalculationResult(
            is_calculable=False,
            production_fcr=None,
            apparent_fcr=apparent_fcr,
            cumulative_feed_kg=cumulative_feed_kg,
            initial_biomass_kg=initial_biomass_kg,
            current_biomass_kg=current_biomass_kg,
            harvested_biomass_kg=harvested_biomass_kg,
            net_biomass_gain_kg=net_gain,
            formula_used=formula_desc,
            calculation_period_label=calculation_period_label,
            warnings=warnings,
        )

    prod_fcr = round(cumulative_feed_kg / net_gain, 2)

    if prod_fcr < 0.8:
        warnings.append(f"Production FCR ({prod_fcr:.2f}) is unusually low; verify feed logs or survival estimate.")
    elif prod_fcr > 2.5:
        warnings.append(f"Production FCR ({prod_fcr:.2f}) is elevated; check check-trays for feed wastage or mortality.")

    return FCRCalculationResult(
        is_calculable=True,
        production_fcr=prod_fcr,
        apparent_fcr=apparent_fcr,
        cumulative_feed_kg=cumulative_feed_kg,
        initial_biomass_kg=initial_biomass_kg,
        current_biomass_kg=current_biomass_kg,
        harvested_biomass_kg=harvested_biomass_kg,
        net_biomass_gain_kg=net_gain,
        formula_used=formula_desc,
        calculation_period_label=calculation_period_label,
        warnings=warnings,
    )


def calculate_harvest_projections(
    current_doc: int,
    current_abw_g: float,
    current_estimated_biomass_kg: float,
    current_estimated_population: int,
    target_abw_g: float = 25.0,
    adg_g_per_day: Optional[float] = None,
    projected_sale_price_per_kg: float = 5.50,
    as_of_date: Optional[datetime] = None,
) -> HarvestProjectionResult:
    """Evaluate harvest planning foundation: days to target ABW, estimated harvest date, and revenue.
    
    Clearly labels projected revenue and harvest timeline as projections, not guarantees.
    """
    now = as_of_date or datetime.now(timezone.utc)
    warnings = []
    days_to_harvest = None
    harvest_doc = None
    harvest_date_str = None
    expected_harvest_biomass = None
    projected_revenue = None
    reliable = False

    if target_abw_g <= current_abw_g:
        days_to_harvest = 0
        harvest_doc = current_doc
        harvest_date_str = now.strftime("%Y-%m-%d")
        expected_harvest_biomass = current_estimated_biomass_kg
        projected_revenue = round(expected_harvest_biomass * projected_sale_price_per_kg, 2)
        reliable = True
        warnings.append(f"Current ABW ({current_abw_g:.1f}g) has reached or exceeded target ({target_abw_g:.1f}g). Ready for harvest.")
    elif adg_g_per_day is None or adg_g_per_day <= 0:
        warnings.append("ADG is not positive or unavailable; cannot project linear days to harvest.")
    else:
        # Linear projection based on observed ADG
        remaining_growth_g = target_abw_g - current_abw_g
        days_to_harvest = int(math.ceil(remaining_growth_g / adg_g_per_day))
        harvest_doc = current_doc + days_to_harvest

        from datetime import timedelta
        proj_date = now + timedelta(days=days_to_harvest)
        harvest_date_str = proj_date.strftime("%Y-%m-%d")

        # Projected biomass at harvest: population * target_abw / 1000
        # Projected biomass at harvest: population * target_abw / 1000
        # (Assuming negligible mortality during remaining days or constant survival)
        expected_harvest_biomass = round((current_estimated_population * target_abw_g) / 1000.0, 2)
        projected_revenue = round(expected_harvest_biomass * projected_sale_price_per_kg, 2)
        reliable = True

    return HarvestProjectionResult(
        target_abw_g=target_abw_g,
        current_abw_g=current_abw_g,
        current_doc=current_doc,
        adg_g_per_day=adg_g_per_day,
        estimated_days_to_harvest=days_to_harvest,
        estimated_harvest_doc=harvest_doc,
        estimated_harvest_date=harvest_date_str,
        estimated_harvest_biomass_kg=expected_harvest_biomass,
        projected_sale_price_per_kg=projected_sale_price_per_kg,
        projected_gross_revenue=projected_revenue,
        is_projection_reliable=reliable,
        warnings=warnings,
    )


# ============================================================================
# Advanced Biomass, SGR, & Harvest Intelligence Additions
# ============================================================================

class SGRCalculationResult(BaseModel):
    """Result of Specific Growth Rate (SGR) calculation: [ln(W2) - ln(W1)] / delta_t * 100."""
    previous_abw_g: float
    current_abw_g: float
    elapsed_days: int
    sgr_pct_per_day: Optional[float]
    is_valid: bool
    status_label: str  # e.g. "NORMAL_SGR", "NEGATIVE_SGR", "INVALID_INTERVAL", "INVALID_WEIGHT"
    formula_used: str = "SGR = [(ln(W2) - ln(W1)) / delta_t] * 100"
    warning: Optional[str] = None


class SurvivingPopulationResult(BaseModel):
    """Surviving shrimp count calculation distinguishing measured mortality vs baseline assumption."""
    initial_count: int
    surviving_count: int
    survival_pct: float
    mortality_deducted: int
    estimation_method: str  # "RECORDED_MORTALITY_DEDUCTION" or "UNVALIDATED_SURVIVAL_ASSUMPTION"
    warning: Optional[str] = None


class DetailedBiomassResult(BaseModel):
    """Dedicated biomass calculation result with quality certification labels and partial harvest deductions."""
    batch_id: Optional[str] = None
    pond_id: str
    has_active_batch: bool
    status_quality: str  # CURRENT_VALIDATED, PROVISIONAL_STALE, UNVALIDATED_BASELINE, NEEDS_DATA
    initial_count: int
    surviving_count: int
    survival_pct: float
    avg_body_weight_g: float
    gross_biomass_kg: float
    cumulative_partial_harvest_kg: float = 0.0
    net_remaining_biomass_kg: float
    is_estimate: bool = True
    days_since_sampling: Optional[int] = None
    sampling_basis: str
    population_basis: str
    advisory_notice: str = "ESTIMATE ONLY: Derived from sample ABW and survival fraction. Never represents direct physical weigh-in."
    warnings: list[str] = Field(default_factory=list)


class HarvestForecastResult(BaseModel):
    """Advisory harvest forecasting using actual batch data, ADG, SGR, and uncertainty bounds."""
    batch_id: Optional[str] = None
    pond_id: str
    is_forecastable: bool
    status_label: str  # "ESTIMATE", "ADVISORY", "NEEDS_DATA"
    target_abw_g: Optional[float] = None
    current_abw_g: float
    current_doc: int
    adg_g_per_day: Optional[float] = None
    sgr_pct_per_day: Optional[float] = None
    estimated_days_to_harvest: Optional[int] = None
    estimated_harvest_doc: Optional[int] = None
    estimated_harvest_date: Optional[str] = None
    expected_harvest_biomass_kg: Optional[float] = None
    biomass_min_kg: Optional[float] = None  # Illustrative sensitivity lower bound (-8%)
    biomass_max_kg: Optional[float] = None  # Illustrative sensitivity upper bound (+8%)
    uncertainty_model: str = "ILLUSTRATIVE_SENSITIVITY_HEURISTIC_8PCT"
    cumulative_partial_harvest_kg: float = 0.0
    net_remaining_forecast_biomass_kg: Optional[float] = None
    projected_sale_price_per_kg: Optional[float] = None
    projected_gross_revenue: Optional[float] = None
    advisory_notes: list[str] = Field(default_factory=list)
    confidence_level: str = "UNAVAILABLE"  # "ADVISORY_RECENT_SAMPLE", "ADVISORY_STALE_SAMPLE", "ADVISORY_BASELINE", "UNAVAILABLE"


def calculate_sgr(
    current_abw_g: float,
    previous_abw_g: float,
    elapsed_days: int,
) -> SGRCalculationResult:
    """Calculate Specific Growth Rate (SGR) in % body weight per day.
    
    Formula:
        SGR = [(ln(W2) - ln(W1)) / elapsed_days] * 100
    Preconditions:
        current_abw_g > 0, previous_abw_g > 0, elapsed_days > 0.
    """
    if elapsed_days <= 0:
        return SGRCalculationResult(
            previous_abw_g=previous_abw_g,
            current_abw_g=current_abw_g,
            elapsed_days=elapsed_days,
            sgr_pct_per_day=None,
            is_valid=False,
            status_label="INVALID_INTERVAL",
            warning="Elapsed days between sampling points must be strictly greater than zero.",
        )

    if previous_abw_g <= 0 or current_abw_g <= 0:
        return SGRCalculationResult(
            previous_abw_g=previous_abw_g,
            current_abw_g=current_abw_g,
            elapsed_days=elapsed_days,
            sgr_pct_per_day=None,
            is_valid=False,
            status_label="INVALID_WEIGHT",
            warning="Shrimp average body weight (ABW) must be strictly positive non-zero values for SGR calculation.",
        )

    sgr = round(((math.log(current_abw_g) - math.log(previous_abw_g)) / elapsed_days) * 100.0, 2)

    if sgr < 0:
        return SGRCalculationResult(
            previous_abw_g=previous_abw_g,
            current_abw_g=current_abw_g,
            elapsed_days=elapsed_days,
            sgr_pct_per_day=sgr,
            is_valid=True,
            status_label="NEGATIVE_SGR",
            warning=f"Negative Specific Growth Rate ({sgr:.2f}%/day) indicates apparent weight drop or sampling variance.",
        )

    return SGRCalculationResult(
        previous_abw_g=previous_abw_g,
        current_abw_g=current_abw_g,
        elapsed_days=elapsed_days,
        sgr_pct_per_day=sgr,
        is_valid=True,
        status_label="NORMAL_SGR",
        warning=None,
    )


def calculate_surviving_population_detail(
    initial_count: int,
    cumulative_recorded_mortality: int = 0,
    cumulative_harvested_count: int = 0,
    estimated_survival_pct: Optional[float] = None,
) -> SurvivingPopulationResult:
    """Calculate surviving shrimp count ensuring mortality and harvest counts are strictly validated.
    
    Prevents negative counts and guarantees no double deductions:
    - If physical mortality records exist, deduct recorded mortalities and harvested pieces.
    - If no mortality records exist, use configured survival percentage or flag as unmeasured.
    """
    if initial_count <= 0:
        return SurvivingPopulationResult(
            initial_count=0,
            surviving_count=0,
            survival_pct=0.0,
            mortality_deducted=0,
            estimation_method="INVALID_STOCKING",
            warning="Initial stocked population must be greater than zero.",
        )

    cum_mort = max(0, cumulative_recorded_mortality)
    cum_hrv = max(0, cumulative_harvested_count)

    if cum_mort > 0:
        surviving = max(0, initial_count - cum_mort - cum_hrv)
        pct = round((surviving / initial_count) * 100.0, 2)
        warn = None
        if surviving == 0:
            warn = "Cumulative recorded mortality plus harvest equals or exceeds initial stocked population."
        return SurvivingPopulationResult(
            initial_count=initial_count,
            surviving_count=surviving,
            survival_pct=pct,
            mortality_deducted=cum_mort,
            estimation_method="RECORDED_MORTALITY_DEDUCTION",
            warning=warn,
        )

    if estimated_survival_pct is not None:
        clamped_pct = max(0.0, min(100.0, estimated_survival_pct))
        base_surviving = int(round(initial_count * (clamped_pct / 100.0)))
        surviving = max(0, base_surviving - cum_hrv)
        pct = round((surviving / initial_count) * 100.0, 2)
        return SurvivingPopulationResult(
            initial_count=initial_count,
            surviving_count=surviving,
            survival_pct=pct,
            mortality_deducted=0,
            estimation_method="UNVALIDATED_SURVIVAL_ASSUMPTION",
            warning="No mortality records logged; population derived from configured survival percentage assumption.",
        )

    # Missing both mortality and configured survival
    surviving = max(0, initial_count - cum_hrv)
    pct = round((surviving / initial_count) * 100.0, 2)
    return SurvivingPopulationResult(
        initial_count=initial_count,
        surviving_count=surviving,
        survival_pct=pct,
        mortality_deducted=0,
        estimation_method="NEEDS_DATA",
        warning="Mortality unrecorded and baseline survival unconfigured; population calculation requires field data.",
    )


def calculate_detailed_biomass(
    pond_id: str,
    batch_id: Optional[str],
    has_active_batch: bool,
    initial_count: int,
    avg_body_weight_g: float,
    cumulative_recorded_mortality: int = 0,
    cumulative_harvested_count: int = 0,
    estimated_survival_pct: Optional[float] = None,
    days_since_sampling: Optional[int] = None,
    is_measured_abw: bool = True,
    cumulative_partial_harvest_kg: float = 0.0,
    documented_losses_kg: float = 0.0,
) -> DetailedBiomassResult:
    """Calculate dedicated biomass with certified labels, mortality bounds, and partial harvest accounting.
    
    Prevents negative remaining biomass and double-counting:
    - Live remaining biomass in pond = Live surviving count * current ABW / 1000
    - Quality labels:
      * NEEDS_DATA: Missing batch, non-positive ABW, or missing inputs
      * MEASURED: Directly observed physical total (e.g. at drain/scale)
      * CALCULATED_ESTIMATE: Sampling within <= 10 days
      * STALE: Sampling older than 10 days
      * BASELINE_ESTIMATE: Initial stocking baseline only
    """
    warnings: list[str] = []

    if not has_active_batch:
        return DetailedBiomassResult(
            batch_id=batch_id,
            pond_id=pond_id,
            has_active_batch=False,
            status_quality="NEEDS_DATA",
            initial_count=0,
            surviving_count=0,
            survival_pct=0.0,
            avg_body_weight_g=0.0,
            gross_biomass_kg=0.0,
            cumulative_partial_harvest_kg=0.0,
            net_remaining_biomass_kg=0.0,
            sampling_basis="NO_ACTIVE_BATCH",
            population_basis="NO_ACTIVE_BATCH",
            warnings=["Pond has no active stocking batch."],
        )

    if avg_body_weight_g <= 0:
        return DetailedBiomassResult(
            batch_id=batch_id,
            pond_id=pond_id,
            has_active_batch=True,
            status_quality="NEEDS_DATA",
            initial_count=initial_count,
            surviving_count=0,
            survival_pct=0.0,
            avg_body_weight_g=0.0,
            gross_biomass_kg=0.0,
            cumulative_partial_harvest_kg=0.0,
            net_remaining_biomass_kg=0.0,
            sampling_basis="MISSING_ABW",
            population_basis="CANNOT_CALCULATE",
            warnings=["Average body weight (ABW) is missing or non-positive."],
        )

    # If harvested count was not logged but harvested kg was, derive pieces without double-counting
    effective_harvested_pieces = max(0, cumulative_harvested_count)
    if effective_harvested_pieces == 0 and cumulative_partial_harvest_kg > 0 and avg_body_weight_g > 0:
        effective_harvested_pieces = int(round((cumulative_partial_harvest_kg * 1000.0) / avg_body_weight_g))

    pop_res = calculate_surviving_population_detail(
        initial_count=initial_count,
        cumulative_recorded_mortality=cumulative_recorded_mortality,
        cumulative_harvested_count=effective_harvested_pieces,
        estimated_survival_pct=estimated_survival_pct,
    )
    if pop_res.warning:
        warnings.append(pop_res.warning)

    # Net remaining live biomass in pond = surviving shrimp currently in pond * current ABW / 1000
    net_remaining_kg = round(max(0.0, (pop_res.surviving_count * avg_body_weight_g) / 1000.0), 2)
    
    # Gross cumulative biomass produced = net remaining live biomass + cumulative partial harvests + documented losses
    gross_produced_kg = round(net_remaining_kg + max(0.0, cumulative_partial_harvest_kg) + max(0.0, documented_losses_kg), 2)

    if cumulative_partial_harvest_kg > 0:
        warnings.append(f"Reflects {cumulative_partial_harvest_kg:.1f} kg harvested ({effective_harvested_pieces:,} pieces removed).")

    # Determine Quality Label
    if days_since_sampling is None:
        quality_status = "BASELINE_ESTIMATE"
        sampling_basis = "Initial stocking baseline (no physical sampling recorded)"
        warnings.append("No sampling recorded; metrics rely on initial stocking parameters.")
    elif days_since_sampling > 10:
        quality_status = "STALE"
        sampling_basis = f"Historical sample ({days_since_sampling} days old, exceeds 10-day freshness window)"
        warnings.append(f"Sampling data is {days_since_sampling} days old. Fresh sampling recommended.")
    else:
        quality_status = "CALCULATED_ESTIMATE"
        sampling_basis = f"Recent physical sample ({days_since_sampling} days ago)" if is_measured_abw else f"Recent manual entry ({days_since_sampling} days ago)"

    return DetailedBiomassResult(
        batch_id=batch_id,
        pond_id=pond_id,
        has_active_batch=True,
        status_quality=quality_status,
        initial_count=initial_count,
        surviving_count=pop_res.surviving_count,
        survival_pct=pop_res.survival_pct,
        avg_body_weight_g=round(avg_body_weight_g, 2),
        gross_biomass_kg=gross_produced_kg,
        cumulative_partial_harvest_kg=round(cumulative_partial_harvest_kg, 2),
        net_remaining_biomass_kg=net_remaining_kg,
        days_since_sampling=days_since_sampling,
        sampling_basis=sampling_basis,
        population_basis=pop_res.estimation_method,
        warnings=warnings,
    )


def calculate_advanced_harvest_forecast(
    pond_id: str,
    batch_id: Optional[str],
    has_active_batch: bool,
    current_doc: int,
    current_abw_g: float,
    surviving_count: int,
    target_abw_g: Optional[float] = None,
    adg_g_per_day: Optional[float] = None,
    sgr_pct_per_day: Optional[float] = None,
    cumulative_partial_harvest_kg: float = 0.0,
    projected_sale_price_per_kg: Optional[float] = None,
    days_since_sampling: Optional[int] = None,
    as_of_date: Optional[datetime] = None,
) -> HarvestForecastResult:
    """Generate advisory harvest forecast with illustrative sensitivity bounds and quality checks.
    
    Guards against inventing target harvest weights, growth rates, or assumptions when inputs are missing.
    Biomass bounds are explicitly flagged as an illustrative sensitivity range (+/-8%), NOT a statistical confidence interval.
    """
    now = as_of_date or datetime.now(timezone.utc)
    notes: list[str] = []

    if not has_active_batch or current_abw_g <= 0:
        return HarvestForecastResult(
            batch_id=batch_id,
            pond_id=pond_id,
            is_forecastable=False,
            status_label="NEEDS_DATA",
            target_abw_g=target_abw_g,
            current_abw_g=current_abw_g,
            current_doc=current_doc,
            advisory_notes=["Cannot generate forecast: Pond has no active batch or valid ABW data."],
            confidence_level="UNAVAILABLE",
        )

    if target_abw_g is None or target_abw_g <= 0:
        return HarvestForecastResult(
            batch_id=batch_id,
            pond_id=pond_id,
            is_forecastable=False,
            status_label="NEEDS_DATA",
            target_abw_g=None,
            current_abw_g=current_abw_g,
            current_doc=current_doc,
            advisory_notes=["Target harvest ABW is not configured. Harvest forecast requires an explicit target weight."],
            confidence_level="UNAVAILABLE",
        )

    # Check if target already reached
    if target_abw_g <= current_abw_g:
        live_kg = round(max(0.0, (surviving_count * current_abw_g) / 1000.0), 2)
        min_kg = round(live_kg * 0.92, 2)
        max_kg = round(live_kg * 1.08, 2)
        rev = round(live_kg * projected_sale_price_per_kg, 2) if projected_sale_price_per_kg and projected_sale_price_per_kg > 0 else None
        basis = "ADVISORY_RECENT_SAMPLE" if days_since_sampling is not None and days_since_sampling <= 10 else "ADVISORY_STALE_SAMPLE"
        return HarvestForecastResult(
            batch_id=batch_id,
            pond_id=pond_id,
            is_forecastable=True,
            status_label="ADVISORY",
            target_abw_g=target_abw_g,
            current_abw_g=current_abw_g,
            current_doc=current_doc,
            adg_g_per_day=adg_g_per_day,
            sgr_pct_per_day=sgr_pct_per_day,
            estimated_days_to_harvest=0,
            estimated_harvest_doc=current_doc,
            estimated_harvest_date=now.strftime("%Y-%m-%d"),
            expected_harvest_biomass_kg=live_kg,
            biomass_min_kg=min_kg,
            biomass_max_kg=max_kg,
            uncertainty_model="ILLUSTRATIVE_SENSITIVITY_HEURISTIC_8PCT",
            cumulative_partial_harvest_kg=cumulative_partial_harvest_kg,
            net_remaining_forecast_biomass_kg=live_kg,
            projected_sale_price_per_kg=projected_sale_price_per_kg,
            projected_gross_revenue=rev,
            advisory_notes=[
                f"Current ABW ({current_abw_g:.1f}g) has reached or exceeded harvest target ({target_abw_g:.1f}g).",
                "Biomass bounds (±8%) are illustrative sensitivity estimates based on assumed sampling variance, NOT a verified statistical confidence interval.",
            ],
            confidence_level=basis,
        )

    if adg_g_per_day is None or adg_g_per_day <= 0:
        return HarvestForecastResult(
            batch_id=batch_id,
            pond_id=pond_id,
            is_forecastable=False,
            status_label="NEEDS_DATA",
            target_abw_g=target_abw_g,
            current_abw_g=current_abw_g,
            current_doc=current_doc,
            adg_g_per_day=adg_g_per_day,
            sgr_pct_per_day=sgr_pct_per_day,
            advisory_notes=["ADG is zero, negative, or unmeasured. Growth trajectory cannot be projected without measured positive growth."],
            confidence_level="UNAVAILABLE",
        )

    # Linear trajectory to target ABW based on actual measured ADG
    remaining_gain_g = target_abw_g - current_abw_g
    days_to_harvest = int(math.ceil(remaining_gain_g / adg_g_per_day))
    harvest_doc = current_doc + days_to_harvest

    from datetime import timedelta
    proj_date = now + timedelta(days=days_to_harvest)
    harvest_date_str = proj_date.strftime("%Y-%m-%d")

    # Projected remaining live biomass at harvest target weight
    live_proj_kg = round(max(0.0, (surviving_count * target_abw_g) / 1000.0), 2)
    min_kg = round(live_proj_kg * 0.92, 2)
    max_kg = round(live_proj_kg * 1.08, 2)

    rev = round(live_proj_kg * projected_sale_price_per_kg, 2) if projected_sale_price_per_kg and projected_sale_price_per_kg > 0 else None

    # Advisory basis categorization
    if days_since_sampling is not None and days_since_sampling > 10:
        basis = "ADVISORY_STALE_SAMPLE"
        notes.append(f"Sampling is {days_since_sampling} days old. Advisory reliability reduced.")
    elif days_since_sampling is None:
        basis = "ADVISORY_BASELINE"
        notes.append("No physical sampling on record; forecast based on stocking baseline.")
    else:
        basis = "ADVISORY_RECENT_SAMPLE"

    notes.append(
        f"Advisory forecast assumes constant ADG of {adg_g_per_day:.3f} g/day to target {target_abw_g:.1f}g. "
        "Biomass bounds (±8%) represent an illustrative sensitivity range, NOT a statistically validated confidence interval."
    )

    return HarvestForecastResult(
        batch_id=batch_id,
        pond_id=pond_id,
        is_forecastable=True,
        status_label="CALCULATED_ESTIMATE",
        target_abw_g=target_abw_g,
        current_abw_g=current_abw_g,
        current_doc=current_doc,
        adg_g_per_day=adg_g_per_day,
        sgr_pct_per_day=sgr_pct_per_day,
        estimated_days_to_harvest=days_to_harvest,
        estimated_harvest_doc=harvest_doc,
        estimated_harvest_date=harvest_date_str,
        expected_harvest_biomass_kg=live_proj_kg,
        biomass_min_kg=min_kg,
        biomass_max_kg=max_kg,
        uncertainty_model="ILLUSTRATIVE_SENSITIVITY_HEURISTIC_8PCT",
        cumulative_partial_harvest_kg=cumulative_partial_harvest_kg,
        net_remaining_forecast_biomass_kg=live_proj_kg,
        projected_sale_price_per_kg=projected_sale_price_per_kg,
        projected_gross_revenue=rev,
        advisory_notes=notes,
        confidence_level=basis,
    )


# ============================================================================
# Harvest Readiness & Financial Actuals Models and Functions
# ============================================================================

class HarvestReadinessResult(BaseModel):
    """Evaluation of shrimp harvest readiness based strictly on recorded samples and user targets."""
    batch_id: str
    pond_id: str
    readiness_status: str  # READY, APPROACHING, GROWING, WITHDRAWAL_RESTRICTED, NEEDS_DATA, HARVESTED, CLOSED
    target_abw_g: float
    current_abw_g: Optional[float] = None
    abw_achieved_pct: Optional[float] = None
    latest_sample_date: Optional[str] = None
    days_since_sampling: Optional[int] = None
    sample_freshness_label: str  # MEASURED, STALE, NEEDS_DATA
    adg_g_per_day: Optional[float] = None
    estimated_days_to_target: Optional[int] = None
    target_harvest_date: Optional[str] = None
    is_withdrawal_held: bool = False
    withdrawal_hold_count: int = 0
    readiness_reason: str
    confidence_label: str  # MEASURED, STALE, NEEDS_DATA, RECORDED
    advisory_notes: list[str] = Field(default_factory=list)


def evaluate_harvest_readiness(
    batch_id: str,
    pond_id: str,
    status: str,
    target_abw_g: Optional[float],
    current_abw_g: Optional[float],
    latest_sample_date: Optional[str] = None,
    days_since_sampling: Optional[int] = None,
    adg_g_per_day: Optional[float] = None,
    target_harvest_date: Optional[str] = None,
    is_withdrawal_held: bool = False,
    withdrawal_hold_count: int = 0,
) -> HarvestReadinessResult:
    """Evaluate batch harvest readiness without fabricating weights or growth rates."""
    target_abw = target_abw_g if target_abw_g and target_abw_g > 0 else 25.0
    notes: list[str] = []

    # Batch already harvested or closed
    if status in ("HARVESTED", "CLOSED"):
        return HarvestReadinessResult(
            batch_id=batch_id,
            pond_id=pond_id,
            readiness_status=status,
            target_abw_g=target_abw,
            current_abw_g=current_abw_g,
            abw_achieved_pct=round((current_abw_g / target_abw) * 100.0, 1) if current_abw_g else None,
            latest_sample_date=latest_sample_date,
            days_since_sampling=days_since_sampling,
            sample_freshness_label="RECORDED" if current_abw_g else "NEEDS_DATA",
            adg_g_per_day=adg_g_per_day,
            estimated_days_to_target=0,
            target_harvest_date=target_harvest_date,
            is_withdrawal_held=False,
            withdrawal_hold_count=0,
            readiness_reason=f"Batch has completed production cycle (Status: {status}).",
            confidence_label="RECORDED",
            advisory_notes=["Batch lifecycle concluded."],
        )

    # Biosecurity check: active withdrawal hold takes highest priority
    if is_withdrawal_held:
        achieved = round((current_abw_g / target_abw) * 100.0, 1) if current_abw_g else None
        notes.append("Harvest is blocked by active chemical or antibiotic withdrawal hold.")
        return HarvestReadinessResult(
            batch_id=batch_id,
            pond_id=pond_id,
            readiness_status="WITHDRAWAL_RESTRICTED",
            target_abw_g=target_abw,
            current_abw_g=current_abw_g,
            abw_achieved_pct=achieved,
            latest_sample_date=latest_sample_date,
            days_since_sampling=days_since_sampling,
            sample_freshness_label="MEASURED" if days_since_sampling is not None and days_since_sampling <= 10 else ("STALE" if days_since_sampling is not None else "NEEDS_DATA"),
            adg_g_per_day=adg_g_per_day,
            estimated_days_to_target=None,
            target_harvest_date=target_harvest_date,
            is_withdrawal_held=True,
            withdrawal_hold_count=withdrawal_hold_count,
            readiness_reason=f"Pond is under {withdrawal_hold_count} active chemical withdrawal hold(s). Commercial harvest prohibited until clearance.",
            confidence_label="MEASURED",
            advisory_notes=notes,
        )

    # Missing recorded sample
    if current_abw_g is None or current_abw_g <= 0:
        notes.append("Zero cast-net samples recorded. Biomass relies on stocking baseline model.")
        return HarvestReadinessResult(
            batch_id=batch_id,
            pond_id=pond_id,
            readiness_status="NEEDS_DATA",
            target_abw_g=target_abw,
            current_abw_g=None,
            abw_achieved_pct=None,
            latest_sample_date=None,
            days_since_sampling=None,
            sample_freshness_label="NEEDS_DATA",
            adg_g_per_day=None,
            estimated_days_to_target=None,
            target_harvest_date=target_harvest_date,
            is_withdrawal_held=False,
            withdrawal_hold_count=0,
            readiness_reason="No physical cast-net samples recorded. Physical sampling required to verify ABW and harvest readiness.",
            confidence_label="NEEDS_DATA",
            advisory_notes=notes,
        )

    # Freshness label
    if days_since_sampling is not None and days_since_sampling > 10:
        freshness = "STALE"
        confidence = "STALE"
        notes.append(f"Last sampling was {days_since_sampling} days ago (> 10d). Conduct fresh sampling before harvest.")
    else:
        freshness = "MEASURED"
        confidence = "MEASURED"

    achieved_pct = round((current_abw_g / target_abw) * 100.0, 1)

    # Days to target if ADG available
    days_to_target = None
    if current_abw_g >= target_abw:
        days_to_target = 0
        readiness_status = "READY"
        reason = f"Target ABW reached: current {current_abw_g:.2f}g >= target {target_abw:.2f}g ({achieved_pct}% achieved)."
    elif achieved_pct >= 85.0:
        readiness_status = "APPROACHING"
        if adg_g_per_day and adg_g_per_day > 0:
            days_to_target = max(1, int(round((target_abw - current_abw_g) / adg_g_per_day)))
            reason = f"Approaching target ABW ({current_abw_g:.2f}g / {target_abw:.2f}g, {achieved_pct}%). Est. {days_to_target} days at current ADG ({adg_g_per_day:.3f} g/d)."
        else:
            reason = f"Approaching target ABW ({current_abw_g:.2f}g / {target_abw:.2f}g, {achieved_pct}%). Consecutive samples needed to estimate days."
    else:
        readiness_status = "GROWING"
        if adg_g_per_day and adg_g_per_day > 0:
            days_to_target = max(1, int(round((target_abw - current_abw_g) / adg_g_per_day)))
            reason = f"Active grow-out ({current_abw_g:.2f}g / {target_abw:.2f}g, {achieved_pct}%). Est. {days_to_target} days to target."
        else:
            reason = f"Active grow-out ({current_abw_g:.2f}g / {target_abw:.2f}g, {achieved_pct}%)."

    return HarvestReadinessResult(
        batch_id=batch_id,
        pond_id=pond_id,
        readiness_status=readiness_status,
        target_abw_g=target_abw,
        current_abw_g=current_abw_g,
        abw_achieved_pct=achieved_pct,
        latest_sample_date=latest_sample_date,
        days_since_sampling=days_since_sampling,
        sample_freshness_label=freshness,
        adg_g_per_day=adg_g_per_day,
        estimated_days_to_target=days_to_target,
        target_harvest_date=target_harvest_date,
        is_withdrawal_held=False,
        withdrawal_hold_count=0,
        readiness_reason=reason,
        confidence_label=confidence,
        advisory_notes=notes,
    )


class FinancialCompletenessStatus(str, Enum):
    """Explicit financial data completeness statuses reflecting verified ledger records."""
    COMPLETE_FROM_RECORDED_ACTUALS = "COMPLETE_FROM_RECORDED_ACTUALS"
    INCOMPLETE_COST_DATA = "INCOMPLETE_COST_DATA"
    INCOMPLETE_REVENUE_DATA = "INCOMPLETE_REVENUE_DATA"
    UNATTRIBUTABLE_COSTS = "UNATTRIBUTABLE_COSTS"
    NO_RECORDS = "NO_RECORDS"


class BatchFinancialSummary(BaseModel):
    """Actual realized harvest revenues and recorded ledger costs without synthetic assumptions."""
    batch_id: str
    total_harvested_kg: float
    partial_harvest_kg: float = 0.0
    final_harvest_kg: float = 0.0
    harvest_events_count: int = 0
    total_revenue: Optional[float] = None
    # UI and backward compatibility aliases
    total_revenue_realized: Optional[float] = None
    weighted_avg_sale_price_per_kg: Optional[float] = None
    average_sale_price_per_kg: Optional[float] = None
    total_documented_losses_kg: float = 0.0

    # Feeding and feed cost attribution
    cumulative_feed_kg: float = 0.0
    costed_feed_kg: float = 0.0
    uncosted_feed_kg: float = 0.0
    recorded_feed_cost: Optional[float] = None
    total_feed_cost_recorded: Optional[float] = None
    has_recorded_feed_cost: bool = False
    feed_cost_completeness: str = "UNRECORDED"  # COMPLETE, PARTIAL, UNRECORDED

    # Other production cost categories
    recorded_seed_cost: Optional[float] = None
    recorded_treatment_cost: Optional[float] = None
    recorded_energy_cost: Optional[float] = None
    other_recorded_costs: Optional[float] = None

    # Attributable totals and margins
    total_recorded_costs: Optional[float] = None
    total_attributable_recorded_costs: Optional[float] = None
    net_realized_margin: Optional[float] = None
    realized_margin_per_kg: Optional[float] = None

    # Categorized cost breakdown
    cost_breakdown: Dict[str, Any] = Field(default_factory=dict)

    # Completeness and data integrity indicators
    financial_status: str  # RECORDED_ACTUALS, REVENUE_ONLY, COSTS_UNRECORDED, NEEDS_DATA, INCOMPLETE_COST_DATA, INCOMPLETE_REVENUE_DATA
    completeness_status: str  # Matches FinancialCompletenessStatus
    is_profitability_complete: bool = False
    missing_cost_categories: List[str] = Field(default_factory=list)
    confidence_label: str  # RECORDED, NEEDS_DATA, MEASURED, CALCULATED_ESTIMATE
    advisory_notice: str
    data_integrity_notes: List[str] = Field(default_factory=list)


def calculate_batch_financial_summary(
    batch_id: str,
    total_harvested_kg: float,
    partial_harvest_kg: float,
    final_harvest_kg: float,
    harvest_events_count: int,
    total_revenue: Optional[float],
    total_documented_losses_kg: float,
    cumulative_feed_kg: float,
    costed_feed_kg: float = 0.0,
    recorded_feed_cost: Optional[float] = None,
    recorded_seed_cost: Optional[float] = None,
    recorded_treatment_cost: Optional[float] = None,
    recorded_energy_cost: Optional[float] = None,
    other_recorded_costs: Optional[float] = None,
    is_active_crop: bool = True,
    has_unattributable_costs: bool = False,
) -> BatchFinancialSummary:
    """Calculate actual commercial revenue and recorded ledger costs without fabricating unrecorded prices.
    
    Strict rules:
    - Never treat missing costs as zero when asserting profitability.
    - Missing seed, treatment, or power costs result in INCOMPLETE_COST_DATA.
    - Ongoing batches with no harvest sales result in INCOMPLETE_REVENUE_DATA.
    - Operating margin reflects only recorded attributable costs and is explicitly flagged as incomplete if cost categories are missing.
    """
    total_harvested_kg = round(max(0.0, total_harvested_kg), 2)
    partial_harvest_kg = round(max(0.0, partial_harvest_kg), 2)
    final_harvest_kg = round(max(0.0, final_harvest_kg), 2)
    cumulative_feed_kg = round(max(0.0, cumulative_feed_kg), 2)
    costed_feed_kg = round(max(0.0, min(cumulative_feed_kg, costed_feed_kg)), 2)
    uncosted_feed_kg = round(max(0.0, cumulative_feed_kg - costed_feed_kg), 2)

    avg_price = None
    if total_revenue is not None and total_harvested_kg > 0:
        avg_price = round(total_revenue / total_harvested_kg, 2)

    # Feed cost analysis
    has_feed_cost = recorded_feed_cost is not None and recorded_feed_cost > 0
    if cumulative_feed_kg == 0:
        feed_completeness = "UNRECORDED"
    elif has_feed_cost and uncosted_feed_kg <= 0.01:
        feed_completeness = "COMPLETE"
    elif has_feed_cost and costed_feed_kg > 0:
        feed_completeness = "PARTIAL"
    else:
        feed_completeness = "UNRECORDED"

    # Attributable costs compilation
    cost_breakdown: Dict[str, Any] = {
        "feed": {
            "recorded_cost": round(recorded_feed_cost, 2) if recorded_feed_cost is not None else None,
            "cumulative_kg": cumulative_feed_kg,
            "costed_kg": costed_feed_kg,
            "uncosted_kg": uncosted_feed_kg,
            "completeness": feed_completeness,
            "status": "RECORDED" if feed_completeness == "COMPLETE" else ("PARTIAL" if feed_completeness == "PARTIAL" else "UNRECORDED"),
        },
        "seed_pl": {
            "recorded_cost": round(recorded_seed_cost, 2) if recorded_seed_cost is not None else None,
            "status": "RECORDED" if recorded_seed_cost is not None else "UNRECORDED",
            "notes": "Post-larvae purchase invoices are not captured in the stocking ledger.",
        },
        "treatment_and_probiotics": {
            "recorded_cost": round(recorded_treatment_cost, 2) if recorded_treatment_cost is not None else None,
            "status": "RECORDED" if recorded_treatment_cost is not None else "UNRECORDED",
            "notes": "Dosages are tracked; purchase unit prices are not captured.",
        },
        "energy_and_aeration": {
            "recorded_cost": round(recorded_energy_cost, 2) if recorded_energy_cost is not None else None,
            "status": "RECORDED" if recorded_energy_cost is not None else "UNRECORDED",
            "notes": "KWh consumption logged; farm utility tariff per batch not recorded.",
        },
    }

    if other_recorded_costs is not None:
        cost_breakdown["other_expenses"] = {
            "recorded_cost": round(other_recorded_costs, 2),
            "status": "RECORDED",
        }

    # Sum only genuinely recorded attributable costs
    recorded_cost_items = [
        val for val in [
            recorded_feed_cost,
            recorded_seed_cost,
            recorded_treatment_cost,
            recorded_energy_cost,
            other_recorded_costs,
        ]
        if val is not None
    ]
    total_attributable_costs = round(sum(recorded_cost_items), 2) if recorded_cost_items else None

    # Track missing cost categories (Never assume zero!)
    missing_categories: List[str] = []
    if recorded_seed_cost is None:
        missing_categories.append("SEED_PL_PURCHASE")
    if feed_completeness != "COMPLETE":
        if feed_completeness == "PARTIAL":
            missing_categories.append("UNCOSTED_FEED_INVOICES")
        elif cumulative_feed_kg > 0:
            missing_categories.append("FEED_PURCHASE_COSTS")
    if recorded_treatment_cost is None:
        missing_categories.append("CHEMICAL_AND_TREATMENTS")
    if recorded_energy_cost is None:
        missing_categories.append("POWER_AND_AERATION")
    if other_recorded_costs is None:
        missing_categories.append("LABOR_AND_OVERHEAD")

    # Net Realized Result
    net_margin = None
    margin_per_kg = None
    if total_revenue is not None and total_attributable_costs is not None:
        net_margin = round(total_revenue - total_attributable_costs, 2)
        if total_harvested_kg > 0:
            margin_per_kg = round(net_margin / total_harvested_kg, 2)

    # Determine explicit Completeness Status
    integrity_notes: List[str] = []
    if has_unattributable_costs:
        comp_status = FinancialCompletenessStatus.UNATTRIBUTABLE_COSTS.value
        fin_status = "UNATTRIBUTABLE_COSTS"
        is_complete = False
        conf = "NEEDS_DATA"
        integrity_notes.append("Farm ledger contains unassigned expenses that cannot be attributed without arbitrary allocation.")
    elif harvest_events_count == 0 and cumulative_feed_kg == 0 and not recorded_cost_items:
        comp_status = FinancialCompletenessStatus.NO_RECORDS.value
        fin_status = "NO_RECORDS"
        is_complete = False
        conf = "NEEDS_DATA"
        integrity_notes.append("No commercial harvest sales or feed transactions recorded for this batch.")
    elif len(missing_categories) > 0:
        is_complete = False
        if total_revenue is None and (is_active_crop or harvest_events_count == 0):
            comp_status = FinancialCompletenessStatus.INCOMPLETE_REVENUE_DATA.value
            fin_status = "INCOMPLETE_REVENUE_DATA"
            conf = "RECORDED" if total_attributable_costs is not None else "NEEDS_DATA"
            integrity_notes.append("Crop is currently in growout or has unrecorded harvest revenue.")
        else:
            comp_status = FinancialCompletenessStatus.INCOMPLETE_COST_DATA.value
            fin_status = "INCOMPLETE_COST_DATA"
            conf = "RECORDED"
            integrity_notes.append(
                f"Operating margin reflects recorded costs only. Unrecorded categories ({', '.join(missing_categories)}) are NOT zero."
            )
    elif total_revenue is None:
        comp_status = FinancialCompletenessStatus.INCOMPLETE_REVENUE_DATA.value
        fin_status = "INCOMPLETE_REVENUE_DATA"
        is_complete = False
        conf = "RECORDED" if total_attributable_costs is not None else "NEEDS_DATA"
        integrity_notes.append("Harvest sales receipts are unrecorded.")
    else:
        comp_status = FinancialCompletenessStatus.COMPLETE_FROM_RECORDED_ACTUALS.value
        fin_status = "RECORDED_ACTUALS"
        is_complete = True
        conf = "RECORDED"
        integrity_notes.append("All direct production inputs and sales revenues are verified from recorded actuals.")

    notice = (
        "Financial figures reflect only verified sale receipts and ledger transactions without synthetic estimates. "
        "Missing cost categories are never treated as zero; complete profitability is asserted only when all actuals are recorded."
    )

    return BatchFinancialSummary(
        batch_id=batch_id,
        total_harvested_kg=total_harvested_kg,
        partial_harvest_kg=partial_harvest_kg,
        final_harvest_kg=final_harvest_kg,
        harvest_events_count=harvest_events_count,
        total_revenue=round(total_revenue, 2) if total_revenue is not None else None,
        total_revenue_realized=round(total_revenue, 2) if total_revenue is not None else None,
        weighted_avg_sale_price_per_kg=avg_price,
        average_sale_price_per_kg=avg_price,
        total_documented_losses_kg=round(total_documented_losses_kg, 2),
        cumulative_feed_kg=cumulative_feed_kg,
        costed_feed_kg=costed_feed_kg,
        uncosted_feed_kg=uncosted_feed_kg,
        recorded_feed_cost=round(recorded_feed_cost, 2) if recorded_feed_cost is not None else None,
        total_feed_cost_recorded=round(recorded_feed_cost, 2) if recorded_feed_cost is not None else None,
        has_recorded_feed_cost=has_feed_cost,
        feed_cost_completeness=feed_completeness,
        recorded_seed_cost=round(recorded_seed_cost, 2) if recorded_seed_cost is not None else None,
        recorded_treatment_cost=round(recorded_treatment_cost, 2) if recorded_treatment_cost is not None else None,
        recorded_energy_cost=round(recorded_energy_cost, 2) if recorded_energy_cost is not None else None,
        other_recorded_costs=round(other_recorded_costs, 2) if other_recorded_costs is not None else None,
        total_recorded_costs=total_attributable_costs,
        total_attributable_recorded_costs=total_attributable_costs,
        net_realized_margin=net_margin,
        realized_margin_per_kg=margin_per_kg,
        cost_breakdown=cost_breakdown,
        financial_status=fin_status,
        completeness_status=comp_status,
        is_profitability_complete=is_complete,
        missing_cost_categories=missing_categories,
        confidence_label=conf,
        advisory_notice=notice,
        data_integrity_notes=integrity_notes,
    )


class FarmEconomicsSummary(BaseModel):
    """Farm-level or pond-level commercial economics rollup derived strictly from attributable records."""
    farm_id: str
    pond_id: Optional[str] = None
    as_of: str
    total_batches_evaluated: int
    total_realized_harvest_kg: float
    total_realized_revenue: float
    total_attributable_feed_cost: float
    total_attributable_recorded_costs: float
    net_realized_margin: Optional[float] = None
    weighted_avg_sale_price_per_kg: Optional[float] = None
    batches_with_revenue_count: int
    batches_with_feed_cost_count: int
    completeness_breakdown: Dict[str, int] = Field(default_factory=dict)
    missing_cost_categories_summary: List[str] = Field(default_factory=list)
    batch_economics: List[Dict[str, Any]] = Field(default_factory=list)
    advisory_notice: str
    data_integrity_notes: List[str] = Field(default_factory=list)


def calculate_farm_economics_summary(
    farm_id: str,
    pond_id: Optional[str],
    batch_summaries: List[BatchFinancialSummary],
) -> FarmEconomicsSummary:
    """Aggregate farm-level economics safely without double-counting or ungrounded overhead allocations."""
    total_batches = len(batch_summaries)
    total_hrv_kg = round(sum(b.total_harvested_kg for b in batch_summaries), 2)
    total_rev = round(sum(b.total_revenue or 0.0 for b in batch_summaries if b.total_revenue is not None), 2)
    total_feed_c = round(sum(b.recorded_feed_cost or 0.0 for b in batch_summaries if b.recorded_feed_cost is not None), 2)
    total_costs = round(sum(b.total_attributable_recorded_costs or 0.0 for b in batch_summaries if b.total_attributable_recorded_costs is not None), 2)

    rev_batches = sum(1 for b in batch_summaries if b.total_revenue is not None and b.total_revenue > 0)
    feed_batches = sum(1 for b in batch_summaries if b.recorded_feed_cost is not None and b.recorded_feed_cost > 0)

    # Margin is only calculated if at least some revenue or costs are documented
    net_margin = None
    if rev_batches > 0 or total_costs > 0:
        net_margin = round(total_rev - total_costs, 2)

    # Weighted average sale price across batches that had both revenue and harvested kg
    kg_with_rev = sum(b.total_harvested_kg for b in batch_summaries if b.total_revenue is not None and b.total_revenue > 0)
    avg_price = round(total_rev / kg_with_rev, 2) if (total_rev > 0 and kg_with_rev > 0) else None

    # Completeness breakdown
    comp_counts: Dict[str, int] = {
        FinancialCompletenessStatus.COMPLETE_FROM_RECORDED_ACTUALS.value: 0,
        FinancialCompletenessStatus.INCOMPLETE_COST_DATA.value: 0,
        FinancialCompletenessStatus.INCOMPLETE_REVENUE_DATA.value: 0,
        FinancialCompletenessStatus.UNATTRIBUTABLE_COSTS.value: 0,
        FinancialCompletenessStatus.NO_RECORDS.value: 0,
    }
    for b in batch_summaries:
        status_key = b.completeness_status
        comp_counts[status_key] = comp_counts.get(status_key, 0) + 1

    # Unique missing categories across batches
    unique_missing: List[str] = []
    for b in batch_summaries:
        for cat in b.missing_cost_categories:
            if cat not in unique_missing:
                unique_missing.append(cat)

    notes = [
        "Farm economics rollups sum only verified batch-attributable commercial records.",
        "Missing cost categories (such as uncosted feed, seed invoices, or facility power) are NEVER assumed as zero.",
        "Farm-wide general expenses are excluded from batch totals to prevent arbitrary allocation errors.",
    ]

    return FarmEconomicsSummary(
        farm_id=farm_id,
        pond_id=pond_id,
        as_of=datetime.now(timezone.utc).isoformat(),
        total_batches_evaluated=total_batches,
        total_realized_harvest_kg=total_hrv_kg,
        total_realized_revenue=total_rev,
        total_attributable_feed_cost=total_feed_c,
        total_attributable_recorded_costs=total_costs,
        net_realized_margin=net_margin,
        weighted_avg_sale_price_per_kg=avg_price,
        batches_with_revenue_count=rev_batches,
        batches_with_feed_cost_count=feed_batches,
        completeness_breakdown=comp_counts,
        missing_cost_categories_summary=unique_missing,
        batch_economics=[b.model_dump() for b in batch_summaries],
        advisory_notice=(
            "Aggregated economics reflect only verified ledger actuals. "
            f"Of {total_batches} batches, {comp_counts[FinancialCompletenessStatus.COMPLETE_FROM_RECORDED_ACTUALS.value]} are fully complete; "
            f"{comp_counts[FinancialCompletenessStatus.INCOMPLETE_COST_DATA.value]} have incomplete cost records."
        ),
        data_integrity_notes=notes,
    )



