# One-Click Multichannel Publishing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a locally runnable one-click publishing MVP that submits every eligible approved LinkedIn, Facebook, Instagram, and TikTok package as one idempotent batch, isolates channel failures, retries only failures, and labels all local results as Demo / Fake.

**Architecture:** Add immutable growth publishing batch and channel-item records around the current `ChannelPackage` objects. A focused growth publishing service owns eligibility, organization isolation, idempotency, Fake Connector execution, partial-success aggregation, and retry; API views expose only batch-level actions. The promotion page calls one batch endpoint and presents channel results in ordinary language, while manual package download remains a secondary fallback. Real OAuth connectors remain disabled until separately authorized and will later replace the fake execution adapter without changing the UI or batch contract.

**Tech Stack:** Django 5, Django REST Framework, SQLite/PostgreSQL-compatible ORM constraints, existing platform account and mock connector boundaries, Vue 3, TanStack Vue Query, TypeScript, Vitest, Playwright.

## Global Constraints

- Work only in `C:\Users\Administrator\Documents\网站\sinofgear-growth-engine`; never enter, modify, build, test, or integrate `..\app`.
- Do not request, store, or use real OAuth credentials, API keys, passwords, cookies, verification codes, or browser sessions.
- Do not call real social publishing APIs; every local success must be labeled `Demo / Fake` and use an invalid/non-routable external URL.
- Only human-approved `ChannelPackage` rows may enter a batch.
- LinkedIn Company Page, Facebook Page, Instagram Business, and TikTok are equal first-class channels.
- One channel failure must not roll back another channel success.
- The same organization and `Idempotency-Key` must never create more than one batch or duplicate channel result.
- The factory-owner UI must not expose `Connector`, `PublishTask`, OAuth scopes, prompts, API settings, or campaign internals.
- Manual JSON package download remains available only as a secondary fallback.

---

### Task 1: Immutable Publish Batch Domain

**Files:**
- Modify: `backend/apps/growth/models.py`
- Create: `backend/apps/growth/migrations/0002_growthpublishbatch_growthpublishitem.py`
- Test: `backend/apps/growth/tests/test_publish_batch_models.py`

**Interfaces:**
- Produces: `GrowthPublishBatch`, `GrowthPublishItem`, their status enums, and database uniqueness constraints.
- Consumes: existing `OrganizationOwnedModel`, `ChannelPackage`, `SocialAccount`, and authenticated user model.

- [ ] **Step 1: Write failing model tests**

Add tests proving one `(organization, idempotency_key)` batch, one `(batch, channel)` item, protected organization ownership, JSON snapshots, and the exact status values `QUEUED`, `RUNNING`, `PARTIAL_SUCCESS`, `SUCCEEDED`, `FAILED`, `CONFIGURATION_REQUIRED` plus item statuses `QUEUED`, `RUNNING`, `SUCCEEDED`, `FAILED`, `SKIPPED`.

```python
def test_publish_batch_enforces_idempotency_per_organization(organization):
    GrowthPublishBatch.objects.create(
        organization=organization, idempotency_key="homepage-proof-1",
        status=GrowthPublishBatch.Status.QUEUED,
    )
    with pytest.raises(IntegrityError):
        GrowthPublishBatch.objects.create(
            organization=organization, idempotency_key="homepage-proof-1",
            status=GrowthPublishBatch.Status.QUEUED,
        )
```

- [ ] **Step 2: Run the focused test and verify RED**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/apps/growth/tests/test_publish_batch_models.py -q`

Expected: import failure because `GrowthPublishBatch` and `GrowthPublishItem` do not exist.

- [ ] **Step 3: Implement the models and migration**

`GrowthPublishBatch` stores `idempotency_key`, `request_fingerprint`, `status`, `is_demo`, `created_by`, and timestamps. `GrowthPublishItem` stores `batch`, `channel_package`, `social_account` nullable, `channel`, `payload_snapshot`, `status`, `attempt_number`, `external_post_id`, `external_post_url`, `last_error`, and timestamps. Use `PROTECT` for all history references and prohibit model deletion by overriding `delete()` on both history models.

- [ ] **Step 4: Run model tests and migration checks**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/apps/growth/tests/test_publish_batch_models.py -q`

