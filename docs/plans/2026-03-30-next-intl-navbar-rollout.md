# Next-Intl Navbar Rollout Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Normalize locale-aware navigation for the global navbar by switching it to the shared `next-intl` navigation helper and adding locale wrappers for the routes it owns.

**Architecture:** Keep the current navbar structure and IA unchanged. Swap `next/link` and `next/navigation` imports in `web/components/navbar.tsx` to the shared `@/i18n/navigation` helper, then add thin `[locale]` page wrappers for the routes the navbar links to so locale-prefixed transitions resolve to real app routes.

**Tech Stack:** Next.js 16 App Router, `next-intl` 4.8.3, Vitest source tests, ESLint, TypeScript.

---

### Task 1: Guard locale-aware navbar wiring

**Files:**
- Modify: `web/components/navbar.source.test.ts`

**Step 1: Write the failing test**

Require:
- `web/components/navbar.tsx` to import `Link`, `usePathname`, and `useRouter` from `@/i18n/navigation`
- `web/components/navbar.tsx` to stop importing `next/link` and `next/navigation`
- locale wrappers to exist for the routes the navbar owns:
  - `web/app/[locale]/access-review/page.tsx`
  - `web/app/[locale]/audit/page.tsx`
  - `web/app/[locale]/auth/page.tsx`
  - `web/app/[locale]/chunk-preview/page.tsx`
  - `web/app/[locale]/data-governance/page.tsx`
  - `web/app/[locale]/data-governance/common-lines/page.tsx`
  - `web/app/[locale]/data-governance/profiles/page.tsx`
  - `web/app/[locale]/datasets/page.tsx`
  - `web/app/[locale]/diagnostics/page.tsx`
  - `web/app/[locale]/evaluations/ablations/page.tsx`
  - `web/app/[locale]/graph/page.tsx`
  - `web/app/[locale]/graph/diagnostics/page.tsx`
  - `web/app/[locale]/graph/snapshots/page.tsx`
  - `web/app/[locale]/knowledge/feedback/page.tsx`
  - `web/app/[locale]/knowledge/ingestion/page.tsx`
  - `web/app/[locale]/knowledge/quarantine/page.tsx`
  - `web/app/[locale]/knowledge/similarity/page.tsx`
  - `web/app/[locale]/parsing/page.tsx`
  - `web/app/[locale]/prompts/page.tsx`
  - `web/app/[locale]/reports/page.tsx`
  - `web/app/[locale]/settings/page.tsx`
  - `web/app/[locale]/settings/groups/page.tsx`
  - `web/app/[locale]/settings/rbac/page.tsx`
  - `web/app/[locale]/usage/page.tsx`

**Step 2: Run test to verify it fails**

Run: `pnpm test components/navbar.source.test.ts`

Expected: FAIL because the navbar still uses Next.js routing primitives and the locale wrappers do not exist yet.

**Step 3: Write minimal implementation**

Switch the navbar to the shared locale-aware navigation helper and add the wrapper pages listed above.

**Step 4: Run test to verify it passes**

Run: `pnpm test components/navbar.source.test.ts`

Expected: PASS.

### Task 2: Verify the navbar rollout does not regress shell navigation

**Files:**
- Modify: `web/components/navbar.tsx`

**Step 1: Run focused source tests**

Run:
- `pnpm test components/navbar.source.test.ts i18n/navigation.source.test.ts components/chat/slash-menu.source.test.ts app/history/page.source.test.ts`

Expected: PASS.

**Step 2: Run type/lint verification**

Run:
- `pnpm exec eslint components/navbar.tsx components/navbar.source.test.ts 'app/[locale]/**/*.tsx'`
- `pnpm exec tsc --noEmit --pretty false`

Expected: PASS.

### Task 3: Land the navbar slice safely

**Files:**
- Modify: `.beads/issues.jsonl`

**Step 1: Update issue notes**

Append a note to `MimirQ-me4q` describing the navbar migration and the new wrapper coverage, plus what still remains (`command-menu`, auth callbacks/redirects, deeper dynamic routes such as dataset detail pages).

**Step 2: Run build**

Run: `pnpm run build`

Expected: PASS with no new next-intl routing failures or bundle-budget regressions.

**Step 3: Commit and push**

Run:
- `git add ...`
- `git commit -m "Extend next-intl navbar route coverage"`
- `git pull --rebase`
- `bd sync`
- `git push`
- `git status -sb`

Expected: clean worktree and branch aligned with `origin/main`.
