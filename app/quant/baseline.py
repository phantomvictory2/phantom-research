"""
baseline.py — Phase 1 deterministic analytics.

Every number here is produced by SQL/Python. No LLM is involved. Results carry
their own sample sizes so a finding can never be quoted without its evidence.

Analyses:
  A. coverage()              — data volume, time span, gaps
  B. market_stats()          — UP/DOWN base rates, resolution coverage
  C. price_convergence()     — winning-side price by elapsed time
  D. btc_poly_alignment()    — direction agreement + reaction lag (7s resolution)
  E. trade_behaviour()       — timing/size/maker-taker distribution
  F. strategy_outcomes()     — Phantom V2 signals/positions (read-only)

IMPORTANT: convergence and alignment use only data available at that elapsed
time; resolution is used strictly as an outcome label, never as an input.
"""

import logging
from app.database.pool import research_ro, phantom_ro

logger = logging.getLogger("research.baseline")


# ── A. Coverage ──────────────────────────────────────────────────────────────
async def coverage() -> dict:
    row = await research_ro.fetchrow("""
        SELECT
          (SELECT count(*) FROM markets)      AS markets,
          (SELECT count(*) FROM resolutions)  AS resolutions,
          (SELECT count(*) FROM trades)       AS trades,
          (SELECT count(*) FROM snapshots)    AS snapshots,
          (SELECT count(*) FROM research.clean_trades)    AS clean_trades,
          (SELECT count(*) FROM research.clean_snapshots) AS clean_snapshots,
          (SELECT min(trade_ts) FROM trades)  AS first_trade,
          (SELECT max(trade_ts) FROM trades)  AS last_trade,
          (SELECT EXTRACT(EPOCH FROM (max(trade_ts) - min(trade_ts)))/86400.0
             FROM trades)                     AS span_days,
          pg_size_pretty(pg_database_size(current_database())) AS db_size
    """)
    d = dict(row)
    d["clean_trade_pct"] = round(
        (d["clean_trades"] / d["trades"] * 100.0) if d["trades"] else 0.0, 2)
    return d


# ── B. Market statistics ─────────────────────────────────────────────────────
async def market_stats() -> dict:
    row = await research_ro.fetchrow("""
        SELECT count(*) AS resolved,
               count(*) FILTER (WHERE winner = 'UP')   AS up_wins,
               count(*) FILTER (WHERE winner = 'DOWN') AS down_wins,
               round(avg(abs(btc_move_bp))::numeric, 2) AS avg_abs_move_bp,
               round((percentile_cont(0.5) WITHIN GROUP
                     (ORDER BY abs(btc_move_bp)))::numeric, 2) AS median_abs_move_bp
        FROM research.clean_markets
    """)
    d = dict(row)
    total = d["resolved"] or 0
    d["up_pct"] = round((d["up_wins"] / total * 100.0), 2) if total else 0.0
    d["down_pct"] = round((d["down_wins"] / total * 100.0), 2) if total else 0.0
    return d


# ── C. Price convergence by elapsed time ─────────────────────────────────────
async def price_convergence() -> list:
    """Average price of the side that eventually won, bucketed by elapsed time.
    Resolution is used only as a label to identify the winning side."""
    rows = await research_ro.fetch("""
        SELECT (s.elapsed_s / 30) * 30 AS bucket_s,
               count(*) AS n,
               round(avg(CASE WHEN m.winner = 'UP' THEN s.up_mid
                              ELSE 1.0 - s.up_mid END)::numeric, 4) AS avg_winner_price
        FROM research.clean_snapshots s
        JOIN research.clean_markets m ON s.slug = m.slug
        GROUP BY bucket_s
        HAVING count(*) > 30
        ORDER BY bucket_s
    """)
    return [dict(r) for r in rows]


# ── D. BTC ↔ Polymarket relationship ─────────────────────────────────────────
async def btc_poly_alignment() -> dict:
    """Does Polymarket's implied direction agree with BTC's actual displacement
    from the window open? Measured at ~7s snapshot resolution — this CANNOT
    support sub-second latency claims."""
    row = await research_ro.fetchrow("""
        WITH j AS (
            SELECT s.slug, s.elapsed_s, s.up_mid, s.btc_price, m.btc_open,
                   CASE WHEN m.btc_open IS NOT NULL AND m.btc_open <> 0
                        THEN (s.btc_price - m.btc_open) / m.btc_open * 10000.0 END AS disp_bp
            FROM research.clean_snapshots s
            JOIN research.clean_markets m ON s.slug = m.slug
            WHERE s.elapsed_s >= 30
        )
        SELECT count(*) AS n,
               count(*) FILTER (WHERE (disp_bp > 0) = (up_mid > 0.5)) AS aligned,
               count(*) FILTER (WHERE abs(disp_bp) >= 5) AS n_displaced,
               count(*) FILTER (WHERE abs(disp_bp) >= 5
                                  AND (disp_bp > 0) = (up_mid > 0.5)) AS aligned_displaced
        FROM j
        WHERE disp_bp IS NOT NULL
    """)
    d = dict(row)
    d["aligned_pct"] = round((d["aligned"] / d["n"] * 100.0), 2) if d["n"] else 0.0
    d["aligned_displaced_pct"] = round(
        (d["aligned_displaced"] / d["n_displaced"] * 100.0), 2) if d["n_displaced"] else 0.0
    return d


