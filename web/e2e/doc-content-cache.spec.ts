import { expect, test, type Page } from '@playwright/test'

import type { DocContentCacheRecord } from '../lib/doc-content-cache'
import type { ParsedFileData } from '../store/use-parsed-files-store'
import { readParsingLibrary, seedTextParsingLibrary } from './parsing-library.helpers'
import {
  installCommonApiMocks,
  PARSED_MARKDOWN,
  UPLOADED_DOCUMENT_FILENAME,
  UPLOADED_DOCUMENT_ID,
} from './enterprise-quality-telemetry.helpers'

test.use({ serviceWorkers: 'block' })

async function writeCachedRecord(
  page: Page,
  options: {
    storageKey: string
    storeName: 'doc_contents' | 'doc_sources'
    record: { id: string } & Record<string, unknown>
  },
) {
  await page.evaluate(async ({ storageKey, storeName, record }) => {
    const scope = storageKey.slice('mimirq_parsed_files:'.length)
    const database = await new Promise<IDBDatabase>((resolve, reject) => {
      const request = indexedDB.open('mimirq', 2)
      request.onsuccess = () => resolve(request.result)
      request.onerror = () => reject(request.error)
    })
    try {
      await new Promise<void>((resolve, reject) => {
        const transaction = database.transaction(storeName, 'readwrite')
        transaction.objectStore(storeName).put({ ...record, id: `${scope}:${record.id}` })
        transaction.oncomplete = () => resolve()
        transaction.onerror = () => reject(transaction.error)
        transaction.onabort = () => reject(transaction.error)
      })
    } finally {
      database.close()
    }
  }, options)
}

function cacheFixture() {
  const file: ParsedFileData = {
    id: 'cache-contract',
    filename: 'cache-contract.md',
    fileType: 'md',
    fileSize: 0,
    markdownContent: '# Saved cached body',
    originalMarkdownContent: '# Saved original',
    parsedAt: '2026-11-14T00:00:00Z',
    parser: 'Text',
    parserBackend: 'text',
    source: 'parsing_workspace',
    status: 'parsed',
    folderId: 'root',
  }
  const remote = {
    id: file.id,
    filename: file.filename,
    file_type: 'md',
    file_size: 0,
    status: 'completed',
    error_message: null,
    created_at: file.parsedAt,
    updated_at: file.parsedAt,
    parser_backend: 'text',
    markdown_content: file.markdownContent,
    original_markdown_content: file.originalMarkdownContent,
  }
  return { file, remote }
}

test('keeps saved complete content when the document viewer receives a truncated preview', async ({ page }) => {
  const file: ParsedFileData = {
    ...cacheFixture().file,
    id: UPLOADED_DOCUMENT_ID,
    filename: UPLOADED_DOCUMENT_FILENAME,
    source: 'knowledge_base',
    markdownContent: '# Complete saved result\n\nFull tail must survive.',
    originalMarkdownContent: '# Complete saved original',
  }
  await installCommonApiMocks(page, { uploaded: true, parsingDocuments: [] })
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${file.id}/parsed-content`,
    (route) =>
      route.fulfill({
        json: {
          document_id: file.id,
          available: true,
          markdown_content: '# Short preview',
          original_markdown_content: '# Short original',
          markdown_truncated: true,
          original_markdown_truncated: true,
          max_chars: 200_000,
          persisted_meta: {},
        },
      }),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${file.id}/chunks`,
    (route) => route.fulfill({ json: { items: [], total: 0 } }),
  )
  const storageKey = await seedTextParsingLibrary(page, [file])
  await page.goto(`/?doc=${encodeURIComponent(file.id)}`)
  await expect(page.getByRole('heading', { name: file.filename, exact: true })).toBeVisible()
  await page.getByRole('tab', { name: '文本定位', exact: true }).click()
  await expect(page.getByText(/文本已截断显示/)).toBeVisible()
  expect((await readParsingLibrary(page, storageKey)).bodies).toContainEqual(
    expect.objectContaining({
      markdownContent: file.markdownContent,
      originalMarkdownContent: file.originalMarkdownContent,
    }),
  )
  await page.reload()
  await expect(page.getByRole('heading', { name: file.filename, exact: true })).toBeVisible()
  await expect(page.getByText(/文本已截断显示/)).toBeVisible()
  expect((await readParsingLibrary(page, storageKey)).bodies).toContainEqual(
    expect.objectContaining({
      markdownContent: file.markdownContent,
      originalMarkdownContent: file.originalMarkdownContent,
    }),
  )
})

