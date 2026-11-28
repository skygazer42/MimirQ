import type { Page } from '@playwright/test'
import type { KGSearchDiagnosticsResponse } from '../lib/kg-diagnostics-schema'
import { remainingFixture } from './remaining-pages.helpers'
import { policyDatasetId } from './dataset-policy.helpers'

export const secondDataset = '22222222-2222-4222-8222-222222222222'

export function diagnosticReport(
  datasetId: string,
  cases: { caseId: string; question: string; error?: string }[],
  runId: string | null,
): KGSearchDiagnosticsResponse {
  const failed = cases.filter(({ error }) => error !== undefined).length
  const valid = cases.length - failed
  const score = valid > 0 ? 0 : null
  return {
    run_id: runId,
    summary: {
      dataset_id: datasetId,
      cases_total: cases.length,
      cases_evaluated: cases.length,
      hardcases_generated: 0,
      baseline_hit_rate: score,
      baseline_mrr: score,
      baseline_recall: score,
      baseline_ndcg: score,
      baseline_map: score,
      baseline_valid_searches: valid,
      baseline_search_errors: failed,
      hardcase_hit_rate: null,
      hardcase_mrr: null,
      hardcase_recall: null,
      hardcase_ndcg: null,
      hardcase_map: null,
      hardcase_valid_searches: 0,
      hardcase_search_errors: 0,
      failure_breakdown: {},
      preflight: {},
    },
    items: cases.map(({ caseId, question, error }) => ({
      case_id: caseId,
      question,
      tags: [],
      evidence_chunk_ids: [],
      ground_truth_event_ids: [],
      baseline: {
        query: question,
        events: [],
        entities: [],
        clues: [],
        stats: {},
        error: error ?? null,
        metrics: {
          hit_at_k: false,
          mrr: 0,
          recall: 0,
          ndcg: 0,
          map: 0,
          matched_evidence_chunks: 0,
          total_evidence_chunks: 0,
          k: 10,
        },
      },
      hardcases: [],
      attribution: { primary_cause: error === undefined ? 'no_evidence' : 'search_error', signals: {} },
    })),
  }
}

export async function diagnosticsFixture(page: Page, theme: 'light' | 'dark' = 'light') {
  await remainingFixture(page, theme)
  await page.setViewportSize({ width: 1440, height: 900 })
  await page.addInitScript(() => localStorage.removeItem('mimirq.themeColor'))
  const state = { fail: true, gate: null as Promise<void> | null, requests: [] as Record<string, unknown>[] }
  await page.route('**/api/v1/**', async (route) => {
    const url = new URL(route.request().url()),
      p = url.pathname.replace(/\/$/, '')
    if (p === '/api/v1/datasets')
      return route.fulfill({
        json: {
          total: 2,
          items: [
            { id: policyDatasetId, name: '产品知识库' },
            { id: secondDataset, name: '另一数据集' },
          ],
        },
      })
    if (p === '/api/v1/evaluations/kg/search/diagnostics') {
      const request = route.request().postDataJSON()
      state.requests.push(request)
      if (state.gate) await state.gate
      return route.fulfill({
        status: state.fail ? 503 : 200,
        json: state.fail
          ? { detail: '诊断服务暂不可用' }
          : diagnosticReport(
              request.dataset_id,
              [{ caseId: 'case-1', question: '维护周期是多久？' }],
              request.persist_run ? 'diagnostic-run-1' : null,
            ),
      })
    }
    if (p === '/api/v1/evaluations/kg/search/diagnostics/runs') return route.fulfill({ json: { total: 0, items: [] } })
    if (p === '/api/v1/evaluations/kg/quality/report')
      return route.fulfill({
        json: {
          summary: {
            documents: 2,
            events: 1,
            entities: 43,
            relations: 82,
            event_entity_links: 0,
            avg_relations_per_entity: 82 / 43,
            isolated_entities: 2,
            isolated_entity_ratio: 2 / 43,
          },
          components: { nodes: 43, edges: 82, components: 3, largest_component_ratio: 41 / 43 },
          noise: {
            relations_total: 82,
            low_confidence_threshold: 0.2,
            low_confidence_relations: 0,
            missing_references_relations: 0,
            missing_chunk_relations: 0,
          },
          truncation: { relation_edges_truncated: false, relation_edges_limit: 1000 },
          scope: { dataset_id: url.searchParams.get('dataset_id'), documents_sampled: 2, documents_allowed: 2 },
        },
      })
    return route.fallback()
  })
  return state
}
