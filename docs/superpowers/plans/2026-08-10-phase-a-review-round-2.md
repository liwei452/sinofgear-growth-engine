# Phase A Review Round 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all six Task 18 round-two findings with durable per-run ownership, safe process cleanup, exact ontology and analytics behavior, and warning-free verification.

**Architecture:** A private identity-app ownership marker stores only a random nonce and HMAC signature bound to the canonical run root; the launcher alone creates the per-run secret. Cleanup and filesystem ownership validation remain separate boundaries. Backend-supported brief concept roles and analytics provenance are surfaced explicitly in the UI, while Playwright exercises only real UI workflows and browser navigation.

**Tech Stack:** Django 5.2, SQLite/PostgreSQL-compatible models, Python HMAC, Vue 3, TypeScript, Node child processes, Playwright, pytest, Vitest.

## Global Constraints

- Every behavior change follows RED → GREEN with a focused real-behavior test.
- No ownership secret may enter logs, API schemas, documentation values, generated types, or committed fixture data.
- E2E state and artifacts remain inside a canonical direct child of the OS temporary root.
- No subagents are used; execution remains inline in the assigned Task 18 session.

---

### Task 1: Durable E2E ownership proof

**Files:**
- Modify: `backend/apps/identity/models.py`
- Create: `backend/apps/identity/migrations/0010_phaseae2eownership.py`
- Modify: `backend/apps/common/management/commands/seed_phase_a.py`
- Modify: `backend/apps/common/tests/test_seed_phase_a.py`
- Modify: `backend/config/e2e_settings.py`
- Modify: `frontend/e2e/launcher.mjs`
- Modify: `frontend/e2e/launcher.test.mjs`

**Interfaces:**
- Consumes: `PHASE_A_E2E_OWNERSHIP_SECRET` and canonical `PHASE_A_E2E_RUN_ID` settings.
- Produces: private `PhaseAE2EOwnership(organization, nonce, signature)` and HMAC verification before any rerun mutation.

- [ ] Add failing tests for fixed-org collision, missing/bad/copied signature, valid rerun, transaction rollback, and launcher secret propagation.
- [ ] Run focused pytest/Node tests and confirm failures are ownership-proof failures.
- [ ] Add the private model/migration, strict settings validation, HMAC create/verify logic, and launcher-generated 32-byte secret.
- [ ] Run focused tests until green and inspect schema/API output for absence of secret fields.

### Task 2: Cleanup ordering and canonical direct-child validation

**Files:**
- Modify: `frontend/e2e/launcher.mjs`
- Modify: `frontend/e2e/launcher.test.mjs`
- Modify: `backend/config/tests/test_e2e_paths.py`

**Interfaces:**
- Produces: `cleanupOwnedRun` always terminates children before guarded removal; `assertOwnedRunRoot` accepts only a canonical direct temp child.

- [ ] Add failing live-child/missing-root and marked nested-grandchild launcher tests, plus backend nested-child rejection.
- [ ] Run focused tests and confirm current early return/nested acceptance failures.
- [ ] Separate process termination from filesystem guard and compare canonical parent equality.
- [ ] Run launcher and backend path tests until green.

### Task 3: Complete brief ontology mapping

**Files:**
- Modify: `backend/apps/campaigns/models.py`
- Create: `backend/apps/campaigns/migrations/0002_brief_product_process_roles.py`
- Modify: `frontend/src/modules/content/api.ts`
- Modify: `frontend/src/modules/content/ContentBriefWizard.vue`
- Modify: `frontend/src/modules/content/ContentFactoryPage.test.ts`
- Update generated API artifact if schema changes.

**Interfaces:**
- Produces exact roles `PRODUCT_TYPE` for `GEAR_TYPE` and `MANUFACTURING_PROCESS` for `PROCESS`, alongside existing STANDARD/INDUSTRY mappings.

- [ ] Add backend and frontend failing tests for Helical Gear, Grinding, DIN, and Packaging Machinery exact roles; inject an unsupported type and assert it is absent or visibly rejected.
- [ ] Run focused tests and confirm missing roles/silent filtering failures.
- [ ] Add backend role/type constraints and exhaustive frontend mapping with explicit submit error for any selected unmapped concept.
- [ ] Run focused suites and migration/API drift checks until green.

### Task 4: Provenance-visible analytics and exact browser acceptance

**Files:**
- Modify: `frontend/src/modules/analytics/AnalyticsPage.vue`
- Modify: `frontend/src/modules/analytics/AnalyticsPage.test.ts`
- Modify: `frontend/e2e/phase-a-active-growth.spec.ts`

**Interfaces:**
- Produces visible campaign/platform IDs in analytics rows and browser-observed 302 response/Location before expected downstream `.invalid` failure.

- [ ] Add failing analytics UI tests for visible campaign/platform provenance and extend E2E assertions to four product/asset/brief/AIRun ontology links.
- [ ] Confirm UI test failure, then expose campaign and platform columns with accessible labels.
- [ ] Extend UI-only E2E to produce a second click with different campaign/platform provenance, assert unfiltered total ≥2 and exact target filters =1, and navigate a real browser page through `/r/` while capturing 302 and Location.
- [ ] Run E2E, diagnose each real failure, and repeat until the full flow passes twice consecutively.

### Task 5: Warning-free props and final verification

**Files:**
- Modify: `frontend/src/modules/content/ContentBriefWizard.vue`
- Modify: Task 18 external report and progress ledger after commit.

**Interfaces:**
- Produces explicit `brief: null` default and zero ESLint warnings.

- [ ] Add the null default and run focused lint with `--max-warnings 0`.
- [ ] Run backend full pytest, Ruff, migration drift, schema validation, frontend full Vitest, lint with zero warnings, typecheck, API drift, build, launcher tests, and E2E twice.
- [ ] Verify `git diff --check`, absence of repo artifacts/secrets/temp roots/processes, commit, then update report and ledger.
