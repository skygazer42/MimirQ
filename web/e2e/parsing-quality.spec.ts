import { expect, test } from '@playwright/test'

import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

test.use({ serviceWorkers: 'block' })

for (const scenario of [
  { name: 'unknown reading order', readingOrderScore: null, enhancementFailed: true },
  { name: 'observed zero reading order', readingOrderScore: 0, enhancementFailed: true },
  { name: 'successful enhancement', readingOrderScore: 1, enhancementFailed: false },
] as const) {
  test('shows saved parsing quality: ' + scenario.name, async ({ page }) => {
    const documentId = 'quality-report'
    const filename = 'quality-report.md'
    const errors: string[] = []
    page.on('pageerror', (error) => errors.push(error.message))
    await installCommonApiMocks(page, {
      uploaded: false,
      parsingDocuments: [
        {
          id: documentId,
          filename,
          file_type: 'md',
          file_size: 24,
          status: 'completed',
          created_at: '2026-11-17T00:00:00Z',
          updated_at: '2026-11-17T00:00:00Z',
          error_message: null,
        },
      ],
    })
    await page.route('**/api/v1/parsing/documents/' + documentId + '/content', (route) =>
      route.fulfill({
        json: {
          document_id: documentId,
          parser_backend: 'text',
          markdown_content: '# Saved body',
          original_markdown_content: '# Saved body',
          edited: false,
          pdf_quality: {
            score: 0.8,
            text_quality_score: 0.8,
            format_consistency_score: 0.8,
            table_quality_score: 0.8,
            reading_order_score: scenario.readingOrderScore,
            is_scanned: false,
            page_count: 1,
          },
          quality_gate: {
            grade: 'pass',
            reasons: [],
            evidence: scenario.enhancementFailed
              ? {
                  vlm_correction: { changed: false, error: 'page_1:http_503' },
                  image_ocr: { error: 'image_unavailable' },
                }
              : {},
          },
        },
      }),
    )
    const openDocument = async () => {
      await page.goto('/parsing')
      await page.getByLabel('选择文档', { exact: true }).click()
      await page.getByRole('dialog', { name: '文件目录', exact: true }).getByText(filename, { exact: true }).click()
    }
    await openDocument()
    const result = page.getByRole('region', { name: '解析结果', exact: true })
    await expect(result.getByRole('heading', { name: 'Saved body' })).toBeVisible()
    if (scenario.enhancementFailed) {
      await result.getByText('部分解析增强未完成', { exact: true }).click()
      await expect(result.getByText('视觉校正未完成：page_1:http_503', { exact: true })).toBeVisible()
      await expect(result.getByText('图片文字识别未完成：image_unavailable', { exact: true })).toBeVisible()
      if (scenario.readingOrderScore === null) {
        await expect(result.getByText(/阅读顺序未评估/)).toBeVisible()
        await page.screenshot({ path: process.env.TEMP + '/codex-parsing-quality-warning-20261117.png' })
        await page.reload()
        await page.getByLabel('选择文档', { exact: true }).click()
        await page.getByRole('dialog', { name: '文件目录', exact: true }).getByText(filename, { exact: true }).click()
        await result.getByText('部分解析增强未完成', { exact: true }).click()
        await expect(result.getByText(/阅读顺序未评估/)).toBeVisible()
      } else {
        await expect(result.getByText(/阅读顺序评分=0.000/)).toBeVisible()
        await expect(result.getByText(/阅读顺序未评估/)).toHaveCount(0)
      }
    } else {
      await expect(result.getByText('部分解析增强未完成', { exact: true })).toHaveCount(0)
      await expect(result.getByText('阅读顺序未评估', { exact: true })).toHaveCount(0)
    }
    await expect(result.getByRole('heading', { name: '解析失败', exact: true })).toHaveCount(0)
    expect(errors).toEqual([])
  })
}

test('restores a directly imported governance body after a browser reload', async ({ page }) => {
  await installCommonApiMocks(page, { uploaded: false })
  await page.route('**/api/v1/documents/preview**', (route) =>
    route.fulfill({
      json: { parser_backend: 'text', segments: [{ content: '# Imported governance body\n\nKept after reload.' }] },
    }),
  )
  await page.goto('/data-governance')
  await page
    .locator('input[type="file"]')
    .first()
    .setInputFiles({
      name: 'imported-governance.md',
      mimeType: 'text/markdown',
      buffer: Buffer.from('Local original source'),
    })
  await expect(page.getByRole('heading', { name: /^Imported governance body/ })).toBeVisible()
  await page.reload()
  await expect(page.getByRole('heading', { name: /^Imported governance body/ })).toBeVisible()
  await expect(page.getByText('Kept after reload.', { exact: true })).toBeVisible()
  await expect(page.getByText('本地文档正文未找到，请重新导入文件', { exact: true })).toHaveCount(0)
})

test('rejects truncated knowledge content before governance can save or continue', async ({ page }) => {
  await installCommonApiMocks(page, { uploaded: false })
  await page.route('**/api/v1/documents?**', (route) =>
    route.fulfill({
      json: {
        total: 1,
        items: [
          {
            id: 'truncated-knowledge',
            filename: 'long-knowledge.md',
            file_type: 'md',
            file_size: 2_000_010,
            status: 'completed',
            created_at: '2026-11-17T00:00:00Z',
            updated_at: '2026-11-17T00:00:00Z',
            error_message: null,
            metadata: {},
            dataset_id: null,
          },
        ],
      },
    }),
  )
  await page.route('**/api/v1/documents/truncated-knowledge/parsed-content**', (route) =>
    route.fulfill({
      json: {
        document_id: 'truncated-knowledge',
        available: true,
        markdown_content: 'Incomplete prefix',
        original_markdown_content: 'Incomplete prefix',
        markdown_truncated: true,
        original_markdown_truncated: true,
        max_chars: 2_000_000,
        persisted_meta: {},
      },
    }),
  )
  await page.goto('/data-governance')
  await expect(page.getByText('解析正文超过读取范围，请在知识库详情中查看', { exact: true })).toBeVisible()
  await expect(page.getByRole('button', { name: '保存', exact: true })).toBeDisabled()
  await expect(page.getByRole('button', { name: '保存并继续切块', exact: true })).toBeDisabled()
  await expect(page.getByText('Incomplete prefix', { exact: true })).toHaveCount(0)
})
