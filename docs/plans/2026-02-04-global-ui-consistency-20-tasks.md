# Global UI Consistency + API Integration (20 Tasks) Implementation Plan

> **For Codex/Claude:** REQUIRED SUB-SKILL: Use `superpowers:executing-plans` to implement this plan task-by-task.

**Goal:** 在不大改布局的信息架构前提下，统一全局 UI 基线（safe-area、阴影 token、搜索框组件化、导航选中态一致性）并完成本地后端接口联调（docker 拉起 + api-ping）。

**Architecture:** 优先改共享 UI primitives（`web/components/ui/*`）与全局导航（`web/components/navbar.tsx`），再在几个高频页面替换重复的搜索框实现为 `SearchInput`。后端联调不改业务逻辑，仅确保本地环境可启动与健康/就绪接口可达。

**Tech Stack:** Next.js 14 + TypeScript + Tailwind + Radix/shadcn；FastAPI + Docker Compose；Vitest（轻量 guard tests）。

**Commit strategy:** 计划拆成 20 个可追踪任务，但按需求 **最终只做 1 个 commit**（分支完成后 ff 合并到 `main`）。

---

### Task 1: Add design notes doc

**Files:**
- Create: `docs/plans/2026-02-04-global-ui-consistency-design.md`

---

### Task 2: Add this plan doc

**Files:**
- Create: `docs/plans/2026-02-04-global-ui-consistency-20-tasks.md`

---

### Task 3: Bootstrap local backend env (untracked) and start docker deps

**Files:** none (expected untracked `.env`, `docker/.env`, `web/.env.local`)

**Steps:**
1. Run:
```bash
make init
make up
```

---

### Task 4: API integration smoke check (backend reachable)

**Files:** none

**Steps:**
1. Verify backend is reachable:
```bash
cd web && pnpm run api-ping
```
Expected: health/ready/meta all `200` and JSON.

2. (Optional) Extra direct check:
```bash
curl -sS http://localhost:8000/api/v1/meta | head
```

---

### Task 5: Add safe-area guard test for fixed global controls (RED)

**Files:**
- Create: `web/components/fixed-controls.safe-area.test.ts`

**Step 1: Write failing test**
```ts
import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('fixed controls safe-area', () => {
  it('navbar toggle respects safe-area-inset-bottom', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'navbar.tsx'), 'utf8')
    expect(src).toContain('safe-area-inset-bottom')
  })

  it('task-center respects safe-area-inset-bottom', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'task-center.tsx'), 'utf8')
    expect(src).toContain('safe-area-inset-bottom')
  })
})
```

**Step 2: Verify RED**
```bash
cd web && pnpm run test -- components/fixed-controls.safe-area.test.ts
```
Expected: FAIL (currently those fixed elements use `bottom-4` without safe-area support).

---

### Task 6: Navbar fixed toggle button respects safe-area-inset

**Files:**
- Modify: `web/components/navbar.tsx`

**Steps:**
1. Update the fixed toggle button className to include:
   - `supports-[padding:env(safe-area-inset-bottom)]:bottom-[calc(env(safe-area-inset-bottom)+1rem)]`
   - (optional) safe-area left

---

### Task 7: TaskCenter fixed container respects safe-area-inset

**Files:**
- Modify: `web/components/task-center.tsx`

**Steps:**
1. Update the outer fixed container className to include:
   - `supports-[padding:env(safe-area-inset-bottom)]:bottom-[calc(env(safe-area-inset-bottom)+1rem)]`
   - `supports-[padding:env(safe-area-inset-right)]:right-[calc(env(safe-area-inset-right)+1rem)]`

**Verify (GREEN):**
```bash
cd web && pnpm run test -- components/fixed-controls.safe-area.test.ts
```

---

### Task 8: Button icon size uses Tailwind `size-*` for square controls (consistency)

**Files:**
- Modify: `web/components/ui/button.tsx`

