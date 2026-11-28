import { expect, test } from '@playwright/test'

import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'
import { readParsingLibrary, seedTextParsingLibrary } from './parsing-library.helpers'
import type { ParsedFileData } from '../store/use-parsed-files-store'

test.use({ serviceWorkers: 'block' })

function libraryFile(overrides: Partial<ParsedFileData> = {}): ParsedFileData {
  return {
    id: 'failure-document',
    filename: 'failure.md',
    fileType: 'md',
    fileSize: 0,
    markdownContent: '# Saved draft',
    originalMarkdownContent: '# Saved original',
    parsedAt: '2026-11-14T00:00:00Z',
    parser: 'Text',
    parserBackend: 'text',
    source: 'parsing_workspace',
    status: 'parsed',
    folderId: 'root',
    ...overrides,
  }
}

function remoteDocument(file: ParsedFileData) {
  return {
    id: file.id,
    filename: file.filename,
    file_type: file.fileType,
    file_size: file.fileSize,
    status: file.status === 'error' ? 'failed' : 'completed',
    error_message: file.error ?? null,
    created_at: file.parsedAt,
    updated_at: file.parsedAt,
    markdown_content: file.markdownContent,
    original_markdown_content: file.originalMarkdownContent,
    parser_backend: 'text',
  }
}

test('keeps the main parsing error when diagnostics are invalid and renders valid zero diagnostics', async ({
  page,
}) => {
  const file = libraryFile({ status: 'error', error: 'Previous parse failed' })
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [remoteDocument(file)] })
  let parses = 0
  await page.route(
    (url) => url.pathname === `/api/v1/parsing/documents/${file.id}/parse`,
    async (route) => {
      parses += 1
      if (parses < 3) {
        await route.fulfill({
          status: 422,
          json: {
            detail: {
              message: 'Parser unavailable',
              diagnostics:
                parses === 1
                  ? { suggested_backends: 'marker' }
                  : {
                      error_type: null,
                      suggested_backends: [],
                      pdf_sample: {
                        page_count: 0,
                        is_scanned: false,
                        samples: [{ page: 1, text_chars: 0, excerpt: '' }],
                      },
                    },
            },
          },
        })
        return
      }
      await route.fulfill({
        json: {
          document_id: file.id,
          parser_backend: 'text',
          markdown_content: '# Recovered body',
          original_markdown_content: '# Saved original',
          edited: false,
          parse_duration_sec: 0,
        },
      })
    },
  )
  const storageKey = await seedTextParsingLibrary(page, [file])
  await page.getByLabel('选择文档', { exact: true }).click()
  await page.getByRole('dialog', { name: '文件目录', exact: true }).getByText(file.filename, { exact: true }).click()
  const result = page.getByRole('region', { name: '解析结果', exact: true })
  await result.getByRole('button', { name: '重试解析', exact: true }).click()
  await expect(result.getByRole('alert')).toContainText('Parser unavailable')
  await expect(result).toContainText('Saved draft')
  await expect(result.getByText('查看 PDF 诊断', { exact: true })).toHaveCount(0)
  await result.getByRole('button', { name: '重试解析', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(result.getByText('查看 PDF 诊断', { exact: true })).toBeVisible()
  await result.getByText('查看 PDF 诊断', { exact: true }).click()
  await expect(result.getByRole('alert')).toContainText('0 页')
  await expect(result.getByRole('alert')).toContainText('第 1 页 · 0 字符')
  await expect(result.getByRole('alert')).toContainText('未检测到可选文字')
  await result.getByText(/第 1 页 · 0 字符/).scrollIntoViewIfNeeded()
  await expect(result.getByText(/第 1 页 · 0 字符/)).toBeVisible()
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/parsing-failures/diagnostics.png',
  })
  await result.getByRole('button', { name: '重试解析', exact: true }).click()
  await expect(result).toContainText('Recovered body')
  expect((await readParsingLibrary(page, storageKey)).files).toHaveLength(1)
  expect(parses).toBe(3)
  expect(errors).toEqual([])
})

