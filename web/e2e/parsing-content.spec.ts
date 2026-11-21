import { expect, test } from '@playwright/test'

import { installCommonApiMocks, UPLOADED_DOCUMENT_ID } from './enterprise-quality-telemetry.helpers'

test.use({ serviceWorkers: 'block' })

test('distinguishes loading, read failure and a saved empty parsing result', async ({ page }) => {
  const filename = 'empty-report.md'
  const documentId = 'empty-report'
  const pageErrors: string[] = []
  page.on('pageerror', (error) => pageErrors.push(error.message))
  await installCommonApiMocks(page, {
    uploaded: false,
    parsingDocuments: [
      {
        id: documentId,
        filename,
        file_type: 'md',
        file_size: 0,
        status: 'completed',
        created_at: '2026-11-13T00:00:00Z',
        updated_at: '2026-11-13T00:00:00Z',
        error_message: null,
      },
    ],
  })
  let releaseRead!: () => void
  const pendingRead = new Promise<void>((resolve) => {
    releaseRead = resolve
  })
  let contentRequests = 0
  await page.route(`**/api/v1/parsing/documents/${documentId}/content`, async (route) => {
    contentRequests += 1
    if (contentRequests === 1) {
      await pendingRead
      await route.fulfill({ status: 503, json: { detail: '读取正文服务暂不可用' } })
      return
    }
    await route.fulfill({
      json: {
        document_id: documentId,
        parser_backend: 'text',
        markdown_content: '',
        original_markdown_content: '',
        edited: false,
      },
    })
  })

  await page.goto('/parsing')
  await page.getByLabel('选择文档', { exact: true }).click()
  await page.getByRole('dialog', { name: '文件目录', exact: true }).getByText(filename, { exact: true }).click()
  const result = page.getByRole('region', { name: '解析结果', exact: true })
  try {
    await expect(result.getByRole('status')).toHaveText('正在读取解析正文')
    await expect(result.getByText('文档待解析', { exact: true })).toHaveCount(0)
  } finally {
    releaseRead()
  }
  await expect(result.getByRole('alert')).toContainText('读取正文服务暂不可用')
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/parsing-content/content-error.png',
  })
  const retry = result.getByRole('button', { name: '重试读取正文', exact: true })
  await retry.focus()
  await page.keyboard.press('Enter')
  await expect(result.getByRole('heading', { name: '正文为空', exact: true })).toBeVisible()
  await expect(result.getByRole('alert')).toHaveCount(0)
  await expect(page.getByText('0 字符', { exact: true })).toBeVisible()
  await page.reload()
  await page.getByLabel('选择文档', { exact: true }).click()
  await page.getByRole('dialog', { name: '文件目录', exact: true }).getByText(filename, { exact: true }).click()
  await expect(result.getByRole('heading', { name: '正文为空', exact: true })).toBeVisible()
  expect(contentRequests).toBe(2)
  expect(pageErrors).toEqual([])
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/parsing-content/content-empty.png',
  })
})

test('keeps an empty parsed result editable after clearing and saving its body', async ({ page }) => {
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [] })
  await page.route(
    (url) => url.pathname === `/api/v1/parsing/documents/${UPLOADED_DOCUMENT_ID}/parse`,
    (route) =>
      route.fulfill({
        json: {
          document_id: UPLOADED_DOCUMENT_ID,
          parser_backend: 'text',
          markdown_content: '',
          original_markdown_content: '',
          edited: false,
        },
      }),
  )
  await page.route(`**/api/v1/parsing/documents/${UPLOADED_DOCUMENT_ID}/content`, async (route) => {
    const submitted = route.request().postDataJSON() as { markdown_content: string }
    await route.fulfill({
      json: {
        document_id: UPLOADED_DOCUMENT_ID,
        parser_backend: 'text',
        markdown_content: submitted.markdown_content,
        original_markdown_content: submitted.markdown_content,
        edited: true,
      },
    })
  })
  await page.goto('/parsing')
  await page
    .getByLabel('选择待解析文件', { exact: true })
    .setInputFiles({ name: 'empty.md', mimeType: 'text/markdown', buffer: Buffer.from('') })
  await page.getByRole('button', { name: '开始解析', exact: true }).click()
  const result = page.getByRole('region', { name: '解析结果', exact: true })
  await expect(result.getByRole('heading', { name: '正文为空', exact: true })).toBeVisible()
  await result.getByRole('button', { name: '更多结果操作', exact: true }).click()
  await page.getByRole('menuitem', { name: '编辑 Markdown', exact: true }).click()
  const editor = page.getByLabel('编辑 Markdown', { exact: true })
  await expect(editor).toHaveValue('')
  await editor.fill('Temporary body')
  await page.getByRole('button', { name: '保存修改', exact: true }).click()
  await expect(result).toContainText('Temporary body')
  await result.getByRole('button', { name: '更多结果操作', exact: true }).click()
  await page.getByRole('menuitem', { name: '编辑 Markdown', exact: true }).click()
  await editor.fill('')
  await page.getByRole('button', { name: '保存修改', exact: true }).click()
  await expect(result.getByRole('heading', { name: '正文为空', exact: true })).toBeVisible()
  await expect(result.getByRole('button', { name: '更多结果操作', exact: true })).toBeEnabled()
})

