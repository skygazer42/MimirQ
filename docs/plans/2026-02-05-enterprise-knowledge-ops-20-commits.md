# Enterprise Knowledge Ops (Tags + Duplicates + Batch ACL/Move) Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** 在不改后端核心逻辑的前提下，补齐企业级知识库运维能力：文档 Tags、重复文档治理（默认归档副本）、批量 ACL 更新与批量 Move（数据集间移动）。

**Architecture:** 前端为主（Next.js App Router）。在 `web/lib/` 提炼纯函数（tags 规范化、重复组决策），在 `web/components/knowledge/*` 封装批量对话框与 duplicates workbench；后端仅调用既有 API（`/documents/*`）。

**Tech Stack:** Next.js 14 + TypeScript + Tailwind + Radix/shadcn primitives；Vitest；后端 FastAPI（仅接口调用）。

**Commit rule (per user request):** **每完成一个 Task 就做一次 commit**，总计 20 个 tasks ≈ 20 commits。

---

### Task 1: Add design notes doc (DONE)

**Files:**
- Added: `docs/plans/2026-02-05-enterprise-knowledge-ops-20-commits-design.md`

**Commit:** already done.

---

### Task 2: Add this plan doc

**Files:**
- Create: `docs/plans/2026-02-05-enterprise-knowledge-ops-20-commits.md`

**Commit:**
```bash
git add docs/plans/2026-02-05-enterprise-knowledge-ops-20-commits.md
git commit -m "docs(plans): add enterprise knowledge ops plan (20 commits)"
```

---

### Task 3: Add tag normalization + patch helpers (pure) with tests

**Files:**
- Create: `web/lib/document-user-tags.ts`
- Test: `web/lib/document-user-tags.test.ts`

**Steps:**
1. Implement helpers:
   - `parseTagsText(text): string[]` (split by newline/comma/semicolon; trim; uniq; limit count/length)
   - `getUserTagsFromDocument(doc): string[]` (safe read from `doc.metadata.user.tags`)
   - `buildTagsPatch(nextTags): { patch: { tags: string[] | null }, replace: false }`
2. Add vitest covering parse/uniq/removal semantics.

**Verify:**
```bash
cd web && pnpm run test -- lib/document-user-tags.test.ts
```

**Commit:**
```bash
git add web/lib/document-user-tags.ts web/lib/document-user-tags.test.ts
git commit -m "feat(tags): add tag utils for document metadata.user"
```

---

### Task 4: Add TagInput UI primitive (no new behavior primitives)

**Files:**
- Create: `web/components/ui/tag-input.tsx`

**Notes:**
- Use existing `Input`, `Badge`, `Button`, `IconButton` patterns.
- Keyboard: Enter adds tag; Backspace on empty input removes last tag (optional).
- Always provide `aria-label` for icon-only remove buttons.

**Commit:**
```bash
git add web/components/ui/tag-input.tsx
git commit -m "feat(ui): add TagInput component"
```

---

### Task 5: Add DocumentTags display component (pills)

**Files:**
- Create: `web/components/documents/document-tags.tsx`

**Commit:**
```bash
git add web/components/documents/document-tags.tsx
git commit -m "feat(tags): add DocumentTags display pills"
```

---

### Task 6: DocumentDetailDialog supports viewing + editing tags

**Files:**
- Modify: `web/components/document-detail-dialog.tsx`

**Steps:**
1. Read current tags from `detail?.metadata?.user?.tags`.
2. Add a small “Tags” section:
   - display tags (pills)
   - “编辑” toggles TagInput
   - “保存” calls `documentApi.patchUserMetadata(id, { patch: { tags }, replace: false })`
