-- =============================================================================
-- 005_features.sql — deterministic feature layer (Phase 2)
-- =============================================================================
-- research.features is the SINGLE SOURCE OF FEATURE NUMBERS for the Phase 3+
-- research brain (built in Antigravity). One row per (slug, elapsed_s) tick,
-- carrying the feature vector as-of that tick. Every value is computable from
-- data with timestamp <= that tick — NO look-ahead. This table is the authoritative
-- interface contract; its column names/types must not drift.
--
-- Additive and idempotent. Never alters raw collector tables.
-- =============================================================================

CREATE TABLE IF NOT EXISTS research.features (
    slug                 TEXT              NOT NULL,
    duration             TEXT,
    elapsed_s            INTEGER           NOT NULL,
    computed_at          TIMESTAMPTZ       NOT NULL DEFAULT now(),

    -- price context (from snapshots, as-of the tick)
    up_mid               DOUBLE PRECISION,
    up_best_bid          DOUBLE PRECISION,
    up_best_ask          DOUBLE PRECISION,
    up_best_bid_size     DOUBLE PRECISION,
    up_best_ask_size     DOUBLE PRECISION,

    -- order-book features (from book_depth, nearest within tolerance)
    book_imbalance       DOUBLE PRECISION,   -- (bidSz - askSz)/(bidSz + askSz), top level
    size_at_ask          DOUBLE PRECISION,   -- executable size at best ask

    -- spot features (BTC, as-of the tick; no future rows)
    spot_momentum_bp     DOUBLE PRECISION,   -- BTC move over a fixed lookback, bp
    spot_displacement_bp DOUBLE PRECISION,   -- BTC move since window open, bp

    -- regime label (rule-based v1)
    regime_label         TEXT,               -- TREND_UP / TREND_DOWN / CHOP / VOLATILE

    feature_version      TEXT              NOT NULL DEFAULT 'v1',

    PRIMARY KEY (slug, elapsed_s)
);

CREATE INDEX IF NOT EXISTS features_slug   ON research.features (slug);
CREATE INDEX IF NOT EXISTS features_regime ON research.features (regime_label);
