# Knowledge Workbench Deep Optimization (Wave 1) (Design)

**Date:** 2026-02-17

## Goal
Turn `/knowledge` into a true “management console” workbench:
- **Left:** scope + navigation (dataset, folder tree, lifecycle/status filters)
- **Main:** virtualized document management surface (search/sort/view/batch actions)
- **Right:** lightweight inspector (selection summary + doc metadata + optional retrieval preview)

Secondary goals (after `/knowledge` is stable):
- Align `/chunk-preview` and `/parsing` with the same Workbench conventions (scaffold slots, spacing, mobile panels, scroll containers).
- Global polish for `AppFrame/Navbar/DocumentViewerPanel` only where consistency gaps remain.

## Non-Goals
- No visual re-theme or token overhaul.
- No backend API changes unless required to fix correctness bugs.
- No new complex animations; motion remains transform/opacity only.

## Constraints (Baseline UI)
- No window scrolling: pages use internal scroll containers only.
- Respect safe-area insets for fixed/sticky elements.
- Avoid ad-hoc z-index; prefer the existing scale.
- Keep workbench density “mid” (matching existing `WorkbenchScaffold` padding conventions).

## Current State (Problems)
`web/components/knowledge/knowledge-page.tsx` is ~2800 LOC and mixes:
- URL state, data fetching, list virtualization, selection/batch actions
- UI layout and panel composition
- Retrieval/settings sub-pages

There is also a correctness risk:
- The page currently derives its scroll element via a global selector:
  - `document.querySelector('[data-page-scroll-container="true"]')`
- In a 3-pane workbench, **multiple** scroll containers exist (left, main, right). A global selector can bind virtualization to the wrong container, causing bad rendering and scroll behavior.

Finally, the current `KnowledgeSidebar` wrapper points at the general `Sidebar` document list, which is not the right “scope/navigation” mental model for a management-console Knowledge workbench.

## Recommended Information Architecture (Option A: Management Console)
### Panel Responsibilities
- **LeftPanel: Scope / Navigation**
  - Dataset selector (All vs specific dataset)
  - Folder tree (always visible when dataset selected)
  - Lifecycle filter and status filter
  - Clear filters + optional saved views (future)

- **MainPanel: Documents Work Surface**
  - Search, sort, view mode (grid/list)
  - Virtualized list/grid for scale
  - Batch selection + batch actions (delete, archive, disable, reingest, etc.)

- **RightPanel: Inspector**
  - Selection summary (0/1/N documents)
  - Metadata for single-selection
  - Desktop-only retrieval preview slot; mobile uses a panel dialog

### Mobile Behavior
- WorkbenchScaffold hides left/right panes by default on small screens.
- Add explicit entry points (toolbar buttons) to open:
  - Scope panel (Left) via `WorkbenchPanelDialog`
  - Inspector panel (Right) via `WorkbenchPanelDialog`

## Proposed Component Architecture
Keep `web/app/knowledge/page.tsx` as the route entry only.

Split `web/components/knowledge/knowledge-page.tsx` into:
- `web/components/knowledge/use-knowledge-query-state.ts`
  - Encapsulate URL <-> state sync for tab/view/q/filters/sort.
- `web/components/knowledge/use-knowledge-scroll-container.ts`
  - Resolve the **main** pane scroll container using a sentinel `ref` + `.closest()` (no global querySelector).
- `web/components/knowledge/knowledge-scope-panel.tsx`
  - LeftPanel UI: dataset/folder/lifecycle/status filters.
- `web/components/knowledge/knowledge-documents-panel.tsx`
  - MainPanel UI: toolbar + list/grid + virtualization.
- `web/components/knowledge/knowledge-retrieval-panel.tsx`
  - Retrieval test UI (main content), with desktop inspector slot.
- `web/components/knowledge/knowledge-settings-panel.tsx`
  - Settings UI (main content).

Existing components remain, but get clearer roles:
- `KnowledgeInspector` stays the RightPanel primitive.
- `file-type.ts` remains a shared helper for list rendering.

## Testing / Verification
- Add/extend source tests to ensure:
  - `/knowledge` no longer binds virtualization to a global scroll container selector.
  - LeftPanel uses `KnowledgeScopePanel` (and does not reuse the generic `Sidebar` document list).
  - Mobile panel dialogs exist for scope/inspector entry points.
- Run `pnpm -C web -s verify` as the primary gate.

## Rollout Strategy
1. Land module boundaries + scroll-container correctness fix first (minimal UI change).
2. Move filters/navigation into LeftPanel and simplify Main toolbar.
3. Add mobile panel dialogs and ensure keyboard/focus behavior remains correct.
4. Only then move on to `/chunk-preview` and `/parsing` alignment + global polish.

