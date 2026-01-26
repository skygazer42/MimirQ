/**
 * 类型定义
 */

// ==================== 通用类型 ====================

export type PermissionEnum = 'only_me' | 'all_team_members' | 'partial_members'
export type DocumentAccessMode = 'inherit' | PermissionEnum

// ==================== 文档相关类型 ====================

export interface Document {
  id: string
  filename: string
  file_type: string
  file_size: number
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled' | 'quarantined'
  processing_progress: number
  chunk_count: number
  total_characters: number
  owner_id?: string | null
  access_mode?: DocumentAccessMode | null
  created_at: string
  updated_at: string
  current_stage?: string
  error_message?: string
  metadata?: Record<string, any>
  governance?: GovernanceInfo
  chunks?: DocumentChunk[]
  dataset_id?: string
}

export interface GovernanceInfo {
  enabled: boolean
  documents: number
  changed_documents: number
  rules_applied: number
  dropped_documents?: number
  drop_reasons?: Record<string, number>
}

export interface DocumentStatus {
  id: string
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled'
  processing_progress: number
  current_stage?: string
  error_message?: string
}

export interface DocumentAccessInfo {
  mode: DocumentAccessMode
  owner_id?: string | null
  partial_member_list?: string[] | null
}

export interface DocumentAccessUpdateRequest {
  mode: DocumentAccessMode
  partial_member_list?: string[] | null
}

// ==================== Connectors ====================

export type ConnectorId = 'url_batch'
export type ConnectorRunStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

export interface ConnectorInfo {
  id: ConnectorId
  name: string
  description?: string
  supports_incremental?: boolean
}

export interface UrlBatchConnectorConfig {
  urls: string[]
  filename?: string | null
  parser_backend?: string
  chunk_strategy?: string
  pipeline?: DocumentPipelineOptions
  access?: DocumentAccessUpdateRequest | null
}

export interface ConnectorRunCreateRequest {
  connector_id: ConnectorId
  dataset_id?: string | null
  config: UrlBatchConnectorConfig
}

export interface ConnectorRunDocumentOut {
  document_id: string
  source_ref?: string | null
  status?: string
}

export interface ConnectorRunOut {
  id: string
  tenant_id: string
  dataset_id?: string | null
  connector_id: string
  requested_by?: string | null
  status: ConnectorRunStatus
  config?: Record<string, any>
  stats?: Record<string, any>
  error_message?: string | null
  task_id?: string | null
  created_at: string
  started_at?: string | null
  finished_at?: string | null
  documents?: ConnectorRunDocumentOut[]
}

export interface ConnectorRunListResponse {
  total: number
  items: ConnectorRunOut[]
}

export interface DocumentStats {
  total: number
  by_status: Record<string, number>
  total_chunks: number
  total_size: number
}

export interface DocumentUserMetadataPatchRequest {
  patch: Record<string, any>
  replace?: boolean
}

export interface DocumentBatchUserMetadataPatchRequest {
  document_ids: string[]
  patch: Record<string, any>
  replace?: boolean
}

export interface DocumentBatchUserMetadataPatchResponse {
  updated: number
  not_found: string[]
  denied: string[]
}

export interface DocumentChunk {
  id: string
  content: string
  page_number?: number
  start_char?: number
  end_char?: number
  chunk_index: number
  metadata?: Record<string, any>
}

export interface DocumentChunkMatch {
  id: string
  chunk_index: number
  page_number?: number
}

export interface DocumentChunkMatchList {
  total: number
  truncated: boolean
  items: DocumentChunkMatch[]
}

