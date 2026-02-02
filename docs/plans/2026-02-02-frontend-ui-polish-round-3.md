# Frontend UI Polish (Round 3) Implementation Plan

> **For Codex/Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Execute 20 small, reviewable tasks (1 task = 1 commit) to improve global UI consistency (A) and reduce motion/performance overhead (C), while aligning with `baseline-ui` constraints (token-first, no gradients/glows by default, minimal motion, fixed z-index scale).

**Architecture:** Next.js App Router UI (Tailwind + Radix primitives). This round focuses on removing JS-driven decorative motion from high-frequency surfaces (chat list, sidebar list), tightening transitions, and standardizing primitives (buttons, dialogs, empty states) without changing backend APIs.

**Tech Stack:** Next.js 14, Tailwind CSS, Radix UI, TanStack Query, Sonner, Vitest, FastAPI (OpenAPI export for types).

---

## Task 1: Add design doc for round 3

**Files:**
- Create: `docs/plans/2026-02-02-frontend-ui-polish-round-3-design.md`

**Steps:**
1. Add the design doc describing A+C direction and constraints.
2. Commit.

**Commit:**
```bash
git add docs/plans/2026-02-02-frontend-ui-polish-round-3-design.md
git commit -m "docs(plans): add frontend UI polish round 3 design"
```

---

## Task 2: Add this plan document

**Files:**
- Create: `docs/plans/2026-02-02-frontend-ui-polish-round-3.md`

**Steps:**
1. Add this plan file.
2. Commit.

**Commit:**
```bash
git add docs/plans/2026-02-02-frontend-ui-polish-round-3.md
git commit -m "docs(plans): add frontend UI polish round 3 plan"
```

---

## Task 3: Button: remove `transition-all` + reduce motion affordances

**Files:**
- Modify: `web/components/ui/button.tsx`

**Steps:**
1. Replace `transition-all` with `transition` (avoid layout-property animation).
2. Remove hover translate effects; keep interaction feedback subtle and <= 200ms.
3. Verify web lint + typecheck.
4. Commit.

**Verify:**
```bash
cd web && pnpm run lint && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/ui/button.tsx
git commit -m "style(ui): tighten Button transitions and reduce motion"
```

---

## Task 4: Tailwind config: remove unused gradient helpers

**Files:**
- Modify: `web/tailwind.config.ts`

**Steps:**
1. Remove `backgroundImage.gradient-radial` (unused; baseline is gradient-free by default).
2. Verify typecheck.
3. Commit.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/tailwind.config.ts
git commit -m "chore(ui): remove unused Tailwind gradient helper"
```

---

## Task 5: TiltCard: remove sheen gradient + fix `will-change` baseline violation

**Files:**
- Modify: `web/components/ui/tilt-card.tsx`

**Steps:**
1. Remove sheen overlay (gradient background + long transitions).
2. Only animate transform/opacity; avoid `transition-all` and remove always-on `will-change`.
3. Add a `(pointer: fine)` guard (like FluidCursor) so it never runs on touch pointers.
4. Verify lint + typecheck.
5. Commit.

**Verify:**
```bash
cd web && pnpm run lint && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/ui/tilt-card.tsx
git commit -m "perf(ui): simplify TiltCard and remove paint-heavy sheen"
```

---

## Task 6: Magnetic: gate to fine pointers + reduce per-event work

**Files:**
- Modify: `web/components/ui/magnetic.tsx`

**Steps:**
1. Add `(pointer: fine)` guard.
2. Keep transform-only movement; ensure reduced-motion returns passthrough.
3. Verify typecheck.
4. Commit.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/ui/magnetic.tsx
git commit -m "perf(ui): gate Magnetic effect to fine pointers"
```

---

## Task 7: Chat list: replace `ScrollReveal` (Framer) with CSS animate-in

**Files:**
- Modify: `web/components/chat-area.tsx`

**Steps:**
1. Replace message wrapper with `tailwindcss-animate` classes (compositor-only).
2. Remove `ScrollReveal` import/usage.
3. Verify web lint + typecheck.
4. Commit.

**Verify:**
```bash
cd web && pnpm run lint && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/chat-area.tsx
git commit -m "perf(chat): replace ScrollReveal with CSS-only message entrance"
```

---

## Task 8: Remove unused `ScrollReveal` component

**Files:**
- Delete: `web/components/ui/scroll-reveal.tsx`

**Steps:**
1. Delete the component after all usages are removed.
2. Verify typecheck.
3. Commit.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git rm web/components/ui/scroll-reveal.tsx
git commit -m "chore(ui): remove unused ScrollReveal component"
```

---

## Task 9: PipelineVisualizer: remove paint-property animations + fix token color usage

**Files:**
- Modify: `web/components/ui/pipeline-visualizer.tsx`

**Steps:**
1. Remove Framer color animations (backgroundColor/borderColor) and use class toggles.
2. Keep progress animation transform-only (scaleX).
3. Ensure transition durations are <= 200ms where interactive.
4. Verify lint + typecheck.
5. Commit.

**Verify:**
```bash
cd web && pnpm run lint && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/ui/pipeline-visualizer.tsx
git commit -m "perf(ui): simplify PipelineVisualizer animations"
```

---

## Task 10: Sidebar: standardize floating icon-only actions with `IconButton`

**Files:**
- Modify: `web/components/sidebar.tsx`

**Steps:**
1. Replace bespoke icon buttons with `IconButton` (consistent sizing + aria-label).
2. Remove `backdrop-blur` on small floating buttons (perf).
3. Verify lint + typecheck.
4. Commit.

**Verify:**
```bash
cd web && pnpm run lint && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/sidebar.tsx
git commit -m "style(nav): standardize sidebar icon actions"
```

---

## Task 11: Add Radix AlertDialog primitive wrapper

**Files:**
- Modify: `web/package.json` (add `@radix-ui/react-alert-dialog`)
- Modify: `web/pnpm-lock.yaml`
- Create: `web/components/ui/alert-dialog.tsx`

**Steps:**
1. Add dependency and create a small `AlertDialog` wrapper matching existing `dialog.tsx` styling.
2. Ensure keyboard/focus behavior is provided by Radix (no custom hand-rolled focus management).
3. Verify web typecheck.
4. Commit.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/package.json web/pnpm-lock.yaml web/components/ui/alert-dialog.tsx
git commit -m "feat(ui): add AlertDialog primitive for destructive actions"
```

