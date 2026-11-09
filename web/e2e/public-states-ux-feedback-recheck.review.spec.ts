import fs from 'node:fs'
import path from 'node:path'
import { expect, test, type Page } from '@playwright/test'
import { publicStateFixture } from './public-states.helpers'

const evidence = path.resolve(__dirname, '../../artifacts/rebrand/public-states-v1/ux-recheck/confirmation-02')
const completionMessage = '校验完成，当前账号仍无法访问此页面。'
fs.mkdirSync(evidence, { recursive: true })

async function capture(page: Page, label: string) {
  const metrics = {
    viewport: page.viewportSize(),
    document: await page.evaluate(() => ({ width: innerWidth, height: innerHeight, scrollWidth: document.documentElement.scrollWidth })),
  }
  const snapshot = await page.locator('body').ariaSnapshot()
  const statuses = await page.getByRole('status').allTextContents()
  await page.screenshot({ path: path.join(evidence, `${label}.png`), animations: 'disabled' })
  fs.writeFileSync(path.join(evidence, `${label}.txt`), `URL: ${page.url()}\nMetrics: ${JSON.stringify(metrics)}\nStatuses: ${JSON.stringify(statuses)}\n${snapshot}`)
  console.log(`OBSERVATION ${label}\n${snapshot}`)
}

async function fixture(page: Page, viewport: { width: number; height: number }) {
  const unexpectedApi: string[] = []
  // This is registered first, so helper fallbacks cannot reach a real API.
  await page.route('**/api/v1/**', async route => {
    unexpectedApi.push(`${route.request().method()} ${new URL(route.request().url()).pathname}`)
    await route.fulfill({ status: 409, contentType: 'application/json', body: JSON.stringify({ detail: '隔离审查未配置此请求' }) })
  })
  const state = await publicStateFixture(page)
  await page.setViewportSize(viewport)
  const pageerrors: string[] = []
  const mutations: string[] = []
  page.on('pageerror', error => pageerrors.push(error.message))
  page.on('request', request => {
    if (new URL(request.url()).pathname.startsWith('/api/v1/') && !['GET', 'HEAD', 'OPTIONS'].includes(request.method())) {
      mutations.push(`${request.method()} ${new URL(request.url()).pathname}`)
    }
  })
  return { state, unexpectedApi, pageerrors, mutations }
}

async function gateNextAccess(page: Page) {
  let release!: () => void
  const gate = new Promise<void>(resolve => { release = resolve })
  await page.route('**/api/v1/rbac/me', async route => { await gate; await route.fallback() }, { times: 1 })
  const request = page.waitForRequest(request => new URL(request.url()).pathname === '/api/v1/rbac/me')
  return { release, request }
}

async function enterDenied(page: Page) {
  await page.goto('/settings/rbac', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '无权限访问', exact: true })).toBeVisible({ timeout: 60000 })
  await page.getByText('权限信息', { exact: true }).click()
  await expect(page.getByText('settings.read', { exact: true })).toBeVisible()
}

async function noChangeRecheck(page: Page, prefix: string) {
  const gate = await gateNextAccess(page)
  await page.getByRole('button', { name: '重新校验', exact: true }).click()
  await gate.request
  await expect(page.getByRole('button', { name: '重新校验', exact: true })).toBeDisabled()
  await capture(page, `${prefix}-pending`)
  const response = page.waitForResponse(response => new URL(response.url()).pathname === '/api/v1/rbac/me' && response.status() === 200)
  gate.release()
  await response
  await expect(page.getByRole('button', { name: '重新校验', exact: true })).toBeEnabled({ timeout: 60000 })
  await expect(page.getByRole('heading', { name: '无权限访问', exact: true })).toBeVisible()
  await expect(page.getByText(completionMessage, { exact: true })).toBeVisible()
  await capture(page, `${prefix}-complete`)
}

