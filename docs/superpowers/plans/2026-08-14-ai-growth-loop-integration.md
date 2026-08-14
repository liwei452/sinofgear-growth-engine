# AI Growth Loop Integration Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Turn the existing growth engine and independent site into one usable AI-led foreign-trade promotion, lead-signal, website-conversion, and CRM-handoff loop without adding a third application.

**Architecture:** `sinofgear-growth-engine` remains the private system of record and orchestration brain; `../app` remains the only public website and receives versioned, approved publication bundles. The site returns signed inquiry-conversion events to the growth engine, while all AI, monitoring, enrichment, evidence, approval, tracking, and CRM-handoff state stays in Django/PostgreSQL and existing Celery/Redis jobs.

**Tech Stack:** Django 5/DRF/PostgreSQL/Celery/Redis/MinIO, Vue 3/Vite/TanStack Query, React 19/Vite/React Router/Tailwind, Cloudflare Pages Functions, Resend, pytest, Vitest, Playwright, OpenAPI.

## Global Constraints

- Modify only the two existing repositories: `sinofgear-growth-engine` and `../app`; do not install or create Postiz, OpenFang, Mautic, n8n, Activepieces, or another standalone platform.
- Keep the formal website at `https://sinfogear.com`; do not change DNS, canonical configuration, `sinofgear.com`, or `sinoforce.net`.
- Keep inquiry delivery addresses unchanged: `452900431@qq.com` and `inquiries@sinfogear.com`; automated tests must use fakes and must not send real email or submit a real production inquiry.
- Preserve unrelated dirty changes in `../app`, especially the existing deleted `platform/packages/contracts/*` files and untracked `.superpowers/` directory.
- At execution time, create isolated worktrees for both repositories with `superpowers:using-git-worktrees`; never implement directly on the dirty `app` worktree.
- Ordinary users see only `今天`, `开始推广`, `客户机会`, `效果`, and `公司资料`; Campaign, Brief, Prompt, Ontology, Job, AIRun, connector, and credential details remain administrator-only.
- Every customer-facing non-Chinese generated content record stores a complete Chinese counterpart.
- AI may propose facts but cannot approve price, lead time, accuracy, certification, material, or manufacturing-capability claims.
- Only approved content may publish; every AI run retains PromptVersion, input snapshot, output JSON, confidence, ontology snapshot, and correction history.
- Social connectors use official APIs/OAuth or explicit licensed sources. Never store platform passwords/cookies, bypass CAPTCHA/anti-bot controls, or automatically message strangers.
- Every high-value lead opportunity requires immutable source evidence; an AI score alone is insufficient.
- CRM remains a handoff boundary, not a CRM implementation.
- Use TDD for every task, regenerate OpenAPI types only from the checked backend schema, and make one intentional commit per task.

## Repository and File Map

### Growth engine (`sinofgear-growth-engine`)

- `backend/apps/growth/`: GrowthProposal, product-document extraction, orchestration, approval, and public user-facing decision APIs.
- `backend/apps/website/`: approved website bundles, build-safe publication feed, signed inbound conversion webhook, and conversion records.
- `backend/apps/leads/`: monitoring targets/runs, source content/evidence, company matches, lead insights, scoring, daily jobs, and CRM handoff preparation.
- `backend/integrations/ai/`: text, vision, image-generation, and image-edit provider capability interfaces.
- `backend/integrations/sources/`: official/public source adapters with normalized results and cursor boundaries.
- `frontend/src/modules/today/`, `promotion/`, `opportunities/`, `company/`, `admin/`: the new ordinary/admin interaction split.
- Existing `catalog`, `assets`, `campaigns`, `content`, `publishing`, `tracking`, `jobs`, `ai`, `knowledge`, and `platforms` remain authoritative lower-level services.

### Independent site (`../app`)

- `src/growth/contracts.ts`: website publication bundle and attribution types shared by site runtime/build scripts.
- `src/growth/generated-content.json`: generated, reviewed website snapshot consumed at build time.
- `src/growth/content.ts`: validates and maps generated articles/products into existing site view models.
- `scripts/sync-growth-content.ts`: fetches the approved feed using a deploy-only token and atomically updates the generated snapshot.
- `src/attribution/context.ts`: allowlisted UTM/content/product context capture without personal data.
- `functions/lib/growthWebhook.ts`: signed inquiry-conversion delivery with bounded retries and idempotency.
- Existing product, blog, SEO, prerender, inquiry email, attachment, and analytics modules remain in place.

---

## Phase 1 — AI-First Promotion Experience

### Task 1: Add provider capabilities and bilingual generation contracts

**Files:**
- Create: `backend/integrations/ai/contracts.py`
- Modify: `backend/integrations/ai/providers.py`
- Modify: `backend/apps/content/payloads.py`
- Modify: `backend/apps/content/services.py`
- Test: `backend/integrations/ai/tests/test_provider_contracts.py`
- Test: `backend/apps/content/tests/test_bilingual_payloads.py`

**Interfaces:**
- Consumes: existing provider selection and `AIRun` orchestration.
- Produces: `AIProviderCapability`, `TextGenerationResult`, `ImageGenerationResult`, `ImageEditResult`, `BilingualContentPayload`, and `get_ai_provider(required_capabilities)`.

- [ ] **Step 1: Write failing provider capability tests**

```python
def test_provider_registry_rejects_missing_multimodal_capability():
    with pytest.raises(ProviderCapabilityError):
        get_ai_provider({AIProviderCapability.IMAGE_EDIT})

def test_deepseek_is_registered_for_text_not_image_generation():
    provider = get_named_ai_provider("deepseek")
    assert AIProviderCapability.TEXT in provider.capabilities
    assert AIProviderCapability.IMAGE_GENERATE not in provider.capabilities
```

- [ ] **Step 2: Run the provider tests and verify failure**

Run: `cd backend && pytest integrations/ai/tests/test_provider_contracts.py -q`  
Expected: FAIL because capability contracts and registry lookup do not exist.

- [ ] **Step 3: Implement explicit provider contracts**

```python
class AIProviderCapability(StrEnum):
    TEXT = "TEXT"
    VISION = "VISION"
    IMAGE_GENERATE = "IMAGE_GENERATE"
    IMAGE_EDIT = "IMAGE_EDIT"

@dataclass(frozen=True)
class TextGenerationResult:
    source_text: str
    chinese_reference: str
    model: str
    provider: str
    usage: dict[str, int]
```

