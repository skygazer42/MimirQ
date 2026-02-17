# Knowledge Workbench Deep Optimization (Wave 1) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Deeply optimize the Knowledge workbench (`/knowledge`) for “management console” usage (A): Left scope/navigation, Main virtualized document management, Right inspector. Fix scroll-container correctness for virtualization, add mobile scope/inspector panel dialogs, and enforce consistent workbench layout conventions. Then align `/chunk-preview` and `/parsing` to the same patterns and finish with verification + landing on `main`.

**Architecture:** Keep `AppFrame` as the global shell and `WorkbenchScaffold` as the workbench archetype. Introduce Knowledge-specific modules under `web/components/knowledge/*`:
- Hooks: `use-knowledge-scroll-container` (correct main-pane scroll element), `use-knowledge-query-state` (URL <-> UI state).
- Panels: `KnowledgeScopePanel` (left), `KnowledgeDocumentsPanel` (main), `KnowledgeInspector` (right), plus extraction modules for retrieval/settings tabs.

**Tech Stack:** Next.js (App Router), React 19, Tailwind CSS v4, Radix UI primitives, Zustand stores, TanStack Query, TanStack Virtual, Vitest.

---

## Conventions / Quality Gates

**Commands (run from repo root):**
- Web: `pnpm -C web -s lint`
- Web: `pnpm -C web -s typecheck`
- Web: `pnpm -C web -s test`
- Web: `pnpm -C web -s ui-check`
- All web checks: `pnpm -C web -s verify`

**Baseline UI constraints:**
- No window scrolling (internal scroll containers only).
- Respect safe-area insets for fixed/sticky UI.
- Avoid `h-screen`; prefer `h-dvh` and `min-h-0`.
- Avoid arbitrary z-index escalation.
- Prefer Radix primitives (Dialog/Popover/Select/Tabs) for keyboard/focus behavior.

**Testing style in this repo:**
- Prefer “source tests” that read component files and assert conventions (see existing `*.source.test.ts` patterns).
- Add behavior tests only when source tests cannot catch regressions.

---

## Knowledge Workbench (Primary)

### Task 1: Add `useKnowledgeScrollContainer` Hook (Main Pane Only)

**Files:**
- Create: `web/components/knowledge/use-knowledge-scroll-container.ts`
- Test: `web/components/knowledge/use-knowledge-scroll-container.source.test.ts`

**Step 1: Write failing test**
- Assert the hook:
  - Exports `useKnowledgeScrollContainer`
  - Uses a sentinel `ref` and `.closest('[data-page-scroll-container=\"true\"]')`
  - Does **not** use a global `document.querySelector('[data-page-scroll-container=\"true\"]')`

**Step 2: Run failing test**
- `pnpm -C web -s test -- use-knowledge-scroll-container.source.test.ts`

**Step 3: Implement minimal code**
- Implement a hook that returns:
  - `sentinelRef` (attach inside the main pane DOM subtree)
  - `scrollEl` (resolved via `.closest(...)` in an effect)

**Step 4: Run tests**
- `pnpm -C web -s test -- use-knowledge-scroll-container.source.test.ts`

**Step 5: Commit**
- `git add web/components/knowledge/use-knowledge-scroll-container.ts web/components/knowledge/use-knowledge-scroll-container.source.test.ts`
- `git commit -m "feat(knowledge): add main-pane scroll container hook"`

---

### Task 2: Bind Knowledge Virtualizers to the Main Pane Scroll Container

**Files:**
- Modify: `web/components/knowledge/knowledge-page.tsx`
- Test: `web/components/knowledge/knowledge-page.scroll-container.test.ts`

**Step 1: Write failing test**
- Source test assertions:
  - `knowledge-page.tsx` imports `useKnowledgeScrollContainer`
  - `knowledge-page.tsx` does not contain `document.querySelector<HTMLElement>('[data-page-scroll-container=\"true\"]')`

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-page.scroll-container.test.ts`

**Step 3: Implement minimal code**
- Add the sentinel element inside the main pane content (documents/retrieval/settings main area).
- Use `scrollEl` for TanStack Virtual `getScrollElement`.
- Keep fallback behavior safe when `scrollEl` is still `null`.

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-page.scroll-container.test.ts`

