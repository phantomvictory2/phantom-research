# PHANTOM ECOSYSTEM — PROJECT READINESS REVIEW

**Date:** 20 July 2026 · **Reviewer role:** engineering review board
**Verdict: CONDITIONAL GO for continued paper research · NO-GO for real capital**

---

## 1. Executive Summary

Phantom has become two things at once: a **genuinely strong research capability**
and a **fragile production trading system**. The gap between those two is the
central finding of this review.

The research layer is the best-engineered part of the ecosystem. In one week it
produced a statistically overwhelming result (H003, p≈10⁻³⁵, n=2,738), then
*disproved its own tradability* under real execution prices — and recorded both
outcomes with provenance. That is exactly how a research function should behave,
and most retail trading projects never build it.

The trading side is weaker than it looks. **Four strategies run in Test; none has
demonstrated an edge.** One was disabled after losing $499 in ten hours. The
production system runs a *different, older* codebase with a single strategy whose
paper profitability depends on fills the historical data suggests aren't
obtainable. There is no defined promotion path from research to production.

**Three findings would block a real-money release on their own:**

1. **Production and Test have silently diverged into two codebases** with no sync
   or promotion process (§2).
2. **No strategy has a validated edge** — the one rigorous study we ran concluded
   *not tradable* (§4, §8).
3. **No alerting is actually wired.** The heartbeat writes to a table nobody is
   paged from (§6, §13).

---

## 2. Architecture Assessment — **6/10**

**Working well.** The observer/controller boundary is real and enforced in code:
the research engine holds no trading credentials, uses read-only transactions,
and refuses writes outside `research.*`. If it dies, trading is unaffected. This
is properly done.

**Critical weakness — Production/Test divergence.** Verified by diff:

| | Production | Test |
|---|---|---|
| Strategy files | 3 | 7 |
| Active strategies | **1** (Last Shadow) | **4** |
| `reversal_logger.py` | absent | present |
| `risk_engine.py`, `main.py`, `monitor.py`, `signal_engine.py`, `database.py`, `dashboard.py` | **all differ** | — |

These are now two independent codebases sharing a name. Every improvement from
this week — the ORBIT v2 rewrite, PHANTOM_ONE, the displacement gates, the
reversal logger — exists **only in Test**. Nothing defines how validated work
reaches Production, and nothing prevents them drifting further. **P0.**

**Second weakness — research logic living in the dashboard.** The `clean_*`
views and research queries sit in `phantom-collector/dashboard.py`, a display
layer with no tests, while the tested research engine runs separately. Acceptable
as a temporary bridge; unacceptable as a destination. **P1.**

**Boundary that is correct:** collector → Research_DB → research engine →
`research.*` → dashboard. No circular dependencies found.

## 3. Codebase Assessment — **7/10**

**Good:** zero TODO/FIXME/HACK markers across Test. 98 tests pass (2 failures are
environment-only: DNS-blocked DB and a logs write permission). Comments explain
*why*, not *what* — the collector's rollback handler documents the 60-hour outage
that motivated it, which is how postmortem knowledge should live in code.

**Concerns:**
- **The file-truncation incident** (eight files silently lost their tails, one of
  which — `risk_engine.py` — still *compiled* while having lost its final
  `return APPROVED`) proves there is no pre-deploy integrity gate. A compile check
  is not a correctness check. **P1.**
- **Dead-ish code:** `orbit_a_240.py` remains imported and called behind a `False`
  flag. Config-gated rather than dead, but it should be archived with a dated
  note rather than left ambiguous.
- **No type checking, no linting, no formatter** in CI (there is no CI).

## 4. Strategy Assessment — **4/10**

| Strategy | Status | Reachable | Tested | Evidence |
|---|---|---|---|---|
| LAST_SHADOW_TRADE_LITE_V4 | Active (Test + Prod) | ✅ | ✅ | Paper-profitable on **fills the data says don't exist** |
| PHANTOM_ONE_V1 | Active (driver) | ✅ | ✅ 18 tests | ~18 trades, no conclusion |
| PHANTOM_MOMENTUM_V1 | Active (signal) | ✅ | ✅ | **Zero fills observed** |
| ORBIT_A_240_V2 | Active (driver) | ✅ | ✅ 14 tests | Untested live |
| ORBIT_A_240 | **Disabled** | gated off | ✅ | −$499 / 825 trades, 55.6% WR vs 63% breakeven |
| LATENCY_ARB, LATE_STAGE_CONFIRM, BREAKOUT_SCALPER, MOMENTUM_RIDE | **Do not exist** | — | — | Referenced in planning docs only |

**The honest position: no strategy has a demonstrated edge.** Four run; one is a
proven loser; one has never filled; two have negligible samples.

