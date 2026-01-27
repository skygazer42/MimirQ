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

## Supported Versions

We provide security fixes for the latest version on the `main` branch.

## Disclosure

We aim to acknowledge reports within 72 hours and provide a remediation plan or fix as soon as practical.

## Automated Scanning

CI includes:
- Secret scanning (TruffleHog)
- Dependency audits (`pip-audit`, `pnpm audit`)
