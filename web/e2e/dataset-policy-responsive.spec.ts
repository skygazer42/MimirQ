import { expect, test } from '@playwright/test'
import { datasetPolicyFixture, openPolicy, policyShot } from './dataset-policy.helpers'

test('laptop and enlarged reading keep rule actions inside the visible workspace', async ({ page }) => {
  const state = await datasetPolicyFixture(page)
  for (const size of [{ width: 1024, height: 768, name: 'laptop-1024' }, { width: 800, height: 500, name: 'zoom-equivalent' }]) {
    await page.setViewportSize(size); await openPolicy(page)
    const region = await page.locator('[data-policy-workspace]').boundingBox()
    const action = await page.getByRole('button', { name: '规则操作 PDF 文本文档', exact: true }).boundingBox()
    expect(action!.x + action!.width).toBeLessThanOrEqual(region!.x + region!.width)
    await expect(page.getByRole('button', { name: '保存策略', exact: true })).toBeVisible()
    expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true)
    await policyShot(page, size.name)
  }
  expect(state.errors).toEqual([]); expect(state.writes).toEqual([]); expect(state.blocked).toEqual([])
})
