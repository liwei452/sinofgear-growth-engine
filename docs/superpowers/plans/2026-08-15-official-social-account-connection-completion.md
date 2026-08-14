# Official Social Account Connection Completion Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete a fixture-tested OAuth callback, manageable-account discovery, explicit account selection, and opaque credential persistence flow for Meta, LinkedIn, and TikTok without opening a live authorization or publishing a live post.

**Architecture:** Extend the existing one-time OAuth attempt with a separate 10-minute account-connection session. Provider authorization adapters exchange fixture codes and normalize manageable accounts behind injected interfaces; an injected token store returns only opaque references. Callback completion creates a short-lived session, and an explicit confirmation transaction creates or updates the official social account and credential. The existing promotion page consumes only safe candidate summaries and connection status.

**Tech Stack:** Django 5.2, Django REST Framework 3.16, Python 3.12 dataclasses/protocols, pytest/pytest-django, Vue 3, TypeScript, TanStack Query, Vitest.

## Global Constraints

- Work only in `C:\Users\Administrator\Documents\网站\sinofgear-growth-engine`; never enter, modify, build, test, or integrate `C:\Users\Administrator\Documents\网站\app`.
- Do not enter or use a real client identifier, client secret, authorization code, token, cookie, password, callback domain, verification code, OAuth session, or live platform account.
- Do not make a live provider request or publish a live post. Every provider exchange and discovery test uses injected fixture transports.
- OAuth completion only prepares account selection. It never approves content, creates a publish batch, or invokes publication.
- Tokens and token-store references never appear in ordinary API responses, logs, browser storage, redirect query strings, or audit payloads.
- Real accounts never fall back to Demo/Fake, and Demo/Fake output is never represented as real.
- Preserve the existing five-item navigation, promotion card hierarchy, human content approval, one-click publication action, manual package download, idempotency, and failed-only retry.
- TikTok remains first-class; an unaudited application is private-only and cannot claim public publishing readiness.

---

## File Structure

- `backend/apps/platforms/models.py`: add the short-lived organization- and actor-scoped connection session.
- `backend/apps/platforms/migrations/0006_accountconnectionsession.py`: create session storage and indexes.
- `backend/apps/platforms/connection_sessions.py`: validate candidates, create/read/expire sessions, and atomically confirm a selected account.
- `backend/integrations/platforms/authorization.py`: provider-neutral exchange, discovery, candidate, and normalized outcome contracts.
- `backend/integrations/platforms/token_store.py`: extend the injected token-store interface with `store` and `delete`.
- `backend/integrations/platforms/meta_authorization.py`: fixture-testable Meta Page and Instagram Business discovery.
- `backend/integrations/platforms/linkedin_authorization.py`: fixture-testable organization administrator discovery.
- `backend/integrations/platforms/tiktok_authorization.py`: fixture-testable creator capability discovery.
- `backend/integrations/platforms/authorization_registry.py`: fail-closed provider authorization adapter resolution.
- `backend/apps/platforms/serializers.py`, `views.py`, `urls.py`: callback, safe session summary, and explicit confirmation APIs.
- `frontend/src/modules/growth/api.ts`: typed safe connection-session API.
- `frontend/src/modules/growth/PromotionPage.vue`: compact account picker in the existing promotion page.
- `frontend/src/modules/growth/growth-pages.css`: minimal picker styling within the current visual system.

### Task 1: Account Connection Session Domain and Opaque Token Store

**Files:**
- Modify: `backend/apps/platforms/models.py`
- Create: `backend/apps/platforms/migrations/0006_accountconnectionsession.py`
- Create: `backend/apps/platforms/connection_sessions.py`
- Modify: `backend/integrations/platforms/token_store.py`
- Test: `backend/apps/platforms/tests/test_connection_sessions.py`
- Test: `backend/integrations/platforms/tests/test_token_store.py`

**Interfaces:**
- Produces: `ConnectionCandidate(candidate_id, external_id, display_name, channel, capabilities, discovered_at)` as the strict session-domain value converted from provider discovery output.
- Produces: `create_connection_session(*, organization, actor, platform, secret_reference, candidates, granted_capabilities) -> AccountConnectionSession`.
- Produces: `get_connection_session(*, session_id, organization, actor) -> AccountConnectionSession`.
- Produces: `confirm_connection_session(*, session, candidate_id) -> SocialAccount`.
- Produces: `TokenStoreContext(organization_id, actor_id, platform_code, attempt_id)`.
- Extends: `TokenStore.store(token_set, context: TokenStoreContext) -> str` and `TokenStore.delete(reference) -> None` while retaining `resolve(reference)`.

