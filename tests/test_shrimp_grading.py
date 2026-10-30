import pytest

from apps.api.src.domain.shrimp_grading import analyze_shrimp_sample


BANDS = [
    {"label": "30-count", "min_count_per_kg": 25, "max_count_per_kg": 35},
    {"label": "40-count", "min_count_per_kg": 36, "max_count_per_kg": 45},
]


def test_classifies_individually_weighed_shrimp_and_reports_distribution():
    result = analyze_shrimp_sample([40.0, 30.0, 25.0], BANDS)

    assert result["sample_count"] == 3
    assert result["average_body_weight_g"] == pytest.approx(31.667, abs=0.001)
    assert result["average_count_per_kg"] == pytest.approx(31.58, abs=0.01)
    assert result["grade_distribution"][0]["shrimp_count"] == 1
    assert result["grade_distribution"][1]["shrimp_count"] == 1
    assert result["unclassified_count"] == 1


def test_rejects_overlapping_grade_bands():
    with pytest.raises(ValueError, match="overlap"):
        analyze_shrimp_sample(
            [30.0],
            [
                {"label": "A", "min_count_per_kg": 20, "max_count_per_kg": 40},
                {"label": "B", "min_count_per_kg": 40, "max_count_per_kg": 50},
            ],
        )


def test_rejects_empty_or_physically_invalid_samples():
    with pytest.raises(ValueError, match="At least one"):
        analyze_shrimp_sample([], BANDS)
    with pytest.raises(ValueError, match="between 0.01g and 200g"):
        analyze_shrimp_sample([0.0], BANDS)


def test_rejects_duplicate_grade_labels():
    with pytest.raises(ValueError, match="Duplicate grade label"):
        analyze_shrimp_sample(
            [30.0],
            [
                {"label": "A", "min_count_per_kg": 20, "max_count_per_kg": 30},
                {"label": "a", "min_count_per_kg": 31, "max_count_per_kg": 40},
            ],
        )
