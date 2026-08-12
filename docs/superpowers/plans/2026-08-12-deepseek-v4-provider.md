# DeepSeek V4 Provider Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect the existing audited content-generation and lead-analysis jobs to DeepSeek V4 with secure Windows credentials, deterministic Flash/Pro routing, bounded cost, truthful recovery, and an administrator setup experience.

**Architecture:** Keep the existing `Job → PromptVersion → AIRun → JSON Schema/domain validation` pipeline. Add an organization-scoped, non-secret provider configuration and immutable execution intent in Django; store the actual key behind a credential-store adapter backed by Windows Credential Manager; call DeepSeek through a focused transport/provider; reserve and reconcile budget atomically; expose only safe configuration and audit metadata to the Vue administrator UI.

**Tech Stack:** Python 3.12, Django 5.2, Django REST Framework, Celery, PostgreSQL/SQLite tests, `httpx` 0.28, Windows Credential Manager via `ctypes`, Vue 3, TypeScript, TanStack Vue Query, Vitest, Playwright.

## Global Constraints

- Production model identifiers are exactly `deepseek-v4-flash` and `deepseek-v4-pro`; legacy `deepseek-chat` and `deepseek-reasoner` must not be introduced.
- Standard work uses V4 Flash with thinking disabled; only frozen policy or an authorized administrator override may use V4 Pro with thinking enabled.
- The complete API key must never enter Git, `.env`, database fields, Redis/job payloads, logs, audit records, exceptions, exports, installer artifacts, or any response sent back to the frontend.
- Internal `reasoning_content` must be discarded and must never be persisted or displayed.
- Automatic tests must not read a real credential or make a paid network request.
- There is no silent fallback to `fake` or `schema-fake` when DeepSeek is configured or fails.
- Provider output remains subject to the existing size, JSON Schema, ontology, evidence, organization, and human-review boundaries.
- Rate limit, overload, network, and timeout failures may have at most two delayed retries; authentication, balance, budget, and validation failures do not enter the transport retry loop.
- Invalid structured output receives at most one paid repair request using the same frozen model, input, and business intent.
- Ordinary mode stays model-agnostic; credential and cost controls require `credentials.manage` and live only in advanced administration.
- Existing deterministic suites remain green and free; a paid smoke test requires an explicit administrator action or `--acknowledge-paid-call` command flag.

## File Structure

New focused units:

- `backend/integrations/credentials/base.py` — credential-store protocol and controlled errors.
- `backend/integrations/credentials/windows.py` — Windows Credential Manager implementation only.
- `backend/integrations/credentials/registry.py` — settings-selected store, with dependency override for tests.
- `backend/integrations/ai/deepseek.py` — DeepSeek request/response mapping and provider error taxonomy.
- `backend/apps/ai/routing.py` — deterministic, versioned Flash/Pro decision.
- `backend/apps/ai/budget.py` — atomic daily reservation and reconciliation.
- `backend/apps/ai/provider_configuration.py` — test-before-save credential/application service.
- `frontend/src/modules/aiSettings/` — administrator settings API, page, and tests.

Existing large orchestration stays in `backend/apps/ai/orchestration.py`; only provider-result, immutable intent, usage, and normalized error seams change there.

---

### Task 1: Secure Credential Store Boundary

**Files:**
- Create: `backend/integrations/credentials/__init__.py`
- Create: `backend/integrations/credentials/base.py`
- Create: `backend/integrations/credentials/windows.py`
- Create: `backend/integrations/credentials/registry.py`
- Create: `backend/integrations/credentials/tests/test_windows_store.py`
- Create: `backend/integrations/credentials/tests/test_registry.py`
- Modify: `backend/config/settings.py`

**Interfaces:**
- Produces: `CredentialStore.read(target: str) -> str | None`, `write(target: str, secret: str) -> None`, `delete(target: str) -> bool`.
- Produces: `credential_target(organization_id) -> str`, formatted as `SinofGear/DeepSeek/<uuid>`.
- Produces: `get_credential_store() -> CredentialStore`; production Windows selects `WindowsCredentialStore`, tests may inject a fake.
- Consumes later: Tasks 2 and 3 read or update the key exclusively through this interface.

- [ ] **Step 1: Write failing adapter contract and Windows API tests**

