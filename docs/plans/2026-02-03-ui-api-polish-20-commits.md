# UI + API Polish (20 Commits) Implementation Plan

> **For Codex/Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Improve high-frequency UI surfaces (baseline-ui compliant) and keep backend API integration checks green, delivered as 20 small commits.

**Architecture:** No backend behavior changes required. Frontend changes are mostly className hygiene (tokens / transitions / blur) plus a small DX addition (`pnpm run verify`). API integration is verified via OpenAPI export + route contract/coverage scripts.

**Tech Stack:** Next.js 14 (App Router) + TypeScript + Tailwind + Radix/shadcn primitives; FastAPI backend; OpenAPI typegen (`openapi-typescript`).

---

### Task 1: Add design notes for this 20-commit round

**Files:**
- Create: `docs/plans/2026-02-03-ui-api-polish-20-commits-design.md`

**Commit:**
```bash
git add docs/plans/2026-02-03-ui-api-polish-20-commits-design.md
git commit -m "docs(plans): add UI+API polish design notes (20 commits)"
```

---

### Task 2: Add this implementation plan

**Files:**
- Create: `docs/plans/2026-02-03-ui-api-polish-20-commits.md`

**Commit:**
```bash
git add docs/plans/2026-02-03-ui-api-polish-20-commits.md
git commit -m "docs(plans): add UI+API polish plan (20 commits)"
```

---

### Task 3: Dialog overlay baseline cleanup (remove large blur + typography utilities)

**Files:**
- Modify: `web/components/ui/dialog.tsx`

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/ui/dialog.tsx
git commit -m "style(ui): tighten dialog overlay + typography (baseline)"
```

---

### Task 4: Add one-command frontend verify script

**Files:**
- Modify: `web/package.json`

**Verify:**
```bash
cd web && pnpm run verify
```

**Commit:**
```bash
git add web/package.json
git commit -m "chore(web): add pnpm verify script"
```

---

### Task 5: Add frontend README (dev + env + checks)

**Files:**
- Create: `web/README.md`

**Commit:**
```bash
git add web/README.md
git commit -m "docs(web): add frontend README"
```

---

### Task 6: Add frontend-backend integration guide

**Files:**
- Create: `docs/guides/frontend_backend_integration.md`

**Commit:**
```bash
git add docs/guides/frontend_backend_integration.md
git commit -m "docs(guides): add frontend-backend integration guide"
```

---

### Task 7: Add UI standards guide (token-first + baseline rules)

**Files:**
- Create: `docs/guides/ui_standards.md`

**Commit:**
```bash
git add docs/guides/ui_standards.md
git commit -m "docs(guides): add UI standards guide"
```

---

### Task 8: FileQueueItem progress bar: switch width animation to transform scaleX

**Files:**
- Modify: `web/components/ui/file-queue-item.tsx`

**Steps:**
1. Replace `style={{ width: ... }}` + `transition-all` with `transform: scaleX(...)` + `transition-transform`.
2. Replace `bg-sky-500` with semantic token (prefer `bg-primary`).
3. Replace broad `transition-all` in hover affordances with targeted transitions; add `focus-ring` to icon buttons.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/ui/file-queue-item.tsx
git commit -m "perf(ui): file queue progress uses transform (no layout anim)"
```

---

### Task 9: TaskCenter progress bar: switch width animation to transform scaleX

**Files:**
- Modify: `web/components/task-center.tsx`

