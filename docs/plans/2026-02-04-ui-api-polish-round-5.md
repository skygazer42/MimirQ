# UI + API Polish (Round 5) Implementation Plan

> **For Codex/Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** 20 small commits to improve Baseline UI compliance (blur/transition/shadow hygiene, token-first styling) while keeping FE/BE integration checks green.

**Architecture:** Frontend-only changes (Next.js / Tailwind / shadcn primitives). No backend behavior changes. Keep verification gates (`make enterprise-checks`, `make openapi-check`) green.

**Tech Stack:** Next.js 14 (App Router) + TypeScript + Tailwind + Radix/shadcn; FastAPI backend; OpenAPI typegen.

---

### Task 1: Add round 5 design notes

**Files:**
- Create: `docs/plans/2026-02-04-ui-api-polish-round-5-design.md`

**Commit:**
```bash
git add docs/plans/2026-02-04-ui-api-polish-round-5-design.md
git commit -m "docs(plans): add UI+API polish round 5 design notes"
```

---

### Task 2: Add this plan document

**Files:**
- Create: `docs/plans/2026-02-04-ui-api-polish-round-5.md`

**Commit:**
```bash
git add docs/plans/2026-02-04-ui-api-polish-round-5.md
git commit -m "docs(plans): add UI+API polish round 5 plan"
```

---

### Task 3: Dataset profile: reduce heavy blur in findings dialog

**Files:**
- Modify: `web/app/datasets/[id]/profile/page.tsx`

**Steps:**
1. Replace `backdrop-blur-xl` with a lighter blur (prefer `backdrop-blur-sm` or remove blur entirely).

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/app/datasets/[id]/profile/page.tsx
git commit -m "perf(profile): reduce heavy blur in findings dialog"
```

---

### Task 4: Dataset ingestion: reduce heavy blur in dialogs

**Files:**
- Modify: `web/app/datasets/[id]/ingestion/page.tsx`

**Steps:**
1. Replace `backdrop-blur-xl` with a lighter blur (prefer `backdrop-blur-sm` or remove blur entirely).

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/app/datasets/[id]/ingestion/page.tsx
git commit -m "perf(ingestion): reduce heavy blur in dialogs"
```

---

### Task 5: Dataset precheck: reduce heavy blur in dialogs

**Files:**
- Modify: `web/app/datasets/[id]/precheck/page.tsx`

**Steps:**
1. Replace `backdrop-blur-xl` with a lighter blur (prefer `backdrop-blur-sm` or remove blur entirely).

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/app/datasets/[id]/precheck/page.tsx
git commit -m "perf(precheck): reduce heavy blur in dialogs"
```

---

### Task 6: Datasets list row actions: transform transition + <=200ms duration

**Files:**
- Modify: `web/app/datasets/page.tsx`

**Steps:**
1. Ensure the action group uses `transition-transform` (not just opacity).
2. Reduce interaction duration to <=200ms (prefer `duration-150` or `duration-200`).

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/app/datasets/page.tsx
git commit -m "style(datasets): row actions use transform transition (<=200ms)"
```

---

### Task 7: Settings provider category cards: tighten hover shadow transition

**Files:**
- Modify: `web/app/settings/page.tsx`

**Steps:**
1. Replace `duration-300` with `duration-200` for hover transitions.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/app/settings/page.tsx
git commit -m "style(settings): tighten hover shadow duration (<=200ms)"
```

---

### Task 8: Chat area: tighten durations + minor copy cleanup

**Files:**
- Modify: `web/components/chat-area.tsx`

**Steps:**
1. Replace `duration-300` on background/toolbar micro-interactions with <=200ms.
2. Keep motion-safe defaults and respect reduced motion.
3. Remove/translate any stray English microcopy in the chat UI where it leaks into the Chinese UI.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/chat-area.tsx
git commit -m "style(chat): tighten micro-interactions (<=200ms)"
```

---

### Task 9: Manual upload dialog: tighten opacity transition durations

**Files:**
- Modify: `web/components/manual-upload-dialog.tsx`

**Steps:**
1. Replace `transition-opacity duration-300` with <=200ms where used for section enable/disable affordances.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/manual-upload-dialog.tsx
git commit -m "style(upload): tighten opacity transitions (<=200ms)"
```

---

### Task 10: Task center: token shadow instead of `shadow-2xl`

**Files:**
- Modify: `web/components/task-center.tsx`

**Steps:**
1. Replace `shadow-2xl` with token shadow (prefer `shadow-strong`).

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/task-center.tsx
git commit -m "style(task-center): use token shadow (baseline)"
```

---

