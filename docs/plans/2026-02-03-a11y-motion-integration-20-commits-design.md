# A11y + Motion + Integration DX (20 Commits) Design Notes

Date: 2026-02-03

## Goal

Ship 20 small, reviewable commits that:

- fix high-impact accessibility issues (WCAG 2.2 A/AA) on core pages
- reduce motion/perf risks (blur/backdrop-filter, long interaction durations, unnecessary transitions)
- improve frontend-backend integration DX (errors show `request_id`, diagnostics stay useful)

## Constraints (Baseline UI)

- Icon-only buttons must have accessible names (`aria-label`/`title`) or use `IconButton`.
- Prefer native semantics (`button`, `a`, `label`) over `role="button"` where feasible.
- No layout animation; only animate `transform/opacity` when needed; interaction feedback <= 200ms.
- Avoid large `blur()` / `backdrop-filter` surfaces on high-frequency views (chat, parsing, history, graph).
- Keep token-first styling (bg/text/border tokens), avoid hard-coded palette sprawl.

## Approach

1. **A11y sweep**: convert safe `role="button"` list items to real `<button type="button">`, add missing labels for form controls, and keep focus visible (`focus-ring`).
2. **Motion/perf sweep**: reduce/disable blur-heavy surfaces and long transitions (e.g. `.glass` blur, page headers/panels that use `backdrop-blur-*`).
3. **Integration DX**: standardize error toasts to use `formatApiError(...)` so `request_id` is preserved for backend log correlation.

## Verification Gates

During execution, keep TypeScript checks green for each UI change:

```bash
cd web && pnpm run typecheck
```

After the final commit:

```bash
make enterprise-checks
make openapi-check
```

