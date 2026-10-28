import fs from 'node:fs'
import path from 'node:path'
import { expect, type Page, type Route } from '@playwright/test'
import { TENANT_PERMISSIONS } from '../lib/tenant-permissions'
import type { ChatCostUsageSummary, ChatTokenQuotaStatus, ChatTokenUsageSummary, TenantQuotaSummary } from '../types'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

export const usageEvidence = path.resolve(__dirname, '../../artifacts/rebrand/usage-overview-v1/tests')
fs.mkdirSync(usageEvidence, { recursive: true })
type DesignRow = { id: string; name: string; messages: number; assistant_tokens: number; llm_prompt_tokens: number; llm_completion_tokens: number; llm_total_tokens: number; embedding_tokens: number; embedding_chars: number; retrieval_sec: number; rerank_sec: number; visibility: string }
const design = JSON.parse(fs.readFileSync(path.resolve(__dirname, '../public/brand/explorations/usage-layouts-v1/facts.json'), 'utf8')) as { rows: DesignRow[] }
const windowEnd = '2026-10-25T10:00:00Z'
const windowStart = (days: number) => new Date(new Date(windowEnd).getTime() - days * 86_400_000).toISOString()
const sum = (rows: DesignRow[], key: keyof DesignRow) => rows.reduce((total, row) => total + Number(row[key]), 0)

async function json(route: Route, value: unknown, status = 200) {
  await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) })
}

