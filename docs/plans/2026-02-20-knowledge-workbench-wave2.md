# Knowledge Workbench Wave 2 (Actions + Import Menu) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Reduce `/knowledge` page complexity and improve header usability by consolidating all import/config actions into a single `导入/新增` dropdown, extracting heavy dialogs into dedicated components, and keeping the docs work-surface performant (no pagination changes).

**Architecture:** Keep Wave 1 workbench IA (Left scope, Main docs, Right inspector). Move “header actions + import dialogs” into a dedicated component (`KnowledgeWorkbenchActions`) and a small import subfolder under `web/components/knowledge/import/*`. Dialog components own their internal form state and reset on close.

**Tech Stack:** Next.js (App Router), React 19, Tailwind v4, Radix UI (Dialog/DropdownMenu), TanStack Virtual, Vitest.

---

## Conventions / Quality Gates

Run from repo root:
- `pnpm -C web -s lint`
- `pnpm -C web -s typecheck`
- `pnpm -C web -s test`
- `pnpm -C web -s verify`

Testing style:
- Prefer source tests for structural/guard assertions (`*.source.test.ts`).

---

## Primary: Knowledge Workbench Actions + Import Menu

### Task 1: Add `KnowledgeWorkbenchActions` Skeleton + Guard Test

**Files:**
- Create: `web/components/knowledge/knowledge-workbench-actions.tsx`
- Test: `web/components/knowledge/knowledge-workbench-actions.source.test.ts`

**Step 1: Write the failing test**
- Source test asserts:
  - exports `KnowledgeWorkbenchActions`
  - uses Radix `DropdownMenu` (or repository wrapper if present)
  - contains the trigger label `导入/新增`

**Step 2: Run test to verify it fails**
- `pnpm -C web -s test -- knowledge-workbench-actions.source.test.ts`
- Expected: FAIL (module missing)

**Step 3: Implement minimal skeleton**
- Render a dropdown trigger button with label `导入/新增`.
- Keep props minimal for now (no dialogs yet).

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-workbench-actions.source.test.ts`
- Expected: PASS

**Step 5: Commit**
```bash
git add web/components/knowledge/knowledge-workbench-actions.tsx web/components/knowledge/knowledge-workbench-actions.source.test.ts
git commit -m "feat(knowledge): add workbench actions skeleton"
```

---

### Task 2: Add `KnowledgeImportMenu` (Dropdown Structure) + Guard Test

**Files:**
- Create: `web/components/knowledge/import/knowledge-import-menu.tsx`
- Test: `web/components/knowledge/import/knowledge-import-menu.source.test.ts`

**Step 1: Write failing test**
- Assert menu includes items (by label text):
  - `上传文件`
  - `通过 URL`
  - `URL 批量（Connector）`
  - `Website Crawl`
  - `管线配置`

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-import-menu.source.test.ts`

**Step 3: Implement minimal menu**
- Use Radix `DropdownMenu*` primitives.
- Provide groups + separators (Add / Import / Config).
- Export `KnowledgeImportMenu` as a presentational component.

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-import-menu.source.test.ts`

**Step 5: Commit**
```bash
git add web/components/knowledge/import/knowledge-import-menu.tsx web/components/knowledge/import/knowledge-import-menu.source.test.ts
git commit -m "feat(knowledge): add import menu dropdown structure"
```

---

### Task 3: Extract Pipeline Config Dialog Component

**Files:**
- Create: `web/components/knowledge/import/knowledge-pipeline-config-dialog.tsx`
- Modify: `web/components/knowledge/knowledge-page.tsx`
- Test: `web/components/knowledge/import/knowledge-pipeline-config-dialog.source.test.ts`

**Step 1: Write failing test**
- Assert the dialog module exports `KnowledgePipelineConfigDialog`.
- Assert it contains `入库管线配置` and renders `PipelineOptionsPanel`.

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-pipeline-config-dialog.source.test.ts`

**Step 3: Implement dialog component**
- Move the existing “管线配置” dialog block out of `knowledge-page.tsx`.
- Keep it self-contained; use existing preference contexts for parser backend / chunk strategy.

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-pipeline-config-dialog.source.test.ts`

**Step 5: Commit**
```bash
git add web/components/knowledge/import/knowledge-pipeline-config-dialog.tsx web/components/knowledge/knowledge-page.tsx web/components/knowledge/import/knowledge-pipeline-config-dialog.source.test.ts
git commit -m "refactor(knowledge): extract pipeline config dialog"
```

---

### Task 4: Extract URL Import Dialog Component

**Files:**
- Create: `web/components/knowledge/import/knowledge-url-import-dialog.tsx`
- Modify: `web/components/knowledge/knowledge-page.tsx`
- Test: `web/components/knowledge/import/knowledge-url-import-dialog.source.test.ts`

**Step 1: Write failing test**
- Asserts module exports `KnowledgeUrlImportDialog`.
- Asserts it calls `uploadDocumentFromUrl` (string guard).

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-url-import-dialog.source.test.ts`

