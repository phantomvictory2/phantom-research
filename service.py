#!/usr/bin/env python3
"""
service.py — long-running entry point for the Phantom Research Engine.

Runs migrations once on boot, seeds hypotheses, then loops the collector
heartbeat forever. This is an OBSERVER: it holds no trading credentials and
cannot place orders.

Exists because the heartbeat must run continuously — the 2026-07-17 outage was
invisible for ~60h precisely because nothing was watching data arrival.
"""

import asyncio
import glob
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.config.settings import settings                    # noqa: E402
from app.database.pool import research_rw, close_all        # noqa: E402
from app.monitoring.heartbeat import CollectorHeartbeat     # noqa: E402
from app.memory import hypotheses                           # noqa: E402
from app.quant.features import run_features                 # noqa: E402

# Recompute the feature layer every N heartbeat cycles (~10 min at 60s).
FEATURE_EVERY = 10

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
log = logging.getLogger("research.service")


async def bootstrap():
    """Idempotent: migrations + hypothesis seeding. Never fatal."""
    here = os.path.dirname(os.path.abspath(__file__))
    for f in sorted(glob.glob(os.path.join(here, "migrations", "*.sql"))):
        try:
            with open(f, "r", encoding="utf-8") as fh:
                await research_rw.execute_migration(fh.read())
            log.info("migration applied: %s", os.path.basename(f))
        except Exception as e:
            log.error("migration %s failed: %s", os.path.basename(f), e)
    try:
        await hypotheses.seed_hypotheses()
        log.info("hypotheses seeded")
    except Exception as e:
        log.error("hypothesis seeding failed: %s", e)
    # One-shot FULL-HISTORY backfill when requested (FEATURE_BACKFILL=1). Batched
    # and throttled; safe to leave off after it completes. Fail-soft.
    if os.getenv("FEATURE_BACKFILL", "0") == "1":
        try:
            from app.quant.features import run_backfill
            summary = await run_backfill()
            log.info("feature backfill: %s", summary)
        except Exception as e:
            log.error("feature backfill failed: %s", e)

    # Populate the Phase 2 feature layer once on boot (bounded). Fail-soft.
    try:
        summary = await run_features(max_windows=60)
        log.info("features bootstrapped: %s", summary)
    except Exception as e:
        log.error("feature bootstrap failed: %s", e)


async def main():
    problems = settings.validate()
    if problems:
        for p in problems:
            log.error("config: %s", p)
        log.error("refusing to start with invalid configuration")
        return 1

    log.info("Phantom Research Engine starting (observer mode, no trading credentials)")
    await bootstrap()

    hb = CollectorHeartbeat()
    interval = settings.heartbeat_interval_s
    log.info("heartbeat loop every %ss", interval)

    cycle = 0
    while True:
        try:
            report = await hb.check()
            log.info("collector=%s trade_age=%ss snapshot_age=%ss trades_15m=%s",
                     report.status,
                     None if report.trade_age_s is None else int(report.trade_age_s),
                     None if report.snapshot_age_s is None else int(report.snapshot_age_s),
                     report.trades_last_15m)
        except Exception as e:
            # A monitoring failure must never kill the monitor.
            log.error("heartbeat check failed: %s", e, exc_info=True)

        # Keep the feature layer fresh on recent windows. Fail-soft; a feature
        # error must never stop the heartbeat.
        if cycle % FEATURE_EVERY == 0:
            try:
                summary = await run_features(max_windows=20)
                log.info("features refreshed: %s", summary)
            except Exception as e:
                log.error("feature refresh failed: %s", e)
        cycle += 1
        await asyncio.sleep(interval)


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(main()))
    except KeyboardInterrupt:
        log.info("shutting down")
