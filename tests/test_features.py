"""
Phase 2 feature-engine tests — golden values and the no-look-ahead guarantee.

These are the two gates the architecture doc requires for Phase 2:
  • golden-value: known input -> known feature output
  • leakage: a feature at time t must never depend on data after t
The leakage test is structural: it recomputes each row against only the ticks up
to and including that tick and asserts the value is unchanged.
"""

import pytest

from app.quant.features import (
    FeatureConfig,
    book_imbalance,
    momentum_bp,
    displacement_bp,
    classify_regime,
    compute_window_features,
)


def _tick(elapsed_s, btc, bid_size=None, ask_size=None,
          up_mid=0.5, up_bid=0.49, up_ask=0.51):
    return {
        "slug": "btc-updown-5m-1", "duration": "5m", "elapsed_s": elapsed_s,
        "btc_price": btc, "up_mid": up_mid, "up_bid": up_bid, "up_ask": up_ask,
        "bid_size": bid_size, "ask_size": ask_size,
    }


# a clean fixture window: BTC flat then rising, so momentum/displacement are exact
WINDOW = [
    _tick(0,  100000.0, bid_size=1000, ask_size=800),
    _tick(5,  100000.0, bid_size=900,  ask_size=900),
    _tick(10, 100000.0, bid_size=500,  ask_size=1500),
    _tick(15, 100050.0, bid_size=1200, ask_size=600),
    _tick(20, 100100.0, bid_size=1000, ask_size=1000),
]


# ── pure helpers ─────────────────────────────────────────────────────────────

def test_book_imbalance_known_values():
    assert book_imbalance(1000, 800) == pytest.approx(0.1111, abs=1e-4)
    assert book_imbalance(500, 1500) == pytest.approx(-0.5)
    assert book_imbalance(1000, 1000) == 0.0
    assert book_imbalance(None, 800) is None
    assert book_imbalance(0, 0) is None


def test_momentum_and_displacement_exact():
    # at elapsed=20, ref 15s earlier is elapsed<=5 => 100000; (100100-100000)/100000*1e4 = 10bp
    assert momentum_bp(WINDOW, 4, 15.0) == pytest.approx(10.0)
    # displacement from window open (100000) at elapsed=15 => 5bp
    assert displacement_bp(WINDOW, 3) == pytest.approx(5.0)
    # no reference 15s before elapsed=0 => momentum None
    assert momentum_bp(WINDOW, 0, 15.0) is None


def test_classify_regime_priority_and_thresholds():
    cfg = FeatureConfig()
    assert classify_regime(10.0, 1.0, cfg) == "TREND_UP"
    assert classify_regime(-10.0, 1.0, cfg) == "TREND_DOWN"
    assert classify_regime(0.5, 1.0, cfg) == "CHOP"
    assert classify_regime(None, 1.0, cfg) == "CHOP"
    # volatility outranks direction
    assert classify_regime(10.0, 99.0, cfg) == "VOLATILE"


# ── golden-value on the full window ──────────────────────────────────────────

def test_window_golden_values():
    rows = compute_window_features(WINDOW)
    assert len(rows) == 5
    r0, r4 = rows[0], rows[4]

    # tick 0: imbalance (1000-800)/1800, size_at_ask 800, no momentum yet
    assert r0["book_imbalance"] == pytest.approx(0.1111, abs=1e-4)
    assert r0["size_at_ask"] == 800
    assert r0["spot_momentum_bp"] is None
    assert r0["spot_displacement_bp"] == pytest.approx(0.0)
    assert r0["regime_label"] == "CHOP"
    assert r0["feature_version"] == "v1"

    # tick 4: +10bp momentum & displacement, balanced book, trending up
    assert r4["spot_momentum_bp"] == pytest.approx(10.0)
    assert r4["spot_displacement_bp"] == pytest.approx(10.0)
    assert r4["book_imbalance"] == pytest.approx(0.0)
    assert r4["regime_label"] == "TREND_UP"


# ── the leakage guarantee ────────────────────────────────────────────────────

def _strip(row):
    d = dict(row)
    d.pop("computed_at", None)   # timestamp metadata, not a feature input
    return d


def test_no_lookahead_each_row_depends_only_on_past():
    full = compute_window_features(WINDOW)
    for i in range(len(WINDOW)):
        truncated = compute_window_features(WINDOW[: i + 1])
        assert _strip(full[i]) == _strip(truncated[-1]), (
            f"row {i} changed when future ticks were removed — look-ahead leak"
        )


def test_mutating_a_future_tick_cannot_change_an_earlier_row():
    full = compute_window_features(WINDOW)
    poisoned = [dict(t) for t in WINDOW]
    poisoned[-1]["btc_price"] = 9_999_999.0   # absurd future value
    after = compute_window_features(poisoned)
    for i in range(len(WINDOW) - 1):           # every row except the last
        assert _strip(full[i]) == _strip(after[i])
