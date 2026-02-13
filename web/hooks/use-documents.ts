/**
 * 文档管理 Hook
 */
'use client'

import { useState, useEffect, useCallback, useRef } from 'react'
import { documentApi } from '@/lib/api-client'
import type { Document } from '@/types'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { formatApiError } from '@/lib/api-errors'
import type { DocumentBatchUploadFailure, DocumentBatchUploadResponse, DocumentBatchUploadSuccess } from '@/types'

export type DocumentListParams = {
  skip?: number
  limit?: number
  status?: string
  lifecycle?: string
  dataset_id?: string
  source_path_prefix?: string
  q?: string
  order_by?: string
  order_dir?: string
}

function matchesDocumentListParams(doc: Document, params: DocumentListParams): boolean {
  const status = String(params.status || '').trim()
  if (status && status !== 'all') {
    const normalized = status.toLowerCase()
    if (normalized === 'processing') {
      if (!(doc.status === 'pending' || doc.status === 'processing')) return false
    } else if (doc.status !== normalized) {
      return false
    }
  }

  const datasetId = String(params.dataset_id || '').trim()
  if (datasetId && String(doc.dataset_id || '') !== datasetId) return false

  const sourcePathPrefix = String(params.source_path_prefix || '').trim()
  if (sourcePathPrefix) {
    const sourcePath = String((doc.metadata as any)?.source_path || '').trim()
    if (!sourcePath || !sourcePath.startsWith(sourcePathPrefix)) return false
  }

  const lifecycle = String(params.lifecycle || '').trim().toLowerCase()
  if (lifecycle && lifecycle !== 'all') {
    const isArchived = Boolean(doc.archived_at)
    const isDisabled = Boolean(doc.disabled_at)
    if (lifecycle === 'active') {
      if (isArchived || isDisabled) return false
    } else if (lifecycle === 'archived') {
      if (!isArchived) return false
    } else if (lifecycle === 'disabled') {
      if (!isDisabled) return false
    }
  }

  const q = String(params.q || '').trim().toLowerCase()
  if (q && !String(doc.filename || '').toLowerCase().includes(q)) return false

  return true
}

