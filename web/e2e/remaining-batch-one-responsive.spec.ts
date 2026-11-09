import { test, expect } from '@playwright/test'
import { remainingFixture, datasetRoute, openRemaining, remainingShot } from './remaining-pages.helpers'

for (const variant of [
  { name: 'desktop', width: 1600, height: 1000, theme: 'light' as const },
  { name: 'narrow-dark', width: 1120, height: 850, theme: 'dark' as const },
  { name: 'phone', width: 390, height: 844, theme: 'light' as const },
]) {
  test(`batch one ${variant.name}: pages stay readable and overflow only inside data surfaces`, async ({ page }) => {
    test.setTimeout(600000)
    const state = await remainingFixture(page, variant.theme)
    await page.setViewportSize({ width: variant.width, height: variant.height })
    for (const [route, title] of [['profile', '数据画像'], ['health', '健康概览'], ['workflow', '工作流配置'], ['tables', '表格资产'], ['db-catalog', '数据库目录'], ['evidence', '证据库'], ['kg', '数据集图谱']]) {
      await openRemaining(page, datasetRoute(route), title)
      await expect(page.getByText('产品知识库', { exact: true }).first()).toBeVisible({ timeout: 30000 })
      await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
      await expect.poll(() => page.getByRole('heading', { name: title, exact: true }).evaluate(node => node.scrollWidth <= node.clientWidth + 1)).toBe(true)
      await remainingShot(page, `after-${route}-${variant.name}`)
    }
    expect(state.base.errors).toEqual([])
    expect(state.base.blocked).toEqual([])
  })
}