- [ ] **Step 1: Write failing session lifecycle tests**

Add tests proving the session lifetime is exactly 10 minutes; actor and organization isolation; a maximum of 100 unique candidates; strict supported channels; bounded identifier/display-name values; internal capability validation; expired and consumed-session rejection; and absence of raw tokens in persisted JSON.

```python
session = create_connection_session(
    organization=organization,
    actor=admin,
    platform=meta,
    secret_reference="vault://fixture/abc",
    candidates=[facebook_page],
    granted_capabilities=["PUBLISH"],
)
assert session.expires_at == session.created_at + timedelta(minutes=10)
assert "token" not in json.dumps(session.candidates).lower()
```

- [ ] **Step 2: Run focused tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest apps/platforms/tests/test_connection_sessions.py integrations/platforms/tests/test_token_store.py -q`

Working directory: `backend`

Expected: collection fails because `AccountConnectionSession` and the new interfaces do not exist.

- [ ] **Step 3: Implement the model, migration, validation service, and token-store contract**

Add an organization-scoped model with actor/platform foreign keys, `secret_reference`, bounded candidate JSON, validated internal capabilities, `expires_at`, `consumed_at`, and `confirmed_candidate_id`. Add an organization/platform/expiry index. Define `TokenStoreContext` using UUID/string identifiers only. Keep default token storage disabled: `store`, `resolve`, and `delete` all raise `ConnectorConfigurationRequired` without inspecting or returning token material.

- [ ] **Step 4: Implement atomic confirmation**

Inside one `transaction.atomic()` block, lock the session, validate actor/organization/expiry/consumption and exact candidate membership, create or update one `ConnectorCredential`, create or update one `SocialAccount` with `connection_kind="official_oauth"`, set `publish_mode=API_CONFIRM`, and mark the session consumed. Same-candidate replay returns the already connected account; a different candidate returns `CONNECTION_SESSION_CONSUMED`.

- [ ] **Step 5: Run focused tests and migration drift check**

Run: `.\.venv\Scripts\python.exe -m pytest apps/platforms/tests/test_connection_sessions.py integrations/platforms/tests/test_token_store.py -q`

Run: `.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=config.test_settings`

Working directory: `backend`

Expected: focused tests pass and no model changes remain.

- [ ] **Step 6: Commit**

```text
git add backend/apps/platforms backend/integrations/platforms/token_store.py
git commit -m "feat: add safe account connection sessions"
```

### Task 2: Fixture Authorization Exchange and Manageable Account Discovery

**Files:**
- Create: `backend/integrations/platforms/authorization.py`
- Create: `backend/integrations/platforms/meta_authorization.py`
- Create: `backend/integrations/platforms/linkedin_authorization.py`
- Create: `backend/integrations/platforms/tiktok_authorization.py`
- Create: `backend/integrations/platforms/authorization_registry.py`
- Test: `backend/integrations/platforms/tests/test_meta_authorization.py`
- Test: `backend/integrations/platforms/tests/test_linkedin_authorization.py`
- Test: `backend/integrations/platforms/tests/test_tiktok_authorization.py`
- Test: `backend/integrations/platforms/tests/test_authorization_registry.py`

**Interfaces:**
- Produces: `AuthorizationCompletion(code, redirect_uri, pkce_reference)`.
- Produces: `ManagedPublishingAccount(external_id, display_name, channel, capabilities, discovered_at)`.
- Produces: `ProviderAuthorizationAdapter.complete(request) -> tuple[OAuthTokenSet, list[ManagedPublishingAccount], list[str]]`.
- Produces: `AuthorizationAdapterRegistry.resolve(platform_code) -> ProviderAuthorizationAdapter`.

- [ ] **Step 1: Write failing provider adapter tests**

Use recording transports and fixture responses. Assert Meta separates Facebook Page and linked Instagram Business candidates; LinkedIn keeps only organizations with the required administrative role; TikTok queries creator information and marks unaudited clients private-only. Assert provider bodies, access tokens, authorization codes, and authorization headers are absent from normalized exceptions.

- [ ] **Step 2: Run provider tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest integrations/platforms/tests/test_meta_authorization.py integrations/platforms/tests/test_linkedin_authorization.py integrations/platforms/tests/test_tiktok_authorization.py integrations/platforms/tests/test_authorization_registry.py -q`

Working directory: `backend`

Expected: import failures for the new authorization modules.

- [ ] **Step 3: Implement provider-neutral contracts and normalized failures**

