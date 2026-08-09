# Task 13 Vue Application Shell Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a novice-friendly Chinese Vue shell with safe Django session authentication, CSRF protection, protected routes, placeholders, and an actionable dashboard.

**Architecture:** A typed fetch client owns cookies, CSRF, response parsing, and recoverable errors. Vue Router performs session resolution before protected components mount, while TanStack Vue Query caches only the current-user response. AppShell owns responsive navigation and renders dashboard or bounded placeholder routes.

**Tech Stack:** Vue 3, TypeScript, Vue Router, TanStack Vue Query, Vite, Vitest, Testing Library, ESLint, Django REST Framework.

## Global Constraints

- Chinese UI, novice-first copy, one primary action per page.
- Brand token must be exactly `--sg-brand: #005BA8`.
- Every API request uses `credentials: "include"`; unsafe methods use Django CSRF cookie/header.
- Never store passwords, sessions, or CSRF tokens in localStorage.
- Protected pages must not render before `/api/v1/auth/me` resolves.
- Eight future business routes stay protected and use one honest placeholder component.
- No Task 14–16 business implementation and no large UI framework.
- This task is executed inline because the user explicitly prohibited subagents.

---

### Task 1: CSRF bootstrap endpoint

**Files:**
- Modify: `backend/apps/identity/views.py`
- Modify: `backend/apps/identity/urls.py`
- Modify: `backend/apps/identity/tests/test_current_user_api.py`

**Interfaces:**
- Produces: anonymous `GET /api/v1/auth/csrf -> 204` with `csrftoken` cookie.
- Preserves: Django middleware rejects login POST without CSRF when enforcement is enabled.

- [ ] Write tests using `APIClient(enforce_csrf_checks=True)` asserting the endpoint returns 204 and a CSRF cookie, login without the header returns 403, and login with cookie plus `HTTP_X_CSRFTOKEN` returns 204.
- [ ] Run the focused Django test and verify RED because `/auth/csrf` is missing.
- [ ] Add `CsrfCookieView` with `AllowAny`, decorate GET with `ensure_csrf_cookie`, and register `auth/csrf`.
- [ ] Re-run the focused test and verify GREEN.

### Task 2: Frontend toolchain and typed API client

**Files:**
- Modify: `frontend/package.json`
- Create: `frontend/index.html`
- Create: `frontend/tsconfig.json`
- Create: `frontend/tsconfig.app.json`
- Create: `frontend/vite.config.ts`
- Create: `frontend/eslint.config.js`
- Create: `frontend/src/env.d.ts`
- Create: `frontend/src/test/setup.ts`
- Create: `frontend/src/api/client.ts`
- Create: `frontend/src/api/client.test.ts`

**Interfaces:**
- Produces: `apiRequest<T>(path, options?): Promise<T | undefined>` and `ApiError` with `status`, `userMessage`, and optional `recoveryAction`.
- CSRF bootstrap: `ensureCsrfCookie(): Promise<void>` calls `/api/v1/auth/csrf` when the cookie is absent.

- [ ] Configure Vue/Vitest/jsdom/Testing Library/ESLint/typecheck/build scripts and Vite `/api` proxy to `http://localhost:8000`.
- [ ] Write API tests with real `Response` objects for credentials, 204, CSRF header, detail/message/recovery parsing, 401/403/5xx and network errors.
- [ ] Install dependencies and run the API test to verify RED because the client does not exist.
- [ ] Implement the minimal fetch client, safe JSON parsing, cookie parsing, CSRF bootstrap, and Chinese error mapping.
- [ ] Re-run API tests and verify GREEN.

### Task 3: Authentication state and protected router

**Files:**
- Create: `frontend/src/app/queryClient.ts`
- Create: `frontend/src/modules/auth/auth.ts`
- Create: `frontend/src/app/router.ts`
- Create: `frontend/src/app/router.test.ts`
- Create: `frontend/src/test/render.ts`

