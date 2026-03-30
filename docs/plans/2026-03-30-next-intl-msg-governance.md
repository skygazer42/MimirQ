# Governance Messages Rollout Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. All work stays inside `/data/temp34/MimirQ/.worktrees/msg-governance`.

**Goal:** Move the governance/admin page copy for Audit, Access Review, RBAC, and the governance settings section into next-intl namespaces so all strings come from `zh-CN.ts`.

**Architecture:** Each page imports `useTranslations` with a dedicated namespace (`AuditPage`, `AccessReviewPage`, `RbacPage`, `GovernanceSection`), all UI copy, button labels, alerts, placeholders, and toast messages reference `t(...)`, and `zh-CN.ts` holds the translations. A focused `source.test.ts` keeps us honest by failing whenever raw Chinese copy resurfaces.

**Tech Stack:** Next.js App Router, `next-intl`, `pnpm`, Vitest source tests, ESLint (TypeScript + React).

---

### Task 1: Source test for governance-admin copy

**Files:**
- Create: `web/app/governance-admin-messages.source.test.ts`

**Step 1: Write the failing test**
```ts
import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

const webRoot = path.resolve(__dirname, '..')
const read = (relative: string) => fs.readFileSync(path.resolve(webRoot, relative), 'utf8')

describe('governance admin copy source', () => {
  it('uses next-intl for each page in this slice', () => {
    const audit = read('app/audit/page.tsx')
    expect(audit).toContain(\"useTranslations('AuditPage')\")
    expect(audit).toContain(\"t('title')\")

    const accessReview = read('app/access-review/page.tsx')
    expect(accessReview).toContain(\"useTranslations('AccessReviewPage')\")
    expect(accessReview).toContain(\"t('summaryTitle')\")

    const rbac = read('app/settings/rbac/page.tsx')
    expect(rbac).toContain(\"useTranslations('RbacPage')\")
    expect(rbac).toContain(\"t('tableHeaders.userId')\")

    const section = read('app/settings/_sections/governance-section.tsx')
    expect(section).toContain(\"useTranslations('GovernanceSection')\")
    expect(section).toContain(\"t('title')\")
  })
})
```

**Step 2: Run it to ensure failure before localization**
Run: `pnpm vitest run app/governance-admin-messages.source.test.ts`
Expected: FAIL (pages still contain Chinese literals).

**Step 3: Keep the test updated during implementation**

**Step 4: After wiring translations, re-run the test to confirm PASS.**

---

### Task 2: Localize governance/admin UI copy

**Files (editing):**
- `web/app/audit/page.tsx`
- `web/app/access-review/page.tsx`
- `web/app/settings/rbac/page.tsx`
- `web/app/settings/_sections/governance-section.tsx`

**Step 1: Import `useTranslations` and initialize `t = useTranslations('Namespace')` for each file.**

**Step 2: Replace every hard-coded Chinese string with `t(...)` lookups, covering:**
- Page metadata (title/description, `PageScaffold` props).
- Action buttons (`刷新`, `重置`, `下载导出`, `JSON`, `保存`, etc.).
- Toast messages (`已复制 details JSON`, `导出 access graph 失败`, etc.).
- Filters, placeholders, summaries, warnings, helper text, and labels (schema/hint text, toggles, stats grid labels, table headers).
- Card/alert copy in the governance section (titles, descriptions, helper paragraphs, switch helper text, ARIA labels).

**Step 3: Use nested keys to keep namespaces organized (e.g., `presets.accessReviewDaily`, `tableHeaders.userId`, `toggles.governanceEnabled`).**

**Step 4: Keep existing logic/structure unchanged aside from string replacements.**

---

### Task 3: Populate the Chinese catalog

**Files:**
- Modify: `web/i18n/messages/zh-CN.ts`

**Step 1: Add these namespaces with the current Chinese text:**
- `AuditPage` (titles, descriptions, actions, filter labels, presets, statuses, toast copy).
- `AccessReviewPage` (metadata, action bar, summary labels, panels, export instructions, warning text, skeleton labels, helper hints).
- `RbacPage` (titles, descriptions, button text, table headers, placeholders, role options, success/error toast strings, status chips).
- `GovernanceSection` (section title, helper badge text, alert copy, toggle labels/descriptions/aria, helper sentences in each card).

**Step 2: Keep the namespace entries grouped/mapped to the keys used in the components.**

---

### Task 4: Verification

**Step 1: Run the focused source test**
Run: `pnpm vitest run app/governance-admin-messages.source.test.ts`
Expected: PASS once translations are wired.

**Step 2: Run ESLint across touched files**
Run: `pnpm eslint app/audit/page.tsx app/access-review/page.tsx app/settings/rbac/page.tsx app/settings/_sections/governance-section.tsx app/governance-admin-messages.source.test.ts i18n/messages/zh-CN.ts`
Expected: no lint errors.

---

### Task 5: Wrap up

**Step 1:** `git status` to verify dirty files.
**Step 2:** Commit with a focused message like `feat: localize governance admin copy`.
**Step 3:** Push the branch: `git push -u origin parallel-next-intl-msg-governance`.
**Step 4:** Report the commit SHA, commands run, and files changed.
