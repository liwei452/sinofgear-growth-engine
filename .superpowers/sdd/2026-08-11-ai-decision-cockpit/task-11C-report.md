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
