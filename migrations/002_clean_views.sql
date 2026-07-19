-- =============================================================================
-- 002_clean_views.sql — filtered views over raw collector data
-- =============================================================================
-- Raw data is never deleted. Instead, all research analysis reads these views,
-- which exclude rows that failed data-quality checks. This makes it structurally
-- hard to draw a conclusion from contaminated data.
--
-- Views are read-only projections; they do not modify the underlying tables.
-- =============================================================================

-- Trades that can be trusted for timing-sensitive analysis:
--   • joined to a real market row
--   • timestamp inside the market's own window (removes ~17% contamination)
--   • valid probability and sane elapsed_s
CREATE OR REPLACE VIEW research.clean_trades AS
SELECT t.*,
       m.open_time,
       m.close_time,
       m.window_ts,
       m.condition_id
FROM trades t
JOIN markets m ON t.slug = m.slug
WHERE t.trade_ts BETWEEN m.open_time AND m.close_time
  AND t.price > 0 AND t.price < 1
  AND t.elapsed_s BETWEEN 0 AND 300;

-- Snapshots usable for cross-market (BTC ↔ Polymarket) analysis.
CREATE OR REPLACE VIEW research.clean_snapshots AS
SELECT s.*,
       m.open_time,
       m.close_time
FROM snapshots s
JOIN markets m ON s.slug = m.slug
WHERE s.btc_price IS NOT NULL
  AND s.up_mid IS NOT NULL
  AND s.up_mid > 0 AND s.up_mid < 1
  AND s.elapsed_s BETWEEN 0 AND 300;

-- Resolved windows with a known winner — the labelled dataset.
CREATE OR REPLACE VIEW research.clean_markets AS
SELECT m.slug,
       m.window_ts,
       m.open_time,
       m.close_time,
       m.condition_id,
       r.winner,
       r.btc_open,
       r.btc_close,
       r.resolved_at,
       r.winner_source,
       CASE
           WHEN r.btc_open IS NOT NULL AND r.btc_open <> 0
           THEN (r.btc_close - r.btc_open) / r.btc_open * 10000.0
       END AS btc_move_bp
FROM markets m
JOIN resolutions r ON m.slug = r.slug
WHERE r.winner IN ('UP', 'DOWN');