Define stable failures `AUTHORIZATION_REJECTED`, `REAUTHORIZATION_REQUIRED`, `NO_MANAGEABLE_ACCOUNT`, `INSUFFICIENT_CAPABILITY`, `PROVIDER_UNAVAILABLE`, and `CONFIGURATION_REQUIRED`. Adapters receive only injected transport plus public provider configuration; constructors and imports perform no network access.

- [ ] **Step 4: Implement Meta, LinkedIn, TikTok fixture adapters and fail-closed registry**

Normalize candidates to internal channels and capabilities. Reject duplicate identifiers per channel, over-limit candidates, unsupported account types, missing publishing capability, and malformed discovery timestamps. The registry raises `ConnectorConfigurationRequired` when no injected adapter exists.

- [ ] **Step 5: Run all platform integration tests**

Run: `.\.venv\Scripts\python.exe -m pytest integrations/platforms/tests -q`

Working directory: `backend`

Expected: new authorization tests and existing publication-adapter tests all pass with no internet access.

- [ ] **Step 6: Commit**

```text
git add backend/integrations/platforms
git commit -m "feat: add official account discovery adapters"
```

### Task 3: Callback, Safe Session Summary, and Explicit Confirmation APIs

**Files:**
- Modify: `backend/apps/platforms/serializers.py`
- Modify: `backend/apps/platforms/views.py`
- Modify: `backend/apps/platforms/urls.py`
- Create: `backend/apps/platforms/tests/test_platform_connection_completion_api.py`
- Modify: `backend/config/settings.py`

**Interfaces:**
- Produces: `GET /api/v1/platform-connections/{platform_code}/callback`.
- Produces: `GET /api/v1/platform-connection-sessions/{session_id}`.
- Produces: `POST /api/v1/platform-connection-sessions/{session_id}/confirm`.
- Consumes: the authorization registry, injected token store, and Task 1 session services.

- [ ] **Step 1: Write failing API tests**

Prove the callback requires authenticated actor identity and credential-management permission; consumes exact state once; rejects disabled provider, denial, missing code/state, wrong actor/provider, expiry, unsafe return paths, and no manageable account; compensates token-store writes when session persistence fails; and redirects only to a safe local path containing `connection_session` plus a stable status.

Prove session read/confirmation is tenant- and actor-isolated, returns only safe candidate fields, rejects unknown request fields, performs no publication request, confirms one candidate atomically, supports same-candidate idempotent replay, and never returns code/state/token/reference/scope/provider payload.

- [ ] **Step 2: Run focused API tests and verify RED**

Run: `.\.venv\Scripts\python.exe -m pytest apps/platforms/tests/test_platform_connection_completion_api.py -q`

Working directory: `backend`

Expected: 404 for the three missing routes.

- [ ] **Step 3: Implement strict serializers and callback orchestration**

Add query serializers for exact `code`, `state`, and stable provider error values. Callback order is: validate configuration → consume attempt → exchange/discover → convert each `ManagedPublishingAccount` to a strict `ConnectionCandidate` → store token set with `TokenStoreContext` → create session → redirect safely. If any step after `store` fails, call `delete(reference)`. Return provider-neutral Chinese recovery messages without provider text.

- [ ] **Step 4: Implement safe session read and confirmation views**

Return only session UUID, platform label, expiry, and candidate identifier/display name/channel/capability labels. Confirmation accepts only `candidate_id`, calls the locked service, and returns the existing safe connection-summary shape. OAuth completion and confirmation must not import or call growth publishing services.

- [ ] **Step 5: Run platform API, permission, schema, and lint tests**

Run: `.\.venv\Scripts\python.exe -m pytest apps/platforms/tests -q`

Run: `.\.venv\Scripts\python.exe -m ruff check apps/platforms integrations/platforms config`

Run: `.\.venv\Scripts\python.exe manage.py spectacular --file NUL --validate --settings=config.test_settings`

Working directory: `backend`

Expected: tests and lint pass; schema includes all three routes and contains no secret schema fields.

- [ ] **Step 6: Commit**

```text
git add backend/apps/platforms backend/config/settings.py
git commit -m "feat: complete safe platform account connection api"
```

### Task 4: Compact Account Picker on the Promotion Page

**Files:**
- Modify: `frontend/src/modules/growth/api.ts`
- Modify: `frontend/src/modules/growth/PromotionPage.vue`
- Modify: `frontend/src/modules/growth/growth-pages.css`
- Modify: `frontend/src/modules/growth/GrowthWorkspacePages.test.ts`

