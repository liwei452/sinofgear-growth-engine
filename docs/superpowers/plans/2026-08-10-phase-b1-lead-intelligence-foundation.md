# Phase B1 Lead Intelligence Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a usable, auditable lead-intelligence foundation that accepts user-scoped public signals through URL, screenshot, CSV, JSON, or paste; preserves immutable evidence; scores enterprise lead candidates; and requires human review before any later handoff.

**Architecture:** Extend the existing Django modular monolith with a `sources` bounded context for imports and immutable public evidence and a `leads` bounded context for candidate analysis and human review. Reuse the existing organization permissions, private asset storage, `Job`/Celery lifecycle, `PromptVersion`/`AIRun` audit trail, ontology snapshots, recoverable API errors, generated OpenAPI client, and Vue Query UI conventions. B1 deliberately stops at reviewed candidates: company enrichment, outreach drafts, CRM handoff, live platform connectors, AIEO, and Market Intelligence each receive a separate implementation plan.

**Tech Stack:** Python 3.12–3.13, Django 5.2, Django REST Framework 3.16, PostgreSQL, Celery 5.5, Redis 6, MinIO/private asset storage, jsonschema 4.23, Vue 3.5, TypeScript 5.8, TanStack Vue Query 5, Vitest 3, Playwright 1.62.

## Global Constraints

- Only ingest public data inside a scope explicitly selected or imported by the user; do not add unattended browser login, password/cookie/captcha storage, anti-bot bypass, private-message scraping, or hidden-contact discovery.
- Do not send outreach automatically and do not add CRM lifecycle, quoting, pipeline, deal, or sales-performance behavior.
- `LeadCandidate` is enterprise-oriented; a public account remains a source actor/evidence reference, not a verified employee or a CRM contact.
- `SourceEvidence.original_text`, source identity, capture method, and content hash are immutable after creation; translations and AI interpretations are derived versioned records.
- Every AI conclusion must reference at least one visible `SourceEvidence`, a published `PromptVersion`, an `AIRun`, and a frozen ontology snapshot.
- Lead score weights are fixed for B1: intent 30, company fit 25, requirement specificity 20, capability fit 15, recency/urgency 10.
- A score of 80–100 enters the high-value queue only when the evidence gates also pass; a numeric score alone never triggers outreach or automatic rejection.
- Unconfirmed low-value raw records default to 30-day retention; evidence referenced by a confirmed candidate is protected from cleanup.
- All queries and service writes are scoped to the active organization; cross-organization object references return the existing safe 403/404 error contract.
- Mutating API failures use the existing `code`, `message`, and `recovery_action` JSON envelope.
- File imports allow partial success, report row numbers and concrete recovery actions, and remain idempotent under retries.
- UI language is plain Chinese, beginner-friendly, keyboard accessible, responsive, and based on the existing SinofGear blue design tokens; no visual redesign is included.
- Use TDD, run the narrow test after every change, run the complete backend/frontend verification before completion, and commit each task independently.

## Delivery Boundary and File Map

### Created backend files

- `backend/apps/sources/apps.py` — Django registration for source ingestion.
- `backend/apps/sources/models.py` — monitoring target, ingestion batch/row, source content/signal, and immutable evidence models.
- `backend/apps/sources/services.py` — normalization, hashing, idempotent ingestion, evidence creation, and retention operations.
- `backend/apps/sources/importers.py` — strict CSV, JSON, paste, URL, and screenshot payload adapters.
- `backend/apps/sources/serializers.py` — request/response contracts.
- `backend/apps/sources/views.py` — organization-scoped collection and import endpoints.
- `backend/apps/sources/urls.py` — `/monitoring-targets`, `/ingestion-batches`, `/source-*` routes.
- `backend/apps/sources/tasks.py` — Celery import and retention workers.
- `backend/apps/sources/migrations/0001_initial.py` — B1 source schema.
- `backend/apps/sources/tests/` — domain, API, idempotency, permissions, import, retention, and task tests.
- `backend/apps/leads/apps.py` — Django registration for lead intelligence.
- `backend/apps/leads/models.py` — candidate, immutable insight version, evidence link, and review models.
- `backend/apps/leads/scoring.py` — deterministic score calculation and evidence gates.
- `backend/apps/leads/schemas.py` — Lead analysis JSON Schema and frozen input validation.
- `backend/apps/leads/services.py` — candidate creation, analysis snapshot, result persistence, and review transitions.
- `backend/apps/leads/orchestration.py` — audited AI execution for `LEAD_ANALYZE` jobs.
- `backend/apps/leads/serializers.py` — candidate, insight, evidence, and review contracts.
- `backend/apps/leads/views.py` — queue/detail/analyze/review endpoints.
- `backend/apps/leads/urls.py` — `/lead-candidates`, `/lead-insights`, `/lead-reviews` routes.
- `backend/apps/leads/tasks.py` — Celery analysis worker.
- `backend/apps/leads/migrations/0001_initial.py` — B1 lead schema.
- `backend/apps/leads/tests/fixtures/lead_evaluation.json` — at least 100 labeled Chinese/English industrial examples.
- `backend/apps/leads/tests/` — scoring, state, audit, API, isolation, and evaluation tests.

### Modified backend files

- `backend/apps/knowledge/models.py`, `relation_rules.py`, `serializers.py`, and seed/tests — add `CAPABILITY` and `REQUIREMENT` without changing `PROCESS` semantics.
- `backend/apps/catalog/models.py` and related tests/UI types — allow approved `CAPABILITY` links in a new product role.
- `backend/apps/identity/permissions.py` and `backend/apps/identity/migrations/0011_refresh_phase_b1_permissions.py` — add the six approved permission codes and role grants.
- `backend/apps/jobs/models.py`, migration, serializers/tests — add B1 job types.
- `backend/apps/ai/orchestration.py` — dispatch-compatible purpose mapping without weakening content generation validation.
- `backend/config/settings.py` and `backend/config/urls.py` — register the two apps and routes.
- `backend/apps/common/management/commands/seed_phase_b1.py` — provide local B1 demo data without changing production data.
- `backend/tests/test_openapi.py`, `test_openapi_contract.py`, and `test_project_layout.py` — enforce public contracts and project boundaries.

### Created frontend files

- `frontend/src/modules/leads/api.ts` and `api.test.ts` — typed B1 API adapter and safe cursor handling.
- `frontend/src/modules/leads/LeadRadarPage.vue` and test — candidate queue and guided empty state.
- `frontend/src/modules/leads/SourceImportDialog.vue` and test — five-mode import wizard with row error recovery.
- `frontend/src/modules/leads/LeadDetailDialog.vue` and test — evidence, score explanation, AI audit summary, and review action.
- `frontend/e2e/phase-b1-lead-intelligence.spec.ts` — user-visible B1 acceptance path.

### Modified frontend files

- `frontend/src/app/router.ts`, `frontend/src/main.ts`, and `frontend/src/app/AppShell.vue` — register and navigate to `/lead-radar`.
- `frontend/src/modules/knowledge/api.ts`, `KnowledgeConceptDialog.vue`, and `KnowledgeLibraryPage.vue` with tests — expose the two new ontology concept types.
- `frontend/src/modules/products/api.ts`, `ProductFormDialog.vue`, and `ProductLibraryPage.vue` with tests — expose the new capability product role.
- `frontend/src/styles/tokens.css` only if an existing semantic token cannot express evidence/score states; do not introduce raw brand colors in components.
- `frontend/src/api/generated/schema.ts` — regenerate from the verified OpenAPI schema, never hand-edit.
- `frontend/e2e/launcher.mjs` — include the B1 test only when the launcher requires an explicit spec list.

