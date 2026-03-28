/**
 * 类型定义
 */

import type {
  JsonObject,
  LooseString,
  PermissionEnum,
} from './common'
import type { DocumentFolderTreeResponse } from './documents'

// ==================== 通用类型 ====================
export * from './common'

// ==================== 文档相关类型 ====================
export * from './documents'

// ==================== Connectors ====================
export * from './connectors'

export type DocumentStats = import('./backend').DocumentStats
export type DocumentBatchLifecycleRequest = import('./backend').DocumentBatchLifecycleRequest
export type DocumentBatchLifecycleResponse = import('./backend').DocumentBatchLifecycleResponse
export type DocumentBatchRetryRequest = import('./backend').DocumentBatchRetryRequest
export type DocumentBatchReingestRequest = import('./backend').DocumentBatchReingestRequest
export type DocumentBatchRetryResponse = import('./backend').DocumentBatchRetryResponse

export type DocumentBatchMoveRequest = import('./backend').DocumentBatchMoveRequest
export type DocumentBatchMoveResponse = import('./backend').DocumentBatchMoveResponse
export type DocumentBatchAccessUpdateRequest = import('./backend').DocumentBatchAccessUpdateRequest
export type DocumentBatchAccessUpdateResponse = import('./backend').DocumentBatchAccessUpdateResponse

export type DuplicateDocumentItem = import('./backend').DuplicateDocumentItem
export type DocumentDuplicateGroup = import('./backend').DocumentDuplicateGroup
export type DocumentDuplicateList = import('./backend').DocumentDuplicateList

// ==================== Observability ====================
export * from './observability'

export type DocumentUserMetadataPatchRequest = import('./backend').DocumentUserMetadataPatchRequest
export type DocumentBatchUserMetadataPatchRequest = import('./backend').DocumentBatchUserMetadataPatchRequest
export type DocumentBatchUserMetadataPatchResponse = import('./backend').DocumentBatchUserMetadataPatchResponse

export type DocumentChunk = import('./backend').DocumentChunk
export type DocumentChunkList = import('./backend').DocumentChunkList
export type DocumentChunkUpdateRequest = import('./backend').DocumentChunkUpdateRequest
export type DocumentChunkCreateRequest = import('./backend').DocumentChunkCreateRequest
export type DocumentChunkMatch = import('./backend').DocumentChunkMatch
export type DocumentChunkMatchList = import('./backend').DocumentChunkMatchList
export type DocumentChunkReembedRequest = import('./backend').DocumentChunkReembedRequest
export type DocumentChunkReembedResponse = import('./backend').DocumentChunkReembedResponse

export type DocumentPipelineOptions = import('./backend').DocumentPipelineOptions
export type DocumentPipelinePatchRequest = import('./backend').DocumentPipelinePatchRequest

export type QAPairPreview = import('./backend').QAPairPreview
export type DocumentQAGenerateRequest = import('./backend').DocumentQAGenerateRequest
export type DocumentQAGenerateResponse = import('./backend').DocumentQAGenerateResponse

export interface Citation {
  document_id: string
  document_name: string
  chunk_id?: string
  chunk_content: string
  matched_terms?: string[]
  page_number?: number
  chunk_index?: number
  start_char?: number
  end_char?: number
  evidence_start_char?: number
  evidence_end_char?: number
  header_path?: string
  chunk_strategy?: string
  chunk_role?: string
  chunk_semantic_role?: string
  policy_clause_id?: string
  policy_clause_number?: string
  policy_path?: string[]
  policy_path_str?: string
  parent_id?: string
  retrieval_role?: string
  neighbor_of?: string
  kg_path?: Array<{ entity_id: string; type?: string }>
  kg_path_provenance?: JsonObject
  doc_pipeline_key?: string
  pipeline_hash?: string
  relevance_score: number
  vector_score?: number
  bm25_score?: number
  keyword_score?: number
  rerank_score?: number
  retrieval_score?: number
  reranker_provider?: string
  rerank_elapsed_sec?: number
  rerank_model_used?: string
  retrieval_mode?: string
  vector_backend?: string
  retrieval_elapsed_sec?: number
  hit_type?: string
  has_image?: boolean
  img_id?: string
  img_url?: string
}

export interface ParsedSegment {
  index: number
  content: string
  page_number?: number
  metadata?: JsonObject
}

export interface DocumentPreview {
  filename: string
  file_type: string
  file_size: number
  segments: ParsedSegment[]
  parser_backend: string
}

export type DocumentParsedContentResponse = import('./backend').DocumentParsedContentResponse

export interface ManualChunk {
  content: string
  page_number?: number
  start_char?: number
  end_char?: number
  metadata?: JsonObject
}

// ==================== 切块预览相关类型 ====================

export interface ChunkPreset {
  id: string
  name: string
  description?: string | null
  payload: JsonObject
}

export interface ChunkPresetCreateRequest {
  name: string
  description?: string | null
  payload: JsonObject
}

export interface ChunkPresetUpdateRequest {
  name: string
  description?: string | null
  payload: JsonObject
}

export interface ChunkPresetListResponse {
  items: ChunkPreset[]
}

export interface ChunkPreviewParams {
  chunk_size: number
  chunk_overlap: number
  unit?: 'chars' | 'tokens'
  strategy_params?: JsonObject
}

export interface ChunkPreviewItem {
  index: number
  content: string
  length: number
  tokens_est?: number
  start_index: number
  end_index: number
  page_number?: number
  metadata?: JsonObject
}

export interface ChunkPreviewHistogramBin {
  label: string
  min?: number | null
  max?: number | null
  count: number
}

export interface ChunkPreviewStats {
  unit?: 'chars' | 'tokens'
  count?: number
  total?: number
  min?: number
  max?: number
  avg?: number
  median?: number
  p10?: number
  p90?: number
  total_tokens_est?: number
  short_count?: number
  duplicate_count?: number
  sum_chunk_chars?: number
  covered_chars?: number
  coverage_ratio?: number
  overlap_waste_ratio?: number
  gap_count?: number
  largest_gap?: number
  histogram?: ChunkPreviewHistogramBin[]
}

export interface ChunkPreviewQualityReason {
  code: string
  severity?: 'info' | 'warning' | 'error'
  message: string
  meta?: JsonObject
}

export interface ChunkPreviewQualityGate {
  grade?: 'pass' | 'warn' | 'fail'
  reasons?: string[]
  reason_items?: ChunkPreviewQualityReason[]
}

export interface ChunkPreviewRecommendationPatch {
  target?: 'preview' | 'pipeline' | 'perf'
  id: string
  title: string
  description?: string
  patch?: JsonObject
}

export interface ChunkPreviewReviewSignals {
  basis?: 'all' | 'child'
  short_indices?: number[]
  duplicate_indices?: number[]
  gap_indices?: number[]
  overlap_indices?: number[]
  gap_before_by_index?: Record<string, number>
  overlap_prev_by_index?: Record<string, number>
}

