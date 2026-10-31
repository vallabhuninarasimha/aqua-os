"""Domain logic and risk evaluation for shrimp health, mortality, and treatments.

Follows strict biological aquaculture principles:
1. Physical mortality tracking vs. sampling survival without double counting.
2. Observational clinical alerts labeled as risk indicators / observational suspicions,
   never claiming unconfirmed laboratory pathology.
3. Withdrawal period calculations and harvest restriction enforcement.
"""

from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from packages.telemetry_schema.models import AlertSeverity


def calculate_population_metrics(
    initial_count: int,
    cumulative_recorded_mortality: int,
    sampling_survival_pct: float = 85.0,
) -> Dict[str, Any]:
    """Calculate documented and conservative live population metrics.

    Mathematical Formulation:
    - Initial Stock: N_0
    - Physical Documented Mortality: M_rec
    - Directly Observed Live Population:
        N_phys = max(0, N_0 - M_rec)
    - Confirmed Mortality Rate (%):
        Mortality_confirmed = (M_rec / N_0) * 100
    - Periodic Net-Sampling Estimated Population:
        N_sampling = round(N_0 * (S_sampling / 100))
    - Conservative Live Population:
        N_adj = min(N_phys, N_sampling)
    - Conservative Live Survival (%):
        S_adj = (N_adj / N_0) * 100
    - Unobserved Loss Rate (%):
        Loss_unobserved = max(0.0, (100.0 - S_sampling) - Mortality_confirmed)

    Ensures that sampling estimates (which encompass cannibalism and natural
    bottom decay) are not double-subtracted alongside retrieved carcasses.
    """
    n0 = max(1, int(initial_count))
    m_rec = max(0, int(cumulative_recorded_mortality))
    s_sample = max(0.0, min(100.0, float(sampling_survival_pct)))

    # Directly retrieved carcass survival
    n_phys = max(0, n0 - m_rec)
    confirmed_mortality_pct = round((m_rec / n0) * 100.0, 2)

    # Sampling estimate
    n_sampling = max(0, int(round(n0 * (s_sample / 100.0))))

    # Conservative live estimate is the stricter bound
    n_adj = min(n_phys, n_sampling)
    s_adj = round((n_adj / n0) * 100.0, 2)

    # Unobserved loss captures difference between net sampling survival and retrieved bodies
    unobserved_loss_pct = round(max(0.0, (100.0 - s_sample) - confirmed_mortality_pct), 2)

    return {
        "initial_stock_count": n0,
        "cumulative_recorded_mortality": m_rec,
        "physical_remaining_population": n_phys,
        "confirmed_mortality_pct": confirmed_mortality_pct,
        "sampling_estimated_population": n_sampling,
        "sampling_survival_pct": round(s_sample, 2),
        "conservative_adjusted_population": n_adj,
        "conservative_adjusted_survival_pct": s_adj,
        "estimated_unobserved_loss_pct": unobserved_loss_pct,
    }


