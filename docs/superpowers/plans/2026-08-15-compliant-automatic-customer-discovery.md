# Compliant Automatic Customer Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a locally runnable customer-discovery loop that periodically reads official TED procurement notices, creates evidence-backed customer opportunities, and exposes one simple control on the existing opportunities page.

**Architecture:** Add organization-scoped discovery profile/run records to the existing growth module, plus a narrow source-adapter interface with a TED implementation. A service owns locking, ingestion, deduplication and scoring; REST endpoints expose status, run-now and schedule state; Celery beat invokes a bounded due-run task. The Vue page shows only user-facing discovery status and actions.

**Tech Stack:** Django 5.2, Django REST Framework 3.16, Python standard-library HTTP client, Celery 5.5, PostgreSQL/SQLite tests, Vue 3.5, TypeScript 5.8, TanStack Vue Query, Vitest, Playwright.

## Global Constraints

- Work only in `C:\Users\Administrator\Documents\网站\sinofgear-growth-engine`; never enter or modify sibling `app`.
- Do not scrape LinkedIn login data, bypass access controls, collect personal email addresses, or send outbound messages.
- Real and fake results must be visibly distinct; TED records use `is_demo=false` and fixtures use `is_demo=true` only when presented as fixture data.
- The only live source in this slice is the official anonymous TED Search API at the fixed HTTPS host `api.ted.europa.eu`.
- A run retrieves at most 20 notices and has a 15-second network timeout and bounded response body.
- Preserve the existing simple factory-owner information architecture; do not expose adapter, cursor, API, prompt, quota or campaign internals.
- Every created opportunity retains an original HTTPS evidence URL, source label, collection method, content hash, scoring breakdown, rule version and uncertainty notes.
- A discovered target account, contact, intent signal and inbound lead remain separate object types.

---

### Task 1: Discovery domain and TED adapter contract

**Files:**
- Modify: `backend/apps/growth/models.py`
- Create: `backend/apps/growth/migrations/0004_discoveryprofile_discoveryrun.py`
- Create: `backend/integrations/sources/__init__.py`
- Create: `backend/integrations/sources/base.py`
- Create: `backend/integrations/sources/ted.py`
- Test: `backend/integrations/sources/tests/test_ted_source.py`
- Test: `backend/apps/growth/tests/test_discovery_models.py`

**Interfaces:**
- Consumes: fixed TED endpoint, CPV codes and a `DiscoveryQuery` value object.
- Produces: `SourceItem`, `SourceBatch`, `SourceAdapterError`, `TedSource.fetch(query)`, `DiscoveryProfile`, and immutable `DiscoveryRun`.

- [ ] **Step 1: Write failing model and adapter tests**

```python
def test_ted_source_normalizes_official_notice(ted_transport):
    batch = TedSource(transport=ted_transport).fetch(
        DiscoveryQuery(cpv_codes=("42141300",), published_from=date(2026, 8, 1), limit=10)
    )
    assert batch.items[0].external_id == "534032-2026"
    assert batch.items[0].buyer_name == "Example Contracting Authority"
    assert batch.items[0].source_url.startswith("https://ted.europa.eu/")
    assert batch.capability_snapshot["capture_method"] == "OFFICIAL_PUBLIC_API"

def test_discovery_run_history_cannot_be_deleted(organization):
    run = DiscoveryRun.objects.create(organization=organization, source_code="TED", status="RUNNING")
    with pytest.raises(ValueError, match="cannot be deleted"):
        run.delete()
```

- [ ] **Step 2: Run focused tests and verify the missing symbols fail**

Run: `cd backend && pytest integrations/sources/tests/test_ted_source.py apps/growth/tests/test_discovery_models.py -q`

Expected: FAIL because the adapter values and discovery models do not exist.

- [ ] **Step 3: Implement focused models and adapter values**

```python
@dataclass(frozen=True)
class DiscoveryQuery:
    cpv_codes: tuple[str, ...]
    published_from: date
    limit: int = 20

@dataclass(frozen=True)
class SourceItem:
    external_id: str
    buyer_name: str
    buyer_country: str
    title: str
    published_at: datetime
    deadline_at: datetime | None
    source_url: str
    cpv_codes: tuple[str, ...]

@dataclass(frozen=True)
class SourceBatch:
    items: tuple[SourceItem, ...]
    capability_snapshot: dict[str, object]
```

