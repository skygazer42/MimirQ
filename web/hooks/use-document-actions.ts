'use client'

import { useCallback } from 'react'
import { CancelledError, useMutation } from '@tanstack/react-query'

import { documentApi } from '@/lib/api/documents'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'

import {
  mergePolledDocument,
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
  const { mutateAsync: cancelDocumentMutation, isPending: cancelDocumentPending } = useMutation({
    mutationFn: async ({ documentId, operation }: DocumentAction) => {
      if (!operation.isActive()) throw new CancelledError()
      cancelDocumentPolling(documentId)
      const status = await documentApi.cancel(documentId)
      if (!operation.isActive()) throw new CancelledError()
      return status
    },
    onMutate: ({ operation }) => {
      if (operation.isCurrent()) setActionError(null)
    },
    onSuccess: (status, { documentId, operation }) => {
      operation.updateCachedDocuments((current) => {
        if (!current?.items?.length) return current
        return {
          ...current,
          items: current.items.map((doc) => mergePolledDocument(doc, documentId, status)),
        }
      })
    },
    onError: (err, { operation }) => {
      if (!operation.isActive()) return
      if (operation.isCurrent()) setActionError(formatApiError(err, 'Failed to cancel document'))
      reportClientError('Cancel document failed', err)
    },
  })

  const { mutateAsync: deleteDocumentMutation, isPending: deleteDocumentPending } = useMutation({
    mutationFn: async ({ documentId, operation }: DocumentAction) => {
      if (!operation.isActive()) throw new CancelledError()
      await documentApi.delete(documentId)
      if (!operation.isActive()) throw new CancelledError()
    },
    onMutate: ({ operation }) => {
      if (operation.isCurrent()) setActionError(null)
    },
    onSuccess: (_result, { documentId, operation }) => {
      operation.updateCachedDocuments((current) => {
        if (!current) return current
        const items = current.items || []
        const remaining = items.filter((doc) => doc.id !== documentId)
        if (remaining.length === items.length) return current
        return {
          ...current,
          items: remaining,
          total: Math.max(0, Number(current.total || 0) - 1),
        }
      })
    },
    onError: (err, { operation }) => {
      if (!operation.isActive()) return
      if (operation.isCurrent()) setActionError(formatApiError(err, 'Failed to delete document'))
      reportClientError('Delete document failed', err)
    },
  })

  const cancelDocument = useCallback(
    async (documentId: string) => cancelDocumentMutation({ documentId, operation: captureDocumentListOperation() }),
    [cancelDocumentMutation, captureDocumentListOperation],
  )

  const deleteDocument = useCallback(
    async (documentId: string) => deleteDocumentMutation({ documentId, operation: captureDocumentListOperation() }),
    [captureDocumentListOperation, deleteDocumentMutation],
  )

  return {
    cancelDocument,
    deleteDocument,
    isActing: cancelDocumentPending || deleteDocumentPending,
  }
}
