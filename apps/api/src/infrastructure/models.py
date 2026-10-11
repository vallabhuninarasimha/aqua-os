"""SQLAlchemy ORM models for Aqua OS."""

import json
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import (
    Boolean,
    Column,
    DateTime,
    Float,
    Integer,
    String,
    Text,
    UniqueConstraint,
)

from apps.api.src.infrastructure.database import Base
from packages.telemetry_schema.config import BiologicalThresholds, PondConfig
from packages.telemetry_schema.models import (
    HardwareStatus,
    MetricReading,
    MetricType,
    PondTelemetryPacket,
    SafetyEvaluationResult,
)


class PondORM(Base):
    """Relational table for pond configurations.

    Compound primary key (farm_id, pond_id) isolates farms and prevents collisions.
    """

    __tablename__ = "ponds"

    farm_id = Column(String(64), primary_key=True, nullable=False, index=True)
    pond_id = Column(String(64), primary_key=True, nullable=False, index=True)
    name = Column(String(128), nullable=False)
    area_acres = Column(Float, nullable=False, default=0.75)
    area_hectares = Column(Float, nullable=False, default=0.3035)
    depth_feet = Column(Float, nullable=False, default=4.0)
    depth_meters = Column(Float, nullable=False, default=1.2192)
    species = Column(String(128), nullable=False, default="Litopenaeus vannamei")
    stocking_count = Column(Integer, nullable=False, default=150_000)
    stocking_density_per_m2 = Column(Integer, nullable=False, default=49)
    days_of_culture = Column(Integer, nullable=False, default=0)
    is_active = Column(Boolean, nullable=False, default=True)
    aerator_count = Column(Integer, nullable=False, default=4)
    feeder_count = Column(Integer, nullable=False, default=0)
    transformer_id = Column(String(32), nullable=False, default="tx-1")
    thresholds_json = Column(Text, nullable=False)
    # Hydraulic & Water Management parameters
    water_level_target_m = Column(Float, nullable=False, default=1.22)
    water_level_min_m = Column(Float, nullable=False, default=0.95)
    water_level_max_m = Column(Float, nullable=False, default=1.40)
    normal_outlet_state = Column(String(32), nullable=False, default="CLOSED")
    full_drain_outlet_state = Column(String(32), nullable=False, default="CLOSED")
    full_drain_locked = Column(Boolean, nullable=False, default=True)
    drain_lock_reason = Column(String(128), nullable=False, default="Active batch biological containment")
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def to_domain(self) -> PondConfig:
        thresholds_dict = json.loads(self.thresholds_json)
        return PondConfig(
            farm_id=self.farm_id,
            pond_id=self.pond_id,
            name=self.name,
            area_acres=getattr(self, "area_acres", 0.75) or 0.75,
            area_hectares=self.area_hectares,
            depth_feet=getattr(self, "depth_feet", 4.0) or 4.0,
            depth_meters=self.depth_meters,
            species=self.species,
            stocking_count=getattr(self, "stocking_count", 150_000) or 150_000,
            stocking_density_per_m2=self.stocking_density_per_m2,
            days_of_culture=self.days_of_culture,
            is_active=self.is_active,
            aerator_count=self.aerator_count,
            feeder_count=self.feeder_count,
            transformer_id=getattr(self, "transformer_id", "tx-1") or "tx-1",
            thresholds=BiologicalThresholds(**thresholds_dict),
        )

    @classmethod
    def from_domain(cls, pond: PondConfig) -> "PondORM":
        return cls(
            farm_id=pond.farm_id,
            pond_id=pond.pond_id,
            name=pond.name,
            area_acres=pond.area_acres,
            area_hectares=pond.area_hectares,
            depth_feet=pond.depth_feet,
            depth_meters=pond.depth_meters,
            species=pond.species,
            stocking_count=pond.stocking_count,
            stocking_density_per_m2=pond.stocking_density_per_m2,
            days_of_culture=pond.days_of_culture,
            is_active=pond.is_active,
            aerator_count=pond.aerator_count,
            feeder_count=pond.feeder_count,
            transformer_id=pond.transformer_id,
            thresholds_json=json.dumps(pond.thresholds.model_dump(mode="json")),
        )


