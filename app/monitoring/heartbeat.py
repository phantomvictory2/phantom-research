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
from app.monitoring.notifier import Notifier

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
    (SELECT count(*) FROM snapshots WHERE ts       > now() - interval '15 minutes') AS snapshots_15m
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

        # Trades and snapshots are the live signals. Resolutions arrive once per
        # window and lag by design, so they inform but never drive the status.
        trade_status = self.thresholds.classify(trade_age)
        snap_status = self.thresholds.classify(snap_age)
        order = ["HEALTHY", "WARNING", "STALE", "CRITICAL"]
        status = max([trade_status, snap_status], key=order.index)

        # Ingestion continuity: rows can be recent yet the rate collapsed.
        if status == "HEALTHY" and (trades_15m == 0 or snaps_15m == 0):
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
        if report.is_alerting():
            await self.notifier.alert(
                f"🔴 [RESEARCH] Collector {report.status}\n{report.summary()}",
                key="collector_health",
            )
        return report

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