export interface DocumentPipelineOptions {
  governance_enabled?: boolean
  governance_remove_toc_lines?: boolean
  governance_remove_noise_lines?: boolean
  governance_unwrap_lines?: boolean
  governance_remove_common_lines?: boolean
  governance_remove_boilerplate?: boolean
  governance_remove_images?: 'none' | 'decorative' | 'all' | string
  governance_regex_rules?: RegexRuleModel[]
  governance_extract_frontmatter?: boolean
  governance_strip_frontmatter?: boolean
  governance_detect_language?: boolean
  governance_language_min_chars?: number
  governance_normalize_urls?: boolean
  governance_normalize_urls_strip_tracking?: boolean
  governance_drop_duplicate_paragraphs?: boolean
  governance_drop_duplicate_paragraphs_min_occurrences?: number
  governance_drop_duplicate_paragraphs_min_chars?: number
  governance_drop_duplicate_paragraphs_max_chars?: number
  governance_trim_references?: boolean
  governance_extract_keywords?: boolean
  governance_keywords_provider?: string
  governance_keywords_top_k?: number
  governance_keywords_max_chars?: number
  governance_normalize_tables?: boolean
  governance_strip_code_line_numbers?: boolean
  governance_pii_anonymize?: boolean
  governance_pii_mode?: 'mask' | 'token' | string
  governance_pii_mask?: string
  governance_secrets_redact?: boolean
  governance_secrets_mode?: 'mask' | 'token' | string
  governance_secrets_mask?: string
  governance_max_blank_lines?: number
  governance_html_xpath?: string
  governance_drop_outline_only?: boolean
  governance_drop_outline_min_content_chars?: number
  governance_drop_outline_max_heading_ratio?: number
  governance_drop_low_density?: boolean
  governance_drop_low_density_threshold?: number
  governance_quarantine_on_drop?: boolean
  governance_unwrap_max_line_length?: number
  governance_noise_min_chars?: number
  governance_noise_ratio_threshold?: number
  governance_common_lines_min_docs?: number
  governance_common_lines_min_ratio?: number
  parse_fallback_enabled?: boolean
  parse_fallback_min_content_chars?: number
  parse_fallback_max_retries?: number
  persist_parsed_content?: boolean
  persist_parsed_content_max_chars?: number
  near_dedup_enabled?: boolean
  near_dedup_hamming_threshold?: number
  near_dedup_max_bucket_size?: number
  chunk_size?: number
  chunk_overlap?: number
  chunk_merge_small_min_chars?: number
  chunk_strategy_params?: Record<string, any>
  embedding_context_prefix_enabled?: boolean
  chunk_vector_enabled?: boolean
  bm25_index_enabled?: boolean
  kg_enabled?: boolean
  event_vector_enabled?: boolean
  entity_vector_enabled?: boolean
}

export interface DocumentPipelinePatchRequest {
  patch: DocumentPipelineOptions
  replace?: boolean
}

export interface Citation {
  document_id: string
  document_name: string
  chunk_id?: string
  chunk_content: string
  matched_terms?: string[]
  page_number?: number
  header_path?: string
  chunk_strategy?: string
  chunk_role?: string
  retrieval_role?: string
  neighbor_of?: string
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
  metadata?: Record<string, any>
}

export interface DocumentPreview {
  filename: string
  file_type: string
  file_size: number
  segments: ParsedSegment[]
  parser_backend: string
}

export interface DocumentParsedContentResponse {
  document_id: string
  available: boolean
  markdown_content: string
  original_markdown_content: string
  persisted_meta: Record<string, any>
  markdown_truncated: boolean
  original_markdown_truncated: boolean
  max_chars: number
}

export interface ManualChunk {
  content: string
  page_number?: number
  start_char?: number
  end_char?: number
  metadata?: Record<string, any>
}

// ==================== 切块预览相关类型 ====================

export interface ChunkPreviewParams {
  chunk_size: number
  chunk_overlap: number
  unit?: 'chars' | 'tokens'
  strategy_params?: Record<string, any>
}

export interface ChunkPreviewItem {
  index: number
  content: string
  length: number
  tokens_est?: number
  start_index: number
  end_index: number
  page_number?: number
  metadata?: Record<string, any>
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
}

export interface ChunkPreviewQualityGate {
  grade?: 'pass' | 'warn' | 'fail'
  reasons?: string[]
}

