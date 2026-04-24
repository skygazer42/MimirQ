# Ingestion UI Enhancement Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement the approved `/knowledge/ingestion` UI enhancements for velocity, error filtering, sparklines, empty states, bulk actions, drag-and-drop upload, stage tooltips, and first-load skeletons without backend changes.

**Architecture:** Keep `web/app/knowledge/ingestion/page-client.tsx` as the orchestration layer while extracting reusable ingestion-specific UI into focused components under `web/components/ingestion/`. Put data-derivation and concurrency helpers in a shared ingestion utility module so the core behaviors are testable with real unit tests instead of only source-string checks.

**Tech Stack:** Next.js App Router, React 19, TanStack Query v5, Recharts, Radix UI (`dialog`, `sheet`, `tooltip`, `checkbox`), Vitest, Tailwind CSS.

---

### Task 1: Add failing tests for shared ingestion monitor helpers

**Files:**
- Create: `web/components/ingestion/monitor-utils.test.ts`
- Create: `web/components/ingestion/monitor-utils.ts`

**Step 1: Write the failing test**

Add tests for:
- docs/min from the last five real buckets
- MB/s from recently completed documents
- bulk action enablement from selected statuses
- CSV export field order
- concurrency-limited task execution

**Step 2: Run test to verify it fails**

Run: `pnpm test web/components/ingestion/monitor-utils.test.ts`
Expected: FAIL because `monitor-utils.ts` exports do not exist yet.

**Step 3: Write minimal implementation**

Implement helper exports for:
- `computeDocsPerMinute`
- `computeMegabytesPerSecond`
- `getBulkActionAvailability`
- `serializeDocumentsToCsv`
- `runWithConcurrencyLimit`

**Step 4: Run test to verify it passes**

Run: `pnpm test web/components/ingestion/monitor-utils.test.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add web/components/ingestion/monitor-utils.ts web/components/ingestion/monitor-utils.test.ts
git commit -m "Add testable ingestion monitor helpers"
```

### Task 2: Add failing source tests for extracted ingestion UI components

**Files:**
- Create: `web/components/ingestion/stat-card.source.test.ts`
- Create: `web/components/ingestion/live-velocity.source.test.ts`
- Create: `web/components/ingestion/error-treemap.source.test.ts`
- Create: `web/components/ingestion/bulk-action-bar.source.test.ts`
- Create: `web/components/ingestion/drop-zone.source.test.ts`
- Create: `web/components/ingestion/empty-state.source.test.ts`
- Modify: `web/app/knowledge/ingestion/page-client.task-cards.source.test.ts`
- Modify: `web/app/knowledge/ingestion/page-client.layout.source.test.ts`

**Step 1: Write the failing test**

Assert the source-level markers for:
- sparkline rendering and placeholder mode
- localStorage-backed velocity chip
- clickable treemap with selected-cell state
- bulk bar buttons and delete-count confirmation
- forward-ref drop zone with shared upload pipeline
- truly-empty vs filter-empty split
- page-level selection and extracted component usage

**Step 2: Run test to verify it fails**

Run: `pnpm test web/components/ingestion/*.source.test.ts web/app/knowledge/ingestion/page-client*.source.test.ts`
Expected: FAIL because the component files and page wiring are not present yet.

**Step 3: Write minimal implementation**

Create the component files with the required exported props, accessibility attributes, and source markers.

**Step 4: Run test to verify it passes**

Run: `pnpm test web/components/ingestion/*.source.test.ts web/app/knowledge/ingestion/page-client*.source.test.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add web/components/ingestion/*.tsx web/components/ingestion/*.source.test.ts web/app/knowledge/ingestion/page-client*.source.test.ts
git commit -m "Extract ingestion monitor UI components"
```

### Task 3: Implement stat cards, velocity chip, empty states, and first-load skeleton

**Files:**
- Modify: `web/app/knowledge/ingestion/page-client.tsx`
- Create: `web/components/ingestion/stat-card.tsx`
- Create: `web/components/ingestion/live-velocity.tsx`
- Create: `web/components/ingestion/empty-state.tsx`

**Step 1: Write the failing test**

Use the Task 1 and Task 2 tests as the red phase for this slice.

**Step 2: Run test to verify it fails**

Run: `pnpm test web/components/ingestion/monitor-utils.test.ts web/components/ingestion/stat-card.source.test.ts web/components/ingestion/live-velocity.source.test.ts web/components/ingestion/empty-state.source.test.ts web/app/knowledge/ingestion/page-client*.source.test.ts`
Expected: FAIL until the new components are wired into the page.

