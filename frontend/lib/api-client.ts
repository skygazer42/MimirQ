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
  Dataset,
  DatasetCreate,
  DatasetUpdate,
  DatasetListResponse,
  MessageFeedback,
  MessageFeedbackCreate,
  MessageFeedbackListResponse,
  SAGExtractResponse,
  SAGSearchRequest,
  SAGSearchResponse,
  BatchUploadRequest,
  BatchUploadResponse,
  BatchTaskStatus,
  BatchFileInfo,
  CleanPreviewRequest,
  CleanPreviewResponse,
  CleanRulesResponse,
} from '@/types'
import { getAuthHeaders } from '@/lib/auth-headers'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

const apiClient = axios.create({
  baseURL: `${API_BASE_URL}/api/v1`,
  headers: {
    'Content-Type': 'application/json',
  },
})

// Inject auth/tenant headers for every request (client-side friendly)
apiClient.interceptors.request.use((config) => {
  const headers = AxiosHeaders.from(config.headers)
  const authHeaders = getAuthHeaders()
  for (const [key, value] of Object.entries(authHeaders)) {
    headers.set(key, value)
  }
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
      const detail = error.response.data?.detail

      switch (status) {
        case 401:
          console.error('[API] 未授权，请检查登录状态')
          break
        case 403:
          console.error('[API] 无权限访问')
          break
        case 404:
          console.error('[API] 资源不存在')
          break
        case 422:
          console.error('[API] 请求参数错误:', detail)
          break
        case 500:
          console.error('[API] 服务器错误:', detail)
          break
        default:
          console.error('[API] 请求失败:', detail || error.message)
      }
    } else if (error.request) {
      console.error('[API] 网络错误，请检查后端服务是否启动')
    }

    return Promise.reject(error)
  }
)

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
    if (options.pipeline) {
      const { pipeline } = options
      const appendIfDefined = (key: string, value: string | number | boolean | undefined) => {
        if (value === undefined || value === null) return
        formData.append(key, String(value))
      }
      appendIfDefined('governance_enabled', pipeline.governance_enabled)
      appendIfDefined('governance_remove_toc_lines', pipeline.governance_remove_toc_lines)
      appendIfDefined('governance_remove_noise_lines', pipeline.governance_remove_noise_lines)
      appendIfDefined('governance_unwrap_lines', pipeline.governance_unwrap_lines)
      appendIfDefined('governance_remove_common_lines', pipeline.governance_remove_common_lines)
      appendIfDefined('governance_unwrap_max_line_length', pipeline.governance_unwrap_max_line_length)
      appendIfDefined('governance_noise_min_chars', pipeline.governance_noise_min_chars)
      appendIfDefined('governance_noise_ratio_threshold', pipeline.governance_noise_ratio_threshold)
      appendIfDefined('governance_common_lines_min_docs', pipeline.governance_common_lines_min_docs)
      appendIfDefined('governance_common_lines_min_ratio', pipeline.governance_common_lines_min_ratio)
      appendIfDefined('chunk_size', pipeline.chunk_size)
      appendIfDefined('chunk_overlap', pipeline.chunk_overlap)
      appendIfDefined('chunk_vector_enabled', pipeline.chunk_vector_enabled)
      appendIfDefined('bm25_index_enabled', pipeline.bm25_index_enabled)
      appendIfDefined('sag_enabled', pipeline.sag_enabled)
      appendIfDefined('event_vector_enabled', pipeline.event_vector_enabled)
      appendIfDefined('entity_vector_enabled', pipeline.entity_vector_enabled)
    }

    const { data } = await apiClient.post('/documents/upload', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
    })

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
  async preview(file: File, parserBackend = 'auto'): Promise<DocumentPreview> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('parser_backend', parserBackend)

    const { data } = await apiClient.post('/documents/preview', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
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
    } = {}
  ): Promise<ChunkPreviewResponse> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('parser_backend', params.parser_backend || 'auto')
    formData.append('chunk_strategy', params.chunk_strategy || 'langchain_recursive')

    const { data } = await apiClient.post('/documents/chunk-preview', formData, {
      headers: {
        'Content-Type': 'multipart/form-data',
      },
      params: {
        chunk_size: params.chunk_size ?? 1000,
        chunk_overlap: params.chunk_overlap ?? 200,
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
}

// ==================== 解析/治理流水线 API ====================

export const pipelineApi = {
  async getCleanRules(): Promise<CleanRulesResponse> {
    const { data } = await apiClient.get('/pipeline/clean-rules')
    return data
  },

  async cleanPreview(params: CleanPreviewRequest): Promise<CleanPreviewResponse> {
    const { data } = await apiClient.post('/pipeline/clean-preview', params)
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
   * 流式对话（返回 EventSource URL）
   */
  getStreamUrl(): string {
    return `${API_BASE_URL}/api/v1/chat/stream`
  },

  /**
   * 发送流式聊天请求
   */
  async streamChat(request: ChatRequest, onEvent: (event: MessageEvent) => void, onError?: (error: Error) => void): Promise<void> {
    const response = await fetch(this.getStreamUrl(), {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
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

// ==================== SAG API ====================

export const sagApi = {
  /**
   * 触发 SAG 实体提取
   */
  async extract(documentId: string): Promise<SAGExtractResponse> {
    const { data } = await apiClient.post(`/sag/documents/${documentId}/extract`)
    return data
  },

  /**
   * SAG 搜索
   */
  async search(params: SAGSearchRequest): Promise<SAGSearchResponse> {
    const { data } = await apiClient.post('/sag/search', params)
    return data
  },
}

// ==================== 设置 API ====================

export interface FeatureFlags {
  sag_enabled: boolean
  deepdoc_enabled: boolean
  markitdown_enabled: boolean
  llama_index_enabled: boolean
  mineru_enabled: boolean
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

export interface SystemSettings {
  feature_flags: FeatureFlags
  llm: LLMConfig
  embedding: EmbeddingConfig
  milvus: MilvusConfig
  rag: RAGConfig
  mineru: MinerUConfig
}

export interface SystemStatus {
  database: { connected: boolean; message: string }
  milvus: { connected: boolean; message: string }
  llm: { configured: boolean; model: string }
  embedding: { configured: boolean; model: string }
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
}

// ==================== 提示词模板 API ====================

export interface PromptTemplate {
  id: string
  tenant_id: string
  name: string
  description?: string
  content: string
  variables: string[]
  is_system: boolean
  is_active: boolean
  category?: string
  tags: string[]
  usage_count: number
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
}

export default apiClient
