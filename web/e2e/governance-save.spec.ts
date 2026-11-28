import { expect, test } from '@playwright/test'

import {
  installCommonApiMocks,
  PARSED_MARKDOWN,
  UPLOADED_DOCUMENT_FILENAME,
  UPLOADED_DOCUMENT_ID,
} from './enterprise-quality-telemetry.helpers'

test.use({ serviceWorkers: 'block' })

test.beforeEach(async ({ page }) => {
  await installCommonApiMocks(page, {
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
  })
  await page.goto('/data-governance')
  await expect(page.locator('[data-governance-document]')).toContainText('Enterprise Telemetry Sample', {
    timeout: 60_000,
  })
})

for (const failure of ['storage unavailable', 'index write rejected', 'content write rejected'] as const) {
  test(`retains the draft and retries after ${failure}`, async ({ page }) => {
    const pageErrors: string[] = []
    page.on('pageerror', (error) => pageErrors.push(error.message))
    const draft = '# Saved after recovery\n\nThe draft survives a failed save and a reload.'
    await page.getByRole('button', { name: '编辑', exact: true }).click()
    const editor = page.getByRole('textbox', { name: '编辑文档正文', exact: true })
    await editor.fill(draft)
    const restoreHandle = await page.evaluateHandle((failure) => {
      if (failure === 'storage unavailable') {
        const descriptor = Object.getOwnPropertyDescriptor(window, 'localStorage')
        if (descriptor === undefined) throw new Error('Expected the native localStorage property')
        Object.defineProperty(window, 'localStorage', {
          configurable: true,
          get() {
            throw new DOMException('本地存储不可用', 'SecurityError')
          },
        })
        return () => {
          Object.defineProperty(window, 'localStorage', descriptor)
        }
      }
      if (failure === 'index write rejected') {
        const setItem = Storage.prototype.setItem
        Storage.prototype.setItem = function (this: Storage, key: string, value: string) {
          if (key.startsWith('mimirq_parsed_files:')) throw new DOMException('文档索引写入被拒绝', 'QuotaExceededError')
          setItem.call(this, key, value)
        }
        return () => {
          Storage.prototype.setItem = setItem
        }
      }
      const open = IDBFactory.prototype.open
      IDBFactory.prototype.open = () => {
        throw new DOMException('正文存储不可用', 'SecurityError')
      }
      return () => {
        IDBFactory.prototype.open = open
      }
    }, failure)
    try {
      await page.getByRole('button', { name: '保存', exact: true }).click()
      await expect(page.getByText(/保存失败：.*修改内容已保留/)).toBeVisible()
      await expect(editor).toHaveValue(draft)
      await expect(page.locator('[data-governance-reader] footer').getByRole('status')).toHaveText('修改尚未保存')
      await expect(page.getByText('治理结果已保存', { exact: true })).toHaveCount(0)
      await expect(page.getByRole('button', { name: '保存', exact: true })).toBeEnabled()
      await expect(page).toHaveURL(/\/data-governance$/)
      if (failure === 'storage unavailable') {
        await page.screenshot({
          path: 'E:/MimirQ/.frontend-structure/20261112-full-frontend-guidelines/durable-save/save-failure.png',
        })
      }
    } finally {
      await restoreHandle.evaluate((restore) => restore())
      await restoreHandle.dispose()
    }

    await page.getByRole('button', { name: '保存', exact: true }).focus()
    await page.keyboard.press('Enter')
    await expect(page.locator('[data-governance-reader] footer')).toContainText('治理结果已保存')
    await page.reload()
    await expect(page.locator('[data-governance-document]')).toContainText(
      'The draft survives a failed save and a reload.',
    )
    await page.getByRole('button', { name: '原文', exact: true }).click()
    await expect(page.locator('[data-governance-document]')).toContainText('Enterprise Telemetry Sample')
    expect(pageErrors).toEqual([])
  })
}

test('batch submission preserves the saved body while its preview is still loading', async ({ page }) => {
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.locator('[data-governance-reader] footer')).toContainText('治理结果已保存')
  await page.addInitScript(() => {
    const open = IDBFactory.prototype.open
    const callbacks: Array<() => void> = []
    let released = false
    const testWindow = window as typeof window & { releaseGovernanceReads?: () => void }
    IDBFactory.prototype.open = function (this: IDBFactory, name: string, version?: number) {
      const request = version === undefined ? open.call(this, name) : open.call(this, name, version)
      if (name === 'mimirq') {
        request.addEventListener('success', (event) => {
          if (released) return
          event.stopImmediatePropagation()
          const handler = request.onsuccess
          if (handler === null) throw new Error('Expected the native database open handler')
          callbacks.push(() => handler.call(request, event))
        })
      }
      return request
    }
    testWindow.releaseGovernanceReads = () => {
      released = true
      IDBFactory.prototype.open = open
      for (const callback of callbacks.splice(0)) callback()
      delete testWindow.releaseGovernanceReads
    }
  })
  await page.reload()
  await expect(page.getByLabel('文档正文', { exact: true }).getByText('正在加载正文…', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '选择文档', exact: true }).click()
  await page.getByRole('button', { name: '批量选择切块文档', exact: true }).click()
  await page.getByRole('checkbox', { name: `选择切块文档 ${UPLOADED_DOCUMENT_FILENAME}`, exact: true }).check()
  await page.getByRole('button', { name: '切块', exact: true }).click()
  await expect(page.locator('[data-governance-reader] footer')).toContainText('正在保存…')
  await page.screenshot({
    path: 'E:/MimirQ/.frontend-structure/20261112-full-frontend-guidelines/durable-save/batch-loading.png',
  })
  await page.evaluate(() => {
    const testWindow = window as typeof window & { releaseGovernanceReads: () => void }
    testWindow.releaseGovernanceReads()
  })
  await page.waitForURL(/\/chunk-preview$/)
  const records = await page.evaluate(
    () =>
      new Promise<unknown[]>((resolve, reject) => {
        const request = indexedDB.open('mimirq', 2)
        request.onerror = () => reject(request.error)
        request.onsuccess = () => {
          const database = request.result
          try {
            const transaction = database.transaction('doc_contents', 'readonly')
            const read = transaction.objectStore('doc_contents').getAll()
            read.onsuccess = () => resolve(read.result)
            read.onerror = () => reject(read.error)
            transaction.oncomplete = () => database.close()
            transaction.onabort = () => database.close()
          } catch (error) {
            database.close()
            reject(error)
          }
        }
      }),
  )
  expect(records).toHaveLength(1)
  expect(records).toContainEqual(
    expect.objectContaining({ markdownContent: PARSED_MARKDOWN, originalMarkdownContent: PARSED_MARKDOWN }),
  )
  expect(pageErrors).toEqual([])
})