export interface ChunkPreviewResponse {
  filename: string
  file_type: string
  file_size: number
  file_sha256?: string
  parse_cache_hit?: boolean
  parse_cache_age_ms?: number
  preview_duration_ms?: number
  upload_duration_ms?: number
  parse_duration_ms?: number | null
  governance_duration_ms?: number
  chunking_duration_ms?: number
  stats_duration_ms?: number
  total_chunks: number
  total_chunks_full?: number
  chunks_truncated?: boolean
  chunks_max_count?: number
  total_characters: number
  params: ChunkPreviewParams
  chunks: ChunkPreviewItem[]
  stats?: ChunkPreviewStats
  auto_selected_strategy?: string
  warnings?: string[]
  review_signals?: ChunkPreviewReviewSignals
  quality_gate?: ChunkPreviewQualityGate
  recommendations?: string[]
  recommendation_patches?: ChunkPreviewRecommendationPatch[]
  original_text?: string
  original_text_cleaned?: string
  original_text_included?: boolean
  original_text_truncated?: boolean
  original_text_max_chars?: number
  parser_backend: string
  chunk_strategy: string
}

// ==================== 数据治理（清洗）相关类型 ====================

export interface RegexRuleModel {
  pattern: string
  repl?: string
  flags?: number
}

export interface CleanPreviewRuleStat {
  index: number
  pattern: string
  repl?: string
  flags?: number
  hits: number
  source?: string | null
  pack?: string | null
}

export interface CleanPreviewRequest {
  markdown: string
  rules?: RegexRuleModel[]
  rule_packs?: string[]
  use_default_rules?: boolean
  include_diff?: boolean
  diff_max_lines?: number
  input_format?: 'markdown' | 'html'
  html_xpath?: string
  normalize_line_endings?: boolean
  trim_trailing_spaces?: boolean
  collapse_blank_lines?: boolean
  max_blank_lines?: number
  remove_control_chars?: boolean
  remove_toc_lines?: boolean
  remove_noise_lines?: boolean
  remove_common_lines?: boolean
  unwrap_lines?: boolean
  remove_boilerplate?: boolean
  remove_images?: LooseString<'none' | 'decorative' | 'all'>
  extract_frontmatter?: boolean
  strip_frontmatter?: boolean
  detect_language?: boolean
  language_min_chars?: number
  normalize_urls?: boolean
  normalize_urls_strip_tracking?: boolean
  drop_duplicate_paragraphs?: boolean
  drop_duplicate_paragraphs_min_occurrences?: number
  drop_duplicate_paragraphs_min_chars?: number
  drop_duplicate_paragraphs_max_chars?: number
  trim_references?: boolean
  extract_keywords?: boolean
  keywords_provider?: string
  keywords_top_k?: number
  keywords_max_chars?: number
  normalize_tables?: boolean
  strip_code_line_numbers?: boolean
  pii_anonymize?: boolean
  pii_mode?: LooseString<'mask' | 'token'>
  pii_mask?: string
  secrets_redact?: boolean
  secrets_mode?: LooseString<'mask' | 'token'>
  secrets_mask?: string
  drop_outline_only?: boolean
  drop_outline_min_content_chars?: number
  drop_outline_max_heading_ratio?: number
  drop_low_density?: boolean
  drop_low_density_threshold?: number
  unwrap_max_line_length?: number
  noise_min_chars?: number
  noise_ratio_threshold?: number
  common_lines_min_occurrences?: number
}

export interface CleanPreviewResponse {
  markdown: string
  applied_rules: number
  changed: boolean
  rule_stats?: CleanPreviewRuleStat[]
  dropped?: boolean
  drop_reason?: string | null
  pii_hits?: Record<string, number> | null
  secrets_hits?: Record<string, number> | null
  frontmatter?: Record<string, unknown> | null
  title?: string | null
  tags?: string[] | null
  language?: string | null
  language_confidence?: number | null
  keywords?: string[] | null
  urls_changed?: number
  paragraphs_dropped?: number
  references_removed_lines?: number
  input_chars?: number
  output_chars?: number
  input_lines?: number
  output_lines?: number
  added_lines?: number
  removed_lines?: number
  changed_lines?: number
  diff_unified?: string | null
  diff_truncated?: boolean
  issues?: GovernanceIssue[]
  suggested_pipeline_patch?: DocumentPipelineOptions
}

export interface CleanRulesResponse {
  rules: RegexRuleModel[]
}

export interface GovernanceIssue {
  code: string
  severity: 'info' | 'warning' | 'error'
  message: string
  count?: number
  samples?: string[]
  suggested_pipeline_patch?: DocumentPipelineOptions
}

export interface GovernanceAnalyzeRequest {
  markdown: string
  input_format?: 'markdown' | 'html'
  html_xpath?: string
  remove_images?: 'none' | 'decorative' | 'all'
  remove_control_chars?: boolean
  unwrap_lines?: boolean
  remove_common_lines?: boolean
  remove_boilerplate?: boolean
  normalize_tables?: boolean
  normalize_urls?: boolean
  normalize_urls_strip_tracking?: boolean
  drop_outline_only?: boolean
  drop_outline_min_content_chars?: number
  drop_outline_max_heading_ratio?: number
  drop_low_density?: boolean
  drop_low_density_threshold?: number
}

export interface GovernanceAnalyzeResponse {
  input_chars?: number
  input_lines?: number
  issues?: GovernanceIssue[]
  suggested_pipeline_patch?: DocumentPipelineOptions
}

export interface GovernanceRulePackListResponse {
  items: string[]
}

// ==================== Governance (Lifecycle) ====================

export interface DocumentLifecycleMetadata {
  lifecycle_owner?: string | null
  review_due_at?: string | null
  authority_level?: number | null
  supersedes_document_id?: string | null
}

export interface DocumentLifecycleMetadataUpdateRequest {
  lifecycle_owner?: string | null
  review_due_at?: string | null
  authority_level?: number | null
  supersedes_document_id?: string | null
}