Run: `backend\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run`

Expected: tests pass and Django reports no pending migrations.

- [ ] **Step 5: Commit the domain change**

```powershell
git add backend/apps/growth/models.py backend/apps/growth/migrations/0002_growthpublishbatch_growthpublishitem.py backend/apps/growth/tests/test_publish_batch_models.py
git commit -m "feat: add growth publishing batches"
```

### Task 2: Idempotent Fake Multichannel Execution Service

**Files:**
- Create: `backend/apps/growth/publishing.py`
- Modify: `backend/integrations/platforms/manual_fake.py`
- Test: `backend/apps/growth/tests/test_publish_batches.py`
- Test: `backend/integrations/platforms/tests/test_manual_fake.py`

**Interfaces:**
- Produces: `create_publish_batch(*, organization, actor, package_ids, idempotency_key) -> GrowthPublishBatch`, `retry_failed_items(*, batch, actor) -> GrowthPublishBatch`, and `serialize_publish_batch(batch) -> dict`.
- Consumes: approved `ChannelPackage` rows, active organization-owned `SocialAccount` rows, existing platform codes, and a Demo-only fake publish adapter.

- [ ] **Step 1: Write failing service tests**

Cover these real behaviors without mocking the service under test:

```python
def test_one_click_publishes_eligible_channels_and_is_idempotent(publish_context):
    first = create_publish_batch(
        organization=publish_context.organization,
        actor=publish_context.user,
        package_ids=[package.id for package in publish_context.packages],
        idempotency_key="publish-demo-1",
    )
    second = create_publish_batch(
        organization=publish_context.organization,
        actor=publish_context.user,
        package_ids=[package.id for package in reversed(publish_context.packages)],
        idempotency_key="publish-demo-1",
    )
    assert first.id == second.id
    assert first.items.count() == 4
    assert set(first.items.values_list("channel", flat=True)) == {
        "LINKEDIN", "FACEBOOK", "INSTAGRAM", "TIKTOK",
    }
```

Also prove: unapproved packages are skipped with `CONTENT_NOT_APPROVED`; foreign packages are rejected without enumeration; missing accounts become `ACCOUNT_NOT_CONNECTED`; one configured fake failure yields `PARTIAL_SUCCESS`; retry increments only failed items and never touches successful items; a reused key with a different package fingerprint raises a conflict; fake URLs use `https://example.invalid/demo-post/` and data label `Demo / Fake`.

- [ ] **Step 2: Run service tests and verify RED**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/apps/growth/tests/test_publish_batches.py backend/integrations/platforms/tests/test_manual_fake.py -q`

Expected: failure because batch publishing functions and the fake publish receipt do not exist.

- [ ] **Step 3: Implement canonical fingerprints and eligibility**

Sort unique package UUIDs before hashing. Lock packages with `select_for_update()`, verify the complete requested set belongs to the organization, snapshot each payload with canonical JSON, and resolve exactly one active `API_AUTO` demo account for the matching platform. Record explicit `SKIPPED` items for unapproved or unconnected channels.

- [ ] **Step 4: Implement Demo-only channel execution**

Add `simulate_publish(channel, payload, attempt_number, outcome)` to `manual_fake.py`. It must reject non-demo payloads and return a deterministic external ID and `example.invalid` URL. Keep the existing `publish()` refusal intact so no code path silently converts the manual connector into a real connector.

- [ ] **Step 5: Implement aggregation and retry**

Aggregate item states deterministically. Retry only `FAILED` items, retain successful external IDs, reuse the original payload snapshot, and refresh batch status after every attempt. Wrap each item attempt in its own transaction boundary so one failure cannot roll back successful siblings.

- [ ] **Step 6: Run service tests and verify GREEN**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/apps/growth/tests/test_publish_batches.py backend/integrations/platforms/tests/test_manual_fake.py -q`

