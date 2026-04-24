# Ingestion Control Room Redesign Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Rebuild `/knowledge/ingestion` into a production-style control room with a left task drawer, centered visual canvas, topology mode, richer empty state guidance, and drag-resizable layout behavior.

**Architecture:** Keep the data-fetching and mutation orchestration in `web/app/knowledge/ingestion/page-client.tsx`, but pivot the page layout into a two-pane control-room shell: task rail on the left, main canvas on the right. Extend `web/components/ingestion/monitor-utils.ts` with ETA/load helpers, and upgrade `web/components/ingestion/empty-state.tsx` to render a workflow-style onboarding state instead of a plain CTA card.

**Tech Stack:** Next.js App Router, React 19, TanStack Query v5, Recharts, Tailwind CSS, existing ingestion UI components, Vitest source tests.

---

### Task 1: Add failing tests for control-room helpers and layout markers

**Files:**
- Modify: `web/components/ingestion/monitor-utils.test.ts`
- Modify: `web/app/knowledge/ingestion/page-client.layout.source.test.ts`
- Modify: `web/app/knowledge/ingestion/page-client.task-cards.source.test.ts`
- Modify: `web/components/ingestion/empty-state.source.test.ts`

**Step 1: Write the failing test**

Add assertions for:
- remaining processing ETA from queue size and throughput
- approximate engine load score
- left task drawer state/width markers
- central control-room canvas markers
- Treemap click expanding the task drawer
- linear empty-state workflow steps

**Step 2: Run test to verify it fails**

Run: `pnpm test components/ingestion/monitor-utils.test.ts app/knowledge/ingestion/page-client.layout.source.test.ts app/knowledge/ingestion/page-client.task-cards.source.test.ts components/ingestion/empty-state.source.test.ts`
Expected: FAIL because the helper exports and new layout markers do not exist yet.

**Step 3: Write minimal implementation**

Create the helper exports and source markers needed by the new control-room layout.

**Step 4: Run test to verify it passes**

Run the same test command.

**Step 5: Commit**

```bash
git add web/components/ingestion/monitor-utils.test.ts web/app/knowledge/ingestion/page-client.layout.source.test.ts web/app/knowledge/ingestion/page-client.task-cards.source.test.ts web/components/ingestion/empty-state.source.test.ts
git commit -m "Define control-room ingestion red-phase tests"
```

### Task 2: Implement control-room utility helpers

**Files:**
- Modify: `web/components/ingestion/monitor-utils.ts`
- Modify: `web/components/ingestion/monitor-utils.test.ts`

**Step 1: Write the failing test**

Use Task 1 tests as the red phase.

**Step 2: Run test to verify it fails**

Run: `pnpm test components/ingestion/monitor-utils.test.ts`
Expected: FAIL until ETA and load helpers exist.

**Step 3: Write minimal implementation**

Implement:
- `computeRemainingMinutesEstimate`
- `computeEngineLoadScore`
- `getDocumentKind`
- `getDocumentKindAccent`

**Step 4: Run test to verify it passes**

Run: `pnpm test components/ingestion/monitor-utils.test.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add web/components/ingestion/monitor-utils.ts web/components/ingestion/monitor-utils.test.ts
git commit -m "Add ingestion control-room helper logic"
```

### Task 3: Upgrade the empty state into a workflow guide

**Files:**
- Modify: `web/components/ingestion/empty-state.tsx`
- Modify: `web/components/ingestion/empty-state.source.test.ts`

**Step 1: Write the failing test**

Use the updated source test as the red phase.

**Step 2: Run test to verify it fails**

Run: `pnpm test components/ingestion/empty-state.source.test.ts`
Expected: FAIL until the workflow-guide layout is present.

**Step 3: Write minimal implementation**

Render a control-room onboarding state with linear ingestion steps and the existing CTA path.

**Step 4: Run test to verify it passes**

Run: `pnpm test components/ingestion/empty-state.source.test.ts`
Expected: PASS

**Step 5: Commit**

```bash
git add web/components/ingestion/empty-state.tsx web/components/ingestion/empty-state.source.test.ts
git commit -m "Upgrade ingestion empty state to workflow guide"
```

### Task 4: Rebuild the page layout into task drawer + main canvas

**Files:**
- Modify: `web/app/knowledge/ingestion/page-client.tsx`
- Modify: `web/app/knowledge/ingestion/page-client.layout.source.test.ts`
- Modify: `web/app/knowledge/ingestion/page-client.task-cards.source.test.ts`

**Step 1: Write the failing test**

Use the updated page source tests as the red phase.

**Step 2: Run test to verify it fails**

Run: `pnpm test app/knowledge/ingestion/page-client.layout.source.test.ts app/knowledge/ingestion/page-client.task-cards.source.test.ts`
Expected: FAIL until task drawer state, resize handle, and control-room canvas markers are present.

**Step 3: Write minimal implementation**

Implement:
- left task drawer with collapse/expand behavior
- drag-resizable rail width
- sticky glass aggregate strip
- main chart + treemap control-room card
- topology mode toggle
- hover preview panel in the canvas
- Treemap click forcing drawer expansion and filtering

**Step 4: Run test to verify it passes**

Run the same source-test command.

**Step 5: Commit**

```bash
git add web/app/knowledge/ingestion/page-client.tsx web/app/knowledge/ingestion/page-client.layout.source.test.ts web/app/knowledge/ingestion/page-client.task-cards.source.test.ts
git commit -m "Rebuild ingestion page as control-room layout"
```

### Task 5: Verify the redesigned ingestion page

**Files:**
- Modify: `web/app/knowledge/ingestion/page-client.tsx` (only if fixes are needed)
- Modify: `web/components/ingestion/empty-state.tsx` (only if fixes are needed)
- Modify: `web/components/ingestion/monitor-utils.ts` (only if fixes are needed)

**Step 1: Run targeted tests**

Run:
- `pnpm test components/ingestion/monitor-utils.test.ts`
- `pnpm test components/ingestion/empty-state.source.test.ts`
- `pnpm test app/knowledge/ingestion/page-client.layout.source.test.ts app/knowledge/ingestion/page-client.task-cards.source.test.ts`

Expected: PASS

**Step 2: Run file-level quality checks**

Run:
- `pnpm exec eslint app/knowledge/ingestion/page-client.tsx components/ingestion/monitor-utils.ts components/ingestion/empty-state.tsx`

Expected: PASS

**Step 3: Run broader ingestion checks**

Run:
- `pnpm test app/knowledge/ingestion/page.source.test.ts app/knowledge/ingestion/page.loading-shell.source.test.ts`

Expected: PASS

**Step 4: Final report**

Report:
- what changed visually
- what interactions are now available
- verification evidence
- remaining gaps versus the full 20-point wishlist
