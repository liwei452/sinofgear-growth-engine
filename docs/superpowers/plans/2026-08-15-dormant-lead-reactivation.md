# Dormant Lead Reactivation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a persisted, human-reviewed dormant-lead reactivation flow restricted to existing legal relationships.

**Architecture:** Add one organization-owned reactivation aggregate and append-only account funnel events, while reusing `TargetAccount`, `IntentSignal`, and `OutreachDraft`. Expose three narrow endpoints and a single owner-friendly Vue card on the opportunities page.

**Tech Stack:** Django, Django REST Framework, Vue 3, TanStack Query, Vitest, Playwright.

## Global Constraints

- Only existing relationships or legally owned lists may enter reactivation.
- Observation accounts never receive outreach drafts.
- Approval records approval only and must always return `delivery: NEVER_SENT`.
- No real sending, OAuth, scraping, paid APIs, independent-site work, AEO, or RFQ work.

---

### Task 1: Persist reactivation and funnel events

**Files:**
- Modify: `backend/apps/growth/models.py`
- Create: `backend/apps/growth/migrations/0016_*.py`
- Test: `backend/apps/growth/tests/test_reactivation.py`

**Interfaces:**
- Produces: `ReactivationRecord` and `AccountFunnelEvent` organization-owned models.

- [ ] Write model/API integration tests proving organization isolation and required relationship metadata.
- [ ] Run `python -m pytest apps/growth/tests/test_reactivation.py -q` and verify the missing models/routes fail.
- [ ] Add the minimal models and migration with an organization/account uniqueness constraint.
- [ ] Re-run the focused test until model persistence passes.

### Task 2: Enforce tier and draft safety in services and API

**Files:**
- Create: `backend/apps/growth/reactivation.py`
- Modify: `backend/apps/growth/serializers.py`
- Modify: `backend/apps/growth/views.py`
- Modify: `backend/apps/growth/urls.py`
- Test: `backend/apps/growth/tests/test_reactivation.py`

**Interfaces:**
- Produces: `select_for_reactivation(account, ...)`, `create_reactivation_draft(record)`, and `approve_reactivation_draft(record, reviewer)`.

- [ ] Add failing tests for unconfirmed relationships, future interaction dates, observation-tier draft rejection, safe personalized text, approval-only delivery, idempotent events, and tenant isolation.
- [ ] Implement score-derived tiers and strict validation without inventing contacts, intent, or cases.
- [ ] Expose select, draft, and approve endpoints plus workspace serialization.
- [ ] Re-run focused tests and verify every branch is green.

### Task 3: Add the owner-facing reactivation card

**Files:**
- Create: `frontend/src/modules/growth/ReactivationWorkbench.vue`
- Create: `frontend/src/modules/growth/ReactivationWorkbench.test.ts`
- Modify: `frontend/src/modules/growth/api.ts`
- Modify: `frontend/src/modules/growth/OpportunitiesPage.vue`

**Interfaces:**
- Consumes: workspace `reactivations` and the three reactivation endpoints.
- Produces: legal-list selection form, evidence/risk card, safe draft review, approval-only timeline.

- [ ] Write a failing component test for legal selection, observation blocking, draft approval, and `NEVER_SENT` messaging.
- [ ] Implement the API types/functions and minimal card.
- [ ] Integrate it above the general opportunity queue and invalidate the workspace after every mutation.
- [ ] Run the focused Vitest, typecheck, and lint.

### Task 4: Browser acceptance and release evidence

**Files:**
- Modify: `frontend/e2e/zz-growth-workspace-persistence.spec.ts`
- Modify: `docs/superpowers/plans/2026-08-14-ai-growth-loop-development-acceptance-checklist.md`

**Interfaces:**
- Proves: persisted legal-list approval flow and low-evidence blocking without delivery.

- [ ] Add E2E steps selecting a legal Demo account, generating and approving a draft, reloading, and confirming no-send state.
- [ ] Add E2E steps selecting a low-evidence account and confirming draft generation is blocked.
- [ ] Run focused backend/frontend tests and E2E.
- [ ] Run full backend tests, full frontend tests, typecheck, lint, build, and complete E2E.
- [ ] Update acceptance evidence, commit the slice, and verify ports 3001 and 8000 remain healthy.