async def btc_poly_by_ttr() -> list:
    """Direction agreement bucketed by elapsed time — does the market track BTC
    more closely as resolution approaches?"""
    rows = await research_ro.fetch("""
        WITH j AS (
            SELECT s.elapsed_s, s.up_mid,
                   CASE WHEN m.btc_open IS NOT NULL AND m.btc_open <> 0
                        THEN (s.btc_price - m.btc_open) / m.btc_open * 10000.0 END AS disp_bp
            FROM research.clean_snapshots s
            JOIN research.clean_markets m ON s.slug = m.slug
        )
        SELECT (elapsed_s / 60) * 60 AS bucket_s,
               count(*) AS n,
               round(100.0 * count(*) FILTER (WHERE (disp_bp > 0) = (up_mid > 0.5))
                     / NULLIF(count(*), 0), 2) AS aligned_pct
        FROM j
        WHERE disp_bp IS NOT NULL
        GROUP BY bucket_s
        HAVING count(*) > 30
        ORDER BY bucket_s
    """)
    return [dict(r) for r in rows]


# ── E. Trade behaviour ───────────────────────────────────────────────────────
async def trade_behaviour() -> dict:
    row = await research_ro.fetchrow("""
        SELECT count(*) AS n,
               round(avg(usdc)::numeric, 2) AS avg_usdc,
               round((percentile_cont(0.5) WITHIN GROUP (ORDER BY usdc))::numeric, 2) AS median_usdc,
               round(avg(price)::numeric, 4) AS avg_price,
               round(100.0 * count(*) FILTER (WHERE is_maker) / NULLIF(count(*),0), 2) AS maker_pct,
               count(DISTINCT wallet) AS unique_wallets
        FROM research.clean_trades
    """)
    return dict(row)


async def trade_timing() -> list:
    rows = await research_ro.fetch("""
        SELECT CASE
                 WHEN elapsed_s < 60  THEN '000-060s'
                 WHEN elapsed_s < 120 THEN '060-120s'
                 WHEN elapsed_s < 180 THEN '120-180s'
                 WHEN elapsed_s < 240 THEN '180-240s'
                 WHEN elapsed_s < 285 THEN '240-285s'
                 ELSE '285-300s'
               END AS phase,
               count(*) AS n,
               round(sum(usdc)::numeric, 0) AS volume_usdc
        FROM research.clean_trades
        GROUP BY phase
        ORDER BY phase
    """)
    return [dict(r) for r in rows]


# ── F. Phantom V2 strategy outcomes (read-only) ──────────────────────────────
async def strategy_outcomes() -> dict:
    """Reads Phantom V2's operational DB. Returns {} if not configured/reachable —
    research must degrade gracefully, never crash."""
    out = {}
    try:
        rows = await phantom_ro.fetch("""
            SELECT strategy_type,
                   count(*) AS trades,
                   count(*) FILTER (WHERE pnl > 0) AS wins,
                   count(*) FILTER (WHERE pnl < 0) AS losses,
                   round(sum(pnl)::numeric, 2) AS total_pnl,
                   round(avg(pnl)::numeric, 4) AS avg_pnl
            FROM positions
            WHERE status = 'CLOSED'
            GROUP BY strategy_type
            ORDER BY total_pnl DESC
        """)
        out["strategies"] = [dict(r) for r in rows]

        skips = await phantom_ro.fetch("""
            SELECT skip_reason, count(*) AS n
            FROM signals
            WHERE skip_reason IS NOT NULL
            GROUP BY skip_reason
            ORDER BY n DESC
            LIMIT 15
        """)
        out["skip_reasons"] = [dict(r) for r in skips]

        rej = await phantom_ro.fetch("""
            SELECT rejection_reason, count(*) AS n
            FROM signals
            WHERE rejection_reason IS NOT NULL
            GROUP BY rejection_reason
            ORDER BY n DESC
            LIMIT 15
        """)
        out["rejection_reasons"] = [dict(r) for r in rej]
    except Exception as e:
        logger.warning("Phantom V2 analytics unavailable: %s", e)
        out["error"] = str(e)
    return out