---

### Task 1: Extend the ontology with capability and requirement concepts

**Files:**
- Modify: `backend/apps/knowledge/models.py`
- Modify: `backend/apps/knowledge/relation_rules.py`
- Modify: `backend/apps/knowledge/management/commands/seed_gear_ontology.py`
- Modify: `backend/apps/catalog/models.py`
- Create: `backend/apps/knowledge/migrations/0004_capability_requirement_types.py`
- Create: `backend/apps/catalog/migrations/0004_add_capability_role.py`
- Test: `backend/apps/knowledge/tests/test_phase_b_ontology.py`
- Test: `backend/apps/catalog/tests/test_product_concepts.py`
- Modify: `frontend/src/modules/knowledge/api.ts`
- Modify: `frontend/src/modules/knowledge/KnowledgeConceptDialog.vue`
- Modify: `frontend/src/modules/knowledge/KnowledgeLibraryPage.vue`
- Modify: `frontend/src/modules/products/api.ts`
- Modify: `frontend/src/modules/products/ProductFormDialog.vue`
- Modify: `frontend/src/modules/products/ProductLibraryPage.vue`
- Test: `frontend/src/modules/knowledge/KnowledgeConceptDialog.test.ts`
- Test: `frontend/src/modules/knowledge/KnowledgeLibraryPage.test.ts`
- Test: `frontend/src/modules/products/ProductFormDialog.test.ts`
- Test: `frontend/src/modules/products/ProductLibraryPage.test.ts`

**Interfaces:**
- Consumes: existing `KnowledgeConcept`, `KnowledgeRelation`, graph-lock, approval, and snapshot services.
- Produces: `KnowledgeConcept.ConceptType.CAPABILITY`, `KnowledgeConcept.ConceptType.REQUIREMENT`, and `ProductConceptLink.Role.CAPABILITY`; approved capability codes become legal Lead analysis references.

- [ ] **Step 1: Write failing ontology and product-link tests**

```python
@pytest.mark.django_db
def test_capability_and_requirement_are_distinct_from_process(organization):
    capability = create_test_knowledge(KnowledgeConcept,
        scope=KnowledgeConcept.Scope.ORGANIZATION,
        organization=organization, code="CAP-GEAR-GRINDING",
        concept_type=KnowledgeConcept.ConceptType.CAPABILITY,
        label_zh="磨齿能力", label_en="Gear grinding capability",
        status=KnowledgeConcept.Status.APPROVED,
    )
    requirement = create_test_knowledge(KnowledgeConcept,
        scope=KnowledgeConcept.Scope.ORGANIZATION,
        organization=organization, code="REQ-DIN6",
        concept_type=KnowledgeConcept.ConceptType.REQUIREMENT,
        label_zh="DIN 6 精度要求", label_en="DIN 6 accuracy required",
        status=KnowledgeConcept.Status.APPROVED,
    )
    assert capability.concept_type == "CAPABILITY"
    assert requirement.concept_type == "REQUIREMENT"
    assert capability.concept_type != KnowledgeConcept.ConceptType.PROCESS

@pytest.mark.django_db
def test_product_accepts_only_approved_capability_link(product, approved_capability):
    link = ProductConceptLink(
        organization=product.organization, product=product,
        role=ProductConceptLink.Role.CAPABILITY, concept=approved_capability,
    )
    link.save()
    assert link.concept_id == approved_capability.id
```

- [ ] **Step 2: Run the narrow tests and confirm they fail because the enum/role does not exist**

Run: `cd backend && pytest apps/knowledge/tests/test_phase_b_ontology.py apps/catalog/tests/test_product_concepts.py -q`

Expected: FAIL mentioning missing `CAPABILITY` or `REQUIREMENT` choices.

- [ ] **Step 3: Add the exact enum and compatibility rules**

```python
class ConceptType(models.TextChoices):
    # keep every existing value unchanged
    CAPABILITY = "CAPABILITY", "Capability"
    REQUIREMENT = "REQUIREMENT", "Requirement"

class Role(models.TextChoices):
    # keep every existing value unchanged
    CAPABILITY = "CAPABILITY", "Capability"

ROLE_CONCEPT_TYPES[ProductConceptLink.Role.CAPABILITY] = frozenset(
    {KnowledgeConcept.ConceptType.CAPABILITY}
)
```

Add only explicit relations required by B1: product type/capability `SATISFIES` requirement, capability `SUPPORTED_BY` knowledge evidence through the existing evidence association, and industry/application `HAS_REQUIREMENT` requirement. Reject reverse or cross-organization relations through the existing validators.

- [ ] **Step 4: Generate and inspect the migration, then update seed data with evidence-backed examples**

Run: `cd backend && python manage.py makemigrations knowledge catalog`

Seed exact starter concepts such as `CAP-GEAR-GRINDING`, `CAP-HEAT-TREATMENT`, `REQ-DIN6`, `REQ-SMALL-BATCH`, and `REQ-URGENT-REPLACEMENT`; seed capability claims only when an existing `KnowledgeEvidence` supports them.

- [ ] **Step 5: Run ontology, catalog, snapshot, and seed tests**

Run: `cd backend && pytest apps/knowledge/tests apps/catalog/tests/test_product_concepts.py apps/catalog/tests/test_product_snapshots.py -q`

Expected: PASS; existing `PROCESS` links and snapshots remain unchanged.

- [ ] **Step 6: Extend the existing typed knowledge/product controls**

Add `CAPABILITY` and `REQUIREMENT` to `ConceptType` and the two Chinese labels to the knowledge screens. Add `CAPABILITY` to `ProductConceptRole`, map only `CAPABILITY: "CAPABILITY"` in `roleForType`, and label the product group `制造能力`; do not map `REQUIREMENT` directly onto products.

Run: `cd frontend && pnpm test -- --run src/modules/knowledge/KnowledgeConceptDialog.test.ts src/modules/knowledge/KnowledgeLibraryPage.test.ts src/modules/products/ProductFormDialog.test.ts src/modules/products/ProductLibraryPage.test.ts && pnpm typecheck`

- [ ] **Step 7: Commit the ontology slice**

```bash
git add backend/apps/knowledge backend/apps/catalog frontend/src/modules/knowledge frontend/src/modules/products
git commit -m "feat: extend ontology for lead requirements"
```

### Task 2: Register B1 apps, permissions, and asynchronous job types

**Files:**
- Create: `backend/apps/sources/__init__.py`
- Create: `backend/apps/sources/apps.py`
- Create: `backend/apps/leads/__init__.py`
- Create: `backend/apps/leads/apps.py`
- Modify: `backend/config/settings.py`
- Modify: `backend/config/urls.py`
- Modify: `backend/apps/identity/permissions.py`
- Create: `backend/apps/identity/migrations/0011_refresh_phase_b1_permissions.py`
- Modify: `backend/apps/jobs/models.py`
- Create: `backend/apps/jobs/migrations/0002_add_phase_b1_job_types.py`
- Test: `backend/apps/identity/tests/test_phase_b1_permissions.py`
- Test: `backend/apps/jobs/tests/test_job_service.py`
- Test: `backend/tests/test_project_layout.py`

