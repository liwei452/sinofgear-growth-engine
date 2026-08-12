# Task 7 Report — Administrator DeepSeek Settings Page

Status: DONE

## Delivered

- Added the administrator-only `/ai-settings` route and lazy-loaded page.
- Added a Chinese, beginner-friendly DeepSeek setup experience using the approved SinofGear blue cockpit visual language.
- Added first-run guidance in the application shell without blocking ordinary non-AI workflows.
- Added permission-gated advanced navigation for `credentials.manage`.
- Added test-before-save, stored-key retest, key replacement, explicit deletion confirmation, and provider limit controls.
- Added truthful model-routing explanations and a usage placeholder that does not invent telemetry.
- Added organization-scoped provider configuration queries and cache clearing on organization or permission changes.
- Regenerated the checked-in OpenAPI TypeScript schema and used its generated types in the page API module.

## Secret lifecycle and safety

- The API Key is held only in transient component/request memory.
- It is never written to query data, mutation variables, route state, browser storage, DOM text, or error output.
- Test and save flows clear the input after every completed request.
- Escape, backdrop close, reset, successful replacement, and failed replacement all clear the input.
- Only the server-provided key suffix is rendered after setup.
- Provider recovery codes are mapped to safe beginner-facing Chinese messages rather than displayed raw.

## TDD evidence

RED was established before implementation with expected failures for the missing settings page, route, permission-gated navigation, first-run banner, and organization cache clearing.

GREEN verification:

- Full frontend suite: 45 files, 515 tests passed.
- DeepSeek settings page: 5 tests passed.
- TypeScript/Vue type check: passed.
- ESLint: passed with no warnings or errors.
- Production build: passed.
- Generated API schema check: current.
- `git diff --check`: passed (only existing line-ending notices for the unrelated backend test settings file).

## UI/UX guidance applied

The local UI/UX design skill was used for accessibility, responsive layout, touch targets, status communication, and modal behavior. The suggested generic purple palette was intentionally not adopted because the approved product reference and existing design system use SinofGear blue. The page uses responsive cards and has a dedicated 390px viewport contract test.

## Scope notes

- No paid provider request was executed by this task.
- Actual usage telemetry is not yet exposed by the local API, so the UI explicitly says usage will appear in audit after tasks run.
- `backend/config/test_settings.py` was pre-existing and was not modified or included in this task's commit.

## Review fix round 1

- Captured immutable organization and permission-generation context for test, save, and delete operations. Late responses after an organization switch, permission loss, or unmount are ignored and cannot update another organization's cache or UI.
- Permission loss immediately hides the settings page, clears provider cache, closes dialogs, and wipes transient key/test/form/status state. Every operation handler now also checks current permission and organization.
- Connected limits are now read-only summaries. Editing happens only in the secure settings dialog and requires the API Key; limits and key are submitted together through the existing tested PUT contract. Failed saves preserve the server-backed values.
- Both settings and deletion dialogs use the shared modal focus lifecycle: initial heading focus, Tab/Shift+Tab trapping, Escape/backdrop/cancel closure, background inerting, and exact opener restoration.
- The first-run banner is displayed only after a successful configuration query explicitly reports a non-connected state. Query failures never claim the provider is unconfigured.

Round 1 verification:

- RED: 5 new regression tests failed for the reviewed behaviors.
- Targeted GREEN: 24/24 tests passed.
- Full frontend GREEN: 45 files, 520/520 tests passed.
- Type check, ESLint, production build, generated API check, and diff check passed.

## Review fix round 3

- The shared modal focus lifecycle now marks itself disposed before any unmount cleanup and uses idempotent cleanup.
- Deferred `nextTick` setup exits immediately after an early unmount and also checks disposal between inerting, stack registration, listener registration, and focus.
- Added direct lifecycle coverage with persistent element refs to prove immediate unmount cannot leave delayed `inert`, `aria-hidden`, keyboard listeners, stack behavior, or focus side effects.

Round 3 verification:

- RED: the persistent-ref immediate-unmount regression failed by leaving background `inert`.
- Targeted GREEN: 13/13 modal and DeepSeek page tests passed.
- Full frontend GREEN: 46 files, 524/524 tests passed.
- Type check, ESLint, and production build passed.

## Review fix round 2

- `OperationModal` now teleports to `document.body`, keeping the modal outside the inert application subtree. While open, all body siblings receive reference-counted `inert` and `aria-hidden="true"`; their original values are restored on close or unmount.
- Delete failures remain inside the deletion dialog with one safe `role="alert"` / assertive live region. Focus moves to that feedback, the dialog stays open, and the administrator can retry or cancel without page-level error focus escaping behind the modal.

Round 2 verification:

- RED: 2 new regression tests failed for inert modal ancestry and delete-failure feedback.
- Targeted GREEN: 11/11 DeepSeek page tests passed.
- Full frontend GREEN: 45 files, 522/522 tests passed.
- Type check, ESLint, production build, generated API check, and diff check passed.
