# Next-Intl Chunk Preview Router Rollout Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Normalize locale-aware imperative navigation in the remaining low-risk chunk-preview entry actions.

**Architecture:** Keep chunk-preview behavior unchanged and migrate only the `useRouter` imports in the entry-action components that push users into already-localized routes such as `/` and `/data-governance`. Leave `web/components/chunk-preview/context.tsx` alone for now because its pathname-sync `router.replace` flow needs separate evidence-driven handling.

**Tech Stack:** Next.js 16 App Router, `next-intl` 4.8.3, Vitest source tests, ESLint, TypeScript.

---

### Task 1: Guard chunk-preview router helper wiring

**Files:**
- Create: `web/i18n/chunk-preview-router-routing.source.test.ts`

**Step 1: Write the failing test**

Require:
- `web/components/chunk-preview/components/ingestion-preview-details-dialog.tsx` to import `useRouter` from `@/i18n/navigation`
- `web/components/chunk-preview/components/workbench/top-bar.tsx` to import `useRouter` from `@/i18n/navigation`

**Step 2: Run test to verify it fails**

Run: `pnpm test i18n/chunk-preview-router-routing.source.test.ts`

Expected: FAIL because these chunk-preview entry-action components still import `useRouter` from Next.js directly.

**Step 3: Write minimal implementation**

Switch the targeted chunk-preview entry-action components to the shared locale-aware router helper.

**Step 4: Run test to verify it passes**

Run: `pnpm test i18n/chunk-preview-router-routing.source.test.ts`

Expected: PASS.

### Task 2: Verify the chunk-preview entry-action rollout does not regress prior next-intl slices

**Files:**
- Modify: `web/components/chunk-preview/components/ingestion-preview-details-dialog.tsx`
- Modify: `web/components/chunk-preview/components/workbench/top-bar.tsx`

**Step 1: Run focused source tests**

Run:
- `pnpm test i18n/chunk-preview-router-routing.source.test.ts i18n/business-router-routing.source.test.ts i18n/shared-pathname-routing.source.test.ts i18n/static-route-routing.source.test.ts i18n/knowledge-routing.source.test.ts i18n/settings-groups-routing.source.test.ts i18n/dataset-detail-routing.source.test.ts components/navbar.source.test.ts components/command-menu.source.test.ts i18n/navigation.source.test.ts`

Expected: PASS.

**Step 2: Run type/lint verification**

Run:
- `pnpm exec eslint components/chunk-preview/components/ingestion-preview-details-dialog.tsx components/chunk-preview/components/workbench/top-bar.tsx i18n/chunk-preview-router-routing.source.test.ts`
- `pnpm exec tsc --noEmit --pretty false`

Expected: PASS.

### Task 3: Land the chunk-preview entry-action slice safely

**Files:**
- Modify: `.beads/issues.jsonl`

**Step 1: Update issue notes**

Append a note to `MimirQ-me4q` describing the chunk-preview entry-action `useRouter` migration and what still remains (chunk-preview context pathname-sync handling plus intentional global-context and params/searchParams entry points).

**Step 2: Run build**

Run: `pnpm run build`

Expected: PASS with no new next-intl routing failures or bundle-budget regressions.

**Step 3: Commit and push**

Run:
- `git add ...`
- `git commit -m "Extend next-intl chunk preview router coverage"`
- `git pull --rebase`
- `bd sync`
- `git push`
- `git status -sb`

Expected: clean worktree and branch aligned with `origin/main`.
