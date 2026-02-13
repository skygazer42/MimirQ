# MimirQ Web (Next.js Frontend)

This folder contains the Next.js 14 (App Router) frontend.

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
- `NEXT_PUBLIC_OIDC_ISSUER` (e.g. `https://idp.example`)
- `NEXT_PUBLIC_OIDC_CLIENT_ID`
- `NEXT_PUBLIC_OIDC_SCOPES` (default: `openid profile email`)
- `NEXT_PUBLIC_OIDC_REDIRECT_URI` (optional; default: `<origin>/auth/oidc/callback`)
- `NEXT_PUBLIC_OIDC_AUTH_PARAMS` (optional; querystring like `audience=...&prompt=login`)

Backend must be configured to accept IdP JWTs (example):

- `AUTH_MODE=jwt`
- `ALGORITHM=RS256`
- `JWT_ISSUER=<same as NEXT_PUBLIC_OIDC_ISSUER>`
- `JWT_JWKS_DISCOVERY_ENABLED=true` (or set `JWT_JWKS_URLS` directly)

Notes:

- Token exchange happens in the browser; your IdP must allow CORS on the OIDC token endpoint for your frontend origin.

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
