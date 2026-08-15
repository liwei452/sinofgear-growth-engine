# Social OAuth Activation-Ready Foundation Design

Date: 2026-08-15

## Goal

Turn the existing fixture-tested Meta, LinkedIn, and TikTok account-connection foundation into an activation-ready, fail-closed social OAuth runtime, and add the same provider boundary for YouTube. After this work, activating a provider should require only approved provider credentials, a stable HTTPS callback URL, an encryption-backed token store, and an explicit enable switch. This phase does not enter real credentials, authorize a real account, submit an app review, call a live provider, or publish a real post.

## Existing Foundation to Preserve

The repository already provides:

- One-time, actor-, organization-, and provider-bound OAuth authorization attempts.
- Safe callbacks that create a short-lived account-selection session.
- Explicit selection of a manageable Page, organization, creator, or professional account.
- Opaque credential references instead of tokens in ordinary models and API responses.
- Official connector interfaces and fail-closed separation from Demo/Fake connectors.
- Human approval, explicit publication, failed-only retry, idempotency, and manual package fallback.

This design completes runtime wiring and operational readiness. It does not replace these boundaries or weaken their activation gates.

## Scope and Safety Boundary

- Work only in `C:\Users\Administrator\Documents\网站\sinofgear-growth-engine`.
- Support Meta Facebook Pages, Instagram professional accounts, LinkedIn Company Pages, TikTok creator accounts, and YouTube channels.
- All providers remain disabled by default.
- Tests use injected fixture transports. No test or local default may contact a provider endpoint.
- No client secret, access token, refresh token, verification code, provider cookie, account password, or live authorization code is committed or printed.
- No live account authorization, app-review submission, real post publication, production deployment, DNS change, paid API, or irreversible external action occurs in this phase.
- Real accounts never fall back to Demo/Fake connectors. Incomplete configuration always returns a stable configuration-required state.
- `app.sinfogear.com` is the intended future application host, but this phase only validates configurable HTTPS callback origins and does not change DNS.

## Recommended Architecture

Add one provider-neutral runtime assembly layer between Django settings and the existing authorization and publishing registries.

1. Typed provider configuration reads only public identifiers and secret references from the environment.
2. A secret resolver retrieves provider client secrets and the token-encryption key at runtime. Ordinary settings, APIs, logs, and database rows contain only references.
3. A token vault stores encrypted provider credential bundles and returns opaque references compatible with the existing `TokenStore` contract.
4. Provider runtime factories construct authorization adapters and publishing connectors only when every required setting, secret reference, callback rule, and capability is valid.
5. A lifecycle service refreshes expiring credentials through an injected provider transport, records safe health outcomes, and supports explicit revoke/disconnect without deleting business history.
6. The existing authorization and connector registries receive the successfully assembled provider runtimes. Missing or invalid providers remain absent and fail closed.
7. A safe readiness API and the existing settings surface explain what the owner must do next without displaying developer terminology or secret values.

The runtime assembly is deterministic and side-effect-free. Constructing it never contacts a provider. Network access occurs only inside explicitly invoked authorization exchange, refresh, revoke, account discovery, or publish operations.

## Provider Configuration

Normalize configuration into a typed `SocialProviderConfig` with:

- Internal provider code.
- Enabled flag, defaulting to `false`.
- Public client identifier.
- Client-secret reference, never a plaintext secret.
- Exact HTTPS callback URI.
- Requested scopes/capabilities.
- Authorization, token, refresh, revoke, discovery, and publishing endpoint metadata owned by the adapter rather than editable ordinary-user fields.
- Optional provider API version.

Provider-specific required configuration:

- Meta: client ID, client-secret reference, callback URI, Pages and Instagram publishing capabilities.
- LinkedIn: client ID, client-secret reference, callback URI, organization publishing capability.
- TikTok: client key, client-secret reference, callback URI, upload capability, and direct-post capability represented separately.
- YouTube: Google OAuth client ID, client-secret reference, callback URI, and `youtube.upload` capability.

Callback validation requires HTTPS outside explicit test settings, rejects fragments and embedded credentials, and accepts only an allow-listed application origin. A configured callback path must match the platform callback route exactly. Local fixture tests may use the Django test host without weakening production validation.

## Secret Resolver and Token Vault

Define a provider-neutral `SecretResolver.resolve(reference) -> SecretValue` interface. The default resolver is disabled. Tests use an in-memory fixture resolver that redacts its representation and never logs values.

Implement an encrypted database token vault behind the existing token-store interface:

- The encryption key is obtained from a secret reference outside the database.
- Each credential bundle is encrypted with authenticated encryption and a unique nonce.
- Associated data binds the ciphertext to organization, actor, platform, connection attempt, and selected external account.
- Access token, refresh token, expiry, token type, granted provider scopes, and provider account binding exist only inside the encrypted payload.
- Database rows expose only an opaque random reference, key version, lifecycle timestamps, and safe status.
- Key rotation decrypts with the previous key version and rewrites with the active version only during an explicit maintenance operation.
- Token resolution returns a redacted value object and never serializes to APIs, audit payloads, or logs.
- Disconnect revokes where supported, marks the credential unavailable, and keeps publishing and attribution history.

No plaintext local-file token store is provided.

## Runtime Factories and Provider Adapters

Create one factory per provider that consumes typed configuration, a secret resolver, token vault, clock, and injected HTTP transport. A provider enters the authorization registry only when authorization configuration is complete. It enters the official publishing registry only when publishing configuration and required capabilities are complete.

Existing Meta, LinkedIn, and TikTok authorization and publishing adapters remain the provider-specific implementation units. Their construction moves into the factories; their test transports remain injectable.

