/**
 * 类型定义
 */

// ==================== 通用类型 ====================

export type PermissionEnum = 'only_me' | 'all_team_members' | 'partial_members'

// ==================== 文档相关类型 ====================

export interface Document {
  id: string
  filename: string
  file_type: string
  file_size: number
  status: 'pending' | 'processing' | 'completed' | 'failed' | 'cancelled'
  processing_progress: number
  chunk_count: number
  total_characters: number
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

export interface DocumentPipelineOptions {
  governance_enabled?: boolean
  governance_remove_toc_lines?: boolean
  governance_remove_noise_lines?: boolean
  governance_unwrap_lines?: boolean
  governance_remove_common_lines?: boolean
  governance_remove_boilerplate?: boolean
  governance_remove_images?: 'none' | 'decorative' | 'all' | string
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
  chunk_vector_enabled?: boolean
  bm25_index_enabled?: boolean
  kg_enabled?: boolean
  event_vector_enabled?: boolean
  entity_vector_enabled?: boolean
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
}

export interface ChunkPreviewItem {
  index: number
  content: string
  length: number
  start_index: number
  end_index: number
  page_number?: number
  metadata?: Record<string, any>
}

export interface ChunkPreviewResponse {
  filename: string
  file_type: string
  file_size: number
  total_chunks: number
  total_characters: number
  params: ChunkPreviewParams
  chunks: ChunkPreviewItem[]
  original_text?: string
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
}

export interface CleanRulesResponse {
  rules: RegexRuleModel[]
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
  items: Conversation[]
}

export interface ConversationDetail {
  conversation_id: string
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
