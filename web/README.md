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
- `pnpm dev` now binds `127.0.0.1` by default and will automatically fall forward to the next free port when `3000` is busy.
- `pnpm dev -- --port 3001` or `PORT=3001 pnpm dev` lets you pick another port explicitly.
- `pnpm dev:public` keeps the old `0.0.0.0` behavior for LAN/device testing.
- `pnpm dev` uses webpack (explicit) to support custom `next.config.mjs#webpack` tweaks.
- `pnpm dev:turbo` uses Turbopack, and `pnpm dev:turbo:public` combines Turbopack with public binding.
- `pnpm start` follows the same localhost-first behavior, and `pnpm start:public` exposes it on `0.0.0.0`.

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

## SAML SSO (Optional)

MimirQ supports IdP-initiated SAML 2.0 behind a guarded Next.js ACS route plus backend assertion exchange.

- Enable switch: `SAML_ENABLED=true` (default: off)
- SP metadata: `GET /api/saml/metadata`
- ACS endpoint: `POST /api/saml/acs`
- Frontend callback: `GET /auth/saml/callback`
- Backend exchange: `POST /api/v1/auth/saml/exchange`

Required backend/server env vars:

- `SAML_PROVIDERS_JSON` (JSON array)
  - shape: `{ id, issuer, audience, acs_url, idp_cert_pem, email_attribute?, groups_attribute? }`
- `SAML_ALLOWED_CLOCK_SKEW_SEC` (default: `60`)
- `SAML_REPLAY_TTL_SEC` (default: `300`)
- `SAML_REPLAY_REDIS_ENABLED` (optional; default: `false`)

Optional SP metadata env vars (enterprise IdP compatibility):

- `SAML_SP_CERT_PEM` (advertise `<KeyDescriptor use="signing">` in SP metadata)
- `SAML_SP_PRIVATE_KEY_PEM` (required for signed metadata)
- `SAML_SP_METADATA_SIGNED=true` (sign SP metadata; default: `false`)

Behavior:

- The Next.js ACS route accepts the IdP POST and forwards the raw assertion to the backend exchange endpoint.
- The backend validates signature, issuer, audience, destination, recipient, time window, and replay state.
- On success, the backend maps `NameID`/email to an existing MimirQ user and issues a normal app JWT session.
- The frontend callback stores that session through the existing `setAuthSession(...)` path.

Implementation details: `docs/guides/saml_sso.md`.

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
