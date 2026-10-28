import fs from 'node:fs'
import path from 'node:path'
import { expect, type Page, type Route } from '@playwright/test'
import type { IngestionPolicy } from '../types'
import { installCommonApiMocks } from './enterprise-quality-telemetry.helpers'

export const policyDatasetId = '4bf314df-47e7-4594-b611-666666666666'
export const policyRoute = `/datasets/${policyDatasetId}/ingestion`
export const policyEvidence = path.resolve(__dirname, '../../artifacts/rebrand/dataset-ingestion-policy-v1/tests')
export function policyFixtureData(): IngestionPolicy {
  return { version: '1', rules: [
    { id: 'pdf-text', name: 'PDF 文本文档', enabled: true, match: { extensions: ['.pdf'], filename_regex: null }, preprocess: { enabled: false, steps: [] }, parser_backend: 'auto', chunk_strategy: 'pdf_layout', governance_profile_ref: 'builtin:pdf_text', pipeline_patch: {} },
    { id: 'web-html', name: '网页正文', enabled: true, match: { extensions: ['.html', '.htm'], filename_regex: '(?i)article' }, preprocess: { enabled: true, steps: [{ id: 'html.strip_scripts_styles', params: {} }, { id: 'text.collapse_blank_lines', params: { max_blank_lines: 2 } }] }, parser_backend: 'auto', chunk_strategy: null, governance_profile_ref: 'builtin:html_web', pipeline_patch: {} },
    { id: 'office', name: 'Office 文件', enabled: true, match: { extensions: ['.docx', '.pptx', '.xlsx'], filename_regex: null }, preprocess: { enabled: false, steps: [] }, parser_backend: 'markitdown', chunk_strategy: null, governance_profile_ref: 'builtin:kb_default', pipeline_patch: {} },
    { id: 'plain-text', name: 'Markdown 与纯文本', enabled: false, match: { extensions: ['.md', '.txt'], filename_regex: null }, preprocess: { enabled: true, steps: [{ id: 'text.normalize_newlines', params: {} }] }, parser_backend: 'auto', chunk_strategy: 'default', governance_profile_ref: 'builtin:kb_default', pipeline_patch: { governance_enabled: true } },
  ] }
}
async function json(route: Route, value: unknown, status = 200) { await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) }) }
export async function datasetPolicyFixture(page: Page, theme: 'light' | 'dark' = 'light') {
  await page.setViewportSize({ width: 1600, height: 1000 }); await installCommonApiMocks(page, { uploaded: false })
  await page.addInitScript(mode => { localStorage.setItem('theme', mode); localStorage.setItem('mimirq.surfaceTheme', 'ocean'); localStorage.setItem('mimirq.themeColor', '#20262e') }, theme)
  const state = { policy: policyFixtureData(), failRead: false, failDataset: false, failStats: false, failProfiles: false, failSave: '', failPreview: '', failReadAfterWrite: false, gate: null as Promise<void> | null, reads: 0, writes: [] as IngestionPolicy[], previews: [] as string[], blocked: [] as string[], errors: [] as string[] }
  page.on('pageerror', error => state.errors.push(error.message))
  await page.route('**/api/v1/**', async route => {
    const req = route.request(), url = new URL(req.url()), p = url.pathname.replace(/\/$/, ''), method = req.method()
    if (p === '/api/v1/rbac/me') return json(route, { tenant_id: 'tenant-fixture', account_id: 'fixture-user', role: 'admin', is_active: true, is_current: true, permissions: ['settings.read', 'settings.write', 'observability.read', 'usage.read', 'audit.read'] })
    if (p === `/api/v1/datasets/${policyDatasetId}` && method === 'GET') return state.failDataset ? json(route, { detail: '数据集暂不可用' }, 503) : json(route, { id: policyDatasetId, tenant_id: 'tenant-fixture', name: '产品知识库', description: '产品使用与维护资料', permission: 'all_team_members', owner_id: 'fixture-user', default_parser_backend: 'auto', default_chunk_strategy: 'default' })
    if (p === `/api/v1/datasets/${policyDatasetId}/ingestion-policy`) {
      if (method === 'GET') { state.reads++; return state.failRead ? json(route, { detail: '策略读取暂不可用' }, 503) : json(route, state.policy) }
      if (method === 'PUT') {
        const body = req.postDataJSON() as IngestionPolicy; state.writes.push(body)
        if (state.gate) await state.gate
        if (state.failSave) return json(route, { detail: state.failSave }, 422)
        state.policy = structuredClone(body)
        if (state.failReadAfterWrite) state.failRead = true
        return json(route, state.policy)
      }
    }
    if (p === `/api/v1/datasets/${policyDatasetId}/ingestion/stats`) return state.failStats ? json(route, { detail: '入库概览暂不可用' }, 503) : json(route, { dataset_id: policyDatasetId, total_documents: 128, total_chunks: 1240, total_size: 1835008, total_characters: 680321, by_status: { completed: 124, failed: 4 }, last_processed_at: '2026-10-26T14:30:00+08:00' })
    if (p === '/api/v1/pipeline/capabilities') return json(route, { pdf_backends: [{ name: 'auto', available: true }, { name: 'markitdown', available: true }], chunk_strategies: [{ name: 'default', available: true }, { name: 'pdf_layout', available: true }], allowed_extensions: ['.pdf', '.html', '.txt', '.md'] })
    if (p === '/api/v1/pipeline/governance-profiles') return state.failProfiles ? json(route, { detail: '治理预设暂不可用' }, 503) : json(route, { total: 3, items: [{ key: 'builtin:kb_default', name: '通用知识库', is_system: true }, { key: 'builtin:pdf_text', name: 'PDF 文本', is_system: true }, { key: 'builtin:html_web', name: '网页正文', is_system: true }] })
    if (p === '/api/v1/pipeline/ingestion-preview' && method === 'POST') {
      state.previews.push(req.postDataBuffer()!.toString('utf8'))
      if (state.gate) await state.gate
      if (state.failPreview) return json(route, { detail: state.failPreview }, 503)
      const filename = state.previews.at(-1)!.match(/filename="([^"]+)"/)![1]
      const extension = filename.slice(filename.lastIndexOf('.')).toLowerCase()
      const rule = state.policy.rules!.find(item => item.enabled && (!item.match?.extensions?.length || item.match.extensions.includes(extension)))
      return json(route, { rule: { matched: Boolean(rule), rule_id: rule?.id, rule_name: rule?.name, parser_backend: rule?.parser_backend || 'auto', chunk_strategy: rule?.chunk_strategy || '', governance_profile_ref: rule?.governance_profile_ref || null }, preprocess: { changed: true }, parse: { markdown: '# 产品手册\n\n导航内容\n\n安装与使用说明。', parser_backend: 'auto' }, clean: { markdown: '# 产品手册\n\n安装与使用说明。', diff_unified: '--- 解析后\n+++ 治理后\n@@ -1,5 +1,3 @@\n # 产品手册\n-导航内容\n 安装与使用说明。', issues: [{ code: 'boilerplate_removed', severity: 'info', message: '已清理导航内容', count: 1 }] } })
    }
    if (p.startsWith('/api/v1/observability/frontend')) return route.fulfill({ status: 204 })
    if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) { state.blocked.push(`${method} ${p}`); return json(route, { detail: '阻止未配置的测试写入' }, 409) }
    return route.fallback()
  })
  return state
}
export async function openPolicy(page: Page, legacy = false) {
  await page.goto(policyRoute, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: legacy ? '入库策略工作台' : '入库策略', exact: true })).toBeVisible({ timeout: 60000 })
  await expect(page.getByText('产品知识库', { exact: true }).first()).toBeVisible({ timeout: 30000 })
}
export async function policyShot(page: Page, name: string) { fs.mkdirSync(policyEvidence, { recursive: true }); await page.screenshot({ path: `${policyEvidence}/${name}.png`, animations: 'disabled' }) }
