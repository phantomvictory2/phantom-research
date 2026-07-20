# Phantom Bot — Project Briefing for Independent Research Analysis

Prepared for: Claude Fable 5, acting as an independent top-level research analyst
Prepared by: Claude (Sonnet 5), Cowork session, July 15, 2026
Purpose: Hand off full project context so Fable 5 can re-analyze the raw data independently and propose new trading strategy ideas for a Polymarket 5-minute BTC up/down "phantom bot" — without being anchored to conclusions already reached below.

---

## 1. What this project is

The user runs a bot ("phantom-collector") on Railway that continuously records every 5-minute BTC up/down market on Polymarket: market metadata, resolutions (outcomes), individual trades, and periodic order-book snapshots. The goal is to mine this data for a tradable edge for a future "phantom bot" that would actually trade these markets.

## 2. URLs and access

- **Live research dashboard (Streamlit, v4):** https://phantom-dashboard-production-af0e.up.railway.app
  Tabs: Data Trust, Markets, Structure, Winners, Wallets, Strategy Lab (interactive backtester), Compare. Auto-refreshes from the live database (60s cache).
- **Railway project:** "Phantom Research Collector" — two services:
  - `phantom-collector` — runs `collector.py`, the always-on data collector. Do not touch.
  - `phantom-dashboard` — runs the Streamlit dashboard above, shares the same database.
- **GitHub repo (source of truth, actually deployed):** `github.com/phantomvictory2/phantom-collector` — contains `collector.py`, `dashboard.py` (v4), `railway.toml`, `railway.dashboard.toml`, `requirements.txt`.
- **Database:** Postgres on Railway, referenced internally as `DATABASE_URL`, shared between both services. Not exposed publicly outside Railway's network — Fable 5 will need either the dashboard's Strategy Lab UI or direct DB access (if given credentials separately) to run its own queries.

## 3. Database schema

Four tables, all keyed by market `slug` (one slug = one 5-minute BTC up/down window):

- **markets** (~2,250 rows) — one row per window: `slug`, `condition_id`, `token_up`, `token_down`, `window_ts`, `open_time`, `close_time`, `duration` (always "5m").
- **resolutions** (~2,248 rows, 100% coverage) — outcome per window: `slug`, `winner` (UP/DOWN), `open_price`, `close_price`, `resolved_at`, `winner_source`, `btc_open`, `btc_close`.
- **trades** (~442,000+ rows and growing) — every individual fill: `id`, `slug`, `tx_hash`, `wallet`, `side`, `price`, `size`, `usdc` (notional, NOT column named "usd"), `is_maker`, `trade_ts`, `elapsed_s` (seconds into the 5-min window), `created_at`, `duration`.
- **snapshots** (~86,000+ rows) — periodic order-book snapshots: `id`, `slug`, `duration`, `ts`, `elapsed_s`, `up_bid`, `up_ask`, `up_mid`, `down_mid` (note: no `down_bid`/`down_ask` columns exist), `btc_price`.

Data collected covers roughly July 7–15, 2026 (~8 days) at the time of this briefing, continuously growing.

## 4. Known data quality issues (important — check these before trusting any query)

- **~21% of trades (~89,000+ rows) are "contaminated"** — their `trade_ts` falls outside their market's `open_time`–`close_time` window. This is a known artifact from before a "collector v3" rewrite (possibly trades backfilled with timestamps after the outcome was already known). Always filter with `t.trade_ts BETWEEN m.open_time AND m.close_time` when precision matters, or check the dashboard's Data Trust tab.
- **Some wallets' trades don't join to any row in `markets`** — they reference slugs with a resolution but no corresponding market record, meaning their timing can't be verified at all.
- **The dashboard's `resolved_trades()` query used to have a hardcoded 250,000-row `LIMIT` with no `ORDER BY`**, making results non-deterministic — this was fixed in the current v4 dashboard.py (`ORDER BY t.trade_ts DESC` before the limit), but be aware if pulling from any older dashboard version.
- **Duplicate-insert incident:** during this session's deployment work, a duplicate `collector.py` process briefly ran twice for under a minute each time before being caught and stopped, inserting a handful of extra trades. Immaterial at this data volume but technically present.

