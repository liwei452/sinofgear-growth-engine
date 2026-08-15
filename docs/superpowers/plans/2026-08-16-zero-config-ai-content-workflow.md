# Zero-Config AI Content Workflow Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a two-stage AI content flow that recommends three evidence-backed market/product/ICP combinations, generates only the selected combination, displays the result immediately, and adds reversible trash for assets, briefs, and generated content.

**Architecture:** Add a small recommendation aggregate to the existing `content` app, execute recommendation through the existing Job/AIRun/provider boundary, and convert the selected option into the existing Campaign/ContentBrief generation pipeline. Reuse existing content lifecycle protection for generated results and existing asset status semantics; add explicit archive/restore services instead of deletion.

**Tech Stack:** Django 5 + Django REST Framework + Celery-compatible task boundary + PostgreSQL/SQLite tests; Vue 3 + TypeScript + TanStack Query + Vitest; Playwright E2E.

## Global Constraints

- Only verified, organization-owned product facts may support recommendations or generated claims.
- Real provider failure must never silently fall back to Fake; Fake/offline output remains explicitly labeled.
- The first recommendation action is an AI call; the second generation action creates content only for the chosen option.
- Results remain drafts or review items and never trigger email, DM, OAuth, social publishing, or other external writes.
- Preserve existing evidence, AIRun, review, publishing-package, organization, and permission boundaries.
- Do not modify the independent storefront, RFQ/drawing systems, production deployment, DNS, or paid data-source integrations.

---

### Task 1: Persist recommendation sessions and options

**Files:**
- Modify: `backend/apps/jobs/models.py`
- Modify: `backend/apps/content/models.py`
- Create: `backend/apps/jobs/migrations/0003_alter_job_type.py`
- Create: `backend/apps/content/migrations/0002_content_recommendations.py`
- Test: `backend/apps/content/tests/test_content_recommendations.py`
- Test: `backend/apps/jobs/tests/test_job_service.py`

**Interfaces:**
- Produces: `Job.Type.CONTENT_RECOMMEND`
- Produces: `ContentRecommendation` with statuses `QUEUED`, `RUNNING`, `READY`, `FAILED`, `ARCHIVED`
- Produces: `ContentRecommendationOption` with `position`, structured selection fields, evidence references, and `selected_at`

- [ ] **Step 1: Write failing model tests**

```python
def test_recommendation_requires_three_unique_options(organization, user):
    recommendation = ContentRecommendation.objects.create_for_job(
        organization=organization, created_by=user, job=create_recommend_job(organization)
    )
    with pytest.raises(ValidationError):
        recommendation.replace_options([valid_option(position=1)] * 3)

def test_recommendation_cannot_reference_another_organization(organization, other_product):
    with pytest.raises(ValidationError):
        ContentRecommendationOption(..., product=other_product).full_clean()
```

- [ ] **Step 2: Run the tests and confirm they fail**

Run: `python -m pytest backend/apps/content/tests/test_content_recommendations.py backend/apps/jobs/tests/test_job_service.py -q`

Expected: FAIL because `CONTENT_RECOMMEND` and recommendation models do not exist.

- [ ] **Step 3: Add the minimum models and migration**

```python
class ContentRecommendation(OrganizationScopedModel):
    class Status(models.TextChoices):
        QUEUED = "QUEUED", "Queued"
        RUNNING = "RUNNING", "Running"
        READY = "READY", "Ready"
        FAILED = "FAILED", "Failed"
        ARCHIVED = "ARCHIVED", "Archived"
    job = models.OneToOneField("jobs.Job", on_delete=models.PROTECT)
    input_snapshot = models.JSONField()
    provider_mode = models.CharField(max_length=32)
    selected_option = models.ForeignKey("ContentRecommendationOption", null=True, blank=True, on_delete=models.PROTECT, related_name="+")
    created_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT)

class ContentRecommendationOption(OrganizationScopedModel):
    recommendation = models.ForeignKey(ContentRecommendation, on_delete=models.PROTECT, related_name="options")
    position = models.PositiveSmallIntegerField()
    product = models.ForeignKey("catalog.Product", on_delete=models.PROTECT)
    market_code = models.CharField(max_length=8)
    language = models.CharField(max_length=16)
    customer_profile = models.CharField(max_length=255)
    channel_codes = models.JSONField(default=list)
    theme = models.CharField(max_length=500)
    rationale = models.TextField()
    evidence = models.JSONField(default=list)
    missing_information = models.JSONField(default=list)
```

