# DeepSeek PDF Understanding Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Convert bounded, machine-readable PDF text into evidence-backed DeepSeek candidate product facts that remain subject to human approval.

**Architecture:** Keep local `pypdf` extraction as the document boundary, then pass page-numbered text through the existing product AI provider with a strict fact schema. Validate every returned excerpt against its source page before persisting suggested facts; retain Fake mode and no-OCR behavior as explicit alternatives.

**Tech Stack:** Django, DRF, pypdf, existing DeepSeek JSON provider, Vue 3, Vitest, pytest.

## Global Constraints

- Never send the PDF binary to DeepSeek; send at most 100,000 extracted characters.
- Keep 20 MiB, 30-page and 10 MiB decompressed-page limits.
- Every persisted fact requires a valid source page and an excerpt present on that page.
- High-risk fields remain `SUGGESTED` until human approval.
- Images and scanned PDFs without text return an OCR-required partial result.
- Provider credentials remain server-only and never enter responses, logs or persistence.

---

### Task 1: Strict DeepSeek fact extraction adapter

**Files:**
- Create: `backend/apps/assets/ai_extraction.py`
- Test: `backend/apps/assets/tests/test_asset_ai_extraction.py`

**Interfaces:**
- Consumes: `tuple[ExtractedPage, ...]`, `provider_registry.get("deepseek")`.
- Produces: `extract_candidate_facts(pages, *, provider_code) -> ExtractionOutcome`.

- [ ] Write failing tests for valid facts, unknown fields, invalid pages, non-source excerpts, prompt-injection text and partial invalid output.
- [ ] Run `pytest apps/assets/tests/test_asset_ai_extraction.py -q` and verify failure because the adapter is absent.
- [ ] Implement an allowlisted JSON schema and post-validation that returns only evidence-backed rows plus bounded warnings.
- [ ] Run the focused tests and verify they pass.

### Task 2: Provider-aware understanding jobs

**Files:**
- Modify: `backend/apps/assets/understanding.py`
- Modify: `backend/apps/assets/serializers.py`
- Test: `backend/apps/assets/tests/test_asset_understanding_service.py`
- Test: `backend/apps/assets/tests/test_asset_understanding_api.py`

**Interfaces:**
- Consumes: `extract_candidate_facts` from Task 1 and `product_ai_status()`.
- Produces: provider-versioned `ASSET_UNDERSTAND` jobs and truthful `provider_label` results.

- [ ] Write failing tests proving DeepSeek mode uses the adapter, persists non-demo suggested facts, keeps high-risk review gates, and does not reuse a Fake job.
- [ ] Run the focused service/API tests and verify the new expectations fail.
- [ ] Select Fake or DeepSeek explicitly, include provider/model in the idempotency key and task snapshot, and persist audited run metadata without secrets.
- [ ] Preserve OCR-required partial results for images and textless PDFs.
- [ ] Run the focused tests and verify they pass.

### Task 3: Truthful asset-page experience

**Files:**
- Modify: `frontend/src/modules/assets/AssetUnderstandingPanel.vue`
- Modify: `frontend/src/modules/assets/AssetUnderstandingPanel.test.ts`
- Modify: `frontend/src/modules/assets/api.ts`

**Interfaces:**
- Consumes: provider-aware understanding API response.
- Produces: visible real/Fake mode, evidence, risk and OCR-required states.

- [ ] Write failing component tests for DeepSeek labeling, Fake labeling, OCR-required empty state and unchanged manual approval.
- [ ] Run the focused Vitest file and verify failure.
- [ ] Render provider-specific explanatory copy without exposing model secrets or implying approval.
- [ ] Run Vitest, Vue type checking and focused ESLint.

### Task 4: End-to-end verification and handoff

**Files:**
- Modify: `frontend/e2e/phase-a-active-growth.spec.ts`
- Modify: `docs/superpowers/plans/2026-08-14-ai-growth-loop-development-acceptance-checklist.md`

**Interfaces:**
- Consumes: completed backend and frontend behavior.
- Produces: browser evidence and acceptance record.

- [ ] Add a no-network E2E scenario with an explicit deterministic DeepSeek transport proving PDF upload, candidate evidence, approval and refresh persistence.
- [ ] Run focused backend tests and asset frontend tests.
- [ ] Run one final backend suite, frontend suite, type check, lint, schema check, build and E2E suite.
- [ ] Confirm `git diff --check`, clean secret scan and healthy previews.
- [ ] Commit the complete implementation as an independent slice.
