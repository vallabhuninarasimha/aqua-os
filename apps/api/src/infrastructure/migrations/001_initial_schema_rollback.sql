-- Aqua OS Migration Rollback: 001_initial_schema_rollback.sql
-- Reverts tables created in 001_initial_schema.sql

DROP TABLE IF EXISTS latest_telemetry CASCADE;
DROP TABLE IF EXISTS telemetry_records CASCADE;
DROP TABLE IF EXISTS ponds CASCADE;