Registry lookup must fail closed when no configured provider supports every requested capability. DeepSeek receives `TEXT`; future multimodal providers register independently through the same interface.

- [ ] **Step 4: Write failing bilingual payload tests**

```python
def test_non_chinese_platform_content_requires_chinese_reference():
    with pytest.raises(ValidationError):
        BilingualContentPayload(
            language="en", source_text="Precision helical gears", chinese_reference=""
        ).validate()
```

- [ ] **Step 5: Implement and validate `BilingualContentPayload`**

The payload must contain `language`, `source_text`, `chinese_reference`, `title`, `cta`, `platform_code`, `media_requests`, `fact_references`, and `landing_page_url`. Chinese source content may mirror `source_text`; all other languages require a non-empty Chinese counterpart.

- [ ] **Step 6: Run focused and existing AI/content tests**

Run: `cd backend && pytest integrations/ai/tests apps/content/tests apps/ai/tests -q`  
Expected: PASS with no change to stored secrets or existing AIRun audit behavior.

- [ ] **Step 7: Commit**

```bash
git add backend/integrations/ai backend/apps/content
git commit -m "feat: add multimodal and bilingual ai contracts"
```

### Task 2: Add product-document extraction and fact review

**Files:**
- Create: `backend/apps/growth/__init__.py`
- Create: `backend/apps/growth/apps.py`
- Create: `backend/apps/growth/models.py`
- Create: `backend/apps/growth/extraction.py`
- Create: `backend/apps/growth/tasks.py`
- Create: `backend/apps/growth/migrations/0001_initial.py`
- Modify: `backend/config/settings.py`
- Test: `backend/apps/growth/tests/test_product_document_extraction.py`
- Test: `backend/apps/growth/tests/test_fact_review.py`

**Interfaces:**
- Consumes: `Asset`, `Product`, `KnowledgeEvidence`, `Job`, `PromptVersion`, `AIRun`, and provider capability contracts from Task 1.
- Produces: `ProductDocumentExtraction`, `ExtractedFact`, `start_product_document_extraction(asset_id, actor) -> Job`, and `review_extracted_fact(fact_id, action, correction, actor)`.

- [ ] **Step 1: Write failing model tests**

```python
def test_extracted_fact_defaults_to_suggested_and_keeps_evidence(asset):
    extraction = ProductDocumentExtraction.objects.create(
        organization=asset.organization,
        asset=asset,
        status=ProductDocumentExtraction.Status.QUEUED,
    )
    fact = ExtractedFact.objects.create(
        extraction=extraction,
        fact_type=ExtractedFact.Type.ACCURACY,
        value_json={"grade": "DIN 6"},
        source_locator={"page": 4, "quote": "DIN 6"},
        confidence="0.82",
    )
    assert fact.review_status == ExtractedFact.ReviewStatus.SUGGESTED
    assert fact.source_locator["page"] == 4
```

- [ ] **Step 2: Run tests and verify missing models**

Run: `cd backend && pytest apps/growth/tests/test_product_document_extraction.py -q`  
Expected: FAIL on missing `apps.growth` models.

- [ ] **Step 3: Implement extraction models and immutable source locators**

`ProductDocumentExtraction` fields: organization, asset, status, job, prompt_version, ai_run, language, started_at, finished_at, error_code. `ExtractedFact` fields: extraction, fact_type, value_json, source_locator, confidence, risk_level, review_status, reviewer, reviewed_at, correction_json. Updates to `value_json` after creation are forbidden; review creates explicit correction data.

- [ ] **Step 4: Write failing extraction service tests with a fake provider**

```python
def test_extraction_creates_high_risk_fact_without_approving_it(fake_vision_provider, manual_asset):
    run_product_document_extraction(manual_asset.id)
    fact = ExtractedFact.objects.get(fact_type="CERTIFICATION")
    assert fact.risk_level == "HIGH"
    assert fact.review_status == "SUGGESTED"
```

- [ ] **Step 5: Implement bounded PDF/image extraction**

Allow PDF and supported image assets only; enforce existing asset size/type rules; use `VISION` only when OCR/text extraction is insufficient. Map output to an allowlisted schema for product type, specification, material, process, application, standard, advantage, MOQ, lead time, certification, and prohibited claim. Reject prompt instructions found inside documents as untrusted content.

- [ ] **Step 6: Implement human fact review**

`APPROVE` may create a proposed Product version or KnowledgeEvidence link through existing services. High-risk facts require explicit reviewer action; `REJECT` and `CORRECT` retain the AI value and add review history.

- [ ] **Step 7: Run migrations and tests**

Run: `cd backend && python manage.py makemigrations --check && pytest apps/growth/tests apps/assets/tests apps/catalog/tests apps/knowledge/tests -q`  
Expected: PASS; migration drift check reports no pending changes.

- [ ] **Step 8: Commit**

```bash
git add backend/apps/growth backend/config/settings.py
git commit -m "feat: extract reviewable product facts from manuals"
```

### Task 3: Add GrowthProposal orchestration and approval

**Files:**
- Modify: `backend/apps/growth/models.py`
- Create: `backend/apps/growth/services.py`
- Create: `backend/apps/growth/serializers.py`
- Create: `backend/apps/growth/views.py`
- Create: `backend/apps/growth/urls.py`
- Create: `backend/apps/growth/migrations/0002_growthproposal.py`
- Modify: `backend/config/urls.py`
- Modify: `backend/apps/identity/services.py`
- Create: `backend/apps/identity/migrations/0011_growth_permissions.py`
- Test: `backend/apps/growth/tests/test_growth_proposal_api.py`
- Test: `backend/apps/growth/tests/test_growth_proposal_approval.py`
- Modify: `backend/tests/test_openapi_contract.py`

**Interfaces:**
- Consumes: approved product/knowledge facts, platform capabilities, assets, tracking destinations, historical analytics, and existing campaign/content/monitoring service boundaries.
- Produces: `GrowthProposal`, `GrowthProposalItem`, `POST /api/v1/growth-proposals`, `POST /api/v1/growth-proposals/{id}/approve`, and `POST /api/v1/growth-proposals/{id}/reject`.

- [ ] **Step 1: Write failing API tests for a one-sentence goal**

```python
response = client.post(
    "/api/v1/growth-proposals",
    {"product_ids": [str(product.id)], "goal": "推广到德国包装机械行业"},
    format="json",
    HTTP_IDEMPOTENCY_KEY="growth-proposal-1",
)
assert response.status_code == 202
assert response.json()["job_id"]
```

- [ ] **Step 2: Run the focused API test and verify 404**