Expected: all focused tests pass.

- [ ] **Step 7: Commit the execution service**

```powershell
git add backend/apps/growth/publishing.py backend/apps/growth/tests/test_publish_batches.py backend/integrations/platforms/manual_fake.py backend/integrations/platforms/tests/test_manual_fake.py
git commit -m "feat: execute idempotent fake publish batches"
```

### Task 3: Batch API and Workspace Readiness

**Files:**
- Modify: `backend/apps/growth/serializers.py`
- Modify: `backend/apps/growth/views.py`
- Modify: `backend/apps/growth/urls.py`
- Modify: `backend/tests/test_growth_workspace_api.py`
- Modify: `backend/apps/common/management/commands/seed_phase_a.py`
- Modify: `backend/apps/common/tests/test_seed_phase_a.py`

**Interfaces:**
- Produces: `POST /api/v1/growth/publish-batches`, `GET /api/v1/growth/publish-batches/{batch_id}`, and `POST /api/v1/growth/publish-batches/{batch_id}/retry-failed`.
- Request: `{ "package_ids": ["uuid", ...] }` plus required `Idempotency-Key` header.
- Response: `{ id, status, is_demo, data_label, created_at, items: [{ channel, status, attempt_number, external_post_url, error_code, recovery_action }] }`.

- [ ] **Step 1: Write failing API tests**

Prove permission checks, organization scoping, required idempotency header, strict UUID list validation, idempotent replay, `201` on first creation, `200` on replay, channel results, retry behavior, and no foreign object disclosure. Add workspace assertions that all four seeded connectors advertise `FAKE_CONNECTOR` and `ONE_CLICK_DEMO` without claiming real OAuth readiness.

- [ ] **Step 2: Run API tests and verify RED**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_growth_workspace_api.py backend/apps/common/tests/test_seed_phase_a.py -q`

Expected: `404` for the new routes and missing connector readiness fields.

- [ ] **Step 3: Add strict serializers and API views**

Use `CanManageCampaigns` for mutations and `CanReadCampaigns` for detail reads. Map service conflicts to stable `409` codes: `IDEMPOTENCY_CONFLICT`, `CONTENT_NOT_APPROVED`, and `NO_ELIGIBLE_CHANNELS`. Never include foreign package names or payloads in errors.

- [ ] **Step 4: Update the stable demo seed**

Keep the four existing channel package IDs. Ensure all four mock social accounts are active and mark their connector metadata as `fixture: phase-a-e2e`; keep TikTok configured to fail its first simulated attempt so partial-success and retry are visible. Do not create or reference any real secret.

- [ ] **Step 5: Run API tests and verify GREEN**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/tests/test_growth_workspace_api.py backend/apps/common/tests/test_seed_phase_a.py -q`

Expected: focused tests pass.

- [ ] **Step 6: Commit the API boundary**

```powershell
git add backend/apps/growth/serializers.py backend/apps/growth/views.py backend/apps/growth/urls.py backend/tests/test_growth_workspace_api.py backend/apps/common/management/commands/seed_phase_a.py backend/apps/common/tests/test_seed_phase_a.py
git commit -m "feat: expose one-click publishing API"
```

### Task 4: Factory-Owner One-Click Publishing UI

**Files:**
- Modify: `frontend/src/modules/growth/api.ts`
- Modify: `frontend/src/modules/growth/PromotionPage.vue`
- Modify: `frontend/src/modules/growth/growth-pages.css`
- Modify: `frontend/src/modules/growth/GrowthWorkspacePages.test.ts`

**Interfaces:**
- Produces: `createPublishBatch(packageIds, idempotencyKey)`, `getPublishBatch(batchId)`, `retryFailedPublishBatch(batchId)`, `PublishBatch`, and `PublishBatchItem`.
- Consumes: approved channel package IDs and the API contract from Task 3.

- [ ] **Step 1: Write failing component tests**

