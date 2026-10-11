"""Configuration-driven models for farm, ponds, and biological thresholds.

Aqua OS uses configuration objects rather than hardcoded pond limits.
This allows seamless scaling from 20 ponds to hundreds of ponds across farms.
"""

from typing import Dict, List, Optional

from pydantic import BaseModel, Field, model_validator


class BiologicalThresholds(BaseModel):
    """Operational water quality parameters for shrimp cultivation (Litopenaeus vannamei).

    NOTE: These thresholds represent provisional baseline parameters derived from
    commercial Litopenaeus vannamei standards. They remain fully configurable and
    must be calibrated to actual farm salinity, stocking density, and diurnal curves.
    """

    do_emergency_mg_l: float = Field(
        3.0,
        ge=0.0,
        le=15.0,
        description="Immediate hypoxia danger - triggers emergency alert (provisional)",
    )
    do_warning_mg_l: float = Field(
        4.0,
        ge=0.0,
        le=15.0,
        description="Sub-optimal dissolved oxygen - warning threshold (provisional)",
    )
    do_target_min_mg_l: float = Field(
        5.0,
        ge=0.0,
        le=15.0,
        description="Healthy baseline minimum DO during feeding hours (provisional)",
    )
    ph_min: float = Field(7.5, ge=0.0, le=14.0, description="Minimum acceptable pH")
    ph_max: float = Field(8.5, ge=0.0, le=14.0, description="Maximum acceptable pH")
    temp_min_c: float = Field(26.0, ge=0.0, le=50.0, description="Minimum optimal temperature °C")
    temp_max_c: float = Field(32.0, ge=0.0, le=50.0, description="Maximum optimal temperature °C")
    salinity_min_ppt: float = Field(10.0, ge=0.0, le=60.0, description="Minimum salinity in ppt")
    salinity_max_ppt: float = Field(35.0, ge=0.0, le=60.0, description="Maximum salinity in ppt")

    # Aeration decision thresholds (provisional, unvalidated configuration)
    aeration_on_threshold_mg_l: float = Field(
        4.5,
        ge=0.0,
        le=15.0,
        description="DO trigger to propose starting aerators (provisional)",
    )
    aeration_off_threshold_mg_l: float = Field(
        5.8,
        ge=0.0,
        le=15.0,
        description="DO trigger to propose stopping aerators (provisional)",
    )
    min_runtime_minutes: int = Field(
        30,
        ge=5,
        le=240,
        description="Anti-cycling hysteresis: minimum run duration before stopping",
    )
    min_offtime_minutes: int = Field(
        15,
        ge=5,
        le=240,
        description="Anti-cycling hysteresis: minimum rest duration before restarting",
    )
    stale_sensor_timeout_seconds: int = Field(
        120,
        ge=30,
        le=3600,
        description="Threshold after which sensor reading is considered stale",
    )

    @model_validator(mode="after")
    def validate_threshold_relationships(self) -> "BiologicalThresholds":
        if self.do_emergency_mg_l >= self.do_warning_mg_l:
            raise ValueError(
                f"do_emergency_mg_l ({self.do_emergency_mg_l}) must be strictly less than "
                f"do_warning_mg_l ({self.do_warning_mg_l})."
            )
        if self.do_warning_mg_l > self.do_target_min_mg_l:
            raise ValueError(
                f"do_warning_mg_l ({self.do_warning_mg_l}) must be <= "
                f"do_target_min_mg_l ({self.do_target_min_mg_l})."
            )
        if self.ph_min >= self.ph_max:
            raise ValueError(
                f"ph_min ({self.ph_min}) must be strictly less than ph_max ({self.ph_max})."
            )
        if self.temp_min_c >= self.temp_max_c:
            raise ValueError(
                f"temp_min_c ({self.temp_min_c}) must be strictly less than "
                f"temp_max_c ({self.temp_max_c})."
            )
        if self.salinity_min_ppt >= self.salinity_max_ppt:
            raise ValueError(
                f"salinity_min_ppt ({self.salinity_min_ppt}) must be strictly less than "
                f"salinity_max_ppt ({self.salinity_max_ppt})."
            )
        return self


class TransformerConfig(BaseModel):
    """Utility electrical distribution transformer parameters."""

    transformer_id: str = Field(..., description="Unique transformer identifier (e.g. tx-1)")
    name: str = Field(..., description="Transformer label / feeder description")
    capacity_kw: float = Field(23.0, ge=1.0, le=500.0, description="Dedicated capacity in kW")
    dedicated: bool = Field(True, description="Whether transformer is dedicated to farm operations")
    max_continuous_load_pct: float = Field(
        80.0, ge=10.0, le=100.0, description="Safe continuous load rating %"
    )


