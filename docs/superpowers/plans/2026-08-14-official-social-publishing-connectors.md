# Official Social Publishing Connectors Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add safe, testable official Meta, TikTok, and LinkedIn publishing connector boundaries and account-readiness APIs, then route the existing one-click growth batch through the correct adapter without performing live OAuth or live publication.

**Architecture:** Keep the current growth batch API and UI. Add organization-scoped authorization-attempt/readiness state to `platforms`, provider-neutral HTTP and token-store interfaces under `integrations/platforms`, fixture-tested official adapters, and a registry that fails closed when real configuration is absent. Growth publishing resolves one account and one adapter per channel; Demo accounts remain explicitly Fake.

**Tech Stack:** Django 5.2, Django REST Framework 3.16, Python 3.12 standard-library HTTP interfaces, pytest/pytest-django, Vue 3, TypeScript, TanStack Query, Vitest, Playwright.

## Global Constraints

- Work only in `C:\Users\Administrator\Documents\网站\sinofgear-growth-engine`; never enter, modify, build, test, or integrate the sibling `app` repository.
- Do not enter any real client ID, client secret, token, cookie, password, verification code, OAuth session, or live platform account.
- Do not make a live social API request or publish a real post during implementation or tests.
- A real account must never fall back to Fake; Demo/Fake output must never be represented as a real platform result.
- Only human-approved packages are eligible for publication; OAuth completion alone never publishes content.
- Ordinary-user UI must not expose connector classes, scopes, client IDs, tokens, API versions, raw provider errors, prompts, or campaign internals.
- Retain manual package download, batch idempotency, per-channel failure isolation, and failed-only retry.
- TikTok remains first-class and must preserve its creator-info/explicit-consent/public-vs-private audit restrictions.
- All tests use injected transports and fixtures; no test depends on internet access.

---

## File Structure

- `backend/apps/platforms/models.py`: organization-scoped OAuth attempt and safe connection readiness state.
- `backend/apps/platforms/oauth.py`: state generation/verification and authorization orchestration.
- `backend/apps/platforms/connection_status.py`: provider-neutral readiness summaries.
- `backend/apps/platforms/serializers.py`, `views.py`, `urls.py`: safe management API.
- `backend/integrations/platforms/base.py`: normalized connector/transport/token contracts.
- `backend/integrations/platforms/meta.py`: Facebook Page and Instagram Professional payloads.
- `backend/integrations/platforms/tiktok.py`: creator-info and Direct Post contract.
- `backend/integrations/platforms/linkedin.py`: versioned organization Posts contract.
- `backend/integrations/platforms/registry.py`: fail-closed account-to-adapter resolution.
- `backend/apps/growth/publishing.py`: existing batch integration only; provider logic stays outside growth.
- `frontend/src/modules/growth/api.ts`, `PromotionPage.vue`, `growth-pages.css`: safe channel connection states and recovery controls.

### Task 1: Safe OAuth Attempt and Connection Readiness Domain

**Files:**
- Modify: `backend/apps/platforms/models.py`
- Create: `backend/apps/platforms/migrations/0004_oauthconnectionattempt.py`
- Create: `backend/apps/platforms/oauth.py`
- Create: `backend/apps/platforms/connection_status.py`
- Test: `backend/apps/platforms/tests/test_oauth_state.py`
- Test: `backend/apps/platforms/tests/test_connection_status.py`

**Interfaces:**
- Produces: `create_authorization_attempt(*, organization, actor, platform, return_path) -> AuthorizationStart`
- Produces: `consume_authorization_attempt(*, raw_state, actor, platform_code) -> OAuthConnectionAttempt`
- Produces: `connection_summary(*, organization, platform_code) -> ConnectionSummary`
- `AuthorizationStart` contains only `attempt_id`, one-time `raw_state`, and `expires_at`.
- `ConnectionSummary.status` is exactly `NOT_CONNECTED`, `CONNECTED`, `REAUTHORIZATION_REQUIRED`, or `CONFIGURATION_REQUIRED`.

- [ ] **Step 1: Write failing state lifecycle tests**

Add tests proving state is 32+ bytes, only a SHA-256 hash is stored, TTL is 10 minutes, exact return paths must begin with `/`, and consumption rejects wrong actor, organization-bound account context, provider, expiry, reuse, and absolute/external return URLs.

