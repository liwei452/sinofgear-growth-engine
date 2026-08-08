# SinofGear Growth Engine

Independent Phase A workspace for the SinofGear growth engine.

## Local development

1. Copy `.env.example` to `.env` and replace development values as needed.
2. Start the local stack with `docker compose up --build`.

Only the frontend (`http://localhost:3000`) and API (`http://localhost:8000`) are exposed to the host. Database, Redis, and MinIO are available only to the Compose network.

Production secrets must differ from the development values in `.env.example`.
