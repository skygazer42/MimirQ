import { expect, test } from '@playwright/test'
import { openUsage, usageEvidence, usageFixture, waitUsage } from './usage-overview.helpers'

test('returning from a dataset preserves the selected usage window', async ({ page }) => {
  await usageFixture(page); await openUsage(page); await waitUsage(page)
  await page.getByRole('button', { name: '近 30 天', exact: true }).click(); await waitUsage(page)
  const before = await page.locator('dl[aria-label="累计用量"] dd').nth(1).textContent()
  await page.getByRole('link', { name: '查看工程文档库知识库', exact: true }).click()
  await expect(page).toHaveURL(/\/knowledge\?dataset=ds-engineering/, { timeout: 30_000 })
  await page.goBack({ waitUntil: 'domcontentloaded' }); await waitUsage(page)
  await expect(page.getByRole('button', { name: '近 30 天', exact: true })).toHaveAttribute('aria-pressed', 'true')
  await expect(page.locator('dl[aria-label="累计用量"] dd').nth(1)).toHaveText(before || '')
  await page.screenshot({ path: `${usageEvidence}/returned-context.png` })
})

test('an unavailable attribution source cannot turn an empty partial result into a confirmed zero', async ({ page }) => {
  const { state } = await usageFixture(page); state.empty = true; state.fail.add('cost')
  await openUsage(page)
  await expect(page.getByRole('button', { name: '重试链路资源', exact: true })).toBeVisible({ timeout: 30_000 })
  await expect(page.getByRole('heading', { name: '暂无用量记录', exact: true })).toHaveCount(0)
  await expect(page.getByRole('heading', { name: '未取得完整用量数据', exact: true })).toBeVisible()
})

test('narrow tables announce their hidden columns without duplicating disabled states', async ({ page }) => {
  const { state } = await usageFixture(page); state.chat.enabled = false
  await page.setViewportSize({ width: 390, height: 844 }); await openUsage(page); await waitUsage(page)
  const hint = page.getByText('左右滑动查看全部字段', { exact: true })
  await hint.scrollIntoViewIfNeeded(); await expect(hint).toBeVisible()
  await expect(page.getByText('未启用此项限制', { exact: true })).toHaveCount(0)
  await page.screenshot({ path: `${usageEvidence}/phone-scroll-hint.png` })
})
