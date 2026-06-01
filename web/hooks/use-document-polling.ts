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
        try {
          const status = await documentApi.getStatus(documentId)

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
          reportClientError('Poll document status failed', err)
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
    [cancelDocumentPolling, updateCachedDocuments]
  )

  useEffect(() => () => {
    cancelAllDocumentPolling()
  }, [cancelAllDocumentPolling])

  return {
    pollDocumentStatus,
    cancelDocumentPolling,
  }
}