**Last Shadow deserves specific scrutiny.** It buys ~0.99 favourites in the final
seconds, risking $50 to win $0.50. Expected value ≈ +$0.15/trade at 99.3% wins —
**77% of all winnings are returned via rare losses.** At 98% wins it loses money.
And the historical record shows only **32 fills ever** in the final 15 seconds
market-wide. Its paper profitability likely reflects a fill model, not an edge.
**It should not go live at size on current evidence. P0 if real money is planned.**

**Conflict check:** the risk engine caps 2 concurrent positions and one per asset,
so a churning strategy starves others — this demonstrably happened (ORBIT_A_240
crowding out PHANTOM_MOMENTUM_V1, which recorded zero fills). Strategies compete
for slots with no priority policy. **P2.**

## 5. Risk Engine Assessment — **6/10**

**Present:** 7-check pipeline, kill switch (env + DB), daily loss limits,
concurrency caps, per-asset exclusivity, cooldowns, circuit breakers, idempotency
guard on ambiguous order states (correctly does *not* retry on ERROR).

**Missing:**
- **No portfolio-level drawdown halt** — only per-strategy daily limits. Four
  strategies can each lose to their own limit simultaneously. **P1.**
- **Bankroll restore ignores `is_paper`** — `$1000 + SUM(pnl)` over all closed
  positions. Paper and live PnL would commingle in equity used to enforce risk
  limits. **P1 before live.**
- **No MFE/MAE capture**, so exit rules cannot be optimised empirically. **P2.**
- **No position reconciliation** against the exchange — the bot trusts its own DB.

## 6. Collector Assessment — **7/10**

**Fixed and verified this week:** the `InFailedSqlTransaction` loop that cost
~60 hours of data is genuinely resolved (rollback + reconnect), confirmed by row
growth, not process status. Heartbeat now runs every 60s and correctly judges
health by *data arrival*.

**Remaining gaps:**
- **No order-book depth.** `snapshots` stores price but **no size**. This blocks
  every execution-realism question — it is the single most valuable missing data
  field in the ecosystem. **P1.**
- DOWN side has mid only; DOWN ask must be inferred as `1 − up_bid`.
- ~7s snapshot cadence rules out sub-second microstructure permanently.
- Single instance, no redundancy — one process is the entire data pipeline.
- **17.4% of trades remain timestamp-contaminated** (correctly excluded, not
  deleted — right call).

## 7. Database Assessment — **6/10**

Research_DB: 352 MB / 5 GB, ~27 MB/day, ~6 months runway. Clean views verified
correct by two independent computations.

**Gaps:** **no backups** on irreplaceable data (**P0** — a volume failure loses
everything); storage alerts are Pro-plan-only and disabled; no index review
performed on the growing `snapshots`/`trades` tables; `research_ro`/`research_rw`
least-privilege roles were designed but **never created** — the engine uses full
credentials with application-layer enforcement only. **P1.**

## 8. Research Assessment — **8/10 — the strongest part of the ecosystem**

**What was actually established (H003):** BTC displacement from the window open
is monotonically inversely related to reversal probability — 23.7% at <1bp
falling to 0.00% above 15bp, n=2,738, p≈1.5×10⁻³⁵, relative risk 12.1×. It
survived UP/DOWN symmetry (bands differ by 0.01pp), day-by-day stability (11/11,
ranges never overlap), and the full tail.

**And then it was disproved as a trade.** At real ask prices, at 60s where ~73%
of volume trades, **no displacement band survives its own confidence interval.**
Spread (1.8–2.4¢ on 0.55–0.86 prices) consumes the 2–6pp edge. Apparent edges
appear only at 120–180s — past the liquidity peak.

**Evidence classification, stated plainly:**

| Claim | Level |
|---|---|
| Displacement predicts reversal | **STATISTICALLY_SUPPORTED** |
| BTC↔Poly 66%/90% "agreement" | **OBSERVATIONAL** — contemporaneous, proves nothing |
| Any tradable edge | **NONE ESTABLISHED** |

**A methodological red flag I want on record:** in the executability grid, the
180s `<1bp` cell showed the *largest* EV (+0.202) — on the band that should carry
the *least* information. That is almost certainly small-sample noise, and it
means the other "surviving" cells deserve suspicion too. 12 cells were tested
with no multiple-comparison correction.

**What's genuinely promising:** the *method* is now trustworthy. Clean views,
provenance, structural validator veto, look-ahead prevented by construction.

**What should be rejected:** the alignment metric as evidence of anything
tradable. **Next:** depth collection, then per-window EV with FDR correction.

## 9. Dashboard Assessment — **7/10**

