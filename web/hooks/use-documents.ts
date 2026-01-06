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

export function useDocuments() {
  const [documents, setDocuments] = useState<Document[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const pollTimersRef = useRef<Map<string, number>>(new Map())
  const { parserBackend } = useParserBackendPreference()
  const { chunkStrategy } = useChunkStrategyPreference()
  const { enabled: pipelineOverridesEnabled, options: pipelineOptions } = usePipelineOptions()

  /**
   * 加载文档列表
   */
  const loadDocuments = useCallback(async () => {
    setIsLoading(true)
    setError(null)

    try {
      const response = await documentApi.list({ limit: 100 })
      setDocuments(response.items)
    } catch (err: any) {
      setError(
        err.response?.data?.detail ||
          err.response?.data?.message ||
          (typeof err.response?.data === 'string' ? err.response.data : undefined) ||
          err.message ||
          'Failed to load documents'
      )
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

          // 如果处理完成或失败，停止轮询
          if (status.status === 'completed' || status.status === 'failed') {
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
        const newDoc = await documentApi.upload(file, {
          parser_backend: parserBackend,
          chunk_strategy: chunkStrategy,
          pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
        })
        setDocuments((prev) => [newDoc, ...prev])

        // 轮询检查处理状态
        pollDocumentStatus(newDoc.id)

        return newDoc
      } catch (err: any) {
        setError(
          err.response?.data?.detail ||
            err.response?.data?.message ||
            (typeof err.response?.data === 'string' ? err.response.data : undefined) ||
            err.message ||
            'Failed to upload document'
        )
        console.error('Upload error:', err)
        throw err
      } finally {
        setIsLoading(false)
      }
    },
    [parserBackend, chunkStrategy, pipelineOverridesEnabled, pipelineOptions, pollDocumentStatus]
  )

  /**
   * 删除文档
   */
  const deleteDocument = useCallback(async (documentId: string) => {
    try {
      await documentApi.delete(documentId)
      setDocuments((prev) => prev.filter((doc) => doc.id !== documentId))
    } catch (err: any) {
      setError(
        err.response?.data?.detail ||
          err.response?.data?.message ||
          (typeof err.response?.data === 'string' ? err.response.data : undefined) ||
          err.message ||
          'Failed to delete document'
      )
      console.error('Delete error:', err)
      throw err
    }
  }, [])

  // 初始加载
  useEffect(() => {
    loadDocuments()
  }, [loadDocuments])

  useEffect(() => {
    return () => {
      for (const timerId of pollTimersRef.current.values()) {
        clearTimeout(timerId)
      }
      pollTimersRef.current.clear()
    }
  }, [])

  return {
    documents,
    isLoading,
    error,
    loadDocuments,
    refreshDocuments: loadDocuments,
    uploadDocument,
    deleteDocument,
  }
}
