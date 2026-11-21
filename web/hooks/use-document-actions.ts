'use client'

import { useCallback, useRef, useState } from 'react'
import { CancelledError, useMutation } from '@tanstack/react-query'

import { documentApi } from '@/lib/api/documents'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'

import {
  mergePolledDocumentList,
  type CaptureDocumentListOperation,
  type DocumentListOperation,
} from './use-document-shared'

type UseDocumentActionsOptions = {
  cancelDocumentPolling: (documentId: string) => void
  setActionError: (error: string | null) => void
  captureDocumentListOperation: CaptureDocumentListOperation
}

type DocumentAction = { documentId: string; operation: DocumentListOperation }

export function useDocumentActions({
  cancelDocumentPolling,
  setActionError,
  captureDocumentListOperation,
}: UseDocumentActionsOptions) {
  const activeDocumentIdsRef = useRef(new Set<string>())
  const [isActing, setIsActing] = useState(false)

  function clearDocumentActionError({ operation }: DocumentAction) {
    if (operation.isCurrent()) setActionError(null)
  }

  const { mutateAsync: cancelDocumentMutation } = useMutation({
    mutationFn: async ({ documentId, operation }: DocumentAction) => {
      if (!operation.isActive()) throw new CancelledError()
      const status = await documentApi.cancel(documentId)
      if (!operation.isActive()) throw new CancelledError()
      cancelDocumentPolling(documentId)
      return status
    },
    onMutate: clearDocumentActionError,
    onSuccess: (status, { documentId, operation }) => {
      operation.updateCachedDocuments((current) => {
        if (!current?.items.length) return current
        return {
          ...current,
          items: mergePolledDocumentList(current.items, documentId, status),
        }
      })
    },
    onError: (err, { operation }) => {
      if (!operation.isActive()) return
      if (operation.isCurrent()) setActionError(formatApiError(err, 'Failed to cancel document'))
      reportClientError('Cancel document failed', err)
    },
  })

  const { mutateAsync: deleteDocumentMutation } = useMutation({
    mutationFn: async ({ documentId, operation }: DocumentAction) => {
      if (!operation.isActive()) throw new CancelledError()
      await documentApi.delete(documentId)
      if (!operation.isActive()) throw new CancelledError()
      cancelDocumentPolling(documentId)
    },
    onMutate: clearDocumentActionError,
    onSuccess: (_result, { documentId, operation }) => {
      operation.updateCachedDocuments((current) => {
        if (!current) return current
        const items = current.items
        const remaining = items.filter((doc) => doc.id !== documentId)
        if (remaining.length === items.length) return current
        return {
          ...current,
          items: remaining,
          total: Math.max(0, current.total - 1),
        }
      })
    },
    onError: (err, { operation }) => {
      if (!operation.isActive()) return
      if (operation.isCurrent()) setActionError(formatApiError(err, 'Failed to delete document'))
      reportClientError('Delete document failed', err)
    },
  })

  const runDocumentAction = useCallback(
    async <Result>(documentId: string, mutate: (action: DocumentAction) => Promise<Result>): Promise<Result> => {
      const activeDocumentIds = activeDocumentIdsRef.current
      if (activeDocumentIds.has(documentId)) throw new CancelledError()
      activeDocumentIds.add(documentId)
      setIsActing(true)
      try {
        return await mutate({ documentId, operation: captureDocumentListOperation() })
      } finally {
        activeDocumentIds.delete(documentId)
        setIsActing(activeDocumentIds.size > 0)
      }
    },
    [captureDocumentListOperation],
  )

  const cancelDocument = useCallback(
    (documentId: string) => runDocumentAction(documentId, cancelDocumentMutation),
    [cancelDocumentMutation, runDocumentAction],
  )

  const deleteDocument = useCallback(
    (documentId: string) => runDocumentAction(documentId, deleteDocumentMutation),
    [deleteDocumentMutation, runDocumentAction],
  )

  return {
    cancelDocument,
    deleteDocument,
    isActing,
  }
}
