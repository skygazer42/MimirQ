import { test, expect } from '@playwright/test'
import { realDatasetFixture, remainingShot } from './remaining-pages.helpers'
test('retain the three original second-batch pages', async ({ page }) => {
  test.setTimeout(600000)
  const state = await realDatasetFixture(page)
  await page.setViewportSize({ width: 1600, height: 1000 })
  for (const [name, url] of [
    ['execution-monitor', `/knowledge/ingestion?mode=execution-monitor&datasetId=${state.dataset_id}`],
    ['common-lines', '/data-governance/common-lines'],
    ['industry-rules', '/governance/industry-rules'],
  ]) {
    await page.goto(url, { waitUntil: 'domcontentloaded' })
    await expect(page.getByRole('heading', { level: 1 }).first()).toBeVisible({ timeout: 60000 })
    await remainingShot(page, `before-${name}`)
  }
})
