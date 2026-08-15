# Asset AI Understanding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a truthful, retryable asset-to-candidate-facts-to-human-verification loop in the existing material library.

**Architecture:** Reuse immutable `MaterialAsset`, protected `Job`/`JobAttempt`, and audited `AIRun`; add one organization-scoped evidence-fact model and a bounded PDF extractor. A deterministic Fake Provider only maps literal labeled lines to candidates, and every candidate requires review before it is available as verified product knowledge.

**Tech Stack:** Django 5.2, DRF, PostgreSQL/SQLite tests, pypdf 6.14.x, Vue 3, TanStack Query, Vitest, Playwright.

## Global Constraints

- Only modify `C:\Users\Administrator\Documents\网站\sinofgear-growth-engine`.
- No independent-site changes, real multimodal/OCR API, scraping, external sending, OAuth, paid API, or production deployment.
- Provider copy must always say `Fake Provider · 本地演示`; image/scanned-PDF results with no text must not invent facts.
- Parsing limits: 20 MiB, 30 PDF pages, 10 MiB decompressed page stream, 100,000 extracted characters.
- Price, lead time, accuracy, certification, material, and capacity are high risk; all facts require human review.

---

### Task 1: Protected data model and dependency boundary

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/apps/jobs/models.py`
- Modify: `backend/apps/assets/models.py`
- Create: `backend/apps/assets/migrations/0002_productevidencefact.py`
- Test: `backend/apps/assets/tests/test_asset_understanding_models.py`

**Interfaces:**
- Produces: `Job.Type.ASSET_UNDERSTAND` and `ProductEvidenceFact` with organization, evidence, review, provider, and audit fields.

- [ ] **Step 1: Write failing model tests** proving cross-organization links fail validation, confidence/bbox are bounded, and a candidate defaults to SUGGESTED/demo.
- [ ] **Step 2: Run** `pytest apps/assets/tests/test_asset_understanding_models.py -q` and confirm failure because the model/type is missing.
- [ ] **Step 3: Add** `pypdf>=6.14,<6.15`, the job type, model, constraints/indexes, and migration with the exact fields from the design.
- [ ] **Step 4: Run the model tests and migration check**; expect PASS and no pending migration.
- [ ] **Step 5: Commit** the model boundary.

### Task 2: Bounded extraction, Fake Provider, job execution, and review

**Files:**
- Create: `backend/apps/assets/understanding.py`
- Modify: `backend/apps/ai/services.py`
- Test: `backend/apps/assets/tests/test_asset_understanding_service.py`

**Interfaces:**
- Consumes: `MaterialAsset`, `ProductEvidenceFact`, `JobService`, `PromptVersionService`, `AIRun`, object storage.
- Produces: `start_understanding(asset, product, actor)`, `retry_understanding(job, actor)`, and `review_fact(fact, decision, actor, note)`.

- [ ] **Step 1: Write failing service tests** using a hand-built two-page PDF with labeled facts. Assert exact source lines/pages, high-risk classification, Fake labeling, successful job/AIRun, no facts for image bytes, partial-page warning retention, and review persistence.
- [ ] **Step 2: Run** `pytest apps/assets/tests/test_asset_understanding_service.py -q`; confirm the wished-for service API is missing.
- [ ] **Step 3: Implement bounded extraction** with explicit MIME/size/page/stream/text limits; treat extracted content only as data and flag prompt-injection phrases without executing them.
- [ ] **Step 4: Implement deterministic labeled-line mapping** for Product, Specification, Process, Application, Standard, Advantage, Accuracy, Certification, Material, Capacity, Lead time, and Price. Values and excerpts must be exact substrings of extracted text.
- [ ] **Step 5: Implement job/AIRun execution** using a published `ASSET_UNDERSTAND` Fake prompt record, preserving partial results and normalized failures; retries create a new attempt without upload.
- [ ] **Step 6: Implement transactional review** that records APPROVE→VERIFIED or REJECT→REJECTED and never mutates Product structured fields.
- [ ] **Step 7: Run targeted tests** and expect PASS.
- [ ] **Step 8: Commit** service behavior.

### Task 3: Organization-scoped API contract

**Files:**
- Modify: `backend/apps/assets/serializers.py`
- Modify: `backend/apps/assets/views.py`
- Modify: `backend/apps/assets/urls.py`
- Modify: `backend/tests/test_openapi_contract.py`
- Test: `backend/apps/assets/tests/test_asset_understanding_api.py`
- Test: `backend/apps/assets/tests/test_asset_schema.py`

**Interfaces:**
- Produces: POST/GET understanding, POST retry, and POST fact review endpoints from the design.

- [ ] **Step 1: Write failing API tests** for happy path, idempotent refresh, retry, permission, unsupported video, oversized parse input, invalid/cross-org product, and cross-org fact review.
- [ ] **Step 2: Run the API tests** and confirm 404/missing contract failures.
- [ ] **Step 3: Add serializers and views** that use existing asset permissions and always filter asset/product/job/fact by `request.organization`.
- [ ] **Step 4: Add OpenAPI declarations and route contract tests** including explicit 400/403/404/409 shapes.
- [ ] **Step 5: Run asset API/schema tests** and expect PASS.
- [ ] **Step 6: Regenerate frontend schema** with `pnpm api:generate` only after the backend schema passes.
- [ ] **Step 7: Commit** API slice.

### Task 4: Visible material-library workflow

**Files:**
- Modify: `frontend/src/modules/assets/api.ts`
- Modify: `frontend/src/modules/assets/api.test.ts`
- Create: `frontend/src/modules/assets/AssetUnderstandingPanel.vue`
- Create: `frontend/src/modules/assets/AssetUnderstandingPanel.test.ts`
- Modify: `frontend/src/modules/assets/AssetLibraryPage.vue`
- Modify: `frontend/src/modules/assets/AssetLibraryPage.test.ts`

**Interfaces:**
- Consumes: generated understanding endpoints and existing products/assets queries.
- Produces: product selection, prepare/retry actions, status/Fake warnings, evidence fact cards, and approve/reject actions.

- [ ] **Step 1: Write failing API and component tests** asserting the exact user flow and copy: no product→disabled, Fake badge visible, PDF evidence displayed, high-risk warning visible, image no-fabrication message, approve refreshes to verified.
- [ ] **Step 2: Run targeted Vitest** and confirm failures because methods/components are missing.
- [ ] **Step 3: Implement typed API functions** with organization-keyed query invalidation.
- [ ] **Step 4: Implement the focused panel** with progressive disclosure; keep the asset page simple and reuse existing product selector.
- [ ] **Step 5: Run targeted Vitest** and expect PASS.
- [ ] **Step 6: Commit** frontend workflow.

### Task 5: Browser acceptance and release verification

**Files:**
- Modify: `frontend/e2e/growth-loop.spec.ts` (or the existing material-library E2E spec selected by repository convention)
- Modify: `docs/superpowers/plans/2026-08-14-ai-growth-loop-development-acceptance-checklist.md`

**Interfaces:**
- Produces: repeatable browser evidence and acceptance record.

- [ ] **Step 1: Add a failing browser scenario** that uploads a labeled PDF fixture, selects a product, starts understanding, verifies Fake/evidence/high-risk copy, approves a fact, reloads, and sees VERIFIED; add image no-fabrication assertion.
- [ ] **Step 2: Run only that E2E** and confirm it fails before final UI wiring/seed adjustments.
- [ ] **Step 3: Make the smallest fixture/selector changes** needed for the real browser flow.
- [ ] **Step 4: Run targeted backend and frontend tests**, then once run full backend, full frontend, API generation check, typecheck, lint, build, and full E2E.
- [ ] **Step 5: Use `superpowers:verification-before-completion`**, inspect `git diff`, update checklist with exact results, and commit the acceptance slice.
