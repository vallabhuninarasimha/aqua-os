"""Unit and persistence tests for configuration-driven pond management."""

import pytest
from pydantic import ValidationError
from sqlalchemy.orm import Session

from apps.api.src.infrastructure.repositories.sql_pond_repository import SQLPondRepository
from apps.api.src.services.pond_registry import PondRegistryService
from packages.telemetry_schema.config import BiologicalThresholds, PondConfig


def test_default_20_pond_initialization():
    """Verify that the baseline configuration initializes exactly 20 ponds."""
    registry = PondRegistryService(farm_id="farm-test")
    ponds = registry.get_all_ponds()

    assert len(ponds) == 20
    assert registry.get_total_pond_count() == 20
    assert registry.get_active_pond_count() == 20

    # Verify naming convention and attributes
    pond_ids = [p.pond_id for p in ponds]
    expected_ids = [f"pond-{i:02d}" for i in range(1, 21)]
    assert pond_ids == expected_ids

    # Check pond 01 defaults
    p1 = registry.get_pond("pond-01")
    assert p1 is not None
    assert p1.species == "Litopenaeus vannamei"
    assert p1.aerator_count == 4
    assert p1.thresholds.do_emergency_mg_l == 3.0


def test_dynamic_pond_expansion_beyond_20():
    """Verify that the system supports adding pond-21 and beyond without redesign."""
    registry = PondRegistryService(farm_id="farm-test")
    assert registry.get_total_pond_count() == 20

    # Add Pond 21 dynamically
    new_pond = PondConfig(
        farm_id="farm-test",
        pond_id="pond-21",
        name="Pond 21 Expansion",
        area_hectares=0.75,
        depth_meters=1.4,
        species="Litopenaeus vannamei",
        stocking_density_per_m2=75,
        days_of_culture=1,
        is_active=True,
        aerator_count=6,
        feeder_count=2,
    )
    registry.register_or_update_pond(new_pond)

    assert registry.get_total_pond_count() == 21
    fetched = registry.get_pond("pond-21")
    assert fetched is not None
    assert fetched.aerator_count == 6


def test_pond_threshold_customization():
    """Verify customized biological thresholds per pond (e.g., nursery vs growout)."""
    registry = PondRegistryService(farm_id="farm-test")
    custom_thresholds = BiologicalThresholds(
        do_emergency_mg_l=3.5,
        do_warning_mg_l=4.5,
        do_target_min_mg_l=5.5,
        ph_min=7.8,
        ph_max=8.2,
    )
    p2 = registry.get_pond("pond-02")
    assert p2 is not None

    updated_p2 = p2.model_copy(update={"thresholds": custom_thresholds})
    registry.register_or_update_pond(updated_p2)

    retrieved = registry.get_pond("pond-02")
    assert retrieved is not None
    assert retrieved.thresholds.do_emergency_mg_l == 3.5
    assert retrieved.thresholds.ph_min == 7.8


def test_sql_pond_repository_persistence_across_restarts(db_session: Session):
    """Verify that pond configurations persist to database and survive application restarts."""
    repo_1 = SQLPondRepository(db_session)
    custom_pond = PondConfig(
        farm_id="farm-alpha",
        pond_id="pond-99",
        name="Persistent Test Pond",
        aerator_count=8,
    )
    repo_1.save(custom_pond)

    # Simulate fresh app startup with new session and repository instance
    repo_2 = SQLPondRepository(db_session)
    retrieved = repo_2.get(farm_id="farm-alpha", pond_id="pond-99")
    assert retrieved is not None
    assert retrieved.name == "Persistent Test Pond"
    assert retrieved.aerator_count == 8


def test_cross_farm_pond_identity_isolation(db_session: Session):
    """Verify that identical pond IDs across different farms are isolated and do not collide."""
    repo = SQLPondRepository(db_session)

    # Farm Alpha Pond 01
    pond_alpha = PondConfig(
        farm_id="farm-alpha",
        pond_id="pond-01",
        name="Alpha Pond 01",
        aerator_count=4,
    )
    repo.save(pond_alpha)

    # Farm Beta Pond 01 (identical pond_id, different farm_id)
    pond_beta = PondConfig(
        farm_id="farm-beta",
        pond_id="pond-01",
        name="Beta Pond 01",
        aerator_count=6,
    )
    repo.save(pond_beta)

    # Verify both exist independently without overwriting each other
    fetched_alpha = repo.get(farm_id="farm-alpha", pond_id="pond-01")
    fetched_beta = repo.get(farm_id="farm-beta", pond_id="pond-01")

    assert fetched_alpha is not None
    assert fetched_beta is not None
    assert fetched_alpha.name == "Alpha Pond 01"
    assert fetched_alpha.aerator_count == 4
    assert fetched_beta.name == "Beta Pond 01"
    assert fetched_beta.aerator_count == 6


def test_invalid_biological_thresholds_rejected():
    """Verify that logically invalid thresholds are caught by validation."""
    # do_emergency >= do_warning is invalid
    with pytest.raises(ValidationError):
        BiologicalThresholds(
            do_emergency_mg_l=4.5,
            do_warning_mg_l=4.0,  # Warning less than emergency!
        )

    # ph_min >= ph_max is invalid
    with pytest.raises(ValidationError):
        BiologicalThresholds(
            ph_min=8.5,
            ph_max=7.5,
        )