```python
def test_windows_store_round_trips_unicode_secret(fake_wincred):
    store = WindowsCredentialStore(api=fake_wincred)
    store.write("SinofGear/DeepSeek/org-1", "sk-密钥-value")
    assert store.read("SinofGear/DeepSeek/org-1") == "sk-密钥-value"
    assert store.delete("SinofGear/DeepSeek/org-1") is True
    assert store.read("SinofGear/DeepSeek/org-1") is None

def test_target_rejects_non_uuid_organization_ids():
    with pytest.raises(CredentialTargetError):
        credential_target("../other-user")
```

The fake API must assert `CRED_TYPE_GENERIC`, session persistence, correct UTF-16 byte length, `CredFree` after reads, empty-secret rejection, not-found behavior, and that raw OS error text is replaced by a controlled exception.

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest integrations\credentials\tests -q`  
Expected: FAIL because the credential modules do not exist.

- [ ] **Step 3: Implement the protocol and Windows adapter**

```python
class CredentialStore(Protocol):
    def read(self, target: str) -> str | None: ...
    def write(self, target: str, secret: str) -> None: ...
    def delete(self, target: str) -> bool: ...

def credential_target(organization_id) -> str:
    value = UUID(str(organization_id))
    return f"SinofGear/DeepSeek/{value}"
```

Use `ctypes.WinDLL("Advapi32.dll", use_last_error=True)` and explicit `CREDENTIALW` signatures. Copy the credential blob into a Python string before `CredFree`; never include the target or secret in raised messages. `registry.py` must fail closed on non-Windows when `AI_CREDENTIAL_STORE=windows`, and allow an in-memory fake only through test settings/dependency override.

- [ ] **Step 4: Run credential tests and backend security tests**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest integrations\credentials\tests apps\common\tests\test_security.py -q`  
Expected: PASS; no test accesses the real Windows credential vault.

- [ ] **Step 5: Commit**

```powershell
git add backend/integrations/credentials backend/config/settings.py
git commit -m "feat: add Windows credential store boundary"
```

---

### Task 2: DeepSeek V4 Transport and Structured Provider

**Files:**
- Create: `backend/integrations/ai/deepseek.py`
- Create: `backend/integrations/ai/tests/test_deepseek_provider.py`
- Modify: `backend/integrations/ai/providers.py`
- Modify: `backend/integrations/ai/__init__.py`
- Modify: `backend/pyproject.toml`
- Modify: `backend/config/settings.py`

**Interfaces:**
- Produces: `ProviderRequest(model, thinking_enabled, prompt, schema, max_tokens, timeout_seconds)`.
- Produces: `ProviderResult(output: dict, metadata: dict)` containing only allowlisted request/model/usage/finish/timing fields.
- Produces: `DeepSeekProvider.generate(*, prompt, schema, execution) -> ProviderResult`.
- Produces controlled subclasses of `ProviderCallError`: `ProviderAuthenticationError`, `ProviderBalanceError`, `ProviderRateLimitError`, `ProviderUnavailableError`, `ProviderTimeoutError`, `ProviderNetworkError`, `ProviderInvalidOutputError`.
- Consumes: Task 1's `CredentialStore` to read the key at call time.
- Consumed later: Task 5 invokes this provider through the registry.

- [ ] **Step 1: Write failing request-shape and response tests with `httpx.MockTransport`**

```python
def test_flash_request_disables_thinking_and_requests_json(deepseek_provider, capture):
    result = deepseek_provider.generate(
        prompt="Return JSON for this content task.",
        schema={"type": "object", "required": ["title"], "properties": {"title": {"type": "string"}}},
        execution=execution(model="deepseek-v4-flash", thinking=False),
    )
    assert capture.json["model"] == "deepseek-v4-flash"
    assert capture.json["thinking"] == {"type": "disabled"}
    assert capture.json["response_format"] == {"type": "json_object"}
    assert capture.headers["Authorization"] == "Bearer secret-from-fake-store"
    assert result.output == {"title": "DIN 6 gear"}

def test_pro_discards_reasoning_content(deepseek_provider, pro_response):
    result = deepseek_provider.generate(...)
    assert "reasoning_content" not in result.metadata
    assert "private chain" not in repr(result)
```

Add cases for 401, 402, 429 with `Retry-After`, 500/503, timeout, connection error, empty choices, `finish_reason=length`, blank content, invalid JSON, oversized body, malicious request IDs, and usage fields. Assert exception strings and `repr` never contain the key, authorization header, response body, or reasoning content.

