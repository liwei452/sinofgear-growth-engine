# Market Pilot Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add an honest Indonesia-versus-South-Africa acquisition-route comparison and complete opportunity evidence taxonomy.

**Architecture:** Keep market strategy in a small backend policy module and expose it through the existing growth workspace response. Extend the existing EvidenceEnvelope without creating a second evidence store, then render a simple comparison component and evidence labels in the existing opportunities page.

**Tech Stack:** Django 5.2, Django REST Framework, Vue 3, TypeScript, Vitest, pytest, Playwright.

## Global Constraints

- Indonesia and South Africa are the only active MVP markets; Vietnam and Philippines remain quality-gated.
- Empty denominators render as `null`/“待采样”, never invented rates.
- Aggregate trade data cannot become company-level direct purchase evidence.
- No payment, OAuth, production deployment, LinkedIn scraping, automatic DM, or unreviewed send.

---

### Task 1: Market policy API

**Files:**
- Create: `backend/apps/growth/market_pilots.py`
- Modify: `backend/apps/growth/views.py`
- Test: `backend/apps/growth/tests/test_market_pilots.py`

**Interfaces:**
- Produces: `market_pilot_summary(signals, accounts) -> dict` with `markets`, `quality_gate`, `search_policy`, and `validation_goals`.

- [x] Write a failing test asserting two active markets, two gated markets, exact 200/80/70/90/10 thresholds and `null` rates without samples.
- [x] Run `python -m pytest apps/growth/tests/test_market_pilots.py -q` and verify the missing summary fails.
- [x] Implement immutable policy constants and workspace serialization; compute only rates with verified denominators and sum saved source cost.
- [x] Run the focused test and `apps/growth/tests/test_discovery_api.py` until green.
- [x] Commit the policy API.

### Task 2: Evidence source taxonomy

**Files:**
- Modify: `backend/apps/growth/discovery.py`
- Modify: `backend/apps/growth/manual_imports.py`
- Modify: `backend/apps/growth/tests/test_discovery_service.py`
- Modify: `backend/apps/growth/tests/test_manual_opportunity_import.py`

**Interfaces:**
- Extends: `IntentSignal.evidence_envelope` with `source_type`, `matched_keywords`, `company_match_confidence`, and `ai_exclusion_reasons`.

- [x] Write failing tests requiring `TENDER` for official procurement and `COMPANY_WEB` for manual URL import.
- [x] Run the two focused test modules and verify the new assertions fail.
- [x] Add the minimal envelope fields while retaining original text, URL, observation time, license, cost, and review status.
- [x] Add a policy validator proving `AGGREGATE_TRADE` is market context only and cannot become a company opportunity.
- [x] Run focused source, discovery, and import tests until green.

### Task 3: Owner-facing market comparison

**Files:**
- Create: `frontend/src/modules/growth/MarketPilotComparison.vue`
- Create: `frontend/src/modules/growth/MarketPilotComparison.test.ts`
- Modify: `frontend/src/modules/growth/api.ts`
- Modify: `frontend/src/modules/growth/OpportunitiesPage.vue`
- Modify: `frontend/src/modules/growth/growth-pages.css`
- Modify: `frontend/src/modules/growth/GrowthWorkspacePages.test.ts`

**Interfaces:**
- Consumes: `GrowthWorkspace.market_pilots` from Task 1.
- Produces: a compact two-route comparison plus gated-market note.

- [x] Write failing component tests for active/gated markets, “待采样”, and the three comparison metrics.
- [x] Run Vitest and verify the component is missing.
- [x] Implement the component and typed API contract; keep internal connector and queue names out of UI copy.
- [x] Extend evidence detail labels for source type, keywords, company match confidence, and AI exclusion reasons.
- [x] Run focused Vue tests until green.

### Task 4: Acceptance

**Files:**
- Modify: `frontend/e2e/zz-growth-workspace-persistence.spec.ts`
- Modify: `docs/superpowers/plans/2026-08-14-ai-growth-loop-development-acceptance-checklist.md`

- [x] Add browser assertions for the two active routes, two gated markets, honest empty metrics, and evidence source type.
- [x] Run migration drift, Ruff, Django check, typecheck, ESLint, production build, full pytest, full Vitest, and Playwright E2E.
- [x] Record fresh counts and known external-data limitations in the acceptance checklist.
- [x] Commit and keep `feature/phase-a` local without push or merge.

### Task 5: Extensible market radar

**Files:**
- Modify: `backend/apps/growth/market_pilots.py`
- Modify: `backend/apps/growth/tests/test_market_pilots.py`
- Modify: `frontend/src/modules/growth/MarketPilotComparison.vue`
- Modify: `frontend/src/modules/growth/MarketPilotComparison.test.ts`
- Modify: `frontend/src/modules/growth/api.ts`

**Interfaces:**
- Extends: `MarketPilotSummary.markets` with five-stage status, weighted score inputs, source types, freshness, sample quality, 20-company evidence threshold, recommended wave, recommendation reasons and hold reasons.

- [x] Write failing backend tests for 15 radar markets, exact score weights, Chile priority and India's `TENDER + COMPANY_WEB` restriction.
- [x] Replace the four-country policy with the five-stage extensible country radar; keep scores null until evidence exists.
- [x] Write failing component assertions for radar weights, country detail fields and explainable reasons.
- [x] Render compact expandable candidate rows without adding a new technical navigation area.
- [x] Run backend and frontend focused tests, then include the radar in full acceptance.
