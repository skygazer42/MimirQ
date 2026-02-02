# Frontend UI Polish (Round 2) Implementation Plan

> **For Codex/Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Ship 20 small, reviewable frontend improvements (1 task = 1 commit) that improve UI clarity, accessibility, and performance while aligning with `baseline-ui` constraints (token-first, no gradients/glows by default, minimal motion, consistent z-index scale).

**Architecture:** Next.js App Router UI (Tailwind + Radix primitives). This round focuses on removing "decorative slop" (gradients, glows, excessive tracking/uppercase styling, long transitions) and replacing it with calmer, token-driven surfaces and consistent typography. Where optional visual effects exist (cursor/particles), gate them behind explicit feature flags and reduced-motion checks.

**Tech Stack:** Next.js 14, Tailwind CSS, Radix UI, TanStack Query, Sonner, Vitest.

**Notes:**
- Corridor MCP tool is not available in this environment; mitigate risk by keeping tasks small and running verification commands frequently.
- Do not commit local agent tooling folders (repo already ignores `.codex/` and `.gemini/`).

---

## Baseline Verification (do once before starting)

Run:
```bash
make enterprise-checks
```
Expected: Ruff OK, Next lint OK, `tsc --noEmit` OK, pytest OK, vitest OK.

---

## Task 1: Add this plan document

**Files:**
- Create: `docs/plans/2026-02-02-frontend-ui-polish-round-2.md`

**Steps:**
1. Add this plan file.
2. Commit.

**Commit:**
```bash
git add docs/plans/2026-02-02-frontend-ui-polish-round-2.md
git commit -m "docs(plans): add frontend UI polish round 2 plan"
```

---

## Task 2: Baseline typography in global CSS (no tracking; text-balance/text-pretty)

**Files:**
- Modify: `web/app/globals.css`

**Steps:**
1. Remove heading-wide `tracking-*` from base styles.
2. Add `text-balance` to headings and `text-pretty` to paragraphs in the base layer.
3. Remove unused gradient utility helpers (`.text-gradient`, `.border-gradient`).
4. Verify web lint.
5. Commit.

**Verify:**
```bash
cd web && pnpm run lint
```

**Commit:**
```bash
git add web/app/globals.css
git commit -m "style(ui): baseline typography + remove gradient utilities"
```

---

## Task 3: Fix shared Card typography to match baseline

**Files:**
- Modify: `web/components/ui/card.tsx`

**Steps:**
1. Remove `tracking-tight` from `CardTitle`.
2. Add `text-balance` to `CardTitle` and `text-pretty` to `CardDescription`.
3. Run typecheck.
4. Commit.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/ui/card.tsx
git commit -m "style(ui): align Card typography with baseline"
```

---

## Task 4: Replace AppBackground gradients/glows with a lightweight, token-driven backdrop

**Files:**
- Modify: `web/components/ui/app-background.tsx`

**Steps:**
1. Remove CSS gradient and blurred glow layers.
2. Replace with a simple, static SVG overlay (inline) using token colors (border/foreground) and low opacity.
3. Ensure it cannot create window scrollbars and is `aria-hidden`.
4. Verify build (typecheck).
5. Commit.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/ui/app-background.tsx
git commit -m "refactor(ui): make AppBackground lightweight and token-driven"
```

---

## Task 5: Make FluidCursor explicitly opt-in (feature flag + reduced-motion)

**Files:**
- Modify: `web/components/ui/fluid-cursor.tsx`
- Modify: `web/app/layout.tsx`

**Steps:**
1. Gate `FluidCursor` behind `NEXT_PUBLIC_ENABLE_FLUID_CURSOR=1`.
2. Keep existing pointer+reduced-motion guards.
3. Ensure no behavior changes when the flag is unset (default off).
4. Verify web lint.
5. Commit.

**Verify:**
```bash
cd web && pnpm run lint
```

**Commit:**
```bash
git add web/components/ui/fluid-cursor.tsx web/app/layout.tsx
git commit -m "perf(ui): gate FluidCursor behind explicit feature flag"
```

---

## Task 6: Auth page: remove particle background dependency (calmer, faster login)

**Files:**
- Modify: `web/app/auth/page.tsx`