- [ ] **Step 2: Run and verify RED**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest integrations\ai\tests\test_deepseek_provider.py -q`  
Expected: FAIL because `DeepSeekProvider` does not exist.

- [ ] **Step 3: Add `httpx` and implement the provider**

Add `httpx>=0.28,<0.29` to `backend/pyproject.toml`. Send one non-streaming POST to `https://api.deepseek.com/chat/completions`; use connect/read/write/pool timeouts derived from the frozen execution. Append a system instruction that explicitly says “Return one JSON object only.” Parse only `choices[0].message.content` with byte/depth bounds, and discard `reasoning_content` before any value reaches metadata or exceptions.

```python
@dataclass(frozen=True)
class ProviderResult:
    output: dict
    metadata: dict

provider_registry.register("deepseek", DeepSeekProvider(...))
```

Do not register DeepSeek when the credential-store backend is unsupported; lookup must return the existing controlled `provider_not_available` preflight error.

- [ ] **Step 4: Run provider and registry tests**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest integrations\ai\tests integrations\credentials\tests -q`  
Expected: PASS with zero real network calls.

- [ ] **Step 5: Commit**

```powershell
git add backend/pyproject.toml backend/config/settings.py backend/integrations/ai
git commit -m "feat: add DeepSeek V4 structured provider"
```

---

### Task 3: Organization Provider Configuration and Safe Admin API

**Files:**
- Modify: `backend/apps/ai/models.py`
- Create: `backend/apps/ai/migrations/0003_provider_configuration.py`
- Create: `backend/apps/ai/provider_configuration.py`
- Modify: `backend/apps/ai/serializers.py`
- Modify: `backend/apps/ai/views.py`
- Modify: `backend/apps/ai/urls.py`
- Create: `backend/apps/ai/tests/test_provider_configuration.py`
- Create: `backend/apps/ai/tests/test_provider_configuration_api.py`
- Modify: `backend/apps/common/security.py`
- Modify: `backend/apps/common/tests/test_security.py`

**Interfaces:**
- Produces model: `AIProviderConfiguration(organization, provider_code, connection_state, key_suffix, credential_revision, last_tested_at, last_tested_by, daily_budget_usd, flash_max_output_tokens, pro_max_output_tokens, timeout_seconds, updated_at)`.
- Produces service: `test_and_save_deepseek_configuration(*, organization, actor, api_key, limits) -> AIProviderConfiguration`.
- Produces service: `delete_deepseek_credential(*, organization, actor) -> AIProviderConfiguration`.
- Produces endpoints: `GET/PUT/DELETE /api/v1/ai-provider-configuration` and `POST /api/v1/ai-provider-configuration/test`.
- Consumes: Tasks 1 and 2.
- Consumed later: Tasks 4–8.

- [ ] **Step 1: Write failing model/service/API tests**

```python
def test_test_and_save_writes_credential_only_after_success(store, provider):
    provider.fail_with(ProviderAuthenticationError())
    with pytest.raises(ProviderConfigurationError, match="invalid_key"):
        test_and_save_deepseek_configuration(..., api_key="sk-secret")
    assert store.writes == []
    assert "sk-secret" not in str(AIProviderConfiguration.objects.all().values())

def test_configuration_api_never_returns_complete_key(admin_client):
    response = admin_client.get("/api/v1/ai-provider-configuration")
    assert response.json()["key_suffix"] == "1234"
    assert "api_key" not in response.json()
```

Cover administrator-only access, other-organization isolation, masked suffix validation, replace rollback if vault write fails, delete idempotency, `test` not saving, invalid limits, duplicate JSON keys, unknown fields, CSRF, no key in captured logs, and controlled Chinese recovery codes.

- [ ] **Step 2: Run and verify RED**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest apps\ai\tests\test_provider_configuration.py apps\ai\tests\test_provider_configuration_api.py -q`  
Expected: FAIL because configuration storage and endpoints do not exist.

- [ ] **Step 3: Implement migration, transactional service, and endpoints**

Store no credential target or secret in the model; derive the vault target from organization UUID. `PUT` accepts the secret write-only and performs a minimal V4 Flash test before the credential store write and database update. `POST .../test` tests the saved key or a submitted replacement without persisting the replacement. Return fixed recovery codes such as `deepseek_invalid_key`, `deepseek_balance_required`, `deepseek_rate_limited`, and `deepseek_unavailable`.

