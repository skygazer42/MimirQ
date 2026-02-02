# Frontend UI Polish (Round 4) Implementation Plan

> **For Codex/Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Execute 20 small, reviewable tasks (1 task = 1 commit) to improve global UI consistency (A) and reduce motion/performance overhead (C), aligned with `baseline-ui` constraints (token-first, no gradients/glows by default, minimal motion, fixed z-index scale).

**Scope:** Next.js App Router UI (Tailwind + Radix primitives). This round focuses on:
- removing remaining decorative “paper texture” overlays + hard-coded hex surfaces
- tightening `transition-all` hotspots (prefer `transition-*` + `duration-200`)
- fixing a worst-case full-screen canvas loop (voice mode overlay)
- keeping frontend/backend API contract checks green (OpenAPI + contract/coverage)

---

## Task 1: Add design doc for round 4

**Files:**
- Create: `docs/plans/2026-02-02-frontend-ui-polish-round-4-design.md`

**Commit:**
```bash
git add docs/plans/2026-02-02-frontend-ui-polish-round-4-design.md
git commit -m "docs(plans): add frontend UI polish round 4 design"
```

---

## Task 2: Add this plan document

**Files:**
- Create: `docs/plans/2026-02-02-frontend-ui-polish-round-4.md`

**Commit:**
```bash
git add docs/plans/2026-02-02-frontend-ui-polish-round-4.md
git commit -m "docs(plans): add frontend UI polish round 4 plan"
```

---

## Task 3: IngestionDetailDialog: remove paper texture overlay

**Files:**
- Modify: `web/components/ingestion/ingestion-detail-dialog.tsx`

**Steps:**
1. Remove the SVG noise “paper texture” overlay layer.
2. Keep the dialog readable with token surfaces only.
3. Verify web typecheck.
4. Commit.

**Verify:**
```bash
cd web; pnpm run typecheck
```

**Commit:**
```bash
git add web/components/ingestion/ingestion-detail-dialog.tsx
git commit -m "style(ingestion): remove decorative texture overlay"
```

---

## Task 4: IngestionDetailDialog: tokenize DialogContent container (no hex/slate)

**Files:**
- Modify: `web/components/ingestion/ingestion-detail-dialog.tsx`

**Steps:**
1. Replace `bg-[#fafafa]`, `border-slate-*`, `shadow-2xl`, `rounded-[2rem]` with token-driven + Tailwind scale equivalents.
2. Prefer `bg-popover`/`bg-card`, `border-border`, `shadow-strong`, `sm:rounded-2xl` (or similar consistent scale).
3. Verify lint + typecheck.
4. Commit.

**Verify:**
```bash
cd web; pnpm run lint; pnpm run typecheck
```

**Commit:**
```bash
git add web/components/ingestion/ingestion-detail-dialog.tsx
git commit -m "style(ingestion): align ingestion detail dialog with token surfaces"
```

---

## Task 5: IngestionDetailDialog: header + progress meta token cleanup

**Files:**
- Modify: `web/components/ingestion/ingestion-detail-dialog.tsx`

**Steps:**
1. Replace remaining `slate-*` text/background classes in the header + progress meta.
2. Add `tabular-nums` for numeric progress.
3. Verify typecheck.
4. Commit.

**Verify:**
```bash
cd web; pnpm run typecheck
```

**Commit:**
```bash
git add web/components/ingestion/ingestion-detail-dialog.tsx
git commit -m "style(ingestion): tighten header tokens and numeric typography"
```

---

## Task 6: IngestionDetailDialog: simplify pipeline stage indicators (no glow/transition-all)

**Files:**
- Modify: `web/components/ingestion/ingestion-detail-dialog.tsx`

**Steps:**
1. Remove `shadow-[...]` glow, `transition-all`, and large scale effects.
2. Map status colors to semantic tokens: `success`, `primary`, `warning`, `destructive`, `muted`.
3. Prefer `size-*` for square elements.
4. Ensure transitions are <=200ms and compositor-only where used.
5. Verify web lint + typecheck.
6. Commit.

**Verify:**
```bash
cd web; pnpm run lint; pnpm run typecheck
```