export interface ChunkPreviewRecommendationPatch {
  target?: 'preview' | 'pipeline' | 'perf'
  id: string
  title: string
  description?: string
  patch?: Record<string, any>
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

export interface CleanPreviewRequest {
  markdown: string
  rules?: RegexRuleModel[]
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
  remove_images?: 'none' | 'decorative' | 'all' | string
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
  pii_mode?: 'mask' | 'token' | string
  pii_mask?: string
  secrets_redact?: boolean
  secrets_mode?: 'mask' | 'token' | string
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
  dropped?: boolean
  drop_reason?: string | null
  pii_hits?: Record<string, number> | null
  secrets_hits?: Record<string, number> | null
  frontmatter?: Record<string, any> | null
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

export interface GovernanceProfilePayload {
  version: string
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
  model_used?: string
  prompt_template_id?: string
  template_key?: string
  ab_experiment_key?: string
  ab_variant?: string
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
  params?: Record<string, any>
}

export interface IngestionPreprocessConfig {
  enabled: boolean
  steps: IngestionPreprocessStep[]
}

export interface IngestionRuleMatch {
  extensions: string[]
  filename_regex?: string | null
}

export interface IngestionRule {
  id: string
  name: string
  enabled: boolean
  match: IngestionRuleMatch
  preprocess: IngestionPreprocessConfig
  parser_backend?: string | null
  chunk_strategy?: string | null
  governance_profile_ref?: string | null
  pipeline_patch?: Record<string, any>
}

export interface IngestionPolicy {
  version: string
  rules: IngestionRule[]
}

export interface IngestionPolicyImportResponse {
  replaced: boolean
  rule_count: number
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
}

// ==================== 数据集相关类型 ====================

export interface Dataset {
  id: string
  tenant_id: string
  name: string
  description?: string
  permission: PermissionEnum
  owner_id?: string
  partial_member_list?: string[]
  pipeline?: DocumentPipelineOptions | null
}

export interface DatasetCreate {
  name: string
  description?: string
  permission?: PermissionEnum
  partial_member_list?: string[]
  pipeline?: DocumentPipelineOptions | null
}

export interface DatasetUpdate {
  name?: string
  description?: string
  permission?: PermissionEnum
  partial_member_list?: string[]
  pipeline?: DocumentPipelineOptions | null
}

export interface DatasetListResponse {
  total: number
  items: Dataset[]
}

// ==================== 对话相关类型 ====================

export interface Message {
  id: string
  role: 'user' | 'assistant'
  content: string
  citations?: Citation[]
  steps?: string[]
  message_metadata?: Record<string, any> | null
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

export interface StreamEvent {
  type: 'citations' | 'token' | 'done' | 'error' | 'route' | 'rewrite' | 'graph' | 'event'
  data: any
  request_id?: string
}

export interface ChatHistoryMessage {
  role: 'user' | 'assistant' | string
  content: string
}

export interface ChatRequest {
  conversation_id?: string
  message: string
  history?: ChatHistoryMessage[]
  document_ids?: string[]
  stream: boolean
  structured_output?: boolean
  structured_preset?: 'faq' | 'summary' | 'action_items' | 'custom' | string | null
  enable_long_term_memory?: boolean
  prompt_template_id?: string
  prompt_template_key?: string
  prompt_ab_experiment_key?: string
  rag_config?: {
    top_k?: number
    score_threshold?: number
    max_tokens?: number
    retrieval_mode?: 'auto' | 'hybrid' | 'vector' | 'keyword' | 'mmr' | string
    alpha?: number
    enable_weight_rerank?: boolean
    vector_weight?: number
    keyword_weight?: number
    mmr_lambda?: number
    enable_reranker?: boolean
    reranker_provider?: string
    reranker_top_n?: number
    use_graph?: boolean
    metadata_filter?: Record<string, any>
  }
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
  metrics: Record<string, any>
  structured: boolean
  structured_data?: any
}

export interface CheckpointItem {
  checkpoint_id?: string | null
  checkpoint_ns?: string
  created_at?: string | null
  next?: any
  metadata?: Record<string, any> | null
  values?: Record<string, any> | null
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
  next?: any
  metadata?: Record<string, any> | null
  values?: Record<string, any> | null
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
  extra?: Record<string, any>
  created_at: string
  updated_at: string
}

export interface MessageFeedbackCreate {
  message_id: string
  rating: number
  reason?: string
  tags?: string[]
  expected_answer?: string
  extra?: Record<string, any>
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

export interface UserProfile {
  id: string
  email: string
  username: string
  is_active: boolean
  created_at: string
  last_login_at?: string | null
}

export interface AuthToken {
  access_token: string
  token_type: string
  expires_in: number
}

export interface AuthResponse {
  user: UserProfile
  token: AuthToken
}

export interface RegisterRequest {
  email: string
  username: string
  password: string
}

export interface LoginRequest {
  identifier: string
  password: string
}

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
  result: Record<string, any>
  query: string
}

export interface KGGraphNode {
  id: string
  label: string
  group?: number
  val?: number
  meta?: Record<string, any>
}

export interface KGGraphLink {
  source: string
  target: string
  label?: string
  weight?: number
  meta?: Record<string, any>
}

export interface KGGraphResponse {
  nodes: KGGraphNode[]
  links: KGGraphLink[]
  stats?: Record<string, any>
}

export interface KGEntityItem {
  id: string
  name: string
  type: string
  normalized_name: string
  description?: string | null
  extra_data?: Record<string, any>
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
  references?: Record<string, any>
  extra_data?: Record<string, any>
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
  stats?: Record<string, any>
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

// ==================== RAG 调试相关类型 ====================

export interface RetrievePreviewRequest {
  query: string
  history?: ChatHistoryMessage[]
  document_ids?: string[]
  rag_config?: ChatRequest['rag_config']
}

export interface RetrievePreviewResponse {
  query_for_retrieval: string
  citations: Citation[]
  metrics: Record<string, any>
}

export interface PromptPreviewRequest {
  query: string
  history?: ChatHistoryMessage[]
  document_ids?: string[]
  rag_config?: ChatRequest['rag_config']
  structured_output?: boolean
  structured_preset?: string
  prompt_template_id?: string
  prompt_template_key?: string
  prompt_ab_experiment_key?: string
}

export interface PromptPreviewResponse {
  query_for_retrieval: string
  prompt_messages: Array<{ type: string; content: any }>
  prompt_text: string
  variables: Record<string, any>
  citations: Citation[]
  metrics: Record<string, any>
  prompt_template_id?: string
  prompt_template_key?: string
  prompt_ab_experiment_key?: string
  prompt_ab_variant?: string
}

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
  result_url?: string
  error?: string
}

export interface DocumentBatchUploadSuccess {
  document_id: string
  filename: string
  status: string
}

export interface DocumentBatchUploadFailure {
  filename: string
  error: string
}

export interface DocumentBatchUploadResponse {
  total: number
  successful_count: number
  failed_count: number
  successful: DocumentBatchUploadSuccess[]
  failed: DocumentBatchUploadFailure[]
}

// ==================== RAGAS 回归测试相关类型 ====================

export interface RegressionCase {
  id: string
  tenant_id: string
  dataset_id?: string
  document_ids: string[]
  question: string
  expected_answer?: string
  tags: string[]
  extra: Record<string, any>
  created_by?: string
  created_at: string
  updated_at: string
}

export interface RegressionCaseCreate {
  question: string
  dataset_id?: string
  document_ids?: string[]
  expected_answer?: string
  tags?: string[]
  extra?: Record<string, any>
}

export interface RegressionCaseList {
  total: number
  items: RegressionCase[]
}

export interface GeneratedQuestion {
  question: string
  expected_answer?: string
  context?: string
  source_type: 'document' | 'conversation'
  source_id: string
  metadata: Record<string, any>
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
  status: string
  metrics: string[]
  params: Record<string, any>
  summary: Record<string, any>
  error_message?: string
  created_at: string
  started_at?: string
  finished_at?: string
}

export interface RegressionRunCreate {
  case_ids?: string[]
  dataset_id?: string
  metrics?: string[]
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
  citations: any[]
  scores: Record<string, any>
  created_at: string
}

export interface RegressionRunDetail {
  run: RegressionRun
  items: RegressionItem[]
}

// ==================== RAGViz（相似度热力图） ====================

export interface RagvizSimilarityCollection {
  id: string
  label: string
  kind: string
  count: number
  meta?: Record<string, any>
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
  x_data: Record<string, any>[]
  y_data: Record<string, any>[]
  x_available_fields: string[]
  y_available_fields: string[]
  stats: RagvizSimilarityStats
  metadata: Record<string, any>
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

