import type { Page } from '@playwright/test'
import { remainingFixture } from './remaining-pages.helpers'
import { policyDatasetId } from './dataset-policy.helpers'

export const auditDocumentId = '11111111-1111-4111-8111-111111111111'
export async function lastBatchFixture(page: Page, theme: 'light' | 'dark' = 'light') {
  await remainingFixture(page, theme)
  const state = { failHealth: false, failSummary: false, failEvidence: false, failChunks: false, emptyChunks: false, evidenceMode: 'evidence', gate: null as Promise<void> | null, evidenceRequests: [] as unknown[] }
  await page.route('**/api/v1/**', async route => {
    const url = new URL(route.request().url()), p = url.pathname.replace(/\/$/, '')
    if (p === `/api/v1/documents/${auditDocumentId}/health`) return route.fulfill({ status: state.failHealth ? 503 : 200, json: state.failHealth ? { detail: '健康审计暂不可用' } : { document_id: auditDocumentId, dataset_id: policyDatasetId, filename: '设备维护与操作手册.pdf', file_type: 'pdf', file_size: 64000, status: 'completed', generated_at: '2026-10-27T08:00:00Z', parsing: { parser_backend: 'auto', page_count: 12, is_scanned: false, parse_quality: { score: 0.86 } }, chunking: { chunk_count: 8, total_characters: 24000, chunk_strategy: 'default', semantic_quality: null, coverage: null }, kg: { summary: { entities: 12, relations: 18, isolated_entity_ratio: 0.08 }, components: { largest_component_ratio: 0.92 } }, retrieval_hits: { enabled: true, available: true, window_minutes: 1440, traces_scanned: 30, traces_with_hits: 24, citations_matched: 36, unique_chunks_matched: 8, hit_rate: 0.8, truncated: false } } })
    if (p === '/api/v1/observability/rag-metrics/summary') return route.fulfill({ status: state.failSummary ? 503 : 200, json: state.failSummary ? { detail: '观测汇总暂不可用' } : { enabled: true, path: 'metrics.jsonl', window_minutes: Number(url.searchParams.get('window_minutes') || 60), truncated: false, record_count: 30, rag_trace_count: 30, reranker_api_count: 12, retrieval_avg_elapsed_sec: 0.4, retrieval_p95_elapsed_sec: 0.9, citations_avg_count: 3, retrieval_mode_counts: { hybrid: 25, vector: 5 }, hit_type_counts: { vector: 20, keyword: 10 }, error_counts: { upstream: 1 }, timeseries: {} } })
    if (p === '/api/v1/observability/rag-metrics/query-analytics') return route.fulfill({ json: { enabled: true, window_minutes: 60, truncated: false, record_count: 30, rag_trace_count: 30, unique_query_hashes: 24, zero_hit_count: 3, zero_hit_rate: 0.1, slow_threshold_sec: 2, slow_count: 2, slow_rate: 0.067, retrieval_p50_elapsed_sec: 0.4, retrieval_p95_elapsed_sec: 0.9, retrieval_p99_elapsed_sec: 1.4, error_kind_counts: { upstream: 1 }, top_zero_hit_queries: [{ query_hash: 'query-empty-001', count: 3 }], top_slow_queries: [{ query_hash: 'query-slow-001', count: 2, max_elapsed_sec: 3.2 }], timeseries: {} } })
    if (p === '/api/v1/documents' && url.searchParams.get('status') === 'completed') return route.fulfill({ json: { total: 1, items: [{ id: auditDocumentId, filename: '设备维护与操作手册.pdf', file_type: 'pdf', status: 'completed', metadata: { chunk_count: 4 } }] } })
    if (p === `/api/v1/documents/${auditDocumentId}/chunks`) return route.fulfill({ status: state.failChunks ? 503 : 200, json: state.failChunks ? { detail: '切片读取暂不可用' } : { total: state.emptyChunks ? 0 : 4, items: state.emptyChunks ? [] : [0, 1, 2, 3].map(index => ({ id: `chunk-${index}`, content: `设备维护第 ${index + 1} 节：每六个月进行例行检查，确认电源和润滑状态。`, chunk_index: index })) } })
    if (p === '/api/v1/rag/retrieve') {
      state.evidenceRequests.push(route.request().postDataJSON())
      const mode = state.evidenceMode
      if (state.gate) await state.gate
      return route.fulfill({ status: state.failEvidence ? 503 : 200, json: state.failEvidence ? { detail: '证据检索暂不可用' } : { query_for_retrieval: route.request().postDataJSON().query, has_evidence: mode === 'evidence', abstain_triggered: mode === 'abstain', abstain_reason: mode === 'abstain' ? '没有足够证据支持回答' : null, citations: mode === 'evidence' ? [{ document_id: auditDocumentId, document_name: '设备维护与操作手册.pdf', chunk_id: 'chunk-1', chunk_index: 1, chunk_content: '维护周期为六个月，完成例行检查后记录维护日期。', relevance_score: 0.86 }] : [], metrics: { top_relevance_score: mode === 'evidence' ? 0.86 : null, retrieval_elapsed_sec: 0.4 } } })
    }
    return route.fallback()
  })
  return state
}