**Interfaces:**
- Consumes: `HasOrganizationPermission`, built-in role permission JSON, and `JobService.create(...)`.
- Produces: `CanReadSources`, `CanManageSources`, `CanReadLeads`, `CanAnalyzeLeads`, `CanReviewLeads`, `CanHandoffLeads`; B1 uses the first five and reserves `leads.handoff` for the B2 plan.

- [ ] **Step 1: Write failing permission and job-type tests**

```python
def test_phase_b1_permission_codes_are_stable():
    assert {code.value for code in PermissionCode if code.value.startswith(("sources.", "leads."))} == {
        "sources.read", "sources.manage", "leads.read",
        "leads.analyze", "leads.review", "leads.handoff",
    }

@pytest.mark.django_db
def test_source_import_job_is_idempotent(organization, user):
    first = JobService.create(
        organization=organization, job_type=Job.Type.SOURCE_IMPORT,
        input_snapshot={"batch_id": "batch-1"}, idempotency_key="import-1", created_by=user,
    )
    second = JobService.create(
        organization=organization, job_type=Job.Type.SOURCE_IMPORT,
        input_snapshot={"batch_id": "batch-1"}, idempotency_key="import-1", created_by=user,
    )
    assert second.id == first.id
```

- [ ] **Step 2: Run tests and confirm missing enum/app failures**

Run: `cd backend && pytest apps/identity/tests/test_phase_b1_permissions.py apps/jobs/tests/test_job_service.py tests/test_project_layout.py -q`

- [ ] **Step 3: Add exact permission and job enums**

```python
class PermissionCode(StrEnum):
    SOURCES_READ = "sources.read"
    SOURCES_MANAGE = "sources.manage"
    LEADS_READ = "leads.read"
    LEADS_ANALYZE = "leads.analyze"
    LEADS_REVIEW = "leads.review"
    LEADS_HANDOFF = "leads.handoff"

class Type(models.TextChoices):
    CONTENT_GENERATE = "CONTENT_GENERATE", "Content generate"
    SOURCE_IMPORT = "SOURCE_IMPORT", "Source import"
    SOURCE_NORMALIZE = "SOURCE_NORMALIZE", "Source normalize"
    EVIDENCE_EXTRACT = "EVIDENCE_EXTRACT", "Evidence extract"
    LEAD_ANALYZE = "LEAD_ANALYZE", "Lead analyze"
    RETENTION_CLEANUP = "RETENTION_CLEANUP", "Retention cleanup"
```

Grant read permissions to viewer-like roles, manage/analyze to operator-like roles, review to reviewer/admin roles, and handoff only to roles that already hold the strongest approval/export authority. Keep the migration deterministic and reversible using the existing role-permission migration pattern.

- [ ] **Step 4: Register apps and empty URL modules without exposing endpoints yet**

Add `apps.sources.apps.SourcesConfig` and `apps.leads.apps.LeadsConfig` after shared infrastructure apps, then include both URL modules under `/api/v1/`.

- [ ] **Step 5: Generate/inspect migrations and run the focused suites**

Run: `cd backend && python manage.py makemigrations --check --dry-run && pytest apps/identity/tests apps/jobs/tests tests/test_project_layout.py -q`

Expected: PASS and no uncommitted model changes.

- [ ] **Step 6: Commit the platform wiring**

```bash
git add backend/apps/sources backend/apps/leads backend/apps/identity backend/apps/jobs backend/config
git commit -m "feat: register phase b1 permissions and jobs"
```

### Task 3: Create the source and immutable evidence domain

**Files:**
- Create: `backend/apps/sources/models.py`
- Create: `backend/apps/sources/services.py`
- Create: `backend/apps/sources/migrations/0001_initial.py`
- Test: `backend/apps/sources/tests/conftest.py`
- Test: `backend/apps/sources/tests/test_source_models.py`
- Test: `backend/apps/sources/tests/test_evidence_immutability.py`
- Test: `backend/apps/sources/tests/test_source_isolation.py`

**Interfaces:**
- Consumes: `OrganizationScopedModel`, `Asset`, organization/user foreign keys.
- Produces: `MonitoringTarget`, `IngestionBatch`, `IngestionRow`, `SourceContent`, `SourceSignal`, `SourceEvidence`, `EvidenceService.create(...)`, and `normalize_source_url(url: str) -> str`.

- [ ] **Step 1: Write failing model invariants**

```python
@pytest.mark.django_db
def test_evidence_service_deduplicates_and_direct_update_is_rejected(signal, user):
    kwargs = dict(
        signal=signal, original_text="We need 200 replacement helical gears.",
        source_url="https://example.com/posts/42", platform="MANUAL",
        collection_method="PASTE", public_published_at=None, created_by=user,
    )
    first = EvidenceService.create(**kwargs)
    second = EvidenceService.create(**kwargs)
    assert second.id == first.id
    with pytest.raises(ValidationError):
        SourceEvidence.objects.filter(pk=first.pk).update(original_text="changed")

@pytest.mark.django_db
def test_source_content_cannot_reference_another_organization(target, other_organization):
    content = SourceContent(
        organization=other_organization, monitoring_target=target,
        platform="MANUAL", canonical_url="https://example.com/post", content_hash="a" * 64,
    )
    with pytest.raises(ValidationError):
        content.full_clean()
```

- [ ] **Step 2: Run tests and verify missing model/service failures**

Run: `cd backend && pytest apps/sources/tests/test_source_models.py apps/sources/tests/test_evidence_immutability.py apps/sources/tests/test_source_isolation.py -q`

- [ ] **Step 3: Implement focused models and database constraints**

Use UUID primary keys and organization FKs throughout. Required enums/fields:

```python
class MonitoringTarget(OrganizationScopedModel):
    class TargetType(models.TextChoices):
        ACCOUNT = "ACCOUNT", "Account"
        POST = "POST", "Post"
        KEYWORD = "KEYWORD", "Keyword"
        INDUSTRY_PAGE = "INDUSTRY_PAGE", "Industry page"
    class CollectionMode(models.TextChoices):
        MANUAL_URL = "MANUAL_URL", "Manual URL"
        SCREENSHOT = "SCREENSHOT", "Screenshot"
        FILE_IMPORT = "FILE_IMPORT", "File import"
        PASTE = "PASTE", "Paste"

class SourceSignal(OrganizationScopedModel):
    class SignalType(models.TextChoices):
        COMMENT = "COMMENT", "Comment"
        POST_AUTHOR = "POST_AUTHOR", "Post author"
        CHANNEL_OWNER = "CHANNEL_OWNER", "Channel owner"
        PROFILE_MATCH = "PROFILE_MATCH", "Profile match"
        MENTION = "MENTION", "Mention"
        HASHTAG_MATCH = "HASHTAG_MATCH", "Hashtag match"
```

`IngestionBatch` stores `status`, counts, `row_errors`, `idempotency_key`, job FK, and timestamps. `IngestionRow` stores immutable normalized row input and outcome. `SourceContent` stores canonical URL/text metadata and a SHA-256 content hash. `SourceEvidence` stores the spec fields plus optional private screenshot/import `Asset` references and `retention_class` (`TRANSIENT_30D`, `CONFIRMED`, `HANDOFF_PROTECTED`). Add unique constraints on organization/platform/external ID where present and on organization/content hash/source URL when external ID is absent.

