"""
checks.py — Data Quality Engine.

Principle: NEVER delete or mutate raw collector data. Problems are *classified*
and recorded in research.data_quality_events, and analysis code consumes a
filtered view so contaminated rows can't silently poison a conclusion.

Checks implemented (all measured against the live Research_DB):
  1. trades_outside_window   — trade_ts outside its market's open/close (~17.4%)
  2. trades_orphan_market    — trade references a slug with no markets row
  3. duplicate_trades        — same tx_hash+wallet+slug recorded more than once
  4. invalid_prices          — price outside (0,1) on trades/snapshots
  5. impossible_elapsed      — elapsed_s outside [0, duration]
  6. missing_btc_price       — snapshot without a BTC price (breaks cross-market work)
  7. missing_resolutions     — closed market with no resolution row
  8. collector_gaps          — periods with no snapshots (e.g. 2026-07-17→19 outage)
"""

import json
import logging
from dataclasses import dataclass
from typing import List

from app.config.settings import settings
from app.database.pool import research_ro, research_rw

logger = logging.getLogger("research.dq")


@dataclass
class QualityResult:
    check_name: str
    severity: str          # GOOD | SUSPECT | INVALID | STALE | PARTIAL
    affected_rows: int
    total_rows: int
    detail: dict

    @property
    def pct(self) -> float:
        return (self.affected_rows / self.total_rows * 100.0) if self.total_rows else 0.0

    def __str__(self):
        return (f"{self.check_name}: {self.affected_rows:,} / {self.total_rows:,} "
                f"({self.pct:.2f}%) [{self.severity}]")


