# Task 11C report — beginner promotion experience

## Status

Implemented the beginner `/promotion` experience while preserving `/content-factory` as the existing advanced workspace. The implementation uses a thin `PromotionPage.vue` wrapper and the existing `ContentFactoryPage`, `ContentBriefWizard`, query keys, APIs, pagination, permissions, and generation-job lifecycle.

Commit: `feat: add beginner promotion experience` (this report is included in that commit).

## Scope delivered

- Added `ContentFactoryPage` prop `experience?: "ordinary" | "advanced"`, default `advanced`.
- Added `PromotionPage.vue`, which renders `ContentFactoryPage experience="ordinary"`.
- Replaced the temporary promotion transition component in the production route wiring with `PromotionPage`.
- Added the exact ordinary heading `你今天想推广什么？`, the three stages `选择推广目标`, `确认 AI 方案`, `批准后执行`, and the action `让 AI 给我方案`.
- Kept campaigns, content briefs, jobs, summary/error details, and record-management controls behind `查看高级记录` in ordinary mode.
- Kept the advanced route and all existing content-factory workflows available by default.
- Added ordinary-mode Chinese job status/action/error wording and hid raw job IDs, raw status enums, and provider error details.
- Added organization-change invalidation for in-flight polling/UI actions so an old organization response cannot populate the current organization.

## TDD evidence

### RED 1 — ordinary experience absent

