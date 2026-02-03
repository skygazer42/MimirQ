/**
 * API 客户端
 */
import axios, { AxiosHeaders } from 'axios'
import type {
  Document,
  DocumentChunk,
  DocumentChunkCreateRequest,
  DocumentChunkMatchList,
  DocumentChunkReembedRequest,
  DocumentChunkReembedResponse,
  DocumentChunkUpdateRequest,
  DocumentQAGenerateRequest,
  DocumentQAGenerateResponse,
  DocumentStatus,
  DocumentTimelineResponse,
  DocumentFolderTreeResponse,
  DocumentStats,
  DocumentAccessInfo,
  DocumentAccessUpdateRequest,
  DocumentBatchLifecycleResponse,
  DocumentBatchReingestRequest,
  DocumentBatchRetryRequest,
  DocumentBatchRetryResponse,
  DocumentBatchMoveRequest,
  DocumentBatchMoveResponse,
  DocumentBatchAccessUpdateRequest,
  DocumentBatchAccessUpdateResponse,
  DocumentDuplicateList,
  DocumentVersionList,
  ConnectorInfo,
  ConnectorConfigCreateRequest,
  ConnectorConfigListResponse,
  ConnectorConfigOut,
  ConnectorConfigUpdateRequest,
  ConnectorScheduledTickResponse,
  ConnectorRunCreateRequest,
  ConnectorRunListResponse,
  ConnectorRunOut,
  DocumentUserMetadataPatchRequest,
  DocumentBatchUserMetadataPatchRequest,
  DocumentBatchUserMetadataPatchResponse,
  DocumentPipelinePatchRequest,
  Conversation,
  Message,
  ChatRequest,
  ChatResponse,
  ConversationSummaryResponse,
  ConversationSummaryUpdateResponse,
  ChatTokenUsageSummary,
  ChatTokenQuotaStatus,
  AuditLogListResponse,
  DocumentPreview,
  DocumentParsedContentResponse,
  ManualChunk,
  DocumentPipelineOptions,
  ChunkPreviewResponse,
  ChunkPreset,
  ChunkPresetCreateRequest,
  ChunkPresetUpdateRequest,
  ChunkPresetListResponse,
  DocumentBatchUploadResponse,
  Dataset,
  DatasetCreate,
  DatasetUpdate,
  DatasetListResponse,
  DatasetCategoryTreeResponse,
  DatasetCategoryCreate,
  DatasetCategoryUpdate,
  DatasetCategoryMoveRequest,
  DatasetCategoryOut,
  DatasetCategoryAssignmentRequest,
  DatasetCategoryAssignmentResponse,
  DatasetIngestionStats,
  DatasetHealthResponse,
  DatasetReport,
  DatasetConfigExport,
  DatasetConfigImportRequest,
  DatasetCloneRequest,
  DatasetProfileSummary,
  DatasetProfileFindingListResponse,
  DatasetProfileScanRunCreateRequest,
  DatasetProfileScanRunListResponse,
  DatasetProfileScanRunOut,
  DatasetPrecheckSummary,
  DatasetPrecheckFindingListResponse,
  DatasetPrecheckScanRunCreateRequest,
  DatasetPrecheckScanRunListResponse,
  DatasetPrecheckScanRunOut,
  DatasetPrecheckSamplesResponse,
  DatasetPrecheckNearDupResponse,
  DatasetPrecheckDiffResponse,
  DatasetPrecheckIngestionSuggestionResponse,
  DatasetTablesListResponse,
  DatasetTableAsset,
  TableQueryRequest,
  TableQueryResponse,
  TableAskRequest,
  TableAskResponse,
  LotusSemFilterRequest,
  MessageFeedback,
  MessageFeedbackCreate,
  MessageFeedbackListResponse,
  MessageFeedbackEnrichedListResponse,
  KGDeleteResponse,
  KGEntityDetailResponse,
  KGEventDetailResponse,
  KGExtractResponse,
  KGGraphNode,
  KGGraphResponse,
  KGSearchRequest,
  KGSearchResponse,
  KGStatsResponse,
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
  GovernanceAnalyzeRequest,
  GovernanceAnalyzeResponse,
  GovernanceRulePackListResponse,
  GovernanceCommonLinesLearnRequest,
  GovernanceCommonLinesLearnResponse,
  GovernanceProfileListResponse,
  GovernanceProfileOut,
  GovernanceProfileCreate,
  GovernanceProfileUpdate,
  GovernanceProfileImportResponse,
  GovernanceProfileResolvedResponse,
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
	  IngestionPolicy,
	  IngestionPolicyImportResponse,
	  IngestionPolicyRollbackRequest,
	  IngestionPolicyVersionListResponse,
	  IngestionPreviewResponse,
	  RagvizSimilarityCollectionsResponse,
  RagvizSimilarityRequest,
  RagvizSimilarityCalculateResponse,
  RagMetricsSummaryResponse,
  RagTraceListResponse,
} from '@/types'
import type { MetaResponse } from '@/types/backend'
import { extractBackendMessage, extractBackendRequestId, withRequestId } from '@/lib/api-errors'
import { buildFetchError } from '@/lib/fetch-errors'
import { getAuthHeaders } from '@/lib/auth-headers'
import { clearAuthSession, getAccessToken } from '@/lib/auth-storage'
import { API_LONG_TIMEOUT_MS, API_TIMEOUT_MS, API_V1_BASE_URL } from '@/lib/env'
import { appendPipelineOptionsToFormData } from '@/lib/form-data'
import { resolveParserBackendForFilename, resolveParserBackendForFiles } from '@/lib/parser-compat'
import { generateRequestId } from '@/lib/request-id'
import { readSseDataStrings } from '@/lib/sse-reader'