```python
start = create_authorization_attempt(
    organization=organization, actor=admin, platform=meta,
    return_path="/promotion",
)
attempt = OAuthConnectionAttempt.objects.get(pk=start.attempt_id)
assert attempt.state_hash == hashlib.sha256(start.raw_state.encode()).hexdigest()
assert start.raw_state not in attempt.state_hash
assert consume_authorization_attempt(
    raw_state=start.raw_state, actor=admin, platform_code="META",
).consumed_at is not None
```

- [ ] **Step 2: Run the focused tests and verify RED**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/apps/platforms/tests/test_oauth_state.py backend/apps/platforms/tests/test_connection_status.py -q`

Expected: collection/import failure because the model and services do not exist.

- [ ] **Step 3: Implement the model and state service**

Add `OAuthConnectionAttempt` with UUID primary key, organization FK, actor FK, platform FK, `state_hash`, `return_path`, `pkce_verifier_reference`, `expires_at`, `consumed_at`, and timestamps. Add uniqueness on `state_hash` and indexes for organization/platform/expiry. Use `secrets.token_urlsafe(32)`, `hashlib.sha256`, `secrets.compare_digest`, `timezone.now() + timedelta(minutes=10)`, row locking, and one-time consumption.

Readiness must inspect `SocialAccount.status`, `publish_mode`, credential presence/expiry, and connector metadata `connection_kind`. Test fixtures with `connection_kind="demo_fake"` remain connected only in Demo mode; official accounts require a credential reference.

- [ ] **Step 4: Run focused tests and migration drift check**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/apps/platforms/tests/test_oauth_state.py backend/apps/platforms/tests/test_connection_status.py -q`

Run: `backend\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run`

Expected: all focused tests pass and no model changes remain.

- [ ] **Step 5: Commit**

```text
git add backend/apps/platforms
git commit -m "feat: add safe platform authorization state"
```

### Task 2: Provider-Neutral Connector Contracts and Official Fixture Adapters

**Files:**
- Modify: `backend/integrations/platforms/base.py`
- Create: `backend/integrations/platforms/transport.py`
- Create: `backend/integrations/platforms/token_store.py`
- Create: `backend/integrations/platforms/meta.py`
- Create: `backend/integrations/platforms/tiktok.py`
- Create: `backend/integrations/platforms/linkedin.py`
- Create: `backend/integrations/platforms/registry.py`
- Test: `backend/integrations/platforms/tests/test_meta.py`
- Test: `backend/integrations/platforms/tests/test_tiktok.py`
- Test: `backend/integrations/platforms/tests/test_linkedin.py`
- Test: `backend/integrations/platforms/tests/test_registry.py`

**Interfaces:**
- Produces: `OfficialPublishRequest(channel, account_external_id, payload, idempotency_key, consent)`.
- Produces: `OfficialPublishResult(status, external_id, external_url, error_code, retryable, retry_after_seconds)`.
- Produces: `ConnectorRegistry.resolve(account) -> OfficialConnector | ManualPackageFakeConnector`.
- `HttpTransport.request(method, url, *, headers, json, timeout_seconds) -> HttpResponse` is injected.
- `TokenStore.resolve(reference) -> OAuthTokenSet` is injected; default disabled store raises `ConnectorConfigurationRequired`.

- [ ] **Step 1: Write failing adapter contract tests**

Test each adapter with a recording transport. Assert exact official host/path, authorization header redaction from exceptions, payload normalization, idempotency propagation where supported, and normalized handling of 200/201, 400 validation, 401 expiry, 403 scope, 429 retry timing, 5xx, and timeout.

TikTok tests must assert creator-info is queried before Direct Post, explicit consent fields are required, and an unaudited client cannot return a public result. LinkedIn tests must assert organization author URN plus configured `LinkedIn-Version` and `X-Restli-Protocol-Version: 2.0.0`. Meta tests must distinguish Facebook Page feed publishing from Instagram media-container creation/status/publish.

- [ ] **Step 2: Run adapter tests and verify RED**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/integrations/platforms/tests/test_meta.py backend/integrations/platforms/tests/test_tiktok.py backend/integrations/platforms/tests/test_linkedin.py backend/integrations/platforms/tests/test_registry.py -q`

Expected: import failures for the new connector modules.

- [ ] **Step 3: Implement minimal contracts and adapters**

Use dataclasses and typed protocols. Do not add a general-purpose SDK dependency. Adapters accept only injected transport/token store/config; module import and constructor perform no network access. Stable error codes are `CONFIGURATION_REQUIRED`, `REAUTHORIZATION_REQUIRED`, `VALIDATION_REJECTED`, `RATE_LIMITED`, `PROVIDER_UNAVAILABLE`, and `OUTCOME_UNKNOWN`.

The registry rules are exact:

```python
if account.connector_metadata.get("connection_kind") == "demo_fake":
    return ManualPackageFakeConnector()
