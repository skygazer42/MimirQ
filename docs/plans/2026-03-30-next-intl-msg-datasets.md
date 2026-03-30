# Next Intl Datasets Messages Rollout Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Move every dataset management copy into focused next-intl namespaces so the slice can roll through translations without visual regressions.
**Architecture:** Keep the same UI structure but source all labels, buttons, dialogs, and toasts from `useTranslations` (new `DatasetsPage`, `DatasetFolderTree`, and `DatasetCategories` namespaces). Pass translated labels down to helper views so existing render tests keep working without wiring a provider.
**Tech Stack:** Next.js (app router + client components), `next-intl`, TypeScript, Vitest source tests, pnpm scripts.

---

### Task 1: Datasets page translation lifting

**Files:**
- Modify: `web/components/datasets/datasets-page.tsx`
- Modify: `web/components/datasets/datasets-page.source.test.ts`
- Modify: `web/i18n/messages/zh-CN.ts`
- Test: `components/datasets/datasets-page.source.test.ts`

**Step 1: Write the failing test**
```ts
expect(src).toContain("import { useTranslations } from 'next-intl'")
expect(src).toContain("const t = useTranslations('DatasetsPage')")
expect(src).toContain("t('pageTitle')")
```

**Step 2: Run the test to see it fail**
Run: `pnpm vitest run components/datasets/datasets-page.source.test.ts`
Expected: current source lacks `useTranslations` usage so the new assertions fail.

**Step 3: Update the component**
- Import `useTranslations('DatasetsPage')` and replace every hardcoded label, placeholder, toast, and dialog text with `t` calls (use `t.rich` when text needs inline markup).
- Use `t('permission.allTeamMembers')`, etc., for the permission badge logic.
- Add the required keys in `zh-CN.ts` under the new `DatasetsPage` namespace.

**Step 4: Run the test again**
Run: `pnpm vitest run components/datasets/datasets-page.source.test.ts`
Expected: The new assertions now pass because `useTranslations` is wired and `t('pageTitle')` exists.

**Step 5: Commit changes for the page slice**
Run:
```
git add web/components/datasets/datasets-page.tsx web/components/datasets/datasets-page.source.test.ts web/i18n/messages/zh-CN.ts
git commit -m "feat: intl datasets page copy"
```

### Task 2: Dataset folder tree translations

**Files:**
- Modify: `web/components/document-library/dataset-folder-tree.tsx`
- Test: `components/document-library/dataset-folder-tree.test.ts`
- Modify: `web/i18n/messages/zh-CN.ts`

**Step 1: Update the view to take label props**
Deliver a `labels` prop (`collapse`, `expand`, `allDirectories`, `loading`, `emptyWithPath`, `empty`) with defaults so the current rendering test still asserts `全部目录` while the app passes `t('allDirectories')`.

**Step 2: Add translation checks to the test**
```ts
const html = renderToStaticMarkup(...)
expect(html).toContain('全部目录')
expect(html).toContain('foo')
```
```
*(This now verifies the view still renders when labels come from translations.)*

**Step 3: Update the container**
- Import `useTranslations('DatasetFolderTree')` and use it for the header, `aria-label`, button text, and error messages (`formatApiError`).
- Pass `labels` built from `t('collapse')`, `t('expand')`, etc., to the view.
- Add the new keys under `DatasetFolderTree` in `zh-CN.ts`.

**Step 4: Run vitest for the folder tree test**
Run: `pnpm vitest run components/document-library/dataset-folder-tree.test.ts`

**Step 5: Commit the folder tree work**
```
git add web/components/document-library/dataset-folder-tree.tsx web/components/document-library/dataset-folder-tree.test.ts web/i18n/messages/zh-CN.ts
git commit -m "feat: intl dataset folder tree copy"
```

### Task 3: Dataset category components translations

**Files:**
- Modify: `web/components/dataset-categories/category-tree.tsx`
- Modify: `web/components/dataset-categories/category-tree.test.ts`
- Modify: `web/components/dataset-categories/category-multi-select.tsx`
- Modify: `web/components/dataset-categories/category-multi-select.source.test.ts`
- Modify: `web/i18n/messages/zh-CN.ts`

**Step 1: Update the category tree test to expect translation-driven labels**
```ts
expect(html).toContain('全部分类')
```
```
*(This keeps the test passing once the view accepts `labels`.)*

**Step 2: Update the multi-select source test**
Add assertions for `useTranslations('DatasetCategories')` and key strings like `t('multiSelect.empty')` so the test fails until we add translations.

**Step 3: Update both components**
- Have `DatasetCategoryTree` import `useTranslations('DatasetCategories')`, translate header, buttons, empty states, and pass `labels` to `DatasetCategoryTreeView` for `collapse`, `expand`, and `allCategories` copy.
- Update `DatasetCategoryTreeView`/`DatasetCategoryTreeView` to accept those labels via props with fallbacks used by tests.
- Update `DatasetCategoryMultiSelect` to use `t('multiSelect.*')` for buttons, toasts, placeholders, and list-empty copy, plus `aria-label` strings.
- Add all referenced keys under the `DatasetCategories` namespace in `zh-CN.ts`.

**Step 4: Run vitest for the category suite**
Run: `pnpm vitest run components/dataset-categories/category-tree.test.ts components/dataset-categories/category-multi-select.source.test.ts`

**Step 5: Commit the category work**
```
git add web/components/dataset-categories/category-tree.tsx web/components/dataset-categories/category-tree.test.ts web/components/dataset-categories/category-multi-select.tsx web/components/dataset-categories/category-multi-select.source.test.ts web/i18n/messages/zh-CN.ts
git commit -m "feat: intl dataset category copy"
```

Plan complete and saved to `docs/plans/2026-03-30-next-intl-msg-datasets.md`. Execution option: subagent-driven (this session) using superpowers:subagent-driven-development.
