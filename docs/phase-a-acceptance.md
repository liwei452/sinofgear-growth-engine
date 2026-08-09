# Phase A active-growth acceptance

This acceptance run proves the Phase A growth loop in a disposable, local-only environment. It exercises the real browser UI and API while using fake AI, eager background jobs, mock publishing connectors, a temporary SQLite database, and temporary filesystem object storage.

## Run it

Prerequisites:

- the backend virtual environment exists at `backend/.venv` and its dependencies are installed;
- frontend dependencies are installed with `pnpm install`;
- Microsoft Edge or Google Chrome is installed, or `PLAYWRIGHT_EXECUTABLE_PATH` points to a Chromium-compatible browser.

From `frontend` run:

```powershell
pnpm test:e2e
```

The launcher reserves dynamic localhost ports, creates a marked operating-system temporary directory, migrates and seeds its own database, starts only its child services, runs Playwright, and removes those children and the marked directory on exit.

## Test-only identities

All four accounts use the password `PhaseA-E2E-Only!` and `.invalid` email addresses:

| Role | Username |
| --- | --- |
| Administrator | `phasea_e2e_admin` |
| Operator | `phasea_e2e_operator` |
| Reviewer | `phasea_e2e_reviewer` |
| Viewer | `phasea_e2e_viewer` |

These credentials are fixtures, not development or production credentials. The seed command refuses to run unless the isolated E2E settings explicitly enable it.

## Expected evidence

The browser test must complete this closed loop:

1. Log in and verify the approved Helical Gear, DIN, Grinding, and Packaging Machinery knowledge.
2. Verify the Custom Helical Gear product and its immutable original factory video.
3. Open the READY Germany packaging-machinery brief and generate master content.
4. Inspect the AI audit, including the prompt version and immutable ontology snapshot, then approve the master content.
5. Generate and approve Facebook, Instagram, LinkedIn, TikTok, and YouTube variants.
6. Schedule and run a Facebook publish task to `SUCCEEDED`.
7. Run the seeded TikTok task, observe its safe `PROVIDER_ERROR` failure, retry it, and observe `SUCCEEDED`.
8. Create a campaign/platform tracking link and short link, visit the short URL, and verify one attributed click in analytics.

A passing Playwright result is the sign-off artifact. The browser assertions cover the visible statuses and the failure-recovery path; backend tests separately prove seed idempotence, stable identifiers, mutable-drift repair, non-seed isolation, permissions, and the absence of real secret material.

## Isolation and cleanup boundary

The acceptance launcher never reads or writes the normal development database, object storage, Docker services, or fixed service ports. Cleanup is fail-closed: it is permitted only for an absolute child of the operating-system temporary directory whose basename starts with `sinofgear-phase-a-e2e-`. It terminates only processes it started and removes only that marked run directory.

The seed is deterministic and transactional. Running it twice leaves stable fixture identifiers and immutable versions unchanged; mutable fixture drift is repaired. It uses only synthetic bytes, fake prompts, mock accounts, and `e2e-test://` credential references. It contains no real provider token or secret.

## Troubleshooting

- If the browser is not found, install Edge/Chrome or set `PLAYWRIGHT_EXECUTABLE_PATH`.
- If the backend cannot start, recreate `backend/.venv` and install backend dependencies.
- If frontend packages are missing, run `pnpm install` in `frontend`.
- Keep the complete launcher output when reporting a failure; it identifies migration, seed, service-start, browser, and cleanup failures separately.
