# A11y + Motion + Integration DX (20 Commits) Implementation Plan

> **For Codex/Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Improve accessibility (WCAG 2.2 A/AA), motion/performance baselines, and FE/BE integration DX as 20 small commits.

**Architecture:** No backend behavior changes. Frontend changes focus on semantic HTML (`button`/`label`), token-first surfaces, reduced blur/backdrop-filter, and consistent API error formatting (request_id preserved).

**Tech Stack:** Next.js 14 (App Router) + TypeScript + Tailwind + Radix/shadcn primitives; FastAPI backend; OpenAPI typegen (`openapi-typescript`).

---

### Task 1: Add design notes for this 20-commit round

**Files:**
- Create: `docs/plans/2026-02-03-a11y-motion-integration-20-commits-design.md`

**Commit:**
```bash
git add docs/plans/2026-02-03-a11y-motion-integration-20-commits-design.md
git commit -m "docs(plans): add a11y+motion+integration design notes (20 commits)"
```

---

### Task 2: Add this implementation plan

**Files:**
- Create: `docs/plans/2026-02-03-a11y-motion-integration-20-commits.md`

**Commit:**
```bash
git add docs/plans/2026-02-03-a11y-motion-integration-20-commits.md
git commit -m "docs(plans): add a11y+motion+integration plan (20 commits)"
```

---

### Task 3: A11y (Chat): label composer + label summary memory checkbox

**Files:**
- Modify: `web/components/chat-area.tsx`

**Steps:**
1. Add an `sr-only` label for `#chat-composer`.
2. Ensure the “摘要记忆（持久）” checkbox has a proper `<Label htmlFor=...>` association (not placeholder-only).

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/chat-area.tsx
git commit -m "a11y(chat): label composer and summary memory toggle"
```

---

### Task 4: Motion (Chat): tighten hover transition duration (<=200ms)

**Files:**
- Modify: `web/components/chat-area.tsx`

**Steps:**
1. Reduce long hover transition durations (e.g. 500ms) to <=200ms for interaction feedback.

**Commit:**
```bash
git add web/components/chat-area.tsx
git commit -m "style(chat): tighten hover transitions (<=200ms)"
```

---

### Task 5: Perf (CSS): reduce `.glass` blur (avoid large backdrop-filter)

**Files:**
- Modify: `web/app/globals.css`

**Steps:**
1. Change `.glass` from `backdrop-blur-xl` to a smaller blur (prefer `backdrop-blur-md`).

**Verify:**
```bash
cd web && pnpm run ui-check
```

**Commit:**
```bash
git add web/app/globals.css
git commit -m "perf(css): reduce glass blur (baseline)"
```

---

### Task 6: Perf (Parsing): remove blur-heavy header/sidebar surfaces

**Files:**
- Modify: `web/app/parsing/page.tsx`

**Steps:**
1. Remove `backdrop-blur*` from high-frequency containers (header/sidebar/main).
2. Keep token-first surfaces (`bg-card/bg-background`) and maintain readability.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/app/parsing/page.tsx
git commit -m "perf(parsing): remove blur-heavy surfaces (baseline)"
```

---

### Task 7: Perf (History): remove blur surfaces in conversation history

**Files:**
- Modify: `web/app/history/page.tsx`

**Commit:**
```bash
git add web/app/history/page.tsx
git commit -m "perf(history): reduce blur surfaces (baseline)"
```

---

### Task 8: Perf (Graph): reduce blur + heavy shadows on overlays

**Files:**
- Modify: `web/app/graph/page.tsx`

**Commit:**
```bash
git add web/app/graph/page.tsx
git commit -m "perf(graph): reduce blur and heavy shadows"
```

---

### Task 9: Perf (Datasets): soften dialog surfaces (avoid backdrop-blur-xl)

