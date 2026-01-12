/**
 * API 客户端
 */
import axios, { AxiosHeaders } from 'axios'
import type {
  Document,
  Conversation,
  Message,
  ChatRequest,
  DocumentPreview,
  ManualChunk,
  DocumentPipelineOptions,
  ChunkPreviewResponse,
  DocumentBatchUploadResponse,
  Dataset,
  DatasetCreate,
  DatasetUpdate,
  DatasetListResponse,
  MessageFeedback,
  MessageFeedbackCreate,
  MessageFeedbackListResponse,
  KGExtractResponse,
  KGGraphNode,
  KGGraphResponse,
  KGSearchRequest,
  KGSearchResponse,
  BatchUploadRequest,
  BatchUploadResponse,
  BatchTaskStatus,
  BatchFileInfo,
  CleanPreviewRequest,
  CleanPreviewResponse,
  CleanRulesResponse,
  CheckpointDetailResponse,
  CheckpointListResponse,
  HealthResponse,
  KeywordExtractRequest,
  KeywordExtractResponse,
  LLMCleanPreviewRequest,
  LLMCleanPreviewResponse,
  PipelineCapabilitiesResponse,
  PipelineChunkPreviewRequest,
  PipelineChunkPreviewResponse,
  PipelineParsePreviewResponse,
  ReadyResponse,
  RetrievePreviewRequest,
  RetrievePreviewResponse,
  PromptPreviewRequest,
  PromptPreviewResponse,
  RegressionCase,
  RegressionCaseCreate,
  RegressionCaseList,
  TestGenFromDocsRequest,
  TestGenFromConversationsRequest,
  TestGenResponse,
  RegressionRun,
  RegressionRunCreate,
  RegressionRunList,
  RegressionRunDetail,
  AuthResponse,
  LoginRequest,
  RegisterRequest,
  UserProfile,
  ZipWithImagesResponse,
} from '@/types'
import type { MetaResponse } from '@/types/backend'
import { extractBackendMessage, extractBackendRequestId, withRequestId } from '@/lib/api-errors'
import { getAuthHeaders } from '@/lib/auth-headers'
import { API_LONG_TIMEOUT_MS, API_TIMEOUT_MS, API_V1_BASE_URL } from '@/lib/env'
import { appendPipelineOptionsToFormData } from '@/lib/form-data'

function getOrCreateRequestId(headers: AxiosHeaders): string {
  const existing = headers.get('X-Request-ID')
  if (existing) return String(existing)

  const requestId =
    (globalThis.crypto as Crypto | undefined)?.randomUUID?.() ||
    `${Date.now().toString(16)}-${Math.random().toString(16).slice(2)}`

  headers.set('X-Request-ID', requestId)
  return requestId
}

const apiClient = axios.create({
  baseURL: API_V1_BASE_URL,
  timeout: API_TIMEOUT_MS,
})

// Inject auth/tenant headers for every request (client-side friendly)
apiClient.interceptors.request.use((config) => {
  const headers = AxiosHeaders.from(config.headers)
  const authHeaders = getAuthHeaders()
  for (const [key, value] of Object.entries(authHeaders)) {
    headers.set(key, value)
  }
  getOrCreateRequestId(headers)
  config.headers = headers
  return config
})

