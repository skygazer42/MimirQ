# Frontend UI Polish (Round 5) Design Notes

**Theme:** A (global consistency / baseline UI) + C (motion & performance).

This round focuses on tightening several high-frequency UI surfaces to better match the project's `baseline-ui` rules:

- token-first surfaces (prefer `bg-*`, `text-*`, `border-*` semantic tokens)
- remove glow / neon shadows and avoid multi-accent palettes inside a single control surface
- avoid `transition-all` (especially when it can animate layout like `width`)
- motion stays compositor-only (`transform`, `opacity`), short (<=200ms) and respects `prefers-reduced-motion`
- looping effects should pause when inactive / hidden

## Target surfaces

### 1) Governance + Ingestion controls (A)

The governance panel and related dropdowns still use a heavy “sky/purple/fuchsia” palette and some `transition-all` hot spots.
We will simplify them to semantic tokens and reduce excessive hover motion.

### 2) Chat message surfaces (A+C)

Chat message bubbles still include glow-heavy shadows, `backdrop-blur`, and broad transitions.
We will calm these surfaces and remove always-on looping indicators where possible.

### 3) File queue progress (C)

Small progress bars currently animate `width` via `transition-all`.
We will switch these to `transform: scaleX(...)` for compositor-only animation.

### 4) Panel layout transitions (C)

The document viewer right panel uses `transition-all` while toggling width.
We will remove layout animation to avoid jank and align with the baseline.

## Non-goals

- No backend API changes this round.
- No new decorative animation; only removing / downgrading motion for performance and baseline compliance.

