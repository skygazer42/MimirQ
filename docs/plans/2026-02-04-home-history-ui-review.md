# Home + History UI Review Implementation Plan

> **For Codex/Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** Apply the UI review feedback on `/` and `/history` to reduce onboarding confusion, strengthen primary CTAs, and align with `baseline-ui` empty-state and affordance rules.

**Architecture:** Pure frontend UI/UX refinements in Next.js (App Router) + Tailwind; no backend behavior changes. Keep existing API client calls and data flow intact.

**Tech Stack:** Next.js 14 + TypeScript + Tailwind + Radix/shadcn primitives; Vitest for lightweight guard tests.

**Commit strategy:** Implement as 20 traceable tasks, but per request we will **ship one final commit on `main`**.

---

### Task 1: Add design notes doc

**Files:**
- Create: `docs/plans/2026-02-04-home-history-ui-review-design.md`

---

### Task 2: Add this plan doc

**Files:**
- Create: `docs/plans/2026-02-04-home-history-ui-review.md`

---

### Task 3: Add a welcome screen regression test (no redundant CTA)

**Files:**
- Create: `web/components/chat-area.welcome.test.ts`

**Steps:**
1. Add a Vitest test that asserts `web/components/chat-area.tsx` does **not** contain the literal string `开始提问`.

**Verify (RED):**
```bash
cd web && pnpm run test -- web/components/chat-area.welcome.test.ts
```
Expected: FAIL until UI is updated.

---

### Task 4: Add a welcome screen regression test (prompt starters wiring)

**Files:**
- Modify: `web/components/chat-area.welcome.test.ts`

**Steps:**
1. Add a test that asserts `web/components/chat-area.tsx` includes `globalEventBus.emit('chat:send'`.

---

### Task 5: Remove the redundant “开始提问” button from welcome state

**Files:**
- Modify: `web/components/chat-area.tsx`

**Steps:**
1. Update `WelcomeScreen()` to remove the standalone button CTA.

**Verify (GREEN):**
```bash
cd web && pnpm run test -- web/components/chat-area.welcome.test.ts
```

---

### Task 6: Convert feature cards into clickable prompt starters

**Files:**
- Modify: `web/components/chat-area.tsx`

**Steps:**
1. Make each feature card a real interactive element (`button`).
2. On click:
   - emit `globalEventBus.emit('chat:send', <prompt>)`
   - focus the composer textarea.
3. Add hover/focus states using Tailwind (transform/opacity only; <= 200ms).

---

### Task 7: Make prompt starters feel clickable (affordance polish)

**Files:**
- Modify: `web/components/chat-area.tsx`

**Steps:**
1. Replace `cursor-default` with `cursor-pointer`.
2. Add subtle lift + border emphasis on hover, and visible `focus-visible` ring.

---

### Task 8: Move `RAG 配置` trigger into the composer surface (not floating above)

**Files:**
- Modify: `web/components/chat-area.tsx`

**Steps:**
1. Remove the “floating” row above the composer that contains the `RAG 配置` pill.
2. Re-introduce the trigger inside the composer container so it visually belongs to the input.
3. Keep the existing `PopoverContent` for settings unchanged.

---

### Task 9: Composer layout tweak to accommodate integrated controls

**Files:**
- Modify: `web/components/chat-area.tsx`

**Steps:**
1. Adjust textarea padding/right inset if needed so text never overlaps buttons.
2. Ensure icon-only controls have `aria-label`.
3. Ensure all motion classes are guarded with `motion-safe:*` and have `motion-reduce:*` fallbacks.

---

### Task 10: Make History page primary CTA visually primary

**Files:**
- Modify: `web/app/history/page.tsx`

**Steps:**
1. Change the PageScaffold action button (“新建对话”) from `outline` to a primary `default`/brand variant.

---

### Task 11: Add one clear next action to History “no selection” empty state

**Files:**
- Modify: `web/app/history/page.tsx`

**Steps:**
1. In the `EmptyState` rendering when `selectedConversation` is null, add a primary button labeled **“发起新对话”** that navigates to `/`.

---

### Task 12: Add History empty-state regression test (must include CTA text)

**Files:**
- Create: `web/app/history/page.empty-state.test.ts`

**Steps:**
1. Add a Vitest test asserting `web/app/history/page.tsx` contains `发起新对话`.

---

### Task 13: (Optional) Improve left-list empty state copy

**Files:**
- Modify: `web/app/history/page.tsx`

**Steps:**
1. If there are no conversations, add a one-line hint (“去首页发起新对话”) to reduce dead-end feel.

---

### Task 14: Run frontend unit tests

Run:
```bash
cd web && pnpm run test
```
Expected: PASS.

---

### Task 15: Run frontend typecheck

Run:
```bash
cd web && pnpm run typecheck
```
Expected: PASS.

---

### Task 16: Run frontend lint

Run:
```bash
cd web && pnpm run lint
```
Expected: PASS.

---

### Task 17: Run UI baseline checks

Run:
```bash
cd web && pnpm run ui-check
```
Expected: PASS.

---

### Task 18: Run API contract checks (static FE/BE alignment)

Run:
```bash
cd web && pnpm run api-check
```
Expected: PASS.

---

### Task 19: (Best-effort) Ping backend for local dev alignment

Run:
```bash
cd web && pnpm run api-ping
```
Expected: PASS if backend is running; otherwise FAIL with `fetch failed` (non-blocking for this UI-only change).

---

### Task 20: Final verification + single commit on `main`

**Steps:**
1. Ensure `git status` is clean except intended changes.
2. Run:
```bash
cd web && pnpm run verify
```
3. Commit once:
```bash
git add docs/plans/2026-02-04-home-history-ui-review-design.md \
        docs/plans/2026-02-04-home-history-ui-review.md \
        web/components/chat-area.tsx \
        web/app/history/page.tsx \
        web/components/chat-area.welcome.test.ts \
        web/app/history/page.empty-state.test.ts
git commit -m "ui: improve home welcome + history empty states"
```

