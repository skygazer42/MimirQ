import type { PromptPreviewResponse } from '@/types'

type JsonRecord = Record<string, unknown>

type RetrievalExplainResponseLike = {
  channels?: Record<string, unknown>
  candidate_counts?: Record<string, unknown>
  rerank?: Record<string, unknown>
  stage_timings?: Record<string, unknown>
  metrics?: Record<string, unknown>
  query_debug?: Record<string, unknown>
  retrieval_trace?: Record<string, unknown>
}

type RetrievalConfigHashResponseLike = {
  hash?: unknown
  effective_config?: unknown
}

type PreviewKV = {
  label: string
  value: string
}

type RagPreviewDiagnosticsSummary = {
  profile: string | null
  configHash: string | null
  queryForRetrieval: string | null
  filtering: PreviewKV[]
  fusion: PreviewKV[]
  reranker: PreviewKV[]
  timings: PreviewKV[]
  degraded: string[]
  fallback: string[]
}

function isRecord(value: unknown): value is JsonRecord {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function asRecord(value: unknown): JsonRecord {
  return isRecord(value) ? value : {}
}

function toText(value: unknown): string | null {
  if (typeof value === 'string' && value.trim()) return value.trim()
  if (typeof value === 'number' && Number.isFinite(value)) return String(value)
  if (typeof value === 'boolean') return value ? 'true' : 'false'
  return null
}

function toNumber(value: unknown): number | null {
  return typeof value === 'number' && Number.isFinite(value) ? value : null
}

function formatObject(value: unknown): string | null {
  if (!isRecord(value)) return null
  const entries = Object.entries(value)
  if (!entries.length) return null
  return entries.map(([key, item]) => `${key}=${toText(item) ?? JSON.stringify(item)}`).join(', ')
}

function pushKV(target: PreviewKV[], label: string, value: unknown, formatter?: (next: unknown) => string | null) {
  const text = formatter ? formatter(value) : toText(value)
  if (!text) return
  target.push({ label, value: text })
}

function filteringItems(config: JsonRecord): PreviewKV[] {
  const items: PreviewKV[] = []
  pushKV(items, 'score_threshold', config.score_threshold)
  pushKV(items, 'retrieval_contract_mode', config.retrieval_contract_mode)
  pushKV(items, 'visible_evidence_only', config.visible_evidence_only)
  pushKV(items, 'metadata_filter', config.metadata_filter, formatObject)
  return items
}

function fusionItems(config: JsonRecord): PreviewKV[] {
  const items: PreviewKV[] = []
  pushKV(items, 'retrieval_mode', config.retrieval_mode)
  pushKV(items, 'alpha', config.alpha)
  pushKV(items, 'fusion_strategy', config.fusion_strategy)
  pushKV(items, 'fusion_budgets', config.fusion_budgets, formatObject)
  pushKV(items, 'fusion_min_scores', config.fusion_min_scores, formatObject)
  pushKV(items, 'fusion_weights', config.fusion_weights, formatObject)
  pushKV(items, 'enable_weight_rerank', config.enable_weight_rerank)
  pushKV(items, 'vector_weight', config.vector_weight)
  pushKV(items, 'keyword_weight', config.keyword_weight)
  pushKV(items, 'mmr_lambda', config.mmr_lambda)
  return items
}

function rerankerItems(config: JsonRecord, explain: RetrievalExplainResponseLike | null): PreviewKV[] {
  const items: PreviewKV[] = []
  pushKV(items, 'enable_reranker', config.enable_reranker)
  pushKV(items, 'reranker_provider', config.reranker_provider)
  pushKV(items, 'reranker_top_n', config.reranker_top_n)
  const rerank = asRecord(explain?.rerank)
  pushKV(items, 'used', rerank.used)
  pushKV(items, 'candidates_n', rerank.candidates_n)
  pushKV(items, 'cache_hits', rerank.cache_hits)
  pushKV(items, 'cache_misses', rerank.cache_misses)
  pushKV(items, 'pipeline_stages', rerank.pipeline_stages, (value) =>
    Array.isArray(value)
      ? value
          .map((item) => toText(item))
          .filter(Boolean)
          .join(' -> ')
      : null,
  )
  return items
}

function timingItems(explain: RetrievalExplainResponseLike | null, preview: PromptPreviewResponse | null): PreviewKV[] {
  const items: PreviewKV[] = []
  const stageTimings = asRecord(explain?.stage_timings)
  for (const [label, value] of Object.entries(stageTimings)) {
    const n = toNumber(value)
    if (n === null) continue
    items.push({ label, value: `${n.toFixed(3)} s` })
  }

  const metrics = asRecord(preview?.metrics)
  for (const [label, value] of [
    ['elapsed_sec', metrics.elapsed_sec],
    ['context_build_elapsed_sec', metrics.context_build_elapsed_sec],
    ['prompt_render_elapsed_sec', metrics.prompt_render_elapsed_sec],
    ['retrieval_elapsed_sec', metrics.retrieval_elapsed_sec],
  ] as const) {
    const n = toNumber(value)
    if (n === null) continue
    if (items.some((item) => item.label === label)) continue
    items.push({ label, value: `${n.toFixed(3)} s` })
  }

  return items
}

function collectFlagTexts(source: JsonRecord, keys: string[]): string[] {
  const out: string[] = []
  for (const key of keys) {
    const text = formatObject(source[key]) || toText(source[key])
    if (text) out.push(`${key}: ${text}`)
  }
  return out
}

function collectListFlagTexts(source: JsonRecord, key: string): string[] {
  const raw = source[key]
  if (!Array.isArray(raw)) return []
  const out: string[] = []
  for (const item of raw) {
    const text = toText(item)
    if (text) out.push(`${key}: ${text}`)
  }
  return out
}

export function buildRagPreviewDiagnosticsSummary(args: {
  promptPreview: PromptPreviewResponse | null
  explain: RetrievalExplainResponseLike | null
  configHash: RetrievalConfigHashResponseLike | null
}): RagPreviewDiagnosticsSummary {
  const { configHash, explain, promptPreview } = args
  const effectiveConfig = asRecord(configHash?.effective_config)
  const metrics = asRecord(explain?.metrics)
  const retrievalTrace = asRecord(explain?.retrieval_trace)

  const configHashText =
    toText(configHash?.hash) || toText(metrics.retrieval_config_hash) || toText(retrievalTrace.retrieval_config_hash)

  const profile =
    toText(effectiveConfig.retrieval_profile) ||
    toText(metrics.retrieval_profile) ||
    toText(retrievalTrace.retrieval_profile)

  const degraded = [
    ...collectFlagTexts(metrics, ['degraded', 'degraded_reason']),
    ...collectFlagTexts(metrics, ['retrieval_degraded', 'retrieval_fallback_reason']),
    ...collectListFlagTexts(metrics, 'retrieval_degraded_reasons'),
    ...collectFlagTexts(asRecord(explain?.query_debug), [
      'degraded',
      'degraded_reason',
      'retrieval_degraded',
      'fallback_reason',
    ]),
    ...collectListFlagTexts(asRecord(explain?.query_debug), 'retrieval_degraded_reasons'),
  ]
  const fallback = [
    ...collectFlagTexts(metrics, [
      'selection_fallback',
      'generation_fallback_used',
      'generation_fallback_error',
      'retrieval_fallback_reason',
    ]),
    ...collectFlagTexts(asRecord(explain?.query_debug), ['fallback', 'fallback_reason', 'selection_fallback']),
  ]

  return {
    profile,
    configHash: configHashText,
    queryForRetrieval: toText(promptPreview?.query_for_retrieval),
    filtering: filteringItems(effectiveConfig),
    fusion: fusionItems(effectiveConfig),
    reranker: rerankerItems(effectiveConfig, explain),
    timings: timingItems(explain, promptPreview),
    degraded,
    fallback,
  }
}
