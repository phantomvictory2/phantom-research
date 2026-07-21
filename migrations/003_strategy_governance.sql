-- =============================================================================
-- 003_strategy_governance.sql — formal strategy lifecycle
-- =============================================================================
-- A strategy must never reach production because "paper P&L looked good".
-- This schema makes the lifecycle explicit and auditable: every stage
-- transition is recorded with the evidence that justified it, and promotion to
-- live states requires a named human approver.
--
-- Read-only for the trading engine. The research engine writes it. Nothing here
-- changes trading behaviour — it records and governs, it does not execute.
-- =============================================================================

DO $$ BEGIN
    CREATE TYPE research.strategy_state AS ENUM (
        'IDEA',
        'RESEARCHING',
        'REJECTED',
        'STATISTICALLY_VALIDATED',
        'EXECUTION_VALIDATED',
        'BACKTESTING',
        'REPLAY_VALIDATED',
        'SHADOW',
        'PAPER',
        'LIVE_CANDIDATE',
        'LIVE_MINIMUM_SIZE',
        'LIVE',
        'DEGRADED',
        'SUSPENDED',
        'RETIRED'
    );
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

DO $$ BEGIN
    CREATE TYPE research.health_state AS ENUM
        ('HEALTHY', 'WATCH', 'DEGRADING', 'INVALIDATED', 'UNKNOWN');
EXCEPTION WHEN duplicate_object THEN NULL; END $$;


CREATE TABLE IF NOT EXISTS research.strategy_registry (
    strategy_id      TEXT PRIMARY KEY,
    version          TEXT NOT NULL DEFAULT 'v1',
    state            research.strategy_state NOT NULL DEFAULT 'IDEA',
    owner            TEXT,
    hypothesis_id    TEXT REFERENCES research.research_hypotheses(id),
    finding_id       BIGINT REFERENCES research.research_findings(id),
    code_version     TEXT,                    -- git commit of the strategy code
    data_period      TEXT,
    evidence_level   research.evidence_level,

    -- gate outcomes; NULL = not attempted
    statistical_status TEXT,
    execution_status   TEXT,
    backtest_status    TEXT,
    replay_status      TEXT,
    shadow_status      TEXT,
    paper_status       TEXT,
    risk_status        TEXT,

    -- live performance snapshot (informational; never auto-promotes)
    trades           BIGINT DEFAULT 0,
    win_rate         DOUBLE PRECISION,
    net_pnl          DOUBLE PRECISION,
    expectancy       DOUBLE PRECISION,
    health           research.health_state NOT NULL DEFAULT 'UNKNOWN',

    promoted_by      TEXT,                    -- human approver for live states
    promotion_date   TIMESTAMPTZ,
    last_reviewed    TIMESTAMPTZ,
    notes            TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Immutable audit trail. Every transition, with its justification.
CREATE TABLE IF NOT EXISTS research.strategy_transitions (
    id            BIGSERIAL PRIMARY KEY,
    strategy_id   TEXT NOT NULL REFERENCES research.strategy_registry(strategy_id),
    from_state    research.strategy_state,
    to_state      research.strategy_state NOT NULL,
    evidence      JSONB,          -- what justified this move
    approved_by   TEXT,           -- required for live states
    rationale     TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_strategy_transitions
    ON research.strategy_transitions (strategy_id, created_at DESC);

-- Rejected-idea memory: stops the same failed idea being rediscovered.
CREATE TABLE IF NOT EXISTS research.rejected_ideas (
    id            BIGSERIAL PRIMARY KEY,
    idea          TEXT NOT NULL,
    kind          TEXT,           -- 'strategy' | 'hypothesis' | 'parameter'
    why_failed    TEXT NOT NULL,
    evidence      JSONB,
    data_period   TEXT,
    sample_size   BIGINT,
    rejected_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
