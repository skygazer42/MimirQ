# Next-Intl Command Menu Rollout Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Normalize locale-aware navigation for the global command menu by switching it to the shared `next-intl` navigation helper and filling the last route wrappers it targets directly.

**Architecture:** Keep the command menu behavior and command catalog unchanged. Swap `usePathname` and `useRouter` in `web/components/command-menu.tsx` to the shared `@/i18n/navigation` helper, then add thin `[locale]` wrappers for the remaining command-menu-only destinations (`observability` and dataset profile detail) so locale-prefixed transitions resolve cleanly.

**Tech Stack:** Next.js 16 App Router, `next-intl` 4.8.3, Vitest source tests, ESLint, TypeScript.

---

### Task 1: Guard locale-aware command menu wiring

**Files:**
- Modify: `web/components/command-menu.source.test.ts`

**Step 1: Write the failing test**

Require:
- `web/components/command-menu.tsx` to import `usePathname` and `useRouter` from `@/i18n/navigation`
- `web/components/command-menu.tsx` to stop importing them from `next/navigation`
- locale wrappers to exist for:
  - `web/app/[locale]/observability/page.tsx`
  - `web/app/[locale]/datasets/[id]/profile/page.tsx`

**Step 2: Run test to verify it fails**

Run: `pnpm test components/command-menu.source.test.ts`

Expected: FAIL because the command menu still uses Next.js routing primitives and those wrappers do not exist yet.

**Step 3: Write minimal implementation**

Switch `web/components/command-menu.tsx` to the shared locale-aware helper and add the two wrapper pages above.

**Step 4: Run test to verify it passes**

Run: `pnpm test components/command-menu.source.test.ts`

Expected: PASS.

### Task 2: Verify the command menu rollout does not regress existing search/navigation guards

**Files:**
- Modify: `web/components/command-menu.tsx`

**Step 1: Run focused source tests**

Run:
- `pnpm test components/command-menu.source.test.ts components/navbar.source.test.ts i18n/navigation.source.test.ts components/chat/slash-menu.source.test.ts app/history/page.source.test.ts`

Expected: PASS.

**Step 2: Run type/lint verification**

Run:
- `pnpm exec eslint components/command-menu.tsx components/command-menu.source.test.ts 'app/[locale]/observability/page.tsx' 'app/[locale]/datasets/[id]/profile/page.tsx'`
- `pnpm exec tsc --noEmit --pretty false`

Expected: PASS.

### Task 3: Land the command menu slice safely

**Files:**
- Modify: `.beads/issues.jsonl`

**Step 1: Update issue notes**

Append a note to `MimirQ-me4q` describing the command-menu migration and the new wrapper coverage, plus what still remains (auth callbacks/redirects, not-found/error entry points, deeper dynamic routes beyond dataset profile/history/home).

**Step 2: Run build**

Run: `pnpm run build`

Expected: PASS with no new next-intl routing failures or bundle-budget regressions.

**Step 3: Commit and push**

Run:
- `git add ...`
- `git commit -m "Extend next-intl command menu route coverage"`
- `git pull --rebase`
- `bd sync`
- `git push`
- `git status -sb`

Expected: clean worktree and branch aligned with `origin/main`.
