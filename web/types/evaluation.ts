/**
 * Evaluation, evidence, and similarity workbench types re-exported by `@/types`.
 */

import type { JsonObject } from './common'

// ==================== 批量上传相关类型 ====================

export type DocumentBatchUploadSuccess = import('./backend').DocumentBatchUploadSuccess
export type DocumentBatchUploadFailure = import('./backend').DocumentBatchUploadFailure
export type DocumentBatchUploadResponse = import('./backend').DocumentBatchUploadResponse

// ==================== RAGAS 回归测试相关类型 ====================

export type ReferenceSource = import('@/lib/regression-case-schema').RegressionReferenceSource

export type RegressionCase = import('@/lib/regression-case-schema').RegressionCase

export type RegressionCaseCreate = {
  question: string
  dataset_id: string
  document_ids?: string[]
  expected_answer?: string
  reference_sources: ReferenceSource[]
  tags?: string[]
  extra?: JsonObject
}

export type RegressionCasePatch = {
  question?: string
  document_ids?: string[]
  expected_answer?: string | null
  reference_sources?: ReferenceSource[]
  tags?: string[]
  extra?: JsonObject
}

export type RegressionCaseBundleItem = import('@/lib/regression-case-schema').RegressionCaseBundleItem
export type RegressionCaseBundleV1 = import('@/lib/regression-case-schema').RegressionCaseBundleV1
export type RegressionCaseImportRequest = import('@/lib/regression-case-schema').RegressionCaseImportRequest
export type RegressionCaseImportResponse = import('@/lib/regression-case-schema').RegressionCaseImportResponse

export type RegressionCaseList = import('@/lib/regression-case-schema').RegressionCaseList

// ==================== Evidence Workbench（Ground Truth 证据库） ====================

export type EvidenceItemStatus = 'draft' | 'reviewed' | 'approved' | 'archived'

export type EvidenceSuite = import('./backend').EvidenceSuite
export type EvidenceSuiteCreate = import('./backend').EvidenceSuiteCreate
export type EvidenceSuitePatch = import('./backend').EvidenceSuitePatch
export type EvidenceSuiteList = import('./backend').EvidenceSuiteList
export type EvidenceSuiteCoverage = import('./backend').EvidenceSuiteCoverage
export type EvidenceSuiteThroughput = import('./backend').EvidenceSuiteThroughput
export type EvidenceSuiteDashboard = import('./backend').EvidenceSuiteDashboard
export type EvidenceSuiteSyncRegressionResponse = import('./backend').EvidenceSuiteSyncRegressionResponse
export type EvidenceSuiteExportV1 = import('./backend').EvidenceSuiteExportV1

export type EvidenceItem = import('./backend').EvidenceItem
export type EvidenceItemCreate = import('./backend').EvidenceItemCreate
export type EvidenceItemPatch = import('./backend').EvidenceItemPatch
export type EvidenceItemList = import('./backend').EvidenceItemList
export type EvidenceItemImportResponse = import('./backend').EvidenceItemImportResponse

export type EvidenceCoverageBucket = import('./backend').EvidenceCoverageBucket
export type EvidenceCoverageHeatmap = import('./backend').EvidenceCoverageHeatmap
export type EvidenceThroughputWindow = import('./backend').EvidenceThroughputWindow
export type EvidenceLeadTimeStats = import('./backend').EvidenceLeadTimeStats

export type EvidenceDriftSliceBucket = import('./backend').EvidenceDriftSliceBucket
export type EvidenceReferenceDriftDetail = import('./backend').EvidenceReferenceDriftDetail
export type EvidenceReferenceDriftAudit = import('./backend').EvidenceReferenceDriftAudit

export type EvidenceReferenceRepairRequest = import('./backend').EvidenceReferenceRepairRequest
export type EvidenceReferenceRepairChange = import('./backend').EvidenceReferenceRepairChange
export type EvidenceReferenceRepairResponse = import('./backend').EvidenceReferenceRepairResponse

