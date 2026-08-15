# Account-Level Effectiveness Attribution Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a truthful, filterable account-level acquisition funnel to the effectiveness page using only events already recorded in the growth workspace.

**Architecture:** A focused Vue component receives the existing `GrowthWorkspace`, derives de-duplicated stage counts and account evidence in computed values, and emits no writes. `EffectivenessPage.vue` mounts it above auxiliary channel metrics; Playwright verifies persisted approval appears after refresh while send/reply/demand remain empty.

**Tech Stack:** Vue 3 Composition API, TypeScript, Vitest, Testing Library, Playwright, existing growth workspace API.

## Global Constraints

- Only modify `C:\Users\Administrator\Documents\网站\sinofgear-growth-engine`.
- Do not modify the independent website, drawings/RFQ, AEO, OAuth, paid APIs, real scraping, real sending, or production deployment.
- Count only persisted workspace facts; missing send, reply, and valid-demand events render as “尚未发生 / 无数据”.
- Keep Demo/Fake separate from licensed or manually recorded data.
- Do not add a database model or migration for filtering or attribution.

---

### Task 1: Account Attribution Panel

**Files:**
- Create: `frontend/src/modules/growth/AccountAttributionPanel.test.ts`
- Create: `frontend/src/modules/growth/AccountAttributionPanel.vue`
- Modify: `frontend/src/modules/growth/growth-pages.css`

**Interfaces:**
- Consumes: `workspace: GrowthWorkspace` prop.
- Produces: a `region` named `账户获客漏斗`, stage controls, simple filters, metric explanations, and account/candidate evidence articles.

- [ ] **Step 1: Write the failing component tests**

Create fixtures with one approved strategic Demo/Fake account, one observation account, accepted/enriched candidates, follow-up, draft, CRM handoff, intent evidence, and provenance cost. Assert literal counts and ratios, account evidence, Demo separation, stage filtering, and “尚未发生 / 无数据” for send/reply/demand.

- [ ] **Step 2: Run the focused test and verify RED**

Run: `pnpm test --run src/modules/growth/AccountAttributionPanel.test.ts`

Expected: FAIL because `AccountAttributionPanel.vue` does not exist.

- [ ] **Step 3: Implement the smallest derivation and presentation component**

Use computed sets keyed by account/candidate ID. Keep absent future stages as `null`; do not reuse channel metric receipts as account events. Expose native buttons and selects so stage/filter behavior is keyboard accessible.

- [ ] **Step 4: Run focused tests and verify GREEN**

Run: `pnpm test --run src/modules/growth/AccountAttributionPanel.test.ts`

Expected: all panel tests PASS.

- [ ] **Step 5: Run type and lint checks**

Run: `pnpm typecheck && pnpm lint`

Expected: both exit 0.

### Task 2: Effectiveness Page Integration

**Files:**
- Modify: `frontend/src/modules/growth/EffectivenessPage.vue`
- Modify: `frontend/src/modules/growth/GrowthWorkspacePages.test.ts`

**Interfaces:**
- Consumes: successful `growthWorkspaceQueryOptions()` response.
- Produces: the account funnel immediately after the effectiveness page header without changing metric backfill behavior.

- [ ] **Step 1: Add a failing page integration assertion**

Render a workspace with attribution records and assert the page shows `账户获客漏斗` and an account name before the auxiliary channel result section.

- [ ] **Step 2: Run the page test and verify RED**

Run: `pnpm test --run src/modules/growth/GrowthWorkspacePages.test.ts`

Expected: FAIL because the page does not mount the panel.

- [ ] **Step 3: Mount the panel**

Import `AccountAttributionPanel` and render it when the workspace query has data. Keep loading behavior empty and non-blocking.

- [ ] **Step 4: Run focused frontend tests and verify GREEN**

Run: `pnpm test --run src/modules/growth/AccountAttributionPanel.test.ts src/modules/growth/GrowthWorkspacePages.test.ts`

Expected: all focused tests PASS.

### Task 3: Browser Persistence and Full Regression

**Files:**
- Modify: `frontend/e2e/zz-growth-workspace-persistence.spec.ts`
- Modify: `docs/superpowers/plans/2026-08-14-ai-growth-loop-development-acceptance-checklist.md`

**Interfaces:**
- Consumes: persisted PackTech approval and NordMotion observation events created earlier in the E2E flow.
- Produces: browser evidence that approval survives refresh, observation remains evidence-only, and future stages are empty.

- [ ] **Step 1: Add E2E assertions after reactivation persistence**

Navigate to `/analytics`, reload, assert PackTech is in `人工批准`, NordMotion recommends evidence completion, and `人工发送`, `回复`, `有效需求` each show `尚未发生` or `无数据`. Return to `/opportunities` and continue the existing market/candidate journey.

- [ ] **Step 2: Run the targeted E2E**

Run: `pnpm test:e2e -- zz-growth-workspace-persistence.spec.ts`

Expected: 1 test PASS.

- [ ] **Step 3: Run full verification**

Run frontend unit tests, backend tests, API generation check, typecheck, lint, production build, and the full E2E suite. Expected: every command exits 0.

- [ ] **Step 4: Record acceptance evidence and commit**

Update the acceptance checklist with actual command counts and browser evidence, then commit all slice files with message `feat: add account-level growth attribution`.