**Steps:**
1. Progress fill uses `scaleX` instead of `width` + `transition-all`.
2. Remove `transition-all duration-300` on the floating launcher button (use targeted transitions, <=200ms).
3. Reduce heavy blur/shadow on the floating button to align with baseline.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/task-center.tsx
git commit -m "perf(ui): task center progress uses transform; calm floating button"
```

---

### Task 10: StepIndicator: remove transition-all (use transition-colors only)

**Files:**
- Modify: `web/components/ui/step-indicator.tsx`

**Commit:**
```bash
git add web/components/ui/step-indicator.tsx
git commit -m "style(ui): step indicator avoids transition-all"
```

---

### Task 11: Chat send button: avoid transition-all and 300ms durations

**Files:**
- Modify: `web/components/chat-area.tsx`

**Steps:**
1. Replace `transition-all duration-300` with targeted transitions (`transition-colors`, `transition-shadow`, `transition-transform`) and <=200ms.

**Commit:**
```bash
git add web/components/chat-area.tsx
git commit -m "style(chat): tighten send button transitions (<=200ms)"
```

---

### Task 12: Message actions: avoid transition-all (use opacity/transform transitions)

**Files:**
- Modify: `web/components/chat/message-item.tsx`

**Steps:**
1. Replace action buttons `transition-all` with `transition-opacity transition-transform`.
2. Reduce broad bubble `transition-all` to narrow transitions.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/chat/message-item.tsx
git commit -m "style(chat): tighten message transitions (no transition-all)"
```

---

### Task 13: ModelProviderCard: tighten hover motion and transitions

**Files:**
- Modify: `web/components/model-provider-card.tsx`

**Commit:**
```bash
git add web/components/model-provider-card.tsx
git commit -m "style(ui): tighten model provider card transitions"
```

---

### Task 14: Document viewer panel: remove layout animation on right panel container

**Files:**
- Modify: `web/components/document-viewer-panel.tsx`

**Steps:**
1. Remove `transition-all` from the panel container that changes width.
2. Replace `shadow-2xl` with token shadow (prefer `shadow-strong`) where appropriate.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/document-viewer-panel.tsx
git commit -m "perf(viewer): remove right panel layout animation"
```

---

### Task 15: Data governance sidebar: remove transition-all (width) on collapsible sidebar

**Files:**
- Modify: `web/components/data-governance-panel.tsx`

**Commit:**
```bash
git add web/components/data-governance-panel.tsx
git commit -m "perf(governance): remove sidebar layout animation"
```

---

### Task 16: Knowledge feedback toolbar: remove blur + transition-all, keep token-first

**Files:**
- Modify: `web/app/knowledge/feedback/page.tsx`

**Commit:**
```bash
git add web/app/knowledge/feedback/page.tsx
git commit -m "style(knowledge): feedback toolbar baseline cleanup"
```

---

### Task 17: Knowledge ingestion toolbar: remove blur + transition-all, keep token-first

**Files:**
- Modify: `web/app/knowledge/ingestion/page.tsx`

**Commit:**
```bash
git add web/app/knowledge/ingestion/page.tsx
git commit -m "style(knowledge): ingestion toolbar baseline cleanup"
```

---

### Task 18: Knowledge quarantine toolbar: remove blur + transition-all, keep token-first

**Files:**
- Modify: `web/app/knowledge/quarantine/page.tsx`

**Commit:**
```bash
git add web/app/knowledge/quarantine/page.tsx
git commit -m "style(knowledge): quarantine toolbar baseline cleanup"
```

---

### Task 19: Add `pnpm run api-ping` (quick backend reachability from web/)

**Files:**
- Create: `web/scripts/api-ping.mjs`
- Modify: `web/package.json`

**Steps:**
1. Add a Node script that calls backend health endpoints and prints status.
2. Wire it as `pnpm run api-ping`.

**Commit:**
```bash
git add web/scripts/api-ping.mjs web/package.json
git commit -m "chore(web): add api-ping script for backend integration"
```

---

### Task 20: Add verification record for this round

**Files:**
- Move: `docs/plans/2026-02-03-frontend-ui-api-integration-verification.md` -> `docs/plans/2026-02-03-ui-api-polish-20-commits-verification.md`
- Modify: `docs/plans/2026-02-03-ui-api-polish-20-commits-verification.md`

**Verify:**
```bash
make openapi-check
make enterprise-checks
```

**Commit:**
```bash
git add docs/plans/2026-02-03-ui-api-polish-20-commits-verification.md
git commit -m "docs(plans): add UI+API polish verification (20 commits)"
```