**Files:**
- Modify: `web/app/datasets/page.tsx`

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/app/datasets/page.tsx
git commit -m "perf(datasets): soften dialog surface (no blur-xl)"
```

---

### Task 10: A11y (Knowledge/Ingestion): replace `role=button` rows with `<button>`

**Files:**
- Modify: `web/app/knowledge/ingestion/page.tsx`

**Commit:**
```bash
git add web/app/knowledge/ingestion/page.tsx
git commit -m "a11y(ingestion): list items use button semantics"
```

---

### Task 11: A11y (Knowledge/Quarantine): replace `role=button` rows with `<button>`

**Files:**
- Modify: `web/app/knowledge/quarantine/page.tsx`

**Commit:**
```bash
git add web/app/knowledge/quarantine/page.tsx
git commit -m "a11y(quarantine): list items use button semantics"
```

---

### Task 12: A11y (Knowledge/Feedback): replace `role=button` rows with `<button>`

**Files:**
- Modify: `web/app/knowledge/feedback/page.tsx`

**Commit:**
```bash
git add web/app/knowledge/feedback/page.tsx
git commit -m "a11y(feedback): list items use button semantics"
```

---

### Task 13: A11y (Chunk Preview): replace `role=button` items with `<button>`

**Files:**
- Modify: `web/components/chunk-preview/components/workbench/sidebar.tsx`

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/chunk-preview/components/workbench/sidebar.tsx
git commit -m "a11y(chunk-preview): sidebar items use button semantics"
```

---

### Task 14: A11y (History): improve list item semantics without nested interactive traps

**Files:**
- Modify: `web/app/history/page.tsx`

**Steps:**
1. Replace `role=button` container selection area with a real `<button type="button">` for the selectable region.
2. Keep delete icon actions as separate buttons (no nested buttons).

**Commit:**
```bash
git add web/app/history/page.tsx
git commit -m "a11y(history): conversation item uses native button semantics"
```

---

### Task 15: Integration DX (Audit): use `formatApiError` in toasts

**Files:**
- Modify: `web/app/audit/page.tsx`

**Commit:**
```bash
git add web/app/audit/page.tsx
git commit -m "dx(api): audit page toasts include request_id"
```

---

### Task 16: Integration DX (Usage): use `formatApiError` in toasts

**Files:**
- Modify: `web/app/usage/page.tsx`

**Commit:**
```bash
git add web/app/usage/page.tsx
git commit -m "dx(api): usage page toasts include request_id"
```

---

### Task 17: Integration DX (Observability): use `formatApiError` in toasts

**Files:**
- Modify: `web/app/observability/page.tsx`

**Commit:**
```bash
git add web/app/observability/page.tsx
git commit -m "dx(api): observability toasts include request_id"
```

---

### Task 18: Integration DX (Governance Profiles + Summary Dialog): use `formatApiError`

**Files:**
- Modify: `web/components/governance-profiles/governance-profiles-page.tsx`
- Modify: `web/components/governance-profiles/profile-editor-drawer.tsx`
- Modify: `web/components/chat/conversation-summary-dialog.tsx`

**Commit:**
```bash
git add web/components/governance-profiles/governance-profiles-page.tsx web/components/governance-profiles/profile-editor-drawer.tsx web/components/chat/conversation-summary-dialog.tsx
git commit -m "dx(api): surface request_id in key toasts"
```

---

### Task 19: Add verification record for this round (skeleton)

**Files:**
- Create: `docs/plans/2026-02-03-a11y-motion-integration-20-commits-verification.md`

**Commit:**
```bash
git add docs/plans/2026-02-03-a11y-motion-integration-20-commits-verification.md
git commit -m "docs(plans): add a11y+motion+integration verification (skeleton)"
```

---

### Task 20: Run verification gates and record results

**Files:**
- Modify: `docs/plans/2026-02-03-a11y-motion-integration-20-commits-verification.md`

**Verify:**
```bash
make enterprise-checks
make openapi-check
```

**Commit:**
```bash
git add docs/plans/2026-02-03-a11y-motion-integration-20-commits-verification.md
git commit -m "docs(plans): record a11y+motion+integration verification"
```

