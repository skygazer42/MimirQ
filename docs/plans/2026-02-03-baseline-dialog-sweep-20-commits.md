# Baseline Dialog Sweep (20 Commits) Implementation Plan

> **For Codex/Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Replace remaining native browser dialogs (`confirm()` / `prompt()`) with Baseline UI dialogs, and keep FE/BE integration checks green, delivered as 20 small commits.

**Architecture:** No backend behavior changes. Frontend changes replace imperative `confirm/prompt` with `AlertDialog` / `Dialog` primitives. Add a lightweight `ui-check` guard to prevent regressions.

**Tech Stack:** Next.js 14 (App Router) + TypeScript + Tailwind + Radix/shadcn primitives; FastAPI backend; OpenAPI typegen (`openapi-typescript`).

---

### Task 1: Add design notes for this 20-commit round

**Files:**
- Create: `docs/plans/2026-02-03-baseline-dialog-sweep-20-commits-design.md`

**Commit:**
```bash
git add docs/plans/2026-02-03-baseline-dialog-sweep-20-commits-design.md
git commit -m "docs(plans): add baseline dialog sweep design notes (20 commits)"
```

---

### Task 2: Add this implementation plan

**Files:**
- Create: `docs/plans/2026-02-03-baseline-dialog-sweep-20-commits.md`

**Commit:**
```bash
git add docs/plans/2026-02-03-baseline-dialog-sweep-20-commits.md
git commit -m "docs(plans): add baseline dialog sweep plan (20 commits)"
```

---

### Task 3: Add reusable ConfirmDialog primitive (AlertDialog wrapper)

**Files:**
- Create: `web/components/ui/confirm-dialog.tsx`

**Steps:**
1. Provide a small wrapper around `AlertDialog` to standardize copy + button variants.
2. Support non-destructive confirmations (`confirmVariant="default"`) as needed.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/ui/confirm-dialog.tsx
git commit -m "feat(ui): add ConfirmDialog wrapper for safe confirmations"
```

---

### Task 4: Quarantine page delete: replace confirm() with ConfirmDialog

**Files:**
- Modify: `web/app/knowledge/quarantine/page.tsx`

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/app/knowledge/quarantine/page.tsx
git commit -m "a11y(quarantine): delete uses ConfirmDialog (no confirm())"
```

---

### Task 5: Conversation summary reset: replace window.confirm() with ConfirmDialog

**Files:**
- Modify: `web/components/chat/conversation-summary-dialog.tsx`

**Commit:**
```bash
git add web/components/chat/conversation-summary-dialog.tsx
git commit -m "a11y(chat): summary reset uses ConfirmDialog (no confirm())"
```

---

### Task 6: Governance profiles delete: replace window.confirm() with ConfirmDialog

**Files:**
- Modify: `web/components/governance-profiles/governance-profiles-page.tsx`

**Commit:**
```bash
git add web/components/governance-profiles/governance-profiles-page.tsx
git commit -m "a11y(governance): delete profile uses ConfirmDialog"
```

---

### Task 7: Document detail switch version: replace confirm() with ConfirmDialog (non-destructive)

**Files:**
- Modify: `web/components/document-detail-dialog.tsx`

**Commit:**
```bash
git add web/components/document-detail-dialog.tsx
git commit -m "a11y(doc-detail): version switch uses ConfirmDialog"
```

---

### Task 8: Document detail delete version: replace confirm() with ConfirmDialog

**Files:**
- Modify: `web/components/document-detail-dialog.tsx`

**Commit:**
```bash
git add web/components/document-detail-dialog.tsx
git commit -m "a11y(doc-detail): version delete uses ConfirmDialog"
```

---

### Task 9: Document detail delete KG event: replace confirm() with ConfirmDialog

**Files:**
- Modify: `web/components/document-detail-dialog.tsx`

**Commit:**
```bash
git add web/components/document-detail-dialog.tsx
git commit -m "a11y(doc-detail): kg event delete uses ConfirmDialog"
```

---

### Task 10: Viewer chunk delete: replace window.confirm() with ConfirmDialog