10 tabs, live data, no hardcoded research values, parameterised SQL, failures
visible rather than silent. **Gaps:** research computation embedded in the
display layer (§2); no per-tab data-freshness stamp; gap severity undifferentiated
(a 61-hour outage and a 7-minute gap render identically); Streamlit re-queries on
every interaction with only a 60s cache.

## 10. Testing Assessment — **6/10**

98 passing unit tests is respectable. **What's missing is the category that
matters for money:**
- **No integration test** covering feed → signal → risk → executor → monitor.
- **No soak test.** Longest observed continuous run is hours, not weeks.
- **No chaos testing** — DB disappearing mid-trade, feed dying between signal and
  fill, duplicate resolution. The 60-hour outage was exactly this class of bug
  and no test would have caught it.
- **No fill-model validation** against `execution_journal`.
- The 2 failing tests are environmental but have been failing long enough to
  become background noise — **that is how real failures get ignored.**

## 11. Security Assessment — **5/10**

**Risks identified (no secret values inspected or reproduced):**
- **Research_DB credential entered on a PowerShell command line** — now in
  `ConsoleHost_history.txt` on disk and in a shared screenshot. **Rotate. P1.**
- **`.env` inside `archive_DO_NOT_DEPLOY/`**, outside git control, unmanaged.
- **`phantom-research` is a public repo** while all trading repos are private.
  No secrets in it, but methodology and infrastructure detail are exposed. **P2.**
- **Least-privilege DB roles never created** (§7).
- **Good:** research service holds no wallet keys and cannot place orders even if
  fully compromised. `.gitignore` coverage verified before every push.

## 12. Performance Assessment — **7/10**

No current bottleneck. Research pool capped at 3 connections. Forward risks:
raising snapshot cadence to 1s multiplies storage ~7× (5 GB exhausted in under a
month); `snapshots`/`trades` will need index review as they grow; Streamlit
re-queries are wasteful but not yet material.

## 13. DevOps Assessment — **4/10 — weakest area**

- **No CI.** Nothing runs the 98 tests before deploy. The truncation incident
  shipped broken code to Railway; a CI gate would have caught it.