export interface StaleDocumentItem {
  id: string
  filename: string
  file_type: string
  status: string
  lifecycle_owner?: string | null
  review_due_at?: string | null
  authority_level?: number | null
  supersedes_document_id?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface StaleDocumentsByDatasetResponse {
  dataset_id: string
  as_of: string
  due_before: string
  mode: 'overdue' | 'due_soon' | 'all'
  skip: number
  limit: number
  total: number
  items: StaleDocumentItem[]
}

export interface GovernanceCommonLineCandidate {
  signature: string
  sample: string
  docs: number
  ratio: number
}

export interface GovernanceCommonLinesLearnRequest {
  dataset_id: string
  limit_docs?: number
  use_original?: boolean
  min_docs?: number
  min_ratio?: number
  max_line_length?: number
  max_candidates?: number
}

export interface GovernanceCommonLinesLearnResponse {
  dataset_id: string
  total_documents: number
  used_documents: number
  candidates: GovernanceCommonLineCandidate[]
}

export interface GovernanceProfilePayload {
  version: string
  extends?: string | null
  input_formats: Array<'markdown' | 'html'>
  pipeline_patch: DocumentPipelineOptions
  regex_rules: RegexRuleModel[]
}

export interface GovernanceProfileSummary {
  id?: string | null
  key: string
  name: string
  description?: string | null
  is_system: boolean
}

export interface GovernanceProfileListResponse {
  total: number
  items: GovernanceProfileSummary[]
}

export interface GovernanceProfileOut extends GovernanceProfileSummary {
  payload: GovernanceProfilePayload
  created_at?: string | null
  updated_at?: string | null
}

export interface GovernanceProfileCreate {
  name: string
  description?: string
  key?: string
  payload: GovernanceProfilePayload
}

export interface GovernanceProfileUpdate {
  name?: string
  description?: string
  payload?: GovernanceProfilePayload
}

export interface GovernanceProfileImportResponse {
  created: number
  updated: number
  items: GovernanceProfileSummary[]
}

export interface GovernanceProfileResolvedResponse {
  profile: GovernanceProfileOut
  chain: GovernanceProfileSummary[]
  effective: GovernanceProfilePayload
}

export interface LLMCleanPreviewRequest {
  markdown: string
  prompt_template_id?: string
  template_key?: string
  ab_experiment_key?: string
  ab_user_key?: string
  model?: string
  temperature?: number
  max_tokens?: number
  max_chars?: number
}

export interface LLMCleanPreviewResponse {
  markdown: string
  changed: boolean
  model_used?: string | null
  prompt_template_id?: string | null
  template_key?: string | null
  ab_experiment_key?: string | null
  ab_variant?: string | null
  warnings?: string[]
}

// ==================== 流水线能力（可用性）相关类型 ====================

export interface ParserBackendInfo {
  name: string
  available: boolean
  notes?: string | null
}

export interface ChunkStrategyInfo {
  name: string
  available: boolean
  notes?: string | null
}

export interface PipelineCapabilitiesResponse {
  default_parser_backend: string
  default_chunk_strategy: string
  pdf_backends: ParserBackendInfo[]
  chunk_strategies: ChunkStrategyInfo[]
}

// ==================== 流水线预览/工具相关类型 ====================

export interface PipelineParseImageInfo {
  id: string
  url: string
  filename: string
}

export interface PipelinePDFQualityScore {
  score: number
  text_quality_score: number
  format_consistency_score: number
  table_quality_score: number
  is_scanned: boolean
  page_count: number
}

export interface PipelineParsePreviewResponse {
  backend: string
  pdf_quality?: PipelinePDFQualityScore | null
  markdown: string
  images: PipelineParseImageInfo[]
}

export interface PipelineChunkItem {
  id: string
  level: string
  index: number
  text: string
  start: number
  end: number
  tokens_est: number
  parent_id?: string | null
}

export interface PipelineChunkPreviewRequest {
  markdown: string
}

export interface PipelineChunkPreviewResponse {
  paragraphs: PipelineChunkItem[]
  sentences: PipelineChunkItem[]
}

export interface KeywordExtractRequest {
  text: string
  provider?: string
  top_k?: number
}

export interface KeywordExtractResponse {
  provider: string
  keywords: string[]
}

export interface ZipImageInfo {
  img_id: string
  original_path: string
  url: string
}

export interface ZipWithImagesResponse {
  markdown: string
  images: ZipImageInfo[]
  image_count: number
  dataset_id: string
  document_id: string
}

// ==================== 入库策略（解析前预处理）相关类型 ====================

export interface IngestionPreprocessStep {
  id: string
  params?: Record<string, unknown>
}

export interface IngestionPreprocessConfig {
  enabled: boolean
  steps?: IngestionPreprocessStep[]
}

export interface IngestionRuleMatch {
  extensions?: string[]
  filename_regex?: string | null
}

export interface IngestionRule {
  id: string
  name: string
  enabled: boolean
  match?: IngestionRuleMatch
  preprocess?: IngestionPreprocessConfig
  parser_backend?: string | null
  chunk_strategy?: string | null
  governance_profile_ref?: string | null
  pipeline_patch?: Record<string, unknown>
}

export interface IngestionPolicy {
  version: string
  rules?: IngestionRule[]
}

export interface IngestionPolicyImportResponse {
  replaced: boolean
  rule_count: number
}

export interface IngestionPolicyVersion {
  id: string
  created_at: string
  created_by?: string | null
  source?: LooseString<'put' | 'import' | 'rollback'>
  policy: IngestionPolicy
  note?: string | null
  rollback_from_version_id?: string | null
  rollback_to_version_id?: string | null
}

export interface IngestionPolicyVersionListResponse {
  current_version_id?: string | null
  items?: IngestionPolicyVersion[]
}

export interface IngestionPolicyRollbackRequest {
  version_id: string
}

export interface PreprocessStepLog {
  id: string
  applied: boolean
  changed: boolean
  note?: string
}

export interface PreprocessSummary {
  changed: boolean
  size_before: number
  size_after: number
  steps: PreprocessStepLog[]
  warnings: string[]
}

export interface IngestionPreviewRule {
  matched: boolean
  rule_id?: string | null
  rule_name?: string | null
  governance_profile_ref?: string | null
  preprocess_steps: IngestionPreprocessStep[]
  parser_backend: string
  chunk_strategy: string
}

export interface IngestionPreviewResponse {
  rule: IngestionPreviewRule
  preprocess: PreprocessSummary
  parse: PipelineParsePreviewResponse
  clean: CleanPreviewResponse
  explain?: Record<string, unknown>
}

// ==================== 数据集相关类型 ====================

export interface Dataset {
  id: string
  tenant_id: string
  name: string
  description?: string | null
  permission: PermissionEnum
  owner_id?: string | null
  partial_member_list?: string[] | null
  partial_group_list?: string[] | null
  pipeline?: DocumentPipelineOptions | null
}

export interface DatasetCreate {
  name: string
  description?: string | null
  permission: PermissionEnum
  partial_member_list?: string[] | null
  partial_group_list?: string[] | null
  pipeline?: DocumentPipelineOptions | null
}

export interface DatasetUpdate {
  name?: string | null
  description?: string | null
  permission?: PermissionEnum | null
  partial_member_list?: string[] | null
  partial_group_list?: string[] | null
  pipeline?: DocumentPipelineOptions | null
}

export interface DatasetListResponse {
  total: number
  items: Dataset[]
}

export interface DatasetCategoryNode {
  id: string
  name: string
  parent_id?: string | null
  sort_order: number
  depth: number
  datasets: number
  children?: DatasetCategoryNode[]
}

export interface DatasetCategoryTreeResponse {
  total: number
  items: DatasetCategoryNode[]
}

export interface DatasetCategoryCreate {
  name: string
  parent_id?: string | null
  sort_order?: number | null
}

export interface DatasetCategoryUpdate {
  name?: string | null
  sort_order?: number | null
}

export interface DatasetCategoryMoveRequest {
  parent_id?: string | null
  sort_order?: number | null
}

export interface DatasetCategoryOut {
  id: string
  tenant_id: string
  name: string
  parent_id?: string | null
  sort_order: number
  created_at: string
  updated_at?: string | null
}

export interface DatasetCategoryAssignmentRequest {
  category_ids?: string[]
}

export interface DatasetCategoryAssignmentResponse {
  dataset_id: string
  category_ids?: string[]
}

export interface DatasetIngestionStats {
  dataset_id: string
  total_documents: number
  by_status?: Record<string, number>
  total_chunks: number
  total_size: number
  total_characters: number
  last_processed_at?: string | null
}

export interface DatasetHealthIngestionSummary {
  total_documents: number
  by_status?: Record<string, number>
  pending: number
  processing: number
  completed: number
  failed: number
  quarantined: number
  cancelled: number
}

export type DatasetHealthResponse = import('./backend').DatasetHealthResponse

export interface DatasetReportCompliance {
  pii_hits_total: Record<string, number>
  secrets_hits_total: Record<string, number>
  quarantined_documents: number
  failed_documents: number
}

export interface DatasetReportPipelineVersion {
  pipeline_hash: string
  documents: number
}

export interface DatasetReportConnectorRun {
  id: string
  connector_id: string
  status: string
  created_at: string
  finished_at?: string | null
  error_message?: string | null
  stats: Record<string, unknown>
}

export interface DatasetGovernanceMetrics {
  total_documents: number
  used_documents: number
  truncated: boolean
  docs_with_governance: number
  rules_applied_total: number
  changed_documents_total: number
  dropped_documents_total: number
  drop_reasons_total: Record<string, number>
  rule_packs_docs: Record<string, number>
}

export interface DatasetGovernanceAudit {
  total_documents: number
  used_documents: number
  truncated: boolean
  docs_with_parsed_content_persisted: number
  parsed_content_truncated_docs: number
  docs_with_char_stats: number
  original_chars_total: number
  cleaned_chars_total: number
  char_reduction_ratio: number
  char_reduction_pct_percentiles: DatasetProfilePercentiles
  char_reduction_pct_histogram: DatasetProfileHistogramBin[]
  docs_changed: number
  docs_dropped: number
  docs_with_governance_quality: number
  density_pct_percentiles: DatasetProfilePercentiles
  density_pct_histogram: DatasetProfileHistogramBin[]
  heading_ratio_pct_percentiles: DatasetProfilePercentiles
  heading_ratio_pct_histogram: DatasetProfileHistogramBin[]
  paragraphs_dropped_total: number
  references_removed_lines_total: number
  urls_changed_total: number
  boilerplate_removed_sections_total: number
  boilerplate_removed_lines_total: number
  images_removed_total: number
  tables_normalized_total: number
  table_rows_changed_total: number
  code_lines_stripped_total: number
}

export interface DatasetReport {
  dataset_id: string
  dataset_name?: string | null
  pipeline_hash?: string | null
  generated_at: string
  profile: DatasetProfileSummary
  compliance: DatasetReportCompliance
  pipeline_versions: DatasetReportPipelineVersion[]
  connectors: DatasetReportConnectorRun[]
  dataset_metadata: Record<string, unknown>
  folder_tree?: DocumentFolderTreeResponse | null
  governance_metrics?: DatasetGovernanceMetrics | null
  governance_audit?: DatasetGovernanceAudit | null
}

export interface DatasetConfigBundle {
  default_parser_backend?: string | null
  default_chunk_strategy?: string | null
  rag_defaults?: Record<string, unknown> | null
  default_prompt_template_id?: string | null
  default_prompt_template_key?: string | null
  default_prompt_ab_experiment_key?: string | null
  pipeline?: DocumentPipelineOptions | null
  ingestion_policy?: IngestionPolicy | null
  workflow_layout?: Record<string, unknown> | null
}

export interface DatasetConfigExport {
  version: string
  dataset_id: string
  name: string
  exported_at: string
  config: DatasetConfigBundle
}

export interface DatasetConfigImportRequest {
  config: DatasetConfigBundle
  replace: boolean
}

export interface DatasetCloneRequest {
  name: string
  description?: string | null
  copy_permission: boolean
  copy_partial_members: boolean
}

// ==================== 对话相关类型 ====================

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  steps?: string[]
  message_metadata?: Record<string, unknown> | null
  created_at: string
}

