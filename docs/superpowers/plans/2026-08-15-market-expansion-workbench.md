# Market Expansion Workbench Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a searchable, filterable, persistent market expansion workbench connected to the existing candidate import flow.

**Architecture:** Extend the existing organization-owned market profile with only the presentation metadata and watched state required by the UI. Keep filtering client-side and reuse the existing market-selection event to open licensed-list and public-lead imports.

**Tech Stack:** Django/DRF, Vue 3, TanStack Query, Vitest, Playwright.

## Global Constraints

- Work only in `sinofgear-growth-engine`.
- No real scraping, paid APIs, OAuth, sending, AEO, independent-site, drawing, or RFQ work.
- Every simulated market record is labeled Demo / research configuration.

---

### Task 1: Persistent market metadata and watch action

**Files:** `backend/apps/growth/models.py`, `backend/apps/growth/market_pilots.py`, `backend/apps/growth/views.py`, `backend/apps/growth/urls.py`, migration and tests.

- [ ] Write failing tests for required countries, two route families, metadata, organization-scoped watch persistence, and permissions.
- [ ] Run focused tests and confirm missing fields/route fail.
- [ ] Add the minimal profile fields, maintainable country configuration, serializer payload, and watch endpoint.
- [ ] Run focused backend tests and migration/lint checks.

### Task 2: Searchable market workbench

**Files:** `frontend/src/modules/growth/MarketPilotComparison.vue`, `frontend/src/modules/growth/api.ts`, component tests.

- [ ] Write failing UI tests for country search, region/path/data filters, sorting, visible evidence/risk, watch persistence action, and candidate-entry event.
- [ ] Run the focused test and confirm controls are absent.
- [ ] Implement compact controls and cards using computed filtering; wire watch mutation and existing selection event.
- [ ] Run focused tests, typecheck, and lint.

### Task 3: Browser acceptance and delivery

**Files:** `frontend/e2e/zz-growth-workspace-persistence.spec.ts`, acceptance checklist.

- [ ] Extend E2E through search, watch, refresh, and market-to-candidate import.
- [ ] Run E2E, backend/full frontend tests, typecheck, lint, and build.
- [ ] Update evidence counts, migrate/restart local preview, commit the slice, and verify ports 3001/8000.
