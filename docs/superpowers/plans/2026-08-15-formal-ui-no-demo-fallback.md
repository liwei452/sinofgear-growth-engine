# Formal UI No Demo Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove automatic Demo/fabricated content from every ordinary user page and replace it with truthful empty states wired to existing workflows.

**Architecture:** Keep test fixtures and existing APIs intact. Add page-local formal selectors that exclude Demo records, delete hardcoded fallback arrays/content, and render one shared interaction pattern: empty reason plus real next-step links.

**Tech Stack:** Vue 3, TypeScript, TanStack Vue Query, Vitest, Testing Library, Playwright.

## Global Constraints

- Only modify `C:\Users\Administrator\Documents\网站\sinofgear-growth-engine`.
- Do not modify the independent website, add real outbound publishing, OAuth, paid APIs, scraping, or production deployment.
- Do not delete test fixtures or user data.
- Ordinary UI must never auto-load Demo/Fake records.

---

### Task 1: Clean the Today dashboard

**Files:**
- Modify: `frontend/src/modules/dashboard/DashboardPage.vue`
- Test: `frontend/src/modules/dashboard/DashboardPage.test.ts`

- [ ] Add a failing empty-workspace test asserting no PackTech, fixed score, ISO claim, fixed channel values, or sparkline appears.
- [ ] Add a failing test that Demo API records are excluded while non-Demo evidence is rendered.
- [ ] Remove `demoOpportunities` and fixed `channels`; derive formal opportunities and metric receipts only.
- [ ] Replace visibility and channel fallbacks with empty reasons and links to `/company`, `/opportunities`, and `/analytics`.
- [ ] Run `DashboardPage.test.ts` and commit the working page.

### Task 2: Clean Promotion and channel readiness

**Files:**
- Modify: `frontend/src/modules/growth/PromotionPage.vue`
- Test: `frontend/src/modules/growth/GrowthWorkspacePages.test.ts`

- [ ] Add failing assertions that an empty workspace has no fixed TikTok script, CTA, UTM, or fake package cards.
- [ ] Filter Demo channel packages out of formal package selectors and treat `DEMO_FAKE` connectors as not officially connected.
- [ ] Remove fallback approval and TikTok placeholder content; render a single empty panel linked to `/content-factory` and `/reviews`.
- [ ] Verify real approved packages, manual export, and official connection paths remain usable.
- [ ] Run the growth workspace test and commit.

### Task 3: Filter opportunities and effectiveness

**Files:**
- Modify: `frontend/src/modules/growth/OpportunitiesPage.vue`
- Modify: `frontend/src/modules/growth/EffectivenessPage.vue`
- Modify: `frontend/src/modules/growth/AccountAttributionPanel.vue`
- Test: `frontend/src/modules/growth/GrowthWorkspacePages.test.ts`
- Test: `frontend/src/modules/growth/AccountAttributionPanel.test.ts`

- [ ] Add failing tests proving Demo accounts, signals, receipts, and funnel rows do not render in formal mode.
- [ ] Filter formal account/signal/contact/receipt selectors without changing persisted data.
- [ ] Replace the effectiveness header Demo badge with a truthful recorded/empty state.
- [ ] Verify empty denominators remain “尚未发生/无数据” and real manual records remain traceable.
- [ ] Run both test files and commit.

### Task 4: Audit company, review, and calendar empty actions

**Files:**
- Modify: `frontend/src/modules/growth/CompanyPage.vue`
- Modify: `frontend/src/modules/content/ReviewCenterPage.vue`
- Modify: `frontend/src/modules/publishing/PublishingCalendarPage.vue`
- Test: `frontend/src/modules/growth/GrowthWorkspacePages.test.ts`
- Test: `frontend/src/modules/content/ReviewCenterPage.test.ts`
- Test: `frontend/src/modules/publishing/PublishingCalendarPage.test.ts`

- [ ] Assert each empty page explains why it is empty and offers a real route.
- [ ] Remove dead buttons and replace them with links to `/assets`, `/content-factory`, `/promotion`, or `/platform-accounts` as appropriate.
- [ ] Verify real records and permissions still control actions.
- [ ] Run the three targeted test files and commit.

### Task 5: Full verification and browser acceptance

**Files:**
- Modify only files required by failures introduced in Tasks 1-4.

- [ ] Run all frontend tests; expected result is zero failures.
- [ ] Run Vue typecheck and ESLint on changed files; expected result is zero errors.
- [ ] Build the production frontend; expected result is success.
- [ ] Run Playwright E2E and inspect empty `/`, `/promotion`, `/opportunities`, `/analytics`, `/company`, `/reviews`, and `/publishing-calendar` pages at `http://127.0.0.1:3001`.
- [ ] Confirm no ordinary page contains fabricated company names, qualifications, scores, channel results, scripts, or trends; commit the final slice.
