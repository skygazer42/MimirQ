/**
 * 文档管理 Hook
 */
'use client'

import { useState, useEffect, useCallback } from 'react'
import { documentApi } from '@/lib/api-client'
import type { Document } from '@/types'

export function useDocuments() {
  const [documents, setDocuments] = useState<Document[]>([])
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

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
      setError(err.message || 'Failed to load documents')
      console.error('Load documents error:', err)
    } finally {
      setIsLoading(false)
    }
  }, [])

  /**
   * 上传文档
   */
  const uploadDocument = useCallback(
    async (file: File) => {
      setIsLoading(true)
      setError(null)

      try {
        const newDoc = await documentApi.upload(file)
        setDocuments((prev) => [newDoc, ...prev])

        // 轮询检查处理状态
        pollDocumentStatus(newDoc.id)

        return newDoc
      } catch (err: any) {
        setError(err.message || 'Failed to upload document')
        console.error('Upload error:', err)
        throw err
      } finally {
        setIsLoading(false)
      }
    },
    []
  )

  /**
   * 删除文档
   */
  const deleteDocument = useCallback(async (documentId: string) => {
    try {
      await documentApi.delete(documentId)
      setDocuments((prev) => prev.filter((doc) => doc.id !== documentId))
    } catch (err: any) {
      setError(err.message || 'Failed to delete document')
      console.error('Delete error:', err)
      throw err
    }
  }, [])

  /**
   * 轮询文档处理状态
   */
  const pollDocumentStatus = useCallback(
    (documentId: string) => {
      const interval = setInterval(async () => {
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
            clearInterval(interval)

            // 重新加载完整的文档信息
            const fullDoc = await documentApi.get(documentId)
            setDocuments((prev) =>
              prev.map((doc) => (doc.id === documentId ? fullDoc : doc))
            )
          }
        } catch (err) {
          console.error('Poll status error:', err)
          clearInterval(interval)
        }
      }, 2000) // 每 2 秒轮询一次

      // 30 秒后停止轮询
      setTimeout(() => clearInterval(interval), 30000)
    },
    []
  )

  // 初始加载
  useEffect(() => {
    loadDocuments()
  }, [loadDocuments])

  return {
    documents,
    isLoading,
    error,
    loadDocuments,
    uploadDocument,
    deleteDocument,
  }
}