if account.connector_metadata.get("connection_kind") != "official_oauth":
    raise ConnectorConfigurationRequired
return official_connector_for(account.platform.code)
```

- [ ] **Step 4: Run adapter and existing Fake tests**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/integrations/platforms/tests -q`

Expected: all integration adapter tests pass; Fake connector still refuses real publication.

- [ ] **Step 5: Commit**

```text
git add backend/integrations/platforms
git commit -m "feat: add official social connector adapters"
```

### Task 3: Safe Platform Connection API

**Files:**
- Modify: `backend/apps/platforms/serializers.py`
- Modify: `backend/apps/platforms/views.py`
- Modify: `backend/apps/platforms/urls.py`
- Create: `backend/apps/platforms/tests/test_platform_connections_api.py`
- Modify: `backend/config/settings.py`
- Modify: `backend/config/test_settings.py`

**Interfaces:**
- Produces: `GET /api/v1/platform-connections`.
- Produces: `POST /api/v1/platform-connections/{platform_code}/authorize`.
- Authorization response contains `status`, `authorization_url`, and `expires_at`; it never contains client secret, state hash, token, credential ID, or raw scopes.
- Provider settings default to disabled and are read from environment only.

- [ ] **Step 1: Write failing connection API tests**

Prove publishing readers can list safe summaries, only `credentials.manage` can start authorization, unknown fields are rejected, disabled provider returns 409 `CONFIGURATION_REQUIRED`, enabled fixture config returns an official HTTPS authorization URL containing one-time state, cross-organization state cannot be used, and OpenAPI includes both paths without secret schemas.

- [ ] **Step 2: Run focused API tests and verify RED**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/apps/platforms/tests/test_platform_connections_api.py -q`

Expected: 404 because platform connection routes do not exist.

- [ ] **Step 3: Implement serializers, views, routes, and disabled-by-default settings**

Use strict serializers. Return only ordinary readiness labels and recovery actions. The authorize endpoint creates state only after provider application configuration is present. Callback code may be implemented as a fixture-tested service entry point, but no live callback route is activated without an HTTPS public base URL.

- [ ] **Step 4: Run platform API suite and schema generation**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/apps/platforms/tests -q`

Run: `backend\.venv\Scripts\python.exe manage.py spectacular --file ..\frontend\openapi-schema.yml --validate`

Expected: tests pass and schema validation succeeds without credential material.

- [ ] **Step 5: Commit**

```text
git add backend/apps/platforms backend/config frontend/openapi-schema.yml
git commit -m "feat: expose safe platform connection readiness"
```

### Task 4: Route Growth One-Click Batches Through the Registry

**Files:**
- Modify: `backend/apps/growth/publishing.py`
- Modify: `backend/apps/growth/serializers.py`
- Modify: `backend/apps/growth/tests/test_publish_batches.py`
- Modify: `backend/tests/test_growth_workspace_api.py`

**Interfaces:**
- Consumes: `ConnectorRegistry.resolve(account)` and normalized official results from Task 2.
- Produces: publish item fields `mode`, `error_code`, `retryable`, and `recovery_action` while preserving existing fields.
- Keeps `create_publish_batch(...)` and `retry_failed_items(...)` public signatures unchanged.

- [ ] **Step 1: Write failing mixed-mode batch tests**

Prove exactly one active account is required; Demo/Fake continues to work; official fixture success is labeled real only when the package is non-Demo; missing provider config becomes configuration-required; expired authorization is not retried; rate limit is retryable; successful items are never replayed; and an official account can never invoke `simulate_publish`.