**Step 5: Commit**
- `git add web/components/knowledge/knowledge-page.tsx web/components/knowledge/knowledge-page.scroll-container.test.ts`
- `git commit -m "fix(knowledge): bind virtualization to main scroll container"`

---

### Task 3: Fix Tab-Switch Scroll Reset to Target the Main Pane Only

**Files:**
- Modify: `web/components/knowledge/knowledge-page.tsx`
- Test: `web/components/knowledge/knowledge-page.tab-scroll-reset.test.ts`

**Step 1: Write failing test**
- Assert tab-switch effect scrolls `scrollEl` (from the new hook) and does not use a global selector.

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-page.tab-scroll-reset.test.ts`

**Step 3: Implement minimal code**
- Replace any `document.querySelector(...)` based scroll reset with `scrollEl?.scrollTo(...)`.

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-page.tab-scroll-reset.test.ts`

**Step 5: Commit**
- `git add web/components/knowledge/knowledge-page.tsx web/components/knowledge/knowledge-page.tab-scroll-reset.test.ts`
- `git commit -m "fix(knowledge): reset main pane scroll on tab changes"`

---

### Task 4: Introduce `KnowledgeScopePanel` Skeleton (Left Scope/Navigation)

**Files:**
- Create: `web/components/knowledge/knowledge-scope-panel.tsx`
- Test: `web/components/knowledge/knowledge-scope-panel.source.test.ts`

**Step 1: Write failing test**
- Assert the module:
  - Exports `KnowledgeScopePanel`
  - Uses `WorkbenchPane`
  - Avoids `h-screen`

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-scope-panel.source.test.ts`

**Step 3: Implement minimal code**
- Implement a `WorkbenchPane`-wrapped panel with a header (e.g., “范围 / Scope”) and placeholder body.

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-scope-panel.source.test.ts`

**Step 5: Commit**
- `git add web/components/knowledge/knowledge-scope-panel.tsx web/components/knowledge/knowledge-scope-panel.source.test.ts`
- `git commit -m "feat(knowledge): add scope panel skeleton"`

---

### Task 5: Wire `KnowledgeScopePanel` Into `WorkbenchScaffold.leftPanel`

**Files:**
- Modify: `web/components/knowledge/knowledge-page.tsx`
- Test: `web/components/knowledge/knowledge-page.left-panel.scope.test.ts`

**Step 1: Write failing test**
- Assert `knowledge-page.tsx` renders `leftPanel={<KnowledgeScopePanel ... />}`.

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-page.left-panel.scope.test.ts`

**Step 3: Implement minimal code**
- Replace the current left panel content with `KnowledgeScopePanel`.
- Keep the existing right inspector intact.

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-page.left-panel.scope.test.ts`

**Step 5: Commit**
- `git add web/components/knowledge/knowledge-page.tsx web/components/knowledge/knowledge-page.left-panel.scope.test.ts`
- `git commit -m "refactor(knowledge): mount scope panel in left workbench pane"`

---

### Task 6: Move Dataset Selection Into `KnowledgeScopePanel`

**Files:**
- Modify: `web/components/knowledge/knowledge-page.tsx`
- Modify: `web/components/knowledge/knowledge-scope-panel.tsx`
- Test: `web/components/knowledge/knowledge-scope-panel.dataset.source.test.ts`

**Step 1: Write failing test**
- Assert scope panel includes a dataset selector control (source-level guard, not behavior-level).

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-scope-panel.dataset.source.test.ts`

**Step 3: Implement minimal code**
- Pass `datasets`, `datasetScope`, `setDatasetScope` into the panel.
- Move the dataset `<Select>` out of the main documents filters.

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-scope-panel.dataset.source.test.ts`

**Step 5: Commit**
- `git add web/components/knowledge/knowledge-page.tsx web/components/knowledge/knowledge-scope-panel.tsx web/components/knowledge/knowledge-scope-panel.dataset.source.test.ts`
- `git commit -m "refactor(knowledge): move dataset scope selector into left panel"`

---

### Task 7: Move Folder Tree (Dataset Folder Scope) Into `KnowledgeScopePanel`