test('restores and parses a library-only row through its inline retry', async ({ page }) => {
  const file = libraryFile({ status: 'error', error: 'Retry this document' })
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [remoteDocument(file)] })
  let downloads = 0
  let parses = 0
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${file.id}/download`,
    async (route) => {
      downloads += 1
      await route.fulfill({ contentType: 'text/markdown', body: '# Saved server source' })
    },
  )
  await page.route(
    (url) => url.pathname === `/api/v1/parsing/documents/${file.id}/parse`,
    async (route) => {
      parses += 1
      await route.fulfill({
        json: {
          document_id: file.id,
          parser_backend: 'text',
          markdown_content: '# Retried library result',
          original_markdown_content: '# Saved server source',
          edited: false,
          parse_duration_sec: 0,
        },
      })
    },
  )
  const storageKey = await seedTextParsingLibrary(page, [file])
  await page.goto('/__parsing-library-fixture')
  await page.evaluate(
    async ({ key, id }) => {
      const scope = key.slice('mimirq_parsed_files:'.length)
      const database = await new Promise<IDBDatabase>((resolve, reject) => {
        const request = indexedDB.open('mimirq', 2)
        request.onsuccess = () => resolve(request.result)
        request.onerror = () => reject(request.error)
      })
      try {
        await new Promise<void>((resolve, reject) => {
          const transaction = database.transaction('doc_sources', 'readwrite')
          transaction.objectStore('doc_sources').delete(`${scope}:${id}`)
          transaction.oncomplete = () => resolve()
          transaction.onerror = () => reject(transaction.error)
        })
      } finally {
        database.close()
      }
    },
    { key: storageKey, id: file.id },
  )
  await page.goto('/parsing')
  await page.getByLabel('选择文档', { exact: true }).click()
  const directory = page.getByRole('dialog', { name: '文件目录', exact: true })
  const row = directory.getByRole('treeitem').filter({ hasText: file.filename })
  await expect(row).toHaveCount(1)
  await row.hover()
  await directory.getByRole('button', { name: '重试', exact: true }).click()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('region', { name: '解析结果', exact: true })).toContainText('Retried library result')
  expect(downloads).toBe(1)
  expect(parses).toBe(1)
  expect((await readParsingLibrary(page, storageKey)).files).toHaveLength(1)
})

test('shows a source read failure and recovers with keyboard retry while retaining the body', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const file = libraryFile()
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [remoteDocument(file)] })
  await page.addInitScript(() => {
    const get = IDBObjectStore.prototype.get
    IDBObjectStore.prototype.get = function (key: IDBValidKey | IDBKeyRange) {
      if (this.name === 'doc_sources' && sessionStorage.getItem('reject-source-read') === '1') {
        throw new DOMException('Source read denied', 'NotReadableError')
      }
      return get.call(this, key)
    }
  })
  await seedTextParsingLibrary(page, [file])
  await page.evaluate(() => sessionStorage.setItem('reject-source-read', '1'))
  await page.reload()
  await page.getByLabel('选择文档', { exact: true }).click()
  await page.getByRole('dialog', { name: '文件目录', exact: true }).getByText(file.filename, { exact: true }).click()
  await expect(page.getByRole('region', { name: '解析结果', exact: true })).toContainText('Saved draft')
  await page.getByRole('button', { name: '原文', exact: true }).click()
  const source = page.getByRole('region', { name: '原文', exact: true })
  await expect(source.getByRole('alert')).toContainText('Source read denied')
  await expect(source).toContainText('原文件检查失败')
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/parsing-failures/source-read-390.png',
  })
  await page.evaluate(() => sessionStorage.removeItem('reject-source-read'))
  await source.getByRole('button', { name: '重试检查原文件', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(source.getByRole('alert')).toHaveCount(0)
  await expect(source.getByRole('button', { name: '恢复源文件', exact: true })).toBeVisible()
  await page.getByRole('button', { name: '解析结果', exact: true }).click()
  await expect(page.getByRole('region', { name: '解析结果', exact: true })).toContainText('Saved draft')
})

test('keeps a broken folder index and recovers only after the stored hierarchy is corrected', async ({ page }) => {
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [] })
  const storageKey = await seedTextParsingLibrary(page, [])
  await page.goto('/__parsing-library-fixture')
  const raw = await page.evaluate((key) => {
    const raw = JSON.stringify({
      version: 0,
      state: {
        files: [],
        activeFolderId: 'root',
        folders: [
          { id: 'cycle-a', name: 'A', parentId: 'cycle-b', createdAt: '' },
          { id: 'cycle-b', name: 'B', parentId: 'cycle-a', createdAt: '' },
        ],
      },
    })
    localStorage.setItem(key, raw)
    return raw
  }, storageKey)
  await page.goto('/parsing')
  const alert = page.getByRole('alert').filter({ hasText: '本地文档记录读取失败' })
  await expect(alert).toContainText('循环')
  expect(await page.evaluate((key) => localStorage.getItem(key), storageKey)).toBe(raw)
  await page.evaluate(
    (key) =>
      localStorage.setItem(
        key,
        JSON.stringify({
          version: 0,
          state: { files: [], folders: [], activeFolderId: 'root' },
        }),
      ),
    storageKey,
  )
  await alert.getByRole('button', { name: '重试读取文档', exact: true }).click()
  await expect(alert).toHaveCount(0)
})

test('keeps a new folder draft when the index refuses writes and saves it on retry', async ({ page }) => {
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [] })
  await page.addInitScript(() => {
    const setItem = Storage.prototype.setItem
    Storage.prototype.setItem = function (key: string, value: string) {
      if (key.startsWith('mimirq_parsed_files:') && sessionStorage.getItem('reject-folder-write') === '1') {
        throw new DOMException('Folder index full', 'QuotaExceededError')
      }
      setItem.call(this, key, value)
    }
  })
  const storageKey = await seedTextParsingLibrary(page, [])
  await page.getByLabel('选择文档', { exact: true }).click()
  const directory = page.getByRole('dialog', { name: '文件目录', exact: true })
  await directory.getByRole('button', { name: 'Upload to root folder', exact: true }).click()
  await page.getByRole('menuitem', { name: '新建文件夹', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '新建文件夹', exact: true })
  await dialog.getByRole('textbox').fill('Retained folder')
  const before = await page.evaluate((key) => localStorage.getItem(key), storageKey)
  await page.evaluate(() => sessionStorage.setItem('reject-folder-write', '1'))
  await dialog.getByRole('button', { name: '确定', exact: true }).click()
  await expect(page.getByText('Folder index full', { exact: true })).toBeVisible()
  await expect(dialog.getByRole('textbox')).toHaveValue('Retained folder')
  await expect(directory.getByText('Retained folder', { exact: true })).toHaveCount(0)
  expect(await page.evaluate((key) => localStorage.getItem(key), storageKey)).toBe(before)
  await page.evaluate(() => sessionStorage.removeItem('reject-folder-write'))
  await dialog.getByRole('button', { name: '确定', exact: true }).click()
  await expect(dialog).toHaveCount(0)
  await expect(directory.getByText('Retained folder', { exact: true })).toBeVisible()
  await page.reload()
  await page.getByLabel('选择文档', { exact: true }).click()
  await expect(directory.getByText('Retained folder', { exact: true })).toBeVisible()
  expect(errors).toEqual([])
})
