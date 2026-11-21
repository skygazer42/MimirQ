import { readFile } from 'node:fs/promises'
import { expect, test, type Page } from '@playwright/test'

import type { ChunkPreviewResponse } from '@/types'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

test.use({ serviceWorkers: 'block', permissions: ['clipboard-read', 'clipboard-write'] })

function createPreview(): ChunkPreviewResponse {
  return {
    filename: 'positions.md',
    file_type: 'md',
    file_size: 12,
    total_chunks: 2,
    total_characters: 12,
    params: { chunk_size: 1000, chunk_overlap: 200, unit: 'chars' },
    chunks: [
      {
        index: 4,
        content: 'first',
        length: 5,
        start_index: 0,
        end_index: 5,
        metadata: { needs_review: true, weight: 0 },
      },
      { index: 9, content: 'second', length: 6, start_index: 6, end_index: 12 },
    ],
    review_signals: { short_indices: [9] },
    original_text: 'first\nsecond',
    original_text_cleaned: 'first\nsecond',
    parser_backend: 'auto',
    chunk_strategy: 'langchain_recursive',
  }
}

async function openPreview(page: Page, preview: ChunkPreviewResponse, text: string) {
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [] })
  await page.route(
    (url) => url.pathname === '/api/v1/documents/chunk-preview',
    (route) => route.fulfill({ json: preview }),
  )
  await page.goto('/chunk-preview')
  await page.getByLabel('上传切块预览文档', { exact: true }).setInputFiles({
    name: preview.filename,
    mimeType: 'text/markdown',
    buffer: Buffer.from(text),
  })
  await expect(page.locator('[data-chunk-card]')).toHaveCount(preview.chunks.length)
}

async function downloadJson(page: Page) {
  await page.getByRole('button', { name: '导出与更多操作', exact: true }).click()
  const pending = page.waitForEvent('download')
  await page.getByRole('menuitem', { name: '导出 JSON', exact: true }).click()
  const download = await pending
  const path = await download.path()
  if (path === null) throw new Error('Missing actual preview JSON download')
  return JSON.parse(await readFile(path, 'utf8')) as ChunkPreviewResponse
}

for (const viewport of [
  { width: 1280, height: 720 },
  { width: 390, height: 844 },
]) {
  test(`keeps edited display, native copying and actual chunk identities consistent at width ${viewport.width}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport)
    await openPreview(page, createPreview(), 'first\nsecond')
    const first = page.locator('[data-chunk-card][data-chunk-index="0"]')
    const second = page.locator('[data-chunk-card][data-chunk-index="1"]')
    await expect(second.getByText('内容偏短', { exact: true })).toBeVisible()
    await expect(first.getByText('内容偏短', { exact: true })).toHaveCount(0)
    await first.locator(':scope > button').first().click()
    await first.getByRole('button', { name: '编辑内容', exact: true }).click()
    const editor = page.getByRole('dialog', { name: '切块编辑器', exact: true })
    const content = viewport.width === 1280 ? '  😀\n````\nbody  \n' : ''
    const length = viewport.width === 1280 ? 16 : 0
    await editor.getByRole('textbox', { name: '切块内容', exact: true }).fill(content)
    await editor.getByRole('button', { name: '保存', exact: true }).click()
    await expect(editor).toHaveCount(0)
    await expect(first.getByText(`${length} 字`, { exact: true })).toBeVisible()
    if (viewport.width === 1280) {
      await page.getByRole('button', { name: '复制切片', exact: true }).click()
    } else {
      await page.getByRole('button', { name: '切块 1 更多操作', exact: true }).click()
      await page.getByRole('menuitem', { name: '复制切片内容', exact: true }).click()
    }
    await expect(page.getByText('已复制切片内容', { exact: true })).toBeVisible()
    // Windows clipboard storage uses CRLF; compare platform line endings without trimming the body.
    await expect
      .poll(async () => (await page.evaluate(() => navigator.clipboard.readText())).replaceAll('\r\n', '\n'))
      .toBe(content)
    await page.getByRole('button', { name: '切块 1 更多操作', exact: true }).click()
    await page.getByRole('menuitem', { name: '复制引用', exact: true }).click()
    const fence = viewport.width === 1280 ? '`````' : '````'
    await expect
      .poll(async () => (await page.evaluate(() => navigator.clipboard.readText())).replaceAll('\r\n', '\n'))
      .toContain(`${fence}text\n${content}\n${fence}`)
    await first.getByRole('button', { name: '标记已复核', exact: true }).click()
    await expect(first.getByText('已复核', { exact: true })).toBeVisible()

    await page.getByRole('button', { name: '切块 2 更多操作', exact: true }).click()
    await page.getByRole('menuitem', { name: '跳过切块', exact: true }).click()
    await expect(second).toHaveAttribute('data-disabled', 'true')
    await expect(first).toHaveAttribute('data-disabled', 'false')
    await second.locator(':scope > button').first().click()
    await second.getByRole('button', { name: '编辑内容', exact: true }).click()
    const skippedEditor = page.getByRole('dialog', { name: '切块编辑器', exact: true })
    const metadata = JSON.parse(
      await skippedEditor.getByRole('textbox', { name: '元数据（JSON 对象）', exact: true }).inputValue(),
    )
    expect(metadata).not.toHaveProperty('__mimirq_skip')
    await skippedEditor.getByRole('button', { name: 'Close', exact: true }).click()

    const exported = await downloadJson(page)
    expect(exported.chunks).toHaveLength(1)
    expect(exported.chunks[0]).toMatchObject({
      index: 4,
      content,
      length,
      start_index: 0,
      end_index: 5,
      metadata: { reviewed: true, review_status: 'approved', weight: 0 },
    })
    expect(exported.chunks[0].metadata).not.toHaveProperty('__mimirq_skip')
    await page.screenshot({
      path: `../.frontend-structure/20261112-full-frontend-guidelines/list-projections/actual-identities-${viewport.width}.png`,
      fullPage: true,
    })
  })
}