**Steps:**
1. Remove `ParticleBackground` usage (and any other heavy decorative motion).
2. Use the existing token surfaces (`glass`, `Card`, `AppBackground` if appropriate) with minimal motion.
3. Verify typecheck.
4. Commit.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/app/auth/page.tsx
git commit -m "style(auth): simplify login visuals and remove particle background"
```

---

## Task 7: Navbar: remove gradient hover styles + tracking; tighten interaction durations

**Files:**
- Modify: `web/components/navbar.tsx`

**Steps:**
1. Replace gradient hover backgrounds with token-based `bg-accent/…` surfaces.
2. Remove `tracking-*` usage.
3. Ensure interactive transitions use <= 200ms and avoid `transition-all`.
4. Verify lint.
5. Commit.

**Verify:**
```bash
cd web && pnpm run lint
```

**Commit:**
```bash
git add web/components/navbar.tsx
git commit -m "style(nav): remove gradients/tracking and tighten navbar interactions"
```

---

## Task 8: Sidebar: remove gradient hover overlay; improve active state clarity

**Files:**
- Modify: `web/components/sidebar.tsx`

**Steps:**
1. Replace gradient overlay with a simple token highlight (bg-accent + border).
2. Remove `tracking-*` usage.
3. Verify lint.
4. Commit.

**Verify:**
```bash
cd web && pnpm run lint
```

**Commit:**
```bash
git add web/components/sidebar.tsx
git commit -m "style(nav): simplify sidebar hover/active states"
```

---

## Task 9: Chat composer: remove tracking-wide; add safe-area padding for fixed controls

**Files:**
- Modify: `web/components/chat-area.tsx`

**Steps:**
1. Remove `tracking-*` in the textarea/composer surface.
2. Ensure bottom padding respects `env(safe-area-inset-bottom)` for mobile.
3. Verify typecheck.
4. Commit.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/chat-area.tsx
git commit -m "style(chat): improve composer typography + safe-area padding"
```

---

## Task 10: Chat empty state: remove gradient/glow layers; keep one clear CTA

**Files:**
- Modify: `web/components/chat-area.tsx`

**Steps:**
1. Replace any gradient/glow decorative layers with token-based shapes/borders.
2. Ensure empty state has one clear next action (existing primary button).
3. Verify lint.
4. Commit.

**Verify:**
```bash
cd web && pnpm run lint
```

**Commit:**
```bash
git add web/components/chat-area.tsx
git commit -m "style(chat): simplify empty state visuals (no gradients/glows)"
```

---

## Task 11: Chat diagnostics dialog: remove HUD gradients/glows; make it a calm data panel

**Files:**
- Modify: `web/components/chat/message-item.tsx`

**Steps:**
1. Remove decorative gradient lines, glow shadows, and excessive tracking/uppercase styling.
2. Ensure tables use `tabular-nums` (and monospace where appropriate).
3. Keep copy-to-clipboard behavior; ensure buttons have labels.
4. Verify vitest (existing tests should still pass).
5. Commit.

**Verify:**
```bash
cd web && pnpm run test
```

**Commit:**
```bash
git add web/components/chat/message-item.tsx
git commit -m "style(chat): redesign diagnostics dialog for clarity and baseline"
```

---

## Task 12: Folder tree “paper band”: replace gradient band with token surface

**Files:**
- Modify: `web/components/document-library/folder-tree.tsx`

**Steps:**
1. Replace `bg-gradient-to-r` band with a simple `bg-muted`/`bg-accent` token variant.
2. Verify lint.
3. Commit.

**Verify:**
```bash
cd web && pnpm run lint
```

**Commit:**
```bash
git add web/components/document-library/folder-tree.tsx
git commit -m "style(ui): remove gradient band from folder tree"
```

---

## Task 13: Pipeline visualizer: remove gradient progress bar

**Files:**
- Modify: `web/components/ui/pipeline-visualizer.tsx`

