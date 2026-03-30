# Next-Intl Task Center Messages Rollout Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move the shared Task Center UI copy into the next-intl message catalog so this surface no longer depends on hardcoded Chinese strings.

**Architecture:** Add a dedicated `TaskCenter` namespace to `web/i18n/messages/zh-CN.ts` and switch `web/components/task-center.tsx` to `useTranslations`, reusing `Common` keys where they already exist. Keep the component behavior unchanged and localize only labels, section headings, stage text, aria labels, titles, and toast/error strings.

**Tech Stack:** Next.js 16 App Router, `next-intl` 4.8.3, Vitest source tests, ESLint, TypeScript.

---

### Task 1: Guard Task Center message-catalog wiring

**Files:**
- Create: `web/lib/task-center-messages.source.test.ts`

**Step 1: Write the failing test**

Require:
- `web/components/task-center.tsx` to import `useTranslations` from `next-intl`
- `web/components/task-center.tsx` to call `useTranslations('TaskCenter')`
- `web/components/task-center.tsx` to source key labels such as the title, monitor button, section headings, and stage labels from translation lookups
- `web/i18n/messages/zh-CN.ts` to define a `TaskCenter` catalog section with the needed keys

**Step 2: Run test to verify it fails**

Run: `pnpm test lib/task-center-messages.source.test.ts`

Expected: FAIL because Task Center still hardcodes its strings.

**Step 3: Write minimal implementation**

Add the `TaskCenter` message section and switch the component to `useTranslations`, keeping behavior unchanged.

**Step 4: Run test to verify it passes**

Run: `pnpm test lib/task-center-messages.source.test.ts`

Expected: PASS.

### Task 2: Verify the Task Center message rollout does not regress existing next-intl coverage

**Files:**
- Modify: `web/components/task-center.tsx`
- Modify: `web/i18n/messages/zh-CN.ts`

**Step 1: Run focused source tests**

Run:
- `pnpm test lib/task-center-messages.source.test.ts lib/messages-rollout.source.test.ts i18n/chunk-preview-context-routing.source.test.ts i18n/chunk-preview-router-routing.source.test.ts i18n/business-router-routing.source.test.ts i18n/shared-pathname-routing.source.test.ts i18n/static-route-routing.source.test.ts i18n/knowledge-routing.source.test.ts i18n/settings-groups-routing.source.test.ts i18n/dataset-detail-routing.source.test.ts components/navbar.source.test.ts components/command-menu.source.test.ts i18n/navigation.source.test.ts`

Expected: PASS.

**Step 2: Run type/lint verification**

Run:
- `pnpm exec eslint components/task-center.tsx i18n/messages/zh-CN.ts lib/task-center-messages.source.test.ts`
- `pnpm exec tsc --noEmit --pretty false`

Expected: PASS.

### Task 3: Land the Task Center message slice safely

**Files:**
- Modify: `.beads/issues.jsonl`

**Step 1: Update issue notes**

Append a note to `MimirQ-me4q` describing the Task Center message-catalog migration and what still remains (broader message-catalog expansion across other hardcoded route surfaces).

**Step 2: Run build**

Run: `pnpm run build`

Expected: PASS with no new next-intl routing failures or bundle-budget regressions.

**Step 3: Commit and push**

Run:
- `git add ...`
- `git commit -m "Extend next-intl task center messages"`
- `git pull --rebase`
- `bd sync`
- `git push`
- `git status -sb`

Expected: clean worktree and branch aligned with `origin/main`.