3. On save success: refresh detail (and keep dialog open).

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/document-detail-dialog.tsx
git commit -m "feat(document): edit tags via metadata.user.tags"
```

---

### Task 7: Knowledge grid cards show tags

**Files:**
- Modify: `web/app/knowledge/page.tsx`

**Commit:**
```bash
git add web/app/knowledge/page.tsx
git commit -m "feat(knowledge): show document tags on cards"
```

---

### Task 8: Knowledge list table shows tags column

**Files:**
- Modify: `web/app/knowledge/page.tsx`

**Commit:**
```bash
git add web/app/knowledge/page.tsx
git commit -m "feat(knowledge): add tags column in list view"
```

---

### Task 9: Knowledge tag filter (multi-select) + URL param

**Files:**
- Modify: `web/app/knowledge/page.tsx`

**Behavior:**
- Add a Tags filter popover; select multiple tags (AND semantics).
- Persist to URL (e.g. `?tags=foo,bar`) and restore on load.
- Filter is client-side (on loaded list) for this round.

**Commit:**
```bash
git add web/app/knowledge/page.tsx
git commit -m "feat(knowledge): add tag filter for documents"
```

---

### Task 10: Bulk tags dialog (replace/append/remove) with progress + safe limit

**Files:**
- Create: `web/components/knowledge/bulk-tags-dialog.tsx`
- Modify: `web/app/knowledge/page.tsx`

**Notes:**
- Replace can use `batch/metadata`; append/remove uses per-doc patch (concurrency-limited).
- Default max selected for per-doc mode: 50 (warn otherwise).

**Commit:**
```bash
git add web/components/knowledge/bulk-tags-dialog.tsx web/app/knowledge/page.tsx
git commit -m "feat(knowledge): bulk edit document tags"
```

---

### Task 11: Bulk access update dialog (batch/access)

**Files:**
- Create: `web/components/knowledge/bulk-access-dialog.tsx`
- Modify: `web/app/knowledge/page.tsx`

**Commit:**
```bash
git add web/components/knowledge/bulk-access-dialog.tsx web/app/knowledge/page.tsx
git commit -m "feat(knowledge): bulk update document access"
```

---

### Task 12: Bulk move dialog (batch/move) with conflicts mapping

**Files:**
- Create: `web/components/knowledge/bulk-move-dialog.tsx`
- Modify: `web/app/knowledge/page.tsx`

**Notes:**
- Conflicts returned by backend are mapped back to filenames for operator clarity.

**Commit:**
```bash
git add web/components/knowledge/bulk-move-dialog.tsx web/app/knowledge/page.tsx
git commit -m "feat(knowledge): bulk move documents across datasets"
```

---

### Task 13: Add navbar entry for duplicates page

**Files:**
- Modify: `web/components/navbar.tsx`

**Commit:**
```bash
git add web/components/navbar.tsx
git commit -m "feat(nav): add duplicates entry under knowledge ops"
```

---

### Task 14: Add duplicates page scaffold + workbench component

**Files:**
- Create: `web/app/knowledge/duplicates/page.tsx`
- Create: `web/components/knowledge/duplicates-workbench.tsx`

**Commit:**
```bash
git add web/app/knowledge/duplicates/page.tsx web/components/knowledge/duplicates-workbench.tsx
git commit -m "feat(duplicates): add page scaffold"
```

---

### Task 15: Duplicates scan controls (dataset selector + params) + listDuplicates integration

**Files:**
- Modify: `web/components/knowledge/duplicates-workbench.tsx`

**Commit:**
```bash
git add web/components/knowledge/duplicates-workbench.tsx
git commit -m "feat(duplicates): scan duplicates by file_sha256"
```

---

### Task 16: Duplicates group rendering + per-group "keep newest + archive others"

**Files:**
- Modify: `web/components/knowledge/duplicates-workbench.tsx`

**Notes:**
- Default keep: newest `created_at`.
- Action uses `AlertDialog` and `documentApi.batchArchive`.

**Commit:**
```bash
git add web/components/knowledge/duplicates-workbench.tsx
git commit -m "feat(duplicates): archive other copies per group (safe default)"
```

---

### Task 17: Write ops markers to metadata.user for archived duplicates (best-effort)

**Files:**
- Modify: `web/components/knowledge/duplicates-workbench.tsx`

**Markers (example):**
- `duplicate_of: <kept_doc_id>`
- `duplicate_sha256: <sha>`
- `dedup_archived_at: <iso>`

**Commit:**
```bash
git add web/components/knowledge/duplicates-workbench.tsx
git commit -m "feat(duplicates): annotate archived duplicates in metadata.user"
```

---

### Task 18: "Archive all groups" sweep with progress + guardrails

**Files:**
- Modify: `web/components/knowledge/duplicates-workbench.tsx`

**Guardrails:**
- Show total to archive before executing.
- Default cap (e.g. 200) unless explicit confirmation.

**Commit:**
```bash
git add web/components/knowledge/duplicates-workbench.tsx
git commit -m "feat(duplicates): sweep archive across all groups"
```

---

### Task 19: Add tests for ops helpers (tags + duplicates planning)

**Files:**
- Create: `web/lib/duplicates-planner.ts`
- Test: `web/lib/duplicates-planner.test.ts`

**Verify:**
```bash
cd web && pnpm run test -- lib/duplicates-planner.test.ts
```

**Commit:**
```bash
git add web/lib/duplicates-planner.ts web/lib/duplicates-planner.test.ts
git commit -m "test(ops): add duplicates planning helpers"
```

---

### Task 20: Add operator guide (docs)

**Files:**
- Create: `docs/guides/document_tags_and_duplicates.md`
- (Optional) Modify: `docs/README.md` (link)

**Verify:**
```bash
cd web && pnpm run verify
```

**Commit:**
```bash
git add docs/guides/document_tags_and_duplicates.md docs/README.md
git commit -m "docs(guides): document tags + duplicates ops workflow"
```

