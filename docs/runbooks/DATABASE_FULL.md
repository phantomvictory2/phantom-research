# Runbook — Database Full

**Alert:** `Research_DB storage ≥85% — CRITICAL`

**Why this is severe:** when the volume hit 100% on 17 July, an INSERT failed,
the collector's transaction aborted, and it looped for 60 hours writing nothing
while Railway reported "Online". **The collector cannot self-heal from a full
disk** — it needs space *and* a restart.

## Act immediately

1. **Resize the volume.** Railway → Research_DB → Settings → Volume → Live
   Resize. Current 5GB; growth ~27MB/day. Resizing is non-destructive.
2. **Restart the collector** afterwards, even if it looks Online.
3. **Verify rows resume** (see COLLECTOR_DOWN.md).

## Then reduce pressure

- Contaminated trades (~17.4%) are excluded by the clean views but still stored.
  They are kept deliberately — **do not delete raw data**.
- Run a backup before any cleanup: `python scripts/backup_db.py`.
- If cadence was recently increased, reconsider: 7s → 1s multiplies storage ~7×
  (≈190MB/day), which exhausts 5GB in under a month.

## Prevent

The research engine warns at 70% and pages at 85% (`STORAGE_WARNING_PCT` /
`STORAGE_CRITICAL_PCT`). Railway's own usage alerts are Pro-plan only.
