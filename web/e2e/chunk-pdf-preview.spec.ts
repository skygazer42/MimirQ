import { readFile } from 'node:fs/promises'
import { resolve } from 'node:path'
import { expect, test, type Page } from '@playwright/test'

import type { ChunkPreviewResponse } from '@/types'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

test.use({ serviceWorkers: 'block' })

const pdfPath = resolve(process.cwd(), '../tests/fixtures/parsing_golden_broader/two_column_pdf/input/sample.pdf')

async function openPdf(page: Page, response: ChunkPreviewResponse) {
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [] })
  await page.route(
    (url) => url.pathname === '/api/v1/documents/chunk-preview',
    (route) => route.fulfill({ json: response }),
  )
  await page.goto('/chunk-preview')
  await page.getByLabel('上传切块预览文档', { exact: true }).setInputFiles(pdfPath)
  return page.getByRole('region', { name: '文档原文', exact: true })
}

async function pdfResponse(rawOriginal: string | null): Promise<ChunkPreviewResponse> {
  return {
    filename: 'sample.pdf',
    file_type: 'pdf',
    file_size: (await readFile(pdfPath)).length,
    total_chunks: 1,
    total_characters: 2,
    params: { chunk_size: 1000, chunk_overlap: 200, unit: 'chars' },
    chunks: [{ index: 9, content: 'AB', length: 2, start_index: 0, end_index: 2 }],
    original_text: rawOriginal,
    original_text_cleaned: rawOriginal === null ? null : rawOriginal.replace(/@@[^#]+##/g, ''),
    parser_backend: 'auto',
    chunk_strategy: 'langchain_recursive',
  }
}

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
]) {
  test(`renders the real PDF without a returned text source at width ${viewport.width}`, async ({ page }) => {
    await page.setViewportSize(viewport)
    const original = await openPdf(page, await pdfResponse(null))
    if (viewport.width === 390) await page.getByRole('button', { name: '文档原文', exact: true }).click()

    const firstPage = original.locator('[data-page-index="0"]')
    await expect(firstPage).toHaveAttribute('data-page-rendered', 'true')
    const hasInk = await firstPage.locator('canvas').evaluate((canvas: HTMLCanvasElement) => {
      const context = canvas.getContext('2d')
      if (context === null) throw new Error('Missing real PDF render context')
      const pixels = context.getImageData(0, 0, canvas.width, canvas.height).data
      for (let index = 0; index < pixels.length; index += 4) {
        if (pixels[index + 3] > 0 && pixels[index] < 240 && pixels[index + 1] < 240 && pixels[index + 2] < 240) {
          return true
        }
      }
      return false
    })
    expect(hasInk).toBe(true)
    await expect(original.getByRole('status')).toContainText('PDF 原页仍可查看')
    await expect(original.locator('[data-bbox-overlay-id]')).toHaveCount(0)
    await page.screenshot({
      path: `../.frontend-structure/20261112-full-frontend-guidelines/pdf-preview/no-text-${viewport.width}.png`,
    })
  })
}

test('keeps Unicode source positions and actual chunk selection aligned through the PDF worker and native overlay', async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.addInitScript(() => {
    const NativeWorker = globalThis.Worker
    globalThis.Worker = class extends NativeWorker {
      constructor(url: string | URL, options?: WorkerOptions) {
        super(url, options)
        if (options?.name !== 'pdf-preview') return
        this.addEventListener(
          'message',
          () => {
            document.documentElement.dataset.pdfPreviewWorkerResponded = 'true'
          },
          { once: true },
        )
      }
    }
  })
  const workerUrls: string[] = []
  const workerWarnings: string[] = []
  page.on('worker', (worker) => workerUrls.push(worker.url()))
  page.on('console', (message) => {
    if (message.text().includes('PDF preview worker failed')) workerWarnings.push(message.text())
  })
  const raw = '😀A@@1 20 220 40 80##B@@1 20 220 140 180##'
  const response = await pdfResponse(raw)
  const start = Array.from(raw.slice(0, raw.indexOf('B'))).length
  response.total_chunks = 2
  response.total_characters = Array.from(raw).length
  response.chunks = [
    { index: 9, content: '😀A', length: 2, start_index: 0, end_index: 2 },
    { index: 15, content: 'B', length: 1, start_index: start, end_index: start + 1 },
  ]
  const original = await openPdf(page, response)
  await expect(original.locator('[data-page-index="0"]')).toHaveAttribute('data-page-rendered', 'true')
  await page.locator('[data-chunk-card][data-chunk-index="1"] > button').first().click()
  await expect(original.locator('[data-bbox-overlay-id="block-1"]')).toHaveAttribute('data-bbox-overlay-active', 'true')
  await original.getByRole('button', { name: '显示全部框', exact: true }).click()
  const firstBox = original.locator('[data-bbox-overlay-id="block-0"]')
  await firstBox.focus()
  await firstBox.press('Enter')
  await expect.poll(() => new URL(page.url()).searchParams.get('chunk')).toBe('1')
  await expect(firstBox).toHaveAttribute('data-bbox-overlay-active', 'true')
  await expect(page.locator('html')).toHaveAttribute('data-pdf-preview-worker-responded', 'true')
  expect(workerWarnings).toEqual([])
  await testInfo.attach('actual-worker-observations', {
    body: JSON.stringify({ workerUrls, workerWarnings }),
    contentType: 'application/json',
  })
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/pdf-preview/unicode-overlay.png',
  })
})

test('keeps real PDF pages and chunk overlays after a native worker module fails asynchronously', async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.addInitScript(() => {
    const NativeWorker = globalThis.Worker
    globalThis.Worker = class extends NativeWorker {
      private failureUrl: string | null

      constructor(url: string | URL, options?: WorkerOptions) {
        const failureUrl =
          options?.name === 'pdf-preview'
            ? URL.createObjectURL(
                new Blob(['throw new Error("forced PDF worker module failure")'], { type: 'text/javascript' }),
              )
            : null
        super(failureUrl === null ? url : failureUrl, options)
        this.failureUrl = failureUrl
        if (failureUrl !== null) {
          this.addEventListener(
            'error',
            () => {
              document.documentElement.dataset.pdfPreviewWorkerError = 'true'
              URL.revokeObjectURL(failureUrl)
            },
            { once: true },
          )
        }
      }

      terminate() {
        if (this.failureUrl !== null) URL.revokeObjectURL(this.failureUrl)
        super.terminate()
      }
    }
  })
  const original = await openPdf(page, await pdfResponse('AB@@1 20 220 40 80##'))
  await expect(original.locator('[data-page-index="0"]')).toHaveAttribute('data-page-rendered', 'true')
  await page.locator('[data-chunk-card] > button').first().click()
  await expect(original.locator('[data-bbox-overlay-id="block-0"]')).toHaveAttribute('data-bbox-overlay-active', 'true')
  await expect(page.locator('html')).toHaveAttribute('data-pdf-preview-worker-error', 'true')
  await testInfo.attach('actual-worker-failure', {
    body: JSON.stringify({ nativeWorkerErrorObserved: true, originalPageRendered: true, chunkOverlayPreserved: true }),
    contentType: 'application/json',
  })
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/pdf-preview/worker-failure.png',
  })
})
