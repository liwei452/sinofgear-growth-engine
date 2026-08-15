# Four-Channel Manual Export Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Download one safe, deterministic ZIP containing the four human-approved social channel packages without making any platform request.

**Architecture:** A focused backend exporter validates current organization-owned packages and builds a bounded deterministic ZIP in memory. A single API endpoint returns the attachment and hash headers; the Promotion page enables one download action only when the four current packages are approved.

**Tech Stack:** Django REST Framework, Python `zipfile`/`hashlib`/`json`, Vue 3, TanStack Query, Vitest, Playwright.

## Global Constraints

- Export exactly LinkedIn, Facebook, Instagram, and TikTok current approved packages.
- Never include secrets, internal storage paths, personal data, or unapproved drafts.
- The same approved versions must produce the same content hash and ZIP bytes.
- The download is local-only and must not call any social platform or other external writer.
- Keep the archive under 2 MiB and all archive paths fixed and safe.

---

### Task 1: Deterministic backend archive

**Files:**
- Create: `backend/apps/growth/manual_export.py`
- Modify: `backend/apps/growth/serializers.py`
- Modify: `backend/apps/growth/views.py`
- Modify: `backend/apps/growth/urls.py`
- Test: `backend/tests/test_growth_workspace_api.py`

**Interfaces:**
- Consumes: four `ChannelPackage` IDs and the authenticated organization.
- Produces: `build_four_channel_export(*, organization, package_ids) -> FourChannelExport` with `filename`, `content_hash`, and `content` bytes.

- [ ] **Step 1: Write failing API tests**

Add tests that create four approved packages, request `/api/v1/growth/channel-packages/manual-export-all`, inspect the ZIP, and assert deterministic bytes/hash, safe file names, evidence and sanitized asset references. Add rejection assertions for unapproved, missing, foreign, and superseded content packages.

- [ ] **Step 2: Run the focused tests and verify RED**

Run `pytest backend/tests/test_growth_workspace_api.py -k manual_export_all -q`; expect 404 before the endpoint exists.

- [ ] **Step 3: Implement the minimal exporter and endpoint**

Create canonical JSON with sorted keys and bounded strings, fixed ZIP timestamps, `ZIP_STORED`, safe fixed paths, a two-pass manifest hash, and a 2 MiB hard limit. Return `application/zip` with `Content-Disposition`, `ETag`, and `X-Content-SHA256`. Map invalid selection or old-version errors to a recoverable 409 without disclosing foreign objects.

- [ ] **Step 4: Run focused backend tests and schema checks**

Run the new tests plus existing single-package export and publish-batch tests. Regenerate and check the OpenAPI artifact after documenting the binary response.

### Task 2: One visible download action

**Files:**
- Modify: `frontend/src/modules/growth/api.ts`
- Modify: `frontend/src/modules/growth/PromotionPage.vue`
- Modify: `frontend/src/modules/growth/growth-pages.css`
- Test: `frontend/src/modules/growth/GrowthWorkspacePages.test.ts`

**Interfaces:**
- Consumes: `downloadFourChannelPackage(packageIds: string[])` and existing `allPackagesApproved` state.
- Produces: one browser download and a truthful local-only status message.

- [ ] **Step 1: Write failing UI tests**

Assert that the combined download is disabled with a clear missing-review explanation, becomes available for four approved packages, makes one backend request, downloads the server filename, and does not call the publish-batch endpoint.

- [ ] **Step 2: Run the focused Vitest file and verify RED**

Run `vitest --run src/modules/growth/GrowthWorkspacePages.test.ts`; expect the combined download control to be absent.

- [ ] **Step 3: Implement binary download and UI state**

Use the existing CSRF-aware request boundary to POST package IDs and read the ZIP blob plus safe attachment filename. Add a single secondary action beside the four-channel review/readiness area; list missing or awaiting-review channels and state that downloading does not publish.

- [ ] **Step 4: Run focused frontend tests and typecheck**

Run the workspace page test and `vue-tsc --noEmit`; both must exit 0.

### Task 3: Regression and browser acceptance

**Files:**
- Modify: `frontend/e2e/growth-workspace.spec.ts`
- Modify: `docs/acceptance/2026-08-14-growth-workspace.md`

**Interfaces:**
- Consumes: the completed API and Promotion page flow.
- Produces: browser evidence that refresh retains eligibility and download remains local-only.

- [ ] **Step 1: Extend the E2E flow**

After four-channel approval, refresh the page, start the combined download, inspect the suggested ZIP filename, and assert no publish request occurred during download.

- [ ] **Step 2: Run focused E2E**

Run the growth workspace browser suite against `http://127.0.0.1:3001`; expect all scenarios to pass.

- [ ] **Step 3: Run one final regression gate**

Run the full backend tests, full frontend tests, production build, E2E suite, `git diff --check`, and the local preview health check once production code is stable.

- [ ] **Step 4: Commit the verified slice**

Commit only the growth-engine files with message `feat: download four-channel manual publishing bundle` and confirm a clean worktree.
