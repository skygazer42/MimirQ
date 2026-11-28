import { expect, test } from '@playwright/test'

import type { ChunkPreviewResponse } from '@/types'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

test.use({ serviceWorkers: 'block' })

function preview(content: string, chunkSize = 1000): ChunkPreviewResponse {
  const length = Array.from(content).length
  return {
    filename: 'submission.md',
    file_type: 'md',
    file_size: Buffer.byteLength('first body'),
    total_chunks: 1,
    total_characters: length,
    params: { chunk_size: chunkSize, chunk_overlap: 200, unit: 'chars' },
    chunks: [{ index: 4, content, length, start_index: 0, end_index: length }],
    original_text: content,
    original_text_cleaned: content,
    parser_backend: 'auto',
    chunk_strategy: 'langchain_recursive',
    review_signals: null,
  }
}

for (const viewport of [
  { width: 1440, height: 900 },
  { width: 390, height: 844 },
]) {
  test(`keeps editor and accepted submission results with their actual preview at width ${viewport.width}`, async ({
    page,
  }) => {
    await page.setViewportSize(viewport)
    await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [] })
    const server = { preview: preview('first body'), previewRequests: 0 }
    const submissions: Array<{ chunks: Array<{ content: string }> }> = []
    let releaseFirstSubmission!: () => void
    const pendingSubmission = new Promise<void>((resolve) => {
      releaseFirstSubmission = resolve
    })
    await page.route(
      (url) => url.pathname === '/api/v1/documents/chunk-preview',
      (route) => {
        server.previewRequests += 1
        return route.fulfill({ json: server.preview })
      },
    )
    await page.route(
      (url) => url.pathname === '/api/v1/documents/manual',
      async (route) => {
        submissions.push(route.request().postDataJSON())
        const index = submissions.length
        if (index === 1) await pendingSubmission
        await route.fulfill({
          json: {
            id: `created-submission-${index}`,
            filename: 'submission.md',
            file_type: 'md',
            file_size: 10,
            status: 'completed',
            created_at: '2026-11-15T00:00:00Z',
            updated_at: '2026-11-15T00:00:00Z',
          },
        })
      },
    )
    await page.goto('/chunk-preview')
    await page.getByLabel('上传切块预览文档', { exact: true }).setInputFiles({
      name: 'submission.md',
      mimeType: 'text/markdown',
      buffer: Buffer.from('first body'),
    })
    const card = page.locator('[data-chunk-card]')
    await expect(card).toHaveCount(1)
    await card.locator(':scope > button').first().click()
    await card.getByRole('button', { name: '编辑内容', exact: true }).click()
    const dialog = page.getByRole('dialog', { name: '切块编辑器', exact: true })
    const content = dialog.getByRole('textbox', { name: '切块内容', exact: true })
    const metadata = dialog.getByRole('textbox', { name: '元数据（JSON 对象）', exact: true })
    await content.fill('😀\n甲\n')
    await expect(dialog.getByText('4 字符 · 3 行', { exact: true })).toBeVisible()
    await metadata.fill('{')
    await expect(dialog.getByRole('button', { name: '保存', exact: true })).toBeDisabled()
    await expect(metadata).toHaveAttribute('aria-describedby', 'chunk-inspector-metadata-error')
    await expect(dialog.getByRole('alert')).toBeVisible()
    await metadata.press('Control+s')
    await metadata.press('Control+Enter')
    await expect(dialog).toBeVisible()
    await expect(content).toHaveValue('😀\n甲\n')
    await expect(metadata).toHaveValue('{')
    expect(server.previewRequests).toBe(1)
    expect(submissions).toHaveLength(0)
    await metadata.scrollIntoViewIfNeeded()
    await page.screenshot({
      path: `../.frontend-structure/20261112-full-frontend-guidelines/submission-snapshots/editor-error-${viewport.width}.png`,
    })
    await metadata.fill('{"weight":0,"reviewed":false}')
    await dialog.getByRole('button', { name: '保存', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    await page.getByRole('button', { name: '确认入库', exact: true }).click()
    try {
      await expect.poll(() => submissions.length).toBe(1)
      expect(submissions[0].chunks[0].content).toBe('😀\n甲\n')
      server.preview = preview('newer preview body')
      await page.keyboard.press('Control+Enter')
      await expect(card.getByText('newer preview body', { exact: true })).toBeVisible()
    } finally {
      releaseFirstSubmission()
    }
    await expect(page.getByRole('button', { name: '确认入库', exact: true })).toBeEnabled()
    await expect(page.getByText('已成功入库', { exact: true })).toHaveCount(0)
    await page.getByRole('button', { name: '导出与更多操作', exact: true }).click()
    await expect(page.getByRole('menuitem', { name: '复制文档 ID', exact: true })).toHaveCount(0)
    await page.keyboard.press('Escape')

    await page.getByRole('button', { name: '确认入库', exact: true }).click()
    await expect(page.getByRole('button', { name: '已完成', exact: true })).toBeVisible()
    expect(submissions).toHaveLength(2)
    expect(submissions[1].chunks[0].content).toBe('newer preview body')
    await card.getByRole('button', { name: '切块 1 更多操作', exact: true }).click()
    await page.getByRole('menuitem', { name: '编辑切块', exact: true }).click()
    await content.fill('')
    await dialog.getByRole('button', { name: '保存', exact: true }).click()
    await expect(dialog).toHaveCount(0)
    await expect(card.getByText('0 字', { exact: true })).toBeVisible()
    await expect(page.getByRole('button', { name: '确认入库', exact: true })).toBeEnabled()
    await page.screenshot({
      path: `../.frontend-structure/20261112-full-frontend-guidelines/submission-snapshots/current-preview-${viewport.width}.png`,
    })
  })
}

