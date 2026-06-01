'use client'

import { useCallback } from 'react'
import { useMutation } from '@tanstack/react-query'

import { documentApi } from '@/lib/api/documents'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'

import { mergePolledDocument, type UpdateCachedDocuments } from './use-document-shared'

type UseDocumentActionsOptions = {
  cancelDocumentPolling: (documentId: string) => void
  setActionError: (error: string | null) => void
  updateCachedDocuments: UpdateCachedDocuments
}

export function useDocumentActions({
  cancelDocumentPolling,
  setActionError,
  updateCachedDocuments,
}: UseDocumentActionsOptions) {
  const {
    mutateAsync: cancelDocumentMutation,
    isPending: cancelDocumentPending,
  } = useMutation({
    mutationFn: async (documentId: string) => {
      cancelDocumentPolling(documentId)
      return documentApi.cancel(documentId)
    },
    onMutate: () => {
      setActionError(null)
    },
    onSuccess: (status, documentId) => {
      updateCachedDocuments((current) => {
        if (!current?.items?.length) return current
        return {
          ...current,
          items: current.items.map((doc) => mergePolledDocument(doc, documentId, status)),
        }
      })
    },
    onError: (err) => {
      setActionError(formatApiError(err, 'Failed to cancel document'))
      reportClientError('Cancel document failed', err)
    },
  })

  const {
    mutateAsync: deleteDocumentMutation,
    isPending: deleteDocumentPending,
  } = useMutation({
    mutationFn: (documentId: string) => documentApi.delete(documentId),
    onMutate: () => {
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
      reportClientError('Delete document failed', err)
    },
  })

  const cancelDocument = useCallback(
    async (documentId: string) => cancelDocumentMutation(documentId),
    [cancelDocumentMutation]
  )

  const deleteDocument = useCallback(
    async (documentId: string) => deleteDocumentMutation(documentId),
    [deleteDocumentMutation]
  )

  return {
    cancelDocument,
    deleteDocument,
    isActing: cancelDocumentPending || deleteDocumentPending,
  }
}
