# MimirQ Web (Next.js Frontend)

This folder contains the Next.js 16 (App Router) frontend.

## Prerequisites

- Node.js 20+
- pnpm (see `package.json#packageManager`)

## Local Development

From repo root:

```bash
cd web
pnpm install
pnpm dev
```

Notes:
- `pnpm dev` uses webpack (explicit) to support custom `next.config.mjs#webpack` tweaks.
- `pnpm dev:turbo` uses Turbopack.

Open:

- Frontend: `http://localhost:3000`
- Backend docs (when backend is running): `http://localhost:8000/docs`

## Environment Variables

The frontend resolves the backend base URL like this:

- Browser/API calls use `NEXT_PUBLIC_API_URL` (default: `http://localhost:8000`)
- Server-side (SSR) can optionally use `API_INTERNAL_URL` (useful in Docker for container DNS)

Common variables:

- `NEXT_PUBLIC_API_URL` (default: `http://localhost:8000`)
- `API_INTERNAL_URL` (optional, SSR-only)
- `NEXT_PUBLIC_API_TIMEOUT_MS` (default: 60000)
- `NEXT_PUBLIC_API_LONG_TIMEOUT_MS` (default: 600000)

See implementation: `web/lib/env.ts`.

## OIDC SSO (Optional)

Frontend supports OIDC SSO via Authorization Code + PKCE.

Frontend env vars (client-side):

- `NEXT_PUBLIC_OIDC_ENABLED` (optional; set false to force-disable)

Single-provider (backward compatible):
- `NEXT_PUBLIC_OIDC_ISSUER` (e.g. `https://idp.example`)
- `NEXT_PUBLIC_OIDC_CLIENT_ID`
- `NEXT_PUBLIC_OIDC_SCOPES` (default: `openid profile email`)
- `NEXT_PUBLIC_OIDC_REDIRECT_URI` (optional; default: `<origin>/auth/oidc/callback`)
- `NEXT_PUBLIC_OIDC_AUTH_PARAMS` (optional; querystring like `audience=...&prompt=login`)

Multi-provider:
- `NEXT_PUBLIC_OIDC_PROVIDERS_JSON` (JSON array; preferred)
  - shape: `{ id, name?, issuer, client_id, scopes?, auth_params? }`
  - example:
    ```json
    [
      { "id": "okta", "name": "Okta", "issuer": "https://idp.example/okta", "client_id": "web-okta" },
      { "id": "google", "name": "Google", "issuer": "https://accounts.google.com", "client_id": "web-google" }
    ]
    ```
  - when multiple providers are present, the login page shows a provider picker.

Backend must be configured to accept IdP JWTs (example):

- `AUTH_MODE=jwt`
- `ALGORITHM=RS256`
- `JWT_ISSUER=<same as provider issuer>`
- `JWT_JWKS_DISCOVERY_ENABLED=true` (or set `JWT_JWKS_URLS` directly)

Notes:

- Browser-first: token exchange is attempted in the browser (PKCE).
- Fallback: if the IdP token endpoint blocks CORS and/or requires a `client_secret`, frontend falls back to a Next.js route handler that performs the code exchange server-side.

Optional server-side env vars (Next.js server only):

Single-provider (backward compatible):
- `OIDC_CLIENT_SECRET` (confidential clients)
- `OIDC_CLIENT_AUTH_METHOD` (`basic` default | `post`)
- `OIDC_SERVER_EXCHANGE_ENABLED` (optional; set false to force-disable server exchange)

Multi-provider:
- `OIDC_PROVIDERS_JSON` (JSON array)
  - shape: `{ id, name?, issuer, client_id, client_secret?, client_auth_method? }`
  - note: `client_secret` is optional; when missing, the route handler still works for public clients (but refresh via httpOnly cookie may be unavailable).

Implementation:

- Code exchange: `POST /api/oidc/exchange` (sets refresh token in an httpOnly cookie when provided)
- Refresh: `POST /api/oidc/refresh` (uses refresh token cookie; returns a new access token)

## Backend Integration / Debugging

- Diagnostics page: `/diagnostics` (shows backend health/ready/meta + frontend API config)
- API contract checks (static): verifies web calls match backend routes

```bash
cd web
pnpm run api-check
```

## UI Standards

We enforce a token-first Tailwind UI baseline.

```bash
cd web
pnpm run ui-check
```

This blocks a small set of hard-coded utility colors (e.g. `bg-white`, `text-cyan-*`) so the UI stays consistent with the design token system.

## One-Command Verification

```bash
cd web
pnpm run verify
```

Runs: lint + ui-check + typecheck + tests + api-check.