Add tests that approve all four packages, reveal one primary button named `一键发布到 4 个渠道`, send one POST containing four package IDs and a stable visible-ASCII idempotency key, render channel-level success/failure, label the outcome `Demo / Fake 发布结果`, offer `重试失败渠道`, and keep manual downloads as secondary controls. Also prove the button is absent when no package is approved.

- [ ] **Step 2: Run the component test and verify RED**

Run: `pnpm exec vitest run src/modules/growth/GrowthWorkspacePages.test.ts --maxWorkers=1`

Expected: no one-click publish button and no publish-batch request.

- [ ] **Step 3: Add typed API functions**

Use the shared API client and send `Idempotency-Key` as a header. Generate one key when the eligible package set changes and retain it across retries or accidental double clicks. Do not expose connector implementation names in the returned user-facing types.

- [ ] **Step 4: Implement the minimal publishing panel**

Replace the TikTok-only bottom approval row with a compact batch action panel. Show eligible channel names, one blue primary button, plain-language channel results, and a single retry button only when failures exist. Move all per-channel download buttons beneath a low-emphasis `手工发布备用` disclosure. Preserve the current cards, TikTok details, white background, restrained blue, and five-item navigation.

- [ ] **Step 5: Run component tests, typecheck, and lint**

Run: `pnpm exec vitest run src/modules/growth/GrowthWorkspacePages.test.ts --maxWorkers=1`

Run: `pnpm run typecheck`

Run: `pnpm run lint`

Expected: all checks pass without warnings.

- [ ] **Step 6: Commit the factory-owner UI**

```powershell
git add frontend/src/modules/growth/api.ts frontend/src/modules/growth/PromotionPage.vue frontend/src/modules/growth/growth-pages.css frontend/src/modules/growth/GrowthWorkspacePages.test.ts
git commit -m "feat: add one-click publishing to promotion"
```

### Task 5: Browser Acceptance and Full Regression

**Files:**
- Modify: `frontend/e2e/zz-growth-workspace-persistence.spec.ts`
- Modify: `docs/acceptance/2026-08-14-growth-workspace.md`

**Interfaces:**
- Consumes: seeded demo accounts/packages and all API/UI behavior from Tasks 1-4.
- Produces: executable browser evidence and updated local acceptance instructions.

- [ ] **Step 1: Extend the browser test before changing acceptance text**

Approve four packages, click `一键发布到 4 个渠道` once, assert one batch POST, verify three successes plus the seeded first-attempt TikTok failure, click `重试失败渠道`, verify TikTok succeeds, reload, and confirm the batch result persists. Assert every external URL uses `example.invalid` and the page says `Demo / Fake 发布结果`.

- [ ] **Step 2: Run the focused E2E test and verify it passes against a fresh isolated database**

Run: `pnpm run test:e2e -- zz-growth-workspace-persistence.spec.ts`

Expected: focused browser scenario passes; the launcher deletes only its owned temporary run directory.

- [ ] **Step 3: Update acceptance documentation**

Document the one-click batch, partial-success behavior, failed-only retry, fake labels, no real OAuth/API calls, and manual-download fallback. Record exact new backend/frontend test counts only after the full runs finish.

- [ ] **Step 4: Run complete verification**

Run backend tests: `backend\.venv\Scripts\python.exe -m pytest backend -q`

Run frontend tests: `pnpm exec vitest run --maxWorkers=1`

Run browser tests: `pnpm run test:e2e`

Run typecheck: `pnpm run typecheck`

Run lint: `pnpm run lint`

Run build: `pnpm run build`

Run migration check: `backend\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run`

Run formatting check: `git diff --check`

Expected: every command passes, no real network publish request occurs, and the local `/promotion` route remains available.

- [ ] **Step 5: Commit acceptance evidence**

```powershell
git add frontend/e2e/zz-growth-workspace-persistence.spec.ts docs/acceptance/2026-08-14-growth-workspace.md
git commit -m "test: verify one-click multichannel publishing"
```
