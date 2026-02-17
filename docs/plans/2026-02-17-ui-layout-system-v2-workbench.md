# UI Layout System v2 + Workbench Scaffold Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Unify the app into a consistent mid-density workbench layout by introducing `WorkbenchScaffold` primitives and migrating core/workbench pages to use them.

**Architecture:** Keep `AppFrame` as the global shell and `PageScaffold` for standard pages. Introduce a new `WorkbenchScaffold` archetype (header/pipeline rail/toolbar + left/main/right panes with internal scroll). Refactor large pages into modular components under `web/components/*`.

**Tech Stack:** Next.js (App Router), React 19, Tailwind CSS v4, Radix UI primitives, Zustand stores, TanStack Query, Vitest.

---

## Conventions / Quality Gates

**Commands (run from repo root):**
- Web: `pnpm -C web -s lint`
- Web: `pnpm -C web -s typecheck`
- Web: `pnpm -C web -s test`
- Web: `pnpm -C web -s ui-check`
- All web checks: `pnpm -C web -s verify`

**Baseline UI constraints:**
- No new animations (unless explicitly requested); keep motion to transform/opacity.
- Avoid gradients/glow.
- Avoid `h-screen`; use `h-dvh`.
- Avoid arbitrary z-index classes.
- Use Radix primitives (Dialog/Popover/Tabs/etc) for keyboard/focus behavior.

**Testing style in this repo:**
- Many UI tests are “source tests” that read component files and assert conventions (see `web/components/ui/search-input.clear-button.test.ts`). Prefer this approach for layout primitives.

---

### Task 1: Create Workbench Directory + Barrel Export

**Files:**
- Create: `web/components/workbench/index.ts`

**Step 1: Write failing test**
- Create: `web/components/workbench/workbench.index.test.ts`
- Assert the barrel exports `WorkbenchScaffold` once implemented.

**Step 2: Run test to verify it fails**
- Run: `pnpm -C web -s test -- workbench.index.test.ts`
- Expected: FAIL (module/file missing)

**Step 3: Implement minimal code**
- Add `index.ts` exporting placeholders (or nothing until Task 2).

**Step 4: Run test to verify it passes**
- Run: `pnpm -C web -s test -- workbench.index.test.ts`

**Step 5: Commit**
- `git add web/components/workbench/index.ts web/components/workbench/workbench.index.test.ts`
- `git commit -m "test(ui): add workbench barrel guard"`

---

### Task 2: Implement `WorkbenchScaffold` Skeleton (Header/Toolbar/Body)

**Files:**
- Create: `web/components/workbench/workbench-scaffold.tsx`
- Modify: `web/components/workbench/index.ts`
- Test: `web/components/workbench/workbench-scaffold.source.test.ts`

**Step 1: Write failing test**
- The test should read `workbench-scaffold.tsx` and assert:
  - Uses `min-h-0` and `overflow-hidden` on the outer containers.
  - Uses internal scroll containers (at least one `overflow-y-auto`).
  - Does not use `h-screen`.

**Step 2: Run test to verify it fails**
- Run: `pnpm -C web -s test -- workbench-scaffold.source.test.ts`

**Step 3: Implement minimal code**
- Implement a typed component with slots:
  - `title`, `icon`, `description`, `actions`
  - `pipelineRail?`, `toolbar?`
  - `leftPanel?`, `mainPanel`, `rightPanel?`
- Use existing primitives where possible:
  - `PageHeader` for header
  - `PageHeaderBar` for sticky toolbar wrapper (optional)
  - `PageContainer` for max width control

**Step 4: Run test to verify it passes**
- Run: `pnpm -C web -s test -- workbench-scaffold.source.test.ts`

**Step 5: Commit**
- `git add web/components/workbench/workbench-scaffold.tsx web/components/workbench/index.ts web/components/workbench/workbench-scaffold.source.test.ts`
- `git commit -m "feat(ui): add WorkbenchScaffold primitive"`

---

### Task 3: Add Pane Primitives (`WorkbenchPane`, `PaneHeader`, `PaneBody`)

