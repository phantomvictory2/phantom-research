"""
heartbeat.py — collector health monitoring.

This exists because of a real incident: on 2026-07-17 the Research_DB volume
filled, an INSERT failed, the collector's psycopg2 transaction aborted, and the
process spun in an error loop writing nothing for ~60 hours. Railway still
reported the service "Online" the entire time. ~60h of market data was lost and
nobody knew until a manual audit.

The check is deliberately based on DATA, not on process status: if rows are not
arriving, the collector is down — regardless of what any dashboard claims.
"""

import logging
from dataclasses import dataclass, asdict
from typing import Optional

from app.config.settings import settings
from app.database.pool import research_ro, research_rw
from app.monitoring.notifier import Notifier, WARNING, CRITICAL

logger = logging.getLogger("research.heartbeat")


@dataclass
class HealthReport:
    status: str                       # worst of the component statuses
    trade_age_s: Optional[float]
    snapshot_age_s: Optional[float]
    resolution_age_s: Optional[float]
    trades_last_15m: int
    snapshots_last_15m: int
    detail: dict

    def is_alerting(self) -> bool:
        return self.status in ("STALE", "CRITICAL")

    def summary(self) -> str:
        def fmt(v):
            return "n/a" if v is None else f"{v:.0f}s"
        return (
            f"COLLECTOR_STATUS = {self.status}\n"
            f"LAST_TRADE_AGE = {fmt(self.trade_age_s)}\n"
            f"LAST_SNAPSHOT_AGE = {fmt(self.snapshot_age_s)}\n"
            f"LAST_RESOLUTION_AGE = {fmt(self.resolution_age_s)}\n"
            f"TRADES_15M = {self.trades_last_15m}\n"
            f"SNAPSHOTS_15M = {self.snapshots_last_15m}"
        )


_HEALTH_SQL = """
SELECT
    (SELECT EXTRACT(EPOCH FROM (now() - max(trade_ts)))   FROM trades)      AS trade_age_s,
    (SELECT EXTRACT(EPOCH FROM (now() - max(ts)))         FROM snapshots)   AS snapshot_age_s,
    (SELECT EXTRACT(EPOCH FROM (now() - max(resolved_at))) FROM resolutions) AS resolution_age_s,
    (SELECT count(*) FROM trades    WHERE trade_ts > now() - interval '15 minutes') AS trades_15m,
    (SELECT count(*) FROM snapshots WHERE ts       > now() - interval '15 minutes') AS snapshots_15m,
    (SELECT pg_database_size(current_database())) AS db_bytes
"""


class CollectorHeartbeat:
    def __init__(self, notifier: Optional[Notifier] = None):
        self.notifier = notifier or Notifier()
        self.thresholds = settings.thresholds

    async def check(self) -> HealthReport:
        row = await research_ro.fetchrow(_HEALTH_SQL)

        trade_age = float(row["trade_age_s"]) if row["trade_age_s"] is not None else None
        snap_age = float(row["snapshot_age_s"]) if row["snapshot_age_s"] is not None else None
        res_age = float(row["resolution_age_s"]) if row["resolution_age_s"] is not None else None
        trades_15m = int(row["trades_15m"] or 0)
        snaps_15m = int(row["snapshots_15m"] or 0)

        # SNAPSHOTS are the collector's own pulse: it writes one every ~5-7s
        # regardless of market activity, so snapshot age is a true health signal.
        #
        # TRADE age is NOT. Trades are market-driven and legitimately bursty —
        # ~73% of volume lands in the first 60s of a window, then the book can
        # sit quiet for minutes. Treating trade_age as a health signal produced
        # a permanent WARNING on a perfectly healthy collector (observed
        # 2026-07-20: snapshot_age 1-5s, 556 trades/15min, yet trade_age 256-317s).
        # A monitor that cries wolf is as useless as no monitor, so trade health
        # is measured by ARRIVAL RATE (rows in the last 15 min), not recency.
        order = ["HEALTHY", "WARNING", "STALE", "CRITICAL"]
        snap_status = self.thresholds.classify(snap_age)
        trade_status = "HEALTHY" if trades_15m > 0 else self.thresholds.classify(trade_age)
        status = max([trade_status, snap_status], key=order.index)

        # Ingestion continuity: snapshots recent but the rate collapsed.
        if status == "HEALTHY" and snaps_15m == 0:
            status = "WARNING"

        detail = {
            "trade_status": trade_status,
            "snapshot_status": snap_status,
            "resolution_status": self.thresholds.classify(res_age),
            "thresholds": asdict(self.thresholds),
        }
        report = HealthReport(
            status=status,
            trade_age_s=trade_age,
            snapshot_age_s=snap_age,
            resolution_age_s=res_age,
            trades_last_15m=trades_15m,
            snapshots_last_15m=snaps_15m,
            detail=detail,
        )
        await self._persist(report)

        # Severity mapping: STALE is a warning, CRITICAL pages. A CRITICAL here
        # means data has stopped arriving — the 2026-07-17 failure mode.
        if report.status == "CRITICAL":
            await self.notifier.alert(
                f"Collector CRITICAL — data has stopped arriving.\n{report.summary()}",
                key="collector_health", severity=CRITICAL)
        elif report.status == "STALE":
            await self.notifier.alert(
                f"Collector STALE.\n{report.summary()}",
                key="collector_health", severity=WARNING)
        elif report.status == "WARNING":
            await self.notifier.alert(
                f"Collector degraded.\n{report.summary()}",
                key="collector_health", severity=WARNING)

        await self._check_storage(row)
        return report

    async def _check_storage(self, row):
        """Storage headroom. The volume filling to 100% is precisely what caused
        the 2026-07-17 outage, and Railway's own usage alerts are Pro-plan only —
        so we monitor it ourselves."""
        try:
            db_bytes = int(row["db_bytes"] or 0)
        except (KeyError, TypeError):
            return
        cap = settings.storage_capacity_mb * 1024 * 1024
        if cap <= 0:
            return
        pct = db_bytes / cap * 100.0
        mb = db_bytes / 1024 / 1024
        msg = (f"Research_DB storage {pct:.1f}% of {settings.storage_capacity_mb}MB "
               f"({mb:.0f}MB used)")
        if pct >= settings.storage_critical_pct:
            await self.notifier.alert(
                msg + " — CRITICAL. Writes will fail when full; the collector "
                      "cannot self-heal from this.",
                key="db_storage", severity=CRITICAL)
        elif pct >= settings.storage_warning_pct:
            await self.notifier.alert(msg + " — approaching capacity.",
                                      key="db_storage", severity=WARNING)

    async def _persist(self, r: HealthReport):
        """Record every check. Failure to record must never crash the monitor."""
        try:
            import json
            await research_rw.execute_write(
                """
                INSERT INTO research.system_health
                    (component, status, trade_age_s, snapshot_age_s,
                     resolution_age_s, rows_last_15m, detail)
                VALUES ('collector', $1::research.health_status, $2, $3, $4, $5, $6::jsonb)
                """,
                r.status, r.trade_age_s, r.snapshot_age_s, r.resolution_age_s,
                r.trades_last_15m, json.dumps(r.detail),
            )
        except Exception as e:
            logger.error("failed to persist health check: %s", e)
