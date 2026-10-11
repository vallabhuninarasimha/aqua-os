-- Aqua OS Migration: 001_initial_schema.sql
-- Target: PostgreSQL 16 with TimescaleDB extension
-- Purpose: Schema definition for multi-farm ponds, hypertable telemetry, and real-time cache.

CREATE EXTENSION IF NOT EXISTS timescaledb CASCADE;

-- 1. Ponds Table (Relational Farm & Pond Registry)
CREATE TABLE IF NOT EXISTS ponds (
    farm_id VARCHAR(64) NOT NULL,
    pond_id VARCHAR(64) NOT NULL,
    name VARCHAR(128) NOT NULL,
    area_hectares DOUBLE PRECISION NOT NULL DEFAULT 0.5,
    depth_meters DOUBLE PRECISION NOT NULL DEFAULT 1.2,
    species VARCHAR(128) NOT NULL DEFAULT 'Litopenaeus vannamei',
    stocking_density_per_m2 INTEGER NOT NULL DEFAULT 60,
    days_of_culture INTEGER NOT NULL DEFAULT 0,
    is_active BOOLEAN NOT NULL DEFAULT TRUE,
    aerator_count INTEGER NOT NULL DEFAULT 4,
    feeder_count INTEGER NOT NULL DEFAULT 1,
    thresholds_json TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (farm_id, pond_id)
);

CREATE INDEX IF NOT EXISTS idx_ponds_farm ON ponds(farm_id);

-- 2. Telemetry Records (Time-Series Hypertables)
CREATE TABLE IF NOT EXISTS telemetry_records (
    id BIGSERIAL,
    farm_id VARCHAR(64) NOT NULL,
    pond_id VARCHAR(64) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    metrics_json TEXT NOT NULL,
    hardware_status_json TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (id, timestamp)
);

-- Idempotency index preventing duplicate event emissions
CREATE UNIQUE INDEX IF NOT EXISTS uq_telemetry_event 
    ON telemetry_records (farm_id, pond_id, timestamp);

-- Convert to TimescaleDB Hypertable partitioned by 7-day chunks (if TimescaleDB is loaded)
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM pg_extension WHERE extname = 'timescaledb') THEN
        PERFORM create_hypertable('telemetry_records', 'timestamp', if_not_exists => TRUE, chunk_time_interval => INTERVAL '7 days');
    END IF;
END $$;

-- 3. Latest Telemetry State (Fast Overview Matrix)
CREATE TABLE IF NOT EXISTS latest_telemetry (
    farm_id VARCHAR(64) NOT NULL,
    pond_id VARCHAR(64) NOT NULL,
    timestamp TIMESTAMPTZ NOT NULL,
    metrics_json TEXT NOT NULL,
    hardware_status_json TEXT,
    safety_result_json TEXT,
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (farm_id, pond_id)
);
