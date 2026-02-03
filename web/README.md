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

