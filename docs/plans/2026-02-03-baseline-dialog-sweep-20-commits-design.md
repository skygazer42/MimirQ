# Baseline Dialog Sweep (20 Commits) Design Notes

Date: 2026-02-03

## Goal

Ship 20 small, reviewable commits that:

- remove remaining native browser dialogs (`confirm()` / `prompt()`) from the Next.js UI
- enforce Baseline UI destructive confirmation via `AlertDialog`
- keep FE/BE integration checks green (`make api-check`, `make openapi-check`, `make enterprise-checks`)

## Constraints (Baseline UI)

- Destructive / irreversible actions must use `AlertDialog` (token-first, no heavy blur, <=200ms interactions).
- Prefer reusable primitives (`web/components/ui/*`) over ad-hoc hand-rolled a11y.
- Avoid adding layout animations; only animate `transform/opacity` when needed.

## Enforcement

- Add a lightweight UI guard script under `web/scripts/` to fail CI if `confirm()` / `prompt()` reappear.

## Verification Gates

During execution, keep `cd web && pnpm run typecheck` green for UI changes.
After the final commit, run:

```bash
make enterprise-checks
make openapi-check
```