def calculate_withdrawal_status(
    application_time: datetime,
    withdrawal_period_days: int,
    current_time: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Calculate harvest restriction window for a medicinal or chemical treatment."""
    now = current_time or datetime.now(timezone.utc)
    if isinstance(application_time, str):
        application_time = datetime.fromisoformat(application_time.replace("Z", "+00:00"))
    if isinstance(now, str):
        now = datetime.fromisoformat(now.replace("Z", "+00:00"))
    if application_time.tzinfo is None:
        application_time = application_time.replace(tzinfo=timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    days = max(0, int(withdrawal_period_days))
    harvest_restriction_until = application_time + timedelta(days=days)
    is_restricted = now < harvest_restriction_until
    remaining_seconds = max(0.0, (harvest_restriction_until - now).total_seconds()) if is_restricted else 0.0

    return {
        "withdrawal_period_days": days,
        "harvest_restriction_until": harvest_restriction_until,
        "is_harvest_restricted": is_restricted,
        "remaining_restriction_days": round(remaining_seconds / 86400.0, 2),
        "remaining_restriction_hours": round(remaining_seconds / 3600.0, 1),
    }


def evaluate_health_risks(
    mortalities_24h_count: int,
    latest_single_mortality: int,
    population: int,
    recent_feed_responses: List[str],
    latest_observation: Optional[Dict[str, Any]] = None,
    water_quality: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """Evaluate observational health risks and yield alert descriptors.

    All generated alerts are labeled as risk indicators or observational suspicions
    rather than confirmed disease diagnoses.
    """
    pop = max(1, population)
    alerts: List[Dict[str, Any]] = []

    # 1. Mortality Spike Check
    rate_24h_pct = (mortalities_24h_count / pop) * 100.0
    if mortalities_24h_count >= 200 or rate_24h_pct >= 0.5:
        alerts.append({
            "alert_code": "HEALTH_MORTALITY_SPIKE_CRITICAL",
            "severity": AlertSeverity.CRITICAL,
            "risk_category": "OBSERVATIONAL_SUSPICION",
            "message": (
                f"Severe mortality spike: {mortalities_24h_count} dead shrimp in last 24h "
                f"({rate_24h_pct:.2f}% of population). High biological risk indicator."
            ),
            "recommended_action": (
                "Immediately inspect pond bottom siphons, engage maximum aeration, "
                "verify dissolved oxygen and unionized ammonia, halt broadcast feeding, "
                "and collect live specimens for PCR diagnostic laboratory testing."
            ),
        })
    elif mortalities_24h_count >= 50 or rate_24h_pct >= 0.1 or latest_single_mortality >= 30:
        alerts.append({
            "alert_code": "HEALTH_MORTALITY_SPIKE_WARNING",
            "severity": AlertSeverity.WARNING,
            "risk_category": "OBSERVATIONAL_SUSPICION",
            "message": (
                f"Elevated mortality detected: {mortalities_24h_count} dead collected in 24h "
                f"(latest single event: {latest_single_mortality}). Potential stress indicator."
            ),
            "recommended_action": (
                "Inspect pond perimeter and feeding trays for sluggish shrimp, "
                "check bottom dissolved oxygen, and monitor next feeding tray consumption."
            ),
        })

    # 2. Repeated Poor Feed Response Check
    poor_count = sum(1 for r in recent_feed_responses if r in ("NONE", "POOR"))
    if len(recent_feed_responses) >= 2 and poor_count >= 2:
        alerts.append({
            "alert_code": "HEALTH_ANOREXIA_FEED_DROP",
            "severity": AlertSeverity.WARNING,
            "risk_category": "OBSERVATIONAL_SUSPICION",
            "message": (
                f"Persistent feed anorexia: {poor_count} consecutive poor or non-existent "
                "feeding tray responses observed."
            ),
            "recommended_action": (
                "Cut broadcast feed rations by 40-50% to prevent water fouling, verify water parameters, "
                "and inspect hepatopancreas condition in sampled shrimp."
            ),
        })

    # 3. Clinical Observation Signs Check
    if latest_observation:
        swimming = latest_observation.get("swimming_activity")
        if swimming in ("SURFACING", "SPIRALING"):
            alerts.append({
                "alert_code": "HEALTH_ABNORMAL_SWIMMING_CRITICAL",
                "severity": AlertSeverity.CRITICAL,
                "risk_category": "OBSERVATIONAL_SUSPICION",
                "message": (
                    f"Critical behavioral abnormality: Shrimp observed {swimming.lower()} along banks/surface. "
                    "Indicates severe hypoxia, acute toxicity, or gill fouling."
                ),
                "recommended_action": (
                    "Turn on all paddlewheel aerators immediately, check dissolved oxygen at 0.5m depth, "
                    "and examine gills for debris, black spots, or protozoan fouling."
                ),
            })
        elif swimming == "LETHARGIC":
            alerts.append({
                "alert_code": "HEALTH_LETHARGIC_BEHAVIOR",
                "severity": AlertSeverity.WARNING,
                "risk_category": "OBSERVATIONAL_SUSPICION",
                "message": "Lethargic shrimp behavior observed at pond perimeter.",
                "recommended_action": "Check feeding trays and sample 10 shrimp to evaluate gut fullness.",
            })

        gills = latest_observation.get("gills_condition")
        if gills in ("BLACK", "BROWN", "FOUL"):
            alerts.append({
                "alert_code": "HEALTH_GILL_DISCOLORATION",
                "severity": AlertSeverity.WARNING,
                "risk_category": "OBSERVATIONAL_SUSPICION",
                "message": f"Abnormal gill coloration observed: {gills}. Potential gill fouling or nitrite stress.",
                "recommended_action": (
                    "Conduct bottom siphoning to remove accumulated organic sludge, test nitrite (NO2-) and TAN, "
                    "and increase aeration."
                ),
            })

        gut = latest_observation.get("gut_fullness")
        if gut == "EMPTY":
            alerts.append({
                "alert_code": "HEALTH_EMPTY_GUT_OBSERVED",
                "severity": AlertSeverity.WARNING,
                "risk_category": "OBSERVATIONAL_SUSPICION",
                "message": "Empty gut observed in health sample. Shrimp have stopped feeding.",
                "recommended_action": "Evaluate water temperature, pH swing, and hepatopancreas pigmentation.",
            })

        lesions_sev = latest_observation.get("lesions_severity")
        if lesions_sev in ("MODERATE", "SEVERE"):
            alerts.append({
                "alert_code": "HEALTH_CUTICULAR_LESIONS",
                "severity": AlertSeverity.CRITICAL if lesions_sev == "SEVERE" else AlertSeverity.WARNING,
                "risk_category": "OBSERVATIONAL_SUSPICION",
                "message": f"Visible physical cuticular/exoskeleton lesions with {lesions_sev} severity observed.",
                "recommended_action": (
                    "Sample shrimp to check for bacterial shell disease or black spot syndrome; "
                    "apply water conditioning probiotics if water exchange is restricted."
                ),
            })

    # 4. Co-occurring Water Quality Excursions Check
    if water_quality and latest_observation:
        do_val = water_quality.get("dissolved_oxygen")
        temp_val = water_quality.get("temperature")
        ph_val = water_quality.get("ph")

        has_clinical = bool(
            latest_observation.get("swimming_activity") in ("SURFACING", "LETHARGIC", "SPIRALING")
            or latest_observation.get("gills_condition") in ("BLACK", "BROWN", "FOUL")
            or latest_observation.get("gut_fullness") == "EMPTY"
        )

        if has_clinical:
            if do_val is not None and do_val < 3.5:
                alerts.append({
                    "alert_code": "HEALTH_WQ_SYNERGY_HYPOXIA",
                    "severity": AlertSeverity.CRITICAL,
                    "risk_category": "RISK_INDICATOR",
                    "message": (
                        f"Compound risk: Abnormal health symptoms combined with low dissolved oxygen ({do_val:.2f} mg/L)."
                    ),
                    "recommended_action": "Engage all aerators immediately and verify power line status.",
                })
            if temp_val is not None and (temp_val < 25.0 or temp_val > 33.0):
                alerts.append({
                    "alert_code": "HEALTH_WQ_SYNERGY_TEMPERATURE",
                    "severity": AlertSeverity.WARNING,
                    "risk_category": "RISK_INDICATOR",
                    "message": (
                        f"Compound risk: Abnormal health symptoms co-occurring with thermal stress ({temp_val:.1f}°C)."
                    ),
                    "recommended_action": "Adjust water depth to mitigate temperature extremes and reduce feeding.",
                })
            if ph_val is not None and (ph_val < 7.5 or ph_val > 8.8):
                alerts.append({
                    "alert_code": "HEALTH_WQ_SYNERGY_PH",
                    "severity": AlertSeverity.WARNING,
                    "risk_category": "RISK_INDICATOR",
                    "message": (
                        f"Compound risk: Abnormal health symptoms co-occurring with pH stress ({ph_val:.2f})."
                    ),
                    "recommended_action": "Buffer water alkalinity with agricultural lime or dolomite.",
                })

    return alerts

