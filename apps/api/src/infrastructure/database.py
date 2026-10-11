"""Database engine and session management for Aqua OS."""

from typing import Generator

from sqlalchemy import create_engine
from sqlalchemy.orm import Session, declarative_base, sessionmaker

from apps.api.src.config import settings

# Base class for SQLAlchemy ORM models
Base = declarative_base()


def get_engine_args(db_url: str) -> dict:
    """Return dialect-specific engine parameters."""
    args = {}
    if db_url.startswith("sqlite"):
        args["connect_args"] = {"check_same_thread": False}
    else:
        # PostgreSQL pool sizing suitable for 20 ponds up to 1,000 ponds
        args["pool_size"] = 10
        args["max_overflow"] = 20
        args["pool_pre_ping"] = True
    return args


# Global engine and sessionmaker
engine = create_engine(settings.database_url, **get_engine_args(settings.database_url))
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)


def get_db() -> Generator[Session, None, None]:
    """FastAPI dependency yielding a scoped database session."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()


def _ensure_table_columns(eng) -> None:
    """Idempotently add new columns to existing SQLite tables if not present."""
    from sqlalchemy import text

    # 1. Stocking batches columns
    try:
        with eng.begin() as conn:
            res = conn.execute(text("PRAGMA table_info(stocking_batches)")).fetchall()
            if res:
                existing_cols = {row[1] for row in res}
                cols_to_add = [
                    ("initial_pl_weight_g", "FLOAT DEFAULT 0.05"),
                    ("initial_biomass_kg", "FLOAT DEFAULT 7.5"),
                    ("seed_supplier", "VARCHAR(128)"),
                    ("seed_quality_notes", "TEXT"),
                    ("target_abw_g", "FLOAT DEFAULT 25.0"),
                    ("target_harvest_date", "TIMESTAMP"),
                    ("target_harvest_biomass_kg", "FLOAT"),
                    ("projected_sale_price_per_kg", "FLOAT DEFAULT 5.50"),
                    ("harvested_date", "TIMESTAMP"),
                    ("harvested_biomass_kg", "FLOAT"),
                    ("harvest_notes", "TEXT"),
                    ("cumulative_recorded_mortality", "INTEGER DEFAULT 0"),
                ]
                for col_name, col_type in cols_to_add:
                    if col_name not in existing_cols:
                        conn.execute(text(f"ALTER TABLE stocking_batches ADD COLUMN {col_name} {col_type}"))
    except Exception:
        pass

    # 2. Feeding logs
    try:
        with eng.begin() as conn:
            res_feed = conn.execute(text("PRAGMA table_info(feeding_logs)")).fetchall()
            if res_feed:
                existing_feed_cols = {row[1] for row in res_feed}
                feed_cols_to_add = [
                    ("batch_id", "VARCHAR(64)"),
                    ("feeding_event_count", "INTEGER DEFAULT 1"),
                    ("created_at", "TIMESTAMP"),
                    ("updated_at", "TIMESTAMP"),
                ]
                for col_name, col_type in feed_cols_to_add:
                    if col_name not in existing_feed_cols:
                        conn.execute(text(f"ALTER TABLE feeding_logs ADD COLUMN {col_name} {col_type}"))
    except Exception:
        pass

    # 3. Ponds table columns
    try:
        with eng.begin() as conn:
            res_ponds = conn.execute(text("PRAGMA table_info(ponds)")).fetchall()
            if res_ponds:
                existing_pond_cols = {row[1] for row in res_ponds}
                pond_cols_to_add = [
                    ("area_acres", "FLOAT DEFAULT 0.75"),
                    ("depth_feet", "FLOAT DEFAULT 4.0"),
                    ("stocking_count", "INTEGER DEFAULT 150000"),
                    ("transformer_id", "VARCHAR(32) DEFAULT 'tx-1'"),
                    ("water_level_target_m", "FLOAT DEFAULT 1.22"),
                    ("water_level_min_m", "FLOAT DEFAULT 0.95"),
                    ("water_level_max_m", "FLOAT DEFAULT 1.40"),
                    ("normal_outlet_state", "VARCHAR(32) DEFAULT 'CLOSED'"),
                    ("full_drain_outlet_state", "VARCHAR(32) DEFAULT 'CLOSED'"),
                    ("full_drain_locked", "BOOLEAN DEFAULT 1"),
                    ("drain_lock_reason", "VARCHAR(128) DEFAULT 'Active batch biological containment'"),
                ]
                for col_name, col_type in pond_cols_to_add:
                    if col_name not in existing_pond_cols:
                        conn.execute(text(f"ALTER TABLE ponds ADD COLUMN {col_name} {col_type}"))
    except Exception:
        pass

    # 4. Sensors table columns
    try:
        with eng.begin() as conn:
            res_sensors = conn.execute(text("PRAGMA table_info(sensors)")).fetchall()
            if res_sensors:
                existing_sensor_cols = {row[1] for row in res_sensors}
                sensor_cols_to_add = [
                    ("register_map_json", "TEXT"),
                    ("has_integrated_temp", "BOOLEAN DEFAULT 0"),
                    ("calibration_offset", "FLOAT DEFAULT 0.0"),
                    ("calibration_slope", "FLOAT DEFAULT 1.0"),
                    ("is_active", "BOOLEAN DEFAULT 1"),
                ]
                for col_name, col_type in sensor_cols_to_add:
                    if col_name not in existing_sensor_cols:
                        conn.execute(text(f"ALTER TABLE sensors ADD COLUMN {col_name} {col_type}"))
    except Exception:
        pass

    # 5. Farm pumps: Ensure columns are nullable so unconfigured state is supported
    try:
        with eng.begin() as conn:
            pump_cols = conn.execute(text("PRAGMA table_info(farm_pumps)")).fetchall()
            is_motor_hp_notnull = any(row[1] == "motor_hp" and row[3] == 1 for row in pump_cols)
            if is_motor_hp_notnull:
                conn.execute(text("""
                    CREATE TABLE farm_pumps_migration (
                        pump_id VARCHAR(64) PRIMARY KEY,
                        farm_id VARCHAR(64) NOT NULL,
                        name VARCHAR(128) NOT NULL DEFAULT 'River Intake Pump House',
                        motor_hp FLOAT,
                        rating_kw FLOAT,
                        transformer_id VARCHAR(32),
                        desired_state VARCHAR(32) NOT NULL DEFAULT 'OFF',
                        physical_state VARCHAR(32) NOT NULL DEFAULT 'OFF',
                        current_draw_amps FLOAT NOT NULL DEFAULT 0.0,
                        power_kw FLOAT NOT NULL DEFAULT 0.0,
                        last_run_timestamp TIMESTAMP,
                        updated_at TIMESTAMP
                    )
                """))
                conn.execute(text("""
                    INSERT INTO farm_pumps_migration (pump_id, farm_id, name, desired_state, physical_state, current_draw_amps, power_kw, last_run_timestamp, updated_at)
                    SELECT pump_id, farm_id, name, desired_state, physical_state, current_draw_amps, power_kw, last_run_timestamp, updated_at FROM farm_pumps
                """))
                conn.execute(text("DROP TABLE farm_pumps"))
                conn.execute(text("ALTER TABLE farm_pumps_migration RENAME TO farm_pumps"))
                conn.execute(text("CREATE INDEX IF NOT EXISTS idx_farm_pumps_farm ON farm_pumps(farm_id)"))
            else:
                conn.execute(text("UPDATE farm_pumps SET motor_hp = NULL, rating_kw = NULL, transformer_id = NULL WHERE pump_id = 'pump-river-intake-01' AND (rating_kw = 7.5 OR motor_hp = 10.0)"))
    except Exception:
        pass

    # 6. Ensure aerator_runtime_logs table exists
    try:
        with eng.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS aerator_runtime_logs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    log_id VARCHAR(64) NOT NULL UNIQUE,
                    farm_id VARCHAR(64) NOT NULL,
                    pond_id VARCHAR(64) NOT NULL,
                    aerator_id VARCHAR(64) NOT NULL,
                    start_time TIMESTAMP NOT NULL,
                    end_time TIMESTAMP,
                    duration_minutes FLOAT NOT NULL DEFAULT 0.0,
                    energy_kwh FLOAT NOT NULL DEFAULT 0.0,
                    trigger_reason VARCHAR(256) NOT NULL DEFAULT 'Automated DO Advisory',
                    is_simulated BOOLEAN NOT NULL DEFAULT 1,
                    created_at TIMESTAMP
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_aerator_runtime_pond ON aerator_runtime_logs(pond_id, start_time)"))
    except Exception:
        pass


def init_db(target_engine=None) -> None:
    """Initialize database tables and default data."""
    eng = target_engine or engine
    import apps.api.src.infrastructure.models  # noqa: F401 - ensure all ORM models are registered
    Base.metadata.create_all(bind=eng)
    _ensure_table_columns(eng)


def seed_default_ponds_if_empty(session: Session, farm_id: str = "farm-alpha") -> int:
    """Seed the baseline 20 ponds if the ponds table has no entries for this farm.

    Guarantees that on clean startup the farm operates with 20 ponds,
    and subsequent changes survive restarts.
    """
    from apps.api.src.infrastructure.models import PondORM
    from packages.telemetry_schema.config import get_default_20_pond_farm_config

    existing_count = session.query(PondORM).filter(PondORM.farm_id == farm_id).count()
    if existing_count > 0:
        return existing_count

    default_farm = get_default_20_pond_farm_config(farm_id=farm_id)
    seeded_count = 0
    for pond in default_farm.ponds.values():
        orm_pond = PondORM.from_domain(pond)
        session.add(orm_pond)
        seeded_count += 1
    session.commit()
    seed_default_hardware_if_empty(session, farm_id=farm_id)
    return seeded_count


def seed_default_hardware_if_empty(session: Session, farm_id: str = "farm-alpha") -> None:
    """Seed sensor registry, aerators, and stocking batch records for ponds."""
    from apps.api.src.infrastructure.models import PondORM
    from apps.api.src.infrastructure.repositories.sql_sensor_repository import SQLSensorRepository
    from apps.api.src.infrastructure.repositories.sql_aerator_repository import SQLAeratorRepository
    from apps.api.src.infrastructure.repositories.sql_pond_records_repository import SQLPondRecordsRepository

    sensor_repo = SQLSensorRepository(session)
    aerator_repo = SQLAeratorRepository(session)
    records_repo = SQLPondRecordsRepository(session)

    ponds = session.query(PondORM).filter(PondORM.farm_id == farm_id).all()
    for p in ponds:
        sensor_repo.seed_defaults_for_pond(farm_id, p.pond_id)
        aerator_repo.seed_defaults_for_pond(
            p.pond_id,
            transformer_id=getattr(p, "transformer_id", "tx-1") or "tx-1",
            count=p.aerator_count or 2,
        )
        records_repo.seed_default_stocking_for_pond(
            farm_id,
            p.pond_id,
            initial_count=getattr(p, "stocking_count", 150_000) or 150_000,
            doc=p.days_of_culture or 35,
        )

    # Seed River Intake Pump House if absent
    from apps.api.src.infrastructure.models import WaterPumpORM
    existing_pump = session.query(WaterPumpORM).filter(WaterPumpORM.farm_id == farm_id).first()
    if not existing_pump:
        session.add(
            WaterPumpORM(
                pump_id="pump-river-intake-01",
                farm_id=farm_id,
                name="River Intake Pump House",
                motor_hp=None,
                rating_kw=None,
                transformer_id=None,
                desired_state="OFF",
                physical_state="OFF",
                current_draw_amps=0.0,
                power_kw=0.0,
            )
        )
        session.commit()
    elif existing_pump.rating_kw in (7.5, 18.5) and existing_pump.motor_hp in (10.0, 25.0):
        # Reset legacy unverified ratings to unconfigured state
        existing_pump.motor_hp = None
        existing_pump.rating_kw = None
        existing_pump.transformer_id = None
        session.commit()


def seed_default_users_if_empty(session: Session) -> int:
    """Seed default local development accounts if users table is empty."""
    from apps.api.src.infrastructure.models import UserORM
    from apps.api.src.security.password import hash_password

    if session.query(UserORM).count() > 0:
        return 0

    default_users = [
        UserORM(
            user_id="usr-admin",
            username="admin",
            password_hash=hash_password("admin_secret_123"),
            farm_id="farm-alpha",
            role="system_admin",
            is_active=True,
        ),
        UserORM(
            user_id="usr-operator",
            username="operator",
            password_hash=hash_password("operator_secret_123"),
            farm_id="farm-alpha",
            role="operator",
            is_active=True,
        ),
        UserORM(
            user_id="usr-viewer",
            username="viewer",
            password_hash=hash_password("viewer_secret_123"),
            farm_id="farm-alpha",
            role="viewer",
            is_active=True,
        ),
        UserORM(
            user_id="usr-beta-op",
            username="beta_operator",
            password_hash=hash_password("beta_secret_123"),
            farm_id="farm-beta",
            role="operator",
            is_active=True,
        ),
    ]

    for u in default_users:
        session.add(u)
    session.commit()
    return len(default_users)
