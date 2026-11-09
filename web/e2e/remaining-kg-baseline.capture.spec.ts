import { test, expect } from '@playwright/test'
import { realDatasetFixture, remainingShot } from './remaining-pages.helpers'

test('capture archived dataset KG before its migration', async ({ page }) => {
  const state = await realDatasetFixture(page)
  await page.goto(`/datasets/${state.dataset_id}/kg`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: /KG Workbench.*ui-redesign-verification/ })).toBeVisible({ timeout: 60000 })
  await remainingShot(page, 'before-kg')
})