export type EvidenceHardcaseCandidate = import('./backend').EvidenceHardcaseCandidate
export type EvidenceHardcaseDiscovery = import('./backend').EvidenceHardcaseDiscovery

export type GeneratedQuestion = import('@/lib/question-generation-schema').GeneratedQuestion
export type TestGenFromDocsRequest = import('@/lib/question-generation-schema').TestGenFromDocsRequest
export type TestGenFromConversationsRequest = import('@/lib/question-generation-schema').TestGenFromConversationsRequest
export type TestGenResponse = import('@/lib/question-generation-schema').TestGenResponse

export type RagasRun = import('@/lib/ragas-conversation-schema').RagasRun
export type RagasItem = import('@/lib/ragas-conversation-schema').RagasItem
export type RagasRunDetail = import('@/lib/ragas-conversation-schema').RagasRunDetail
export type RagasRunList = import('@/lib/ragas-conversation-schema').RagasRunList
export type RagasRunCreateRequest = import('@/lib/ragas-conversation-schema').RagasRunCreateRequest
export type RagasConversationReadinessRequest =
  import('@/lib/ragas-conversation-schema').RagasConversationReadinessRequest
export type RagasConversationReadinessItem = import('@/lib/ragas-conversation-schema').RagasConversationReadinessItem
export type RagasConversationReadinessResponse =
  import('@/lib/ragas-conversation-schema').RagasConversationReadinessResponse

export type KGHardcaseMode = import('@/lib/kg-diagnostics-schema').KGHardcaseMode
export type KGSearchDiagnosticsRequest = import('@/lib/kg-diagnostics-schema').KGSearchDiagnosticsRequest
export type KGSearchDiagnosticsItem = import('@/lib/kg-diagnostics-schema').KGSearchDiagnosticsItem
export type KGSearchDiagnosticsSummary = import('@/lib/kg-diagnostics-schema').KGSearchDiagnosticsSummary
export type KGSearchDiagnosticsResponse = import('@/lib/kg-diagnostics-schema').KGSearchDiagnosticsResponse
export type KGSearchDiagnosticsRunOut = import('@/lib/kg-diagnostics-schema').KGSearchDiagnosticsRunOut
export type KGSearchDiagnosticsRunList = import('@/lib/kg-diagnostics-schema').KGSearchDiagnosticsRunList
export type KGQualityReport = import('@/lib/kg-diagnostics-schema').KGQualityReport
export type SyntheticHardcaseGenerateRequest = import('@/lib/evaluation-ops-schema').SyntheticHardcaseGenerateRequest
export type SyntheticHardcaseGenerateResponse = import('@/lib/evaluation-ops-schema').SyntheticHardcaseGenerateResponse
export type RegressionRunPurgeRequest = import('@/lib/evaluation-ops-schema').RegressionRunPurgeRequest
export type RegressionRunPurgeResponse = import('@/lib/evaluation-ops-schema').RegressionRunPurgeResponse

export type KGSearchDiagnosticsRunListParams = import('@/lib/kg-diagnostics-schema').KGSearchDiagnosticsRunListParams

export type KGSearchDiagnosticsRunDetail = import('@/lib/kg-diagnostics-schema').KGSearchDiagnosticsRunDetail

export type RegressionRun = import('@/lib/regression-run-schema').RegressionRun