Run: `cd backend && pytest apps/growth/tests/test_growth_proposal_api.py -q`  
Expected: FAIL because the route does not exist.

- [ ] **Step 3: Implement proposal state and immutable plan snapshot**

States: `DRAFT`, `GENERATING`, `READY_FOR_REVIEW`, `APPROVED`, `REJECTED`, `EXECUTING`, `COMPLETED`, `PARTIAL_FAILURE`, `FAILED`. Store `goal`, `strategy_json`, `evidence_json`, `cost_estimate_json`, `required_confirmations_json`, PromptVersion/AIRun/Ontology snapshot, and version. `GrowthProposalItem` types: `SOCIAL_CONTENT`, `WEBSITE_ARTICLE`, `LEAD_MONITORING`, `AIEO_CHECK`.

- [ ] **Step 4: Implement proposal generation using existing services**

The generator chooses products, markets, ICP, platforms, landing destinations, bilingual topics, media requests, and monitoring criteria. It must not create active Campaign/Brief/PublishTask/MonitoringTask records before approval.

- [ ] **Step 5: Write failing approval atomicity tests**

```python
def test_approval_creates_lower_level_drafts_once(proposal, reviewer):
    first = approve_growth_proposal(proposal.id, reviewer)
    second = approve_growth_proposal(proposal.id, reviewer)
    assert first.id == second.id
    assert Campaign.objects.filter(growth_proposal_id=proposal.id).count() == 1
```

- [ ] **Step 6: Implement idempotent approval and audit**

Within one transaction, lock proposal/version, validate required confirmations, create lower-level drafts using existing domain services, create approval audit, and enqueue execution jobs after commit. Repeated approval returns the same result; stale versions return 409.

- [ ] **Step 7: Add permissions and OpenAPI coverage**

Permissions: `growth.read`, `growth.manage`, `growth.review`. Ordinary operator receives read/manage/review needed for the simple flow; only admins retain lower-level advanced permissions.

- [ ] **Step 8: Run backend checks**

Run: `cd backend && pytest apps/growth/tests apps/campaigns/tests apps/content/tests apps/jobs/tests tests/test_openapi_contract.py -q`  
Run: `cd backend && python manage.py check && python manage.py makemigrations --check`  
Expected: all PASS.

- [ ] **Step 9: Commit**

```bash
git add backend/apps/growth backend/apps/identity backend/config backend/tests/test_openapi_contract.py
git commit -m "feat: orchestrate reviewable ai growth proposals"
```

### Task 4: Replace the ordinary content factory with the simple AI promotion flow

**Files:**
- Create: `frontend/src/modules/promotion/api.ts`
- Create: `frontend/src/modules/promotion/api.test.ts`
- Create: `frontend/src/modules/promotion/PromotionPage.vue`
- Create: `frontend/src/modules/promotion/PromotionPage.test.ts`
- Create: `frontend/src/modules/today/TodayPage.vue`
- Create: `frontend/src/modules/today/TodayPage.test.ts`
- Create: `frontend/src/modules/admin/AdminHomePage.vue`
- Create: `frontend/src/modules/admin/AdminHomePage.test.ts`
- Modify: `frontend/src/app/router.ts`
- Modify: `frontend/src/app/router.test.ts`
- Modify: `frontend/src/app/AppShell.vue`
- Modify: `frontend/src/app/AppShell.test.ts`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/styles/tokens.css`
- Modify: `frontend/src/styles/base.css`

**Interfaces:**
- Consumes: proposal and extraction APIs from Tasks 2–3.
- Produces: `/promotion`, `/`, and `/admin` experiences with ordinary/admin navigation separation.

- [ ] **Step 1: Write failing navigation tests**

```ts
expect(screen.getByRole('link', { name: '开始推广' })).toBeVisible()
expect(screen.getByRole('link', { name: '客户机会' })).toBeVisible()
expect(screen.queryByRole('link', { name: 'AI 内容工厂' })).not.toBeInTheDocument()
```

- [ ] **Step 2: Run UI tests and verify failure**

Run: `cd frontend && pnpm test -- AppShell.test.ts router.test.ts`  
Expected: FAIL because the new routes and navigation do not exist.

- [ ] **Step 3: Implement role-aware navigation**

Ordinary navigation: `今天`, `开始推广`, `客户机会`, `效果`, `公司资料`. Admin navigation is available only when membership includes administrator permissions and contains the existing products, knowledge, assets, campaigns/content, reviews, publishing, platform accounts, AI settings, jobs, and audit pages.

- [ ] **Step 4: Write failing promotion-flow tests**

```ts
await user.upload(screen.getByLabelText('上传产品手册或图片'), manualFile)
await user.type(screen.getByLabelText('推广目标（可选）'), '推广到德国包装机械行业')
await user.click(screen.getByRole('button', { name: '让AI制定方案' }))
expect(await screen.findByText('AI正在分析产品和市场')).toBeVisible()
```

- [ ] **Step 5: Implement progressive disclosure**

The default screen contains one upload/selection area, one optional goal input, and one primary button. `READY_FOR_REVIEW` renders strategy cards with `批准执行`, `调整目标`, and `查看AI依据`; lower-level IDs and advanced fields are never shown to ordinary users.

- [ ] **Step 6: Implement Today decision queue**

Aggregate proposal decisions, pending bilingual content, high-value opportunities, inbound inquiries, and failed jobs into user-language cards. Each card must state what AI did, why a decision is needed, and the single recommended action.

- [ ] **Step 7: Run frontend quality gates**

Run: `cd frontend && pnpm test -- PromotionPage.test.ts TodayPage.test.ts AppShell.test.ts router.test.ts`  
Run: `cd frontend && pnpm typecheck && pnpm lint && pnpm build`  
Expected: PASS, no horizontal overflow at 360px, keyboard focus remains visible, and primary controls are at least 44px high.

- [ ] **Step 8: Commit**

```bash
git add frontend/src
git commit -m "feat: replace content setup with ai promotion flow"
```

## Phase 2 — Approved Website Publishing and Inquiry Conversion

### Task 5: Add versioned website publication bundles to the growth engine

**Files:**
- Create: `backend/apps/website/__init__.py`
- Create: `backend/apps/website/apps.py`
- Create: `backend/apps/website/models.py`
- Create: `backend/apps/website/contracts.py`
- Create: `backend/apps/website/services.py`
- Create: `backend/apps/website/serializers.py`
- Create: `backend/apps/website/views.py`
- Create: `backend/apps/website/urls.py`
- Create: `backend/apps/website/migrations/0001_initial.py`
- Modify: `backend/config/settings.py`
- Modify: `backend/config/urls.py`
- Test: `backend/apps/website/tests/test_publication_bundle.py`
- Test: `backend/apps/website/tests/test_publication_feed.py`
- Modify: `backend/tests/test_openapi_contract.py`

**Interfaces:**
- Consumes: approved `MasterContent`, approved product snapshots, KnowledgeEvidence, media assets, and tracking destinations.
- Produces: `WebsitePublicationBundle`, `build_publication_bundle(content_id, actor)`, and deploy-token-protected `GET /api/v1/website-publications/feed`.

- [ ] **Step 1: Write a failing contract test**

```python
def test_bundle_contains_only_approved_content_and_relative_canonical_path(approved_content):
    bundle = build_publication_bundle(approved_content.id, approved_content.reviewed_by)
    assert bundle.payload["schema_version"] == "1.0"
    assert bundle.payload["canonical_path"].startswith("/blog/")
    assert "sinfogear.com" not in bundle.payload["canonical_path"]