**Interfaces:**
- Produces: `CurrentUser`, `currentUserQueryOptions()`, `login(credentials)`, `logout()`.
- Produces: `createAppRouter(queryClient)` and `safeRedirect(value): string`.

- [ ] Write router tests proving protected content does not mount while `/auth/me` is pending, 401/403 redirects to `/login?redirect=...`, successful login target returns to a safe local path, and external/protocol-relative/backslash/control redirects become `/`.
- [ ] Run router tests and verify RED because auth/router modules do not exist.
- [ ] Implement query options with no auth retry, route meta protection, async guard, and strict local redirect validation.
- [ ] Re-run router tests and verify GREEN.

### Task 4: Login experience

**Files:**
- Create: `frontend/src/modules/auth/LoginPage.vue`
- Create: `frontend/src/modules/auth/LoginPage.test.ts`

**Interfaces:**
- Consumes: `login`, `currentUserQueryOptions`, `safeRedirect`, router/query client injection.
- Produces: accessible username/password form and session transition.

- [ ] Write component tests asserting explicit labels, pending submit disabled/text, generic failure copy, no account-enumeration detail, query invalidation, and safe post-login navigation.
- [ ] Run tests and verify RED because LoginPage is missing.
- [ ] Implement the concise form with `aria-live`, autocomplete values, pending state, fixed Chinese failure and one primary submit button.
- [ ] Re-run tests and verify GREEN.

### Task 5: Application shell, responsive navigation, dashboard, and placeholders

**Files:**
- Create: `frontend/src/app/AppShell.vue`
- Create: `frontend/src/shared/components/NextStepPanel.vue`
- Create: `frontend/src/shared/components/PlaceholderPage.vue`
- Create: `frontend/src/modules/dashboard/DashboardPage.vue`
- Create: `frontend/src/app/AppShell.test.ts`
- Create: `frontend/src/modules/dashboard/DashboardPage.test.ts`

**Interfaces:**
- AppShell consumes route meta and current-user query data.
- NextStepPanel consumes `{ steps, loading, error, onRetry }` and renders exactly one primary link when ready.
- PlaceholderPage consumes route meta title and links to `/` / `/#next-steps`.

- [ ] Write AppShell tests for all nine Chinese navigation labels, organization/user display, active item, logout, and narrow-screen open/close behavior.
- [ ] Write dashboard tests for heading, three literal novice steps, primary action, loading, empty and error/retry accessible states.
- [ ] Run tests and verify RED because components are missing.
- [ ] Implement semantic shell, responsive menu, dashboard and shared placeholder without business data.
- [ ] Re-run component tests and verify GREEN.

### Task 6: Bootstrap and visual system

**Files:**
- Create: `frontend/src/main.ts`
- Create: `frontend/src/App.vue`
- Create: `frontend/src/styles/tokens.css`
- Create: `frontend/src/styles/base.css`

**Interfaces:**
- Bootstrap installs router and VueQueryPlugin with the shared query client.
- Tokens expose brand, hover, focus, surface, text, border, spacing, radius and shadow values.

- [ ] Add a smoke test assertion to AppShell/Login tests that relies on mounted bootstrap-facing structure and verify RED before adding bootstrap/styles.
- [ ] Implement app entry, root router view, CSS tokens, responsive layout, focus-visible rules and reduced-motion override.
- [ ] Run all frontend tests and verify GREEN.

### Task 7: Final verification and report

**Files:**
- Create: `app/.superpowers/sdd/2026-08-08-sinofgear-phase-a/task-13-report.md` outside the repository.

- [ ] Run `pnpm --dir frontend test --run` and record the exact passing test count.
- [ ] Run `pnpm --dir frontend lint`, `pnpm --dir frontend typecheck`, and `pnpm --dir frontend build`.
- [ ] Run the focused backend identity tests, backend Ruff, Django check, and migration drift check.
- [ ] Run `git diff --check`, inspect scope, write the report, commit with `feat: add novice-friendly Vue application shell`, and confirm a clean worktree.
