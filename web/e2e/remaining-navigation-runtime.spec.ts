import fs from 'node:fs'
import path from 'node:path'
import { test, expect } from '@playwright/test'
import { openRemaining, remainingEvidence, remainingFixture, datasetRoute } from './remaining-pages.helpers'

test('opening a workspace does not compile every navigation destination in the background', async ({ page }) => {
  test.setTimeout(180000)
  await remainingFixture(page)
  // Exercise the actual user-browser branch, which differs from automated browsers.
  await page.addInitScript(() => Object.defineProperty(navigator, 'webdriver', { get: () => false }))
  const prefetches: string[] = []
  page.on('request', request => { if (request.headers()['next-router-prefetch'] === '1') prefetches.push(new URL(request.url()).pathname) })
  await openRemaining(page, datasetRoute('profile'), '数据画像')
  await page.evaluate(() => new Promise<void>(resolve => {
    requestAnimationFrame(() => {
      if ('requestIdleCallback' in window) window.requestIdleCallback(() => resolve(), { timeout: 2500 })
      else resolve()
    })
  }))
  await page.waitForLoadState('networkidle', { timeout: 90000 })
  fs.mkdirSync(path.join(remainingEvidence, 'runtime'), { recursive: true })
  fs.writeFileSync(path.join(remainingEvidence, 'runtime', 'navigation-prefetch.json'), JSON.stringify(prefetches, null, 2))
  expect(prefetches).toEqual([])
  await page.getByRole('link', { name: '数据集', exact: true }).click()
  await expect(page.getByRole('heading', { name: '数据集', exact: true })).toBeVisible({ timeout: 60000 })
})
