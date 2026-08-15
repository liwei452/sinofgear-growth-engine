# Manual Opportunity Import Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Allow an ordinary user to save a permitted public HTTPS lead source as an evidence-backed, non-Demo opportunity without fetching the source or contacting anyone.

**Architecture:** A focused growth service validates source locators, computes evidence hashes, applies a conservative deterministic score, and creates or reuses records atomically. A single REST endpoint exposes that operation. A small collapsible Vue form on the existing opportunities page submits the facts and refreshes/selects the saved opportunity.

**Tech Stack:** Django 5, Django REST Framework, SQLite/PostgreSQL-compatible ORM, Vue 3, TanStack Vue Query, TypeScript, Vitest, Testing Library, Playwright.

## Global Constraints

- Work only in `C:\Users\Administrator\Documents\网站\sinofgear-growth-engine`; do not enter or modify the sibling `app` repository.
- Do not fetch the submitted URL, resolve DNS, scrape LinkedIn, send messages, publish content, or use real OAuth/API credentials.
- Accept only user-provided public HTTPS source locators and non-sensitive company/evidence facts.
- Every imported signal is non-Demo, labeled as a permitted/user-provided source, and conservatively scored as “继续观察”.
- Duplicate evidence in one organization must be idempotent.
- Ordinary-user UI must not expose SourceRun, Prompt, Campaign, API, or connector internals.

---

### Task 1: Atomic manual evidence import service and API

**Files:**
- Create: `backend/apps/growth/manual_imports.py`
- Create: `backend/apps/growth/tests/test_manual_opportunity_import.py`
- Modify: `backend/apps/growth/serializers.py`
- Modify: `backend/apps/growth/views.py`
- Modify: `backend/apps/growth/urls.py`
- Modify: `backend/tests/test_openapi_contract.py`

**Interfaces:**
- Consumes: `organization`, validated `company_name`, `country`, `industry`, `source_label`, `source_url`, and `evidence_text`.
- Produces: `import_manual_opportunity(*, organization, data) -> tuple[TargetAccount, IntentSignal, bool]` and `POST /api/v1/growth/opportunity-imports/manual-url`.

- [ ] **Step 1: Write failing service and API tests**

Cover: a successful 201 response, exact score breakdown totaling 50, `MANUAL_URL`, SHA-256, non-Demo labels, organization isolation, duplicate 200 response, no duplicate signal, and rejection of HTTP, credentials, localhost, `.local`, private/reserved/loopback IP, blank evidence, and overlong values.

```python
response = api_client.post("/api/v1/growth/opportunity-imports/manual-url", {
    "company_name": "Buyer Systems GmbH",
    "country": "Germany",
    "industry": "Packaging machinery",
    "source_label": "Public company news",
    "source_url": "https://example.invalid/news/expansion",
    "evidence_text": "The company announced a new packaging line.",
}, format="json")
assert response.status_code == 201
assert response.data["signal"]["priority_label"] == "继续观察"
assert response.data["signal"]["score_breakdown"]["evidence_coverage"] == 10
```

- [ ] **Step 2: Run focused tests and verify red**

Run: `cd backend && .venv/Scripts/python.exe -m pytest apps/growth/tests/test_manual_opportunity_import.py tests/test_openapi_contract.py -q`

Expected: FAIL because the endpoint and service do not exist.

- [ ] **Step 3: Implement locator validation and atomic import**

`validate_manual_source_url(value)` parses with `urllib.parse.urlsplit`, requires scheme `https`, a hostname, no username/password, rejects `localhost`, `.local`, and any literal address for which `ipaddress.ip_address(host).is_global` is false, and returns the normalized URL without a fragment. It never performs DNS or HTTP I/O.

`import_manual_opportunity` normalizes whitespace, hashes `normalized_url + "\n" + evidence_text` with SHA-256, locks the organization row inside `transaction.atomic()`, returns an existing same-hash signal when present, reuses a case-insensitive exact-name account, or creates a non-Demo account. It creates a non-Demo signal with:

```python
score_breakdown = {
    "icp_fit": 15,
    "intent_strength": 15,
    "recency": 12,
    "role_relevance": 3,
    "evidence_coverage": 10,
    "risk_penalty": 5,
}
```

and `confidence=50`, `scoring_rule_version="manual-opportunity-v1"`, plus the two fixed uncertainty notes from the design.

- [ ] **Step 4: Implement serializer, view, route, and OpenAPI coverage**

Use a plain DRF serializer with exact maximum lengths matching model fields and `min_length=2` for names/labels, `min_length=10` for evidence. The view requires `CanManageCampaigns`, returns `{account, signal, created}` using existing serializers, with status 201 for new and 200 for duplicate.

- [ ] **Step 5: Run focused backend checks and verify green**

