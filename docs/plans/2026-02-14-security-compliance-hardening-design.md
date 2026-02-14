# Security/Compliance Hardening Design (Prod-Strict Baseline)

Date: 2026-02-14

## Goal

Harden the MimirQ backend security posture with a "strict in production, compatible in dev/test" strategy:

- Prevent leaking internal multi-tenant context headers to third-party services.
- Strengthen production defaults and add fail-closed validation for dangerous configs.
- Improve auditability for sensitive administrative actions.
- Add regression tests so these guarantees do not drift.

## Scope (20 Tasks)

This design maps to `bd` epic `MimirQ-xj7` with 20 child tasks (`MimirQ-xj7.1` .. `MimirQ-xj7.20`).

Primary changes:

- Outbound HTTP header injection controls (internal vs external clients).
- Production hardening: allowed hosts, CORS validation, docs exposure, security headers, body-size limits.
- Settings API hardening: disable `.env` writes in production by default + audit log for changes.
- Tests and CI workflow alignment.

## Strategy: Strict In Production Only (Option A)

When `ENV=production|prod`:

- Dangerous defaults become opt-in and validated.
- Misconfiguration fails closed with clear error messages.

When not in production:

- Preserve current dev ergonomics (localhost CORS, docs enabled, etc.) unless explicitly configured otherwise.

## Threat Model / Risks Addressed

1. **Internal context header leakage to third parties**
   - Current global HTTP clients inject `X-Request-ID`, `X-Tenant-ID` (and custom tenant header), and `X-User-ID`.
   - When used against third-party endpoints (LLM providers, arbitrary URL ingest, crawlers, connectors), this can leak tenant IDs or other internal identifiers.

2. **Production misconfiguration**
   - CORS is currently permissive (`allow_credentials=True`, `allow_headers=["*"]`) and relies on deployer correctness.
   - No Host header protection exists (spoofing, cache poisoning edge cases).
   - Docs/openapi are exposed unless disabled.

3. **Administrative surface area**
   - The Settings API can mutate `.env` at runtime. Even if access-controlled, it is high impact and should be disabled by default in production.
   - Settings changes should be audited without persisting secret values.

## Design: Outbound HTTP Client Segmentation

### Key Idea

Provide two outbound HTTP client profiles via `app/core/http_client.py`:

- **Internal client (default)**: may inject internal context headers for service-to-service calls in a trusted environment.
- **External client**: does **not** inject tenant/user headers. Optionally inject request correlation ID only.

### Call Sites

Use the **external client** for:

- LLM provider calls (`app/rag/engine.py`).
- Arbitrary URL ingestion (`app/api/utils/url_ingest.py`).
- Web crawler (`app/services/web_crawler.py`).
- Connectors that call third-party systems (e.g. Confluence).

### Testing

Add unit tests that intercept outbound httpx requests and assert:

- `X-Tenant-ID`, custom tenant header, and `X-User-ID` are absent for external calls.
- Existing internal call behavior is unchanged (where relevant).

## Design: Production Hardening Defaults + Validation

### Allowed Hosts

- Add an `ALLOWED_HOSTS` setting (CSV) and enable `TrustedHostMiddleware` in production.
- In production: fail startup if allowed hosts are empty.

### CORS

- Add production validation and a config for `allow_credentials`.
- In production: disallow empty origins, localhost origins, and insecure wildcard combinations.

### Docs / OpenAPI

- Add configuration to disable `/docs`, `/redoc`, and `/openapi.json` in production by default.
- In dev: keep enabled.

### Security Headers

Extend existing middleware to support additional headers (configurable):

- Strict-Transport-Security (HSTS) (production-friendly; disabled by default unless enabled)
- Permissions-Policy
- Cross-Origin-Opener-Policy / Cross-Origin-Resource-Policy (optional)

### Request Body Size Limit

Add middleware that rejects requests with `Content-Length` above a configurable limit, returning HTTP 413.

## Design: Settings API Hardening + Audit

### Disable `.env` Writes In Production By Default

Add a setting (e.g. `SETTINGS_ENV_WRITE_ENABLED`):

- In production default: `false` unless explicitly enabled.
- In dev default: `true` (preserve current behavior).

### Audit Log Settings Changes

On settings updates (`PUT /api/v1/settings`):

- Record an audit log event (`action=settings.update`) with:
  - tenant_id, actor_id, request_id, ip/user-agent (best effort)
  - list of updated keys only (no values)
- Must remain fail-open (audit logging must not break the settings update).

## Non-Goals

- Implementing a full policy engine (ABAC/OPA) for endpoint authorization.
- A full CSP rollout (likely to break existing UI and requires coordinated frontend work).
- Replacing all `requests` usage in the codebase (we target high-risk paths first).
- Full WAF-level protections (belongs at ingress/proxy layer).

## Rollout / Backwards Compatibility

- All strictness gates on `ENV=production` so local/dev is not disrupted.
- Changes that affect outbound headers are safe-by-default and should not break functionality (headers removed should not be required by third-party services).

## Success Criteria

- No internal tenant/user context headers are sent to third-party services on any supported path.
- Production startup fails fast on insecure CORS/host/docs/settings-write configuration.
- Settings changes are audit logged without storing secrets.
- CI and unit tests prevent regressions.

