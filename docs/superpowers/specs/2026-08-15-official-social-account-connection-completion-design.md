# Official Social Account Connection Completion Design

Date: 2026-08-15

## Goal

Complete the locally testable account-connection lifecycle that begins at the existing safe authorization endpoint: validate the provider callback, exchange fixture authorization data through injected provider services, discover only accounts the authenticated provider user may manage, let the factory owner choose a publishing account, and persist an opaque credential reference. This phase does not open a live OAuth consent screen, store a real token, call a live provider, or publish a real post.

## Scope and Safety Boundary

- Work only in `C:\Users\Administrator\Documents\网站\sinofgear-growth-engine`; never enter or modify the sibling `app` repository.
- Support Meta Facebook Pages and Instagram Business accounts, LinkedIn Company Pages, and TikTok creator accounts.
- OAuth completion connects an account only. It never approves content, creates a publish batch, or calls a publishing endpoint.
- All provider exchanges and discovery calls use injected fixture transports in tests. Production transports and real provider secrets remain disabled.
- Tokens never appear in API responses, ordinary model fields, logs, audit payloads, browser storage, URLs after callback processing, or exception text.
- A persisted `ConnectorCredential.secret_reference` is an opaque reference produced by an injected encrypted `TokenStore`; the default local token store remains disabled.
- Provider accounts are never invented. Each candidate is returned by a provider discovery adapter and carries a provider account identifier, display name, channel, capability summary, and evidence timestamp.
- Existing human content approval, explicit one-click publication, Demo/Fake labeling, manual download fallback, and fail-closed real-versus-Demo routing remain unchanged.

## Recommended Architecture

Use a two-step completion flow rather than creating a `SocialAccount` directly inside the callback.

1. The callback consumes the existing one-time, short-lived, actor/provider-bound authorization attempt.
2. A provider-specific authorization adapter exchanges the fixture code, resolves granted capabilities, and discovers manageable publishing accounts.
3. The backend stores a short-lived `AccountConnectionSession` containing only encrypted/opaque token-store reference data and normalized account candidates. The raw provider code and token are discarded before the response.
4. The browser returns to `/promotion` with only a local connection-session identifier. It displays a compact account picker when more than one candidate exists.
5. A credential manager confirms one candidate. The backend revalidates ownership, session expiry, actor, organization, provider, and candidate membership, then atomically creates or updates `SocialAccount` and `ConnectorCredential`.
6. Connection readiness changes to `CONNECTED` only when required publishing capabilities and an unexpired credential reference are present.

This prevents a callback from silently selecting the wrong Page or Company and keeps provider secrets outside ordinary request and response data.

## Domain Model

Add `AccountConnectionSession`, scoped to organization, actor, and platform, with:

- UUID primary key.
- Opaque token-store reference.
- Normalized account candidates in a bounded JSON structure containing only account identifier, display name, channel, capability labels, and discovery timestamp.
- Granted capability identifiers stored as normalized internal names, never raw OAuth scope strings in ordinary-user responses.
- Session `expires_at`, provider credential `credential_expires_at`, `consumed_at`, `confirmed_candidate_id`, `created_at`, and `updated_at`.
- A maximum lifetime of 10 minutes and one-time confirmation.

The session may contain at most 100 candidates. Candidate display names and identifiers have strict length limits. Unknown fields, duplicate provider account identifiers, unsupported channels, and candidates without publishing capability are rejected before persistence.

`SocialAccount.connector_metadata.connection_kind` is set to `official_oauth`. Its external identifier and display name come from the selected provider candidate. `ConnectorCredential.secret_reference` stores only the token-store reference. Account and credential updates occur in one database transaction.

## Provider Authorization Interfaces

Add provider-neutral contracts under `backend/integrations/platforms`:

- `AuthorizationCodeExchange.exchange(code, redirect_uri, pkce_reference) -> OAuthTokenSet`
- `ManagedAccountDiscovery.discover(token_set) -> list[ManagedPublishingAccount]`
- `TokenStore.store(token_set, context) -> secret_reference`
- `TokenStore.delete(secret_reference)` for compensation when session creation or confirmation fails.

Provider adapters normalize these outcomes:

