# Social OAuth Activation-Ready Foundation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Meta, LinkedIn, TikTok, and YouTube social OAuth activation-ready behind disabled-by-default configuration, encrypted token storage, lifecycle management, and safe owner-facing readiness without using real credentials or publishing live content.

**Architecture:** Add typed provider configuration, a secret resolver, an encrypted database token vault, and deterministic runtime factories around the existing authorization and publishing registries. Extend the provider-neutral contracts to YouTube and add refresh, reauthorization, probe, and disconnect lifecycle operations. Every external interaction remains behind injected fixture transports and all providers remain disabled by default.

**Tech Stack:** Django 5.2, Django REST Framework 3.16, Python 3.12, pyca/cryptography authenticated encryption, Celery, pytest/pytest-django, Vue 3, TypeScript, TanStack Query, Vitest, Playwright.

## Global Constraints

- Work only in `C:\Users\Administrator\Documents\网站\sinofgear-growth-engine`; do not modify the independent external-trade website.
- Preserve unrelated uncommitted asset/AI-understanding work. Never reset, delete, or overwrite it.
- Do not enter or use a real client identifier, client secret, access token, refresh token, authorization code, account cookie, password, callback domain verification, or live account.
- Do not make a live provider request, submit an app review, publish a live post, deploy production, change DNS, use a paid API, or delete business history.
- All providers remain disabled by default; incomplete configuration fails closed and never falls back to Demo/Fake.
- Tests use injected fixture transports only and assert that runtime construction makes zero network calls.
- Ordinary APIs, logs, audit events, browser storage, URLs after callback processing, and model fields never contain token or secret values.
- Keep human content approval, explicit publication, idempotency, failed-only retry, and manual package download unchanged.
- TikTok upload readiness and public direct-post readiness are separate. YouTube upload is unavailable until its provider is explicitly enabled.

---

## File Structure

- `backend/integrations/platforms/provider_config.py`: typed provider configuration and callback validation.
- `backend/integrations/platforms/secret_resolver.py`: disabled and fixture secret resolvers.
- `backend/integrations/platforms/encrypted_token_store.py`: authenticated encrypted credential persistence.
- `backend/integrations/platforms/runtime.py`: deterministic authorization/publishing registry assembly.
- `backend/integrations/platforms/youtube_authorization.py`, `youtube.py`: fixture-testable YouTube OAuth and upload adapter.
- `backend/apps/platforms/models.py`, `migrations/0007_encryptedoauthcredential.py`: encrypted credential envelopes and lifecycle status.
- `backend/apps/platforms/lifecycle.py`, `views.py`, `urls.py`, `serializers.py`: probe, reauthorize, and disconnect orchestration.
- `backend/apps/jobs/tasks.py`: bounded credential-refresh task.
- `backend/config/settings.py`, `.env.example`: disabled public configuration and secret references.
- `frontend/src/modules/growth/api.ts`, `PromotionPage.vue`, `growth-pages.css`: five-channel readiness and lifecycle actions.

### Task 1: Typed Provider Configuration and Secret Resolver

**Files:**
- Create: `backend/integrations/platforms/provider_config.py`
- Create: `backend/integrations/platforms/secret_resolver.py`
- Modify: `backend/config/settings.py`
- Modify: `.env.example`
- Test: `backend/integrations/platforms/tests/test_provider_config.py`
- Test: `backend/integrations/platforms/tests/test_secret_resolver.py`

**Interfaces:**
- Produces: `SocialProviderConfig(code, enabled, client_id, client_secret_reference, redirect_uri, scopes, api_version, audited)`.
- Produces: `load_provider_configs(raw: dict, *, allowed_origins: tuple[str, ...], test_mode: bool = False) -> dict[str, SocialProviderConfig]`.
- Produces: `SecretResolver.resolve(reference: str) -> SecretValue`.
- Produces: `DisabledSecretResolver` and `FixtureSecretResolver` whose values are redacted in `repr` and `str`.

