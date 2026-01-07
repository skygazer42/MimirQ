# MimirQ Repo Reference

## Common Commands

- Unit tests: `make test`
- Full verify: `make verify`
- Python audit (minimal): `make audit-py`
- OpenAPI → TS types: `make openapi-check`
- Alembic revision: `make db-revision m="add_some_table"`
- Alembic upgrade: `make db-upgrade`

## Key Paths

- Backend app entry: `app/main.py`
- Backend settings: `app/core/config.py`, `.env.example`
- API routes: `app/api/v1/`
- Middleware: `app/api/middleware/`
- DB migrations: `alembic/`, `alembic.ini`
- Web app: `web/`

## Observability Flags

- Logging: `LOG_LEVEL`, `LOG_FORMAT=json`
- Prometheus: `PROMETHEUS_ENABLED=true` exposes `/metrics`
- Sentry: set `SENTRY_DSN`
- OpenTelemetry: set `OTEL_ENABLED=true` and configure OTLP exporter via `OTEL_EXPORTER_OTLP_*`

