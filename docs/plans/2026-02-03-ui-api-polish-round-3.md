# UI + API Polish (Round 3) Implementation Plan

> **For Codex/Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** 20 small commits to tighten UI baseline compliance and improve FE/BE integration tooling.

**Architecture:** Prefer safe refactors (className hygiene, accessibility labels, non-layout transitions) + small DX improvements (ping scripts, diagnostics links). Keep behavior stable and keep `make enterprise-checks` green.

**Tech Stack:** Next.js 14 + TypeScript + Tailwind + Radix/shadcn primitives; FastAPI backend; OpenAPI typegen.

---

### Task 1: Add round 3 design notes

**Files:**
- Create: `docs/plans/2026-02-03-ui-api-polish-round-3-design.md`

**Commit:**
```bash
git add docs/plans/2026-02-03-ui-api-polish-round-3-design.md
git commit -m "docs(plans): add UI+API polish round 3 design notes"
```

---

### Task 2: Add this plan document

**Files:**
- Create: `docs/plans/2026-02-03-ui-api-polish-round-3.md`

**Commit:**
```bash
git add docs/plans/2026-02-03-ui-api-polish-round-3.md
git commit -m "docs(plans): add UI+API polish round 3 plan"
```

---

### Task 3: Governance upload CTA: avoid `transition-all` + remove hover lift

**Files:**
- Modify: `web/components/data-governance-panel.tsx`

**Commit:**
```bash
git add web/components/data-governance-panel.tsx
git commit -m "style(governance): upload CTA avoids transition-all and hover lift"
```

---

### Task 4: Governance file rows: avoid `transition-all` + use `size-*` for icon tile

**Files:**
- Modify: `web/components/data-governance-panel.tsx`

**Commit:**
```bash
git add web/components/data-governance-panel.tsx
git commit -m "style(governance): file rows avoid transition-all"
```

---

### Task 5: Governance row delete button: targeted transitions + a11y label

**Files:**
- Modify: `web/components/data-governance-panel.tsx`

**Commit:**
```bash
git add web/components/data-governance-panel.tsx
git commit -m "a11y(governance): delete icon uses aria-label and avoids transition-all"
```

---

### Task 6: Governance content container: remove layout transition (`max-w-*`)

**Files:**
- Modify: `web/components/data-governance-panel.tsx`

**Commit:**
```bash
git add web/components/data-governance-panel.tsx
git commit -m "perf(governance): remove layout transition from content container"
```

---

### Task 7: Governance right panel: avoid layout `transition-all` (use transform-only)

**Files:**
- Modify: `web/components/data-governance-panel.tsx`

**Commit:**
```bash
git add web/components/data-governance-panel.tsx
git commit -m "perf(governance): tool panel avoids transition-all"
```

---

### Task 8: Governance tool tabs: avoid `transition-all`

**Files:**
- Modify: `web/components/data-governance-panel.tsx`

**Commit:**
```bash
git add web/components/data-governance-panel.tsx
git commit -m "style(governance): tool tabs avoid transition-all"
```

---

### Task 9: Chat page AppFrame: remove layout transition className

**Files:**
- Modify: `web/components/chat-page-client.tsx`

**Commit:**
```bash
git add web/components/chat-page-client.tsx
git commit -m "perf(chat): remove AppFrame transition-all"
```

---

### Task 10: Document detail dialog view toggles: avoid `transition-all`

**Files:**
- Modify: `web/components/document-detail-dialog.tsx`

**Commit:**
```bash
git add web/components/document-detail-dialog.tsx
git commit -m "style(viewer): doc detail tabs avoid transition-all"
```

---

### Task 11: Document viewer chunk cards: avoid `transition-all`

**Files:**
- Modify: `web/components/document-viewer-panel.tsx`

**Commit:**
```bash
git add web/components/document-viewer-panel.tsx
git commit -m "style(viewer): chunk cards avoid transition-all"
```

---

### Task 12: Chunk preview chunk card: avoid `transition-all` + remove hover lift

**Files:**
- Modify: `web/components/chunk-preview/components/chunk-card.tsx`

**Commit:**
```bash
git add web/components/chunk-preview/components/chunk-card.tsx
git commit -m "style(chunk-preview): chunk card avoids transition-all and hover lift"
```

---

### Task 13: Chunk preview empty state container: avoid `transition-all`

**Files:**
- Modify: `web/components/chunk-preview/components/empty-state.tsx`

**Commit:**
```bash
git add web/components/chunk-preview/components/empty-state.tsx
git commit -m "style(chunk-preview): empty state container avoids transition-all"
```

---

### Task 14: Chunk preview empty state example card: avoid `transition-all`

**Files:**
- Modify: `web/components/chunk-preview/components/empty-state.tsx`

**Commit:**
```bash
git add web/components/chunk-preview/components/empty-state.tsx
git commit -m "style(chunk-preview): empty state cards avoid transition-all"
```

---

### Task 15: Chunk preview top bar submit button: avoid `transition-all`

**Files:**
- Modify: `web/components/chunk-preview/components/workbench/top-bar.tsx`

**Commit:**
```bash
git add web/components/chunk-preview/components/workbench/top-bar.tsx
git commit -m "style(chunk-preview): submit button avoids transition-all"
```

---

### Task 16: Chunk preview sidebar remove button: avoid `transition-all`

**Files:**
- Modify: `web/components/chunk-preview/components/workbench/sidebar.tsx`

**Commit:**
```bash
git add web/components/chunk-preview/components/workbench/sidebar.tsx
git commit -m "style(chunk-preview): sidebar remove button avoids transition-all"
```

---

### Task 17: Chunk strategy dropdown: avoid `transition-all`

**Files:**
- Modify: `web/components/ui/chunk-strategy-dropdown.tsx`

**Commit:**
```bash
git add web/components/ui/chunk-strategy-dropdown.tsx
git commit -m "style(ui): chunk strategy dropdown avoids transition-all"
```

---

### Task 18: Parser dropdown: avoid `transition-all`

**Files:**
- Modify: `web/components/ui/parser-dropdown.tsx`

**Commit:**
```bash
git add web/components/ui/parser-dropdown.tsx
git commit -m "style(ui): parser dropdown avoids transition-all"
```

---

### Task 19: Stats card: avoid `transition-all` + use `tabular-nums` for values

**Files:**
- Modify: `web/components/ui/stats-card.tsx`

**Commit:**
```bash
git add web/components/ui/stats-card.tsx
git commit -m "style(ui): stats card avoids transition-all"
```

---

### Task 20: Backend integration DX: extend root `make api-ping` + add `make web-api-ping` + diagnostics shortcuts

**Files:**
- Modify: `scripts/api_ping.py`
- Modify: `Makefile`
- Modify: `web/app/diagnostics/page.tsx`

**Commit:**
```bash
git add scripts/api_ping.py Makefile web/app/diagnostics/page.tsx
git commit -m "chore(dx): improve api ping and diagnostics shortcuts"
```

---

## Final Verification (after task 20)

```bash
make openapi-check
make enterprise-checks
```

