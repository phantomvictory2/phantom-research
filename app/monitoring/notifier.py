"""
notifier.py — alert delivery for the Research Engine.

Deliberately does NOT import Phantom V2's telegram.py. Coupling a monitoring
path to a trading module would violate the isolation rule; ~40 lines of
duplication is cheaper than that dependency.

DESIGN NOTES
- Severity-aware. INFO is logged only; WARNING and CRITICAL are delivered.
- Deduplicated per (key, severity) with a cooldown, because an alerting system
  that spams is an alerting system people mute — and a muted alert is how the
  2026-07-17 outage stayed invisible for 60 hours.
- CRITICAL bypasses the normal cooldown on a shorter floor, and re-alerts on
  state change, so a genuine emergency cannot be silently suppressed.
- Fail-soft: a delivery failure never propagates into research logic.
- If no credentials are configured the engine still runs, logging alerts and
  recording that delivery is UNCONFIGURED (so the gap is visible, not silent).
"""

import time
import logging
import urllib.parse
import urllib.request

from app.config.settings import settings

logger = logging.getLogger("research.notifier")

INFO, WARNING, CRITICAL = "INFO", "WARNING", "CRITICAL"
_ICON = {INFO: "\u2139\ufe0f", WARNING: "\u26a0\ufe0f", CRITICAL: "\U0001f534"}
_RANK = {INFO: 0, WARNING: 1, CRITICAL: 2}


class Notifier:
    """Severity-aware, deduplicated alert delivery."""

    def __init__(self, cooldown_s: int = None, critical_cooldown_s: int = 300):
        self.cooldown_s = cooldown_s if cooldown_s is not None else settings.alert_cooldown_s
        self.critical_cooldown_s = critical_cooldown_s
        self._last_sent: dict = {}      # (key, severity) -> ts
        self._last_state: dict = {}     # key -> severity
        self.delivery_configured = bool(
            settings.telegram_bot_token and settings.telegram_chat_id
        )
        if not self.delivery_configured:
            logger.warning(
                "ALERT DELIVERY UNCONFIGURED — set RESEARCH_TELEGRAM_BOT_TOKEN and "
                "RESEARCH_TELEGRAM_CHAT_ID. Alerts will be logged only, and no human "
                "will be paged."
            )

    # ── suppression policy ───────────────────────────────────────────────────
    def _should_send(self, key: str, severity: str) -> bool:
        now = time.time()
        prev_state = self._last_state.get(key)
        self._last_state[key] = severity

        # Escalation (e.g. WARNING -> CRITICAL) always gets through.
        if prev_state is not None and _RANK[severity] > _RANK.get(prev_state, 0):
            self._last_sent[(key, severity)] = now
            return True

        cooldown = self.critical_cooldown_s if severity == CRITICAL else self.cooldown_s
        last = self._last_sent.get((key, severity), 0)
        if now - last < cooldown:
            return False
        self._last_sent[(key, severity)] = now
        return True

    # ── public API ───────────────────────────────────────────────────────────
    async def alert(self, message: str, key: str = "default",
                    severity: str = WARNING) -> bool:
        """Send an alert. Returns True only if delivered to an external sink."""
        if severity not in _RANK:
            severity = WARNING

        log = logger.info if severity == INFO else (
            logger.warning if severity == WARNING else logger.error)
        log("ALERT [%s/%s]: %s", severity, key, message)

        if severity == INFO:
            return False                      # logged only, never paged
        if not self._should_send(key, severity):
            logger.debug("alert suppressed by cooldown (%s/%s)", key, severity)
            return False
        if not self.delivery_configured:
            return False

        text = f"{_ICON[severity]} [{severity}] PHANTOM RESEARCH\n{message}"
        try:
            url = f"https://api.telegram.org/bot{settings.telegram_bot_token}/sendMessage"
            data = urllib.parse.urlencode(
                {"chat_id": settings.telegram_chat_id, "text": text}
            ).encode()
            with urllib.request.urlopen(
                urllib.request.Request(url, data=data), timeout=8
            ) as resp:
                ok = resp.status == 200
                if not ok:
                    logger.error("telegram returned HTTP %s", resp.status)
                return ok
        except Exception as e:
            # Never let a notification failure break the monitor.
            logger.error("alert delivery failed: %s", e)
            return False

    async def info(self, message, key="default"):
        return await self.alert(message, key, INFO)

    async def warning(self, message, key="default"):
        return await self.alert(message, key, WARNING)

    async def critical(self, message, key="default"):
        return await self.alert(message, key, CRITICAL)