Add uniqueness constraints for `(recommendation, position)` and `(recommendation, product, market_code, language, customer_profile, theme)`, plus model validation for organization ownership and bounded JSON/text values.

- [ ] **Step 4: Run migration drift and model tests**

Run: `python backend/manage.py makemigrations --check --dry-run && python -m pytest backend/apps/content/tests/test_content_recommendations.py backend/apps/jobs/tests/test_job_service.py -q`

Expected: no drift; PASS.

- [ ] **Step 5: Commit**

```text
git add backend/apps/jobs/models.py backend/apps/jobs/migrations/0003_alter_job_type.py backend/apps/content/models.py backend/apps/content/migrations/0002_content_recommendations.py backend/apps/content/tests/test_content_recommendations.py backend/apps/jobs/tests/test_job_service.py
git commit -m "feat: persist AI content recommendations"
```

### Task 2: Build and validate evidence-backed AI recommendations

**Files:**
- Create: `backend/apps/content/recommendations.py`
- Modify: `backend/apps/content/payloads.py`
- Modify: `backend/apps/content/tasks.py`
- Modify: `backend/apps/ai/orchestration.py`
- Test: `backend/apps/content/tests/test_content_recommendations.py`
- Test: `backend/integrations/ai/tests/test_deepseek_provider.py`

**Interfaces:**
- Produces: `build_recommendation_input(organization_id: UUID) -> RecommendationInput`
- Produces: `RECOMMENDATION_SCHEMA`
- Produces: `validate_recommendation_output(payload, allowed_input) -> list[ValidatedOption]`
- Produces: `generate_content_recommendations_job(job_id: str, prompt_version_id: str)`

- [ ] **Step 1: Write failing input and output validation tests**

```python
def test_recommendation_input_contains_only_verified_facts(...):
    snapshot = build_recommendation_input(organization.id).to_dict()
    assert snapshot["facts"] == [{"id": str(verified.id), "field": verified.field_name, "value": verified.value}]
    assert str(unverified.id) not in json.dumps(snapshot)

@pytest.mark.parametrize("mutation", [foreign_product, unknown_fact, fourth_option, duplicate_option, oversized_text])
def test_invalid_recommendation_output_is_rejected(mutation, allowed_input):
    with pytest.raises(ContentRecommendationError):
        validate_recommendation_output(mutation(valid_payload()), allowed_input)
```

- [ ] **Step 2: Run tests and confirm they fail**

Run: `python -m pytest backend/apps/content/tests/test_content_recommendations.py -q`

Expected: FAIL because builders and validators are missing.

- [ ] **Step 3: Implement strict schema and fact allow-list validation**

```python
RECOMMENDATION_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["options"],
    "properties": {"options": {"type": "array", "minItems": 3, "maxItems": 3, "items": OPTION_SCHEMA}},
}

def validate_recommendation_output(payload, allowed_input):
    validate(instance=payload, schema=RECOMMENDATION_SCHEMA)
    allowed_products = set(allowed_input.product_ids)
    allowed_facts = set(allowed_input.fact_ids)
    # Normalize bounded text and reject every unknown product/fact/market/channel.
    return normalized_options
```

The input builder must collect approved product facts, configured active/observed markets, available ICP summaries, enabled channel codes, and safe language choices. If required inputs are absent, raise `RecommendationInputError` with actionable missing-item codes instead of calling AI.

