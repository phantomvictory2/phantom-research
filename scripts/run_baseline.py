#!/usr/bin/env python3
"""Run the Phase 1 baseline: health check, data quality, analytics, report."""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.settings import settings              # noqa: E402
from app.database.pool import close_all               # noqa: E402
from app.memory import hypotheses                     # noqa: E402
from app.reports import baseline_report               # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("baseline")


async def main():
    problems = settings.validate()
    if problems:
        for p in problems:
            log.error("config: %s", p)
        return 1

    log.info("seeding research hypotheses …")
    await hypotheses.seed_hypotheses()

    log.info("generating baseline report …")
    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    path = await baseline_report.generate(os.path.join(here, "reports", "baseline_report.md"))
    log.info("done → %s", path)

    await close_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
