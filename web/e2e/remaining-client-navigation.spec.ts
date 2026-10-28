import { test, expect } from '@playwright/test'
import { remainingFixture, openRemaining, datasetRoute, remainingShot } from './remaining-pages.helpers'
test('client navigation resolves each route and its dynamic page module', async ({ page }) => {
  test.setTimeout(300000)
  const state = await remainingFixture(page)
  const badScripts: string[] = []
  page.on('response', response => { if (response.url().includes('/_next/') && response.url().split('?')[0].endsWith('.js') && !response.ok()) badScripts.push(new URL(response.url()).pathname) })
  await openRemaining(page, datasetRoute('health'), '健康概览')
  await page.getByRole('button', { name: '数据画像', exact: true }).click()
  await expect(page.getByRole('heading', { name: '数据画像', exact: true })).toBeVisible({ timeout: 60000 })
  await expect(page.getByText('正在读取数据画像…', { exact: true })).toHaveCount(0)
  await page.getByRole('button', { name: '返回上一级', exact: true }).click()
  await expect(page.getByRole('heading', { name: '数据集', exact: true })).toBeVisible({ timeout: 60000 })
  expect(badScripts).toEqual([])
  expect(state.base.errors).toEqual([])
  await remainingShot(page, 'after-client-navigation-datasets')
})
