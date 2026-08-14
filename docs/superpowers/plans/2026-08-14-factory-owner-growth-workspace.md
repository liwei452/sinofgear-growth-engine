# Factory-owner Growth Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deliver a locally runnable, evidence-first AI promotion and customer-acquisition MVP using the approved factory-owner UI concept.

**Architecture:** Add a bounded `growth` domain API for workspace snapshots and human-reviewed actions, backed by deterministic demo data and a no-network Fake Connector. Reuse the existing Vue shell, tracking, publishing, products, and knowledge foundations while replacing ordinary-user navigation and pages with five task-language workspaces.

**Tech Stack:** Django 5.2, Django REST Framework, Vue 3, TypeScript, TanStack Query, Vitest, pytest.

## Global Constraints

- Modify only `sinofgear-growth-engine`; do not read, modify, build, test, or integrate `../app`.
- No drawing upload/interpretation, engineering RFQ, quote, real OAuth, real publication, real email/private message, or LinkedIn scraping.
- Demo opportunities and metrics must be visibly labeled `Demo / Fake`.
- Every outbound draft requires human review and stays unsent.

---

### Task 1: Growth domain contracts and Fake Connector

**Files:** create `backend/apps/growth/` models, serializers, services, views, URLs, migrations, and tests; modify backend settings and root URLs.

- [ ] Write failing tests proving target account, contact, intent signal, inbound lead, follow-up, bilingual draft, channel package, metric, and field provenance remain distinct and organization-scoped.
- [ ] Run focused tests and verify the missing app/API failure.
- [ ] Implement the minimal models and `/api/v1/growth/workspace`, `/opportunities/{id}/follow-up`, and `/opportunities/{id}/draft` endpoints.
- [ ] Add a Fake Connector that only returns manual packages/simulated receipts and rejects external publication.
- [ ] Run growth tests, migration checks, API schema checks, and ruff.

### Task 2: Five-entry shell and approved Today workspace

**Files:** modify `frontend/src/app/AppShell.vue`, router, app wiring, and styles; replace dashboard page/tests; create `frontend/src/modules/growth/api.ts`.

- [ ] Write failing shell/router tests for exactly `今天 / 推广 / 客户机会 / 效果 / 我的公司`.
- [ ] Write failing dashboard tests for evidence labels, explainable visibility, AI knowledge gaps, five channels, and the three opportunity actions.
- [ ] Run focused tests and verify they fail against the old grouped administration UI.
- [ ] Implement the two-column approved concept with responsive card ordering and safe demo fallback.
- [ ] Run focused tests, typecheck, lint, and build.

### Task 3: Promotion, opportunity, effectiveness, and company workspaces

**Files:** create focused Vue pages/components under `frontend/src/modules/growth/`; modify router and app wiring.

- [ ] Write failing tests for ICP review, bilingual content, the complete TikTok 15–60 second 9:16 package, follow-up/draft/evidence actions, metric evidence, and fact provenance.
- [ ] Run focused tests and verify missing route/component failures.
- [ ] Implement the four pages using the growth API and explicit loading/error/retry states.
- [ ] Keep administrator-only legacy routes out of ordinary navigation but addressable for authorized future use.
- [ ] Run focused tests and all frontend gates.

### Task 4: Local acceptance and safety audit

**Files:** add/update growth E2E coverage and `docs/acceptance/2026-08-14-growth-workspace.md`.

- [ ] Add a browser journey for evidence inspection, follow-up, bilingual draft, and TikTok package review.
- [ ] Verify no network write path exists outside the local API and Fake Connector.
- [ ] Run backend tests, migration checks, frontend tests, typecheck, lint, build, and E2E.
- [ ] Record exact evidence, known environment limitations, and rollback files in the acceptance report.