test('shows a failed knowledge task with its saved body and a retry action', async ({ page }) => {
  await installCommonApiMocks(page, { uploaded: true, parsingDocuments: [] })
  let failed = false
  let processing = false
  let readUnavailable = false
  const document = () => ({
    id: UPLOADED_DOCUMENT_ID,
    dataset_id: null,
    filename: 'knowledge-report.md',
    file_type: 'md',
    file_size: 10,
    status: failed ? 'failed' : processing ? 'processing' : 'completed',
    processing_progress: failed ? 0 : 100,
    current_stage: failed ? 'failed' : 'indexed',
    error_message: failed ? 'Knowledge task failed' : null,
    chunk_count: 0,
    created_at: '2026-11-13T00:00:00Z',
    updated_at: '2026-11-13T00:00:00Z',
    archived_at: null,
    disabled_at: null,
    metadata: {},
  })
  await page.route(
    (url) => url.pathname === '/api/v1/documents',
    (route) => route.fulfill({ json: { total: 1, items: [document()] } }),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${UPLOADED_DOCUMENT_ID}`,
    (route) =>
      readUnavailable
        ? route.fulfill({ status: 503, json: { detail: 'Knowledge state unavailable' } })
        : route.fulfill({ json: document() }),
  )
  await page.route(`**/api/v1/documents/${UPLOADED_DOCUMENT_ID}/download**`, (route) =>
    route.fulfill({ contentType: 'text/markdown', body: 'Original source text' }),
  )
  await page.route(`**/api/v1/documents/${UPLOADED_DOCUMENT_ID}/pipeline`, (route) =>
    route.fulfill({ json: document() }),
  )
  await page.route(
    (url) => url.pathname === `/api/v1/documents/${UPLOADED_DOCUMENT_ID}/retry`,
    (route) => {
      processing = true
      readUnavailable = true
      return route.fulfill({ json: document() })
    },
  )
  await page.route(`**/api/v1/documents/${UPLOADED_DOCUMENT_ID}/parsed-content**`, (route) =>
    route.fulfill({
      json: {
        document_id: UPLOADED_DOCUMENT_ID,
        available: true,
        markdown_content: 'Previously saved text',
        original_markdown_content: 'Previously saved text',
        persisted_meta: {},
        markdown_truncated: false,
        original_markdown_truncated: false,
        max_chars: 2_000_000,
      },
    }),
  )
  await page.goto('/parsing')
  await page.getByLabel('选择文档', { exact: true }).click()
  await page
    .getByRole('dialog', { name: '文件目录', exact: true })
    .getByText('knowledge-report.md', { exact: true })
    .click()
  const result = page.getByRole('region', { name: '解析结果', exact: true })
  await expect(result.getByText('Previously saved text', { exact: true })).toBeVisible()
  await page
    .getByRole('region', { name: '原文', exact: true })
    .getByRole('button', { name: '恢复源文件', exact: true })
    .click()
  await result.getByRole('button', { name: '更多结果操作', exact: true }).click()
  await expect(page.getByRole('menuitem', { name: '编辑 Markdown', exact: true })).toBeDisabled()
  await page.keyboard.press('Escape')
  await page.getByRole('button', { name: '重新解析', exact: true }).click()
  await expect(result.getByRole('alert')).toContainText('Knowledge state unavailable')
  processing = false
  readUnavailable = false
  await result.getByRole('button', { name: '重试读取正文', exact: true }).click()
  await expect(result.getByRole('button', { name: '更多结果操作', exact: true })).toBeVisible()
  await expect(result.getByRole('alert')).toHaveCount(0)
  failed = true
  await page.reload()
  await page.getByLabel('选择文档', { exact: true }).click()
  await page
    .getByRole('dialog', { name: '文件目录', exact: true })
    .getByText('knowledge-report.md', { exact: true })
    .click()
  await expect(result.getByText('Previously saved text', { exact: true })).toBeVisible()
  await expect(result.getByRole('alert')).toContainText('Knowledge task failed')
  await expect(result.getByRole('alert').getByRole('button')).toBeEnabled()
  await page.screenshot({
    path: '../.frontend-structure/20261112-full-frontend-guidelines/parsing-content/knowledge-failure.png',
  })
})
