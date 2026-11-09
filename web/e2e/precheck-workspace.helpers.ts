import fs from 'node:fs'
import path from 'node:path'
import { expect, type Page, type Route } from '@playwright/test'
import type { DatasetPrecheckScanRunOut, DatasetPrecheckSummary, DatasetPrecheckScanRunCreateRequest } from '../types'
import { datasetPolicyFixture, policyDatasetId, policyFixtureData } from './dataset-policy.helpers'

export const precheckRoute = `/datasets/${policyDatasetId}/precheck`
export const precheckEvidence = path.resolve(__dirname, '../../artifacts/rebrand/dataset-precheck-v1/tests')
export const runOne = 'b7935651-349c-447f-bc13-000000000001', runTwo = 'b7935651-349c-447f-bc13-000000000002'
export function precheckSummary(id = runOne, count = 128): DatasetPrecheckSummary {
  const ratio = count / 128
  return { dataset_id: policyDatasetId, scan_run_id: id, generated_at: '2026-10-26T16:30:00+08:00', total_files: count, total_size_bytes: 1835008 * ratio, reused_files: 0, by_file_type: { pdf: 80 * ratio, docx: 32 * ratio, md: 16 * ratio }, file_size_histogram: [{ label: '< 1 MB', count: count / 2 }, { label: '1–10 MB', count: count / 4 }, { label: '> 10 MB', count: count / 4 }], length_histogram: [{ label: '< 1k', count: count / 4 }, { label: '1k–5k', count: count / 2 }, { label: '> 5k', count: count / 4 }], length_percentiles: { p25: 800, p50: 2400, p75: 5200, p90: 8800, p99: 12000 }, pdf_scan: { scanned: 12 * ratio, not_scanned: 64 * ratio, unknown: 4 * ratio }, findings: [{ key: 'pdf_scanned', label: '扫描版 PDF', severity: 'warning', count: 12 * ratio, description: '需要 OCR 识别的 PDF 文件' }, { key: 'empty_text', label: '正文过短', severity: 'warning', count: Math.ceil(3 * ratio), description: '请确认文件是否包含有效正文' }], pii_hits_total: { email: 2 * ratio }, secrets_hits_total: {}, embedding_advisories: [] }
}
export function precheckRuns(): DatasetPrecheckScanRunOut[] {
  return [runOne, runTwo].map((id, i) => ({ id, tenant_id: 'tenant-fixture', dataset_id: policyDatasetId, requested_by: 'fixture-user', kind: 'precheck', status: 'completed', progress: 100, config: { root_path: '/uploads/product-notes' }, summary: { total_files: i ? 64 : 128 }, artifacts: {}, error_message: null, started_at: '2026-10-26T16:20:00+08:00', finished_at: '2026-10-26T16:30:00+08:00', created_at: i ? '2026-10-25T10:20:00+08:00' : '2026-10-26T16:20:00+08:00', updated_at: '2026-10-26T16:30:00+08:00' }))
}
async function json(route: Route, value: unknown, status = 200) { await route.fulfill({ status, contentType: 'application/json', body: JSON.stringify(value) }) }
export async function precheckFixture(page: Page, theme: 'light' | 'dark' = 'light') {
  const base = await datasetPolicyFixture(page, theme)
  const state = { base, runs: precheckRuns(), failRead: false, failSummary: false, failFinding: false, failSamples: false, failStart: '', failCancel: '', failApply: '', running: false, startGate: null as Promise<void> | null, summaryGates: {} as Partial<Record<string, Promise<void>>>, starts: [] as DatasetPrecheckScanRunCreateRequest[], cancels: [] as string[], applies: [] as boolean[], reads: [] as string[] }
  const prefix = `/api/v1/datasets/${policyDatasetId}/precheck/scan-runs`
  await page.route('**/api/v1/**', async route => {
    const request = route.request(), url = new URL(request.url()), p = url.pathname.replace(/\/$/, ''), method = request.method()
    if (!p.startsWith(prefix)) return route.fallback()
    if (p === prefix) {
      if (method === 'GET') return state.failRead ? json(route, { detail: '预检记录暂不可用' }, 503) : json(route, { total: state.runs.length, items: state.runs })
      if (method === 'POST') {
        const config = request.postDataJSON() as DatasetPrecheckScanRunCreateRequest; state.starts.push(config)
        if (state.startGate) await state.startGate
        if (state.failStart) return json(route, { detail: state.failStart }, 503)
        const run = { ...precheckRuns()[0], id: `b7935651-349c-447f-bc13-${String(state.runs.length + 1).padStart(12, '0')}`, config: { ...config }, status: state.running ? 'running' : 'completed', progress: state.running ? 25 : 100 }
        state.runs.unshift(run); return json(route, run, 201)
      }
    }
    const rest = p.slice(prefix.length + 1), id = rest.split('/')[0], run = state.runs.find(item => item.id === id)
    if (!run) return json(route, { detail: '未找到此预检记录' }, 404)
    state.reads.push(rest)
    if (rest === id && method === 'GET') return json(route, run)
    if (p.endsWith('/summary')) {
      const summary = precheckSummary(id, id === runTwo ? 64 : 128)
      await state.summaryGates[id]
      return state.failSummary ? json(route, { detail: '统计报告暂不可用' }, 503) : json(route, summary)
    }
    if (p.endsWith('/cancel') && method === 'POST') { state.cancels.push(id); if (state.failCancel) return json(route, { detail: state.failCancel }, 503); run.status = 'cancelled'; return json(route, run) }
    if (p.endsWith('/events')) return route.fulfill({ status: 200, contentType: 'text/event-stream', body: '' })
    if (p.endsWith('/samples')) return state.failSamples ? json(route, { detail: '样本暂不可用' }, 503) : json(route, { requested: 60, strata_count: 1, representative: [{ name: 'product-guide.pdf', file_type: 'pdf', file_size: 4096, text_characters: 2400, estimated_text: false, pii_hits: {}, secrets_hits: {}, findings: [] }], needs_review: {}, top_large_files: [], top_long_text: [] })
    if (p.includes('/findings/')) return state.failFinding ? json(route, { detail: '问题清单暂不可用' }, 503) : json(route, { total: 1, items: [{ name: 'product-guide.pdf', file_type: 'pdf', file_size: 4096, text_characters: 2400, estimated_text: false, pii_hits: {}, secrets_hits: {}, pdf_scanned: true, findings: ['pdf_scanned'] }] })
    if (p.endsWith('/near-dups')) return json(route, { clusters_returned: 1, pairs_returned: 1, threshold: 5, max_pairs: 500, pairs: [{ a: 'product-guide.pdf', b: 'guide-v2.pdf', distance: 2 }], clusters: [{ id: 'one', members: ['product-guide.pdf', 'guide-v2.pdf'] }] })
    if (p.endsWith('/diff')) return json(route, { total_files: { before: 64, after: 128, delta: 64 }, pdf_scanned: { before: 6, after: 12, delta: 6 }, pdf_unknown: { before: 2, after: 4, delta: 2 }, findings: [{ key: 'pdf_scanned', before: 6, after: 12, delta: 6 }] })
    if (p.endsWith('/suggest-ingestion-policy')) return json(route, { policy: policyFixtureData(), notes: [], manual_review: [] })
    if (p.endsWith('/apply-ingestion-policy') && method === 'POST') { state.applies.push(url.searchParams.get('replace') === 'true'); return state.failApply ? json(route, { detail: state.failApply }, 503) : json(route, { replaced: state.applies.at(-1), rule_count: 4 }) }
    if (p.endsWith('/export-html')) return route.fulfill({ status: 200, contentType: 'text/html', body: '<!doctype html><title>fixture report</title><p>128 files</p>' })
    if (p.endsWith('/export')) return json(route, precheckSummary(id))
    return json(route, { detail: '未配置的预检测试请求' }, 409)
  })
  return state
}
export async function openPrecheck(page: Page, title = '文档预检') {
  await page.goto(precheckRoute, { waitUntil: 'domcontentloaded' })
  await expect(page.getByRole('heading', { name: title, exact: true })).toBeVisible({ timeout: 60000 })
  await expect(page.getByText('产品知识库', { exact: true }).first()).toBeVisible({ timeout: 30000 })
}
export async function precheckShot(page: Page, name: string) {
  fs.mkdirSync(precheckEvidence, { recursive: true })
  await page.screenshot({ path: path.join(precheckEvidence, `${name}.png`), animations: 'disabled' })
  const html = (await page.content()).replace(/<script\b[^>]*>[\s\S]*?<\/script>/gi, '').replace(/\b(href|src)="\/(?!\/)/g, '$1="http://127.0.0.1:3000/')
  fs.writeFileSync(path.join(precheckEvidence, `${name}.html`), html)
}