Add a YouTube adapter with the same contracts:

- OAuth authorization-code exchange.
- Channel identity discovery for the authenticated Google user.
- Credential refresh and revoke support.
- Video upload publishing request normalization.
- Safe provider result mapping with external video ID and canonical URL.

YouTube upload remains disabled until the Google project, OAuth consent configuration, requested scope, account authorization, and explicit application switch are all complete.

## Credential Lifecycle

Add a lifecycle service with explicit operations:

- `probe`: validate locally available metadata and optionally query provider identity only when invoked by an authorized administrator.
- `refresh_due`: refresh credentials inside a bounded time window before expiry using an idempotent, per-credential lock.
- `reauthorize`: create a new authorization attempt without overwriting a still-valid connection until confirmation succeeds.
- `disconnect`: attempt provider revoke, mark the credential disconnected, and retain account/publication history.

Refresh failures are normalized into stable states:

- `CONFIGURATION_REQUIRED`
- `CONNECTED`
- `REFRESH_DUE`
- `REAUTHORIZATION_REQUIRED`
- `INSUFFICIENT_CAPABILITY`
- `PROVIDER_UNAVAILABLE`
- `DISCONNECTED`

Provider response bodies, token values, scope strings not intended for ordinary users, and exception traces never appear in owner-facing responses.

## Readiness API and Owner Experience

Extend the existing connection-readiness response rather than create a separate technical console. Each channel returns:

- Channel and provider label.
- Safe status and plain Chinese explanation.
- Whether authorization can start.
- Whether account selection is pending.
- Whether publishing is available, draft/upload-only, private-only, or unavailable.
- The next owner action, such as “等待平台审核”, “连接账号”, “重新授权”, or “联系管理员完成服务器配置”.

The settings page shows Facebook, Instagram, LinkedIn, TikTok, and YouTube as separate business channels even when Meta shares one developer application. It never asks an ordinary user to paste a client secret or token. Secret references and provider application configuration remain deployment-administrator concerns.

## API and Callback Shape

Preserve the existing provider-neutral routes:

- `POST /api/v1/platform-connections/{platform_code}/authorize`
- `GET /api/v1/platform-connections/{platform_code}/callback`
- `GET /api/v1/platform-connection-sessions/{session_id}`
- `POST /api/v1/platform-connection-sessions/{session_id}/confirm`

Add administrator lifecycle actions under the account resource:

- `POST /api/v1/social-accounts/{account_id}/probe`
- `POST /api/v1/social-accounts/{account_id}/reauthorize`
- `POST /api/v1/social-accounts/{account_id}/disconnect`

Do not expose a general-purpose token endpoint. Background refresh calls the lifecycle service directly through the job system and uses organization-scoped locking and bounded retries.

Future callback examples are derived from configuration, not hard-coded:

- `https://app.sinfogear.com/api/v1/platform-connections/FACEBOOK/callback`
- `https://app.sinfogear.com/api/v1/platform-connections/INSTAGRAM/callback`
- `https://app.sinfogear.com/api/v1/platform-connections/LINKEDIN/callback`
- `https://app.sinfogear.com/api/v1/platform-connections/TIKTOK/callback`
- `https://app.sinfogear.com/api/v1/platform-connections/YOUTUBE/callback`

## Error Handling and Observability

- Redact authorization codes, tokens, secrets, cookie values, query strings, and provider bodies before logging.
- Record safe audit events for authorization started, connection confirmed, refresh succeeded/failed, reauthorization required, disconnect requested/completed, and provider runtime disabled.
- Bound provider timeouts, response sizes, retry counts, media reads, and redirect following.
- Use idempotency keys for refresh, revoke, and publication operations where the provider permits them.
- A provider outage never disables manual publishing-package export or other providers.
- A failed activation never mutates an existing valid credential.

## Testing and Acceptance

- Configuration tests cover disabled defaults, missing fields, invalid callback origins, wrong callback paths, incomplete scopes, and secret-reference redaction.
- Token-vault tests cover authenticated encryption, tenant/account binding, ciphertext tampering, wrong keys, expiry, disconnect, and zero plaintext persistence or logging.
- Runtime-factory tests prove incomplete providers are absent, complete fixture providers are registered, authorization readiness is independent from publishing readiness, and no construction-time network request occurs.
- Provider fixture tests cover Meta Page/Instagram separation, LinkedIn administrator filtering, TikTok upload versus public-post readiness, and YouTube channel discovery/upload normalization.
- Lifecycle tests cover refresh locking, bounded retries, reauthorization without premature overwrite, revoke failure recovery, disconnect history retention, and stable safe errors.
- API tests cover permissions, tenant isolation, CSRF, callback state, lifecycle actions, and absence of secrets.
- Frontend tests cover all five channels, plain Chinese readiness states, authorization entry, reauthorization, disconnect confirmation, and no secret input fields.
- Full backend and frontend tests, lint, type checking, OpenAPI generation check, migration drift check, production build, and local browser acceptance must pass.

## Activation Runbook Boundary

This implementation ends with all providers disabled and fixture-tested. Activating one provider later requires a separate explicit external-operations step:

1. Deploy the application behind stable HTTPS.
2. Configure `app.sinfogear.com` DNS and TLS.
3. Create or approve the provider developer application.
4. Register the exact callback URI, privacy policy, terms, and deletion instructions.
5. Store client secrets and the token-vault encryption key in the selected production secret manager.
6. Enter only secret references and public client identifiers in runtime configuration.
7. Complete sandbox authorization and permission review.
8. Enable one provider at a time.
9. Authorize a real company account and perform a separately confirmed first publication.

No step in this design performs those external operations automatically.