Extend secret scrubbing so DeepSeek authorization patterns and strings shaped like `sk-...` are removed even when nested under an innocently named key. Preserve safe token counts such as `input_tokens`.

- [ ] **Step 4: Run API, migration, OpenAPI, and security tests**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest apps\ai\tests apps\common\tests\test_security.py tests\test_openapi.py tests\test_openapi_contract.py -q`  
Expected: PASS; `python manage.py makemigrations --check --dry-run` reports no changes.

- [ ] **Step 5: Commit**

```powershell
git add backend/apps/ai backend/apps/common/security.py backend/apps/common/tests/test_security.py
git commit -m "feat: add safe DeepSeek configuration API"
```

---

### Task 4: Immutable Routing Intent and Atomic Daily Budget

**Files:**
- Modify: `backend/apps/ai/models.py`
- Create: `backend/apps/ai/migrations/0004_execution_intent_and_usage.py`
- Create: `backend/apps/ai/routing.py`
- Create: `backend/apps/ai/budget.py`
- Create: `backend/apps/ai/tests/test_routing.py`
- Create: `backend/apps/ai/tests/test_budget.py`
- Modify: `backend/apps/content/views.py`
- Modify: `backend/apps/leads/services.py`
- Modify: `backend/apps/content/tests/test_content_api.py`
- Modify: `backend/apps/leads/tests/test_lead_api.py`

**Interfaces:**
- Produces immutable model: `AIExecutionIntent(job one-to-one, organization, provider, model, thinking_enabled, policy_code, policy_version, override_reason, max_output_tokens, timeout_seconds, estimated_input_tokens, reserved_cost_usd, created_by, created_at)`.
- Produces ledger models: `AIUsageDay(organization, usage_date, reserved_usd, actual_usd)` and `AIUsageAttempt(run, intent, status, reserved_usd, actual_usd, input_tokens, output_tokens, cache_hit_tokens, reconciled_at)`.
- Produces: `route_ai_work(*, job_type, snapshot, administrator_override=False) -> RoutingDecision`.
- Produces: `reserve_budget(intent, run) -> AIUsageAttempt`, `reconcile_usage(attempt, metadata, status) -> None`.
- Consumes: Task 3 configuration.
- Consumed later: Task 5 orchestration and Task 7 usage UI.

- [ ] **Step 1: Write failing routing and concurrency tests**

```python
def test_routine_content_routes_to_flash():
    decision = route_ai_work(job_type="CONTENT_GENERATE", snapshot={})
    assert (decision.model, decision.thinking_enabled) == ("deepseek-v4-flash", False)

def test_conflicting_lead_routes_to_pro():
    decision = route_ai_work(
        job_type="LEAD_ANALYZE",
        snapshot={"routing_signals": {"evidence_conflict": True}},
    )
    assert (decision.model, decision.thinking_enabled) == ("deepseek-v4-pro", True)

@pytest.mark.django_db(transaction=True)
def test_concurrent_reservations_cannot_exceed_daily_ceiling(...):
    results = run_two_reservations_against_budget("0.50")
    assert sum(result.accepted for result in results) == 1
```

Also test unauthorized override rejection, ordinary user payload cannot inject a model, stable policy code/version, retry reuses intent, exact UTC/organization billing date rule, release on pre-call cancellation, reconcile on success/failure, and no negative/duplicate reconciliation.

- [ ] **Step 2: Run and verify RED**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest apps\ai\tests\test_routing.py apps\ai\tests\test_budget.py -q`  
Expected: FAIL because routing and budget modules do not exist.

- [ ] **Step 3: Implement routing, immutable intent creation, and row-locked budget ledger**

Create the intent transactionally with job creation in content and lead services. Use policy `deepseek-routing-v1`. Only `credentials.manage` may submit `enhanced_analysis=true`; the field is rejected rather than ignored for other users. Estimate input tokens conservatively from UTF-8 prompt/snapshot size and reserve the configured maximum output cost before the paid call.

Use `select_for_update()` on the unique `(organization, usage_date)` row. Store money as `Decimal`, never float. A retry against the same job attempt must return the existing usage attempt and must not reserve twice.

