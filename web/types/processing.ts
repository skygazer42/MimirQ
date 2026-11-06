/**
 * Processing, chunk preview, governance, and ingestion types re-exported by `@/types`.
 */

import type { JsonObject, LooseString } from './common'

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

export type Citation = {
  document_id: string
  document_name: string
  chunk_id?: string
  chunk_content: string
  matched_terms?: string[]
  page_number?: number
  bbox?: { x0: number; y0: number; x1: number; y1: number }
  bbox_page_number?: number
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

export type ParsedSegment = {
  index: number
  content: string
  page_number?: number
  metadata?: JsonObject
}

export type DocumentPreview = {
  filename: string
  file_type: string
  file_size: number
  segments: ParsedSegment[]
  parser_backend: string
}

export type DocumentParsedContentResponse = import('./backend').DocumentParsedContentResponse

export type ManualChunk = {
  content: string
  page_number?: number
  start_char?: number
  end_char?: number
  metadata?: JsonObject
}

// ==================== 切块预览相关类型 ====================

export type ChunkPreset = {
  id: string
  name: string
  description?: string | null
  payload: JsonObject
}

export type ChunkPresetCreateRequest = {
  name: string
  description?: string | null
  payload: JsonObject
}

export type ChunkPresetUpdateRequest = {
  name: string
  description?: string | null
  payload: JsonObject
}

export type ChunkPresetListResponse = {
  items: ChunkPreset[]
}

export type ChunkPreviewParams = {
  chunk_size: number
  chunk_overlap: number
  unit?: 'chars' | 'tokens'
  strategy_params?: JsonObject
}

export type ChunkPreviewItem = {
  index: number
  content: string
  length: number
  tokens_est?: number
  start_index: number
  end_index: number
  page_number?: number
  metadata?: JsonObject
}

export type ChunkPreviewHistogramBin = {
  label: string
  min?: number | null
  max?: number | null
  count: number
}

export type ChunkPreviewStats = {
  unit?: 'chars' | 'tokens'
  count?: number
  total?: number
  min?: number
  max?: number
  avg?: number
  median?: number
  p10?: number
  p90?: number
  p95?: number
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

export type ChunkPreviewQualityReason = {
  code: string
  severity?: 'info' | 'warning' | 'error'
  message: string
  meta?: JsonObject
}

export type ChunkPreviewQualityGate = {
  grade?: 'pass' | 'warn' | 'fail'
  reasons?: string[]
  reason_items?: ChunkPreviewQualityReason[]
}

export type ChunkPreviewRecommendationPatch = {
  target?: 'preview' | 'pipeline' | 'perf'
  id: string
  title: string
  description?: string
  patch?: JsonObject
}

export type ChunkPreviewReviewSignals = {
  basis?: 'all' | 'child'
  short_indices?: number[]
  duplicate_indices?: number[]
  gap_indices?: number[]
  overlap_indices?: number[]
  gap_before_by_index?: Record<string, number>
  overlap_prev_by_index?: Record<string, number>
}

export type ChunkPreviewResponse = {
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

export type RegexRuleModel = {
  pattern: string
  repl?: string
  flags?: number
}

export type CleanPreviewRuleStat = {
  index: number
  pattern: string
  repl?: string
  flags?: number
  hits: number
  source?: string | null
  pack?: string | null
}

export type CleanPreviewRequest = {
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

export type CleanPreviewResponse = {
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

export type CleanRulesResponse = {
  rules: RegexRuleModel[]
}

export type GovernanceIssue = {
  code: string
  severity: 'info' | 'warning' | 'error'
  message: string
  count?: number
  samples?: string[]
  suggested_pipeline_patch?: DocumentPipelineOptions
}

export type GovernanceAnalyzeRequest = {
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

export type GovernanceAnalyzeResponse = {
  input_chars?: number
  input_lines?: number
  issues?: GovernanceIssue[]
  suggested_pipeline_patch?: DocumentPipelineOptions
}

export type GovernanceRulePackListResponse = {
  items: string[]
}

// ==================== Governance (Lifecycle) ====================

export type DocumentLifecycleMetadata = {
  publication_status?: 'draft' | 'published' | 'deprecated'
  lifecycle_owner?: string | null
  review_due_at?: string | null
  authority_level?: number | null
  supersedes_document_id?: string | null
}

export type DocumentLifecycleMetadataUpdateRequest = {
  publication_status?: 'draft' | 'published' | 'deprecated'
  lifecycle_owner?: string | null
  review_due_at?: string | null
  authority_level?: number | null
  supersedes_document_id?: string | null
}

export type StaleDocumentItem = {
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

export type StaleDocumentsByDatasetResponse = {
  dataset_id: string
  as_of: string
  due_before: string
  mode: 'overdue' | 'due_soon' | 'all'
  skip: number
  limit: number
  total: number
  items: StaleDocumentItem[]
}

export type GovernanceCommonLineCandidate = {
  signature: string
  sample: string
  docs: number
  ratio: number
}

export type GovernanceCommonLinesLearnRequest = {
  dataset_id: string
  limit_docs?: number
  use_original?: boolean
  min_docs?: number
  min_ratio?: number
  max_line_length?: number
  max_candidates?: number
}

export type GovernanceCommonLinesLearnResponse = {
  dataset_id: string
  total_documents: number
  used_documents: number
  candidates: GovernanceCommonLineCandidate[]
}

export type GovernanceProfilePayload = {
  version: string
  extends?: string | null
  input_formats: Array<'markdown' | 'html'>
  pipeline_patch: DocumentPipelineOptions
  regex_rules: RegexRuleModel[]
  processing_scripts?: GovernanceProcessingScript[]
}

export type GovernanceProcessingScript = {
  name: string
  language: 'javascript' | 'typescript' | 'python' | 'rust'
  stage: 'post_parse' | 'post_governance'
  content: string
  enabled?: boolean
  description?: string | null
  created_at?: string | null
}

export type GovernanceProfileSummary = {
  id?: string | null
  key: string
  name: string
  description?: string | null
  is_system: boolean
}

export type GovernanceProfileListResponse = {
  total: number
  items: GovernanceProfileSummary[]
}

export type GovernanceProfileOut = GovernanceProfileSummary & {
  payload: GovernanceProfilePayload
  created_at?: string | null
  updated_at?: string | null
}

export type GovernanceProfileCreate = {
  name: string
  description?: string
  key?: string
  payload: GovernanceProfilePayload
}

export type GovernanceProfileUpdate = {
  name?: string
  description?: string
  payload?: GovernanceProfilePayload
}

export type GovernanceProfileImportResponse = {
  created: number
  updated: number
  items: GovernanceProfileSummary[]
}

export type GovernanceProfileResolvedResponse = {
  profile: GovernanceProfileOut
  chain: GovernanceProfileSummary[]
  effective: GovernanceProfilePayload
}

export type LLMCleanPreviewRequest = {
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

export type LLMCleanPreviewResponse = {
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

export type ParserBackendInfo = {
  name: string
  available: boolean
  notes?: string | null
}

export type ChunkStrategyInfo = {
  name: string
  available: boolean
  notes?: string | null
}

export type PipelineCapabilitiesResponse = {
  default_parser_backend: string
  default_chunk_strategy: string
  pdf_backends: ParserBackendInfo[]
  chunk_strategies: ChunkStrategyInfo[]
}

// ==================== 流水线预览/工具相关类型 ====================

export type PipelineParseImageInfo = {
  id: string
  url: string
  filename: string
}

export type PipelinePDFQualityScore = {
  score: number
  text_quality_score: number
  format_consistency_score: number
  table_quality_score: number
  is_scanned: boolean
  page_count: number
}

export type PipelineParsePreviewResponse = {
  backend: string
  pdf_quality?: PipelinePDFQualityScore | null
  markdown: string
  images: PipelineParseImageInfo[]
}

export type PipelineChunkItem = {
  id: string
  level: string
  index: number
  text: string
  start: number
  end: number
  tokens_est: number
  parent_id?: string | null
}

export type PipelineChunkPreviewRequest = {
  markdown: string
}

export type PipelineChunkPreviewResponse = {
  paragraphs: PipelineChunkItem[]
  sentences: PipelineChunkItem[]
}

export type KeywordExtractRequest = {
  text: string
  provider?: string
  top_k?: number
}

export type KeywordExtractResponse = {
  provider: string
  keywords: string[]
}

export type AutoAnnotationRequest = {
  text: string
  mode?: 'document_focus' | 'compliance'
  providers?: Array<'cpu' | 'llm' | 'keyword' | 'entity' | 'regex' | 'pii' | 'secret' | 'sensitive'>
  enable_llm?: boolean
  enable_llm_topics?: boolean
  llm_model?: string | null
  enable_keywords?: boolean
  enable_entities?: boolean
  enable_sensitive?: boolean
  keyword_provider?: string
  keyword_top_k?: number
  max_chars?: number
  max_annotations?: number
}

export type AutoAnnotationItem = {
  text: string
  type: 'entity' | 'keyword' | 'sensitive' | 'custom'
  label: string
  start: number
  end: number
  confidence: number
  source: string
}

export type AutoDocumentTag = {
  type: 'topic' | 'category' | 'domain' | 'industry' | 'doc_type' | 'sensitivity' | 'quality' | 'keyword'
  value: string
  label: string
  confidence: number
  source: string
}

export type AutoAnnotationResponse = {
  annotations: AutoAnnotationItem[]
  document_tags: AutoDocumentTag[]
  summary?: string | null
  text_chars: number
  scanned_chars: number
  truncated: boolean
  keyword_provider?: string | null
  strategy: 'llm' | 'rules' | 'hybrid'
  providers_used: string[]
  warnings: string[]
}

export type ZipImageInfo = {
  img_id: string
  original_path: string
  url: string
}

export type ZipWithImagesResponse = {
  markdown: string
  images: ZipImageInfo[]
  image_count: number
  dataset_id: string
  document_id: string
}

// ==================== 入库策略（解析前预处理）相关类型 ====================

export type IngestionPreprocessStep = {
  id: string
  params?: Record<string, unknown>
}

export type IngestionPreprocessConfig = {
  enabled: boolean
  steps?: IngestionPreprocessStep[]
}

export type IngestionRuleMatch = {
  extensions?: string[]
  filename_regex?: string | null
}

export type IngestionRule = {
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

export type IngestionPolicy = {
  version: string
  rules?: IngestionRule[]
}

export type IngestionPolicyImportResponse = {
  replaced: boolean
  rule_count: number
}

export type IngestionPolicyVersion = {
  id: string
  created_at: string
  created_by?: string | null
  source?: LooseString<'put' | 'import' | 'rollback'>
  policy: IngestionPolicy
  note?: string | null
  rollback_from_version_id?: string | null
  rollback_to_version_id?: string | null
}

export type IngestionPolicyVersionListResponse = {
  current_version_id?: string | null
  items?: IngestionPolicyVersion[]
}

export type IngestionPolicyRollbackRequest = {
  version_id: string
}

export type PreprocessStepLog = {
  id: string
  applied: boolean
  changed: boolean
  note?: string
}

export type PreprocessSummary = {
  changed: boolean
  size_before: number
  size_after: number
  steps: PreprocessStepLog[]
  warnings: string[]
}

export type IngestionPreviewRule = {
  matched: boolean
  rule_id?: string | null
  rule_name?: string | null
  governance_profile_ref?: string | null
  preprocess_steps: IngestionPreprocessStep[]
  parser_backend: string
  chunk_strategy: string
}

export type IngestionPreviewResponse = {
  rule: IngestionPreviewRule
  preprocess: PreprocessSummary
  parse: PipelineParsePreviewResponse
  clean: CleanPreviewResponse
  explain?: Record<string, unknown>
}