**Files:**
- Create: `web/components/workbench/workbench-pane.tsx`
- Modify: `web/components/workbench/index.ts`
- Test: `web/components/workbench/workbench-pane.source.test.ts`

**Step 1: Write failing test**
- Assert `WorkbenchPane` uses a consistent structure:
  - outer: `min-h-0 overflow-hidden`
  - body scroll: `overflow-y-auto` + `overscroll-contain`
  - header: supports sticky within pane when requested

**Step 2: Run failing test**
- `pnpm -C web -s test -- workbench-pane.source.test.ts`

**Step 3: Implement minimal code**
- `WorkbenchPane` should accept `header` and `children`.
- `WorkbenchPaneBody` should optionally set `data-page-scroll-container="true"` (see Task 5).

**Step 4: Run tests**
- `pnpm -C web -s test -- workbench-pane.source.test.ts`

**Step 5: Commit**
- `git add web/components/workbench/workbench-pane.tsx web/components/workbench/index.ts web/components/workbench/workbench-pane.source.test.ts`
- `git commit -m "feat(ui): add workbench pane primitives"`

---

### Task 4: Add `PipelineRail` Wrapper Around `IngestionWorkflowStepper`

**Files:**
- Create: `web/components/workbench/pipeline-rail.tsx`
- Modify: `web/components/workbench/index.ts`
- Test: `web/components/workbench/pipeline-rail.source.test.ts`

**Step 1: Write failing test**
- Assert the component renders `IngestionWorkflowStepper` and provides consistent padding + border separation.

**Step 2: Run test**
- `pnpm -C web -s test -- pipeline-rail.source.test.ts`

**Step 3: Implement minimal code**
- Wrap `IngestionWorkflowStepper` in a `Panel` or a thin bordered row (avoid heavy blur).

**Step 4: Run tests**
- `pnpm -C web -s test -- pipeline-rail.source.test.ts`

**Step 5: Commit**
- `git add web/components/workbench/pipeline-rail.tsx web/components/workbench/index.ts web/components/workbench/pipeline-rail.source.test.ts`
- `git commit -m "feat(ui): add pipeline rail wrapper"`

---

### Task 5: Fix Route Scroll Reset to Support Multiple Scroll Containers

**Files:**
- Modify: `web/components/route-scroll-reset.tsx`
- Test: `web/components/route-scroll-reset.test.ts`

**Step 1: Write failing test**
- Source test: assert `querySelectorAll('[data-page-scroll-container="true"]')` is used.

**Step 2: Run failing test**
- `pnpm -C web -s test -- route-scroll-reset.test.ts`

**Step 3: Implement minimal code**
- Update to scroll all matched containers to top.

**Step 4: Run tests**
- `pnpm -C web -s test -- route-scroll-reset.test.ts`

**Step 5: Commit**
- `git add web/components/route-scroll-reset.tsx web/components/route-scroll-reset.test.ts`
- `git commit -m "fix(ui): reset all internal scroll containers on route changes"`

---

### Task 6: Add Mobile Panel Dialog Helper (`WorkbenchPanelDialog`)

**Files:**
- Create: `web/components/workbench/workbench-panel-dialog.tsx`
- Modify: `web/components/workbench/index.ts`
- Test: `web/components/workbench/workbench-panel-dialog.source.test.ts`

**Step 1: Write failing test**
- Assert it uses Radix `Dialog` primitives and sets `aria-label` for icon-only triggers.

**Step 2: Run failing test**
- `pnpm -C web -s test -- workbench-panel-dialog.source.test.ts`

**Step 3: Implement minimal code**
- Provide a wrapper that:
  - Accepts `open`, `onOpenChange`, `title`, and `children`.
  - Uses `DialogContent` sizing similar to `chunk-preview` mobile settings panel.

**Step 4: Run tests**
- `pnpm -C web -s test -- workbench-panel-dialog.source.test.ts`

**Step 5: Commit**
- `git add web/components/workbench/workbench-panel-dialog.tsx web/components/workbench/index.ts web/components/workbench/workbench-panel-dialog.source.test.ts`
- `git commit -m "feat(ui): add workbench mobile panel dialog helper"`