export interface Conversation {
  id: string
  title?: string
  last_message?: string
  message_count: number
  created_at: string
  updated_at: string
}

export interface ConversationListResponse {
  total: number
  returned?: number
  has_more?: boolean
  items: Conversation[]
}

export interface ConversationDetail {
  conversation_id: string
  returned?: number
  has_more?: boolean
  messages: Message[]
}

// ==================== RAG Trace (Visualization) ====================

export interface RagTraceStep {
  key: string
  label: string
  elapsed_sec?: number | null
  meta?: Record<string, unknown>
}

export interface RagTraceCitation {
  document_id?: string | null
  chunk_id?: string | null
  chunk_index?: number | null
  page_number?: number | null
  start_char?: number | null
  end_char?: number | null

  retrieval_role?: string | null
  neighbor_of?: string | null

  doc_pipeline_key?: string | null
  pipeline_hash?: string | null

  relevance_score?: number | null
  vector_score?: number | null
  bm25_score?: number | null
  lexical_score?: number | null
  sparse_score?: number | null
  colbert_score?: number | null
  keyword_score?: number | null
  rerank_score?: number | null
  retrieval_score?: number | null

  reranker_provider?: string | null
  rerank_elapsed_sec?: number | null
  rerank_model_used?: string | null

  retrieval_mode?: string | null
  vector_backend?: string | null
  retrieval_elapsed_sec?: number | null
  hit_type?: string | null

  has_image?: boolean

  kg_path?: Array<{ entity_id: string; type?: string }> | null
  kg_path_provenance?: Record<string, unknown> | null
}

export interface RagTraceRetrievalQuery {
  kind?: string | null
  query_chars?: number | null
  elapsed_sec?: number | null
  ok?: boolean | null
  retriever_debug?: JsonObject | null
}

export interface RagTraceRetrieval {
  mode?: string | null
  requested_mode?: string | null
  auto_routed?: boolean | null

  retrieval_config_hash?: string | null

  top_k?: number | null
  query_parallelism?: number | null
  query_count?: number | null

  per_query?: RagTraceRetrievalQuery[]
  errors?: string[]

  enable_reranker?: boolean | null
  reranker_provider?: string | null
  reranker_top_n?: number | null

  elapsed_sec?: number | null
}

export interface RagTraceRerank {
  enabled: boolean
  provider?: string | null
  top_n?: number | null
  elapsed_sec?: number | null
  model_used?: string | null
}

export interface RagTrace {
  schema_version: number
  ts_ms: number
  request_id?: string | null
  conversation_id?: string | null
  retrieval: RagTraceRetrieval
  rerank: RagTraceRerank
  citations: RagTraceCitation[]
  citations_count: number
  steps: RagTraceStep[]
}

export interface RagTraceListResponse {
  enabled: boolean
  path: string
  window_minutes: number
  truncated: boolean
  returned: number
  items: RagTrace[]
}

