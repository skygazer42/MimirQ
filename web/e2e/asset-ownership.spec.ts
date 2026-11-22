import { readFile } from 'node:fs/promises'
import { expect, test, type Page } from '@playwright/test'

import type { Document, EvidenceRetrieveResponse } from '@/types/backend'
import { fulfillChatStream, installCommonApiMocks, UPLOADED_DOCUMENT_ID } from './enterprise-quality-telemetry.helpers'

test.use({ serviceWorkers: 'block' })

const imageBytes = Buffer.from(
  'iVBORw0KGgoAAAANSUhEUgAAAEAAAAAoCAIAAADBrGu+AAAAWklEQVR4nO3PUQkAIBTAwBfFEqawfx9D+HEIgwW4zdrn64YLGtCCBrSgAS1oQAsa0IIGtKABLWhACxrQgga0oAEtaEALGtCCBrSgAS1oQAsa0IIGtKABLXjsAvXoQFvl25PpAAAAAElFTkSuQmCC',
  'base64',
)
const imagePath = '/api/v1/documents/image/11111111-1111-4111-8111-111111111111'

function imageCitation() {
  return {
    document_id: UPLOADED_DOCUMENT_ID,
    document_name: '图片来源',
    chunk_id: 'image-chunk',
    chunk_content: '这是当前图片证据。',
    relevance_score: 0.95,
    has_image: true,
    img_url: imagePath,
    page_number: 1,
  }
}

async function openDocument(page: Page, content: Buffer) {
  const document: Document = {
    id: UPLOADED_DOCUMENT_ID,
    dataset_id: null,
    filename: '文档下载.txt',
    file_type: 'txt',
    file_size: content.length,
    status: 'completed',
    processing_progress: 100,
    processing_attempts: 1,
    chunk_count: 1,
    total_characters: content.toString('utf8').length,
    publication_status: 'published',
    created_at: '2026-11-15T00:00:00Z',
    updated_at: '2026-11-15T00:00:00Z',
    metadata: {},
  }
  await page.route(
    (url) => url.pathname === '/api/v1/documents/' + UPLOADED_DOCUMENT_ID,
    (route) => route.fulfill({ json: document }),
  )
  await page.goto('/?doc=' + UPLOADED_DOCUMENT_ID)
  await expect(page.getByRole('heading', { name: document.filename, exact: true })).toBeVisible()
}

for (const width of [1440, 390]) {
  test('downloads only on activation and recovers a failed download at width ' + width, async ({ page }, testInfo) => {
    await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
    await installCommonApiMocks(page, { uploaded: true, parsingDocuments: [] })
    const content = Buffer.from('Ragvia 文档下载内容\n保留实际字节。\n', 'utf8')
    let attempts = 0
    let continueDownload!: () => void
    const responseReady = new Promise<void>((resolve) => {
      continueDownload = resolve
    })
    await page.route(
      (url) => url.pathname === '/api/v1/documents/' + UPLOADED_DOCUMENT_ID + '/download',
      async (route) => {
        attempts += 1
        if (attempts === 1) return route.fulfill({ status: 503, json: { detail: 'Download unavailable (503)' } })
        await responseReady
        return route.fulfill({ contentType: 'text/plain;charset=utf-8', body: content })
      },
    )
    await openDocument(page, content)
    const action = page
      .getByRole('group', { name: '文档操作', exact: true })
      .getByRole('button', { name: '下载原文件', exact: true })
    expect(attempts).toBe(0)
    await action.click()
    const retry = page.getByRole('button', { name: '重试下载原文件', exact: true })
    await expect(retry).toBeVisible()
    await expect(page.getByRole('alert').filter({ has: retry })).toContainText('503')
    await page.screenshot({ path: testInfo.outputPath('download-error.png') })
    const downloadStarted = page.waitForEvent('download')
    try {
      await retry.focus()
      await retry.press('Enter')
      await expect(action).toBeDisabled()
      await expect(action).toHaveAttribute('aria-busy', 'true')
      await expect.poll(() => attempts).toBe(2)
    } finally {
      continueDownload()
    }
    const download = await downloadStarted
    expect(download.suggestedFilename()).toBe('文档下载.txt')
    const saved = testInfo.outputPath('downloaded-source.txt')
    await download.saveAs(saved)
    expect(await readFile(saved)).toEqual(content)
    await expect(action).toBeEnabled()
    await page.screenshot({ path: testInfo.outputPath('download-ready.png') })
  })

  test(
    'recovers HTTP and native image errors through the linked image at width ' + width,
    async ({ page }, testInfo) => {
      await page.setViewportSize({ width, height: width === 390 ? 844 : 900 })
      await installCommonApiMocks(page, { uploaded: true, parsingDocuments: [] })
      const response: EvidenceRetrieveResponse = {
        schema: 'mimirq.evidence.v1',
        query_for_retrieval: '查看图片',
        citations: [imageCitation()],
        metrics: {},
        has_evidence: true,
        abstain_triggered: false,
      }
      await page.route(
        (url) => url.pathname === '/api/v1/rag/retrieve',
        (route) => route.fulfill({ json: response }),
      )
      let attempts = 0
      await page.route(
        (url) => url.pathname === imagePath,
        (route) => {
          attempts += 1
          if (attempts === 1) return route.fulfill({ status: 503, body: 'Image temporarily unavailable' })
          return route.fulfill({
            contentType: 'image/png',
            body: attempts === 2 ? Buffer.from('invalid image bytes') : imageBytes,
          })
        },
      )
      await page.goto('/knowledge/evidence')
      await page.getByRole('textbox', { name: '检索问题', exact: true }).fill('查看图片')
      await page.getByRole('button', { name: '运行检索', exact: true }).click()
      const evidence = page.getByRole('region', { name: '引用证据列表', exact: true })
      await expect(evidence.getByRole('alert')).toContainText('503')
      await evidence.getByRole('button', { name: '重试', exact: true }).click()
      await expect(evidence.getByRole('alert')).toContainText('图片无法显示')
      await page.screenshot({ path: testInfo.outputPath('image-native-error.png') })
      const retry = evidence.getByRole('button', { name: '重试', exact: true })
      await retry.focus()
      await retry.press('Enter')
      const image = evidence.getByRole('img', { name: '引用图片', exact: true })
      await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.naturalWidth)).toBe(64)
      await expect(evidence.getByRole('link', { name: '引用图片', exact: true })).toHaveAttribute('href', /^blob:/)
      expect(attempts).toBe(3)
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth)).toBe(true)
      await page.screenshot({ path: testInfo.outputPath('image-ready.png') })
    },
  )
}

