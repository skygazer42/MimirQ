/**
 * Evaluation, evidence, and similarity workbench types re-exported by `@/types`.
 */

import type { OpenApiSchema } from './backend'
import type { JsonObject } from './common'

// ==================== 批量上传相关类型 ====================

export type BatchFileInfo = {
  name: string
  data_id: string
}

export type BatchUploadRequest = {
  files: BatchFileInfo[]
}

export type BatchUploadResponse = {
  batch_id: string
  file_urls: string[]
  files: BatchFileInfo[]
  message: string
}

export type BatchTaskStatus = {
  batch_id: string
  status: string
  total_files: number
  completed_files: number
  failed_files: number
  progress: number
  result_url?: string | null
  error?: string | null
}

export type DocumentBatchUploadSuccess = import('./backend').DocumentBatchUploadSuccess
export type DocumentBatchUploadFailure = import('./backend').DocumentBatchUploadFailure
export type DocumentBatchUploadResponse = import('./backend').DocumentBatchUploadResponse

// ==================== RAGAS 回归测试相关类型 ====================

export type ReferenceSource = {
  document_id: string
  chunk_id: string
  chunk_index?: number
  page_number?: number
  start_char?: number
  end_char?: number
  doc_pipeline_key?: string
  pipeline_hash?: string
  quote?: string
  label?: string
}

// Alias kept for UI components that use the older naming.
export type RegressionReferenceSource = ReferenceSource

export type RegressionCase = {
  id: string
  tenant_id: string
  dataset_id?: string
  document_ids: string[]
  question: string
  expected_answer?: string
  reference_sources: ReferenceSource[]
  tags: string[]
  extra: JsonObject
  created_by?: string
  created_at: string
  updated_at: string
}