```

- [ ] **Step 2: Run test and verify missing website app**

Run: `cd backend && pytest apps/website/tests/test_publication_bundle.py -q`  
Expected: FAIL because the contract does not exist.

- [ ] **Step 3: Implement the bundle schema**

```python
class WebsitePublicationPayload(TypedDict):
    schema_version: Literal["1.0"]
    bundle_id: str
    version: int
    content_id: str
    product_ids: list[str]
    kind: Literal["BLOG_ARTICLE", "PRODUCT_UPDATE", "CASE_STUDY", "FAQ"]
    locale: str
    slug: str
    title: str
    summary: str
    sections: list[dict[str, object]]
    seo: dict[str, object]
    canonical_path: str
    cta: dict[str, str]
    media: list[dict[str, str]]
    evidence: list[dict[str, str]]
    checksum: str
```

The checksum covers a canonical JSON representation. Bundle rows are immutable; a correction creates the next version and may supersede, never edit, a published version.

- [ ] **Step 4: Implement feed authentication and ETag**

The feed accepts a dedicated read-only deploy token stored server-side, returns only `PUBLISHED_TO_FEED` bundles, supports `If-None-Match`, and never exposes internal AIRun/Prompt data or private asset URLs.

- [ ] **Step 5: Run API and security tests**

Run: `cd backend && pytest apps/website/tests tests/test_openapi_contract.py -q`  
Expected: PASS; invalid token is 401, stale version is excluded, unsafe external links are rejected.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/website backend/config backend/tests/test_openapi_contract.py
git commit -m "feat: publish approved website content bundles"
```

### Task 6: Consume approved bundles in the existing independent site build

**Files (`../app` worktree):**
- Create: `src/growth/contracts.ts`
- Create: `src/growth/content.ts`
- Create: `src/growth/generated-content.json`
- Create: `src/growth/content.test.ts`
- Create: `scripts/sync-growth-content.ts`
- Create: `scripts/sync-growth-content.test.ts`
- Modify: `src/data/articles.ts`
- Modify: `src/data/articles.test.ts`
- Modify: `src/pages/BlogIndexPage.tsx`
- Modify: `src/pages/BlogArticlePage.tsx`
- Modify: `scripts/static-site.ts`
- Modify: `package.json`
- Modify: `.env.example`

**Interfaces:**
- Consumes: Task 5 feed payload and `ETag` using `GROWTH_CONTENT_FEED_URL` and deploy-only `GROWTH_CONTENT_DEPLOY_TOKEN` at build time.
- Produces: validated generated articles merged into existing blog routes and static prerender output.

- [ ] **Step 1: Write failing schema-validation tests**

```ts
expect(() => parseWebsiteBundle({ schema_version: '2.0' })).toThrow('Unsupported bundle schema')
expect(() => parseWebsiteBundle({ ...validBundle, checksum: 'wrong' })).toThrow('Bundle checksum mismatch')
```

- [ ] **Step 2: Run tests and verify missing parser**

Run: `npm test -- src/growth/content.test.ts`  
Expected: FAIL because `parseWebsiteBundle` does not exist.

- [ ] **Step 3: Implement strict local contracts**

Accept schema `1.0`, allowlisted block types, relative canonical/CTA paths, approved media hosts, valid locale, unique slug/version, and checksum. Reject script/style/raw HTML, external canonical URLs, unknown fields that change rendering semantics, and duplicate active slugs.

- [ ] **Step 4: Implement atomic build-time sync**

`npm run sync:growth-content` downloads into a temporary file, validates the entire feed, compares ETag/checksum, and renames only after success. If the network or validation fails, it leaves the prior generated snapshot unchanged and exits non-zero.

- [ ] **Step 5: Merge generated articles without rewriting handcrafted articles**

Existing `articles` remain unchanged. Export `allArticles = mergeArticles(articles, generatedArticles)` and make blog index/detail, related links, article routes, sitemap, and prerender consume `allArticles`.

- [ ] **Step 6: Prove static SEO output**

Run: `npm test -- src/growth/content.test.ts src/data/articles.test.ts src/pages/BlogPages.test.tsx scripts/static-site.test.ts`  
Run: `npm run lint && npm run build`  
Expected: generated article HTML contains title, description, canonical `https://sinfogear.com/blog/<slug>`, JSON-LD, CTA, and no unapproved script markup.

- [ ] **Step 7: Commit in the app repository**

```bash
git add src/growth src/data/articles.ts src/data/articles.test.ts src/pages scripts package.json .env.example
git commit -m "feat: publish approved growth content on the site"
```

### Task 7: Add signed inquiry conversion ingestion to the growth engine

**Files:**
- Modify: `backend/apps/website/models.py`
- Create: `backend/apps/website/webhook.py`
- Modify: `backend/apps/website/views.py`
- Modify: `backend/apps/website/urls.py`
- Create: `backend/apps/website/migrations/0002_inboundconversion.py`
- Modify: `backend/apps/tracking/models.py`
- Create: `backend/apps/tracking/migrations/0004_conversion_attribution.py`
- Test: `backend/apps/website/tests/test_inquiry_webhook.py`
- Test: `backend/apps/website/tests/test_inquiry_idempotency.py`
- Test: `backend/apps/tracking/tests/test_conversion_attribution.py`

