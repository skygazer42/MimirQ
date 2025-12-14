/**
 * API 客户端
 */
import axios from 'axios'
import type {
  Document,
  Conversation,
  Message,
  ChatRequest,
  DocumentPreview,
  ManualChunk,
  ChunkPreviewResponse,
} from '@/types'

const API_BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000'

const apiClient = axios.create({
  baseURL: `${API_BASE_URL}/api/v1`,
  headers: {
    'Content-Type': 'application/json',
  },
})

// ==================== 文档管理 API ====================

export const documentApi = {
  /**
   * 上传文档
   */
  async upload(
    file: File,
    options: { parser_backend?: string; chunk_strategy?: string } = {}
  ): Promise<Document> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('parser_backend', options.parser_backend || 'auto')
    formData.append('chunk_strategy', options.chunk_strategy || 'langchain_recursive')

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
  }): Promise<{ total: number; items: Document[] }> {
    const { data } = await apiClient.get('/documents/', { params })
    return data
  },

  /**
   * 获取文档详情
   *
   * 默认不包含 chunks，如需包含传入 options.includeChunks = true
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
    metadata?: Record<string, any>
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
  getStreamUrl(request: ChatRequest): string {
    const params = new URLSearchParams()

    // 注意：实际应该使用 POST 请求，这里简化处理
    // 正确做法是在组件中直接使用 fetch POST
    return `${API_BASE_URL}/api/v1/chat/stream`
  },
}

export default apiClient