test('preserves the existing citation action while retrying a nested image and opens its actual resource', async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await installCommonApiMocks(page, { uploaded: true, parsingDocuments: [] })
  await page.route(
    (url) => url.pathname === '/api/v1/datasets' || url.pathname === '/api/v1/datasets/',
    (route) =>
      route.fulfill({
        json: {
          items: [
            {
              id: 'dataset-images',
              name: '图片知识库',
              description: '图片证据来源',
              created_at: '2026-11-15T00:00:00Z',
              updated_at: '2026-11-15T00:00:00Z',
            },
          ],
          total: 1,
        },
      }),
  )
  await page.route(
    (url) => url.pathname === '/api/v1/chat/stream',
    (route) =>
      fulfillChatStream(route, {
        contentParts: ['请查看图片证据。'],
        citations: [imageCitation()],
        requestId: 'request-asset-test',
      }),
  )
  let attempts = 0
  await page.route(
    (url) => url.pathname === imagePath,
    (route) => {
      attempts += 1
      return attempts === 1
        ? route.fulfill({ status: 503, body: 'image unavailable' })
        : route.fulfill({ contentType: 'image/png', body: imageBytes })
    },
  )
  await page.goto('/')
  await expect(page.getByRole('button', { name: '图片知识库', exact: true })).toBeVisible()
  await page.getByRole('textbox', { name: '消息输入框', exact: true }).fill('查看图片')
  await page.getByRole('button', { name: '发送', exact: true }).click()
  await page.locator('summary').filter({ hasText: '来源与证据' }).click()
  const preview = page.getByRole('button', { name: 'open-evidence-viewer', exact: true })
  await expect(preview.getByRole('alert')).toContainText('503')
  await expect(preview.locator('button, a')).toHaveCount(0)
  await preview.focus()
  await preview.press('Enter')
  const dialog = page.getByRole('dialog').filter({ hasText: 'Image Evidence' })
  await expect(dialog).toBeVisible()
  const image = dialog.getByRole('img', { name: 'evidence image', exact: true })
  await expect.poll(() => image.evaluate((node: HTMLImageElement) => node.naturalWidth)).toBe(64)
  const link = dialog.getByRole('link', { name: '新窗口打开', exact: true })
  const target = await link.getAttribute('href')
  const popupOpened = page.waitForEvent('popup')
  await link.click()
  const popup = await popupOpened
  await expect.poll(() => popup.url()).toBe(target)
  await popup.close()
  expect(attempts).toBe(2)
  await page.screenshot({ path: testInfo.outputPath('nested-evidence-ready.png') })
})