**Interfaces:**
- Consumes: signed `POST /api/v1/webhooks/website/inquiries`, tracking/short-link provenance, content ID, and product ID.
- Produces: `InboundConversion`, `verify_website_signature(body, timestamp, signature)`, and attribution link to content/platform/product.

- [ ] **Step 1: Write failing signature and replay tests**

```python
response = client.post(path, body, content_type="application/json", HTTP_X_SINOF_TIMESTAMP=old, HTTP_X_SINOF_SIGNATURE=sig)
assert response.status_code == 401

first = post_signed_inquiry(reference="SF-ABC12345")
second = post_signed_inquiry(reference="SF-ABC12345")
assert first.status_code == second.status_code == 202
assert InboundConversion.objects.count() == 1
```

- [ ] **Step 2: Run tests and verify route absence**

Run: `cd backend && pytest apps/website/tests/test_inquiry_webhook.py -q`  
Expected: FAIL with 404.

- [ ] **Step 3: Implement the allowlisted webhook payload**

Fields: `schema_version`, `reference`, `received_at`, `language`, `source_url`, `product_slug`, `quantity`, `country`, `contact`, `has_drawing`, `drawing_type`, `attribution`, `consent_version`, and `idempotency_key`. `attribution` contains only `utm_source`, `utm_medium`, `utm_campaign`, `utm_content`, `utm_term`, `content_id`, `product_id`, and `platform_code`.

- [ ] **Step 4: Implement HMAC verification and privacy bounds**

Use HMAC-SHA256 over `timestamp + "." + raw_body`, constant-time comparison, a five-minute time window, body-size limit, strict email/length validation, and idempotency uniqueness. Reject secrets and unknown personal-data fields.

- [ ] **Step 5: Implement attribution**

Match exact content/product/platform provenance when present. A missing or invalid ID does not reject a valid inquiry; store it as unattributed with an explanation. Never infer a person from an anonymous click.

- [ ] **Step 6: Run focused tests**

Run: `cd backend && pytest apps/website/tests apps/tracking/tests -q`  
Expected: PASS for signatures, replay, duplicates, malformed UTM, cross-organization IDs, and unattributed fallback.

- [ ] **Step 7: Commit**

```bash
git add backend/apps/website backend/apps/tracking
git commit -m "feat: ingest signed website inquiry conversions"
```

### Task 8: Send site inquiry conversions without changing email delivery semantics

**Files (`../app` worktree):**
- Create: `src/attribution/context.ts`
- Create: `src/attribution/context.test.ts`
- Create: `functions/lib/growthWebhook.ts`
- Create: `functions/lib/growthWebhook.test.ts`
- Modify: `src/components/InquiryForm.tsx`
- Modify: `src/lib/inquiry.ts`
- Modify: `src/services/inquiryApi.ts`
- Modify: `functions/lib/inquiryServer.ts`
- Modify: `functions/lib/inquiryServer.test.ts`
- Modify: `functions/api/inquiries.ts`
- Modify: `functions/api/inquiries.test.ts` 
- Modify: `functions/types.ts`
- Modify: `.env.example`

**Interfaces:**
- Consumes: browser URL/query context and Task 7 webhook using `GROWTH_INQUIRY_WEBHOOK_URL` and encrypted `GROWTH_INQUIRY_WEBHOOK_SECRET`.
- Produces: signed, idempotent conversion notification after successful Resend delivery.

- [ ] **Step 1: Write failing attribution allowlist tests**

```ts
expect(parseAttribution('?utm_source=linkedin&email=secret@example.com')).toEqual({
  utm_source: 'linkedin',
})
expect(parseAttribution('?content_id=not-a-uuid')).toEqual({})
```

- [ ] **Step 2: Implement bounded attribution capture**

Allow only the standard UTM fields, UUID content/product IDs, and an allowlisted platform code. Add hidden form fields from current URL; do not store personal data or query strings in localStorage.

- [ ] **Step 3: Write failing delivery-order tests**

```ts
expect(callOrder).toEqual(['resend', 'growth-webhook'])
expect(response.status).toBe(200)
expect(await response.json()).toMatchObject({ reference: 'SF-ABC12345' })
```

The fake growth webhook fails all attempts; the customer response still succeeds because email delivery completed.

- [ ] **Step 4: Implement signed webhook delivery**

After `sendInquiryEmail` succeeds, build the allowlisted payload, sign it, and attempt delivery up to three times with short bounded backoff using `context.waitUntil` when available. Extend `InquiryPagesContext` with an optional `waitUntil(promise)` field so local/unit environments can fall back to an awaited, bounded attempt. Log only reference/error code. Return the existing successful response regardless of webhook failure; never send a second email during webhook retries.

- [ ] **Step 5: Keep bot and attachment behavior unchanged**

Honeypot submissions send neither email nor webhook. Attachment bytes remain only in the email path; the webhook contains `has_drawing` and validated type, not file contents.

- [ ] **Step 6: Run site tests and build**

Run: `npm test -- src/attribution functions/lib/growthWebhook.test.ts functions/api/inquiries.test.ts functions/lib/inquiryServer.test.ts src/services/inquiryApi.test.ts`  
Run: `npm run lint && npm run build`  
Expected: PASS with fetch mocked; no request reaches Resend or a real growth endpoint.

- [ ] **Step 7: Commit in the app repository**

```bash
git add src/attribution src/components/InquiryForm.tsx src/lib/inquiry.ts src/services/inquiryApi.ts functions .env.example
git commit -m "feat: report attributed inquiries to the growth engine"
```

### Task 9: Upgrade analytics from clicks to explainable conversions

**Files:**
- Create: `backend/apps/website/analytics.py`
- Modify: `backend/apps/website/serializers.py`
- Modify: `backend/apps/website/views.py`
- Create: `backend/apps/website/tests/test_conversion_summary.py`
- Modify: `frontend/src/modules/analytics/api.ts`
- Modify: `frontend/src/modules/analytics/api.test.ts`
- Modify: `frontend/src/modules/analytics/AnalyticsPage.vue`
- Modify: `frontend/src/modules/analytics/AnalyticsPage.test.ts`

**Interfaces:**
- Consumes: click events, InboundConversion, publishing provenance, product/content/platform IDs.
- Produces: `GET /api/v1/analytics/conversions` and human-readable evidence-backed recommendations.

- [ ] **Step 1: Write failing conversion-summary tests**

```python
assert summary["totals"] == {"clicks": 20, "inquiries": 2, "crm_handoffs": 1}
assert summary["recommendations"][0]["sample_sufficient"] is False
```

- [ ] **Step 2: Implement exact aggregation without anonymous identity inference**

