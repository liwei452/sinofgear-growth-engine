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

## Fix Round 1: async-session isolation and ARIA tabs

### RED / GREEN

- RED: added lifecycle and accessibility regressions, then ran `SourceImportDialog.test.ts`. The pre-fix implementation failed the tab focus/relationship assertion and did not provide safe file-read recovery. The initial test run recorded 2 failing tests and an unhandled screenshot-preview error in jsdom before test fixtures were completed.
- GREEN: introduced a monotonically increasing session token for close, reopen, organization changes, and submissions. Every upload, ingestion creation, job poll, timer schedule, error, and completion emission checks its captured token after awaiting. File reads have independent read tokens and file-mode checks. The green run passes all dialog and API tests.

### Fix Round 1 commands and results

| Command | Result |
| --- | --- |
| `C:\tmp\task-10b-node\node-v22.21.1-win-x64\node.exe node_modules/vitest/vitest.mjs --run src/modules/leads/SourceImportDialog.test.ts` | GREEN: 6/6 dialog tests passed. |
| `C:\tmp\task-10b-node\node-v22.21.1-win-x64\node.exe node_modules/vitest/vitest.mjs --run src/modules/leads/api.test.ts src/modules/leads/SourceImportDialog.test.ts` | GREEN: 19/19 tests passed in 2 files. |
| `C:\tmp\task-10b-node\node-v22.21.1-win-x64\node.exe node_modules/vue-tsc/bin/vue-tsc.js --noEmit` | PASS. |
| `C:\tmp\task-10b-node\node-v22.21.1-win-x64\node.exe node_modules/eslint/bin/eslint.js .` | PASS. |
| `git diff --check` | PASS. |

### Fix Round 1 self-review

- A stale poll or upload cannot write progress, clear another session's timer, schedule a timer, emit `completed`, or create an ingestion batch after close/reopen, unmount, or organization change.
- CSV/JSON clears prior text before reading; failed reads show `文件没有读取成功，请重新选择文件。` with a `重新选择文件` focus recovery. Stale read completion is ignored after a new file, mode change, reset, close/reopen, or organization change.
- The selector now uses roving tabindex, `aria-controls`, a labelled tabpanel, ArrowLeft/ArrowRight/Home/End activation and focus movement. Disclosure transfers focus to the first newly visible tab.
- Screenshot object URLs are still synchronously revoked on replacement and reset paths; the reset path is reached for close, `open=false`, organization changes, and unmount.

## Fix Round 2: reset invalidated submission state

- RED: the new close-during-deferred-upload/reopen regression failed because the reopened action stayed `正在提交…` and disabled.
- GREEN: reset now clears `submitting` and progress synchronously while incrementing the session; stale finally blocks remain unable to mutate the newer session. The regression proves a new valid URL import proceeds and the old upload remains inert.
- Verification: focused API+dialog suite passed 20/20; `vue-tsc --noEmit` and ESLint passed; full frontend Vitest passed 30 files / 205 tests; `git diff --check` passed.
