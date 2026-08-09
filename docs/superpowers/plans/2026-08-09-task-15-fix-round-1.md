# Task 15 Fix Round 1 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Harden the AI content workflow so audit responses are bounded and secret-safe, content head state is authoritative, all cursor pages are reachable, briefs are READY-complete, polling is unmount-safe, dialogs are accessible, and query failures are recoverable.

**Architecture:** Backend serializers expose explicit safe summaries and database-annotated lineage head facts. Frontend cursor resources use a shared user-driven accumulator keyed by organization and filters, while the full brief form is shared between create and edit flows. Each finding is implemented as a separate RED→GREEN cycle in the current session; no Task16 work and no subagents.

**Tech Stack:** Django 5.2, Django REST Framework, PostgreSQL-compatible ORM, Vue 3, TanStack Vue Query, TypeScript, Vitest, Testing Library.

## Global Constraints

- Every production behavior change must have a failing regression test observed before implementation.
- Keep organization/session query keys isolated and accept cursor links only through exact-path same-origin validation.
- Do not expose prompt templates or raw audit JSON; keep every AI Run response deterministically bounded.
- Preserve permission plus state guards in both rendered controls and event handlers.
- Finish with frontend full/typecheck/lint/build and backend focused/full/ruff/check/migration verification.

---

### Task 1: Bounded AI Audit Contract

**Files:**
- Modify: `backend/apps/ai/serializers.py`
- Modify: `backend/apps/ai/tests/test_ai_run_api.py`
- Modify if shared helper is justified by tests: `backend/apps/common/security.py`

**Interfaces:**
- Produces `bounded_audit_value(value, allowed_keys=...)` behavior with depth, object-key, list-item, string, and total-byte limits plus explicit truncation markers.
- `error` is always the controlled `normalize_persisted_error` shape; provider metadata is an allowlisted summary.

- [ ] Add API tests containing mixed-case key secrets, nested/list value secrets, oversized strings/arrays/maps, and a database refresh assertion proving serialization does not mutate stored JSON.
- [ ] Run `pytest apps/ai/tests/test_ai_run_api.py -q` and observe failures showing raw values or unbounded output.
- [ ] Implement allowlists, recursive value redaction, structural limits, total serialized-byte enforcement, and controlled error/provider metadata shapes.
- [ ] Re-run the AI API tests and retain the prompt-without-template assertion.

### Task 2: Authoritative Current Head

**Files:**
- Modify: `backend/apps/content/serializers.py`
- Modify: `backend/apps/content/views.py`
- Modify: `backend/apps/content/tests/test_content_api.py` or the existing content API hardening test module
- Modify: `frontend/src/modules/content/api.ts`
- Modify: `frontend/src/modules/content/ReviewCenterPage.vue`
- Modify: `frontend/src/modules/content/ReviewCenterPage.test.ts`

**Interfaces:**
- Master and platform response items include read-only boolean `is_current_head` sourced from an organization-scoped `Exists` annotation over all lineage rows.

- [ ] Add backend tests where the successor has another status and is beyond the requested cursor page; assert old false/new true and foreign-organization corruption does not affect the result, with bounded query count.
- [ ] Run focused content tests and observe missing/incorrect `is_current_head` failures.
- [ ] Annotate list and detail querysets with organization-scoped successor `Exists` facts and expose the field.
- [ ] Add a frontend regression test proving an old item with `is_current_head:false` never renders or executes review mutations.
- [ ] Remove page-local lineage inference and use the server field; run backend and frontend focused tests green.

### Task 3: User-Driven Cursor Pagination

**Files:**
- Modify: `frontend/src/modules/content/api.ts`
- Create: `frontend/src/modules/content/useCursorAccumulator.ts`
- Create: `frontend/src/modules/content/useCursorAccumulator.test.ts`
- Modify: `frontend/src/modules/content/ContentFactoryPage.vue`
- Modify: `frontend/src/modules/content/ContentBriefWizard.vue`
- Modify: `frontend/src/modules/content/ReviewCenterPage.vue`
- Modify: `frontend/src/modules/content/ContentFactoryPage.test.ts`
- Modify: `frontend/src/modules/content/ReviewCenterPage.test.ts`