Group by date, platform, product, content, and market. Conversion rate is `attributed inquiries / attributed clicks`; always return numerator/denominator and exclude corrupted provenance using existing tracking consistency checks.

- [ ] **Step 3: Add recommendation guardrails**

Recommendations require a configured minimum sample and include date range, evidence metrics, confidence, and `sample_sufficient`. Below threshold, copy must say `样本不足，暂不调整策略`.

- [ ] **Step 4: Replace ID-heavy analytics UI with conclusions**

Default cards: effective product, effective platform, visits, inquiries, and AI next action. Detailed tables and raw IDs move to admin view. Every conclusion exposes `查看依据`.

- [ ] **Step 5: Run tests**

Run: `cd backend && pytest apps/website/tests/test_conversion_summary.py apps/tracking/tests -q`  
Run: `cd frontend && pnpm test -- AnalyticsPage.test.ts api.test.ts && pnpm typecheck`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/website frontend/src/modules/analytics
git commit -m "feat: explain website inquiry conversion performance"
```

## Phase 3 — Daily Evidence-Based Lead Discovery

### Task 10: Implement the lead-signal and immutable evidence domain

**Files:**
- Create: `backend/apps/leads/__init__.py`
- Create: `backend/apps/leads/apps.py`
- Create: `backend/apps/leads/models.py`
- Create: `backend/apps/leads/services.py`
- Create: `backend/apps/leads/serializers.py`
- Create: `backend/apps/leads/views.py`
- Create: `backend/apps/leads/urls.py`
- Create: `backend/apps/leads/migrations/0001_initial.py`
- Modify: `backend/config/settings.py`
- Modify: `backend/config/urls.py`
- Create: `backend/apps/identity/migrations/0012_lead_permissions.py`
- Test: `backend/apps/leads/tests/test_evidence_immutability.py`
- Test: `backend/apps/leads/tests/test_company_matching.py`
- Test: `backend/apps/leads/tests/test_lead_api.py`
- Modify: `backend/tests/test_openapi_contract.py`

**Interfaces:**
- Consumes: organization, product/ontology capability snapshots, assets/screenshots, jobs, AIRun, and approvals.
- Produces: `MonitoringTarget`, `SourceRun`, `SourceContent`, `SourceSignal`, `SourceEvidence`, `CompanyMatch`, `LeadCandidate`, `LeadInsight`, `LeadReview`, and REST APIs.

- [ ] **Step 1: Write failing evidence immutability tests**

```python
evidence = SourceEvidence.objects.create(
    organization=org,
    source_url="https://example.com/post/1",
    captured_at=now,
    content="Looking for replacement helical gears",
    content_hash=expected_hash,
    capture_method="PUBLIC_API",
)
evidence.content = "changed"
with pytest.raises(ValidationError):
    evidence.save()
```

- [ ] **Step 2: Implement normalized domain and state machines**

Monitoring target states: `DRAFT`, `ACTIVE`, `PAUSED`, `DISABLED`. Source run states: `QUEUED`, `RUNNING`, `PARTIAL_SUCCESS`, `SUCCEEDED`, `FAILED`, `CANCELLED`. Lead states: `DISCOVERED`, `ANALYZING`, `ANALYZED`, `REVIEWED`, `READY_FOR_HANDOFF`, `HANDED_OFF`, `IGNORED`.

- [ ] **Step 3: Implement deterministic deduplication and cautious company matching**

Exact source ID/URL/content hash deduplicates content. Exact normalized domain or verified registry ID may auto-link a company. Name similarity, logo, email-domain inference, or AI guesses create ranked `CompanyMatch` candidates and never auto-merge.

- [ ] **Step 4: Add tenant permissions and APIs**

Permissions: `leads.read`, `leads.manage`, `leads.review`, `leads.handoff`. APIs return evidence excerpts and safe source URLs but not connector secrets or private screenshot storage paths.

- [ ] **Step 5: Run tests and migration checks**

Run: `cd backend && pytest apps/leads/tests tests/test_openapi_contract.py -q`  
Run: `cd backend && python manage.py check && python manage.py makemigrations --check`  
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add backend/apps/leads backend/apps/identity backend/config backend/tests/test_openapi_contract.py
git commit -m "feat: add evidence based lead intelligence domain"
```

### Task 11: Add compliant source adapters and scheduled monitoring

**Files:**
- Create: `backend/integrations/sources/__init__.py`
- Create: `backend/integrations/sources/base.py`
- Create: `backend/integrations/sources/registry.py`
- Create: `backend/integrations/sources/rss.py`
- Create: `backend/integrations/sources/youtube.py`
- Create: `backend/integrations/sources/manual.py`
- Modify: `backend/apps/leads/services.py`
- Create: `backend/apps/leads/tasks.py`
- Test: `backend/integrations/sources/tests/test_source_contract.py`
- Test: `backend/integrations/sources/tests/test_rss_source.py`
- Test: `backend/integrations/sources/tests/test_youtube_source.py`
- Test: `backend/apps/leads/tests/test_monitoring_tasks.py`

**Interfaces:**
- Consumes: MonitoringTarget criteria/cursor and official/public source credentials.
- Produces: `SourceAdapter.fetch(target, cursor) -> SourceBatch`, normalized `SourceItem`, and daily `run_due_monitoring_targets` Celery task.

- [ ] **Step 1: Write failing adapter conformance tests**

```python
batch = adapter.fetch(target, cursor=None)
assert batch.next_cursor
assert all(item.external_id and item.url and item.published_at for item in batch.items)
assert batch.capability_snapshot["capture_method"] in {"PUBLIC_API", "PUBLIC_RSS", "MANUAL_IMPORT"}
```

- [ ] **Step 2: Implement a strict adapter interface**

`SourceItem` contains platform, external ID, canonical URL, author/account, published time, text, media metadata, parent content, and raw checksum. Adapter capabilities declare authentication mode, content types, pagination, comments, metrics, rate limits, and capture method.

- [ ] **Step 3: Implement RSS and manual imports first**

RSS allows HTTPS feeds, blocks private/network metadata addresses, bounds response size/time/items, and sanitizes HTML. Manual import validates URL/CSV/JSON/screenshot metadata and records `MANUAL_IMPORT` without pretending it was API-collected.

- [ ] **Step 4: Implement YouTube Data API adapter with fakes**

Use official YouTube API search/videos/commentThreads endpoints, incremental published time/page tokens, quota accounting, and explicit `commentsDisabled` partial success. Tests use recorded fixtures, never a real API key.