**Files:**
- Modify: `web/components/knowledge/knowledge-page.tsx`
- Modify: `web/components/knowledge/knowledge-scope-panel.tsx`
- Test: `web/components/knowledge/knowledge-scope-panel.folder-tree.source.test.ts`

**Step 1: Write failing test**
- Assert scope panel renders `DatasetFolderTree` when a dataset is selected.

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-scope-panel.folder-tree.source.test.ts`

**Step 3: Implement minimal code**
- Remove the folder Popover from the main filters.
- Render `DatasetFolderTree` in the left panel body when `selectedDatasetId` exists.

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-scope-panel.folder-tree.source.test.ts`

**Step 5: Commit**
- `git add web/components/knowledge/knowledge-page.tsx web/components/knowledge/knowledge-scope-panel.tsx web/components/knowledge/knowledge-scope-panel.folder-tree.source.test.ts`
- `git commit -m "refactor(knowledge): make folder scope a persistent left navigation tree"`

---

### Task 8: Move Lifecycle Filter Into `KnowledgeScopePanel`

**Files:**
- Modify: `web/components/knowledge/knowledge-page.tsx`
- Modify: `web/components/knowledge/knowledge-scope-panel.tsx`
- Test: `web/components/knowledge/knowledge-scope-panel.lifecycle.source.test.ts`

**Step 1: Write failing test**
- Assert scope panel contains the lifecycle filter control.

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-scope-panel.lifecycle.source.test.ts`

**Step 3: Implement minimal code**
- Move lifecycle `<Select>` out of the main toolbar into the left panel.
- Ensure `DatasetFolderTree` still receives the lifecycle value.

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-scope-panel.lifecycle.source.test.ts`

**Step 5: Commit**
- `git add web/components/knowledge/knowledge-page.tsx web/components/knowledge/knowledge-scope-panel.tsx web/components/knowledge/knowledge-scope-panel.lifecycle.source.test.ts`
- `git commit -m "refactor(knowledge): move lifecycle filter into left scope panel"`

---

### Task 9: Move Status Filter (All/Ready/Processing/Failed/Quarantined) Into Left Scope Panel

**Files:**
- Modify: `web/components/knowledge/knowledge-page.tsx`
- Modify: `web/components/knowledge/knowledge-scope-panel.tsx`
- Test: `web/components/knowledge/knowledge-scope-panel.status.source.test.ts`

**Step 1: Write failing test**
- Assert scope panel owns the status filter (and main no longer does).

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-scope-panel.status.source.test.ts`

**Step 3: Implement minimal code**
- Move the status pill group into the left panel.
- Keep the counts (from doc stats) visible in scope panel.

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-scope-panel.status.source.test.ts`

**Step 5: Commit**
- `git add web/components/knowledge/knowledge-page.tsx web/components/knowledge/knowledge-scope-panel.tsx web/components/knowledge/knowledge-scope-panel.status.source.test.ts`
- `git commit -m "refactor(knowledge): move status filter into left scope panel"`

---

### Task 10: Simplify the Main Documents Toolbar (Search/Sort/View Only)

**Files:**
- Modify: `web/components/knowledge/knowledge-page.tsx`
- Test: `web/components/knowledge/knowledge-documents-toolbar.source.test.ts`

**Step 1: Write failing test**
- Assert main documents toolbar still includes `SearchInput` and sort controls, but does not include dataset/folder/lifecycle/status controls.

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-documents-toolbar.source.test.ts`

**Step 3: Implement minimal code**
- Keep:
  - Search input
  - Sort selector
  - View toggle
- Remove duplicated scope UI from main.

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-documents-toolbar.source.test.ts`

**Step 5: Commit**
- `git add web/components/knowledge/knowledge-page.tsx web/components/knowledge/knowledge-documents-toolbar.source.test.ts`
- `git commit -m "refactor(knowledge): keep scope in left panel; simplify main toolbar"`

---

### Task 11: Mobile Scope Panel Dialog (Left Panel on Small Screens)

**Files:**
- Modify: `web/components/knowledge/knowledge-page.tsx`
- Test: `web/components/knowledge/knowledge-page.mobile-scope-dialog.source.test.ts`