---

### Task 7: Add Standard `PageToolbar` Primitive for Standard Pages

**Files:**
- Create: `web/components/ui/page-toolbar.tsx`
- Test: `web/components/ui/page-toolbar.source.test.ts`

**Step 1: Write failing test**
- Assert the toolbar uses:
  - `min-h-0` safe structure
  - token-based borders (`border-border/60`)
  - no heavy shadows

**Step 2: Run failing test**
- `pnpm -C web -s test -- page-toolbar.source.test.ts`

**Step 3: Implement minimal code**
- A simple wrapper used inside `PageScaffold` toolbars.

**Step 4: Run tests**
- `pnpm -C web -s test -- page-toolbar.source.test.ts`

**Step 5: Commit**
- `git add web/components/ui/page-toolbar.tsx web/components/ui/page-toolbar.source.test.ts`
- `git commit -m "feat(ui): add PageToolbar primitive"`

---

### Task 8: Integrate `PageToolbar` Into `PageScaffold`

**Files:**
- Modify: `web/components/ui/page-scaffold.tsx`
- Test: `web/components/ui/page-scaffold.toolbar.test.ts`

**Step 1: Write failing test**
- Source test: assert `PageScaffold` wraps `toolbar` content with `PageToolbar`.

**Step 2: Run failing test**
- `pnpm -C web -s test -- page-scaffold.toolbar.test.ts`

**Step 3: Implement minimal code**
- Replace the raw div inside `PageHeaderBar` with `PageToolbar`.

**Step 4: Run tests**
- `pnpm -C web -s test -- page-scaffold.toolbar.test.ts`

**Step 5: Commit**
- `git add web/components/ui/page-scaffold.tsx web/components/ui/page-scaffold.toolbar.test.ts web/components/ui/page-toolbar.tsx`
- `git commit -m "refactor(ui): standardize PageScaffold toolbar structure"`

---

### Task 9: Create Knowledge Page Entry Component (Module Boundary)

**Files:**
- Create: `web/components/knowledge/knowledge-page.tsx`
- Modify: `web/app/knowledge/page.tsx`
- Test: `web/app/knowledge/knowledge-page.entry.test.ts`

**Step 1: Write failing test**
- Source test: ensure `web/app/knowledge/page.tsx` is a thin wrapper that imports and returns `<KnowledgePage />`.

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-page.entry.test.ts`

**Step 3: Implement minimal code**
- Move the existing implementation from `web/app/knowledge/page.tsx` into `web/components/knowledge/knowledge-page.tsx`.
- Keep exports/defaults consistent.

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-page.entry.test.ts`
- `pnpm -C web -s typecheck`

**Step 5: Commit**
- `git add web/app/knowledge/page.tsx web/components/knowledge/knowledge-page.tsx web/app/knowledge/knowledge-page.entry.test.ts`
- `git commit -m "refactor(knowledge): extract route page into component"`

---

### Task 10: Split Knowledge File Type Helpers

**Files:**
- Create: `web/components/knowledge/file-type.ts`
- Modify: `web/components/knowledge/knowledge-page.tsx`
- Test: `web/components/knowledge/file-type.test.ts`

**Step 1: Write failing test**
- Source test: assert `file-type.ts` exports `getFileTypeMeta` (or equivalent) and does not use gradients.

**Step 2: Run failing test**
- `pnpm -C web -s test -- file-type.test.ts`

**Step 3: Implement minimal code**
- Move `getFileTypeInfo` from the page into `file-type.ts`.

**Step 4: Run tests**
- `pnpm -C web -s test -- file-type.test.ts`
- `pnpm -C web -s typecheck`

**Step 5: Commit**
- `git add web/components/knowledge/file-type.ts web/components/knowledge/knowledge-page.tsx web/components/knowledge/file-type.test.ts`
- `git commit -m "refactor(knowledge): extract file type helpers"`

---

### Task 11: Introduce Knowledge Workbench Skeleton Using `WorkbenchScaffold`

