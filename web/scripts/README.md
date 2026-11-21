# Web-side Contract Scripts

This folder hosts frontend-facing API contract checks.

## Commands

Run from repo root:

```bash
make api-check
```

Run from `web/`:

```bash
pnpm run api-check
```

Both commands verify:

- Frontend calls must exist in backend routes.
- Browser-facing backend routes must have a corresponding entry in `web/lib/api/`.