- [ ] **Step 4: Implement guarded evidence writes and deterministic hashing**

```python
def evidence_fingerprint(*, original_text: str, source_url: str, platform: str) -> str:
    canonical = "\n".join((platform.strip().upper(), normalize_source_url(source_url), " ".join(original_text.split())))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()

@transaction.atomic
def create(*, signal, original_text, source_url, platform, collection_method,
           public_published_at, created_by, screenshot_asset=None, import_asset=None):
    fingerprint = evidence_fingerprint(
        original_text=original_text, source_url=source_url, platform=platform,
    )
    with evidence_service_writes():
        evidence, _ = SourceEvidence.objects.get_or_create(
            organization=signal.organization, content_hash=fingerprint,
            defaults={"source_signal": signal, "original_text": original_text,
                      "source_url": normalize_source_url(source_url), "platform": platform,
                      "collection_method": collection_method, "created_by": created_by,
                      "screenshot_asset": screenshot_asset, "import_asset": import_asset,
                      "retention_class": SourceEvidence.RetentionClass.TRANSIENT_30D},
        )
    return evidence
```

- [ ] **Step 5: Generate migration and test constraints against SQLite test settings and PostgreSQL compose**

Run: `cd backend && python manage.py makemigrations sources && pytest apps/sources/tests -q`

Expected: PASS; direct save/update/delete of committed evidence fails, service idempotency passes, and organization mismatch fails.

- [ ] **Step 6: Commit the source domain**

```bash
git add backend/apps/sources
git commit -m "feat: add immutable public source evidence"
```

### Task 4: Build strict multi-mode import adapters and idempotent ingestion

**Files:**
- Create: `backend/apps/sources/importers.py`
- Modify: `backend/apps/sources/services.py`
- Create: `backend/apps/sources/tasks.py`
- Test: `backend/apps/sources/tests/test_importers.py`
- Test: `backend/apps/sources/tests/test_ingestion_service.py`
- Test: `backend/apps/sources/tests/test_source_tasks.py`

**Interfaces:**
- Consumes: `IngestionBatch`, `IngestionRow`, `EvidenceService`, private `Asset`, `JobService`.
- Produces: `ImportRow(platform, source_url, signal_type, original_text, author_name, published_at, screenshot_asset_id)`, `parse_import(payload, source_type) -> list[ImportRow]`, `IngestionService.run(batch_id, claim_token) -> IngestionBatch`, and `execute_source_import(job_id: str, batch_id: str)`.

- [ ] **Step 1: Write failing adapter tests for all five B1 modes and partial errors**

```python
@pytest.mark.parametrize("source_type,payload", [
    ("URL", {"source_url": "https://example.com/p/1", "original_text": "Need gear quote"}),
    ("SCREENSHOT", {"source_url": "https://example.com/p/2", "original_text": "200 pcs", "screenshot_asset_id": "00000000-0000-0000-0000-000000000001"}),
    ("JSON", {"rows": [{"source_url": "https://example.com/p/3", "original_text": "DIN 6"}]}),
    ("PASTE", {"text": "https://example.com/p/4\tNeed replacement gear"}),
])
def test_parse_supported_import_modes(source_type, payload):
    rows = parse_import(payload, source_type=source_type)
    assert rows[0].source_url.startswith("https://")
    assert rows[0].original_text

def test_csv_reports_row_number_without_discarding_valid_rows():
    result = parse_csv("source_url,original_text\nhttps://e.test/1,Need gear\n,Missing URL")
    assert len(result.rows) == 1
    assert result.errors == [{"row": 3, "code": "SOURCE_URL_REQUIRED", "recovery_action": "补充公开来源链接后重新导入该行。"}]
```

- [ ] **Step 2: Run adapters/service tests and confirm missing functions**

Run: `cd backend && pytest apps/sources/tests/test_importers.py apps/sources/tests/test_ingestion_service.py -q`

- [ ] **Step 3: Implement bounded input contracts**

Enforce UTF-8, CSV/JSON/Paste maximum 10,000 rows per batch, original text maximum 20,000 characters per row, HTTPS/HTTP public URL schemes only, and screenshot/import assets belonging to the active organization. Treat spreadsheet formulas as plain input and never execute them. Return `ImportResult(rows, errors)` so valid rows survive invalid neighbors.

```python
@dataclass(frozen=True)
class ImportRow:
    platform: str
    source_url: str
    signal_type: str
    original_text: str
    author_name: str = ""
    published_at: datetime | None = None
    screenshot_asset_id: UUID | None = None
```

- [ ] **Step 4: Implement transactional row processing and idempotent retries**

Lock the batch, reject organization mismatches, process each row in its own savepoint, persist `IngestionRow` outcome, increment exact counts, and finish as `SUCCEEDED`, `PARTIAL_SUCCESS`, or `FAILED`. Re-running the same batch/job must reuse evidence by fingerprint and must not increment accepted/duplicate counts twice.

- [ ] **Step 5: Add the Celery worker using Job claim ownership**

```python
@shared_task
def execute_source_import(job_id: str, batch_id: str):
    job = JobService.claim(worker_id="source-import-worker", job_id=job_id)
    if job is None:
        return {"job_id": job_id, "status": "UNCHANGED"}
    try:
        batch = IngestionService.run(batch_id=batch_id, organization=job.organization)
        JobService.succeed(job.id, claim_token=job.claim_token,
                           result_reference={"ingestion_batch_id": str(batch.id)})
    except Exception:
        JobService.fail(job.id, claim_token=job.claim_token,
                        error={"code": "SOURCE_IMPORT_FAILED", "message": "公开线索导入失败。"})
        raise
    return {"ingestion_batch_id": str(batch.id), "status": batch.status}
```

- [ ] **Step 6: Run import/task tests and commit**

Run: `cd backend && pytest apps/sources/tests/test_importers.py apps/sources/tests/test_ingestion_service.py apps/sources/tests/test_source_tasks.py -q`

```bash
git add backend/apps/sources
git commit -m "feat: import public signals from guided inputs"
```

### Task 5: Expose organization-safe source APIs

**Files:**
- Create: `backend/apps/sources/serializers.py`
- Create: `backend/apps/sources/views.py`
- Create: `backend/apps/sources/urls.py`
- Test: `backend/apps/sources/tests/test_source_api.py`
- Test: `backend/apps/sources/tests/test_source_permissions.py`
- Test: `backend/apps/sources/tests/test_source_openapi.py`

**Interfaces:**
- Consumes: Task 2 permissions/jobs and Task 3–4 services.
- Produces: `GET/POST /api/v1/monitoring-targets`, `GET/POST /api/v1/ingestion-batches`, `GET /api/v1/source-contents`, `GET /api/v1/source-signals`, `GET /api/v1/source-evidences`; the import POST returns HTTP 202 with `job_id` and `ingestion_batch_id`.

- [ ] **Step 1: Write failing API tests for creation, 202 response, paging, evidence read-only behavior, and tenant isolation**

