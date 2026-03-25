/**
 * 文档管理 Hook
 */
'use client'

import { keepPreviousData, useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { useCallback, useEffect, useRef, useState } from 'react'
import { documentApi } from '@/lib/api/documents'
import type {
  Document,
  DocumentBatchUploadFailure,
  DocumentBatchUploadResponse,
  DocumentBatchUploadSuccess,
  DocumentPipelineOptions,
} from '@/types'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'

export type DocumentListParams = {
  skip?: number
  limit?: number
  status?: string
  lifecycle?: 'active' | 'archived' | 'disabled' | 'all'
  dataset_id?: string
  source_path_prefix?: string
  q?: string
  order_by?: 'created_at' | 'filename' | 'file_size'
  order_dir?: 'asc' | 'desc'
}

type UploadBatchRequestOptions = {
  parser_backend: string
  chunk_strategy: string
  dataset_id?: string
  pipeline?: DocumentPipelineOptions
  max_concurrent: number
}

type DocumentStatusSnapshot = Pick<
  Document,
  'status' | 'processing_progress' | 'current_stage' | 'error_message'
>

const TERMINAL_DOCUMENT_STATUSES = new Set(['completed', 'failed', 'cancelled', 'quarantined'])

export function matchesStatusFilter(doc: Document, statusFilter: string | undefined): boolean {
  const status = String(statusFilter || '').trim().toLowerCase()
  if (!status || status === 'all') return true
  if (status === 'processing') {
    return doc.status === 'pending' || doc.status === 'processing'
  }
  return doc.status === status
}

export function matchesLifecycleFilter(doc: Document, lifecycleFilter: string | undefined): boolean {
  const lifecycle = String(lifecycleFilter || '').trim().toLowerCase()
  if (!lifecycle || lifecycle === 'all') return true

  const isArchived = Boolean(doc.archived_at)
  const isDisabled = Boolean(doc.disabled_at)
  if (lifecycle === 'active') return !isArchived && !isDisabled
  if (lifecycle === 'archived') return isArchived
  if (lifecycle === 'disabled') return isDisabled
  return true
}

export function matchesDocumentListParams(doc: Document, params: DocumentListParams): boolean {
  if (!matchesStatusFilter(doc, params.status)) return false
  const datasetId = String(params.dataset_id || '').trim()
  if (datasetId && String(doc.dataset_id || '') !== datasetId) return false

  const sourcePathPrefix = String(params.source_path_prefix || '').trim()
  if (sourcePathPrefix) {
    const sourcePath = String((doc.metadata as any)?.source_path || '').trim()
    if (!sourcePath?.startsWith(sourcePathPrefix)) return false
  }

  if (!matchesLifecycleFilter(doc, params.lifecycle)) return false
  const q = String(params.q || '').trim().toLowerCase()
  if (q && !String(doc.filename || '').toLowerCase().includes(q)) return false

  return true
}

export function isTerminalDocumentStatus(status: string | undefined): boolean {
  return TERMINAL_DOCUMENT_STATUSES.has(String(status || '').toLowerCase())
}

export function mergePolledDocument(
  doc: Document,
  documentId: string,
  status: DocumentStatusSnapshot
): Document {
  if (doc.id !== documentId) return doc
  return {
    ...doc,
    status: status.status,
    processing_progress: status.processing_progress,
    current_stage: status.current_stage,
    error_message: status.error_message,
  }
}

export function replacePolledDocument(doc: Document, documentId: string, nextDocument: Document): Document {
  return doc.id === documentId ? nextDocument : doc
}

export function mergePolledDocumentList(
  documents: Document[],
  documentId: string,
  status: DocumentStatusSnapshot
): Document[] {
  return documents.map((doc) => mergePolledDocument(doc, documentId, status))
}

export function replacePolledDocumentList(
  documents: Document[],
  documentId: string,
  nextDocument: Document
): Document[] {
  return documents.map((doc) => replacePolledDocument(doc, documentId, nextDocument))
}

export function clampUploadOption(
  value: number | undefined,
  fallback: number,
  min: number,
  max: number
): number {
  return Math.max(min, Math.min(max, Number(value ?? fallback)))
}

export function getUploadFileKey(
  file: Pick<File, 'name'> & { webkitRelativePath?: string } | DocumentBatchUploadFailure
): string {
  if ('source_path' in file || 'filename' in file) {
    return String(file.source_path || file.filename || '').trim()
  }
  return String(file.webkitRelativePath || file.name || '').trim()
}

export function collectRetryFiles(
  failed: DocumentBatchUploadFailure[],
  fileByKey: Map<string, File>
): File[] {
  const nextRemaining: File[] = []
  for (const item of failed) {
    const retryFile = fileByKey.get(getUploadFileKey(item))
    if (retryFile) nextRemaining.push(retryFile)
  }
  return nextRemaining
}

async function uploadBatchRound(
  files: File[],
  options: UploadBatchRequestOptions,
  fileByKey: Map<string, File>
): Promise<{
  successful: DocumentBatchUploadSuccess[]
  failed: DocumentBatchUploadFailure[]
  nextRemaining: File[]
}> {
  const successful: DocumentBatchUploadSuccess[] = []
  const failed: DocumentBatchUploadFailure[] = []

  for (let i = 0; i < files.length; i += 50) {
    const batch = files.slice(i, i + 50)
    const response = await documentApi.uploadBatch(batch, options)
    successful.push(...(response.successful || []))
    failed.push(...(response.failed || []))
  }

  return {
    successful,
    failed,
    nextRemaining: collectRetryFiles(failed, fileByKey),
  }
}

type DocumentListResponse = Awaited<ReturnType<typeof documentApi.list>>

export function useDocuments() {
  const queryClient = useQueryClient()
  const pollTimersRef = useRef<Map<string, number>>(new Map())
  const [listParams, setListParams] = useState<DocumentListParams>({ limit: 100, lifecycle: 'active' })
  const lastListParamsRef = useRef<DocumentListParams>(listParams)
  const [actionError, setActionError] = useState<string | null>(null)
  const { parserBackend } = useParserBackendPreference()
  const { chunkStrategy } = useChunkStrategyPreference()
  const { enabled: pipelineOverridesEnabled, options: pipelineOptions } = usePipelineOptions()

  const {
    data: listData,
    error: listError,
    isFetching,
    isLoading: isListLoading,
  } = useQuery<DocumentListResponse>({
    queryKey: queryKeys.documents.list(listParams),
    queryFn: () => documentApi.list(listParams),
    placeholderData: keepPreviousData,
  })

  const updateCachedDocuments = useCallback(
    (updater: (current: DocumentListResponse | undefined) => DocumentListResponse | undefined) => {
      queryClient.setQueryData<DocumentListResponse>(
        queryKeys.documents.list(lastListParamsRef.current),
        updater
      )
    },
    [queryClient]
  )

  const loadDocuments = useCallback(
    async (params?: DocumentListParams) => {
      setActionError(null)

      const effective: DocumentListParams = params
        ? { ...lastListParamsRef.current, ...params }
        : { ...lastListParamsRef.current }

      lastListParamsRef.current = effective
      setListParams(effective)

      try {
        await queryClient.fetchQuery({
          queryKey: queryKeys.documents.list(effective),
          queryFn: () => documentApi.list(effective),
        })
      } catch (err: any) {
        setActionError(formatApiError(err, 'Failed to load documents'))
        console.error('Load documents error:', err)
      }
    },
    [queryClient]
  )

  /**
   * 轮询文档处理状态
   */
  const pollDocumentStatus = useCallback(
    (documentId: string) => {
      const existing = pollTimersRef.current.get(documentId)
      if (existing) {
        clearTimeout(existing)
        pollTimersRef.current.delete(documentId)
      }

      const startedAt = Date.now()
      const pollOnce = async () => {
        try {
          const status = await documentApi.getStatus(documentId)

          // 更新文档状态
          updateCachedDocuments((current) => {
            if (!current?.items?.length) return current
            return {
              ...current,
              items: mergePolledDocumentList(current.items || [], documentId, status),
            }
          })

          // 如果处理完成/失败/隔离，停止轮询
          if (isTerminalDocumentStatus(status.status)) {
            pollTimersRef.current.delete(documentId)

            // 重新加载完整的文档信息
            const fullDoc = await documentApi.get(documentId)
            updateCachedDocuments((current) => {
              if (!current?.items?.length) return current
              return {
                ...current,
                items: replacePolledDocumentList(current.items || [], documentId, fullDoc),
              }
            })
            return
          }
        } catch (err) {
          console.error('Poll status error:', err)
          pollTimersRef.current.delete(documentId)
          return
        }

        if (Date.now() - startedAt > 30000) {
          pollTimersRef.current.delete(documentId)
          return
        }

        const timeoutId = globalThis.window.setTimeout(pollOnce, 2000)
        pollTimersRef.current.set(documentId, timeoutId)
      }

      void pollOnce()
    },
    [updateCachedDocuments]
  )

  const {
    mutateAsync: uploadDocumentMutation,
    isPending: uploadDocumentPending,
  } = useMutation({
    mutationFn: async (file: File) => {
      const datasetId = String(lastListParamsRef.current.dataset_id || '').trim()
      return documentApi.upload(file, {
        parser_backend: parserBackend,
        chunk_strategy: chunkStrategy,
        dataset_id: datasetId || undefined,
        pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
      })
    },
    onMutate: async () => {
      setActionError(null)
    },
    onSuccess: (newDoc) => {
      const params = lastListParamsRef.current
      if (matchesDocumentListParams(newDoc, params)) {
        updateCachedDocuments((current) => ({
          ...(current || { items: [], total: 0 }),
          items: [newDoc, ...(current?.items || [])],
          total: Number(current?.total || 0) + 1,
        }))
      }
      pollDocumentStatus(newDoc.id)
    },
    onError: (err) => {
      setActionError(formatApiError(err, 'Failed to upload document'))
      console.error('Upload error:', err)
    },
  })

  const uploadDocument = useCallback(
    async (file: File) => uploadDocumentMutation(file),
    [uploadDocumentMutation]
  )

  /**
   * 批量上传（支持 folder upload 的相对路径保留 + 自动重试失败项）
   */
  const {
    mutateAsync: uploadDocumentsMutation,
    isPending: uploadDocumentsPending,
  } = useMutation({
    mutationFn: async ({
      files,
      options,
    }: {
      files: File[]
      options?: { maxRetries?: number; maxConcurrent?: number }
    }): Promise<DocumentBatchUploadResponse> => {
      const maxRetries = clampUploadOption(options?.maxRetries, 1, 0, 3)
      const maxConcurrent = clampUploadOption(options?.maxConcurrent, 5, 1, 10)
      const datasetId = String(lastListParamsRef.current.dataset_id || '').trim()

      const originalFiles = files.filter(Boolean)
      const total = originalFiles.length
      if (total === 0) {
        return { total: 0, successful_count: 0, failed_count: 0, successful: [], failed: [] }
      }

      const fileByKey = new Map<string, File>()
      for (const f of originalFiles) {
        const k = getUploadFileKey(f)
        if (k) fileByKey.set(k, f)
      }

      const successes: DocumentBatchUploadSuccess[] = []
      let failures: DocumentBatchUploadFailure[] = []

      let remaining = originalFiles
      let attempt = 0

      while (remaining.length > 0 && attempt <= maxRetries) {
        const round = await uploadBatchRound(
          remaining,
          {
            parser_backend: parserBackend,
            chunk_strategy: chunkStrategy,
            dataset_id: datasetId || undefined,
            pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
            max_concurrent: maxConcurrent,
          },
          fileByKey
        )

        successes.push(...round.successful)
        failures = round.failed
        const nextRemaining = round.nextRemaining
        if (nextRemaining.length === 0) break
        attempt += 1
        remaining = nextRemaining
      }

      // Refresh list once and then start polling new docs (ensures doc ids are present in state).
      await loadDocuments()
      for (const s of successes) {
        if (s?.document_id) pollDocumentStatus(String(s.document_id))
      }

      return {
        total,
        successful_count: successes.length,
        failed_count: failures.length,
        successful: successes,
        failed: failures,
      }
    },
    onMutate: async () => {
      setActionError(null)
    },
    onError: (err) => {
      setActionError(formatApiError(err, 'Failed to upload documents'))
      console.error('Batch upload error:', err)
    },
  })

  const uploadDocuments = useCallback(
    async (
      files: File[],
      options: { maxRetries?: number; maxConcurrent?: number } = {}
    ) => uploadDocumentsMutation({ files, options }),
    [uploadDocumentsMutation]
  )

  /**
   * 通过 URL 导入文档（后端拉取并入库）
   */
  const {
    mutateAsync: uploadDocumentFromUrlMutation,
    isPending: uploadDocumentFromUrlPending,
  } = useMutation({
    mutationFn: async (params: { url: string; filename?: string; dataset_id?: string }) => {
      return documentApi.uploadFromUrl({
        url: params.url,
        filename: params.filename,
        dataset_id: params.dataset_id,
        parser_backend: parserBackend,
        chunk_strategy: chunkStrategy,
        pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
      })
    },
    onMutate: async () => {
      setActionError(null)
    },
    onSuccess: (newDoc) => {
      const params = lastListParamsRef.current
      if (matchesDocumentListParams(newDoc, params)) {
        updateCachedDocuments((current) => ({
          ...(current || { items: [], total: 0 }),
          items: [newDoc, ...(current?.items || [])],
          total: Number(current?.total || 0) + 1,
        }))
      }
      pollDocumentStatus(newDoc.id)
    },
    onError: (err) => {
      setActionError(formatApiError(err, 'Failed to upload document from URL'))
      console.error('Upload from URL error:', err)
    },
  })

  const uploadDocumentFromUrl = useCallback(
    async (params: { url: string; filename?: string; dataset_id?: string }) => {
      return uploadDocumentFromUrlMutation(params)
    },
    [uploadDocumentFromUrlMutation]
  )

  /**
   * 取消文档处理
   */
  const {
    mutateAsync: cancelDocumentMutation,
    isPending: cancelDocumentPending,
  } = useMutation({
    mutationFn: async (documentId: string) => {
      const existing = pollTimersRef.current.get(documentId)
      if (existing) {
        clearTimeout(existing)
        pollTimersRef.current.delete(documentId)
      }

      return documentApi.cancel(documentId)
    },
    onMutate: async () => {
      setActionError(null)
    },
    onSuccess: (status, documentId) => {
      updateCachedDocuments((current) => {
        if (!current?.items?.length) return current
        return {
          ...current,
          items: current.items.map((doc) =>
            doc.id === documentId
              ? {
                  ...doc,
                  status: status.status,
                  processing_progress: status.processing_progress,
                  current_stage: status.current_stage,
                  error_message: status.error_message,
                }
              : doc
          ),
        }
      })
    },
    onError: (err) => {
      setActionError(formatApiError(err, 'Failed to cancel document'))
      console.error('Cancel error:', err)
    },
  })

  const cancelDocument = useCallback(
    async (documentId: string) => cancelDocumentMutation(documentId),
    [cancelDocumentMutation]
  )

  /**
   * 删除文档
   */
  const {
    mutateAsync: deleteDocumentMutation,
    isPending: deleteDocumentPending,
  } = useMutation({
    mutationFn: (documentId: string) => documentApi.delete(documentId),
    onMutate: async () => {
      setActionError(null)
    },
    onSuccess: (_result, documentId) => {
      updateCachedDocuments((current) => {
        if (!current) return current
        return {
          ...current,
          items: (current.items || []).filter((doc) => doc.id !== documentId),
          total: Math.max(0, Number(current.total || 0) - 1),
        }
      })
    },
    onError: (err) => {
      setActionError(formatApiError(err, 'Failed to delete document'))
      console.error('Delete error:', err)
    },
  })

  const deleteDocument = useCallback(
    async (documentId: string) => {
      return deleteDocumentMutation(documentId)
    },
    [deleteDocumentMutation]
  )

  const documents = listData?.items || []
  const total = Number(listData?.total) || 0
  const isLoading =
    isListLoading ||
    isFetching ||
    uploadDocumentPending ||
    uploadDocumentsPending ||
    uploadDocumentFromUrlPending ||
    cancelDocumentPending ||
    deleteDocumentPending
  const error = actionError || (listError ? formatApiError(listError, 'Failed to load documents') : null)

  useEffect(() => {
    const timers = pollTimersRef.current
    return () => {
      for (const timerId of timers.values()) {
        clearTimeout(timerId)
      }
      timers.clear()
    }
  }, [])

  return {
    documents,
    total,
    isLoading,
    error,
    loadDocuments,
    refreshDocuments: loadDocuments,
    uploadDocument,
    uploadDocuments,
    uploadDocumentFromUrl,
    cancelDocument,
    deleteDocument,
  }
}