- [ ] **Step 5: Implement scheduled runs and backoff**

Celery beat finds due active targets. Each SourceRun saves capability snapshot, cursor before/after, quota usage, partial failures, and retry-after. Deduplicate before AI analysis; never run overlapping scans for one target.

- [ ] **Step 6: Run tests**

Run: `cd backend && pytest integrations/sources/tests apps/leads/tests/test_monitoring_tasks.py -q`  
Expected: PASS for SSRF, invalid feed, quota exhaustion, partial comments, duplicate cursor, and concurrent run lock.

- [ ] **Step 7: Commit**

```bash
git add backend/integrations/sources backend/apps/leads
git commit -m "feat: monitor compliant public lead sources"
```

### Task 12: Add explainable lead scoring, daily queue, and CRM handoff

**Files:**
- Create: `backend/apps/leads/scoring.py`
- Create: `backend/apps/leads/analysis.py`
- Modify: `backend/apps/leads/models.py`
- Modify: `backend/apps/leads/services.py`
- Modify: `backend/apps/leads/tasks.py`
- Create: `backend/apps/leads/migrations/0002_lead_handoff.py`
- Test: `backend/apps/leads/tests/test_lead_scoring.py`
- Test: `backend/apps/leads/tests/test_lead_analysis.py`
- Test: `backend/apps/leads/tests/test_lead_handoff.py`

**Interfaces:**
- Consumes: SourceEvidence, company candidates, product/ontology capability evidence, and AI provider.
- Produces: `LeadScoreBreakdown`, versioned LeadInsight, OutreachDraft, and evidence-complete LeadHandoff JSON/CSV/Mock CRM payload.

- [ ] **Step 1: Write failing deterministic scoring tests**

```python
score = calculate_lead_score(
    icp_fit=90, intent=95, recency=100, authority=60, evidence_coverage=100, risk=10
)
assert score.total == 88
assert score.tier == "HIGH"
```

- [ ] **Step 2: Implement versioned scoring rules**

Persist each component, weights, rule version, total, tier, and explanation. AI extracts structured facts and citations; deterministic code calculates the final score. Missing evidence caps tier below `HIGH` regardless of model output.

- [ ] **Step 3: Write failing evidence-complete handoff tests**

```python
payload = build_lead_handoff(candidate.id, reviewer)
assert payload["candidate_id"] == str(candidate.id)
assert payload["source_evidence"][0]["url"]
assert payload["source_evidence"][0]["content"]
```

- [ ] **Step 4: Implement human review and handoff**

Only `REVIEWED` leads with at least one immutable SourceEvidence and approved capability evidence may become `READY_FOR_HANDOFF`. `OutreachDraft` is a suggestion with Chinese explanation; no service sends it. Handoff supports JSON, CSV, and existing Mock CRM connector.

- [ ] **Step 5: Implement daily analysis queue**

After source ingestion, enqueue bounded batches, retain failed items for retry, and generate a daily summary of counts, top opportunities, evidence gaps, and costs. Preserve original AI output after corrections.

- [ ] **Step 6: Run tests**

Run: `cd backend && pytest apps/leads/tests apps/ai/tests apps/jobs/tests -q`  
Expected: PASS for low evidence, ambiguous company, human correction, duplicate handoff, and connector failure.

- [ ] **Step 7: Commit**

```bash
git add backend/apps/leads
git commit -m "feat: score and hand off evidence backed opportunities"
```

### Task 13: Build the simple customer-opportunity interface

**Files:**
- Create: `frontend/src/modules/opportunities/api.ts`
- Create: `frontend/src/modules/opportunities/api.test.ts`
- Create: `frontend/src/modules/opportunities/OpportunitiesPage.vue`
- Create: `frontend/src/modules/opportunities/OpportunitiesPage.test.ts`
- Create: `frontend/src/modules/opportunities/EvidenceDialog.vue`
- Create: `frontend/src/modules/opportunities/EvidenceDialog.test.ts`
- Modify: `frontend/src/app/router.ts`
- Modify: `frontend/src/App.vue`
- Modify: `frontend/src/modules/today/TodayPage.vue`

**Interfaces:**
- Consumes: lead list/detail/review/handoff APIs from Tasks 10–12.
- Produces: `/opportunities` ordinary-user queue and evidence dialog.

- [ ] **Step 1: Write failing opportunity card tests**

```ts
expect(await screen.findByText('今天发现 3 个值得关注的客户')).toBeVisible()
expect(screen.getByRole('button', { name: '交给CRM' })).toBeVisible()
expect(screen.getByRole('button', { name: '查看依据' })).toBeVisible()
expect(screen.queryByText('SourceSignal')).not.toBeInTheDocument()
```

- [ ] **Step 2: Implement user-language queue**

Default sort: HIGH tier, newest evidence, then score. Cards show company, country, likely requirement, one-sentence reason, source platform/time, confidence, and actions. Filters use human terms: `优先跟进`, `继续观察`, `已处理`, not internal states.

- [ ] **Step 3: Implement evidence and correction flow**

Evidence dialog shows original content, safe source link, capture time/method, company-match reasoning, capability evidence, and AI uncertainty. `判断不准确` captures structured correction without editing original evidence.

- [ ] **Step 4: Implement CRM confirmation**

Clicking `交给CRM` opens a concise confirmation with company, insight, evidence count, and suggested next question. It never sends a message to the lead.

- [ ] **Step 5: Run frontend tests**

Run: `cd frontend && pnpm test -- OpportunitiesPage.test.ts EvidenceDialog.test.ts TodayPage.test.ts`  
Run: `cd frontend && pnpm typecheck && pnpm lint && pnpm build`  
Expected: PASS with keyboard dialog focus, accessible labels, empty/error/loading states, and mobile layout.

- [ ] **Step 6: Commit**

```bash
git add frontend/src/modules/opportunities frontend/src/modules/today frontend/src/app/router.ts frontend/src/App.vue
git commit -m "feat: show simple evidence backed customer opportunities"
```

## Phase 4 — Cross-Repository Acceptance and Controlled Expansion

### Task 14: Add end-to-end acceptance without production side effects

