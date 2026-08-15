# UK Contracts Finder Discovery Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add UK Contracts Finder as a second official procurement-intent source behind the existing one-click automatic customer discovery flow.

**Architecture:** A strict `ContractsFinderSource` normalizes official search results into source-aware `SourceItem` records. A small composite adapter calls TED and Contracts Finder independently, interleaves successful items, records partial failures, and feeds the existing transactional discovery ingestion service.

**Tech Stack:** Python 3.12, Django 5, urllib, pytest, Vue 3, Vitest, Playwright.

## Global Constraints

- Modify only `C:\Users\Administrator\Documents\网站\sinofgear-growth-engine`.
- Use only fixed official HTTPS endpoints; do not scrape Google Maps, LinkedIn, or authenticated pages.
- Never store personal contact names, email addresses, or phone numbers returned inside procurement notices.
- Never send email, direct messages, forms, or social posts.
- Keep every real source distinct from Demo / Fake fixtures.
- Preserve the ordinary-user navigation and existing minimal opportunity page.

---

### Task 1: Add the strict Contracts Finder adapter

**Files:**
- Create: `backend/integrations/sources/contracts_finder.py`
- Create: `backend/integrations/sources/tests/test_contracts_finder_source.py`
- Modify: `backend/integrations/sources/base.py`
- Modify: `backend/integrations/sources/ted.py`

**Interfaces:**
- Consumes: `DiscoveryQuery(cpv_codes, published_from, limit)`.
- Produces: `ContractsFinderSource.fetch(query) -> SourceBatch` and source-aware `SourceItem.source_code`.

- [ ] **Step 1: Write failing request and normalization tests**

Test that the adapter posts only to the fixed official URL with `statuses=["Open"]`, requested CPV codes, `size=query.limit`, 15-second timeout, and 2 MB bound. Fixture results must cover a valid exact CPV, a parent-only CPV, an unsafe URL, missing required fields, HTML entities, and an official buyer ID.

- [ ] **Step 2: Run the adapter test and verify RED**

Run: `cd backend && pytest integrations/sources/tests/test_contracts_finder_source.py -q`

Expected: FAIL because `ContractsFinderSource` and `SourceItem.source_code` do not exist.

- [ ] **Step 3: Implement the minimal adapter**

Create `ContractsFinderSource` using an injected JSON transport. Normalize only exact CPV intersections, strip/HTML-unescape text, parse timezone-aware ISO dates, accept only `https://www.contractsfinder.service.gov.uk/Notice/<uuid>`, and set `source_code="UK_CONTRACTS_FINDER"`.

- [ ] **Step 4: Verify adapter GREEN and TED compatibility**

