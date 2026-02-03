# UI + API Polish (Round 4) Implementation Plan

> **For Codex/Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** 20 small commits to improve Baseline UI compliance (replace `confirm()` with `AlertDialog`, remove remaining `transition-all`) while keeping FE/BE integration stable.

**Architecture:** Keep changes localized to UI interaction surfaces (buttons/menus/dialogs). Do not change backend behavior. Maintain verification gates: `make enterprise-checks`.

**Tech Stack:** Next.js 14 + TypeScript + Tailwind + Radix/shadcn primitives; FastAPI backend; OpenAPI typegen.

---

### Task 1: Add round 4 design notes

**Files:**
- Create: `docs/plans/2026-02-03-ui-api-polish-round-4-design.md`

**Commit:**
```bash
git add docs/plans/2026-02-03-ui-api-polish-round-4-design.md
git commit -m "docs(plans): add UI+API polish round 4 design notes"
```

---

### Task 2: Add this plan document

**Files:**
- Create: `docs/plans/2026-02-03-ui-api-polish-round-4.md`

**Commit:**
```bash
git add docs/plans/2026-02-03-ui-api-polish-round-4.md
git commit -m "docs(plans): add UI+API polish round 4 plan"
```

---

### Task 3: Graph explainability steps: avoid `transition-all`

**Files:**
- Modify: `web/app/graph/page.tsx`

**Commit:**
```bash
git add web/app/graph/page.tsx
git commit -m "style(graph): explainability steps avoid transition-all"
```

---

### Task 4: Graph delete node: replace `confirm()` with `AlertDialog`

**Files:**
- Modify: `web/app/graph/page.tsx`

**Commit:**
```bash
git add web/app/graph/page.tsx
git commit -m "a11y(graph): node delete uses AlertDialog"
```

---

### Task 5: Prompts batch delete: replace `confirm()` with `AlertDialog`

**Files:**
- Modify: `web/app/prompts/page.tsx`

**Commit:**
```bash
git add web/app/prompts/page.tsx
git commit -m "a11y(prompts): batch delete uses AlertDialog"
```

---

### Task 6: Prompts single delete: replace `confirm()` with `AlertDialog`

**Files:**
- Modify: `web/app/prompts/page.tsx`

**Commit:**
```bash
git add web/app/prompts/page.tsx
git commit -m "a11y(prompts): delete action uses AlertDialog"
```

---

### Task 7: Knowledge connector run cancel: replace `confirm()` with `AlertDialog`

**Files:**
- Modify: `web/app/knowledge/page.tsx`

**Commit:**
```bash
git add web/app/knowledge/page.tsx
git commit -m "a11y(knowledge): cancel run uses AlertDialog"
```

---

### Task 8: Knowledge connector run retry/resume: replace `confirm()` with `AlertDialog`

**Files:**
- Modify: `web/app/knowledge/page.tsx`

**Commit:**
```bash
git add web/app/knowledge/page.tsx
git commit -m "a11y(knowledge): retry/resume uses AlertDialog"
```

---

### Task 9: Settings URL ingest toggles: replace `confirm()` with `AlertDialog`

**Files:**
- Modify: `web/app/settings/page.tsx`

**Commit:**
```bash
git add web/app/settings/page.tsx
git commit -m "a11y(settings): url ingest toggles use AlertDialog"
```

---

### Task 10: Governance panel delete file: replace `confirm()` with `AlertDialog`

**Files:**
- Modify: `web/components/data-governance-panel.tsx`

**Commit:**
```bash
git add web/components/data-governance-panel.tsx
git commit -m "a11y(governance): file delete uses AlertDialog"
```

---

### Task 11: Governance panel remove file record: replace `confirm()` with `AlertDialog`

**Files:**
- Modify: `web/components/data-governance-panel.tsx`

**Commit:**
```bash
git add web/components/data-governance-panel.tsx
git commit -m "a11y(governance): remove file record uses AlertDialog"
```

---

### Task 12: Quarantine delete doc: replace `confirm()` with `AlertDialog`

**Files:**
- Modify: `web/app/knowledge/quarantine/page.tsx`

**Commit:**
```bash
git add web/app/knowledge/quarantine/page.tsx
git commit -m "a11y(quarantine): delete doc uses AlertDialog"
```

---

### Task 13: Test case manager delete single: replace `confirm()` with `AlertDialog`

**Files:**
- Modify: `web/components/test-case-manager.tsx`

**Commit:**
```bash
git add web/components/test-case-manager.tsx
git commit -m "a11y(tests): delete case uses AlertDialog"
```

---

### Task 14: Test case manager delete bulk: replace `confirm()` with `AlertDialog`

**Files:**
- Modify: `web/components/test-case-manager.tsx`

**Commit:**
```bash
git add web/components/test-case-manager.tsx
git commit -m "a11y(tests): bulk delete uses AlertDialog"
```

---

### Task 15: Governance profiles delete: replace `confirm()` with `AlertDialog`

**Files:**
- Modify: `web/components/governance-profiles/governance-profiles-page.tsx`

**Commit:**
```bash
git add web/components/governance-profiles/governance-profiles-page.tsx
git commit -m "a11y(governance): profile delete uses AlertDialog"
```

---

### Task 16: Folder tree delete: replace `confirm()` with `AlertDialog`

**Files:**
- Modify: `web/components/document-library/folder-tree.tsx`

**Commit:**
```bash
git add web/components/document-library/folder-tree.tsx
git commit -m "a11y(library): folder delete uses AlertDialog"
```

---

### Task 17: Document detail switch version: replace `confirm()` with `AlertDialog`

**Files:**
- Modify: `web/components/document-detail-dialog.tsx`

**Commit:**
```bash
git add web/components/document-detail-dialog.tsx
git commit -m "a11y(viewer): switch pipeline version uses AlertDialog"
```

---

### Task 18: Document detail delete version + delete KG event: replace `confirm()` with `AlertDialog`

**Files:**
- Modify: `web/components/document-detail-dialog.tsx`

**Commit:**
```bash
git add web/components/document-detail-dialog.tsx
git commit -m "a11y(viewer): destructive actions use AlertDialog"
```

---

### Task 19: Document viewer delete chunk: replace `confirm()` with `AlertDialog`

**Files:**
- Modify: `web/components/document-viewer-panel.tsx`

**Commit:**
```bash
git add web/components/document-viewer-panel.tsx
git commit -m "a11y(viewer): delete chunk uses AlertDialog"
```

---

### Task 20: Conversation summary clear memory: replace `confirm()` with `AlertDialog`

**Files:**
- Modify: `web/components/chat/conversation-summary-dialog.tsx`

**Commit:**
```bash
git add web/components/chat/conversation-summary-dialog.tsx
git commit -m "a11y(chat): clear summary uses AlertDialog"
```

---

## Final Verification (after task 20)

```bash
make openapi-check
make enterprise-checks
```