- [ ] **Step 1: Write failing configuration tests**

Cover disabled defaults, missing client ID, missing secret reference, non-HTTPS callbacks, fragments, embedded credentials, wrong callback path, origin allow-list rejection, shared Meta configuration, TikTok audited flag, LinkedIn API version, and YouTube scope. Assert serialized configuration and exception text never contain fixture secret values.

```python
config = load_provider_configs(
    {"YOUTUBE": {"enabled": True, "client_id": "public-id", "client_secret_reference": "env://YOUTUBE_CLIENT_SECRET", "redirect_uri": "https://app.sinfogear.com/api/v1/platform-connections/YOUTUBE/callback", "scopes": ["https://www.googleapis.com/auth/youtube.upload"]}},
    allowed_origins=("https://app.sinfogear.com",),
)
assert config["YOUTUBE"].enabled is True
assert "secret" not in repr(config["YOUTUBE"]).lower()
```

- [ ] **Step 2: Verify RED**

Run from `backend`:

```powershell
.\.venv\Scripts\python.exe -m pytest integrations/platforms/tests/test_provider_config.py integrations/platforms/tests/test_secret_resolver.py -q
```

Expected: collection fails because the configuration and resolver modules do not exist.

- [ ] **Step 3: Implement minimal typed configuration and redacted secret values**

Require exact callback path `/api/v1/platform-connections/{CHANNEL}/callback`; Meta may serve Facebook and Instagram with one provider configuration. Production callbacks require HTTPS and an allowed origin. `FixtureSecretResolver` accepts only test-owned mappings. `DisabledSecretResolver.resolve` raises `ConnectorConfigurationRequired` without echoing the reference.

- [ ] **Step 4: Add disabled environment keys**

Add `SOCIAL_OAUTH_ALLOWED_ORIGINS`, provider client-secret reference keys, LinkedIn API version, TikTok audited flag, and YouTube configuration. Keep every `*_OAUTH_ENABLED=false`, every public identifier empty, and every secret reference empty in `.env.example`.

- [ ] **Step 5: Verify GREEN and regression**

```powershell
.\.venv\Scripts\python.exe -m pytest integrations/platforms/tests/test_provider_config.py integrations/platforms/tests/test_secret_resolver.py apps/platforms/tests/test_platform_connections_api.py -q
```

- [ ] **Step 6: Commit only Task 1 files**

```powershell
git add .env.example backend/config/settings.py backend/integrations/platforms/provider_config.py backend/integrations/platforms/secret_resolver.py backend/integrations/platforms/tests/test_provider_config.py backend/integrations/platforms/tests/test_secret_resolver.py
git commit -m "feat: add fail-closed social provider configuration"
```

### Task 2: Authenticated Encrypted Token Vault

**Files:**
- Modify: `backend/pyproject.toml`
- Modify: `backend/apps/platforms/models.py`
- Create: `backend/apps/platforms/migrations/0007_encryptedoauthcredential.py`
- Create: `backend/integrations/platforms/encrypted_token_store.py`
- Create: `backend/apps/platforms/management/commands/rotate_social_oauth_keys.py`
- Test: `backend/integrations/platforms/tests/test_encrypted_token_store.py`
- Test: `backend/apps/platforms/tests/test_rotate_social_oauth_keys.py`

**Interfaces:**
- Produces: `EncryptedOAuthCredential(reference, organization_id, actor_id, platform_code, account_binding, ciphertext, nonce, key_version, status, expires_at)`.
- Produces: `EncryptedDatabaseTokenStore(secret_resolver, key_reference, key_version, clock)` implementing existing `TokenStore.store/resolve/bind/delete`.
- Extends: `OAuthTokenSet` with `token_type`, `provider_scopes`, and safe expiry metadata while retaining redacted representation.

- [ ] **Step 1: Write failing vault tests**