**Step 1: Write failing test**
- Assert `WorkbenchPanelDialog` is used to render `KnowledgeScopePanel` for mobile.

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-page.mobile-scope-dialog.source.test.ts`

**Step 3: Implement minimal code**
- Add state `scopeOpen`.
- Add a toolbar button visible on small screens (e.g., `lg:hidden`) to open.
- Render `<WorkbenchPanelDialog title="范围筛选">` with `KnowledgeScopePanel`.

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-page.mobile-scope-dialog.source.test.ts`

**Step 5: Commit**
- `git add web/components/knowledge/knowledge-page.tsx web/components/knowledge/knowledge-page.mobile-scope-dialog.source.test.ts`
- `git commit -m "feat(knowledge): add mobile scope panel dialog"`

---

### Task 12: Mobile Inspector Panel Dialog (Right Panel on Small Screens)

**Files:**
- Modify: `web/components/knowledge/knowledge-page.tsx`
- Test: `web/components/knowledge/knowledge-page.mobile-inspector-dialog.source.test.ts`

**Step 1: Write failing test**
- Assert `WorkbenchPanelDialog` is used to render `KnowledgeInspector` for mobile.

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-page.mobile-inspector-dialog.source.test.ts`

**Step 3: Implement minimal code**
- Add state `inspectorOpen`.
- Show a toolbar button on small screens when:
  - A selection exists, or
  - The active tab is `retrieval` (so preview is accessible).
- Render `<WorkbenchPanelDialog title="Inspector">` with `KnowledgeInspector`.

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-page.mobile-inspector-dialog.source.test.ts`

**Step 5: Commit**
- `git add web/components/knowledge/knowledge-page.tsx web/components/knowledge/knowledge-page.mobile-inspector-dialog.source.test.ts`
- `git commit -m "feat(knowledge): add mobile inspector panel dialog"`

---

### Task 13: Extract Retrieval Tab Into `KnowledgeRetrievalPanel`

**Files:**
- Create: `web/components/knowledge/knowledge-retrieval-panel.tsx`
- Modify: `web/components/knowledge/knowledge-page.tsx`
- Test: `web/components/knowledge/knowledge-retrieval-panel.source.test.ts`

**Step 1: Write failing test**
- Assert the module exists and exports `KnowledgeRetrievalPanel`.

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-retrieval-panel.source.test.ts`

**Step 3: Implement minimal code**
- Move the `activeTab === 'retrieval'` block into the module.
- Keep props minimal (dataset id, handlers, loading state).

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-retrieval-panel.source.test.ts`

**Step 5: Commit**
- `git add web/components/knowledge/knowledge-retrieval-panel.tsx web/components/knowledge/knowledge-page.tsx web/components/knowledge/knowledge-retrieval-panel.source.test.ts`
- `git commit -m "refactor(knowledge): extract retrieval tab panel module"`

---

### Task 14: Extract Settings Tab Into `KnowledgeSettingsPanel`

**Files:**
- Create: `web/components/knowledge/knowledge-settings-panel.tsx`
- Modify: `web/components/knowledge/knowledge-page.tsx`
- Test: `web/components/knowledge/knowledge-settings-panel.source.test.ts`

**Step 1: Write failing test**
- Assert the module exists and exports `KnowledgeSettingsPanel`.

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-settings-panel.source.test.ts`

**Step 3: Implement minimal code**
- Move the `activeTab === 'settings'` block into the module.

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-settings-panel.source.test.ts`

**Step 5: Commit**
- `git add web/components/knowledge/knowledge-settings-panel.tsx web/components/knowledge/knowledge-page.tsx web/components/knowledge/knowledge-settings-panel.source.test.ts`
- `git commit -m "refactor(knowledge): extract settings tab panel module"`

---

### Task 15: Extract Documents Tab Into `KnowledgeDocumentsPanel`

**Files:**
- Create: `web/components/knowledge/knowledge-documents-panel.tsx`
- Modify: `web/components/knowledge/knowledge-page.tsx`
- Test: `web/components/knowledge/knowledge-documents-panel.source.test.ts`

**Step 1: Write failing test**
- Assert the module exists and exports `KnowledgeDocumentsPanel`.

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-documents-panel.source.test.ts`

**Step 3: Implement minimal code**
- Move the `activeTab === 'documents'` block into the module.
- Pass in the virtualizer instance data rather than rebuilding it in multiple places.

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-documents-panel.source.test.ts`