export interface StreamEvent {
  type: 'citations' | 'token' | 'done' | 'error' | 'route' | 'rewrite' | 'graph' | 'event'
  data: unknown
  request_id?: string
}

export interface ChatHistoryMessage {
  role: LooseString<'user' | 'assistant'>
  content: string
}

export interface ChatRequest {
  conversation_id?: string
  message: string
  history?: ChatHistoryMessage[]
  document_ids?: string[]
  stream: boolean
  structured_output?: boolean
  structured_preset?: LooseString<'faq' | 'summary' | 'action_items' | 'custom'> | null
  enable_long_term_memory?: boolean
  enable_summary_memory?: boolean
  prompt_template_id?: string
  prompt_template_key?: string
  prompt_ab_experiment_key?: string
  rag_config?: {
    retrieval_profile?: string
    top_k?: number
    score_threshold?: number
    max_tokens?: number
    retrieval_mode?: LooseString<'auto' | 'hybrid' | 'vector' | 'keyword' | 'mmr'>
    alpha?: number
    enable_weight_rerank?: boolean
    vector_weight?: number
    keyword_weight?: number
    mmr_lambda?: number
    enable_reranker?: boolean
    reranker_provider?: string
    reranker_top_n?: number
    use_graph?: boolean
    metadata_filter?: JsonObject
  }
}

export interface ConversationSummaryResponse {
  available: boolean
  summary?: string | null
}

export interface ConversationSummaryUpdateResponse {
  summary: string
}

// ==================== Usage / Quotas ====================

export interface ChatTokenUsageRow {
  dataset_id?: string | null
  assistant_messages: number
  assistant_tokens: number
}

export interface ChatTokenUsageSummary {
  window_start: string
  window_end: string
  total_assistant_messages: number
  total_assistant_tokens: number
  by_dataset: ChatTokenUsageRow[]
}

export interface ChatCostUsageRow {
  dataset_id?: string | null
  assistant_messages: number
  llm_prompt_tokens: number
  llm_completion_tokens: number
  llm_total_tokens: number
  embedding_query_tokens: number
  embedding_query_chars: number
  retrieval_elapsed_sec_sum: number
  rerank_elapsed_sec_sum: number
}

export interface ChatCostUsageSummary {
  window_start: string
  window_end: string
  total_assistant_messages: number
  total_llm_prompt_tokens: number
  total_llm_completion_tokens: number
  total_llm_total_tokens: number
  total_embedding_query_tokens: number
  total_embedding_query_chars: number
  total_retrieval_elapsed_sec: number
  total_rerank_elapsed_sec: number
  by_dataset: ChatCostUsageRow[]
}

export interface ChatTokenQuotaStatus {
  enabled: boolean
  mode: string
  limit: number
  used: number
  remaining: number
  exceeded: boolean
  window_hours: number
  window_start: string
  window_end: string
}

export interface TenantDocumentQuotaStatus {
  enabled: boolean
  limit: number
  used: number
  remaining: number
  exceeded: boolean
}

export interface TenantStorageQuotaStatus {
  enabled: boolean
  limit_bytes: number
  used_bytes: number
  remaining_bytes: number
  exceeded: boolean
}

export interface TenantEmbeddingCharQuotaStatus {
  enabled: boolean
  mode: string
  limit_chars: number
  used_chars: number
  remaining_chars: number
  exceeded: boolean
  window_hours: number
  window_start: string
  window_end: string
}

export interface TenantQpsQuotaConfig {
  enabled: boolean
  mode: string
  rps: number
  burst: number
}

export interface TenantQuotaSummary {
  documents: TenantDocumentQuotaStatus
  storage: TenantStorageQuotaStatus
  embedding_chars: TenantEmbeddingCharQuotaStatus
  qps: TenantQpsQuotaConfig
}

// ==================== Audit Logs ====================

export interface AuditLogItem {
  id: string
  tenant_id: string
  actor_id?: string | null
  action: string
  resource_type?: string | null
  resource_id?: string | null
  request_id?: string | null
  ip?: string | null
  user_agent?: string | null
  details: JsonObject
  created_at: string
}

export interface AuditLogListResponse {
  total: number
  items: AuditLogItem[]
}

export interface ChatResponse {
  conversation_id: string
  assistant_message_id: string
  request_id: string
  content: string
  citations: Citation[]
  total_tokens: number
  total_chars: number
  retrieval_mode?: string | null
  vector_backend?: string | null
  confidence_score?: number | null
  followup_questions?: string[]
  metrics: JsonObject
  structured: boolean
  structured_data?: unknown
}

export interface CheckpointItem {
  checkpoint_id?: string | null
  checkpoint_ns?: string
  created_at?: string | null
  next?: unknown
  metadata?: JsonObject | null
  values?: JsonObject | null
}

export interface CheckpointListResponse {
  thread_id: string
  items: CheckpointItem[]
}

export interface CheckpointDetailResponse {
  thread_id: string
  checkpoint_id?: string | null
  checkpoint_ns?: string
  created_at?: string | null
  next?: unknown
  metadata?: JsonObject | null
  values?: JsonObject | null
}

// ==================== 反馈相关类型 ====================

export interface MessageFeedback {
  id: string
  tenant_id: string
  conversation_id: string
  message_id: string
  account_id: string
  rating: number
  reason?: string
  tags: string[]
  expected_answer?: string
  extra?: JsonObject
  created_at: string
  updated_at: string
}

export interface MessageFeedbackCreate {
  message_id: string
  rating: number
  reason?: string
  tags?: string[]
  expected_answer?: string
  extra?: JsonObject
}

export interface MessageFeedbackListResponse {
  total: number
  items: MessageFeedback[]
}

export interface MessageFeedbackEnriched extends MessageFeedback {
  conversation_title?: string
  message_content?: string
  message_created_at?: string
}

export interface MessageFeedbackEnrichedListResponse {
  total: number
  items: MessageFeedbackEnriched[]
}

// ==================== Auth ====================

export type UserProfile = import('./backend').UserProfile
export type AuthToken = import('./backend').AuthToken
export type AuthResponse = import('./backend').AuthResponse
export type RegisterRequest = import('./backend').RegisterRequest
export type LoginRequest = import('./backend').LoginRequest

// ==================== Health ====================

export type HealthResponse = import('./backend').HealthResponse
export type ReadyResponse = import('./backend').ReadyResponse
export type MetaResponse = import('./backend').MetaResponse

// ==================== KG 相关类型 ====================

export interface KGExtractResponse {
  document_id: string
  chunk_count: number
  event_count: number
  message: string
}

export interface KGSearchRequest {
  query: string
  tenant_id?: string
  document_ids?: string[]
}

export interface KGSearchResponse {
  result: JsonObject
  query: string
}

export interface KGGraphNode {
  id: string
  label: string
  group?: number
  val?: number
  meta?: JsonObject
}

export interface KGGraphLink {
  source: string
  target: string
  label?: string
  weight?: number
  meta?: JsonObject
}

export interface KGGraphResponse {
  nodes: KGGraphNode[]
  links: KGGraphLink[]
  stats?: JsonObject
}

