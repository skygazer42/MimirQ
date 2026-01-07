---
name: mimirq-maintainer
description: "Maintain and optimize the MimirQ repo (FastAPI backend + Next.js web): update settings/.env docs, add or modify API routes, regenerate OpenAPI TypeScript types, manage Alembic migrations, and run standard checks (tests, lint, audits). Use when working inside this repository on backend/frontend changes, CI, dependency updates, or observability hardening (logging/Prometheus/Sentry/OpenTelemetry)."
---

# MimirQ Maintainer

## Quick Start

- Run backend tests: `make test`
- Run full verify (ruff + API contract + web lint/typecheck): `make verify`
- Run Python audit (minimal deps): `make audit-py`
- Regenerate OpenAPI TS types (after API/schema changes): `make openapi-check`
- Create/upgrade DB migrations: `make db-revision m="..."` then `make db-upgrade`

## Repo Map

- **Backend**
  - App entry: `app/main.py`
  - Settings: `app/core/config.py` and `.env.example`
  - API routes: `app/api/v1/`
  - Middleware: `app/api/middleware/`
  - DB + migrations: `app/core/database.py`, `alembic/`, `alembic.ini`
- **Web**
  - Next.js app: `web/app/`
  - API client: `web/lib/api-client.ts`
  - Types: `web/types/`

## Standard Workflows

### Change Settings / Env Vars

1. Add setting with safe default in `app/core/config.py`
2. Document it in `.env.example`
3. Add/adjust unit tests under `tests/` when behavior changes
4. Run `make test` and `make verify`

### Change Backend API

1. Update route/schema under `app/api/v1/`
2. Run `make openapi-check` (or `make openapi-export && make openapi-types`)
3. Update `web/lib/api-client.ts` and/or `web/types/` if needed
4. Run `make verify`

### Update Dependencies

1. Update `requirements.txt`
2. Run `make audit-py` (and `make audit` when touching web deps too)
3. Run `make test` and `make verify`

## Observability Toggles

- Logging: `LOG_LEVEL`, `LOG_FORMAT=json`
- Prometheus: `PROMETHEUS_ENABLED=true` exposes `/metrics`
- Sentry: set `SENTRY_DSN`
- OpenTelemetry: set `OTEL_ENABLED=true` (configure OTLP via `OTEL_EXPORTER_OTLP_*` or the settings)

## Resources

- `references/repo.md`: key commands and paths
- `scripts/run_verify.sh`: one-shot verify runner
- `scripts/run_verify.ps1`: Windows verify runner
