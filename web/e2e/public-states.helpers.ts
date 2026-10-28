import fs from 'node:fs'
import path from 'node:path'
import { expect, type Page, type Route } from '@playwright/test'
import { datasetPolicyFixture, policyRoute } from './dataset-policy.helpers'

export const publicStateEvidence = path.resolve(__dirname, '../../artifacts/rebrand/public-states-v1/tests')
async function json(route: Route, value: unknown, status = 200) { await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) }) }
export async function publicStateFixture(page: Page, theme: 'light' | 'dark' = 'light', authenticated = true) {
  const policyState = await datasetPolicyFixture(page, theme)
  await page.addInitScript(hasToken => {
    if (hasToken) {
      sessionStorage.setItem('mimirq_access_token', 'isolated-boundary-fixture')
      localStorage.setItem('mimirq_user_id', 'fixture-user')
      localStorage.setItem('mimirq_tenant_id', 'tenant-fixture')
      localStorage.setItem('mimirq_user_profile', JSON.stringify({ id: 'fixture-user', username: 'boundary.user', email: 'boundary@example.com', is_active: true, system_role: 'user' }))
    }
  }, authenticated)
  const state = { policyState, authenticated, settingsRead: false, promptsOpen: false, failAccess: false, accessReads: 0 }
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), url = new URL(request.url()), p = url.pathname.replace(/\/$/, ''), method = request.method()
    if (p === '/api/v1/meta' && method === 'GET') return json(route, { name: 'Ragvia API', api_version: 'fixture', features: { auth_mode: state.authenticated ? 'jwt' : 'header', vector_backend: 'memory', task_queue_enabled: false } })
    if (p === '/api/v1/auth/me') return json(route, { id: 'fixture-user', username: 'boundary.user', email: 'boundary@example.com', is_active: true, system_role: 'user' })
    if (p === '/api/v1/rbac/me') {
      state.accessReads++
      return state.failAccess ? json(route, { detail: '权限服务暂不可用' }, 503) : json(route, { tenant_id: 'tenant-fixture', account_id: 'fixture-user', role: state.settingsRead ? 'admin' : 'viewer', is_active: true, is_current: true, permissions: state.settingsRead ? ['settings.read', 'settings.write'] : [], navigation_user_visible_modules: state.promptsOpen ? ['prompts'] : [] })
    }
    if (p === '/api/v1/rbac/members') return json(route, { total: 0, items: [] })
    return route.fallback()
  })
  return state
}
export async function publicStateShot(page: Page, name: string) {
  fs.mkdirSync(publicStateEvidence, { recursive: true })
  await page.screenshot({ path: `${publicStateEvidence}/${name}.png`, animations: 'disabled' })
  const html = (await page.content()).replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '').replace(/\b(href|src)="\/(?!\/)/g, '$1="http://127.0.0.1:3000/')
  fs.writeFileSync(path.join(publicStateEvidence, `${name}.html`), html)
}
export async function openPublicState(page: Page, url: string, title: string) {
  await page.goto(url, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible({ timeout: 60000 })
}
export async function openInjectedRouteError(page: Page, state: Awaited<ReturnType<typeof publicStateFixture>>) {
  state.policyState.policy.rules![0].name = { fixture: 'page-boundary' } as unknown as string
  await openPublicState(page, policyRoute, '页面加载失败')
}
