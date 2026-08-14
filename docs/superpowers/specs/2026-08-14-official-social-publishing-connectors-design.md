# Official Social Publishing Connectors Design

## Goal

Replace the growth workspace's hard-coded Fake publishing execution with an official-connector boundary that can publish approved content to Facebook Pages, Instagram Professional accounts, TikTok accounts, and LinkedIn Company Pages after the user explicitly connects and authorizes each account. The existing one-click batch, channel isolation, failed-only retry, manual export, and factory-owner UI remain intact.

This phase implements and tests the complete connector and authorization contracts without performing a live OAuth authorization or a live public post. Real platform activation remains configuration-gated and requires the user to confirm account authorization, application credentials, and each first live publication.

## Chosen Approach

Use direct official platform APIs behind provider-specific adapters.

- Meta is implemented first and provides Facebook Page and Instagram Professional publishing.
- TikTok uses the official Content Posting API and retains the platform-required creator-information and explicit-consent step.
- LinkedIn uses the versioned Posts API for organization authors.
- The Fake connector remains available only for Demo/Fake accounts and automated tests.

Rejected alternatives:

- A third-party social publishing aggregator would reduce initial OAuth work but adds recurring cost, another processor of customer tokens, and platform feature gaps.
- Browser automation, stored cookies, passwords, or scraping are prohibited because they are fragile and violate the product's safety boundary.

## User Experience

The ordinary factory-owner UI keeps the current five-item navigation and current promotion page. It exposes only three account states:

- `未连接` — offer `连接账号`.
- `已连接` — the approved package is eligible for one-click publishing.
- `需要重新授权` — offer `重新连接` and keep manual export available.

No ordinary-user screen exposes connector class names, OAuth scopes, client IDs, access tokens, refresh tokens, API versions, or raw provider errors. The one-click button continues to submit all approved eligible packages. A provider failure is shown in plain Chinese per channel and does not roll back successful channels.

The UI never starts a real post merely because OAuth completed. OAuth only connects an account. Publication still requires approved content and an explicit click on the existing one-click publication button. TikTok's required creator-information and consent data is shown immediately before submission when TikTok is among the selected channels.

## Architecture

### Connector registry

`integrations/platforms/registry.py` resolves a connector by platform code and account connection mode. It returns Fake only for accounts explicitly marked as Demo/Fake. A real account with missing configuration returns `CONFIGURATION_REQUIRED`; it never falls back to Fake.

Every connector implements a common contract:

- validate account readiness and required capabilities;
- normalize an approved channel package into the provider payload;
- publish with a caller-supplied idempotency reference;
- normalize success, retryable failure, rate limiting, expired authorization, and permanent rejection;
- return the provider post ID and public URL when the provider supplies them.

Provider HTTP is injected behind a small transport protocol so contract tests use recorded/local fixtures and never require credentials or network access.

### Authorization state

Add an `OAuthConnectionAttempt` model scoped to organization, actor, platform, and intended return path. It stores a one-time hashed state value, PKCE verifier reference when required, creation/expiry timestamps, and consumed timestamp. Raw state is returned once to the browser and never persisted. Callback handling verifies organization, actor, provider, expiry, one-time use, and an exact allow-listed return path.

Provider application credentials come only from environment-backed settings or a production secret manager. OAuth access and refresh tokens are written through a `TokenStore` interface. The default local store is disabled unless an explicit encryption key is configured. `ConnectorCredential.secret_reference` stores only the opaque token-store reference; list/read APIs never return token material.

OAuth callback completion discovers only accounts the authenticated platform user is authorized to manage, creates or updates the chosen `SocialAccount`, records granted capabilities and expiry, and marks publication mode as `API_CONFIRM` until the first provider readiness check succeeds. Revoked or expired authorization changes readiness to `REAUTHORIZATION_REQUIRED` and prevents publication.

### Growth batch integration

The growth publishing service stops filtering on the E2E fixture marker. It selects exactly one active organization-owned account for each package and asks the registry for its execution adapter.

