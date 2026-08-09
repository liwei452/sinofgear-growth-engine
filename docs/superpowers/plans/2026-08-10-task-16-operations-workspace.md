# Task 16 Publishing Operations and Analytics Workspace Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the four remaining operational placeholders with safe, beginner-friendly, real-data workspaces for assets, platform connections, publishing, analytics, and tracking links.

**Architecture:** Keep backend changes inside the existing assets/platforms/publishing/tracking apps and expose only minimal safe contracts. On the frontend, give each workspace its own typed API, organization-scoped query keys, page component, dialogs, and behavior tests; reuse the generation-safe cursor composable and modal-focus composable. All server writes remain permission-gated and all pagination URLs remain exact-origin/exact-path validated.

**Tech Stack:** Django 5.2, Django REST Framework, pytest, Vue 3, TypeScript, TanStack Vue Query, Vue Router, Testing Library, Vitest.

## Global Constraints

- Do not start Task 17 or add OAuth flows, deletion, raw click events, IPs, hashes, arbitrary JSON editors, or automatic JavaScript URL navigation.
- Use real backend contracts and organization-scoped query keys; preserve auth/focus behavior from Task 13.
- Use `#005BA8` as the primary action color, status text in addition to color, one primary action per page, accessible labels/live regions, modal focus trapping, and narrow-screen cards.
- Every behavior change follows RED → GREEN. Unknown fields and bad cursors return controlled 400 responses.
- Final commit message is exactly `feat: add publishing operations and analytics workspace`.

---

### Task 1: Backend platform-account and connector-credential contracts

**Files:**
- Modify: `backend/apps/platforms/serializers.py`
- Modify: `backend/apps/platforms/views.py`
- Modify: `backend/apps/platforms/urls.py`
- Modify: `backend/apps/platforms/tests/test_social_accounts_api.py`
- Modify: `backend/apps/platforms/tests/test_openapi_schema.py`

**Interfaces:**
- Produces safe social account fields: `id`, `platform_id`, `external_id`, `display_name`, `publish_mode`, `status`, `effective_capabilities`, `credential_configured`.
- Produces credential fields: `id`, `platform_id`, `granted_scopes`, `expires_at`, `configured`; `secret_reference` is input-only.

- [ ] Add failing API tests for publishing-read safe list/detail, management-only create/patch, cross-org isolation, strict unknown fields, same-org/same-platform credentials, write-only secrets, valid platform capability scopes, and OpenAPI paths.
- [ ] Implement strict read/create/update serializers, capability summaries, method-specific permissions, organization-scoped lookup, and credential list/create/update endpoints.
- [ ] Run platform tests and keep every response/cache/error free of `secret_reference` and non-manager credential IDs.

### Task 2: Backend analytics total and controlled cursors

**Files:**
- Modify: `backend/apps/tracking/serializers.py`
- Modify: `backend/apps/tracking/views.py`
- Modify: `backend/apps/tracking/tests/test_analytics_api.py`
- Modify: `backend/apps/publishing/views.py`
- Modify: `backend/apps/publishing/tests/test_publishing_api.py`

**Interfaces:**
- Adds `total_clicks: integer` to `/api/v1/analytics/channel-summary`, computed after every consistency/filter rule but before offset/limit.
- Converts invalid publishing/tracking/short cursor pagination into `{"errors":{"cursor":[...]}}` with status 400.

- [ ] Add failing aggregation, pagination-independence, privacy/OpenAPI, and malformed-cursor tests.
- [ ] Compute `total_clicks` from the fully filtered consistent click queryset and catch DRF `NotFound` around cursor pagination.
- [ ] Run focused tracking/publishing tests.

