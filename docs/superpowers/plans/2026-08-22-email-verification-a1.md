# Email Verification A1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox syntax (`- [ ]`) for tracking.

**Goal:** Build a tenant-safe, local-first email verification pipeline with durable evidence, explainable independent scores, phased network execution, and an optional third-party fallback contract.

**Architecture:** Preserve `apps.growth.email_verification` as the public module but replace its basic lookup with pure value-object checks and injected DNS/SMTP boundaries. Add tenant-owned run/evidence models and a phased service: prepare transaction, transaction-free network work, finalize transaction. A Celery task accepts explicit organization and run IDs. PostgreSQL FORCE RLS protects both new tables immediately, even though other Growth tables remain scheduled for RLS-2C.

**Tech Stack:** Python 3.12, Django 5.2, Celery 5.5, PostgreSQL 17 RLS, Redis-backed Django cache, dnspython, pytest, Ruff.

**Spec:** `docs/email-verification-a1-audit.md`

---

### Task 1: Lock contracts with failing pure-pipeline tests

**Files:**
- Modify: `backend/apps/growth/tests/test_email_verification.py`
- Modify: `backend/apps/growth/email_verification.py`
- Modify: `backend/pyproject.toml`

- [ ] Add parameterized tests for strict normalization, invalid syntax, nonexistent domain, null/no MX, disposable domains, and role mailboxes.
- [ ] Add fake resolver and fake SMTP probe tests for normal MX, explicit recipient rejection, catch-all, timeout, rate limit, greylist, and ambiguous responses.
- [ ] Assert deliverability and contact-quality scores are separate, reason codes are stable, role mailboxes are not `INVALID`, SMTP acceptance is at most `LIKELY_VALID`, and catch-all is never `VALID`.
- [ ] Run the focused tests and confirm they fail for missing behavior.
- [ ] Add frozen request/result/evidence dataclasses, five-state enums, check/source/reason enums, normalization, disposable/role/name-pattern logic, and deterministic scoring.
- [ ] Add `dnspython` and implement an injectable resolver with bounded lifetime/timeout.
- [ ] Implement an injectable SMTP prober that never sends `DATA`, stores only response classes/codes, and classifies greylist/timeout/ambiguous outcomes.
- [ ] Implement a hashed shared-cache domain lease with explicit concurrency/minimum-interval outcomes.
- [ ] Re-run focused tests until green.

### Task 2: Add tenant-owned lifecycle and evidence models

**Files:**
- Modify: `backend/apps/growth/models.py`
- Create: `backend/apps/growth/migrations/0050_email_verification_pipeline.py`
- Create: `backend/apps/growth/tests/test_email_verification_models.py`

- [ ] Write failing model tests for organization-scoped idempotency, field validation, optional-parent organization consistency through the service, immutable evidence, lifecycle values, reason-code list validation, score bounds, and safe defaults.
- [ ] Add `EmailVerificationRun` with organization, optional contact/candidate, normalized email/fingerprint/domain, idempotency key, lifecycle/result, independent scores, reasons, verifier/source metadata, provider-review flag, safe error code, claim token, attempts, and timestamps.
- [ ] Add append-only `EmailVerificationEvidence` with direct organization, run, sequence, check/source/version/outcome/reason, sanitized evidence, duration, observation, and expiry.
- [ ] Add database uniqueness/index constraints for tenant idempotency, email/version lookup, and ordered evidence.
- [ ] Generate only `growth.0050`; inspect it to ensure dependencies include `growth.0049` and `knowledge.0008`, with no data backfill.
- [ ] Run model tests and `makemigrations --check --dry-run`.

### Task 3: Implement phased, idempotent verification service

**Files:**
- Create: `backend/apps/growth/email_verification_services.py`
- Modify: `backend/apps/growth/email_verification.py`
- Create: `backend/apps/growth/tests/test_email_verification_services.py`

- [ ] Write failing tests for prepare/network/finalize transaction boundaries, history weighting, idempotent reuse, concurrent/stale finalize, pause, cross-tenant parent rejection, and safe errors.
- [ ] Implement prepare inside `tenant_atomic`: explicit tenant filters, stable locks, idempotent get/create, pause check, immutable request snapshot, and a fresh claim token.
- [ ] Query historical `OutreachMessage` results only in prepare and convert them to a minimal immutable history snapshot. Treat reply as strong positive, accepted send as weak positive, and bounce as negative.
- [ ] Run DNS, SMTP, shared-cache throttle, and optional Provider outside database transactions with no ORM access.
- [ ] Implement fallback policy: local `INVALID` never calls Provider; `RISKY`, `UNKNOWN`, catch-all, and high-value contacts request review and may call only an injected Provider.
- [ ] Implement finalize in a new `tenant_atomic`: lock by organization and ID, validate claim/state, insert sanitized evidence, and atomically save result. Stale workers must not overwrite pauses/new claims.
- [ ] Keep `verify_email()` as a backwards-compatible stateless local contract while providing a tenant-aware persisted entry for production callers.
- [ ] Run service and transaction-boundary tests.

