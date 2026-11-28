import { test, expect } from '@playwright/test'
import { openPrecheck, precheckFixture } from './precheck-workspace.helpers'

test('a new policy application clears old success feedback while retaining the failed choice', async ({ page }) => {
  const state = await precheckFixture(page)
  await page.setViewportSize({ width: 390, height: 844 })
  await openPrecheck(page)
  await expect(page.locator('[data-precheck-total]')).toBeVisible({ timeout: 30000 })
  await page.getByRole('button', { name: '生成策略', exact: true }).click()
  const dialog = page.getByRole('dialog')
  await expect(dialog.getByRole('heading', { name: /建议规则.*4/ })).toBeVisible()
  await expect(dialog.getByRole('list')).toContainText('PDF 文本文档')
  await expect(dialog.getByText('已有策略时需要勾选覆盖，应用后会替换整份策略。', { exact: true })).toBeVisible()
  await dialog.getByRole('button', { name: '应用到数据集', exact: true }).click()
  const oldSuccess = page.getByText('已应用入库策略，共 4 条规则', { exact: true })
  await expect(oldSuccess).toBeVisible()
  await dialog.getByRole('button', { name: '关闭', exact: true }).click()
  await page.getByRole('button', { name: '生成策略', exact: true }).click()
  await expect(oldSuccess).toHaveCount(0, { timeout: 2000 })
  await dialog.getByLabel('覆盖已有入库策略', { exact: true }).check()
  await dialog.getByText('查看策略 JSON', { exact: true }).click()
  state.failApply = '本次策略写入失败'
  await dialog.getByRole('button', { name: '应用到数据集', exact: true }).click()
  await expect(dialog.getByRole('alert')).toContainText('本次策略写入失败')
  await expect(oldSuccess).toHaveCount(0)
  await expect(dialog.getByLabel('覆盖已有入库策略', { exact: true })).toBeChecked()
  await expect(dialog.locator('details')).toHaveAttribute('open', '')
  state.failApply = ''
  await dialog.getByRole('button', { name: '应用到数据集', exact: true }).click()
  await expect(oldSuccess).toBeVisible()
  expect(state.applies).toEqual([false, true, true])
  expect(state.base.blocked).toEqual([])
})