// 响应拦截器：统一错误处理
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    // 统一错误处理
    if (error.response) {
      const status = error.response.status
      const data = error.response.data
      const detail = extractBackendMessage(data) || error.message
      const headerRequestId = error.response.headers?.['x-request-id']
      const requestId = extractBackendRequestId(data) || (headerRequestId ? String(headerRequestId) : undefined)

      switch (status) {
        case 401:
          console.error('[API] 未授权，请检查登录状态', requestId ? `(request_id=${requestId})` : '')
          break
        case 403:
          console.error('[API] 无权限访问', requestId ? `(request_id=${requestId})` : '')
          break
        case 404:
          console.error('[API] 资源不存在', requestId ? `(request_id=${requestId})` : '')
          break
        case 422:
          console.error('[API] 请求参数错误:', detail, requestId ? `(request_id=${requestId})` : '')
          break
        case 429: {
          const retryAfter = error.response.headers?.['retry-after']
          const extra = retryAfter ? `(retry_after=${String(retryAfter)}s)` : ''
          console.error('[API] 请求过于频繁，请稍后重试', extra, requestId ? `(request_id=${requestId})` : '')
          break
        }
        case 500:
          console.error('[API] 服务器错误:', detail, requestId ? `(request_id=${requestId})` : '')
          break
        default:
          console.error('[API] 请求失败:', detail || error.message, requestId ? `(request_id=${requestId})` : '')
      }
    } else if (error.request) {
      const headers = AxiosHeaders.from(error.config?.headers)
      const requestId = headers.get('X-Request-ID')
      console.error('[API] 网络错误，请检查后端服务是否启动', requestId ? `(request_id=${requestId})` : '')
    }

    return Promise.reject(error)
  }
)

// ==================== Health API ====================

export const healthApi = {
  async health(): Promise<HealthResponse> {
    const { data } = await apiClient.get('/health')
    return data
  },
  async ready(): Promise<ReadyResponse> {
    const { data } = await apiClient.get('/health/ready')
    return data
  },
}

// ==================== 文档管理 API ====================

export const documentApi = {
  /**
   * 上传文档
   */
  async upload(
    file: File,
    options: { parser_backend?: string; chunk_strategy?: string; dataset_id?: string; pipeline?: DocumentPipelineOptions } = {}
  ): Promise<Document> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('parser_backend', options.parser_backend || 'auto')
    formData.append('chunk_strategy', options.chunk_strategy || 'langchain_recursive')
    if (options.dataset_id) {
      formData.append('dataset_id', options.dataset_id)
    }
    appendPipelineOptionsToFormData(formData, options.pipeline)

    const { data } = await apiClient.post('/documents/upload', formData)

    return data
  },

  /**
   * 批量上传文档（一次请求多文件）
   */
  async uploadBatch(
    files: File[],
    options: {
      parser_backend?: string
      chunk_strategy?: string
      dataset_id?: string
      pipeline?: DocumentPipelineOptions
      max_concurrent?: number
    } = {}
  ): Promise<DocumentBatchUploadResponse> {
    const formData = new FormData()
    for (const file of files) {
      formData.append('files', file)
    }
    formData.append('parser_backend', options.parser_backend || 'auto')
    formData.append('chunk_strategy', options.chunk_strategy || 'langchain_recursive')
    if (options.dataset_id) {
      formData.append('dataset_id', options.dataset_id)
    }
    if (typeof options.max_concurrent === 'number') {
      formData.append('max_concurrent', String(options.max_concurrent))
    }
    appendPipelineOptionsToFormData(formData, options.pipeline)

    const { data } = await apiClient.post('/documents/upload-batch', formData)
    return data
  },

  /**
   * 获取文档列表
   */
  async list(params?: {
    skip?: number
    limit?: number
    status?: string
    dataset_id?: string
  }): Promise<{ total: number; items: Document[] }> {
    const { data } = await apiClient.get('/documents/', { params })
    return data
  },

  /**
   * 获取文档详情
   */
  async get(
    documentId: string,
    options?: { includeChunks?: boolean }
  ): Promise<Document> {
    const params = options?.includeChunks
      ? { include_chunks: true }
      : undefined

    const { data } = await apiClient.get(`/documents/${documentId}`, {
      params,
    })
    return data
  },

  /**
   * 获取文档处理状态
   */
  async getStatus(documentId: string) {
    const { data } = await apiClient.get(`/documents/${documentId}/status`)
    return data
  },

  /**
   * 删除文档
   */
  async delete(documentId: string): Promise<void> {
    await apiClient.delete(`/documents/${documentId}`)
  },

  /**
   * 文档解析预览（仅解析，不入库）
   */
  async preview(
    file: File,
    parserBackend = 'auto',
    pipeline?: DocumentPipelineOptions
  ): Promise<DocumentPreview> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('parser_backend', parserBackend)
    appendPipelineOptionsToFormData(formData, pipeline)

    const { data } = await apiClient.post('/documents/preview', formData, {
      timeout: API_LONG_TIMEOUT_MS,
    })

    return data
  },

  /**
   * 基于手动切片创建文档
   */
  async createFromChunks(params: {
    filename: string
    file_type: string
    file_size: number
    chunks: ManualChunk[]
    dataset_id?: string
    metadata?: Record<string, any>
    pipeline?: DocumentPipelineOptions
  }): Promise<Document> {
    const { data } = await apiClient.post('/documents/manual', params)
    return data
  },

  /**
   * 切块预览（预览切块效果，不入库）
   */
  async chunkPreview(
    file: File,
    params: {
      chunk_size?: number
      chunk_overlap?: number
      parser_backend?: string
      chunk_strategy?: string
      pipeline?: DocumentPipelineOptions
    } = {}
  ): Promise<ChunkPreviewResponse> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('parser_backend', params.parser_backend || 'auto')
    formData.append('chunk_strategy', params.chunk_strategy || 'langchain_recursive')
    appendPipelineOptionsToFormData(formData, params.pipeline)

    const effectiveChunkSize = params.chunk_size ?? params.pipeline?.chunk_size ?? 1000
    const effectiveChunkOverlap = params.chunk_overlap ?? params.pipeline?.chunk_overlap ?? 200

    const { data } = await apiClient.post('/documents/chunk-preview', formData, {
      timeout: API_LONG_TIMEOUT_MS,
      params: {
        chunk_size: effectiveChunkSize,
        chunk_overlap: effectiveChunkOverlap,
      },
    })

    return data
  },

  /**
   * 批量上传申请 URL
   */
  async applyBatchUploadUrls(files: BatchFileInfo[]): Promise<BatchUploadResponse> {
    const { data } = await apiClient.post('/documents/batch-upload/apply-urls', { files })
    return data
  },

  /**
   * 获取批量任务状态
   */
  async getBatchTaskStatus(batchId: string): Promise<BatchTaskStatus> {
    const { data } = await apiClient.get(`/documents/batch-upload/status/${batchId}`)
    return data
  },

  /**
   * 获取本地图片（uploads/{tenant}/images/{image_id}.png）
   */
  async fetchImage(imageId: string): Promise<Blob> {
    const { data } = await apiClient.get(`/documents/image/${imageId}`, { responseType: 'blob' })
    return data as Blob
  },

  /**
   * 获取图片（MinIO 预签名 URL 302 跳转后资源）
   */
  async fetchImageByImgId(imgId: string): Promise<Blob> {
    const { data } = await apiClient.get(`/documents/image-url/${encodeURIComponent(imgId)}`, { responseType: 'blob' })
    return data as Blob
  },
}

