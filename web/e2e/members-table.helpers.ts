import fs from 'node:fs'
import path from 'node:path'
import { expect, type Page, type Route } from '@playwright/test'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'
import type { TenantMember } from '../lib/api/access'

const facts = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../public/brand/explorations/members-layouts-v1/facts.json'), 'utf8')) as { members: TenantMember[] }
export const memberEvidence = path.resolve(__dirname, '../../artifacts/rebrand/members-table-v1/tests')
export function fixtureMembers(): TenantMember[] {
  return facts.members.map(member => ({ ...member, tenant_id: 'tenant-fixture', is_current: member.is_current || member.user_id === 'member-viewer-a', created_at: member.created_at!.replace(' ', 'T') + ':00+08:00', updated_at: member.updated_at!.replace(' ', 'T') + ':00+08:00' }))
}
async function json(route: Route, value: unknown, status = 200) { await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) }) }
export async function memberFixture(page: Page, theme: 'light' | 'dark' = 'light') {
  await page.setViewportSize({ width: 1600, height: 1000 })
  await installCommonApiMocks(page, { uploaded: false })
  await page.addInitScript(mode => {
    localStorage.setItem('theme', mode); localStorage.setItem('mimirq.surfaceTheme', 'ocean'); localStorage.setItem('mimirq.themeColor', '#20262e')
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (value: string) => { (window as unknown as { copiedMember: string }).copiedMember = value } } })
  }, theme)
  const state = {
    members: fixtureMembers(), accountId: 'member-owner', canRead: true, canManage: true, failList: false, failRole: '', failRemove: '', failScim: false, samlConfigured: false,
    failReadAfterWrite: false, gate: null as Promise<void> | null, reads: [] as number[], writes: [] as { path: string; method: string; body: Record<string, unknown> | null }[],
    scimCalls: [] as { tenant: string; token: string }[], samlProviders: [] as string[], blocked: [] as string[], errors: [] as string[],
  }
  page.on('pageerror', error => state.errors.push(error.message))
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), url = new URL(request.url()), p = url.pathname.replace(/\/$/, ''), method = request.method()
    if (p === '/api/v1/rbac/me') return json(route, { tenant_id: 'tenant-fixture', account_id: state.accountId, role: state.members.find(member => member.user_id === state.accountId)?.role || 'admin', is_active: true, is_current: true, permissions: state.canRead ? state.canManage ? ['settings.read', 'settings.write'] : ['settings.read'] : [] })
    if (p === '/api/v1/rbac/members' && method === 'GET') {
      const skip = Number(url.searchParams.get('skip') || 0), limit = Number(url.searchParams.get('limit') || 200)
      state.reads.push(skip)
      return state.failList ? json(route, { detail: '成员目录暂不可用' }, 503) : json(route, { items: state.members.slice(skip, skip + limit), total: state.members.length })
    }
    if (p.startsWith('/api/v1/rbac/members/') && ['PATCH', 'DELETE'].includes(method)) {
      const body = method === 'DELETE' ? null : request.postDataJSON() as Record<string, unknown>
      state.writes.push({ path: p, method, body })
      if (state.gate) await state.gate
      if (!state.canManage) return json(route, { detail: '没有权限管理成员' }, 403)
      const userId = decodeURIComponent(p.split('/').at(-1)!), member = state.members.find(item => item.user_id === userId)
      if (!member) return json(route, { detail: '找不到该成员' }, 404)
      if (method === 'PATCH') {
        if (state.failRole) return json(route, { detail: state.failRole }, 409)
        member.role = String(body!.role); member.updated_at = '2026-10-26T16:50:00+08:00'
        if (member.user_id === state.accountId && !['owner', 'admin'].includes(member.role)) { state.canManage = false; state.canRead = false }
        if (state.failReadAfterWrite) state.failList = true
        return json(route, member)
      }
      if (state.failRemove) return json(route, { detail: state.failRemove }, 409)
      state.members = state.members.filter(item => item.user_id !== userId)
      return json(route, { user_id: userId, removed: true, revoked_group_memberships: 1, revoked_dataset_permissions: 2, revoked_document_permissions: 1 })
    }
    // Credential tests and downloads must never reach the real API.
    if (p === '/api/v1/scim/v2/ServiceProviderConfig') {
      const headers = request.headers(); state.scimCalls.push({ tenant: headers['x-tenant-id'], token: headers.authorization })
      return state.failScim ? json(route, { detail: 'SCIM 凭据无效' }, 401) : json(route, { schemas: ['urn:ietf:params:scim:schemas:core:2.0:ServiceProviderConfig'], patch: { supported: true } })
    }
    if (p === '/api/v1/auth/saml/metadata') {
      state.samlProviders.push(url.searchParams.get('provider_id') || '')
      return state.samlConfigured ? route.fulfill({ status: 200, contentType: 'application/xml', body: '<?xml version="1.0"?><EntityDescriptor entityID="fixture" />' }) : json(route, { detail: 'SAML not configured' }, 400)
    }
    if (p.startsWith('/api/v1/observability/frontend')) return route.fulfill({ status: 204 })
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) { state.blocked.push(`${method} ${p}`); return json(route, { detail: '测试阻止了未知写操作' }, 409) }
    return route.fallback()
  })
  return state
}
export async function openMembers(page: Page) {
  await page.goto('/settings/rbac', { waitUntil: 'domcontentloaded' })
  await expect(page.locator('[data-members-workspace]')).toBeVisible({ timeout: 60000 })
  await expect(page.getByRole('button', { name: '刷新成员', exact: true })).toBeEnabled({ timeout: 30000 })
}
export async function reloadMembers(page: Page) {
  await page.reload({ waitUntil: 'domcontentloaded' })
  await expect(page.locator('[data-members-workspace]')).toBeVisible({ timeout: 60000 })
  await expect(page.getByRole('button', { name: '刷新成员', exact: true })).toBeEnabled({ timeout: 30000 })
}
export async function memberShot(page: Page, name: string) { fs.mkdirSync(memberEvidence, { recursive: true }); await page.screenshot({ path: `${memberEvidence}/${name}.png`, animations: 'disabled' }) }
export async function pickRole(page: Page, name: string, role: string) {
  await page.getByRole('combobox', { name: `角色 ${name}`, exact: true }).click()
  await page.getByRole('option', { name: role, exact: true }).click()
}