function getOrCreateRequestId(headers: AxiosHeaders): string {
  const existing = headers.get('X-Request-ID')
  if (existing) return String(existing)

  const requestId = generateRequestId()

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
  (response) => {
    const responseType = response.config?.responseType
    const expectsJson = !responseType || responseType === 'json'
    if (expectsJson) {
      const contentType = String(response.headers?.['content-type'] || '').toLowerCase()
      if (typeof response.data === 'string') {
        const trimmed = response.data.trimStart().slice(0, 200).toLowerCase()
        const looksHtml = trimmed.startsWith('<!doctype html') || trimmed.startsWith('<html')
        if (looksHtml || contentType.includes('text/html')) {
          // When NEXT_PUBLIC_API_URL points to a web app / reverse proxy, the API may return HTML with 200 OK.
          // Fail fast so callers don't accidentally treat `string` payloads as typed JSON objects.
          const err: any = new Error(
            'Backend returned HTML (可能 API 地址配错了；请检查 NEXT_PUBLIC_API_URL / 反向代理配置)'
          )
          err.code = 'ERR_BAD_RESPONSE'
          err.response = response
          err.config = response.config
          err.request = response.request
          return Promise.reject(err)
        }
      }
    }

    return response
  },
  (error) => {
    // 统一错误处理
    if (error.response) {
      const status = error.response.status
      const data = error.response.data
      const detail = extractBackendMessage(data) || error.message
      const headerRequestId = error.response.headers?.['x-request-id']
      const requestId = extractBackendRequestId(data) || (headerRequestId ? String(headerRequestId) : undefined)
      ;(error as any).requestId = requestId

      switch (status) {
        case 401: {
          console.error('[API] 未授权，请检查登录状态', requestId ? `(request_id=${requestId})` : '')

          // If we were using JWT auth and the token is rejected/expired, clear the session
          // so the UI doesn't stay in a broken "logged-in" state.
          const token = getAccessToken()
          if (token) {
            clearAuthSession()
            if (typeof window !== 'undefined') {
              const path = String(window.location?.pathname || '')
              if (!path.startsWith('/auth')) {
                window.location.href = '/auth'
              }
            }
          }
          break
        }
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
      ;(error as any).requestId = requestId ? String(requestId) : undefined
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
    options: {
      parser_backend?: string
      chunk_strategy?: string
      dataset_id?: string
      pipeline?: DocumentPipelineOptions
      user_metadata?: Record<string, any>
    } = {}
  ): Promise<Document> {
    const resolvedParser = resolveParserBackendForFilename(file.name, options.parser_backend)
    const formData = new FormData()
    const uploadName = (file as any).webkitRelativePath || file.name
    formData.append('file', file, uploadName)
    formData.append('parser_backend', resolvedParser.backend || 'auto')
    formData.append('chunk_strategy', options.chunk_strategy || 'langchain_recursive')
    if (options.dataset_id) {
      formData.append('dataset_id', options.dataset_id)
    }
    if (options.user_metadata) {
      formData.append('user_metadata', JSON.stringify(options.user_metadata))
    }
    appendPipelineOptionsToFormData(formData, options.pipeline)

    const { data } = await apiClient.post('/documents/upload', formData)

    return data
  },

  /**
   * 通过 URL 导入文档（后端拉取并入库）
   */
  async uploadFromUrl(params: {
    url: string
    dataset_id?: string
    filename?: string
    parser_backend?: string
    chunk_strategy?: string
    pipeline?: DocumentPipelineOptions
  }): Promise<Document> {
    const body: any = {
      url: params.url,
      dataset_id: params.dataset_id,
      filename: params.filename,
      parser_backend: params.parser_backend || 'auto',
      chunk_strategy: params.chunk_strategy || 'langchain_recursive',
      pipeline: params.pipeline,
    }
    const { data } = await apiClient.post('/documents/upload-url', body)
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
      user_metadata_map?: Record<string, Record<string, any>>
    } = {}
  ): Promise<DocumentBatchUploadResponse> {
    const resolvedParser = resolveParserBackendForFiles(files, options.parser_backend)
    const formData = new FormData()
    for (const file of files) {
      const uploadName = (file as any).webkitRelativePath || file.name
      formData.append('files', file, uploadName)
    }
    formData.append('parser_backend', resolvedParser.backend || 'auto')
    formData.append('chunk_strategy', options.chunk_strategy || 'langchain_recursive')
    if (options.dataset_id) {
      formData.append('dataset_id', options.dataset_id)
    }
    if (typeof options.max_concurrent === 'number') {
      formData.append('max_concurrent', String(options.max_concurrent))
    }
    if (options.user_metadata_map) {
      formData.append('user_metadata_map', JSON.stringify(options.user_metadata_map))
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
    lifecycle?: string
    dataset_id?: string
    source_path_prefix?: string
    file_type?: string
    owner_id?: string
    q?: string
    order_by?: string
    order_dir?: 'asc' | 'desc' | string
  }): Promise<{ total: number; items: Document[] }> {
    const { data } = await apiClient.get('/documents/', { params })
    return data
  },

  /**
   * 获取文档目录树（按 document.metadata.source_path 聚合）
   */
  async folders(params: {
    dataset_id: string
    lifecycle?: 'active' | 'archived' | 'disabled' | 'all' | string
    max_depth?: number
  }): Promise<DocumentFolderTreeResponse> {
    const { data } = await apiClient.get('/documents/folders', { params })
    return data
  },

  /**
   * 文档统计（用于知识库仪表盘/卡片）
   */
  async stats(params?: { dataset_id?: string; lifecycle?: string; file_type?: string; owner_id?: string; q?: string }): Promise<DocumentStats> {
    const { data } = await apiClient.get('/documents/stats', { params })
    return data
  },

  /**
   * 获取文档详情
   */
  async get(
    documentId: string,
    options?: { includeChunks?: boolean; pipeline_hash?: string; all_versions?: boolean }
  ): Promise<Document> {
    const params = options?.includeChunks
      ? {
          include_chunks: true,
          pipeline_hash: options.pipeline_hash,
          all_versions: options.all_versions,
        }
      : undefined

    const { data } = await apiClient.get(`/documents/${documentId}`, {
      params,
    })
    return data
  },

  /**
   * 获取文档处理时间线（可回溯：audit logs + 合成状态事件）
   */
  async getTimeline(documentId: string, params?: { limit?: number }): Promise<DocumentTimelineResponse> {
    const { data } = await apiClient.get(`/documents/${documentId}/timeline`, { params })
    return data
  },

  /**
   * 获取文档访问控制（ACL）
   */
  async getAccess(documentId: string): Promise<DocumentAccessInfo> {
    const { data } = await apiClient.get(`/documents/${documentId}/access`)
    return data
  },

  /**
   * 更新文档访问控制（ACL）
   */
  async updateAccess(documentId: string, payload: DocumentAccessUpdateRequest): Promise<DocumentAccessInfo> {
    const { data } = await apiClient.put(`/documents/${documentId}/access`, payload)
    return data
  },

  /**
   * 获取已持久化的解析 Markdown（原始+清洗后）
   *
   * 说明：仅当 ingestion pipeline 开启 persist_parsed_content 时可用；
   * 未开启时后端会返回 available=false（内容为空）。
   */
  async getParsedContent(
    documentId: string,
    params?: { max_chars?: number }
  ): Promise<DocumentParsedContentResponse> {
    const { data } = await apiClient.get(`/documents/${documentId}/parsed-content`, { params })
    return data
  },

  /**
   * 获取文档切片列表（分页）
   */
  async listChunks(
    documentId: string,
    params?: { skip?: number; limit?: number; q?: string; pipeline_hash?: string; all_versions?: boolean }
  ): Promise<{ total: number; items: DocumentChunk[] }> {
    const { data } = await apiClient.get(`/documents/${documentId}/chunks`, { params })
    return data
  },

  /**
   * 搜索切片匹配（轻量：只返回 id/index/page，用于“文档内查找/跳转”）
   */
  async getChunkMatches(
    documentId: string,
    params: { q: string; limit?: number; pipeline_hash?: string; all_versions?: boolean }
  ): Promise<DocumentChunkMatchList> {
    const { data } = await apiClient.get(`/documents/${documentId}/chunks/matches`, { params })
    return data
  },

  /**
   * 获取单个切片（用于引用/定位，避免一次性拉全量）
   */
  async getChunk(documentId: string, chunkId: string): Promise<DocumentChunk> {
    const { data } = await apiClient.get(`/documents/${documentId}/chunks/${chunkId}`)
    return data
  },

  /**
   * 创建新切片（追加到当前激活版本）
   */
  async createChunk(documentId: string, payload: DocumentChunkCreateRequest): Promise<DocumentChunk> {
    const { data } = await apiClient.post(`/documents/${documentId}/chunks`, payload)
    return data
  },

  /**
   * 更新切片（入库后手工编辑）
   */
  async updateChunk(documentId: string, chunkId: string, payload: DocumentChunkUpdateRequest): Promise<DocumentChunk> {
    const { data } = await apiClient.patch(`/documents/${documentId}/chunks/${chunkId}`, payload)
    return data
  },

  /**
   * 删除切片（入库后手工编辑）
   */
  async deleteChunk(documentId: string, chunkId: string): Promise<void> {
    await apiClient.delete(`/documents/${documentId}/chunks/${chunkId}`)
  },

  /**
   * 禁用切片（从检索/索引中排除）
   */
  async disableChunk(documentId: string, chunkId: string): Promise<DocumentChunk> {
    const { data } = await apiClient.post(`/documents/${documentId}/chunks/${chunkId}/disable`)
    return data
  },

  /**
   * 启用切片（需要 re-embed 才能恢复向量索引）
   */
  async enableChunk(documentId: string, chunkId: string): Promise<DocumentChunk> {
    const { data } = await apiClient.post(`/documents/${documentId}/chunks/${chunkId}/enable`)
    return data
  },

  /**
   * 重新嵌入指定切片（向量 + BM25 best-effort）
   */
  async reembedChunks(documentId: string, payload: DocumentChunkReembedRequest): Promise<DocumentChunkReembedResponse> {
    const { data } = await apiClient.post(`/documents/${documentId}/chunks/reembed`, payload)
    return data
  },

  /**
   * 下载/预览原始文件（返回 Blob）
   */
  /**
   * Generate FAQ-style Q&A pairs for a document and index them as extra chunks (file_type=qa).
   */
  async generateQa(documentId: string, payload: DocumentQAGenerateRequest): Promise<DocumentQAGenerateResponse> {
    const { data } = await apiClient.post(`/documents/${documentId}/qa/generate`, payload)
    return data
  },

  async download(documentId: string, params?: { inline?: boolean }): Promise<Blob> {
    const { data } = await apiClient.get(`/documents/${documentId}/download`, {
      params,
      responseType: 'blob',
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
   * 取消文档处理
   */
  async cancel(documentId: string): Promise<DocumentStatus> {
    const { data } = await apiClient.post(`/documents/${documentId}/cancel`)
    return data
  },

  /**
   * 重试文档处理（失败/取消后）
   */
  async retry(documentId: string, params?: { force?: boolean }): Promise<DocumentStatus> {
    const { data } = await apiClient.post(`/documents/${documentId}/retry`, null, { params })
    return data
  },

  /**
   * 删除文档
   */
  async delete(documentId: string): Promise<void> {
    await apiClient.delete(`/documents/${documentId}`)
  },

  /**
   * 批量删除文档
   */
  async batchDelete(document_ids: string[]): Promise<{ deleted: number; not_found: string[]; denied: string[] }> {
    const { data } = await apiClient.post('/documents/batch-delete', { document_ids })
    return data
  },

  /**
   * 批量禁用文档
   */
  async batchDisable(document_ids: string[]): Promise<DocumentBatchLifecycleResponse> {
    const { data } = await apiClient.post('/documents/batch/disable', { document_ids })
    return data
  },

  /**
   * 批量启用文档
   */
  async batchEnable(document_ids: string[]): Promise<DocumentBatchLifecycleResponse> {
    const { data } = await apiClient.post('/documents/batch/enable', { document_ids })
    return data
  },

  /**
   * 批量归档文档
   */
  async batchArchive(document_ids: string[]): Promise<DocumentBatchLifecycleResponse> {
    const { data } = await apiClient.post('/documents/batch/archive', { document_ids })
    return data
  },

  /**
   * 批量取消归档文档
   */
  async batchUnarchive(document_ids: string[]): Promise<DocumentBatchLifecycleResponse> {
    const { data } = await apiClient.post('/documents/batch/unarchive', { document_ids })
    return data
  },

  /**
   * 批量重试/重新入库
   */
  async batchRetry(payload: DocumentBatchRetryRequest): Promise<DocumentBatchRetryResponse> {
    const { data } = await apiClient.post('/documents/batch/retry', payload)
    return data
  },

  /**
   * 批量重新入库（可选：先 patch pipeline，然后 force retry）
   */
  async batchReingest(payload: DocumentBatchReingestRequest): Promise<DocumentBatchRetryResponse> {
    const { data } = await apiClient.post('/documents/batch/reingest', payload)
    return data
  },

  /**
   * 批量更新文档 ACL（access_mode + allowlist）
   */
  async batchUpdateAccess(payload: DocumentBatchAccessUpdateRequest): Promise<DocumentBatchAccessUpdateResponse> {
    const { data } = await apiClient.post('/documents/batch/access', payload)
    return data
  },

  /**
   * 批量移动文档到目标数据集（受限：不支持 MinIO-backed/含 MinIO 图片的文档）
   */
  async batchMove(payload: DocumentBatchMoveRequest): Promise<DocumentBatchMoveResponse> {
    const { data } = await apiClient.post('/documents/batch/move', payload)
    return data
  },

  /**
   * 查找重复文档（按 file_sha256，数据集内）
   */
  async listDuplicates(params: {
    dataset_id: string
    min_count?: number
    max_groups?: number
    max_docs_per_group?: number
  }): Promise<DocumentDuplicateList> {
    const { data } = await apiClient.get('/documents/duplicates', { params })
    return data
  },

  /**
   * 更新文档的用户元数据（metadata.user）
   */
  async patchUserMetadata(
    documentId: string,
    payload: DocumentUserMetadataPatchRequest
  ): Promise<Document> {
    const { data } = await apiClient.patch(`/documents/${documentId}/metadata`, payload)
    return data
  },

  /**
   * 更新文档的 pipeline 配置（metadata.pipeline）
   */
  async patchPipeline(
    documentId: string,
    payload: DocumentPipelinePatchRequest
  ): Promise<Document> {
    const { data } = await apiClient.patch(`/documents/${documentId}/pipeline`, payload)
    return data
  },

  // Document pipeline versions (ops/debug/rollback)
  async listVersions(documentId: string): Promise<DocumentVersionList> {
    const { data } = await apiClient.get(`/documents/${documentId}/versions`)
    return data
  },

  async activateVersion(documentId: string, pipelineHash: string): Promise<Document> {
    const { data } = await apiClient.post(
      `/documents/${documentId}/versions/${encodeURIComponent(pipelineHash)}/activate`
    )
    return data
  },

  async deleteVersion(documentId: string, pipelineHash: string): Promise<void> {
    await apiClient.delete(`/documents/${documentId}/versions/${encodeURIComponent(pipelineHash)}`)
  },

  /**
   * 批量更新文档用户元数据（metadata.user）
   */
  async batchPatchUserMetadata(
    payload: DocumentBatchUserMetadataPatchRequest
  ): Promise<DocumentBatchUserMetadataPatchResponse> {
    const { data } = await apiClient.post(`/documents/batch/metadata`, payload)
    return data
  },

  /**
   * 文档解析预览（仅解析，不入库）
   */
  async preview(
    file: File,
    parserBackend = 'auto',
    pipeline?: DocumentPipelineOptions,
    options?: { signal?: AbortSignal; dataset_id?: string }
  ): Promise<DocumentPreview> {
    const resolvedParser = resolveParserBackendForFilename(file.name, parserBackend)
    const formData = new FormData()
    formData.append('file', file)
    formData.append('parser_backend', resolvedParser.backend || 'auto')
    if (options?.dataset_id) formData.append('dataset_id', options.dataset_id)
    appendPipelineOptionsToFormData(formData, pipeline)

    const { data } = await apiClient.post('/documents/preview', formData, {
      timeout: API_LONG_TIMEOUT_MS,
      signal: options?.signal,
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
      child_ratio?: number
      min_child_size?: number
      pipeline?: DocumentPipelineOptions
      dataset_id?: string
      include_original_text?: boolean
      original_text_max_chars?: number
      max_chunks?: number
      use_parse_cache?: boolean
      separator_preset?: string
      separator?: string
      keep_separator?: boolean
      separator_max_chunk_size?: number
    } = {},
    options?: { signal?: AbortSignal }
  ): Promise<ChunkPreviewResponse> {
    const resolvedParser = resolveParserBackendForFilename(file.name, params.parser_backend || 'auto')
    const formData = new FormData()
    formData.append('file', file)
    formData.append('parser_backend', resolvedParser.backend || 'auto')
    const effectiveStrategy = params.chunk_strategy || 'langchain_recursive'
    formData.append('chunk_strategy', effectiveStrategy)
    if (params.dataset_id) formData.append('dataset_id', params.dataset_id)
    if (effectiveStrategy === 'parent_child') {
      if (typeof params.child_ratio === 'number') formData.append('child_ratio', String(params.child_ratio))
      if (typeof params.min_child_size === 'number') formData.append('min_child_size', String(params.min_child_size))
    }
    if (params.separator_preset) formData.append('separator_preset', params.separator_preset)
    if (typeof params.separator === 'string') formData.append('separator', params.separator)
    if (typeof params.keep_separator === 'boolean') {
      formData.append('keep_separator', params.keep_separator ? 'true' : 'false')
    }
    if (typeof params.separator_max_chunk_size === 'number') {
      formData.append('separator_max_chunk_size', String(params.separator_max_chunk_size))
    }
    appendPipelineOptionsToFormData(formData, params.pipeline)

    const effectiveChunkSize = params.chunk_size ?? params.pipeline?.chunk_size ?? 1000
    const effectiveChunkOverlap = params.chunk_overlap ?? params.pipeline?.chunk_overlap ?? 200

    const { data } = await apiClient.post('/documents/chunk-preview', formData, {
      timeout: API_LONG_TIMEOUT_MS,
      signal: options?.signal,
      params: {
        chunk_size: effectiveChunkSize,
        chunk_overlap: effectiveChunkOverlap,
        include_original_text: typeof params.include_original_text === 'boolean' ? params.include_original_text : undefined,
        original_text_max_chars: typeof params.original_text_max_chars === 'number' ? params.original_text_max_chars : undefined,
        max_chunks: typeof params.max_chunks === 'number' ? params.max_chunks : undefined,
        use_parse_cache: typeof params.use_parse_cache === 'boolean' ? params.use_parse_cache : undefined,
      },
    })

    return data
  },

  /**
   * 批量上传申请 URL
   */
  /**
   * 切块预览（复用后端解析缓存，不上传文件）
   *
   * 说明：需要先调用一次 `chunkPreview(file, ...)` 让后端缓存解析结果。
   * 如果缓存 miss，会返回 404；前端应回退到上传文件的方式。
   */
  async chunkPreviewBySha(
    params: {
      file_sha256: string
      file_type?: string
      filename?: string
      file_size?: number
      chunk_size?: number
      chunk_overlap?: number
      parser_backend?: string
      chunk_strategy?: string
      child_ratio?: number
      min_child_size?: number
      pipeline?: DocumentPipelineOptions
      dataset_id?: string
      include_original_text?: boolean
      original_text_max_chars?: number
      max_chunks?: number
      use_parse_cache?: boolean
      separator_preset?: string
      separator?: string
      keep_separator?: boolean
      separator_max_chunk_size?: number
    },
    options?: { signal?: AbortSignal }
  ): Promise<ChunkPreviewResponse> {
    const name = params.filename || `doc.${String(params.file_type || 'txt').replace(/^\\.+/, '')}`
    const resolvedParser = resolveParserBackendForFilename(name, params.parser_backend || 'auto')

    const formData = new FormData()
    formData.append('file_sha256', String(params.file_sha256 || ''))
    if (params.file_type) formData.append('file_type', String(params.file_type))
    if (params.filename) formData.append('filename', String(params.filename))
    if (typeof params.file_size === 'number') formData.append('file_size', String(params.file_size))

    formData.append('parser_backend', resolvedParser.backend || 'auto')
    const effectiveStrategy = params.chunk_strategy || 'langchain_recursive'
    formData.append('chunk_strategy', effectiveStrategy)
    if (params.dataset_id) formData.append('dataset_id', params.dataset_id)
    if (effectiveStrategy === 'parent_child') {
      if (typeof params.child_ratio === 'number') formData.append('child_ratio', String(params.child_ratio))
      if (typeof params.min_child_size === 'number') formData.append('min_child_size', String(params.min_child_size))
    }
    if (params.separator_preset) formData.append('separator_preset', params.separator_preset)
    if (typeof params.separator === 'string') formData.append('separator', params.separator)
    if (typeof params.keep_separator === 'boolean') {
      formData.append('keep_separator', params.keep_separator ? 'true' : 'false')
    }
    if (typeof params.separator_max_chunk_size === 'number') {
      formData.append('separator_max_chunk_size', String(params.separator_max_chunk_size))
    }
    appendPipelineOptionsToFormData(formData, params.pipeline)

    const effectiveChunkSize = params.chunk_size ?? params.pipeline?.chunk_size ?? 1000
    const effectiveChunkOverlap = params.chunk_overlap ?? params.pipeline?.chunk_overlap ?? 200

    const { data } = await apiClient.post('/documents/chunk-preview/by-sha', formData, {
      timeout: API_LONG_TIMEOUT_MS,
      signal: options?.signal,
      params: {
        chunk_size: effectiveChunkSize,
        chunk_overlap: effectiveChunkOverlap,
        include_original_text: typeof params.include_original_text === 'boolean' ? params.include_original_text : undefined,
        original_text_max_chars: typeof params.original_text_max_chars === 'number' ? params.original_text_max_chars : undefined,
        max_chunks: typeof params.max_chunks === 'number' ? params.max_chunks : undefined,
        use_parse_cache: typeof params.use_parse_cache === 'boolean' ? params.use_parse_cache : undefined,
      },
    })

    return data
  },

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

// ==================== Parsing Workspace API ====================

export interface ParsingContentResponse {
  document_id: string
  parser_backend: string
  markdown_content: string
  original_markdown_content: string
  stats?: {
    page_count?: number
    table_count?: number
    image_count?: number
    block_count?: number
  } | null
  parse_duration_sec?: number | null
  pdf_quality?: {
    score: number
    text_quality_score: number
    format_consistency_score: number
    table_quality_score: number
    is_scanned: boolean
    page_count: number
  } | null
  quality_gate?: {
    grade: 'pass' | 'warn' | 'fail'
    reasons: string[]
    evidence?: Record<string, any>
  } | null
}

export interface ParsingContentUpdateRequest {
  markdown_content: string
  original_markdown_content?: string | null
}

export const parsingApi = {
  async listDocuments(params?: { skip?: number; limit?: number; status?: string }): Promise<{ total: number; items: Document[] }> {
    const { data } = await apiClient.get('/parsing/documents', { params })
    return data
  },

  async upload(file: File, options?: { parser_backend?: string }): Promise<Document> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('parser_backend', (options?.parser_backend || 'auto').toString())
    const { data } = await apiClient.post('/parsing/documents', formData)
    return data
  },

  async parse(
    documentId: string,
    options?: { parser_backend?: string; image_caption_enabled?: boolean; signal?: AbortSignal }
  ): Promise<ParsingContentResponse> {
    const params: Record<string, any> = {}
    if (options?.parser_backend) params.parser_backend = options.parser_backend
    if (options?.image_caption_enabled) params.image_caption_enabled = true
    const { data } = await apiClient.post(
      `/parsing/documents/${documentId}/parse`,
      null,
      {
        timeout: API_LONG_TIMEOUT_MS,
        signal: options?.signal,
        params: Object.keys(params).length ? params : undefined,
      }
    )
    return data
  },

  async getContent(documentId: string): Promise<ParsingContentResponse> {
    const { data } = await apiClient.get(`/parsing/documents/${documentId}/content`)
    return data
  },

  async updateContent(documentId: string, payload: ParsingContentUpdateRequest): Promise<ParsingContentResponse> {
    const { data } = await apiClient.patch(`/parsing/documents/${documentId}/content`, payload)
    return data
  },

  async delete(documentId: string): Promise<void> {
    await apiClient.delete(`/parsing/documents/${documentId}`)
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

  async governanceAnalyze(params: GovernanceAnalyzeRequest): Promise<GovernanceAnalyzeResponse> {
    const { data } = await apiClient.post('/pipeline/governance-analyze', params)
    return data
  },

  async learnCommonLines(params: GovernanceCommonLinesLearnRequest): Promise<GovernanceCommonLinesLearnResponse> {
    const { data } = await apiClient.post('/pipeline/learn-common-lines', params, { timeout: API_LONG_TIMEOUT_MS })
    return data
  },

  async listGovernanceProfiles(params?: {
    q?: string
    include_builtin?: boolean
    limit?: number
  }): Promise<GovernanceProfileListResponse> {
    const { data } = await apiClient.get('/pipeline/governance-profiles', { params })
    return data
  },

  async getGovernanceProfile(profileRef: string): Promise<GovernanceProfileOut> {
    const { data } = await apiClient.get(`/pipeline/governance-profiles/${encodeURIComponent(profileRef)}`)
    return data
  },

  async getGovernanceProfileResolved(profileRef: string): Promise<GovernanceProfileResolvedResponse> {
    const { data } = await apiClient.get(`/pipeline/governance-profiles/${encodeURIComponent(profileRef)}/resolved`)
    return data
  },

  async createGovernanceProfile(payload: GovernanceProfileCreate): Promise<GovernanceProfileOut> {
    const { data } = await apiClient.post('/pipeline/governance-profiles', payload)
    return data
  },

  async updateGovernanceProfile(profileRef: string, payload: GovernanceProfileUpdate): Promise<GovernanceProfileOut> {
    const { data } = await apiClient.patch(`/pipeline/governance-profiles/${encodeURIComponent(profileRef)}`, payload)
    return data
  },

  async deleteGovernanceProfile(profileRef: string): Promise<void> {
    await apiClient.delete(`/pipeline/governance-profiles/${encodeURIComponent(profileRef)}`)
  },

  async importGovernanceProfiles(file: File, overwrite = false): Promise<GovernanceProfileImportResponse> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('overwrite', overwrite ? 'true' : 'false')
    const { data } = await apiClient.post('/pipeline/governance-profiles/import', formData, {
      timeout: API_LONG_TIMEOUT_MS,
    })
    return data
  },

  async exportGovernanceProfile(profileRef: string): Promise<Blob> {
    const { data } = await apiClient.get(`/pipeline/governance-profiles/${encodeURIComponent(profileRef)}/export`, {
      responseType: 'blob',
    })
    return data as Blob
  },

  async exportGovernanceProfileIngestionPolicy(profileRef: string): Promise<Blob> {
    const { data } = await apiClient.get(
      `/pipeline/governance-profiles/${encodeURIComponent(profileRef)}/export-ingestion-policy`,
      {
        responseType: 'blob',
      }
    )
    return data as Blob
  },

  async parsePreview(
    file: File,
    parserBackend = 'auto',
    options?: { signal?: AbortSignal }
  ): Promise<PipelineParsePreviewResponse> {
    const resolvedParser = resolveParserBackendForFilename(file.name, parserBackend)
    const formData = new FormData()
    formData.append('file', file)
    formData.append('parser_backend', resolvedParser.backend || 'auto')
    const { data } = await apiClient.post('/pipeline/parse-preview', formData, {
      timeout: API_LONG_TIMEOUT_MS,
      signal: options?.signal,
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

  async ingestionPreview(
    file: File,
    params: { dataset_id: string; parser_backend?: string; chunk_strategy?: string; diff_max_lines?: number }
  ): Promise<IngestionPreviewResponse> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('dataset_id', params.dataset_id)
    if (params.parser_backend) formData.append('parser_backend', params.parser_backend)
    if (params.chunk_strategy) formData.append('chunk_strategy', params.chunk_strategy)
    if (params.diff_max_lines != null) formData.append('diff_max_lines', String(params.diff_max_lines))
    const { data } = await apiClient.post('/pipeline/ingestion-preview', formData, { timeout: API_LONG_TIMEOUT_MS })
    return data
  },
}

// ==================== Governance API ====================

export const governanceApi = {
  async listRulePacks(): Promise<GovernanceRulePackListResponse> {
    const { data } = await apiClient.get('/governance/rule-packs')
    return data
  },
}

// ==================== Chunk Presets (Chunk Preview) API ====================

export const chunkPresetApi = {
  async list(params?: { q?: string; limit?: number }): Promise<ChunkPresetListResponse> {
    const { data } = await apiClient.get('/chunk-presets', { params })
    return data
  },

  async create(payload: ChunkPresetCreateRequest): Promise<ChunkPreset> {
    const { data } = await apiClient.post('/chunk-presets', payload)
    return data
  },

  async update(presetId: string, payload: ChunkPresetUpdateRequest): Promise<ChunkPreset> {
    const { data } = await apiClient.put(`/chunk-presets/${encodeURIComponent(presetId)}`, payload)
    return data
  },

  async delete(presetId: string): Promise<void> {
    await apiClient.delete(`/chunk-presets/${encodeURIComponent(presetId)}`)
  },
}

// ==================== Connectors API ====================

export const connectorApi = {
  async listConnectors(): Promise<ConnectorInfo[]> {
    const { data } = await apiClient.get('/connectors')
    return data
  },

  async listConfigs(params?: {
    skip?: number
    limit?: number
    dataset_id?: string
    connector_id?: string
    enabled?: boolean
  }): Promise<ConnectorConfigListResponse> {
    const { data } = await apiClient.get('/connectors/configs', { params })
    return data
  },

  async createConfig(payload: ConnectorConfigCreateRequest): Promise<ConnectorConfigOut> {
    const { data } = await apiClient.post('/connectors/configs', payload)
    return data
  },

  async updateConfig(configId: string, payload: ConnectorConfigUpdateRequest): Promise<ConnectorConfigOut> {
    const { data } = await apiClient.put(`/connectors/configs/${configId}`, payload)
    return data
  },

  async deleteConfig(configId: string): Promise<void> {
    await apiClient.delete(`/connectors/configs/${configId}`)
  },

  async runConfig(configId: string): Promise<ConnectorRunOut> {
    const { data } = await apiClient.post(`/connectors/configs/${configId}/run`)
    return data
  },

  async scheduledTick(): Promise<ConnectorScheduledTickResponse> {
    const { data } = await apiClient.post('/connectors/scheduled/tick')
    return data
  },

  async createRun(payload: ConnectorRunCreateRequest): Promise<ConnectorRunOut> {
    const { data } = await apiClient.post('/connectors/runs', payload)
    return data
  },

  async listRuns(params?: { skip?: number; limit?: number; dataset_id?: string }): Promise<ConnectorRunListResponse> {
    const { data } = await apiClient.get('/connectors/runs', { params })
    return data
  },

  async getRun(runId: string): Promise<ConnectorRunOut> {
    const { data } = await apiClient.get(`/connectors/runs/${runId}`)
    return data
  },

  async cancelRun(runId: string): Promise<ConnectorRunOut> {
    const { data } = await apiClient.post(`/connectors/runs/${runId}/cancel`)
    return data
  },

  async retryFailed(runId: string): Promise<ConnectorRunOut> {
    const { data } = await apiClient.post(`/connectors/runs/${runId}/retry-failed`)
    return data
  },

  async resumeRun(runId: string): Promise<ConnectorRunOut> {
    const { data } = await apiClient.post(`/connectors/runs/${runId}/resume`)
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
    category_id?: string
    include_descendants?: boolean
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

  async getIngestionStats(datasetId: string): Promise<DatasetIngestionStats> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/ingestion/stats`)
    return data
  },

  async getHealth(datasetId: string): Promise<DatasetHealthResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/health`)
    return data
  },

  /**
   * 更新数据集
   */
  async update(datasetId: string, params: DatasetUpdate): Promise<Dataset> {
    const { data } = await apiClient.patch(`/datasets/${datasetId}`, params)
    return data
  },

  async getCategories(datasetId: string): Promise<DatasetCategoryAssignmentResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/categories`)
    return data
  },

  async setCategories(datasetId: string, payload: DatasetCategoryAssignmentRequest): Promise<DatasetCategoryAssignmentResponse> {
    const { data } = await apiClient.put(`/datasets/${datasetId}/categories`, payload)
    return data
  },

  /**
   * 删除数据集
   */
  async delete(datasetId: string): Promise<void> {
    await apiClient.delete(`/datasets/${datasetId}`)
  },

  async getIngestionPolicy(datasetId: string): Promise<IngestionPolicy> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/ingestion-policy`)
    return data
  },

  async updateIngestionPolicy(datasetId: string, policy: IngestionPolicy): Promise<IngestionPolicy> {
    const { data } = await apiClient.put(`/datasets/${datasetId}/ingestion-policy`, policy)
    return data
  },

  async importIngestionPolicy(datasetId: string, file: File, replace = true): Promise<IngestionPolicyImportResponse> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('replace', replace ? 'true' : 'false')
    const { data } = await apiClient.post(`/datasets/${datasetId}/ingestion-policy/import`, formData, { timeout: API_LONG_TIMEOUT_MS })
    return data
  },

  async exportIngestionPolicy(datasetId: string): Promise<Blob> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/ingestion-policy/export`, { responseType: 'blob' })
    return data as Blob
  },

  async listIngestionPolicyVersions(datasetId: string): Promise<IngestionPolicyVersionListResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/ingestion-policy/versions`)
    return data
  },

  async rollbackIngestionPolicy(datasetId: string, body: IngestionPolicyRollbackRequest): Promise<IngestionPolicy> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/ingestion-policy/rollback`, body)
    return data
  },

  async exportConfig(datasetId: string): Promise<DatasetConfigExport> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/config/export`)
    return data
  },

  async importConfig(datasetId: string, payload: DatasetConfigImportRequest): Promise<Dataset> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/config/import`, payload)
    return data
  },

  async clone(datasetId: string, payload: DatasetCloneRequest): Promise<Dataset> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/clone`, payload)
    return data
  },

  // ==================== Dataset Profile (Ingestion Scan) ====================

  async getProfileSummary(datasetId: string): Promise<DatasetProfileSummary> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/profile/summary`)
    return data
  },

  async listProfileFinding(
    datasetId: string,
    findingKey: string,
    params?: { skip?: number; limit?: number }
  ): Promise<DatasetProfileFindingListResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/profile/findings/${findingKey}`, { params })
    return data
  },

  async startProfileScan(datasetId: string, body: DatasetProfileScanRunCreateRequest): Promise<DatasetProfileScanRunOut> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/profile/scan-runs`, body || {})
    return data
  },

  async listProfileScanRuns(
    datasetId: string,
    params?: { skip?: number; limit?: number }
  ): Promise<DatasetProfileScanRunListResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/profile/scan-runs`, { params })
    return data
  },

  async getProfileScanRun(datasetId: string, scanRunId: string): Promise<DatasetProfileScanRunOut> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/profile/scan-runs/${scanRunId}`)
    return data
  },

  async exportProfileSummary(datasetId: string): Promise<Blob> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/profile/export`, { responseType: 'blob' })
    return data as Blob
  },

  async exportProfileHtml(datasetId: string, params?: { redact?: boolean }): Promise<Blob> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/profile/export-html`, { params, responseType: 'blob' })
    return data as Blob
  },

  // ==================== Dataset Precheck (Local Folder Scan) ====================

  async startPrecheckScan(datasetId: string, body: DatasetPrecheckScanRunCreateRequest): Promise<DatasetPrecheckScanRunOut> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/precheck/scan-runs`, body || {})
    return data
  },

  async listPrecheckScanRuns(
    datasetId: string,
    params?: { skip?: number; limit?: number }
  ): Promise<DatasetPrecheckScanRunListResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs`, { params })
    return data
  },

  async getPrecheckScanRun(datasetId: string, scanRunId: string): Promise<DatasetPrecheckScanRunOut> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}`)
    return data
  },

  async getPrecheckSummary(datasetId: string, scanRunId: string): Promise<DatasetPrecheckSummary> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/summary`)
    return data
  },

  async listPrecheckFinding(
    datasetId: string,
    scanRunId: string,
    findingKey: string,
    params?: { skip?: number; limit?: number }
  ): Promise<DatasetPrecheckFindingListResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/findings/${findingKey}`, { params })
    return data
  },

  async exportPrecheckSummary(datasetId: string, scanRunId: string): Promise<Blob> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/export`, { responseType: 'blob' })
    return data as Blob
  },

  async exportPrecheckHtml(datasetId: string, scanRunId: string, params?: { redact?: boolean }): Promise<Blob> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/export-html`, { params, responseType: 'blob' })
    return data as Blob
  },

  async cancelPrecheckScan(datasetId: string, scanRunId: string): Promise<DatasetPrecheckScanRunOut> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/cancel`)
    return data
  },

  async getPrecheckSamples(
    datasetId: string,
    scanRunId: string,
    params?: { size?: number; prefer_artifact?: boolean }
  ): Promise<DatasetPrecheckSamplesResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/samples`, { params })
    return data
  },

  async getPrecheckNearDups(datasetId: string, scanRunId: string): Promise<DatasetPrecheckNearDupResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/near-dups`)
    return data
  },

  async diffPrecheckScanRuns(
    datasetId: string,
    scanRunId: string,
    params: { base_scan_run_id: string }
  ): Promise<DatasetPrecheckDiffResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/diff`, { params })
    return data
  },

  async suggestPrecheckIngestionPolicy(
    datasetId: string,
    scanRunId: string,
    params?: { max_names_per_bucket?: number }
  ): Promise<DatasetPrecheckIngestionSuggestionResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/suggest-ingestion-policy`, { params })
    return data
  },

  async applyPrecheckIngestionPolicy(
    datasetId: string,
    scanRunId: string,
    params?: { replace?: boolean }
  ): Promise<IngestionPolicyImportResponse> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/apply-ingestion-policy`, undefined, { params })
    return data
  },

  // ==================== Dataset Tables (TAG) ====================

  async listTables(
    datasetId: string,
    params?: { skip?: number; limit?: number; include_columns?: boolean; include_sample_rows?: boolean }
  ): Promise<DatasetTablesListResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/tables`, { params })
    return data
  },

  async getTable(
    datasetId: string,
    tableId: string,
    params?: { include_columns?: boolean; include_sample_rows?: boolean }
  ): Promise<DatasetTableAsset> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/tables/${encodeURIComponent(tableId)}`, { params })
    return data
  },

  async previewTable(datasetId: string, tableId: string, params?: { limit?: number }): Promise<TableQueryResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/tables/${encodeURIComponent(tableId)}/preview`, { params })
    return data
  },

  async queryTable(datasetId: string, tableId: string, body: TableQueryRequest): Promise<TableQueryResponse> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/tables/${encodeURIComponent(tableId)}/query`, body)
    return data
  },

  async askTable(datasetId: string, tableId: string, body: TableAskRequest): Promise<TableAskResponse> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/tables/${encodeURIComponent(tableId)}/ask`, body, { timeout: API_LONG_TIMEOUT_MS })
    return data
  },

  async lotusSemFilter(datasetId: string, tableId: string, body: LotusSemFilterRequest): Promise<TableQueryResponse> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/tables/${encodeURIComponent(tableId)}/lotus/sem-filter`, body, { timeout: API_LONG_TIMEOUT_MS })
    return data
  },
}

