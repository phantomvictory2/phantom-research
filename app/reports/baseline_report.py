"""
baseline_report.py — generates the PHANTOM QUANT RESEARCH REPORT — BASELINE.

Discipline enforced in the output:
  • Every section states its sample size and data period.
  • Findings are labelled OBSERVATIONAL unless they have passed statistical
    validation. Phase 1 produces mostly OBSERVATIONAL results and says so.
  • Limitations are stated, not buried.
"""

import logging
from datetime import datetime, timezone

from app.quant import baseline
from app.data_quality.checks import DataQualityEngine
from app.monitoring.heartbeat import CollectorHeartbeat
from app.memory import hypotheses

logger = logging.getLogger("research.report")


def _table(headers, rows) -> str:
    if not rows:
        return "_no data_\n"
    out = "| " + " | ".join(headers) + " |\n"
    out += "|" + "|".join(["---"] * len(headers)) + "|\n"
    for r in rows:
        out += "| " + " | ".join("" if v is None else str(v) for v in r) + " |\n"
    return out


async def generate(path: str = "reports/baseline_report.md") -> str:
    ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")

    health = await CollectorHeartbeat().check()
    dq = await DataQualityEngine().run_all()
    cov = await baseline.coverage()
    mkt = await baseline.market_stats()
    conv = await baseline.price_convergence()
    align = await baseline.btc_poly_alignment()
    align_ttr = await baseline.btc_poly_by_ttr()
    beh = await baseline.trade_behaviour()
    timing = await baseline.trade_timing()
    strat = await baseline.strategy_outcomes()
    hyps = await hypotheses.list_hypotheses()

    period = f"{cov.get('first_trade')} → {cov.get('last_trade')}"
    span = cov.get("span_days") or 0

    md = f"""# PHANTOM QUANT RESEARCH REPORT — BASELINE

**Generated:** {ts}
**Data period:** {period} (~{span:.1f} days)
**Engine:** phantom-research (Phase 1) — observer only, no execution authority

> All Phase 1 findings are **OBSERVATIONAL** unless explicitly labelled otherwise.
> An observation is not an edge. Nothing here has survived out-of-sample testing
> or realistic execution costs.

---

## 1. Data Coverage

| Metric | Value |
|---|---|
| Markets | {cov.get('markets'):,} |
| Resolutions | {cov.get('resolutions'):,} |
| Trades (raw) | {cov.get('trades'):,} |
| Trades (clean) | {cov.get('clean_trades'):,} ({cov.get('clean_trade_pct')}%) |
| Snapshots (raw) | {cov.get('snapshots'):,} |
| Snapshots (clean) | {cov.get('clean_snapshots'):,} |
| Database size | {cov.get('db_size')} |

## 2. Collector Health

```
{health.summary()}
```

## 3. Data Quality

{_table(["Check", "Affected", "Total", "%", "Severity"],
        [[d.check_name, f"{d.affected_rows:,}", f"{d.total_rows:,}",
          f"{d.pct:.2f}%", d.severity] for d in dq])}

## 4. Market Statistics

| Metric | Value |
|---|---|
| Resolved markets | {mkt.get('resolved'):,} |
| UP wins | {mkt.get('up_wins'):,} ({mkt.get('up_pct')}%) |
| DOWN wins | {mkt.get('down_wins'):,} ({mkt.get('down_pct')}%) |
| Mean abs BTC move | {mkt.get('avg_abs_move_bp')} bp |
| Median abs BTC move | {mkt.get('median_abs_move_bp')} bp |

## 5. Price Convergence (winning side)

Average price of the side that eventually won, by elapsed time.
Resolution used **only** as an outcome label — never as an input.

{_table(["Elapsed", "N", "Avg winner price"],
        [[f"{r['bucket_s']}s", f"{r['n']:,}", r['avg_winner_price']] for r in conv])}

## 6. BTC ↔ Polymarket Relationship

Measured at ~7-second snapshot resolution. **This cannot support sub-second
latency-arbitrage conclusions** — only coarse directional agreement.

| Metric | Value |
|---|---|
| Observations | {align.get('n'):,} |
| Direction agreement | {align.get('aligned_pct')}% |
| Observations with \\|displacement\\| ≥ 5bp | {align.get('n_displaced'):,} |
| Agreement when displaced ≥ 5bp | {align.get('aligned_displaced_pct')}% |

{_table(["Elapsed", "N", "Agreement %"],
        [[f"{r['bucket_s']}s", f"{r['n']:,}", r['aligned_pct']] for r in align_ttr])}

## 7. Trade Behaviour

| Metric | Value |
|---|---|
| Clean trades | {beh.get('n'):,} |
| Unique wallets | {beh.get('unique_wallets'):,} |
| Mean size | ${beh.get('avg_usdc')} |
| Median size | ${beh.get('median_usdc')} |
| Mean price | {beh.get('avg_price')} |
| Maker share | {beh.get('maker_pct')}% |

### Timing within the 5-minute window

{_table(["Phase", "Trades", "Volume (USDC)"],
        [[r['phase'], f"{r['n']:,}", f"{r['volume_usdc']:,}"] for r in timing])}

## 8. Phantom V2 Strategy Outcomes

{_table(["Strategy", "Trades", "Wins", "Losses", "Total PnL", "Avg PnL"],
        [[s['strategy_type'], s['trades'], s['wins'], s['losses'],
          s['total_pnl'], s['avg_pnl']] for s in strat.get('strategies', [])])}

### Skip reasons

{_table(["Reason", "Count"],
        [[s['skip_reason'], f"{s['n']:,}"] for s in strat.get('skip_reasons', [])])}

### Rejection reasons

{_table(["Reason", "Count"],
        [[s['rejection_reason'], f"{s['n']:,}"] for s in strat.get('rejection_reasons', [])])}

## 9. Registered Hypotheses

{_table(["ID", "Status", "Question"],
        [[h['id'], h['status'], h['question'][:90] + "…"] for h in hyps])}

## 10. Limitations

- **Snapshot resolution ~7s.** No sub-second microstructure conclusions are possible.
- **No BTC order book, volume, or bid/ask** — only spot price. Whole feature
  families (order-flow imbalance, aggressor side) are unavailable.
- **Single regime.** The dataset spans days, not months; regime-conditional
  claims have weak statistical power.
- **Known data gap 2026-07-17 → 2026-07-19** (collector outage, volume full).
  Unrecoverable; must not be read as a market phenomenon.
- **Displayed prices ≠ executable prices.** Nothing here models fills.
- **No MFE/MAE** recorded on Phantom V2 positions, so exit optimisation is
  not yet possible.

## 11. Recommended Next Experiments

1. Test **H003** (reversal rate vs displacement) — directly actionable for the
   Last Shadow displacement gate, and cheap with existing data.
2. Test **H005** (late-window liquidity) — determines whether any late-entry
   strategy is executable at all.
3. Test **H006** (rejected vs accepted signals) — measures whether existing risk
   rules add value; uses data already collected.
4. Build the cost model from `execution_journal` so **H008** can be applied to
   every future candidate.

---
*Generated by phantom-research. Observer only — this engine holds no trading
credentials and cannot place orders.*
"""

    import os
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write(md)
    logger.info("report written to %s", path)
    return path