**Commit:**
```bash
git add web/components/ingestion/ingestion-detail-dialog.tsx
git commit -m "perf(ingestion): simplify pipeline stage indicator visuals"
```

---

## Task 7: IngestionDetailDialog: runtime details tokenization

**Files:**
- Modify: `web/components/ingestion/ingestion-detail-dialog.tsx`

**Steps:**
1. Replace `bg-slate-*` and `border-slate-*` runtime card styling with token surfaces.
2. Keep hover feedback subtle (shadow transition only, <=200ms).
3. Verify typecheck.
4. Commit.

**Verify:**
```bash
cd web; pnpm run typecheck
```

**Commit:**
```bash
git add web/components/ingestion/ingestion-detail-dialog.tsx
git commit -m "style(ingestion): tokenise runtime details surface"
```

---

## Task 8: IngestionDetailDialog: action buttons baseline cleanup

**Files:**
- Modify: `web/components/ingestion/ingestion-detail-dialog.tsx`

**Steps:**
1. Replace custom `sky/red/amber` button classes with component variants + tokens.
2. Avoid `shadow-*` glows and keep interaction feedback <=200ms.
3. Verify lint.
4. Commit.

**Verify:**
```bash
cd web; pnpm run lint
```

**Commit:**
```bash
git add web/components/ingestion/ingestion-detail-dialog.tsx
git commit -m "style(ingestion): standardize action buttons"
```

---

## Task 9: Knowledge feedback: detail dialog remove texture + token surfaces

**Files:**
- Modify: `web/app/knowledge/feedback/page.tsx`

**Steps:**
1. Remove the SVG noise “paper texture” overlay.
2. Replace DialogContent hard-coded hex/slate colors with tokens.
3. Verify typecheck.
4. Commit.

**Verify:**
```bash
cd web; pnpm run typecheck
```

**Commit:**
```bash
git add web/app/knowledge/feedback/page.tsx
git commit -m "style(knowledge): simplify feedback detail dialog surfaces"
```

---

## Task 10: Knowledge feedback: tag chips tokenization

**Files:**
- Modify: `web/app/knowledge/feedback/page.tsx`

**Steps:**
1. Replace `indigo-*` chip palette utilities with token equivalents.
2. Keep labels readable and calm; avoid decorative uppercasing where possible.
3. Verify lint.
4. Commit.

**Verify:**
```bash
cd web; pnpm run lint
```

**Commit:**
```bash
git add web/app/knowledge/feedback/page.tsx
git commit -m "style(knowledge): tokenise feedback tags"
```

---

## Task 11: Knowledge feedback: list card hover + shadow cleanup

**Files:**
- Modify: `web/app/knowledge/feedback/page.tsx`

**Steps:**
1. Replace arbitrary `shadow-[...]` with Tailwind shadow scale (or token shadow utilities).
2. Remove hover “float” translate and replace `transition-all` with a narrower transition.
3. Verify lint + typecheck.
4. Commit.

**Verify:**
```bash
cd web; pnpm run lint; pnpm run typecheck
```

**Commit:**
```bash
git add web/app/knowledge/feedback/page.tsx
git commit -m "style(knowledge): tighten feedback list card interactions"
```

---

## Task 12: Knowledge feedback: empty state next action

**Files:**
- Modify: `web/app/knowledge/feedback/page.tsx`

**Steps:**
1. Give empty state one clear next action (e.g., clear search/filter).
2. Tokenize icon container and text colors.
3. Verify typecheck.
4. Commit.

**Verify:**
```bash
cd web; pnpm run typecheck
```

**Commit:**
```bash
git add web/app/knowledge/feedback/page.tsx
git commit -m "ux(knowledge): add a clear next action to feedback empty state"
```

---

## Task 13: CommandDialog: reduce heavy blur + tokenize dark surface

**Files:**
- Modify: `web/components/ui/command.tsx`

**Steps:**
1. Reduce `backdrop-blur-3xl` to a lighter value (or remove).
2. Replace `dark:bg-slate-950/80` with token-based surface.
3. Keep styling consistent with `DialogContent` baseline.
4. Verify lint + typecheck.
5. Commit.

**Verify:**
```bash
cd web; pnpm run lint; pnpm run typecheck
```

