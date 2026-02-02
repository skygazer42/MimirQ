# Frontend UI Polish (Round 4) Design Notes

**Theme:** A (global consistency / baseline UI) + C (motion & performance).

This round continues tightening UI surfaces to match the project's `baseline-ui` constraints:

- token-first surfaces (prefer `bg-*`, `text-*`, `border-*` tokens over palette/hex)
- no gradients/glow-by-default; remove decorative "paper/texture" overlays
- motion is minimal, compositor-only (transform/opacity), <= 200ms for interaction feedback
- pause looping animation when hidden/off-screen; respect `prefers-reduced-motion`
- destructive actions already use `AlertDialog` (keep that pattern)

## What we will target

### 1) Token consistency + remove "AI aesthetic"

Two surfaces still use hard-coded hex colors + heavy “paper texture” overlays:

- `web/components/ingestion/ingestion-detail-dialog.tsx`
- `web/app/knowledge/feedback/page.tsx` (detail dialog)

We will simplify these to standard `DialogContent` styling (token background/border/shadow) and remove the texture overlay.

### 2) Motion + performance hotspots

`web/components/chat/voice-mode-overlay.tsx` currently repaints a full-screen canvas continuously and also resizes the canvas *every frame*.
That is a worst-case pattern for CPU/GPU and battery.

We will:

- resize only on open + on window resize (with DPR support)
- animate only when listening (otherwise render a single static frame)
- pause when tab is hidden; respect `prefers-reduced-motion`

### 3) Transition hygiene

We will remove a few high-impact `transition-all` usages on frequently-used primitives/surfaces and replace them with narrower transitions + `duration-200`.

## Non-goals

- No backend API changes in this round.
- No new animation effects; only remove or downgrade existing ones for performance and baseline compliance.

