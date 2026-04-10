import path from 'node:path'
import { expect, test } from '@playwright/test'

import {
  EnterpriseTelemetryMockState,
  installCommonApiMocks,
  PARSED_MARKDOWN,
  UPLOADED_DOCUMENT_FILENAME,
} from './enterprise-quality-telemetry.helpers'

function escapeRegExp(value: string) {
  return value.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')
}

test('document upload flows into intelligent chat smoke path', async ({ page }) => {
  const state: EnterpriseTelemetryMockState = { uploaded: false, parsingDocuments: [] }
  await installCommonApiMocks(page, state)
  await page.route('**/api/v1/datasets**', async (route) => {
    await route.fulfill({
      status: 200,
      contentType: 'application/json',
      body: JSON.stringify({
        items: [
          {
            id: 'dataset-e2e',
            name: 'E2E Dataset',
            description: 'Smoke dataset for document chat',
          },
        ],
        total: 1,
      }),
    })
  })
  const filenamePattern = escapeRegExp(UPLOADED_DOCUMENT_FILENAME)
  const queueFileRow = page.getByRole('button', { name: new RegExp(filenamePattern) })

  await page.goto('/parsing')
  await expect(page.getByRole('heading', { name: '文档解析' })).toBeVisible({ timeout: 60_000 })

  await page
    .locator('input[type="file"][multiple]:not([webkitdirectory])')
    .setInputFiles(path.resolve(__dirname, 'fixtures/enterprise-telemetry-sample.md'))

  await expect(page.getByText('已加入队列：1 个文件')).toBeVisible()
  await expect(queueFileRow).toBeVisible()
  await expect(page.getByText('1 等待')).toBeVisible()
  await expect(page.getByText('准备就绪')).toBeVisible()

  await page.getByRole('button', { name: '开始解析' }).click()

  await expect(page.getByText('1 完成')).toBeVisible({ timeout: 60_000 })
  await expect(queueFileRow).toBeVisible()
  await expect(page.getByText(PARSED_MARKDOWN.split('\n')[2])).toBeVisible()

  await page.goto('/')

  const input = page.getByPlaceholder('问点什么... (Shift + Enter 换行)')
  await expect(input).toBeVisible({ timeout: 60_000 })
  await input.fill('请总结刚上传文档的重点。')
  await page.getByRole('button', { name: '发送' }).click()

  await expect(page.getByText('已完成智能对话验证。')).toBeVisible()
})