---

## Task 12: Sidebar: confirm document deletion via AlertDialog

**Files:**
- Modify: `web/components/sidebar.tsx`

**Steps:**
1. Wrap delete action in `AlertDialog` confirm (no silent deletes).
2. Ensure errors render next to the action (or toast + inline where appropriate).
3. Verify lint.
4. Commit.

**Verify:**
```bash
cd web && pnpm run lint
```

**Commit:**
```bash
git add web/components/sidebar.tsx
git commit -m "feat(nav): confirm document delete with AlertDialog"
```

---

## Task 13: Datasets: confirm destructive action (delete dataset) via AlertDialog

**Files:**
- Modify: `web/app/datasets/page.tsx` (or relevant dataset list component)

**Steps:**
1. Identify the dataset delete action and wrap it in `AlertDialog`.
2. Verify typecheck.
3. Commit.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/app/datasets/page.tsx
git commit -m "feat(datasets): confirm delete with AlertDialog"
```

---

## Task 14: EmptyState: remove glow overlay and encourage a single next action

**Files:**
- Modify: `web/components/ui/empty-state.tsx`

**Steps:**
1. Remove the blurred glow layer behind the icon.
2. Keep a calm token-driven layout; preserve `children` slot but make primary action visually dominant.
3. Verify typecheck.
4. Commit.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/ui/empty-state.tsx
git commit -m "style(ui): simplify EmptyState visuals (no glow)"
```

---

## Task 15: Sidebar: replace raw amber palette utilities with `warning` tokens

**Files:**
- Modify: `web/components/sidebar.tsx`

**Steps:**
1. Replace `amber-*` utilities with `warning` tokens (`bg-warning/..`, `text-warning`, `border-warning/..`).
2. Verify `ui-check`.
3. Commit.

**Verify:**
```bash
cd web && pnpm run ui-check
```

**Commit:**
```bash
git add web/components/sidebar.tsx
git commit -m "style(nav): use warning tokens instead of amber palette"
```

---

## Task 16: ParticleBackground: switch to token colors + pause on tab hidden

**Files:**
- Modify: `web/components/ui/particle-background.tsx`
- Modify: `web/lib/css-vars.ts` (if helper needed)

**Steps:**
1. Replace hard-coded `#ffffff`/`#0ea5e9` colors with CSS variable-driven colors (`getCssHslColor`).
2. Pause particles when `document.visibilityState !== 'visible'`.
3. Keep reduced-motion + `(pointer: fine)` guard.
4. Verify typecheck.
5. Commit.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/ui/particle-background.tsx web/lib/css-vars.ts
git commit -m "perf(ui): token-driven ParticleBackground + pause when hidden"
```

---

## Task 17: CinematicTypewriter: remove glow-y caret shadow + avoid arbitrary shadow utilities

**Files:**
- Modify: `web/components/ui/cinematic-typewriter.tsx`

**Steps:**
1. Remove glow-y caret shadow (`shadow-[...]`).
2. Keep caret readable using tokens only.
3. Verify lint + typecheck.
4. Commit.

**Verify:**
```bash
cd web && pnpm run lint && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/ui/cinematic-typewriter.tsx
git commit -m "style(chat): simplify typewriter caret (no glow)"
```

---

## Task 18: Navbar mobile overlay: remove full-screen backdrop blur (perf)

**Files:**
- Modify: `web/components/navbar.tsx`

**Steps:**
1. Remove `backdrop-blur-sm` from the full-screen mobile overlay.
2. Keep contrast and focus behavior.
3. Verify lint.
4. Commit.

**Verify:**
```bash
cd web && pnpm run lint
```

**Commit:**
```bash
git add web/components/navbar.tsx
git commit -m "perf(nav): remove heavy mobile overlay blur"
```

---

## Task 19: API debugging UX: surface `request_id` in error messages where available

**Files:**
- Modify: `web/lib/api-errors.ts`
- Modify: one representative UI surface that shows API errors (e.g., `web/app/auth/page.tsx`)

**Steps:**
1. Ensure `formatApiError` can append request id when present (safe, compact).
2. Update one page to display it in a copyable/visible way (avoid over-noising UI).
3. Verify web tests.
4. Commit.

**Verify:**
```bash
cd web && pnpm run test
```

**Commit:**
```bash
git add web/lib/api-errors.ts web/app/auth/page.tsx
git commit -m "feat(api): show request_id in user-facing error messages"
```

---

## Task 20: Verification record for round 3 (and ensure OpenAPI types remain in sync)

**Files:**
- Create: `docs/plans/2026-02-02-frontend-ui-polish-round-3-verification.md`

**Steps:**
1. Run `make openapi-check` and `make enterprise-checks`.
2. Record the commands + outcomes in a short verification doc.
3. Commit.

**Verify:**
```bash
make openapi-check
make enterprise-checks
```

**Commit:**
```bash
git add docs/plans/2026-02-02-frontend-ui-polish-round-3-verification.md
git commit -m "docs(plans): record round 3 verification"
```

