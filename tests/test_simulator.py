"""Automated test suite for 20-pond biology/physics simulator."""

from datetime import datetime, timezone

from packages.telemetry_schema.models import MetricType, QualityStatus
from tools.simulators.clock import VirtualClock
from tools.simulators.generator import PondTelemetryGenerator
from tools.simulators.scenarios import PondScenarioConfig, ScenarioType


def test_deterministic_reproducibility_with_seed():
    """Verify identical random seeds produce byte-for-byte identical telemetry."""
    clock_1 = VirtualClock(datetime(2026, 10, 10, 6, 0, 0, tzinfo=timezone.utc))
    gen_1 = PondTelemetryGenerator(pond_count=20, clock=clock_1, seed=999)

    clock_2 = VirtualClock(datetime(2026, 10, 10, 6, 0, 0, tzinfo=timezone.utc))
    gen_2 = PondTelemetryGenerator(pond_count=20, clock=clock_2, seed=999)

    # Step both generators 10 times
    for _ in range(10):
        clock_1.advance(30)
        clock_2.advance(30)
        packets_1 = gen_1.step(30)
        packets_2 = gen_2.step(30)

        assert len(packets_1) == 20
        assert len(packets_2) == 20
        for p1, p2 in zip(packets_1, packets_2):
            assert p1.pond_id == p2.pond_id
            assert p1.is_simulated is True
            assert (
                p1.metrics[MetricType.DISSOLVED_OXYGEN].value
                == p2.metrics[MetricType.DISSOLVED_OXYGEN].value
            )
            assert (
                p1.metrics[MetricType.TEMPERATURE].value
                == p2.metrics[MetricType.TEMPERATURE].value
            )


def test_20_ponds_generated_by_default():
    """Verify generator initializes 20 ponds by default with simulated flags."""
    clock = VirtualClock()
    generator = PondTelemetryGenerator(pond_count=20, clock=clock)
    packets = generator.step()

    assert len(packets) == 20
    pond_ids = [p.pond_id for p in packets]
    expected_ids = [f"pond-{i:02d}" for i in range(1, 21)]
    assert pond_ids == expected_ids
    assert all(p.is_simulated for p in packets)


def test_day_night_diurnal_cycle():
    """Verify photosynthesis elevates DO in the afternoon compared to pre-dawn respiration."""
    clock = VirtualClock(datetime(2026, 10, 10, 5, 0, 0, tzinfo=timezone.utc))
    gen = PondTelemetryGenerator(pond_count=1, clock=clock, seed=42)

    # Sample at 05:00 (pre-dawn respiration low)
    packets_dawn = gen.step(dt_seconds=60)
    do_dawn = packets_dawn[0].metrics[MetricType.DISSOLVED_OXYGEN].value

    # Simulate hourly through the morning up to 14:00 (9 hours of daylight)
    for _ in range(9):
        clock.advance(3600)
        packets_afternoon = gen.step(dt_seconds=3600)

    do_afternoon = packets_afternoon[0].metrics[MetricType.DISSOLVED_OXYGEN].value

    # Afternoon DO must be significantly higher than dawn DO due to photosynthesis
    assert do_afternoon > do_dawn + 1.0


def test_aerator_failure_scenario():
    """Verify that an aerator failure event overnight triggers severe DO depletion."""
    clock = VirtualClock(datetime(2026, 10, 10, 1, 0, 0, tzinfo=timezone.utc))
    gen = PondTelemetryGenerator(pond_count=1, clock=clock, seed=42)

    # Configure aerator failure fault starting at 01:00
    gen.set_pond_scenario(
        "pond-01",
        PondScenarioConfig(
            pond_id="pond-01",
            scenario_type=ScenarioType.AERATOR_FAILURE,
            trigger_hour=1.0,
            duration_hours=5.0,
        ),
    )

    # Step overnight for 3 hours with aerators failed
    for _ in range(18):
        clock.advance(600)
        packets = gen.step(dt_seconds=600)

    final_do = packets[0].metrics[MetricType.DISSOLVED_OXYGEN].value
    # Without aerators at night, DO plunges into hypoxia (< 3.0 mg/L)
    assert final_do < 3.5
    assert packets[0].hardware_status.mains_power_ok is False


def test_sensor_fault_scenario():
    """Verify that sensor fault scenario emits SENSOR_FAULT quality flag."""
    clock = VirtualClock()
    gen = PondTelemetryGenerator(pond_count=1, clock=clock)
    gen.set_pond_scenario(
        "pond-01",
        PondScenarioConfig(pond_id="pond-01", scenario_type=ScenarioType.SENSOR_FAULT),
    )

    packets = gen.step()
    do_reading = packets[0].metrics[MetricType.DISSOLVED_OXYGEN]
    assert do_reading.quality == QualityStatus.SENSOR_FAULT


def test_probe_fouling_scenario():
    """Verify probe fouling scenario emits SUSPECT_DRIFT quality flag."""
    clock = VirtualClock()
    gen = PondTelemetryGenerator(pond_count=1, clock=clock)
    gen.set_pond_scenario(
        "pond-01",
        PondScenarioConfig(pond_id="pond-01", scenario_type=ScenarioType.PROBE_FOULING),
    )

    packets = gen.step()
    do_reading = packets[0].metrics[MetricType.DISSOLVED_OXYGEN]
    assert do_reading.quality == QualityStatus.SUSPECT_DRIFT


def test_stale_readings_scenario():
    """Verify stale reading scenario freezes sensor readings."""
    clock = VirtualClock()
    gen = PondTelemetryGenerator(pond_count=1, clock=clock)

    # Baseline step
    gen.step(10)

    # Set stale scenario
    gen.set_pond_scenario(
        "pond-01",
        PondScenarioConfig(pond_id="pond-01", scenario_type=ScenarioType.STALE_READINGS),
    )

    clock.advance(30)
    p1 = gen.step(30)[0].metrics[MetricType.DISSOLVED_OXYGEN].value
    clock.advance(30)
    p2 = gen.step(30)[0].metrics[MetricType.DISSOLVED_OXYGEN].value
    clock.advance(30)
    p3 = gen.step(30)[0].metrics[MetricType.DISSOLVED_OXYGEN].value

    # Reading should be frozen
    assert p1 == p2 == p3


def test_out_of_bounds_spike_scenario():
    """Verify that an electrical spike is flagged OUT_OF_BOUNDS."""
    clock = VirtualClock()
    gen = PondTelemetryGenerator(pond_count=1, clock=clock)
    gen.set_pond_scenario(
        "pond-01",
        PondScenarioConfig(pond_id="pond-01", scenario_type=ScenarioType.OUT_OF_BOUNDS_SPIKE),
    )

    packets = gen.step()
    do_reading = packets[0].metrics[MetricType.DISSOLVED_OXYGEN]
    assert do_reading.quality == QualityStatus.OUT_OF_BOUNDS
    assert do_reading.value > 25.0
