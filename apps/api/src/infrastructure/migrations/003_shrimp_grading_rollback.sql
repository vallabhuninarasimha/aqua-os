-- Rollback Aqua OS Migration 003.
DROP INDEX IF EXISTS idx_shrimp_grading_farm_pond_time;
DROP TABLE IF EXISTS shrimp_grading_samples;