Command (the configured `node` wrapper was unavailable, so the same checked-in Vitest entry point was launched with Codex's bundled Node runtime):

```powershell
& 'C:\Users\Administrator\AppData\Local\Programs\OpenAI\Codex\resources\cua_node\bin\node.exe' node_modules/vitest/vitest.mjs --run src/modules/content/PromotionPage.test.ts src/modules/content/ContentFactoryPage.test.ts src/app/router.test.ts
```

Result: exit 1. `PromotionPage.test.ts` and `router.test.ts` failed to resolve missing `PromotionPage.vue`; the unchanged content-factory suite passed 14/14. This was the expected failure because the wrapper and ordinary experience did not exist.

### GREEN 1 — ordinary experience and routing

Same command after the minimal wrapper and experience mode were implemented.

Result: exit 0; 3 files passed, 36 tests passed.

### RED 2 — stale organization polling response

Command:

```powershell
& 'C:\Users\Administrator\AppData\Local\Programs\OpenAI\Codex\resources\cua_node\bin\node.exe' node_modules/vitest/vitest.mjs --run src/modules/content/ContentFactoryPage.test.ts
```

Result: exit 1; 1 failed, 14 passed. The deferred job response from `org-1` reappeared after switching to `org-2`.

### GREEN 2 — organization-scoped async lifecycle

Same command after scoping active polling and action completions to the captured organization and clearing timers/UI state on organization change.

Result: exit 0; 15/15 tests passed.

### RED 3 — honest pagination and recovery edge cases

Command:

```powershell
& 'C:\Users\Administrator\AppData\Local\Programs\OpenAI\Codex\resources\cua_node\bin\node.exe' node_modules/vitest/vitest.mjs --run src/modules/content/PromotionPage.test.ts
```

Result: exit 1; 2 failed, 4 passed. The action was incorrectly disabled when a safe next product page existed, and an initial campaign-load error had no ordinary recovery control.

### GREEN 3 — paginated data and ordinary recovery

Same command after allowing a known next product page and adding `重新检查已有推广资料`.

Result: exit 0; 6/6 tests passed.

## Final verification

Because `C:\Users\Administrator\.local\bin\node.cmd` and `npm.cmd` point to a removed `C:\tmp\codex-global-tools\nodejs` runtime, and the Codex-bundled npm package is incomplete, project tools were invoked directly with the Codex-bundled Node executable. No dependencies were installed or changed.

Focused promotion/content/router/shell tests:

```powershell
& 'C:\Users\Administrator\AppData\Local\Programs\OpenAI\Codex\resources\cua_node\bin\node.exe' node_modules/vitest/vitest.mjs --run src/modules/content/PromotionPage.test.ts src/modules/content/ContentFactoryPage.test.ts src/app/router.test.ts src/app/AppShell.test.ts
```

Result: exit 0; 4 files passed, 49 tests passed.

Full frontend suite:

```powershell
& 'C:\Users\Administrator\AppData\Local\Programs\OpenAI\Codex\resources\cua_node\bin\node.exe' node_modules/vitest/vitest.mjs --run
```

Result: exit 0; 34 files passed, 285 tests passed.

Typecheck:

```powershell
& 'C:\Users\Administrator\AppData\Local\Programs\OpenAI\Codex\resources\cua_node\bin\node.exe' node_modules/vue-tsc/bin/vue-tsc.js --noEmit
```

Result: exit 0, no diagnostics.

Lint:

```powershell
& 'C:\Users\Administrator\AppData\Local\Programs\OpenAI\Codex\resources\cua_node\bin\node.exe' node_modules/eslint/bin/eslint.js .
```

Result: exit 0, no diagnostics.

Build:

```powershell
& 'C:\Users\Administrator\AppData\Local\Programs\OpenAI\Codex\resources\cua_node\bin\node.exe' node_modules/vite/bin/vite.js build
```

Result: exit 0; 150 modules transformed; production bundle built successfully.

`git diff --check`: exit 0.

Task 11D E2E was not added or run.

## Self-review

### Progressive disclosure

- The initial ordinary DOM contains the goal heading, stages, readiness, action, and disclosure button only.
- It does not render campaign names, the `内容需求` or `生成任务` sections, job IDs, job enums, advanced summary labels, or advanced query errors.
- `查看高级记录` reveals real campaign records, brief records, job records, summary/error recovery, and existing management actions. No records were copied into a second data model.

### Permissions

- `campaigns.manage` controls whether proposal creation is offered.
- `products.read` is required before offering a real product-based proposal.
- Existing read/manage/review/content/job permission checks remain the authority for queries and record actions.
- Missing optional asset/knowledge read permissions are stated plainly and do not claim those data were inspected.
- Unauthorized users are not shown a non-functional proposal action.

### Data honesty

- Readiness comes from the existing product/platform/asset/approved-knowledge APIs and organization-scoped cache keys.
- No proposal, count, record, product, platform, asset, or knowledge item is fabricated.
- Required product/platform absence disables the action with a concrete next step; a known safe next page remains usable through the existing wizard pagination.
- Initial campaign/product/platform failures block the action and provide ordinary recovery where applicable.
- The real, already-tested `ContentBriefWizard` opens; creation still posts the real campaign/content-brief payloads.

### Backward compatibility

- The optional prop defaults to `advanced`, so all existing call sites retain the advanced page.
- `/content-factory` still mounts `ContentFactoryPage` directly and therefore remains advanced by default.
- Existing content-factory workflow tests remain unchanged in behavior and pass in the full suite; an explicit advanced-mode regression test was added.
- The `/promotion` route already existed in `router.ts` at the starting revision, so route structure/guards did not need duplication or modification; only production component wiring and route tests changed.

### Lifecycle and organization isolation

- Existing cursor collections and query keys remain organization-scoped.
- Polling now records the organization scope per job and verifies it before and after every await and timer callback.
- Organization changes stop all old timers, clear live jobs and transient editor/action state, and make deferred old responses inert.
- Generate/review/revise/job-action completions capture their organization and do not mutate the new organization's UI.
- Unmount cleanup remains intact and covered by existing tests.

## Concerns

- Environment only: the configured global Node/npm wrappers are broken as described above. Direct project-tool verification is complete and green; repository code does not need a workaround.
- The old `PromotionTransitionPage.vue` is now unused but was intentionally left untouched to keep Task 11C scoped and avoid an unrelated deletion.
- No backend, generated schema, dependency, or E2E changes were made.

## Fix Round 1

Addressed review findings C1 and I1-I4. M1 and M2 remain deferred as requested.

### C1 — live permission revocation

- Added permission-derived campaign, brief, job, and generated-content views so cached protected records disappear synchronously when read permissions are revoked while the page remains mounted.
- On revocation, the page cancels and removes the affected organization-scoped queries, resets cursor collections, closes editors that could retain protected data, clears live job state, and stops all job polling timers.
- In-flight job-detail responses now re-check both disclosure state and current permission before mutating UI or scheduling another poll.
- Added tests for mounted live revocation and revocation during an unresolved poll.

### I1 — evidence-based readiness

- Product and asset requests now use `status=ACTIVE`, with filter-aligned organization query keys.
- The page boundary independently filters products/assets to `ACTIVE`, so an over-broad backend response cannot enter readiness counts or the wizard.
- Readiness uses explicit `已加载 N 项` wording and states that counts cover loaded pages only.
- An empty first product page with a safe next cursor blocks proposal entry and exposes `加载更多产品资料`; the action becomes available only after an eligible product has actually loaded.
- Added mixed-status, empty-first-page, and multi-page coverage.

### I2 — platform permission and meaning

- Platform definitions are requested only with `memberships.read`.
- Missing permission blocks proposal entry with an explicit explanation and makes no platform request.
- UI copy now identifies these records as system-supported platform definitions and does not imply an account connection.
- Live membership-read revocation clears the platform collection and closes an open wizard.

### I3 — disclosed job observation and controlled recovery

- Ordinary mode does not request the jobs list or begin polling until `查看高级记录` is opened.
- Closing disclosure stops polls and clears live job state; advanced mode retains the existing always-visible behavior.
- Job list, polling, action, and generation errors are contained inside the advanced job section. Ordinary users receive controlled Chinese recovery text and `重新加载生成记录`; backend error details are not exposed.

### I4 — approved knowledge boundary

- The frontend response type now represents all backend concept statuses.
- Only `APPROVED` concepts are counted and passed into the brief wizard, even when the response contains suggested, rejected, or deprecated records.

### TDD evidence

- C1 RED: both live-revocation tests failed because cached campaign/job records remained visible and an in-flight poll could repopulate the revoked job.
- C1 GREEN: 2/2 targeted tests passed after cancellation, clearing, gating, and post-await checks.
- I1/I2 RED: 3/3 targeted tests failed on unfiltered request paths, dishonest empty-page behavior, and unconditional platform loading.
- I1/I2 GREEN: 3/3 targeted tests passed after ACTIVE filters, loaded-page copy, explicit load-more gating, and membership permission enforcement.
- I4 RED/GREEN: the mixed-status response initially counted 2 concepts; after boundary filtering the test passed with exactly 1 approved concept.
- I3 RED/GREEN: the hidden ordinary page initially fetched `/api/v1/jobs`; after disclosure-gated observation, the test passed with zero hidden requests and controlled disclosed recovery.

### Fix Round 1 verification

The configured npm/node shims still target a removed runtime, so the verified Codex runtime Node executable was used directly; no dependency was installed or changed.

- Focused content tests: 17/17 passed.
- Focused promotion tests: 10/10 passed.
- Full frontend suite: 34 files, 291/291 tests passed.
- Typecheck: exit 0, no diagnostics.
- Lint: exit 0, no diagnostics.
- Production build: exit 0, 150 modules transformed.
- `git diff --check`: exit 0.
- Backend, generated schema, dependencies, E2E, plan, and ledger were not changed.

## Fix Round 2

Commit: `2c6cc27 fix: preserve advanced promotion recovery`.

Addressed the remaining review findings C1 and I3 and the Fix Round 1 regression N1. M1 and M2 remain deferred as requested.

### C1 — complete live permission revocation

- Added current-permission gates for product, asset, and knowledge-derived wizard inputs so retained query data cannot remain visible after permission loss.
- Added synchronous revocation watchers for `products.read`, `assets.read`, and `knowledge.read`. Each watcher resets the relevant collection where applicable, cancels/removes the organization-scoped cache, and immediately closes both creation and edit wizards.
- Added a synchronous `campaigns.manage` watcher that immediately closes the writable wizard/editor and clears the active write marker after manage permission is revoked.
- Guarded the ordinary product recovery action with the current `products.read` permission.
- Added a post-await `canObserveJobs` check to `refreshJob`, preventing a deferred 409 recovery detail response from repopulating `liveJobs` after `jobs.read` disappears.
- Added mounted regressions that open the real wizard and then revoke each of `products.read`, `assets.read`, `knowledge.read`, and `campaigns.manage`, plus product-retry and deferred-refresh revocation coverage.

### I3 — controlled ordinary job pagination recovery

- Added a permission/disclosure-safe computed pagination error for jobs.
- In ordinary mode, a failed next-page request now renders the fixed Chinese text `生成记录下一页暂时无法加载，请重新加载后再试。` and the concrete action `重新加载更多生成记录`.
- Backend English, error codes, and cursor details remain absent from the ordinary DOM. Advanced mode retains the existing diagnostic pagination message.
- Added a failed safe-next-cursor regression whose backend response contains `Invalid cursor JOB_CURSOR_EXPIRED_400`; the test asserts that the detail is not rendered.

### N1 — preserve advanced stale-link recovery

- Kept ordinary mode on ACTIVE product/asset requests and the APPROVED concept request.
- Changed advanced `/content-factory` product, asset, and concept sources to unfiltered list requests, while retaining organization-scoped, filter-aligned query keys.
- The wizard now presents only ACTIVE products/assets and APPROVED supported concepts as new selections.
- Already-linked inactive/archived/rejected/deprecated records are shown with `不可用，仅可移除`. Their one-way removal row disappears after unchecking, so the stale relationship cannot be re-added as a new selection.
- Existing product/asset/concept IDs outside the loaded page are represented by selected, remove-only provenance placeholders. Existing concept roles remain preservable until the operator removes the relationship.
- Added tests for loaded stale product/asset/concept visibility and removal payloads, a relationship outside loaded pages, ordinary creation exclusion of unlinked unavailable rows, and advanced page integration using the unfiltered sources.

### Fix Round 2 TDD evidence

#### C1/I3 RED

Initial command after adding the page-level regressions:

```powershell
& 'C:\Users\Administrator\AppData\Local\Programs\OpenAI\Codex\resources\cua_node\bin\node.exe' node_modules/vitest/vitest.mjs run src/modules/content/ContentFactoryPage.test.ts --config vite.config.ts --reporter=dot
```

Result: exit 1; 24 tests ran, 6 failed and 18 passed. This first run also exposed that the new ordinary-only fixtures had to pass `experience="ordinary"` explicitly because the component default is intentionally advanced. After correcting that test setup, inspection confirmed the intended implementation RED paths: no product/asset/knowledge/manage revocation watchers, no post-await permission check in `refreshJob`, an unguarded product retry, and direct rendering of `jobPages.error.value`.

GREEN command after the minimal permission and pagination changes:

```powershell
& 'C:\Users\Administrator\AppData\Local\Programs\OpenAI\Codex\resources\cua_node\bin\node.exe' node_modules/vitest/vitest.mjs run src/modules/content/ContentFactoryPage.test.ts --config vite.config.ts --reporter=dot
```

Result: exit 0; 1 file passed, 24/24 tests passed.

#### N1 wizard RED

Command:

```powershell
& 'C:\Users\Administrator\AppData\Local\Programs\OpenAI\Codex\resources\cua_node\bin\node.exe' node_modules/vitest/vitest.mjs run src/modules/content/ContentBriefWizard.test.ts --config vite.config.ts --reporter=dot
```

Result: exit 1; 3 failed, 4 passed. Linked unavailable records had no unavailable/remove-only label, outside-page linked provenance had no visible checkbox, and an unlinked archived product remained selectable during creation.

GREEN with the eligibility and remove-only reconciliation implemented: exit 0; 1 file passed, 7/7 tests passed.

#### N1 page integration RED

Command:

```powershell
& 'C:\Users\Administrator\AppData\Local\Programs\OpenAI\Codex\resources\cua_node\bin\node.exe' node_modules/vitest/vitest.mjs run src/modules/content/ContentFactoryPage.test.ts --config vite.config.ts -t "loads linked unavailable records" --reporter=dot
```

Result: exit 1; 1 failed, 24 skipped. The editor displayed ID-only placeholders because the advanced page still requested globally filtered sources and could not load the stale record metadata.

GREEN after separating ordinary and advanced query filters: exit 0; 1 passed, 24 skipped. The linked archived product, archived asset, and rejected concept were visible by name with remove-only labels, and the test observed the unfiltered advanced request URLs.

### Fix Round 2 final verification

The configured global npm/node shims still point to a removed runtime, so the same Codex-bundled Node executable was used directly. No dependency was installed or changed.

Focused promotion/content/wizard tests:

```powershell
& 'C:\Users\Administrator\AppData\Local\Programs\OpenAI\Codex\resources\cua_node\bin\node.exe' node_modules/vitest/vitest.mjs run src/modules/content/PromotionPage.test.ts src/modules/content/ContentFactoryPage.test.ts src/modules/content/ContentBriefWizard.test.ts --config vite.config.ts --reporter=dot
```

Result: exit 0; 3 files passed, 42/42 tests passed.

Full frontend suite:

```powershell
& 'C:\Users\Administrator\AppData\Local\Programs\OpenAI\Codex\resources\cua_node\bin\node.exe' node_modules/vitest/vitest.mjs run --config vite.config.ts --reporter=dot
```

Result: exit 0; 34 files passed, 302/302 tests passed.

Typecheck:

```powershell
& 'C:\Users\Administrator\AppData\Local\Programs\OpenAI\Codex\resources\cua_node\bin\node.exe' node_modules/vue-tsc/bin/vue-tsc.js --noEmit
```

Result: exit 0, no diagnostics.

Lint:

```powershell
& 'C:\Users\Administrator\AppData\Local\Programs\OpenAI\Codex\resources\cua_node\bin\node.exe' node_modules/eslint/bin/eslint.js .
```

Result: exit 0, no diagnostics.

Production build:

```powershell
& 'C:\Users\Administrator\AppData\Local\Programs\OpenAI\Codex\resources\cua_node\bin\node.exe' node_modules/vite/bin/vite.js build
```

Result: exit 0; 150 modules transformed; production bundle built successfully.

Diff check:

```powershell
git diff --check
```

Result: exit 0, no whitespace errors.

No backend, generated API/schema, dependency, E2E, project-plan, or task-ledger files changed. Task 11D E2E was not added or run.

### Fix Round 2 self-review

#### Permission and async boundaries

- Every read permission named by the re-review now has both a current-use gate and revocation cleanup at the page boundary.
- Wizard closure is synchronous with permission-cache mutation, so protected selections and write controls do not survive into a later render.
- Product and asset query cleanup uses organization prefixes, covering both ordinary filtered and advanced unfiltered variants.
- Knowledge cleanup removes the currently active ordinary/advanced concept query key.
- Both polling and 409 refresh paths re-check current observation authority after awaiting a job detail response.

#### Ordinary error privacy

- Initial job observation remains disclosure-gated.
- List, poll, action, generation, and now cursor-page errors all use controlled ordinary Chinese recovery wording.
- The failed-cursor test proves backend English/code text does not cross the ordinary rendering boundary.

#### Advanced backward compatibility and data honesty

- `/promotion` continues to count and offer only ACTIVE/APPROVED data.
- `/content-factory` can load existing stale relationship metadata, but the shared wizard still forbids every unavailable record as a new relationship.
- Missing-page placeholders use only real IDs from the persisted brief; they do not fabricate resources or introduce a relationship.
- Removing a stale relationship changes the PATCH payload. Leaving a visible stale relationship selected preserves its real ID and existing concept role for deliberate operator recovery.

### Fix Round 2 concerns

- Environment only: the configured global Node/npm wrappers remain broken; direct project-tool verification with the bundled Node runtime is complete and green.
- The advanced unfiltered lists still load through normal cursor pages. Linked records outside loaded pages therefore use explicit ID provenance placeholders rather than issuing unsupported per-record asset/concept requests.
- M1 (unused transition component) and M2 (`aria-controls` for disclosure) remain intentionally deferred.
- This requested bookkeeping append is intentionally left uncommitted, so commit `2c6cc27` and all source code remain unchanged; `task-11C-report.md` is the only tracked worktree modification.

## Fix Round 3

Requested commit: `fix: guard promotion revision completion`.

Addressed the remaining Important finding from the Fix Round 2 re-review. M1 and M2 remain deferred as requested.

### Deferred revision completion authority boundary

- `createBriefRevision` now captures both the initiating organization and membership ID before starting the revision request.
- A shared completion guard requires that the component is still mounted, the organization and membership are unchanged, and the current session still has `campaigns.manage`.
- The guard runs immediately after the revision request and again after brief-query invalidation, covering permission or session changes during either awaited operation.
- The error path uses the same guard, so a rejected late response cannot post a stale action error after management authority disappears.
- A deterministic regression starts a revision, revokes `campaigns.manage` while the response is unresolved, resolves it, and proves that no editor, success notice, or alert appears. It then restores the permission and proves the late revision still does not reopen the editor or repopulate stale UI state.

### Sibling awaited-management audit

- `ready`: completion invalidates the readable brief collection and may report the real server transition, but it does not reopen or repopulate a protected write surface. No analogous gap was found.
- `startGeneration`: an accepted server job is represented only in the separately `jobs.read`-gated observation surface; polling also re-checks current job visibility. Revoking `content.manage` cannot restore a generation control or editor. No analogous gap was found.
- `jobAction`: a completed cancel/retry reflects a real job state in the separately readable job surface and does not restore a management control. No analogous gap was found.
- `saved`: a temporary deferred PATCH probe revoked `campaigns.manage` before settlement. The existing synchronous watcher unmounted the wizard, and the late child completion remained inert without posting the parent success notice. Because it passed before any save-path production change, the diagnostic test was removed and no speculative hardening was added.

### Fix Round 3 TDD evidence

The final deterministic RED command was:

```powershell
& 'C:\Users\Administrator\AppData\Local\Programs\OpenAI\Codex\resources\cua_node\bin\node.exe' node_modules/vitest/vitest.mjs run src/modules/content/ContentFactoryPage.test.ts --config vite.config.ts -t "does not reopen a deferred revision" --reporter=dot
```

RED result: exit 1; 1 failed and 25 skipped. After the deferred revision resolved, the editor reopened and the stale success notice `已从可生成需求创建新的草稿版本，请检查并保存。` appeared despite the revoked permission.

GREEN after adding the organization, membership-session, and current-permission completion guard: exit 0; 1 passed and 25 skipped.

The sibling saved-completion diagnostic used a deferred draft PATCH and the same live permission revocation. It passed without save-path production changes, confirming there was no concrete analogous reopen/repopulate gap to retain as a regression.

### Fix Round 3 final verification

The configured global npm/node shims still point to a removed runtime, so the verified Codex-bundled Node executable was used directly. No dependency was installed or changed.

Focused promotion/content/wizard tests:

```powershell
& 'C:\Users\Administrator\AppData\Local\Programs\OpenAI\Codex\resources\cua_node\bin\node.exe' node_modules/vitest/vitest.mjs run src/modules/content/PromotionPage.test.ts src/modules/content/ContentFactoryPage.test.ts src/modules/content/ContentBriefWizard.test.ts --config vite.config.ts --reporter=dot
```

Result: exit 0; 3 files passed, 43/43 tests passed.

Full frontend suite:

```powershell
& 'C:\Users\Administrator\AppData\Local\Programs\OpenAI\Codex\resources\cua_node\bin\node.exe' node_modules/vitest/vitest.mjs run --config vite.config.ts --reporter=dot
```

Result: exit 0; 34 files passed, 303/303 tests passed.

Typecheck:

```powershell
& 'C:\Users\Administrator\AppData\Local\Programs\OpenAI\Codex\resources\cua_node\bin\node.exe' node_modules/vue-tsc/bin/vue-tsc.js --noEmit
```

Result: exit 0, no diagnostics.

Lint:

```powershell
& 'C:\Users\Administrator\AppData\Local\Programs\OpenAI\Codex\resources\cua_node\bin\node.exe' node_modules/eslint/bin/eslint.js .
```

Result: exit 0, no diagnostics.

Production build:

```powershell
& 'C:\Users\Administrator\AppData\Local\Programs\OpenAI\Codex\resources\cua_node\bin\node.exe' node_modules/vite/bin/vite.js build
```

Result: exit 0; 150 modules transformed; production bundle built successfully.

### Fix Round 3 self-review

- The fix is scoped to the one completion that could recreate a protected editor from a server response.
- It checks both identity continuity and present authorization, rather than treating request-time permission as durable.
- It checks before query invalidation and again before UI mutation, so neither awaited boundary can bypass the guard.
- Permission restoration does not replay or surface the discarded late revision response.
- No sibling completion was changed without a concrete analogous failure.
- Backend, generated API/schema, dependencies, E2E, project-plan, and task-ledger files remain unchanged. Task 11D E2E was not added or run.

### Fix Round 3 concerns

- Environment only: the configured global Node/npm wrappers remain broken; direct project-tool verification with the bundled Node runtime is complete and green.
- The server may still have created the revision before permission revocation reached the client. The client intentionally discards that stale response; a later authorized brief refresh is the source of truth.
- M1 (unused transition component) and M2 (`aria-controls` for disclosure) remain intentionally deferred.