test('keeps an approved working copy when the viewer receives a different complete server preview', async ({
  page,
}) => {
  const file: ParsedFileData = {
    ...cacheFixture().file,
    id: UPLOADED_DOCUMENT_ID,
    filename: UPLOADED_DOCUMENT_FILENAME,
    source: 'knowledge_base',
    markdownContent: '# Approved working copy',
    originalMarkdownContent: '# Approved original',
  }
  await installCommonApiMocks(page, { uploaded: true, parsingDocuments: [] })
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${file.id}/parsed-content`,
    (route) =>
      route.fulfill({
        json: {
          document_id: file.id,
          available: true,
          markdown_content: 'Different server preview',
          original_markdown_content: 'Different original preview',
          markdown_truncated: false,
          original_markdown_truncated: false,
          max_chars: 200_000,
          persisted_meta: {},
        },
      }),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${file.id}/chunks`,
    (route) => route.fulfill({ json: { items: [], total: 0 } }),
  )
  const storageKey = await seedTextParsingLibrary(page, [file])
  await page.goto(`/?doc=${encodeURIComponent(file.id)}`)
  await expect(page.getByRole('heading', { name: file.filename, exact: true })).toBeVisible()
  await page.getByRole('tab', { name: '文本定位', exact: true }).click()
  await expect(page.getByText('Different server preview', { exact: true })).toBeVisible({ timeout: 30_000 })
  await page.reload()
  await expect(page.getByRole('heading', { name: file.filename, exact: true })).toBeVisible()
  await expect(page.getByText('Different server preview', { exact: true })).toBeVisible({ timeout: 30_000 })
  expect((await readParsingLibrary(page, storageKey)).bodies).toContainEqual(
    expect.objectContaining({
      markdownContent: file.markdownContent,
      originalMarkdownContent: file.originalMarkdownContent,
    }),
  )
})

test('reports malformed cached text without a remote fallback and retries the repaired cache', async ({ page }) => {
  const { file, remote } = cacheFixture()
  const errors: string[] = []
  page.on('pageerror', (error) => errors.push(error.message))
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [remote] })
  let contentRequests = 0
  await page.route(
    (url) => url.pathname === `/api/v1/parsing/documents/${file.id}/content`,
    async (route) => {
      contentRequests += 1
      await route.fallback()
    },
  )
  const storageKey = await seedTextParsingLibrary(page, [file])
  await page.goto('/__parsing-library-fixture')
  await writeCachedRecord(page, {
    storageKey,
    storeName: 'doc_contents',
    record: { id: file.id, markdownContent: 42, originalMarkdownContent: file.originalMarkdownContent, updatedAt: 0 },
  })
  await page.goto('/parsing')
  await page.getByLabel('选择文档', { exact: true }).click()
  await page.getByRole('dialog', { name: '文件目录', exact: true }).getByText(file.filename, { exact: true }).click()
  const result = page.getByRole('region', { name: '解析结果', exact: true })
  await expect(result.getByRole('alert')).toContainText('正文缓存格式不正确')
  await expect(page.getByText('正文读取失败', { exact: true })).toBeVisible()
  expect((await readParsingLibrary(page, storageKey)).bodies).toContainEqual(
    expect.objectContaining({ markdownContent: 42 }),
  )
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/cache-api/invalid-content.png',
  })
  await writeCachedRecord(page, {
    storageKey,
    storeName: 'doc_contents',
    record: { id: file.id, markdownContent: '# Repaired cached body', originalMarkdownContent: '', updatedAt: 0 },
  })
  await result.getByRole('button', { name: '重试读取正文', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(result).toContainText('Repaired cached body')
  await expect(result.getByRole('alert')).toHaveCount(0)
  expect(contentRequests).toBe(0)
  expect(errors).toEqual([])
})

