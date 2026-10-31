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
                    ("product_id", "VARCHAR(64)"),
                    ("plan_id", "VARCHAR(64)"),
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
                    ("manufacturer", "VARCHAR(64) DEFAULT 'AquaSensors Ltd'"),
                    ("model", "VARCHAR(64) DEFAULT 'AQ-PROBE-485'"),
                    ("serial_number", "VARCHAR(64)"),
                    ("calibration_expiry", "TIMESTAMP"),
                    ("health_status", "VARCHAR(32) DEFAULT 'HEALTHY'"),
                    ("battery_level_pct", "FLOAT DEFAULT 100.0"),
                    ("last_communication_at", "TIMESTAMP"),
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

    # 7. Ensure feed inventory tables exist
    try:
        with eng.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS feed_products (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    product_id VARCHAR(64) NOT NULL UNIQUE,
                    farm_id VARCHAR(64) NOT NULL,
                    product_name VARCHAR(128) NOT NULL,
                    brand VARCHAR(128),
                    feed_type VARCHAR(64),
                    pellet_size VARCHAR(64),
                    unit_of_measure VARCHAR(32) NOT NULL DEFAULT 'kg',
                    reorder_threshold_kg FLOAT NOT NULL DEFAULT 100.0,
                    is_active BOOLEAN NOT NULL DEFAULT 1,
                    notes TEXT,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_feed_products_farm ON feed_products(farm_id)"))

            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS feed_inventory_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transaction_id VARCHAR(64) NOT NULL UNIQUE,
                    farm_id VARCHAR(64) NOT NULL,
                    product_id VARCHAR(64) NOT NULL,
                    transaction_type VARCHAR(32) NOT NULL,
                    quantity_kg FLOAT NOT NULL,
                    unit_of_measure VARCHAR(32) NOT NULL DEFAULT 'kg',
                    unit_price FLOAT,
                    total_cost FLOAT,
                    supplier VARCHAR(128),
                    invoice_number VARCHAR(64),
                    feeding_log_id INTEGER,
                    pond_id VARCHAR(64),
                    batch_id VARCHAR(64),
                    reason TEXT,
                    notes TEXT,
                    idempotency_key VARCHAR(128) UNIQUE,
                    recorded_by VARCHAR(64) NOT NULL,
                    timestamp TIMESTAMP,
                    created_at TIMESTAMP
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_feed_tx_farm_product ON feed_inventory_transactions(farm_id, product_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_feed_tx_feeding_log ON feed_inventory_transactions(feeding_log_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_feed_tx_idempotency ON feed_inventory_transactions(idempotency_key)"))
    except Exception:
        pass

    # 8. Ensure feed_plans table exists
    try:
        with eng.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS feed_plans (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    plan_id VARCHAR(64) NOT NULL UNIQUE,
                    farm_id VARCHAR(64) NOT NULL,
                    pond_id VARCHAR(64) NOT NULL,
                    batch_id VARCHAR(64) NOT NULL,
                    plan_date TIMESTAMP NOT NULL,
                    product_id VARCHAR(64),
                    feed_type VARCHAR(128) NOT NULL DEFAULT 'Grower Pellet 38%',
                    planned_daily_kg FLOAT NOT NULL,
                    feeding_sessions_count INTEGER NOT NULL DEFAULT 4,
                    session_times_json TEXT,
                    planned_kg_per_session FLOAT NOT NULL,
                    status VARCHAR(32) NOT NULL DEFAULT 'DRAFT',
                    recommendation_basis VARCHAR(64) NOT NULL DEFAULT 'MANUAL',
                    ration_inputs_json TEXT,
                    notes TEXT,
                    created_by VARCHAR(64) NOT NULL,
                    approved_by VARCHAR(64),
                    approved_at TIMESTAMP,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_feed_plans_farm_date ON feed_plans(farm_id, plan_date)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_feed_plans_pond_date ON feed_plans(pond_id, plan_date)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_feed_plans_batch ON feed_plans(batch_id)"))
    except Exception:
        pass

    # 9. Ensure harvest_records table exists
    try:
        with eng.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS harvest_records (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    harvest_id VARCHAR(64) NOT NULL UNIQUE,
                    farm_id VARCHAR(64) NOT NULL,
                    pond_id VARCHAR(64) NOT NULL,
                    batch_id VARCHAR(64) NOT NULL,
                    harvest_type VARCHAR(32) NOT NULL DEFAULT 'FINAL',
                    harvest_date TIMESTAMP NOT NULL,
                    harvested_weight_kg FLOAT NOT NULL,
                    count_pieces INTEGER,
                    count_per_kg FLOAT,
                    avg_body_weight_g FLOAT,
                    grade VARCHAR(64),
                    selling_price_per_kg FLOAT,
                    total_revenue FLOAT,
                    documented_losses_kg FLOAT NOT NULL DEFAULT 0.0,
                    buyer VARCHAR(128),
                    notes TEXT,
                    idempotency_key VARCHAR(128) UNIQUE,
                    recorded_by VARCHAR(64) NOT NULL,
                    created_at TIMESTAMP
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_harvest_records_farm_date ON harvest_records(farm_id, harvest_date)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_harvest_records_pond ON harvest_records(pond_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_harvest_records_batch ON harvest_records(batch_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_harvest_records_idempotency ON harvest_records(idempotency_key)"))
    except Exception:
        pass

    # 10. Ensure farm_expenses table exists
    try:
        with eng.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS farm_expenses (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    expense_id VARCHAR(64) NOT NULL UNIQUE,
                    farm_id VARCHAR(64) NOT NULL,
                    pond_id VARCHAR(64),
                    batch_id VARCHAR(64),
                    category VARCHAR(64) NOT NULL,
                    amount FLOAT NOT NULL,
                    currency VARCHAR(16) NOT NULL DEFAULT 'USD',
                    transaction_date TIMESTAMP NOT NULL,
                    supplier VARCHAR(128),
                    invoice_number VARCHAR(64),
                    payment_method VARCHAR(64),
                    idempotency_key VARCHAR(128) UNIQUE,
                    status VARCHAR(32) NOT NULL DEFAULT 'ACTIVE',
                    correction_type VARCHAR(32) NOT NULL DEFAULT 'ORIGINAL',
                    corrected_expense_id VARCHAR(64),
                    correction_reason TEXT,
                    notes TEXT,
                    recorded_by VARCHAR(64) NOT NULL,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_farm_expenses_farm_date ON farm_expenses(farm_id, transaction_date)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_farm_expenses_pond ON farm_expenses(pond_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_farm_expenses_batch ON farm_expenses(batch_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_farm_expenses_category ON farm_expenses(category)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_farm_expenses_idempotency ON farm_expenses(idempotency_key)"))
    except Exception:
        pass

    # 11. Ensure farm_cash_transactions table exists
    try:
        with eng.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS farm_cash_transactions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    transaction_id VARCHAR(64) NOT NULL UNIQUE,
                    farm_id VARCHAR(64) NOT NULL,
                    entry_type VARCHAR(32) NOT NULL,
                    category VARCHAR(64) NOT NULL,
                    amount FLOAT NOT NULL,
                    currency VARCHAR(16) NOT NULL DEFAULT 'USD',
                    payment_date TIMESTAMP NOT NULL,
                    payment_method VARCHAR(64) NOT NULL DEFAULT 'BANK_TRANSFER',
                    reference_number VARCHAR(64),
                    payer_payee VARCHAR(128),
                    expense_id VARCHAR(64),
                    harvest_id VARCHAR(64),
                    batch_id VARCHAR(64),
                    pond_id VARCHAR(64),
                    idempotency_key VARCHAR(128) UNIQUE,
                    status VARCHAR(32) NOT NULL DEFAULT 'COMPLETED',
                    void_reason TEXT,
                    notes TEXT,
                    recorded_by VARCHAR(64) NOT NULL,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cash_tx_farm_date ON farm_cash_transactions(farm_id, payment_date)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cash_tx_entry_type ON farm_cash_transactions(entry_type)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cash_tx_expense ON farm_cash_transactions(expense_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cash_tx_harvest ON farm_cash_transactions(harvest_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cash_tx_batch ON farm_cash_transactions(batch_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_cash_tx_idempotency ON farm_cash_transactions(idempotency_key)"))
    except Exception:
        pass

    # 12. Ensure crop_cycle_budgets table exists
    try:
        with eng.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS crop_cycle_budgets (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    budget_id VARCHAR(64) NOT NULL UNIQUE,
                    farm_id VARCHAR(64) NOT NULL,
                    batch_id VARCHAR(64),
                    pond_id VARCHAR(64),
                    cycle_label VARCHAR(64),
                    category VARCHAR(64) NOT NULL,
                    budgeted_amount FLOAT NOT NULL,
                    currency VARCHAR(16) NOT NULL DEFAULT 'USD',
                    notes TEXT,
                    created_by VARCHAR(64) NOT NULL,
                    created_at TIMESTAMP,
                    updated_at TIMESTAMP
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_budgets_farm ON crop_cycle_budgets(farm_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_budgets_batch ON crop_cycle_budgets(batch_id)"))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_budgets_category ON crop_cycle_budgets(category)"))
    except Exception:
        pass

    # 13. Ensure cash_balance_snapshots table exists
    try:
        with eng.begin() as conn:
            conn.execute(text("""
                CREATE TABLE IF NOT EXISTS cash_balance_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    snapshot_id VARCHAR(64) NOT NULL UNIQUE,
                    farm_id VARCHAR(64) NOT NULL,
                    balance_date TIMESTAMP NOT NULL,
                    opening_balance FLOAT NOT NULL,
                    closing_balance FLOAT,
                    currency VARCHAR(16) NOT NULL DEFAULT 'USD',
                    bank_account_name VARCHAR(128),
                    verified_by VARCHAR(64) NOT NULL,
                    notes TEXT,
                    created_at TIMESTAMP
                )
            """))
            conn.execute(text("CREATE INDEX IF NOT EXISTS idx_balance_snapshots_farm_date ON cash_balance_snapshots(farm_id, balance_date)"))
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