- [ ] **Step 4: Execute recommendations through existing provider orchestration**

Create a published prompt purpose `CONTENT_RECOMMEND`, use `PRODUCT_AI_PROVIDER`/`PRODUCT_AI_MODEL`, persist provider mode, AIRun, result references, and sanitized errors. Fake provider output must be deterministic and labeled only when Fake mode is explicitly configured.

- [ ] **Step 5: Run focused provider and recommendation tests**

Run: `python -m pytest backend/apps/content/tests/test_content_recommendations.py backend/integrations/ai/tests/test_deepseek_provider.py -q`

Expected: PASS for missing key, timeout, invalid JSON, oversized response, schema mismatch, injection text, and valid three-option output.

- [ ] **Step 6: Commit**

```text
git add backend/apps/content/recommendations.py backend/apps/content/payloads.py backend/apps/content/tasks.py backend/apps/ai/orchestration.py backend/apps/content/tests/test_content_recommendations.py backend/integrations/ai/tests/test_deepseek_provider.py
git commit -m "feat: generate evidence-backed content directions"
```

### Task 3: Expose recommendation and selection APIs

**Files:**
- Modify: `backend/apps/content/serializers.py`
- Modify: `backend/apps/content/services.py`
- Modify: `backend/apps/content/views.py`
- Modify: `backend/apps/content/urls.py`
- Modify: `backend/apps/campaigns/services.py`
- Test: `backend/apps/content/tests/test_content_api.py`
- Test: `backend/apps/content/tests/test_content_recommendations.py`
- Test: `backend/tests/test_openapi.py`
- Test: `backend/tests/test_openapi_contract.py`

**Interfaces:**
- `POST /api/v1/content-recommendations` creates or returns an idempotent recommendation job.
- `GET /api/v1/content-recommendations` returns current organization sessions, excluding archived by default.
- `GET /api/v1/content-recommendations/{id}` returns status and exactly three options when ready.
- `POST /api/v1/content-recommendations/{id}/options/{option_id}/select` creates/reuses a READY brief and returns it.

- [ ] **Step 1: Write failing API tests**

```python
def test_select_option_creates_one_ready_brief_and_is_idempotent(client, ready_recommendation):
    url = f"/api/v1/content-recommendations/{ready_recommendation.id}/options/{ready_recommendation.options.first().id}/select"
    first = client.post(url, {}, format="json")
    second = client.post(url, {}, format="json")
    assert first.status_code == second.status_code == 200
    assert first.json()["brief_id"] == second.json()["brief_id"]

def test_foreign_organization_cannot_read_or_select(client, foreign_recommendation):
    assert client.get(f"/api/v1/content-recommendations/{foreign_recommendation.id}").status_code == 404
```

- [ ] **Step 2: Run tests and confirm 404/route failures**

Run: `python -m pytest backend/apps/content/tests/test_content_api.py backend/apps/content/tests/test_content_recommendations.py -q`

- [ ] **Step 3: Implement serializers, services, routes, and OpenAPI contracts**

`select_recommendation_option(*, recommendation, option, actor) -> ContentBrief` must lock the session, reject non-READY/archived/foreign options, create or reuse a campaign/brief linked to the selected product and allowed platforms, mark the brief READY through the existing lifecycle service, and store the selection atomically.

- [ ] **Step 4: Run API and OpenAPI tests**

Run: `python -m pytest backend/apps/content/tests/test_content_api.py backend/apps/content/tests/test_content_recommendations.py backend/tests/test_openapi.py backend/tests/test_openapi_contract.py -q`

Expected: PASS; unknown fields return 400; missing permissions return 403; foreign resources return 404.

- [ ] **Step 5: Commit**

