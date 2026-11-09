import fs from 'node:fs'
import path from 'node:path'
import { gzipSync } from 'node:zlib'
import { expect, type Page, type Route } from '@playwright/test'
import type { AuditLogItem } from '../types'
import { TENANT_PERMISSIONS } from '../lib/tenant-permissions'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

export const auditEvidence = path.resolve(__dirname, '../../artifacts/rebrand/audit-table-v1/tests')
fs.mkdirSync(auditEvidence, { recursive: true })
const facts = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../public/brand/explorations/audit-layouts-v1/facts.json'), 'utf8')) as { rows: AuditLogItem[] }
export const seedAuditRows = facts.rows.map(row => ({ id: row.id, tenant_id: row.tenant_id, actor_id: row.actor_id, action: row.action, resource_type: row.resource_type, resource_id: row.resource_id, request_id: row.request_id, ip: row.ip, user_agent: row.user_agent, details: row.details, created_at: row.created_at }))

async function json(route: Route, body: unknown, status = 200) { await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(body) }) }

export async function auditFixture(page: Page, config: { authenticated?: boolean; allowed?: boolean; manage?: boolean; dark?: boolean; count?: number } = {}) {
  await page.setViewportSize({ width: 1600, height: 1000 }); await installCommonApiMocks(page, { uploaded: false })
  await page.addInitScript(({ authenticated, dark }) => {
    localStorage.setItem('theme', dark ? 'dark' : 'light'); localStorage.setItem('mimirq.surfaceTheme', 'ocean'); localStorage.setItem('mimirq.themeColor', '#20262e')
    if (authenticated) sessionStorage.setItem('mimirq_access_token', 'audit-test-only')
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (text: string) => { (window as Window & { auditCopied?: string }).auditCopied = text } } })
  }, { authenticated: config.authenticated ?? false, dark: config.dark ?? false })
  const count = config.count ?? 47
  const initial = Array.from({ length: count }, (_, i) => i < seedAuditRows.length ? structuredClone(seedAuditRows[i]) : { ...structuredClone(seedAuditRows[0]), id: `7c6a2e40-0f71-4f62-9b74-${String(1001 + i).padStart(12, '0')}`, action: 'settings.update', resource_type: 'settings', resource_id: 'env', request_id: `req-audit-${1001 + i}`, created_at: new Date(Date.UTC(2026, 9, 23, 23) - i * 1000).toISOString(), details: { changed: true } })
  const state = { rows: initial, fail: new Set<string>(), hold: null as Promise<void> | null, holdAction: '', requests: [] as Array<{ path: string; method: string; params: Record<string, string>; body: unknown }>, errors: [] as string[], console: [] as string[], exportCompressed: false }
  page.on('pageerror', error => state.errors.push(error.message))
  page.on('console', entry => { if (entry.type() === 'error') state.console.push(entry.text()) })
  function matched(params: URLSearchParams) {
    return state.rows.filter(row => ['action', 'actor_id', 'resource_type', 'resource_id', 'request_id'].every(key => !params.get(key) || row[key as keyof AuditLogItem] === params.get(key)) && (!params.get('since') || new Date(row.created_at) >= new Date(params.get('since')!)) && (!params.get('until') || new Date(row.created_at) <= new Date(params.get('until')!)))
  }
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), url = new URL(request.url()), p = url.pathname, method = request.method(), q = url.searchParams
    if (p === '/api/v1/rbac/me') return json(route, { tenant_id: 'fixture', account_id: 'fixture', role: config.manage === false ? 'auditor' : 'owner', permissions: config.allowed === false ? [] : Object.values(TENANT_PERMISSIONS).filter(permission => config.manage !== false || permission !== 'audit.manage'), is_active: true, is_current: true })
    if (p === '/api/v1/auth/me') return json(route, { id: 'fixture', username: '验收账号', account_id: 'fixture', tenant_id: 'fixture', role: config.manage === false ? 'auditor' : 'owner' })
    if (p.startsWith('/api/v1/observability/frontend-')) return route.fulfill({ status: 204 })
    if (p.startsWith('/api/v1/audit/')) {
      let body: unknown = null
      try { body = request.postDataJSON() } catch { /* GET and empty POST bodies. */ }
      state.requests.push({ path: p, method, params: Object.fromEntries(q), body })
      if (p === '/api/v1/audit/logs' && method === 'GET') {
        if (state.hold && q.get('action') === state.holdAction) await state.hold
        if (state.fail.has(Number(q.get('limit')) === 200 ? 'options' : 'list')) return json(route, { detail: '审计服务暂不可用' }, 503)
        const all = matched(q), skip = Number(q.get('skip') || 0), limit = Number(q.get('limit') || 20)
        return json(route, { total: all.length, items: all.slice(skip, skip + limit) })
      }
      if (p === '/api/v1/audit/logs/export') {
        if (state.fail.has('export')) return json(route, { detail: '导出服务暂不可用' }, 503)
        const text = matched(q).map(row => JSON.stringify(row)).join('\n') + '\n'
        return route.fulfill({ status: 200, contentType: 'application/x-ndjson', body: state.exportCompressed ? gzipSync(text) : Buffer.from(text) })
      }
      if (p === '/api/v1/audit/logs/purge' && method === 'POST') {
        if (state.fail.has('purge')) return json(route, { detail: '清理服务暂不可用' }, 503)
        if (state.hold) await state.hold
        const dryRun = q.get('dry_run') !== 'false', filtered = q.get('purge_scope') === 'filtered', max = Number(q.get('max_delete') || 1000)
        const list = (filtered ? matched(q) : []).slice(0, max), eligible = list.length
        if (!dryRun) { const ids = new Set(list.map(row => row.id)); state.rows = state.rows.filter(row => !ids.has(row.id)) }
        return json(route, { dry_run: dryRun, scope: filtered ? 'filtered' : 'retention', retention_days: Number(q.get('retention_days') || 90), cutoff: '2026-07-27T12:00:00Z', max_delete: max, eligible, deleted: dryRun ? 0 : eligible, filters: Object.fromEntries([...q].filter(([key]) => ['action', 'actor_id', 'resource_type', 'resource_id', 'request_id', 'since', 'until'].includes(key))) })
      }
      if ((method === 'DELETE' && p.startsWith('/api/v1/audit/logs/')) || (p === '/api/v1/audit/logs/bulk-delete' && method === 'POST')) {
        if (state.fail.has('delete')) return json(route, { detail: '删除服务暂不可用' }, 503)
        const ids = method === 'DELETE' ? [p.split('/').at(-1)!] : (body as { ids: string[] }).ids
        const found = new Set(state.rows.filter(row => ids.includes(row.id)).map(row => row.id))
        state.rows = state.rows.filter(row => !found.has(row.id))
        return json(route, { requested: ids.length, deleted: found.size, missing: ids.length - found.size, ids })
      }
      return json(route, { detail: 'Unrecognized isolated audit endpoint' }, 409)
    }
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) return json(route, { detail: 'Unrecognized write blocked' }, 409)
    return route.fallback()
  })
  return state
}

export async function openAudit(page: Page, suffix = '') { await page.goto(`/audit${suffix}`, { waitUntil: 'domcontentloaded' }); await expect(page.getByRole('heading', { name: '审计日志', exact: true })).toBeVisible({ timeout: 60_000 }) }
export async function waitAudit(page: Page) { await expect(page.getByRole('button', { name: '刷新审计日志', exact: true })).toBeEnabled({ timeout: 30_000 }) }
export async function exactFilter(page: Page, key: string, value: string) { await page.getByRole('button', { name: '更多审计筛选', exact: true }).click(); const d = page.getByRole('dialog', { name: '精确筛选', exact: true }); await d.getByLabel(key, { exact: true }).fill(value); await d.getByRole('button', { name: '应用筛选', exact: true }).click(); await waitAudit(page) }
