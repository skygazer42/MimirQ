# Visual Pipeline Editor (MVP) Design

**Date:** 2026-02-13
**Issue:** `MimirQ-qto.5`

## Goal

Add a **read-only** visual graph view of the current dataset ingestion/RAG configuration ("pipeline") with **export/import** support. This is intended to make configuration easier to understand at a glance before iterating to editable nodes later.

## Scope (MVP)

- New dataset subpage: `/datasets/[id]/workflow`
- Fetch current config via `DatasetConfigBundle` export
- Render a **high-level graph** (top-level bundles + a few key sub-blocks)
- Click a node to see:
  - A human-readable summary
  - The underlying JSON for that node
- Export JSON (compatible with `DatasetConfigBundle`)
- Import JSON with `replace=true` semantics (overwrite/clear supported keys), with a confirmation dialog
- Add a simple entrypoint from the datasets list page

## Non-Goals (MVP)

- No visual editing of the graph (nodes/edges are read-only)
- No "diff" preview for imports
- No expansion of ingestion policy rules into per-rule nodes (keep it high-level)
- No changes to existing ingestion/settings UI beyond adding a new navigation button

## UX / Information Architecture

### Location

Create a new route: `web/app/datasets/[id]/workflow/page.tsx`.

Rationale: keeps the large existing ingestion settings UI stable and avoids regressions.

### Layout

- Two-pane layout:
  - Left: graph viewer (2D)
  - Right: detail panel for the selected node (summary + JSON)
- Mobile:
  - Graph above, details below (responsive grid)

### Actions

Page header actions:
- Back to datasets list
- Quick links to existing pages (`ingestion`, `profile`, `tables`)
- Refresh graph (re-export config)
- Export JSON
- Import JSON (file picker + confirm)

## Data Model / Compatibility

### Export

- UI calls `GET /datasets/{id}/config/export`
- Download the returned JSON payload as a file

### Import

- UI accepts either:
  1. Full export payload (`{ version, dataset_id, exported_at, config }`)
  2. Raw `DatasetConfigBundle` object
- UI calls `POST /datasets/{id}/config/import` with:
  - `replace=true` (default for this MVP)
  - `config=<DatasetConfigBundle>`

### Compatibility requirement

Export/import must remain compatible with backend `DatasetConfigBundle` semantics.

## Graph Model

### High-level nodes

Always show (configured/unconfigured) nodes for:
- `Ingestion Defaults` (default parser backend, default chunk strategy)
- `Pipeline` (DocumentPipelineOptions)
- `Ingestion Policy`
- `RAG Defaults`
- `Prompt Defaults`
- `Chunk Targets` (if present)
- `FLS Policy` (if present)

### Pipeline sub-block nodes (few key blocks)

If `pipeline` exists, optionally show:
- `Governance` (governance_* fields)
- `Chunking` (chunk_size/overlap/strategy params)
- `Indexing` (bm25/vector/kg/entity/event flags)
- `Tables / TAG` (table_store_* fields)

### Layout choice

Use existing `GraphViewer` (ForceGraph2D) in `tree` mode for stable readability.

## Node Details

Selecting a node populates the detail pane with:

- Title: node label
- Summary: small list of derived facts (counts, key toggles, selected defaults)
- JSON: the underlying object for that node, formatted with `JSON.stringify(..., null, 2)`
- Copy JSON button

## Safety / Error Handling

- Import requires an explicit confirmation dialog (because `replace=true` is destructive).
- Import parse errors show a toast with actionable text.
- Import network errors show a toast with formatted API errors.
- After successful import:
  - Show success toast
  - Reload export and re-render graph

## Testing (Web)

- Implement graph building as a pure function (`DatasetConfigBundle -> {nodes, links}`) in `web/lib/`.
- Add `vitest` unit tests that validate:
  - Empty bundle produces stable base nodes and edges
  - Presence of `pipeline` adds expected pipeline sub-nodes
  - Presence of `ingestion_policy` is reflected in summary/metadata

## Follow-Ups

- Editable nodes and incremental patching UX
- Per-rule expansion of ingestion policy
- Import diff preview and/or rollback support
