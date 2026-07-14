'use client'

import { useCallback, useEffect, useRef } from 'react'

import { documentApi } from '@/lib/api/documents'
import { reportClientError } from '@/lib/client-logging'

import {
  isTerminalDocumentStatus,
  mergePolledDocumentList,
  replacePolledDocumentList,
  type UpdateCachedDocuments,
} from './use-document-shared'

type UseDocumentPollingOptions = {
  updateCachedDocuments: UpdateCachedDocuments
}

export function useDocumentPolling({ updateCachedDocuments }: UseDocumentPollingOptions) {
  const pollTimersRef = useRef<Map<string, number>>(new Map())
  const cancelledRef = useRef(false)

  const cancelDocumentPolling = useCallback((documentId: string) => {
    const existing = pollTimersRef.current.get(documentId)
    if (existing) {
      clearTimeout(existing)
      pollTimersRef.current.delete(documentId)
    }
  }, [])

  const cancelAllDocumentPolling = useCallback(() => {
    for (const timerId of pollTimersRef.current.values()) {
      clearTimeout(timerId)
    }
    pollTimersRef.current.clear()
  }, [])

  const pollDocumentStatus = useCallback(
    (documentId: string) => {
      cancelDocumentPolling(documentId)

      const startedAt = Date.now()
      const pollOnce = async () => {
        if (cancelledRef.current) return
        try {
          const status = await documentApi.getStatus(documentId)
          if (cancelledRef.current) return

          updateCachedDocuments((current) => {
            if (!current?.items?.length) return current
            return {
              ...current,
              items: mergePolledDocumentList(current.items || [], documentId, status),
            }
          })

          if (isTerminalDocumentStatus(status.status)) {
            pollTimersRef.current.delete(documentId)

            const fullDoc = await documentApi.get(documentId)
            if (cancelledRef.current) return
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
          if (cancelledRef.current) return
          reportClientError('Poll document status failed', err)
          pollTimersRef.current.delete(documentId)
          return
        }

        if (Date.now() - startedAt > 30000) {
          pollTimersRef.current.delete(documentId)
          return
        }

        if (cancelledRef.current) return
        const timeoutId = globalThis.window.setTimeout(pollOnce, 2000)
        pollTimersRef.current.set(documentId, timeoutId)
      }

      void pollOnce()
    },
    [cancelDocumentPolling, updateCachedDocuments]
  )

  useEffect(() => {
    cancelledRef.current = false
    return () => {
      cancelledRef.current = true
      cancelAllDocumentPolling()
    }
  }, [cancelAllDocumentPolling])

  return {
    pollDocumentStatus,
    cancelDocumentPolling,
  }
}