**Interfaces:**
- The cursor accumulator fetches exactly one next page per user action, validates with `getCursorPage(url, exactPath)`, de-duplicates IDs, exposes loading/error/retry, and resets on organization/filter key changes.

- [ ] Add accumulator tests for exact-path rejection, duplicate-ID removal, terminal next=null, retry, and reset on a changed key.
- [ ] Run the new unit tests RED, then implement the minimal composable and run GREEN.
- [ ] Add page tests proving second-page products/assets become selectable, second-page master/platform content becomes reviewable, and filter changes discard accumulated rows.
- [ ] Run page tests RED, then wire campaigns/briefs/products/assets/jobs/master and review master/platform/campaign pagination with explicit load-more controls.
- [ ] Re-run focused tests and confirm no automatic infinite-page fetching.

### Task 4: READY-Complete Brief Form and Editing

**Files:**
- Modify: `frontend/src/modules/content/ContentBriefWizard.vue`
- Create or modify shared form component under `frontend/src/modules/content/`
- Modify: `frontend/src/modules/content/ContentFactoryPage.vue`
- Modify: `frontend/src/modules/content/ContentFactoryPage.test.ts`

**Interfaces:**
- Create and edit use one full form state containing six scalar fields, landing URL, three required arrays, products/assets/platforms, and preserved `concept_links`.

- [ ] Add a test proving each of selling points, advantages, and keywords must contain at least one normalized value and receives a field-visible error.
- [ ] Run RED, add field validation/focus, then run GREEN.
- [ ] Add an edit test asserting the exact PATCH includes every READY prerequisite and preserves products/assets/platforms/concept_links.
- [ ] Run RED, replace the reduced inline editor with the shared full accessible form, then run GREEN.
- [ ] Add and pass a test that READY revision clearly opens/presents the new DRAFT and that completing missing fields enables successful READY confirmation.

### Task 5: Polling In-Flight Unmount Safety

**Files:**
- Modify: `frontend/src/modules/content/ContentFactoryPage.vue`
- Modify: `frontend/src/modules/content/ContentFactoryPage.test.ts`

**Interfaces:**
- A mounted generation token (or AbortController) is checked after every await and before state/cache/timer work.

- [ ] Add a deferred `getJob` response test, unmount while it is in flight, resolve it, and assert no state write, invalidation, or new 2500ms timer.
- [ ] Run RED and observe the post-unmount timer/state side effect.
- [ ] Implement mounted-token checks around polling awaits and scheduling; retain job de-duplication, terminal stop, cancel, and timer cleanup.
- [ ] Re-run focused polling tests GREEN.

### Task 6: Modal Accessibility

**Files:**
- Modify shared brief form/dialog files from Task 4
- Modify: `frontend/src/modules/content/ContentFactoryPage.test.ts`

**Interfaces:**
- The edit modal uses `useModalFocus` for initial focus, Tab/Shift+Tab trapping, Escape, background inertness, and trigger focus restoration.

- [ ] Add an interaction test for initial focus, wraparound Tab directions, Escape closure, inert background, and restored trigger focus.
- [ ] Run RED, wire `useModalFocus`, then re-run GREEN.

### Task 7: Required Query Error Recovery and Final Verification

**Files:**
- Modify: `frontend/src/modules/content/ContentFactoryPage.vue`
- Modify: `frontend/src/modules/content/ContentBriefWizard.vue`
- Modify: `frontend/src/modules/content/ContentFactoryPage.test.ts`
- Add external report: `C:/Users/Administrator/Documents/网站/app/.superpowers/sdd/2026-08-08-sinofgear-phase-a/task-15-fix-round-1-report.md`

**Interfaces:**
- Each enabled required resource exposes a named load failure and resource-specific retry without treating permission-disabled queries as errors.

- [ ] Add product, platform, and job failure/recovery tests; run RED.
- [ ] Render named error panels and targeted retry handlers; disable the wizard when prerequisite products/platforms are unavailable; run GREEN.
- [ ] Run frontend full Vitest, `vue-tsc --noEmit`, ESLint, and Vite build.
- [ ] Run focused backend AI/content/campaign/jobs/platform tests, Ruff, Django check, migration check, then full pytest because public serializers changed.
- [ ] Review `git diff --check`, write the external report, and commit exactly `fix: harden content workflow pagination and audit safety`.
