import { test, expect } from '@playwright/test'
import { batchTwoFixture } from './remaining-batch-two.helpers'
import { openRemaining, remainingShot } from './remaining-pages.helpers'
import { policyDatasetId } from './dataset-policy.helpers'
for (const variant of [{ name: 'desktop', width: 1600, height: 1000, theme: 'light' as const }, { name: 'narrow-dark', width: 1120, height: 850, theme: 'dark' as const }, { name: 'phone', width: 390, height: 844, theme: 'light' as const }]) {
  test(`second batch ${variant.name} surfaces and on-demand forms`, async ({ page }) => {
    test.setTimeout(300000)
    await batchTwoFixture(page, variant.theme)
    await page.setViewportSize({ width: variant.width, height: variant.height })
    for (const [name, route, title] of [['execution-monitor', `/knowledge/ingestion?mode=execution-monitor&datasetId=${policyDatasetId}`, '入库执行监控'], ['common-lines', '/data-governance/common-lines', '重复内容规则'], ['industry-rules', '/governance/industry-rules', '行业规则']]) {
      await openRemaining(page, route, title)
      if (name === 'execution-monitor') await expect(page.getByRole('table').first().getByRole('row')).toHaveCount(21)
      if (name === 'common-lines') { await page.getByRole('button', { name: '扫描重复内容', exact: true }).click(); await expect(page.getByText('版权所有，未经许可不得转载', { exact: true })).toBeVisible() }
      if (name === 'industry-rules') await expect(page.getByRole('cell', { name: '单点登录', exact: true })).toBeVisible()
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
      await remainingShot(page, `after-${name}-${variant.name}`)
      if (name === 'common-lines') {
        await page.getByRole('button', { name: '扫描参数', exact: true }).click()
        await expect(page.getByRole('dialog').getByRole('spinbutton', { name: '最小命中比例', exact: true })).toBeVisible()
        await remainingShot(page, `after-common-lines-settings-${variant.name}`)
        await page.getByRole('dialog').getByRole('button', { name: '完成', exact: true }).click()
      }
    }
  })
}