export async function usageFixture(page: Page, options: { dark?: boolean; authenticated?: boolean; allowed?: boolean } = {}) {
  await page.setViewportSize({ width: 1600, height: 1000 })
  await installCommonApiMocks(page, { uploaded: false })
  await page.addInitScript(({ dark, authenticated }) => {
    localStorage.setItem('theme', dark ? 'dark' : 'light')
    localStorage.setItem('mimirq.surfaceTheme', 'ocean')
    localStorage.setItem('mimirq.themeColor', '#20262e')
    if (authenticated) sessionStorage.setItem('mimirq_access_token', 'isolated-usage-fixture')
    Object.defineProperty(navigator, 'clipboard', { configurable: true, value: { writeText: async (text: string) => { (window as Window & { usageCopied?: string }).usageCopied = text } } })
  }, { dark: options.dark ?? false, authenticated: options.authenticated ?? false })
  const state = {
    rows: structuredClone(design.rows), fail: new Set<string>(), empty: false,
    hold14: null as Promise<void> | null,
    requests: [] as Array<{ path: string; days: number; method: string }>, errors: [] as string[],
    chat: { enabled: true, mode: 'block', used: 42560, limit: 50000, remaining: 7440, exceeded: false, window_hours: 24, window_start: windowStart(1), window_end: windowEnd } as ChatTokenQuotaStatus,
    tenant: {
      documents: { enabled: true, used: 2432, limit: 5000, remaining: 2568, exceeded: false },
      storage: { enabled: true, used_bytes: 8375186227, limit_bytes: 21474836480, remaining_bytes: 13099650253, exceeded: false },
      embedding_chars: { enabled: true, mode: 'block', used_chars: 1680000, limit_chars: 2000000, remaining_chars: 320000, exceeded: false, window_hours: 24, window_start: windowStart(1), window_end: windowEnd },
      qps: { enabled: true, mode: 'block', rps: 10, burst: 20, scopes: ['chat', 'retrieval'] },
    } as TenantQuotaSummary,
  }
  page.on('pageerror', error => state.errors.push(error.message))
  const rowsFor = (days: number) => (state.empty ? [] : state.rows).map(row => {
    const copy = { ...row }
    for (const key of ['messages', 'assistant_tokens', 'llm_prompt_tokens', 'llm_completion_tokens', 'llm_total_tokens', 'embedding_tokens', 'embedding_chars'] as const) copy[key] = Math.round(row[key] * days / 7)
    return copy
  })
  const summaryFor = (days: number): ChatTokenUsageSummary => {
    const rows = rowsFor(days)
    return { window_start: windowStart(days), window_end: windowEnd, total_assistant_messages: sum(rows, 'messages'), total_assistant_tokens: sum(rows, 'assistant_tokens'), by_dataset: rows.map(r => ({ dataset_id: r.id || null, assistant_messages: r.messages, assistant_tokens: r.assistant_tokens })) }
  }
  const costFor = (days: number): ChatCostUsageSummary => {
    const rows = rowsFor(days)
    return { window_start: windowStart(days), window_end: windowEnd, total_assistant_messages: sum(rows, 'messages'),
      total_llm_prompt_tokens: sum(rows, 'llm_prompt_tokens'), total_llm_completion_tokens: sum(rows, 'llm_completion_tokens'), total_llm_total_tokens: sum(rows, 'llm_total_tokens'), total_embedding_query_tokens: sum(rows, 'embedding_tokens'), total_embedding_query_chars: sum(rows, 'embedding_chars'), total_retrieval_elapsed_sec: sum(rows, 'retrieval_sec'), total_rerank_elapsed_sec: sum(rows, 'rerank_sec'),
      by_dataset: rows.map(r => ({ dataset_id: r.id || null, assistant_messages: r.messages, llm_prompt_tokens: r.llm_prompt_tokens, llm_completion_tokens: r.llm_completion_tokens, llm_total_tokens: r.llm_total_tokens, embedding_query_tokens: r.embedding_tokens, embedding_query_chars: r.embedding_chars, retrieval_elapsed_sec_sum: r.retrieval_sec, rerank_elapsed_sec_sum: r.rerank_sec })) }
  }
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()), p = url.pathname, method = route.request().method(), days = Number(url.searchParams.get('window_days') || 7)
    if (p === '/api/v1/rbac/me') return json(route, { tenant_id: 'fixture', account_id: 'fixture', role: options.allowed === false ? 'viewer' : 'owner', permissions: options.allowed === false ? [] : Object.values(TENANT_PERMISSIONS), is_active: true, is_current: true })
    if (p === '/api/v1/auth/me') return json(route, { id: 'fixture', username: '设计验收', account_id: 'fixture', tenant_id: 'fixture', role: options.allowed === false ? 'viewer' : 'owner' })
    if (p === '/api/v1/observability/frontend-vitals' || p === '/api/v1/observability/frontend-traces') return route.fulfill({ status: 204 })
    const source = p.endsWith('/chat/tokens/summary') ? 'summary' : p.endsWith('/chat/cost/summary') ? 'cost' : p.endsWith('/chat/tokens/quota') ? 'chat' : p.endsWith('/tenant/quotas') ? 'tenant' : /^\/api\/v1\/datasets\/?$/.test(p) ? 'labels' : null
    if (source) {
      state.requests.push({ path: p, days, method })
      if (days === 14 && ['summary', 'cost'].includes(source) && state.hold14) await state.hold14
      if (state.fail.has(source)) return json(route, { detail: `${source} fixture unavailable` }, 503)
      if (source === 'summary') return json(route, summaryFor(days))
      if (source === 'cost') return json(route, costFor(days))
      if (source === 'chat') return json(route, state.chat)
      if (source === 'tenant') return json(route, state.tenant)
      const visible = state.rows.filter(r => r.visibility === 'visible').map(r => ({ id: r.id, name: r.name }))
      return json(route, { total: visible.length, items: visible })
    }
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) return json(route, { detail: 'unhandled fixture write blocked' }, 409)
    return route.fallback()
  })
  return { state, summaryFor }
}

export async function openUsage(page: Page) {
  await page.goto('/usage', { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: '用量／配额', exact: true })).toBeVisible({ timeout: 60_000 })
}

export async function waitUsage(page: Page) {
  await expect(page.getByRole('button', { name: '刷新用量', exact: true })).toBeEnabled({ timeout: 30_000 })
}