### Task 11: Model config dialog: token shadow instead of `shadow-2xl`

**Files:**
- Modify: `web/components/model-config-dialog.tsx`

**Steps:**
1. Replace `shadow-2xl` with token shadow (prefer `shadow-strong`).

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/model-config-dialog.tsx
git commit -m "style(settings): model config dialog uses token shadow"
```

---

### Task 12: Holographic radar: reduce heavy blur + use token shadow

**Files:**
- Modify: `web/components/evaluation/holographic-radar.tsx`

**Steps:**
1. Reduce `blur-3xl` to a lighter blur (prefer `blur-2xl` or `blur-xl`).
2. Replace any heavy `shadow-xl` usage in tooltip with token shadow where possible.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/evaluation/holographic-radar.tsx
git commit -m "style(evaluation): calm holographic radar effects (baseline)"
```

---

### Task 13: Prompts page: use `formatApiError` for API failure toasts

**Files:**
- Modify: `web/app/prompts/page.tsx`

**Steps:**
1. Replace plain `toast.error('...')` in API catch blocks with `toast.error(formatApiError(err, '...'))`.
2. Keep existing success toasts unchanged.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/app/prompts/page.tsx
git commit -m "dx(prompts): include request_id in error toasts"
```

---

### Task 14: Evaluations page: use `formatApiError` for start failure toast

**Files:**
- Modify: `web/app/evaluations/page.tsx`

**Steps:**
1. Replace `toast.error('启动评测失败...')` with `toast.error(formatApiError(err, '启动评测失败'))`.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/app/evaluations/page.tsx
git commit -m "dx(evaluation): include request_id in start error toast"
```

---

### Task 15: Document viewer panel: `formatApiError` for chunk/Q&A failures + copy cleanup

**Files:**
- Modify: `web/components/document-viewer-panel.tsx`

**Steps:**
1. Replace English/plain API error toasts for chunk CRUD / QA generate with `formatApiError`.
2. Translate user-facing toasts/messages to match the app language where appropriate (avoid mixing EN/zh for common flows).

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/document-viewer-panel.tsx
git commit -m "dx(viewer): request_id aware error toasts for chunk/qa"
```

---

### Task 16: Docs: update integration guide with `web-api-ping` workflow

**Files:**
- Modify: `docs/guides/frontend_backend_integration.md`

**Steps:**
1. Add a short section describing `make web-api-ping` / `pnpm run api-ping` for quick reachability checks.

**Commit:**
```bash
git add docs/guides/frontend_backend_integration.md
git commit -m "docs(guides): document api-ping workflow for local integration"
```

---

### Task 17: Knowledge page: translate remaining English toasts + include request_id where applicable

**Files:**
- Modify: `web/app/knowledge/page.tsx`

**Steps:**
1. Translate leftover English error toasts ("Please input ...", etc.) to Chinese.
2. For API-backed failures, prefer `formatApiError`.

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/app/knowledge/page.tsx
git commit -m "ux(knowledge): unify error copy and request_id handling"
```

---

### Task 18: Test generation dialog: migrate to shadcn `Dialog` + token-first styling

**Files:**
- Modify: `web/components/test-generation-dialog.tsx`

**Steps:**
1. Replace custom fixed overlay with `Dialog` / `DialogContent` for focus trap + keyboard behavior.
2. Replace `border-slate-*` / `text-slate-*` with semantic tokens (`border-border`, `text-muted-foreground`, etc.).

**Verify:**
```bash
cd web && pnpm run typecheck
cd web && pnpm run ui-check
```

**Commit:**
```bash
git add web/components/test-generation-dialog.tsx
git commit -m "a11y(tests): test generation uses Dialog (token-first)"
```

---

### Task 19: Test generation dialog: use `formatApiError` for API failures + better copy

**Files:**
- Modify: `web/components/test-generation-dialog.tsx`

**Steps:**
1. Replace plain API error toasts with `formatApiError`.
2. Keep non-API validation toasts as-is (e.g. "请选择一个对话").

**Verify:**
```bash
cd web && pnpm run typecheck
```

**Commit:**
```bash
git add web/components/test-generation-dialog.tsx
git commit -m "dx(tests): request_id aware error toasts for test generation"
```

---

### Task 20: Add round 5 verification record

**Files:**
- Create: `docs/plans/2026-02-04-ui-api-polish-round-5-verification.md`

**Verify:**
```bash
make openapi-check
make enterprise-checks
```

**Commit:**
```bash
git add docs/plans/2026-02-04-ui-api-polish-round-5-verification.md
git commit -m "docs(plans): add UI+API polish round 5 verification"
```

