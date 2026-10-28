import { test, expect } from '@playwright/test'
import { openRemaining, remainingShot } from './remaining-pages.helpers'
import { diagnosticsFixture, secondDataset } from './remaining-advanced-diagnostics.helpers'
import { policyDatasetId } from './dataset-policy.helpers'

test('diagnostics retain failed configuration, expose results and reject a late dataset result', async ({ page }) => {
  const state = await diagnosticsFixture(page)
  await openRemaining(page, '/graph/diagnostics', '图谱检索评测')
  const dataset = page.getByRole('combobox', { name: '数据集', exact: true })
  await expect(dataset).toHaveValue(policyDatasetId)
  await page.getByRole('spinbutton', { name: '评测样本数', exact: true }).fill('25')
  await page.getByRole('button', { name: '开始评测', exact: true }).click()
  await expect(page.getByRole('alert').filter({ hasText: '诊断服务暂不可用' })).toBeVisible()
  await expect(page.getByRole('spinbutton', { name: '评测样本数', exact: true })).toHaveValue('25')
  state.fail = false
  await page.getByRole('button', { name: '开始评测', exact: true }).click()
  await expect(page.getByRole('cell', { name: '维护周期是多久？', exact: true })).toBeVisible()
  expect(state.requests.at(-1)?.max_cases).toBe(25)
  await remainingShot(page, 'after-graph-diagnostics-filled')
  await page.getByRole('tab', { name: '抽取质量', exact: true }).click()
  await page.getByRole('button', { name: '读取质量报告', exact: true }).click()
  await expect(page.getByText('43', { exact: true })).toBeVisible()
  let release!: () => void
  state.gate = new Promise<void>(resolve => { release = resolve })
  await page.getByRole('button', { name: '开始评测', exact: true }).click()
  await expect.poll(() => state.requests.length).toBe(3)
  await dataset.selectOption(secondDataset)
  release()
  await expect(page.getByRole('heading', { name: '尚未运行评测', exact: true })).toBeVisible()
  await expect(page.getByText('维护周期是多久？', { exact: true })).toHaveCount(0)
})

for (const variant of [{ name: 'narrow-dark', width: 1120, height: 850, theme: 'dark' as const }, { name: 'phone', width: 390, height: 844, theme: 'light' as const }]) {
  test(`diagnostics ${variant.name} configuration and reader remain usable`, async ({ page }) => {
    await diagnosticsFixture(page, variant.theme)
    await page.setViewportSize(variant)
    await openRemaining(page, '/graph/diagnostics', '图谱检索评测')
    if (variant.name === 'phone') await page.getByRole('button', { name: '评测配置', exact: true }).click()
    await expect(page.getByRole('spinbutton', { name: '评测样本数', exact: true })).toBeVisible()
    await remainingShot(page, `after-graph-diagnostics-${variant.name}`)
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
  })
}
