import type {
  BatchFileInfo,
  BatchTaskStatus,
  BatchUploadResponse,
  ChunkPreviewResponse,
  Document,
  DocumentAccessInfo,
  DocumentAccessUpdateRequest,
  DocumentBatchAccessUpdateRequest,
  DocumentBatchAccessUpdateResponse,
  DocumentBatchLifecycleResponse,
  DocumentBatchMoveRequest,
  DocumentBatchMoveResponse,
  DocumentBatchReingestRequest,
  DocumentBatchRetryRequest,
  DocumentBatchRetryResponse,
  DocumentBatchUploadResponse,
  DocumentBatchUserMetadataPatchRequest,
  DocumentBatchUserMetadataPatchResponse,
  DocumentChunk,
  DocumentChunkCreateRequest,
  DocumentChunkList,
  DocumentChunkMatchList,
  DocumentChunkReembedRequest,
  DocumentChunkReembedResponse,
  DocumentChunkUpdateRequest,
  DocumentDuplicateList,
  DocumentFolderTreeResponse,
  DocumentHealthCard,
  DocumentLifecycleMetadata,
  DocumentLifecycleMetadataUpdateRequest,
  DocumentList,
  DocumentParsedContentResponse,
  DocumentPipelineOptions,
  DocumentPipelinePatchRequest,
  DocumentPreview,
  DocumentQAGenerateRequest,
  DocumentQAGenerateResponse,
  DocumentStats,
  DocumentStatus,
  DocumentTimelineResponse,
  DocumentUserMetadataPatchRequest,
  DocumentVersionDiff,
  DocumentVersionList,
  IngestDeadLetterList,
  IngestDeadLetterReplayResponse,
  ManualChunk,
} from '@/types'
import { z } from 'zod'

import { API_LONG_TIMEOUT_MS } from '@/lib/env'
import { appendPipelineOptionsToFormData } from '@/lib/form-data'
import { resolveParserBackendForFilename, resolveParserBackendForFiles } from '@/lib/parser-compat'
import { apiClient, openapiRequest, type ApiRequestOptions } from '@/lib/api/core'
import {
  appendChunkPreviewFormFields,
  buildChunkPreviewQueryParams,
  type ChunkPreviewRequestParams,
  type DocumentLifecycleFilter,
} from '@/lib/api/document-helpers'

function resolveChunkPreviewStrategy(chunkStrategy?: string): string {
  return chunkStrategy || 'langchain_recursive'
}

const documentParsedContentResponseSchema: z.ZodType<DocumentParsedContentResponse> = z.looseObject({
    document_id: z.string(),
    available: z.boolean(),
    markdown_content: z.string(),
    original_markdown_content: z.string(),
    persisted_meta: z.record(z.string(), z.unknown()).optional(),
    markdown_truncated: z.boolean(),
    original_markdown_truncated: z.boolean(),
    max_chars: z.number().int(),
  })

