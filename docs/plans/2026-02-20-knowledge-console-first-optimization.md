# Knowledge Console-first Optimization Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Make `/knowledge` a management-console workbench: default list view, denser documents work surface, clearer import/add flows, and more actionable connector-runs monitoring.

**Architecture:** Keep `WorkbenchScaffold` (Left Scope, Main Work Surface, Right Inspector). Keep tabs (`documents` / `retrieval` / `settings`). Improve defaults, table affordances, destructive confirmations, and monitoring UX without introducing new animation systems or re-theming.

**Tech Stack:** Next.js (App Router), React 19, Tailwind CSS v4 (token-first), Radix primitives, TanStack Virtual, Vitest.

---

## Quality Gates
Run from repo root:
- `pnpm -C web -s lint`
- `pnpm -C web -s typecheck`
- `pnpm -C web -s test`
- `pnpm -C web -s ui-check`
- `pnpm -C web -s verify`

## Plan Notes
- Keep changes scoped to `web/components/knowledge/*` first.
- Follow baseline-ui: use `AlertDialog` for destructive actions; avoid new animations; no gradients.
- User preference: commit once after all tasks are done (plan will still include per-task `git add`, but actual execution may batch commits).

---

## Batch 1: Default View = List (URL + Initial State)

### Task 1: Change Knowledge Query Defaults to `list`
**Files:**
- Modify: `web/components/knowledge/use-knowledge-query-state.ts`
- Test: `web/components/knowledge/use-knowledge-query-state.test.ts`

**Steps:**
1. Update parse default `viewMode` to `'list'`.
2. Update serialize so `view` param is only emitted when `viewMode !== 'list'` (i.e. `grid`).
3. Update tests:
   - empty query parses to `viewMode: 'list'`
   - default serialization omits `view` when list.
4. Run: `pnpm -C web -s test -- use-knowledge-query-state.test.ts`

### Task 2: Align `KnowledgePage` Initial View State to `list`
**Files:**
- Modify: `web/components/knowledge/knowledge-page.tsx`

**Steps:**
1. Change `useState<ViewMode>('grid')` to `'list'` to avoid first-render flicker.
2. Run: `pnpm -C web -s typecheck`

---

## Batch 2: Documents Table (Console Density + Accessibility)

### Task 3: Sticky Table Header for List View
**Files:**
- Modify: `web/components/knowledge/knowledge-documents-panel.tsx`
- Test: Create `web/components/knowledge/knowledge-documents-panel.table-head.source.test.ts`

**Steps:**
1. Add a source test to assert list-table header uses sticky classes (no `h-screen`).
2. Make `th` sticky with `top-0` and a token background (`bg-background`), plus `z-10`.
3. Run: `pnpm -C web -s test -- knowledge-documents-panel.table-head.source.test.ts`

### Task 4: Make Row Actions Visible Without Hover (Touch + Keyboard)
**Files:**
- Modify: `web/components/knowledge/knowledge-documents-panel.tsx`
- Test: Create `web/components/knowledge/knowledge-documents-panel.row-actions.source.test.ts`

**Steps:**
1. Add a source test that asserts row actions are not hover-only (must include `group-focus-within:` or mobile-visible pattern).
2. Update action buttons to:
   - be visible on small screens (`opacity-100` default)
   - be hover/focus-within revealed on desktop (`md:opacity-0 md:group-hover:opacity-100 md:group-focus-within:opacity-100`)
3. Run: `pnpm -C web -s test -- knowledge-documents-panel.row-actions.source.test.ts`

### Task 5: Batch Delete Uses `AlertDialog` (Baseline UI)
**Files:**
- Modify: `web/components/knowledge/knowledge-documents-panel.tsx`
- Test: Create `web/components/knowledge/knowledge-documents-panel.batch-delete.source.test.ts`

**Steps:**
1. Write a source test that asserts `AlertDialog` is used for batch delete (and not `Dialog`).
2. Replace the batch delete confirmation `Dialog` with `AlertDialog` primitives from `web/components/ui/alert-dialog.tsx`.
3. Ensure buttons disable correctly while deleting.
4. Run: `pnpm -C web -s test -- knowledge-documents-panel.batch-delete.source.test.ts`

---

## Batch 3: Import/Add Flows (Inline Errors + Refresh-on-Success)

### Task 6: URL Import Dialog Inline Validation
**Files:**
- Modify: `web/components/knowledge/import/knowledge-url-import-dialog.tsx`
- Test: Create `web/components/knowledge/import/knowledge-url-import-dialog.validation.source.test.ts`

**Steps:**
1. Add local inline error state (URL required).
2. Display error message under URL input; keep toast for server errors.
3. Run: `pnpm -C web -s test -- knowledge-url-import-dialog.validation.source.test.ts`

### Task 7: Refresh Documents After URL Import Success
**Files:**
- Modify: `web/components/knowledge/knowledge-workbench-actions.tsx`
- Modify: `web/components/knowledge/import/knowledge-url-import-dialog.tsx`
- Test: Extend an existing source test or add `web/components/knowledge/knowledge-workbench-actions.refresh.source.test.ts`

**Steps:**
1. Add optional `onAfterImport` callback to URL import dialog.
2. Wire it from `KnowledgeWorkbenchActions` to call `loadDocuments()`.
3. Run: `pnpm -C web -s test -- knowledge-workbench-actions.refresh.source.test.ts`

---

## Batch 4: Monitoring (Connector Runs in Settings)

### Task 8: Fix Settings Empty-State Copy to Match `导入/新增`
**Files:**
- Modify: `web/components/knowledge/knowledge-settings-panel.tsx`
- Test: Create `web/components/knowledge/knowledge-settings-panel.copy.source.test.ts`

**Steps:**
1. Update empty text “可通过顶部…创建” to refer to `导入/新增`.
2. Run: `pnpm -C web -s test -- knowledge-settings-panel.copy.source.test.ts`

### Task 9: Add Simple Connector Runs Status Filter
**Files:**
- Modify: `web/components/knowledge/knowledge-page.tsx`
- Modify: `web/components/knowledge/knowledge-settings-panel.tsx`
- Test: Create `web/components/knowledge/knowledge-settings-panel.filter.source.test.ts`

**Steps:**
1. Add a UI filter (status) in settings panel: `all/pending/running/failed/completed/cancelled`.
2. Filter `connectorRuns` in render (client-side; no API changes).
3. Run: `pnpm -C web -s test -- knowledge-settings-panel.filter.source.test.ts`

---

## Batch 5: Verification

### Task 10: Run Web Verify
**Steps:**
1. Run: `pnpm -C web -s verify`
2. Fix any regressions with narrow changes + add guard tests when helpful.

