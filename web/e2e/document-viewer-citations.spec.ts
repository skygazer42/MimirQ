import { expect, test, type Page } from '@playwright/test'
import { installCommonApiMocks, UPLOADED_DOCUMENT_ID } from './enterprise-quality-telemetry.helpers'

test.use({ serviceWorkers: 'block', permissions: ['clipboard-read', 'clipboard-write'] })

async function restoreCitation(page: Page, content: string, position?: number) {
  const backend = { ready: false }
  await installCommonApiMocks(page, { uploaded: true, parsingDocuments: [] })
  const chunk = {
    id: 'source-hit',
    content: 'Current server chunk',
    chunk_index: 7,
    start_char: null,
    end_char: null,
    page_number: 1,
    disabled_at: null,
    created_at: null,
    updated_at: null,
    metadata: {},
  }
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${UPLOADED_DOCUMENT_ID}/chunks/source-hit`,
    (route) => route.fulfill(backend.ready ? { json: chunk } : { status: 403, json: { detail: 'Chunk unavailable' } }),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${UPLOADED_DOCUMENT_ID}/chunks`,
    (route) =>
      route.fulfill(
        backend.ready ? { json: { total: 1, items: [chunk] } } : { status: 503, json: { detail: 'List unavailable' } },
      ),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${UPLOADED_DOCUMENT_ID}/parsed-content`,
    (route) =>
      route.fulfill({
        json: {
          document_id: UPLOADED_DOCUMENT_ID,
          available: true,
          markdown_content: '',
          original_markdown_content: '',
          markdown_truncated: false,
          original_markdown_truncated: false,
          max_chars: 5000,
        },
      }),
  )
  await page.goto(`/?doc=${UPLOADED_DOCUMENT_ID}&chunk=source-hit&start=0&end=8`)
  await page.getByRole('tab', { name: '切片', exact: true }).click()
  await expect(page.getByRole('button', { name: '重试读取引用切片', exact: true })).toBeVisible()
  await page.evaluate(
    ({ content, position }) => {
      const key = 'mimirq_document_view_v1'
      const stored = localStorage.getItem(key)
      if (stored === null) throw new Error('The real viewer record was not persisted')
      const record: { state: Record<string, unknown> } = JSON.parse(stored)
      const sourceContext = {
        kind: 'chat-citation',
        messageId: '11111111-1111-4111-8111-111111111111',
        documentId: record.state.documentId,
        chunkId: record.state.highlightChunkId,
        chunkContent: content,
        chunkIndex: position,
        pageNumber: position,
      }
      record.state.sourceContext = sourceContext
      record.state.lastOpenedTarget = {
        documentId: record.state.documentId,
        chunkId: record.state.highlightChunkId,
        highlightRange: record.state.highlightRange,
        previewAnchor: record.state.previewAnchor,
        activeTab: record.state.activeTab,
        sourceContext,
      }
      localStorage.setItem(key, JSON.stringify(record))
    },
    { content, position },
  )
  await page.goto('/')
  await expect(page.getByRole('region', { name: '对话引用', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '重试读取引用切片', exact: true })).toBeVisible()
  return backend
}

test('keeps unknown citation metadata and exact source while reads fail, then restores real chunk actions', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 720 })
  const content = '  quoted source\n\n'
  const backend = await restoreCitation(page, content)
  const snapshot = page.getByRole('region', { name: '对话引用', exact: true })
  await expect(snapshot).toContainText('序号未知')
  await expect(snapshot).not.toContainText('#0')
  await expect(snapshot).not.toContainText('P.0')
  expect(await snapshot.locator('p').textContent()).toBe(content)
  await expect(snapshot.getByRole('button', { name: 'Edit chunk', exact: true })).toHaveCount(0)
  await expect(snapshot.getByRole('button', { name: 'Delete chunk', exact: true })).toHaveCount(0)
  await snapshot.getByRole('button', { name: '复制引用原文', exact: true }).click()
  const copiedContent = await page.evaluate(() => navigator.clipboard.readText())
  expect(copiedContent.replace(/\r\n/g, '\n')).toBe(content)
  await snapshot.getByRole('button', { name: '复制定位链接', exact: true }).click()
  const link = new URL(await page.evaluate(() => navigator.clipboard.readText()))
  expect(Object.fromEntries(link.searchParams)).toEqual({
    doc: UPLOADED_DOCUMENT_ID,
    chunk: 'source-hit',
    start: '0',
    end: '8',
  })
  await page.getByRole('button', { name: '加载全部切片', exact: true }).click()
  await expect(page.getByRole('button', { name: '重试读取切片', exact: true })).toBeVisible()
  await expect(snapshot).toBeVisible()
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/viewer-citations/readonly-citation.png',
    fullPage: true,
  })
  backend.ready = true
  await page.getByRole('button', { name: '重试读取引用切片', exact: true }).click()
  await expect(snapshot).toHaveCount(0)
  await expect(page.getByRole('button', { name: 'Edit chunk', exact: true })).toBeEnabled()
  await page.getByRole('button', { name: '重试读取切片', exact: true }).click()
  const row = page.locator('[id="chunk-source-hit"]')
  await expect(row).toBeVisible()
  await page.mouse.move(0, 0)
  const copy = row.getByRole('button', { name: '复制切片内容', exact: true })
  await copy.focus()
  await expect.poll(() => copy.evaluate((button) => getComputedStyle(button.parentElement!).opacity)).toBe('1')
  await page.getByRole('tab', { name: '文本定位', exact: true }).click()
  await expect(page.getByText('1 个切片暂不能在正文中定位。', { exact: true })).toBeVisible()
})

test('retains zero citation metadata and an actual empty source after native storage restoration', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await restoreCitation(page, '', 0)
  const snapshot = page.getByRole('region', { name: '对话引用', exact: true })
  await expect(snapshot).toContainText('#0')
  await expect(snapshot).toContainText('P.0')
  await expect(snapshot).toContainText('引用原文为空')
  await snapshot.getByRole('button', { name: '复制引用原文', exact: true }).click()
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe('')
  await page.reload()
  await expect(snapshot).toContainText('引用原文为空')
  await expect(snapshot).toContainText('#0')
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/viewer-citations/empty-citation-mobile.png',
    fullPage: true,
  })
})

test('highlights the actual Unicode text while preserving API coordinates in copied links', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 })
  await installCommonApiMocks(page, { uploaded: true, parsingDocuments: [] })
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${UPLOADED_DOCUMENT_ID}/chunks/unicode-hit`,
    (route) =>
      route.fulfill({
        json: {
          id: 'unicode-hit',
          content: 'AB',
          chunk_index: 0,
          start_char: 1,
          end_char: 3,
          page_number: 1,
          disabled_at: null,
          created_at: null,
          updated_at: null,
          metadata: { chunk_role: 'child', parent_start_char: 0, parent_end_char: 3 },
        },
      }),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${UPLOADED_DOCUMENT_ID}/parsed-content`,
    (route) =>
      route.fulfill({
        json: {
          document_id: UPLOADED_DOCUMENT_ID,
          available: true,
          markdown_content: '😀AB',
          original_markdown_content: '😀AB',
          markdown_truncated: false,
          original_markdown_truncated: false,
          max_chars: 5000,
        },
      }),
  )
  await page.goto(`/?doc=${UPLOADED_DOCUMENT_ID}&chunk=unicode-hit&start=1&end=3`)
  await page.getByRole('tab', { name: '文本定位', exact: true }).click()
  const citation = page.locator('.mimirq-monaco-citation-highlight')
  await expect.poll(async () => (await citation.allTextContents()).join('')).toBe('AB')
  await expect
    .poll(async () => (await page.locator('.mimirq-monaco-active-highlight').allTextContents()).join(''))
    .toBe('AB')
  await expect
    .poll(async () => (await page.locator('.mimirq-monaco-parent-highlight').allTextContents()).join(''))
    .toBe('😀AB')
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/monaco-contracts/unicode-viewer.png',
    fullPage: true,
  })
  await page.getByRole('tab', { name: '切片', exact: true }).click()
  await page.getByRole('button', { name: '复制定位链接', exact: true }).click()
  const link = new URL(await page.evaluate(() => navigator.clipboard.readText()))
  expect(link.searchParams.get('start')).toBe('1')
  expect(link.searchParams.get('end')).toBe('3')
})
