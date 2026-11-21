import { readFile } from 'node:fs/promises'
import { expect, test, type Page } from '@playwright/test'

import type { ChunkPreviewItem, ChunkPreviewResponse } from '@/types'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

test.use({ serviceWorkers: 'block', permissions: ['clipboard-read', 'clipboard-write'] })

function createPreviewResponse(text: string, chunks: ChunkPreviewItem[]): ChunkPreviewResponse {
  return {
    filename: 'metadata.md',
    file_type: 'md',
    file_size: Buffer.byteLength(text),
    total_chunks: chunks.length,
    total_characters: Array.from(text).length,
    params: { chunk_size: 1000, chunk_overlap: 200, unit: 'chars' },
    chunks,
    original_text: text,
    original_text_cleaned: text,
    parser_backend: 'auto',
    chunk_strategy: 'langchain_recursive',
  }
}

async function openChunkPreview(page: Page, server: { preview: ChunkPreviewResponse }, text: string) {
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [] })
  await page.route(
    (url) => url.pathname === '/api/v1/documents/chunk-preview',
    (route) => route.fulfill({ json: server.preview }),
  )
  await page.goto('/chunk-preview')
  await page.getByLabel('上传切块预览文档', { exact: true }).setInputFiles({
    name: 'metadata.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from(text),
  })
  await expect(page.locator('[data-chunk-card]')).toHaveCount(server.preview.chunks.length)
}

for (const viewport of [
  { width: 1280, height: 720 },
  { width: 390, height: 844 },
]) {
  test(`keeps real metadata edits and exact citation content at width ${viewport.width}`, async ({ page }) => {
    await page.setViewportSize(viewport)
    const content = '  source\n\n'
    const metadata = {
      header_path: 'Original',
      weight: 0,
      reviewed: false,
      semantic_quality: { needs_review: true, reasons: ['toString', '  reason\n'] },
    }
    const server = {
      preview: createPreviewResponse(content, [
        { index: 0, content, length: content.length, start_index: 0, end_index: content.length, metadata },
      ]),
    }
    await openChunkPreview(page, server, content)
    const card = page.locator('[data-chunk-card][data-chunk-index="0"]')
    await expect(card.getByText('待复核', { exact: true })).toHaveAttribute('title', /toString/)
    await expect(card.getByText('待复核', { exact: true })).not.toHaveAttribute('title', /function/)
    await card.locator(':scope > button').first().click()
    await card.getByRole('button', { name: '编辑内容', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '切块编辑器', exact: true })
    const editor = dialog.getByRole('textbox', { name: '元数据（JSON 对象）', exact: true })
    await editor.fill('')
    await expect(editor).toHaveValue('')
    await expect(dialog.getByRole('button', { name: '保存', exact: true })).toBeDisabled()
    await expect(dialog.getByText('JSON 正常', { exact: true })).toHaveCount(0)
    await editor.fill(JSON.stringify({ ...metadata, header_path: '0' }))
    await dialog.getByRole('button', { name: '保存', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    await expect(card.getByRole('heading', { name: '0', exact: true })).toBeVisible()

    await card.getByRole('button', { name: '切块 1 更多操作', exact: true }).click()
    await page.getByRole('menuitem', { name: '复制引用', exact: true }).click()
    const citation = await page.evaluate(() => navigator.clipboard.readText())
    expect(citation.replace(/\r\n/g, '\n')).toContain(`\n\`\`\`\`text\n${content}\n\`\`\`\``)

    await page.getByRole('button', { name: '导出与更多操作', exact: true }).click()
    const downloaded = page.waitForEvent('download')
    await page.getByRole('menuitem', { name: '导出 JSON', exact: true }).click()
    const download = await downloaded
    const path = await download.path()
    if (path === null) throw new Error('No actual downloaded JSON file')
    const exported = JSON.parse(await readFile(path, 'utf8')) as ChunkPreviewResponse
    expect(exported.chunks[0].metadata).toEqual({ ...metadata, header_path: '0' })
    expect(exported.chunks[0].content).toBe(content)

    await card.getByRole('button', { name: '编辑内容', exact: true }).click()
    expect(JSON.parse(await editor.inputValue())).toEqual({ ...metadata, header_path: '0' })
    await editor.scrollIntoViewIfNeeded()
    await page.screenshot({
      path: `../.frontend-structure/20261112-full-frontend-guidelines/metadata-readers/metadata-edit-${viewport.width}.png`,
      fullPage: true,
    })
  })
}

test('compares different bodies even when their former hashes collide', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 })
  const text = 'costarring\nliquid'
  const server = {
    preview: createPreviewResponse(text, [
      { index: 0, content: 'costarring', length: 10, start_index: 0, end_index: 10 },
    ]),
  }
  await openChunkPreview(page, server, text)
  server.preview = createPreviewResponse(text, [
    { index: 0, content: 'liquid', length: 6, start_index: 11, end_index: 17 },
  ])
  server.preview.params.chunk_size = 900
  const size = page.getByRole('spinbutton', { name: '目标长度（字符）', exact: true })
  await size.fill('900')
  await page.keyboard.press('Control+Enter')
  await expect(page.locator('[data-chunk-card]').getByText('liquid', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '导出与更多操作', exact: true }).click()
  await page.getByRole('menuitem', { name: '预览对比（A/B）', exact: true }).click()
  const dialog = page.getByRole('dialog', { name: '预览对比（A/B）', exact: true })
  await expect(dialog.getByText('+1 / -1', { exact: true })).toBeVisible()
  await expect(dialog.getByText('0%', { exact: true })).toBeVisible()
  await expect(dialog.getByText('costarring', { exact: true })).toBeVisible()
  await expect(dialog.getByText('liquid', { exact: true })).toBeVisible()
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/metadata-readers/exact-content-comparison.png',
    fullPage: true,
  })
})
