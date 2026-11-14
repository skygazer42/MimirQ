'use client'

import { useCallback, useEffect, useRef } from 'react'

import { documentApi } from '@/lib/api/documents'
import { reportClientError } from '@/lib/client-logging'

import {
  isTerminalDocumentStatus,
  mergePolledDocumentList,
  replacePolledDocumentList,
  type CaptureDocumentListOperation,
} from './use-document-shared'

type UseDocumentPollingOptions = {
  captureDocumentListOperation: CaptureDocumentListOperation
}

type DocumentPoll = { timerId?: number }

export function useDocumentPolling({ captureDocumentListOperation }: UseDocumentPollingOptions) {
  const pollsRef = useRef<Map<string, DocumentPoll>>(new Map())
  const cancelledRef = useRef(false)

  const cancelDocumentPolling = useCallback((documentId: string) => {
    const existing = pollsRef.current.get(documentId)
    if (existing?.timerId !== undefined) clearTimeout(existing.timerId)
    pollsRef.current.delete(documentId)
  }, [])

  const cancelAllDocumentPolling = useCallback(() => {
    for (const poll of pollsRef.current.values()) {
      if (poll.timerId !== undefined) clearTimeout(poll.timerId)
    }
    pollsRef.current.clear()
  }, [])

  const pollDocumentStatus = useCallback(
    (documentId: string, operation = captureDocumentListOperation()) => {
      cancelDocumentPolling(documentId)

      const poll: DocumentPoll = {}
      pollsRef.current.set(documentId, poll)
      const isCurrent = () => !cancelledRef.current && operation.isActive() && pollsRef.current.get(documentId) === poll
      const finish = () => {
        if (pollsRef.current.get(documentId) === poll) pollsRef.current.delete(documentId)
      }
      const startedAt = Date.now()
      const pollOnce = async () => {
        if (!isCurrent()) {
          finish()
          return
        }
        try {
          const status = await documentApi.getStatus(documentId)
          if (!isCurrent()) {
            finish()
            return
          }

          operation.updateCachedDocuments((current) => {
            if (!current?.items?.length) return current
            return {
              ...current,
              items: mergePolledDocumentList(current.items || [], documentId, status),
            }
          })

          if (isTerminalDocumentStatus(status.status)) {
            const fullDoc = await documentApi.get(documentId)
            if (!isCurrent()) {
              finish()
              return
            }
            operation.updateCachedDocuments((current) => {
              if (!current?.items?.length) return current
              return {
                ...current,
                items: replacePolledDocumentList(current.items || [], documentId, fullDoc),
              }
            })
            finish()
            return
          }
        } catch (err) {
          if (!isCurrent()) {
            finish()
            return
          }
          reportClientError('Poll document status failed', err)
          finish()
          return
        }

        if (Date.now() - startedAt > 30000) {
          finish()
          return
        }

        if (!isCurrent()) {
          finish()
          return
        }
        poll.timerId = globalThis.window.setTimeout(pollOnce, 2000)
      }

      void pollOnce()
    },
    [cancelDocumentPolling, captureDocumentListOperation],
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
