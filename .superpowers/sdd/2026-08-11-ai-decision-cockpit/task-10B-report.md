# Task 10B report: guided public-signal import dialog

## Delivered

- Added `SourceImportDialog` with URL, paste, screenshot, CSV, and JSON import modes. URL and paste are presented first; the other modes are disclosed by the “更多导入方式” control.
- Reused `OperationModal` for modal focus, Escape, inert background, and focus restoration.
- Reused the existing private asset upload API for screenshot submission. CSV/JSON are read locally as UTF-8 text and previewed before submission.
- Added local preview counts and row-level validation messaging, disabled submission for invalid imports, stable idempotency per unchanged intent, organization-scoped job query keys, bounded active-job polling, terminal recovery copy, and screenshot object-URL cleanup.
- Added `isActiveImportJob` as the narrow API helper used by the dialog and covered it in the existing API test suite.

## RED / GREEN evidence

1. RED: the supplied dialog tests were authored before the dialog component existed. The initially requested command could not start because this environment's `node.cmd` points at a missing `C:\tmp\codex-global-tools\nodejs\node.exe` runtime.
2. RED confirmation: with Node 22.21.1 in a temporary tool directory, the same test was run against commit `55dbffb` in a disposable baseline worktree. Vite failed as expected: `Failed to resolve import "./SourceImportDialog.vue" ... Does the file exist?`.
3. GREEN: after implementation, the dialog test passes with both progressive-mode and lifecycle polling assertions.

## Commands and results

| Command | Result |
| --- | --- |
| `cd frontend && node node_modules/vitest/vitest.mjs --run src/modules/leads/SourceImportDialog.test.ts` | Blocked before execution: the supplied Node launcher targets a nonexistent runtime. |
| `C:\tmp\task-10b-node\node-v22.21.1-win-x64\node.exe node_modules/vitest/vitest.mjs --run src/modules/leads/SourceImportDialog.test.ts` | PASS: 2/2 tests. |
| `C:\tmp\task-10b-node\node-v22.21.1-win-x64\node.exe node_modules/vitest/vitest.mjs --run src/modules/leads/api.test.ts src/modules/leads/SourceImportDialog.test.ts` | PASS: 15/15 tests in 2 files. |
| `C:\tmp\task-10b-node\node-v22.21.1-win-x64\node.exe node_modules/vue-tsc/bin/vue-tsc.js --noEmit` | PASS. |
| `C:\tmp\task-10b-node\node-v22.21.1-win-x64\node.exe node_modules/eslint/bin/eslint.js .` | PASS with zero warnings/errors after formatting. |
| `git diff --check` | PASS. |

## Lifecycle and security self-review

- Screenshot preview object URLs are revoked on file replacement, dialog close, `open=false`, and component unmount.
- The polling timer is scheduled only for `QUEUED`, `RUNNING`, and `RETRY_QUEUED`; it is cleared on terminal state, close, and unmount. Terminal success emits `{ batchId, jobId }`; terminal failures provide a short recovery action.
- Job cache lookups use `leadKeys.job(organizationId, jobId)`, preserving organization scope.
- URL acceptance and each local preview use Task 10A's public HTTP(S) and row validation; this dialog has no login, scraping, or outbound-message path. Screenshots use the existing private asset upload path.
- Idempotency keys are retained for the exact same normalized intent and replaced only when that intent changes.
- `OperationModal` is mounted only while `open`, so its existing focus trapping, Escape handling, inert background, and focus restoration apply on each open cycle. Narrow screens use wrapped controls and a one-column tab layout.
- Generated schema, backend, queue page, plan, and ledger were not changed.

## Commit

`feat: add guided public signal imports`

## Concerns

- The workspace's configured Node launcher is broken. Verification used a temporary, untracked Node 22.21.1 runtime at `C:\tmp\task-10b-node`; no project dependency or lockfile was changed.