test('same-path UX recheck: desktop unchanged feedback and next validation', async ({ page }) => {
  const run = await fixture(page, { width: 1600, height: 1000 })
  await enterDenied(page)
  await capture(page, '01-desktop-permission-information')
  await noChangeRecheck(page, '02-desktop-no-change')
  run.state.settingsRead = true
  const gate = await gateNextAccess(page)
  await page.getByRole('button', { name: '重新校验', exact: true }).click()
  await gate.request
  await expect(page.getByRole('button', { name: '重新校验', exact: true })).toBeDisabled()
  await capture(page, '03a-desktop-next-validation-immediate')
  await expect(page.getByText(completionMessage, { exact: true })).toHaveCount(0, { timeout: 2000 })
  await capture(page, '03b-desktop-next-validation-feedback-cleared')
  gate.release()
  await expect(page.getByRole('heading', { name: '成员权限', exact: true })).toBeVisible({ timeout: 60000 })
  await expect(page).toHaveURL(/\/settings\/rbac$/)
  await capture(page, '04-desktop-access-restored')
  fs.writeFileSync(path.join(evidence, 'desktop-run-state.json'), JSON.stringify({ ...run, state: { accessReads: run.state.accessReads, blocked: run.state.policyState.blocked, writes: run.state.policyState.writes, previews: run.state.policyState.previews } }, null, 2))
  expect(run.unexpectedApi).toEqual([])
  expect(run.state.policyState.blocked).toEqual([])
  expect(run.state.policyState.writes).toEqual([])
  expect(run.mutations.filter(request => request !== 'POST /api/v1/observability/frontend-vitals')).toEqual([])
  expect(run.pageerrors).toEqual([])
})

test('same-path UX recheck: mobile failure recovery and browser return', async ({ page }) => {
  const run = await fixture(page, { width: 390, height: 844 })
  await enterDenied(page)
  await capture(page, '05-mobile-permission-information')
  await noChangeRecheck(page, '06-mobile-no-change')
  run.state.failAccess = true
  const gate = await gateNextAccess(page)
  await page.getByRole('button', { name: '重新校验', exact: true }).click()
  await gate.request
  await expect(page.getByRole('button', { name: '重新校验', exact: true })).toBeDisabled()
  await capture(page, '07a-mobile-next-validation-immediate')
  await expect(page.getByText(completionMessage, { exact: true })).toHaveCount(0, { timeout: 2000 })
  await capture(page, '07b-mobile-next-validation-feedback-cleared')
  gate.release()
  await expect(page.getByRole('heading', { name: '无法确认权限', exact: true })).toBeVisible({ timeout: 60000 })
  await expect(page.getByRole('button', { name: '重新校验', exact: true })).toBeEnabled({ timeout: 60000 })
  await expect(page.getByText('settings.read', { exact: true })).toBeVisible()
  await capture(page, '08-mobile-access-read-failed')
  run.state.failAccess = false
  run.state.settingsRead = true
  await page.getByRole('button', { name: '重新校验', exact: true }).click()
  await expect(page.getByRole('heading', { name: '成员权限', exact: true })).toBeVisible({ timeout: 60000 })
  await expect(page).toHaveURL(/\/settings\/rbac$/)
  await capture(page, '09-mobile-access-restored')
  const response = await page.goto('/__missing-boundary-fixture__', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '页面不存在', exact: true })).toBeVisible({ timeout: 60000 })
  await page.setViewportSize({ width: 390, height: 844 })
  await capture(page, '10-mobile-missing-location')
  await page.setViewportSize({ width: 1600, height: 1000 })
  await capture(page, '11-desktop-missing-location')
  await page.setViewportSize({ width: 390, height: 844 })
  await page.goBack({ waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '成员权限', exact: true })).toBeVisible({ timeout: 60000 })
  await expect(page).toHaveURL(/\/settings\/rbac$/)
  await capture(page, '12-mobile-browser-return')
  fs.writeFileSync(path.join(evidence, 'mobile-run-state.json'), JSON.stringify({ unexpectedApi: run.unexpectedApi, pageerrors: run.pageerrors, mutations: run.mutations, accessReads: run.state.accessReads, blocked: run.state.policyState.blocked, writes: run.state.policyState.writes, previews: run.state.policyState.previews, missingResponse: response?.status() }, null, 2))
  expect(run.unexpectedApi).toEqual([])
  expect(run.state.policyState.blocked).toEqual([])
  expect(run.state.policyState.writes).toEqual([])
  expect(run.mutations.filter(request => request !== 'POST /api/v1/observability/frontend-vitals')).toEqual([])
  expect(run.pageerrors).toEqual([])
})
