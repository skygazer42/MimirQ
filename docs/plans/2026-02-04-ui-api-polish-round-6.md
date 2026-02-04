# UI + API Polish (Round 6) Implementation Plan

> **For Codex/Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** 20 tasks to polish UI baseline (token shadows, motion timing, focus visibility) and improve FE/BE integration ergonomics (request_id-aware error toasts).

**Architecture:** Frontend-focused changes (Next.js / Tailwind / shadcn). No backend behavior changes. Add a couple of lightweight Vitest “guard” tests to prevent regressions.

**Tech Stack:** Next.js 14 + TypeScript + Tailwind + Radix/shadcn; FastAPI backend; Vitest for node-env unit tests.

**Commit strategy:** The plan is written as 20 small tasks for traceability, but per request we will **squash to a single final commit** at the end of the round.

---

### Task 1: Add round 6 design notes

**Files:**
- Create: `docs/plans/2026-02-04-ui-api-polish-round-6-design.md`

---

### Task 2: Add this plan document

**Files:**
- Create: `docs/plans/2026-02-04-ui-api-polish-round-6.md`

---

### Task 3: Add baseline UI guard test (ban heavy Tailwind shadows)

**Files:**
- Create: `web/lib/baseline-ui-guards.test.ts`

**Steps:**
1. Add a test that scans `web/` source files and fails if it finds these classes:
   - `shadow-xl`
   - `shadow-2xl`
   - `shadow-3xl`

**Verify (RED):**
```bash
cd web && pnpm run test -- web/lib/baseline-ui-guards.test.ts
```
Expected: FAIL (current code uses `shadow-xl` / `shadow-2xl`).

---

### Task 4: Chat composer: replace `shadow-2xl` with token shadows

**Files:**
- Modify: `web/components/chat-area.tsx`

**Steps:**
1. Replace the composer container shadow classes with token shadows (prefer `shadow-soft hover:shadow-strong`).

---

### Task 5: Chat message bubble: replace `shadow-2xl` with token shadows

**Files:**
- Modify: `web/components/chat/message-item.tsx`

**Steps:**
1. Replace user bubble `shadow-2xl` usage with token shadows (avoid Tailwind `shadow-2xl`).

---

### Task 6: Data governance panel: replace `shadow-xl` with token shadow

**Files:**
- Modify: `web/components/data-governance-panel.tsx`

---

### Task 7: Parser dropdown: replace `shadow-xl` with token shadow

**Files:**
- Modify: `web/components/ui/parser-dropdown.tsx`

---

### Task 8: Chunk preview empty state: replace `shadow-xl` with token shadow

**Files:**
- Modify: `web/components/chunk-preview/components/empty-state.tsx`

**Verify (GREEN for tasks 4-8):**
```bash
cd web && pnpm run test -- web/lib/baseline-ui-guards.test.ts
```
Expected: PASS (no banned shadow classes remain).

---

### Task 9: Add baseline a11y guard test (ban focus-ring suppression)

**Files:**
- Modify: `web/lib/baseline-ui-guards.test.ts`

**Steps:**
1. Add a test that fails when it finds:
   - `focus-visible:ring-0`
   - `focus:ring-0`

**Verify (RED):**
```bash
cd web && pnpm run test -- web/lib/baseline-ui-guards.test.ts
```
Expected: FAIL (a few knowledge pages currently suppress focus rings).

---

### Task 10: Feedback triage toolbar: restore visible focus treatment

**Files:**
- Modify: `web/app/knowledge/feedback/page.tsx`

**Steps:**
1. Remove `focus-visible:ring-0` override from the search input.
2. Remove `focus:ring-0` override from the Select trigger.
3. Add a visible `focus-within` ring to the toolbar container so keyboard users can see focus clearly.

---

### Task 11: Knowledge ingestion toolbar: restore visible focus treatment

**Files:**
- Modify: `web/app/knowledge/ingestion/page.tsx`

**Steps:**
1. Remove `focus-visible:ring-0` override from the search input.
2. Remove `focus:ring-0` override from the Select trigger.
3. Add a visible `focus-within` ring to the toolbar container.

---

### Task 12: Quarantine toolbar: restore visible focus treatment

**Files:**
- Modify: `web/app/knowledge/quarantine/page.tsx`

**Steps:**
1. Remove `focus-visible:ring-0` override from the search input.
2. Add a visible `focus-within` ring to the toolbar container.

**Verify (GREEN for tasks 10-12):**
```bash
cd web && pnpm run test -- web/lib/baseline-ui-guards.test.ts
```
Expected: PASS (no focus-ring suppression patterns remain).

---

### Task 13: Governance profile selector: request_id-aware error toasts + a11y label

**Files:**
- Modify: `web/components/governance-profile-selector.tsx`

**Steps:**
1. Replace API failure toasts with `toast.error(formatApiError(err, '...'))`.
2. For detail load failure, surface a toast (so failures aren’t silent).
3. Add `aria-label` to icon-only refresh button.

---

### Task 14: Regression test tab: request_id-aware error toasts

**Files:**
- Modify: `web/components/evaluation/regression-tab.tsx`

**Steps:**
1. Replace API failure toasts with `toast.error(formatApiError(err, '...'))`.

---

### Task 15: Chat message rating: request_id-aware error toast

**Files:**
- Modify: `web/components/chat/message-item.tsx`

**Steps:**
1. Replace feedback submit failure toast with `formatApiError`.

---

### Task 16: Chat message entry animation: shorten duration

**Files:**
- Modify: `web/components/chat/message-item.tsx`

**Steps:**
1. Replace `duration-500` with `duration-300` for the message entry animation.

---

### Task 17: Knowledge page tab entry animations: shorten duration

**Files:**
- Modify: `web/app/knowledge/page.tsx`

**Steps:**
1. Replace `duration-500` with `duration-300` for the three tab content wrappers that use `animate-in fade-in slide-in-from-bottom-*`.

---

### Task 18: Feedback triage: swap key `text-slate-*` to semantic tokens

**Files:**
- Modify: `web/app/knowledge/feedback/page.tsx`

**Steps:**
1. Replace a few high-visibility `text-slate-*` classes (header/toolbar) with semantic tokens (`text-muted-foreground`, `text-foreground`, etc.) to improve theme consistency.

---

### Task 19: Install deps + run verification gates

**Steps:**
1. Install web dependencies:
```bash
cd web && pnpm install
```

2. Run frontend verification:
```bash
cd web && pnpm run verify
```

3. Run contract checks + repo verification:
```bash
make api-check
make verify
```

---

### Task 20: Add round 6 verification record

**Files:**
- Create: `docs/plans/2026-02-04-ui-api-polish-round-6-verification.md`

**Content:**
- Paste the output (or summary) of the commands from Task 19.

---

### Final Commit (single commit)

After all tasks are completed and verified:

```bash
git add -A
git commit -m "ui: polish shadows, focus rings, and request_id error toasts (round 6)"
```