```python
@pytest.mark.django_db
def test_create_paste_batch_returns_job_reference(api_client, operator):
    api_client.force_authenticate(operator.user)
    response = api_client.post("/api/v1/ingestion-batches", {
        "source_type": "PASTE",
        "idempotency_key": "paste-20260810-1",
        "payload": {"text": "https://example.com/p/1\tWe need 200 replacement gears"},
    }, format="json")
    assert response.status_code == 202
    assert set(response.data) >= {"job_id", "ingestion_batch_id", "status"}

def test_source_evidence_has_no_update_route(api_client, evidence, operator):
    api_client.force_authenticate(operator.user)
    response = api_client.patch(f"/api/v1/source-evidences/{evidence.id}", {"original_text": "x"})
    assert response.status_code == 405
```

- [ ] **Step 2: Run API tests and confirm route failures**

Run: `cd backend && pytest apps/sources/tests/test_source_api.py apps/sources/tests/test_source_permissions.py -q`

- [ ] **Step 3: Implement serializers with explicit writable fields**

The ingestion request serializer accepts only `source_type`, `monitoring_target_id`, `idempotency_key`, `payload`, and optional organization-owned `import_asset_id`. Never serialize connector credentials, raw storage keys, cookies, request headers, or internal exception messages. Evidence serializer includes provenance and private asset download links generated through the existing asset service.

- [ ] **Step 4: Implement cursor-paginated views and recoverable errors**

Filter every queryset with `organization=request.organization`. Use `CanReadSources` for GET and `CanManageSources` for POST. Validate idempotency-key reuse against a different payload as HTTP 409. Queue with `transaction.on_commit(lambda: execute_source_import.delay(...))` so workers cannot race an uncommitted batch.

- [ ] **Step 5: Document endpoints with drf-spectacular and verify schema operation IDs**

Run: `cd backend && pytest apps/sources/tests/test_source_openapi.py tests/test_openapi_contract.py -q`

Expected operation IDs: `monitoring_targets_list`, `monitoring_targets_create`, `ingestion_batches_list`, `ingestion_batches_create`, `source_contents_list`, `source_signals_list`, and `source_evidences_list`.

- [ ] **Step 6: Run all source tests and commit**

Run: `cd backend && pytest apps/sources/tests -q`

```bash
git add backend/apps/sources backend/config/urls.py
git commit -m "feat: expose guided source ingestion api"
```

### Task 6: Add enterprise lead candidates, versioned insights, and deterministic scoring

**Files:**
- Create: `backend/apps/leads/models.py`
- Create: `backend/apps/leads/scoring.py`
- Create: `backend/apps/leads/migrations/0001_initial.py`
- Test: `backend/apps/leads/tests/conftest.py`
- Test: `backend/apps/leads/tests/test_lead_models.py`
- Test: `backend/apps/leads/tests/test_scoring.py`
- Test: `backend/apps/leads/tests/test_lead_isolation.py`

**Interfaces:**
- Consumes: `SourceSignal`, `SourceEvidence`, approved ontology concepts/snapshot IDs.
- Produces: `LeadCandidate`, `LeadCandidateEvidence`, `LeadInsight`, `LeadInsightRequirement`, `score_lead(dimensions: ScoreDimensions, gates: EvidenceGates) -> ScoreResult`.

- [ ] **Step 1: Write failing score boundary and evidence-gate tests**

```python
def test_score_uses_approved_weights():
    result = score_lead(
        ScoreDimensions(intent=30, company_fit=20, specificity=18, capability_fit=15, recency=8),
        EvidenceGates(traceable_source=True, explicit_need_or_company_match=True,
                      capability_evidence=True, audited_run=True, ontology_snapshot=True),
    )
    assert result.total == 91
    assert result.band == "HIGH"
    assert result.high_value_eligible is True

def test_high_numeric_score_without_traceable_evidence_is_not_high_value():
    result = score_lead(ScoreDimensions(30, 25, 20, 15, 10), EvidenceGates(False, True, True, True, True))
    assert result.total == 100
    assert result.band == "HIGH"
    assert result.high_value_eligible is False
```

- [ ] **Step 2: Write failing candidate/insight history tests**

```python
@pytest.mark.django_db
def test_new_analysis_appends_insight_and_preserves_previous(candidate, evidence, ai_run):
    first = LeadService.record_insight(candidate=candidate, ai_run=ai_run, evidence=[evidence], payload=payload(score=72))
    second = LeadService.record_insight(candidate=candidate, ai_run=next_run(), evidence=[evidence], payload=payload(score=85))
    assert [first.version, second.version] == [1, 2]
    assert LeadInsight.objects.filter(candidate=candidate).count() == 2
    assert LeadInsight.objects.get(pk=first.pk).score == 72
```

- [ ] **Step 3: Implement exact model states and immutable history**

```python
class LeadCandidate(OrganizationScopedModel):
    class Status(models.TextChoices):
        DISCOVERED = "DISCOVERED", "Discovered"
        ANALYZING = "ANALYZING", "Analyzing"
        ANALYZED = "ANALYZED", "Analyzed"
        REVIEWED = "REVIEWED", "Reviewed"
        READY_FOR_HANDOFF = "READY_FOR_HANDOFF", "Ready for handoff"
        HANDED_OFF = "HANDED_OFF", "Handed off"
        DISMISSED = "DISMISSED", "Dismissed"
```

B1 services may transition only through `DISCOVERED → ANALYZING → ANALYZED → REVIEWED`, plus `ANALYZED|REVIEWED → DISMISSED` and `DISMISSED → DISCOVERED`. The two handoff states exist for compatibility but no B1 endpoint may enter them. Candidate fields include `company_name`, normalized public `company_domain`, country hint, latest insight FK, and version. Evidence joins are organization-validated and append-only. Insights store all five dimension scores, total, band, eligibility, explanation, extracted requirement values, confidence triplet, ontology snapshot, `AIRun`, and version.

- [ ] **Step 4: Implement pure scoring with bounds and explicit explanations**

```python
WEIGHTS = {"intent": 30, "company_fit": 25, "specificity": 20, "capability_fit": 15, "recency": 10}

def score_lead(dimensions: ScoreDimensions, gates: EvidenceGates) -> ScoreResult:
    values = asdict(dimensions)
    for name, value in values.items():
        if not 0 <= value <= WEIGHTS[name]:
            raise ValueError(f"{name} must be between 0 and {WEIGHTS[name]}")
    total = sum(values.values())
    band = "HIGH" if total >= 80 else "WATCH" if total >= 60 else "OBSERVE" if total >= 40 else "LOW"
    return ScoreResult(total=total, band=band,
                       high_value_eligible=band == "HIGH" and all(asdict(gates).values()))
```

- [ ] **Step 5: Generate migration, run lead domain tests, and commit**

Run: `cd backend && python manage.py makemigrations leads && pytest apps/leads/tests/test_lead_models.py apps/leads/tests/test_scoring.py apps/leads/tests/test_lead_isolation.py -q`

```bash
git add backend/apps/leads
git commit -m "feat: add auditable lead candidates and scoring"
```

### Task 7: Run audited AI analysis against frozen evidence and ontology

**Files:**
- Create: `backend/apps/leads/schemas.py`
- Create: `backend/apps/leads/services.py`
- Create: `backend/apps/leads/orchestration.py`
- Create: `backend/apps/leads/tasks.py`
- Modify: `backend/apps/ai/orchestration.py`
- Test: `backend/apps/leads/tests/test_analysis_snapshot.py`
- Test: `backend/apps/leads/tests/test_lead_orchestration.py`
- Test: `backend/apps/leads/tests/test_lead_tasks.py`