- Demo account + Demo package: Fake connector is allowed and result remains `Demo / Fake`.
- Real account + approved real package + ready official connector: official connector executes.
- Real account missing configuration or authorization: item becomes `CONFIGURATION_REQUIRED` or `REAUTHORIZATION_REQUIRED` with manual export recovery.
- Demo package on a real connector, or real package on Fake: fail closed.

The existing batch idempotency key is propagated as the connector idempotency reference. Successful items are immutable during retry. Only retryable failed items may be retried automatically; authorization and validation failures require user action first.

## Provider Requirements

### Meta: Facebook and Instagram

One Meta application handles Facebook Login for Business. Facebook Page publication uses a Page access token and the approved Page publishing capabilities. Instagram publication targets a Professional account and requires content-publishing permission. Media must be reachable from a provider-accessible URL; local-only assets therefore remain manual exports until an approved public asset origin exists.

### TikTok

TikTok uses Content Posting API Direct Post. The connector queries creator information before initializing a post and binds the user's latest privacy/comment/duet/stitch choices to the publish request. An unaudited TikTok client is treated as private-only and the UI must not claim public publication. Public posting readiness requires TikTok audit approval.

### LinkedIn

LinkedIn uses the versioned Posts API with the organization as author. Readiness requires the authenticated member to have an accepted Company Page role and organization publishing permission. Every request sends the current configured LinkedIn API version and REST.li protocol version; sunset versions make the connector not ready rather than silently downgrading.

## Error Handling and Safety

- Tokens, authorization codes, client secrets, cookies, and raw provider responses are redacted from logs and API responses.
- OAuth callback errors use stable internal codes and plain-language recovery actions.
- Rate limits preserve provider retry timing and do not retry in a tight loop.
- A provider timeout after submission is treated as outcome-unknown; the connector reconciles by provider/idempotency reference before another create call.
- No connector supports personal-message automation, comment spam, follower scraping, password login, cookie import, or CAPTCHA bypass.
- A platform cannot be marked `已连接` from manually typed account identifiers alone.
- Production activation requires HTTPS redirect URIs, exact origin allow-lists, platform app review where applicable, and an explicit non-Fake environment flag.

## API Surface

Add management-only endpoints:

- `GET /api/v1/platform-connections` — safe readiness summaries for the four channels.
- `POST /api/v1/platform-connections/{platform}/authorize` — create a short-lived authorization attempt and return the official authorization URL.
- `GET /api/v1/platform-connections/{platform}/callback` — validate the callback and complete or stage account selection.
- `POST /api/v1/platform-connections/{platform}/disconnect` — disable the connection and revoke through the provider when supported; this destructive external action requires explicit user confirmation.

The growth workspace includes safe connection summaries but never credential identifiers. Existing publish-batch endpoints and payloads remain backward compatible; batch items gain stable `mode`, `error_code`, `retryable`, and `recovery_action` fields.

## Testing and Acceptance

- Contract-test all four official adapters with injected HTTP fixtures for success, validation rejection, 401/expired token, 403/scope rejection, 429/rate limit, 5xx, timeout, and duplicate reconciliation.
- Prove OAuth state is hashed, short-lived, one-time, actor/org/provider-bound, and rejects an unlisted return path.
- Prove no serializer, log, OpenAPI example, or frontend state contains token material.
- Prove a real account never falls back to Fake and a Demo/Fake result never appears as a real post.
- Prove one-click mixed outcomes preserve successful channels and retry only eligible failures.
- Prove TikTok unaudited mode cannot be represented as a public post.
- Keep all existing backend, frontend, build, lint, migration, and browser-flow checks green.

## Activation Gate

Implementation may proceed locally with fixture transports and disabled provider settings. The work must stop for user confirmation before entering any real client ID/client secret, opening a real OAuth consent flow, publishing a real post, requesting paid platform access, or deploying callback URLs. Until those gates are satisfied, the UI must continue to identify the current execution as Demo/Fake or configuration required.
