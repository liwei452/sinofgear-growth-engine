# SinofGear Growth Engine

Independent Phase A workspace for the SinofGear growth engine.

## Local development

1. Copy `.env.example` to `.env` and replace development values as needed.
2. Start the local stack with `docker compose up --build`.

Only the frontend (`http://localhost:3000`) and API (`http://localhost:8000`) are exposed to the host. Database, Redis, and MinIO are available only to the Compose network.

Production secrets must differ from the development values in `.env.example`.

## Phase A acceptance

The complete active-growth acceptance runs through the real browser UI against disposable local services:

```powershell
cd frontend
pnpm test:e2e
```

It creates a uniquely marked operating-system temporary directory, uses dynamic localhost ports, a temporary SQLite database and filesystem storage, fake AI, eager jobs, and mock platform connectors. It does not use normal development data, object storage, Docker services, provider accounts, or real secrets. The launcher removes only the child processes and marked temporary directory that it created.

See [the Phase A acceptance guide](docs/phase-a-acceptance.md) for prerequisites, test-only credentials, expected statuses, forced publish-failure recovery, evidence, and cleanup boundaries.