class DataQualityEngine:

    async def run_all(self) -> List[QualityResult]:
        results = []
        for fn in (
            self.check_trades_outside_window,
            self.check_orphan_trades,
            self.check_duplicate_trades,
            self.check_invalid_prices,
            self.check_impossible_elapsed,
            self.check_missing_btc_price,
            self.check_missing_resolutions,
            self.check_collector_gaps,
        ):
            try:
                res = await fn()
                results.append(res)
                await self._record(res)
                logger.info("%s", res)
            except Exception as e:
                logger.error("check %s failed: %s", fn.__name__, e)
        return results

    # ── 1. Timestamp contamination ───────────────────────────────────────────
    async def check_trades_outside_window(self) -> QualityResult:
        row = await research_ro.fetchrow("""
            SELECT count(*) AS total,
                   count(*) FILTER (
                       WHERE t.trade_ts < m.open_time OR t.trade_ts > m.close_time
                   ) AS bad
            FROM trades t JOIN markets m ON t.slug = m.slug
        """)
        total, bad = int(row["total"] or 0), int(row["bad"] or 0)
        pct = (bad / total * 100.0) if total else 0.0
        return QualityResult(
            "trades_outside_window",
            "INVALID" if pct > 5 else ("SUSPECT" if pct > 0 else "GOOD"),
            bad, total,
            {"pct": round(pct, 2),
             "note": "trade timestamp outside its market's open/close window"},
        )

    # ── 2. Trades with no market record ──────────────────────────────────────
    async def check_orphan_trades(self) -> QualityResult:
        row = await research_ro.fetchrow("""
            SELECT (SELECT count(*) FROM trades) AS total,
                   (SELECT count(*) FROM trades t
                     LEFT JOIN markets m ON t.slug = m.slug
                    WHERE m.slug IS NULL) AS bad
        """)
        total, bad = int(row["total"] or 0), int(row["bad"] or 0)
        return QualityResult(
            "trades_orphan_market",
            "INVALID" if bad else "GOOD", bad, total,
            {"note": "trade references a slug with no markets row — timing unverifiable"},
        )

    # ── 3. Duplicates ────────────────────────────────────────────────────────
    async def check_duplicate_trades(self) -> QualityResult:
        row = await research_ro.fetchrow("""
            WITH d AS (
                SELECT tx_hash, wallet, slug, count(*) AS c
                FROM trades
                WHERE tx_hash IS NOT NULL
                GROUP BY tx_hash, wallet, slug
                HAVING count(*) > 1
            )
            SELECT (SELECT count(*) FROM trades) AS total,
                   COALESCE((SELECT sum(c - 1) FROM d), 0) AS bad
        """)
        total, bad = int(row["total"] or 0), int(row["bad"] or 0)
        return QualityResult(
            "duplicate_trades",
            "SUSPECT" if bad else "GOOD", bad, total,
            {"note": "same tx_hash+wallet+slug appears more than once"},
        )

    # ── 4. Invalid probabilities ─────────────────────────────────────────────
    async def check_invalid_prices(self) -> QualityResult:
        row = await research_ro.fetchrow("""
            SELECT (SELECT count(*) FROM trades) AS total,
                   (SELECT count(*) FROM trades
                     WHERE price IS NULL OR price <= 0 OR price >= 1) AS bad
        """)
        total, bad = int(row["total"] or 0), int(row["bad"] or 0)
        return QualityResult(
            "invalid_prices",
            "INVALID" if bad else "GOOD", bad, total,
            {"note": "prediction-market price must lie strictly in (0,1)"},
        )

    # ── 5. Impossible elapsed values ─────────────────────────────────────────
    async def check_impossible_elapsed(self) -> QualityResult:
        row = await research_ro.fetchrow("""
            SELECT (SELECT count(*) FROM trades) AS total,
                   (SELECT count(*) FROM trades
                     WHERE elapsed_s IS NULL OR elapsed_s < 0 OR elapsed_s > 300) AS bad
        """)
        total, bad = int(row["total"] or 0), int(row["bad"] or 0)
        return QualityResult(
            "impossible_elapsed",
            "SUSPECT" if bad else "GOOD", bad, total,
            {"note": "elapsed_s must be within [0,300] for a 5-minute window"},
        )

    # ── 6. Missing BTC price (blocks cross-market analysis) ──────────────────
    async def check_missing_btc_price(self) -> QualityResult:
        row = await research_ro.fetchrow("""
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE btc_price IS NULL) AS bad
            FROM snapshots
        """)
        total, bad = int(row["total"] or 0), int(row["bad"] or 0)
        pct = (bad / total * 100.0) if total else 0.0
        return QualityResult(
            "missing_btc_price",
            "PARTIAL" if pct > 1 else "GOOD", bad, total,
            {"pct": round(pct, 2),
             "note": "snapshot without BTC price cannot support BTC↔Poly analysis"},
        )

    # ── 7. Missing resolutions ───────────────────────────────────────────────
    async def check_missing_resolutions(self) -> QualityResult:
        row = await research_ro.fetchrow("""
            SELECT count(*) AS total,
                   count(*) FILTER (WHERE r.slug IS NULL) AS bad
            FROM markets m
            LEFT JOIN resolutions r ON m.slug = r.slug
            WHERE m.close_time < now() - interval '10 minutes'
        """)
        total, bad = int(row["total"] or 0), int(row["bad"] or 0)
        return QualityResult(
            "missing_resolutions",
            "PARTIAL" if bad else "GOOD", bad, total,
            {"note": "closed market with no resolution — outcome unknown, unusable as a label"},
        )

    # ── 8. Collector outage gaps ─────────────────────────────────────────────
    async def check_collector_gaps(self) -> QualityResult:
        rows = await research_ro.fetch("""
            WITH ordered AS (
                SELECT ts, lag(ts) OVER (ORDER BY ts) AS prev_ts
                FROM snapshots
            )
            SELECT prev_ts AS gap_start, ts AS gap_end,
                   EXTRACT(EPOCH FROM (ts - prev_ts)) AS gap_s
            FROM ordered
            WHERE prev_ts IS NOT NULL
              AND EXTRACT(EPOCH FROM (ts - prev_ts)) > $1
            ORDER BY gap_s DESC
            LIMIT 20
        """, float(settings.gap_threshold_s))

        gaps = [
            {"start": str(r["gap_start"]), "end": str(r["gap_end"]),
             "minutes": round(float(r["gap_s"]) / 60.0, 1)}
            for r in rows
        ]
        total_lost_min = round(sum(g["minutes"] for g in gaps), 1)
        return QualityResult(
            "collector_gaps",
            "STALE" if gaps else "GOOD", len(gaps), len(gaps),
            {"gaps": gaps, "total_minutes_lost": total_lost_min,
             "threshold_s": settings.gap_threshold_s,
             "note": "periods with no snapshots — collector outage; data unrecoverable"},
        )

    # ── persistence ──────────────────────────────────────────────────────────
    async def _record(self, r: QualityResult):
        try:
            await research_rw.execute_write(
                """
                INSERT INTO research.data_quality_events
                    (check_name, severity, affected_rows, detail)
                VALUES ($1, $2::research.quality_level, $3, $4::jsonb)
                """,
                r.check_name, r.severity, r.affected_rows,
                json.dumps({**r.detail, "total_rows": r.total_rows,
                            "pct": round(r.pct, 4)}),
            )
        except Exception as e:
            logger.error("failed to record %s: %s", r.check_name, e)