class TelemetryORM(Base):
    """Historical telemetry storage.

    Compatible with standard PostgreSQL/SQLite and TimescaleDB hypertable conversion.
    """

    __tablename__ = "telemetry_records"
    __table_args__ = (
        UniqueConstraint("farm_id", "pond_id", "timestamp", name="uq_telemetry_event"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    farm_id = Column(String(64), nullable=False, index=True)
    pond_id = Column(String(64), nullable=False, index=True)
    timestamp = Column(DateTime(timezone=True), nullable=False, index=True)
    metrics_json = Column(Text, nullable=False)
    hardware_status_json = Column(Text, nullable=True)
    is_simulated = Column(Boolean, nullable=False, default=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))

    def to_domain(self) -> PondTelemetryPacket:
        raw_metrics = json.loads(self.metrics_json)
        metrics = {
            MetricType(k): MetricReading(**v)
            for k, v in raw_metrics.items()
        }
        hw = None
        if self.hardware_status_json:
            hw = HardwareStatus(**json.loads(self.hardware_status_json))

        return PondTelemetryPacket(
            farm_id=self.farm_id,
            pond_id=self.pond_id,
            timestamp=self.timestamp,
            metrics=metrics,
            hardware_status=hw,
            is_simulated=bool(self.is_simulated),
        )

    @classmethod
    def from_domain(cls, packet: PondTelemetryPacket) -> "TelemetryORM":
        raw_metrics = {
            m_type.value: reading.model_dump(mode="json")
            for m_type, reading in packet.metrics.items()
        }
        hw_json = (
            json.dumps(packet.hardware_status.model_dump(mode="json"))
            if packet.hardware_status
            else None
        )
        return cls(
            farm_id=packet.farm_id,
            pond_id=packet.pond_id,
            timestamp=packet.timestamp,
            metrics_json=json.dumps(raw_metrics),
            hardware_status_json=hw_json,
            is_simulated=packet.is_simulated,
        )


class LatestTelemetryORM(Base):
    """Current state cache in SQL for real-time overview matrix."""

    __tablename__ = "latest_telemetry"

    farm_id = Column(String(64), primary_key=True, nullable=False)
    pond_id = Column(String(64), primary_key=True, nullable=False)
    timestamp = Column(DateTime(timezone=True), nullable=False)
    metrics_json = Column(Text, nullable=False)
    hardware_status_json = Column(Text, nullable=True)
    safety_result_json = Column(Text, nullable=True)
    is_simulated = Column(Boolean, nullable=False, default=False)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )

    def to_domain(self) -> tuple[PondTelemetryPacket, Optional[SafetyEvaluationResult]]:
        raw_metrics = json.loads(self.metrics_json)
        metrics = {
            MetricType(k): MetricReading(**v)
            for k, v in raw_metrics.items()
        }
        hw = None
        if self.hardware_status_json:
            hw = HardwareStatus(**json.loads(self.hardware_status_json))

        packet = PondTelemetryPacket(
            farm_id=self.farm_id,
            pond_id=self.pond_id,
            timestamp=self.timestamp,
            metrics=metrics,
            hardware_status=hw,
            is_simulated=bool(self.is_simulated),
        )
        safety_eval = None
        if self.safety_result_json:
            safety_eval = SafetyEvaluationResult(**json.loads(self.safety_result_json))

        return packet, safety_eval