export interface KGEntityItem {
  id: string
  name: string
  type: string
  normalized_name: string
  description?: string | null
  extra_data?: JsonObject
  created_at?: string | null
  updated_at?: string | null
}

export interface KGEventItem {
  id: string
  title: string
  summary: string
  content: string
  document_id?: string | null
  chunk_id?: string | null
  references?: JsonObject
  extra_data?: JsonObject
  created_at?: string | null
  updated_at?: string | null
}

export interface KGEventEntityItem {
  entity: KGEntityItem
  weight?: number
  role?: string | null
}

export interface KGEventDetailResponse {
  event: KGEventItem
  entities: KGEventEntityItem[]
}

export interface KGEntityNeighbor {
  entity_id: string
  name: string
  type: string
  count: number
}

export interface KGEntityDetailResponse {
  entity: KGEntityItem
  events: KGEventItem[]
  neighbors: KGEntityNeighbor[]
  stats?: JsonObject
}

export interface KGEntityTypeCount {
  type: string
  count: number
}

export interface KGStatsResponse {
  events: number
  entities: number
  links: number
  entity_types: KGEntityTypeCount[]
  updated_at?: string | null
}

export interface KGDeleteResponse {
  document_id: string
  events_deleted: number
  entities_pruned: number
}

export interface KGEntityMergeRequest {
  source_entity_id: string
  target_entity_id: string
}

export interface KGEntityMergePreviewResponse {
  source_entity_id: string
  target_entity_id: string
  stats?: JsonObject
}

export interface KGEntityMergeResponse {
  action_id: string
  source_entity_id: string
  target_entity_id: string
  stats?: JsonObject
}

export interface KGEntityResolutionUndoResponse {
  action_id: string
  status: string
  stats?: JsonObject
}

export interface KGEntitySplitRequest {
  entity_id: string
  new_entity_name: string
  event_ids: string[]
}

export interface KGEntitySplitResponse {
  action_id: string
  original_entity_id: string
  new_entity_id: string
  stats?: JsonObject
}

export interface KGEntityAliasCreateRequest {
  alias: string
}

export interface KGEntityAliasItem {
  id: string
  canonical_entity_id: string
  alias: string
  normalized_alias: string
  created_by?: string | null
  extra_data?: JsonObject
  created_at?: string | null
  updated_at?: string | null
}

export interface KGEntityAliasesResponse {
  entity_id: string
  resolved_entity_id: string
  aliases: KGEntityAliasItem[]
}

export interface KGEntityAliasSuggestionItem {
  entity_id: string
  name: string
  type: string
  similarity: number
  reason?: string
}

export interface KGEntityAliasSuggestionsResponse {
  entity_id: string
  suggestions: KGEntityAliasSuggestionItem[]
  mode?: string
  stats?: JsonObject
}

export interface KGPredicateOntologyItem {
  id: string
  tenant_id: string
  predicate: string
  display_name?: string | null
  description?: string | null
  is_enabled: boolean
  extra_data?: JsonObject
  created_at?: string | null
  updated_at?: string | null
}

export interface KGPredicateOntologyCreateRequest {
  predicate: string
  display_name?: string | null
  description?: string | null
  is_enabled?: boolean
}

export interface KGPredicateOntologyUpdateRequest {
  display_name?: string | null
  description?: string | null
  is_enabled?: boolean | null
}

export interface KGPredicateOntologyListResponse {
  predicates: KGPredicateOntologyItem[]
}

// ==================== RAG 调试相关类型 ====================

export type RetrievePreviewRequest = import('./backend').RetrievePreviewRequest
export type RetrievePreviewResponse = import('./backend').RetrievePreviewResponse
export type EvidenceRetrieveRequest = import('./backend').EvidenceRetrieveRequest
export type EvidenceRetrieveResponse = import('./backend').EvidenceRetrieveResponse
export type PromptPreviewRequest = import('./backend').PromptPreviewRequest
export type PromptPreviewResponse = import('./backend').PromptPreviewResponse

// ==================== 批量上传相关类型 ====================

export interface BatchFileInfo {
  name: string
  data_id: string
}

export interface BatchUploadRequest {
  files: BatchFileInfo[]
}

export interface BatchUploadResponse {
  batch_id: string
  file_urls: string[]
  files: BatchFileInfo[]
  message: string
}

