import { expect, test, type Page } from '@playwright/test'

import type { ChunkPreviewItem, ChunkPreviewResponse } from '@/types'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

test.use({ serviceWorkers: 'block' })

function preview(text: string, chunks: ChunkPreviewItem[]): ChunkPreviewResponse {
  return {
    filename: 'structure.md',
    file_type: 'md',
    file_size: Buffer.byteLength(text),
    total_chunks: chunks.length,
    total_characters: Array.from(text).length,
    params: { chunk_size: 1000, chunk_overlap: 200, unit: 'chars' },
    chunks,
    parser_backend: 'auto',
    chunk_strategy: 'langchain_recursive',
    original_text: text,
    original_text_cleaned: text,
    review_signals: null,
  }
}

async function openPreview(page: Page, server: { preview: ChunkPreviewResponse; requests: number }, text: string) {
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [] })
  await page.route(
    (url) => url.pathname === '/api/v1/documents/chunk-preview',
    (route) => {
      server.requests += 1
      return route.fulfill({ json: server.preview })
    },
  )
  await page.goto('/chunk-preview')
  await page.getByLabel('上传切块预览文档', { exact: true }).setInputFiles({
    name: 'structure.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from(text),
  })
  await expect(page.locator('[data-chunk-card]')).toHaveCount(server.preview.chunks.length)
}

async function choose(page: Page, label: string, option: string) {
  await page.getByRole('combobox', { name: label, exact: true }).click()
  await page.getByRole('option', { name: option, exact: true }).click()
}

test('groups actual parent identities once and restores collapse preference after page-zero filtering', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 720 })
  const text = 'first child\nsecond child\nend'
  const data = preview(text, [
    {
      index: 4,
      content: text,
      length: 28,
      start_index: 0,
      end_index: 28,
      page_number: null,
      metadata: { chunk_role: 'parent', node_id: 0 },
    },
    {
      index: 9,
      content: 'first child',
      length: 11,
      start_index: 0,
      end_index: 11,
      page_number: 0,
      metadata: { chunk_role: 'child', parent_node_id: 0 },
    },
    {
      index: 12,
      content: 'second child',
      length: 12,
      start_index: 12,
      end_index: 24,
      page_number: 1,
      metadata: { chunk_role: 'child', parent_node_id: 0 },
    },
  ])
  data.chunk_strategy = 'parent_child'
  data.review_signals = {
    basis: 'child',
    short_indices: [4, 9, 12],
    duplicate_indices: [],
    gap_indices: [12],
    gap_before_by_index: { 12: 1 },
    overlap_indices: [],
  }
  await openPreview(page, { preview: data, requests: 0 }, text)
  await page.getByRole('button', { name: '筛选', exact: true }).click()
  await choose(page, 'View', 'Hierarchy')
  const collapse = page.getByRole('button', { name: 'Collapse group', exact: true })
  await expect(collapse).toBeVisible()
  await expect(page.locator('[data-chunk-card]')).toHaveCount(3)
  await collapse.click()
  await expect(page.locator('[data-chunk-card]')).toHaveCount(1)
  await page.getByRole('button', { name: '检索', exact: true }).click()
  await page.getByRole('textbox', { name: '输入检索词', exact: true }).fill('first child')
  await page
    .getByRole('button')
    .filter({ has: page.getByText('#2', { exact: true }) })
    .click()
  await expect(page.locator('[data-chunk-card][data-chunk-index="1"][data-selected="true"]')).toBeVisible()
  await expect(page.locator('[data-chunk-card]')).toHaveCount(3)
  await page.getByRole('button', { name: /^检索/ }).click()
  await collapse.click()
  await expect(page.locator('[data-chunk-card]')).toHaveCount(1)
  await choose(page, '页面', 'P.0')
  await expect(page.locator('[data-chunk-card]')).toHaveCount(2)
  await expect(page.getByRole('button', { name: 'Collapse group', exact: true })).toBeDisabled()
  await expect(page.locator('[data-chunk-card][data-chunk-index="1"]')).toBeVisible()
  await choose(page, '页面', '全部页面')
  await expect(page.locator('[data-chunk-card]')).toHaveCount(1)
  await page.getByRole('button', { name: 'Expand', exact: true }).click()
  await expect(page.locator('[data-chunk-card]')).toHaveCount(3)
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/list-structure/hierarchy-1280.png',
    fullPage: true,
  })
})