```text
git add backend/apps/content/serializers.py backend/apps/content/services.py backend/apps/content/views.py backend/apps/content/urls.py backend/apps/campaigns/services.py backend/apps/content/tests/test_content_api.py backend/apps/content/tests/test_content_recommendations.py backend/tests/test_openapi.py backend/tests/test_openapi_contract.py
git commit -m "feat: expose AI content direction workflow"
```

### Task 4: Replace the manual-first content factory with the two-stage flow

**Files:**
- Modify: `frontend/src/modules/content/api.ts`
- Modify: `frontend/src/modules/content/api.test.ts`
- Create: `frontend/src/modules/content/ContentRecommendationPanel.vue`
- Create: `frontend/src/modules/content/ContentRecommendationPanel.test.ts`
- Modify: `frontend/src/modules/content/ContentFactoryPage.vue`
- Modify: `frontend/src/modules/content/ContentFactoryPage.test.ts`

**Interfaces:**
- Produces TS types `ContentRecommendation`, `ContentRecommendationOption`, `RecommendationAccepted`.
- Produces API functions `createRecommendation`, `listRecommendations`, `getRecommendation`, `selectRecommendationOption`.
- `ContentRecommendationPanel` emits `brief-ready` with the selected READY brief.

- [ ] **Step 1: Write failing UI tests**

```ts
it("shows three AI directions and generates only the selected one", async () => {
  render(ContentFactoryPage)
  await user.click(screen.getByRole("button", { name: "让 AI 推荐推广方向" }))
  expect(await screen.findAllByRole("button", { name: "选择这个方向" })).toHaveLength(3)
  await user.click(screen.getAllByRole("button", { name: "选择这个方向" })[1])
  await user.click(screen.getByRole("button", { name: "生成这组内容" }))
  expect(await screen.findByText("Generated visible title")).toBeVisible()
  expect(screen.queryByText(/^job-/)).not.toBeInTheDocument()
})
```

- [ ] **Step 2: Run tests and confirm failure**

Run: `pnpm --dir frontend vitest run src/modules/content/api.test.ts src/modules/content/ContentRecommendationPanel.test.ts src/modules/content/ContentFactoryPage.test.ts`

- [ ] **Step 3: Add typed API functions and recommendation panel**

The panel must display provider state before the first call, poll only the returned job/session, render three cards with reasons/evidence/missing information, and keep technical IDs in an expandable detail section.

- [ ] **Step 4: Render generated master content immediately**

After generation succeeds, invalidate the master-content query, fetch `result_reference.id`, assign it to `focusedMasterId`, render title/body/CTA/tags/evidence, and call `scrollIntoView({ block: "start", behavior: "smooth" })`. Provide edit, submit-review, and archive actions; do not auto-submit.

- [ ] **Step 5: Run focused frontend tests**

Run: `pnpm --dir frontend vitest run src/modules/content/api.test.ts src/modules/content/ContentRecommendationPanel.test.ts src/modules/content/ContentFactoryPage.test.ts`

Expected: PASS for configured AI, configuration required, explicit Fake label, retry, duplicate click, refresh restoration, and visible result.

- [ ] **Step 6: Commit**

```text
git add frontend/src/modules/content/api.ts frontend/src/modules/content/api.test.ts frontend/src/modules/content/ContentRecommendationPanel.vue frontend/src/modules/content/ContentRecommendationPanel.test.ts frontend/src/modules/content/ContentFactoryPage.vue frontend/src/modules/content/ContentFactoryPage.test.ts
git commit -m "feat: add guided AI content generation"
```

### Task 5: Add reversible archive and restore services

