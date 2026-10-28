import type { Page } from '@playwright/test'
import { remainingFixture } from './remaining-pages.helpers'
import { policyDatasetId } from './dataset-policy.helpers'

export const secondDataset = '22222222-2222-4222-8222-222222222222'
export async function diagnosticsFixture(page: Page, theme: 'light' | 'dark' = 'light') {
  await remainingFixture(page, theme)
  const state = { fail: true, gate: null as Promise<void> | null, requests: [] as Record<string, unknown>[] }
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()), p = url.pathname.replace(/\/$/, '')
    if (p === '/api/v1/datasets') return route.fulfill({ json: { total: 2, items: [{ id: policyDatasetId, name: '产品知识库' }, { id: secondDataset, name: '另一数据集' }] } })
    if (p === '/api/v1/evaluations/kg/search/diagnostics') {
      state.requests.push(route.request().postDataJSON())
      if (state.gate) await state.gate
      return route.fulfill({ status: state.fail ? 503 : 200, json: state.fail ? { detail: '诊断服务暂不可用' } : { summary: { baseline_hit_rate: 0.75, baseline_mrr: 0.6, baseline_recall: 0.8, hardcases_generated: 1 }, items: [{ case_id: 'case-1', question: '维护周期是多久？', baseline: { metrics: { hit_at_k: false, mrr: 0, recall: 0 } } }] } })
    }
    if (p === '/api/v1/evaluations/kg/search/diagnostics/runs') return route.fulfill({ json: { total: 0, items: [] } })
    if (p === '/api/v1/evaluations/kg/quality/report') return route.fulfill({ json: { entities: 43, relations: 82, isolated_entities: 2 } })
    return route.fallback()
  })
  return state
}
