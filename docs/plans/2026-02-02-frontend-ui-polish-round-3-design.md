# Frontend UI Polish (Round 3) Design

**Goal:** Ship a cohesive, calmer, faster UI pass focused on global consistency (A) and motion/performance cleanup (C) while staying inside `baseline-ui` constraints (token-first, no gradients/glows by default, minimal motion).

## Direction

**Aesthetic:** "Instrument panel" calm. Clean surfaces, strong hierarchy, restrained accents (primary + semantic status colors), predictable interactions, and fewer decorative effects.

## Core Principles

- **Token-first surfaces:** Prefer semantic tokens (`bg-card`, `text-muted-foreground`, `border-border`, `text-warning`, etc.). Avoid raw Tailwind palette utilities unless already tokenized.
- **One accent per view:** Keep attention on primary actions; use semantic colors only for status, not decoration.
- **Predictable motion:** Only animate compositor props (`transform`, `opacity`). Keep interaction feedback <= 200ms. Respect `prefers-reduced-motion`.
- **Optional eye-candy is opt-in:** Cursor/particles/tilt/magnetic effects must be gated (feature flag + pointer: fine + reduced-motion checks) and must not run by default.

## Global Consistency Targets

- Standardize transitions (avoid `transition-all`), spacing, and icon-only buttons (`aria-label` + shared `IconButton` where possible).
- Ensure destructive actions use an `AlertDialog` confirm (no silent deletes).
- Tighten empty/loading states: clear next action, token surfaces, no glow overlays.

## Performance Targets

- Reduce JS-driven animations on high-frequency surfaces (chat message list, document list cards).
- Remove paint-property animations (e.g., background-color animation loops) and replace with class toggles + small CSS transitions.
- Pause/disable looping visuals when hidden/off-screen (particles) and on non-fine pointers.

## Backend Integration & Verification

- Keep OpenAPI types in sync (`make openapi-check`) and ensure route coverage checks remain green (`make api-check` / `make enterprise-checks`).
- Improve error surfaces to retain request identifiers where helpful for debugging API issues.

