# Disaster Recovery — Research_DB

**Status: backups are NOT automated.** Railway backups and PITR require the Pro
plan (verified 2026-07-20: *"Backups and point-in-time recovery (PITR) are only
available for customers on the Pro plan"*, schedule reads **"No backup schedule"**).

**What is at risk:** ~680k trades, ~120k snapshots, ~2,800 resolved markets.
**This data cannot be re-collected** — Polymarket does not serve deep history,
and the 17–19 July outage already proved gaps are permanent. A volume failure
today loses everything.

## Backup

```bash
export RESEARCH_DB_URL="<Research_DB connection string>"
python scripts/backup_db.py --out ./backups --keep 7
```

Produces a compressed `pg_dump` custom-format archive (~350MB DB → ~60–90MB) and
verifies it is readable by `pg_restore --list`. A dump under 1MB is rejected as
a failed backup rather than silently kept.

**Recommended cadence:** daily. Options, cheapest first:

| Option | Cost | Durability |
|---|---|---|
| Manual/local run | free | depends on your machine |
| Railway volume attached to `phantom-research` + cron | ~free | survives DB volume loss **(recommended)** |
| Railway Pro plan | paid | automated + PITR **(APPROVAL REQUIRED)** |

## Restore

```bash
# 1. verify the archive first
python scripts/backup_db.py --verify backups/research_<stamp>.dump

# 2. restore into a SCRATCH database — never straight over production
createdb research_restore_test
pg_restore -d research_restore_test --no-owner --no-acl backups/research_<stamp>.dump

# 3. confirm the data is actually there
psql research_restore_test -c "SELECT count(*) FROM trades;"
psql research_restore_test -c "SELECT max(trade_ts) FROM trades;"
psql research_restore_test -c "SELECT count(*) FROM research.research_findings;"
```

## ⚠️ A backup is not a backup until a restore has been tested

`--verify` proves the archive is *readable*, not that it *restores*. Run the full
restore drill above **at least quarterly** and record the date here.

| Date | Archive | Restored rows | Result | By |
|---|---|---|---|---|
| _(none yet — first drill outstanding)_ | | | | |
