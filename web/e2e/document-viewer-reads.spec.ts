import { expect, test } from '@playwright/test'

import {
  installCommonApiMocks,
  UPLOADED_DOCUMENT_FILENAME,
  UPLOADED_DOCUMENT_ID,
} from './enterprise-quality-telemetry.helpers'

test.use({ serviceWorkers: 'block' })

test('shows a failed document request and reads it again through keyboard retry', async ({ page }) => {
  await installCommonApiMocks(page, { uploaded: true, parsingDocuments: [] })
  let reads = 0
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${UPLOADED_DOCUMENT_ID}`,
    async (route) => {
      reads += 1
      if (reads === 1) {
        await route.fulfill({ status: 503, json: { detail: 'Document read denied' } })
        return
      }
      await route.fallback()
    },
  )
  await page.goto(`/?doc=${UPLOADED_DOCUMENT_ID}`)
  const alert = page.getByRole('alert').filter({ hasText: 'Document read denied' })
  await expect(alert).toBeVisible()
  await expect(page.getByText('暂不支持内嵌预览', { exact: true })).toHaveCount(0)
  await alert.getByRole('button', { name: '重试读取文档', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: UPLOADED_DOCUMENT_FILENAME, exact: true })).toBeVisible()
  await expect(alert).toHaveCount(0)
  expect(reads).toBe(2)
})

test('retries failed text and preserves a genuinely empty available response after reload', async ({ page }) => {
  await installCommonApiMocks(page, { uploaded: true, parsingDocuments: [] })
  let reads = 0
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${UPLOADED_DOCUMENT_ID}/parsed-content`,
    async (route) => {
      reads += 1
      if (reads === 1) {
        await route.fulfill({ status: 503, json: { detail: 'Text read denied' } })
        return
      }
      await route.fulfill({
        json: {
          document_id: UPLOADED_DOCUMENT_ID,
          available: true,
          markdown_content: '',
          original_markdown_content: '',
          markdown_truncated: false,
          original_markdown_truncated: false,
          max_chars: 200_000,
          persisted_meta: {},
        },
      })
    },
  )
  await page.goto(`/?doc=${UPLOADED_DOCUMENT_ID}`)
  await page.getByRole('tab', { name: '文本定位', exact: true }).click()
  const alert = page.getByRole('alert').filter({ hasText: 'Text read denied' })
  await expect(alert).toBeVisible()
  await expect(page.getByRole('heading', { name: '暂无解析文本', exact: true })).toHaveCount(0)
  await alert.getByRole('button', { name: '重试读取文本', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByRole('heading', { name: '正文为空', exact: true })).toBeVisible()
  await expect(alert).toHaveCount(0)
  expect(reads).toBe(2)
  await page.reload()
  await expect(page.getByRole('heading', { name: '正文为空', exact: true })).toBeVisible()
  expect(reads).toBeGreaterThan(2)
})

test('reports a selected-chunk failure and retries the same resource', async ({ page }) => {
  await installCommonApiMocks(page, { uploaded: true, parsingDocuments: [] })
  let reads = 0
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${UPLOADED_DOCUMENT_ID}/chunks/viewer-hit`,
    async (route) => {
      reads += 1
      await route.fulfill(
        reads === 1
          ? { status: 503, json: { detail: 'Highlight read denied' } }
          : {
              json: {
                id: 'viewer-hit',
                content: 'Highlight recovered body',
                chunk_index: 0,
                page_number: 1,
                start_char: null,
                end_char: null,
                disabled_at: null,
                created_at: null,
                updated_at: null,
                metadata: {},
              },
            },
      )
    },
  )
  await page.goto(`/?doc=${UPLOADED_DOCUMENT_ID}&chunk=viewer-hit`)
  await page.getByRole('tab', { name: '切片', exact: true }).click()
  const alert = page.getByRole('alert').filter({ hasText: 'Highlight read denied' })
  await expect(alert).toBeVisible()
  await expect(page.getByText('未找到命中切片（可能已被删除或无权限）', { exact: true })).toHaveCount(0)
  await alert.getByRole('button', { name: '重试读取引用切片', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(page.getByText('Highlight recovered body', { exact: true })).toBeVisible()
  await expect(alert).toHaveCount(0)
  expect(reads).toBe(2)
})

test('distinguishes failed search and failed chunk loading from empty results', async ({ page }) => {
  await installCommonApiMocks(page, { uploaded: true, parsingDocuments: [] })
  const chunk = {
    id: 'viewer-hit',
    content: 'Recoverable needle chunk',
    chunk_index: 0,
    page_number: 1,
    start_char: null,
    end_char: null,
    disabled_at: null,
    created_at: null,
    updated_at: null,
    metadata: {},
  }
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${UPLOADED_DOCUMENT_ID}/chunks/${chunk.id}`,
    (route) => route.fulfill({ json: chunk }),
  )
  let searches = 0
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${UPLOADED_DOCUMENT_ID}/chunks/matches`,
    async (route) => {
      searches += 1
      await route.fulfill(
        searches === 1
          ? { status: 503, json: { detail: 'Search read denied' } }
          : { json: { total: 1, truncated: false, items: [{ id: chunk.id, chunk_index: 0, page_number: 1 }] } },
      )
    },
  )
  let reads = 0
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${UPLOADED_DOCUMENT_ID}/chunks`,
    async (route) => {
      reads += 1
      await route.fulfill(
        reads === 1 ? { status: 503, json: { detail: 'Chunk read denied' } } : { json: { total: 1, items: [chunk] } },
      )
    },
  )
  await page.goto(`/?doc=${UPLOADED_DOCUMENT_ID}&chunk=${chunk.id}`)
  await page.getByRole('tab', { name: '切片', exact: true }).click()
  await page.getByRole('textbox', { name: '搜索文档切片', exact: true }).fill('needle')
  const searchError = page.getByRole('alert').filter({ hasText: 'Search read denied' })
  await expect(searchError).toBeVisible()
  await expect(page.getByText('搜索失败', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '下一个', exact: true })).toBeDisabled()
  await searchError.getByRole('button', { name: '重试搜索', exact: true }).click()
  await expect(page.getByText('1/1', { exact: true })).toBeVisible()
  await expect(searchError).toHaveCount(0)
  await page.getByRole('button', { name: '加载全部切片', exact: true }).click()
  const readError = page.getByRole('alert').filter({ hasText: 'Chunk read denied' })
  await expect(readError).toBeVisible()
  await expect(page.getByText('暂无切片数据', { exact: true })).toHaveCount(0)
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/viewer-reads/chunk-read-error.png',
  })
  await readError.getByRole('button', { name: '重试读取切片', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(readError).toHaveCount(0)
  await expect(page.getByText(chunk.content, { exact: true })).toBeVisible()
  expect(reads).toBe(2)
  expect(searches).toBe(2)
})
