# Next-Intl Shared Pathname Rollout Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Normalize locale-aware pathname and link handling across shared UI helpers by switching the remaining shared pathname-driven components to the common `next-intl` navigation helper.

**Architecture:** Keep the behavior of the shared UI helpers unchanged. Replace `usePathname` imports from `next/navigation` with `@/i18n/navigation` in the shared pathname-driven components, and swap `next/link` to the locale-aware `Link` helper where those components generate navigable URLs.

**Tech Stack:** Next.js 16 App Router, `next-intl` 4.8.3, Vitest source tests, ESLint, TypeScript.

---

### Task 1: Guard shared locale-aware pathname wiring

**Files:**
- Create: `web/i18n/shared-pathname-routing.source.test.ts`

**Step 1: Write the failing test**

Require:
- `web/components/ui/breadcrumb.tsx` to import `Link` and `usePathname` from `@/i18n/navigation`
- `web/components/route-scroll-reset.tsx` to import `usePathname` from `@/i18n/navigation`
- `web/components/providers/web-vitals-reporter.tsx` to import `usePathname` from `@/i18n/navigation`
- `web/components/ui/fluid-cursor.tsx` to import `usePathname` from `@/i18n/navigation`
- `web/components/ui/ingestion-workflow-stepper.tsx` to import `Link` and `usePathname` from `@/i18n/navigation`
- `web/components/page-transition.tsx` to continue importing `usePathname` from `next/navigation` because `app/template.tsx` renders during `/_global-error` prerendering and the `next-intl` pathname helper is not available in that context

**Step 2: Run test to verify it fails**

Run: `pnpm test i18n/shared-pathname-routing.source.test.ts`

Expected: FAIL because the shared components still import path/link primitives from Next.js directly.

**Step 3: Write minimal implementation**

Switch the shared pathname-driven components to the shared locale-aware helper imports, but keep `web/components/page-transition.tsx` on `next/navigation` and document that exception in the source test.

**Step 4: Run test to verify it passes**

Run: `pnpm test i18n/shared-pathname-routing.source.test.ts`

Expected: PASS.

### Task 2: Verify the shared pathname rollout does not regress existing route guards

**Files:**
- Modify: `web/components/ui/breadcrumb.tsx`
- Modify: `web/components/route-scroll-reset.tsx`
- Modify: `web/components/page-transition.tsx`
- Modify: `web/components/providers/web-vitals-reporter.tsx`
- Modify: `web/components/ui/fluid-cursor.tsx`
- Modify: `web/components/ui/ingestion-workflow-stepper.tsx`

Note:
- `web/components/page-transition.tsx` is verified as an intentional exception rather than a migrated file, because switching it to `@/i18n/navigation` breaks `/_global-error` prerendering.

**Step 1: Run focused source tests**

Run:
- `pnpm test i18n/shared-pathname-routing.source.test.ts i18n/static-route-routing.source.test.ts i18n/knowledge-routing.source.test.ts i18n/settings-groups-routing.source.test.ts i18n/dataset-detail-routing.source.test.ts components/navbar.source.test.ts components/command-menu.source.test.ts i18n/navigation.source.test.ts`

Expected: PASS.

**Step 2: Run type/lint verification**

Run:
- `pnpm exec eslint components/ui/breadcrumb.tsx components/route-scroll-reset.tsx components/page-transition.tsx components/providers/web-vitals-reporter.tsx components/ui/fluid-cursor.tsx components/ui/ingestion-workflow-stepper.tsx i18n/shared-pathname-routing.source.test.ts`
- `pnpm exec tsc --noEmit --pretty false`

Expected: PASS.

### Task 3: Land the shared pathname slice safely

**Files:**
- Modify: `.beads/issues.jsonl`

**Step 1: Update issue notes**

Append a note to `MimirQ-me4q` describing the shared pathname/link helper migration, the `page-transition` global-error prerender exception, and what still remains (not-found/error entry points plus router-driven business components that still import `next/navigation` directly).

**Step 2: Run build**

Run: `pnpm run build`

Expected: PASS with no new next-intl routing failures or bundle-budget regressions.

**Step 3: Commit and push**

Run:
- `git add ...`
- `git commit -m "Extend next-intl shared pathname coverage"`
- `git pull --rebase`
- `bd sync`
- `git push`
- `git status -sb`

Expected: clean worktree and branch aligned with `origin/main`.
