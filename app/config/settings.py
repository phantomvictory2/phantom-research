"""
settings.py — Phantom Research Intelligence Engine configuration.

Every value comes from this service's OWN environment. Nothing is imported
from Phantom V2, and no trading credentials are read or accepted here.

Two database URLs are used, both READ-ONLY in intent:
  RESEARCH_DB_URL  — the Collector's Research_DB (markets/trades/snapshots/resolutions)
  PHANTOM_DB_URL   — Phantom V2's operational DB (signals/positions/journals)

Derived research data is written ONLY into the `research` schema, using
RESEARCH_RW_URL (which may point at the same instance with a restricted role).
"""

import os
from dataclasses import dataclass, field


def _env(name: str, default=None):
    return os.getenv(name, default)


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# ── Collector health thresholds (seconds since last row) ─────────────────────
# Rationale: the collector writes a snapshot every ~5-7s and trades every ~15s.
# 120s means several cycles have been missed; 1800s is the 2026-07-17 scenario.
@dataclass(frozen=True)
class HealthThresholds:
    healthy_s: int = 120
    warning_s: int = 600
    stale_s: int = 1800          # beyond this → CRITICAL

    def classify(self, age_s) -> str:
        """Map an age in seconds to a status label. None age → CRITICAL."""
        if age_s is None:
            return "CRITICAL"
        if age_s <= self.healthy_s:
            return "HEALTHY"
        if age_s <= self.warning_s:
            return "WARNING"
        if age_s <= self.stale_s:
            return "STALE"
        return "CRITICAL"


@dataclass(frozen=True)
class Settings:
    # ── Databases ────────────────────────────────────────────────────────────
    research_db_url: str = field(default_factory=lambda: _env("RESEARCH_DB_URL", ""))
    phantom_db_url: str = field(default_factory=lambda: _env("PHANTOM_DB_URL", ""))
    # Write target for derived research tables (defaults to research_db_url).
    research_rw_url: str = field(
        default_factory=lambda: _env("RESEARCH_RW_URL") or _env("RESEARCH_DB_URL", "")
    )

    # ── Connection safety (must never starve the collector or Phantom V2) ────
    pool_min: int = field(default_factory=lambda: _int("RESEARCH_POOL_MIN", 1))
    pool_max: int = field(default_factory=lambda: _int("RESEARCH_POOL_MAX", 3))
    statement_timeout_ms: int = field(
        default_factory=lambda: _int("RESEARCH_STATEMENT_TIMEOUT_MS", 15000)
    )
    connect_timeout_s: float = field(
        default_factory=lambda: _float("RESEARCH_CONNECT_TIMEOUT_S", 10.0)
    )

    # ── Monitoring ───────────────────────────────────────────────────────────
    heartbeat_interval_s: int = field(default_factory=lambda: _int("HEARTBEAT_INTERVAL_S", 60))
    alert_cooldown_s: int = field(default_factory=lambda: _int("ALERT_COOLDOWN_S", 1800))

    # ── Alerting (optional; logs only when unset) ────────────────────────────
    telegram_bot_token: str = field(default_factory=lambda: _env("RESEARCH_TELEGRAM_BOT_TOKEN", ""))
    telegram_chat_id: str = field(default_factory=lambda: _env("RESEARCH_TELEGRAM_CHAT_ID", ""))

    # ── Storage monitoring ───────────────────────────────────────────────────
    # Railway usage alerts require the Pro plan, so the engine watches capacity
    # itself. Defaults match the current 5GB volume.
    storage_capacity_mb: int = field(default_factory=lambda: _int("STORAGE_CAPACITY_MB", 5000))
    storage_warning_pct: float = field(default_factory=lambda: _float("STORAGE_WARNING_PCT", 70.0))
    storage_critical_pct: float = field(default_factory=lambda: _float("STORAGE_CRITICAL_PCT", 85.0))

    # ── Data quality ─────────────────────────────────────────────────────────
    # A window with no snapshot for this long counts as a collection gap.
    gap_threshold_s: int = field(default_factory=lambda: _int("GAP_THRESHOLD_S", 120))

    thresholds: HealthThresholds = field(default_factory=HealthThresholds)

    def validate(self) -> list:
        """Return a list of configuration problems (empty == OK)."""
        problems = []
        if not self.research_db_url:
            problems.append("RESEARCH_DB_URL is not set")
        if self.pool_max > 5:
            problems.append(
                f"RESEARCH_POOL_MAX={self.pool_max} exceeds the safety cap of 5 — "
                "research must never exhaust the shared database"
            )
        if self.pool_min > self.pool_max:
            problems.append("RESEARCH_POOL_MIN > RESEARCH_POOL_MAX")
        return problems


settings = Settings()