**Step 5: Commit**
- `git add web/components/knowledge/knowledge-documents-panel.tsx web/components/knowledge/knowledge-page.tsx web/components/knowledge/knowledge-documents-panel.source.test.ts`
- `git commit -m "refactor(knowledge): extract documents tab panel module"`

---

### Task 16: Add `useKnowledgeQueryState` Hook (URL <-> UI State)

**Files:**
- Create: `web/components/knowledge/use-knowledge-query-state.ts`
- Test: `web/components/knowledge/use-knowledge-query-state.test.ts`

**Step 1: Write failing test**
- Add a unit test for parsing + serialization:
  - Given a query string, parse state (tab/view/q/status/lifecycle/dataset/folder/order_by/order_dir).
  - Given state, serialize back to a stable query string.

**Step 2: Run failing test**
- `pnpm -C web -s test -- use-knowledge-query-state.test.ts`

**Step 3: Implement minimal code**
- Implement pure helpers:
  - `parseKnowledgeQueryState(searchParams: URLSearchParams)`
  - `serializeKnowledgeQueryState(state): string`
- Keep it framework-agnostic to make it testable.

**Step 4: Run tests**
- `pnpm -C web -s test -- use-knowledge-query-state.test.ts`

**Step 5: Commit**
- `git add web/components/knowledge/use-knowledge-query-state.ts web/components/knowledge/use-knowledge-query-state.test.ts`
- `git commit -m "feat(knowledge): extract url query state helpers"`

---

### Task 17: Refactor KnowledgePage to Use `useKnowledgeQueryState`

**Files:**
- Modify: `web/components/knowledge/knowledge-page.tsx`
- Test: `web/components/knowledge/knowledge-page.query-state.source.test.ts`

**Step 1: Write failing test**
- Assert `knowledge-page.tsx` imports and uses `useKnowledgeQueryState` (or the parse/serialize helpers).

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-page.query-state.source.test.ts`

**Step 3: Implement minimal code**
- Replace inline URL init/sync effects with the new hook/helpers.
- Preserve current URL shape for backwards compatibility.

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-page.query-state.source.test.ts`

**Step 5: Commit**
- `git add web/components/knowledge/knowledge-page.tsx web/components/knowledge/knowledge-page.query-state.source.test.ts`
- `git commit -m "refactor(knowledge): centralize url query state handling"`

---

### Task 18: Strengthen `KnowledgeInspector` for Management Console Use

**Files:**
- Modify: `web/components/knowledge/knowledge-inspector.tsx`
- Test: `web/components/knowledge/knowledge-inspector.meta.source.test.ts`

**Step 1: Write failing test**
- Assert inspector uses `getFileTypeMeta` (or equivalent) to show a consistent file-type badge/icon for selected docs.

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-inspector.meta.source.test.ts`

**Step 3: Implement minimal code**
- Improve the single-document view:
  - show type badge (icon + label)
  - show dataset/folder if available (best-effort)

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-inspector.meta.source.test.ts`

**Step 5: Commit**
- `git add web/components/knowledge/knowledge-inspector.tsx web/components/knowledge/knowledge-inspector.meta.source.test.ts`
- `git commit -m "feat(knowledge): enhance inspector metadata blocks"`

---

## Chunk Preview Alignment (Secondary)

### Task 19: Add Guard Test Requiring WorkbenchScaffold for Chunk Preview

**Files:**
- Test: `web/components/chunk-preview/components/workbench/workbench.scaffold.source.test.ts`

**Step 1: Write failing test**
- Source test: assert chunk-preview `Workbench` includes `WorkbenchScaffold`.

**Step 2: Run failing test**
- `pnpm -C web -s test -- workbench.scaffold.source.test.ts`

**Step 3: Implement minimal fix**
- None yet (will fail until Task 20).

**Step 4: Commit**
- Commit the failing test only after implementing Task 20 (keep repo green).

---

### Task 20: Refactor Chunk Preview Workbench to Use `WorkbenchScaffold`