**Interfaces:**
- Consumes: `connection_session` from the safe local URL and the session read/confirm APIs.
- Produces: a compact “选择要用于发布的账号” card and explicit “使用此账号” action.
- Preserves: existing authorize action, content approval, one-click batch, retry, and manual download behavior.

- [ ] **Step 1: Write failing frontend behavior tests**

Cover one candidate preselected but unconnected until confirmation; multiple candidates; private-only TikTok labeling; close-without-connection; expired-session recovery; successful confirmation refreshing workspace state and removing only the local session query; and zero calls to publish-batch endpoints during callback/session/confirmation.

- [ ] **Step 2: Run focused frontend tests and verify RED**

Run: `node --max-old-space-size=4096 node_modules/vitest/vitest.mjs run src/modules/growth/GrowthWorkspacePages.test.ts --pool=threads --maxWorkers=1 --no-file-parallelism`

Working directory: `frontend`

Expected: tests fail because the account picker and API functions do not exist.

- [ ] **Step 3: Implement typed APIs and compact picker**

Read only a UUID-shaped `connection_session` from `window.location.search`. Render safe candidate summaries inside the existing promotion-page card hierarchy. Require an explicit click to confirm even for one candidate. On success, invalidate the growth workspace query and remove only `connection_session` and its stable status from the current URL using `history.replaceState`; retain unrelated safe local query values.

- [ ] **Step 4: Implement safe errors and accessibility**

Use a radio group for multiple candidates, labeled actions, focus the picker heading on return, announce success/error through status/alert roles, and display plain Chinese recovery messages. Never render raw scopes, API names, tokens, references, codes, provider payloads, or connector terminology.

- [ ] **Step 5: Run focused tests, typecheck, lint, and build**

Run: `node --max-old-space-size=4096 node_modules/vitest/vitest.mjs run src/modules/growth/GrowthWorkspacePages.test.ts --pool=threads --maxWorkers=1 --no-file-parallelism`

Run: `node --max-old-space-size=4096 node_modules/vue-tsc/bin/vue-tsc.js --noEmit`

Run: `node --max-old-space-size=4096 node_modules/eslint/bin/eslint.js .`

Run: `node --max-old-space-size=4096 node_modules/vite/bin/vite.js build`

Working directory: `frontend`

Expected: all commands pass.

- [ ] **Step 6: Commit**

```text
git add frontend/src/modules/growth
git commit -m "feat: add official publishing account picker"
```

### Task 5: Full Verification, Local Preview, and Acceptance Record

**Files:**
- Modify: `docs/acceptance/2026-08-14-growth-workspace.md`
- Modify: `.env.example` only if new disabled public configuration names are introduced.

**Interfaces:**
- Records exact verification totals and activation gates without secret-shaped examples.
- Keeps all official providers disabled in the local preview.

- [ ] **Step 1: Run complete backend verification**

Run: `.\.venv\Scripts\python.exe -m pytest -q`

Run: `.\.venv\Scripts\python.exe -m ruff check .`

Run: `.\.venv\Scripts\python.exe manage.py check --settings=config.test_settings`

Run: `.\.venv\Scripts\python.exe manage.py makemigrations --check --dry-run --settings=config.test_settings`

Working directory: `backend`

- [ ] **Step 2: Run complete frontend verification**

Run: `node --max-old-space-size=4096 node_modules/vitest/vitest.mjs run --pool=threads --maxWorkers=1 --no-file-parallelism`

Run: `node --max-old-space-size=4096 node_modules/vue-tsc/bin/vue-tsc.js --noEmit`

Run: `node --max-old-space-size=4096 node_modules/eslint/bin/eslint.js .`

Run: `node --max-old-space-size=4096 node_modules/vite/bin/vite.js build`

Working directory: `frontend`

- [ ] **Step 3: Update the acceptance record**

Record exact test totals, migration name, fixture-only callback/discovery coverage, explicit account confirmation, no-publication proof, and the unchanged gates for real client credentials, OAuth, provider review, token-store encryption, first live account connection, and first live post.

- [ ] **Step 4: Refresh the isolated local preview**

Apply migration `platforms.0006_accountconnectionsession` only to the existing `config.e2e_settings` preview database, restart only the known backend preview process, and verify `http://127.0.0.1:8000/api/v1/health` plus `http://127.0.0.1:3001/promotion`. Keep providers disabled and do not open an external authorization URL.

- [ ] **Step 5: Run final patch checks and commit**

Run: `git diff --check`

Run: `git status --short`

Expected: only the intended acceptance/config files remain before commit.

```text
git add docs/acceptance/2026-08-14-growth-workspace.md .env.example
git commit -m "test: verify official account connection completion"
```
