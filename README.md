# Phantom Quant Research Intelligence Engine

**Phase 1 — Observer.** Independent research service. It reads market data and
Phantom V2 outcomes, classifies data quality, monitors collector health, and
produces research reports.

## Non-negotiable boundaries

- **Observer, not controller.** No runtime path from Phantom V2 into this service.
- **No trading credentials.** This service cannot place an order even if compromised.
- **Read-only** on raw collector tables and Phantom V2 tables. Writes only to `research.*`.
- **Capped connection pool** (max 5, default 3) so research can never starve the
  collector or the trading bot.
- **No LLM** in any feed/signal/risk/execution path.

If this service crashes, Phantom V2 continues. If the AI API fails, Phantom V2
continues. If this database fails, Phantom V2 continues.

## Setup

```bash
cp .env.example .env      # fill RESEARCH_DB_URL, PHANTOM_DB_URL
pip install -r requirements.txt
python scripts/run_migrations.py   # creates research schema + clean views
python scripts/run_baseline.py     # health + quality + analytics + report
pytest -q                          # 14 tests
```

Output: `reports/baseline_report.md`

## Why the heartbeat exists

On 2026-07-17 the Research_DB volume filled. An INSERT failed, the collector's
transaction aborted, and because `collector.py` never rolled back it spun in an
error loop writing nothing for ~60 hours while Railway reported it "Online".
~60h of market data was lost. The heartbeat checks *data arrival*, not process
status, so that failure mode is detected in minutes rather than days.
