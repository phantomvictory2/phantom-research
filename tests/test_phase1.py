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


# ── Alerting severity & suppression (Phase A) ────────────────────────────────

def test_notifier_severity_ranking():
    from app.monitoring.notifier import Notifier, INFO, WARNING, CRITICAL
    n = Notifier(cooldown_s=3600)
    # first WARNING passes the cooldown gate
    assert n._should_send("k", WARNING) is True
    # immediate repeat of the same severity is suppressed
    assert n._should_send("k", WARNING) is False
    # ESCALATION to CRITICAL must never be suppressed
    assert n._should_send("k", CRITICAL) is True


def test_notifier_critical_not_starved_by_long_cooldown():
    """A 30-min warning cooldown must not silence a CRITICAL."""
    from app.monitoring.notifier import Notifier, CRITICAL
    n = Notifier(cooldown_s=99999, critical_cooldown_s=0)
    assert n._should_send("x", CRITICAL) is True
    assert n._should_send("x", CRITICAL) is True   # short floor allows re-alert


def test_notifier_reports_unconfigured_delivery():
    """If nobody can be paged, that must be visible rather than silent."""
    from app.monitoring.notifier import Notifier
    n = Notifier()
    assert isinstance(n.delivery_configured, bool)


@pytest.mark.asyncio
async def test_info_never_pages():
    from app.monitoring.notifier import Notifier
    n = Notifier()
    assert await n.info("routine") is False


def test_storage_thresholds_ordered():
    from app.config.settings import Settings
    s = Settings(research_db_url="postgres://x")
    assert 0 < s.storage_warning_pct < s.storage_critical_pct <= 100
    assert s.storage_capacity_mb > 0


# ── Strategy lifecycle governance (Phase A) ──────────────────────────────────

def test_lifecycle_has_no_shortcut_to_live():
    """No state may jump straight to LIVE. Every path runs the full gauntlet."""
    from app.memory.strategy_registry import ALLOWED
    for state, targets in ALLOWED.items():
        if state != "LIVE_MINIMUM_SIZE":
            assert "LIVE" not in targets, f"{state} can jump straight to LIVE"


def test_paper_cannot_reach_live_directly():
    """The exact failure this governance exists to prevent."""
    from app.memory.strategy_registry import ALLOWED
    assert "LIVE" not in ALLOWED["PAPER"]
    assert "LIVE_MINIMUM_SIZE" not in ALLOWED["PAPER"]
    assert ALLOWED["PAPER"] >= {"LIVE_CANDIDATE"}


def test_retired_is_terminal():
    from app.memory.strategy_registry import ALLOWED
    assert ALLOWED["RETIRED"] == set()


def test_every_state_can_reach_rejection_or_is_terminal():
    """A strategy must always have an exit path."""
    from app.memory.strategy_registry import ALLOWED
    for state, targets in ALLOWED.items():
        if state in ("RETIRED",):
            continue
        assert targets, f"{state} is a dead end with no exit"


@pytest.mark.asyncio
async def test_live_promotion_requires_human_approver():
    """Governance must be structural, not a matter of discipline."""
    from app.memory import strategy_registry as reg
    with pytest.raises(reg.PromotionError, match="human approver"):
        await reg.transition("X", "LIVE", approved_by=None)


def test_live_states_enumerated():
    from app.memory.strategy_registry import LIVE_STATES
    assert LIVE_STATES == {"LIVE_CANDIDATE", "LIVE_MINIMUM_SIZE", "LIVE"}
