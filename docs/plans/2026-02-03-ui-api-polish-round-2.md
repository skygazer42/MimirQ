# UI + API Polish (Round 2) Implementation Plan

> **For Codex/Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Another 20 small commits improving UI baseline compliance and backend integration tooling without changing backend behavior.

**Architecture:** UI changes are className/interaction hygiene (tokens, transitions, blur). API integration work is limited to small DX scripts and docs. Keep `make enterprise-checks` green.

**Tech Stack:** Next.js 14 (App Router) + TypeScript + Tailwind + Radix/shadcn primitives; FastAPI backend; OpenAPI typegen.

---

### Task 1: Add round 2 design notes

**Files:**
- Create: `docs/plans/2026-02-03-ui-api-polish-round-2-design.md`

**Commit:**
```bash
git add docs/plans/2026-02-03-ui-api-polish-round-2-design.md
git commit -m "docs(plans): add UI+API polish round 2 design notes"
```

---

### Task 2: Add this plan document

**Files:**
- Create: `docs/plans/2026-02-03-ui-api-polish-round-2.md`

**Commit:**
```bash
git add docs/plans/2026-02-03-ui-api-polish-round-2.md
git commit -m "docs(plans): add UI+API polish round 2 plan"
```

---

### Task 3: Data annotator card: remove `transition-all`

**Files:**
- Modify: `web/components/data-governance/data-annotator.tsx`

**Commit:**
```bash
git add web/components/data-governance/data-annotator.tsx
git commit -m "style(governance): data annotator avoids transition-all"
```

---

### Task 4: Data classifier card: remove `transition-all`

**Files:**
- Modify: `web/components/data-governance/data-classifier.tsx`

**Commit:**
```bash
git add web/components/data-governance/data-classifier.tsx
git commit -m "style(governance): data classifier avoids transition-all"
```

---

### Task 5: Chat citation card: tighten hover styles (no lift, no `transition-all`)

**Files:**
- Modify: `web/components/chat/message-item.tsx`

**Commit:**
```bash
git add web/components/chat/message-item.tsx
git commit -m "style(chat): citation card avoids transition-all and hover lift"
```

---

### Task 6: Settings page selection cards: tighten transitions

**Files:**
- Modify: `web/app/settings/page.tsx`

**Commit:**
```bash
git add web/app/settings/page.tsx
git commit -m "style(settings): selection cards avoid transition-all"
```

---

### Task 7: Parsing page: button chips avoid `transition-all`

**Files:**
- Modify: `web/app/parsing/page.tsx`

**Commit:**
```bash
git add web/app/parsing/page.tsx
git commit -m "style(parsing): action chips avoid transition-all"
```

---

### Task 8: Parse compare dialog: button chips avoid `transition-all`

**Files:**
- Modify: `web/components/parsing/parse-compare-dialog.tsx`

**Commit:**
```bash
git add web/components/parsing/parse-compare-dialog.tsx
git commit -m "style(parsing): compare dialog chips avoid transition-all"
```

---

### Task 9: Knowledge page: tighten toolbar transitions (no `transition-all`)

**Files:**
- Modify: `web/app/knowledge/page.tsx`

**Commit:**
```bash
git add web/app/knowledge/page.tsx
git commit -m "style(knowledge): toolbar avoids transition-all"
```

---

### Task 10: Knowledge page: progress bar uses transform scaleX

**Files:**
- Modify: `web/app/knowledge/page.tsx`

**Commit:**
```bash
git add web/app/knowledge/page.tsx
git commit -m "perf(knowledge): progress bar uses transform (no layout anim)"
```

---

### Task 11: Knowledge page: cards avoid `transition-all` and hover lift

**Files:**
- Modify: `web/app/knowledge/page.tsx`

**Commit:**
```bash
git add web/app/knowledge/page.tsx
git commit -m "style(knowledge): cards avoid transition-all and hover lift"
```

---

### Task 12: Knowledge feedback page: remove AppFrame `transition-all` usage

**Files:**
- Modify: `web/app/knowledge/feedback/page.tsx`

**Commit:**
```bash
git add web/app/knowledge/feedback/page.tsx
git commit -m "perf(knowledge): remove layout transition class usage"
```

---

### Task 13: Knowledge ingestion stats cards: avoid `transition-all` and hover lift

**Files:**
- Modify: `web/app/knowledge/ingestion/page.tsx`

**Commit:**
```bash
git add web/app/knowledge/ingestion/page.tsx
git commit -m "style(knowledge): ingestion stats cards baseline cleanup"
```

---

### Task 14: Knowledge ingestion list items: avoid `transition-all`

**Files:**
- Modify: `web/app/knowledge/ingestion/page.tsx`

**Commit:**
```bash
git add web/app/knowledge/ingestion/page.tsx
git commit -m "style(knowledge): ingestion list items avoid transition-all"
```

---

### Task 15: Knowledge ingestion row actions: use opacity/transform transitions only

**Files:**
- Modify: `web/app/knowledge/ingestion/page.tsx`

**Commit:**
```bash
git add web/app/knowledge/ingestion/page.tsx
git commit -m "style(knowledge): ingestion row actions tighten transitions"
```

---

### Task 16: Knowledge ingestion progress bar: switch width animation to transform scaleX

**Files:**
- Modify: `web/app/knowledge/ingestion/page.tsx`

**Commit:**
```bash
git add web/app/knowledge/ingestion/page.tsx
git commit -m "perf(knowledge): ingestion progress uses transform"
```

---

### Task 17: Tabs primitive: avoid `transition-all`

**Files:**
- Modify: `web/components/ui/tabs.tsx`

**Commit:**
```bash
git add web/components/ui/tabs.tsx
git commit -m "style(ui): tabs avoid transition-all"
```

---

### Task 18: Graph page primary button: token-first + no `transition-all`

**Files:**
- Modify: `web/app/graph/page.tsx`

**Commit:**
```bash
git add web/app/graph/page.tsx
git commit -m "style(graph): token-first primary button (no transition-all)"
```

---

### Task 19: Mode toggle icon transitions: avoid `transition-all`

**Files:**
- Modify: `web/components/mode-toggle.tsx`

**Commit:**
```bash
git add web/components/mode-toggle.tsx
git commit -m "style(ui): mode toggle avoids transition-all"
```

---

### Task 20: Backend integration: extend `api-ping` (health/ready/meta)

**Files:**
- Modify: `web/scripts/api-ping.mjs`

**Commit:**
```bash
git add web/scripts/api-ping.mjs
git commit -m "chore(web): api-ping also checks backend meta"
```

---

## Final Verification (after task 20)

```bash
make openapi-check
make enterprise-checks
```