// ==================== Auth API ====================

export const authApi = {
  async register(payload: RegisterRequest): Promise<AuthResponse> {
    const { data } = await apiClient.post('/auth/register', payload)
    return data
  },
  async login(payload: LoginRequest): Promise<AuthResponse> {
    const { data } = await apiClient.post('/auth/login', payload)
    return data
  },
  async me(): Promise<UserProfile> {
    const { data } = await apiClient.get('/auth/me')
    return data
  },
}

// ==================== 解析/治理流水线 API ====================

export const pipelineApi = {
  async getCapabilities(): Promise<PipelineCapabilitiesResponse> {
    const { data } = await apiClient.get('/pipeline/capabilities')
    return data
  },

  async parsePreview(file: File, parserBackend = 'auto'): Promise<PipelineParsePreviewResponse> {
    const formData = new FormData()
    formData.append('file', file)
    if (parserBackend) {
      formData.append('parser_backend', parserBackend)
    }
    const { data } = await apiClient.post('/pipeline/parse-preview', formData, {
      timeout: API_LONG_TIMEOUT_MS,
    })
    return data
  },

  async chunkPreview(params: PipelineChunkPreviewRequest): Promise<PipelineChunkPreviewResponse> {
    const { data } = await apiClient.post('/pipeline/chunk-preview', params)
    return data
  },

  async extractKeywords(params: KeywordExtractRequest): Promise<KeywordExtractResponse> {
    const { data } = await apiClient.post('/pipeline/extract-keywords', params)
    return data
  },

  async getCleanRules(): Promise<CleanRulesResponse> {
    const { data } = await apiClient.get('/pipeline/clean-rules')
    return data
  },

  async cleanPreview(params: CleanPreviewRequest): Promise<CleanPreviewResponse> {
    const { data } = await apiClient.post('/pipeline/clean-preview', params)
    return data
  },

  async llmCleanPreview(params: LLMCleanPreviewRequest): Promise<LLMCleanPreviewResponse> {
    const { data } = await apiClient.post('/pipeline/llm-clean-preview', params)
    return data
  },

  async uploadZipWithImages(params: { file: File; dataset_id: string; document_id?: string }): Promise<ZipWithImagesResponse> {
    const formData = new FormData()
    formData.append('file', params.file)
    formData.append('dataset_id', params.dataset_id)
    if (params.document_id) {
      formData.append('document_id', params.document_id)
    }
    const { data } = await apiClient.post('/pipeline/upload-zip-with-images', formData, {
      timeout: API_LONG_TIMEOUT_MS,
    })
    return data
  },
}