- [ ] **Step 4: Run routing, budget, content, lead, and migration tests**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest apps\ai\tests\test_routing.py apps\ai\tests\test_budget.py apps\content\tests apps\leads\tests\test_lead_api.py -q`  
Expected: PASS, including the transaction/concurrency test on the supported test database path.

- [ ] **Step 5: Commit**

```powershell
git add backend/apps/ai backend/apps/content backend/apps/leads
git commit -m "feat: freeze DeepSeek routing and daily budget"
```

---

### Task 5: Connect DeepSeek to Audited Orchestration

**Files:**
- Modify: `backend/apps/ai/orchestration.py`
- Modify: `backend/apps/ai/models.py`
- Create: `backend/apps/ai/migrations/0005_run_routing_audit.py`
- Modify: `backend/apps/ai/serializers.py`
- Modify: `backend/apps/ai/tests/test_ai_orchestration.py`
- Modify: `backend/apps/ai/tests/test_ai_run_api.py`
- Modify: `backend/apps/content/tasks.py`
- Modify: `backend/apps/leads/orchestration.py`
- Modify: `backend/apps/leads/tasks.py`
- Modify: `backend/apps/leads/tests/test_lead_orchestration.py`

**Interfaces:**
- Consumes: `AIExecutionIntent`, `ProviderResult`, `reserve_budget`, and `reconcile_usage` from Tasks 2 and 4.
- Produces: existing `execute_generation_job(...) -> AIRun` with DeepSeek-specific provider result and controlled retry support, without changing callers' result type.
- Produces safe AIRun fields/metadata: actual model, thinking flag, routing policy, request ID, usage, cost, duration, finish reason; never reasoning content.
- Consumed later: Tasks 6–9.

- [ ] **Step 1: Write failing orchestration tests**

```python
def test_deepseek_run_uses_frozen_intent_and_persists_safe_usage(...):
    run = execute_generation_job(job.id, prompt_version_id=prompt.id)
    assert run.provider == "deepseek"
    assert run.model == "deepseek-v4-flash"
    assert run.provider_metadata["thinking_enabled"] is False
    assert run.provider_metadata["input_tokens"] == 120
    assert "reasoning_content" not in json.dumps(run.provider_metadata)

def test_provider_failure_never_falls_back_to_fake(...):
    run = execute_generation_job(...)
    assert run.status == "FAILED"
    assert fake_provider.calls == []
```

Cover: missing configuration before claim; budget failure before provider call; cancellation before/after reservation; two transport retries only for retryable taxonomy; `Retry-After` cap; one invalid-output repair; repair uses same intent; actual usage reconciliation; local timeout ambiguous outcome; duplicate worker/job invocation; successful domain evidence validation; failed finalization; secrets and reasoning absent from DB/API/logs.

- [ ] **Step 2: Run focused orchestration suites and verify RED**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest apps\ai\tests\test_ai_orchestration.py apps\leads\tests\test_lead_orchestration.py -q`  
Expected: FAIL because orchestration ignores execution intent and `ProviderResult`.

- [ ] **Step 3: Implement provider execution, retry scheduling, repair, audit, and reconciliation**

Resolve the immutable intent before claiming the job. Reserve budget immediately after `AIRun` creation and before the provider call. The provider call receives an explicit `ProviderExecution` built only from the intent. Convert provider exceptions to controlled job codes; never persist exception strings.

For Celery delayed retries, persist a safe retry state and schedule `self.retry(countdown=...)` without marking the job terminal. Authentication, balance, budget, canceled, and invalid-output-after-repair paths finalize immediately. Fake providers used by tests must also return `ProviderResult`, so orchestration has one contract.