export interface BatchTaskStatus {
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

export interface ReferenceSource {
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

export interface RegressionCase {
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

export interface RegressionCaseCreate {
  question: string
  dataset_id?: string
  document_ids?: string[]
  expected_answer?: string
  reference_sources?: ReferenceSource[]
  tags?: string[]
  extra?: JsonObject
}

export interface RegressionCasePatch {
  question?: string
  document_ids?: string[]
  expected_answer?: string | null
  reference_sources?: ReferenceSource[]
  tags?: string[]
  extra?: JsonObject
}

export interface RegressionCaseBundleItem {
  question: string
  expected_answer?: string | null
  tags: string[]
  reference_sources: ReferenceSource[]
}

export interface RegressionCaseBundleV1 {
  schema: 'mimirq.regression_cases.v1'
  dataset_id: string
  items: RegressionCaseBundleItem[]
}

export interface RegressionCaseImportResponse {
  created: number
  updated: number
  skipped: number
  errors: JsonObject[]
}

export interface RegressionCaseList {
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

export interface GeneratedQuestion {
  question: string
  expected_answer?: string
  context?: string
  source_type: 'document' | 'conversation'
  source_id: string
  metadata: JsonObject
}

export interface TestGenFromDocsRequest {
  dataset_id?: string
  document_ids?: string[]
  num_questions?: number
  question_types?: string[]
  auto_save_as_cases?: boolean
}

export interface TestGenFromConversationsRequest {
  conversation_ids: string[]
  num_questions?: number
  quality_threshold?: number
  auto_save_as_cases?: boolean
}

export interface TestGenResponse {
  status: string
  generated_questions: GeneratedQuestion[]
  saved_case_ids: string[]
  error_message?: string
}

export interface RegressionRun {
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

export interface RegressionRunCreate {
  case_ids?: string[]
  dataset_id?: string
  metrics?: string[]
  use_llm_judge?: boolean
  skip_empty_contexts?: boolean
  max_cases?: number
  top_k?: number
  score_threshold?: number
  retrieval_mode?: string
  alpha?: number
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

export interface RegressionRunList {
  total: number
  items: RegressionRun[]
}

export interface RegressionItem {
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

export interface RegressionRunDetail {
  run: RegressionRun
  items: RegressionItem[]
}

export interface RegressionRunMetricDiff {
  key: string
  before?: unknown
  after?: unknown
  delta?: number | null
}

export interface RegressionRunDiffScore {
  version: string
  used_metric_keys: string[]
  weights: Record<string, number>
  base_score?: number | null
  target_score?: number | null
  delta?: number | null
  base_metrics: Record<string, number>
  target_metrics: Record<string, number>
}

export interface RegressionRunSliceBucketDiff {
  key: string
  items_before: number
  items_after: number
  metrics: RegressionRunMetricDiff[]
}

export interface RegressionRunSliceDiff {
  truncated_before: boolean
  truncated_after: boolean
  buckets: RegressionRunSliceBucketDiff[]
}

export interface RagasRegressionRunDiffResponse {
  base_run_id: string
  target_run_id: string
  generated_at: string
  base_params: JsonObject
  target_params: JsonObject
  metric_diffs: RegressionRunMetricDiff[]
  diff_score?: RegressionRunDiffScore | null
  slice_diffs: Record<string, RegressionRunSliceDiff>
}

// ==================== RAGViz（相似度热力图） ====================

export interface RagvizSimilarityCollection {
  id: string
  label: string
  kind: string
  count: number
  meta?: JsonObject
}

export interface RagvizSimilarityCollectionsResponse {
  success: boolean
  collections: RagvizSimilarityCollection[]
  count: number
}

export interface RagvizSimilarityRequest {
  x_collection: string
  y_collection: string
  x_max_items?: number
  y_max_items?: number
  max_items?: number
}

export interface RagvizSimilarityStats {
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

export interface RagvizSimilarityMatrixResult {
  matrix: number[][]
  x_data: JsonObject[]
  y_data: JsonObject[]
  x_available_fields: string[]
  y_available_fields: string[]
  stats: RagvizSimilarityStats
  metadata: JsonObject
}

export interface RagvizSimilarityCalculateResponse {
  success: boolean
  result?: RagvizSimilarityMatrixResult
  message?: string
  error?: string
  error_type?: string
  x_collection?: string
  y_collection?: string
}

// ==================== Dataset Profile (Ingestion Scan) ====================

export type DatasetProfileFindingSeverity = 'info' | 'warning' | 'error'

export interface DatasetProfileHistogramBin {
  label: string
  min?: number | null
  max?: number | null
  count: number
}

export interface DatasetProfilePercentiles {
  p25: number
  p50: number
  p75: number
  p90: number
  p99: number
}

export interface DatasetProfilePdfScanStats {
  scanned: number
  not_scanned: number
  unknown: number
}

export interface DatasetProfileParsingProvenanceStats {
  docs_with_provenance: number
  by_resolved_backend: Record<string, number>
  fallback_docs: number
  elapsed_ms_percentiles: DatasetProfilePercentiles
}

export type DatasetProfileTargetCheckStatus = 'pass' | 'warn' | 'fail'

export interface DatasetProfileTargetCheck {
  key: string
  label: string
  status: DatasetProfileTargetCheckStatus
  observed: JsonObject
  target: JsonObject
  message?: string | null
  suggestions: string[]
}

export interface DatasetProfileFindingSummary {
  key: string
  label: string
  severity: DatasetProfileFindingSeverity
  count: number
  description?: string | null
}

export interface DatasetProfileScanRunSummary {
  id: string
  kind: string
  status: string
  progress: number
  requested_by?: string | null
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
  error_message?: string | null
}

export interface DatasetProfileSummary {
  dataset_id: string
  generated_at: string

  total_documents: number
  total_size_bytes: number
  by_status: Record<string, number>
  by_file_type: Record<string, number>
  by_directory?: Record<string, number>
  by_quality_bucket?: Record<string, number>

  file_size_histogram: DatasetProfileHistogramBin[]
  length_percentiles: DatasetProfilePercentiles
  length_histogram: DatasetProfileHistogramBin[]
  chunk_count_percentiles?: DatasetProfilePercentiles
  chunk_count_histogram?: DatasetProfileHistogramBin[]
  avg_chunk_chars_percentiles?: DatasetProfilePercentiles
  avg_chunk_chars_histogram?: DatasetProfileHistogramBin[]
  chunk_length_percentiles?: DatasetProfilePercentiles
  chunk_length_histogram?: DatasetProfileHistogramBin[]
  chunk_token_percentiles?: DatasetProfilePercentiles
  chunk_token_histogram?: DatasetProfileHistogramBin[]
  avg_chunk_tokens_percentiles?: DatasetProfilePercentiles
  avg_chunk_tokens_histogram?: DatasetProfileHistogramBin[]
  chunk_coverage_percentiles?: DatasetProfilePercentiles
  chunk_coverage_histogram?: DatasetProfileHistogramBin[]
  chunk_overlap_waste_percentiles?: DatasetProfilePercentiles
  chunk_overlap_waste_histogram?: DatasetProfileHistogramBin[]
  page_number_histogram?: DatasetProfileHistogramBin[]
  parse_quality_histogram?: DatasetProfileHistogramBin[]
  language_mix?: Record<string, number>
  pdf_scan: DatasetProfilePdfScanStats
  parsing_provenance?: DatasetProfileParsingProvenanceStats

  pii_hits_total: Record<string, number>
  secrets_hits_total: Record<string, number>

  findings: DatasetProfileFindingSummary[]
  chunk_targets?: DatasetProfileTargetCheck[]
  latest_scan_run?: DatasetProfileScanRunSummary | null
}

export interface DatasetProfileDocumentOut {
  id: string
  dataset_id?: string | null
  filename: string
  file_type: string
  file_size: number
  status: string
  chunk_count: number
  total_characters: number
  created_at?: string | null
  updated_at?: string | null
  error_message?: string | null
  metadata: JsonObject
  preview?: string | null
  preview_truncated?: boolean
}

export interface DatasetProfileFindingListResponse {
  total: number
  items: DatasetProfileDocumentOut[]
}

export interface DatasetProfileDocumentListResponse {
  total: number
  items: DatasetProfileDocumentOut[]
}

export interface DatasetProfileScanRunCreateRequest {
  backfill_pdf_quality?: boolean
  backfill_text_quality?: boolean
  backfill_chunk_stats?: boolean
  compute_file_hash?: boolean
  max_documents?: number | null
}

export interface DatasetProfileScanRunOut {
  id: string
  tenant_id: string
  dataset_id: string
  requested_by?: string | null
  kind: string
  status: string
  progress: number
  config: JsonObject
  summary: JsonObject
  error_message?: string | null
  started_at?: string | null
  finished_at?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface DatasetProfileScanRunListResponse {
  total: number
  items: DatasetProfileScanRunOut[]
}

// ==================== Dataset Precheck (Local Folder Scan) ====================

export type DatasetPrecheckFindingSeverity = 'info' | 'warning' | 'error'

export interface DatasetPrecheckHistogramBin {
  label: string
  min?: number | null
  max?: number | null
  count: number
}

export interface DatasetPrecheckPercentiles {
  p25: number
  p50: number
  p75: number
  p90: number
  p99: number
}

export interface DatasetPrecheckPdfScanStats {
  scanned: number
  not_scanned: number
  unknown: number
}

export interface DatasetPrecheckPdfPageBreakdown {
  page_count: number
  sampled_pages: number
  scanned_pages: number
  text_pages: number
  low_density_pages: number
  unknown_pages: number
  scan_ratio: number
  low_density_ratio: number
}

export interface DatasetPrecheckSpreadsheetStats {
  row_count: number
  col_count: number
  sheet_count: number
  merged_cell_ratio: number
  estimated_rows: boolean
  estimated_cols: boolean
}

export interface DatasetPrecheckMatchSample {
  kind: string
  masked: string
  context: string
  start?: number | null
  end?: number | null
}

export interface DatasetPrecheckFindingSummary {
  key: string
  label: string
  severity: DatasetPrecheckFindingSeverity
  count: number
  description?: string | null
}

export interface DatasetPrecheckSummary {
  dataset_id: string
  scan_run_id: string
  generated_at: string

