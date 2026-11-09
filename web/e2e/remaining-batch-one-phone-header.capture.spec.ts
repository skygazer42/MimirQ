import { test, expect } from '@playwright/test'
import { remainingFixture, openRemaining, datasetRoute, remainingShot } from './remaining-pages.helpers'
test('phone header titles and textual export actions stay inside their own targets', async ({ page }) => {
  await remainingFixture(page)
  await page.setViewportSize({ width: 390, height: 844 })
  for (const [route, title] of [['profile', '数据画像'], ['health', '健康概览']]) {
    await openRemaining(page, datasetRoute(route), title)
    await expect(page.getByText('产品知识库', { exact: true }).first()).toBeVisible()
    await expect.poll(() => page.locator('[data-operational-workspace] header button').evaluateAll(buttons => buttons.every(button => button.scrollWidth <= button.clientWidth + 1))).toBe(true)
    await remainingShot(page, `after-${route}-phone`)
  }
})