**Files:**
- Modify: `web/components/chunk-preview/components/workbench/index.tsx`
- Modify: `web/components/chunk-preview/components/workbench/top-bar.tsx` (as needed)
- Modify: `web/components/chunk-preview/components/workbench/sidebar.tsx` (as needed)
- Test: `web/components/chunk-preview/components/workbench/workbench.scaffold.source.test.ts`

**Step 1: Implement the refactor**
- Replace the custom header + pipeline wrapper with:
  - `WorkbenchScaffold` header (title/icon/actions)
  - `pipelineRail={<PipelineRail />}`
  - `leftPanel` for settings (desktop)
  - `mainPanel` for original/chunks

**Step 2: Run tests**
- `pnpm -C web -s test -- chunk-preview/components/workbench/workbench.scaffold.source.test.ts`

**Step 3: Commit**
- `git add web/components/chunk-preview/components/workbench/index.tsx web/components/chunk-preview/components/workbench/workbench.scaffold.source.test.ts`
- `git commit -m "refactor(chunk-preview): adopt WorkbenchScaffold layout"`

---

### Task 21: Move TopBar Controls Into WorkbenchScaffold `actions` / `toolbar`

**Files:**
- Modify: `web/components/chunk-preview/components/workbench/top-bar.tsx`
- Modify: `web/components/chunk-preview/components/workbench/index.tsx`
- Test: `web/components/chunk-preview/components/workbench/workbench.toolbar.source.test.ts`

**Step 1: Write failing test**
- Assert TopBar is not rendered as a separate full-width bar when WorkbenchScaffold is used.

**Step 2: Run failing test**
- `pnpm -C web -s test -- workbench.toolbar.source.test.ts`

**Step 3: Implement minimal code**
- Mount the core controls into WorkbenchScaffold slots.

**Step 4: Run tests**
- `pnpm -C web -s test -- workbench.toolbar.source.test.ts`

**Step 5: Commit**
- `git add web/components/chunk-preview/components/workbench/index.tsx web/components/chunk-preview/components/workbench/top-bar.tsx web/components/chunk-preview/components/workbench/workbench.toolbar.source.test.ts`
- `git commit -m "refactor(chunk-preview): normalize toolbar controls"`

---

### Task 22: Normalize Mobile Settings Panel Entry Point

**Files:**
- Modify: `web/components/chunk-preview/components/workbench/index.tsx`
- Test: `web/components/chunk-preview/components/workbench/workbench.mobile-dialog.source.test.ts`

**Step 1: Write failing test**
- Assert `WorkbenchPanelDialog` is the mobile settings mechanism and is reachable from a toolbar/action button.

**Step 2: Run failing test**
- `pnpm -C web -s test -- workbench.mobile-dialog.source.test.ts`

**Step 3: Implement minimal code**
- Ensure the open/close state is driven from an explicit control in the header/toolbar.

**Step 4: Run tests**
- `pnpm -C web -s test -- workbench.mobile-dialog.source.test.ts`

**Step 5: Commit**
- `git add web/components/chunk-preview/components/workbench/index.tsx web/components/chunk-preview/components/workbench/workbench.mobile-dialog.source.test.ts`
- `git commit -m "feat(chunk-preview): add explicit mobile settings dialog trigger"`

---

### Task 23: Ensure Chunk Preview Main Surface Shrinks Correctly (`min-w-0`, `min-h-0`)

**Files:**
- Modify: `web/components/chunk-preview/components/workbench/index.tsx`
- Test: `web/components/chunk-preview/components/workbench/workbench.shrink.source.test.ts`

**Step 1: Write failing test**
- Source test asserts main surface includes `min-w-0` and `min-h-0` in the correct containers.

**Step 2: Run failing test**
- `pnpm -C web -s test -- workbench.shrink.source.test.ts`

**Step 3: Implement minimal code**
- Add missing shrink classes to the correct wrappers.

**Step 4: Run tests**
- `pnpm -C web -s test -- workbench.shrink.source.test.ts`

**Step 5: Commit**
- `git add web/components/chunk-preview/components/workbench/index.tsx web/components/chunk-preview/components/workbench/workbench.shrink.source.test.ts`
- `git commit -m "fix(chunk-preview): enforce shrink-safe main surface"`

---

### Task 24: Run Targeted Web Tests for Chunk Preview

