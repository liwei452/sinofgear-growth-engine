# User-Selected Watch Market Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Let an empty formal workspace create a truthful organization-owned watch market and continue into the existing candidate import flow.

**Architecture:** Add one validated create-or-reset endpoint around `MarketCountryProfile`, then add a small form to `MarketPilotComparison`. Reuse the existing workspace refresh and `selectMarket` event; store no inferred scores or evidence.

**Tech Stack:** Django REST Framework, pytest, Vue 3, TanStack Query, Vitest.

## Global Constraints

- Only modify `sinofgear-growth-engine`.
- No external fetch, paid API, OAuth, publishing, messaging, or independent-site changes.
- New watch records must be non-demo but must not claim recommendation, evidence, sample quality, or demand.

---

### Task 1: Organization-scoped watch-market creation

**Files:**
- Modify: `backend/apps/growth/serializers.py`
- Modify: `backend/apps/growth/views.py`
- Modify: `backend/apps/growth/urls.py`
- Test: `backend/apps/growth/tests/test_market_pilots.py`

**Interfaces:**
- Consumes: `{country_code, country_label, path_family}`.
- Produces: a safe market payload with `is_demo=false`, `is_watched=true`, empty scores/sample evidence, and `created`.

- [ ] Write API tests for validation, idempotency, reset of demo research fields, and organization isolation.
- [ ] Run the targeted tests and confirm the new endpoint is absent.
- [ ] Implement the serializer and transactional create-or-reset service in the view.
- [ ] Run the targeted tests and confirm they pass.

### Task 2: Empty-radar market selection form

**Files:**
- Modify: `frontend/src/modules/growth/api.ts`
- Modify: `frontend/src/modules/growth/MarketPilotComparison.vue`
- Test: `frontend/src/modules/growth/MarketPilotComparison.test.ts`

**Interfaces:**
- Consumes: `createWatchMarket({countryCode, countryLabel, pathFamily})`.
- Produces: query invalidation plus the existing `selectMarket` event for candidate import.

- [ ] Write a component test that submits an empty-radar selection and asserts the exact safe request.
- [ ] Run it and confirm the form/action is missing.
- [ ] Implement the API helper, form, loading/error states, and workspace refresh.
- [ ] Run the component tests and confirm they pass.

### Task 3: Regression and browser acceptance

**Files:**
- Modify: `frontend/e2e/zz-growth-workspace-persistence.spec.ts`
- Modify: `docs/acceptance/2026-08-14-growth-workspace.md`

- [ ] Extend the clean-workspace browser test to create a watch market, reload, and open candidate import without Demo/Fake content.
- [ ] Run targeted backend/frontend tests, then one full frontend/backend regression, typecheck, lint, build, and E2E.
- [ ] Commit the verified slice and keep `http://127.0.0.1:3001` available.

