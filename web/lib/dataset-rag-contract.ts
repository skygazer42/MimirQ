import type { RAGConfig } from '@/lib/api/settings'
import type { DatasetRagDefaults } from '@/types'

const MANAGED_DATASET_RAG_FIELDS = [
  ['retrieval_top_k', 'top_k'],
  ['similarity_threshold', 'score_threshold'],
  ['retrieval_mode', 'retrieval_mode'],
] as const satisfies ReadonlyArray<
  readonly [keyof RAGConfig, keyof DatasetRagDefaults]
>

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function toFiniteNumber(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : undefined
  }
  return undefined
}

function toOptionalBoolean(value: unknown): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined
}

function toOptionalString(value: unknown): string | undefined {
  return typeof value === 'string' && value.trim() ? value : undefined
}

export function hasDatasetRagContract(
  value: DatasetRagDefaults | Record<string, unknown> | null | undefined
): value is DatasetRagDefaults {
  return isRecord(value) && Object.keys(value).length > 0
}

export function mergeDatasetRagDefaultsIntoRagConfig(
  base: RAGConfig,
  datasetRagDefaults?: DatasetRagDefaults | null
): RAGConfig {
  if (!hasDatasetRagContract(datasetRagDefaults)) return { ...base }

  return {
    ...base,
    retrieval_top_k:
      toFiniteNumber(datasetRagDefaults.top_k) ?? base.retrieval_top_k,
    similarity_threshold:
      toFiniteNumber(datasetRagDefaults.score_threshold) ??
      base.similarity_threshold,
    retrieval_profile:
      toOptionalString(datasetRagDefaults.retrieval_profile) ??
      base.retrieval_profile,
    retrieval_mode:
      toOptionalString(datasetRagDefaults.retrieval_mode) ??
      base.retrieval_mode,
    retrieval_contract_mode:
      toOptionalString(datasetRagDefaults.retrieval_contract_mode) ??
      base.retrieval_contract_mode,
    alpha: toFiniteNumber(datasetRagDefaults.alpha) ?? base.alpha,
    fusion_strategy:
      toOptionalString(datasetRagDefaults.fusion_strategy) ??
      base.fusion_strategy,
    fusion_budgets: isRecord(datasetRagDefaults.fusion_budgets)
      ? (datasetRagDefaults.fusion_budgets as Record<string, number>)
      : base.fusion_budgets,
    fusion_min_scores: isRecord(datasetRagDefaults.fusion_min_scores)
      ? (datasetRagDefaults.fusion_min_scores as Record<string, number>)
      : base.fusion_min_scores,
    fusion_weights: isRecord(datasetRagDefaults.fusion_weights)
      ? (datasetRagDefaults.fusion_weights as Record<string, number>)
      : base.fusion_weights,
    enable_weight_rerank:
      toOptionalBoolean(datasetRagDefaults.enable_weight_rerank) ??
      base.enable_weight_rerank,
    vector_weight:
      toFiniteNumber(datasetRagDefaults.vector_weight) ?? base.vector_weight,
    keyword_weight:
      toFiniteNumber(datasetRagDefaults.keyword_weight) ?? base.keyword_weight,
    mmr_lambda:
      toFiniteNumber(datasetRagDefaults.mmr_lambda) ?? base.mmr_lambda,
    enable_reranker:
      toOptionalBoolean(datasetRagDefaults.enable_reranker) ??
      base.enable_reranker,
    reranker_provider:
      toOptionalString(datasetRagDefaults.reranker_provider) ??
      base.reranker_provider,
    reranker_top_n:
      toFiniteNumber(datasetRagDefaults.reranker_top_n) ??
      base.reranker_top_n,
    visible_evidence_only:
      toOptionalBoolean(datasetRagDefaults.visible_evidence_only) ??
      base.visible_evidence_only,
  }
}

export function buildDatasetRagDefaultsForUpdate(args: {
  currentDefaults?: DatasetRagDefaults | null
  savedRag: RAGConfig
  draftRag: RAGConfig
}): DatasetRagDefaults | null {
  const { currentDefaults, draftRag, savedRag } = args
  const base = hasDatasetRagContract(currentDefaults)
    ? ({ ...currentDefaults } as DatasetRagDefaults)
    : null

  let changed = false
  const next: DatasetRagDefaults = { ...(base ?? {}) }

  for (const [ragKey, datasetKey] of MANAGED_DATASET_RAG_FIELDS) {
    const savedValue = savedRag[ragKey]
    const draftValue = draftRag[ragKey]
    if (savedValue === draftValue) continue
    if (datasetKey === 'top_k') {
      next.top_k = typeof draftValue === 'number' ? draftValue : null
    } else if (datasetKey === 'score_threshold') {
      next.score_threshold = typeof draftValue === 'number' ? draftValue : null
    } else {
      next.retrieval_mode =
        typeof draftValue === 'string' ? draftValue : null
    }
    changed = true
  }

  if (!base && !changed) return null
  return next
}

export function buildRetrievalConfigHashRequest(
  defaults?: DatasetRagDefaults | null
): { rag_config: Record<string, unknown>; include_runtime_defaults: true } | null {
  if (!hasDatasetRagContract(defaults)) return null
  return {
    rag_config: { ...defaults },
    include_runtime_defaults: true,
  }
}

export function datasetRagContractModeLabel(
  defaults?: DatasetRagDefaults | null
): string {
  if (!hasDatasetRagContract(defaults)) return '未配置'

  const profile = toOptionalString(defaults.retrieval_profile)
  const mode = toOptionalString(defaults.retrieval_mode)
  if (profile && mode) return `${profile} · ${mode}`
  return profile || mode || '已配置'
}