**Files:**
- Modify: `backend/apps/assets/services.py`
- Modify: `backend/apps/assets/views.py`
- Modify: `backend/apps/assets/urls.py`
- Modify: `backend/apps/campaigns/models.py`
- Modify: `backend/apps/campaigns/services.py`
- Modify: `backend/apps/campaigns/views.py`
- Modify: `backend/apps/campaigns/urls.py`
- Modify: `backend/apps/content/models.py`
- Modify: `backend/apps/content/services.py`
- Modify: `backend/apps/content/views.py`
- Modify: `backend/apps/content/urls.py`
- Create: `backend/apps/assets/migrations/0003_materialasset_archive_metadata.py`
- Create: `backend/apps/campaigns/migrations/0003_contentbrief_archive_metadata.py`
- Create: `backend/apps/content/migrations/0003_mastercontent_archive_metadata.py`
- Test: `backend/apps/assets/tests/test_asset_api.py`
- Test: `backend/apps/campaigns/tests/test_campaign_api.py`
- Test: `backend/apps/content/tests/test_content_api.py`

**Interfaces:**
- `POST /api/v1/assets/{id}/archive` and `/restore`
- `POST /api/v1/content-briefs/{id}/archive` and `/restore`
- `POST /api/v1/master-contents/{id}/restore`
- List endpoints accept `status=ARCHIVED`; default lists hide archived records.

- [ ] **Step 1: Write failing archive/restore and permission tests**

```python
@pytest.mark.parametrize("resource", ["asset", "brief", "master"])
def test_archive_hides_and_restore_returns_resource(resource, clients, factories):
    item = factories[resource]()
    assert clients.manager.post(f"/api/v1/{resource_path(resource)}/{item.id}/archive", {}).status_code == 200
    assert item.id not in list_default_ids(clients.manager, resource)
    assert clients.viewer.post(f"/api/v1/{resource_path(resource)}/{item.id}/restore", {}).status_code == 403
    assert clients.manager.post(f"/api/v1/{resource_path(resource)}/{item.id}/restore", {}).status_code == 200
```

- [ ] **Step 2: Run focused backend tests and confirm route/state failures**

Run: `python -m pytest backend/apps/assets/tests/test_asset_api.py backend/apps/campaigns/tests/test_campaign_api.py backend/apps/content/tests/test_content_api.py -q`

- [ ] **Step 3: Implement atomic archive/restore services**

Store `archived_at`, `archived_by`, and `archived_from_status` where status alone cannot restore the prior lifecycle. Preserve binaries, links, evidence, AIRuns, review records, funnel events, and provenance. Reject review/generation/channel-package actions while archived. Return an impact summary for referenced assets; do not delete references.

- [ ] **Step 4: Run migration, permissions, and lifecycle tests**

Run: `python backend/manage.py makemigrations --check --dry-run && python -m pytest backend/apps/assets/tests backend/apps/campaigns/tests backend/apps/content/tests -q`

Expected: PASS; archive is idempotent; restore is idempotent; cross-organization actions return 404.

- [ ] **Step 5: Commit**

```text
git add backend/apps/assets backend/apps/campaigns backend/apps/content
git commit -m "feat: add reversible content trash"
```

### Task 6: Add the user-visible recycle bin

**Files:**
- Modify: `frontend/src/modules/assets/api.ts`
- Modify: `frontend/src/modules/assets/AssetLibraryPage.vue`
- Modify: `frontend/src/modules/assets/AssetLibraryPage.test.ts`
- Modify: `frontend/src/modules/content/api.ts`
- Create: `frontend/src/modules/content/ContentTrashPanel.vue`
- Create: `frontend/src/modules/content/ContentTrashPanel.test.ts`
- Modify: `frontend/src/modules/content/ContentFactoryPage.vue`
- Modify: `frontend/src/modules/content/ContentFactoryPage.test.ts`

**Interfaces:**
- Adds `archiveAsset`, `restoreAsset`, `archiveBrief`, `restoreBrief`, `restoreMasterContent`.
- `ContentTrashPanel` shows archived assets, briefs, and generated results and emits `restored`.

- [ ] **Step 1: Write failing UI tests for archive, impact copy, refresh, and restore**

