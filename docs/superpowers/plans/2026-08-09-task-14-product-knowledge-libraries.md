# Task 14 Product and Knowledge Libraries Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the product and knowledge placeholders with permission-aware, novice-friendly interfaces backed only by the existing organization-scoped APIs.

**Architecture:** Keep backend business rules authoritative and expose the authenticated membership's stable permission codes through `/auth/me`. Add focused typed frontend API modules, then compose two route-level Vue pages from small dialog/panel components. TanStack Query owns server state; mutations invalidate exact query-key families; product edits retain the GET ETag and send it through `If-Match`.

**Tech Stack:** Django REST Framework, pytest, Vue 3, TypeScript, Vue Router, TanStack Vue Query, Vitest, Testing Library, existing CSS token system.

## Global Constraints

- Do not start Task 15 and do not use subagents.
- Use real API records only; never synthesize product, concept, relation, alias, or evidence data in production.
- Keep `#005BA8` as the primary brand color and avoid a large UI library.
- Product pagination may follow only same-origin `/api/` URLs; reject external origins and malformed cursors.
- Product PATCH must use the ETag from the latest GET as `If-Match`; `409` never blindly overwrites.
- Frontend visibility uses permission codes from `/auth/me`; backend permissions remain authoritative.
- SYSTEM knowledge creation/review is never inferred from role names.
- Every behavioral change follows RED → GREEN → refactor and ships with its regression test.

---

### Task 1: Authenticated Permission Contract

**Files:**
- Modify: `backend/apps/identity/serializers.py`
- Modify: `backend/apps/identity/tests/test_current_user_api.py`
- Modify: `frontend/src/modules/auth/auth.ts`

**Interfaces:**
- Produces: `CurrentUser.membership.permissions: string[]`, sorted and copied only from the authenticated membership's persisted role.

- [ ] Write a backend test that assigns distinct permission arrays to own and foreign memberships, calls `/api/v1/auth/me`, and expects only the sorted own-role permissions.
- [ ] Run `pytest apps/identity/tests/test_current_user_api.py -q` and observe the missing field failure.
- [ ] Add `permissions: sorted(str(code) for code in membership.role.permissions)` to `CurrentUserSerializer` and the matching TypeScript field.
- [ ] Re-run the focused backend test and existing auth/router frontend tests.

### Task 2: Typed API Boundary and Safe Metadata

**Files:**
- Modify: `frontend/src/api/client.ts`
- Modify: `frontend/src/api/client.test.ts`
- Create: `frontend/src/modules/products/api.ts`
- Create: `frontend/src/modules/products/api.test.ts`
- Create: `frontend/src/modules/knowledge/api.ts`
- Create: `frontend/src/modules/knowledge/api.test.ts`

**Interfaces:**
- Produces: `apiRequestWithMeta<T>(path, options): Promise<{ data: T | undefined; response: Response }>`.
- Produces: product types, query keys, list/detail/create/patch functions, and `safeProductPageUrl`.
- Produces: concept/alias/relation/evidence/resolution types, query keys, list/create/review/resolve functions.

- [ ] Write client tests proving successful headers are available without weakening credentials, CSRF, or safe error handling.
- [ ] Write product API tests proving next/previous same-origin URLs work and `https://evil.example`, protocol-relative URLs, non-`/api/` paths, and malformed URLs are rejected before fetch.
- [ ] Write knowledge API tests for exact concept, review-action, and resolve request contracts.
- [ ] Run the three focused test files and observe missing-module/API failures.
- [ ] Extract one internal request function returning response metadata; preserve `apiRequest<T>` as the data-only wrapper.
- [ ] Implement literal TypeScript response types and exact query-key builders; do not normalize invented fields.
- [ ] Re-run focused API tests.

### Task 3: Guided Product Library

**Files:**
- Create: `frontend/src/modules/products/ProductLibraryPage.vue`
- Create: `frontend/src/modules/products/ProductLibraryPage.test.ts`
- Create: `frontend/src/modules/products/ProductFormDialog.vue`
- Create: `frontend/src/modules/products/ProductFormDialog.test.ts`
- Modify: `frontend/src/styles/base.css`

**Interfaces:**
- Consumes: product API/query keys, approved concepts from knowledge API, and `products.manage`.
- Produces: route page for `/products`, create/edit dialog, responsive table/cards, filters, pagination, and ETag conflict recovery.

