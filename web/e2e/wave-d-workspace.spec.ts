import { expect, test } from '@playwright/test'
import { lastBatchFixture } from './remaining-last-batch.helpers'
import { datasetRoute } from './remaining-pages.helpers'

test('shared workspace centers wide content and preserves overflow detection and sticky actions', async ({ page }) => {
  await lastBatchFixture(page)
  await page.setViewportSize({ width: 1920, height: 1080 })
  await page.goto('/observability', { waitUntil: 'domcontentloaded' })
  const workspace = page.locator('[data-operational-workspace="可观测性"]')
  await expect(workspace.getByRole('heading', { name: '可观测性', exact: true })).toBeVisible({ timeout: 60000 })
  await page.getByRole('tab', { name: '查询分析', exact: true }).click()
  const table = page.getByRole('table', { name: '查询分析', exact: true })
  await expect(table).toContainText('query-slow-001')
  const gutters = await workspace.evaluate((element) => {
    const header = element.firstElementChild!
    const body = element.querySelector('[data-workspace-content]')!
    const expected = Math.max(24, (element.clientWidth - 1440) / 2 + 24)
    return {
      expected,
      actual: [header.firstElementChild!, header.nextElementSibling!, body].map((node) =>
        Number.parseFloat(getComputedStyle(node).paddingLeft),
      ),
    }
  })
  for (const gutter of gutters.actual) expect(gutter).toBeCloseTo(gutters.expected, 0)
  const scroll = table.locator('..')
  await expect(scroll).toHaveCSS('border-top-width', '1px')
  await expect(scroll).toHaveCSS('border-radius', '10px')
  await expect(scroll).not.toHaveAttribute('role', 'region')
  await page.screenshot({ path: test.info().outputPath('workspace-wide.png'), animations: 'disabled' })
  await page.setViewportSize({ width: 390, height: 844 })
  const region = page.getByRole('region', { name: '查询分析表格', exact: true })
  await expect(region).toHaveAttribute('tabindex', '0')
  await expect(page.getByText('左右滑动查看完整字段', { exact: true })).toBeVisible()
  await region.scrollIntoViewIfNeeded()
  const action = table.locator('tbody tr').first().locator('td').last()
  const before = await action.boundingBox()
  await region.evaluate((element) => {
    element.scrollLeft = element.scrollWidth
  })
  expect(await region.evaluate((element) => element.scrollLeft)).toBeGreaterThan(0)
  expect((await action.boundingBox())!.x).toBeCloseTo(before!.x, 0)
  expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1)
  await page.screenshot({ path: test.info().outputPath('workspace-phone-scrolled.png'), animations: 'disabled' })
  await page.setViewportSize({ width: 1920, height: 1080 })
  await expect(scroll).not.toHaveAttribute('role', 'region')
  await expect(scroll).not.toHaveAttribute('tabindex', '0')
  await expect(page.getByText('左右滑动查看完整字段', { exact: true })).toBeHidden()
})

test('dataset workspaces retain bounded content and full-width canvas bodies', async ({ page }) => {
  test.setTimeout(240000)
  await lastBatchFixture(page)
  await page.setViewportSize({ width: 1920, height: 1080 })
  for (const route of ['profile', 'health', 'tables', 'db-catalog']) {
    await page.goto(datasetRoute(route), { waitUntil: 'domcontentloaded' })
    const workspace = page.locator('[data-operational-workspace]')
    await expect(workspace.locator('h1')).toBeVisible({ timeout: 60000 })
    const geometry = await workspace.locator('[data-workspace-content]').evaluate((element) => {
      const style = getComputedStyle(element)
      return {
        padding: Number.parseFloat(style.paddingLeft),
        overflow: style.overflowY,
        width: element.clientWidth,
        parent: element.parentElement!.clientWidth,
      }
    })
    expect(geometry.width).toBe(geometry.parent)
    if (geometry.overflow === 'hidden') expect(geometry.padding).toBe(0)
    else expect(geometry.padding).toBeCloseTo(Math.max(24, (geometry.parent - 1440) / 2 + 24), 0)
    expect(await page.evaluate(() => document.documentElement.scrollWidth - innerWidth)).toBeLessThanOrEqual(1)
  }
})