// ==================== RAG 调试 API ====================

export const ragApi = {
  async retrievePreview(params: RetrievePreviewRequest): Promise<RetrievePreviewResponse> {
    const { data } = await apiClient.post('/rag/retrieve-preview', params)
    return data
  },

  async promptPreview(params: PromptPreviewRequest): Promise<PromptPreviewResponse> {
    const { data } = await apiClient.post('/rag/prompt-preview', params)
    return data
  },
}

// ==================== 数据集 API ====================

export const datasetApi = {
  /**
   * 创建数据集
   */
  async create(params: DatasetCreate): Promise<Dataset> {
    const { data } = await apiClient.post('/datasets/', params)
    return data
  },

  /**
   * 获取数据集列表
   */
  async list(params?: {
    skip?: number
    limit?: number
  }): Promise<DatasetListResponse> {
    const { data } = await apiClient.get('/datasets/', { params })
    return data
  },

  /**
   * 获取数据集详情
   */
  async get(datasetId: string): Promise<Dataset> {
    const { data } = await apiClient.get(`/datasets/${datasetId}`)
    return data
  },

  /**
   * 更新数据集
   */
  async update(datasetId: string, params: DatasetUpdate): Promise<Dataset> {
    const { data } = await apiClient.patch(`/datasets/${datasetId}`, params)
    return data
  },

  /**
   * 删除数据集
   */
  async delete(datasetId: string): Promise<void> {
    await apiClient.delete(`/datasets/${datasetId}`)
  },
}

// ==================== 对话 API ====================

