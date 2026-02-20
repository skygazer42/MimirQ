# Knowledge Workbench Wave 2 (Actions + Import Menu) (Design)

**Date:** 2026-02-20

## Goal
Further optimize `/knowledge` as a management-console workbench by:
- Reducing `web/components/knowledge/knowledge-page.tsx` complexity (maintainability).
- Improving header usability by consolidating import/config actions into a **single** `导入/新增` dropdown entry point (interaction).
- Improving render performance by moving heavy dialog trees out of the `KnowledgePage` render hot-path (performance).

## Non-Goals
- No backend API changes.
- No pagination/infinite scrolling (keep the current “load up to 200 docs” strategy).
- No visual theme/token overhaul.
- No major new information architecture changes (Wave 1 layout stays: Left Scope, Main Docs, Right Inspector).

## Current State (Problems)
`web/components/knowledge/knowledge-page.tsx` is still large (~1800 LOC) and mixes:
- Workbench layout + routing query-state.
- Documents list virtualization + selection/batch actions.
- Multiple import/config dialogs (upload, URL import, URL batch connector, website crawl connector, pipeline config).
- Connector runs state/loaders and index audit state/handlers.

This creates:
- High coupling (every page state change re-renders heavy dialog subtrees).
- Header clutter (multiple outline buttons competing with primary action).
- Friction for future iteration (hard to isolate changes and tests).

## UX Decision: Single Import Entry Point
Replace the current multi-button header actions with a single dropdown trigger:
- **Trigger label:** `导入/新增`
- Menu groups:
  - Add: Upload files
  - Import: URL import / URL batch / Website crawl
  - Config: Pipeline config

Notes:
- The empty-state upload CTA inside the documents surface can remain; the header is the global entry point.
- The dropdown should be keyboard navigable (Radix `DropdownMenu`) and each item opens its corresponding dialog.

## Proposed Component Architecture

### High-Level
Keep `KnowledgePage` as the composition root, but move “header actions + dialogs” into their own component subtree.

New modules:
- `web/components/knowledge/knowledge-workbench-actions.tsx`
  - Renders the `导入/新增` dropdown and owns the dialog open/close state.
  - Uses existing contexts for parser backend / chunk strategy / pipeline options.
  - Calls back to `KnowledgePage` for “refresh documents” and “refresh connector runs” when runs are created.

- `web/components/knowledge/import/knowledge-import-menu.tsx`
  - Pure UI: menu structure, labels, icons, group separators.

- Dialog components (each owns its internal form state and resets on close):
  - `web/components/knowledge/import/knowledge-pipeline-config-dialog.tsx`
  - `web/components/knowledge/import/knowledge-url-import-dialog.tsx`
  - `web/components/knowledge/import/knowledge-url-batch-dialog.tsx`
  - `web/components/knowledge/import/knowledge-web-crawl-dialog.tsx`

### Data / State Boundaries
- Keep datasets loading in `KnowledgePage` (single source of truth) and pass:
  - `datasets`, `datasetsLoading`, `selectedDatasetId`, and `DATASET_DEFAULT` behavior into actions/dialogs.
- Keep “documents reload” and “connector runs reload” as callbacks passed into actions.
- Keep heavy dialog form state inside each dialog component:
  - This reduces `KnowledgePage` state count and prevents unrelated state changes (search/sort/view) from re-rendering big forms.

### Performance Considerations
- Ensure `KnowledgeWorkbenchActions` is isolated so changes in documents-related state do not cause deep dialog tree churn.
- Prefer stable callbacks (`useCallback`) for `onAfterImport` / `onAfterRunCreated` so dialogs can call:
  - `loadDocuments()` (best-effort refresh)
  - `loadConnectorRuns({ datasetId })` (only when relevant)

## Testing / Verification
Add source-level tests to prevent regressions:
- `web/components/knowledge/knowledge-page.actions.source.test.ts`
  - Asserts `KnowledgePage` imports and renders `KnowledgeWorkbenchActions`.
  - Asserts `KnowledgePage` no longer contains the large inline `<Dialog ... URL 导入 ...>` blocks (guard by key strings).

- `web/components/knowledge/import/knowledge-import-menu.source.test.ts`
  - Asserts the dropdown menu contains entries for:
    - Upload
    - URL import
    - URL batch
    - Website crawl
    - Pipeline config

Quality gates:
- `pnpm -C web -s verify`

## Rollout Strategy
1. Introduce new actions components + tests, keep behavior identical.
2. Switch `KnowledgePage` to render the new consolidated `导入/新增` dropdown and remove old inline dialogs.
3. Run web verify gate and ship.