`TedSource` must build one fixed POST request to `/v3/notices/search`, request only the required fields, prefer English multilingual values, fall back deterministically, reject non-HTTPS TED links, reject malformed records, cap the decoded body, and map timeout/429/5xx/schema failures to safe `SourceAdapterError.code` values.

`DiscoveryProfile` is unique per organization and stores `enabled`, `source_code`, `cpv_codes`, `result_limit`, `next_run_at`, `last_succeeded_at`, `consecutive_failures`, and `last_error_code`. `DiscoveryRun` stores trigger/status/query/capability/count/timestamp snapshots and overrides `delete()`.

- [ ] **Step 4: Generate the migration and rerun tests**

Run: `cd backend && python manage.py makemigrations growth && pytest integrations/sources/tests/test_ted_source.py apps/growth/tests/test_discovery_models.py -q`

Expected: PASS.

- [ ] **Step 5: Commit the adapter boundary**

```bash
git add backend/apps/growth backend/integrations/sources
git commit -m "feat: add official discovery source boundary"
```

### Task 2: Idempotent discovery ingestion and scheduled runs

**Files:**
- Create: `backend/apps/growth/discovery.py`
- Create: `backend/apps/growth/tasks.py`
- Modify: `backend/config/settings.py`
- Test: `backend/apps/growth/tests/test_discovery_service.py`
- Test: `backend/apps/growth/tests/test_discovery_tasks.py`

**Interfaces:**
- Consumes: `DiscoveryProfile`, `TedSource.fetch(DiscoveryQuery) -> SourceBatch`.
- Produces: `run_discovery(profile_id, trigger, source=None) -> DiscoveryRun`, `run_due_discovery_profiles(limit=25) -> dict`, and Celery task `scan_due_discovery_profiles`.

- [ ] **Step 1: Write failing ingestion tests**

```python
def test_official_notice_creates_account_and_intent_signal(profile, source_batch):
    run = run_discovery(profile.id, trigger="MANUAL", source=FakeSource(source_batch))
    signal = IntentSignal.objects.get(organization=profile.organization, content_hash=source_batch.items[0].content_hash)
    assert signal.account.name == source_batch.items[0].buyer_name
    assert signal.collection_method == "OFFICIAL_PUBLIC_API"
    assert signal.is_demo is False
    assert run.created_signal_count == 1

def test_repeat_notice_is_idempotent(profile, source_batch):
    run_discovery(profile.id, trigger="MANUAL", source=FakeSource(source_batch))
    second = run_discovery(profile.id, trigger="MANUAL", source=FakeSource(source_batch))
    assert IntentSignal.objects.filter(organization=profile.organization).count() == 1
    assert second.duplicate_count == 1
```

Also cover concurrent profile locking, missing buyer/link skips, timeout failure recording, backoff, result limits, and only-due enabled profiles.

- [ ] **Step 2: Run focused tests and verify failure**

Run: `cd backend && pytest apps/growth/tests/test_discovery_service.py apps/growth/tests/test_discovery_tasks.py -q`

Expected: FAIL because orchestration functions do not exist.

- [ ] **Step 3: Implement locking, scoring and ingestion**

```python
TED_SCORE = {
    "icp_fit": 20,
    "intent_strength": 24,
    "recency": 18,
    "role_relevance": 5,
    "evidence_coverage": 18,
    "risk_penalty": 5,
}
```

Use `transaction.atomic()` and `select_for_update(nowait=True)` on the profile. Create the run before the external read, then ingest a bounded batch in a second transaction. Derive the content hash from source code, external ID, canonical URL and normalized title. Use `source_code + external_id` in the evidence text and hash so repeated records remain idempotent. Set `scoring_rule_version="ted-procurement-v1"` and uncertainty notes explaining that the buyer is a public procurement entity and no individual contact has been verified.

Success schedules `next_run_at` 24 hours later and clears failures. Failure stores only a safe code and schedules exponential backoff capped at 24 hours. `run_due_discovery_profiles` orders by due time and never executes disabled profiles.

