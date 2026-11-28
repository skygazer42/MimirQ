import { expect, test, type Page } from '@playwright/test'

import type { ChunkPreviewItem, ChunkPreviewResponse } from '@/types'
import { changePreviewAppearance } from './chunk-compare.helpers'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

test.use({ serviceWorkers: 'block' })

function createPreviewResponse(
  text: string | null,
  cleaned: string | null,
  chunks: ChunkPreviewItem[] = [],
): ChunkPreviewResponse {
  return {
    filename: 'positions.md',
    file_type: 'md',
    file_size: 64,
    total_chunks: chunks.length,
    total_characters: text === null ? 0 : Array.from(text).length,
    params: { chunk_size: 500, chunk_overlap: 0, unit: 'chars' },
    chunks,
    original_text: text,
    original_text_cleaned: cleaned,
    parser_backend: 'auto',
    chunk_strategy: 'recursive',
  }
}

async function openPreview(page: Page, server: { response: ChunkPreviewResponse }, localText: string) {
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [] })
  await page.route(
    (url) => url.pathname === '/api/v1/documents/chunk-preview',
    (route) => route.fulfill({ json: server.response }),
  )
  await page.goto('/chunk-preview')
  await page.getByLabel('上传切块预览文档', { exact: true }).setInputFiles({
    name: 'positions.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from(localText),
  })
  return page.getByRole('region', { name: '文档原文', exact: true })
}

test('keeps Unicode positions and chunk identity across source, reading and actual Monaco views', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 })
  const raw = '😀one@@1 0 10 0 10##\n\n😀AB'
  const cleaned = '😀one\n\n😀AB'
  const start = Array.from(raw.slice(0, raw.indexOf('AB'))).length
  const chunk: ChunkPreviewItem = {
    index: 42,
    content: 'AB',
    length: 2,
    start_index: start,
    end_index: start + 2,
    metadata: { chunk_role: 'child', parent_start_char: 0, parent_end_char: start + 2 },
  }
  const server = {
    response: createPreviewResponse(raw, cleaned, [
      { index: 7, content: 'outside', length: 7, start_index: 1000, end_index: 1007 },
      chunk,
    ]),
  }
  const original = await openPreview(page, server, raw)
  await expect(original.getByRole('button', { name: '源码', exact: true })).toBeEnabled()
  await page.locator('[data-chunk-card][data-chunk-index="1"] > button').first().click()
  await expect(original.locator('mark mark')).toHaveText('AB')
  await expect(original).toContainText(`位置 ${start}-${start + 2}`)
  await original.getByRole('button', { name: '阅读', exact: true }).click()
  await expect(original.locator('[data-source-selected]')).toHaveText('😀AB')
  await original.getByRole('button', { name: '编辑器', exact: true }).click()
  await expect(original.locator('.monaco-editor')).toBeVisible({ timeout: 30_000 })
  await expect
    .poll(async () => (await original.locator('.mimirq-monaco-active-highlight').allTextContents()).join(''))
    .toBe('AB')
  await expect
    .poll(async () => (await original.locator('.mimirq-monaco-parent-highlight').allTextContents()).join(''))
    .toBe(cleaned.replaceAll('\n', ''))
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/monaco-contracts/unicode-workbench.png',
    fullPage: true,
  })
})

test('preserves an empty server source and distinguishes an unpositioned local source', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 })
  const localText = 'local source must stay readable'
  const server = { response: createPreviewResponse('', '') }
  const original = await openPreview(page, server, localText)
  await expect(original.getByRole('status')).toHaveText('原文为空')
  await expect(original).not.toContainText(localText)
  await expect(original.getByRole('button', { name: '编辑器', exact: true })).toBeEnabled()
  server.response = createPreviewResponse(null, null, [
    { index: 4, content: 'source', length: 6, start_index: 6, end_index: 12 },
  ])
  await page.keyboard.press('Control+Enter')
  await expect(original).toContainText(localText)
  await expect(original).toContainText('当前原文缺少可核对的解析位置')
  await expect(original.locator('mark')).toHaveCount(0)
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/monaco-contracts/local-source.png',
    fullPage: true,
  })
})

