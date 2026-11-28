import { expect, test } from '@playwright/test'

import { makeProfileScan } from '../test/dataset-profile-fixtures'
import { installCommonApiMocks, UPLOADED_DOCUMENT_ID } from './enterprise-quality-telemetry.helpers'
import { policyDatasetId } from './dataset-policy.helpers'
import { profileSummary } from './remaining-pages.helpers'
import type { DatasetProfileDocumentOut, Document } from '../types'

test.use({ serviceWorkers: 'block' })

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
]) {
  test(`preserves tag input and confirms a saved document at width ${viewport.width}`, async ({ page }) => {
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    const tags = Array.from({ length: 50 }, (_, index) => `#标签 ${index}`)
    let stored: Document & DatasetProfileDocumentOut = {
      id: UPLOADED_DOCUMENT_ID,
      dataset_id: policyDatasetId,
      filename: 'tag-contract.md',
      file_type: 'md',
      file_size: 100,
      status: 'completed',
      processing_progress: 100,
      processing_attempts: 0,
      error_message: null,
      chunk_count: 0,
      total_characters: 100,
      publication_status: 'draft',
      preview: null,
      preview_truncated: false,
      created_at: '2026-11-16T00:00:00Z',
      updated_at: '2026-11-16T00:00:00Z',
      metadata: { user: { tags } },
    }
    const writes: Array<{ replace: false; patch: { tags: string[] | null } }> = []
    let release!: () => void
    const pending = new Promise<void>((resolve) => {
      release = resolve
    })
    await installCommonApiMocks(page, { uploaded: true, parsingDocuments: [] })
    const profile = profileSummary()
    await page.route(
      (url) => url.pathname.startsWith(`/api/v1/datasets/${policyDatasetId}`),
      async (route) => {
        const path = new URL(route.request().url()).pathname
        const datasetPath = `/api/v1/datasets/${policyDatasetId}`
        if (path === datasetPath)
          await route.fulfill({ json: { id: policyDatasetId, name: 'Tag documents', document_count: 1 } })
        else if (path === `${datasetPath}/profile/summary`) await route.fulfill({ json: profile })
        else if (path === `${datasetPath}/profile/scan-runs`)
          await route.fulfill({ json: { total: 1, items: [makeProfileScan(profile)] } })
        else if (path.startsWith(`${datasetPath}/profile/findings/`))
          await route.fulfill({ json: { total: 1, items: [stored] } })
        else await route.fallback()
      },
    )
    await page.route(
      (url) => url.pathname.replace(/\/$/, '') === '/api/v1/documents',
      (route) => route.fulfill({ json: { items: [stored], total: 1 } }),
    )
    await page.route(
      (url) => url.pathname.startsWith(`/api/v1/documents/${UPLOADED_DOCUMENT_ID}`),
      async (route) => {
        const path = new URL(route.request().url()).pathname
        const documentPath = `/api/v1/documents/${UPLOADED_DOCUMENT_ID}`
        if (path === `${documentPath}/metadata` && route.request().method() === 'PATCH') {
          const body = route.request().postDataJSON() as { replace: false; patch: { tags: string[] | null } }
          writes.push(body)
          if (writes.length === 1) {
            await route.fulfill({ status: 503, json: { detail: '标签保存服务暂不可用' } })
            return
          }
          await pending
          stored = { ...stored, metadata: { user: { tags: body.patch.tags } } }
          await route.fulfill({ json: stored })
        } else if (path === documentPath) {
          await route.fulfill({ json: stored })
        } else if (path === `${documentPath}/chunks`) {
          await route.fulfill({ json: { items: [], total: 0 } })
        } else if (path === `${documentPath}/versions`) {
          await route.fulfill({ json: { document_id: UPLOADED_DOCUMENT_ID, active_pipeline_hash: null, items: [] } })
        } else if (path === `${documentPath}/access`) {
          await route.fulfill({
            json: { mode: 'inherit', owner_id: null, partial_member_list: [], partial_group_list: [] },
          })
        } else if (path === `${documentPath}/lifecycle`) {
          await route.fulfill({ json: { publication_status: 'draft' } })
        } else {
          await route.fallback()
        }
      },
    )
    await page.setViewportSize(viewport)
    await page.goto(`/datasets/${policyDatasetId}/profile`)
    await page.getByRole('button', { name: '查看正文过短文件', exact: true }).click()
    await page.getByRole('button', { name: stored.filename, exact: true }).click()
    const dialog = page.getByRole('dialog', { name: stored.filename, exact: true })
    await expect(dialog).toBeVisible()
    await dialog.getByRole('button', { name: '编辑', exact: true }).first().click()
    const input = dialog.getByRole('textbox', { name: '标签', exact: true })
    const form = dialog.locator('form').filter({ has: page.getByRole('textbox', { name: '标签', exact: true }) })
    const save = dialog.getByRole('button', { name: '保存', exact: true })
    await expect(form.getByText('50 / 50', { exact: true })).toBeVisible()
    await form.getByRole('button', { name: '移除标签 #标签 49', exact: true }).click()

    const overlong = '😀'.repeat(65)
    await input.fill(overlong)
    await input.press('Enter')
    await expect(input).toHaveValue(overlong)
    await expect(form.getByRole('alert')).toContainText('每个标签最多 64 个字符')
    await save.click()
    expect(writes).toEqual([])
    await input.fill('中文')
    await input.dispatchEvent('keydown', { key: 'Enter', isComposing: true, bubbles: true, cancelable: true })
    await expect(form.getByRole('button', { name: '移除标签 中文', exact: true })).toHaveCount(0)
    await expect(input).toHaveValue('中文')
    await input.press('Enter')
    await expect(form.getByRole('button', { name: '移除标签 中文', exact: true })).toBeVisible()
    await form.getByRole('button', { name: '移除标签 中文', exact: true }).click()

    await input.fill('新增, 超额, 剩余')
    await input.press('Enter')
    await expect(form.getByRole('button', { name: '移除标签 新增', exact: true })).toBeVisible()
    await expect(input).toHaveValue(/超额.*剩余/)
    await save.click()
    expect(writes).toEqual([])
    await page.screenshot({
      path: `../.frontend-structure/20261112-full-frontend-guidelines/tag-input/rejected-tags-${viewport.width}.png`,
    })

    await input.fill('')
    await input.fill('待补')
    await input.press('Enter')
    await input.press('Tab')
    await form.getByRole('button', { name: '移除标签 新增', exact: true }).click()
    await save.click()
    expect(writes).toEqual([])
    await expect(input).toHaveValue('待补')
    await form.getByRole('button', { name: '添加', exact: true }).click()
    await expect(input).toHaveValue('')
    await save.click()
    await expect(dialog.getByRole('alert')).toContainText('标签保存服务暂不可用')
    await expect(form.getByText('50 / 50', { exact: true })).toBeVisible()
    expect(
      await dialog.evaluate((element) => {
        const bounds = element.getBoundingClientRect()
        return (
          bounds.left >= 0 &&
          bounds.right <= window.innerWidth &&
          bounds.top >= 0 &&
          bounds.bottom <= window.innerHeight
        )
      }),
    ).toBe(true)
    expect(await form.evaluate((element) => element.scrollWidth <= element.clientWidth)).toBe(true)
    expect(writes[0]).toEqual({ replace: false, patch: { tags: [...tags.slice(0, -1), '待补'] } })
    await dialog.getByRole('alert').scrollIntoViewIfNeeded()
    await page.screenshot({
      path: `../.frontend-structure/20261112-full-frontend-guidelines/tag-input/save-failed-${viewport.width}.png`,
    })
    await save.click()
    try {
      await expect(input).toBeDisabled()
      await form.evaluate((element) => {
        element.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
        element.dispatchEvent(new Event('submit', { bubbles: true, cancelable: true }))
      })
      expect(writes).toHaveLength(2)
    } finally {
      release()
    }
    await expect(form).toHaveCount(0)
    await expect(page.getByText('已更新标签', { exact: true })).toBeVisible()

    await page.reload()
    await page.getByRole('button', { name: '查看正文过短文件', exact: true }).click()
    await page.getByRole('button', { name: stored.filename, exact: true }).click()
    await dialog.getByRole('button', { name: '编辑', exact: true }).first().click()
    await expect(form.getByText('50 / 50', { exact: true })).toBeVisible()
    await expect(form.getByRole('button', { name: '移除标签 #标签 48', exact: true })).toBeVisible()
    await expect(form.getByRole('button', { name: '移除标签 #标签 49', exact: true })).toHaveCount(0)
    await expect(form.getByRole('button', { name: '移除标签 待补', exact: true })).toBeVisible()
    await page.screenshot({
      path: `../.frontend-structure/20261112-full-frontend-guidelines/tag-input/saved-tags-${viewport.width}.png`,
    })
    expect(pageErrors).toEqual([])
  })
}
