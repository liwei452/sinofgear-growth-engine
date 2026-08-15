# Public Trade Market Radar Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build an organization-isolated, evidence-first UN Comtrade market radar that persists public trade snapshots and computes transparent market indicators without creating buyer accounts.

**Architecture:** A bounded Comtrade adapter normalizes official aggregate rows into immutable snapshot records through an idempotent sync service. Read APIs compute explainable indicators from snapshots; the existing market workbench adds a small evidence panel and honest empty/configuration states.

**Tech Stack:** Django 5.2, Django REST Framework, injected urllib/Fake JSON transport, PostgreSQL/SQLite tests, Vue 3, TanStack Query, Vitest, Playwright.

## Global Constraints

- Only modify `sinofgear-growth-engine`; do not modify the independent site or the five-page UI redesign.
- Tests and browser acceptance use Fake transport only; no paid API or external network request.
- Aggregate trade data never creates or implies TargetAccount, Contact, IntentSignal, or company purchase evidence.
- Default HS codes are `848340` and `848390`; custom HS must be 4 or 6 digits.
- Every indicator returns formula inputs and source evidence; no opaque weighted score.
- No real outbound, social publishing, OAuth, production deployment, or business-history deletion.

---

### Task 1: Standardized Comtrade Adapter

**Files:**
- Create: `backend/integrations/sources/comtrade.py`
- Create: `backend/integrations/sources/tests/test_comtrade_source.py`
- Modify: `backend/integrations/sources/base.py`

**Interfaces:**
- Produces `TradeQuery`, `TradeRow`, `TradeBatch`, `ComtradeSource.fetch(query)` and `trade_governance_for("UN_COMTRADE")`.

```python
query = TradeQuery(reporter_code="360", partner_code="0", flow="M", hs_codes=("848340",), periods=("2024",))
batch = ComtradeSource(transport=fake_transport).fetch(query)
assert batch.rows[0].trade_value_usd == 125000
assert batch.rows[0].source_url.startswith("https://comtradeplus.un.org/")
```

- [ ] Write failing tests for valid annual import normalization, custom HS validation, fixed official host, timeout/429/oversize/invalid JSON mapping, skipped malformed rows, and no network with injected Fake transport.
- [ ] Run `pytest backend/integrations/sources/tests/test_comtrade_source.py -q` and verify failures are caused by missing interfaces.
- [ ] Implement bounded dataclasses, governance metadata and adapter normalization with exact field allow-list.
- [ ] Re-run the focused tests and Ruff; commit `feat: add bounded comtrade source adapter`.

### Task 2: Snapshot Persistence and Idempotent Sync

**Files:**
- Modify: `backend/apps/growth/models.py`
- Create: `backend/apps/growth/trade_data.py`
- Create: `backend/apps/growth/migrations/0019_tradesyncrun_tradedatasetsnapshot.py`
- Create: `backend/apps/growth/tests/test_trade_data.py`

**Interfaces:**
- Produces `sync_trade_data(organization, actor, query, source)` and `trade_indicators(organization, country_code, hs_codes, periods)`.

```python
first = sync_trade_data(organization=org, actor=user, query=query, source=fake)
second = sync_trade_data(organization=org, actor=user, query=query, source=fake)
assert first.snapshot_ids == second.snapshot_ids
assert TargetAccount.objects.filter(organization=org).count() == 0
```

- [ ] Write failing model/service tests for record hash uniqueness, successful rerun reuse, changed official revision creating a new snapshot, organization isolation, failure audit, and zero TargetAccount/IntentSignal side effects.
- [ ] Verify RED with the focused pytest module.
- [ ] Implement immutable audit models, canonical hashing, atomic sync, transparent metric helpers and missing-denominator behavior.
- [ ] Generate migration, run focused tests and migration drift, then commit `feat: persist public trade snapshots`.

### Task 3: Trade APIs and Enterprise Import Contract

**Files:**
- Modify: `backend/apps/growth/serializers.py`
- Modify: `backend/apps/growth/views.py`
- Modify: `backend/apps/growth/urls.py`
- Create: `backend/apps/growth/trade_contracts.py`
- Create: `backend/apps/growth/tests/test_trade_api.py`
- Create: `docs/integrations/enterprise-trade-record-import-contract.md`

**Interfaces:**
- Produces POST `/api/v1/growth/trade-syncs`, GET `/api/v1/growth/trade-snapshots`, GET `/api/v1/growth/trade-indicators`.

```python
response = client.get("/api/v1/growth/trade-indicators?country=IDN&hs_code=848340")
assert response.data["indicators"]["year_over_year"]["formula"] == "(current - previous) / previous * 100"
assert response.data["indicators"]["china_share"]["inputs"]["world_value"] == 125000
```

- [ ] Write failing API tests for permissions, strict request fields, default/custom HS, disabled-provider response, fixture sync, filters, provenance, idempotency and cross-organization isolation.
- [ ] Write failing contract tests validating importer/consignee/shipper/notify-party roles, normalized entity fields, freight-forwarder review flags and required license metadata.
- [ ] Verify RED, implement strict serializers/views/runtime selection and the type-level import contract without creating accounts.
- [ ] Run focused API/OpenAPI tests and commit `feat: expose explainable trade radar api`.

### Task 4: Minimal Existing-Workbench UI

**Files:**
- Modify: `frontend/src/modules/growth/api.ts`
- Create: `frontend/src/modules/growth/TradeMarketEvidencePanel.vue`
- Create: `frontend/src/modules/growth/TradeMarketEvidencePanel.test.ts`
- Modify: `frontend/src/modules/growth/MarketPilotComparison.vue`
- Modify: `frontend/src/modules/growth/GrowthWorkspacePages.test.ts`

**Interfaces:**
- Consumes the trade snapshot and indicator APIs; emits no candidate/account mutations.

```ts
expect(await screen.findByText("当前没有官方贸易快照")).toBeVisible()
await user.click(screen.getByRole("button", { name: "同步公开贸易数据" }))
expect(await screen.findByText("(本期 - 上年同期) / 上年同期 × 100%" )).toBeVisible()
```

- [ ] Write failing component tests for honest empty state, provider-disabled state, HS 848340/848390 defaults, custom HS validation, fixture sync, formula inputs/source links, refresh persistence and unchanged candidate count.
- [ ] Verify RED, add typed API calls and a compact expandable panel within the existing market workbench.
- [ ] Run focused Vitest and typecheck; commit `feat: show public trade evidence in market radar`.

### Task 5: Full Verification and Browser Acceptance

**Files:**
- Create: `frontend/e2e/public-trade-market-radar.spec.ts`
- Modify: `frontend/src/api/generated/schema.ts`

```ts
await expect(page.getByText("宏观贸易仅用于市场判断，不是具体买家证据")).toBeVisible()
await page.reload()
await expect(page.getByRole("link", { name: "查看 UN Comtrade 原始来源" })).toBeVisible()
```

- [ ] Add an E2E fixture-only flow: open watched market, sync 848340/848390, inspect persisted snapshot/formula/source, reload, and assert candidate count did not change.
- [ ] Run focused E2E, then full backend pytest, Ruff, migration drift, OpenAPI/API generation check, full frontend tests, ESLint, typecheck and build.
- [ ] Verify ports 3001 and 8000 return 200, `git diff --check` passes and worktree is clean after commit.
- [ ] Commit `test: verify public trade market radar`.