Run: `cd backend && .venv/Scripts/python.exe -m pytest apps/growth/tests/test_manual_opportunity_import.py apps/growth/tests/test_opportunity_evidence.py tests/test_openapi_contract.py -q`

Run: `cd backend && .venv/Scripts/python.exe -m ruff check apps/growth tests/test_openapi_contract.py`

Expected: all pass.

- [ ] **Step 6: Commit the backend slice**

```bash
git add backend/apps/growth backend/tests/test_openapi_contract.py
git commit -m "feat: import permitted opportunity evidence"
```

---

### Task 2: Minimal customer-facing import form

**Files:**
- Create: `frontend/src/modules/growth/ManualOpportunityImportForm.vue`
- Create: `frontend/src/modules/growth/ManualOpportunityImportForm.test.ts`
- Modify: `frontend/src/modules/growth/api.ts`
- Modify: `frontend/src/modules/growth/OpportunitiesPage.vue`
- Modify: `frontend/src/modules/growth/growth-pages.css`

**Interfaces:**
- Consumes: `importManualOpportunity(input: ManualOpportunityImportInput) -> ManualOpportunityImportResult`.
- Produces: `imported(accountId: string)` and `cancelled()` component events.

- [ ] **Step 1: Write failing component and API behavior tests**

Tests open the form, verify the safety sentence, submit the exact six fields, keep values after an API failure, show field validation, and emit the returned account ID after success. The opportunities page test verifies that a successful import invalidates the workspace query, selects the returned account, and removes the page-wide Demo badge.

- [ ] **Step 2: Run focused frontend tests and verify red**

Run: `cd frontend && node node_modules/vitest/vitest.mjs --run src/modules/growth/ManualOpportunityImportForm.test.ts src/modules/growth/GrowthWorkspacePages.test.ts --maxWorkers=1 --minWorkers=1 --no-file-parallelism`

Expected: FAIL because the component and API function do not exist.

- [ ] **Step 3: Implement typed API client**

Add `ManualOpportunityImportInput` with the six string fields and `ManualOpportunityImportResult` with typed `account`, `signal`, and `created`. POST to `/api/v1/growth/opportunity-imports/manual-url`; do not add external requests.

- [ ] **Step 4: Implement accessible collapsible form**

Use native labels and inputs. Required fields are company, country, source label, HTTPS URL, and evidence; industry remains optional. Buttons are “保存为待核实机会” and “取消”. While pending, disable both actions and show “正在保存…”. Display the API error without clearing inputs.

- [ ] **Step 5: Integrate with the opportunity queue**

Add the secondary “导入公开线索” button near the queue heading. On `imported`, invalidate `growthQueryKeys.workspace`, set `selectedAccountId`, close the form, and show a short success status. Replace the page-wide `Demo / Fake` badge with “人工审核后跟进”; preserve per-account truth labels.

- [ ] **Step 6: Run focused frontend quality gates and verify green**

Run the focused Vitest command from Step 2, then Vue TypeScript and ESLint for the changed frontend tree.

Expected: all pass with no accessibility query failures.

- [ ] **Step 7: Commit the frontend slice**

```bash
git add frontend/src/modules/growth
git commit -m "feat: add public lead import flow"
```

---

### Task 3: Browser persistence and acceptance verification

**Files:**
- Modify: `frontend/e2e/zz-growth-workspace-persistence.spec.ts`
- Modify: `docs/acceptance/2026-08-14-growth-workspace.md`

**Interfaces:**
- Consumes: the running UI and manual import endpoint from Tasks 1–2.
- Produces: a browser-level proof that an imported permitted source persists and remains evidence-limited.

- [ ] **Step 1: Extend the isolated browser journey**

Use a unique company name and `https://example.invalid/manual-import/evidence`. Submit the form, assert the non-Demo label, `继续观察 · 50`, manual collection method, `manual-opportunity-v1`, uncertainty notes, safe source link, and persistence after reload. Submit the same evidence again through the API and assert only one matching signal remains.

- [ ] **Step 2: Run the browser journey**

Run: `cd frontend && node e2e/launcher.mjs zz-growth-workspace-persistence.spec.ts`

Expected: one complete isolated test passes; no network request targets `example.invalid`.

- [ ] **Step 3: Run full quality gates**

Backend: full pytest, Ruff, Django check, and migration drift check. Frontend: full Vitest, TypeScript, ESLint, and Vite build.

Expected: zero failures and no pending migration.

- [ ] **Step 4: Update acceptance evidence and local preview**

Document the manual-import safety boundary and fresh test counts. Restart only the local preview if necessary, then verify `/api/v1/health` and `/opportunities` return 200. Do not configure real data sources or publish anything.

- [ ] **Step 5: Commit the acceptance slice**

```bash
git add frontend/e2e/zz-growth-workspace-persistence.spec.ts docs/acceptance/2026-08-14-growth-workspace.md
git commit -m "test: verify permitted opportunity import"
```