  total_files: number
  total_size_bytes: number
  reused_files?: number
  by_file_type: Record<string, number>

  file_size_histogram: DatasetPrecheckHistogramBin[]
  length_percentiles: DatasetPrecheckPercentiles
  length_histogram: DatasetPrecheckHistogramBin[]

  pdf_scan: DatasetPrecheckPdfScanStats
  pdf_detection?: JsonObject

  pii_hits_total: Record<string, number>
  secrets_hits_total: Record<string, number>

  findings: DatasetPrecheckFindingSummary[]
}

export interface DatasetPrecheckFileOut {
  name: string
  file_type: string
  file_size: number
  file_mtime?: number | null
  text_characters: number
  estimated_text: boolean
  pdf_scanned?: boolean | null
  pdf_pages?: DatasetPrecheckPdfPageBreakdown | null
  spreadsheet?: DatasetPrecheckSpreadsheetStats | null
  text_simhash64?: string | null
  pii_hits: Record<string, number>
  secrets_hits: Record<string, number>
  pii_samples?: DatasetPrecheckMatchSample[]
  secrets_samples?: DatasetPrecheckMatchSample[]
  file_sha256?: string | null
  findings: string[]
  error_message?: string | null
}

export interface DatasetPrecheckFindingListResponse {
  total: number
  items: DatasetPrecheckFileOut[]
}

export interface DatasetPrecheckScanRunCreateRequest {
  root_path: string
  max_files?: number | null
  enable_pdf_quality?: boolean
  enable_text_extract?: boolean
  enable_pii?: boolean
  enable_secrets?: boolean
  compute_file_hash?: boolean
  pdf_sample_pages?: number | null
  text_extract_max_bytes?: number | null
  redact_paths?: boolean

  enable_pii_samples?: boolean
  pii_context_chars?: number | null
  pii_max_samples_per_file?: number | null

  enable_secrets_samples?: boolean
  secrets_context_chars?: number | null
  secrets_max_samples_per_file?: number | null

  pdf_min_text_chars_per_page?: number | null
  pdf_text_chars_per_page?: number | null
  pdf_scan_ratio_threshold?: number | null

  enable_near_dup?: boolean
  near_dup_hamming_threshold?: number | null
  near_dup_max_pairs?: number | null

  enable_sampling?: boolean
  sample_size?: number | null

  reuse_unchanged_files?: boolean
  reuse_from_scan_run_id?: string | null
}

export interface DatasetPrecheckScanRunOut {
  id: string
  tenant_id: string
  dataset_id: string
  requested_by?: string | null
  kind: string
  status: string
  progress: number
  config: JsonObject
  summary: JsonObject
  artifacts: JsonObject
  error_message?: string | null
  started_at?: string | null
  finished_at?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface DatasetPrecheckScanRunListResponse {
  total: number
  items: DatasetPrecheckScanRunOut[]
}

export interface DatasetPrecheckSamplesResponse {
  requested: number
  strata_count: number
  representative: DatasetPrecheckFileOut[]
  needs_review: Record<string, DatasetPrecheckFileOut[]>
  top_large_files: DatasetPrecheckFileOut[]
  top_long_text: DatasetPrecheckFileOut[]
}

export interface DatasetPrecheckNearDupCluster {
  id: string
  members: string[]
}

export interface DatasetPrecheckNearDupPair {
  a: string
  b: string
  distance: number
}

export interface DatasetPrecheckNearDupResponse {
  threshold: number
  max_pairs: number
  pairs_returned: number
  clusters_returned: number
  clusters: DatasetPrecheckNearDupCluster[]
  pairs: DatasetPrecheckNearDupPair[]
}

export interface DatasetPrecheckDiffItem {
  key: string
  before: number
  after: number
  delta: number
}

export interface DatasetPrecheckDiffResponse {
  base_scan_run_id: string
  target_scan_run_id: string
  generated_at: string
  total_files: DatasetPrecheckDiffItem
  total_size_bytes: DatasetPrecheckDiffItem
  pdf_scanned: DatasetPrecheckDiffItem
  pdf_unknown: DatasetPrecheckDiffItem
  by_file_type: DatasetPrecheckDiffItem[]
  findings: DatasetPrecheckDiffItem[]
}

export interface DatasetPrecheckManualReviewBucket {
  key: string
  total: number
  sample_names: string[]
}

export interface DatasetPrecheckIngestionSuggestionResponse {
  generated_at: string
  policy: IngestionPolicy
  notes: string[]
  manual_review: DatasetPrecheckManualReviewBucket[]
}

// ==================== Dataset Tables (TAG) ====================

export interface DatasetTableColumn {
  name: string
  dtype?: string | null
}

export interface DatasetTableAsset {
  table_id: string
  document_id: string
  document_filename?: string | null
  sheet_index: number
  sheet_name?: string | null
  row_count: number
  col_count: number
  truncated: boolean
  columns: DatasetTableColumn[]
  sample_rows: JsonObject[]
}

export interface DatasetTablesListResponse {
  total: number
  items: DatasetTableAsset[]
}

export interface TableQueryRequest {
  sql: string
  max_rows?: number | null
  max_cols?: number | null
}

export interface TableQueryResponse {
  sql: string
  columns: string[]
  rows: unknown[][]
  truncated: boolean
}

export interface TableAskRequest {
  question: string
  max_rows?: number | null
}

export interface TableAskResponse {
  answer: string
  sql?: string | null
  data?: TableQueryResponse | null
}

export interface LotusSemFilterRequest {
  user_instruction: string
  strategy?: string
  max_rows?: number | null
}

// ==================== DB Catalog (SQL) ====================

export interface DbCatalogColumn {
  id: string
  table_id: string
  ordinal: number
  name: string
  data_type?: string | null
  nullable?: boolean | null
  comment?: string | null
  created_at: string
}

export interface DbCatalogTableSummary {
  id: string
  connector_config_id?: string | null
  engine: string
  db_name: string
  schema_name?: string | null
  table_name: string
  table_type: string
  comment?: string | null
  fingerprint: string
  last_seen_at?: string | null
  created_at: string
  updated_at?: string | null
}

export interface DbCatalogTableDetail extends DbCatalogTableSummary {
  columns: DbCatalogColumn[]
}

export interface DbCatalogTablesListResponse {
  total: number
  items: DbCatalogTableSummary[]
}

export interface DbProfileSnapshot {
  id: string
  table_id: string
  entitlement_hash: string
  profile: JsonObject
  sample_meta: JsonObject
  created_at: string
}

export interface DbProfileSnapshotListResponse {
  total: number
  items: DbProfileSnapshot[]
}