### Task 3: FormData client support

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/client.test.ts`

**Interfaces:**
- `ApiRequestOptions.body` accepts JSON-compatible values or `FormData`.
- Unsafe FormData requests still include cookies and CSRF but do not set `Content-Type` or stringify the body.

- [ ] Add failing tests for FormData CSRF/body/header behavior and unchanged JSON requests.
- [ ] Branch body preparation on `instanceof FormData` and verify GREEN.

### Task 4: Asset workspace

**Files:**
- Create: `frontend/src/modules/assets/api.ts`
- Create: `frontend/src/modules/assets/AssetLibraryPage.vue`
- Create: `frontend/src/modules/assets/AssetLibraryPage.test.ts`

**Interfaces:**
- Organization keys under `['assets', organizationId, ...]`.
- API functions list/filter/upload/link/download using `/api/v1/assets` exact-path pagination.

- [ ] Add failing tests for loading/page-two/filter reset, named retry, upload multipart/duplicate 200, field errors/focus, product linking, and safe http/https-only download buttons.
- [ ] Implement typed API, generation-safe list, beginner upload dialog with deduplicated tags/default metadata, detail actions, and accessible states.
- [ ] Verify focused asset UI tests.

### Task 5: Platform account workspace

**Files:**
- Create: `frontend/src/modules/platformAccounts/api.ts`
- Create: `frontend/src/modules/platformAccounts/PlatformAccountsPage.vue`
- Create: `frontend/src/modules/platformAccounts/PlatformAccountsPage.test.ts`

**Interfaces:**
- Organization keys under `['platform-accounts', organizationId, ...]`.
- Uses platforms, safe social accounts, and management-only credential endpoints.

- [ ] Add failing tests for publishing-read cards, manager-only actions, manual/API-auto exact payloads, capability/credential guidance, secret non-disclosure, edit constraints, and friendly 403/409 states.
- [ ] Implement safe cards and a focused new/edit connection wizard; keep secret reference only in a password input with `autocomplete="off"` and local submission state, then clear it.
- [ ] Verify focused platform-account UI tests.

### Task 6: Publishing calendar workspace

**Files:**
- Create: `frontend/src/modules/publishing/api.ts`
- Create: `frontend/src/modules/publishing/PublishingCalendarPage.vue`
- Create: `frontend/src/modules/publishing/PublishingCalendarPage.test.ts`

**Interfaces:**
- Organization keys under `['publishing', organizationId, ...]`.
- Uses explicit UTC range plus browser IANA timezone for calendar, cursor task list, approved current-head platform content, safe accounts, and guarded schedule/cancel/retry APIs.

- [ ] Add failing tests for timezone/range/filter/truncated calendar, page-two tasks, exact scheduling body/header/stable idempotency, unavailable-account guidance, cancel/retry conflict refresh, active polling, unmount and in-flight cleanup.
- [ ] Implement month navigation and agenda cards, task details, controlled errors, eligible content/account selection, local-to-ISO scheduling, stable per-submit UUID, guarded actions, and disposal-safe polling.
- [ ] Verify focused publishing UI tests.

### Task 7: Analytics and tracking-link workspace

**Files:**
- Create: `frontend/src/modules/analytics/api.ts`
- Create: `frontend/src/modules/analytics/AnalyticsPage.vue`
- Create: `frontend/src/modules/analytics/AnalyticsPage.test.ts`

**Interfaces:**
- Organization keys under `['analytics', organizationId, ...]`.
- Uses channel summary offset pagination plus exact-path cursor lists for tracking/short links and a locked publishing-content provenance chain.

- [ ] Add failing tests for exact `total_clicks`, date/filter/reset generation, accessible trend/table, name mapping, empty/error/narrow states, tracking/short page two, provenance-derived create payloads, short-link creation, and clipboard failure.
- [ ] Implement 30-day defaults, bounded filters, accessible bars plus table fallback, name lookup, safe link lists, provenance-locked creation flow, idempotency keys, displayed `full_url`/`redirect_path`, and copy feedback.
- [ ] Verify focused analytics UI tests.

### Task 8: Lazy routes, cross-organization freshness, and final verification

**Files:**
- Modify: `frontend/src/app/router.ts`
- Modify: `frontend/src/app/router.test.ts`
- Modify: `frontend/src/main.ts`
- Modify: relevant workspace tests for organization changes

**Interfaces:**
- Replaces the four placeholder component routes with distinct lazy components: `Assets`, `PublishingCalendar`, `PlatformAccounts`, and `Analytics`.

- [ ] Add failing lazy-route and organization-cache freshness tests.
- [ ] Wire distinct route components and preserve login redirect/focus contracts.
- [ ] Run frontend full tests, typecheck, lint, and build.
- [ ] Run backend focused platforms/assets/publishing/tracking/content tests, Ruff, Django check, migration drift, then full pytest because shared API behavior changed.
- [ ] Run `git diff --check`, write `task-16-report.md`, commit exactly, and confirm a clean worktree.