**Interfaces:**
- Consumes: published prompt purpose `LEAD_ANALYZE`, `Job.Type.LEAD_ANALYZE`, evidence IDs, ontology snapshot service, AI provider registry, `AIRun` audit model.
- Produces: `build_analysis_snapshot(candidate, evidence_ids, actor) -> dict`, `execute_lead_analysis_job(job_id, prompt_version_id, provider_code=None) -> AIRun`, and result reference `{"lead_candidate_id": UUID, "lead_insight_id": UUID, "ai_run_id": UUID}`.

- [ ] **Step 1: Write failing frozen-input and output-schema tests**

```python
@pytest.mark.django_db
def test_snapshot_contains_only_committed_org_evidence_and_approved_ontology(candidate, evidence, reviewer):
    snapshot = build_analysis_snapshot(candidate=candidate, evidence_ids=[evidence.id], actor=reviewer.user)
    assert snapshot["organization_id"] == str(candidate.organization_id)
    assert snapshot["evidence"][0]["content_hash"] == evidence.content_hash
    assert all(row["status"] == "APPROVED" for row in snapshot["ontology_snapshot"]["concept_versions"])

def test_output_schema_requires_evidence_for_each_reason():
    errors = lead_analysis_errors({"company_name": "ABC", "dimensions": {}, "reasons": [{"text": "Likely buyer", "evidence_ids": []}]})
    assert errors
```

- [ ] **Step 2: Run tests and confirm missing schema/orchestrator failures**

Run: `cd backend && pytest apps/leads/tests/test_analysis_snapshot.py apps/leads/tests/test_lead_orchestration.py -q`

- [ ] **Step 3: Define the complete structured output schema**

Require `company_name`, optional `company_domain`/country, `need_summary_zh`, `need_summary_en`, five integer dimensions within their maxima, `requirements` with type/value/unit/evidence IDs, `capability_matches` with approved capability code/knowledge evidence IDs/source evidence IDs, `reasons`, three confidence values in 0–1, and `insufficient_evidence`. Set `additionalProperties: false` at every object level.

- [ ] **Step 4: Implement snapshot creation and orchestration**

Lock the candidate before entering `ANALYZING`; verify all evidence belongs to the same organization; freeze full original text and provenance, not live URLs alone; call the existing provider with a published `LEAD_ANALYZE` prompt; validate once, retry provider generation once on invalid structured output, and then persist a failed `AIRun`/Job if still invalid. Never invent missing company facts: blank/unknown stays blank.

```python
def _result_writer(run: AIRun, output: dict) -> dict:
    insight = LeadService.record_analysis_output(run=run, output=output)
    return {"lead_candidate_id": str(insight.candidate_id),
            "lead_insight_id": str(insight.id), "ai_run_id": str(run.id)}
```

- [ ] **Step 5: Prove cancellation, retry, invalid output, and idempotent result persistence**

Run: `cd backend && pytest apps/leads/tests/test_lead_orchestration.py apps/leads/tests/test_lead_tasks.py apps/ai/tests/test_ai_orchestration.py -q`

Expected: one insight per successful job attempt; retry creates a new `AIRun` and insight version but never overwrites history; canceled/stale workers cannot finalize.

- [ ] **Step 6: Commit audited analysis**

```bash
git add backend/apps/leads backend/apps/ai/orchestration.py
git commit -m "feat: analyze leads with frozen evidence audit"
```

### Task 8: Add candidate queue, detail, analysis, and human-review APIs

**Files:**
- Create: `backend/apps/leads/serializers.py`
- Create: `backend/apps/leads/views.py`
- Create: `backend/apps/leads/urls.py`
- Test: `backend/apps/leads/tests/test_lead_api.py`
- Test: `backend/apps/leads/tests/test_review_service.py`
- Test: `backend/apps/leads/tests/test_lead_permissions.py`
- Test: `backend/apps/leads/tests/test_lead_openapi.py`

**Interfaces:**
- Consumes: Tasks 6–7 models/services and Phase A auth/error conventions.
- Produces: `GET/POST /api/v1/lead-candidates`, `GET /api/v1/lead-candidates/{id}`, `POST /api/v1/lead-candidates/{id}/analyze`, `GET /api/v1/lead-insights`, and `POST /api/v1/lead-reviews`.

- [ ] **Step 1: Write failing queue/analyze/review tests**

```python
@pytest.mark.django_db
def test_reviewer_correction_appends_review_and_insight(api_client, analyzed_candidate, reviewer):
    api_client.force_authenticate(reviewer.user)
    response = api_client.post("/api/v1/lead-reviews", {
        "candidate_id": str(analyzed_candidate.id), "action": "CORRECT",
        "expected_version": analyzed_candidate.version,
        "correction": {"company_name": "ABC Packaging GmbH", "dimension_overrides": {"company_fit": 22}},
        "reason": "官网与公开主页一致。",
    }, format="json")
    assert response.status_code == 201
    assert response.data["candidate_status"] == "REVIEWED"
    assert response.data["insight_version"] == 2
```

- [ ] **Step 2: Run tests and confirm missing API/service behavior**

Run: `cd backend && pytest apps/leads/tests/test_lead_api.py apps/leads/tests/test_review_service.py apps/leads/tests/test_lead_permissions.py -q`

- [ ] **Step 3: Implement review actions as append-only service operations**

Support `CONFIRM`, `CORRECT`, `DISMISS`, `REOPEN`, and `REQUEST_MORE_EVIDENCE` in B1. Reserve `MERGE_COMPANY` and `SPLIT_COMPANY` for B2 where company matching exists. Require `expected_version`; return 409 when stale. `CORRECT` creates a new `LeadInsight` that links the original AI insight and records `human_correction`, reviewer, time, and reason. `CONFIRM` protects linked evidence from 30-day cleanup. `DISMISS` records a normalized ignore fingerprint/reason without creating a permanent blacklist.

- [ ] **Step 4: Implement serializers and cursor queue filters**

Queue filters: status, score band, minimum score, platform, country, review state, and created time. Reject repeated/ambiguous filters like existing product APIs. Candidate detail returns score dimensions, eligibility gates, reasons with evidence summaries, extracted requirements, capability matches, AI audit metadata, history, and permitted actions; it never exposes prompt secrets/provider credentials.

- [ ] **Step 5: Implement analyze endpoint with safe 202 scheduling**

Require `leads.analyze`, at least one selected evidence ID, a published `LEAD_ANALYZE` prompt, and candidate version. Create/reuse an idempotent job and schedule after commit. Return `{"job_id", "lead_candidate_id", "status": "QUEUED"}`.

- [ ] **Step 6: Verify OpenAPI, permissions, isolation, and commit**

Run: `cd backend && pytest apps/leads/tests -q && pytest tests/test_openapi.py tests/test_openapi_contract.py -q`

```bash
git add backend/apps/leads backend/config/urls.py
git commit -m "feat: add lead review and analysis api"
```

### Task 9: Enforce 30-day retention without deleting protected evidence

**Files:**
- Modify: `backend/apps/sources/services.py`
- Modify: `backend/apps/sources/tasks.py`
- Test: `backend/apps/sources/tests/test_retention.py`
- Test: `backend/apps/sources/tests/test_source_tasks.py`

**Interfaces:**
- Consumes: evidence retention classes, candidate evidence links, review confirmation, audit log service, `Job.Type.RETENTION_CLEANUP`.
- Produces: `RetentionService.cleanup(*, organization, cutoff, actor=None) -> RetentionResult` with counts for deleted text, anonymized actors, protected evidence, and failures.

