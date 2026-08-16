import { apiClient } from '@/lib/api/core'

export interface FeatureFlags {
  kg_enabled: boolean
  deepdoc_enabled: boolean
  docling_enabled: boolean
  etl4llm_enabled: boolean
  marker_enabled: boolean
  paddle_vl_enabled: boolean
  textin_enabled: boolean
  markitdown_enabled: boolean
  llama_index_enabled: boolean
  mineru_enabled: boolean
  magicpdf_enabled: boolean
}

export interface KGConfig {
  chat_enabled: boolean
  extract_prompt_template_id: string
  extract_prompt_template_key: string
  extract_prompt_ab_experiment_key: string
  extract_replace_existing: boolean
  extract_prune_orphan_entities: boolean
}

export interface LLMConfig {
  api_key: string
  api_base: string
  model: string
  temperature: number
  timeout: number
  max_retries: number
}

export interface EmbeddingConfig {
  provider: string
  model: string
  api_key: string
  api_base: string
}

export interface MilvusConfig {
  host: string
  port: number
  user: string
  password: string
  collection_name: string
}

export interface MinIOConfig {
  enabled: boolean
  endpoint: string
  access_key: string
  secret_key: string
  bucket_name: string
  use_ssl: boolean
  documents_enabled: boolean
  image_max_bytes: number
}

export interface RAGConfig {
  chunk_size: number
  chunk_overlap: number
  chunk_min_chars: number
  retrieval_top_k: number
  similarity_threshold: number
  retrieval_profile?: string
  retrieval_mode?: string
  retrieval_contract_mode?: string
  alpha?: number
  fusion_strategy?: string | null
  fusion_budgets?: Record<string, number> | null
  fusion_min_scores?: Record<string, number> | null
  fusion_weights?: Record<string, number> | null
  enable_weight_rerank?: boolean
  vector_weight?: number
  keyword_weight?: number
  mmr_lambda?: number
  default_parser_backend: string
  default_chunk_strategy: string
  bm25_index_enabled: boolean
  enable_reranker: boolean
  reranker_provider: string
  reranker_top_n: number
  visible_evidence_only?: boolean
  show_image_in_answer: boolean
  image_append_max: number
}

export interface CacheConfig {
  upload_dedup_enabled: boolean
  chat_response_cache_enabled: boolean
  chat_response_cache_ttl_sec: number
  chat_response_cache_max_value_bytes: number
  chat_response_cache_require_empty_history: boolean
}

export interface UrlIngestConfig {
  enabled: boolean
  max_bytes: number
  timeout_sec: number
  allow_private_ips: boolean
  follow_redirects: boolean
}

export interface GovernanceConfig {
  enabled: boolean
  pii_anonymize: boolean
  secrets_redact: boolean
  quarantine_on_drop: boolean
}

export interface MinerUConfig {
  api_token: string
  api_base: string
  model_version: string
  backend: string
  local_server_url: string
  vl_server: string
}

export interface Etl4LlmConfig {
  api_url: string
  timeout_sec: number
  mode: string
  force_ocr: boolean
  enable_formula: boolean
  extract_images: boolean
  filter_page_header_footer: boolean
}

export interface MarkerConfig {
  api_url: string
  timeout_sec: number
}

export interface PaddleVLConfig {
  api_url: string
  timeout_sec: number
}

export interface TextInConfig {
  api_url: string
  app_id: string
  secret_code: string
  timeout_sec: number
  parse_mode: string
  table_flavor: string
  apply_document_tree: boolean
  markdown_details: boolean
  get_image: string
  dpi: number
  page_count: number
}

export interface MagicPDFConfig {
  cli: string
  method: string
  lang: string
  debug: boolean
  timeout_sec: number
  models_dir: string
  device_mode: string
  keep_artifacts: boolean
}

export interface ObservabilityConfig {
  tool_call_log_enabled: boolean
  tool_call_log_include_preview: boolean
  tool_call_log_max_preview_chars: number
  agent_log_enabled: boolean
  agent_log_include_execution_path: boolean
  agent_log_max_preview_chars: number
  metrics_log_enabled: boolean
  metrics_log_include_text: boolean
}

export interface SafetyConfig {
  pii_redaction_enabled: boolean
  pii_redaction_mask: string
  pii_stream_holdback_chars: number
}

export interface ChatConfig {
  stream_heartbeat_sec: number
  stream_cancel_on_disconnect: boolean
}

export interface LangGraphConfig {
  use_subgraphs: boolean
}

export interface NavigationConfig {
  user_visible_modules: string[]
}

export interface DifyExternalKnowledgeConfig {
  enabled: boolean
  api_keys: string
  tenant_id: string
  account_id: string
  knowledge_map_json: string
  top_k_max: number
  endpoint_path: string
}

export interface SystemSettings {
  feature_flags: FeatureFlags
  kg: KGConfig
  llm: LLMConfig
  embedding: EmbeddingConfig
  milvus: MilvusConfig
  minio: MinIOConfig
  rag: RAGConfig
  cache: CacheConfig
  url_ingest: UrlIngestConfig
  governance: GovernanceConfig
  mineru: MinerUConfig
  etl4llm: Etl4LlmConfig
  marker: MarkerConfig
  paddle_vl: PaddleVLConfig
  textin: TextInConfig
  magicpdf: MagicPDFConfig
  observability: ObservabilityConfig
  safety: SafetyConfig
  chat: ChatConfig
  langgraph: LangGraphConfig
  navigation: NavigationConfig
  dify_external_knowledge: DifyExternalKnowledgeConfig
}

export interface ParserBackendStatus {
  enabled: boolean
  available: boolean
  message: string
}

export interface SystemStatus {
  database: { connected: boolean; message: string }
  milvus: { connected: boolean; message: string }
  llm: { configured: boolean; model: string }
  embedding: { configured: boolean; model: string }
  parsers?: Record<string, ParserBackendStatus>
}

export interface TestLLMRequest {
  api_key: string
  api_base: string
  model: string
  temperature?: number
  timeout?: number
  max_retries?: number
}

export interface TestLLMResponse {
  success: boolean
  message: string
}

export const settingsApi = {
  async get(): Promise<SystemSettings> {
    const { data } = await apiClient.get('/settings')
    return data
  },

  async update(settings: Partial<SystemSettings>): Promise<{ success: boolean; message: string; updated_keys: string[] }> {
    const { data } = await apiClient.put('/settings', settings)
    return data
  },

  async getStatus(): Promise<SystemStatus> {
    const { data } = await apiClient.get('/settings/status')
    return data
  },

  async testLLM(params: TestLLMRequest): Promise<TestLLMResponse> {
    const { data } = await apiClient.post('/settings/llm/test', params)
    return data
  },
}