- **No rollback procedure** beyond manually redeploying an old commit.
- **No versioning or release process.** No tags, no changelog, no semver.
- ~~**No alerting.**~~ **RESOLVED 2026-07-21.** Telegram credentials are
  configured on `phantom-research`, and delivery was proven by a live-fire test
  (storage threshold temporarily lowered below actual usage; a real WARNING was
  fired and received on the operator's phone; threshold restored). The gap that
  allowed the 60-hour outage to stay invisible is closed. Remaining alerting
  gap: nothing watches the *trading bot's* liveness — only the collector's.
- Health checks exist for the collector only; nothing watches the trading bot's
  own liveness.

## 14. Documentation Assessment — **7/10**

Unusually good *research* documentation: architecture assessment, feasibility
report, audit, H003 results with reproduction SQL. **Missing entirely:** runbooks
(what to do when the collector dies, when a strategy misbehaves, when the DB
fills), deployment guide, strategy specification docs, developer onboarding,
recovery procedures. **All institutional knowledge about operations lives in chat
history, not in the repo.** **P1.**

## 15. Missing Components

**Should exist and doesn't:**
1. **Order-book depth collection** — blocks all execution realism. **P1**
2. **Real alerting** (page a human) — **P0**
3. **CI pipeline** — **P0**
4. **Backups** — **P0**
5. **Promotion pipeline** Test→Production — **P0**
6. **Integration + soak tests** — **P1**
7. **Runbooks** — **P1**
8. **Cost model calibrated from `execution_journal`** — **P1**
9. **Experiment Lab** (`research_experiments` populated) — **P2**
10. **Strategy health monitor / decay detection** — **P2**

**Deliberately should NOT build yet:** AI Research Brain, feature store, model
registry, message bus. The deterministic layer isn't finished.

## 16. Top Recommendations (P0 → P3)

| # | Pri | Problem | Recommendation | Effort |
|---|---|---|---|---|
| 1 | ~~P0~~ **DONE 2026-07-21** | Heartbeat monitored into a void | Telegram alerting wired **and proven by live-fire test** | ✅ |
| 2 | **P0** | No backups on irreplaceable data | Enable Research_DB backups | 30m |
| 3 | **P0** | Prod/Test diverged, no promotion path | Define and document promotion; reconcile or formally fork | 1d |
| 4 | **P0** | Broken code can ship | GitHub Actions running pytest on push | 2h |
| 5 | **P0** | No strategy has a validated edge | Stop adding strategies until one is validated | — |
| 6 | **P1** | No order-book depth | Extend collector `snapshots` with size | 4h |
| 7 | **P1** | Bankroll commingles paper/live | Filter `is_paper=false` in restore | 15m |
| 8 | **P1** | No portfolio drawdown halt | Add ecosystem-level limit | 2h |
| 9 | **P1** | DB credential in shell history | Rotate | 15m |
| 10 | **P1** | No least-privilege roles | Create `research_ro`/`research_rw` | 1h |
| 11 | **P1** | No integration/soak tests | End-to-end + 72h soak | 1–2d |
| 12 | **P1** | No runbooks | Write 5 core runbooks | 4h |
| 13 | **P1** | Research logic in dashboard | Migrate to research engine | 1d |
| 14 | **P1** | Fill model unvalidated | Calibrate from `execution_journal` | 4h |
| 15 | **P2** | No MFE/MAE | Add to positions | 2h |
| 16 | **P2** | Strategies compete for slots | Priority policy | 2h |
| 17 | **P2** | Gap severity undifferentiated | Tier by duration | 1h |
| 18 | **P2** | Public research repo | Make private | 5m |
| 19 | **P2** | 2 tests permanently failing | Fix or quarantine | 1h |
| 20 | **P3** | No versioning | Tags + changelog | 2h |

## 17. Production Readiness Scores

| Area | Score | Rationale |
|---|---|---|
| Architecture | 6/10 | Clean research/trading boundary; Prod/Test divergence |
| Code Quality | 7/10 | No TODOs, tests pass; truncation incident, no CI |
| Trading Engine | 6/10 | Solid mechanics; unvalidated fill assumptions |
| Strategies | **4/10** | Four active, none with a demonstrated edge |
| Collector | 7/10 | Fixed and monitored; no depth, single instance |
| Database | 6/10 | Healthy; **no backups**, no least-privilege |
| Research | **8/10** | Rigorous, honest, self-disproving. Best component |
| Dashboard | 7/10 | Functional, dynamic; computation in wrong layer |
| Security | 5/10 | No trading creds exposed; credential hygiene lapses |
| Testing | 6/10 | 98 unit tests; no integration/soak/chaos |
| Monitoring | 7/10 | Heartbeat + alerting **verified end-to-end**; bot liveness unwatched |
| DevOps | 6/10 | Alerting live, versioned changelog; CI written but not enforced |
| Documentation | 7/10 | Excellent research docs; zero runbooks |
| **Overall** | **6/10** | Strong research, immature operations |

## 18. Final Verdict

**CONDITIONAL GO** — continue paper trading and research.
**NO-GO** — real capital, on current evidence.

---

## 19. The Honest Answers

**What we're doing really well.** The research discipline is genuinely
institutional-grade. Look-ahead prevented by construction, not review. Contaminated
data excluded by view, not by remembering. A validator veto enforced in code.
Findings carrying evidence levels. And — rarest of all — **we published a result
that killed our own idea.** The executability study was designed to disprove H003
and it largely did. Most people build a system to confirm what they hope.

**What we're doing poorly.** Operations. No CI, no backups, no alerting, no
rollback, no runbooks. We built a research telescope and bolted it to a car with
no brakes. The 60-hour outage wasn't bad luck — it was the predictable result of
having no alerting, and *it is still true today*.

**What we're missing completely.** (1) A promotion path from research to
production — the whole point of research is to change what trades, and there's no
defined route. (2) Order-book depth — without size, execution realism is
unanswerable. (3) Anyone being paged when something breaks.

**What we should stop doing.** **Stop adding strategies.** We have four, none
validated, one a proven loser, one that has never filled. Each new one adds
surface area and competes for position slots. Also stop treating paper P&L as
evidence — Last Shadow's paper profit rests on fills the data suggests don't
exist.

**What to build next, in order:** alerting → backups → CI → depth collection.
Three of those are under two hours each.

**If this were my company, before real money:**

1. **Prove one strategy, live, at minimum size, for a month** — every strategy
   is currently either unvalidated or disproven. I'd send $50 through Last Shadow
   and compare actual fills to the paper model. My expectation is it degrades
   badly, and I'd want to learn that for $50.
2. **Fix the bankroll `is_paper` bug before a single live trade.** Commingled
   equity means risk limits enforce against a fictional number.
3. **Wire alerting and backups today** — hours of work standing between us and
   losing irreplaceable data.
4. **Build the promotion pipeline**, or accept that Production will drift into an
   unmaintained fork.
5. **Get depth data, then re-run the executability study.** That study is the
   gate everything must pass, and right now it's running blind on size.

The uncomfortable summary: **the research says we don't yet have an edge, and the
operations aren't ready to trade one if we found it.** Both are fixable, and
knowing it now — from queries rather than drawdowns — is the most valuable thing
this project has produced.

---
*No code was modified during this review. Phantom V2 untouched. Last Shadow 3bp
gate unchanged.*
