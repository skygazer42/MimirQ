import type { Page } from '@playwright/test'
import { remainingFixture } from './remaining-pages.helpers'
import { policyDatasetId } from './dataset-policy.helpers'

export async function ablationsFixture(page: Page, theme: 'light' | 'dark' = 'light') {
  await remainingFixture(page, theme)
  await page.route('**/api/v1/**', async route => {
    if (/^\/api\/v1\/datasets\/?$/.test(new URL(route.request().url()).pathname)) return route.fulfill({ json: { total: 1, items: [{ id: policyDatasetId, tenant_id: 'test-tenant', name: '产品知识库', permission: 'all_team_members' }] } })
    return route.fallback()
  })
  const runs = ['candidate-run', 'baseline-run'].map((id, index) => ({ id, dataset_id: policyDatasetId, tenant_id: 'test-tenant', status: 'completed', metrics: ['retrieval_mrr'], params: { top_k: index ? 10 : 20 }, summary: { retrieval_mrr: index ? 0.6 : 0.75 }, created_at: `2026-10-27T0${index + 8}:00:00Z` }))
  const olderRun = { ...runs[0], id: 'archived-best-run', params: { top_k: 7 }, summary: { retrieval_mrr: 0.99 }, created_at: '2025-01-01T08:00:00Z' }
  const state = { failSave: true, includeOlder: false, detailGate: null as Promise<void> | null, writes: [] as Record<string, unknown>[], detailReads: [] as string[], diffs: [] as Array<{ target: string; base: string | null }>, runs, olderRun }
  await page.route('**/api/v1/evaluations/ragas/regression/**', async route => {
    const url = new URL(route.request().url()), p = url.pathname
    if (p.endsWith('/cases')) return route.fulfill({ json: { total: 1, items: [] } })
    if (p.endsWith('/runs') && route.request().method() === 'POST') {
      const payload = route.request().postDataJSON(); state.writes.push(payload)
      if (state.failSave) return route.fulfill({ status: 503, json: { detail: '实验提交暂不可用' } })
      const run = { ...runs[0], id: 'new-verification-run', status: 'pending', params: payload }
      runs.unshift(run)
      return route.fulfill({ json: run })
    }
    if (p.endsWith('/leaderboard')) return route.fulfill({ json: { items: [...(state.includeOlder ? [olderRun] : []), ...runs].map(run => ({ run_id: run.id, status: run.status, metric_key: 'retrieval_mrr', metric_value: run.summary.retrieval_mrr, retrieval_config_hash: 'config-' + run.id })) } })
    if (p.endsWith('/runs/archived-best-run')) {
      state.detailReads.push('archived-best-run')
      if (state.detailGate) await state.detailGate
      return route.fulfill({ json: { run: olderRun, items: [] } })
    }
    if (p.endsWith('/runs')) return route.fulfill({ json: { total: runs.length, items: runs } })
    if (p.endsWith('/diff')) {
      state.diffs.push({ target: p.split('/').at(-2)!, base: url.searchParams.get('base_run_id') })
      return route.fulfill({ json: { base_run_id: 'baseline-run', target_run_id: 'candidate-run', generated_at: '2026-10-27T10:00:00Z', base_params: { top_k: 10 }, target_params: { top_k: 20 }, metric_diffs: [{ key: 'retrieval_mrr', before: 0.6, after: 0.75, delta: 0.15 }], diff_score: { version: '1', used_metric_keys: ['retrieval_mrr'], weights: { retrieval_mrr: 1 }, base_score: 0.6, target_score: 0.75, delta: 0.15, base_metrics: { retrieval_mrr: 0.6 }, target_metrics: { retrieval_mrr: 0.75 } }, slice_diffs: {}, case_diffs: [], significance: [], significance_summary: {} } })
    }
    return route.fallback()
  })
  return state
}
