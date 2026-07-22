#!/usr/bin/env python3
"""Compute + upsert the Phase 2 feature layer into research.features.

Idempotent and safe to re-run / schedule. Reads raw tables read-only; writes only
to research.features. Run after migrations so the table exists.

    python scripts/run_features.py [max_windows]
"""

import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.config.settings import settings          # noqa: E402
from app.database.pool import close_all            # noqa: E402
from app.quant.features import run_features         # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("run_features")


async def main() -> int:
    problems = settings.validate()
    if problems:
        for p in problems:
            log.error("config: %s", p)
        return 1

    max_windows = int(sys.argv[1]) if len(sys.argv) > 1 else 300
    summary = await run_features(max_windows=max_windows)
    log.info("done: %s", summary)
    await close_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
