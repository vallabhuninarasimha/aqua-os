"""Measured-sample shrimp size grading.

Converts individually measured shrimp weights into count-per-kg size classes.
Commercial class boundaries are supplied by the farm/operator; buyer-specific
grade conventions are never hard-coded.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any


def analyze_shrimp_sample(
    weights_g: list[float],
    grade_bands: list[dict[str, Any]],
) -> dict[str, Any]:
    """Classify a physical sample by count/kg using operator-defined bands.

    Individual count/kg is 1000 / weight_g. The sample average count/kg is
    calculated as 1000 / mean body weight, not the mean of individual ratios.
    """
    if not weights_g:
        raise ValueError("At least one measured shrimp weight is required.")
    if len(weights_g) > 500:
        raise ValueError("A single grading sample is limited to 500 shrimp.")
    normalized_weights = [float(weight) for weight in weights_g]
    if any(not (0.01 <= weight <= 200.0) for weight in normalized_weights):
        raise ValueError("Each shrimp weight must be between 0.01g and 200g.")

    if not grade_bands:
        raise ValueError("At least one operator-defined commercial grade band is required.")
    if len(grade_bands) > 20:
        raise ValueError("A maximum of 20 grade bands is supported.")

    bands: list[dict[str, Any]] = []
    labels: set[str] = set()
    for raw in grade_bands:
        label = str(raw.get("label", "")).strip()
        low = float(raw.get("min_count_per_kg", 0))
        high = float(raw.get("max_count_per_kg", 0))
        if not label or len(label) > 64:
            raise ValueError("Each grade band requires a label of 1 to 64 characters.")
        if label.lower() in labels:
            raise ValueError(f"Duplicate grade label: {label}.")
        if low <= 0 or high < low:
            raise ValueError(f"Invalid count/kg range for grade '{label}'.")
        labels.add(label.lower())
        bands.append({"label": label, "min": low, "max": high})

    bands.sort(key=lambda item: item["min"])
    for previous, current in zip(bands, bands[1:]):
        if current["min"] <= previous["max"]:
            raise ValueError(
                f"Grade bands '{previous['label']}' and '{current['label']}' overlap."
            )

    classified: dict[str, list[float]] = defaultdict(list)
    unclassified: list[float] = []
    for weight in normalized_weights:
        count_per_kg = 1000.0 / weight
        match = next(
            (band for band in bands if band["min"] <= count_per_kg <= band["max"]),
            None,
        )
        if match:
            classified[match["label"]].append(weight)
        else:
            unclassified.append(weight)

    count = len(normalized_weights)
    average_weight = sum(normalized_weights) / count
    ordered_weights = sorted(normalized_weights)
    median_weight = (
        ordered_weights[count // 2]
        if count % 2
        else (ordered_weights[count // 2 - 1] + ordered_weights[count // 2]) / 2
    )
    variance = sum((weight - average_weight) ** 2 for weight in normalized_weights) / count
    grade_distribution = []
    for band in bands:
        members = classified[band["label"]]
        grade_distribution.append({
            "grade": band["label"],
            "min_count_per_kg": band["min"],
            "max_count_per_kg": band["max"],
            "shrimp_count": len(members),
            "sample_percentage": round(len(members) / count * 100.0, 2),
            "average_weight_g": round(sum(members) / len(members), 3) if members else None,
        })

    return {
        "status": "ANALYZED",
        "measurement_basis": "INDIVIDUALLY_MEASURED_SAMPLE",
        "sample_count": count,
        "average_body_weight_g": round(average_weight, 3),
        "median_body_weight_g": round(median_weight, 3),
        "average_count_per_kg": round(1000.0 / average_weight, 2),
        "individual_count_per_kg_mean": round(
            sum(1000.0 / weight for weight in normalized_weights) / count, 2
        ),
        "weight_std_deviation_g": round(variance ** 0.5, 3),
        "minimum_weight_g": round(ordered_weights[0], 3),
        "maximum_weight_g": round(ordered_weights[-1], 3),
        "grade_distribution": grade_distribution,
        "unclassified_count": len(unclassified),
        "unclassified_percentage": round(len(unclassified) / count * 100.0, 2),
        "unclassified_weights_g": [round(weight, 3) for weight in unclassified],
        "grade_band_source": "OPERATOR_CONFIGURED",
        "limitations": [
            "This is a sample-based size classification, not a confirmed whole-pond or whole-harvest grade.",
            "Results depend on calibrated scales, representative sampling, and buyer-specific grade bands.",
            "No camera inference, harvest decision, pricing decision, or equipment command was performed.",
        ],
    }
