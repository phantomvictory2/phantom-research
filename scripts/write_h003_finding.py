#!/usr/bin/env python3
"""
Persist the H003 finding to research.research_findings.

Separate from the analysis so the write is explicit and auditable: a finding
enters permanent research memory only by deliberate action, never as a side
effect of running a query. Idempotent — re-running will not duplicate.

Full methodology: docs/H003_RESULTS.md
"""

import asyncio, json, os, sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.database.pool import research_rw, research_ro, close_all   # noqa: E402
from app.memory import hypotheses                                   # noqa: E402

STATEMENT = (
    "BTC displacement from the 5-minute window open is strongly and monotonically "
    "inversely related to late-window reversal probability. At the last clean "
    "snapshot in 240-285s elapsed: <1bp reverses 23.72%, 1-3bp 8.93%, 3-7bp 1.96%, "
    "7-15bp 0.29%, 15bp+ 0.00%. Relative risk <1bp vs 3-7bp = 12.1x "
    "(z=12.44, p=1.5e-35). Effect is symmetric UP/DOWN and stable on 11/11 days."
)

LIMITATIONS = (
    "NOT a demonstrated trading edge. Price-conditioning shows Polymarket largely "
    "prices displacement in (favourite mid rises 0.81->0.94 across bands), so low "
    "reversal risk is mostly already paid for. The residual +4-5pt gap between "
    "realised and implied probability was measured on MIDPOINTS, not executable "
    "asks, with no spread/slippage/fee/partial-fill model, in a window region "
    "where liquidity is thin. TTR conditioning (does it hold early enough to act "
    "on?) NOT tested. Survivorship inferred (~99.5% coverage), not directly queried."
)

PROVENANCE = {
    "hypothesis": "H003",
    "views": ["research.clean_snapshots", "research.clean_markets"],
    "observation": "DISTINCT ON (slug), last snapshot where elapsed_s BETWEEN 240 AND 285",
    "displacement_bp": "(btc_price - btc_open)/btc_open*10000",
    "reversal": "sign(displacement) != winner",
    "look_ahead_check": "btc_open known at t=0; winner used only as outcome label",
    "tests_passed": ["up_down_symmetry", "day_stability_11_of_11", "tail_to_15bp_plus"],
    "tests_pending": ["ttr_conditioning", "direct_survivorship_query", "executability"],
    "doc": "docs/H003_RESULTS.md",
}


async def main():
    existing = await research_ro.fetchval(
        "SELECT count(*) FROM research.research_findings "
        "WHERE provenance->>'hypothesis' = 'H003'"
    )
    if existing:
        print(f"H003 finding already recorded ({existing} row(s)) — nothing to do")
        await close_all(); return 0

    await research_rw.execute_write(
        """
        INSERT INTO research.research_findings
            (category, statement, evidence_level, sample_size, data_period,
             confidence, limitations, provenance)
        VALUES ($1, $2, $3::research.evidence_level, $4, $5, $6, $7, $8::jsonb)
        """,
        "market_structure", STATEMENT, "STATISTICALLY_SUPPORTED", 2738,
        "2026-07-07 to 2026-07-20 (11 full days; 17-19 Jul outage excluded)",
        "95% Wilson CIs non-overlapping from 1-3bp onward; separation held 11/11 days",
        LIMITATIONS, json.dumps(PROVENANCE),
    )
    print("H003 finding written to research.research_findings")

    # Validator has NOT signed off on the full battery (TTR + survivorship
    # pending), so H003 stays TESTING rather than SUPPORTED in the registry.
    await hypotheses.update_status(
        "H003", "TESTING",
        evidence_level="STATISTICALLY_SUPPORTED", sample_size=2738,
        method="Displacement-banded reversal rates at 240-285s elapsed; Wilson CIs; "
               "two-proportion z-tests; UP/DOWN and day-by-day robustness",
        result="Monotonic inverse relationship, p=1.5e-35, RR 12.1x. Symmetric and "
               "time-stable. Not established as tradable — see limitations.",
        notes="TTR conditioning and direct survivorship query outstanding.",
    )
    print("H003 status -> TESTING (validator battery incomplete)")
    await close_all()
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
