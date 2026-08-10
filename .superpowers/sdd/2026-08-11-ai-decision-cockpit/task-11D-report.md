# Task 11D Report — Cockpit Browser Acceptance

## Status

Complete. The browser acceptance suite now covers the ordinary five-entry cockpit, the beginner promotion flow, public-signal import through evidence-backed opportunity review, mobile drawer behavior, advanced-mode persistence and recovery, and role/organization boundary checks.

## Scope delivered

- Added `frontend/e2e/ai-decision-cockpit.spec.ts` with four real-browser journeys:
  - ordinary mode exposes exactly Today, Promotion, Customer Opportunities, Results, and Company Profile;
  - an operator completes the real beginner promotion wizard and receives `201` responses from both campaign and content-brief creation;
  - an operator imports a public signal through the real ingestion endpoint, waits for successful completion, verifies the persisted source evidence, attaches it to a candidate through the production candidate API, and reads the exact source text and URL in the opportunity dialog;
  - a 390 x 844 viewport verifies drawer focus entry, focus wrapping, Escape close, focus restoration, and five ordinary entries;
  - read-only and reviewer sessions do not expose import controls, a forged read-only import receives `403`, advanced links survive navigation and reload, and returning to ordinary mode survives reload.
- Hardened organization scoping assertions in the browser flow: clients cannot submit an `organization_id` override when creating a candidate (`400`), the rejection does not echo persisted evidence text, and the accepted candidate is scoped from the authenticated session.
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

## Final verification

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
- The current Phase A E2E seed contains one organization. Browser coverage proves that the organization scope cannot be client-overridden and that mutation permissions are enforced server-side; exhaustive two-organization non-leakage remains covered by lower-level backend tests rather than by inventing a second browser fixture in Task 11D.

## Files changed

- `frontend/e2e/ai-decision-cockpit.spec.ts`
- `frontend/e2e/phase-a-active-growth.spec.ts`
- `frontend/src/modules/leads/LeadRadarPage.vue`
- `.superpowers/sdd/2026-08-11-ai-decision-cockpit/task-11D-report.md`
