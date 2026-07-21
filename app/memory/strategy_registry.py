"""
strategy_registry.py — strategy lifecycle governance.

CORE RULE
No strategy reaches a live state on P&L alone. Promotion into LIVE_CANDIDATE,
LIVE_MINIMUM_SIZE or LIVE requires a named human approver, and every transition
must be justified by recorded evidence. This is enforced in code, exactly as the
Quant Validator veto is — governance that depends on discipline is not governance.

The registry is descriptive, not executive: it records and gates decisions. It
does not start, stop or configure any strategy.
"""

import json
import logging

from app.database.pool import research_rw, research_ro

logger = logging.getLogger("research.registry")

# Legal forward transitions. Anything else must be explicit and justified.
ALLOWED = {
    "IDEA":                    {"RESEARCHING", "REJECTED"},
    "RESEARCHING":             {"STATISTICALLY_VALIDATED", "REJECTED"},
    "STATISTICALLY_VALIDATED": {"EXECUTION_VALIDATED", "REJECTED"},
    "EXECUTION_VALIDATED":     {"BACKTESTING", "REJECTED"},
    "BACKTESTING":             {"REPLAY_VALIDATED", "REJECTED"},
    "REPLAY_VALIDATED":        {"SHADOW", "REJECTED"},
    "SHADOW":                  {"PAPER", "REJECTED", "SUSPENDED"},
    "PAPER":                   {"LIVE_CANDIDATE", "REJECTED", "SUSPENDED", "DEGRADED"},
    "LIVE_CANDIDATE":          {"LIVE_MINIMUM_SIZE", "SUSPENDED", "REJECTED"},
    "LIVE_MINIMUM_SIZE":       {"LIVE", "SUSPENDED", "DEGRADED"},
    "LIVE":                    {"DEGRADED", "SUSPENDED", "RETIRED"},
    "DEGRADED":                {"SUSPENDED", "RETIRED", "PAPER"},
    "SUSPENDED":               {"PAPER", "RETIRED", "RESEARCHING"},
    "REJECTED":                {"RESEARCHING"},     # only on materially new data
    "RETIRED":                 set(),
}

# States that move real money. Human approval mandatory.
LIVE_STATES = {"LIVE_CANDIDATE", "LIVE_MINIMUM_SIZE", "LIVE"}


class PromotionError(PermissionError):
    """Raised when a transition violates lifecycle governance."""


async def register(strategy_id: str, *, owner: str = None, version: str = "v1",
                   state: str = "IDEA", hypothesis_id: str = None,
                   code_version: str = None, notes: str = None):
    await research_rw.execute_write(
        """
        INSERT INTO research.strategy_registry
            (strategy_id, version, state, owner, hypothesis_id, code_version, notes)
        VALUES ($1,$2,$3::research.strategy_state,$4,$5,$6,$7)
        ON CONFLICT (strategy_id) DO NOTHING
        """,
        strategy_id, version, state, owner, hypothesis_id, code_version, notes)


async def current_state(strategy_id: str):
    return await research_ro.fetchval(
        "SELECT state::text FROM research.strategy_registry WHERE strategy_id=$1",
        strategy_id)


async def transition(strategy_id: str, to_state: str, *, evidence: dict = None,
                     approved_by: str = None, rationale: str = None,
                     force: bool = False):
    """Move a strategy to a new lifecycle state.

    Raises PromotionError if the transition is illegal, or if a live state is
    requested without a named human approver.
    """
    # Governance checks run BEFORE any database access, so a violation fails
    # fast and identically whether or not the DB is reachable. A rule that only
    # applies when infrastructure is healthy is not a rule.
    if to_state in LIVE_STATES and not approved_by:
        raise PromotionError(
            f"{strategy_id}: promotion to {to_state} requires a named human "
            f"approver (approved_by). Paper P&L is not sufficient evidence to "
            f"move real money."
        )
    if to_state in LIVE_STATES and not evidence:
        raise PromotionError(
            f"{strategy_id}: promotion to {to_state} requires recorded evidence")

    frm = await current_state(strategy_id)
    if frm is None:
        raise PromotionError(f"{strategy_id} is not registered")

    if not force and to_state not in ALLOWED.get(frm, set()):
        raise PromotionError(
            f"{strategy_id}: illegal transition {frm} -> {to_state}. "
            f"Permitted from {frm}: {sorted(ALLOWED.get(frm, set())) or 'none'}"
        )

    await research_rw.execute_write(
        """
        UPDATE research.strategy_registry
           SET state=$2::research.strategy_state,
               promoted_by=COALESCE($3, promoted_by),
               promotion_date=CASE WHEN $2 IN ('LIVE_CANDIDATE','LIVE_MINIMUM_SIZE','LIVE')
                                   THEN NOW() ELSE promotion_date END,
               updated_at=NOW()
         WHERE strategy_id=$1
        """, strategy_id, to_state, approved_by)

    await research_rw.execute_write(
        """
        INSERT INTO research.strategy_transitions
            (strategy_id, from_state, to_state, evidence, approved_by, rationale)
        VALUES ($1,$2::research.strategy_state,$3::research.strategy_state,
                $4::jsonb,$5,$6)
        """, strategy_id, frm, to_state, json.dumps(evidence or {}),
        approved_by, rationale)

    logger.info("%s: %s -> %s%s", strategy_id, frm, to_state,
                f" (approved by {approved_by})" if approved_by else "")


async def record_rejection(idea: str, why_failed: str, *, kind: str = "strategy",
                           evidence: dict = None, data_period: str = None,
                           sample_size: int = None):
    """Remember what failed, so it is not rediscovered."""
    await research_rw.execute_write(
        """
        INSERT INTO research.rejected_ideas
            (idea, kind, why_failed, evidence, data_period, sample_size)
        VALUES ($1,$2,$3,$4::jsonb,$5,$6)
        """, idea, kind, why_failed, json.dumps(evidence or {}),
        data_period, sample_size)


async def inventory():
    rows = await research_ro.fetch(
        "SELECT strategy_id, version, state::text, evidence_level::text, trades, "
        "net_pnl, health::text FROM research.strategy_registry ORDER BY strategy_id")
    return [dict(r) for r in rows]