**Commit:**
```bash
git add web/components/ui/command.tsx
git commit -m "perf(ui): lighten CommandDialog surfaces (less blur)"
```

---

## Task 14: globals.css: replace `transition-all` in `.glass-card`

**Files:**
- Modify: `web/app/globals.css`

**Steps:**
1. Replace `transition-all` with a narrower transition.
2. Ensure interaction feedback is <=200ms; keep `motion-reduce` guards.
3. Verify web lint.
4. Commit.

**Verify:**
```bash
cd web; pnpm run lint
```

**Commit:**
```bash
git add web/app/globals.css
git commit -m "style(css): tighten glass-card transition properties"
```

---

## Task 15: ThemeCustomizer: floating trigger baseline cleanup

**Files:**
- Modify: `web/components/theme-customizer.tsx`

**Steps:**
1. Replace `h-12 w-12` with `size-12`.
2. Remove hover rotate and `transition-all`; keep feedback subtle and <=200ms.
3. Respect safe-area inset for the fixed button.
4. Verify typecheck.
5. Commit.

**Verify:**
```bash
cd web; pnpm run typecheck
```

**Commit:**
```bash
git add web/components/theme-customizer.tsx
git commit -m "style(theme): polish ThemeCustomizer trigger"
```

---

## Task 16: ThemeCustomizer: tighten internal control transitions

**Files:**
- Modify: `web/components/theme-customizer.tsx`

**Steps:**
1. Replace `transition-all` on internal controls with `transition-colors` (or `transition`).
2. Keep durations <=200ms and preserve focus styles.
3. Verify lint.
4. Commit.

**Verify:**
```bash
cd web; pnpm run lint
```

**Commit:**
```bash
git add web/components/theme-customizer.tsx
git commit -m "style(theme): tighten ThemeCustomizer control interactions"
```

---

## Task 17: VoiceModeOverlay: resize canvas on open/resize (no per-frame reflow)

**Files:**
- Modify: `web/components/chat/voice-mode-overlay.tsx`

**Steps:**
1. Stop setting `canvas.width/height` on every frame.
2. Implement size sync on open + window resize (with devicePixelRatio).
3. Keep draw loop compositor-friendly by avoiding layout reads in the animation frame.
4. Verify lint + typecheck.
5. Commit.

**Verify:**
```bash
cd web; pnpm run lint; pnpm run typecheck
```

**Commit:**
```bash
git add web/components/chat/voice-mode-overlay.tsx
git commit -m "perf(voice): avoid per-frame canvas resize in voice overlay"
```

---

## Task 18: VoiceModeOverlay: animate only when listening + pause when hidden

**Files:**
- Modify: `web/components/chat/voice-mode-overlay.tsx`

**Steps:**
1. Only run the rAF loop when listening (otherwise render a single static frame).
2. Pause when `document.visibilityState !== 'visible'`.
3. Respect `prefers-reduced-motion` (no loop).
4. Verify typecheck.
5. Commit.

**Verify:**
```bash
cd web; pnpm run typecheck
```

**Commit:**
```bash
git add web/components/chat/voice-mode-overlay.tsx
git commit -m "perf(voice): pause voice overlay animation when inactive/hidden"
```

---

## Task 19: useResizeObserver: remove rAF+setTimeout retry loop

**Files:**
- Modify: `web/hooks/use-resize-observer.ts`

**Steps:**
1. Remove nested `requestAnimationFrame(() => setTimeout(...))`.
2. Prefer a single initial measure + `ResizeObserver` updates (optionally rAF-throttled).
3. Ensure cleanup is correct.
4. Verify web typecheck + tests.
5. Commit.

**Verify:**
```bash
cd web; pnpm run typecheck; pnpm run test
```

**Commit:**
```bash
git add web/hooks/use-resize-observer.ts
git commit -m "perf(hooks): simplify useResizeObserver scheduling"
```

---

## Task 20: Verification record for round 4

**Files:**
- Create: `docs/plans/2026-02-02-frontend-ui-polish-round-4-verification.md`

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
git add docs/plans/2026-02-02-frontend-ui-polish-round-4-verification.md
git commit -m "docs(plans): record round 4 verification"
```

