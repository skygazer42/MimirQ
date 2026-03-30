# Next-Intl Settings Groups Rollout Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Normalize locale-aware routing for the settings group management flow by switching its route transitions to the shared `next-intl` navigation helper and adding the missing locale wrapper for group detail pages.

**Architecture:** Keep the group-management UI and API behavior unchanged. Swap `useRouter` imports from `next/navigation` to `@/i18n/navigation` in the settings groups list/detail pages while leaving `useParams` on `next/navigation` where required. Add a thin `[locale]/settings/groups/[id]` wrapper so locale-prefixed group-detail navigation resolves cleanly.

**Tech Stack:** Next.js 16 App Router, `next-intl` 4.8.3, Vitest source tests, ESLint, TypeScript.

---

### Task 1: Guard locale-aware settings groups routing wiring

**Files:**
- Create: `web/i18n/settings-groups-routing.source.test.ts`

**Step 1: Write the failing test**

Require:
- `web/app/settings/groups/page.tsx` to import `useRouter` from `@/i18n/navigation`
- `web/app/settings/groups/[id]/page.tsx` to import `useRouter` from `@/i18n/navigation`
- `web/app/settings/groups/[id]/page.tsx` to keep `useParams` on `next/navigation`
- `web/app/[locale]/settings/groups/[id]/page.tsx` to exist and wrap the existing detail route

**Step 2: Run test to verify it fails**

Run: `pnpm test i18n/settings-groups-routing.source.test.ts`

Expected: FAIL because the settings groups pages still use `next/navigation` for `useRouter` and the locale detail wrapper does not exist yet.

**Step 3: Write minimal implementation**

Switch the settings groups pages to the shared locale-aware helper and add the wrapper page.

**Step 4: Run test to verify it passes**

Run: `pnpm test i18n/settings-groups-routing.source.test.ts`

Expected: PASS.

### Task 2: Verify the settings groups rollout does not regress existing route guards

**Files:**
- Modify: `web/app/settings/groups/page.tsx`
- Modify: `web/app/settings/groups/[id]/page.tsx`

**Step 1: Run focused source tests**

Run:
- `pnpm test i18n/settings-groups-routing.source.test.ts i18n/dataset-detail-routing.source.test.ts components/navbar.source.test.ts components/command-menu.source.test.ts i18n/navigation.source.test.ts`

Expected: PASS.

**Step 2: Run type/lint verification**

Run:
- `pnpm exec eslint app/settings/groups/page.tsx 'app/settings/groups/[id]/page.tsx' i18n/settings-groups-routing.source.test.ts 'app/[locale]/settings/groups/[id]/page.tsx'`
- `pnpm exec tsc --noEmit --pretty false`

Expected: PASS.

### Task 3: Land the settings groups slice safely

**Files:**
- Modify: `.beads/issues.jsonl`

**Step 1: Update issue notes**

Append a note to `MimirQ-me4q` describing the settings groups route migration and locale detail wrapper coverage, plus what still remains (not-found/error entry points, remaining locale wrappers outside settings groups, and non-settings pages/components still using `next/navigation` directly).

**Step 2: Run build**

Run: `pnpm run build`

Expected: PASS with no new next-intl routing failures or bundle-budget regressions.

**Step 3: Commit and push**

Run:
- `git add ...`
- `git commit -m "Extend next-intl settings groups coverage"`
- `git pull --rebase`
- `bd sync`
- `git push`
- `git status -sb`

Expected: clean worktree and branch aligned with `origin/main`.