test('reports a malformed source and restores a newly associated native File after reload', async ({ page }) => {
  const { file, remote } = cacheFixture()
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [remote] })
  let downloads = 0
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${file.id}/download`,
    async (route) => {
      downloads += 1
      await route.fallback()
    },
  )
  const storageKey = await seedTextParsingLibrary(page, [file])
  await page.goto('/__parsing-library-fixture')
  await writeCachedRecord(page, {
    storageKey,
    storeName: 'doc_sources',
    record: { id: file.id, filename: '', mimeType: '', size: 0, lastModified: 0, updatedAt: 0, blob: 'invalid Blob' },
  })
  await page.goto('/parsing')
  await page.getByLabel('选择文档', { exact: true }).click()
  await page.getByRole('dialog', { name: '文件目录', exact: true }).getByText(file.filename, { exact: true }).click()
  const source = page.getByRole('region', { name: '原文', exact: true })
  await expect(source.getByRole('alert')).toContainText('原文件缓存格式不正确')
  await expect(page.getByRole('region', { name: '解析结果', exact: true })).toContainText('Saved cached body')
  await source.getByRole('button', { name: '关联本地原文件', exact: true }).click()
  await page.getByLabel('重新关联原文件', { exact: true }).setInputFiles({
    name: 'new-source.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from('# Freshly associated source'),
  })
  await expect(source).toContainText('Freshly associated source')
  await page.reload()
  await page.getByLabel('选择文档', { exact: true }).click()
  await page.getByRole('dialog', { name: '文件目录', exact: true }).getByText(file.filename, { exact: true }).click()
  await source.getByRole('button', { name: '恢复源文件', exact: true }).click()
  await expect(source).toContainText('Freshly associated source')
  expect(downloads).toBe(0)
  expect((await readParsingLibrary(page, storageKey)).files).toHaveLength(1)
})

test('governance and parsing expose an initial cache read failure and recover through retry', async ({ page }) => {
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [] })
  await page.goto('/data-governance')
  await expect(page.getByText('当前范围没有文档', { exact: true })).toBeVisible({ timeout: 60_000 })
  const storageKey = await page.evaluate(() => {
    const key = Object.keys(localStorage).find((key) => key.startsWith('mimirq_parsed_files:'))
    if (key === undefined) throw new Error('Expected the document index to be persisted before corruption')
    localStorage.setItem(key, '{invalid document index')
    return key
  })
  await page.reload()

  const loadErrorAlert = page.getByRole('alert').filter({ hasText: '本地文档记录读取失败' })
  await expect(loadErrorAlert).toBeVisible()
  await expect(page.getByText('正在加载文档…', { exact: true })).toHaveCount(0)
  await expect(page.getByText('当前范围没有文档', { exact: true })).toHaveCount(0)
  expect(await page.evaluate((key) => localStorage.getItem(key), storageKey)).toBe('{invalid document index')

  await page.getByRole('link', { name: '文档解析', exact: true }).click()
  await page.waitForURL(/\/parsing$/)
  await expect(loadErrorAlert).toBeVisible()
  await page.evaluate(
    (key) =>
      localStorage.setItem(
        key,
        JSON.stringify({ version: 0, state: { files: [], folders: [], activeFolderId: 'root' } }),
      ),
    storageKey,
  )
  await page.getByRole('button', { name: '重试读取文档', exact: true }).click()
  await expect(loadErrorAlert).toHaveCount(0)

  await page.getByRole('link', { name: '数据治理', exact: true }).click()
  await page.waitForURL(/\/data-governance$/)
  await expect(page.getByText('当前范围没有文档', { exact: true })).toBeVisible()
})

test('governance saves edited content and keeps its original text in native IndexedDB after reload', async ({
  page,
}) => {
  const editedMarkdown = '# Saved draft\n\nThe edited body must survive a page reload.'
  await installCommonApiMocks(page, {
    uploaded: false,
    parsingDocuments: [
      {
        id: UPLOADED_DOCUMENT_ID,
        filename: UPLOADED_DOCUMENT_FILENAME,
        file_type: 'md',
        file_size: PARSED_MARKDOWN.length,
        status: 'completed',
        created_at: '2026-11-12T00:00:00Z',
        updated_at: '2026-11-12T00:00:00Z',
        error_message: null,
        markdown_content: PARSED_MARKDOWN,
        original_markdown_content: PARSED_MARKDOWN,
        parser_backend: 'text',
      },
    ],
  })
  await page.goto('/zh-CN/data-governance')
  await expect(page.locator('[data-governance-document]')).toContainText('Enterprise Telemetry Sample')
  await page.getByRole('button', { name: '编辑', exact: true }).click()
  await page.getByRole('textbox', { name: '编辑文档正文', exact: true }).fill(editedMarkdown)
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: '治理结果已保存' })).toBeVisible()

  await expect
    .poll(() =>
      page.evaluate(
        () =>
          new Promise<DocContentCacheRecord[]>((resolve, reject) => {
            const openRequest = indexedDB.open('mimirq', 2)
            openRequest.onerror = () => reject(openRequest.error)
            openRequest.onsuccess = () => {
              const database = openRequest.result
              try {
                const transaction = database.transaction('doc_contents', 'readonly')
                const recordsRequest = transaction.objectStore('doc_contents').getAll()
                recordsRequest.onsuccess = () => resolve(recordsRequest.result)
                recordsRequest.onerror = () => reject(recordsRequest.error)
                transaction.oncomplete = () => database.close()
                transaction.onabort = () => database.close()
              } catch (error) {
                database.close()
                reject(error)
              }
            }
          }),
      ),
    )
    .toContainEqual(
      expect.objectContaining({ markdownContent: editedMarkdown, originalMarkdownContent: PARSED_MARKDOWN }),
    )

  await page.reload()
  await expect(page.locator('[data-governance-document]')).toContainText('The edited body must survive a page reload.')
  await page.getByRole('button', { name: '原文', exact: true }).click()
  await expect(page.locator('[data-governance-document]')).toContainText('Enterprise Telemetry Sample')
  await expect(page.locator('[data-governance-document]')).not.toContainText(
    'The edited body must survive a page reload.',
  )
})
