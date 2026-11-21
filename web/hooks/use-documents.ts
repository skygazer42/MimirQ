'use client'

import { useState } from 'react'

import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { formatApiError } from '@/lib/api-errors'
import { useDocumentActions } from './use-document-actions'
import { useDocumentList } from './use-document-list'
import { useDocumentPolling } from './use-document-polling'
import { useDocumentUpload } from './use-document-upload'
import type { DocumentListParams } from './use-document-shared'

export function useDocuments(initialParams: DocumentListParams) {
  const [actionError, setActionError] = useState<string | null>(null)
  const { parserBackend } = useParserBackendPreference()
  const { chunkStrategy } = useChunkStrategyPreference()
  const { enabled: pipelineOverridesEnabled, options: pipelineOptions } = usePipelineOptions()

  const listState = useDocumentList({ setActionError, initialParams })
  const polling = useDocumentPolling({
    captureDocumentListOperation: listState.captureDocumentListOperation,
  })
  const uploadState = useDocumentUpload({
    preferences: {
      parserBackend,
      chunkStrategy,
      pipelineOverridesEnabled,
      pipelineOptions,
    },
    captureDocumentListOperation: listState.captureDocumentListOperation,
    pollDocumentStatus: polling.pollDocumentStatus,
    setActionError,
  })
  const actionState = useDocumentActions({
    cancelDocumentPolling: polling.cancelDocumentPolling,
    setActionError,
    captureDocumentListOperation: listState.captureDocumentListOperation,
  })

  const { isPlaceholderData } = listState
  const isLoading = listState.isFetching || isPlaceholderData || uploadState.isUploading || actionState.isActing
  const error =
    actionError ??
    (listState.listError === null ? null : formatApiError(listState.listError, 'Failed to load documents'))

  return {
    documents: listState.documents,
    total: listState.total,
    isLoading,
    isPlaceholderData,
    error,
    loadDocuments: listState.loadDocuments,
    uploadDocuments: uploadState.uploadDocuments,
    uploadDocumentFromUrl: uploadState.uploadDocumentFromUrl,
    deleteDocument: actionState.deleteDocument,
  }
}
