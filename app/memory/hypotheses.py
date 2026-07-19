"""
hypotheses.py — research memory for hypotheses.

Rules encoded here:
  • Nothing is "known" without provenance (data period, sample size, method).
  • A hypothesis cannot reach SUPPORTED without validator_passed = TRUE.
    That is the Quant Validator's structural veto, enforced in code rather
    than left to discipline.
  • Rejected hypotheses are not silently re-tested; callers check first.
"""

import logging
from app.database.pool import research_rw, research_ro

logger = logging.getLogger("research.memory")


# Seed questions for Phase 1. All start as PROPOSED — none is assumed true.
SEED_HYPOTHESES = [
    ("H001",
     "Does BTC displacement from the window open predict the eventual winner "
     "better than the Polymarket price alone?",
     "Cross-market lead/lag is the core thesis of the whole platform. If BTC "
     "displacement adds no information beyond price, most strategy ideas die.",
     "clean_snapshots (btc_price, up_mid), clean_markets (winner, btc_open)"),

    ("H002",
     "Does Polymarket repricing lag BTC movement at measurable (>=7s) resolution?",
     "Snapshot cadence is ~7s, so only coarse lag is testable. A null result "
     "here does not disprove sub-second lag; it bounds what we can claim.",
     "clean_snapshots time series per window"),

    ("H003",
     "Is the last-second reversal rate materially higher when BTC sits near the "
     "window open (|displacement| < 2bp)?",
     "Directly tests the Last Shadow failure mode: near-certain favourites that "
     "flip. Determines whether the displacement gate is justified per asset.",
     "clean_snapshots at high elapsed_s + clean_markets.winner"),

    ("H004",
     "Does the winning side's price converge monotonically, and where is the "
     "gap between price and realised win rate widest?",
     "The seven-wallet study found 0.55-0.70 beat its implied probability. "
     "Re-test on the full dataset with clean data.",
     "clean_snapshots.up_mid by elapsed_s + winner label"),

    ("H005",
     "Is liquidity so concentrated early in the window that late-window "
     "strategies are unexecutable at size?",
     "Prior analysis found only 32 fills ever in the final 15s. If confirmed, "
     "any late-entry strategy is fiction regardless of its backtest.",
     "clean_trades grouped by elapsed_s phase"),

    ("H006",
     "Do Phantom V2's rejected signals have worse realised outcomes than "
     "accepted ones — i.e. are the risk rules adding value?",
     "Tests whether existing risk gates protect the bot or merely reduce "
     "sample size. Rarely measured; cheap to test with existing data.",
     "phantom signals (rejection_reason) + market outcomes"),

    ("H007",
     "Are there conditions under which NO_TRADE has higher expectancy than any "
     "available action?",
     "Foundation of the No-Trade model. Sometimes the best decision is to sit out.",
     "features + outcomes across regimes"),

    ("H008",
     "Does apparent edge survive realistic execution costs (spread, fees, "
     "slippage, partial fills)?",
     "Every prior candidate died here. Must be applied to every future finding "
     "before it is called an edge.",
     "execution_journal (real slippage/fees) + candidate expectancy"),
]


async def seed_hypotheses() -> int:
    """Insert seed hypotheses if absent. Idempotent."""
    inserted = 0
    for hid, question, rationale, data_required in SEED_HYPOTHESES:
        try:
            await research_rw.execute_write(
                """
                INSERT INTO research.research_hypotheses
                    (id, question, rationale, data_required, status, evidence_level)
                VALUES ($1, $2, $3, $4, 'PROPOSED'::research.hypothesis_status,
                        'OBSERVATIONAL'::research.evidence_level)
                ON CONFLICT (id) DO NOTHING
                """,
                hid, question, rationale, data_required,
            )
            inserted += 1
        except Exception as e:
            logger.error("failed to seed %s: %s", hid, e)
    return inserted


async def list_hypotheses(status: str = None) -> list:
    if status:
        rows = await research_ro.fetch(
            "SELECT id, question, status, evidence_level, sample_size "
            "FROM research.research_hypotheses WHERE status = $1::research.hypothesis_status "
            "ORDER BY id", status)
    else:
        rows = await research_ro.fetch(
            "SELECT id, question, status, evidence_level, sample_size "
            "FROM research.research_hypotheses ORDER BY id")
    return [dict(r) for r in rows]


async def update_status(hid: str, status: str, *, validator_passed: bool = False,
                        evidence_level: str = None, sample_size: int = None,
                        method: str = None, result: str = None, notes: str = None):
    """Update a hypothesis. SUPPORTED requires the Validator's approval."""
    if status == "SUPPORTED" and not validator_passed:
        raise PermissionError(
            f"{hid}: cannot mark SUPPORTED without validator_passed=True "
            "(Quant Validator holds veto power)"
        )
    await research_rw.execute_write(
        """
        UPDATE research.research_hypotheses
           SET status = $2::research.hypothesis_status,
               validator_passed = $3,
               evidence_level = COALESCE($4::research.evidence_level, evidence_level),
               sample_size = COALESCE($5, sample_size),
               method = COALESCE($6, method),
               result = COALESCE($7, result),
               notes = COALESCE($8, notes),
               updated_at = NOW()
         WHERE id = $1
        """,
        hid, status, validator_passed, evidence_level, sample_size,
        method, result, notes,
    )
