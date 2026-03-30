# Next-Intl Chunk Preview Context Rollout Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Migrate the chunk-preview context's router usage to the locale-aware helper without depending on the current browser pathname for query-sync updates.

**Architecture:** Keep the deep-link `chunk` query syncing behavior unchanged, but replace the current `window.location.pathname`-based `router.replace` with the internal route path `/chunk-preview` so `@/i18n/navigation` can localize it safely. Leave `useSearchParams` on `next/navigation`, and keep the global `page-transition` exception untouched.

**Tech Stack:** Next.js 16 App Router, `next-intl` 4.8.3, Vitest source tests, ESLint, TypeScript.

---

### Task 1: Guard chunk-preview context router wiring

**Files:**
- Create: `web/i18n/chunk-preview-context-routing.source.test.ts`

**Step 1: Write the failing test**

Require:
- `web/components/chunk-preview/context.tsx` to import `useRouter` from `@/i18n/navigation`
- `web/components/chunk-preview/context.tsx` to keep `useSearchParams` on `next/navigation`
- `web/components/chunk-preview/context.tsx` to sync the `chunk` query param through the internal path `/chunk-preview`
- `web/components/chunk-preview/context.tsx` not to depend on `window.location.pathname`

**Step 2: Run test to verify it fails**

Run: `pnpm test i18n/chunk-preview-context-routing.source.test.ts`

Expected: FAIL because the context still imports `useRouter` from Next.js directly and still derives the replace target from `window.location.pathname`.

**Step 3: Write minimal implementation**

Switch the chunk-preview context to the shared locale-aware router helper and replace the pathname-dependent URL sync with the internal `/chunk-preview` route.

**Step 4: Run test to verify it passes**

Run: `pnpm test i18n/chunk-preview-context-routing.source.test.ts`

Expected: PASS.

### Task 2: Verify the chunk-preview context rollout does not regress prior next-intl slices

**Files:**
- Modify: `web/components/chunk-preview/context.tsx`

**Step 1: Run focused source tests**

Run:
- `pnpm test i18n/chunk-preview-context-routing.source.test.ts i18n/chunk-preview-router-routing.source.test.ts i18n/business-router-routing.source.test.ts i18n/shared-pathname-routing.source.test.ts i18n/static-route-routing.source.test.ts i18n/knowledge-routing.source.test.ts i18n/settings-groups-routing.source.test.ts i18n/dataset-detail-routing.source.test.ts components/navbar.source.test.ts components/command-menu.source.test.ts i18n/navigation.source.test.ts`

Expected: PASS.

**Step 2: Run type/lint verification**

Run:
- `pnpm exec eslint components/chunk-preview/context.tsx i18n/chunk-preview-context-routing.source.test.ts`
- `pnpm exec tsc --noEmit --pretty false`

Expected: PASS.

### Task 3: Land the chunk-preview context slice safely

**Files:**
- Modify: `.beads/issues.jsonl`

**Step 1: Update issue notes**

Append a note to `MimirQ-me4q` describing the chunk-preview context router migration and what still remains (intentional global-context and params/searchParams entry points that continue to use `next/navigation`).

**Step 2: Run build**

Run: `pnpm run build`

Expected: PASS with no new next-intl routing failures or bundle-budget regressions.

**Step 3: Commit and push**

Run:
- `git add ...`
- `git commit -m "Extend next-intl chunk preview context coverage"`
- `git pull --rebase`
- `bd sync`
- `git push`
- `git status -sb`

Expected: clean worktree and branch aligned with `origin/main`.
