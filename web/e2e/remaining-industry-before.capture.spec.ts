import { test, expect } from '@playwright/test'
import { realDatasetFixture, remainingShot } from './remaining-pages.helpers'
test('original industry rules baseline', async ({ page }) => {
  await realDatasetFixture(page)
  await page.setViewportSize({ width: 1600, height: 1000 })
  const detail = page.waitForResponse(response => /\/industry-rules\/rulesets\/[^/]+$/.test(new URL(response.url()).pathname) && response.ok())
  await page.goto('/governance/industry-rules', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '行业规则库', exact: true })).toBeVisible({ timeout: 60000 })
  await detail
  await remainingShot(page, 'before-industry-rules')
})
