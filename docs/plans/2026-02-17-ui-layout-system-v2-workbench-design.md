# UI Layout System v2 + Workbench Scaffold (Design)

**Date:** 2026-02-17

## Goal
Build a consistent, mid-density “workbench” UI across the app.

This effort focuses on layout primitives, information hierarchy, and module boundaries (not a visual re-theme). It targets:
- Global app shell consistency (`AppFrame` + left navigation)
- Core workflows: Chat (`/`), Knowledge (`/knowledge`), Datasets (`/datasets`)
- Workbench workflows: Parsing (`/parsing`), Data Governance (`/data-governance`), Chunk Preview (`/chunk-preview`)

## Constraints (Baseline UI)
- Tailwind-first; reuse existing component primitives (Radix already present).
- No new animations unless explicitly requested; keep motion limited to transform/opacity.
- Avoid gradients; avoid glow-as-affordance.
- No window scrolling: all pages use internal scroll containers.
- Respect safe-area insets for fixed/sticky elements.
- Avoid arbitrary z-index; use fixed scale.

## Current State (Audit)
The project already has good foundations:
- `web/components/app-frame.tsx`: full-height shell, locks window scroll, supports global right document viewer.
- `web/components/navbar.tsx`: left navigation (desktop + mobile overlay), structured sections.
- `web/components/ui/page-scaffold.tsx` + `page-body.tsx` + `page-container.tsx`: standard page header + body scrolling.
- `web/app/globals.css`: token-driven theme, focus ring utility, background grid.

Primary pain points we want to fix:
- **Layout duplication:** multiple pages implement their own left/sidebar collapse + scroll + sticky patterns.
- **Inconsistent workbench patterns:** parsing/governance/chunk-preview behave like separate “apps” instead of one system.
- **Module boundaries:** some pages (notably `web/app/knowledge/page.tsx`) are extremely large and couple unrelated concerns.
- **Inspector semantics:** there’s a global `DocumentViewerPanel` and also per-page side/detail panes; they need consistent rules to avoid UI conflict.

## Design Principles
1. **One app shell.** `AppFrame` stays the only place that controls window-level scroll locking, global background, left navigation, and optional global right panel.
2. **Two page archetypes.**
   - “Standard pages” use `PageScaffold`.
   - “Workbench pages” use a new `WorkbenchScaffold`.
3. **Panels have roles.** Left = navigation/queue/config; Center = main work; Right = inspector/details.
4. **Stable hierarchy.** Header (optional) → Toolbar (optional sticky) → Body (internal scroll).
5. **Signature element: Pipeline Rail.** Workbench pages optionally show a consistent Parse → Govern → Chunk → Index rail using the existing stepper.

## Proposed Architecture

### 1) Keep `AppFrame` as the global shell
Responsibilities:
- Height: `h-dvh`, window scroll locked.
- Left navigation (`Navbar`).
- Optional global right panel (`DocumentViewerPanel`), with the existing padding behavior (`withDocumentViewerPadding`).

Non-goals for this work:
- Rewriting `Navbar` information architecture.
- Re-theming tokens.

### 2) Standard Pages: continue to use `PageScaffold`
Pages like `/datasets`, `/settings`, `/history`, `/usage` remain `PageScaffold`-based.

We’ll standardize “header actions + toolbar layout” by extracting a consistent toolbar block (so pages stop hand-rolling their top-of-page controls).

### 3) New: `WorkbenchScaffold` (mid-density workbench archetype)
A layout primitive for pages with multi-pane workflows.

**Slots:**
- `title`, `icon`, `description`, `actions`
- `pipelineRail` (optional): shows Parse → Govern → Chunk → Index context
- `toolbar` (optional): filters/search/view controls
- `leftPanel` (optional): nav/queue/config (collapsible)
- `mainPanel`: primary working surface
- `rightPanel` (optional): inspector/details (collapsible)

**Behavioral rules:**
- No window scroll; each pane can be independently scrollable.
- Sticky should be limited to pane-local headers/toolbars.
- Mobile behavior should prefer “panel as dialog/sheet” over cramped multi-column layout.

### 4) Inspector Rules (avoid conflict with global `DocumentViewerPanel`)
- Page-level inspector is for *page-local entities* (selected row, selected job, selected chunk metadata).
- Global `DocumentViewerPanel` remains the cross-page document viewer.
- Workbench pages should not re-implement a second heavy document viewer.

### 5) Module Boundaries (reduce page.tsx size)
Create a predictable structure for large pages:
- `web/components/workbench/*`: scaffold + pane primitives
- `web/components/knowledge/*`: knowledge page modules
- `web/components/parsing/*`, `web/components/governance/*` (or similar): workbench-specific modules

Rule of thumb:
- `web/app/**/page.tsx` should wire modules together and hold route-level state only.

## Page Migrations (Target State)

### Chat (`/`)
- Keep `AppFrame` + global `DocumentViewerPanel`.
- Align internal scrolling and header semantics with the broader layout system.

### Knowledge (`/knowledge`)
- Convert to workbench archetype:
  - Left: dataset folder tree + filters
  - Main: documents/connectors/ingestion tables and views
  - Right: light inspector for selected document/run + retrieval preview
- Split large file into focused components and hooks.

### Datasets (`/datasets`)
- Keep `PageScaffold`.
- Extract editor/create dialogs into modular components.
- Standardize header/toolbar and reduce inline layout duplication.

### Parsing (`/parsing`)
- Convert to workbench archetype:
  - Left: queue/tree/upload
  - Main: preview/editor
  - Right: blocks/TOC/settings
- Add Pipeline Rail (Parse highlighted; quick links to the next stages).

### Data Governance (`/data-governance`)
- Keep dynamic import, but move the panel onto `WorkbenchScaffold` so it matches parsing/chunk-preview.

### Chunk Preview (`/chunk-preview`)
- Currently has its own `Workbench` component; align it with `WorkbenchScaffold` conventions.
- Reuse common pane primitives to prevent “mini-app divergence”.

## Rollout Strategy
- Introduce primitives first (no page behavior changes yet).
- Migrate one flagship page at a time to de-risk.
- Prefer mechanical refactors with tests over visual churn.

## Risks / Mitigations
- **Large diffs:** mitigate with a worktree, small tasks, and frequent verification (`pnpm -C web verify`).
- **CSS/scroll regressions:** add targeted tests for key behaviors (sticky headers, scroll container presence).
- **A11y regressions:** keep keyboard/focus behavior inside existing primitives; don’t hand-roll complex interactions.

## Quality Gates
Run from `web/`:
- `pnpm -s lint`
- `pnpm -s typecheck`
- `pnpm -s test`
- `pnpm -s ui-check`

## Task Budget (30 tasks)
We’ll deliver as 30 small, reviewable tasks grouped into 5 batches:
1. Layout primitives (AppFrame/PageScaffold helpers/WorkbenchScaffold)
2. Workbench pane primitives (scroll containers, pane headers, inspector patterns)
3. Core pages refactors (`/`, `/knowledge`, `/datasets`)
4. Workbench pages refactors (`/parsing`, `/data-governance`, `/chunk-preview`)
5. Consistency + QA (a11y checks, token checks, regressions)
