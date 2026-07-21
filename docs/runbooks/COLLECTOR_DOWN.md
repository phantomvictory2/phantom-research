# Runbook — Collector Down

**Alert:** `Collector CRITICAL — data has stopped arriving`

## Diagnose (in order)

1. **Is data actually stopped?** Process status lies — check the data.
   ```sql
   SELECT now(),
          (SELECT max(ts) FROM snapshots) AS last_snapshot,
          (SELECT count(*) FROM snapshots WHERE ts > now() - interval '15 min') AS snaps_15m;
   ```
   Snapshots are the collector's pulse (~5–7s). Trades are bursty and may
   legitimately be minutes old — **do not diagnose from trade age**.

2. **Is the volume full?** This caused the 60-hour outage of 17–19 July.
   Railway → Research_DB → Metrics → Volume Usage. At 100%, writes fail.

3. **Read the logs.** Railway → phantom-collector → Deploy Logs.
   Look for `InFailedSqlTransaction` — the historical failure mode.

## Fix

| Symptom | Action |
|---|---|
| Volume at/near 100% | Resize volume (Settings → Volume → Live Resize), **then restart the collector** — it does not self-heal |
| `InFailedSqlTransaction` loop | Restart the service. The rollback handler (commit `169fd61`) should now prevent recurrence — if it recurs, that fix has regressed |
| Process crashed | Restart; check for a bad deploy and roll back if needed |
| DB unreachable | Check Research_DB is Online; check connection limits |

## Verify recovery — do not trust "Online"

```sql
SELECT count(*) FROM trades WHERE trade_ts > now() - interval '5 minutes';
```
Expect roughly 50–150. Zero means it is still down regardless of what Railway
shows. Confirm `research.system_health` returns to HEALTHY within ~2 minutes.

## Post-incident

Record the gap: the research engine flags collection gaps automatically, and any
gap over 30 minutes should be noted in the affected analyses — it is
unrecoverable data, not market behaviour.
