# Changelog — Phantom Research Engine

Format: [Keep a Changelog](https://keepachangelog.com/). Versioning: semantic.

Production should run a **known version**, never "whatever is on main".
Rollback: redeploy the previous tag in Railway → Deployments → Redeploy.

## [v0.4.0] — 2026-07-21 — CI enforced before deploy

### Added
- **`.github/workflows/ci.yml` is live on GitHub** (finally pushable after the
  PAT was reissued with `workflow` scope). Six gates: syntax, integrity,
  imports, lint, secret scan, unit tests.
- **Railway "Wait for CI" enabled** on `phantom-research`. This is what makes
  enforcement real: Railway auto-deploys on push, so CI running *alongside* a
  deploy would have let broken code ship while the build was still red. Railway
  now holds the deploy until the check suite reports success.

### Fixed
- **Gate 5 self-match (CI run #1 failed).** The secret scan greps `*.yml` for a
  token pattern, and the pattern literal lives inside `ci.yml` — so the scanner
  detected itself and failed the build. Patterns are now written with
  single-character classes (`gh[p]_`), which match real tokens but not the
  literal text of the rule. Excluding `.github/` was rejected as a fix: it would
  create a blind spot exactly where secrets most often leak.
- Root cause of the miss: the gate was verified locally against a clone made
  *before* `ci.yml` existed, so the offending file was absent from the test.
  Re-verified against a tree containing `ci.yml`, plus planted-token and
  planted-DSN negative controls to confirm the gate still catches real secrets.

### Security
- A PAT was exposed in conversation by a failed redaction and has been revoked
  and replaced. Token-in-remote-URL remains the storage method; migrating to
  Git Credential Manager is an open item.

### Known gaps
- Enforcement covers `phantom-research` only. `phantom-collector` and
  `phantom-dashboard` still auto-deploy with no CI gate.
- Backups remain unaddressed on the Hobby plan (Pro planned next month).

## [v0.3.1] — 2026-07-21 — Alerting verified end-to-end

### Verified
- **Telegram delivery is live and PROVEN.** `RESEARCH_TELEGRAM_BOT_TOKEN` and
  `RESEARCH_TELEGRAM_CHAT_ID` set on the `phantom-research` Railway service;
  the "ALERT DELIVERY UNCONFIGURED" startup warning no longer appears.
- **Live-fire test performed, not assumed.** `STORAGE_WARNING_PCT` was
  temporarily lowered to 5 (against ~7% actual usage) so the heartbeat crossed
  a real threshold and fired a genuine WARNING through the real Telegram path.
  Alert received on the operator's phone. Threshold restored to 70.
- This closes readiness review **P0 #1** ("heartbeat monitors into a void").
  The monitor is no longer theoretical: it has been observed to page a human.

### Note
Only the storage path has been exercised end-to-end. The collector-CRITICAL
path shares the same `Notifier.alert()` delivery code, so delivery is proven,
but the *trigger* for a collector outage has not itself been fired in anger.

## [v0.3.0] — 2026-07-20 — Institutional Foundation (Phase A)

### Added
- **CI pipeline** (`.github/workflows/ci.yml`): syntax, integrity, imports,
  lint, secret scan, unit tests. A failing gate blocks deploy.
- **Integrity check** (`tests/integrity_check.py`) detecting the truncation
  class of failure that shipped broken code on 19 July — verified against a
  simulation of that exact incident.
- **Severity-based alerting**: INFO/WARNING/CRITICAL, per-key dedup,
  escalation always delivered, unconfigured delivery reported rather than silent.
- **Storage monitoring**: warns at 70%, pages at 85% (Railway alerts are Pro-only).
- **Backup tooling** (`scripts/backup_db.py`) + `docs/DISASTER_RECOVERY.md`.
- **Strategy lifecycle governance** (migration 003, `app/memory/strategy_registry.py`):
  15-state machine, illegal transitions rejected, live promotion requires a
  named human approver and recorded evidence — enforced before any DB access.
- **Rejected-idea memory** so failed ideas are not rediscovered.
- Runbooks: COLLECTOR_DOWN, DATABASE_FULL.

### Changed
- Heartbeat no longer treats trade *recency* as a health signal (produced a
  permanent false WARNING); trade health is now measured by arrival rate.

### Tests
25 passing (was 14).

## [v0.2.0] — 2026-07-20 — H003
Executability study; H003 SUPPORTED / STATISTICALLY_SUPPORTED, **not tradable**.

## [v0.1.0] — 2026-07-19 — Phase 1
Observer engine: capped read-only pools, heartbeat, data-quality engine,
hypothesis registry with validator veto, baseline analytics.
