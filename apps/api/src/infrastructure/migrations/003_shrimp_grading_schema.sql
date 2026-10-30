-- Aqua OS Migration 003: measured shrimp grading sample audit history.
-- Grade bands are supplied by the farm/buyer and are persisted with every result.

CREATE TABLE IF NOT EXISTS shrimp_grading_samples (
    grade_sample_id VARCHAR(36) PRIMARY KEY,
    farm_id VARCHAR(64) NOT NULL,
    pond_id VARCHAR(64) NOT NULL,
    sample_count INTEGER NOT NULL CHECK (sample_count > 0 AND sample_count <= 500),
    average_body_weight_g DOUBLE PRECISION NOT NULL CHECK (average_body_weight_g > 0),
    average_count_per_kg DOUBLE PRECISION NOT NULL CHECK (average_count_per_kg > 0),
    sample_weights_json TEXT NOT NULL,
    grade_bands_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    recorded_by VARCHAR(64) NOT NULL,
    sampled_at TIMESTAMPTZ NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_shrimp_grading_farm_pond_time
    ON shrimp_grading_samples (farm_id, pond_id, sampled_at DESC);