export const documentApi = {
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

  async uploadFromUrl(params: {
    url: string
    dataset_id?: string
    filename?: string
    parser_backend?: string
    chunk_strategy?: string
    pipeline?: DocumentPipelineOptions
  }): Promise<Document> {
    const body = {
      url: params.url,
      dataset_id: params.dataset_id,
      filename: params.filename,
      parser_backend: params.parser_backend || 'auto',
      chunk_strategy: params.chunk_strategy || 'langchain_recursive',
      pipeline: params.pipeline,
    }
    return openapiRequest({
      path: '/api/v1/documents/upload-url',
      method: 'post',
      body,
    })
  },

  async uploadBatch(
    files: File[],
    options: {
      parser_backend?: string
      chunk_strategy?: string
      dataset_id?: string
      precheck_only?: boolean
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
    if (options.precheck_only) {
      formData.append('precheck_only', 'true')
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

  async list(
    params?: {
      skip?: number
      limit?: number
      status?: string | null
      lifecycle?: DocumentLifecycleFilter
      dataset_id?: string | null
      file_type?: string | null
      owner_id?: string | null
      q?: string | null
      source_path_prefix?: string | null
      order_by?: 'created_at' | 'filename' | 'file_size'
      order_dir?: 'asc' | 'desc'
    },
    options?: ApiRequestOptions
  ): Promise<DocumentList> {
    return openapiRequest({
      path: '/api/v1/documents/',
      method: 'get',
      query: params,
      signal: options?.signal,
    })
  },

  async listDeadLetters(
    params?: {
      skip?: number
      limit?: number
      status?: string | null
      dataset_id?: string | null
      document_id?: string | null
      error_code?: string | null
      failed_stage?: string | null
    },
    options?: ApiRequestOptions
  ): Promise<IngestDeadLetterList> {
    return openapiRequest({
      path: '/api/v1/documents/dead-letters',
      method: 'get',
      query: params,
      signal: options?.signal,
    })
  },

  async replayDeadLetter(deadLetterId: string): Promise<IngestDeadLetterReplayResponse> {
    return openapiRequest({
      path: '/api/v1/documents/dead-letters/{dead_letter_id}/replay',
      method: 'post',
      pathParams: { dead_letter_id: deadLetterId },
    })
  },

  async folders(params: {
    dataset_id: string
    lifecycle?: DocumentLifecycleFilter
    max_depth?: number
  }): Promise<DocumentFolderTreeResponse> {
    return openapiRequest({
      path: '/api/v1/documents/folders',
      method: 'get',
      query: params,
    })
  },

  async stats(params?: {
    dataset_id?: string | null
    lifecycle?: DocumentLifecycleFilter
    file_type?: string | null
    owner_id?: string | null
    q?: string | null
  }): Promise<DocumentStats> {
    return openapiRequest({
      path: '/api/v1/documents/stats',
      method: 'get',
      query: params,
    })
  },

  async get(
    documentId: string,
    options?: { includeChunks?: boolean; pipeline_hash?: string; all_versions?: boolean },
    request?: ApiRequestOptions
  ): Promise<Document> {
    const query = options?.includeChunks
      ? {
          include_chunks: true,
          pipeline_hash: options.pipeline_hash,
          all_versions: options.all_versions,
        }
      : undefined

    return openapiRequest({
      path: '/api/v1/documents/{document_id}',
      method: 'get',
      pathParams: { document_id: documentId },
      query,
      signal: request?.signal,
    })
  },

  async health(
    documentId: string,
    params?: { window_minutes?: number; max_bytes?: number; max_chunks_scored?: number }
  ): Promise<DocumentHealthCard> {
    const encoded = encodeURIComponent(String(documentId))
    const { data } = await apiClient.get(`/documents/${encoded}/health`, { params })
    return data
  },

  async getTimeline(documentId: string, params?: { limit?: number }): Promise<DocumentTimelineResponse> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/timeline',
      method: 'get',
      pathParams: { document_id: documentId },
      query: params,
    })
  },

  async getAccess(documentId: string): Promise<DocumentAccessInfo> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/access',
      method: 'get',
      pathParams: { document_id: documentId },
    })
  },

  async updateAccess(documentId: string, payload: DocumentAccessUpdateRequest): Promise<DocumentAccessInfo> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/access',
      method: 'put',
      pathParams: { document_id: documentId },
      body: payload,
    })
  },

  async getParsedContent(
    documentId: string,
    params?: { max_chars?: number }
  ): Promise<DocumentParsedContentResponse> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/parsed-content',
      method: 'get',
      pathParams: { document_id: documentId },
      query: params,
      responseSchema: documentParsedContentResponseSchema,
      responseSchemaName: 'DocumentParsedContentResponse',
    })
  },

  async listChunks(
    documentId: string,
    params?: { skip?: number; limit?: number; q?: string; pipeline_hash?: string; all_versions?: boolean }
  ): Promise<DocumentChunkList> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/chunks',
      method: 'get',
      pathParams: { document_id: documentId },
      query: params,
    })
  },

  async getChunkMatches(
    documentId: string,
    params: { q: string; limit?: number; pipeline_hash?: string; all_versions?: boolean }
  ): Promise<DocumentChunkMatchList> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/chunks/matches',
      method: 'get',
      pathParams: { document_id: documentId },
      query: params,
    })
  },

  async getChunk(documentId: string, chunkId: string): Promise<DocumentChunk> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/chunks/{chunk_id}',
      method: 'get',
      pathParams: { document_id: documentId, chunk_id: chunkId },
    })
  },

  async createChunk(documentId: string, payload: DocumentChunkCreateRequest): Promise<DocumentChunk> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/chunks',
      method: 'post',
      pathParams: { document_id: documentId },
      body: payload,
    })
  },

  async updateChunk(documentId: string, chunkId: string, payload: DocumentChunkUpdateRequest): Promise<DocumentChunk> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/chunks/{chunk_id}',
      method: 'patch',
      pathParams: { document_id: documentId, chunk_id: chunkId },
      body: payload,
    })
  },

  async deleteChunk(documentId: string, chunkId: string): Promise<void> {
    await openapiRequest({
      path: '/api/v1/documents/{document_id}/chunks/{chunk_id}',
      method: 'delete',
      pathParams: { document_id: documentId, chunk_id: chunkId },
    })
  },

  async disableChunk(documentId: string, chunkId: string): Promise<DocumentChunk> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/chunks/{chunk_id}/disable',
      method: 'post',
      pathParams: { document_id: documentId, chunk_id: chunkId },
    })
  },

  async enableChunk(documentId: string, chunkId: string): Promise<DocumentChunk> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/chunks/{chunk_id}/enable',
      method: 'post',
      pathParams: { document_id: documentId, chunk_id: chunkId },
    })
  },

  async reembedChunks(documentId: string, payload: DocumentChunkReembedRequest): Promise<DocumentChunkReembedResponse> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/chunks/reembed',
      method: 'post',
      pathParams: { document_id: documentId },
      body: payload,
    })
  },

  async generateQa(documentId: string, payload: DocumentQAGenerateRequest): Promise<DocumentQAGenerateResponse> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/qa/generate',
      method: 'post',
      pathParams: { document_id: documentId },
      body: payload,
    })
  },

  async download(documentId: string, params?: { inline?: boolean }): Promise<Blob> {
    const { data } = await apiClient.get(`/documents/${documentId}/download`, {
      params,
      responseType: 'blob',
    })
    return data
  },

  async cleanDocx(documentId: string): Promise<Blob> {
    const { data } = await apiClient.get(`/documents/${documentId}/clean-docx`, {
      responseType: 'blob',
    })
    return data as Blob
  },

  async getStatus(documentId: string): Promise<DocumentStatus> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/status',
      method: 'get',
      pathParams: { document_id: documentId },
    })
  },

  async cancel(documentId: string): Promise<DocumentStatus> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/cancel',
      method: 'post',
      pathParams: { document_id: documentId },
    })
  },

  async retry(documentId: string, params?: { force?: boolean; skip_if_unchanged?: boolean }): Promise<DocumentStatus> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/retry',
      method: 'post',
      pathParams: { document_id: documentId },
      query: params,
    })
  },

  async delete(documentId: string): Promise<void> {
    await openapiRequest({
      path: '/api/v1/documents/{document_id}',
      method: 'delete',
      pathParams: { document_id: documentId },
    })
  },

  async batchDelete(
    document_ids: string[]
  ): Promise<{ deleted: number; not_found?: string[]; denied?: string[] }> {
    return openapiRequest({
      path: '/api/v1/documents/batch-delete',
      method: 'post',
      body: { document_ids },
    })
  },

  async batchDisable(document_ids: string[]): Promise<DocumentBatchLifecycleResponse> {
    return openapiRequest({
      path: '/api/v1/documents/batch/disable',
      method: 'post',
      body: { document_ids },
    })
  },

  async batchEnable(document_ids: string[]): Promise<DocumentBatchLifecycleResponse> {
    return openapiRequest({
      path: '/api/v1/documents/batch/enable',
      method: 'post',
      body: { document_ids },
    })
  },

  async batchArchive(document_ids: string[]): Promise<DocumentBatchLifecycleResponse> {
    return openapiRequest({
      path: '/api/v1/documents/batch/archive',
      method: 'post',
      body: { document_ids },
    })
  },

  async batchUnarchive(document_ids: string[]): Promise<DocumentBatchLifecycleResponse> {
    return openapiRequest({
      path: '/api/v1/documents/batch/unarchive',
      method: 'post',
      body: { document_ids },
    })
  },

  async batchRetry(payload: DocumentBatchRetryRequest): Promise<DocumentBatchRetryResponse> {
    return openapiRequest({
      path: '/api/v1/documents/batch/retry',
      method: 'post',
      body: payload,
    })
  },

  async batchReingest(payload: DocumentBatchReingestRequest): Promise<DocumentBatchRetryResponse> {
    return openapiRequest({
      path: '/api/v1/documents/batch/reingest',
      method: 'post',
      body: payload,
    })
  },

  async batchUpdateAccess(payload: DocumentBatchAccessUpdateRequest): Promise<DocumentBatchAccessUpdateResponse> {
    return openapiRequest({
      path: '/api/v1/documents/batch/access',
      method: 'post',
      body: payload,
    })
  },

  async batchMove(payload: DocumentBatchMoveRequest): Promise<DocumentBatchMoveResponse> {
    return openapiRequest({
      path: '/api/v1/documents/batch/move',
      method: 'post',
      body: payload,
    })
  },

  async listDuplicates(params: {
    dataset_id: string
    min_count?: number
    max_groups?: number
    max_docs_per_group?: number
  }): Promise<DocumentDuplicateList> {
    return openapiRequest({
      path: '/api/v1/documents/duplicates',
      method: 'get',
      query: params,
    })
  },

  async patchUserMetadata(
    documentId: string,
    payload: DocumentUserMetadataPatchRequest
  ): Promise<Document> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/metadata',
      method: 'patch',
      pathParams: { document_id: documentId },
      body: payload,
    })
  },

  async patchPipeline(
    documentId: string,
    payload: DocumentPipelinePatchRequest
  ): Promise<Document> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/pipeline',
      method: 'patch',
      pathParams: { document_id: documentId },
      body: payload,
    })
  },

  async getLifecycleMetadata(documentId: string): Promise<DocumentLifecycleMetadata> {
    const { data } = await apiClient.get(`/documents/${encodeURIComponent(documentId)}/lifecycle-metadata`)
    return data
  },

  async patchLifecycleMetadata(
    documentId: string,
    payload: DocumentLifecycleMetadataUpdateRequest
  ): Promise<DocumentLifecycleMetadata> {
    const { data } = await apiClient.patch(
      `/documents/${encodeURIComponent(documentId)}/lifecycle-metadata`,
      payload
    )
    return data
  },

  async listVersions(documentId: string, options?: ApiRequestOptions): Promise<DocumentVersionList> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/versions',
      method: 'get',
      pathParams: { document_id: documentId },
      signal: options?.signal,
    })
  },

  async activateVersion(documentId: string, pipelineHash: string): Promise<Document> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/versions/{pipeline_hash}/activate',
      method: 'post',
      pathParams: { document_id: documentId, pipeline_hash: pipelineHash },
    })
  },

  async deleteVersion(documentId: string, pipelineHash: string): Promise<void> {
    await openapiRequest({
      path: '/api/v1/documents/{document_id}/versions/{pipeline_hash}',
      method: 'delete',
      pathParams: { document_id: documentId, pipeline_hash: pipelineHash },
    })
  },

  async diffVersions(params: {
    document_id: string
    from: string
    to: string
    sample_limit?: number
  }): Promise<DocumentVersionDiff> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/versions/diff',
      method: 'get',
      pathParams: { document_id: params.document_id },
      query: { from: params.from, to: params.to, sample_limit: params.sample_limit },
    })
  },

  async batchPatchUserMetadata(
    payload: DocumentBatchUserMetadataPatchRequest
  ): Promise<DocumentBatchUserMetadataPatchResponse> {
    return openapiRequest({
      path: '/api/v1/documents/batch/metadata',
      method: 'post',
      body: payload,
    })
  },

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

  async createFromChunks(params: {
    filename: string
    file_type: string
    file_size: number
    chunks: ManualChunk[]
    dataset_id?: string
    metadata?: Record<string, any>
    pipeline?: DocumentPipelineOptions
  }): Promise<Document> {
    return openapiRequest({
      path: '/api/v1/documents/manual',
      method: 'post',
      body: params,
    })
  },

  async chunkPreview(
    file: File,
    params: ChunkPreviewRequestParams = {},
    options?: { signal?: AbortSignal }
  ): Promise<ChunkPreviewResponse> {
    const resolvedParser = resolveParserBackendForFilename(file.name, params.parser_backend || 'auto')
    const effectiveStrategy = resolveChunkPreviewStrategy(params.chunk_strategy)
    const formData = new FormData()
    formData.append('file', file)
    formData.append('parser_backend', resolvedParser.backend || 'auto')
    formData.append('chunk_strategy', effectiveStrategy)
    appendChunkPreviewFormFields(formData, params, effectiveStrategy)

    const { data } = await apiClient.post('/documents/chunk-preview', formData, {
      timeout: API_LONG_TIMEOUT_MS,
      signal: options?.signal,
      params: buildChunkPreviewQueryParams(params),
    })

    return data
  },

  async chunkPreviewBySha(
    params: ChunkPreviewRequestParams & {
      file_sha256: string
      file_type?: string
      filename?: string
      file_size?: number
    },
    options?: { signal?: AbortSignal }
  ): Promise<ChunkPreviewResponse> {
    const name = params.filename || `doc.${String(params.file_type || 'txt').replace(/^\\.+/, '')}`
    const resolvedParser = resolveParserBackendForFilename(name, params.parser_backend || 'auto')
    const effectiveStrategy = resolveChunkPreviewStrategy(params.chunk_strategy)

    const formData = new FormData()
    formData.append('file_sha256', String(params.file_sha256 || ''))
    if (params.file_type) formData.append('file_type', params.file_type)
    if (params.filename) formData.append('filename', params.filename)
    if (typeof params.file_size === 'number') formData.append('file_size', String(params.file_size))
    formData.append('parser_backend', resolvedParser.backend || 'auto')
    formData.append('chunk_strategy', effectiveStrategy)
    appendChunkPreviewFormFields(formData, params, effectiveStrategy)

    const { data } = await apiClient.post('/documents/chunk-preview/by-sha', formData, {
      timeout: API_LONG_TIMEOUT_MS,
      signal: options?.signal,
      params: buildChunkPreviewQueryParams(params),
    })

    return data
  },

  async applyBatchUploadUrls(files: BatchFileInfo[]): Promise<BatchUploadResponse> {
    return openapiRequest({
      path: '/api/v1/documents/batch-upload/apply-urls',
      method: 'post',
      body: { files },
    })
  },

  async getBatchTaskStatus(batchId: string): Promise<BatchTaskStatus> {
    return openapiRequest({
      path: '/api/v1/documents/batch-upload/status/{batch_id}',
      method: 'get',
      pathParams: { batch_id: batchId },
    })
  },

  async fetchImage(imageId: string): Promise<Blob> {
    const { data } = await apiClient.get(`/documents/image/${imageId}`, { responseType: 'blob' })
    return data as Blob
  },

  async fetchImageByImgId(imgId: string): Promise<Blob> {
    const { data } = await apiClient.get(`/documents/image-url/${encodeURIComponent(imgId)}`, { responseType: 'blob' })
    return data as Blob
  },
}
