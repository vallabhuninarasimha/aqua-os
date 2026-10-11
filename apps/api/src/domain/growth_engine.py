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
import math
from typing import Any, Dict, Optional, Tuple
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