**Step 3: Write minimal implementation**

Implement:
- localStorage-backed velocity chip
- stat cards with inline sparkline or placeholder stroke
- truly-empty CTA block and filter-empty fallback
- skeleton layout for initial loading
- `placeholderData: keepPreviousData` on the dashboard query

**Step 4: Run test to verify it passes**

Run the same targeted test command.

**Step 5: Commit**

```bash
git add web/app/knowledge/ingestion/page-client.tsx web/components/ingestion/stat-card.tsx web/components/ingestion/live-velocity.tsx web/components/ingestion/empty-state.tsx
git commit -m "Add velocity, sparkline, empty, and skeleton states"
```

### Task 4: Implement treemap filtering, selection model, and bulk action bar

**Files:**
- Modify: `web/app/knowledge/ingestion/page-client.tsx`
- Create: `web/components/ingestion/error-treemap.tsx`
- Create: `web/components/ingestion/bulk-action-bar.tsx`

**Step 1: Write the failing test**

Use the source tests plus helper tests as the red phase for:
- `reasonFilter`
- `selection` state
- select-all / clear
- delete confirmation by count
- bulk action enablement

**Step 2: Run test to verify it fails**

Run: `pnpm test web/components/ingestion/error-treemap.source.test.ts web/components/ingestion/bulk-action-bar.source.test.ts web/app/knowledge/ingestion/page-client.task-cards.source.test.ts web/components/ingestion/monitor-utils.test.ts`
Expected: FAIL until the page wires selection and treemap callbacks.

**Step 3: Write minimal implementation**

Implement:
- treemap click-to-filter behavior
- reason filter chip beside search
- task-row checkboxes and ESC clear
- fixed bulk action toolbar
- bulk retry/cancel/delete/export flows with `Promise.allSettled`

**Step 4: Run test to verify it passes**

Run the same targeted test command.

**Step 5: Commit**

```bash
git add web/app/knowledge/ingestion/page-client.tsx web/components/ingestion/error-treemap.tsx web/components/ingestion/bulk-action-bar.tsx
git commit -m "Add ingestion treemap filters and bulk actions"
```

### Task 5: Implement drag-and-drop upload and stage tooltip polish

**Files:**
- Modify: `web/app/knowledge/ingestion/page-client.tsx`
- Create: `web/components/ingestion/drop-zone.tsx`
- Modify: `web/components/ui/dialog.tsx`

**Step 1: Write the failing test**

Use the drop-zone source test plus page source tests as the red phase.

**Step 2: Run test to verify it fails**

Run: `pnpm test web/components/ingestion/drop-zone.source.test.ts web/app/knowledge/ingestion/page-client*.source.test.ts`
Expected: FAIL until document-level drag listeners, dialog flow, and tooltip wrapping are present.

**Step 3: Write minimal implementation**

Implement:
- document-level drag listeners
- forward-ref `DropZoneHandle`
- dataset-aware upload path
- dataset picker dialog fallback when URL lacks `dataset_id`
- stage tooltip wrapping for active progress badges

**Step 4: Run test to verify it passes**

Run the same targeted test command.

**Step 5: Commit**

```bash
git add web/app/knowledge/ingestion/page-client.tsx web/components/ingestion/drop-zone.tsx web/components/ui/dialog.tsx
git commit -m "Add ingestion drag-and-drop upload flow"
```

### Task 6: Run verification and capture remaining risks

**Files:**
- Modify: `web/app/knowledge/ingestion/page-client.tsx` (only if fixes are needed)
- Modify: `web/components/ingestion/*.tsx` (only if fixes are needed)

**Step 1: Run targeted tests**

Run:
- `pnpm test web/components/ingestion/monitor-utils.test.ts`
- `pnpm test web/components/ingestion/*.source.test.ts`
- `pnpm test web/app/knowledge/ingestion/page-client*.source.test.ts`

Expected: PASS

**Step 2: Run broader verification**

Run:
- `pnpm lint`
- `pnpm typecheck`
- `pnpm test web/app/knowledge/ingestion/page.source.test.ts web/app/knowledge/ingestion/page.loading-shell.source.test.ts`

Expected: PASS, or fix forward until green.

**Step 3: Run full verification if feasible**

Run: `pnpm verify`
Expected: PASS, or record the exact blocker if the workspace has unrelated failures.

**Step 4: Final report**

Report:
- changed files
- simplifications made
- verification evidence
- remaining risks
