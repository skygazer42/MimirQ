# Next-Intl Dataset Detail Rollout Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Normalize locale-aware routing for dataset detail pages by switching their route transitions to the shared `next-intl` navigation helper and adding locale wrappers for the missing detail subpages.

**Architecture:** Keep the dataset detail business pages unchanged. Swap `useRouter` imports from `next/navigation` to `@/i18n/navigation` in the dataset detail entry files while leaving `useParams` and `useSearchParams` on `next/navigation` where needed. Add thin `[locale]/datasets/[id]/...` wrapper pages for the missing detail subroutes so locale-prefixed dataset navigation resolves cleanly.

**Tech Stack:** Next.js 16 App Router, `next-intl` 4.8.3, Vitest source tests, ESLint, TypeScript.

---

### Task 1: Guard locale-aware dataset detail routing wiring

**Files:**
- Create: `web/i18n/dataset-detail-routing.source.test.ts`

**Step 1: Write the failing test**

Require:
- `web/app/datasets/[id]/health/page-client.tsx` to import `useRouter` from `@/i18n/navigation`
- `web/app/datasets/[id]/profile/page-client.tsx` to import `useRouter` from `@/i18n/navigation`
- `web/app/datasets/[id]/db-catalog/page.tsx` to import `useRouter` from `@/i18n/navigation`
- `web/app/datasets/[id]/evidence/page.tsx` to import `useRouter` from `@/i18n/navigation` while keeping `useParams` and `useSearchParams` on `next/navigation`
- `web/app/datasets/[id]/ingestion/page.tsx` to import `useRouter` from `@/i18n/navigation`
- `web/app/datasets/[id]/precheck/page-client.tsx` to import `useRouter` from `@/i18n/navigation`
- `web/app/datasets/[id]/tables/page.tsx` to import `useRouter` from `@/i18n/navigation`
- `web/app/datasets/[id]/workflow/page.tsx` to import `useRouter` from `@/i18n/navigation`
- `web/components/datasets/dataset-kg-workbench-page.tsx` to import `useRouter` from `@/i18n/navigation`
- locale wrappers to exist for:
  - `web/app/[locale]/datasets/[id]/db-catalog/page.tsx`
  - `web/app/[locale]/datasets/[id]/evidence/page.tsx`
  - `web/app/[locale]/datasets/[id]/health/page.tsx`
  - `web/app/[locale]/datasets/[id]/ingestion/page.tsx`
  - `web/app/[locale]/datasets/[id]/kg/page.tsx`
  - `web/app/[locale]/datasets/[id]/precheck/page.tsx`
  - `web/app/[locale]/datasets/[id]/tables/page.tsx`
  - `web/app/[locale]/datasets/[id]/workflow/page.tsx`

**Step 2: Run test to verify it fails**

Run: `pnpm test i18n/dataset-detail-routing.source.test.ts`

Expected: FAIL because the dataset detail pages still use `next/navigation` for `useRouter` and the locale wrappers do not exist yet.

**Step 3: Write minimal implementation**

Switch the dataset detail route-entry files to the shared locale-aware helper and add the eight missing wrapper pages above.

**Step 4: Run test to verify it passes**

Run: `pnpm test i18n/dataset-detail-routing.source.test.ts`

Expected: PASS.

### Task 2: Verify the dataset detail rollout does not regress existing route guards

**Files:**
- Modify: `web/app/datasets/[id]/health/page-client.tsx`
- Modify: `web/app/datasets/[id]/profile/page-client.tsx`
- Modify: `web/app/datasets/[id]/db-catalog/page.tsx`
- Modify: `web/app/datasets/[id]/evidence/page.tsx`
- Modify: `web/app/datasets/[id]/ingestion/page.tsx`
- Modify: `web/app/datasets/[id]/precheck/page-client.tsx`
- Modify: `web/app/datasets/[id]/tables/page.tsx`
- Modify: `web/app/datasets/[id]/workflow/page.tsx`
- Modify: `web/components/datasets/dataset-kg-workbench-page.tsx`

**Step 1: Run focused source tests**

Run:
- `pnpm test i18n/dataset-detail-routing.source.test.ts app/datasets/[id]/health/page-client.source.test.ts app/datasets/[id]/ingestion/page.source.test.ts app/datasets/[id]/kg/page.entry.test.ts components/navbar.source.test.ts components/command-menu.source.test.ts i18n/navigation.source.test.ts`

Expected: PASS.

**Step 2: Run type/lint verification**

Run:
- `pnpm exec eslint app/datasets/[id]/health/page-client.tsx app/datasets/[id]/profile/page-client.tsx app/datasets/[id]/db-catalog/page.tsx app/datasets/[id]/evidence/page.tsx app/datasets/[id]/ingestion/page.tsx app/datasets/[id]/precheck/page-client.tsx app/datasets/[id]/tables/page.tsx app/datasets/[id]/workflow/page.tsx components/datasets/dataset-kg-workbench-page.tsx i18n/dataset-detail-routing.source.test.ts 'app/[locale]/datasets/[id]/db-catalog/page.tsx' 'app/[locale]/datasets/[id]/evidence/page.tsx' 'app/[locale]/datasets/[id]/health/page.tsx' 'app/[locale]/datasets/[id]/ingestion/page.tsx' 'app/[locale]/datasets/[id]/kg/page.tsx' 'app/[locale]/datasets/[id]/precheck/page.tsx' 'app/[locale]/datasets/[id]/tables/page.tsx' 'app/[locale]/datasets/[id]/workflow/page.tsx'`
- `pnpm exec tsc --noEmit --pretty false`

Expected: PASS.

### Task 3: Land the dataset detail slice safely

**Files:**
- Modify: `.beads/issues.jsonl`

**Step 1: Update issue notes**

Append a note to `MimirQ-me4q` describing the dataset detail page migration and new wrapper coverage, plus what still remains (not-found/error entry points, broader message catalogs, and non-dataset business pages still using `next/navigation` directly).

**Step 2: Run build**

Run: `pnpm run build`

Expected: PASS with no new next-intl routing failures or bundle-budget regressions.

**Step 3: Commit and push**

Run:
- `git add ...`
- `git commit -m "Extend next-intl dataset detail coverage"`
- `git pull --rebase`
- `bd sync`
- `git push`
- `git status -sb`

Expected: clean worktree and branch aligned with `origin/main`.
