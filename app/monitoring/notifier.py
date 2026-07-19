"""
notifier.py — alert abstraction for the Research Engine.

Deliberately does NOT import Phantom V2's telegram.py. Coupling the research
service to a trading module would violate the isolation rule; a copy of ~30
lines is cheaper than a dependency.

If no research Telegram credentials are configured, alerts are logged only.
The engine must run fine without them.
"""

import time
import logging
import urllib.parse
import urllib.request

from app.config.settings import settings

logger = logging.getLogger("research.notifier")


class Notifier:
    """Log-first alerting with an optional Telegram sink and per-key cooldown."""

    def __init__(self, cooldown_s: int = None):
        self.cooldown_s = cooldown_s if cooldown_s is not None else settings.alert_cooldown_s
        self._last_sent: dict = {}

    def _throttled(self, key: str) -> bool:
        now = time.time()
        last = self._last_sent.get(key, 0)
        if now - last < self.cooldown_s:
            return True
        self._last_sent[key] = now
        return False

    async def alert(self, message: str, key: str = "default") -> bool:
        """Send an alert. Returns True if delivered to an external sink."""
        if self._throttled(key):
            logger.debug("alert throttled (%s)", key)
            return False

        logger.warning("ALERT [%s]: %s", key, message)

        token = settings.telegram_bot_token
        chat_id = settings.telegram_chat_id
        if not token or not chat_id:
            return False   # log-only mode; not an error

        try:
            url = f"https://api.telegram.org/bot{token}/sendMessage"
            data = urllib.parse.urlencode(
                {"chat_id": chat_id, "text": message}
            ).encode()
            req = urllib.request.Request(url, data=data)
            # Never let a notification failure propagate into research logic.
            with urllib.request.urlopen(req, timeout=8) as resp:
                return resp.status == 200
        except Exception as e:
            logger.error("telegram alert failed: %s", e)
            return False
