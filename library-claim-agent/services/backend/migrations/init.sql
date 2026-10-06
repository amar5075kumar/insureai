-- Library Claim Agent — Database Schema
-- Runs on first container start via Docker init hook.
-- Idempotent: safe to run multiple times.

CREATE EXTENSION IF NOT EXISTS "uuid-ossp";

-- ── Sweeps ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS sweeps (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    country         VARCHAR(2)   NOT NULL DEFAULT 'GB',
    currency        VARCHAR(3)   NOT NULL DEFAULT 'GBP',
    state           VARCHAR(20)  NOT NULL DEFAULT 'initializing',
    device          VARCHAR(200),
    duration_s      INTEGER,
    captured_at     TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at    TIMESTAMPTZ,
    -- Scale calibration (from user voice during sweep)
    scale_method    VARCHAR(100),
    scale_value_m   FLOAT,
    scale_confidence FLOAT,
    -- Profile and cost tracking
    sweep_profile   VARCHAR(20)  NOT NULL DEFAULT 'standard',
    cost_usd        FLOAT        NOT NULL DEFAULT 0.0,
    error_message   TEXT,
    CONSTRAINT sweeps_state_check CHECK (state IN (
        'initializing', 'sweeping', 'processing',
        'reviewing', 'finalizing', 'complete',
        'failed', 'interrupted'
    ))
);

CREATE INDEX IF NOT EXISTS idx_sweeps_state ON sweeps(state);
CREATE INDEX IF NOT EXISTS idx_sweeps_captured_at ON sweeps(captured_at);