## 5. What's already been found (prior analysis — treat as a starting point, not the final word)

### 5.1 Base rates
Of 2,110 resolved markets: DOWN won 50.3%, UP won 49.7%. No inherent directional bias — as expected for short-horizon BTC.

### 5.2 Liquidity distribution (where trading actually happens)
Heavily front-loaded: ~73% of all trade volume happens in the first 60 seconds of each 5-minute window. Only 32 trades total (across 2,114+ windows) have ever occurred in the final 15 seconds. Any strategy relying on late-window execution has essentially no liquidity to trade against.

| Phase | Trades | Volume (USDC) |
|---|---|---|
| 0–60s | 289,316 | ~$4.99M |
| 60–180s | 89,988 | ~$1.34M |
| 180–285s | 18,804 | ~$294K |
| 285–300s | 32 | ~$615 |

### 5.3 Price convergence
Average price paid for the eventual winning side climbs gradually from ~53¢ near t=0 to ~88¢ by t=270s — no single "reveal" moment, just steady informational convergence. This gradual, imperfect convergence is the most plausible place a real edge could live.

| Elapsed | Avg winning-side price |
|---|---|
| 0–30s | 0.53 |
| 60–90s | 0.63 |
| 120–150s | 0.72 |
| 210–240s | 0.84 |
| 270–300s | 0.88 |

### 5.4 Strategies already tested (and their results)
- **Crowd-following (volume-weighted majority):** even at >70% volume concentration on one side, that side only wins ~55–56% of the time — not enough margin to clear fees. Weak signal alone.
- **"LAST_SHADOW" (bet near-certain side, final 15s, price ≥0.97):** only 18 trades ever qualified across all history — unexecutable at any real size, and lost money on the few fills that did happen. Liquidity-starved, not a real strategy.
- **"Mid-window momentum" (elapsed 120–240s, price 0.60–0.85, either side):** full-sample backtest showed 76.1% win rate and +$3,722 net PnL after 100bps fees — looked promising. But splitting the ~8-day sample in half revealed the *entire* profit came from the second half; the first half actually lost money (-$198) despite a 71% win rate. This strongly suggests the aggregate result reflects a lucky/trending stretch of BTC volatility rather than a stable structural edge. Not validated as repeatable.
- **Wallet leaderboard:** the top 2 "highest PnL" wallets on the platform are data artifacts, not skilled traders — one had only 2 of 52 trades inside a valid market window (the rest contaminated), the other's 22 trades don't match any market record at all. Any wallet-level analysis needs contamination filtering first.

### 5.5 Bottom line from prior analysis
No strategy tested so far has a validated, stable edge over an ~8-day sample. The most reliable finding is structural (liquidity concentrated in the first 60 seconds, dead after 285s) rather than directional/predictive.

## 6. What Fable 5 is being asked to do

Using the schema, known data quality caveats, and prior findings above as context (not as constraints), independently analyze the underlying trade/market/snapshot/resolution data — via the live dashboard's Strategy Lab or direct queries if credentials are provided separately — and propose new hypotheses or strategies that haven't been tested yet. Areas that have NOT been explored in the analysis above and may be worth a fresh look:
- Order-book microstructure from `snapshots` (bid-ask spread dynamics, `up_mid` vs `down_mid` divergence) rather than just trade-level data.
- Maker vs. taker (`is_maker`) behavior differences.
- Cross-window correlation — does one window's outcome or volatility predict the next window's behavior?
- Wallet-level behavioral clustering (excluding contaminated wallets) — are there consistently profitable non-corrupted wallets worth reverse-engineering?
- Time-of-day / day-of-week effects now that more data may have accumulated since this briefing.
- Whether walk-forward validation (train on days 1–4, test on days 5–8, roll forward) changes the "mid-window momentum" conclusion above.

The dataset is continuously growing (collector runs live), so any new analysis should note the data window it covers.
