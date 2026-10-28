import { test, expect } from '@playwright/test'
import { datasetRoute, openRemaining, remainingFixture, remainingShot } from './remaining-pages.helpers'

test('profile separates problems, distribution and scan history with explicit failed reads', async ({ page }) => {
  const state = await remainingFixture(page)
  await openRemaining(page, datasetRoute('profile'), '数据画像')
  await page.getByRole('tab', { name: '问题与概览', exact: true }).click()
  await expect(page.getByRole('table', { name: '画像问题清单' })).toContainText('扫描版 PDF')
  await page.getByRole('button', { name: '查看扫描版 PDF文件', exact: true }).click()
  await expect(page.getByRole('dialog')).toContainText('product-guide.pdf', { timeout: 30000 })
  await page.keyboard.press('Escape')
  await page.getByRole('tab', { name: '分布分析', exact: true }).click()
  await expect(page.getByRole('tab', { name: '文档分布', exact: true })).toBeVisible()
  await page.getByRole('tab', { name: '扫描历史', exact: true }).click()
  state.failHistory = true
  await page.getByRole('button', { name: '重新读取扫描历史', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: '扫描历史读取暂不可用' })).toBeVisible({ timeout: 30000 })
  expect(state.base.blocked).toEqual([])
})

test('health presents actual exceptions and a failed read can recover without reporting zero', async ({ page }) => {
  const state = await remainingFixture(page); state.failHealth = true
  await openRemaining(page, datasetRoute('health'), '健康概览')
  await expect(page.getByRole('button', { name: '重新读取健康概览', exact: true })).toBeVisible({ timeout: 30000 })
  await expect(page.locator('[data-health-document-count]')).toHaveCount(0)
  state.failHealth = false
  await page.getByRole('button', { name: '重新读取健康概览', exact: true }).click()
  await expect(page.locator('[data-health-document-count]')).toContainText('128', { timeout: 30000 })
  await expect(page.getByRole('table', { name: '健康异常清单' })).toContainText('扫描版 PDF')
  await remainingShot(page, 'health-desktop')
})

test('capture current profile and health workspaces', async ({ page }) => {
  await remainingFixture(page)
  for (const [name, title] of [['profile', '数据画像'], ['health', '健康概览']]) {
    await openRemaining(page, datasetRoute(name), title)
    await expect(page.getByText('产品知识库', { exact: true }).first()).toBeVisible({ timeout: 30000 })
    await remainingShot(page, `after-${name}`)
  }
})
