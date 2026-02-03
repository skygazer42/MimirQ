# UI + API Polish (Round 3) Design Notes

Date: 2026-02-03

## Goal

Ship another 20 small commits focusing on:

- UI baseline compliance (no `transition-all`, no layout animations, no hover “lift”)
- Accessibility polish (icon-only buttons have `aria-label`; data uses `tabular-nums`)
- Frontend/backend integration DX (quick ping tools + diagnostics shortcuts)

## Scope

### UI Baseline (Baseline UI skill)

- Replace `transition-all` with targeted transitions: `transition-colors`, `transition-shadow`, `transition-opacity`, `transition-transform`.
- Avoid animating layout properties (e.g. `margin`, `width`, `max-width`).
- Remove hover translate “lift” where present.
- Prefer `size-*` for square icons/containers when touching code.
- Use `text-balance` for headings and `text-pretty` for body text where missing.
- Use `tabular-nums` for numeric stats.

### Backend Integration

- Extend local ping tooling so FE/BE connectivity checks include `/api/v1/meta`.
- Add quick links on the diagnostics page to backend `/docs` and `/openapi.json`.
- Add a Makefile helper target to run the web ping script (`pnpm run api-ping`) from repo root.

## Constraints

- Keep behavior stable (no backend changes; minimize UX changes to style/interaction hygiene).
- Respect `prefers-reduced-motion` (keep `motion-reduce:*` where relevant).
- Keep verification green: `make enterprise-checks`.

## Verification Gates (end of round)

```bash
make openapi-check
make enterprise-checks
```

