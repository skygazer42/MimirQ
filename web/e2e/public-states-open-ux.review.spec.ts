import fs from 'node:fs'
import path from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import { publicStateFixture } from './public-states.helpers'

const evidence = path.resolve(__dirname, '../../artifacts/rebrand/public-states-v1/ux-review')
fs.mkdirSync(evidence, { recursive: true })

async function capture(page: Page, label: string) {
  const metrics = { viewport: page.viewportSize(), document: await page.evaluate(() => ({ width: innerWidth, height: innerHeight, scrollWidth: document.documentElement.scrollWidth })) }
  await page.screenshot({ path: path.join(evidence, `${label}.png`), animations: 'disabled' })
  const snapshot = await page.locator('body').ariaSnapshot()
  fs.writeFileSync(path.join(evidence, `${label}.txt`), `URL: ${page.url()}\nMetrics: ${JSON.stringify(metrics)}\n${snapshot}`)
  console.log(`OBSERVATION ${label}\n${snapshot}`)
}

test('open UX observation from settings entry', async ({ page }) => {
  await page.setViewportSize({ width: 1600, height: 1000 })
  const state = await publicStateFixture(page)
  const errors: string[] = []
  page.on('pageerror', error => errors.push(error.message))
  await page.goto('/settings/rbac', { waitUntil: 'domcontentloaded' })
  await expect.poll(() => state.accessReads, { timeout: 60000 }).toBeGreaterThan(0)
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible({ timeout: 60000 })
  await capture(page, '01-desktop-entry')
  await page.getByText('权限信息', { exact: true }).click()
  await capture(page, '02-desktop-permission-information')
  let releaseNoChange!: () => void
  const noChangeGate = new Promise<void>(resolve => { releaseNoChange = resolve })
  await page.route('**/api/v1/rbac/me', async route => { await noChangeGate; await route.fallback() }, { times: 1 })
  const noChangeRequest = page.waitForRequest(request => new URL(request.url()).pathname === '/api/v1/rbac/me')
  await page.getByRole('button', { name: '重新校验', exact: true }).click()
  await noChangeRequest
  await expect(page.getByRole('button', { name: '重新校验', exact: true })).toBeDisabled()
  await capture(page, '02b-desktop-recheck-pending')
  const noChangeResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/rbac/me' && response.status() === 200)
  releaseNoChange()
  await noChangeResponse
  await expect(page.getByRole('button', { name: '重新校验', exact: true })).toBeEnabled({ timeout: 60000 })
  await capture(page, '03-desktop-recheck-no-change')
  state.settingsRead = true
  await page.getByRole('button', { name: '重新校验', exact: true }).click()
  await expect(page.getByRole('heading', { name: '无权限访问', exact: true })).toBeHidden({ timeout: 60000 })
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible({ timeout: 60000 })
  await capture(page, '04-desktop-access-restored')
  await page.setViewportSize({ width: 390, height: 844 })
  state.settingsRead = false
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '无权限访问', exact: true })).toBeVisible({ timeout: 60000 })
  await capture(page, '05-mobile-entry')
  await page.getByText('权限信息', { exact: true }).click()
  await capture(page, '06-mobile-permission-information')
  state.failAccess = true
  let releaseRecheck!: () => void
  const recheckGate = new Promise<void>(resolve => { releaseRecheck = resolve })
  await page.route('**/api/v1/rbac/me', async route => { await recheckGate; await route.fallback() }, { times: 1 })
  const recheckRequest = page.waitForRequest(request => new URL(request.url()).pathname === '/api/v1/rbac/me')
  await page.getByRole('button', { name: '重新校验', exact: true }).click()
  await recheckRequest
  await capture(page, '07-mobile-recheck-pending')
  const recheckResponse = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/rbac/me' && response.status() === 503)
  releaseRecheck()
  await recheckResponse
  await page.evaluate(() => new Promise(resolve => requestAnimationFrame(() => requestAnimationFrame(resolve))))
  await capture(page, '08-mobile-recheck-after-first-503')
  await expect(page.getByRole('button', { name: '重新校验', exact: true })).toBeEnabled({ timeout: 60000 })
  await capture(page, '09-mobile-recheck-failed-complete')
  state.failAccess = false
  state.settingsRead = true
  await page.getByRole('button', { name: '重新校验', exact: true }).click()
  await expect(page.getByRole('heading', { name: '成员权限', exact: true })).toBeVisible({ timeout: 60000 })
  await capture(page, '10-mobile-access-restored')
  fs.writeFileSync(path.join(evidence, '01-pageerrors.json'), JSON.stringify(errors, null, 2))
})

test('open UX observation from a stale direct location', async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 })
  const state = await publicStateFixture(page)
  state.settingsRead = true
  await page.goto('/settings/rbac', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '成员权限', exact: true })).toBeVisible({ timeout: 60000 })
  const response = await page.goto('/__missing-boundary-fixture__', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { level: 1 })).toBeVisible({ timeout: 60000 })
  await page.setViewportSize({ width: 390, height: 844 })
  await capture(page, '11-mobile-missing-location')
  await page.setViewportSize({ width: 1600, height: 1000 })
  await capture(page, '12-desktop-missing-location')
  fs.writeFileSync(path.join(evidence, '11-missing-location-response.json'), JSON.stringify({ status: response?.status(), url: page.url() }, null, 2))
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goBack({ waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '成员权限', exact: true })).toBeVisible({ timeout: 60000 })
  await capture(page, '13-mobile-browser-back-restores-task')
})
