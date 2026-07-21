#!/usr/bin/env python3
"""
backup_db.py — logical backup of Research_DB.

WHY THIS EXISTS
Railway's automated backups and PITR require the Pro plan (verified 2026-07-20:
"Backups and point-in-time recovery (PITR) are only available for customers on
the Pro plan", schedule shows "No backup schedule"). Research_DB holds ~680k
trades and ~120k snapshots that CANNOT be re-collected — Polymarket does not
serve deep history. A volume failure today loses all of it.

This provides a free, plan-independent logical backup using pg_dump.

USAGE
    python scripts/backup_db.py --out /path/to/backups
    python scripts/backup_db.py --out /data/backups --keep 7
    python scripts/backup_db.py --verify /data/backups/research_YYYYmmdd.dump

IMPORTANT
A backup is not a backup until a RESTORE has been tested. Use --verify, and see
docs/DISASTER_RECOVERY.md for the full restore procedure.

Storage: a ~350MB database dumps to roughly 60-90MB compressed.
"""

import argparse
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path


def dsn() -> str:
    d = os.getenv("RESEARCH_DB_URL") or os.getenv("DATABASE_URL")
    if not d:
        print("ERROR: set RESEARCH_DB_URL (or DATABASE_URL)", file=sys.stderr)
        sys.exit(2)
    return d


def run(cmd, **kw):
    return subprocess.run(cmd, check=False, capture_output=True, text=True, **kw)


def backup(out_dir: Path, keep: int) -> int:
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = out_dir / f"research_{stamp}.dump"

    # custom format (-Fc): compressed, selective restore, pg_restore compatible
    print(f"dumping -> {target}")
    r = run(["pg_dump", "-Fc", "-Z", "6", "--no-owner", "--no-acl",
             "-f", str(target), dsn()])
    if r.returncode != 0:
        print(f"pg_dump FAILED:\n{r.stderr}", file=sys.stderr)
        if target.exists():
            target.unlink()          # never leave a partial dump looking valid
        return 1

    size_mb = target.stat().st_size / 1024 / 1024
    if size_mb < 1:
        print(f"ERROR: dump is only {size_mb:.2f}MB — suspiciously small, treating "
              f"as failed", file=sys.stderr)
        target.unlink()
        return 1
    print(f"✓ dump complete: {target.name} ({size_mb:.1f}MB)")

    # integrity: pg_restore --list must parse the archive
    v = run(["pg_restore", "--list", str(target)])
    if v.returncode != 0:
        print(f"ERROR: dump is unreadable by pg_restore:\n{v.stderr}", file=sys.stderr)
        return 1
    tables = sum(1 for line in v.stdout.splitlines() if " TABLE DATA " in line)
    print(f"✓ archive verified readable — {tables} table(s) with data")

    # retention
    dumps = sorted(out_dir.glob("research_*.dump"))
    for old in dumps[:-keep] if keep > 0 else []:
        print(f"  pruning old backup {old.name}")
        old.unlink()
    print(f"✓ retention: {min(len(dumps), keep)} backup(s) kept")
    return 0


def verify(path: Path) -> int:
    """Structural verification. A FULL restore test into a scratch database is
    the only complete verification — see docs/DISASTER_RECOVERY.md."""
    if not path.exists():
        print(f"ERROR: {path} not found", file=sys.stderr)
        return 1
    r = run(["pg_restore", "--list", str(path)])
    if r.returncode != 0:
        print(f"CORRUPT: {r.stderr}", file=sys.stderr)
        return 1
    lines = r.stdout.splitlines()
    tables = [l for l in lines if " TABLE DATA " in l]
    print(f"✓ {path.name} is readable")
    print(f"  {len(tables)} tables with data, {len(lines)} archive entries")
    for t in tables[:12]:
        print(f"    {t.split()[-2] if len(t.split())>2 else t}")
    print("\nNOTE: this verifies the archive is READABLE, not that it RESTORES "
          "correctly.\nRun the full restore drill in docs/DISASTER_RECOVERY.md "
          "at least once per quarter.")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="Research_DB logical backup")
    ap.add_argument("--out", type=Path, default=Path("./backups"))
    ap.add_argument("--keep", type=int, default=7, help="backups to retain (0=all)")
    ap.add_argument("--verify", type=Path, help="verify an existing dump instead")
    a = ap.parse_args()
    return verify(a.verify) if a.verify else backup(a.out, a.keep)


if __name__ == "__main__":
    sys.exit(main())