**Files:**
- Modify: `web/components/knowledge/knowledge-page.tsx`
- Modify: `web/components/workbench/workbench-scaffold.tsx` (if needed)
- Test: `web/components/knowledge/knowledge-page.workbench.test.ts`

**Step 1: Write failing test**
- Source test: assert `knowledge-page.tsx` uses `WorkbenchScaffold`.

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-page.workbench.test.ts`

**Step 3: Implement minimal code**
- Wrap existing content in `WorkbenchScaffold`.
- Keep behavior the same; focus on structural slots:
  - header/title/actions
  - optional pipeline rail and/or toolbar
  - left/main/right placeholder panels

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-page.workbench.test.ts`

**Step 5: Commit**
- `git add web/components/knowledge/knowledge-page.tsx web/components/knowledge/knowledge-page.workbench.test.ts`
- `git commit -m "feat(knowledge): adopt WorkbenchScaffold skeleton"`

---

### Task 12: Datasets Page Toolbar Normalization (Remove Decorative Pulse)

**Files:**
- Modify: `web/app/datasets/page.tsx`
- Test: `web/app/datasets/datasets.header.source.test.ts`

**Step 1: Write failing test**
- Source test: assert datasets header does not use `animate-pulse`.

**Step 2: Run failing test**
- `pnpm -C web -s test -- datasets.header.source.test.ts`

**Step 3: Implement minimal code**
- Replace the pulsing dot with a static status chip or a neutral delimiter.

**Step 4: Run tests**
- `pnpm -C web -s test -- datasets.header.source.test.ts`

**Step 5: Commit**
- `git add web/app/datasets/page.tsx web/app/datasets/datasets.header.source.test.ts`
- `git commit -m "refactor(datasets): remove decorative pulse from header"`

---

### Task 13: Extract Datasets Page Into Component Module

**Files:**
- Create: `web/components/datasets/datasets-page.tsx`
- Modify: `web/app/datasets/page.tsx`
- Test: `web/app/datasets/datasets-page.entry.test.ts`

**Step 1: Write failing test**
- Source test: ensure route `page.tsx` is a thin wrapper.

**Step 2: Run failing test**
- `pnpm -C web -s test -- datasets-page.entry.test.ts`

**Step 3: Implement minimal code**
- Move the page implementation under `web/components/datasets/`.

**Step 4: Run tests**
- `pnpm -C web -s test -- datasets-page.entry.test.ts`
- `pnpm -C web -s typecheck`

**Step 5: Commit**
- `git add web/app/datasets/page.tsx web/components/datasets/datasets-page.tsx web/app/datasets/datasets-page.entry.test.ts`
- `git commit -m "refactor(datasets): extract route page into component"`

---

### Task 14: Parsing Page Entry Extraction (Module Boundary)

**Files:**
- Create: `web/components/parsing/parsing-page.tsx`
- Modify: `web/app/parsing/page.tsx`
- Test: `web/app/parsing/parsing-page.entry.test.ts`

**Step 1: Write failing test**
- Assert route `page.tsx` becomes a thin wrapper.

**Step 2: Run failing test**
- `pnpm -C web -s test -- parsing-page.entry.test.ts`

**Step 3: Implement minimal code**
- Move parsing implementation into component file.

**Step 4: Run tests**
- `pnpm -C web -s test -- parsing-page.entry.test.ts`
- `pnpm -C web -s typecheck`

**Step 5: Commit**
- `git add web/app/parsing/page.tsx web/components/parsing/parsing-page.tsx web/app/parsing/parsing-page.entry.test.ts`
- `git commit -m "refactor(parsing): extract route page into component"`

---

### Task 15: Parsing Workbench Scaffold Wrap

**Files:**
- Modify: `web/components/parsing/parsing-page.tsx`
- Test: `web/components/parsing/parsing-page.workbench.test.ts`

**Step 1: Write failing test**
- Source test: assert `ParsingPage` uses `WorkbenchScaffold`.

**Step 2: Run failing test**
- `pnpm -C web -s test -- parsing-page.workbench.test.ts`