```ts
it("moves a generated result to trash and restores it", async () => {
  render(ContentFactoryPage)
  await user.click(await screen.findByRole("button", { name: "移到回收站" }))
  expect(screen.queryByText("Generated visible title")).not.toBeInTheDocument()
  await user.click(screen.getByRole("button", { name: "回收站" }))
  await user.click(await screen.findByRole("button", { name: "恢复" }))
  expect(await screen.findByText("Generated visible title")).toBeVisible()
})
```

- [ ] **Step 2: Run focused tests and confirm they fail**

Run: `pnpm --dir frontend vitest run src/modules/assets/AssetLibraryPage.test.ts src/modules/content/ContentTrashPanel.test.ts src/modules/content/ContentFactoryPage.test.ts`

- [ ] **Step 3: Implement minimal archive/restore actions and recycle-bin panel**

Use one secondary “回收站” entry, show object type and archive time, expose only real restore actions, and display asset reference impact before archive. Keep permanent deletion out of the normal flow.

- [ ] **Step 4: Run focused frontend tests**

Run: `pnpm --dir frontend vitest run src/modules/assets/AssetLibraryPage.test.ts src/modules/content/ContentTrashPanel.test.ts src/modules/content/ContentFactoryPage.test.ts`

Expected: PASS including permissions, request failures, refresh persistence, and no fake fallback rows.

- [ ] **Step 5: Commit**

```text
git add frontend/src/modules/assets frontend/src/modules/content
git commit -m "feat: expose reversible content recycle bin"
```

### Task 7: Browser acceptance and full regression

**Files:**
- Create: `frontend/e2e/zero-config-ai-content.spec.ts`
- Modify: `frontend/e2e/launcher.mjs`
- Modify: `docs/superpowers/plans/2026-08-16-zero-config-ai-content-workflow.md` only to check completed steps

**Interfaces:**
- Produces one explicit Fake/offline E2E workflow; no paid/provider/network calls.

- [ ] **Step 1: Add an E2E test that explicitly injects organization-owned fixture facts**

```ts
test("recommend, select, view, archive, refresh, and restore content", async ({ page }) => {
  await seedVerifiedFactsAndExplicitFakeProvider(page)
  await page.goto("/content-factory")
  await page.getByRole("button", { name: "让 AI 推荐推广方向" }).click()
  await expect(page.getByRole("button", { name: "选择这个方向" })).toHaveCount(3)
  await page.getByRole("button", { name: "选择这个方向" }).nth(1).click()
  await page.getByRole("button", { name: "生成这组内容" }).click()
  await expect(page.getByRole("heading", { name: /for/ })).toBeVisible()
  await page.getByRole("button", { name: "移到回收站" }).click()
  await page.reload()
  await page.getByRole("button", { name: "回收站" }).click()
  await page.getByRole("button", { name: "恢复" }).click()
})
```

- [ ] **Step 2: Run the new E2E test alone**

Run: `pnpm --dir frontend exec playwright test e2e/zero-config-ai-content.spec.ts`

Expected: PASS with no real provider or social requests.

- [ ] **Step 3: Run one final full verification pass**

Run:

```text
python -m pytest backend -q
python backend/manage.py makemigrations --check --dry-run
python backend/manage.py spectacular --validate --file NUL
pnpm --dir frontend test
pnpm --dir frontend lint
pnpm --dir frontend typecheck
pnpm --dir frontend build
pnpm --dir frontend exec playwright test
```

Expected: all backend/frontend tests, OpenAPI, migration drift, lint, typecheck, build, and E2E pass.

- [ ] **Step 4: Verify local preview**

Confirm `http://127.0.0.1:3001/content-factory` loads, provider status is honest, recommendations/results persist after refresh, archived rows are hidden from normal lists, and no real external write occurs.

- [ ] **Step 5: Commit**

```text
git add frontend/e2e/zero-config-ai-content.spec.ts frontend/e2e/launcher.mjs docs/superpowers/plans/2026-08-16-zero-config-ai-content-workflow.md
git commit -m "test: verify zero-config AI content workflow"
```
