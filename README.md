# SinofGear Growth Engine

Independent Phase A workspace for the SinofGear growth engine.

## Local development

1. Copy `.env.example` to `.env` and replace development values as needed.
2. Start the local stack with `docker compose up --build`.

Only the frontend (`http://localhost:3000`) and API (`http://localhost:8000`) are exposed to the host. Database, Redis, and MinIO are available only to the Compose network.

Production secrets must differ from the development values in `.env.example`.

Open `http://localhost:3000` in a browser after the stack starts. The signed-in product opens in ordinary mode by default, with five work destinations: **今天、产品资料、推广、客户机会、效果**. If advanced navigation is already selected in that browser, use **返回普通功能** to return to the ordinary experience without signing out or changing organization.

This batch delivers the Growth Director cockpit, audited human decisions, the five-entry beginner navigation and the read-only AI Agent Center. It is an orchestration foundation: approvals are recorded but do not pretend to perform platform publishing or CRM handoff that has not yet been connected. See [the cockpit acceptance record](docs/acceptance/growth-director-cockpit-foundation.md) for exact verified and deferred scope.

## Phase A acceptance

The complete active-growth acceptance runs through the real browser UI against disposable local services:

```powershell
cd frontend
pnpm test:e2e
```

It creates a uniquely marked operating-system temporary directory, uses dynamic localhost ports, a temporary SQLite database and filesystem storage, fake AI, eager jobs, and mock platform connectors. It does not use normal development data, object storage, Docker services, provider accounts, or real secrets. The launcher removes only the child processes and marked temporary directory that it created.

See [the Phase A acceptance guide](docs/phase-a-acceptance.md) for prerequisites, test-only credentials, expected statuses, forced publish-failure recovery, evidence, and cleanup boundaries.

See [the AI-native UI acceptance guide](docs/acceptance/ai-native-ui-redesign.md) for the ordinary-mode browser journeys, viewport coverage, deterministic provider boundaries, CRM export behavior, verification commands, and current limitations.

## DeepSeek on Windows

An administrator connects DeepSeek from **Advanced Settings > AI model**. The API
key is stored for the signed-in Windows user in Windows Credential Manager; it is
not stored in Git, `.env`, a backup/zip, the database, browser storage, logs, or
the installer. A different Windows user or computer must enter the key again.

See [DeepSeek Windows credential operations](docs/operations/deepseek-windows-credentials.md)
for connection testing, rotation, deletion, reinstall/uninstall, backup, and
incident response. The paid command-line smoke test is opt-in and must never be
run by automation.
