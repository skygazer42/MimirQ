# Next-Intl Navigation Rollout Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Normalize locale-aware client navigation for the first next-intl rollout slice by introducing shared navigation helpers and extending locale wrappers to the pages reached from the already-localized home/history surfaces.

**Architecture:** Add `web/i18n/navigation.ts` via `next-intl/navigation`, switch the existing locale-aware client components to consume `useRouter` from that helper, and add thin `[locale]` page wrappers for `knowledge` and `evaluations` so the new localized router has matching route targets. Keep the rest of the app tree unchanged for now.

**Tech Stack:** Next.js 16 App Router, next-intl 4.8.3, Vitest source tests, ESLint, TypeScript.

---

### Task 1: Guard locale-aware navigation wiring

**Files:**
- Create: `web/i18n/navigation.source.test.ts`

**Step 1: Write the failing test**

Require:
- `web/i18n/navigation.ts` to use `createNavigation` with `routing`
- `web/components/chat-area.tsx` to import `useRouter` from `@/i18n/navigation`
- `web/components/chat-page-client.tsx` to import `useRouter` from `@/i18n/navigation`
- `web/app/history/page-client.tsx` to import `useRouter` from `@/i18n/navigation`
- `web/app/[locale]/knowledge/page.tsx` and `web/app/[locale]/evaluations/page.tsx` to wrap the existing pages

**Step 2: Run test to verify it fails**

Run: `pnpm test i18n/navigation.source.test.ts`

Expected: FAIL because the helper and wrappers do not exist yet.

**Step 3: Write minimal implementation**

Add the navigation helper and locale wrappers, then switch the three guarded components to the helper router.

**Step 4: Run test to verify it passes**

Run: `pnpm test i18n/navigation.source.test.ts`

Expected: PASS.

### Task 2: Verify the helper does not regress existing route behavior

**Files:**
- Modify: `web/components/chat/slash-menu.source.test.ts` (only if needed)

**Step 1: Run the focused source tests**

Run:
- `pnpm test i18n/navigation.source.test.ts components/chat/slash-menu.source.test.ts app/history/page.source.test.ts app/history/page.empty-state.test.ts`

Expected: Existing route behavior guards remain green.

**Step 2: Run type/lint verification**

Run:
- `pnpm exec eslint i18n/navigation.ts 'app/[locale]/knowledge/page.tsx' 'app/[locale]/evaluations/page.tsx' components/chat-area.tsx components/chat-page-client.tsx app/history/page-client.tsx`
- `pnpm exec tsc --noEmit --pretty false`

Expected: PASS.

### Task 3: Land the slice safely

**Files:**
- Modify: `.beads/issues.jsonl`

**Step 1: Update issue notes**

Append a note to `MimirQ-me4q` describing the new helper and wrapper coverage, plus what still remains (`command-menu`, `navbar`, route-link hotspots outside the first localized surfaces).

**Step 2: Run build**

Run: `pnpm run build`

Expected: PASS with no new next-intl routing failures.

**Step 3: Commit and push**

Run:
- `git add ...`
- `git commit -m "Extend next-intl locale-aware navigation"`
- `git pull --rebase`
- `bd sync`
- `git push`
- `git status -sb`

Expected: clean worktree and branch aligned with `origin/main`.
