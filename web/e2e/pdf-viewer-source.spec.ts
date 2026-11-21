import { expect, test, type Page } from '@playwright/test'

import type { ChunkPreviewResponse } from '@/types'
import type { Document } from '@/types/backend'
import { installCommonApiMocks, UPLOADED_DOCUMENT_ID } from './enterprise-quality-telemetry.helpers'

test.use({ serviceWorkers: 'block' })

function createPdf({ pages, width, height }: { pages: number; width: number; height: number }): Buffer {
  const pageReferences = Array.from({ length: pages }, (_, index) => `${4 + index * 2} 0 R`)
  const objects = [
    '<< /Type /Catalog /Pages 2 0 R >>',
    `<< /Type /Pages /Kids [${pageReferences.join(' ')}] /Count ${pages} >>`,
    '<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>',
  ]
  for (let index = 0; index < pages; index += 1) {
    const contentId = 5 + index * 2
    const content = `BT /F1 14 Tf 20 ${height - 30} Td (PDF page ${index + 1}) Tj ET\n0.2 0.3 0.5 rg 20 20 80 15 re f\n`
    objects.push(
      `<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${width} ${height}] /Resources << /Font << /F1 3 0 R >> >> /Contents ${contentId} 0 R >>`,
      `<< /Length ${Buffer.byteLength(content)} >>\nstream\n${content}endstream`,
    )
  }
  let document = '%PDF-1.4\n'
  const objectOffsets: number[] = []
  for (const [index, object] of objects.entries()) {
    objectOffsets.push(Buffer.byteLength(document))
    document += `${index + 1} 0 obj\n${object}\nendobj\n`
  }
  const xrefOffset = Buffer.byteLength(document)
  document += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`
  for (const offset of objectOffsets) document += `${String(offset).padStart(10, '0')} 00000 n \n`
  document += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF\n`
  return Buffer.from(document)
}

async function openChunkPdf(page: Page, binary: Buffer) {
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [] })
  const response: ChunkPreviewResponse = {
    filename: 'long-pages.pdf',
    file_type: 'pdf',
    file_size: binary.length,
    total_chunks: 1,
    total_characters: 5,
    params: { chunk_size: 1000, chunk_overlap: 200, unit: 'chars' },
    chunks: [{ index: 9, content: 'First', length: 5, start_index: 0, end_index: 5 }],
    original_text: 'First@@1 20 100 30 60##',
    original_text_cleaned: 'First',
    parser_backend: 'auto',
    chunk_strategy: 'langchain_recursive',
  }
  await page.route(
    (url) => url.pathname === '/api/v1/documents/chunk-preview',
    (route) => route.fulfill({ json: response }),
  )
  await page.goto('/chunk-preview')
  await page.getByLabel('上传切块预览文档', { exact: true }).setInputFiles({
    name: 'long-pages.pdf',
    mimeType: 'application/pdf',
    buffer: binary,
  })
  return page.getByRole('region', { name: 'PDF 页面', exact: true })
}

test('keeps reading deep pages after an earlier chunk was selected and new page geometry arrives', async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  const pdf = await openChunkPdf(page, createPdf({ pages: 9, width: 400, height: 600 }))
  await expect(pdf.locator('[data-page-index="0"]')).toHaveAttribute('data-page-rendered', 'true')
  await page.locator('[data-chunk-card] > button').first().click()
  await expect(pdf.locator('[data-bbox-overlay-id]')).toHaveAttribute('data-bbox-overlay-active', 'true')
  await pdf.focus()
  await pdf.press('End')
  await expect(pdf.locator('[data-page-index="8"]')).toHaveAttribute('data-page-rendered', 'true')
  await expect.poll(() => pdf.evaluate((element) => element.scrollTop)).toBeGreaterThan(1000)
  await expect.poll(() => pdf.locator('[data-page-rendered="true"]').count()).toBeLessThanOrEqual(6)
  await page.screenshot({ path: testInfo.outputPath('deep-reading.png') })
})

test('advances short PDF pages through the real parsing toolbar and applies actual page zoom', async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [] })
  await page.goto('/parsing')
  await page.getByLabel('选择待解析文件', { exact: true }).setInputFiles({
    name: 'short-pages.pdf',
    mimeType: 'application/pdf',
    buffer: createPdf({ pages: 10, width: 400, height: 150 }),
  })
  const source = page.getByRole('region', { name: '原文', exact: true })
  const pdf = source.getByRole('region', { name: 'PDF 页面', exact: true })
  await expect(pdf.locator('[data-page-index="0"]')).toHaveAttribute('data-page-rendered', 'true')
  const next = source.getByRole('button', { name: '下一页原文', exact: true })
  await next.click()
  await expect(source.getByText('2 / 10 页', { exact: true })).toBeVisible()
  await next.click()
  await expect(source.getByText('3 / 10 页', { exact: true })).toBeVisible()
  await source.getByLabel('原文缩放', { exact: true }).selectOption('100')
  await expect(pdf.locator('[data-page-index="0"]')).toHaveCSS('width', '400px')
  await source.getByLabel('原文缩放', { exact: true }).selectOption('200')
  await expect(pdf.locator('[data-page-index="0"]')).toHaveCSS('width', '800px')
  await page.screenshot({ path: testInfo.outputPath('short-page-navigation.png') })
})

test('retries an actual same-origin PDF download while preserving the application headers', async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await installCommonApiMocks(page, { uploaded: true, parsingDocuments: [] })
  const binary = createPdf({ pages: 2, width: 400, height: 600 })
  const document: Document = {
    id: UPLOADED_DOCUMENT_ID,
    dataset_id: null,
    filename: 'download-source.pdf',
    file_type: 'pdf',
    file_size: binary.length,
    status: 'completed',
    processing_progress: 100,
    processing_attempts: 1,
    chunk_count: 1,
    total_characters: 'PDF page 1PDF page 2'.length,
    publication_status: 'published',
    created_at: '2026-11-15T00:00:00Z',
    updated_at: '2026-11-15T00:00:00Z',
    metadata: {},
  }
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${UPLOADED_DOCUMENT_ID}`,
    (route) => route.fulfill({ json: document }),
  )
  const downloads: Array<{ hasAppHeader: boolean }> = []
  let downloadAvailable = false
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${UPLOADED_DOCUMENT_ID}/download`,
    (route) => {
      if (new URL(route.request().url()).searchParams.get('inline') === '0') {
        return route.fulfill({ contentType: 'application/pdf', body: binary })
      }
      const headers = route.request().headers()
      downloads.push({ hasAppHeader: ['authorization', 'x-user-id', 'x-tenant-id'].some((name) => name in headers) })
      return downloadAvailable
        ? route.fulfill({ contentType: 'application/pdf', body: binary })
        : route.fulfill({ status: 503, body: 'download unavailable' })
    },
  )
  await page.goto(`/?doc=${UPLOADED_DOCUMENT_ID}`)
  await page.getByRole('tab', { name: '原文', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: 'PDF 加载失败' })).toContainText('503')
  await page.screenshot({ path: testInfo.outputPath('download-error.png') })
  const failedDownloadCount = downloads.length
  downloadAvailable = true
  await page.getByRole('button', { name: '重试', exact: true }).click()
  const pdf = page.getByRole('region', { name: 'PDF 页面', exact: true })
  await expect(pdf.locator('[data-page-index="0"]')).toHaveAttribute('data-page-rendered', 'true')
  expect(downloads.length).toBeGreaterThan(failedDownloadCount)
  expect(downloads.every((download) => download.hasAppHeader)).toBe(true)
  await page.screenshot({ path: testInfo.outputPath('download-retry.png') })
})