**Steps:**
1. Replace `h-* w-*` pairs in `size.icon` with `size-*` (e.g. `h-11 w-11` -> `size-11`).

---

### Task 9: EmptyState uses `size-*` for square icon container (consistency)

**Files:**
- Modify: `web/components/ui/empty-state.tsx`

**Steps:**
1. Replace icon wrapper `h-16 w-16` with `size-16`.

---

### Task 10: SearchInput uses `size-*` for clear button hit target (consistency)

**Files:**
- Modify: `web/components/ui/search-input.tsx`

**Steps:**
1. Replace clear IconButton `h-8 w-8` with `size-8` (and keep positioning).

---

### Task 11: Knowledge page filter search uses shared `SearchInput` (remove custom implementation)

**Files:**
- Modify: `web/app/knowledge/page.tsx`

**Steps:**
1. Replace the custom search input (Search icon + input + clear button) with `SearchInput`.
2. Preserve existing “glass” feel via `inputClassName` (rounded, bg opacity, blur) where needed.

---

### Task 12: Ingestion page search uses shared `SearchInput`

**Files:**
- Modify: `web/app/knowledge/ingestion/page.tsx`

---

### Task 13: Prompts page search uses shared `SearchInput`

**Files:**
- Modify: `web/app/prompts/page.tsx`

---

### Task 14: Reports page searches use shared `SearchInput` (directory + category)

**Files:**
- Modify: `web/app/reports/page.tsx`

---

### Task 15: Popover shadow uses token `shadow-strong` (overlay consistency)

**Files:**
- Modify: `web/components/ui/popover.tsx`

**Steps:**
1. Replace `shadow-md` with `shadow-strong`.

---

### Task 16: DropdownMenu shadows use token `shadow-strong` (overlay consistency)

**Files:**
- Modify: `web/components/ui/dropdown-menu.tsx`

**Steps:**
1. Replace `shadow-md` and `shadow-lg` with `shadow-strong`.

---

### Task 17: Add overlay shadow token guard test (RED -> GREEN)

**Files:**
- Create: `web/components/ui/overlay-shadows.token.test.ts`

**Steps:**
1. Write a test asserting `popover.tsx` and `dropdown-menu.tsx` contain `shadow-strong` and do not contain `shadow-md`/`shadow-lg`.
2. Run it (should be RED before tasks 15/16; GREEN after).

---

### Task 18: Navbar active route affordance (indicator + primary tint)

**Files:**
- Modify: `web/components/navbar.tsx`

**Steps:**
1. Adjust active menu item style to include a subtle indicator (e.g., left border/rail) and primary tint on icon/text.
2. Keep spacing/layout stable.

---

### Task 19: Full verification (frontend + api ping)

**Steps:**
1. Run:
```bash
cd web && pnpm run verify
cd web && pnpm run api-ping
```

---

### Task 20: Single final commit + fast-forward merge to main

**Steps:**
1. Ensure only intended changes are staged.
2. Commit once on branch:
```bash
git add docs/plans/2026-02-04-global-ui-consistency-design.md \
        docs/plans/2026-02-04-global-ui-consistency-20-tasks.md \
        web/components/navbar.tsx \
        web/components/task-center.tsx \
        web/components/fixed-controls.safe-area.test.ts \
        web/components/ui/button.tsx \
        web/components/ui/empty-state.tsx \
        web/components/ui/search-input.tsx \
        web/app/knowledge/page.tsx \
        web/app/knowledge/ingestion/page.tsx \
        web/app/prompts/page.tsx \
        web/app/reports/page.tsx \
        web/components/ui/popover.tsx \
        web/components/ui/dropdown-menu.tsx \
        web/components/ui/overlay-shadows.token.test.ts
git commit -m "ui: global consistency polish + backend integration"
```
3. Fast-forward merge into `main` (from the primary workspace):
```bash
git checkout main
git merge --ff-only ui-global-consistency
```

