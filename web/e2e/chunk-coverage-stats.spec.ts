import path from 'node:path'
import { expect, test } from '@playwright/test'
import { fixture, open, noOverflow } from './chunk-compare.helpers'

const evidence = path.resolve(__dirname, '../../artifacts/rebrand/chunk-coverage-stats-v1')

test('coverage statistics stay readable in a themed popover without moving the source toolbar', async ({ page }) => {
  await fixture(page, { gaps: true })
  await open(page)
  const trigger = page.getByRole('button', { name: '覆盖统计', exact: true })
  const strip = page.locator('[data-original-preview-health-strip]')
  const before = await strip.boundingBox()
  await trigger.click()
  const panel = page.getByRole('dialog', { name: '原文覆盖统计', exact: true })
  await expect(panel).toBeVisible()
  await expect(panel.locator('dl>div').nth(0)).toContainText('覆盖率')
  await expect(panel.locator('dl>div').nth(1)).toContainText('重叠浪费0%')
  await expect(panel.locator('dl>div').nth(2)).toContainText('缺口2')
  await expect(panel).toContainText('最大缺口 2 字符')
  const progress = panel.getByRole('progressbar', { name: '原文覆盖率', exact: true })
  expect(Number(await progress.getAttribute('aria-valuenow'))).toBeGreaterThanOrEqual(98)
  const after = await strip.boundingBox()
  expect(Math.abs(after!.height - before!.height)).toBeLessThanOrEqual(1)
  await page.evaluate(() => document.fonts.ready)
  await panel.screenshot({ path: `${evidence}/light.png` })
  await page.keyboard.press('Escape')
  await expect(panel).toBeHidden()
  await expect(trigger).toBeFocused()

  await page.getByRole('button', { name: '切换主题', exact: true }).click()
  await page.getByRole('menuitem', { name: /深色|暗色/ }).click()
  await trigger.click()
  await expect(panel).toBeVisible()
  await expect.poll(() => panel.evaluate(element => {
    const channels = getComputedStyle(element).backgroundColor.match(/\d+/g)?.map(Number) || []
    return channels.slice(0, 3).every(value => value < 100)
  })).toBe(true)
  await panel.screenshot({ path: `${evidence}/dark.png` })
  await page.keyboard.press('Escape')

  await page.setViewportSize({ width: 390, height: 844 })
  const sidebarClose = page.getByRole('button', { name: '收起侧边栏', exact: true })
  if (await sidebarClose.isVisible()) await sidebarClose.click()
  await page.getByRole('button', { name: '文档原文', exact: true }).click()
  await trigger.click()
  await expect(panel).toBeVisible()
  const bounds = await panel.boundingBox()
  expect(bounds!.x).toBeGreaterThanOrEqual(0)
  expect(bounds!.x + bounds!.width).toBeLessThanOrEqual(390)
  await noOverflow(page)
  await page.screenshot({ path: `${evidence}/phone.png` })
})