class UserORM(Base):
    """User account model with credentials and role."""

    __tablename__ = "users"

    user_id = Column(String(64), primary_key=True, nullable=False)
    username = Column(String(64), unique=True, nullable=False, index=True)
    password_hash = Column(String(256), nullable=False)
    farm_id = Column(String(64), nullable=False, index=True)
    role = Column(String(32), nullable=False, default="viewer")
    is_active = Column(Boolean, nullable=False, default=True)
    failed_login_attempts = Column(Integer, nullable=False, default=0)
    locked_until = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class RevokedTokenORM(Base):
    """Token revocation blacklist tracking revoked JTIs."""

    __tablename__ = "revoked_tokens"

    jti = Column(String(64), primary_key=True, nullable=False)
    revoked_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    expires_at = Column(DateTime(timezone=True), nullable=False)


class AuditLogORM(Base):
    """Immutable audit trail for security-critical actions and overrides."""

    __tablename__ = "audit_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    timestamp = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    farm_id = Column(String(64), nullable=False, index=True)
    user_id = Column(String(64), nullable=False, index=True)
    action = Column(String(64), nullable=False)
    resource_type = Column(String(64), nullable=False)
    resource_id = Column(String(64), nullable=True)
    details_json = Column(Text, nullable=True)
    ip_address = Column(String(45), nullable=True)