class PondConfig(BaseModel):
    """Configuration definition for a single operational pond."""

    farm_id: str = Field(
        "farm-alpha",
        min_length=2,
        max_length=64,
        description="Owning farm identifier",
    )
    pond_id: str = Field(..., min_length=2, max_length=64, description="Unique pond identifier")
    name: str = Field(..., description="Human-readable pond name")
    area_acres: float = Field(
        0.75, ge=0.01, le=25.0, description="Allocated pond surface area in acres"
    )
    area_hectares: float = Field(0.3035, ge=0.01, le=10.0, description="Pond surface area")
    depth_feet: float = Field(4.0, ge=1.0, le=15.0, description="Operating water depth in feet")
    depth_meters: float = Field(1.2192, ge=0.3, le=4.0, description="Operating water depth")
    species: str = Field("Litopenaeus vannamei", description="Cultured species")
    stocking_count: int = Field(
        150_000, ge=1000, le=1_000_000, description="Initial post-larvae stocked count"
    )
    stocking_density_per_m2: int = Field(49, ge=1, le=250)
    days_of_culture: int = Field(0, ge=0, le=180, description="DOC from stocking date")
    is_active: bool = Field(True, description="Whether pond is currently stocked and monitored")
    aerator_count: int = Field(4, ge=0, le=20, description="Installed mechanical aerators")
    feeder_count: int = Field(0, ge=0, le=10, description="Installed automated feeders (0=manual)")
    transformer_id: str = Field("tx-1", description="Assigned electrical transformer feeder")
    thresholds: BiologicalThresholds = Field(default_factory=BiologicalThresholds)


class FarmConfig(BaseModel):
    """Farm-level configuration managing N ponds."""

    farm_id: str = Field("aqua-farm-alpha", description="Farm identifier")
    name: str = Field("Aqua OS Primary Farm", description="Human-readable farm name")
    location: str = Field("Coastal Aquaculture Zone", description="Geographic location")
    total_area_acres: float = Field(6.0, ge=0.1, le=1000.0, description="Total farm land in acres")
    telemetry_interval_seconds: int = Field(
        10,
        ge=1,
        le=300,
        description="Default edge sensor reporting interval",
    )
    transformers: List[TransformerConfig] = Field(
        default_factory=lambda: [
            TransformerConfig(
                transformer_id="tx-1", name="Transformer 1 (North)", capacity_kw=23.0
            ),
            TransformerConfig(
                transformer_id="tx-2", name="Transformer 2 (South)", capacity_kw=23.0
            ),
        ],
        description="Installed utility transformers",
    )
    ponds: Dict[str, PondConfig] = Field(
        default_factory=dict,
        description="Mapping of pond_id to PondConfig",
    )

    def get_pond(self, pond_id: str) -> Optional[PondConfig]:
        return self.ponds.get(pond_id)

    def add_or_update_pond(self, pond: PondConfig) -> None:
        self.ponds[pond.pond_id] = pond

    def active_pond_count(self) -> int:
        return sum(1 for p in self.ponds.values() if p.is_active)

    def total_transformer_capacity_kw(self) -> float:
        return sum(tx.capacity_kw for tx in self.transformers)


def get_farm_6acre_8pond_config(farm_id: str = "farm-alpha") -> FarmConfig:
    """Factory creating our 6-acre commercial farm layout with 8 ponds.

    - Total Farm Area: ~6 acres
    - Pond count: 8 ponds (~0.75 acre allocated per pond = ~0.3035 hectares)
    - Initial water depth: 4 feet (~1.22 meters)
    - Initial stocking: 150,000 post-larvae (PL) per pond = 1,200,000 PL total
    - Manual feeding: feeder_count = 0
    - Electrical supply: 2 transformers with 23 kW dedicated capacity each (total 46 kW)
    """
    farm = FarmConfig(
        farm_id=farm_id,
        name="Aqua OS Commercial Farm (6-Acre)",
        total_area_acres=6.0,
        location="Coastal Aquaculture Zone",
        telemetry_interval_seconds=10,
        transformers=[
            TransformerConfig(
                transformer_id="tx-1",
                name="Transformer 1 (North Grid)",
                capacity_kw=23.0,
                dedicated=True,
            ),
            TransformerConfig(
                transformer_id="tx-2",
                name="Transformer 2 (South Grid)",
                capacity_kw=23.0,
                dedicated=True,
            ),
        ],
    )
    for i in range(1, 9):
        pond_id = f"pond-{i:02d}"
        tx_id = "tx-1" if i <= 4 else "tx-2"
        farm.add_or_update_pond(
            PondConfig(
                farm_id=farm_id,
                pond_id=pond_id,
                name=f"Pond {i:02d}",
                area_acres=0.75,
                area_hectares=round(0.75 * 0.404686, 4),  # ~0.3035 ha
                depth_feet=4.0,
                depth_meters=round(4.0 * 0.3048, 4),      # ~1.2192 m
                species="Litopenaeus vannamei",
                stocking_count=150_000,
                stocking_density_per_m2=int(150_000 / (0.75 * 4046.86)),  # ~49 PL/m2
                days_of_culture=1,
                is_active=True,
                aerator_count=4,
                feeder_count=0,  # Manual feeding managed
                transformer_id=tx_id,
                thresholds=BiologicalThresholds(),
            )
        )
    return farm


def get_default_20_pond_farm_config(farm_id: str = "farm-alpha") -> FarmConfig:
    """Factory creating our baseline 20-pond operational configuration.

    Ponds 1 through 20 are initialized with standard dimensions,
    water quality thresholds, and 4 aerators each.
    """
    farm = FarmConfig(
        farm_id=farm_id,
        name="Aqua OS Core Farm",
        telemetry_interval_seconds=10,
    )
    for i in range(1, 21):
        pond_id = f"pond-{i:02d}"
        farm.add_or_update_pond(
            PondConfig(
                farm_id=farm_id,
                pond_id=pond_id,
                name=f"Pond {i:02d}",
                area_hectares=0.5,
                depth_meters=1.2,
                species="Litopenaeus vannamei",
                stocking_density_per_m2=60,
                days_of_culture=30,
                is_active=True,
                aerator_count=4,
                feeder_count=1,
                thresholds=BiologicalThresholds(),
            )
        )
    return farm