**Steps:**
1. Replace gradient bar with a solid token-based bar.
2. Verify typecheck.
3. Commit.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/ui/pipeline-visualizer.tsx
git commit -m "style(ui): remove gradients from pipeline visualizer"
```

---

## Task 14: Parsing page: remove gradients in headers/empty states; tighten transition durations

**Files:**
- Modify: `web/app/parsing/page.tsx`

**Steps:**
1. Replace `bg-gradient-*` surfaces with `bg-card` / `bg-muted` token surfaces.
2. Reduce long interaction durations (>200ms) where used for hover/focus.
3. Verify lint.
4. Commit.

**Verify:**
```bash
cd web && pnpm run lint
```

**Commit:**
```bash
git add web/app/parsing/page.tsx
git commit -m "style(parsing): remove gradients + tighten interactions"
```

---

## Task 15: Graph page: remove gradient icon backgrounds and heavy shadows

**Files:**
- Modify: `web/app/graph/page.tsx`

**Steps:**
1. Replace gradient icon blocks with token surfaces and default shadow scale.
2. Replace `shadow-2xl` usage with `shadow-strong` where needed.
3. Verify typecheck.
4. Commit.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/app/graph/page.tsx
git commit -m "style(graph): remove gradients and normalize panel shadows"
```

---

## Task 16: History page: remove gradients and tracking; apply tabular-nums to timestamps

**Files:**
- Modify: `web/app/history/page.tsx`

**Steps:**
1. Replace gradient icon wrappers with token surfaces.
2. Remove `tracking-*` usage.
3. Add `tabular-nums` to timestamp / numeric columns.
4. Verify lint.
5. Commit.

**Verify:**
```bash
cd web && pnpm run lint
```

**Commit:**
```bash
git add web/app/history/page.tsx
git commit -m "style(history): simplify visuals + tabular numbers"
```

---

## Task 17: Evaluations/Knowledge pages: remove decorative top gradients

**Files:**
- Modify: `web/app/evaluations/page.tsx`
- Modify: `web/app/knowledge/page.tsx`

**Steps:**
1. Replace decorative gradient overlays with a simple divider/keyline (border) or remove entirely.
2. Verify typecheck.
3. Commit.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/app/evaluations/page.tsx web/app/knowledge/page.tsx
git commit -m "style(pages): remove decorative gradient overlays"
```

---

## Task 18: Remove remaining tracking-* usage across UI (targeted pass)

**Files:**
- Modify: (as needed; keep this task focused on 3-6 files with the highest-impact tracking usage)

**Steps:**
1. Remove remaining `tracking-*` from the most visible surfaces (navigation + primary pages).
2. Replace with font weight/size changes only.
3. Verify lint.
4. Commit.

**Verify:**
```bash
cd web && pnpm run lint
```

**Commit:**
```bash
git add web
git commit -m "style(ui): remove remaining tracking-* from core surfaces"
```

---

## Task 19: Update UI regression guard to block gradients + tracking classes

**Files:**
- Modify: `web/scripts/check-design-tokens.mjs`

**Steps:**
1. Add high-signal rules to forbid Tailwind gradient utilities (`bg-gradient-*`, `text-gradient`, etc.).
2. Add a rule to forbid Tailwind letter-spacing utilities (`tracking-*`).
3. Ensure no false positives (avoid matching colormap preview strings).
4. Verify `pnpm run ui-check` passes.
5. Commit.

**Verify:**
```bash
cd web && pnpm run ui-check
```

**Commit:**
```bash
git add web/scripts/check-design-tokens.mjs
git commit -m "chore(ui-check): forbid gradients and tracking utilities"
```

---

## Task 20: Final full verification

**Files:**
- None (verification-only)

**Steps:**
1. Run full CI-like checks.
2. Commit a short verification note to the plan file (append output summary).

**Verify:**
```bash
make enterprise-checks
```

**Commit:**
```bash
git add docs/plans/2026-02-02-frontend-ui-polish-round-2.md
git commit -m "docs(plans): record round 2 verification"
```

---

## Verification (2026-02-02)

Ran:
```bash
make enterprise-checks
```

Result: PASS
- ruff: OK
- api-check: OK (contract + coverage)
- web: lint OK, ui-check OK, typecheck OK
- backend: compileall OK
- pytest: 568 passed, 3 skipped (integration tests disabled by default)
- vitest: 28 files, 72 tests passed

Notes:
- One Python warning: torch/cuda FutureWarning (pynvml deprecation).
- One vitest warning: Vite CJS Node API deprecation notice.