export type RegressionRunCreate = {
  case_ids?: string[]
  dataset_id: string
  answer_mode?: 'rag' | 'ontology'
  metrics?: string[]
  use_llm_judge?: boolean
  skip_empty_contexts?: boolean
  max_cases?: number
  retrieval_profile?: string | null
  enable_query_alias_expansion?: boolean | null
  query_alias_max_queries?: number | null
  enable_multi_query?: boolean | null
  multi_query_count?: number | null
  multi_query_temperature?: number | null
  multi_query_max_chars?: number | null
  enable_hyde?: boolean | null
  enable_hierarchy_recall?: boolean | null
  hierarchy_family_collapse?: boolean | null
  hierarchy_family_aggregation?: 'frequency' | 'score' | 'combined' | null
  hierarchy_tree_dedup?: boolean | null
  hierarchy_parent_depth?: number | null
  hierarchy_sibling_window?: number | null
  hierarchy_overfetch_factor?: number | null
  enable_query_rewrite?: boolean | null
  query_rewrite_strategy?: string | null
  query_rewrite_temperature?: number | null
  query_rewrite_max_chars?: number | null
  top_k?: number
  score_threshold?: number
  retrieval_mode?: string
  alpha?: number
  fusion_strategy?: string | null
  fusion_budgets?: Record<string, number> | null
  fusion_min_scores?: Record<string, number> | null
  fusion_weights?: Record<string, number> | null
  enable_weight_rerank?: boolean
  vector_weight?: number
  keyword_weight?: number
  mmr_lambda?: number
  enable_reranker?: boolean
  reranker_provider?: string
  reranker_top_n?: number
  prompt_template_id?: string
  prompt_template_key?: string
  prompt_ab_experiment_key?: string
}

export type RegressionAblationGridValue = string | number | boolean | null | JsonObject

export type RegressionAblationBatchRequest = RegressionRunCreate & {
  grid: Record<string, RegressionAblationGridValue[]>
  max_combinations?: number
  ablation_label_prefix?: string | null
}

export type RegressionAblationBatchResponse = import('@/lib/regression-run-schema').RegressionAblationBatchResponse

export type RegressionRunList = import('@/lib/regression-run-schema').RegressionRunList
export type RegressionRunLeaderboard = import('@/lib/regression-run-schema').RegressionRunLeaderboard
export type RegressionItem = import('@/lib/regression-run-schema').RegressionItem
export type RegressionRunDetail = import('@/lib/regression-run-schema').RegressionRunDetail

export type RegressionRunMetricDiff = import('@/lib/regression-diff-schema').RegressionRunMetricDiff
export type RegressionRunDiffScore = import('@/lib/regression-diff-schema').RegressionRunDiffScore
export type RegressionRunSliceBucketDiff = import('@/lib/regression-diff-schema').RegressionRunSliceBucketDiff
export type RegressionRunSliceDiff = import('@/lib/regression-diff-schema').RegressionRunSliceDiff
export type RegressionRunCaseDiff = import('@/lib/regression-diff-schema').RegressionRunCaseDiff
export type RegressionRunMetricSignificance = import('@/lib/regression-diff-schema').RegressionRunMetricSignificance
export type RagasRegressionRunDiffResponse = import('@/lib/regression-diff-schema').RagasRegressionRunDiffResponse

// ==================== RAGViz（相似度热力图） ====================

export type RagvizSimilarityCollection = {
  id: string
  label: string
  kind: string
  count: number
  meta?: JsonObject
}

export type RagvizSimilarityCollectionsResponse = {
  success: boolean
  collections: RagvizSimilarityCollection[]
  count: number
}

export type RagvizSimilarityRequest = {
  x_collection: string
  y_collection: string
  x_max_items?: number
  y_max_items?: number
  max_items?: number
}

export type RagvizSimilarityStats = {
  total_pairs: number
  avg_similarity: number
  min_similarity: number
  max_similarity: number
  std_similarity: number
  high_similarity_count: number
  medium_similarity_count: number
  low_similarity_count: number
  compute_time: number
}

export type RagvizSimilarityMatrixResult = {
  matrix: number[][]
  x_data: JsonObject[]
  y_data: JsonObject[]
  x_available_fields: string[]
  y_available_fields: string[]
  stats?: Partial<RagvizSimilarityStats> | null
  metadata: JsonObject
}

export type RagvizSimilarityCalculateResponse = {
  success: boolean
  result?: RagvizSimilarityMatrixResult
  message?: string
  error?: string
  error_type?: string
  x_collection?: string
  y_collection?: string
}
