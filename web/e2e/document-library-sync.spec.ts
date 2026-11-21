import { expect, test } from '@playwright/test'

import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

test.use({ serviceWorkers: 'block' })

test('keeps an uploaded local preview through library refresh and source failure recovery', async ({ page }) => {
  let parsingUnavailable = false
  await installCommonApiMocks(page, { uploaded: false, parsingDocuments: [] })
  await page.route('**/api/v1/documents/preview**', (route) =>
    route.fulfill({
      json: { parser_backend: 'text', segments: [{ content: '# Local preview retained across workspaces' }] },
    }),
  )
  await page.route('**/api/v1/parsing/documents**', async (route) => {
    if (parsingUnavailable) await route.fulfill({ status: 503, json: { detail: 'Parsing directory unavailable' } })
    else await route.fallback()
  })
  await page.goto('/data-governance')
  await expect(page.getByRole('heading', { name: '数据治理', exact: true })).toBeVisible({ timeout: 60_000 })
  await page.getByLabel('上传治理文档', { exact: true }).setInputFiles({
    name: 'local-preview.md',
    mimeType: 'text/markdown',
    buffer: Buffer.from('# Local preview retained across workspaces'),
  })
  await expect(page.locator('[data-governance-document]')).toContainText('Local preview retained across workspaces')
  await page.getByRole('button', { name: '保存', exact: true }).click()
  await expect(page.getByRole('status').filter({ hasText: '治理结果已保存' })).toBeVisible()

  await page.getByRole('link', { name: '文档解析', exact: true }).click()
  await page.waitForURL(/\/parsing$/)
  await page.getByLabel('选择文档', { exact: true }).click()
  const directory = page.getByRole('dialog', { name: '文件目录', exact: true })
  await expect(directory.getByText('local-preview.md', { exact: true })).toBeVisible()

  parsingUnavailable = true
  await page.reload()
  const syncError = page.getByRole('alert').filter({ hasText: '文档目录同步失败' })
  await expect(syncError).toBeVisible()
  await page.getByLabel('选择文档', { exact: true }).click()
  await expect(directory.getByText('local-preview.md', { exact: true })).toBeVisible()
  await expect(directory.getByRole('alert')).toContainText('文档目录同步失败')

  parsingUnavailable = false
  await directory.getByRole('button', { name: '重试同步目录', exact: true }).click()
  await expect(syncError).toHaveCount(0)
  await expect(directory.getByText('local-preview.md', { exact: true })).toBeVisible()
})
