# Next-Intl Business Router Rollout Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Normalize locale-aware imperative navigation across the remaining low-risk business components that only need `useRouter` migration.

**Architecture:** Keep the route behavior unchanged and migrate only the locale-sensitive `useRouter` import from `next/navigation` to `@/i18n/navigation` in business components that push or replace already-localized routes. Leave `useParams` and `useSearchParams` on `next/navigation` where those hooks are still required, and avoid global entry points such as layouts, templates, and error surfaces.

**Tech Stack:** Next.js 16 App Router, `next-intl` 4.8.3, Vitest source tests, ESLint, TypeScript.

---

### Task 1: Guard business-router helper wiring

**Files:**
- Create: `web/i18n/business-router-routing.source.test.ts`

**Step 1: Write the failing test**

Require:
- `web/app/graph/use-graph-page-actions.ts` to import `useRouter` from `@/i18n/navigation`
- `web/components/chat/message-item.tsx` to import `useRouter` from `@/i18n/navigation`
- `web/components/data-governance-panel.tsx` to import `useRouter` from `@/i18n/navigation` while keeping `useSearchParams` on `next/navigation`
- `web/components/datasets/datasets-page.tsx` to import `useRouter` from `@/i18n/navigation`
- `web/components/governance-common-lines/governance-common-lines-page.tsx` to import `useRouter` from `@/i18n/navigation`
- `web/components/parsing/use-parsing-editor-actions.ts` to import `useRouter` from `@/i18n/navigation`
- `web/components/task-center.tsx` to import `useRouter` from `@/i18n/navigation`

**Step 2: Run test to verify it fails**

Run: `pnpm test i18n/business-router-routing.source.test.ts`

Expected: FAIL because these business components still import `useRouter` from Next.js directly.

**Step 3: Write minimal implementation**

Switch the targeted business components to the shared locale-aware router helper while preserving any `useSearchParams` imports from `next/navigation`.

**Step 4: Run test to verify it passes**

Run: `pnpm test i18n/business-router-routing.source.test.ts`

Expected: PASS.

### Task 2: Verify the business-router rollout does not regress prior next-intl slices

**Files:**
- Modify: `web/app/graph/use-graph-page-actions.ts`
- Modify: `web/components/chat/message-item.tsx`
- Modify: `web/components/data-governance-panel.tsx`
- Modify: `web/components/datasets/datasets-page.tsx`
- Modify: `web/components/governance-common-lines/governance-common-lines-page.tsx`
- Modify: `web/components/parsing/use-parsing-editor-actions.ts`
- Modify: `web/components/task-center.tsx`

**Step 1: Run focused source tests**

Run:
- `pnpm test i18n/business-router-routing.source.test.ts i18n/shared-pathname-routing.source.test.ts i18n/static-route-routing.source.test.ts i18n/knowledge-routing.source.test.ts i18n/settings-groups-routing.source.test.ts i18n/dataset-detail-routing.source.test.ts components/navbar.source.test.ts components/command-menu.source.test.ts i18n/navigation.source.test.ts`

Expected: PASS.

**Step 2: Run type/lint verification**

Run:
- `pnpm exec eslint app/graph/use-graph-page-actions.ts components/chat/message-item.tsx components/data-governance-panel.tsx components/datasets/datasets-page.tsx components/governance-common-lines/governance-common-lines-page.tsx components/parsing/use-parsing-editor-actions.ts components/task-center.tsx i18n/business-router-routing.source.test.ts`
- `pnpm exec tsc --noEmit --pretty false`

Expected: PASS.

### Task 3: Land the business-router slice safely

**Files:**
- Modify: `.beads/issues.jsonl`

**Step 1: Update issue notes**

Append a note to `MimirQ-me4q` describing the business-component `useRouter` migration and what still remains (not-found/error entry points plus chunk-preview/global-context surfaces and other components that still import `next/navigation` directly).

**Step 2: Run build**

Run: `pnpm run build`

Expected: PASS with no new next-intl routing failures or bundle-budget regressions.

**Step 3: Commit and push**

Run:
- `git add ...`
- `git commit -m "Extend next-intl business router coverage"`
- `git pull --rebase`
- `bd sync`
- `git push`
- `git status -sb`

Expected: clean worktree and branch aligned with `origin/main`.