test('keeps actual section labels, unknown measurements and zero/invalid length drafts on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const text = 'first\nsecond'
  const data = preview(text, [
    {
      index: 4,
      content: 'first',
      length: 5,
      start_index: 0,
      end_index: 5,
      metadata: { header_path: '__mimirq_section_none__' },
    },
    { index: 9, content: 'second', length: 6, start_index: 6, end_index: 12 },
  ])
  await openPreview(page, { preview: data, requests: 0 }, text)
  const first = page.locator('[data-chunk-card][data-chunk-index="0"]')
  await first.locator(':scope > button').first().click()
  await first.getByRole('button', { name: '编辑内容', exact: true }).click()
  const editor = page.getByRole('dialog', { name: '切块编辑器', exact: true })
  await editor.getByRole('textbox', { name: '切块内容', exact: true }).fill('')
  await editor.getByRole('button', { name: '保存', exact: true }).click()
  await expect(editor).toHaveCount(0)
  await page.getByRole('button', { name: '筛选', exact: true }).click()
  await expect(page.getByText('当前没有可用的统计标记', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '短块 —', exact: true })).toBeDisabled()
  await choose(page, 'Section', '__mimirq_section_none__')
  await expect(page.locator('[data-chunk-card]')).toHaveCount(1)
  await expect(first).toBeVisible()
  await choose(page, 'Section', 'All sections')
  await choose(page, 'Group', 'Section')
  await expect(page.getByRole('button', { name: 'Collapse section', exact: true })).toHaveCount(2)
  const maximum = page.getByRole('textbox', { name: '最大长度过滤', exact: true })
  await maximum.fill('0')
  await expect(maximum).toHaveValue('0')
  await expect(first.getByText('0 字', { exact: true })).toBeVisible()
  await expect(page.locator('[data-chunk-card]')).toHaveCount(1)
  await maximum.fill('1.5')
  await expect(maximum).toHaveValue('1.5')
  await expect(page.getByRole('alert').filter({ hasText: '请输入有效的非负整数' })).toBeVisible()
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/list-structure/filters-390.png',
    fullPage: true,
  })
})

test('keeps original Unicode highlights and real ranked results while the panel is collapsed', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 })
  const text = 'İ😀 hit\nanother target'
  const data = preview(text, [
    { index: 4, content: 'İ😀 hit', length: 6, start_index: 0, end_index: 6 },
    { index: 9, content: 'another target', length: 14, start_index: 7, end_index: 21 },
  ])
  await openPreview(page, { preview: data, requests: 0 }, text)
  await page.getByRole('textbox', { name: '搜索切块内容', exact: true }).fill('hit')
  await expect(page.locator('[data-chunk-card] mark')).toHaveText(['hit'])
  await page.getByRole('button', { name: '检索', exact: true }).click()
  const rankedQuery = page.getByRole('textbox', { name: '输入检索词', exact: true })
  await rankedQuery.fill('another')
  await page
    .getByRole('button')
    .filter({ has: page.getByText('#2', { exact: true }) })
    .click()
  await expect(page.getByRole('textbox', { name: '搜索切块内容', exact: true })).toHaveValue('')
  await expect(page.locator('[data-chunk-card][data-chunk-index="1"][data-selected="true"]')).toBeVisible()
  await rankedQuery.fill('hit')
  await expect(page.getByRole('button', { name: /^检索\s*1$/ })).toBeVisible()
  await page.getByRole('button', { name: /^检索\s*1$/ }).click()
  await expect(page.getByRole('button', { name: /^检索\s*1$/ })).toBeVisible()
  await page.getByRole('button', { name: /^检索\s*1$/ }).click()
  await page.getByRole('button', { name: '词语匹配排序', exact: true }).click()
  const weight = page.getByRole('slider', { name: '检索得分权重', exact: true })
  await weight.focus()
  await weight.press('Home')
  await expect(weight).toHaveValue('0')
  await expect(page.getByText('综合 1.00', { exact: true })).toBeVisible()
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/list-structure/search-1280.png',
    fullPage: true,
  })
})

test('resets list scope for a new preview of the same filename and reports unavailable active markers', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1280, height: 720 })
  const text = 'first version\nsecond version'
  const first = preview(text, [{ index: 4, content: 'first version', length: 13, start_index: 0, end_index: 13 }])
  first.review_signals = { short_indices: [4] }
  const second = preview(text, [{ index: 9, content: 'second version', length: 14, start_index: 14, end_index: 28 }])
  second.params.chunk_size = 900
  const server = { preview: first, requests: 0 }
  await openPreview(page, server, text)
  server.preview = second
  const size = page.getByRole('spinbutton', { name: '目标长度（字符）', exact: true })
  await size.fill('900')
  await page.getByRole('button', { name: '生成预览', exact: true }).click()
  await expect(page.locator('[data-chunk-card]').getByText('second version', { exact: true })).toBeVisible()
  const search = page.getByRole('textbox', { name: '搜索切块内容', exact: true })
  await search.fill('second')
  await size.fill('1000')
  server.preview = first
  await page.getByRole('button', { name: '生成预览', exact: true }).click()
  await expect(search).toHaveValue('')
  await expect(page.locator('[data-chunk-card]').getByText('first version', { exact: true })).toBeVisible()
  expect(server.requests).toBe(3)
  await page.getByRole('button', { name: '筛选', exact: true }).click()
  await page.getByRole('button', { name: '短块 1', exact: true }).click()
  const card = page.locator('[data-chunk-card]')
  await card.locator(':scope > button').first().click()
  await card.getByRole('button', { name: '编辑内容', exact: true }).click()
  const editor = page.getByRole('dialog', { name: '切块编辑器', exact: true })
  await editor.getByRole('textbox', { name: '切块内容', exact: true }).fill('long text '.repeat(100))
  await editor.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByText('当前筛选缺少可用统计标记，请清除统计筛选。', { exact: true })).toBeVisible()
  await expect(page.getByText('未找到匹配切片', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '清除统计筛选', exact: true }).click()
  await expect(page.locator('[data-chunk-card]')).toHaveCount(1)
})