Test round-trip storage, random nonces, organization/platform/attempt associated-data binding, selected-account binding, ciphertext tampering, wrong key, expired/disconnected references, key version mismatch, delete compensation, and absence of plaintext token fragments from all database character/binary fields, logs, `repr`, and exceptions.

```python
reference = store.store(OAuthTokenSet(access_token="fixture-access", refresh_token="fixture-refresh"), context)
row = EncryptedOAuthCredential.objects.get(reference=reference)
assert b"fixture-access" not in bytes(row.ciphertext)
assert store.resolve(reference).access_token == "fixture-access"
```

- [ ] **Step 2: Verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest integrations/platforms/tests/test_encrypted_token_store.py -q
```

- [ ] **Step 3: Add the encryption dependency and model**

Add a compatible `cryptography` dependency and use `AESGCM` authenticated encryption with a fresh 96-bit nonce. The encryption key must decode to 32 bytes and come only from `SecretResolver`. Store ciphertext and nonce as binary fields. Generate opaque references with at least 256 bits of randomness.

- [ ] **Step 4: Implement store, bind, resolve, delete, and explicit key rotation**

`bind` decrypts the short-lived bundle, selects only the candidate token, writes a new account-bound encrypted envelope, and invalidates the bundle reference only after the new row commits. `delete` marks rows unavailable and removes ciphertext without deleting publication history. Use database transactions and row locks for bind/delete.

Add `rotate_social_oauth_keys --from-version <old> --to-version <new> --new-key-reference <reference> --dry-run`. It must be organization-bounded when `--organization` is supplied, lock one bounded batch at a time, decrypt with the old resolver reference, rewrite with the new version and fresh nonce, continue idempotently after interruption, and print only row counts and opaque references. Tests cover dry-run, partial restart, wrong old key, organization isolation, and zero plaintext output.

- [ ] **Step 5: Verify GREEN and migration drift**

```powershell
.\.venv\Scripts\python.exe -m pytest integrations/platforms/tests/test_encrypted_token_store.py apps/platforms/tests/test_rotate_social_oauth_keys.py apps/platforms/tests/test_connection_sessions.py -q
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=config.test_settings
```

- [ ] **Step 6: Commit only Task 2 files**

```powershell
git add backend/pyproject.toml backend/apps/platforms/models.py backend/apps/platforms/migrations/0007_encryptedoauthcredential.py backend/apps/platforms/management/commands/rotate_social_oauth_keys.py backend/apps/platforms/tests/test_rotate_social_oauth_keys.py backend/integrations/platforms/encrypted_token_store.py backend/integrations/platforms/tests/test_encrypted_token_store.py
git commit -m "feat: add encrypted social credential vault"
```

### Task 3: Deterministic Runtime Assembly for Meta, LinkedIn, and TikTok

**Files:**
- Create: `backend/integrations/platforms/runtime.py`
- Modify: `backend/apps/platforms/views.py`
- Modify: `backend/apps/growth/publishing.py`
- Test: `backend/integrations/platforms/tests/test_runtime.py`
- Test: `backend/apps/platforms/tests/test_platform_connection_completion_api.py`
- Test: `backend/apps/growth/tests/test_publish_batches.py`

**Interfaces:**
- Produces: `SocialProviderRuntime(authorization_registry, connector_registry, token_store, readiness)`.
- Produces: `build_social_provider_runtime(configs, secret_resolver, token_store, transport_factory) -> SocialProviderRuntime`.
- Produces: `ProviderReadiness(authorization_ready, publishing_ready, status, safe_reason)`.

- [ ] **Step 1: Write failing assembly tests**

Prove disabled/incomplete providers are absent; configuration construction makes no network requests; Meta registers Facebook and Instagram separately for readiness while sharing one adapter; authorization readiness can be true while publishing readiness is false; TikTok upload-only/private-only does not claim public direct-post readiness; and no secret appears in the runtime representation.

- [ ] **Step 2: Verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest integrations/platforms/tests/test_runtime.py -q
```