- [ ] **Step 1: Write failing cutoff/protection tests**

```python
@pytest.mark.django_db
def test_cleanup_redacts_old_low_value_text_but_keeps_confirmed_evidence(old_evidence, confirmed_evidence):
    result = RetentionService.cleanup(
        organization=old_evidence.organization, cutoff=timezone.now() - timedelta(days=30)
    )
    old_evidence.refresh_from_db(); confirmed_evidence.refresh_from_db()
    assert old_evidence.original_text == ""
    assert old_evidence.availability_status == "REDACTED_BY_RETENTION"
    assert confirmed_evidence.original_text
    assert result.protected == 1
```

- [ ] **Step 2: Run retention tests and verify failure**

Run: `cd backend && pytest apps/sources/tests/test_retention.py -q`

- [ ] **Step 3: Implement service-controlled redaction and audit**

Do not hard-delete evidence rows needed for fingerprints/history. Under the guarded service context, clear original/translated text and private asset references for expired transient evidence, keep content hash/source class/retention reason, anonymize unconfirmed author display names, and append an audit entry. Abort and report a conflict if any evidence is referenced by confirmed/reviewed candidates or a later handoff protection class.

- [ ] **Step 4: Add idempotent cleanup worker and verify second-run zero changes**

Run: `cd backend && pytest apps/sources/tests/test_retention.py apps/sources/tests/test_source_tasks.py -q`

Expected: first run reports exact changes; second run succeeds with zero additional redactions; organizations are processed independently.

- [ ] **Step 5: Commit retention policy**

```bash
git add backend/apps/sources
git commit -m "feat: enforce lead evidence retention policy"
```

### Task 10: Build the beginner-friendly Lead Radar queue and import wizard

**Files:**
- Create: `frontend/src/modules/leads/api.ts`
- Create: `frontend/src/modules/leads/api.test.ts`
- Create: `frontend/src/modules/leads/LeadRadarPage.vue`
- Create: `frontend/src/modules/leads/LeadRadarPage.test.ts`
- Create: `frontend/src/modules/leads/SourceImportDialog.vue`
- Create: `frontend/src/modules/leads/SourceImportDialog.test.ts`
- Modify: `frontend/src/app/router.ts`
- Modify: `frontend/src/main.ts`
- Modify: `frontend/src/app/AppShell.vue`
- Modify: `frontend/src/app/router.test.ts`
- Modify: `frontend/src/app/AppShell.test.ts`

**Interfaces:**
- Consumes: generated schema plus Task 5/8 endpoints.
- Produces: `/lead-radar`, typed query keys, `listLeadCandidates`, `createIngestionBatch`, `getJob`, and import modes `URL | SCREENSHOT | CSV | JSON | PASTE`.

- [ ] **Step 1: Write failing API adapter tests**

```typescript
it("rejects a cursor that leaves the lead endpoint", () => {
  expect(safeLeadPageUrl("https://evil.example/leads")).toBeNull()
  expect(safeLeadPageUrl("/api/v1/lead-candidates?cursor=abc")).toBe("/api/v1/lead-candidates?cursor=abc")
})

it("creates a paste import with an idempotency key", async () => {
  server.use(http.post("/api/v1/ingestion-batches", async ({ request }) => {
    expect(await request.json()).toMatchObject({ source_type: "PASTE", idempotency_key: expect.any(String) })
    return HttpResponse.json({ job_id: "j1", ingestion_batch_id: "b1", status: "QUEUED" }, { status: 202 })
  }))
  await expect(createIngestionBatch({ mode: "PASTE", text: "https://e.test/1\tNeed gears" })).resolves.toMatchObject({ job_id: "j1" })
})
```

- [ ] **Step 2: Write failing UI tests for first-use guidance and permissions**

```typescript
it("guides a new user through collect then filter", async () => {
  render(LeadRadarPage, { global: testApp() })
  expect(await screen.findByRole("heading", { name: "潜客雷达" })).toBeVisible()
  expect(screen.getByText("先收集公开线索，再由系统筛选值得人工查看的企业")).toBeVisible()
  await userEvent.click(screen.getByRole("button", { name: "导入公开线索" }))
  expect(screen.getByRole("tab", { name: "粘贴内容" })).toBeVisible()
})
```

- [ ] **Step 3: Implement typed API functions and polling**

Use organization ID in every Vue Query key. Poll a submitted import job while status is `QUEUED`, `RUNNING`, or `RETRY_QUEUED`; stop on success/failure/cancel or component unmount. Map recoverable server errors to a short Chinese explanation plus a concrete next action. Do not cache screenshot object URLs beyond the dialog lifecycle.

- [ ] **Step 4: Implement the queue page with progressive disclosure**

Top-level elements: plain-language purpose, `导入公开线索` primary action, four summary cards (待分析/高价值待审核/需要补证据/已处理), status/score/platform filters, candidate cards/table, and a next-step panel. Hide management controls when permissions are absent. Show score and `证据门槛未满足` separately so beginners do not confuse a score with approval.

- [ ] **Step 5: Implement the five-mode import dialog**

Each mode shows an example and only its required fields. Screenshot mode first uses the existing private asset upload API and then submits its asset ID. CSV/JSON mode previews valid/invalid row counts before submission. Paste supports `URL<TAB>原文` per line. Confirmation states exactly: “系统只保存你提供范围内的公开信息，不会自动登录平台或发送消息。”

- [ ] **Step 6: Wire route/navigation, run frontend checks, and commit**

Run: `cd frontend && pnpm test -- --run src/modules/leads/api.test.ts src/modules/leads/LeadRadarPage.test.ts src/modules/leads/SourceImportDialog.test.ts src/app/router.test.ts src/app/AppShell.test.ts`

Run: `cd frontend && pnpm typecheck && pnpm lint`

```bash
git add frontend/src/modules/leads frontend/src/app
git commit -m "feat: add guided lead radar and imports"
```

### Task 11: Add evidence-first lead detail and human review UI

**Files:**
- Create: `frontend/src/modules/leads/LeadDetailDialog.vue`
- Create: `frontend/src/modules/leads/LeadDetailDialog.test.ts`
- Modify: `frontend/src/modules/leads/api.ts`
- Modify: `frontend/src/modules/leads/api.test.ts`
- Modify: `frontend/src/modules/leads/LeadRadarPage.vue`
- Modify: `frontend/src/modules/leads/LeadRadarPage.test.ts`

**Interfaces:**
- Consumes: candidate detail, analyze job, evidence, and review endpoints.
- Produces: evidence-first candidate review with `CONFIRM`, `CORRECT`, `DISMISS`, `REOPEN`, and `REQUEST_MORE_EVIDENCE` actions.

- [ ] **Step 1: Write failing detail/review interaction tests**

```typescript
it("shows why the lead was scored before offering review", async () => {
  render(LeadDetailDialog, { props: { candidateId: "lead-1", organizationId: "org-1" }, global: testApp() })
  expect(await screen.findByText("We need replacement helical gears, 200 pcs.")).toBeVisible()
  expect(screen.getByRole("link", { name: "打开公开来源" })).toHaveAttribute("href", "https://example.com/post/1")
  expect(screen.getByText("采购意向 30 / 30")).toBeVisible()
  expect(screen.getByText("AI 分析版本")).toBeVisible()
})

it("requires a reason before dismissing", async () => {
  render(LeadDetailDialog, { props: detailProps(), global: testApp() })
  await userEvent.click(await screen.findByRole("button", { name: "暂不跟进" }))
  expect(screen.getByRole("button", { name: "确认暂不跟进" })).toBeDisabled()
})
```