- Meta discovers Pages managed by the authenticated user and linked Instagram professional accounts. Facebook and Instagram remain separate channel candidates.
- LinkedIn discovers organizations for which the authenticated member has the required administrative role.
- TikTok obtains creator information and publishing capability; an unaudited application is represented as private-only and cannot claim public-post readiness.

No adapter is constructed with real configuration by default. Provider response bodies are never copied into exceptions or audit events.

## API Flow

### Callback

`GET /api/v1/platform-connections/{platform_code}/callback?code=...&state=...`

- Requires the same authenticated actor who started authorization.
- Accepts only the exact provider and one-time state.
- Rejects provider errors, missing fields, expired/reused state, wrong actor, wrong organization context, unsafe return paths, and disabled configuration.
- Exchanges and discovers through injected services only.
- Redirects to the stored safe local return path with `connection_session=<uuid>` and a stable status code. It never includes provider code, state, token, raw error, or scope values in the redirect.

### Session Summary

`GET /api/v1/platform-connection-sessions/{session_id}`

- Only the owning actor with credential-management permission may read it.
- Returns provider label, expiry, and safe candidate summaries.
- Never returns token-store references, raw scopes, credential identifiers, provider payloads, or callback parameters.

### Confirmation

`POST /api/v1/platform-connection-sessions/{session_id}/confirm`

Body: `{ "candidate_id": "..." }`

- Strictly validates the candidate belongs to the unconsumed session.
- Atomically creates or updates one official `SocialAccount` plus credential reference.
- Records the confirmed candidate, marks the session consumed, and returns a safe connection summary.
- Idempotent replay returns the same safe summary only for the same candidate; a different candidate is rejected.

## Factory-Owner Experience

The existing `/promotion` page remains the only ordinary-user surface.

- Returning from authorization opens a compact card titled “选择要用于发布的账号”.
- A single candidate is preselected but still requires an explicit “使用此账号” click.
- Multiple candidates show channel, account display name, and a plain capability label such as “可发布” or “仅私密发布”.
- No OAuth scope, token, client ID, API version, connector class, provider response, or prompt terminology is shown.
- After confirmation the picker closes, connection states refresh, and the selected channel displays “已连接 · 官方连接”.
- Closing the picker does not connect anything and does not publish anything. Manual publishing-package download remains available.

## Error Handling and Recovery

Stable internal outcomes map to plain Chinese recovery actions:

- `CONFIGURATION_REQUIRED`: “官方账号连接尚未配置”.
- `AUTHORIZATION_REJECTED`: “授权未完成，请重新连接”.
- `REAUTHORIZATION_REQUIRED`: “授权已失效，请重新连接”.
- `NO_MANAGEABLE_ACCOUNT`: “没有发现你可管理的发布账号”.
- `INSUFFICIENT_CAPABILITY`: “该账号暂不具备发布权限”.
- `CONNECTION_SESSION_EXPIRED`: “连接已超时，请重新连接”.
- `PROVIDER_UNAVAILABLE`: “平台暂时不可用，请稍后重试”.

Provider error text and response bodies are never exposed. If token storage succeeds but session creation fails, the stored reference is deleted. If confirmation fails before the database transaction commits, no account is partially connected.

## Testing and Acceptance

- State callback tests cover actor, organization, provider, expiry, reuse, provider denial, safe redirect construction, and absence of secret material.
- Provider fixture tests cover code exchange, manageable-account normalization, Meta Page/Instagram separation, LinkedIn admin filtering, and TikTok public/private capability.
- Token-store tests prove only opaque references persist and compensation deletes orphaned references.
- Session API tests cover permission, tenant isolation, expiry, candidate membership, one-time confirmation, same-candidate idempotency, and atomic account/credential creation.
- Frontend tests cover one/multiple candidates, explicit confirmation, cancel-without-connection, safe Chinese errors, connection-state refresh, and zero publication requests.
- Full backend and frontend suites, type checking, linting, build, migration drift, and local browser acceptance must pass.

## Activation Gates

Implementation stops at fixture-tested boundaries. A later live activation requires separate user confirmation before any real client identifier, client secret, callback domain, encryption key, OAuth consent, provider review submission, live account selection, or first real publication is used. Each provider must pass sandbox readiness and permission review independently; enabling one provider does not enable the others.