  file_size_histogram: DatasetProfileHistogramBin[]
  length_percentiles: DatasetProfilePercentiles
  length_histogram: DatasetProfileHistogramBin[]
  pdf_scan: DatasetProfilePdfScanStats

  pii_hits_total: Record<string, number>
  secrets_hits_total: Record<string, number>

  findings: DatasetProfileFindingSummary[]
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
  metadata: Record<string, any>
}

export interface DatasetProfileFindingListResponse {
  total: number
  items: DatasetProfileDocumentOut[]
}

export interface DatasetProfileScanRunCreateRequest {
  backfill_pdf_quality?: boolean
  backfill_text_quality?: boolean
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
  config: Record<string, any>
  summary: Record<string, any>
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
  by_file_type: Record<string, number>

  file_size_histogram: DatasetPrecheckHistogramBin[]
  length_percentiles: DatasetPrecheckPercentiles
  length_histogram: DatasetPrecheckHistogramBin[]

  pdf_scan: DatasetPrecheckPdfScanStats

  pii_hits_total: Record<string, number>
  secrets_hits_total: Record<string, number>

  findings: DatasetPrecheckFindingSummary[]
}

export interface DatasetPrecheckFileOut {
  name: string
  file_type: string
  file_size: number
  text_characters: number
  estimated_text: boolean
  pdf_scanned?: boolean | null
  pii_hits: Record<string, number>
  secrets_hits: Record<string, number>
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
}

export interface DatasetPrecheckScanRunOut {
  id: string
  tenant_id: string
  dataset_id: string
  requested_by?: string | null
  kind: string
  status: string
  progress: number
  config: Record<string, any>
  summary: Record<string, any>
  artifacts: Record<string, any>
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