- [ ] **Step 4: Run AI, content, lead, job, and audit API suites**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest apps\ai\tests apps\content\tests apps\leads\tests apps\jobs\tests -q`  
Expected: PASS; existing deterministic provider tests remain free.

- [ ] **Step 5: Commit**

```powershell
git add backend/apps/ai backend/apps/content/tasks.py backend/apps/leads
git commit -m "feat: run audited jobs through DeepSeek"
```

---

### Task 6: Truthful Recovery Copy and Job Progress

**Files:**
- Modify: `backend/apps/common/security.py`
- Modify: `backend/apps/jobs/serializers.py`
- Modify: `backend/apps/jobs/tests/test_job_api.py`
- Modify: `frontend/src/shared/presentation/ordinary.ts`
- Modify: `frontend/src/shared/presentation/ordinary.test.ts`
- Modify: `frontend/src/modules/content/ContentFactoryPage.vue`
- Modify: `frontend/src/modules/content/ContentFactoryPage.test.ts`
- Modify: `frontend/src/modules/leads/LeadDetailDialog.vue`
- Modify: `frontend/src/modules/leads/LeadDetailDialog.test.ts`

**Interfaces:**
- Consumes: controlled errors/retry state from Task 5.
- Produces ordinary Chinese mappings for invalid key, balance, limit, overload, timeout, repair failure, budget ceiling, retry scheduled, canceled, and administrator approval required.
- Produces no model chooser in ordinary mode.

- [ ] **Step 1: Write failing backend and frontend presentation tests**

```ts
expect(ordinaryJobError({ code: "deepseek_balance_required" })).toEqual({
  message: "AI账户余额不足，任务没有继续扣费。",
  recovery: "请联系管理员充值后重新尝试。",
})
expect(screen.queryByText(/V4|Flash|Pro|模型/)).not.toBeInTheDocument()
```

Backend tests must assert the public error shape has only controlled code/message/recovery fields and never contains provider response bodies or secrets.

- [ ] **Step 2: Run and verify RED**

Run: `cd frontend && pnpm vitest run src/shared/presentation/ordinary.test.ts src/modules/content/ContentFactoryPage.test.ts src/modules/leads/LeadDetailDialog.test.ts`  
Expected: FAIL because the new controlled states have no user-facing mapping.

- [ ] **Step 3: Implement safe status and recovery presentation**

Map fixed codes at the presentation boundary. Show scheduled retry count and next retry time when supplied. Keep technical provider/model/routing/cost details inside administrator or AI audit disclosures. Do not interpolate raw backend `detail` into ordinary UI.

- [ ] **Step 4: Run backend job and affected frontend suites**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest apps\jobs\tests\test_job_api.py apps\common\tests\test_security.py -q`  
Run: `cd frontend && pnpm vitest run src/shared/presentation/ordinary.test.ts src/modules/content/ContentFactoryPage.test.ts src/modules/leads/LeadDetailDialog.test.ts`  
Expected: PASS.

- [ ] **Step 5: Commit**

```powershell
git add backend/apps/common/security.py backend/apps/jobs frontend/src/shared/presentation frontend/src/modules/content frontend/src/modules/leads
git commit -m "feat: explain DeepSeek recovery safely"
```

---

### Task 7: Administrator DeepSeek Settings Page and First-Run Guidance

**Files:**
- Create: `frontend/src/modules/aiSettings/api.ts`
- Create: `frontend/src/modules/aiSettings/DeepSeekSettingsPage.vue`
- Create: `frontend/src/modules/aiSettings/DeepSeekSettingsPage.test.ts`
- Modify: `frontend/src/app/router.ts`
- Modify: `frontend/src/app/router.test.ts`
- Modify: `frontend/src/main.ts`
- Modify: `frontend/src/app/AppShell.vue`
- Modify: `frontend/src/app/AppShell.test.ts`
- Modify: `frontend/src/shared/components/AppIcon.vue`
- Modify: `frontend/src/api/generated/schema.ts`

**Interfaces:**
- Consumes: Task 3 configuration endpoints and Task 4 usage summary.
- Produces advanced route `/ai-settings`, guarded by `credentials.manage`.
- Produces setup UI for test/save, retest, replace, delete, daily ceiling, timeout, output caps, safe connection status, and recent usage.
- Produces first-run administrator banner linking to settings; it does not block read-only work or ordinary navigation.

- [ ] **Step 1: Write failing page, permission, secret-lifecycle, and accessibility tests**

```ts
it("tests before saving and never redisplays the key", async () => {
  await user.type(screen.getByLabelText("DeepSeek API Key"), "sk-secret-1234")
  await user.click(screen.getByRole("button", { name: "测试并保存" }))
  expect(requestBody).toEqual({ api_key: "sk-secret-1234", ...safeLimits })
  expect(screen.queryByDisplayValue("sk-secret-1234")).not.toBeInTheDocument()
  expect(screen.getByText("已连接 · 尾号 1234")).toBeInTheDocument()
})
```