**Files:**
- Modify: `web/components/document-viewer-panel.tsx`

**Commit:**
```bash
git add web/components/document-viewer-panel.tsx
git commit -m "a11y(viewer): chunk delete uses ConfirmDialog"
```

---

### Task 11: Governance remove file record: replace confirm() with ConfirmDialog

**Files:**
- Modify: `web/components/data-governance-panel.tsx`

**Commit:**
```bash
git add web/components/data-governance-panel.tsx
git commit -m "a11y(governance): remove file record uses ConfirmDialog"
```

---

### Task 12: Folder tree delete: replace window.confirm() with ConfirmDialog

**Files:**
- Modify: `web/components/document-library/folder-tree.tsx`

**Commit:**
```bash
git add web/components/document-library/folder-tree.tsx
git commit -m "a11y(library): folder delete uses ConfirmDialog"
```

---

### Task 13: Test case delete: replace confirm() with ConfirmDialog

**Files:**
- Modify: `web/components/test-case-manager.tsx`

**Commit:**
```bash
git add web/components/test-case-manager.tsx
git commit -m "a11y(tests): delete case uses ConfirmDialog"
```

---

### Task 14: Test case batch delete: replace confirm() with ConfirmDialog

**Files:**
- Modify: `web/components/test-case-manager.tsx`

**Commit:**
```bash
git add web/components/test-case-manager.tsx
git commit -m "a11y(tests): batch delete uses ConfirmDialog"
```

---

### Task 15: Pipeline options import JSON: replace window.prompt() with Dialog

**Files:**
- Modify: `web/components/pipeline-options-panel.tsx`

**Steps:**
1. Add a small dialog with a textarea to paste pipeline JSON.
2. Keep validation + toast behavior, but avoid blocking native prompt.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/pipeline-options-panel.tsx
git commit -m "a11y(pipeline): import JSON uses Dialog (no prompt())"
```

---

### Task 16: Graph connect mode relation label: replace prompt() with Dialog

**Files:**
- Modify: `web/app/graph/page.tsx`

**Commit:**
```bash
git add web/app/graph/page.tsx
git commit -m "a11y(graph): relation label uses Dialog (no prompt())"
```

---

### Task 17: Add UI guard for native confirm/prompt

**Files:**
- Create: `web/scripts/check-native-dialogs.mjs`
- Modify: `web/package.json` (extend `ui-check`)

**Steps:**
1. Scan `web/` source for `confirm(` / `window.confirm(` / `prompt(` / `window.prompt(`.
2. Ignore generated artifacts (`web/types/openapi.ts`, `.next`, `node_modules`).
3. Wire into `pnpm run ui-check`.

**Verify:**
```bash
cd web && pnpm run ui-check
```

**Commit:**
```bash
git add web/scripts/check-native-dialogs.mjs web/package.json
git commit -m "chore(ui): ban native confirm/prompt dialogs (ui-check)"
```

---

### Task 18: Update UI standards guide (ban native dialogs; show new patterns)

**Files:**
- Modify: `docs/guides/ui_standards.md`

**Commit:**
```bash
git add docs/guides/ui_standards.md
git commit -m "docs(ui): document ConfirmDialog + ban native confirm/prompt"
```

---

### Task 19: Add verification record for this round (skeleton)

**Files:**
- Create: `docs/plans/2026-02-03-baseline-dialog-sweep-20-commits-verification.md`

**Commit:**
```bash
git add docs/plans/2026-02-03-baseline-dialog-sweep-20-commits-verification.md
git commit -m "docs(plans): add baseline dialog sweep verification (skeleton)"
```

---

### Task 20: Run verification gates and record results

**Files:**
- Modify: `docs/plans/2026-02-03-baseline-dialog-sweep-20-commits-verification.md`

**Verify:**
```bash
make enterprise-checks
make openapi-check
```

**Commit:**
```bash
git add docs/plans/2026-02-03-baseline-dialog-sweep-20-commits-verification.md
git commit -m "docs(plans): record baseline dialog sweep verification"
```
