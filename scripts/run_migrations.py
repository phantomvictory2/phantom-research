#!/usr/bin/env python3
"""Apply research schema migrations. Safe to re-run (idempotent DDL)."""

import asyncio
import glob
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.settings import settings          # noqa: E402
from app.database.pool import research_rw, close_all  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("migrate")


async def main():
    problems = settings.validate()
    if problems:
        for p in problems:
            log.error("config: %s", p)
        return 1

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    files = sorted(glob.glob(os.path.join(here, "migrations", "*.sql")))
    if not files:
        log.error("no migration files found")
        return 1

    for f in files:
        name = os.path.basename(f)
        log.info("applying %s …", name)
        with open(f, "r", encoding="utf-8") as fh:
            sql = fh.read()
        await research_rw.execute_migration(sql)
        log.info("  ✓ %s applied", name)

    await close_all()
    log.info("migrations complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
