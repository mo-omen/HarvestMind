CREATE EXTENSION IF NOT EXISTS pgcrypto;

CREATE TABLE IF NOT EXISTS farmers (
    farmer_id TEXT PRIMARY KEY,
    location TEXT NOT NULL DEFAULT '',
    preferred_crops JSONB NOT NULL DEFAULT '[]'::jsonb,
    current_crop TEXT,
    current_price_rm_per_kg DOUBLE PRECISION CHECK (current_price_rm_per_kg IS NULL OR current_price_rm_per_kg >= 0),
    expected_harvest_date DATE,
    farm_size_hectares DOUBLE PRECISION,
    expected_harvest_days INTEGER CHECK (expected_harvest_days IS NULL OR expected_harvest_days BETWEEN 1 AND 365),
    labor_flexibility_pct INTEGER CHECK (labor_flexibility_pct IS NULL OR labor_flexibility_pct BETWEEN 0 AND 100),
    candidate_crops JSONB NOT NULL DEFAULT '[]'::jsonb,
    latest_intake_state JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

ALTER TABLE farmers
    ADD COLUMN IF NOT EXISTS location TEXT NOT NULL DEFAULT '';

ALTER TABLE farmers
    ADD COLUMN IF NOT EXISTS preferred_crops JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE farmers
    ADD COLUMN IF NOT EXISTS farm_size_hectares DOUBLE PRECISION;

ALTER TABLE farmers
    ADD COLUMN IF NOT EXISTS current_crop TEXT;

ALTER TABLE farmers
    ADD COLUMN IF NOT EXISTS current_price_rm_per_kg DOUBLE PRECISION;

ALTER TABLE farmers
    ADD COLUMN IF NOT EXISTS expected_harvest_date DATE;

ALTER TABLE farmers
    ADD COLUMN IF NOT EXISTS expected_harvest_days INTEGER;

ALTER TABLE farmers
    ADD COLUMN IF NOT EXISTS labor_flexibility_pct INTEGER;

ALTER TABLE farmers
    ADD COLUMN IF NOT EXISTS candidate_crops JSONB NOT NULL DEFAULT '[]'::jsonb;

ALTER TABLE farmers
    ADD COLUMN IF NOT EXISTS latest_intake_state JSONB;

ALTER TABLE farmers
    ADD COLUMN IF NOT EXISTS updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW();

CREATE TABLE IF NOT EXISTS recommendation_runs (
    recommendation_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    farmer_id TEXT NOT NULL REFERENCES farmers (farmer_id) ON DELETE CASCADE,
    recorded_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    input_payload JSONB NOT NULL,
    evidence_packet JSONB NOT NULL,
    decision TEXT NOT NULL CHECK (decision IN ('persevere', 'pivot_partially', 'harvest_early')),
    confidence NUMERIC(4, 3) NOT NULL CHECK (confidence >= 0 AND confidence <= 1),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS recommendation_runs_farmer_recorded_at_idx
    ON recommendation_runs (farmer_id, recorded_at DESC, created_at DESC);

CREATE INDEX IF NOT EXISTS recommendation_runs_input_payload_gin_idx
    ON recommendation_runs
    USING GIN (input_payload);

CREATE INDEX IF NOT EXISTS recommendation_runs_evidence_packet_gin_idx
    ON recommendation_runs
    USING GIN (evidence_packet);

CREATE TABLE IF NOT EXISTS intake_sessions (
    session_id TEXT PRIMARY KEY,
    farmer_id TEXT REFERENCES farmers (farmer_id) ON DELETE SET NULL,
    state JSONB NOT NULL,
    analysis_request JSONB,
    transcript JSONB NOT NULL DEFAULT '[]'::jsonb,
    status TEXT NOT NULL CHECK (status IN ('needs_input', 'complete')),
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS intake_sessions_farmer_updated_at_idx
    ON intake_sessions (farmer_id, updated_at DESC);

CREATE TABLE IF NOT EXISTS recommendation_feedback (
    feedback_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    recommendation_id UUID REFERENCES recommendation_runs (recommendation_id) ON DELETE SET NULL,
    farmer_id TEXT NOT NULL REFERENCES farmers (farmer_id) ON DELETE CASCADE,
    rating INTEGER CHECK (rating IS NULL OR rating BETWEEN 1 AND 5),
    outcome_label TEXT,
    notes TEXT,
    actual_decision TEXT,
    actual_revenue_change_pct DOUBLE PRECISION,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS recommendation_feedback_farmer_created_at_idx
    ON recommendation_feedback (farmer_id, created_at DESC);

CREATE TABLE IF NOT EXISTS signal_snapshots (
    snapshot_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    farmer_id TEXT REFERENCES farmers (farmer_id) ON DELETE CASCADE,
    signal_type TEXT NOT NULL CHECK (signal_type IN ('price', 'weather', 'news')),
    crop TEXT,
    location TEXT,
    source TEXT NOT NULL,
    normalized_payload JSONB NOT NULL,
    raw_payload JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS signal_snapshots_farmer_type_created_at_idx
    ON signal_snapshots (farmer_id, signal_type, created_at DESC);

CREATE INDEX IF NOT EXISTS signal_snapshots_context_type_created_at_idx
    ON signal_snapshots (location, crop, signal_type, created_at DESC);

CREATE TABLE IF NOT EXISTS sync_jobs (
    job_id UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source TEXT NOT NULL CHECK (source IN ('market', 'weather', 'news')),
    status TEXT NOT NULL CHECK (status IN ('queued', 'running', 'completed', 'failed')),
    farmer_id TEXT REFERENCES farmers (farmer_id) ON DELETE SET NULL,
    crop TEXT,
    location TEXT,
    summary TEXT,
    result_payload JSONB,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS sync_jobs_source_created_at_idx
    ON sync_jobs (source, created_at DESC);