export type RegressionCaseCreate = {
  question: string
  dataset_id?: string
  document_ids?: string[]
  expected_answer?: string
  reference_sources?: ReferenceSource[]
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

export type RegressionCaseBundleItem = {
  question: string
  expected_answer?: string | null
  tags: string[]
  reference_sources: ReferenceSource[]
  reasoning_hops?: string[]
  evidence_chain?: ReferenceSource[]
  extra?: JsonObject
}

export type RegressionCaseBundleV1 = {
  schema: 'mimirq.regression_cases.v1'
  dataset_id: string
  items: RegressionCaseBundleItem[]
}

export type RegressionCaseImportResponse = {
  created: number
  updated: number
  skipped: number
  errors: JsonObject[]
  created_case_ids: string[]
  updated_case_ids: string[]
  skipped_case_ids: string[]
  case_ids: string[]
}

export type RegressionCaseList = {
  total: number
  items: RegressionCase[]
}

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

export type WhyMissedReferenceStatus = 'retrieved' | 'missing' | 'drifted' | 'unknown'

export type WhyMissedReferenceHints = {
  /** Rank (1-based) of the first citation matching the reference document. */
  document_hit_rank?: number
  /** Rank (1-based) of the first citation matching the document and chunk index. */
  chunk_index_hit_rank?: number
  /** Rank (1-based) of the first citation matching the reference hierarchy family. */
  family_hit_rank?: number
}

export type WhyMissedRetrievalInfo = {
  rank: number
  hit_type?: string
  score?: number
}

export type WhyMissedDriftInfo = {
  reason: string
  expected?: unknown
  observed?: unknown
}

export type WhyMissedReferenceReportRow = {
  document_id: string | null
  chunk_id: string
  chunk_index?: number
  label?: string | null
  status: WhyMissedReferenceStatus
  retrieval?: WhyMissedRetrievalInfo
  drift?: WhyMissedDriftInfo
  hints?: WhyMissedReferenceHints
}

export type WhyMissedSummary = {
  total_references: number
  retrieved_references: number
  missing_references: number
  drifted_references: number
  unknown_references: number
}

export type WhyMissedReport = {
  summary: WhyMissedSummary
  references: WhyMissedReferenceReportRow[]
}

export type GeneratedQuestion = {
  question: string
  expected_answer?: string
  context?: string
  source_type: 'document' | 'conversation'
  source_id: string
  metadata: JsonObject
}

export type TestGenFromDocsRequest = {
  dataset_id?: string
  document_ids?: string[]
  num_questions?: number
  question_types?: string[]
  auto_save_as_cases?: boolean
}

export type TestGenFromConversationsRequest = {
  conversation_ids: string[]
  num_questions?: number
  quality_threshold?: number
  auto_save_as_cases?: boolean
}

export type TestGenResponse = {
  status: string
  generated_questions: GeneratedQuestion[]
  saved_case_ids: string[]
  error_message?: string
}

export type RagasRun = {
  id: string
  conversation_id?: string
  status: string
  metrics: string[]
  params: JsonObject
  summary: JsonObject
  error_message?: string
  created_at: string
  started_at?: string
  finished_at?: string
}

export type RagasItem = {
  id: string
  run_id: string
  turn_index: number
  user_message_id?: string
  assistant_message_id?: string
  user_input: string
  response: string
  retrieved_contexts?: string[] | null
  citations: unknown[]
  scores: JsonObject
  created_at: string
}

export type RagasRunDetail = {
  run: RagasRun
  items: RagasItem[]
}

export type RagasRunList = {
  total: number
  items: RagasRun[]
}

export type RagasRunCreateRequest = {
  conversation_id: string
  metrics?: string[]
  max_turns?: number
  skip_empty_contexts?: boolean
  include_contexts_in_response?: boolean
}

export type RagasConversationReadinessRequest = {
  conversation_ids: string[]
}

export type RagasConversationReadinessItem = {
  conversation_id: string
  assistant_turns: number
  evaluable_turns: number
  citations_count: number
  is_evaluable: boolean
}

export type RagasConversationReadinessResponse = {
  total: number
  items: RagasConversationReadinessItem[]
}

export type KGHardcaseMode = 'off' | 'deterministic' | 'llm'

export type KGSearchDiagnosticsRequest = {
  dataset_id: string
  case_ids?: string[]
  max_cases?: number
  k?: number
  auto_extract_kg?: boolean
  extract_skills?: boolean | null
  extract_relations?: boolean | null
  hardcase_mode?: KGHardcaseMode
  hardcases_per_failed_case?: number
  max_failed_cases_for_hardcase?: number
  llm_temperature?: number
  persist_run?: boolean
}

export type KGSearchDiagnosticsItem = OpenApiSchema<'KGSearchDiagnosticsItem'>
export type KGSearchDiagnosticsSummary = OpenApiSchema<'KGSearchDiagnosticsSummary'>

export type KGSearchDiagnosticsResponse = {
  run_id?: string | null
  summary: KGSearchDiagnosticsSummary
  items?: KGSearchDiagnosticsItem[]
}

export type KGSearchDiagnosticsRunOut = {
  id: string
  tenant_id: string
  account_id?: string | null
  dataset_id: string
  status: string
  params?: JsonObject
  summary?: JsonObject
  created_at: string
}

export type KGSearchDiagnosticsRunList = {
  total: number
  items: KGSearchDiagnosticsRunOut[]
}

export type KGSearchDiagnosticsRunListParams = {
  dataset_id: string
  limit?: number
}

export type KGSearchDiagnosticsRunDetail = {
  run: KGSearchDiagnosticsRunOut
  items?: JsonObject[]
}

export type RegressionRun = {
  id: string
  tenant_id: string
  account_id?: string
  dataset_id?: string
  status: string
  metrics: string[]
  params: JsonObject
  summary: JsonObject
  error_message?: string
  created_at: string
  started_at?: string
  finished_at?: string
}

export type RegressionRunCreate = {
  case_ids?: string[]
  dataset_id?: string
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
  sparse_retrieval_enabled?: boolean | null
  sparse_retrieval_provider?: string | null
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

export type RegressionAblationBatchResponse = {
  ablation_id: string
  total: number
  run_ids: string[]
  variants: JsonObject[]
  status: string
}

export type RegressionRunList = {
  total: number
  items: RegressionRun[]
}

export type RegressionItem = {
  id: string
  run_id: string
  case_id: string
  question: string
  response: string
  retrieved_contexts?: string[]
  citations: unknown[]
  scores: JsonObject
  meta?: JsonObject
  created_at: string
}

export type RegressionRunDetail = {
  run: RegressionRun
  items: RegressionItem[]
}

export type RegressionRunMetricDiff = {
  key: string
  before?: unknown
  after?: unknown
  delta?: number | null
}

export type RegressionRunDiffScore = {
  version: string
  used_metric_keys: string[]
  weights: Record<string, number>
  base_score?: number | null
  target_score?: number | null
  delta?: number | null
  base_metrics: Record<string, number>
  target_metrics: Record<string, number>
}

export type RegressionRunSliceBucketDiff = {
  key: string
  items_before: number
  items_after: number
  metrics: RegressionRunMetricDiff[]
}

export type RegressionRunSliceDiff = {
  truncated_before: boolean
  truncated_after: boolean
  buckets: RegressionRunSliceBucketDiff[]
}

export type RegressionRunCaseDiff = {
  case_id: string
  question: string
  metric_diffs: RegressionRunMetricDiff[]
  mean_delta?: number | null
  label: string
}

export type RegressionRunMetricSignificance = {
  key: string
  compared: number
  base_mean?: number | null
  target_mean?: number | null
  delta_mean?: number | null
  bootstrap_ci_low?: number | null
  bootstrap_ci_high?: number | null
  p_value?: number | null
  p_value_method?: string | null
  p_value_bh?: number | null
  wilcoxon_p_value?: number | null
  mcnemar_p_value?: number | null
  cohen_d?: number | null
  significant: boolean
}

export type RagasRegressionRunDiffResponse = {
  base_run_id: string
  target_run_id: string
  generated_at: string
  base_params: JsonObject
  target_params: JsonObject
  metric_diffs: RegressionRunMetricDiff[]
  diff_score?: RegressionRunDiffScore | null
  slice_diffs: Record<string, RegressionRunSliceDiff>
  significance: RegressionRunMetricSignificance[]
  case_diffs: RegressionRunCaseDiff[]
  significance_summary: JsonObject
}

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
  stats: RagvizSimilarityStats
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
