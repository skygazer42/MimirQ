import { test, expect } from '@playwright/test'
import { remainingFixture, remainingShot } from './remaining-pages.helpers'
test('retain original advanced diagnostic workspaces', async ({ page }) => {
  test.setTimeout(600000)
  await remainingFixture(page)
  for (const [name, url, text] of [
    ['graph-snapshots', '/graph/snapshots', '图谱快照'],
    ['graph-diagnostics', '/graph/diagnostics', '图谱检索评测'],
    ['retrieval-ablations', '/evaluations/ablations', '检索调参对比'],
    ['similarity', '/knowledge/similarity', '矩阵设置'],
  ]) {
    await page.goto(url, { waitUntil: 'domcontentloaded' })
    await expect(page.getByText(text, { exact: true }).first()).toBeVisible({ timeout: 60000 })
    await remainingShot(page, `before-${name}`)
  }
})