class SensorRegistryORM(Base):
    """Registered physical and simulated sensors per pond."""

    __tablename__ = "sensors"

    id = Column(Integer, primary_key=True, autoincrement=True)
    farm_id = Column(String(64), nullable=False, index=True)
    pond_id = Column(String(64), nullable=False, index=True)
    sensor_id = Column(String(64), nullable=False, unique=True, index=True)
    sensor_type = Column(String(64), nullable=False)
    protocol = Column(String(32), nullable=False, default="MODBUS_RTU_RS485")
    device_address = Column(Integer, nullable=False, default=1)
    register_map_json = Column(Text, nullable=True)
    capabilities_json = Column(Text, nullable=False)  # e.g. ["dissolved_oxygen", "temperature"]
    has_integrated_temp = Column(Boolean, nullable=False, default=False)
    calibration_date = Column(DateTime(timezone=True), nullable=True)
    calibration_offset = Column(Float, nullable=False, default=0.0)
    calibration_slope = Column(Float, nullable=False, default=1.0)
    is_active = Column(Boolean, nullable=False, default=True)
    is_simulated = Column(Boolean, nullable=False, default=False)
    status = Column(String(32), nullable=False, default="ONLINE")
    last_reading_at = Column(DateTime(timezone=True), nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AeratorUnitORM(Base):
    """Individual aerator equipment units with power and physical verification states."""

    __tablename__ = "aerators"

    id = Column(Integer, primary_key=True, autoincrement=True)
    farm_id = Column(String(64), nullable=False, index=True)
    pond_id = Column(String(64), nullable=False, index=True)
    aerator_id = Column(String(64), nullable=False, unique=True, index=True)
    name = Column(String(128), nullable=False)
    rating_kw = Column(Float, nullable=False, default=1.5)
    phase = Column(Integer, nullable=False, default=3)
    transformer_id = Column(String(32), nullable=False, default="tx-1")
    desired_state = Column(String(32), nullable=False, default="OFF")
    verified_physical_state = Column(String(32), nullable=False, default="OFF")
    current_draw_amps = Column(Float, nullable=True)
    power_kw = Column(Float, nullable=True)
    runtime_minutes_today = Column(Float, nullable=False, default=0.0)
    last_state_change = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    fault_reason = Column(String(256), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class AeratorRuntimeLogORM(Base):
    """Historical record of aerator operational runs and daily runtime summaries."""

    __tablename__ = "aerator_runtime_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    log_id = Column(String(64), nullable=False, unique=True, index=True)
    farm_id = Column(String(64), nullable=False, index=True)
    pond_id = Column(String(64), nullable=False, index=True)
    aerator_id = Column(String(64), nullable=False, index=True)
    start_time = Column(DateTime(timezone=True), nullable=False, index=True)
    end_time = Column(DateTime(timezone=True), nullable=True)
    duration_minutes = Column(Float, nullable=False, default=0.0)
    energy_kwh = Column(Float, nullable=False, default=0.0)
    trigger_reason = Column(String(256), nullable=False, default="Automated DO Advisory")
    is_simulated = Column(Boolean, nullable=False, default=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class AeratorDecisionORM(Base):
    """Auditable log of automated and manual aeration decisions (Dry-Run / Safe)."""

    __tablename__ = "aeration_decisions"

    id = Column(Integer, primary_key=True, autoincrement=True)
    decision_id = Column(String(64), nullable=False, unique=True, index=True)
    farm_id = Column(String(64), nullable=False, index=True)
    pond_id = Column(String(64), nullable=False, index=True)
    timestamp = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    do_value = Column(Float, nullable=True)
    proposed_action = Column(String(32), nullable=False)
    reason = Column(String(256), nullable=False)
    interlocks_ok = Column(Boolean, nullable=False, default=True)
    execution_mode = Column(String(32), nullable=False, default="DRY_RUN")
    operator_id = Column(String(64), nullable=True)


class AlertRecordORM(Base):
    """Lifecycle-managed pond alerts with deduplication, acknowledgement, and resolution."""

    __tablename__ = "alerts"

    id = Column(Integer, primary_key=True, autoincrement=True)
    alert_id = Column(String(64), nullable=False, unique=True, index=True)
    farm_id = Column(String(64), nullable=False, index=True)
    pond_id = Column(String(64), nullable=False, index=True)
    alert_code = Column(String(64), nullable=False, index=True)
    severity = Column(String(32), nullable=False)
    status = Column(String(32), nullable=False, default="ACTIVE", index=True)
    message = Column(Text, nullable=False)
    recommended_action = Column(Text, nullable=True)
    trigger_value = Column(Float, nullable=True)
    threshold_value = Column(Float, nullable=True)
    is_simulated = Column(Boolean, nullable=False, default=False)
    first_triggered_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    last_triggered_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
    )
    acknowledged_at = Column(DateTime(timezone=True), nullable=True)
    acknowledged_by = Column(String(64), nullable=True)
    resolved_at = Column(DateTime(timezone=True), nullable=True)
    resolved_by = Column(String(64), nullable=True)


class StockingBatchORM(Base):
    """Pond shrimp stocking batch, multi-batch lifecycle, DOC, and biomass growth observations."""

    __tablename__ = "stocking_batches"

    id = Column(Integer, primary_key=True, autoincrement=True)
    batch_id = Column(String(64), nullable=False, unique=True, index=True)
    farm_id = Column(String(64), nullable=False, index=True)
    pond_id = Column(String(64), nullable=False, index=True)
    stocking_date = Column(DateTime(timezone=True), nullable=False)
    species = Column(String(128), nullable=False, default="Litopenaeus vannamei")
    initial_count = Column(Integer, nullable=False, default=150_000)
    initial_pl_weight_g = Column(Float, nullable=False, default=0.05)
    initial_biomass_kg = Column(Float, nullable=False, default=7.5)
    seed_supplier = Column(String(128), nullable=True)
    seed_quality_notes = Column(Text, nullable=True)
    days_of_culture = Column(Integer, nullable=False, default=1)
    estimated_survival_pct = Column(Float, nullable=False, default=85.0)
    avg_body_weight_g = Column(Float, nullable=False, default=0.05)
    estimated_biomass_kg = Column(Float, nullable=False, default=6.375)
    target_abw_g = Column(Float, nullable=True, default=25.0)
    target_harvest_date = Column(DateTime(timezone=True), nullable=True)
    target_harvest_biomass_kg = Column(Float, nullable=True)
    projected_sale_price_per_kg = Column(Float, nullable=True, default=5.50)
    harvested_date = Column(DateTime(timezone=True), nullable=True)
    harvested_biomass_kg = Column(Float, nullable=True)
    harvest_notes = Column(Text, nullable=True)
    cumulative_recorded_mortality = Column(Integer, nullable=False, default=0)
    status = Column(String(32), nullable=False, default="ACTIVE")  # ACTIVE, HARVESTED, CLOSED
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class GrowthSamplingORM(Base):
    """Periodic pond shrimp sampling records for growth, ABW, and ADG tracking."""

    __tablename__ = "growth_samplings"

    id = Column(Integer, primary_key=True, autoincrement=True)
    sample_id = Column(String(64), nullable=False, unique=True, index=True)
    farm_id = Column(String(64), nullable=False, index=True)
    pond_id = Column(String(64), nullable=False, index=True)
    batch_id = Column(String(64), nullable=False, index=True)
    sample_date = Column(DateTime(timezone=True), nullable=False, index=True)
    doc = Column(Integer, nullable=False)
    sample_count = Column(Integer, nullable=False, default=50)
    abw_g = Column(Float, nullable=False)
    measurement_type = Column(String(32), nullable=False, default="MEASURED")  # MEASURED, ESTIMATED, MANUAL_ENTRY
    sampling_method = Column(String(64), nullable=False, default="Cast net")
    observations = Column(Text, nullable=True)
    estimated_survival_pct = Column(Float, nullable=True)
    estimated_biomass_kg = Column(Float, nullable=False)
    is_biomass_estimated = Column(Boolean, nullable=False, default=True)
    adg_g_per_day = Column(Float, nullable=True)
    recorded_by = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class FeedingLogORM(Base):
    """Manual feeding records, ration weights, and feeding tray consumption observations."""

    __tablename__ = "feeding_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    farm_id = Column(String(64), nullable=False, index=True)
    pond_id = Column(String(64), nullable=False, index=True)
    batch_id = Column(String(64), nullable=True, index=True)
    timestamp = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    feed_type = Column(String(64), nullable=False, default="Starter Crumble #1")
    feed_kg = Column(Float, nullable=False)
    feeding_event_count = Column(Integer, nullable=False, default=1)
    feed_time_label = Column(String(64), nullable=False, default="06:00 Morning")
    tray_observation = Column(String(64), nullable=False, default="100% Consumed")
    notes = Column(Text, nullable=True)
    recorded_by = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class MortalityRecordORM(Base):
    """Pond and batch-specific shrimp mortality collection records."""

    __tablename__ = "mortality_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    mortality_id = Column(String(64), nullable=False, unique=True, index=True)
    farm_id = Column(String(64), nullable=False, index=True)
    pond_id = Column(String(64), nullable=False, index=True)
    batch_id = Column(String(64), nullable=False, index=True)
    timestamp = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    doc = Column(Integer, nullable=False)
    dead_count = Column(Integer, nullable=False)
    collection_method = Column(String(64), nullable=False, default="Central drain siphon")
    suspected_reason = Column(String(128), nullable=False, default="Unknown")
    notes = Column(Text, nullable=True)
    recorded_by = Column(String(64), nullable=False)
    is_corrected = Column(Boolean, nullable=False, default=False)
    correction_notes = Column(Text, nullable=True)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class HealthObservationORM(Base):
    """Physical, swimming, behavioral, and clinical shrimp health observations."""

    __tablename__ = "health_observations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    observation_id = Column(String(64), nullable=False, unique=True, index=True)
    farm_id = Column(String(64), nullable=False, index=True)
    pond_id = Column(String(64), nullable=False, index=True)
    batch_id = Column(String(64), nullable=False, index=True)
    timestamp = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    doc = Column(Integer, nullable=False)
    sample_count = Column(Integer, nullable=False, default=20)
    observation_method = Column(String(64), nullable=False, default="Feeding tray inspection")
    swimming_activity = Column(String(64), nullable=False, default="NORMAL")
    feed_response = Column(String(64), nullable=False, default="NORMAL")
    shell_body_condition = Column(String(64), nullable=False, default="NORMAL_CLEAN")
    gill_condition = Column(String(64), nullable=False, default="CLEAN_TRANSLUCENT")
    gut_condition = Column(String(64), nullable=False, default="FULL_CONTINUOUS")
    coloration = Column(String(64), nullable=False, default="NORMAL_TRANSLUCENT")
    visible_lesions = Column(String(64), nullable=False, default="NONE")
    severity = Column(String(32), nullable=False, default="NORMAL")  # NORMAL, MILD, MODERATE, SEVERE
    water_quality_context_json = Column(Text, nullable=True)
    photo_reference_url = Column(String(256), nullable=True)
    notes = Column(Text, nullable=True)
    recorded_by = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class TreatmentRecordORM(Base):
    """Pond chemical, mineral, probiotic, and water treatment records with withdrawal tracking."""

    __tablename__ = "treatment_records"

    id = Column(Integer, primary_key=True, autoincrement=True)
    treatment_id = Column(String(64), nullable=False, unique=True, index=True)
    farm_id = Column(String(64), nullable=False, index=True)
    pond_id = Column(String(64), nullable=False, index=True)
    batch_id = Column(String(64), nullable=False, index=True)
    timestamp = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    doc = Column(Integer, nullable=False)
    product_name = Column(String(128), nullable=False)
    active_ingredient = Column(String(128), nullable=True)
    reason_for_treatment = Column(String(128), nullable=False)
    dosage_amount = Column(Float, nullable=False)
    dosage_unit = Column(String(32), nullable=False, default="kg/ha")
    withdrawal_period_days = Column(Integer, nullable=False, default=0)
    harvest_restriction_until = Column(DateTime(timezone=True), nullable=True)
    product_label_info = Column(Text, nullable=True)
    has_missing_label_info = Column(Boolean, nullable=False, default=False)
    notes = Column(Text, nullable=True)
    recorded_by = Column(String(64), nullable=False)
    created_at = Column(DateTime(timezone=True), default=lambda: datetime.now(timezone.utc))


class WaterPumpORM(Base):
    """Farm-level water intake / supply pump unit."""

    __tablename__ = "farm_pumps"

    pump_id = Column(String(64), primary_key=True, nullable=False)
    farm_id = Column(String(64), nullable=False, index=True)
    name = Column(String(128), nullable=False, default="River Intake Pump House")
    motor_hp = Column(Float, nullable=True, default=None)
    rating_kw = Column(Float, nullable=True, default=None)
    transformer_id = Column(String(32), nullable=True, default=None)
    desired_state = Column(String(32), nullable=False, default="OFF")
    physical_state = Column(String(32), nullable=False, default="OFF")
    current_draw_amps = Column(Float, nullable=False, default=0.0)
    power_kw = Column(Float, nullable=False, default=0.0)
    last_run_timestamp = Column(DateTime(timezone=True), nullable=True)
    updated_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        onupdate=lambda: datetime.now(timezone.utc),
    )


class WaterExchangeLogORM(Base):
    """Pond water exchange, leveling, and drainage operation audit logs."""

    __tablename__ = "water_exchange_logs"

    id = Column(Integer, primary_key=True, autoincrement=True)
    exchange_id = Column(String(64), nullable=False, unique=True, index=True)
    farm_id = Column(String(64), nullable=False, index=True)
    pond_id = Column(String(64), nullable=False, index=True)
    mode = Column(String(32), nullable=False)  # WaterManagementMode
    initial_level_m = Column(Float, nullable=False)
    final_level_m = Column(Float, nullable=True)
    started_at = Column(
        DateTime(timezone=True),
        default=lambda: datetime.now(timezone.utc),
        index=True,
    )
    completed_at = Column(DateTime(timezone=True), nullable=True)
    operator_id = Column(String(64), nullable=False)
    notes = Column(Text, nullable=True)