**Step 3: Implement minimal code**
- Introduce a `WorkbenchScaffold` wrapper.
- Keep existing internal sections, but map them to left/main/right slots.

**Step 4: Run tests**
- `pnpm -C web -s test -- parsing-page.workbench.test.ts`

**Step 5: Commit**
- `git add web/components/parsing/parsing-page.tsx web/components/parsing/parsing-page.workbench.test.ts`
- `git commit -m "feat(parsing): adopt WorkbenchScaffold skeleton"`

---

### Task 16: Data Governance Panel Uses Workbench Scaffold (Outer Structure)

**Files:**
- Modify: `web/components/data-governance-panel.tsx`
- Test: `web/components/data-governance-panel.workbench.test.ts`

**Step 1: Write failing test**
- Source test: assert `DataGovernancePanel` uses `WorkbenchScaffold` or (if too heavy) uses `WorkbenchPane` primitives.

**Step 2: Run failing test**
- `pnpm -C web -s test -- data-governance-panel.workbench.test.ts`

**Step 3: Implement minimal code**
- Replace the top-level layout wrappers in `DataGovernancePanel` with `WorkbenchScaffold` and `PipelineRail`.

**Step 4: Run tests**
- `pnpm -C web -s test -- data-governance-panel.workbench.test.ts`

**Step 5: Commit**
- `git add web/components/data-governance-panel.tsx web/components/data-governance-panel.workbench.test.ts`
- `git commit -m "feat(governance): align panel layout with workbench scaffold"`

---

### Task 17: Chunk Preview Workbench Align With Workbench Pane Primitives

**Files:**
- Modify: `web/components/chunk-preview/components/workbench/index.tsx`
- Test: `web/components/chunk-preview/components/workbench/workbench.layout.test.ts`

**Step 1: Write failing test**
- Source test: assert chunk preview workbench uses `min-h-0 overflow-hidden` consistently and includes optional pipeline rail.

**Step 2: Run failing test**
- `pnpm -C web -s test -- workbench.layout.test.ts`

**Step 3: Implement minimal code**
- Use `WorkbenchPane` primitives for the left settings panel and main area containers.

**Step 4: Run tests**
- `pnpm -C web -s test -- workbench.layout.test.ts`

**Step 5: Commit**
- `git add web/components/chunk-preview/components/workbench/index.tsx web/components/chunk-preview/components/workbench/workbench.layout.test.ts`
- `git commit -m "refactor(chunk-preview): align workbench layout primitives"`

---

### Task 18: Ensure Workbench Pages Expose Scroll Containers for Route Reset

**Files:**
- Modify: `web/components/workbench/workbench-pane.tsx`
- Modify: `web/components/workbench/workbench-scaffold.tsx`
- Test: `web/components/workbench/workbench-scroll-containers.test.ts`

**Step 1: Write failing test**
- Source test: assert workbench scaffold sets `data-page-scroll-container="true"` on pane bodies.

**Step 2: Run failing test**
- `pnpm -C web -s test -- workbench-scroll-containers.test.ts`

**Step 3: Implement minimal code**
- Ensure left/main/right pane bodies all opt-in to scroll reset.

**Step 4: Run tests**
- `pnpm -C web -s test -- workbench-scroll-containers.test.ts`

**Step 5: Commit**
- `git add web/components/workbench/workbench-pane.tsx web/components/workbench/workbench-scaffold.tsx web/components/workbench/workbench-scroll-containers.test.ts`
- `git commit -m "feat(ui): standardize workbench scroll reset containers"`

---

### Task 19: Normalize Safe Area Handling in Global Document Viewer Panel

**Files:**
- Modify: `web/components/document-viewer-panel.tsx`
- Test: `web/components/document-viewer-panel.safe-area.test.ts`

**Step 1: Write failing test**
- Source test: assert the panel header includes safe-area top padding when supported.

**Step 2: Run failing test**
- `pnpm -C web -s test -- document-viewer-panel.safe-area.test.ts`

**Step 3: Implement minimal code**
- Add `supports-[padding:env(safe-area-inset-top)]` style similar to `PageHeaderBar`.