- [ ] **Step 2: Run growth publishing tests and verify RED**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/apps/growth/tests/test_publish_batches.py backend/tests/test_growth_workspace_api.py -q`

Expected: new official-account cases fail because growth currently filters on the E2E fixture and calls Fake directly.

- [ ] **Step 3: Implement registry routing and normalized result persistence**

Remove the `connector_metadata__fixture="phase-a-e2e"` selection filter. Resolve exactly one active account by organization/platform. Build a provider-neutral request from the immutable payload snapshot and batch idempotency key. Fail closed on Demo/real mismatch. Persist only redacted stable errors and provider post identifiers/URLs.

- [ ] **Step 4: Run growth, publishing, and integration suites**

Run: `backend\.venv\Scripts\python.exe -m pytest backend/apps/growth backend/apps/publishing backend/integrations/platforms backend/tests/test_growth_workspace_api.py -q`

Expected: all tests pass, including existing partial failure and Fake behavior.

- [ ] **Step 5: Commit**

```text
git add backend/apps/growth backend/tests/test_growth_workspace_api.py
git commit -m "feat: route one-click batches through connector registry"
```

### Task 5: Factory-Owner Connection States on Promotion Page

**Files:**
- Modify: `frontend/src/modules/growth/api.ts`
- Modify: `frontend/src/modules/growth/PromotionPage.vue`
- Modify: `frontend/src/modules/growth/growth-pages.css`
- Modify: `frontend/src/modules/growth/GrowthWorkspacePages.test.ts`

**Interfaces:**
- Consumes: safe `connection_status`, `connection_label`, and `recovery_action` fields only.
- Produces: per-channel labels `未连接`, `已连接`, and `需要重新授权` plus `连接账号`/`重新连接` actions.
- Existing one-click batch API usage remains unchanged.

- [ ] **Step 1: Write failing UI behavior tests**

Render four channel cards with mixed readiness. Assert no token/scope/API/version words appear; connected approved channels are eligible; disconnected channels retain download fallback; clicking connect calls the safe authorize endpoint but never publishes; the page clearly retains `Demo / Fake` when all seeded connections are fake.

- [ ] **Step 2: Run focused frontend tests and verify RED**

Run: `npm test -- --run src/modules/growth/GrowthWorkspacePages.test.ts`

Working directory: `frontend`

Expected: connection labels/actions are absent.

- [ ] **Step 3: Implement minimal UI and typed API**

Keep the existing card layout and primary one-click button. Add small status rows inside each existing channel card; do not add a settings dashboard. For a returned authorization URL, require an exact `https:` URL and navigate only from a direct user click. In disabled/local mode, show the returned recovery message and leave Fake/manual operation intact.

- [ ] **Step 4: Run frontend tests, typecheck, lint, and build**

Run: `npm test -- --run src/modules/growth/GrowthWorkspacePages.test.ts`

Run: `npm run typecheck`

Run: `npm run lint`

Run: `npm run build`

Working directory: `frontend`

Expected: every command passes.

- [ ] **Step 5: Commit**

```text
git add frontend/src/modules/growth
git commit -m "feat: show official channel connection readiness"
```

### Task 6: Full Verification and Acceptance Record

**Files:**
- Modify: `docs/acceptance/2026-08-14-growth-workspace.md`
- Modify: `.env.example`

**Interfaces:**
- Documents provider configuration names without values and records exact verification results.
- Does not activate a real provider or include any secret-shaped example.

- [ ] **Step 1: Document disabled provider configuration and activation gates**

List boolean enable flags, public callback base URL requirement, secret-manager references, platform review/audit prerequisites, and the explicit approval requirement for first live OAuth and first live post. Keep all example values empty or disabled.

- [ ] **Step 2: Run complete backend verification**

Run: `backend\.venv\Scripts\python.exe -m pytest -q`

Run: `backend\.venv\Scripts\python.exe -m ruff check .`

Run: `backend\.venv\Scripts\python.exe manage.py check`

Run: `backend\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run`

Working directory: `backend`

- [ ] **Step 3: Run complete frontend verification**

Run: `npm test -- --run`

Run: `npm run typecheck`

Run: `npm run lint`

Run: `npm run build`

Working directory: `frontend`

- [ ] **Step 4: Run local browser acceptance**

Verify `/promotion` displays the existing card hierarchy, four connection states, Demo/Fake execution by default, approved-channel one-click publishing, isolated failure, failed-only retry, reload persistence, and manual download fallback. Assert no live external social request appears.

- [ ] **Step 5: Record evidence and commit**

Update the acceptance document with exact command totals and browser observations, then run `git diff --check` and confirm `git status --short` contains only the intended acceptance/config documentation before committing.

```text
git add .env.example docs/acceptance/2026-08-14-growth-workspace.md
git commit -m "test: verify official connector preparation"
```
