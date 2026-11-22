import { test, expect } from '@playwright/test'
import { realDatasetFixture, remainingShot } from './remaining-pages.helpers'

test('capture the live dataset knowledge graph workspace', async ({ page }) => {
  const state = await realDatasetFixture(page)
  await page.goto(`/datasets/${state.dataset_id}/kg`, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '数据集图谱', exact: true })).toBeVisible({
    timeout: 60000,
  })
  await expect(page.getByText(state.name, { exact: true }).first()).toBeVisible()
  await remainingShot(page, 'baseline-kg')
})
