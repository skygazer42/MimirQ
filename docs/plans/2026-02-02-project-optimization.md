# Project Optimization Implementation Plan (FE/BE Connectivity + Frontend Polish)

> **For Codex/Claude:** This repo prefers small, safe changes with frequent commits. Execute this plan task-by-task with verification between batches.

**Goal:** Confirm frontend↔backend connectivity is correct and ship 20 incremental, reviewable optimizations (1 commit per task) focused on UI quality, accessibility, and dev diagnostics.

**Architecture:** Keep the existing FastAPI `/api/v1` + Next.js App Router structure. Prefer token-based Tailwind styling, existing Radix-based primitives, and small refactors that preserve behavior.

**Tech Stack:** FastAPI, Next.js 14, Tailwind CSS, Radix UI, TanStack Query, axios, Vitest, Ruff, Pytest.

**Notes:**
- Repo already has static FE/BE contract guards: `make api-check` (route existence + coverage).
- A runtime “is the backend reachable” check is useful for local debugging; we will add a small CLI helper and improve the `/diagnostics` page.
- Corridor MCP tool is not available in this environment; we will do manual risk checks and keep commits small.

---

## Baseline Verification (do once before starting)

Run:
```bash
make enterprise-checks
```
Expected: `make verify` passes; backend pytest passes; web vitest passes.

---

## Task 1: Add optimization plan document

**Files:**
- Create: `docs/plans/2026-02-02-project-optimization.md`

**Steps:**
1. Add the plan file (this document).
2. Commit.

**Commit:**
```bash
git add docs/plans/2026-02-02-project-optimization.md
git commit -m "docs(plans): add 2026-02-02 optimization plan"
```

---

## Task 2: Add CLI backend reachability ping helper

**Files:**
- Create: `scripts/api_ping.py`
- Modify: `Makefile`
- Modify (docs): `docs/integration/FE_BE_DEBUG.md`

**Steps:**
1. Add a small script that calls `GET /api/v1/health` and `GET /api/v1/health/ready` and prints status/latency.
2. Add `make api-ping` target (uses `BACKEND_BASE_URL` or defaults to `http://localhost:8000`).
3. Document it in FE/BE debug checklist.
4. Verify script runs (`python scripts/api_ping.py --help`).
5. Commit.

---

## Task 3: Diagnostics page: show backend health summary + latency

**Files:**
- Create: `web/hooks/use-backend-health.ts`
- Modify: `web/app/diagnostics/page.tsx`

**Steps:**
1. Add `useBackendHealth()` hook (TanStack Query).
2. Add a “Backend Health” card: status, latency, and raw JSON (copy button).
3. Verify: `cd web && pnpm lint && pnpm typecheck && pnpm test`.
4. Commit.

---

## Task 4: Introduce a consistent z-index scale (remove z-[...])

**Files:**
- Modify: `web/tailwind.config.ts`
- Modify: `web/components/ui/fluid-cursor.tsx`
- Modify: `web/components/chat/voice-mode-overlay.tsx`
- Modify: `web/components/document-viewer/floating-menu.tsx`
- Modify: `web/components/app-frame.tsx`

**Steps:**
1. Add named z-index tokens in Tailwind (e.g. `z-overlay`, `z-popover`, `z-cursor`).
2. Replace `z-[...]` usages with the named scale.
3. Verify: `cd web && pnpm lint && pnpm typecheck`.
4. Commit.

---

## Task 5: FluidCursor: avoid layout animations (transform/opacity only)

**Files:**
- Modify: `web/components/ui/fluid-cursor.tsx`

**Steps:**
1. Replace width/height animation with transform scale; keep behavior unchanged.
2. Ensure `prefers-reduced-motion` still disables the cursor.
3. Verify: `cd web && pnpm lint && pnpm typecheck`.
4. Commit.

---

## Task 6: PageHeader redesign (remove gradients/glow; improve typography)

**Files:**
- Modify: `web/components/ui/page-header.tsx`

**Steps:**
1. Remove glow/blur/gradient visuals; keep a distinctive but restrained “instrument panel” header.
2. Apply baseline typography helpers: `text-balance` on title, `text-pretty` on description.
3. Replace `w-* h-*` squares with `size-*` where reasonable in touched code.
4. Verify: `cd web && pnpm lint && pnpm typecheck && pnpm test`.
5. Commit.

---

## Task 7: Mode toggle: enforce icon-button accessibility

**Files:**
- Modify: `web/components/mode-toggle.tsx`

**Steps:**
1. Add explicit `aria-label` to the icon-only trigger.
2. Use `size-*` utilities for square sizing in this component.
3. Verify: `cd web && pnpm lint && pnpm typecheck`.
4. Commit.

---

## Task 8: Auth page: remove hero gradient background + reduce glow

**Files:**
- Modify: `web/app/auth/page.tsx`
- Modify: `web/tailwind.config.ts`
- Modify (optional): `web/app/globals.css`