**Step 3: Implement dialog component**
- Own internal state (`open`, `url`, `filename`, `datasetId`, `submitting`).
- Accept props for `datasets`, `datasetsLoading`, `selectedDatasetId`, and `DATASET_DEFAULT` semantics.
- On success: toast + close + clear fields, and call `onAfterImport()` callback.

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-url-import-dialog.source.test.ts`

**Step 5: Commit**
```bash
git add web/components/knowledge/import/knowledge-url-import-dialog.tsx web/components/knowledge/knowledge-page.tsx web/components/knowledge/import/knowledge-url-import-dialog.source.test.ts
git commit -m "refactor(knowledge): extract url import dialog"
```

---

### Task 5: Extract URL Batch (Connector) Dialog Component

**Files:**
- Create: `web/components/knowledge/import/knowledge-url-batch-dialog.tsx`
- Modify: `web/components/knowledge/knowledge-page.tsx`
- Test: `web/components/knowledge/import/knowledge-url-batch-dialog.source.test.ts`

**Step 1: Write failing test**
- Asserts module exports `KnowledgeUrlBatchDialog`.
- Asserts it calls `connectorApi.createRun` (string guard).

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-url-batch-dialog.source.test.ts`

**Step 3: Implement dialog component**
- Own internal state (urls text, filename, dataset id, access mode/members, submitting).
- Reuse the existing parsing helpers (move helpers into this module if they are only used here).
- On success: close, reset, toast, call `onAfterRunCreated()`.

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-url-batch-dialog.source.test.ts`

**Step 5: Commit**
```bash
git add web/components/knowledge/import/knowledge-url-batch-dialog.tsx web/components/knowledge/knowledge-page.tsx web/components/knowledge/import/knowledge-url-batch-dialog.source.test.ts
git commit -m "refactor(knowledge): extract url batch connector dialog"
```

---

### Task 6: Extract Website Crawl Dialog Component

**Files:**
- Create: `web/components/knowledge/import/knowledge-web-crawl-dialog.tsx`
- Modify: `web/components/knowledge/knowledge-page.tsx`
- Test: `web/components/knowledge/import/knowledge-web-crawl-dialog.source.test.ts`

**Step 1: Write failing test**
- Asserts module exports `KnowledgeWebCrawlDialog`.
- Asserts it references connector id `web_crawl` and calls `connectorApi.createRun`.

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-web-crawl-dialog.source.test.ts`

**Step 3: Implement dialog component**
- Own internal state (seed URLs, limits, discovery toggles, auth, dataset, access, submitting).
- Keep behavior identical to existing dialog.
- On success: reset, toast, call `onAfterRunCreated()`.

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-web-crawl-dialog.source.test.ts`

**Step 5: Commit**
```bash
git add web/components/knowledge/import/knowledge-web-crawl-dialog.tsx web/components/knowledge/knowledge-page.tsx web/components/knowledge/import/knowledge-web-crawl-dialog.source.test.ts
git commit -m "refactor(knowledge): extract web crawl connector dialog"
```

---

### Task 7: Consolidate Header Actions Into `导入/新增` Dropdown

**Files:**
- Modify: `web/components/knowledge/knowledge-workbench-actions.tsx`
- Modify: `web/components/knowledge/knowledge-page.tsx`
- Test: `web/components/knowledge/knowledge-page.actions.source.test.ts`

**Step 1: Write failing test**
- Assert `knowledge-page.tsx` renders `<KnowledgeWorkbenchActions`.
- Assert `knowledge-page.tsx` no longer contains key inline dialog markers:
  - `通过 URL 导入文档`
  - `URL 批量导入（Connector）`
  - `Website Crawl (Connector)`

**Step 2: Run failing test**
- `pnpm -C web -s test -- knowledge-page.actions.source.test.ts`

**Step 3: Implement integration**
- `KnowledgeWorkbenchActions` composes:
  - `KnowledgeImportMenu`
  - `KnowledgePipelineConfigDialog`
  - `KnowledgeUrlImportDialog`
  - `KnowledgeUrlBatchDialog`
  - `KnowledgeWebCrawlDialog`
  - Hidden `<input type="file" multiple accept={UPLOAD_ACCEPT}>` for upload.
- Wire callbacks to refresh documents and connector runs best-effort.
- Replace `WorkbenchScaffold.actions` inline blocks with the new component.

**Step 4: Run tests**
- `pnpm -C web -s test -- knowledge-page.actions.source.test.ts`

**Step 5: Commit**
```bash
git add web/components/knowledge/knowledge-workbench-actions.tsx web/components/knowledge/knowledge-page.tsx web/components/knowledge/knowledge-page.actions.source.test.ts
git commit -m "refactor(knowledge): consolidate import actions into dropdown"
```

---

### Task 8: Web Verify Gate

**Files:**
- None (verification)

**Step 1: Run**
- `pnpm -C web -s verify`

**Step 2: Fix any failures**
- Keep fixes narrow; add source tests if missing guards are discovered.

**Step 3: Commit**
- Commit any required fixes with narrow messages.

---

## Issue Tracking + Landing

### Task 9: File/Update bd Issue + Sync

**Step 1: Create or update issue**
- Create a new epic or task (Wave 2) and link to this plan/design.

**Step 2: Sync**
- `bd sync`

**Step 3: Commit**
- `git add .beads/issues.jsonl`
- `git commit -m "bd sync"`

---

### Task 10: Land the Plane (Merge to main + Push)

Follow repo policy:
```bash
git pull --rebase
bd sync
git push
git status
```

