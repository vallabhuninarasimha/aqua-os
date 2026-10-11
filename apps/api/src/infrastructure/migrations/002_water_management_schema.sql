-- Aqua OS Migration: 002_water_management_schema.sql
-- Target: PostgreSQL 16 with TimescaleDB extension / standard SQL
-- Purpose: Schema definitions for water management: dual outlet states, pump representations, and water exchange logs.

-- 1. Extend ponds table with hydraulic & outlet configuration columns
DO $$
BEGIN
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'ponds' AND column_name = 'water_level_target_m') THEN
        ALTER TABLE ponds ADD COLUMN water_level_target_m DOUBLE PRECISION NOT NULL DEFAULT 1.22;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'ponds' AND column_name = 'water_level_min_m') THEN
        ALTER TABLE ponds ADD COLUMN water_level_min_m DOUBLE PRECISION NOT NULL DEFAULT 0.95;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'ponds' AND column_name = 'water_level_max_m') THEN
        ALTER TABLE ponds ADD COLUMN water_level_max_m DOUBLE PRECISION NOT NULL DEFAULT 1.40;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'ponds' AND column_name = 'normal_outlet_state') THEN
        ALTER TABLE ponds ADD COLUMN normal_outlet_state VARCHAR(32) NOT NULL DEFAULT 'CLOSED';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'ponds' AND column_name = 'full_drain_outlet_state') THEN
        ALTER TABLE ponds ADD COLUMN full_drain_outlet_state VARCHAR(32) NOT NULL DEFAULT 'CLOSED';
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'ponds' AND column_name = 'full_drain_locked') THEN
        ALTER TABLE ponds ADD COLUMN full_drain_locked BOOLEAN NOT NULL DEFAULT TRUE;
    END IF;
    IF NOT EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name = 'ponds' AND column_name = 'drain_lock_reason') THEN
        ALTER TABLE ponds ADD COLUMN drain_lock_reason VARCHAR(128) NOT NULL DEFAULT 'Active batch biological containment';
    END IF;
END $$;

-- 2. Farm Pumps Table (River Intake & Water Transfer Units)
CREATE TABLE IF NOT EXISTS farm_pumps (
    pump_id VARCHAR(64) PRIMARY KEY,
    farm_id VARCHAR(64) NOT NULL,
    name VARCHAR(128) NOT NULL DEFAULT 'River Intake Pump House',
    motor_hp DOUBLE PRECISION,
    rating_kw DOUBLE PRECISION,
    transformer_id VARCHAR(32),
    desired_state VARCHAR(32) NOT NULL DEFAULT 'OFF',
    physical_state VARCHAR(32) NOT NULL DEFAULT 'OFF',
    current_draw_amps DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    power_kw DOUBLE PRECISION NOT NULL DEFAULT 0.0,
    last_run_timestamp TIMESTAMPTZ,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_farm_pumps_farm ON farm_pumps(farm_id);

-- 3. Water Exchange & Drainage Audit Logs
CREATE TABLE IF NOT EXISTS water_exchange_logs (
    id BIGSERIAL PRIMARY KEY,
    exchange_id VARCHAR(64) NOT NULL UNIQUE,
    farm_id VARCHAR(64) NOT NULL,
    pond_id VARCHAR(64) NOT NULL,
    mode VARCHAR(32) NOT NULL,
    initial_level_m DOUBLE PRECISION NOT NULL,
    final_level_m DOUBLE PRECISION,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    operator_id VARCHAR(64) NOT NULL,
    notes TEXT
);

CREATE INDEX IF NOT EXISTS idx_water_exchange_farm_pond ON water_exchange_logs(farm_id, pond_id, started_at);