test('skips the actual filtered chunk without confusing its list position with its backend index', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 })
  await openPreview(page, createPreview(), 'first\nsecond')
  await page.getByRole('textbox', { name: '搜索切块内容', exact: true }).fill('second')
  await expect(page.locator('[data-chunk-card]')).toHaveCount(1)
  await page.getByRole('button', { name: /^筛选/ }).click()
  await page.getByRole('button', { name: 'Batch', exact: true }).click()
  await page.getByRole('menuitem', { name: '跳过筛选结果（1）', exact: true }).click()
  await page.getByRole('textbox', { name: '搜索切块内容', exact: true }).fill('')
  await expect(page.locator('[data-chunk-card]')).toHaveCount(2)
  await expect(page.locator('[data-chunk-card][data-chunk-index="0"]')).toHaveAttribute('data-disabled', 'false')
  await expect(page.locator('[data-chunk-card][data-chunk-index="1"]')).toHaveAttribute('data-disabled', 'true')
  const exported = await downloadJson(page)
  expect(exported.chunks.map((chunk) => chunk.index)).toEqual([4])
})

test('keeps whole characters at both boundaries of the actual original-text window', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 })
  const text = `${'a'.repeat(5000)}😀${'a'.repeat(1999)}X${'b'.repeat(1999)}😀${'b'.repeat(20000)}`
  const preview: ChunkPreviewResponse = {
    ...createPreview(),
    filename: 'window.md',
    file_size: Buffer.byteLength(text),
    total_chunks: 1,
    total_characters: 29001,
    review_signals: undefined,
    chunks: [
      { index: 11, content: 'X', length: 1, start_index: 7000, end_index: 7001, tokens_est: null, page_number: null },
    ],
    original_text: text,
    original_text_cleaned: text,
  }
  await openPreview(page, preview, text)
  await page.locator('[data-chunk-card]').locator(':scope > button').first().click()
  await expect(page.getByText(`😀${'a'.repeat(1999)}`, { exact: true })).toBeVisible()
  await expect(page.getByText(`${'b'.repeat(1999)}😀`, { exact: true })).toBeVisible()
  await expect(page.locator('mark')).toHaveText(['X'])
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/list-projections/whole-character-window.png',
    fullPage: true,
  })
})
