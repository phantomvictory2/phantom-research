-- =============================================================================
-- 001_research_schema.sql — Phantom Quant Research Intelligence Engine
-- =============================================================================
-- Creates the ONLY schema the Research Engine may write to. Raw collector
-- tables (markets/trades/snapshots/resolutions) and Phantom V2 operational
-- tables are never modified by this service.
--
-- Idempotent: safe to re-run.
-- =============================================================================

CREATE SCHEMA IF NOT EXISTS research;

-- ── Enumerated vocabularies ─────────────────────────────────────────────────
-- Data quality classification (raw rows are never deleted — only labelled).
DO $$ BEGIN
    CREATE TYPE research.quality_level AS ENUM
        ('GOOD', 'SUSPECT', 'INVALID', 'STALE', 'PARTIAL');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- Lifecycle of a research hypothesis.
DO $$ BEGIN
    CREATE TYPE research.hypothesis_status AS ENUM
        ('PROPOSED', 'TESTING', 'SUPPORTED', 'REJECTED', 'INCONCLUSIVE', 'DEGRADED');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- How strong the evidence behind a finding is. This is what prevents an
-- observation from ever being presented as proven profitability.
DO $$ BEGIN
    CREATE TYPE research.evidence_level AS ENUM
        ('OBSERVATIONAL', 'STATISTICALLY_SUPPORTED',
         'OUT_OF_SAMPLE_VALIDATED', 'PAPER_VALIDATED');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE research.health_status AS ENUM
        ('HEALTHY', 'WARNING', 'STALE', 'CRITICAL');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;


-- ── Collector / system health heartbeat ─────────────────────────────────────
CREATE TABLE IF NOT EXISTS research.system_health (
    id              BIGSERIAL PRIMARY KEY,
    checked_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    component       TEXT        NOT NULL,          -- 'collector' | 'research_db' | ...
    status          research.health_status NOT NULL,
    trade_age_s     DOUBLE PRECISION,
    snapshot_age_s  DOUBLE PRECISION,
    resolution_age_s DOUBLE PRECISION,
    rows_last_15m   INTEGER,
    detail          JSONB
);
CREATE INDEX IF NOT EXISTS ix_system_health_time
    ON research.system_health (checked_at DESC);
CREATE INDEX IF NOT EXISTS ix_system_health_component
    ON research.system_health (component, checked_at DESC);


-- ── Data quality events ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS research.data_quality_events (
    id              BIGSERIAL PRIMARY KEY,
    detected_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    check_name      TEXT        NOT NULL,   -- 'trades_outside_window', 'collector_gap', ...
    severity        research.quality_level NOT NULL,
    affected_rows   BIGINT,
    period_start    TIMESTAMPTZ,
    period_end      TIMESTAMPTZ,
    detail          JSONB
);
CREATE INDEX IF NOT EXISTS ix_dq_events_time
    ON research.data_quality_events (detected_at DESC);
CREATE INDEX IF NOT EXISTS ix_dq_events_check
    ON research.data_quality_events (check_name, detected_at DESC);


-- ── Derived per-window features (populated in Phase 2) ──────────────────────
CREATE TABLE IF NOT EXISTS research.market_features (
    id              BIGSERIAL PRIMARY KEY,
    window_ts       BIGINT      NOT NULL,
    slug            TEXT        NOT NULL,
    elapsed_s       INTEGER     NOT NULL,
    btc_price       DOUBLE PRECISION,
    btc_ret_30s     DOUBLE PRECISION,
    btc_ret_60s     DOUBLE PRECISION,
    btc_velocity    DOUBLE PRECISION,
    btc_accel       DOUBLE PRECISION,
    btc_disp_bp     DOUBLE PRECISION,   -- displacement from window open, basis points
    up_mid          DOUBLE PRECISION,
    down_mid        DOUBLE PRECISION,
    spread          DOUBLE PRECISION,
    poly_velocity   DOUBLE PRECISION,
    direction_align BOOLEAN,
    quality         research.quality_level NOT NULL DEFAULT 'GOOD',
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (slug, elapsed_s)
);
CREATE INDEX IF NOT EXISTS ix_features_window
    ON research.market_features (window_ts, elapsed_s);