- [ ] **Step 2: Run the tests and confirm the component is absent**

Run: `cd frontend && pnpm test -- --run src/modules/leads/LeadDetailDialog.test.ts`

- [ ] **Step 3: Implement evidence-first layout and uncertainty copy**

Order the dialog as: enterprise summary → original evidence cards → five score dimensions → evidence gates → extracted requirements/capability matches → AI audit/version → review history → actions. Always show original language before translation. Label uncertain company/domain fields as `待确认`, not as facts. External links use `target="_blank" rel="noopener noreferrer"` and only HTTP(S) URLs accepted by a safe URL helper.

- [ ] **Step 4: Implement mutation/version-conflict recovery**

Send `expected_version` with analyze/review. On HTTP 409, keep the user's typed correction/reason, refetch candidate, explain that another review was saved, and offer `按最新版重新提交`. On successful review, invalidate queue/detail/job queries and announce status through an `aria-live` region.

- [ ] **Step 5: Run component, accessibility-adjacent, type, and lint checks**

Run: `cd frontend && pnpm test -- --run src/modules/leads/LeadDetailDialog.test.ts src/modules/leads/LeadRadarPage.test.ts src/modules/leads/api.test.ts`

Run: `cd frontend && pnpm typecheck && pnpm lint`

- [ ] **Step 6: Commit the review experience**

```bash
git add frontend/src/modules/leads
git commit -m "feat: add evidence-first lead review"
```

### Task 12: Add evaluation fixture, OpenAPI generation, seed data, and end-to-end acceptance

**Files:**
- Create: `backend/apps/leads/tests/fixtures/lead_evaluation.json`
- Create: `backend/apps/leads/tests/test_lead_evaluation.py`
- Create: `backend/apps/common/management/commands/seed_phase_b1.py`
- Create: `backend/apps/common/tests/test_seed_phase_b1.py`
- Modify: `backend/tests/test_openapi.py`
- Modify: `backend/tests/test_openapi_contract.py`
- Regenerate: `frontend/src/api/generated/schema.ts`
- Create: `frontend/e2e/phase-b1-lead-intelligence.spec.ts`
- Modify: `frontend/e2e/launcher.mjs` only if required by its current discovery behavior
- Modify: `docs/project-handoff-2026-08-10.md`
- Create: `docs/phase-b1-acceptance.md`

**Interfaces:**
- Consumes: every prior B1 task.
- Produces: reproducible offline quality metrics, fresh-machine demo data, schema/client synchronization, and browser acceptance evidence.

- [ ] **Step 1: Add at least 100 fully labeled bilingual industrial examples**

Each JSON record must contain a stable ID, language, public-text fixture, expected `is_explicit_need`, expected score band, expected company-match confidence class, required evidence spans, and category from: explicit need, vague need, ordinary engagement, advertisement, recruitment, job seeker, competitor/supplier pitch, academic/student, or company page without comments. Do not include real private contact details.

```json
{
  "id": "en-explicit-001",
  "language": "en",
  "text": "We need 200 replacement helical gears for a packaging machine, DIN 6 if possible.",
  "category": "explicit_need",
  "is_explicit_need": true,
  "expected_band": "HIGH",
  "required_spans": ["200", "replacement helical gears", "packaging machine", "DIN 6"]
}
```

- [ ] **Step 2: Write and run deterministic evaluation tests**

The test uses the deterministic normalization/scoring/evidence validator, not a live paid model. Assert explicit-need recall ≥ 0.90, high-value precision ≥ 0.80, and evidence-reference coverage = 1.00. Print false-negative/false-positive fixture IDs on failure.

Run: `cd backend && pytest apps/leads/tests/test_lead_evaluation.py -q`

- [ ] **Step 3: Add idempotent B1 seed data**

The command creates one monitoring target, one mixed ingestion batch, several source/evidence examples, low/watch/high candidates, one failed analysis job, and one reviewed correction for a named organization/user argument. Running it twice must not duplicate rows.

Run: `cd backend && pytest apps/common/tests/test_seed_phase_b1.py -q`

- [ ] **Step 4: Regenerate and verify the frontend API schema**

Run: `cd frontend && pnpm api:generate && pnpm api:check && pnpm typecheck`

The existing generator exports and validates a temporary schema with `config.test_settings`, generates `schema.ts` atomically, and removes the temporary JSON. Do not create a tracked OpenAPI JSON file and do not hand-edit `schema.ts`.

- [ ] **Step 5: Write the complete browser acceptance flow**

```typescript
test("collects, analyzes, explains, and reviews a public lead", async ({ page }) => {
  await page.goto("/lead-radar")
  await page.getByRole("button", { name: "导入公开线索" }).click()
  await page.getByRole("tab", { name: "粘贴内容" }).click()
  await page.getByLabel("公开内容").fill("https://example.com/post/1\tWe need 200 replacement helical gears")
  await page.getByRole("button", { name: "开始导入" }).click()
  await expect(page.getByText("导入完成")).toBeVisible()
  await page.getByRole("link", { name: /ABC Packaging/ }).click()
  await expect(page.getByText("We need 200 replacement helical gears")).toBeVisible()
  await page.getByRole("button", { name: "确认值得跟进" }).click()
  await expect(page.getByText("已完成人工审核")).toBeVisible()
})
```

- [ ] **Step 6: Run full verification**

Run: `cd backend && pytest -q`

Run: `cd frontend && pnpm test -- --run && pnpm typecheck && pnpm lint && pnpm build`

Run: `cd frontend && pnpm test:e2e -- phase-b1-lead-intelligence.spec.ts`

Run: `docker compose config`

Expected: all commands exit 0; no live social-platform credentials or paid AI calls are required.

- [ ] **Step 7: Update acceptance/handoff documentation and commit**

Record exact commands, passed counts, supported import modes, known platform limitations, retention behavior, and the boundary that B2 owns company enrichment/outreach/handoff.

```bash
git add backend frontend docs
git commit -m "test: close phase b1 acceptance"
```

## Self-Review Record

- Spec coverage: B1 URL/screenshot/CSV/JSON/paste intake, complete user-scoped signal preservation, immutable evidence, candidate/insight states, fixed scoring, AI audit, human correction, organization permissions, jobs, partial failure, idempotency, retention, beginner UI, offline evaluation, OpenAPI, and E2E each map to Tasks 1–12.
- Deliberate exclusions: `SourceAccount`, `PublicActor`, `CompanyMatch`, `CompanyIntelligenceProfile`, `OutreachDraft`, `LeadHandoff`, official live connectors, AIEO, and Market Intelligence remain outside B1 and require separate plans; their enum/interface reservations do not expose behavior.
- Type consistency: `SOURCE_IMPORT`, `LEAD_ANALYZE`, `SourceEvidence`, `LeadCandidate`, `LeadInsight`, score bands, permission codes, and API paths use the same names across backend, frontend, and tests.
- Placeholder scan: the plan contains no deferred implementation markers; every task names exact files, interfaces, tests, commands, expected outcomes, and commit boundaries.
