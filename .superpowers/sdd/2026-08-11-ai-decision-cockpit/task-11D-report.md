# Task 11D Report — Cockpit Browser Acceptance

## Status

Complete for the bounded pre-Task 12 acceptance scope. The browser suite covers the ordinary five-entry cockpit, the beginner promotion flow, public-signal import through UI evidence viewing, mobile drawer behavior, advanced-mode persistence and recovery, and real role-permission behavior. Final browser acceptance for the full analyze/review decision and two-organization isolation remains a parent Task 12 requirement.

## Scope delivered

- Added `frontend/e2e/ai-decision-cockpit.spec.ts` with four real-browser journeys:
  - ordinary mode exposes exactly Today, Promotion, Customer Opportunities, Results, and Company Profile;
  - an operator completes the real beginner promotion wizard and receives `201` responses from both campaign and content-brief creation;
  - an operator imports a public signal through the real ingestion endpoint, waits for successful completion, verifies the persisted source evidence, uses the production candidate API as an explicitly named pre-Task 12 fixture bridge, and reads the exact source text and URL in the opportunity dialog;
  - a 390 x 844 viewport verifies drawer focus entry, focus wrapping, Escape close, focus restoration, and five ordinary entries;
  - read-only and reviewer sessions do not expose import controls, a forged read-only import receives `403`, advanced links survive navigation and reload, and returning to ordinary mode survives reload.
- Kept the completed import dialog mounted so the user can actually see the successful completion state before closing it.
- Allowed persisted opportunities to remain visible while an analysis status banner is present. Previously a single `DISCOVERED` or `ANALYZING` candidate hid the entire opportunity list, blocking evidence review.
- Narrowed the existing Phase A content-brief locator to its semantic section. The cockpit added another workflow card carrying the same campaign name, which made the old global locator ambiguous.

## TDD evidence

### RED

Focused command:

```text
pnpm test:e2e ai-decision-cockpit.spec.ts --grep "a beginner imports"
```

The real ingestion request returned `202`, the eager ingestion job reached `SUCCEEDED`, and evidence persisted, but the browser could not find the completed-import message because `LeadRadarPage` immediately unmounted the dialog. After preserving the dialog, the same journey exposed the second behavior defect: a pending-analysis banner replaced the opportunity list, so the imported evidence could not be opened.

One earlier attempt did not run tests because the machine's default Node shim pointed to a missing runtime. All recorded RED/GREEN runs below used the bundled Codex Node runtime; this was an environment invocation issue, not a product failure.

### GREEN

- Focused import/evidence journey: **1/1 passed**.
- New cockpit browser spec: **4/4 passed**.
- Full browser suite: **5/5 passed**, including the pre-existing Phase A active-growth journey.
- Lead radar and import-dialog component tests after the production fixes: **29/29 passed**.

## Initial verification

All commands were run from the linked Task 11 worktree with the bundled Codex Node runtime.

| Gate | Result |
| --- | --- |
| `pnpm test:e2e` | 5 passed, 0 failed |
| Vitest full frontend suite | 34 files, 307 passed, 0 failed |
| Vue TypeScript check | passed |
| ESLint | passed |
| Vite production build | passed; 150 modules transformed |
| E2E launcher unit tests | 5 passed, 0 failed |
| `git diff --check` | passed |

The E2E launcher created its isolated database/storage root, applied migrations, seeded Phase A data, ran the Django and Vite services, exercised the installed Chromium-compatible Edge browser, and cleaned the owned run root on exit.

## Boundary notes

- This task did not add or modify backend APIs, schemas, dependencies, the parent plan, or the SDD progress ledger.
- At this baseline, public ingestion persists `SourceEvidence` but does not automatically create a `LeadCandidate`; the browser acceptance therefore uses the production candidate API within the same authenticated organization to bridge the imported evidence into the opportunity view. Parent Task 12 can replace this bridge if its Phase B1 seed or orchestration adds that automatic linkage.
- The current Phase A E2E seed contains one organization. The former unknown `organization_id` rejection was only strict-field validation, so it is no longer presented as isolation evidence. The existing backend lead API and permission suite independently covers lower-level isolation and permissions; a real two-organization browser proof is deferred to parent Task 12.
- The current E2E fixture has no published `LEAD_ANALYZE` prompt or compatible lead-analysis provider. Task 11D does not expand `seed_phase_a`, modify the fake provider, or add a test-only mutation path. The full UI analyze-to-review journey therefore waits for parent Task 12's normal `seed_phase_b1` prerequisites.

