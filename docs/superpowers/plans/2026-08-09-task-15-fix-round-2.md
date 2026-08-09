# Task 15 Fix Round 2 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the remaining public-audit redaction, cursor generation race, review filter query recovery, and wizard backend-error focus gaps.

**Architecture:** Keep audit summarization schema-driven but replace partial secret substitution with a fail-closed whole-string decision based on Unicode-normalized marker detection. Add monotonic generations and disposal to the cursor composable, keep review query recovery at the page boundary, and centralize wizard backend field alias/step/focus mapping.

**Tech Stack:** Django/DRF/Python, Vue 3/TypeScript, TanStack Vue Query, Vitest/Testing Library, pytest.

## Global Constraints

- Work only on Task 15 fix round 2; do not start Task 16.
- Every production change follows an observed RED test, then focused GREEN.
- Preserve existing allowlists, bounds, truncation, database immutability, READY validation, exact-path cursors, and permission guards.
- Final commit message is exactly `fix: close audit redaction and cursor race gaps`.
- Write the external report to `task-15-fix-round-2-report.md`.

---

### Task 1: Fail-closed public audit text sanitizer

**Files:**
- Modify: `backend/apps/ai/serializers.py`
- Test: `backend/apps/ai/tests/test_ai_run_api.py`

**Interfaces:**
- Consumes: every schema-allowed string processed by `_allowlisted_summary`.
- Produces: `_redact_and_bound_string(value: str) -> str`, returning `[REDACTED]` for any normalized credential/authentication marker and otherwise retaining the bounded safe value.

- [ ] Add table-driven API tests with unique sentinels for Basic/Bearer, quoted and Unicode separators, snake/camel/space credential assignments, query/fragment parameters, full-width variants, and safe unassigned phrases.
- [ ] Run the focused audit test and confirm sentinel leakage under the existing partial replacement.
- [ ] Implement Unicode NFKC/casefold marker detection and whole-string fail-closed redaction.
- [ ] Run all AI API tests and confirm allowlist/bounds/truncation/database non-mutation remain green.

### Task 2: Cursor generation isolation and disposal

**Files:**
- Modify: `frontend/src/modules/content/useCursorCollection.ts`
- Test: `frontend/src/modules/content/ReviewCenterPage.test.ts`

**Interfaces:**
- Consumes: first-page ref, exact path, reset key, identity function.
- Produces: the existing collection contract plus generation-scoped state writes and `dispose()` lifecycle cleanup.

- [ ] Add deferred component tests where an old page resolves or rejects after filter/organization reset and after the new generation finishes.
- [ ] Run focused tests and confirm old items/error/next/loading overwrite the new generation.
- [ ] Increment a monotonic generation on reset, capture it per load, gate success/catch/finally, and dispose on component unmount.
- [ ] Run cursor/API/page tests and confirm one-page loading, de-duplication, reset, retry, and end stopping remain green.

### Task 3: Review campaign/platform first-page recovery

**Files:**
- Modify: `frontend/src/modules/content/ReviewCenterPage.vue`
- Test: `frontend/src/modules/content/ReviewCenterPage.test.ts`

**Interfaces:**
- Consumes: `campaignsQuery.isError/error/refetch` and `platformsQuery.isError/error/refetch`.
- Produces: named safe error panels with `重新加载活动` and `重新加载平台` actions; cursor errors continue through the same safe presentation.

- [ ] Add first-request 503 tests for campaigns and platforms, retry, and assert recovered options.
- [ ] Run focused tests and confirm retry controls are absent.
- [ ] Render permission-aware first-page errors and call the matching query `refetch` from each named action.
- [ ] Run the review suite and confirm disabled queries do not report errors.

### Task 4: Wizard backend field errors, step routing, and real focus

**Files:**
- Modify: `frontend/src/modules/content/ContentBriefWizard.vue`
- Test: `frontend/src/modules/content/ContentFactoryPage.test.ts`

**Interfaces:**
- Consumes: `ApiError.fieldErrors` from create/PATCH responses.
- Produces: canonical field names, target step selection, visible per-field messages, and focus on the real first product/platform checkbox, scalar control, or alert summary.

- [ ] Add tests for product/platform aliases, cross-field selling-points/prohibited-claims errors, and unknown/non-field errors.
- [ ] Run focused tests and confirm the wizard stays on confirmation with only a generic alert.
- [ ] Implement alias mapping (`products`/`product_ids`, `platforms`/`platform_ids`/`target_platforms`), step routing, next-tick focus helpers, and alert fallback focus.
- [ ] Run wizard/factory tests and confirm existing client READY validation remains green.

### Task 5: Verification, report, and commit

**Files:**
- Create: external `task-15-fix-round-2-report.md`

**Interfaces:**
- Produces: verified clean commit and concise handoff.

- [ ] Run frontend full tests, typecheck, lint, and build.
- [ ] Run backend AI focused and related tests, Ruff, Django check, and migration drift check; run full backend tests if changes affect shared behavior.
- [ ] Run `git diff --check`, inspect scope/status, and write the external report.
- [ ] Commit exactly as `fix: close audit redaction and cursor race gaps` and confirm the worktree is clean.