**Files:**
- Create: `frontend/e2e/ai-growth-loop.spec.ts`
- Modify: `frontend/e2e/launcher.mjs`
- Create: `backend/apps/common/management/commands/seed_growth_loop.py`
- Create: `backend/apps/common/tests/test_seed_growth_loop.py`
- Create (`../app` worktree): `e2e/growth-conversion.spec.ts` 
- Create (`../app` worktree): `e2e/fixtures/growth-feed.json` 
- Create (`../app` worktree): `playwright.config.ts`
- Modify (`../app` worktree): `package.json`
- Create: `docs/ai-growth-loop-acceptance.md`
- Modify: `docs/architecture.md`
- Modify (`../app` worktree): `README.md`
- Modify (`../app` worktree): `PROJECT_STRUCTURE.md`

**Interfaces:**
- Consumes: all prior public APIs and site build/inquiry interfaces.
- Produces: repeatable local acceptance with fake AI, fake platform connectors, fake Resend, and fake signed webhooks.

- [ ] **Step 1: Add deterministic seed data**

Seed one organization, admin, ordinary operator, approved helical-gear product/evidence, product manual asset, fake platform accounts, one source signal, and Mock CRM. The command must refuse non-test settings unless `--allow-non-test` is explicitly provided.

- [ ] **Step 2: Write the growth-engine browser journey**

```ts
test('manual to approved bilingual promotion and lead handoff', async ({ page }) => {
  await page.goto('/promotion')
  await page.setInputFiles('input[type=file]', 'e2e/fixtures/helical-gear-manual.pdf')
  await page.getByLabel('推广目标（可选）').fill('推广到德国包装机械行业')
  await page.getByRole('button', { name: '让AI制定方案' }).click()
  await expect(page.getByText('等待你批准')).toBeVisible()
  await page.getByRole('button', { name: '批准执行' }).click()
  await expect(page.getByText('中文对照')).toBeVisible()
})
```

- [ ] **Step 3: Write the site publication and inquiry test**

Add `@playwright/test` to the independent-site development dependencies and a web-server-based `playwright.config.ts`. Use a fixture feed, build the site, open the generated blog page with UTM/content/product parameters, submit to a fake inquiry endpoint, and assert exactly one fake Resend call plus one correctly signed conversion payload. Never reference the production Resend key or production webhook.

- [ ] **Step 4: Add failure-path journeys**

Cover AI unavailable/retry, high-risk fact confirmation, platform not authorized/publish package fallback, website feed invalid/previous snapshot retained, webhook unavailable/customer still sees success, ambiguous company/no auto-merge, and low-evidence lead/no CRM handoff.

- [ ] **Step 5: Run the complete growth-engine gates**

Run: `cd backend && pytest -q && ruff check . && python manage.py check && python manage.py makemigrations --check`  
Run: `cd frontend && pnpm test --run && pnpm typecheck && pnpm lint && pnpm build && pnpm test:e2e`  
Expected: all PASS.

- [ ] **Step 6: Run the complete independent-site gates**

Run: `npm test && npm run lint && npm run build && npm run test:e2e`  
Expected: all PASS; generated canonical remains `https://sinfogear.com`; no DNS/mail values changed.

- [ ] **Step 7: Run security and side-effect audit**

Search both diffs for `RESEND_API_KEY`, platform passwords/cookies, real access tokens, `sinofgear.com` canonical changes, `sinoforce.net` DNS changes, automatic send calls, and raw AI secrets. Confirm only example variable names/fakes are present.

- [ ] **Step 8: Write acceptance report**

Record exact commands, pass/fail counts, screenshots of the three ordinary-user flows, fake connector proof, known platform-approval limitations, and rollback instructions for each repository.

- [ ] **Step 9: Commit separately in each repository**

Growth engine:

```bash
git add frontend/e2e backend/apps/common docs
git commit -m "test: verify the ai growth loop end to end"
```

Independent site:

```bash
git add e2e playwright.config.ts package.json package-lock.json README.md PROJECT_STRUCTURE.md
git commit -m "test: verify attributed growth site conversion"
```

### Task 15: Prepare—but do not activate—official connector expansion

**Files:**
- Create: `docs/platform-connector-readiness.md`
- Create: `backend/integrations/platforms/conformance.py`
- Create: `backend/integrations/platforms/tests/test_connector_conformance.py`
- Modify: `backend/apps/platforms/capabilities.py`
- Modify: `frontend/src/modules/admin/AdminHomePage.vue`

**Interfaces:**
- Consumes: existing platform models and official developer-application facts supplied by an administrator.
- Produces: connector readiness records and a conformance suite; it does not activate a connector without approved credentials/scopes.

- [ ] **Step 1: Define readiness schema**

For LinkedIn, Facebook, Instagram, YouTube, TikTok, Pinterest, X, and independent-site publishing, record official documentation URL, application ID presence, OAuth redirect URI, approved scopes, publish/read/comment/metrics capability, quota, review state, data-retention rule, and tested-at timestamp.

- [ ] **Step 2: Add failing conformance tests**

Every enabled connector must prove capability snapshot, OAuth/token redaction, idempotent publish, rate-limit handling, safe retry, payload validation, and no password/cookie fields. A connector missing approved scopes remains `CONFIGURATION_REQUIRED`.

- [ ] **Step 3: Implement readiness-only admin view**

Show `可连接`, `等待平台审核`, `仅支持发布包`, or `未配置`; do not show nonfunctional “连接成功” demos. User input of an account name starts official authorization guidance but never stores a password.

- [ ] **Step 4: Run conformance tests**

Run: `cd backend && pytest integrations/platforms/tests apps/platforms/tests -q`  
Run: `cd frontend && pnpm test -- AdminHomePage.test.ts && pnpm typecheck`  
Expected: mock connectors PASS; unconfigured real connectors remain disabled and explicit.

- [ ] **Step 5: Commit**

```bash
git add docs/platform-connector-readiness.md backend/integrations/platforms backend/apps/platforms frontend/src/modules/admin
git commit -m "chore: gate official platform connectors by readiness"
```

## Execution Checkpoints

1. **After Phase 1:** user can upload/select a product, enter one optional goal, receive a bilingual proposal, inspect evidence, and approve it without using the old content wizard.
2. **After Phase 2:** approved content appears in a locally built independent site; a fake inquiry returns signed attribution to the growth engine without changing email semantics.
3. **After Phase 3:** a scheduled public-source scan produces evidence-backed, deduplicated opportunities and allows human CRM handoff without automatic outreach.
4. **After Phase 4:** both repositories pass complete unit, integration, build, security, and browser acceptance; real platform connectors remain disabled until official credentials and scopes are approved.

At each checkpoint, stop for user acceptance. Do not begin the next phase merely because lower-level tests pass; demonstrate the ordinary-user outcome in the browser first.