**Steps:**
1. Replace `bg-hero-glow` usage with token-based surfaces + optional subtle noise texture.
2. If `hero-glow` becomes unused, remove it from Tailwind config.
3. Verify: `cd web && pnpm lint && pnpm typecheck`.
4. Commit.

---

## Task 9: Replace `shadow-glow` in Sidebar document cards

**Files:**
- Modify: `web/components/sidebar.tsx`

**Steps:**
1. Replace selected-state glow with token shadow/border emphasis.
2. Verify: `cd web && pnpm lint && pnpm typecheck && pnpm test`.
3. Commit.

---

## Task 10: Replace `shadow-glow` in datasets CTA(s)

**Files:**
- Modify: `web/app/datasets/page.tsx`

**Steps:**
1. Replace glow shadows with token-based shadows/borders.
2. Verify: `cd web && pnpm lint && pnpm typecheck`.
3. Commit.

---

## Task 11: Replace `shadow-glow` in knowledge CTA(s)

**Files:**
- Modify: `web/app/knowledge/page.tsx`

**Steps:**
1. Replace glow shadows with token-based shadows/borders.
2. Verify: `cd web && pnpm lint && pnpm typecheck`.
3. Commit.

---

## Task 12: Replace `shadow-glow` in chunk-preview workbench sidebar

**Files:**
- Modify: `web/components/chunk-preview/components/workbench/sidebar.tsx`

**Steps:**
1. Replace glow shadow usage with token-based styling.
2. Verify: `cd web && pnpm lint && pnpm typecheck && pnpm test`.
3. Commit.

---

## Task 13: Remove `shadow-glow` token if fully unused

**Files:**
- Modify: `web/tailwind.config.ts`

**Steps:**
1. Confirm no `shadow-glow` references remain.
2. Remove the custom `shadow-glow` token if unused.
3. Verify: `cd web && pnpm lint && pnpm typecheck`.
4. Commit.

---

## Task 14: FloatingMenu: clamp position + improve robustness

**Files:**
- Modify: `web/components/document-viewer/floating-menu.tsx`

**Steps:**
1. Clamp menu position to viewport (avoid rendering off-screen).
2. Use safe-area insets for top/bottom padding where relevant.
3. Replace `w-* h-*` icon sizes with `size-*` in this file.
4. Verify: `cd web && pnpm lint && pnpm typecheck`.
5. Commit.

---

## Task 15: Graph controls: replace raw palette colors with tokens

**Files:**
- Modify: `web/app/graph/page.tsx`

**Steps:**
1. Replace `sky-*` color utilities in control buttons with token-based `accent/info` styling.
2. Verify: `cd web && pnpm lint && pnpm typecheck`.
3. Commit.

---

## Task 16: ForceGraph2D wrapper: dynamic import + loading skeleton

**Files:**
- Modify: `web/components/graph/force-graph-2d-wrapper.tsx`
- Modify (optional): `web/components/ui/skeleton.tsx`

**Steps:**
1. Dynamic import 2D graph to reduce initial bundle and avoid SSR pitfalls.
2. Provide a skeleton placeholder during load.
3. Verify: `cd web && pnpm lint && pnpm typecheck`.
4. Commit.

---

## Task 17: Diagnostics: improve copy-to-clipboard fallback + errors

**Files:**
- Modify: `web/app/diagnostics/page.tsx`

**Steps:**
1. Make clipboard fallback more robust and surface copy failures via toast.
2. Verify: `cd web && pnpm lint && pnpm typecheck && pnpm test`.
3. Commit.

---

## Task 18: Backend meta: include more safe debug hints (non-sensitive)

**Files:**
- Modify: `app/api/v1/meta.py`
- Modify: `app/api/schemas/meta.py` (if schema needs update)

**Steps:**
1. Add safe fields helpful for FE/BE debugging (e.g. `auth_mode`, `cors_enabled` flag).
2. Do NOT expose secrets or full env vars.
3. Verify: `python -m pytest -q`.
4. Commit.

---

## Task 19: Web: surface request_id on API errors in UI

**Files:**
- Modify: `web/lib/api-errors.ts`
- Modify: `web/lib/api-client.ts`
- Modify: `web/lib/api-errors.test.ts`

**Steps:**
1. Ensure `X-Request-ID` is captured and included in error objects.
2. Keep console logging but make it easier for UI to show request_id.
3. Verify: `cd web && pnpm test`.
4. Commit.

---

## Task 20: Final full verification + tidy

**Files:**
- Modify (docs): `CHANGELOG.md` (optional, if project policy requires)

**Steps:**
1. Run full checks:
   ```bash
   make enterprise-checks
   ```
2. Ensure `git status` clean (in this worktree).
3. Commit any final small doc updates needed.

---

## Execution Log (2026-02-02)

- Branch: `optimize-2026-02-02`
- Final verification: `make enterprise-checks` (PASS)