Cover Escape/backdrop/reset wiping the field, no query caching of mutation bodies, paste support, disabled duplicate submit, error focus, screen-reader status, administrator-only nav/route/API, organization switch clearing cached configuration, delete confirmation, failed replace retaining old connection metadata without retaining new key, mobile 390px layout, and no raw technical errors.

- [ ] **Step 2: Run and verify RED**

Run: `cd frontend && pnpm vitest run src/modules/aiSettings/DeepSeekSettingsPage.test.ts src/app/AppShell.test.ts src/app/router.test.ts`  
Expected: FAIL because the route/page does not exist.

- [ ] **Step 3: Generate the API artifact and implement the page**

Run `pnpm api:generate` only after backend schema tests pass. Use mutations rather than a query for any request containing a key, clear the input immediately after settlement, and never store it in Vue Query, local storage, URL, router state, error state, or telemetry. Configuration queries must be keyed by organization ID and removed on permission loss or organization change.

The page shows model policy as read-only Chinese explanations: “日常任务：快速模型” and “复杂任务：增强模型.” It does not expose arbitrary model strings or prompt editing.

- [ ] **Step 4: Run page, shell, contract, API, type, and build checks**

Run: `cd frontend && pnpm vitest run src/modules/aiSettings/DeepSeekSettingsPage.test.ts src/app/AppShell.test.ts src/app/router.test.ts src/app/ordinaryMode.contract.test.ts && pnpm typecheck && pnpm lint && pnpm build && pnpm api:check`  
Expected: PASS with no key in snapshots/output.

- [ ] **Step 5: Commit**

```powershell
git add frontend/src/modules/aiSettings frontend/src/app frontend/src/main.ts frontend/src/shared/components/AppIcon.vue frontend/src/api/generated/schema.ts
git commit -m "feat: add DeepSeek administrator setup"
```

---

### Task 8: Installer Credential Boundary and Operations Documentation

**Files:**
- Modify: `.env.example`
- Modify: `README.md`
- Create: `docs/operations/deepseek-windows-credentials.md`
- Create: `backend/apps/ai/management/commands/deepseek_smoke_test.py`
- Create: `backend/apps/ai/tests/test_deepseek_smoke_command.py`
- Modify: `docs/acceptance/ai-native-ui-redesign.md`

**Interfaces:**
- Produces: `python manage.py deepseek_smoke_test --organization-slug <slug> --acknowledge-paid-call`.
- Produces operational instructions for configure, test, rotate, delete, reinstall, uninstall, backup, and incident response without ever exporting the key.
- Consumed: Task 9 acceptance.

- [ ] **Step 1: Write failing command safety tests**

```python
def test_smoke_command_refuses_without_paid_acknowledgement(configured_org):
    with pytest.raises(CommandError, match="acknowledge-paid-call"):
        call_command("deepseek_smoke_test", organization_slug=configured_org.slug)

def test_smoke_output_never_prints_secret(configured_org, capsys):
    call_command("deepseek_smoke_test", ..., acknowledge_paid_call=True)
    assert "sk-secret" not in capsys.readouterr().out
```

Also assert the command refuses fake provider mode, missing configuration, unsupported credential backend, and interactive/ambiguous organization selection.

