import type { Page } from '@playwright/test'
import type { RegressionCase } from '../lib/regression-case-schema'
import type { RegressionRun } from '../lib/regression-run-schema'
import { remainingFixture } from './remaining-pages.helpers'
import { policyDatasetId } from './dataset-policy.helpers'

export async function ablationsFixture(page: Page, theme: 'light' | 'dark' = 'light') {
  await remainingFixture(page, theme)
  await page.route('**/api/v1/**', async (route) => {
    if (/^\/api\/v1\/datasets\/?$/.test(new URL(route.request().url()).pathname))
      return route.fulfill({
        json: {
          total: 1,
          items: [
            { id: policyDatasetId, tenant_id: 'test-tenant', name: '产品知识库', permission: 'all_team_members' },
          ],
        },
      })
    return route.fallback()
  })
  const runs: (RegressionRun & { summary: { retrieval_mrr?: number } })[] = ['candidate-run', 'baseline-run'].map(
    (id, index) => ({
      id,
      dataset_id: policyDatasetId,
      tenant_id: 'test-tenant',
      account_id: null,
      status: 'completed',
      metrics: ['retrieval_mrr'],
      params: { top_k: index ? 10 : 20 },
      summary: { retrieval_mrr: index ? 0.6 : 0.75 },
      error_message: null,
      created_at: `2026-10-27T0${index + 8}:00:00Z`,
      started_at: `2026-10-27T0${index + 8}:00:00Z`,
      finished_at: `2026-10-27T0${index + 8}:05:00Z`,
    }),
  )
  const sample: RegressionCase = {
    id: 'maintenance-case',
    tenant_id: 'test-tenant',
    dataset_id: policyDatasetId,
    document_ids: ['maintenance-doc'],
    question: '维护周期是多久？',
    expected_answer: '每月一次',
    reference_sources: [{ document_id: 'maintenance-doc', chunk_id: 'maintenance-chunk' }],
    tags: [],
    reasoning_hops: [],
    evidence_chain: [],
    extra: {},
    created_by: null,
    created_at: '2026-10-27T08:00:00Z',
    updated_at: '2026-10-27T08:00:00Z',
  }
  const olderRun = {
    ...runs[0],
    id: 'archived-best-run',
    params: { top_k: 7 },
    summary: { retrieval_mrr: 0.99 },
    created_at: '2025-01-01T08:00:00Z',
    started_at: '2025-01-01T08:00:00Z',
    finished_at: '2025-01-01T08:05:00Z',
  }
  const state = {
    failSave: true,
    includeOlder: false,
    detailGate: null as Promise<void> | null,
    writes: [] as Record<string, unknown>[],
    detailReads: [] as string[],
    diffs: [] as Array<{ target: string; base: string | null }>,
    runs,
    olderRun,
  }
  await page.route('**/api/v1/evaluations/ragas/regression/**', async (route) => {
    const url = new URL(route.request().url()),
      p = url.pathname
    if (p.endsWith('/cases')) return route.fulfill({ json: { total: 1, items: [sample] } })
    if (p.endsWith('/runs') && route.request().method() === 'POST') {
      const payload = route.request().postDataJSON()
      state.writes.push(payload)
      if (state.failSave) return route.fulfill({ status: 503, json: { detail: '实验提交暂不可用' } })
      const run = {
        ...runs[0],
        id: 'new-verification-run',
        status: 'pending',
        params: payload,
        summary: {},
        started_at: null,
        finished_at: null,
      }
      runs.unshift(run)
      return route.fulfill({ json: run })
    }
    if (p.endsWith('/leaderboard')) {
      const metricKey = url.searchParams.get('metric_key') ?? 'retrieval_mrr'
      return route.fulfill({
        json: {
          metric_key: metricKey,
          items: [...(state.includeOlder ? [olderRun] : []), ...runs].map((run) => ({
            run_id: run.id,
            status: run.status,
            metric_key: metricKey,
            metric_value: metricKey === 'retrieval_mrr' ? (run.summary.retrieval_mrr ?? null) : null,
            retrieval_config_hash: 'config-' + run.id,
          })),
        },
      })
    }
    if (p.endsWith('/runs/archived-best-run')) {
      state.detailReads.push('archived-best-run')
      if (state.detailGate) await state.detailGate
      return route.fulfill({ json: { run: olderRun, items: [] } })
    }
    if (p.endsWith('/runs')) return route.fulfill({ json: { total: runs.length, items: runs } })
    if (p.endsWith('/diff')) {
      const targetId = p.split('/').at(-2)!
      const baseId = url.searchParams.get('base_run_id')
      state.diffs.push({ target: targetId, base: baseId })
      const target = (targetId === olderRun.id ? olderRun : runs.find((run) => run.id === targetId))!
      const baseline = runs.find((run) => run.id === baseId)!
      const before = baseline.summary.retrieval_mrr ?? null
      const after = target.summary.retrieval_mrr ?? null
      const delta = before === null || after === null ? null : Number((after - before).toFixed(2))
      return route.fulfill({
        json: {
          base_run_id: baseline.id,
          target_run_id: target.id,
          generated_at: '2026-10-27T10:00:00Z',
          base_params: baseline.params,
          target_params: target.params,
          metric_diffs: [{ key: 'retrieval_mrr', before, after, delta }],
          diff_score:
            delta === null
              ? null
              : {
                  version: '1',
                  used_metric_keys: ['retrieval_mrr'],
                  weights: { retrieval_mrr: 1 },
                  base_score: before,
                  target_score: after,
                  delta,
                  base_metrics: { retrieval_mrr: before },
                  target_metrics: { retrieval_mrr: after },
                },
          slice_diffs: {},
          case_diffs: [],
          significance: [],
          significance_summary: {},
        },
      })
    }
    return route.fallback()
  })
  return state
}
