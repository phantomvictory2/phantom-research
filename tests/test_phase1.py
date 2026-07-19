"""
Phase 1 test suite — isolation, safety, and correctness.

These tests must pass before Phase 1 is declared complete. They deliberately
focus on the guarantees that protect Phantom V2 and research integrity, not on
cosmetics.
"""

import pytest

from app.config.settings import Settings, HealthThresholds
from app.database.pool import ResearchPool
from app.data_quality.checks import QualityResult


# ── Health threshold classification ──────────────────────────────────────────

def test_health_thresholds_classify():
    t = HealthThresholds()
    assert t.classify(10) == "HEALTHY"
    assert t.classify(120) == "HEALTHY"
    assert t.classify(300) == "WARNING"
    assert t.classify(700) == "STALE"
    assert t.classify(5000) == "CRITICAL"


def test_health_threshold_none_is_critical():
    # No rows at all must never be read as healthy.
    assert HealthThresholds().classify(None) == "CRITICAL"


def test_the_2026_07_17_outage_would_be_caught():
    """60 hours of staleness — the incident that motivated this monitor."""
    assert HealthThresholds().classify(60 * 3600) == "CRITICAL"


# ── Connection-pool safety ───────────────────────────────────────────────────

def test_pool_cap_enforced_by_config():
    s = Settings(pool_max=9, research_db_url="postgres://x")
    problems = s.validate()
    assert any("exceeds the safety cap" in p for p in problems)


def test_pool_cap_allows_safe_value():
    s = Settings(pool_max=3, pool_min=1, research_db_url="postgres://x")
    assert s.validate() == []


def test_missing_dsn_flagged():
    s = Settings(research_db_url="")
    assert any("RESEARCH_DB_URL" in p for p in s.validate())


# ── Read-only enforcement ────────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_read_only_pool_refuses_writes():
    ro = ResearchPool("postgres://unused", "test_ro", read_only=True)
    with pytest.raises(PermissionError):
        await ro.execute_write("INSERT INTO research.system_health DEFAULT VALUES")


@pytest.mark.asyncio
async def test_read_only_pool_refuses_migrations():
    ro = ResearchPool("postgres://unused", "test_ro", read_only=True)
    with pytest.raises(PermissionError):
        await ro.execute_migration("CREATE TABLE x(i int)")


@pytest.mark.asyncio
async def test_write_pool_refuses_non_research_schema():
    """The critical guard: research must never write to raw or Phantom tables."""
    rw = ResearchPool("postgres://unused", "test_rw", read_only=False)
    for bad in (
        "INSERT INTO trades (slug) VALUES ('x')",
        "UPDATE positions SET pnl = 0",
        "DELETE FROM snapshots",
        "TRUNCATE markets",
    ):
        with pytest.raises(PermissionError):
            await rw.execute_write(bad)


# ── Data-quality result semantics ────────────────────────────────────────────

def test_quality_result_pct():
    r = QualityResult("x", "SUSPECT", 174, 1000, {})
    assert r.pct == pytest.approx(17.4)


def test_quality_result_zero_total_is_safe():
    r = QualityResult("x", "GOOD", 0, 0, {})
    assert r.pct == 0.0


def test_quality_result_str_includes_severity():
    assert "INVALID" in str(QualityResult("c", "INVALID", 1, 2, {}))


# ── Hypothesis validator veto ────────────────────────────────────────────────

@pytest.mark.asyncio
async def test_cannot_mark_supported_without_validator():
    """Quant Validator veto must be structural, not a matter of discipline."""
    from app.memory import hypotheses
    with pytest.raises(PermissionError):
        await hypotheses.update_status("H001", "SUPPORTED", validator_passed=False)


def test_seed_hypotheses_are_well_formed():
    from app.memory.hypotheses import SEED_HYPOTHESES
    ids = [h[0] for h in SEED_HYPOTHESES]
    assert len(ids) == len(set(ids)), "hypothesis IDs must be unique"
    for hid, question, rationale, data_required in SEED_HYPOTHESES:
        assert hid.startswith("H")
        assert question.endswith("?"), f"{hid} must be phrased as a question"
        assert rationale and data_required