- [ ] **Step 4: Configure hourly beat dispatch and pass tests**

Add `CELERY_BEAT_SCHEDULE["growth-discovery-hourly"]` calling `apps.growth.tasks.scan_due_discovery_profiles` every 3600 seconds.

Run: `cd backend && pytest apps/growth/tests/test_discovery_service.py apps/growth/tests/test_discovery_tasks.py -q`

Expected: PASS.

- [ ] **Step 5: Commit orchestration**

```bash
git add backend/apps/growth backend/config/settings.py
git commit -m "feat: schedule evidence backed customer discovery"
```

### Task 3: Discovery REST contract

**Files:**
- Modify: `backend/apps/growth/serializers.py`
- Modify: `backend/apps/growth/views.py`
- Modify: `backend/apps/growth/urls.py`
- Modify: `backend/tests/test_openapi_contract.py`
- Test: `backend/apps/growth/tests/test_discovery_api.py`

**Interfaces:**
- Consumes: `run_discovery`, organization permissions and discovery models.
- Produces: workspace `discovery` summary, `POST /api/v1/growth/discovery/run`, and `PATCH /api/v1/growth/discovery/profile`.

- [ ] **Step 1: Write failing API tests**

```python
def test_manager_can_run_discovery_and_reader_cannot(manager_client, reader_client, fake_source):
    response = manager_client.post("/api/v1/growth/discovery/run")
    assert response.status_code == 200
    assert response.json()["status"] == "SUCCEEDED"
    assert reader_client.post("/api/v1/growth/discovery/run").status_code == 403

def test_workspace_exposes_owner_friendly_summary(client):
    summary = client.get("/api/v1/growth/workspace").json()["discovery"]
    assert set(summary) >= {"enabled", "source_label", "schedule_label", "last_run"}
    assert "cursor" not in summary
```

- [ ] **Step 2: Run API tests and verify failure**

Run: `cd backend && pytest apps/growth/tests/test_discovery_api.py tests/test_openapi_contract.py -q`

Expected: FAIL with missing routes and workspace field.

- [ ] **Step 3: Implement serializers and views**

The summary serializer returns only:

```json
{
  "enabled": true,
  "source_label": "欧盟官方采购数据",
  "schedule_label": "每天自动查找",
  "product_scope_label": "齿轮、传动与驱动部件",
  "next_run_at": "2026-08-16T02:00:00Z",
  "last_run": {
    "status": "SUCCEEDED",
    "finished_at": "2026-08-15T02:00:00Z",
    "found_count": 6,
    "new_company_count": 3,
    "new_signal_count": 4,
    "message": "发现 4 条新采购信号，等待你审核。"
  }
}
```

The run endpoint performs the bounded read synchronously so local preview works without a worker, while the same service remains Celery-safe. Map overlap to 409 and safe source failures to 503 with a user recovery action. The profile endpoint accepts only `{ "enabled": boolean }`.

- [ ] **Step 4: Run API and schema tests**

Run: `cd backend && pytest apps/growth/tests/test_discovery_api.py tests/test_openapi_contract.py -q && python manage.py spectacular --file NUL --validate`

Expected: PASS.

- [ ] **Step 5: Commit the API**

```bash
git add backend/apps/growth backend/tests/test_openapi_contract.py
git commit -m "feat: expose automatic discovery controls"
```

### Task 4: Simple opportunities-page controls

**Files:**
- Modify: `frontend/src/modules/growth/api.ts`
- Create: `frontend/src/modules/growth/AutomaticDiscoveryCard.vue`
- Create: `frontend/src/modules/growth/AutomaticDiscoveryCard.test.ts`
- Modify: `frontend/src/modules/growth/OpportunitiesPage.vue`
- Modify: `frontend/src/modules/growth/growth-pages.css`
- Modify: `frontend/src/modules/growth/GrowthWorkspacePages.test.ts`

**Interfaces:**
- Consumes: workspace discovery summary and run/profile endpoints.
- Produces: one owner-facing card with run-now, daily toggle, status and result counts.

- [ ] **Step 1: Write failing component tests**