-- ── Market regimes (Phase 2) ────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS research.market_regimes (
    id              BIGSERIAL PRIMARY KEY,
    window_ts       BIGINT      NOT NULL,
    slug            TEXT        NOT NULL,
    direction       TEXT,       -- BULLISH | BEARISH | NEUTRAL
    volatility      TEXT,       -- LOW | MEDIUM | HIGH
    liquidity       TEXT,       -- THIN | NORMAL | DEEP
    stage           TEXT,       -- EARLY | MID | LATE
    regime_hash     TEXT,
    computed_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (slug)
);


-- ── Pattern instances (Phase 4) ─────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS research.pattern_instances (
    id              BIGSERIAL PRIMARY KEY,
    pattern_id      TEXT        NOT NULL,
    window_ts       BIGINT      NOT NULL,
    slug            TEXT        NOT NULL,
    elapsed_s       INTEGER,
    features        JSONB,
    fwd_ret_5s      DOUBLE PRECISION,
    fwd_ret_10s     DOUBLE PRECISION,
    fwd_ret_30s     DOUBLE PRECISION,
    outcome         TEXT,
    quality         research.quality_level NOT NULL DEFAULT 'GOOD',
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_pattern_instances_pattern
    ON research.pattern_instances (pattern_id, window_ts);


-- ── Research memory: hypotheses, experiments, findings ──────────────────────
CREATE TABLE IF NOT EXISTS research.research_hypotheses (
    id              TEXT PRIMARY KEY,           -- 'H001'
    question        TEXT        NOT NULL,
    rationale       TEXT,
    data_required   TEXT,
    status          research.hypothesis_status NOT NULL DEFAULT 'PROPOSED',
    evidence_level  research.evidence_level,
    sample_size     BIGINT,
    data_period     TEXT,
    method          TEXT,
    result          TEXT,
    confidence      TEXT,
    validator_passed BOOLEAN,                   -- Quant Validator veto gate
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS research.research_experiments (
    id              BIGSERIAL PRIMARY KEY,
    hypothesis_id   TEXT REFERENCES research.research_hypotheses(id),
    params          JSONB,
    split_type      TEXT,        -- FULL | TRAIN | TEST | WALK_FORWARD | OOS
    sample_size     BIGINT,
    metrics         JSONB,
    passed          BOOLEAN,
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_experiments_hypothesis
    ON research.research_experiments (hypothesis_id, created_at DESC);

CREATE TABLE IF NOT EXISTS research.research_findings (
    id              BIGSERIAL PRIMARY KEY,
    reported_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    category        TEXT,
    statement       TEXT        NOT NULL,
    evidence_level  research.evidence_level NOT NULL,
    sample_size     BIGINT,
    data_period     TEXT,
    confidence      TEXT,
    limitations     TEXT,
    provenance      JSONB       -- queries/experiments backing this claim
);
CREATE INDEX IF NOT EXISTS ix_findings_time
    ON research.research_findings (reported_at DESC);


-- ── Backtests (Phase 8) ─────────────────────────────────────────────────────
CREATE TABLE IF NOT EXISTS research.backtest_results (
    id              BIGSERIAL PRIMARY KEY,
    candidate_id    TEXT,
    split           TEXT,
    samples         BIGINT,
    win_rate        DOUBLE PRECISION,
    gross_expectancy DOUBLE PRECISION,
    net_expectancy  DOUBLE PRECISION,   -- after fees/spread/slippage
    profit_factor   DOUBLE PRECISION,
    max_drawdown    DOUBLE PRECISION,
    ci_low          DOUBLE PRECISION,
    ci_high         DOUBLE PRECISION,
    cost_model      JSONB,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);


-- ── AI research memory (Phase 6+) ───────────────────────────────────────────
CREATE TABLE IF NOT EXISTS research.ai_research_memory (
    id              BIGSERIAL PRIMARY KEY,
    agent           TEXT        NOT NULL,
    question        TEXT,
    answer          TEXT,
    citations       JSONB,      -- must reference deterministic results
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_ai_memory_time
    ON research.ai_research_memory (created_at DESC);
