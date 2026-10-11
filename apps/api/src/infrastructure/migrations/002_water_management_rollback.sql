-- Aqua OS Rollback: 002_water_management_rollback.sql
-- Target: PostgreSQL 16
-- Purpose: Safely rollback 002 water management tables and added columns.

DROP TABLE IF EXISTS water_exchange_logs;
DROP TABLE IF EXISTS farm_pumps;

ALTER TABLE ponds DROP COLUMN IF EXISTS water_level_target_m;
ALTER TABLE ponds DROP COLUMN IF EXISTS water_level_min_m;
ALTER TABLE ponds DROP COLUMN IF EXISTS water_level_max_m;
ALTER TABLE ponds DROP COLUMN IF EXISTS normal_outlet_state;
ALTER TABLE ponds DROP COLUMN IF EXISTS full_drain_outlet_state;
ALTER TABLE ponds DROP COLUMN IF EXISTS full_drain_locked;
ALTER TABLE ponds DROP COLUMN IF EXISTS drain_lock_reason;