- [ ] **Step 2: Run and verify RED**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest apps\ai\tests\test_deepseek_smoke_command.py -q`  
Expected: FAIL because the command does not exist.

- [ ] **Step 3: Implement command and documentation**

The command performs one minimal Flash connection check, then optionally one representative schema-bound generation only when `--include-content-generation` is also supplied. Print run ID, model, thinking status, token usage, estimated cost, and pass/fail—not prompt contents, provider body, key target, suffix, or reasoning.

`.env.example` may contain only non-secret backend selectors and safe default ceilings. Explicitly state that `DEEPSEEK_API_KEY` is unsupported and ignored, preventing operators from normalizing secret storage in environment files.

- [ ] **Step 4: Run command, documentation leak scan, and launcher tests**

Run: `cd backend && .\.venv\Scripts\python.exe -m pytest apps\ai\tests\test_deepseek_smoke_command.py -q`  
Run: `rg -n "sk-[A-Za-z0-9_-]{12,}|DEEPSEEK_API_KEY\s*=|reasoning_content" . -g '!frontend/node_modules/**' -g '!backend/.venv/**'`  
Expected: tests pass; scan finds only explicit tests/design statements and no real-looking committed secret or persisted reasoning field.

- [ ] **Step 5: Commit**

```powershell
git add .env.example README.md docs/operations docs/acceptance backend/apps/ai/management backend/apps/ai/tests/test_deepseek_smoke_command.py
git commit -m "docs: define DeepSeek Windows operations"
```

---

### Task 9: Full Acceptance, Real Opt-In Smoke Test, and Git Handoff

**Files:**
- Create: `frontend/e2e/deepseek-settings.spec.ts`
- Modify: `frontend/e2e/launcher.mjs`
- Modify: `frontend/e2e/launcher.test.mjs`
- Create: `docs/acceptance/deepseek-v4-provider.md`
- Modify: `docs/project-handoff-2026-08-10.md`

**Interfaces:**
- Consumes all prior tasks.
- Produces deterministic browser coverage for administrator setup/recovery without paid calls.
- Produces an explicit manual record template for the one paid DeepSeek smoke test.
- Produces the final verified branch ready for Windows installer planning.

- [ ] **Step 1: Write failing isolated browser acceptance**

The E2E fake credential store must exist only inside the owned temporary run and must never access Windows Credential Manager. Mock DeepSeek at the transport boundary with cases for successful test/save, invalid key, insufficient balance, rate limit/retry display, configuration deletion, organization switch, permission removal, and ordinary content/lead success through the same orchestration contract.

```ts
test("administrator configures DeepSeek without the key reappearing", async ({ page }) => {
  await login(page, "phasea_e2e_admin")
  await page.getByRole("button", { name: "打开高级功能" }).click()
  await page.getByRole("link", { name: "AI服务设置" }).click()
  await page.getByLabel("DeepSeek API Key").fill("sk-e2e-only-not-real")
  await page.getByRole("button", { name: "测试并保存" }).click()
  await expect(page.getByText("已连接 · 尾号 real")).toBeVisible()
  await expect(page.locator("body")).not.toContainText("sk-e2e-only-not-real")
})
```

- [ ] **Step 2: Run the new E2E and verify RED**

Run: `cd frontend && pnpm playwright test e2e/deepseek-settings.spec.ts` through the owned launcher entry point.  
Expected: FAIL until launcher dependency injection and routes are complete.

- [ ] **Step 3: Complete isolated launcher injection and acceptance documentation**

Add an E2E-only in-memory credential adapter and HTTP mock selected by explicit guarded settings. The production registry must reject those adapters when the safety gate is false. Document exact automated results and a blank manual smoke record with fields for date, operator, organization, run ID, model, thinking flag, token usage, estimated cost, and outcome—never the key or raw prompt.

- [ ] **Step 4: Run complete verification**

Run:

```powershell
cd backend
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run
.\.venv\Scripts\python.exe manage.py spectacular --file openapi.yaml --validate

cd ..\frontend
pnpm vitest run
pnpm typecheck
pnpm lint
pnpm build
pnpm api:check
pnpm test:e2e:launcher
pnpm test:e2e
git diff --check
```

Expected: all free deterministic checks pass; no command accesses a real credential or paid endpoint.

- [ ] **Step 5: Run the explicit paid smoke test only with the user present**

After the user enters the key through the UI and explicitly approves a paid test, run:

```powershell
cd backend
.\.venv\Scripts\python.exe manage.py deepseek_smoke_test `
  --organization-slug <confirmed-slug> `
  --acknowledge-paid-call `
  --include-content-generation
```

Expected: one Flash connectivity call and one schema-bound content call succeed; audit displays `deepseek`, `deepseek-v4-flash`, thinking disabled, safe usage/cost, and no reasoning/key. If it fails, record the controlled category and stop—do not switch to fake or Pro.

- [ ] **Step 6: Commit final acceptance record**

```powershell
git add frontend/e2e docs/acceptance/deepseek-v4-provider.md docs/project-handoff-2026-08-10.md
git commit -m "test: accept DeepSeek V4 integration"
```

- [ ] **Step 7: Request final review and publish only after clean verification**

Use `superpowers:requesting-code-review`, address all Critical/Important findings, rerun affected plus full checks, then use `github:yeet` to push the feature branch. Do not merge, build the Windows installer, email completion, or shut down until the user approves the verified real-provider result.