### Task 4: Add explicit Celery task and production dispatch

**Files:**
- Modify: `backend/apps/growth/tasks.py`
- Modify: `backend/apps/growth/agent/acquisition.py`
- Modify: `backend/apps/growth/agent/pipeline_tools.py`
- Create: `backend/apps/growth/tests/test_email_verification_tasks.py`
- Modify: `backend/apps/growth/tests/test_agent_enrichment_tools.py`

- [ ] Write failing tests that the task requires strict UUID strings, cannot see cross-tenant runs, re-queries inside tenant context, performs DNS/SMTP outside a transaction, preserves organization ID across retry, and is idempotent.
- [ ] Add `run_email_verification(organization_id: str, verification_id: str)` with no object-ID tenant inference.
- [ ] Dispatch only through `transaction.on_commit()` when a run is created or reset.
- [ ] Add pause/resume service behavior without API/UI changes.
- [ ] Update the proactive acquisition contact-verification tool to pass its closed-over trusted organization ID and optional candidate ID. Never accept organization from tool arguments.
- [ ] Keep generic non-tenant pipeline use stateless and clearly marked as non-persisted compatibility behavior.
- [ ] Run task and representative Agent tool tests.

### Task 5: Add immediate PostgreSQL RLS protection

**Files:**
- Modify: `backend/apps/common/rls_manifest.py`
- Modify: `backend/apps/common/management/commands/audit_rls_coverage.py`
- Modify: `backend/apps/common/tests/test_rls_manifest.py`
- Create: `backend/apps/growth/tests/test_postgres_email_verification_rls.py`
- Modify: `backend/apps/growth/migrations/0050_email_verification_pipeline.py`
- Modify: `.github/workflows/ci.yml`

- [ ] Classify both tables explicitly as tenant-direct, customer-content, background-task-access tables in RLS-2C, with an explicit early-policy marker that the audit command understands.
- [ ] Add PostgreSQL-only migration operations: ENABLE/FORCE RLS, tenant `USING`/`WITH CHECK`, mutable run policies, append-only evidence SELECT/INSERT policies, and reversible removal of only these policies.
- [ ] Ensure non-PostgreSQL migration behavior is a clear no-op for policy SQL.
- [ ] Write real runtime-role tests for no-context denial, A/B read and write isolation, evidence parent consistency, evidence UPDATE/DELETE denial, and runtime-role ownership/BYPASS invariants.
- [ ] Add the new PostgreSQL module to the existing runtime-role CI job; SQLite must skip it and must not count as RLS acceptance.
- [ ] Run manifest tests/audit and the PostgreSQL module against owner/runtime DSNs.

### Task 6: Configure bounded network behavior and privacy controls

**Files:**
- Modify: `backend/config/settings.py`
- Modify: `backend/config/test_settings.py`
- Modify: `docs/email-verification-a1-audit.md`
- Create: `docs/email-verification-a1-operations.md`

- [ ] Add environment-backed DNS timeout/lifetime, SMTP connect/read timeout, retry count, domain lock TTL, and minimum interval with conservative defaults and validation.
- [ ] Configure the production default cache to use the existing Redis URL while tests remain deterministic.
- [ ] Document no-DATA SMTP behavior, abuse controls, safe evidence fields, retention considerations, Provider fallback, and the fact that no screening percentage is guaranteed before real-data calibration.
- [ ] Document deployment ordering: stop task dispatch, owner migrate, role/bootstrap grants, runtime RLS checks, start workers, then verify organization-bearing task payloads.
- [ ] Document rollback using the owner role and migration reverse, with no deletion of historical migrations or unrelated data.

### Task 7: Migration round-trip and regression verification

**Files:**
- Create: `backend/apps/growth/tests/test_email_verification_migration.py`

- [ ] Write a migration executor test for `0049 -> 0050 -> 0049 -> 0050`, preserving pre-existing Growth data and restoring the complete `leaf_nodes()` graph in teardown.
- [ ] Run all Email Verification, Agent contact, outreach feedback, tenancy, manifest, and PostgreSQL RLS focused tests.
- [ ] Run complete backend tests.
- [ ] Run Ruff on changed Python files.
- [ ] Run Django system check and `makemigrations --check --dry-run`.
- [ ] Run `audit_rls_coverage` and `git diff --check`.
- [ ] Record exact pass counts and any environment-specific skips in the Draft PR.

### Task 8: Commit, push, and open Draft PR

**Files:**
- Modify: `docs/email-verification-a1-operations.md` only if final evidence needs correction.

- [ ] Review the diff against `origin/merge/consolidation-security` for unrelated changes, secrets, raw SMTP text, real addresses, and migration rewrites.
- [ ] Split implementation into minimal, accurately named commits after the already separate audit/plan commit.
- [ ] Push `feature/email-verification-a1` normally without force.
- [ ] Create a Draft PR targeting `merge/consolidation-security`; do not enable auto-merge and do not merge.
- [ ] Report baseline/head SHA, exact files, model and policy contracts, transaction-boundary evidence, test results, CI state, and clean worktree status.
