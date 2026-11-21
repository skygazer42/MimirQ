import { expect, test, type Page } from '@playwright/test'

import {
  installCommonApiMocks,
  PARSED_MARKDOWN,
  UPLOADED_DOCUMENT_FILENAME,
  UPLOADED_DOCUMENT_ID,
} from './enterprise-quality-telemetry.helpers'

test.use({ serviceWorkers: 'block' })

async function readCachedBodies(page: Page): Promise<string[] | null> {
  return page.evaluate(async () => {
    const databases = await indexedDB.databases()
    if (!databases.some((database) => database.name === 'mimirq')) return null
    const database = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('mimirq')
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
    try {
      if (!database.objectStoreNames.contains('doc_contents')) return null
      return await new Promise<string[]>((resolve, reject) => {
        const request = database.transaction('doc_contents', 'readonly').objectStore('doc_contents').getAll()
        request.onsuccess = () =>
          resolve((request.result as Array<{ markdownContent: string }>).map((record) => record.markdownContent))
        request.onerror = () => reject(request.error)
      })
    } finally {
      database.close()
    }
  })
}

for (const viewport of [
  { width: 1280, height: 720 },
  { width: 390, height: 844 },
]) {
  test(`retains a failed deletion and confirms its retry at width ${viewport.width}`, async ({ page }) => {
    await page.setViewportSize(viewport)
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    const state = {
      uploaded: false,
      parsingDocuments: [
        {
          id: UPLOADED_DOCUMENT_ID,
          filename: UPLOADED_DOCUMENT_FILENAME,
          file_type: 'md',
          file_size: PARSED_MARKDOWN.length,
          status: 'completed',
          created_at: '2026-11-13T00:00:00Z',
          updated_at: '2026-11-13T00:00:00Z',
          error_message: null,
          markdown_content: PARSED_MARKDOWN,
          original_markdown_content: PARSED_MARKDOWN,
          parser_backend: 'text',
        },
      ],
    }
    await installCommonApiMocks(page, state)
    let releaseDelete!: () => void
    const pendingDelete = new Promise<void>((resolve) => {
      releaseDelete = resolve
    })
    let attempts = 0
    const failure = '拒绝删除：' + 'D'.repeat(220)
    await page.route(
      (url) => url.pathname === `/api/v1/parsing/documents/${UPLOADED_DOCUMENT_ID}`,
      async (route) => {
        if (route.request().method() !== 'DELETE') {
          await route.fallback()
          return
        }
        attempts += 1
        if (attempts === 1) {
          await pendingDelete
          await route.fulfill({ status: 503, json: { detail: failure } })
          return
        }
        state.parsingDocuments = []
        await route.fulfill({ status: 204, body: '' })
      },
    )
    await page.goto('/parsing')
    await page.getByLabel('选择文档', { exact: true }).click()
    const directory = page.getByRole('dialog', { name: '文件目录', exact: true, includeHidden: true })
    await directory.getByText(UPLOADED_DOCUMENT_FILENAME, { exact: true }).click()
    await expect(page.getByRole('region', { name: '解析结果', exact: true })).toContainText(
      'Enterprise Telemetry Sample',
    )
    await expect.poll(() => readCachedBodies(page)).toEqual(expect.arrayContaining([PARSED_MARKDOWN]))
    await page.getByLabel('选择文档', { exact: true }).click()
    await directory.getByText(UPLOADED_DOCUMENT_FILENAME, { exact: true }).hover()
    await directory.getByRole('button', { name: '删除', exact: true }).click()
    const confirmation = page.getByRole('alertdialog', { name: '删除该文件？', exact: true })
    const confirm = confirmation.getByRole('button', { name: '删除', exact: true })
    const widthBefore = await confirm.evaluate((element) => getComputedStyle(element).width)
    await confirm.click()
    try {
      await expect(confirm).toBeDisabled()
      await expect(confirmation.getByRole('button', { name: '返回', exact: true })).toBeDisabled()
      expect(await confirm.evaluate((element) => getComputedStyle(element).width)).toBe(widthBefore)
      await page.keyboard.press('Escape')
      await expect(confirmation).toBeVisible()
      await expect(directory.getByText(UPLOADED_DOCUMENT_FILENAME, { exact: true })).toBeVisible()
    } finally {
      releaseDelete()
    }
    await expect(confirmation.getByRole('alert')).toContainText(failure)
    expect(await confirmation.evaluate((element) => element.scrollWidth > element.clientWidth)).toBe(false)
    const heightLimit = await confirmation.evaluate((element) => Number.parseFloat(getComputedStyle(element).maxHeight))
    expect(heightLimit).toBeLessThan(viewport.height)
    await expect.poll(() => readCachedBodies(page)).toEqual(expect.arrayContaining([PARSED_MARKDOWN]))
    await page.screenshot({
      path: `../.frontend-structure/20261112-full-frontend-guidelines/queue-confirmation/delete-failure-${viewport.width}.png`,
    })
    await confirm.focus()
    await page.keyboard.press('Enter')
    await expect(confirmation).toHaveCount(0)
    await expect(directory.getByText(UPLOADED_DOCUMENT_FILENAME, { exact: true })).toHaveCount(0)
    await expect.poll(() => readCachedBodies(page)).toEqual([])
    await page.reload()
    await page.getByLabel('选择文档', { exact: true }).click()
    await expect(directory.getByText(UPLOADED_DOCUMENT_FILENAME, { exact: true })).toHaveCount(0)
    expect(attempts).toBe(2)
    expect(pageErrors).toEqual([])
  })
}