test('rejects an outdated selected preview in the document drawer without losing selection', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [] })
  await page.route(
    (url) => url.pathname === '/api/v1/documents/chunk-preview',
    (route) => route.fulfill({ json: preview('first body') }),
  )
  let submissions = 0
  await page.route(
    (url) => url.pathname === '/api/v1/documents/manual',
    async (route) => {
      submissions += 1
      await route.fulfill({ json: { id: 'unexpected-write', status: 'completed' } })
    },
  )
  await page.goto('/chunk-preview')
  await page.getByLabel('上传切块预览文档', { exact: true }).setInputFiles({
    name: 'submission.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from('first body'),
  })
  await expect(page.locator('[data-chunk-card]')).toHaveCount(1)
  await page.getByRole('button', { name: '管理文档', exact: true }).first().click()
  const drawer = page.getByRole('dialog', { name: '文档与数据范围', exact: true })
  const selection = drawer.getByRole('button', { name: '选择入库：submission.md', exact: true })
  await selection.click()
  await drawer.getByRole('button', { name: '返回预览', exact: true }).click()
  await page.getByRole('spinbutton', { name: '目标长度（字符）', exact: true }).fill('900')
  await page.getByRole('button', { name: '管理文档', exact: true }).first().click()
  await drawer.getByRole('button', { name: '批量入库', exact: true }).click()
  await expect(page.getByText('当前预览需要更新，请重新生成后再入库。', { exact: true })).toBeVisible()
  await expect(selection).toHaveAttribute('aria-pressed', 'true')
  expect(submissions).toBe(0)
})

test('retries a failed document read in place and preserves the uploaded preview', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [] })
  let reads = 0
  await page.route(
    (url) => url.pathname === '/api/v1/parsing/documents',
    async (route) => {
      reads += 1
      if (reads === 1) {
        await route.fulfill({ status: 503, json: { detail: 'scope offline' } })
        return
      }
      await route.fulfill({
        json: {
          total: 1,
          items: [{ id: 'remote-a', filename: 'remote.md', file_type: 'md', file_size: 11, status: 'completed' }],
        },
      })
    },
  )
  await page.route(
    (url) => url.pathname === '/api/v1/parsing/documents/remote-a/content',
    (route) =>
      route.fulfill({
        json: {
          document_id: 'remote-a',
          parser_backend: 'text',
          markdown_content: 'remote body',
          original_markdown_content: 'remote body',
          edited: false,
          pdf_quality: null,
          quality_gate: null,
        },
      }),
  )
  await page.route(
    (url) => url.pathname === '/api/v1/documents/chunk-preview',
    (route) => route.fulfill({ json: preview('first body') }),
  )
  await page.goto('/chunk-preview')
  await page.getByLabel('上传切块预览文档', { exact: true }).setInputFiles({
    name: 'submission.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from('first body'),
  })
  await expect(page.locator('[data-chunk-card]')).toHaveCount(1)
  await page.getByRole('button', { name: '管理文档', exact: true }).first().click()
  const drawer = page.getByRole('dialog', { name: '文档与数据范围', exact: true })
  await expect(drawer.getByRole('alert')).toContainText('scope offline')
  await drawer.getByRole('button', { name: '重试读取文档', exact: true }).focus()
  await page.keyboard.press('Enter')
  await expect(drawer.getByText('remote.md', { exact: true })).toBeVisible()
  await expect(drawer.getByText('scope offline', { exact: true })).toHaveCount(0)
  await drawer.getByRole('button', { name: '返回预览', exact: true }).click()
  await expect(page.locator('[data-current-file-summary]')).toContainText('submission.md')
  await expect(page.locator('[data-chunk-card]').getByText('first body', { exact: true })).toBeVisible()
  expect(reads).toBe(2)
})