export const chatApi = {
  /**
   * 创建对话
   */
  async createConversation(params?: {
    title?: string
    document_ids?: string[]
  }): Promise<Conversation> {
    const { data } = await apiClient.post('/chat/conversations', params)
    return data
  },

  /**
   * 获取对话列表
   */
  async listConversations(params?: {
    skip?: number
    limit?: number
  }): Promise<{ total: number; items: Conversation[] }> {
    const { data } = await apiClient.get('/chat/conversations', { params })
    return data
  },

  /**
   * 获取对话消息
   */
  async getMessages(conversationId: string): Promise<{ conversation_id: string; messages: Message[] }> {
    const { data } = await apiClient.get(`/chat/conversations/${conversationId}/messages`)
    return data
  },

  /**
   * 删除对话
   */
  async deleteConversation(conversationId: string): Promise<void> {
    await apiClient.delete(`/chat/conversations/${conversationId}`)
  },

  /**
   * 发送流式聊天请求
   */
  async streamChat(request: ChatRequest, onEvent: (event: MessageEvent) => void, onError?: (error: Error) => void): Promise<void> {
    const requestId =
      typeof crypto !== 'undefined' && typeof crypto.randomUUID === 'function'
        ? crypto.randomUUID()
        : `req-${Date.now()}-${Math.random().toString(16).slice(2)}`

    const response = await fetch(`${API_V1_BASE_URL}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
        'X-Request-ID': requestId,
      },
      body: JSON.stringify(request),
    })

    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`)
    }

    const reader = response.body?.getReader()
    if (!reader) {
      throw new Error('No response body')
    }

    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()

      if (done) break

      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''

      for (const line of lines) {
        if (line.trim()) {
          try {
            const event = new MessageEvent('message', { data: line })
            onEvent(event)
          } catch (e) {
            onError?.(e as Error)
          }
        }
      }
    }
  },

  async listCheckpoints(
    conversationId: string,
    params?: { limit?: number; before?: string; include_values?: boolean }
  ): Promise<CheckpointListResponse> {
    const { data } = await apiClient.get(`/chat/conversations/${conversationId}/checkpoints`, { params })
    return data
  },

  async getCheckpoint(
    conversationId: string,
    checkpointId: string,
    params?: { include_values?: boolean }
  ): Promise<CheckpointDetailResponse> {
    const { data } = await apiClient.get(`/chat/conversations/${conversationId}/checkpoints/${checkpointId}`, { params })
    return data
  },

  async deleteCheckpoints(conversationId: string): Promise<void> {
    await apiClient.delete(`/chat/conversations/${conversationId}/checkpoints`)
  },
}

// ==================== 反馈 API ====================

export const feedbackApi = {
  /**
   * 提交消息反馈
   */
  async create(params: MessageFeedbackCreate): Promise<MessageFeedback> {
    const { data } = await apiClient.post('/feedback/messages', params)
    return data
  },

  /**
   * 获取反馈列表
   */
  async list(params?: {
    skip?: number
    limit?: number
    message_id?: string
  }): Promise<MessageFeedbackListResponse> {
    const { data } = await apiClient.get('/feedback/messages', { params })
    return data
  },
}

// ==================== KG API ====================

export const kgApi = {
  /**
   * 触发 KG 实体/事件抽取
   */
  async extract(documentId: string): Promise<KGExtractResponse> {
    const { data } = await apiClient.post(`/kg/documents/${documentId}/extract`)
    return data
  },

  /**
   * KG 搜索
   */
  async search(params: KGSearchRequest): Promise<KGSearchResponse> {
    const { data } = await apiClient.post('/kg/search', params)
    return data
  },

  async getGraph(params?: {
    document_ids?: string[]
    max_events?: number
    max_entities?: number
    max_links?: number
  }): Promise<KGGraphResponse> {
    const { data } = await apiClient.get('/kg/graph', { params })
    return data
  },

  async expandGraph(params: {
    node_id: string
    document_ids?: string[]
    max_events?: number
    max_entities?: number
    max_links?: number
  }): Promise<KGGraphResponse> {
    const { data } = await apiClient.get('/kg/graph/expand', { params })
    return data
  },

  async searchGraphNodes(params: {
    q: string
    kind?: string
    limit?: number
    document_ids?: string[]
  }): Promise<KGGraphNode[]> {
    const { data } = await apiClient.get('/kg/graph/search', { params })
    return data
  },
}

// ==================== 设置 API ====================