-- ── Frames ──────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS frames (
    id              UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sweep_id        UUID         NOT NULL REFERENCES sweeps(id) ON DELETE CASCADE,
    timestamp_ms    BIGINT       NOT NULL,
    s3_key          VARCHAR(500) NOT NULL,
    blur_score      FLOAT,
    is_blurry       BOOLEAN      NOT NULL DEFAULT FALSE,
    is_overexposed  BOOLEAN      NOT NULL DEFAULT FALSE,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_frames_sweep_id ON frames(sweep_id);
CREATE INDEX IF NOT EXISTS idx_frames_s3_key ON frames(s3_key);

-- ── Books ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS books (
    id              UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    sweep_id        UUID         NOT NULL REFERENCES sweeps(id) ON DELETE CASCADE,
    shelf           VARCHAR(100),
    position        INTEGER,
    frame_ref       VARCHAR(500) NOT NULL,
    status          VARCHAR(20)  NOT NULL DEFAULT 'processing',
    title           VARCHAR(500),
    author          VARCHAR(300),
    edition         VARCHAR(100),
    isbn            VARCHAR(20),
    ocr_raw_text    VARCHAR(1000),
    spine_height_cm FLOAT,
    spine_thickness_cm FLOAT,
    measurement_method VARCHAR(50),
    measurement_uncertainty_pct INTEGER,
    id_confidence   FLOAT,
    -- Replacement cost (new)
    replacement_cost_amount    FLOAT,
    replacement_cost_source    VARCHAR(100),
    replacement_cost_url       TEXT,
    replacement_cost_retrieved_at TIMESTAMPTZ,
    replacement_cost_converted BOOLEAN NOT NULL DEFAULT FALSE,
    replacement_cost_from_currency VARCHAR(3),
    replacement_cost_from_amount   FLOAT,
    -- Used market value
    used_value_amount    FLOAT,
    used_value_source    VARCHAR(100),
    used_value_url       TEXT,
    used_value_retrieved_at TIMESTAMPTZ,
    used_value_condition VARCHAR(50),
    -- Flags
    excluded_from_totals BOOLEAN NOT NULL DEFAULT FALSE,
    rare_signals    TEXT[],
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT books_status_check CHECK (status IN (
        'processing', 'identified', 'unidentified',
        'needs_appraisal', 'ocr_only', 'low_confidence', 'excluded'
    )),
    -- Integrity rule: unidentified books must not have a title
    CONSTRAINT books_unidentified_no_title CHECK (
        NOT (status IN ('unidentified', 'ocr_only') AND title IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS idx_books_sweep_id ON books(sweep_id);
CREATE INDEX IF NOT EXISTS idx_books_status ON books(status);
CREATE INDEX IF NOT EXISTS idx_books_isbn ON books(isbn) WHERE isbn IS NOT NULL;

-- ── Items ───────────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS items (
    id              UUID         PRIMARY KEY DEFAULT uuid_generate_v4(),
    sweep_id        UUID         NOT NULL REFERENCES sweeps(id) ON DELETE CASCADE,
    category        VARCHAR(100) NOT NULL,
    description     TEXT,
    brand_model     VARCHAR(200),
    frame_ref       VARCHAR(500) NOT NULL,
    width_cm        FLOAT,
    height_cm       FLOAT,
    depth_cm        FLOAT,
    status          VARCHAR(20)  NOT NULL DEFAULT 'processing',
    replacement_cost_low  FLOAT,
    replacement_cost_high FLOAT,
    replacement_cost_source VARCHAR(100),
    replacement_cost_url    TEXT,
    replacement_cost_retrieved_at TIMESTAMPTZ,
    confidence      FLOAT,
    user_confirmed_print BOOLEAN,
    created_at      TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT items_status_check CHECK (status IN (
        'processing', 'priced', 'range', 'needs_appraisal', 'no_price'
    ))
);

CREATE INDEX IF NOT EXISTS idx_items_sweep_id ON items(sweep_id);

-- ── Room Geometry ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS room_geometry (
    sweep_id            UUID PRIMARY KEY REFERENCES sweeps(id) ON DELETE CASCADE,
    length_m            FLOAT,
    width_m             FLOAT,
    height_m            FLOAT,
    floor_area_m2       FLOAT,
    wall_area_m2        FLOAT,
    shelved_wall_area_m2 FLOAT,
    scale_method        VARCHAR(100),
    confidence          FLOAT,
    shape               VARCHAR(50) NOT NULL DEFAULT 'rectangular',
    notes               TEXT,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ── Review Queue ─────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS review_queue (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sweep_id    UUID        NOT NULL REFERENCES sweeps(id) ON DELETE CASCADE,
    ref_id      VARCHAR(200) NOT NULL,
    reason      TEXT         NOT NULL,
    severity    VARCHAR(20)  NOT NULL DEFAULT 'info',
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    CONSTRAINT review_severity_check CHECK (severity IN ('info', 'warning', 'critical'))
);

CREATE INDEX IF NOT EXISTS idx_review_sweep_id ON review_queue(sweep_id);

-- ── Conversations ────────────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS conversations (
    id          UUID PRIMARY KEY DEFAULT uuid_generate_v4(),
    sweep_id    UUID        NOT NULL REFERENCES sweeps(id) ON DELETE CASCADE,
    role        VARCHAR(10)  NOT NULL CHECK (role IN ('user', 'agent')),
    content     TEXT         NOT NULL,
    timestamp_ms BIGINT,
    created_at  TIMESTAMPTZ  NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_conv_sweep_id ON conversations(sweep_id);

-- ── Celery Task Tracking ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS celery_tasks (
    task_id       VARCHAR(200) PRIMARY KEY,
    sweep_id      UUID        NOT NULL REFERENCES sweeps(id) ON DELETE CASCADE,
    task_type     VARCHAR(50)  NOT NULL,
    ref_id        VARCHAR(200),
    status        VARCHAR(20)  NOT NULL DEFAULT 'pending',
    dispatched_at TIMESTAMPTZ  NOT NULL DEFAULT NOW(),
    completed_at  TIMESTAMPTZ,
    error_message TEXT,
    CONSTRAINT celery_status_check CHECK (status IN (
        'pending', 'running', 'complete', 'failed', 'timeout'
    ))
);

CREATE INDEX IF NOT EXISTS idx_celery_sweep_id ON celery_tasks(sweep_id);
CREATE INDEX IF NOT EXISTS idx_celery_status ON celery_tasks(status);
