"""
features.py — deterministic feature engine (Phase 2).

Produces the feature vector that Phase 3+ (the research brain) consumes from
`research.features`. Every feature is computed AS-OF a tick, using only rows at
that tick or earlier — never a future row. This is enforced structurally: the
pure `compute_window_features` walks ticks in time order and each tick reads only
`ticks[0..i]`. That property is what the leakage test verifies.

Design:
  • Pure functions (this module's top half) do all the math on in-memory ticks —
    no DB, no I/O — so they are unit-testable with fixtures (golden-value tests).
  • The async DB layer (bottom half) loads ticks per window from the read-only
    pool, runs the pure computation, and upserts into research.features via the
    schema-guarded write pool.

No look-ahead. No LLM. No dependency on Phantom V2.
"""

import logging
import statistics
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger("research.features")

FEATURE_VERSION = "v1"


@dataclass(frozen=True)
class FeatureConfig:
    momentum_lookback_s: float = 15.0   # BTC momentum window
    vol_window_s: float = 30.0          # realized-vol window
    trend_threshold_bp: float = 3.0     # |momentum| above this => trend
    vol_threshold_bp: float = 8.0       # realized vol above this => volatile
    version: str = FEATURE_VERSION


# ── Pure feature math (no DB, fully testable) ────────────────────────────────

def book_imbalance(bid_size, ask_size) -> Optional[float]:
    """Top-of-book imbalance in [-1, 1]. None if either side is missing/empty."""
    if bid_size is None or ask_size is None:
        return None
    total = bid_size + ask_size
    if total <= 0:
        return None
    return (bid_size - ask_size) / total


def _price_at_or_before(ticks, i, cutoff_elapsed) -> Optional[float]:
    """BTC price at the latest tick with elapsed_s <= cutoff_elapsed, scanning
    only ticks[0..i] (never the future)."""
    for j in range(i, -1, -1):
        if ticks[j]["elapsed_s"] <= cutoff_elapsed and ticks[j].get("btc_price"):
            return ticks[j]["btc_price"]
    return None


def momentum_bp(ticks, i, lookback_s) -> Optional[float]:
    """BTC move (bp) from `lookback_s` ago to tick i, as-of tick i."""
    btc_i = ticks[i].get("btc_price")
    if not btc_i:
        return None
    ref = _price_at_or_before(ticks, i, ticks[i]["elapsed_s"] - lookback_s)
    if not ref:
        return None
    return (btc_i - ref) / ref * 10000.0


def displacement_bp(ticks, i) -> Optional[float]:
    """BTC move (bp) since window open (first tick), as-of tick i."""
    btc_i = ticks[i].get("btc_price")
    btc_open = ticks[0].get("btc_price") if ticks else None
    if not btc_i or not btc_open:
        return None
    return (btc_i - btc_open) / btc_open * 10000.0


def realized_vol_bp(ticks, i, window_s) -> Optional[float]:
    """Std-dev of consecutive BTC returns (bp) within `window_s` up to tick i."""
    lo = ticks[i]["elapsed_s"] - window_s
    window = [t for t in ticks[: i + 1]
              if t["elapsed_s"] >= lo and t.get("btc_price")]
    if len(window) < 3:
        return None
    rets = []
    for k in range(1, len(window)):
        p0 = window[k - 1]["btc_price"]
        p1 = window[k]["btc_price"]
        if p0:
            rets.append((p1 - p0) / p0 * 10000.0)
    if len(rets) < 2:
        return None
    return statistics.pstdev(rets)


def classify_regime(momentum, vol, cfg: FeatureConfig) -> str:
    """Rule-based regime. VOLATILE takes priority over direction."""
    if vol is not None and vol >= cfg.vol_threshold_bp:
        return "VOLATILE"
    if momentum is None:
        return "CHOP"
    if momentum >= cfg.trend_threshold_bp:
        return "TREND_UP"
    if momentum <= -cfg.trend_threshold_bp:
        return "TREND_DOWN"
    return "CHOP"


def compute_window_features(ticks, cfg: FeatureConfig = None) -> list:
    """Compute one feature row per tick for a single market window.

    `ticks`: list of dicts, sorted by elapsed_s ascending, each with keys:
        slug, duration, elapsed_s, btc_price, up_mid, up_bid, up_ask,
        bid_size, ask_size  (sizes may be None when depth is missing).

    Returns a list of feature dicts. LEAKAGE GUARANTEE: the row for tick i uses
    only ticks[0..i]; mutating any tick j > i cannot change row i.
    """
    cfg = cfg or FeatureConfig()
    ticks = sorted(ticks, key=lambda t: t["elapsed_s"])
    out = []
    now = datetime.now(timezone.utc)
    for i, t in enumerate(ticks):
        mom = momentum_bp(ticks, i, cfg.momentum_lookback_s)
        vol = realized_vol_bp(ticks, i, cfg.vol_window_s)
        out.append({
            "slug": t["slug"],
            "duration": t.get("duration"),
            "elapsed_s": t["elapsed_s"],
            "computed_at": now,
            "up_mid": t.get("up_mid"),
            "up_best_bid": t.get("up_bid"),
            "up_best_ask": t.get("up_ask"),
            "up_best_bid_size": t.get("bid_size"),
            "up_best_ask_size": t.get("ask_size"),
            "book_imbalance": book_imbalance(t.get("bid_size"), t.get("ask_size")),
            "size_at_ask": t.get("ask_size"),
            "spot_momentum_bp": mom,
            "spot_displacement_bp": displacement_bp(ticks, i),
            "regime_label": classify_regime(mom, vol, cfg),
            "feature_version": cfg.version,
        })
    return out


