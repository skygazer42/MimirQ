import { expect, test } from '@playwright/test'

import {
  EnterpriseTelemetryMockState,
  installCommonApiMocks,
  installDeterministicRandom,
  installRagvizApiMocks,
} from './enterprise-quality-telemetry.helpers'

test.describe('enterprise telemetry visual regression', () => {
  test('graph 3d module keeps a stable semantic snapshot', async ({ page }) => {
    const state: EnterpriseTelemetryMockState = { uploaded: false }
    await installDeterministicRandom(page)
    await installCommonApiMocks(page, state)

    await page.goto('/graph')
    await expect(page.getByRole('heading', { name: '知识图谱' })).toBeVisible({ timeout: 60_000 })
    await page.getByRole('button', { name: '加载示例数据' }).click()

    const semanticList = page.getByLabel('知识图谱语义化结构列表')
    await expect(semanticList).toBeVisible({ timeout: 60_000 })
    await expect(semanticList).toContainText('Artificial Intelligence')
    await expect(semanticList).toHaveScreenshot('graph-3d-semantic-list.png', {
      animations: 'disabled',
    })
  })

  test('ragviz matrix layout keeps a stable screenshot', async ({ page }) => {
    const state: EnterpriseTelemetryMockState = { uploaded: false }
    await installCommonApiMocks(page, state)
    await installRagvizApiMocks(page)

    await page.goto('/knowledge/similarity')
    await expect(page.getByText('Collection × Collection 相似度热力图')).toBeVisible({ timeout: 60_000 })

    const selectors = page.locator('select')
    await selectors.nth(0).selectOption('alpha')
    await selectors.nth(1).selectOption('beta')
    await page.getByRole('button', { name: '计算相似度' }).click()

    await expect(page.getByText('当前显示对比数')).toBeVisible()
    await expect(page.getByText('4 / 4')).toBeVisible()
    await expect(page.locator('#main-content')).toHaveScreenshot('ragviz-heatmap.png', {
      animations: 'disabled',
    })
  })
})
