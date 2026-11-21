import { expect, test, type Page } from '@playwright/test'
import { installCommonApiMocks, UPLOADED_DOCUMENT_ID } from './enterprise-quality-telemetry.helpers'

test.use({
  serviceWorkers: 'block',
  permissions: ['clipboard-read', 'clipboard-write'],
  viewport: { width: 1280, height: 720 },
})

async function openViewer(page: Page) {
  await installCommonApiMocks(page, { uploaded: true, parsingDocuments: [] })
  const chunk = {
    id: 'layout-hit',
    content: 'Exact source text',
    chunk_index: 0,
    page_number: 0,
    start_char: 0,
    end_char: 9,
    disabled_at: null,
    created_at: null,
    updated_at: null,
    metadata: {},
  }
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${UPLOADED_DOCUMENT_ID}/chunks/layout-hit`,
    (route) => route.fulfill({ json: chunk }),
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
  await page.goto(`/?doc=${UPLOADED_DOCUMENT_ID}&chunk=layout-hit`)
  await page.getByRole('tab', { name: '文本定位', exact: true }).click()
  await expect(page.getByRole('button', { name: '原始解析', exact: true })).toBeVisible()
}

test('restores expansion, text mode and keyboard width, and copies a real zero-offset link', async ({ page }) => {
  await page.setViewportSize({ width: 2560, height: 1440 })
  await openViewer(page)
  await page.getByRole('button', { name: '展开', exact: true }).click()
  await page.getByRole('button', { name: '原始解析', exact: true }).click()
  await expect(page.getByRole('button', { name: '原始解析', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.reload()
  await expect(page.getByRole('button', { name: '收起', exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '原始解析', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await page.getByRole('button', { name: '收起', exact: true }).click()
  const resize = page.getByRole('separator', { name: '拖动调整文档查看器宽度', exact: true })
  const panel = resize.locator('..')
  await panel.evaluate(async (element) => {
    await Promise.all(element.getAnimations().map((animation) => animation.finished))
  })
  const initialWidth = await panel.evaluate((element) => Math.round(element.getBoundingClientRect().width))
  await expect(resize).toHaveAttribute('aria-valuenow', String(initialWidth))
  await resize.focus()
  await page.keyboard.press('ArrowLeft')
  const savedWidth = initialWidth + 24
  await expect(resize).toHaveAttribute('aria-valuenow', String(savedWidth))
  await page.reload()
  await expect(resize).toHaveAttribute('aria-valuenow', String(savedWidth))
  await expect(page.getByRole('button', { name: '原始解析', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await resize.hover()
  await page.mouse.down()
  await page.mouse.move(64, 720)
  await page.mouse.up()
  await expect(resize).toHaveAttribute('aria-valuenow', '1800')
  await expect(resize).toHaveAttribute('aria-valuemax', '1800')
  await page.reload()
  await expect(resize).toHaveAttribute('aria-valuenow', '1800')
  await page.setViewportSize({ width: 1280, height: 720 })
  await expect(resize).toHaveAttribute('aria-valuenow', '1100')
  await expect(resize).toHaveAttribute('aria-valuemax', '1100')
  await panel.evaluate(async (element) => {
    await Promise.all(element.getAnimations().map((animation) => animation.finished))
  })
  const displayedWidth = await panel.evaluate((element) => element.getBoundingClientRect().width)
  expect(displayedWidth).toBeLessThanOrEqual(1280 * 0.86)
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/viewer-layout/saved-layout.png',
    fullPage: true,
  })
  await page.setViewportSize({ width: 2560, height: 1440 })
  await expect(resize).toHaveAttribute('aria-valuenow', '1800')
  await page.getByRole('tab', { name: '切片', exact: true }).click()
  await page.getByRole('button', { name: '复制定位链接', exact: true }).click()
  const copiedLink = new URL(await page.evaluate(() => navigator.clipboard.readText()))
  expect(Object.fromEntries(copiedLink.searchParams)).toEqual({
    doc: UPLOADED_DOCUMENT_ID,
    chunk: 'layout-hit',
    start: '0',
    end: '9',
  })
})

test('keeps the initial panel inside its real minimum at a narrow desktop width', async ({ page }) => {
  await page.setViewportSize({ width: 800, height: 800 })
  await openViewer(page)
  const resize = page.getByRole('separator', { name: '拖动调整文档查看器宽度', exact: true })
  const panel = resize.locator('..')
  const displayedWidth = await panel.evaluate((element) => element.getBoundingClientRect().width)
  expect(displayedWidth).toBe(360)
  await expect(resize).toHaveAttribute('aria-valuenow', '360')
  await resize.focus()
  await page.keyboard.press('ArrowRight')
  await expect(resize).toHaveAttribute('aria-valuenow', '360')
  expect(await panel.evaluate((element) => element.getBoundingClientRect().width)).toBe(360)
})

test('shows malformed retrieval as failure and retries from the retained question on mobile', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  await openViewer(page)
  let responseMode: 'invalid' | 'success' | 'failure' = 'invalid'
  await page.route(
    (url) => url.pathname === '/api/v1/rag/retrieve-preview',
    (route) => {
      if (responseMode === 'failure') return route.fulfill({ status: 503, json: { detail: 'Retrieval unavailable' } })
      return route.fulfill({
        json: {
          query_for_retrieval: 'Current question',
          citations: [
            {
              document_id: UPLOADED_DOCUMENT_ID,
              document_name: 'Fixture document',
              chunk_id: 'layout-hit',
              ...(responseMode === 'invalid'
                ? {}
                : { chunk_content: '  matched text\n\n', relevance_score: 0, page_number: null }),
            },
          ],
        },
      })
    },
  )
  const question = page.getByRole('textbox', { name: '检索测试问题', exact: true })
  await question.fill('Current question')
  await question.press('Enter')
  await expect(page.getByText('检索测试失败，请稍后重试', { exact: true })).toBeVisible()
  await expect(question).toHaveValue('Current question')
  await expect(page.getByText('检索结果', { exact: true })).toHaveCount(0)
  responseMode = 'success'
  await question.press('Enter')
  await expect(page.getByText('检索测试失败，请稍后重试', { exact: true })).toHaveCount(0)
  await expect(page.getByText('检索结果', { exact: true })).toBeVisible()
  await expect(page.getByText('0.0000', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: /score 0\.0000/ })).not.toContainText('P.0')
  responseMode = 'failure'
  await question.fill('Next question')
  await question.press('Enter')
  await expect(page.getByText('检索测试失败，请稍后重试', { exact: true })).toBeVisible()
  await expect(page.getByText('查询：Current question', { exact: true })).toBeVisible()
  await expect(page.getByText('失败查询：Next question', { exact: true })).toBeVisible()
  await expect(page.getByText('0.0000', { exact: true })).toBeVisible()
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/viewer-layout/retrieval-mobile.png',
    fullPage: true,
  })
})