- [ ] **Step 3: Implement factories and dependency injection**

Construct existing `MetaAuthorizationAdapter`, `LinkedInAuthorizationAdapter`, `TikTokAuthorizationAdapter`, `MetaConnector`, `LinkedInConnector`, and `TikTokConnector` only from validated configs and resolved secret values. Do not create a global live HTTP transport in tests. Expose one application runtime accessor that defaults to disabled resolver/token store when configuration is incomplete.

- [ ] **Step 4: Replace empty module globals with runtime dependencies**

Update the account callback and publication dispatch to resolve adapters/connectors through the assembled runtime. Preserve tests that inject fixture registries/stores. Never silently use Demo/Fake for `official_oauth` accounts.

- [ ] **Step 5: Verify GREEN and existing connector regressions**

```powershell
.\.venv\Scripts\python.exe -m pytest integrations/platforms/tests apps/platforms/tests/test_platform_connection_completion_api.py apps/growth/tests/test_publish_batches.py -q
```

- [ ] **Step 6: Commit only Task 3 files**

```powershell
git add backend/integrations/platforms/runtime.py backend/integrations/platforms/tests/test_runtime.py backend/apps/platforms/views.py backend/apps/platforms/tests/test_platform_connection_completion_api.py backend/apps/growth/publishing.py backend/apps/growth/tests/test_publish_batches.py
git commit -m "feat: assemble official social provider runtime"
```

### Task 4: YouTube OAuth and Upload Connector Boundary

**Files:**
- Create: `backend/integrations/platforms/youtube_authorization.py`
- Create: `backend/integrations/platforms/youtube.py`
- Create: `backend/integrations/platforms/tests/test_youtube_authorization.py`
- Create: `backend/integrations/platforms/tests/test_youtube.py`
- Modify: `backend/integrations/platforms/runtime.py`
- Modify: `backend/apps/platforms/views.py`
- Modify: `backend/apps/platforms/management/commands/seed_platforms.py`
- Test: `backend/apps/platforms/tests/test_platform_connections_api.py`

**Interfaces:**
- Produces: `YouTubeAuthorizationAdapter.complete(request) -> (ProviderCredentialBundle, list[ManagedPublishingAccount], tuple[str, ...])`.
- Produces: `YouTubeConnector.publish(request) -> OfficialPublishResult`.

- [ ] **Step 1: Write failing YouTube fixture tests**

Cover code exchange, refresh-token retention, channel discovery, no-channel rejection, upload scope readiness, safe errors, media validation, idempotent upload initialization, provider timeout, rate limit, and canonical `https://www.youtube.com/watch?v={id}` result. Use a fixture transport that records calls and never reaches the network.