**Step 4: Run tests**
- `pnpm -C web -s test -- document-viewer-panel.safe-area.test.ts`

**Step 5: Commit**
- `git add web/components/document-viewer-panel.tsx web/components/document-viewer-panel.safe-area.test.ts`
- `git commit -m "fix(ui): respect safe area in document viewer panel"`

---

### Task 20: Introduce `KnowledgeSidebar` Rename Wrapper (reduce ambiguous naming)

**Files:**
- Create: `web/components/knowledge/knowledge-sidebar.tsx`
- Modify: `web/components/sidebar.tsx` (export alias)
- Test: `web/components/knowledge/knowledge-sidebar.test.ts`

**Step 1: Write failing test**
- Assert `knowledge-sidebar.tsx` exports `KnowledgeSidebar`.

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-sidebar.test.ts`

**Step 3: Implement minimal code**
- Export the existing `Sidebar` as `KnowledgeSidebar` without breaking imports.

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-sidebar.test.ts`

**Step 5: Commit**
- `git add web/components/knowledge/knowledge-sidebar.tsx web/components/sidebar.tsx web/components/knowledge/knowledge-sidebar.test.ts`
- `git commit -m "refactor(knowledge): add explicit KnowledgeSidebar export"`

---

### Task 21: Knowledge Workbench Left Panel Integration

**Files:**
- Modify: `web/components/knowledge/knowledge-page.tsx`
- Modify: `web/components/knowledge/knowledge-sidebar.tsx`
- Test: `web/components/knowledge/knowledge-page.left-panel.test.ts`

**Step 1: Write failing test**
- Source test: assert WorkbenchScaffold `leftPanel` slot is provided.

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-page.left-panel.test.ts`

**Step 3: Implement minimal code**
- Mount the knowledge sidebar into the left panel slot.

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-page.left-panel.test.ts`

**Step 5: Commit**
- `git add web/components/knowledge/knowledge-page.tsx web/components/knowledge/knowledge-page.left-panel.test.ts`
- `git commit -m "feat(knowledge): place document sidebar into workbench left panel"`

---

### Task 22: Knowledge Workbench Right Panel (Light Inspector) Placeholder

**Files:**
- Create: `web/components/knowledge/knowledge-inspector.tsx`
- Modify: `web/components/knowledge/knowledge-page.tsx`
- Test: `web/components/knowledge/knowledge-inspector.source.test.ts`

**Step 1: Write failing test**
- Assert `KnowledgeInspector` exists and uses `Panel` + token borders.

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-inspector.source.test.ts`

**Step 3: Implement minimal code**
- Add a placeholder inspector with selected-document summary and a slot for retrieval preview.

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-inspector.source.test.ts`

**Step 5: Commit**
- `git add web/components/knowledge/knowledge-inspector.tsx web/components/knowledge/knowledge-page.tsx web/components/knowledge/knowledge-inspector.source.test.ts`
- `git commit -m "feat(knowledge): add light inspector panel"`

---

### Task 23: Parsing Left Panel Extract (Queue/Tree) Into Module

**Files:**
- Create: `web/components/parsing/parsing-left-panel.tsx`
- Modify: `web/components/parsing/parsing-page.tsx`
- Test: `web/components/parsing/parsing-left-panel.source.test.ts`

**Step 1: Write failing test**
- Assert the new module exists and does not use `h-screen`.

**Step 2: Run failing test**
- `pnpm -C web -s test -- parsing-left-panel.source.test.ts`

**Step 3: Implement minimal code**
- Move the left panel rendering code into the module and pass required props.

**Step 4: Run tests**
- `pnpm -C web -s test -- parsing-left-panel.source.test.ts`

**Step 5: Commit**
- `git add web/components/parsing/parsing-left-panel.tsx web/components/parsing/parsing-page.tsx web/components/parsing/parsing-left-panel.source.test.ts`
- `git commit -m "refactor(parsing): extract left panel module"`

---

### Task 24: Parsing Right Panel Extract (TOC/Blocks/Settings) Into Module