## Files changed

- `frontend/e2e/ai-decision-cockpit.spec.ts`
- `frontend/e2e/phase-a-active-growth.spec.ts`
- `frontend/src/modules/leads/LeadRadarPage.vue`
- `.superpowers/sdd/2026-08-11-ai-decision-cockpit/task-11D-report.md`

## Fix Round 1 — acceptance boundaries and pending-page pagination

### Review disposition

- Fixed the real queue defect: pagination now remains reachable whenever the loaded page has candidates, including a page made entirely of `DISCOVERED` and `ANALYZING` candidates. Safe cursor validation and disabled-button behavior remain unchanged.
- Removed the browser assertion that treated an unknown `organization_id` field returning `400` as cross-organization isolation evidence. That response only proved strict request-field validation.
- Renamed and documented candidate creation as a pre-Task 12 fixture bridge. The import itself, completion state, opportunity opening, exact evidence text, and public-source link are still exercised through the real product UI.
- Preserved real permission behavior: read-only users cannot see import controls and receive `403` for a forged import request; reviewer users cannot see source-management controls.
- Did not modify the parent plan, progress ledger, `seed_phase_a`, backend APIs, schemas, or AI providers.

### Pagination RED/GREEN

The regression test models a current page containing only `DISCOVERED`/`ANALYZING` candidates plus a safe `next` cursor, then requires the user to navigate to the next page.

- **RED:** focused `LeadRadarPage` run reported **1 failed, 16 passed** because no accessible `下一页` button existed while `onlyAnalyzing` was true.
- **GREEN:** after removing the analysis-status condition from pagination visibility, the focused run reported **17 passed, 0 failed**, and the test followed `/api/v1/lead-candidates?cursor=pending-next` to the next page.

### Audit of the three earlier changes

1. Completed imports remain visible until the user closes the dialog. The Task 11D browser flow observes the exact terminal message before closing it.
2. Pending-only opportunity pages show both the analysis banner and their persisted opportunity cards, so evidence remains reachable. The component suite and browser fixture flow both exercise this behavior; Fix Round 1 additionally covers safe cursor navigation from such a page.
3. The existing Phase A content-brief locator remains scoped to `section[aria-labelledby="briefs-title"]`, avoiding the cockpit's similarly named promotion card. The full legacy Phase A browser journey still passes.

### Fix Round 1 verification

| Gate | Result |
| --- | --- |
| Focused `LeadRadarPage` test | 17 passed, 0 failed |
| Task 11D browser spec | 4 passed, 0 failed |
| Full browser suite | 5 passed, 0 failed |
| Full frontend Vitest suite | 34 files, 308 passed, 0 failed |
| Vue TypeScript check | passed |
| ESLint | passed |
| Vite production build | passed; 150 modules transformed |
| E2E launcher unit tests | 5 passed, 0 failed |
| Backend lead API/permission tests | 19 passed, 0 failed |

### Parent Task 12 acceptance requirement

Task 11D intentionally remains before the broader parent Task 12 gate. Final acceptance must use parent Task 12's normal `seed_phase_b1` setup to provide a published, schema-compatible lead-analysis prompt/provider and a second organization. The browser must then prove the real UI sequence `查看依据 → 重新分析 → 等待分析完成 → reviewer 登录 → 确认机会并填写原因 → 处理结果已保存`, plus own-list visibility, foreign detail `404`, and rejection of a real foreign evidence ID without content leakage. Until that parent fixture exists and this browser proof passes, Task 11D must not be described as full analyze/review or browser-level organization-isolation acceptance.

### Fix Round 1 files

- `frontend/src/modules/leads/LeadRadarPage.vue`
- `frontend/src/modules/leads/LeadRadarPage.test.ts`
- `frontend/e2e/ai-decision-cockpit.spec.ts`
- `.superpowers/sdd/2026-08-11-ai-decision-cockpit/task-11D-report.md`
