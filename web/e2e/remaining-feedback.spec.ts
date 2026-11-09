import { test, expect } from '@playwright/test'
import { batchTwoFixture } from './remaining-batch-two.helpers'
import { openRemaining } from './remaining-pages.helpers'
test('transient feedback permits underlying actions, expires and can still be closed', async ({ page }) => {
  await batchTwoFixture(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await openRemaining(page, '/data-governance/common-lines', '重复内容规则')
  await expect(page.getByRole('button', { name: '导入脚本草案', exact: true })).toBeEnabled()
  const upload = () => page.locator('input[type=file]').first().setInputFiles({ name: 'ui-feedback-draft.py', mimeType: 'text/x-python', buffer: Buffer.from('# isolated feedback verification\n') })
  await upload()
  const toast = page.locator('[data-sonner-toast]').filter({ hasText: '已导入 1 个处理脚本草案' })
  await expect(toast).toBeVisible()
  await page.getByRole('button', { name: '扫描参数', exact: true }).click({ timeout: 3000 })
  await expect(page.getByRole('dialog', { name: '扫描参数', exact: true })).toBeVisible()
  await expect(toast).toHaveCount(0, { timeout: 6000 })
  await page.getByRole('dialog').getByRole('button', { name: '完成', exact: true }).click()
  await upload()
  await expect(toast).toBeVisible()
  await toast.locator('[data-close-button]').click()
  await expect(toast).toHaveCount(0)
})