# ── Async DB layer (loads ticks, writes features) ────────────────────────────

# Snapshot is the spine (has up_mid, btc_price, up_bid/ask); order-book depth is
# joined by NEAREST capture time within a small tolerance, because the collector
# writes the snapshot and the book on the same tick but a second or two apart.
_WINDOW_SQL = """
SELECT s.slug, s.duration, s.elapsed_s, s.ts,
       s.up_mid, s.up_bid, s.up_ask, s.btc_price,
       bd.up_best_ask_size AS ask_size,
       bd.up_best_bid_size AS bid_size
FROM snapshots s
LEFT JOIN LATERAL (
    SELECT up_best_ask_size, up_best_bid_size
    FROM book_depth b
    WHERE b.slug = s.slug
      AND b.captured_at BETWEEN s.ts - interval '5 seconds'
                            AND s.ts + interval '5 seconds'
    ORDER BY abs(extract(epoch FROM (b.captured_at - s.ts)))
    LIMIT 1
) bd ON true
WHERE s.slug = $1
  AND s.elapsed_s BETWEEN 0 AND 300
ORDER BY s.elapsed_s
"""

_RECENT_SLUGS_SQL = """
SELECT slug FROM markets
WHERE window_ts IS NOT NULL
ORDER BY window_ts DESC
LIMIT $1
"""

_UPSERT_SQL = """
INSERT INTO research.features
    (slug, duration, elapsed_s, computed_at, up_mid, up_best_bid, up_best_ask,
     up_best_bid_size, up_best_ask_size, book_imbalance, size_at_ask,
     spot_momentum_bp, spot_displacement_bp, regime_label, feature_version)
VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12,$13,$14,$15)
ON CONFLICT (slug, elapsed_s) DO UPDATE SET
    computed_at          = EXCLUDED.computed_at,
    up_mid               = EXCLUDED.up_mid,
    up_best_bid          = EXCLUDED.up_best_bid,
    up_best_ask          = EXCLUDED.up_best_ask,
    up_best_bid_size     = EXCLUDED.up_best_bid_size,
    up_best_ask_size     = EXCLUDED.up_best_ask_size,
    book_imbalance       = EXCLUDED.book_imbalance,
    size_at_ask          = EXCLUDED.size_at_ask,
    spot_momentum_bp     = EXCLUDED.spot_momentum_bp,
    spot_displacement_bp = EXCLUDED.spot_displacement_bp,
    regime_label         = EXCLUDED.regime_label,
    feature_version      = EXCLUDED.feature_version
"""


async def run_features(max_windows: int = 300, cfg: FeatureConfig = None) -> dict:
    """Compute + upsert features for the most recent `max_windows` windows.
    Idempotent. Returns a small summary. Reads raw tables read-only; writes only
    to research.features."""
    from app.database.pool import research_ro, research_rw
    cfg = cfg or FeatureConfig()

    slugs = [r["slug"] for r in await research_ro.fetch(_RECENT_SLUGS_SQL, max_windows)]
    windows = 0
    rows_written = 0
    for slug in slugs:
        recs = await research_ro.fetch(_WINDOW_SQL, slug)
        if not recs:
            continue
        ticks = [{
            "slug": r["slug"], "duration": r["duration"], "elapsed_s": r["elapsed_s"],
            "btc_price": r["btc_price"], "up_mid": r["up_mid"],
            "up_bid": r["up_bid"], "up_ask": r["up_ask"],
            "bid_size": r["bid_size"], "ask_size": r["ask_size"],
        } for r in recs]
        feats = compute_window_features(ticks, cfg)
        for f in feats:
            await research_rw.execute_write(
                _UPSERT_SQL,
                f["slug"], f["duration"], f["elapsed_s"], f["computed_at"],
                f["up_mid"], f["up_best_bid"], f["up_best_ask"],
                f["up_best_bid_size"], f["up_best_ask_size"], f["book_imbalance"],
                f["size_at_ask"], f["spot_momentum_bp"], f["spot_displacement_bp"],
                f["regime_label"], f["feature_version"],
            )
            rows_written += 1
        windows += 1
    logger.info("features: %d windows, %d rows upserted", windows, rows_written)
    return {"windows": windows, "rows": rows_written, "version": cfg.version}
