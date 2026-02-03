# UI + API Polish (20 Commits) Design Notes

Date: 2026-02-03

## Goal

Ship 20 small, reviewable commits that:

- tighten the frontend UI against the project's UI baselines (token-first, minimal motion, no layout animation)
- keep backend API integration healthy (OpenAPI typegen + route contract/coverage checks)
- keep `make enterprise-checks` green

## Constraints (Baseline UI)

- Prefer semantic tokens (`bg-*`, `text-*`, `border-*`) over hard-coded palettes.
- Avoid `transition-all` (especially where it can animate layout like `width`).
- Avoid animating layout properties (`width/height/top/left/...`); only animate `transform/opacity` when needed.
- Keep interaction feedback <= 200ms; respect `prefers-reduced-motion`.
- Avoid large `backdrop-filter`/blur surfaces, especially on high-frequency views.

## UI/UX Pro Max (Design System Output - Reference Only)

We generated a design-system recommendation via `ui-ux-pro-max` for an enterprise dashboard product.
We will **not** re-theme the app in this round; we will only apply high-signal, low-risk guidelines:

- keep an enterprise, conservative feel (reduce glow-heavy shadows)
- simplify transitions and remove layout animations
- keep typography readable (use existing `text-balance`/`text-pretty` utilities)

## Verification Gates

After the final commit:

```bash
make openapi-check
make enterprise-checks
```

During execution, each commit should keep TypeScript + lint + API contract checks in a safe state.