test('requires a full active preview and can explicitly regenerate without a chunk limit', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 })
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [] })
  const text = 'first body\nsecond body'
  const full = preview(text)
  full.file_size = Buffer.byteLength(text)
  full.chunks = [
    { index: 4, content: 'first body', length: 10, start_index: 0, end_index: 10 },
    { index: 9, content: 'second body', length: 11, start_index: 11, end_index: 22 },
  ]
  const limits: Array<string | null> = []
  await page.route(
    (url) => url.pathname === '/api/v1/documents/chunk-preview',
    (route) => {
      const limit = new URL(route.request().url()).searchParams.get('max_chunks')
      limits.push(limit)
      const chunks = limit === '0' ? full.chunks : full.chunks.slice(0, Number(limit))
      return route.fulfill({
        json: {
          ...full,
          chunks,
          total_chunks: chunks.length,
          total_chunks_full: full.chunks.length,
          chunks_truncated: chunks.length < full.chunks.length,
          chunks_max_count: Number(limit),
        },
      })
    },
  )
  const submitted: Array<{ chunks: Array<{ content: string }> }> = []
  await page.route(
    (url) => url.pathname === '/api/v1/documents/manual',
    (route) => {
      submitted.push(route.request().postDataJSON())
      return route.fulfill({ json: { id: 'complete-preview', status: 'completed' } })
    },
  )
  await page.goto('/chunk-preview')
  await page.getByLabel('上传切块预览文档', { exact: true }).setInputFiles({
    name: 'submission.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from(text),
  })
  await expect(page.locator('[data-chunk-card]')).toHaveCount(2)
  await page.getByLabel('打开高级切块配置', { exact: true }).click()
  const settings = page.getByRole('dialog', { name: '高级切块配置', exact: true })
  await settings.getByText('预览设置', { exact: true }).click()
  const maximum = settings.getByRole('spinbutton', { name: '最多返回切块', exact: true })
  await maximum.fill('1')
  await settings.getByRole('button', { name: '生成预览', exact: true }).click()
  await expect.poll(() => limits.at(-1)).toBe('1')
  await settings.getByRole('button', { name: '返回预览', exact: true }).click()
  await expect(page.locator('[data-chunk-card]')).toHaveCount(1)
  await page.getByRole('button', { name: '确认入库', exact: true }).click()
  await expect(page.getByText(/当前预览只包含部分切块/)).toBeVisible()
  expect(submitted).toHaveLength(0)

  await page.getByLabel('打开高级切块配置', { exact: true }).click()
  await settings.getByText('预览设置', { exact: true }).click()
  await maximum.fill('0')
  await settings.getByRole('button', { name: '生成预览', exact: true }).click()
  await expect.poll(() => limits.at(-1)).toBe('0')
  await settings.getByRole('button', { name: '返回预览', exact: true }).click()
  await expect(page.locator('[data-chunk-card]')).toHaveCount(2)
  await page.getByRole('button', { name: '确认入库', exact: true }).click()
  await expect(page.getByRole('button', { name: '已完成', exact: true })).toBeVisible()
  expect(submitted).toHaveLength(1)
  expect(submitted[0].chunks.map((chunk) => chunk.content)).toEqual(['first body', 'second body'])
  expect(limits).toEqual(['2000', '1', '0'])
})