- [ ] **Step 2: Verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest integrations/platforms/tests/test_youtube_authorization.py integrations/platforms/tests/test_youtube.py -q
```

- [ ] **Step 3: Implement minimal YouTube adapters**

Normalize authenticated YouTube channels into `ManagedPublishingAccount(channel="YOUTUBE", capabilities=("PUBLISH", "METRICS_READ"))`. Require an HTTPS media source or bounded server-owned asset stream consistent with existing connector media limits. Do not implement comments, livestreams, playlists, or analytics beyond the existing normalized result.

- [ ] **Step 4: Register YouTube as a first-class channel**

Add YouTube to platform seeding, connection list, runtime readiness, and provider configuration without changing other channel codes.

- [ ] **Step 5: Verify GREEN and seed idempotency**

```powershell
.\.venv\Scripts\python.exe -m pytest integrations/platforms/tests/test_youtube_authorization.py integrations/platforms/tests/test_youtube.py apps/platforms/tests/test_platform_connections_api.py apps/common/tests/test_seed_phase_a.py -q
```

- [ ] **Step 6: Commit only Task 4 files**

```powershell
git add backend/integrations/platforms/youtube_authorization.py backend/integrations/platforms/youtube.py backend/integrations/platforms/tests/test_youtube_authorization.py backend/integrations/platforms/tests/test_youtube.py backend/integrations/platforms/runtime.py backend/apps/platforms/views.py backend/apps/platforms/management/commands/seed_platforms.py backend/apps/platforms/tests/test_platform_connections_api.py
git commit -m "feat: add YouTube account and upload connector boundary"
```

### Task 5: Credential Lifecycle, Refresh Job, and Safe Administrator APIs

**Files:**
- Create: `backend/apps/platforms/lifecycle.py`
- Modify: `backend/apps/platforms/models.py`
- Create: `backend/apps/platforms/migrations/0008_socialaccount_connection_status.py`
- Modify: `backend/apps/platforms/serializers.py`
- Modify: `backend/apps/platforms/views.py`
- Modify: `backend/apps/platforms/urls.py`
- Modify: `backend/apps/jobs/tasks.py`
- Test: `backend/apps/platforms/tests/test_credential_lifecycle.py`
- Test: `backend/apps/platforms/tests/test_platform_lifecycle_api.py`
- Test: `backend/apps/jobs/tests/test_social_credential_refresh.py`

**Interfaces:**
- Produces: `probe_social_account`, `start_reauthorization`, `disconnect_social_account`, and `refresh_due_credentials`.
- Produces stable states `CONFIGURATION_REQUIRED`, `CONNECTED`, `REFRESH_DUE`, `REAUTHORIZATION_REQUIRED`, `INSUFFICIENT_CAPABILITY`, `PROVIDER_UNAVAILABLE`, and `DISCONNECTED`.

- [ ] **Step 1: Write failing lifecycle tests**

Cover permission and tenant isolation, refresh window, per-credential locking, idempotent retries, refresh-token rotation, provider unavailable, invalid grant, reauthorization without overwriting a valid credential, revoke success/failure, disconnect history retention, and redacted audit/log output.

- [ ] **Step 2: Verify RED**

```powershell
.\.venv\Scripts\python.exe -m pytest apps/platforms/tests/test_credential_lifecycle.py apps/platforms/tests/test_platform_lifecycle_api.py apps/jobs/tests/test_social_credential_refresh.py -q
```

- [ ] **Step 3: Implement lifecycle service and state persistence**

Add safe lifecycle status/timestamps without putting tokens or raw scopes on `SocialAccount`. Refresh uses the token vault and provider adapter under a row lock. Disconnect marks the account unavailable and preserves content, publication, click, attribution, and audit history.

- [ ] **Step 4: Add administrator actions and background refresh**

Add `POST /api/v1/social-accounts/{account_id}/probe`, `/reauthorize`, and `/disconnect`. Require `CanManageCredentials`, CSRF, organization ownership, and explicit disconnect confirmation. Add a bounded Celery task that calls the lifecycle service; do not add an automatic schedule that could contact providers while all providers are disabled.

- [ ] **Step 5: Verify GREEN and OpenAPI contract**

```powershell
.\.venv\Scripts\python.exe -m pytest apps/platforms/tests apps/jobs/tests/test_social_credential_refresh.py tests/test_openapi_contract.py -q
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=config.test_settings
```

- [ ] **Step 6: Commit only Task 5 files**

```powershell
git add backend/apps/platforms backend/apps/jobs/tasks.py backend/apps/jobs/tests/test_social_credential_refresh.py
git commit -m "feat: manage social credential lifecycle"
```

### Task 6: Five-Channel Owner Readiness and Lifecycle UI

**Files:**
- Modify: `frontend/src/modules/growth/api.ts`
- Modify: `frontend/src/modules/growth/PromotionPage.vue`
- Modify: `frontend/src/modules/growth/growth-pages.css`
- Modify: `frontend/src/modules/growth/GrowthWorkspacePages.test.ts`
- Modify: `frontend/src/api/generated/schema.ts`
- Test: `frontend/e2e/social-connection-readiness.spec.ts`

**Interfaces:**
- Consumes five-channel readiness and lifecycle endpoints.
- Produces plain Chinese states and actions without client-secret/token inputs.

- [ ] **Step 1: Write failing component tests**

Test Facebook, Instagram, LinkedIn, TikTok, and YouTube cards; disabled configuration; waiting for platform review; upload-only/private-only labels; connect, reauthorize, and disconnect actions; explicit disconnect confirmation; account-picker return; and zero ordinary-user secret fields.

- [ ] **Step 2: Verify RED**

```powershell
pnpm exec vitest run src/modules/growth/GrowthWorkspacePages.test.ts
```

- [ ] **Step 3: Implement minimal owner-facing UI**

Reuse existing promotion/account cards. Show only business language: “连接账号”, “等待平台审核”, “可上传草稿”, “仅私密发布”, “重新授权”, and “断开连接”. Do not add a developer console or ask ordinary users to paste credentials.

- [ ] **Step 4: Regenerate and check API types**

```powershell
pnpm api:generate
pnpm api:check
pnpm typecheck
```

- [ ] **Step 5: Add browser acceptance with fixture backend only**

The Playwright test signs in locally, opens `/promotion`, verifies five clean channel states, opens fixture authorization, returns to the account picker, confirms one fixture channel, refreshes the page, and verifies persistence. It must assert no publish endpoint was called.

- [ ] **Step 6: Verify GREEN**

```powershell
pnpm exec vitest run src/modules/growth/GrowthWorkspacePages.test.ts
pnpm test:e2e -- social-connection-readiness.spec.ts
pnpm lint
pnpm typecheck
pnpm build
```

- [ ] **Step 7: Commit only Task 6 files**

```powershell
git add frontend/src/modules/growth frontend/src/api/generated/schema.ts frontend/e2e/social-connection-readiness.spec.ts
git commit -m "feat: expose five-channel social connection readiness"
```

### Task 7: Full Verification and Activation Runbook

**Files:**
- Create: `docs/social-oauth-activation-runbook.md`
- Modify only if required by verified failures: files already in Tasks 1-6.

- [ ] **Step 1: Write the activation runbook**

Document the exact future order: deploy stable HTTPS, configure `app.sinfogear.com`, create provider applications, register callback URLs/privacy/terms/deletion URLs, store secrets in a production secret manager, set only references/public IDs, complete sandbox review, enable one provider, authorize one company account, and separately confirm the first real publication. State that this work performs none of those actions.

- [ ] **Step 2: Run full backend verification**

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m ruff check .
.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=config.test_settings
```

- [ ] **Step 3: Run full frontend verification**

```powershell
pnpm test -- --run
pnpm test:e2e
pnpm lint
pnpm typecheck
pnpm api:check
pnpm build
```

- [ ] **Step 4: Audit the repository for secret leakage and external activation**

```powershell
rg -n "access_token|refresh_token|client_secret|BEGIN PRIVATE KEY|Bearer " backend frontend .env.example
git diff --check
git status --short
```

Review every match and prove it is a field name, redaction test, or fixture—not a live value. Confirm every `*_OAUTH_ENABLED` example remains `false` and no production DNS/deployment file changed.

- [ ] **Step 5: Record evidence and commit**

Add exact commands, pass counts, build result, browser acceptance result, remaining external activation gates, and unrelated pre-existing worktree changes to the runbook.

```powershell
git add docs/social-oauth-activation-runbook.md
git commit -m "docs: add social oauth activation runbook"
```

- [ ] **Step 6: Stop before external activation**

Do not request or enter real credentials. Report that the activation-ready foundation is locally verified and list the external steps that still require the owner: DNS/TLS, provider developer accounts, app review, production secret manager, real OAuth consent, and first real publication approval.
