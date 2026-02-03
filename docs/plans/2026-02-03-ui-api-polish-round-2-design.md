# UI + API Polish (Round 2) Design Notes

Date: 2026-02-03

## Goal

Execute another 20 small commits to keep improving:

- UI baseline compliance (token-first, less blur/glow, minimal motion, avoid layout animation)
- Frontend/backend integration quality (contract checks + quick reachability scripts)

## Scope

This round prioritizes:

1. Removing remaining `transition-all` hotspots across high-traffic views.
2. Removing hover “lift” transforms and long durations where not explicitly needed.
3. Switching remaining progress bars from `width` animation to `transform: scaleX(...)`.
4. Reducing heavy `backdrop-blur-*` usage on toolbars (keep surfaces crisp and fast).
5. Small improvements to backend integration tooling (`api-ping`) without changing backend behavior.

## Constraints (Baseline UI)

- Avoid layout property animation (`width/height/margin/...`).
- Use targeted transitions (`transition-colors`, `transition-shadow`, `transition-opacity`, `transition-transform`).
- Interaction feedback <= 200ms.
- Respect `prefers-reduced-motion`.
- Prefer semantic tokens: `primary/success/warning/info`, `bg-card/bg-background`, `text-*-foreground`, `border-border`.

## Verification Gates

At the end of the round:

```bash
make openapi-check
make enterprise-checks
```

