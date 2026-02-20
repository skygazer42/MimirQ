# Knowledge Console-first Optimization (Design)

**Date:** 2026-02-20

## Goal
Make `/knowledge` feel and behave like a true **knowledge management console** (control panel), with a bias toward:
- **A. Documents work-surface:** dense, fast, batch-friendly operations.
- **B. Import/add flows:** one clear entry point + inline errors + best-effort refresh.
- **C. Monitoring/diagnostics:** connector runs are actionable (filterable, recoverable, debuggable).

Primary UX decision:
- **Default documents view is `list`** (table) for management-console density.

## Non-Goals
- No backend API changes.
- No major information architecture overhaul (keep current tabs: `documents` / `retrieval` / `settings`).
- No theme/token overhaul (stay token-first, Tailwind v4 baseline).
- No new animations (baseline-ui).

## Current State (Baseline)
The workbench foundation is already in place:
- `WorkbenchScaffold` with left scope + main work surface + right inspector.
- URL state is centralized via `use-knowledge-query-state`.
- Main scroll container is correctly resolved via `use-knowledge-scroll-container` sentinel (avoids global selector bugs).
- Import actions are consolidated into a single `导入/新增` dropdown (`KnowledgeWorkbenchActions`) and extracted dialogs.

What still reads “app demo” vs “console”:
- Default view is grid (lower density).
- Table header is not sticky; row actions depend on hover (touch + keyboard discoverability issues).
- Destructive actions aren’t consistently guarded via `AlertDialog`.
- Connectors runs sit inside “settings” and have limited filtering/triage affordances; empty state copy is outdated.

## Decisions

### 1) Default View Strategy
**Decision:** When `view` is omitted from the URL, default to `list`.
- `view=list` remains supported for backwards compatibility.
- `view=grid` is used to explicitly choose grid view.

Implications:
- Update defaults in `web/components/knowledge/use-knowledge-query-state.ts`.
- Align initial React state in `web/components/knowledge/knowledge-page.tsx` to avoid first-render flicker.

### 2) Documents Table (Console Density)
**Decision:** Treat list/table as the primary workflow.
- Sticky table header within the main pane internal scroll container.
- Row actions accessible without hover:
  - Always visible on small screens.
  - Visible on hover *and* `focus-within` on desktop.
- Batch actions bar: clear ordering + consistent disabled states.
- Destructive operations use `AlertDialog` (baseline-ui).

### 3) Import / Add (One Entry Point, Clear Errors)
**Decision:** Keep the existing `导入/新增` dropdown entry point, but make import flows “console-grade”:
- Inline field errors (not just toast) in dialogs.
- Success path triggers best-effort refresh:
  - Documents list refresh.
  - Connector runs refresh when relevant.
- Success guidance: “what happens next” (e.g., where to monitor a run).

### 4) Monitoring / Diagnostics (Connector Runs)
**Decision:** Keep runs inside `settings` for now, but elevate it as an operational surface:
- Add simple status filtering (pending/running/failed/completed/cancelled).
- Improve empty state copy to match the new action entry point (`导入/新增`).
- Make recovery actions (resume/retry/cancel) clearer and more consistent.

## Implementation Scope (30 Tasks, High-Level)
These are the concrete outcomes we will land (details live in the implementation plan):
1. Default view is list and URL semantics updated.
2. Sticky table header, higher-density list surface.
3. Touch + keyboard accessible row actions (no hover-only affordances).
4. Batch delete uses `AlertDialog` and better “what will be deleted” copy.
5. Import dialogs: inline validation + refresh-on-success.
6. Connector runs: filtering + better empty state + clearer recovery actions.
7. Add/extend source tests to lock key conventions.