Run: `cd backend && pytest integrations/sources/tests/test_contracts_finder_source.py integrations/sources/tests/test_ted_source.py -q`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/integrations/sources
git commit -m "feat: add uk procurement source"
```

### Task 2: Compose and ingest multiple official sources

**Files:**
- Create: `backend/integrations/sources/composite.py`
- Create: `backend/integrations/sources/tests/test_composite_source.py`
- Modify: `backend/apps/growth/discovery.py`
- Modify: `backend/apps/growth/models.py`
- Create: `backend/apps/growth/migrations/0007_official_procurement_source.py`
- Modify: `backend/apps/growth/e2e_sources.py`
- Modify: `backend/apps/growth/tests/test_discovery_service.py`
- Modify: `backend/apps/growth/tests/test_discovery_tasks.py`
- Modify: `backend/config/settings.py`
- Modify: `.env.example`

**Interfaces:**
- Consumes: a tuple of adapters exposing `fetch(query) -> SourceBatch`.
- Produces: `CompositeDiscoverySource.fetch(query) -> SourceBatch`, source-aware hashing/identity/labels, and `build_discovery_source()` configured with TED plus Contracts Finder.

- [ ] **Step 1: Write failing composite behavior tests**

Test round-robin ordering, one-source partial success with a recorded failure, all-source failure, and preservation of per-source capability snapshots.

- [ ] **Step 2: Run composite tests and verify RED**

Run: `cd backend && pytest integrations/sources/tests/test_composite_source.py -q`

Expected: FAIL because the composite does not exist.

- [ ] **Step 3: Implement the minimal composite**

Fetch each source independently, retain successful batches, round-robin their items up to `query.limit`, sum skipped/total counts, and raise `SOURCE_UNAVAILABLE` only when every source fails.

- [ ] **Step 4: Write failing source-aware ingestion tests**

Test that `TED:X` and `UK_CONTRACTS_FINDER:X` never share evidence hashes, UK buyer IDs create stable `UK_CONTRACTS_FINDER:GBR:<id>` identities, no-ID records remain notice-specific, and UK signals display `英国 Contracts Finder 官方采购公告`.

- [ ] **Step 5: Run ingestion tests and verify RED**

Run: `cd backend && pytest apps/growth/tests/test_discovery_service.py apps/growth/tests/test_discovery_tasks.py -q`

Expected: FAIL because ingestion still hardcodes TED.

- [ ] **Step 6: Implement source-aware ingestion and factory**

Include `source_code` in evidence hashes and account identities; map source labels without trusting source payload text. Configure `build_discovery_source()` to return the composite while retaining the injectable E2E factory. Migrate the profile source code to `OFFICIAL_PROCUREMENT`.

- [ ] **Step 7: Verify backend discovery GREEN**

Run: `cd backend && pytest integrations/sources/tests apps/growth/tests/test_discovery_models.py apps/growth/tests/test_discovery_service.py apps/growth/tests/test_discovery_tasks.py apps/growth/tests/test_discovery_api.py -q`

Expected: PASS.

- [ ] **Step 8: Commit**

```bash
git add .env.example backend/apps/growth backend/config backend/integrations/sources
git commit -m "feat: combine official procurement sources"
```

### Task 3: Expose UK status and verify the browser flow

**Files:**
- Modify: `backend/apps/growth/views.py`
- Modify: `backend/apps/growth/tests/test_discovery_api.py`
- Modify: `frontend/src/modules/growth/AutomaticDiscoveryCard.test.ts`
- Modify: `frontend/e2e/zz-growth-workspace-persistence.spec.ts`
- Modify: `docs/acceptance/2026-08-14-growth-workspace.md`
- Modify: `docs/superpowers/plans/2026-08-14-ai-growth-loop-development-acceptance-checklist.md`

**Interfaces:**
- Consumes: workspace discovery summary and existing run/profile endpoints.
- Produces: ordinary-user source status for TED, UK Contracts Finder, and key-gated Google Places.

- [ ] **Step 1: Write failing API and component tests**

Assert `source_label="欧盟与英国官方采购数据"`, TED and UK statuses are `ACTIVE`, Google Places is `KEY_REQUIRED`, and the card renders both enabled official sources without exposing API terms.

- [ ] **Step 2: Run focused tests and verify RED**

Run: `cd backend && pytest apps/growth/tests/test_discovery_api.py -q`

Run: `cd frontend && pnpm test --run src/modules/growth/AutomaticDiscoveryCard.test.ts`

Expected: FAIL because UK is not yet in the workspace summary.

- [ ] **Step 3: Implement the summary copy and E2E assertions**

Update the backend summary only; the existing component must render the new source automatically. Extend the browser journey to assert both official sources, duplicate-safe run results, and Google Places key status.

- [ ] **Step 4: Run complete verification**

Run: `cd backend && pytest -q && ruff check . && python manage.py check && python manage.py makemigrations --check`

Run: `cd frontend && pnpm test --run && pnpm typecheck && pnpm lint && pnpm build && pnpm test:e2e`

Expected: all PASS.

- [ ] **Step 5: Run an isolated official read-only smoke**

Call the Contracts Finder adapter with the gear CPV query, print only counts and source URLs, and verify no personal contact fields are stored or emitted. Do not contact any buyer.

- [ ] **Step 6: Update acceptance evidence and commit**

```bash
git add backend/apps/growth frontend docs
git commit -m "test: verify uk procurement discovery"
```
