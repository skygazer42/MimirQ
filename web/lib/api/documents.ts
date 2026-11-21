import type {
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
  DocumentList,
  DocumentParsedContentResponse,
  DocumentPipelineOptions,
  DocumentPipelinePatchRequest,
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
  OpenApiSchema,
} from '@/types/backend'
import type { JsonObject } from '@/types/common'
import type { OpenApiQueryParams } from '@/types/openapi-helpers'
import type {
  ChunkPreviewResponse,
  DocumentLifecycleMetadata,
  DocumentLifecycleMetadataUpdateRequest,
  DocumentPreview,
  ManualChunk,
} from '@/types/processing'
import { z } from 'zod'

import { API_LONG_TIMEOUT_MS } from '@/lib/env'
import { documentAccessInfoSchema } from '@/lib/document-access-schema'
import {
  createDocumentBatchRetryResponseSchema,
  createDocumentBatchUploadResponseSchema,
} from '@/lib/document-batch-schema'
import { parseApiResponse } from '@/lib/openapi-request'
import { resolveParserBackendForFilename, resolveParserBackendForFiles } from '@/lib/parser-compat'
import { integerSchema } from '@/lib/response-schema'
import { apiClient, openapiRequest, type ApiRequestOptions } from '@/lib/api/core'
import {
  appendChunkPreviewSettings,
  appendPipelineOptionsToForm,
  buildChunkPreviewQueryParams,
  DOCUMENT_UPLOAD_BATCH_LIMIT,
  getUploadFilename,
  type ChunkPreviewRequestParams,
  type DocumentLifecycleFilter,
} from '@/lib/api/document-helpers'

type BatchFileInfo = OpenApiSchema<'BatchFileInfo'>
type BatchTaskStatus = OpenApiSchema<'BatchTaskStatus'>
type BatchUploadResponse = OpenApiSchema<'BatchUploadResponse'>