export interface FeatureFlags {
  kg_enabled: boolean
  deepdoc_enabled: boolean
  docling_enabled: boolean
  etl4llm_enabled: boolean
  marker_enabled: boolean
  paddle_vl_enabled: boolean
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

export interface RAGConfig {
  chunk_size: number
  chunk_overlap: number
  retrieval_top_k: number
  similarity_threshold: number
  default_parser_backend: string
  default_chunk_strategy: string
}

export interface MinerUConfig {
  api_token: string
  api_base: string
  model_version: string
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

export interface MagicPDFConfig {
  cli: string
  method: string
  lang: string
  debug: boolean
  timeout_sec: number
  keep_artifacts: boolean
}

export interface ObservabilityConfig {
  tool_call_log_enabled: boolean
  tool_call_log_include_preview: boolean
  tool_call_log_max_preview_chars: number
  agent_log_enabled: boolean
  agent_log_include_execution_path: boolean
  agent_log_max_preview_chars: number
}

export interface SafetyConfig {
  pii_redaction_enabled: boolean
  pii_redaction_mask: string
  pii_stream_holdback_chars: number
}

export interface LangGraphConfig {
  use_subgraphs: boolean
}

export interface SystemSettings {
  feature_flags: FeatureFlags
  kg: KGConfig
  llm: LLMConfig
  embedding: EmbeddingConfig
  milvus: MilvusConfig
  rag: RAGConfig
  mineru: MinerUConfig
  etl4llm: Etl4LlmConfig
  marker: MarkerConfig
  paddle_vl: PaddleVLConfig
  magicpdf: MagicPDFConfig
  observability: ObservabilityConfig
  safety: SafetyConfig
  langgraph: LangGraphConfig
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

export type BackendMeta = MetaResponse

export const metaApi = {
  async get(): Promise<BackendMeta> {
    const { data } = await apiClient.get('/meta')
    return data
  },
}

export const settingsApi = {
  /**
   * 获取系统配置
   */
  async get(): Promise<SystemSettings> {
    const { data } = await apiClient.get('/settings')
    return data
  },

  /**
   * 更新系统配置
   */
  async update(settings: Partial<SystemSettings>): Promise<{ success: boolean; message: string; updated_keys: string[] }> {
    const { data } = await apiClient.put('/settings', settings)
    return data
  },

  /**
   * 获取系统状态
   */
  async getStatus(): Promise<SystemStatus> {
    const { data } = await apiClient.get('/settings/status')
    return data
  },

  /**
   * 测试 LLM 连接（不写入配置）
   */
  async testLLM(params: TestLLMRequest): Promise<TestLLMResponse> {
    const { data } = await apiClient.post('/settings/llm/test', params)
    return data
  },
}

// ==================== RAGAS 评测 API ====================

export interface RagasRun {
  id: string
  conversation_id?: string
  status: 'pending' | 'running' | 'completed' | 'failed' | string
  metrics: string[]
  params: Record<string, any>
  summary: Record<string, any>
  error_message?: string
  created_at: string
  started_at?: string
  finished_at?: string
}

export interface RagasItem {
  id: string
  run_id: string
  turn_index: number
  user_message_id?: string
  assistant_message_id?: string
  user_input: string
  response: string
  retrieved_contexts?: string[] | null
  citations: any[]
  scores: Record<string, any>
  created_at: string
}

export interface RagasRunDetail {
  run: RagasRun
  items: RagasItem[]
}

export const evaluationApi = {
  async createRagasRun(params: {
    conversation_id: string
    metrics?: string[]
    max_turns?: number
    skip_empty_contexts?: boolean
    include_contexts_in_response?: boolean
  }): Promise<RagasRun> {
    const { data } = await apiClient.post('/evaluations/ragas/runs', params)
    return data
  },

  async listRagasRuns(params?: {
    skip?: number
    limit?: number
    conversation_id?: string
  }): Promise<{ total: number; items: RagasRun[] }> {
    const { data } = await apiClient.get('/evaluations/ragas/runs', { params })
    return data
  },

  async getRagasRun(
    runId: string,
    params?: { include_items?: boolean; include_contexts?: boolean }
  ): Promise<RagasRunDetail> {
    const { data } = await apiClient.get(`/evaluations/ragas/runs/${runId}`, {
      params,
    })
    return data
  },

  // ==================== 回归测试用例管理 ====================

  async createRegressionCase(params: RegressionCaseCreate): Promise<RegressionCase> {
    const { data } = await apiClient.post('/evaluations/ragas/regression/cases', params)
    return data
  },

  async listRegressionCases(params?: {
    skip?: number
    limit?: number
    dataset_id?: string
  }): Promise<RegressionCaseList> {
    const { data } = await apiClient.get('/evaluations/ragas/regression/cases', { params })
    return data
  },

  async deleteRegressionCase(caseId: string): Promise<void> {
    await apiClient.delete(`/evaluations/ragas/regression/cases/${caseId}`)
  },

  // ==================== AI 生成测试问题 ====================

  async generateFromDocuments(params: TestGenFromDocsRequest): Promise<TestGenResponse> {
    const { data } = await apiClient.post('/evaluations/ragas/test-gen/from-documents', params)
    return data
  },

  async generateFromConversations(params: TestGenFromConversationsRequest): Promise<TestGenResponse> {
    const { data } = await apiClient.post('/evaluations/ragas/test-gen/from-conversations', params)
    return data
  },

  // ==================== 回归测试运行 ====================

  async createRegressionRun(params: RegressionRunCreate): Promise<RegressionRun> {
    const { data } = await apiClient.post('/evaluations/ragas/regression/runs', params)
    return data
  },

  async listRegressionRuns(params?: {
    skip?: number
    limit?: number
  }): Promise<RegressionRunList> {
    const { data } = await apiClient.get('/evaluations/ragas/regression/runs', { params })
    return data
  },

  async getRegressionRun(
    runId: string,
    params?: { include_items?: boolean; include_contexts?: boolean }
  ): Promise<RegressionRunDetail> {
    const { data } = await apiClient.get(`/evaluations/ragas/regression/runs/${runId}`, {
      params,
    })
    return data
  },
}

// ==================== 提示词模板 API ====================

export interface PromptTemplate {
  id: string
  tenant_id: string
  template_key?: string | null
  name: string
  description?: string
  content: string
  variables: string[]
  is_system: boolean
  is_active: boolean
  category?: string
  tags: string[]
  usage_count: number
  version?: number
  parent_id?: string | null
  ab_experiment_key?: string | null
  ab_variant?: string | null
  ab_weight?: number
  created_at: string
  updated_at: string
}

export interface PromptTemplateCreate {
  name: string
  description?: string
  content: string
  variables?: string[]
  category?: string
  tags?: string[]
  is_active?: boolean
}

export interface PromptTemplateUpdate {
  name?: string
  description?: string
  content?: string
  variables?: string[]
  category?: string
  tags?: string[]
  is_active?: boolean
}

export interface PromptTemplateNewVersion {
  name?: string
  description?: string
  content?: string
  variables?: string[]
  category?: string
  tags?: string[]
  is_active?: boolean
  deactivate_previous?: boolean
  ab_experiment_key?: string
  ab_variant?: string
  ab_weight?: number
}

export const promptTemplateApi = {
  /**
   * 创建提示词模板
   */
  async create(params: PromptTemplateCreate): Promise<PromptTemplate> {
    const { data } = await apiClient.post('/prompt-templates', params)
    return data
  },

  /**
   * 获取提示词模板列表
   */
  async list(params?: {
    skip?: number
    limit?: number
    category?: string
    is_active?: boolean
  }): Promise<{ total: number; items: PromptTemplate[] }> {
    const { data } = await apiClient.get('/prompt-templates', { params })
    return data
  },

  /**
   * 获取单个提示词模板
   */
  async get(templateId: string): Promise<PromptTemplate> {
    const { data } = await apiClient.get(`/prompt-templates/${templateId}`)
    return data
  },

  /**
   * 更新提示词模板
   */
  async update(templateId: string, params: PromptTemplateUpdate): Promise<PromptTemplate> {
    const { data } = await apiClient.put(`/prompt-templates/${templateId}`, params)
    return data
  },

  /**
   * 删除提示词模板
   */
  async delete(templateId: string): Promise<void> {
    await apiClient.delete(`/prompt-templates/${templateId}`)
  },

  /**
   * 复制提示词模板
   */
  async duplicate(templateId: string): Promise<PromptTemplate> {
    const { data } = await apiClient.post(`/prompt-templates/${templateId}/duplicate`)
    return data
  },

  async createVersion(templateId: string, params: PromptTemplateNewVersion): Promise<PromptTemplate> {
    const { data } = await apiClient.post(`/prompt-templates/${templateId}/versions`, params)
    return data
  },
}

export default apiClient