- [ ] Write page tests for loading skeleton, empty guidance, error retry, status/concept filtering, pagination, responsive semantic content, details, and hidden write controls without `products.manage`.
- [ ] Run page tests and observe missing component failures.
- [ ] Implement the list query using exact URL parameters and same-origin pagination helpers; render names, status text, specifications, MOQ/lead time, and real linked concepts.
- [ ] Re-run page tests.
- [ ] Write dialog tests for cancel, required/range/URL validation, create success, backend field errors with first-error focus, GET ETag + PATCH `If-Match`, `409` reload, `403` read-only feedback, and archive status mutation.
- [ ] Run dialog tests and observe missing behavior failures.
- [ ] Implement one accessible `role="dialog"` with common fields first and `<details>` sections for gear/manufacturing/inspection/internal fields; group approved concepts by compatible product role.
- [ ] On create invalidate lists and show a live success message; on edit fetch fresh detail+ETag, patch only through `If-Match`, and expose reload on `409`.
- [ ] Re-run all product tests.

### Task 4: Guided Knowledge Library

**Files:**
- Create: `frontend/src/modules/knowledge/KnowledgeLibraryPage.vue`
- Create: `frontend/src/modules/knowledge/KnowledgeLibraryPage.test.ts`
- Create: `frontend/src/modules/knowledge/KnowledgeConceptDialog.vue`
- Create: `frontend/src/modules/knowledge/KnowledgeConceptDialog.test.ts`
- Create: `frontend/src/modules/knowledge/AliasResolver.vue`
- Create: `frontend/src/modules/knowledge/AliasResolver.test.ts`
- Modify: `frontend/src/styles/base.css`

**Interfaces:**
- Consumes: knowledge API/query keys and `knowledge.create`, `knowledge.review_organization`, `knowledge.manage_system`, `knowledge.deprecate`.
- Produces: route page for `/knowledge`, organization suggestion dialog, legal review controls, and collapsible resolver.

- [ ] Write page tests for plain-language introduction, search by Chinese/English/code, status/type/scope filters, counts, evidence counts, empty/error states, and permission-controlled create/review controls.
- [ ] Run page tests and observe missing component failures.
- [ ] Implement client-side filtering over the real visible concept response and lightweight real counts for aliases/relations/evidence.
- [ ] Re-run page tests.
- [ ] Write form tests for ORGANIZATION-only suggestion payload, duplicate-code and field error display, submit state, cancel, and success invalidation.
- [ ] Write review tests for legal actions by permission, required rejection reason, response-driven state refresh, and absence of SYSTEM controls without `knowledge.manage_system`.
- [ ] Implement the dialog and action controls without role-name checks.
- [ ] Write resolver tests for unique, ambiguous, and empty results and prove it never calls an alias-create endpoint.
- [ ] Implement the collapsible resolver with text/language inputs and an `aria-live` result region.
- [ ] Re-run all knowledge tests.

### Task 5: Real Lazy Routes and Shell Integration

**Files:**
- Modify: `frontend/src/app/router.ts`
- Modify: `frontend/src/app/router.test.ts`
- Modify: `frontend/src/main.ts`
- Modify: `frontend/src/app/AppShell.test.ts`

**Interfaces:**
- Produces: lazy `/products` and `/knowledge` route components; six remaining future routes retain `PlaceholderPage`.

- [ ] Update router tests first to require distinct product/knowledge components and retain protected-route behavior.
- [ ] Run router/AppShell tests and observe placeholder component failures.
- [ ] Extend `AppRouteComponents` with `Products` and `Knowledge`; define lazy imports in `main.ts`; keep route meta titles and auth guard unchanged.
- [ ] Re-run router, shell focus, products, and knowledge route tests.

### Task 6: Verification, Report, and Commit

**Files:**
- Create: `C:/Users/Administrator/Documents/网站/app/.superpowers/sdd/2026-08-08-sinofgear-phase-a/task-14-report.md`

- [ ] Run `pnpm test --run`, `pnpm typecheck`, `pnpm lint`, and `pnpm build` in `frontend`.
- [ ] Run focused `identity`, `catalog`, and `knowledge` pytest suites, Ruff, Django check, and migration drift checks.
- [ ] Because the shared API client and `/auth/me` contract changed, run full backend pytest.
- [ ] Run `git diff --check`, review scope, write the Task 14 report with RED/GREEN evidence and exact counts.
- [ ] Commit implementation as `feat: add guided product and knowledge libraries` and confirm a clean worktree.