const documentChunkMatchListSchema = z.looseObject({
  total: integerSchema.nonnegative(),
  truncated: z.boolean(),
  items: z.array(
    z.looseObject({
      id: z.string(),
      chunk_index: integerSchema,
      page_number: integerSchema.nullish(),
    }),
  ),
}) satisfies z.ZodType<Required<DocumentChunkMatchList>>

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
      dataset_id?: string | null
      pipeline?: DocumentPipelineOptions
      user_metadata?: JsonObject
    } = {},
  ): Promise<Document> {
    const resolvedParser = resolveParserBackendForFilename(file.name, options.parser_backend)
    const formData = new FormData()
    const uploadName = getUploadFilename(file)
    formData.append('file', file, uploadName)
    formData.append('parser_backend', resolvedParser.backend)
    if (options.chunk_strategy !== undefined) {
      formData.append('chunk_strategy', options.chunk_strategy)
    }
    if (options.dataset_id) {
      formData.append('dataset_id', options.dataset_id)
    }
    if (options.user_metadata) {
      formData.append('user_metadata', JSON.stringify(options.user_metadata))
    }
    appendPipelineOptionsToForm(formData, options.pipeline)

    const { data } = await apiClient.post('/documents/upload', formData)
    return data
  },

  async uploadFromUrl(params: {
    url: string
    dataset_id?: string
    filename?: string
    parser_backend: string
    chunk_strategy: string
    pipeline?: DocumentPipelineOptions
  }): Promise<Document> {
    const body = {
      url: params.url,
      dataset_id: params.dataset_id,
      filename: params.filename,
      parser_backend: params.parser_backend,
      chunk_strategy: params.chunk_strategy,
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
      dataset_id?: string | null
      precheck_only?: boolean
      upload_only?: boolean
      pipeline?: DocumentPipelineOptions
      max_concurrent?: number
      user_metadata_map?: Record<string, JsonObject>
    } = {},
  ) {
    if (files.length > DOCUMENT_UPLOAD_BATCH_LIMIT) {
      throw new RangeError(`一次最多提交 ${DOCUMENT_UPLOAD_BATCH_LIMIT} 个文件，请分批提交`)
    }
    const resolvedParser = resolveParserBackendForFiles(files, options.parser_backend)
    const formData = new FormData()
    for (const file of files) {
      const uploadName = getUploadFilename(file)
      formData.append('files', file, uploadName)
    }
    formData.append('parser_backend', resolvedParser.backend)
    if (options.chunk_strategy !== undefined) {
      formData.append('chunk_strategy', options.chunk_strategy)
    }
    if (options.dataset_id) {
      formData.append('dataset_id', options.dataset_id)
    }
    if (options.precheck_only) {
      formData.append('precheck_only', 'true')
    }
    if (options.upload_only) {
      formData.append('upload_only', 'true')
    }
    if (typeof options.max_concurrent === 'number') {
      formData.append('max_concurrent', String(options.max_concurrent))
    }
    if (options.user_metadata_map) {
      formData.append('user_metadata_map', JSON.stringify(options.user_metadata_map))
    }
    appendPipelineOptionsToForm(formData, options.pipeline)

    const response = await apiClient.post<unknown>('/documents/upload-batch', formData)
    return parseApiResponse(
      response,
      createDocumentBatchUploadResponseSchema(files.length, options.precheck_only === true),
      'DocumentBatchUpload',
    )
  },

  async list(
    params?: OpenApiQueryParams<'/api/v1/documents/', 'get'>,
    options?: ApiRequestOptions,
  ): Promise<DocumentList> {
    const { data } = await apiClient.get<DocumentList>('/documents', {
      params,
      signal: options?.signal,
    })
    return data
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
    options?: ApiRequestOptions,
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

  async folders(
    params: { dataset_id: string; lifecycle?: DocumentLifecycleFilter; max_depth?: number },
    options?: ApiRequestOptions,
  ): Promise<DocumentFolderTreeResponse> {
    return openapiRequest({
      path: '/api/v1/documents/folders',
      method: 'get',
      query: params,
      signal: options?.signal,
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
    request?: ApiRequestOptions,
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

  health(
    documentId: string,
    params?: OpenApiQueryParams<'/api/v1/documents/{document_id}/health', 'get'>,
    options: ApiRequestOptions = {},
  ) {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/health',
      method: 'get',
      pathParams: { document_id: documentId },
      query: params,
      signal: options.signal,
    })
  },

  getTimeline(
    documentId: string,
    params?: OpenApiQueryParams<'/api/v1/documents/{document_id}/timeline', 'get'>,
    options?: ApiRequestOptions,
  ): Promise<DocumentTimelineResponse> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/timeline',
      method: 'get',
      pathParams: { document_id: documentId },
      query: params,
      signal: options?.signal,
    })
  },

  getAccess(documentId: string, options?: ApiRequestOptions): Promise<DocumentAccessInfo> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/access',
      method: 'get',
      pathParams: { document_id: documentId },
      signal: options?.signal,
      responseSchema: documentAccessInfoSchema,
      responseSchemaName: 'DocumentAccessInfo',
    })
  },

  updateAccess(documentId: string, payload: DocumentAccessUpdateRequest): Promise<DocumentAccessInfo> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/access',
      method: 'put',
      pathParams: { document_id: documentId },
      body: payload,
      responseSchema: documentAccessInfoSchema,
      responseSchemaName: 'DocumentAccessInfo',
    })
  },

  async getParsedContent(
    documentId: string,
    params?: { max_chars?: number },
    options?: ApiRequestOptions,
  ): Promise<DocumentParsedContentResponse> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/parsed-content',
      method: 'get',
      pathParams: { document_id: documentId },
      query: params,
      signal: options?.signal,
      responseSchema: documentParsedContentResponseSchema,
      responseSchemaName: 'DocumentParsedContentResponse',
    })
  },

  async listChunks(
    documentId: string,
    params?: { skip?: number; limit?: number; q?: string; pipeline_hash?: string; all_versions?: boolean },
    options?: ApiRequestOptions,
  ): Promise<DocumentChunkList> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/chunks',
      method: 'get',
      pathParams: { document_id: documentId },
      query: params,
      signal: options?.signal,
    })
  },

  async getChunkMatches(
    documentId: string,
    params: { q: string; limit?: number; pipeline_hash?: string; all_versions?: boolean },
    options?: ApiRequestOptions,
  ): Promise<Required<DocumentChunkMatchList>> {
    const response = await apiClient.get<unknown>(`/documents/${encodeURIComponent(documentId)}/chunks/matches`, {
      params,
      signal: options?.signal,
    })
    return parseApiResponse(response, documentChunkMatchListSchema, 'DocumentChunkMatchList')
  },

  async getChunk(documentId: string, chunkId: string, options?: ApiRequestOptions): Promise<DocumentChunk> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/chunks/{chunk_id}',
      method: 'get',
      pathParams: { document_id: documentId, chunk_id: chunkId },
      signal: options?.signal,
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

  async download(documentId: string, params?: { inline?: boolean }, options?: ApiRequestOptions): Promise<Blob> {
    const { data } = await apiClient.get<Blob>(`/documents/${documentId}/download`, {
      params,
      signal: options?.signal,
      responseType: 'blob',
    })
    return data
  },

  async cleanDocx(documentId: string): Promise<Blob> {
    const { data } = await apiClient.get<Blob>(`/documents/${documentId}/clean-docx`, {
      responseType: 'blob',
    })
    return data
  },

  async getStatus(documentId: string, options?: ApiRequestOptions): Promise<DocumentStatus> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/status',
      method: 'get',
      pathParams: { document_id: documentId },
      signal: options?.signal,
    })
  },

  async cancel(documentId: string): Promise<DocumentStatus> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/cancel',
      method: 'post',
      pathParams: { document_id: documentId },
    })
  },

  async retry(
    documentId: string,
    params?: { force?: boolean; skip_if_unchanged?: boolean; parser_backend?: string },
  ): Promise<DocumentStatus> {
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

  async batchDelete(document_ids: string[]): Promise<{ deleted: number; not_found?: string[]; denied?: string[] }> {
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
    const response = await apiClient.post<unknown>('/documents/batch/retry', payload)
    return parseApiResponse(
      response,
      createDocumentBatchRetryResponseSchema(payload.document_ids.length),
      'DocumentBatchRetry',
    )
  },

  async batchReingest(payload: DocumentBatchReingestRequest): Promise<DocumentBatchRetryResponse> {
    const response = await apiClient.post<unknown>('/documents/batch/reingest', payload)
    return parseApiResponse(
      response,
      createDocumentBatchRetryResponseSchema(payload.document_ids.length),
      'DocumentBatchReingest',
    )
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

  async patchUserMetadata(documentId: string, payload: DocumentUserMetadataPatchRequest): Promise<Document> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/metadata',
      method: 'patch',
      pathParams: { document_id: documentId },
      body: payload,
    })
  },

  async patchPipeline(documentId: string, payload: DocumentPipelinePatchRequest): Promise<Document> {
    return openapiRequest({
      path: '/api/v1/documents/{document_id}/pipeline',
      method: 'patch',
      pathParams: { document_id: documentId },
      body: payload,
    })
  },

  async getLifecycleMetadata(documentId: string, options?: ApiRequestOptions): Promise<DocumentLifecycleMetadata> {
    const { data } = await apiClient.get<DocumentLifecycleMetadata>(
      `/documents/${encodeURIComponent(documentId)}/lifecycle-metadata`,
      { signal: options?.signal },
    )
    return data
  },

  async patchLifecycleMetadata(
    documentId: string,
    payload: DocumentLifecycleMetadataUpdateRequest,
  ): Promise<DocumentLifecycleMetadata> {
    const { data } = await apiClient.patch(`/documents/${encodeURIComponent(documentId)}/lifecycle-metadata`, payload)
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
    payload: DocumentBatchUserMetadataPatchRequest,
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
    options?: { signal?: AbortSignal; dataset_id?: string },
  ): Promise<DocumentPreview> {
    const resolvedParser = resolveParserBackendForFilename(file.name, parserBackend)
    const formData = new FormData()
    formData.append('file', file)
    formData.append('parser_backend', resolvedParser.backend)
    if (options?.dataset_id) formData.append('dataset_id', options.dataset_id)
    appendPipelineOptionsToForm(formData, pipeline)

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
    metadata?: JsonObject
    pipeline?: DocumentPipelineOptions
  }): Promise<Document> {
    return openapiRequest({
      path: '/api/v1/documents/manual',
      method: 'post',
      body: params,
      timeoutMs: API_LONG_TIMEOUT_MS,
    })
  },

  async chunkPreview(
    file: File,
    params: ChunkPreviewRequestParams = {},
    options?: ApiRequestOptions,
  ): Promise<ChunkPreviewResponse> {
    const formData = new FormData()
    formData.append('file', file)
    appendChunkPreviewSettings(formData, file.name, params)

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
    options?: ApiRequestOptions,
  ): Promise<ChunkPreviewResponse> {
    const extension = params.file_type ? params.file_type.replace(/^\.+/, '') : 'txt'
    const filename = params.filename ? params.filename : `doc.${extension}`

    const form = new URLSearchParams({ file_sha256: params.file_sha256 })
    if (params.file_type) form.append('file_type', params.file_type)
    if (params.filename) form.append('filename', params.filename)
    if (typeof params.file_size === 'number') form.append('file_size', String(params.file_size))
    appendChunkPreviewSettings(form, filename, params)

    const { data } = await apiClient.post('/documents/chunk-preview/by-sha', form, {
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
    const { data } = await apiClient.get<Blob>(`/documents/image/${encodeURIComponent(imageId)}`, {
      responseType: 'blob',
    })
    return data
  },

  async fetchImageByImgId(imgId: string): Promise<Blob> {
    const { data } = await apiClient.get<Blob>(`/documents/image-url/${encodeURIComponent(imgId)}`, {
      responseType: 'blob',
    })
    return data
  },
}