```typescript
it("runs official customer discovery and refreshes opportunities", async () => {
  renderDiscovery({ enabled: true, source_label: "欧盟官方采购数据" })
  await userEvent.click(screen.getByRole("button", { name: "立即查找" }))
  expect(fetch).toHaveBeenCalledWith("/api/v1/growth/discovery/run", expect.objectContaining({ method: "POST" }))
  expect(await screen.findByText("发现 2 条新采购信号，等待你审核。")).toBeInTheDocument()
})

it("explains that discovery does not contact customers", () => {
  renderDiscovery()
  expect(screen.getByText(/不会自动联系客户/)).toBeInTheDocument()
})
```

- [ ] **Step 2: Run component tests and verify failure**

Run: `cd frontend && npm test -- --run src/modules/growth/AutomaticDiscoveryCard.test.ts src/modules/growth/GrowthWorkspacePages.test.ts`

Expected: FAIL because the card and client functions do not exist.

- [ ] **Step 3: Implement the card and integrate it**

Place the card above the existing manual-import bar. Use a compact blue-accent status dot, `每天自动查找` switch, primary `立即查找` button, last-run sentence and source badge. Keep the manual import as a secondary fallback. Disable actions while a mutation is pending, retain a retryable error message, and invalidate `growthQueryKeys.workspace` after success.

- [ ] **Step 4: Run frontend checks**

Run: `cd frontend && npm test -- --run src/modules/growth/AutomaticDiscoveryCard.test.ts src/modules/growth/GrowthWorkspacePages.test.ts && npm run typecheck && npm run lint && npm run build`

Expected: PASS.

- [ ] **Step 5: Commit the UI**

```bash
git add frontend/src/modules/growth
git commit -m "feat: add automatic customer discovery card"
```

### Task 5: End-to-end acceptance and documentation

**Files:**
- Modify: `frontend/e2e/growth-opportunity-actions.spec.ts`
- Modify: `docs/superpowers/plans/2026-08-14-ai-growth-loop-development-acceptance-checklist.md`
- Modify: `docs/acceptance/2026-08-14-growth-workspace.md`
- Modify: `.env.example`

**Interfaces:**
- Consumes: complete backend and frontend discovery flow.
- Produces: repeatable local acceptance evidence and operator configuration notes.

- [ ] **Step 1: Add E2E coverage with a fixture adapter**

The E2E test must log in, open `/opportunities`, assert the official-source label, click `立即查找`, see a newly created non-Demo opportunity, open its evidence URL, run discovery again, and assert the opportunity count does not increase.

- [ ] **Step 2: Add safe configuration documentation**

Document `TED_DISCOVERY_ENABLED=true`, `TED_DISCOVERY_TIMEOUT_SECONDS=15`, `TED_DISCOVERY_MAX_RESPONSE_BYTES=2000000`, and `TED_DISCOVERY_RESULT_LIMIT=20`. Tests override the source factory and never call the network.

- [ ] **Step 3: Run full verification**

Run: `cd backend && pytest -q && ruff check . && python manage.py check && python manage.py makemigrations --check`

Run: `cd frontend && npm test -- --run && npm run typecheck && npm run lint && npm run build && npx playwright test frontend/e2e/growth-opportunity-actions.spec.ts`

Expected: all checks pass.

- [ ] **Step 4: Run one explicit read-only TED smoke check**

With the local server running and authenticated, click `立即查找` once and verify every created non-Demo signal has `source_label="TED 欧盟官方采购公告"`, an HTTPS `ted.europa.eu` evidence link, CPV evidence and `collection_method="OFFICIAL_PUBLIC_API"`. This action reads public data only and never sends or publishes anything.

- [ ] **Step 5: Update acceptance evidence and commit**

```bash
git add frontend/e2e docs .env.example
git commit -m "test: verify automatic customer discovery"
```

## Self-review

- Spec coverage: source choice, CPV precision, user UI, domain separation, audit records, scoring, scheduling, concurrency, timeout, bounded reads, failure safety, real/Demo labeling and no-outreach constraints each map to Tasks 1–5.
- Placeholder scan: no TBD/TODO/unspecified implementation steps remain.
- Type consistency: `DiscoveryQuery`, `SourceItem`, `SourceBatch`, `TedSource.fetch`, `run_discovery`, discovery summary fields and REST routes are used consistently across tasks.