export function useDocuments() {
  const [documents, setDocuments] = useState<Document[]>([])
  const [total, setTotal] = useState(0)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pollTimersRef = useRef<Map<string, number>>(new Map())
  const lastListParamsRef = useRef<DocumentListParams>({ limit: 100, lifecycle: 'active' })
  const { parserBackend } = useParserBackendPreference()
  const { chunkStrategy } = useChunkStrategyPreference()
  const { enabled: pipelineOverridesEnabled, options: pipelineOptions } = usePipelineOptions()

  /**
   * 加载文档列表
   */
  const loadDocuments = useCallback(async (params?: DocumentListParams) => {
    setIsLoading(true)
    setError(null)

    try {
      const effective: DocumentListParams = { ...lastListParamsRef.current, ...(params || {}) }
      lastListParamsRef.current = effective
      const response = await documentApi.list(effective)
      setDocuments(response.items || [])
      setTotal(Number(response.total) || 0)
    } catch (err: any) {
      setError(formatApiError(err, 'Failed to load documents'))
      console.error('Load documents error:', err)
    } finally {
      setIsLoading(false)
    }
  }, [])

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
          setDocuments((prev) =>
            prev.map((doc) =>
              doc.id === documentId
                ? {
                    ...doc,
                    status: status.status,
                    processing_progress: status.processing_progress,
                    current_stage: status.current_stage,
                    error_message: status.error_message,
                  }
                : doc
            )
          )

          // 如果处理完成/失败/隔离，停止轮询
          if (status.status === 'completed' || status.status === 'failed' || status.status === 'cancelled' || status.status === 'quarantined') {
            pollTimersRef.current.delete(documentId)

            // 重新加载完整的文档信息
            const fullDoc = await documentApi.get(documentId)
            setDocuments((prev) =>
              prev.map((doc) => (doc.id === documentId ? fullDoc : doc))
            )
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

        const timeoutId = window.setTimeout(pollOnce, 2000)
        pollTimersRef.current.set(documentId, timeoutId)
      }

      pollOnce()
    },
    []
  )

  /**
   * 上传文档
   */
  const uploadDocument = useCallback(
    async (file: File) => {
      setIsLoading(true)
      setError(null)

      try {
        const datasetId = String(lastListParamsRef.current.dataset_id || '').trim()
        const newDoc = await documentApi.upload(file, {
          parser_backend: parserBackend,
          chunk_strategy: chunkStrategy,
          dataset_id: datasetId || undefined,
          pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
        })
        const params = lastListParamsRef.current
        if (matchesDocumentListParams(newDoc, params)) {
          setDocuments((prev) => [newDoc, ...prev])
          setTotal((prev) => prev + 1)
        }

        // 轮询检查处理状态
        pollDocumentStatus(newDoc.id)

        return newDoc
      } catch (err: any) {
        setError(formatApiError(err, 'Failed to upload document'))
        console.error('Upload error:', err)
        throw err
      } finally {
        setIsLoading(false)
      }
    },
    [parserBackend, chunkStrategy, pipelineOverridesEnabled, pipelineOptions, pollDocumentStatus]
  )

  /**
   * 批量上传（支持 folder upload 的相对路径保留 + 自动重试失败项）
   */
  const uploadDocuments = useCallback(
    async (
      files: File[],
      options: { maxRetries?: number; maxConcurrent?: number } = {}
    ): Promise<DocumentBatchUploadResponse> => {
      setIsLoading(true)
      setError(null)

      const maxRetries = Math.max(0, Math.min(3, Number(options.maxRetries ?? 1)))
      const maxConcurrent = Math.max(1, Math.min(10, Number(options.maxConcurrent ?? 5)))
      const datasetId = String(lastListParamsRef.current.dataset_id || '').trim()

      const originalFiles = Array.from(files || []).filter(Boolean)
      const total = originalFiles.length
      if (total === 0) {
        return { total: 0, successful_count: 0, failed_count: 0, successful: [], failed: [] }
      }

      const keyOf = (f: File) => String((f as any).webkitRelativePath || f.name || '').trim()
      const fileByKey = new Map<string, File>()
      for (const f of originalFiles) {
        const k = keyOf(f)
        if (k) fileByKey.set(k, f)
      }

      const successes: DocumentBatchUploadSuccess[] = []
      let failures: DocumentBatchUploadFailure[] = []

      let remaining = originalFiles
      let attempt = 0

      try {
        while (remaining.length > 0 && attempt <= maxRetries) {
          const nextRemaining: File[] = []
          const roundFailures: DocumentBatchUploadFailure[] = []

          // Server caps at 50 files per request.
          for (let i = 0; i < remaining.length; i += 50) {
            const batch = remaining.slice(i, i + 50)
            const res = await documentApi.uploadBatch(batch, {
              parser_backend: parserBackend,
              chunk_strategy: chunkStrategy,
              dataset_id: datasetId || undefined,
              pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
              max_concurrent: maxConcurrent,
            })

            successes.push(...(res.successful || []))
            const failed = res.failed || []
            roundFailures.push(...failed)

            // Prepare retry list (best-effort mapping by source_path or filename).
            for (const item of failed) {
              const key = String(item.source_path || item.filename || '').trim()
              const f = key ? fileByKey.get(key) : undefined
              if (f) nextRemaining.push(f)
            }
          }

          failures = roundFailures
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
      } catch (err: any) {
        setError(formatApiError(err, 'Failed to upload documents'))
        console.error('Batch upload error:', err)
        throw err
      } finally {
        setIsLoading(false)
      }
    },
    [chunkStrategy, loadDocuments, parserBackend, pipelineOptions, pipelineOverridesEnabled, pollDocumentStatus]
  )

  /**
   * 通过 URL 导入文档（后端拉取并入库）
   */
  const uploadDocumentFromUrl = useCallback(
    async (params: { url: string; filename?: string; dataset_id?: string }) => {
      setIsLoading(true)
      setError(null)

      try {
        const newDoc = await documentApi.uploadFromUrl({
          url: params.url,
          filename: params.filename,
          dataset_id: params.dataset_id,
          parser_backend: parserBackend,
          chunk_strategy: chunkStrategy,
          pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
        })

        const listParams = lastListParamsRef.current
        if (matchesDocumentListParams(newDoc, listParams)) {
          setDocuments((prev) => [newDoc, ...prev])
          setTotal((prev) => prev + 1)
        }

        pollDocumentStatus(newDoc.id)
        return newDoc
      } catch (err: any) {
        setError(formatApiError(err, 'Failed to upload document from URL'))
        console.error('Upload from URL error:', err)
        throw err
      } finally {
        setIsLoading(false)
      }
    },
    [parserBackend, chunkStrategy, pipelineOverridesEnabled, pipelineOptions, pollDocumentStatus]
  )

  /**
   * 取消文档处理
   */
  const cancelDocument = useCallback(async (documentId: string) => {
    const existing = pollTimersRef.current.get(documentId)
    if (existing) {
      clearTimeout(existing)
      pollTimersRef.current.delete(documentId)
    }

    try {
      const status = await documentApi.cancel(documentId)
      setDocuments((prev) =>
        prev.map((doc) =>
          doc.id === documentId
            ? {
                ...doc,
                status: status.status,
                processing_progress: status.processing_progress,
                current_stage: status.current_stage,
                error_message: status.error_message,
              }
            : doc
        )
      )
      return status
    } catch (err: any) {
      setError(formatApiError(err, 'Failed to cancel document'))
      console.error('Cancel error:', err)
      throw err
    }
  }, [])

  /**
   * 删除文档
   */
  const deleteDocument = useCallback(async (documentId: string) => {
    try {
      await documentApi.delete(documentId)
      setDocuments((prev) => prev.filter((doc) => doc.id !== documentId))
      setTotal((prev) => Math.max(0, prev - 1))
    } catch (err: any) {
      setError(formatApiError(err, 'Failed to delete document'))
      console.error('Delete error:', err)
      throw err
    }
  }, [])

  // 初始加载
  useEffect(() => {
    loadDocuments()
  }, [loadDocuments])

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