**Files:**
- Create: `web/components/parsing/parsing-right-panel.tsx`
- Modify: `web/components/parsing/parsing-page.tsx`
- Test: `web/components/parsing/parsing-right-panel.source.test.ts`

**Step 1: Write failing test**
- Assert module exists and uses internal scroll container.

**Step 2: Run failing test**
- `pnpm -C web -s test -- parsing-right-panel.source.test.ts`

**Step 3: Implement minimal code**
- Move the right panel code into module.

**Step 4: Run tests**
- `pnpm -C web -s test -- parsing-right-panel.source.test.ts`

**Step 5: Commit**
- `git add web/components/parsing/parsing-right-panel.tsx web/components/parsing/parsing-page.tsx web/components/parsing/parsing-right-panel.source.test.ts`
- `git commit -m "refactor(parsing): extract right panel module"`

---

### Task 25: Parsing Main Panel Extract (Preview/Edit Surface) Into Module

**Files:**
- Create: `web/components/parsing/parsing-main-panel.tsx`
- Modify: `web/components/parsing/parsing-page.tsx`
- Test: `web/components/parsing/parsing-main-panel.source.test.ts`

**Step 1: Write failing test**
- Assert main panel module exists and uses `min-w-0` and `min-h-0`.

**Step 2: Run failing test**
- `pnpm -C web -s test -- parsing-main-panel.source.test.ts`

**Step 3: Implement minimal code**
- Move preview/editor UI into module.

**Step 4: Run tests**
- `pnpm -C web -s test -- parsing-main-panel.source.test.ts`

**Step 5: Commit**
- `git add web/components/parsing/parsing-main-panel.tsx web/components/parsing/parsing-page.tsx web/components/parsing/parsing-main-panel.source.test.ts`
- `git commit -m "refactor(parsing): extract main panel module"`

---

### Task 26: WorkbenchScaffold: Add Default Mid-Density Spacing Tokens (No New Theme)

**Files:**
- Modify: `web/components/workbench/workbench-scaffold.tsx`
- Test: `web/components/workbench/workbench-scaffold.spacing.test.ts`

**Step 1: Write failing test**
- Source test: assert scaffold uses consistent `px-6 md:px-8` and avoids ad-hoc spacing.

**Step 2: Run failing test**
- `pnpm -C web -s test -- workbench-scaffold.spacing.test.ts`

**Step 3: Implement minimal code**
- Normalize padding and section spacing to match `PageScaffold` conventions.

**Step 4: Run tests**
- `pnpm -C web -s test -- workbench-scaffold.spacing.test.ts`

**Step 5: Commit**
- `git add web/components/workbench/workbench-scaffold.tsx web/components/workbench/workbench-scaffold.spacing.test.ts`
- `git commit -m "refactor(ui): normalize workbench scaffold spacing"`

---

### Task 27: Update Baseline UI Guards for New Patterns (if needed)

**Files:**
- Modify: `web/lib/baseline-ui-guards.test.ts` (only if new primitives introduce false positives)

**Step 1: Write failing test**
- If a violation appears, reproduce locally by running `pnpm -C web -s test -- baseline-ui-guards.test.ts`.

**Step 2: Implement minimal fix**
- Prefer changing new code to comply, rather than adding ignores.

**Step 3: Verify**
- `pnpm -C web -s test -- baseline-ui-guards.test.ts`

**Step 4: Commit**
- `git add web/lib/baseline-ui-guards.test.ts`
- `git commit -m "test(ui): adjust baseline ui guards (if necessary)"`

---

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
- `bd update MimirQ-w7q --append-notes 'Completed tasks 1-28 for layout system v2 workbench migration.'`

**Step 2: Sync beads**
- `bd sync`

**Step 3: Commit**
- `git add .beads/issues.jsonl`
- `git commit -m "bd sync"`

---

### Task 30: Land the Plane (Merge to main + Push)

**Step 1: Rebase main**
- From main worktree: `git pull --rebase`

**Step 2: Merge fast-forward**
- `git merge --ff-only ui-layout-v2`

**Step 3: Push**
- `git push`

**Step 4: Verify clean**
- `git status` must show up to date with origin.

