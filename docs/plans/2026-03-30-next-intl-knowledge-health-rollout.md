# Next-Intl Knowledge Health Rollout Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Normalize locale-aware navigation for the knowledge health flow by switching its links/router usage to the shared `next-intl` helper and adding the locale wrapper for the health route.

**Architecture:** Keep the knowledge document list and document health UI unchanged. Swap `next/link` and `next/navigation` usage in the knowledge health entry points to `@/i18n/navigation`, then add a thin `[locale]/knowledge/[id]/health` wrapper so locale-prefixed health links resolve correctly.

**Tech Stack:** Next.js 16 App Router, `next-intl` 4.8.3, Vitest source tests, ESLint, TypeScript.

---

### Task 1: Guard locale-aware knowledge health wiring

**Files:**
- Create: `web/i18n/knowledge-health-routing.source.test.ts`

**Step 1: Write the failing test**

Require:
- `web/components/knowledge/document-health-page.tsx` to import `useRouter` from `@/i18n/navigation`
- `web/components/knowledge/knowledge-documents-panel.tsx` to import `Link` from `@/i18n/navigation`
- `web/app/[locale]/knowledge/[id]/health/page.tsx` to exist and wrap the existing route

**Step 2: Run test to verify it fails**

Run: `pnpm test i18n/knowledge-health-routing.source.test.ts`

Expected: FAIL because the files still use Next.js routing primitives and the locale wrapper does not exist yet.

**Step 3: Write minimal implementation**

Switch the two knowledge health entry points to the shared locale-aware helper and add the wrapper page.

**Step 4: Run test to verify it passes**

Run: `pnpm test i18n/knowledge-health-routing.source.test.ts`

Expected: PASS.

### Task 2: Verify the knowledge health rollout does not regress existing route guards

**Files:**
- Modify: `web/components/knowledge/document-health-page.tsx`
- Modify: `web/components/knowledge/knowledge-documents-panel.tsx`

**Step 1: Run focused source tests**

Run:
- `pnpm test i18n/knowledge-health-routing.source.test.ts components/knowledge/document-health-page.source.test.ts components/knowledge/knowledge-documents-panel.document-health.source.test.ts components/navbar.source.test.ts components/command-menu.source.test.ts`

Expected: PASS.

**Step 2: Run type/lint verification**

Run:
- `pnpm exec eslint components/knowledge/document-health-page.tsx components/knowledge/knowledge-documents-panel.tsx i18n/knowledge-health-routing.source.test.ts 'app/[locale]/knowledge/[id]/health/page.tsx'`
- `pnpm exec tsc --noEmit --pretty false`

Expected: PASS.

### Task 3: Land the knowledge health slice safely

**Files:**
- Modify: `.beads/issues.jsonl`

**Step 1: Update issue notes**

Append a note to `MimirQ-me4q` describing the knowledge health flow migration and wrapper coverage, plus what still remains (not-found/error entry points, broader message catalogs, deeper dataset detail routes).

**Step 2: Run build**

Run: `pnpm run build`

Expected: PASS with no new next-intl routing failures or bundle-budget regressions.

**Step 3: Commit and push**

Run:
- `git add ...`
- `git commit -m "Extend next-intl knowledge health coverage"`
- `git pull --rebase`
- `bd sync`
- `git push`
- `git status -sb`

Expected: clean worktree and branch aligned with `origin/main`.
