# Next-Intl Static Route Rollout Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Finish the remaining locale wrapper gaps for static route entry points by making the singular evaluation redirect locale-aware and adding locale wrappers for the leftover static pages.

**Architecture:** Keep the existing evaluation and logos preview surfaces unchanged. Replace the singular `/evaluation` redirect with the shared `next-intl` redirect helper, add a locale-specific `/[locale]/evaluation` redirect page, and add a thin `[locale]/logos-preview` wrapper so all remaining static entry points resolve cleanly under localized navigation.

**Tech Stack:** Next.js 16 App Router, `next-intl` 4.8.3, Vitest source tests, ESLint, TypeScript.

---

### Task 1: Guard locale-aware static route wiring

**Files:**
- Create: `web/i18n/static-route-routing.source.test.ts`

**Step 1: Write the failing test**

Require:
- `web/app/evaluation/page.tsx` to import `redirect` from `@/i18n/navigation`
- `web/app/evaluation/page.tsx` to use `routing.defaultLocale` when redirecting to `/evaluations`
- `web/app/[locale]/evaluation/page.tsx` to exist and redirect to `/evaluations` with the route locale
- `web/app/[locale]/logos-preview/page.tsx` to exist and wrap the existing route

**Step 2: Run test to verify it fails**

Run: `pnpm test i18n/static-route-routing.source.test.ts`

Expected: FAIL because the evaluation redirect still uses `next/navigation` and the two locale wrappers do not exist yet.

**Step 3: Write minimal implementation**

Switch the singular evaluation redirect to the shared locale-aware helper and add the two locale route entries above.

**Step 4: Run test to verify it passes**

Run: `pnpm test i18n/static-route-routing.source.test.ts`

Expected: PASS.

### Task 2: Verify the static route rollout does not regress existing route guards

**Files:**
- Modify: `web/app/evaluation/page.tsx`

**Step 1: Run focused source tests**

Run:
- `pnpm test i18n/static-route-routing.source.test.ts i18n/knowledge-routing.source.test.ts i18n/settings-groups-routing.source.test.ts i18n/dataset-detail-routing.source.test.ts components/navbar.source.test.ts i18n/navigation.source.test.ts`

Expected: PASS.

**Step 2: Run type/lint verification**

Run:
- `pnpm exec eslint app/evaluation/page.tsx i18n/static-route-routing.source.test.ts 'app/[locale]/evaluation/page.tsx' 'app/[locale]/logos-preview/page.tsx'`
- `pnpm exec tsc --noEmit --pretty false`

Expected: PASS.

### Task 3: Land the static route slice safely

**Files:**
- Modify: `.beads/issues.jsonl`

**Step 1: Update issue notes**

Append a note to `MimirQ-me4q` describing the evaluation/logos locale route coverage and what still remains (not-found/error entry points plus shared components that still import `next/navigation` directly).

**Step 2: Run build**

Run: `pnpm run build`

Expected: PASS with no new next-intl routing failures or bundle-budget regressions.

**Step 3: Commit and push**

Run:
- `git add ...`
- `git commit -m "Extend next-intl static route coverage"`
- `git pull --rebase`
- `bd sync`
- `git push`
- `git status -sb`

Expected: clean worktree and branch aligned with `origin/main`.
