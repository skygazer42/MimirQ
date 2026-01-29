# Governance Profiles UI Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** 在 Web 端新增“治理 Profiles 管理”页面：支持列表/搜索、创建/编辑、自测（clean-preview）、导入/导出/删除，方便文档治理配置落地。

**Architecture:** 仅新增前端页面 + 少量纯函数工具；复用现有后端 API：`/api/v1/pipeline/governance-profiles/*` 与 `POST /api/v1/pipeline/clean-preview`。

**Tech Stack:** Next.js 14 (App Router), Tailwind/shadcn, `pipelineApi`（axios client）, vitest（node env）。

---

### Task 1: Add Pure Helper + Tests (Profile -> CleanPreviewRequest)

**Files:**
- Create: `web/lib/governance-profile-utils.test.ts`
- Create: `web/lib/governance-profile-utils.ts`

**Step 1: Write the failing test**

```ts
import { describe, expect, it } from 'vitest'
import type { GovernanceProfilePayload } from '@/types'
import { buildCleanPreviewRequestFromGovernanceProfile } from './governance-profile-utils'

describe('buildCleanPreviewRequestFromGovernanceProfile', () => {
  it('maps governance pipeline_patch + regex_rules into clean-preview request', () => {
    const payload: GovernanceProfilePayload = {
      version: '1',
      input_formats: ['markdown'],
      pipeline_patch: {
        governance_max_blank_lines: 2,
        governance_unwrap_lines: false,
        governance_remove_boilerplate: true,
        governance_normalize_urls: true,
        governance_normalize_urls_strip_tracking: false,
      },
      regex_rules: [{ pattern: 'foo', repl: 'bar', flags: 0 }],
    }
    const req = buildCleanPreviewRequestFromGovernanceProfile(payload, 'foo', {
      includeDiff: true,
      inputFormat: 'markdown',
    })
    expect(req.markdown).toBe('foo')
    expect(req.rules).toEqual([{ pattern: 'foo', repl: 'bar', flags: 0 }])
    expect(req.max_blank_lines).toBe(2)
    expect(req.unwrap_lines).toBe(false)
    expect(req.remove_boilerplate).toBe(true)
    expect(req.normalize_urls).toBe(true)
    expect(req.normalize_urls_strip_tracking).toBe(false)
    expect(req.include_diff).toBe(true)
  })
})
```

**Step 2: Run test to verify it fails**

Run: `pnpm -C web test`
Expected: FAIL with module/function missing.

**Step 3: Write minimal implementation**

```ts
// buildCleanPreviewRequestFromGovernanceProfile(...) returns a CleanPreviewRequest
```

**Step 4: Run test to verify it passes**

Run: `pnpm -C web test`
Expected: PASS.

**Step 5: Commit**

```bash
git add web/lib/governance-profile-utils.ts web/lib/governance-profile-utils.test.ts
git commit -m "feat(web): add governance profile clean-preview helper"
```

---

### Task 2: Create Governance Profiles Page Route (+ minimal UI skeleton)

**Files:**
- Create: `web/app/data-governance/profiles/page.tsx`
- Create: `web/components/governance-profiles/governance-profiles-page.tsx`

**Step 1: Write minimal page that loads profiles**
- Use `pipelineApi.listGovernanceProfiles({ include_builtin: true })`
- Render: table/list (name/key/is_system/updated_at) + search box

**Step 2: Verify build**

Run: `pnpm -C web typecheck`
Expected: PASS.

**Step 3: Commit**

```bash
git add web/app/data-governance/profiles/page.tsx web/components/governance-profiles/governance-profiles-page.tsx
git commit -m "feat(web): add governance profiles page"
```

---

### Task 3: Add Create/Edit Drawer + Profile Test (clean-preview)

**Files:**
- Modify: `web/components/governance-profiles/governance-profiles-page.tsx`
- Create: `web/components/governance-profiles/profile-editor-drawer.tsx`

**Step 1: Editor fields**
- `name`, `key`（创建时可编辑）、`description`
- `payload.input_formats`（checkbox）
- `payload.pipeline_patch`：以“常用治理开关”表单方式编辑（不做全量暴露，提供 Advanced JSON 编辑区）
- `payload.regex_rules`：可增删（pattern/repl/flags）

**Step 2: Test run**
- 输入 markdown/html sample + 选择 inputFormat
- 使用 `buildCleanPreviewRequestFromGovernanceProfile()` + `pipelineApi.cleanPreview()` 显示结果与 diff

**Step 3: Run quick checks**

Run: `pnpm -C web test && pnpm -C web typecheck`
Expected: PASS.

**Step 4: Commit**

```bash
git add web/components/governance-profiles/profile-editor-drawer.tsx web/components/governance-profiles/governance-profiles-page.tsx
git commit -m "feat(web): add governance profile editor and sandbox test"
```

---

### Task 4: Import/Export/Delete + Navbar Link

**Files:**
- Modify: `web/components/governance-profiles/governance-profiles-page.tsx`
- Modify: `web/components/navbar.tsx`

**Step 1: Import**
- file picker -> `pipelineApi.importGovernanceProfiles(file, overwrite)`
- 显示 created/updated + items

**Step 2: Export**
- action -> `pipelineApi.exportGovernanceProfile(profileRef)` -> download blob

**Step 3: Delete**
- confirm dialog -> `pipelineApi.deleteGovernanceProfile(profileRef)`（built-in 禁用）

**Step 4: Add Navbar entry**
- under “入库流程”：`治理配置` -> `/data-governance/profiles`

**Step 5: Verify**

Run: `pnpm -C web test && pnpm -C web typecheck`
Expected: PASS.

**Step 6: Commit**

```bash
git add web/components/navbar.tsx web/components/governance-profiles/governance-profiles-page.tsx
git commit -m "feat(web): add governance profile import/export/delete and nav link"
```

---

### Task 5: Polish + Docs Link

**Files:**
- Modify: `docs/guides/data_governance.md`

**Step 1: Add section “治理 Profiles 管理”**
- 简述用途、入口、导入导出格式、注意事项（regex 安全、built-in 只读）

**Step 2: Verify**
- `pnpm -C web lint`（如果项目可跑）

**Step 3: Commit**

```bash
git add docs/guides/data_governance.md
git commit -m "docs: add governance profiles UI usage notes"
```

