'use client'

import { useCallback, useLayoutEffect, useRef } from 'react'

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

type DocumentPoll = { controller: AbortController; timerId?: number }

const POLL_INTERVAL_MS = 2_000
const POLL_WINDOW_MS = 30_000

export function useDocumentPolling({ captureDocumentListOperation }: UseDocumentPollingOptions) {
  const pollsRef = useRef<Map<string, DocumentPoll>>(new Map())
  const cancelledRef = useRef(false)

  const cancelDocumentPolling = useCallback((documentId: string) => {
    const poll = pollsRef.current.get(documentId)
    if (poll === undefined) return
    pollsRef.current.delete(documentId)
    if (poll.timerId !== undefined) globalThis.window.clearTimeout(poll.timerId)
    poll.controller.abort()
  }, [])

  const pollDocumentStatus = useCallback(
    (documentId: string, operation = captureDocumentListOperation()) => {
      if (cancelledRef.current || !operation.isActive()) return
      cancelDocumentPolling(documentId)

      const poll: DocumentPoll = { controller: new AbortController() }
      pollsRef.current.set(documentId, poll)
      const request = { signal: poll.controller.signal }
      const isCurrent = () => pollsRef.current.get(documentId) === poll && operation.isActive()
      const finish = () => {
        if (pollsRef.current.get(documentId) === poll) pollsRef.current.delete(documentId)
      }
      const startedAt = Date.now()
      const pollOnce = async () => {
        poll.timerId = undefined
        if (!isCurrent()) {
          finish()
          return
        }
        try {
          const status = await documentApi.getStatus(documentId, request)
          if (!isCurrent()) {
            finish()
            return
          }

          operation.updateCachedDocuments((current) => {
            if (!current?.items.length) return current
            return {
              ...current,
              items: mergePolledDocumentList(current.items, documentId, status),
            }
          })

          if (isTerminalDocumentStatus(status.status)) {
            const fullDoc = await documentApi.get(documentId, undefined, request)
            if (!isCurrent()) {
              finish()
              return
            }
            operation.updateCachedDocuments((current) => {
              if (!current?.items.length) return current
              return {
                ...current,
                items: replacePolledDocumentList(current.items, documentId, fullDoc),
              }
            })
            finish()
            return
          }
        } catch (error) {
          if (isCurrent()) reportClientError('Poll document status failed', error)
          finish()
          return
        }

        if (Date.now() - startedAt > POLL_WINDOW_MS || !isCurrent()) {
          finish()
          return
        }
        poll.timerId = globalThis.window.setTimeout(pollOnce, POLL_INTERVAL_MS)
      }

      void pollOnce()
    },
    [cancelDocumentPolling, captureDocumentListOperation],
  )

  useLayoutEffect(() => {
    const polls = pollsRef.current
    cancelledRef.current = false
    return () => {
      cancelledRef.current = true
      for (const documentId of polls.keys()) cancelDocumentPolling(documentId)
    }
  }, [cancelDocumentPolling])

  return {
    pollDocumentStatus,
    cancelDocumentPolling,
  }
}
