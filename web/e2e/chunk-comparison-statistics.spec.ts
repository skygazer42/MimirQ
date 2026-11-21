import { readFile } from 'node:fs/promises'
import { expect, test, type Page } from '@playwright/test'

import type { ChunkPreviewResponse, ChunkPreviewStats } from '@/types'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

test.use({ serviceWorkers: 'block' })

function createPreview(
  content: string,
  unit: 'chars' | 'tokens',
  stats: ChunkPreviewStats | null,
): ChunkPreviewResponse {
  return {
    filename: 'statistics.md',
    file_type: 'md',
    file_size: 12,
    total_chunks: 1,
    total_characters: 12,
    params: { chunk_size: 1000, chunk_overlap: 200, unit },
    chunks: [
      {
        index: 0,
        content,
        length: content.length,
        start_index: content === 'first' ? 0 : 6,
        end_index: content === 'first' ? 5 : 12,
      },
    ],
    original_text: 'first\nsecond',
    original_text_cleaned: 'first\nsecond',
    parser_backend: 'auto',
    chunk_strategy: unit === 'tokens' ? 'langchain_token' : 'langchain_recursive',
    stats,
  }
}

async function compareRuns(page: Page, baseline: ChunkPreviewResponse, current: ChunkPreviewResponse) {
  const server = { preview: baseline }
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [] })
  await page.route(
    (url) => url.pathname === '/api/v1/documents/chunk-preview',
    (route) => route.fulfill({ json: server.preview }),
  )
  await page.goto('/chunk-preview')
  await page.getByLabel('上传切块预览文档', { exact: true }).setInputFiles({
    name: 'statistics.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from('first\nsecond'),
  })
  await expect(page.locator('[data-chunk-card]').getByText('first', { exact: true })).toBeVisible()
  server.preview = current
  current.params.chunk_size = 900
  const size = page.getByRole('spinbutton', { name: '目标长度（字符）', exact: true })
  if (!(await size.isVisible())) await page.getByRole('button', { name: /^切块参数/ }).click()
  await size.fill('900')
  await page.keyboard.press('Control+Enter')
  await expect(page.locator('[data-chunk-card]').getByText('second', { exact: true })).toBeVisible()
  await page.getByRole('button', { name: '导出与更多操作', exact: true }).click()
  await page.getByRole('menuitem', { name: '预览对比（A/B）', exact: true }).click()
  return page.getByRole('dialog', { name: '预览对比（A/B）', exact: true })
}

test('shows actual run units and backend P95 without an incompatible length delta', async ({ page }) => {
  await page.setViewportSize({ width: 1280, height: 720 })
  const dialog = await compareRuns(
    page,
    createPreview('first', 'chars', { unit: 'chars', avg: 100, p10: 80, p95: 120, coverage_ratio: 0.5 }),
    createPreview('second', 'tokens', { unit: 'tokens', avg: 7, p10: 5, p95: 9, coverage_ratio: 0.75 }),
  )
  const lengths = dialog.getByRole('region', { name: /^长度分布/ })
  await expect(lengths).toContainText('A: 100 / B: 7')
  await expect(lengths).toContainText('A: 120 / B: 9')
  await expect(lengths).toContainText('单位不同，不计算长度差值。')
  await expect(lengths).not.toContainText('(-93)')
  const downloaded = page.waitForEvent('download')
  await dialog.getByRole('button', { name: '导出 diff.json', exact: true }).click()
  const download = await downloaded
  const path = await download.path()
  if (path === null) throw new Error('Actual diff download is unavailable')
  const exported = JSON.parse(await readFile(path, 'utf8')) as { diff: Record<string, unknown> }
  expect(exported.diff).toMatchObject({
    aUnit: 'chars',
    bUnit: 'tokens',
    aP95: 120,
    bP95: 9,
    deltaAvg: null,
    deltaP10: null,
    deltaP95: null,
    deltaCoverage: 0.25,
  })
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/comparison-statistics/mixed-units.png',
    fullPage: true,
  })
})

test('distinguishes unavailable baseline statistics from actual current zero values on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const dialog = await compareRuns(
    page,
    createPreview('first', 'chars', null),
    createPreview('second', 'chars', {
      unit: 'chars',
      avg: 0,
      p10: 0,
      p95: 0,
      coverage_ratio: 0,
      overlap_waste_ratio: 0,
      gap_count: 0,
    }),
  )
  const lengths = dialog.getByRole('region', { name: /^长度分布/ })
  await expect(lengths).toContainText('A: - / B: 0')
  await expect(lengths).not.toContainText('(0)')
  const quality = dialog.getByRole('region', { name: '覆盖/重叠/质量', exact: true })
  await expect(quality).toContainText('0%')
  await expect(quality).not.toContainText('(0%)')
  const box = await dialog.boundingBox()
  if (box === null) throw new Error('Actual comparison dialog is not rendered')
  expect(box.y).toBeGreaterThanOrEqual(0)
  expect(box.y + box.height).toBeLessThanOrEqual(page.viewportSize()!.height)
  await expect(dialog.getByRole('button', { name: 'Close', exact: true })).toBeInViewport()
  await expect(dialog.getByRole('button', { name: '导出 diff.json', exact: true })).toBeInViewport()
  await expect(dialog.getByRole('button', { name: '关闭', exact: true })).toBeInViewport()
  await quality.scrollIntoViewIfNeeded()
  await expect(dialog.getByRole('button', { name: '导出 diff.json', exact: true })).toBeInViewport()
  await expect(dialog.getByRole('button', { name: '关闭', exact: true })).toBeInViewport()
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/comparison-statistics/missing-and-zero-mobile.png',
    fullPage: true,
  })
  await dialog.getByRole('button', { name: '关闭', exact: true }).click()
  await expect(dialog).toHaveCount(0)
})
