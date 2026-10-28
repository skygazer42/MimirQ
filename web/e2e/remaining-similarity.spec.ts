import { test, expect } from '@playwright/test'
import { similarityFixture } from './remaining-similarity.helpers'
import { openRemaining, remainingShot } from './remaining-pages.helpers'

test('controlled tool dialogs return keyboard focus to their opener', async ({ page }) => {
  await similarityFixture(page)
  await openRemaining(page, '/knowledge/similarity', '向量相似度诊断')
  const source = page.getByRole('button', { name: '数据源与计算', exact: true })
  await source.click()
  await expect(page.getByRole('dialog', { name: '数据源与计算', exact: true })).toBeVisible()
  await page.keyboard.press('Escape')
  await expect(page.getByRole('dialog')).toHaveCount(0)
  await expect(source).toBeFocused()
})

for (const variant of [{ name: 'desktop', width: 1600, height: 1000, theme: 'light' as const }, { name: 'narrow-dark', width: 1120, height: 850, theme: 'dark' as const }, { name: 'phone', width: 390, height: 844, theme: 'light' as const }]) {
  test(`similarity ${variant.name} preserves failed inputs and displays a calculated matrix`, async ({ page }) => {
    const state = await similarityFixture(page, variant.theme)
    await page.setViewportSize(variant)
    await openRemaining(page, '/knowledge/similarity', '向量相似度诊断')
    await page.getByRole('button', { name: '数据源与计算', exact: true }).click()
    const dialog = page.getByRole('dialog')
    await dialog.getByRole('combobox', { name: '横轴数据源 1', exact: true }).selectOption('source-a')
    await dialog.getByRole('combobox', { name: '纵轴数据源 1', exact: true }).selectOption('source-b')
    await dialog.getByRole('spinbutton', { name: '横轴最大项目数', exact: true }).fill('40')
    await remainingShot(page, `after-similarity-source-${variant.name}`)
    await dialog.getByRole('button', { name: '计算相似度', exact: true }).click()
    await expect(page.getByRole('alert').filter({ hasText: '相似度服务暂不可用' })).toBeVisible()
    await page.getByRole('button', { name: '数据源与计算', exact: true }).click()
    await expect(dialog.getByRole('spinbutton', { name: '横轴最大项目数', exact: true })).toHaveValue('40')
    await expect(dialog.getByRole('combobox', { name: '纵轴数据源 1', exact: true })).toHaveValue('source-b')
    state.fail = false
    await dialog.getByRole('button', { name: '计算相似度', exact: true }).click()
    await expect(page.getByText('2 × 2', { exact: true })).toBeVisible()
    await expect(page.locator('[aria-label="相似度工作区"] svg').first()).toBeVisible()
    await expect(page.getByText('0.73', { exact: true }).first()).toBeVisible()
    expect(state.requests).toHaveLength(2)
    await expect.poll(() => page.evaluate(() => document.documentElement.scrollWidth <= innerWidth + 1)).toBe(true)
    await remainingShot(page, `after-similarity-${variant.name}`)
    await page.getByRole('button', { name: '显示与筛选', exact: true }).click()
    await expect(dialog.getByRole('button', { name: '完成', exact: true })).toBeVisible()
    await remainingShot(page, `after-similarity-filters-${variant.name}`)
  })
}