**Files:**
- None (verification)

**Step 1: Run**
- `pnpm -C web -s test -- chunk-preview`

**Step 2: Fix any failures**
- Keep fixes narrow.

**Step 3: Commit**
- Commit any required fixes with a narrow message.

---

## Parsing + Global Polish (Tertiary)

### Task 25: Parsing Mobile Queue Panel Dialog (Scope/Queue on Small Screens)

**Files:**
- Modify: `web/components/parsing/parsing-page.tsx`
- Test: `web/components/parsing/parsing-page.mobile-queue-dialog.source.test.ts`

**Step 1: Write failing test**
- Assert parsing page uses `WorkbenchPanelDialog` for the queue panel on small screens.

**Step 2: Run failing test**
- `pnpm -C web -s test -- parsing-page.mobile-queue-dialog.source.test.ts`

**Step 3: Implement minimal code**
- Add a small-screen trigger button in the header/toolbar.
- Mount the queue/tree UI into a dialog for small screens.

**Step 4: Run tests**
- `pnpm -C web -s test -- parsing-page.mobile-queue-dialog.source.test.ts`

**Step 5: Commit**
- `git add web/components/parsing/parsing-page.tsx web/components/parsing/parsing-page.mobile-queue-dialog.source.test.ts`
- `git commit -m "feat(parsing): add mobile queue panel dialog"`

---

### Task 26: Parsing Mobile Inspector Dialog (Blocks/Markdown Controls)

**Files:**
- Modify: `web/components/parsing/parsing-page.tsx`
- Test: `web/components/parsing/parsing-page.mobile-inspector-dialog.source.test.ts`

**Step 1: Write failing test**
- Assert parsing page exposes right-side controls via a mobile dialog.

**Step 2: Run failing test**
- `pnpm -C web -s test -- parsing-page.mobile-inspector-dialog.source.test.ts`

**Step 3: Implement minimal code**
- Add a trigger button and mount the inspector UI into `WorkbenchPanelDialog`.

**Step 4: Run tests**
- `pnpm -C web -s test -- parsing-page.mobile-inspector-dialog.source.test.ts`

**Step 5: Commit**
- `git add web/components/parsing/parsing-page.tsx web/components/parsing/parsing-page.mobile-inspector-dialog.source.test.ts`
- `git commit -m "feat(parsing): add mobile inspector dialog"`

---

### Task 27: Global Consistency Pass (Narrow)

**Files:**
- Modify: `web/components/workbench/workbench-scaffold.tsx` (only if needed)
- Modify: `web/components/ui/page-toolbar.tsx` (only if needed)

**Step 1: Identify inconsistencies**
- Spacing mismatches between Knowledge/Chunk Preview/Parsing.
- Safe-area or sticky header issues.

**Step 2: Implement minimal fixes**
- Prefer fixing call sites over adding exceptions.

**Step 3: Verify**
- `pnpm -C web -s test`

**Step 4: Commit**
- `git add <files>`
- `git commit -m \"refactor(ui): normalize workbench toolbar/padding\"`

---

## QA + Issue Tracking + Landing

### Task 28: Run Full Web Verify Gate

**Files:**
- None (verification)

**Step 1: Run**
- `pnpm -C web -s verify`

**Step 2: Fix any failures**
- Keep fixes small; add source tests when regressions are likely.

**Step 3: Commit**
- If fixes were required: commit with a narrow message.

---

### Task 29: Update bd Issue + Sync

**Files:**
- Modify: `.beads/issues.jsonl` (via `bd sync`)

**Step 1: Update issue**
- `bd update MimirQ-96g --append-notes \"Completed wave 1: knowledge IA + chunk-preview/parsing alignment + verify.\"`

**Step 2: Sync beads**
- `bd sync`

**Step 3: Commit**
- `git add .beads/issues.jsonl`
- `git commit -m \"bd sync\"`

---

### Task 30: Land the Plane (Merge to main + Push)

**Step 1: Rebase main**
- From main worktree: `git pull --rebase`

**Step 2: Merge fast-forward**
- `git merge --ff-only knowledge-workbench-opt`

**Step 3: Push**
- `git push`

**Step 4: Verify clean**
- `git status` must show up to date with origin.