test('keeps a linked parent and theme colors across the actual source and editor views', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 })
  const text = '\uFEFF😀aa\rAB\r\ncc\nDD'
  const length = Array.from(text).length
  const start = Array.from(text.slice(0, text.indexOf('AB'))).length
  const nextStart = Array.from(text.slice(0, text.indexOf('cc'))).length
  const server = {
    response: createPreviewResponse(text, text, [
      {
        index: 10,
        content: text,
        length,
        start_index: 0,
        end_index: length,
        metadata: { chunk_role: 'parent', node_id: 'parent-node' },
      },
      {
        index: 42,
        content: 'AB',
        length: 2,
        start_index: start,
        end_index: start + 2,
        metadata: { chunk_role: 'child', parent_node_id: 'parent-node' },
      },
      {
        index: 87,
        content: 'cc',
        length: 2,
        start_index: nextStart,
        end_index: nextStart + 2,
        metadata: { chunk_role: 'child', parent_node_id: 'parent-node' },
      },
    ]),
  }
  const original = await openPreview(page, server, text)
  await expect(original.getByRole('button', { name: '源码', exact: true })).toBeEnabled()
  await page.locator('[data-chunk-card][data-chunk-index="1"] > button').first().click()
  await expect(original.locator('mark mark')).toHaveText('AB')
  await expect(original.locator('mark').first()).toHaveText(text)
  await original.getByRole('button', { name: '编辑器', exact: true }).click()
  await expect(original.locator('.monaco-editor')).toBeVisible({ timeout: 30_000 })
  const active = original.locator('.mimirq-monaco-active-highlight')
  await expect.poll(async () => (await active.allTextContents()).join('')).toBe('AB')
  await expect
    .poll(async () => (await original.locator('.mimirq-monaco-parent-highlight').allTextContents()).join(''))
    .toBe(text.replace(/^\uFEFF/, '').replace(/\r\n|\r|\n/g, ''))
  await original.locator('.view-line').getByText('cc', { exact: true }).click()
  await expect(original).toContainText(`位置 ${nextStart}-${nextStart + 2}`)
  await expect.poll(async () => (await active.allTextContents()).join('')).toBe('cc')
  await changePreviewAppearance(page, '浅色')
  await expect(page.locator('html')).toHaveClass(/light/)
  const lightColor = await active.evaluate((element) => getComputedStyle(element).backgroundColor)
  expect(lightColor).not.toBe('rgba(0, 0, 0, 0)')
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/monaco-contracts/linked-parent-light.png',
    fullPage: true,
  })
  await changePreviewAppearance(page, '深色')
  await expect(page.locator('html')).toHaveClass(/dark/)
  await expect.poll(() => active.evaluate((element) => getComputedStyle(element).backgroundColor)).not.toBe(lightColor)
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/monaco-contracts/linked-parent-dark.png',
    fullPage: true,
  })
  await original.getByRole('button', { name: '源码', exact: true }).click()
  await expect(original.locator('mark').first()).toHaveText(text)
  await expect(original.locator('mark mark')).toHaveText('cc')
})

test('opens the displayed section when a deeper heading uses the same title', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 })
  const text = [
    '##### Overview',
    'First section.',
    '## Overview',
    'Second section.',
    '## Overview 2',
    '[Malformed anchor](#%FF)',
  ].join('\n\n')
  const original = await openPreview(page, { response: createPreviewResponse(text, text) }, text)
  await original.getByRole('button', { name: '阅读', exact: true }).click()
  await expect(original.locator('h5')).toHaveAttribute('id', 'overview')
  await expect(original.locator('h2').first()).toHaveAttribute('id', 'overview-2')
  await expect(original.locator('h2').last()).toHaveAttribute('id', 'overview-2-2')
  await expect(original.getByText('Malformed anchor', { exact: true })).toBeVisible()
  await expect(original.getByRole('link', { name: 'Malformed anchor', exact: true })).toHaveCount(0)

  await original.getByText('章节目录', { exact: true }).click()
  const directory = original.getByRole('navigation', { name: 'Table of contents' })
  await directory.getByRole('button', { name: 'Overview', exact: true }).click()
  await expect(page).toHaveURL(/#overview-2$/)
  await directory.getByRole('button', { name: 'Overview 2', exact: true }).click()
  await expect(page).toHaveURL(/#overview-2-2$/)
})
