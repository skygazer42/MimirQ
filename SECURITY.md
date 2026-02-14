# Security Policy

## Reporting a Vulnerability

Please do **not** open a public GitHub issue for security vulnerabilities.

Instead, report privately via:
- Email: `207829897@qq.com` (project maintainer)

Include:
- A clear description of the issue and impact
- Steps to reproduce (proof-of-concept if possible)
- Affected version/commit and environment details

## Security Notes (for Deployments)

This project includes several features that may interact with external systems. Please review these before running in production:

- **Secrets**: do not commit real secrets. Use `.env.example` templates and set `SECRET_KEY` (>= 32 chars) and other credentials via your deployment secret manager.
- **Default credentials**: the backend performs validation and/or warnings for default MinIO credentials and default `SECRET_KEY`. Do not use defaults in production.
- **URL ingestion / connectors (SSRF risk)**: server-side URL fetch is gated by `URL_INGEST_ENABLED` and includes protections (timeouts, size limits, private IP blocking by default). Keep the feature disabled unless you need it.
- **Authentication**: `AUTH_MODE=header` is intended for local/dev. Use `AUTH_MODE=jwt` in production.
- **Network exposure**: the default `docker-compose.yml` does not expose database/vector/object-store ports; avoid exposing infra ports publicly.

## Production Checklist (Recommended)

This checklist summarizes the "prod-strict baseline" defaults and hardening settings. Most of these are enforced only when `ENV=production`.

- Set `ENV=production`.
- Use `AUTH_MODE=jwt` (header mode is unsafe and must not be used in production).
- Set `SECRET_KEY` (minimum 32 chars; do not use default/example values).
- Configure allowed hosts: `TRUSTED_HOSTS_ENABLED=true` by default; in production, set `ALLOWED_HOSTS` to a comma-separated list (do not use `*`).
- Configure CORS: in production, `CORS_ORIGINS` is required and must be a comma-separated list of `http(s)` origins (no `*`, no `null`, no localhost); `CORS_ALLOW_CREDENTIALS` defaults to `false` unless explicitly enabled.
- Reduce public API surface: `API_DOCS_ENABLED` and `API_OPENAPI_ENABLED` default to `false` in production unless explicitly enabled.
- Disable settings `.env` mutation (recommended): `SETTINGS_ENV_WRITE_ENABLED` defaults to `false` in production; keep it disabled unless you explicitly need runtime configuration writes via the Settings API.
- Set request size guardrails: `REQUEST_MAX_BODY_BYTES` limits requests with `Content-Length` (default: 60000000). Tune for your workload.
- Review any outbound fetch features (SSRF/egress risk): keep `URL_INGEST_ENABLED=false` unless required; if enabled, configure allowlists and keep private IP access disabled unless you have a controlled network environment.
- Outbound HTTP safety: outbound requests use a dedicated HTTP client profile and should not forward inbound authentication headers by default (defense-in-depth against header leakage).
- Prefer keeping production docs/schema off: only enable `API_DOCS_ENABLED`/`API_OPENAPI_ENABLED` temporarily for debugging.

## Supported Versions

We provide security fixes for the latest version on the `main` branch.

## Disclosure

We aim to acknowledge reports within 72 hours and provide a remediation plan or fix as soon as practical.

## Automated Scanning

CI includes:
- Secret scanning (TruffleHog)
- Dependency audits (`pip-audit`, `pnpm audit`)
