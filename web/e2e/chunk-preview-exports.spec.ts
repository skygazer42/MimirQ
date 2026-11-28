import { readFile } from 'node:fs/promises'
import { expect, test, type Page } from '@playwright/test'

import type { ChunkPreviewResponse } from '@/types'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

test.use({ serviceWorkers: 'block', permissions: ['clipboard-read', 'clipboard-write'] })

async function downloadExport(page: Page, name: string) {
  await page.getByRole('button', { name: '导出与更多操作', exact: true }).click()
  const pending = page.waitForEvent('download')
  await page.getByRole('menuitem', { name, exact: true }).click()
  const download = await pending
  const path = await download.path()
  if (path === null) throw new Error(`Missing actual ${name} download`)
  return readFile(path, 'utf8')
}

async function copyIngestPayload(page: Page, content: string) {
  await page.getByRole('button', { name: '导出与更多操作', exact: true }).click()
  await page.getByRole('menuitem', { name: '复制手动入库 payload', exact: true }).click()
  await expect.poll(() => page.evaluate(() => navigator.clipboard.readText())).toContain(JSON.stringify(content))
  return JSON.parse(await page.evaluate(() => navigator.clipboard.readText())) as {
    chunks: Array<Record<string, unknown>>
  }
}

test('downloads the current edited selection in all formats and can explicitly include skipped chunks', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 720 })
  const preview: ChunkPreviewResponse = {
    filename: 'export.md',
    file_type: 'md',
    file_size: 12,
    total_chunks: 2,
    total_chunks_full: 2,
    total_characters: 12,
    params: { chunk_size: 1000, chunk_overlap: 200, unit: 'chars' },
    chunks: [
      { index: 0, content: 'first', length: 5, start_index: 0, end_index: 5, page_number: 0 },
      { index: 1, content: 'second', length: 6, start_index: 6, end_index: 12 },
    ],
    original_text: 'first\nsecond',
    original_text_cleaned: 'first\nsecond',
    original_text_included: true,
    stats: { count: 2, avg: 6, p95: 6 },
    chunking_stats_tokens: { count: 2, avg: 2 },
    quality_gate: { grade: 'pass' },
    parser_backend: 'auto',
    chunk_strategy: 'langchain_recursive',
  }
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [] })
  await page.route(
    (url) => url.pathname === '/api/v1/documents/chunk-preview',
    (route) => route.fulfill({ json: preview }),
  )
  await page.goto('/chunk-preview')
  await page.getByLabel('上传切块预览文档', { exact: true }).setInputFiles({
    name: 'export.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from('first\nsecond'),
  })
  const cards = page.locator('[data-chunk-card]')
  await expect(cards).toHaveCount(2)
  const originalPayload = await copyIngestPayload(page, 'first')
  expect(originalPayload.chunks).toHaveLength(2)
  expect(originalPayload.chunks[0]).not.toHaveProperty('metadata')
  const card = page.locator('[data-chunk-card][data-chunk-index="0"]')
  await card.locator(':scope > button').first().click()
  await card.getByRole('button', { name: '编辑内容', exact: true }).click()
  const editor = page.getByRole('dialog', { name: '切块编辑器', exact: true })
  const content = '  😀\n````\nbody  \n'
  await editor.getByRole('textbox', { name: '切块内容', exact: true }).fill(content)
  await editor.getByRole('button', { name: '保存', exact: true }).click()
  await expect(editor).toHaveCount(0)
  await page.getByRole('button', { name: '切块 2 更多操作', exact: true }).click()
  await page.getByRole('menuitem', { name: '跳过切块', exact: true }).click()

  const json = JSON.parse(await downloadExport(page, '导出 JSON')) as ChunkPreviewResponse
  expect(json.chunks).toHaveLength(1)
  expect(json.chunks[0]).toMatchObject({ index: 0, content, length: 16, page_number: 0, start_index: 0, end_index: 5 })
  expect(json.original_text_included).toBe(false)
  expect(json).not.toHaveProperty('original_text')
  expect(json).not.toHaveProperty('original_text_cleaned')
  expect(json.stats).toBeNull()
  expect(json).not.toHaveProperty('chunking_stats_tokens')
  expect(json).not.toHaveProperty('quality_gate')
  expect(json).not.toHaveProperty('total_chunks_full')
  expect(json.total_chunks).toBe(1)

  const markdown = await downloadExport(page, '导出 Markdown')
  expect(markdown).toContain('`````text\n' + content + '\n`````')
  expect(markdown).toContain('## Chunk 1 (P.0)')
  expect(markdown).not.toContain('second')
  const csv = await downloadExport(page, '导出 CSV')
  expect(csv).toContain(`0,0,0,5,16,"${content}"`)
  expect(csv).not.toContain('second')
  const jsonl = JSON.parse(await downloadExport(page, '导出 JSONL')) as Record<string, unknown>
  expect(jsonl).toMatchObject({ index: 0, content, length: 16, page_number: 0 })
  expect(jsonl).not.toHaveProperty('tokens_est')

  await page.getByRole('button', { name: '导出与更多操作', exact: true }).click()
  await page.getByRole('menuitemcheckbox', { name: '导出时包含 SKIP chunks (1)', exact: true }).click()
  const all = JSON.parse(await downloadExport(page, '导出 JSON')) as ChunkPreviewResponse
  expect(all.total_chunks).toBe(2)
  expect(all.chunks[1]).toMatchObject({ index: 1, content: 'second', metadata: { __mimirq_skip: true } })
  const payload = await copyIngestPayload(page, content)
  expect(payload.chunks).toHaveLength(1)
  expect(payload.chunks[0]).toMatchObject({ content, page_number: 0, start_char: 0, end_char: 5 })
  await expect(cards).toHaveCount(2)
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/preview-exports/edited-selection-1280.png',
    fullPage: true,
  })
})
