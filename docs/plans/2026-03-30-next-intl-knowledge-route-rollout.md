# Next-Intl Knowledge Route Rollout Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Normalize locale-aware routing for the knowledge management flow by switching its remaining route transitions to the shared `next-intl` navigation helper and adding the missing locale wrappers for direct knowledge tools.

**Architecture:** Keep the knowledge workbench, feedback triage UI, and tool pages unchanged. Swap `useRouter` imports from `next/navigation` to `@/i18n/navigation` in the knowledge home/feedback entry files while leaving `useSearchParams` on `next/navigation` where required. Add thin `[locale]/knowledge/evidence` and `[locale]/knowledge/nebula` wrappers so locale-prefixed knowledge tool routes resolve cleanly.

**Tech Stack:** Next.js 16 App Router, `next-intl` 4.8.3, Vitest source tests, ESLint, TypeScript.

---

### Task 1: Guard locale-aware knowledge routing wiring

**Files:**
- Create: `web/i18n/knowledge-routing.source.test.ts`

**Step 1: Write the failing test**

Require:
- `web/app/knowledge/feedback/page.tsx` to import `useRouter` from `@/i18n/navigation`
- `web/components/knowledge/knowledge-page.tsx` to import `useRouter` from `@/i18n/navigation`
- `web/components/knowledge/knowledge-page.tsx` to keep `useSearchParams` on `next/navigation`
- locale wrappers to exist for:
  - `web/app/[locale]/knowledge/evidence/page.tsx`
  - `web/app/[locale]/knowledge/nebula/page.tsx`

**Step 2: Run test to verify it fails**

Run: `pnpm test i18n/knowledge-routing.source.test.ts`

Expected: FAIL because the knowledge pages still use `next/navigation` for `useRouter` and the locale wrappers do not exist yet.

**Step 3: Write minimal implementation**

Switch the knowledge feedback/home routing entry points to the shared locale-aware helper and add the two wrapper pages above.

**Step 4: Run test to verify it passes**

Run: `pnpm test i18n/knowledge-routing.source.test.ts`

Expected: PASS.

### Task 2: Verify the knowledge rollout does not regress existing route guards

**Files:**
- Modify: `web/app/knowledge/feedback/page.tsx`
- Modify: `web/components/knowledge/knowledge-page.tsx`

**Step 1: Run focused source tests**

Run:
- `pnpm test i18n/knowledge-routing.source.test.ts app/knowledge/feedback/page.source.test.ts app/knowledge/knowledge-page.entry.test.ts components/knowledge/knowledge-page.query-state.source.test.ts components/navbar.source.test.ts components/command-menu.source.test.ts i18n/navigation.source.test.ts`

Expected: PASS.

**Step 2: Run type/lint verification**

Run:
- `pnpm exec eslint app/knowledge/feedback/page.tsx components/knowledge/knowledge-page.tsx i18n/knowledge-routing.source.test.ts 'app/[locale]/knowledge/evidence/page.tsx' 'app/[locale]/knowledge/nebula/page.tsx'`
- `pnpm exec tsc --noEmit --pretty false`

Expected: PASS.

### Task 3: Land the knowledge slice safely

**Files:**
- Modify: `.beads/issues.jsonl`

**Step 1: Update issue notes**

Append a note to `MimirQ-me4q` describing the knowledge route migration and wrapper coverage, plus what still remains (not-found/error entry points, the last non-knowledge locale wrappers, and shared business components elsewhere that still import `next/navigation` directly).

**Step 2: Run build**

Run: `pnpm run build`

Expected: PASS with no new next-intl routing failures or bundle-budget regressions.

**Step 3: Commit and push**

Run:
- `git add ...`
- `git commit -m "Extend next-intl knowledge route coverage"`
- `git pull --rebase`
- `bd sync`
- `git push`
- `git status -sb`

Expected: clean worktree and branch aligned with `origin/main`.
