import path from 'node:path'
import { expect, test } from '@playwright/test'

import {
  type EnterpriseTelemetryMockState,
  installCommonApiMocks,
  PARSED_MARKDOWN,
  UPLOADED_DOCUMENT_FILENAME,
} from './enterprise-quality-telemetry.helpers'

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
  await page.goto('/parsing')
  await expect(page.getByRole('heading', { name: '文档解析' })).toBeVisible({ timeout: 60_000 })

  await page
    .getByLabel('选择待解析文件', { exact: true })
    .setInputFiles(path.resolve(__dirname, 'fixtures/enterprise-telemetry-sample.md'))

  await expect(page.getByLabel('选择文档', { exact: true })).toContainText(UPLOADED_DOCUMENT_FILENAME)

  await page.getByRole('button', { name: '开始解析', exact: true }).click()

  await expect(page.getByRole('region', { name: '解析结果', exact: true })).toContainText(
    PARSED_MARKDOWN.split('\n')[2],
  )

  await page.goto('/')

  const input = page.getByRole('textbox', { name: '消息输入框', exact: true })
  await expect(input).toBeVisible({ timeout: 60_000 })
  await input.fill('请总结刚上传文档的重点。')
  await page.getByRole('button', { name: '发送' }).click()

  await expect(page.getByText('已完成智能对话验证。')).toBeVisible()
  await expect.poll(() => state.chatRequests?.at(-1)?.message).toBe('请总结刚上传文档的重点。')
  await expect
    .poll(() => new URL(page.url()).searchParams.get('conversation'))
    .toBe(state.chatRequests?.at(-1)?.conversationId)
})