// ==================== 数据集分类（目录树） API ====================

export const datasetCategoryApi = {
  async listTree(): Promise<DatasetCategoryTreeResponse> {
    const { data } = await apiClient.get('/dataset-categories/')
    return data
  },

  async create(payload: DatasetCategoryCreate): Promise<DatasetCategoryOut> {
    const { data } = await apiClient.post('/dataset-categories/', payload)
    return data
  },

  async update(categoryId: string, payload: DatasetCategoryUpdate): Promise<DatasetCategoryOut> {
    const { data } = await apiClient.patch(`/dataset-categories/${categoryId}`, payload)
    return data
  },

  async move(categoryId: string, payload: DatasetCategoryMoveRequest): Promise<DatasetCategoryOut> {
    const { data } = await apiClient.post(`/dataset-categories/${categoryId}/move`, payload)
    return data
  },

  async delete(categoryId: string): Promise<void> {
    await apiClient.delete(`/dataset-categories/${categoryId}`)
  },
}

// ==================== Reports API ====================

export const reportApi = {
  async getDatasetReport(
    datasetId: string,
    params?: { pipeline_hash?: string; connector_runs_limit?: number }
  ): Promise<DatasetReport> {
    const { data } = await apiClient.get(`/reports/datasets/${datasetId}`, { params })
    return data
  },

  async exportDatasetReportJson(
    datasetId: string,
    params?: { pipeline_hash?: string; connector_runs_limit?: number }
  ): Promise<Blob> {
    const { data } = await apiClient.get(`/reports/datasets/${datasetId}/export`, { params, responseType: 'blob' })
    return data as Blob
  },

  async exportDatasetReportHtml(
    datasetId: string,
    params?: { pipeline_hash?: string; connector_runs_limit?: number; redact?: boolean }
  ): Promise<Blob> {
    const { data } = await apiClient.get(`/reports/datasets/${datasetId}/export-html`, { params, responseType: 'blob' })
    return data as Blob
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
   * 更新对话元数据（当前：title）
   */
  async updateConversation(conversationId: string, payload: { title?: string | null }): Promise<Conversation> {
    const { data } = await apiClient.patch(`/chat/conversations/${conversationId}`, payload)
    return data
  },

  /**
   * 导出对话（markdown/json）
   */
  async exportConversation(conversationId: string, params?: { fmt?: 'markdown' | 'json'; include_citations?: boolean }): Promise<Blob> {
    const { data } = await apiClient.get(`/chat/conversations/${conversationId}/export`, { params, responseType: 'blob' })
    return data as Blob
  },

  /**
   * 获取对话列表
   */
  async listConversations(params?: {
    skip?: number
    limit?: number
  }): Promise<{ total: number; returned?: number; has_more?: boolean; items: Conversation[] }> {
    const { data } = await apiClient.get('/chat/conversations', { params })
    return data
  },

  /**
   * 获取对话消息
   */
  async getMessages(
    conversationId: string,
    params?: { limit?: number; before?: string }
  ): Promise<{ conversation_id: string; messages: Message[]; returned?: number; has_more?: boolean }> {
    const { data } = await apiClient.get(`/chat/conversations/${conversationId}/messages`, { params })
    return data
  },

  /**
   * 删除对话
   */
  async deleteConversation(conversationId: string): Promise<void> {
    await apiClient.delete(`/chat/conversations/${conversationId}`)
  },

  /**
   * Get conversation RAG traces (for visualization: retrieve -> rerank -> citations).
   */
  async getRagTraces(
    conversationId: string,
    params?: { limit?: number; window_minutes?: number; max_bytes?: number }
  ): Promise<RagTraceListResponse> {
    const { data } = await apiClient.get(`/chat/conversations/${conversationId}/rag-traces`, { params })
    return data
  },

  /**
   * 发送流式聊天请求
   */
  async streamChat(
    request: ChatRequest,
    onJson: (jsonStr: string) => void,
    options: { signal?: AbortSignal; onError?: (error: unknown) => void } = {}
  ): Promise<{ requestId: string }> {
    const requestId = generateRequestId()

    const response = await fetch(`${API_V1_BASE_URL}/chat/stream`, {
      method: 'POST',
      headers: {
        'Content-Type': 'application/json',
        Accept: 'text/event-stream',
        ...getAuthHeaders(),
        'X-Request-ID': requestId,
      },
      body: JSON.stringify(request),
      signal: options.signal,
    })

    if (!response.ok) {
      throw await buildFetchError(response, 'Chat stream failed')
    }

    const reader = response.body?.getReader()
    if (!reader) {
      throw new Error('No response body')
    }

    const backendRequestId = response.headers.get('X-Request-ID') || requestId
    await readSseDataStrings(reader, onJson, options.onError)
    return { requestId: backendRequestId }
  },

  /**
   * 非流式聊天（一次性返回 JSON）
   */
  async chat(request: ChatRequest, options: { signal?: AbortSignal } = {}): Promise<ChatResponse> {
    const { data } = await apiClient.post('/chat', request, { timeout: API_LONG_TIMEOUT_MS, signal: options.signal })
    return data
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

  async getConversationSummary(conversationId: string): Promise<ConversationSummaryResponse> {
    const { data } = await apiClient.get(`/chat/conversations/${conversationId}/summary`)
    return data
  },

  async updateConversationSummary(conversationId: string): Promise<ConversationSummaryUpdateResponse> {
    const { data } = await apiClient.post(`/chat/conversations/${conversationId}/summary/update`)
    return data
  },

  async deleteConversationSummary(conversationId: string): Promise<void> {
    await apiClient.delete(`/chat/conversations/${conversationId}/summary`)
  },
}

// ==================== SSE helpers (scan progress) ====================

export const sseApi = {
  async streamPrecheckScanEvents(
    datasetId: string,
    scanRunId: string,
    onJson: (jsonStr: string) => void,
    options: { onError?: (error: unknown) => void; signal?: AbortSignal } = {}
  ): Promise<{ requestId: string }> {
    const requestId = generateRequestId()

    const response = await fetch(`${API_V1_BASE_URL}/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/events`, {
      method: 'GET',
      headers: {
        Accept: 'text/event-stream',
        ...getAuthHeaders(),
        'X-Request-ID': requestId,
      },
      signal: options.signal,
    })

    if (!response.ok) {
      throw await buildFetchError(response, 'Precheck SSE failed')
    }

    const reader = response.body?.getReader()
    if (!reader) {
      throw new Error('No response body')
    }

    const backendRequestId = response.headers.get('X-Request-ID') || requestId
    await readSseDataStrings(reader, onJson, options.onError)
    return { requestId: backendRequestId }
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

  /**
   * 获取反馈列表（联表包含消息内容/对话标题，用于质检面板）
   */
  async listEnriched(params?: {
    skip?: number
    limit?: number
    conversation_id?: string
    message_id?: string
    min_rating?: number
    max_rating?: number
  }): Promise<MessageFeedbackEnrichedListResponse> {
    const { data } = await apiClient.get('/feedback/messages/enriched', { params })
    return data
  },

  /**
   * 将反馈转为回归用例（RAGAS regression case）
   */
  async toRegressionCase(
    feedbackId: string,
    body: { include_document_scope?: boolean; tags?: string[]; extra?: Record<string, any> } = {}
  ): Promise<RegressionCase> {
    const { data } = await apiClient.post(`/feedback/messages/${feedbackId}/to-regression-case`, body)
    return data
  },
}

// ==================== KG API ====================

export const kgApi = {
  /**
   * 触发 KG 实体/事件抽取
   */
  async extract(
    documentId: string,
    params?: {
      async?: boolean
      replace_existing?: boolean
      prune_orphan_entities?: boolean
      prompt_template_id?: string
      prompt_template_key?: string
      prompt_ab_experiment_key?: string
    }
  ): Promise<KGExtractResponse> {
    const { data } = await apiClient.post(`/kg/documents/${documentId}/extract`, null, { params })
    return data
  },

  async deleteDocumentKG(
    documentId: string,
    params?: { prune_orphan_entities?: boolean }
  ): Promise<KGDeleteResponse> {
    const { data } = await apiClient.delete(`/kg/documents/${documentId}`, { params })
    return data
  },

  /**
   * KG 搜索
   */
  async search(params: KGSearchRequest): Promise<KGSearchResponse> {
    const { data } = await apiClient.post('/kg/search', params)
    return data
  },

  async getStats(params?: { document_ids?: string[] }): Promise<KGStatsResponse> {
    const { data } = await apiClient.get('/kg/stats', { params })
    return data
  },

  async getGraph(params?: {
    document_ids?: string[]
    max_events?: number
    max_entities?: number
    max_links?: number
    include_entity_links?: boolean
    min_shared_events?: number
    max_entity_links?: number
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
    include_entity_links?: boolean
    min_shared_events?: number
    max_entity_links?: number
  }): Promise<KGGraphResponse> {
    const { data } = await apiClient.get('/kg/graph/expand', { params })
    return data
  },

  async exportGraphML(params?: {
    document_ids?: string[]
    max_events?: number
    max_entities?: number
    max_links?: number
    include_entity_links?: boolean
    min_shared_events?: number
    max_entity_links?: number
  }): Promise<string> {
    const { data } = await apiClient.get('/kg/graph/export', {
      params,
      responseType: 'text',
    })
    return data as unknown as string
  },

  async getEvent(eventId: string, params?: { document_ids?: string[] }): Promise<KGEventDetailResponse> {
    const { data } = await apiClient.get(`/kg/events/${eventId}`, { params })
    return data
  },

  async getEntity(
    entityId: string,
    params?: { document_ids?: string[]; max_events?: number; max_neighbors?: number }
  ): Promise<KGEntityDetailResponse> {
    const { data } = await apiClient.get(`/kg/entities/${entityId}`, { params })
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

export interface RAGConfig {
  chunk_size: number
  chunk_overlap: number
  chunk_min_chars: number
  retrieval_top_k: number
  similarity_threshold: number
  default_parser_backend: string
  default_chunk_strategy: string
  bm25_index_enabled: boolean
  enable_reranker: boolean
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

export interface SystemSettings {
  feature_flags: FeatureFlags
  kg: KGConfig
  llm: LLMConfig
  embedding: EmbeddingConfig
  milvus: MilvusConfig
  rag: RAGConfig
  cache: CacheConfig
  url_ingest: UrlIngestConfig
  governance: GovernanceConfig
  mineru: MinerUConfig
  etl4llm: Etl4LlmConfig
  marker: MarkerConfig
  paddle_vl: PaddleVLConfig
  magicpdf: MagicPDFConfig
  observability: ObservabilityConfig
  safety: SafetyConfig
  chat: ChatConfig
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

export const observabilityApi = {
  async getRagMetricsSummary(params: { window_minutes?: number; max_bytes?: number }): Promise<RagMetricsSummaryResponse> {
    const { data } = await apiClient.get('/observability/rag-metrics/summary', { params })
    return data
  },
}

export const usageApi = {
  async getChatTokenUsageSummary(params: { window_days?: number; since?: string; until?: string } = {}): Promise<ChatTokenUsageSummary> {
    const { data } = await apiClient.get('/usage/chat/tokens/summary', { params })
    return data
  },

  async getChatTokenQuotaStatus(): Promise<ChatTokenQuotaStatus> {
    const { data } = await apiClient.get('/usage/chat/tokens/quota')
    return data
  },
}

export const auditApi = {
  async listLogs(params: {
    skip?: number
    limit?: number
    actor_id?: string
    action?: string
    resource_type?: string
    resource_id?: string
    request_id?: string
    since?: string
    until?: string
  } = {}): Promise<AuditLogListResponse> {
    const { data } = await apiClient.get('/audit/logs', { params })
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

// ==================== RAGViz (Similarity Heatmap) API ====================

export const ragvizApi = {
  async listSimilarityCollections(): Promise<RagvizSimilarityCollectionsResponse> {
    const { data } = await apiClient.get('/ragviz/similarity/collections')
    return data
  },

  async calculateSimilarityMatrix(params: RagvizSimilarityRequest): Promise<RagvizSimilarityCalculateResponse> {
    const { data } = await apiClient.post('/ragviz/similarity/calculate', params)
    return data
  },
}

export default apiClient
