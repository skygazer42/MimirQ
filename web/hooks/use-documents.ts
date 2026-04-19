/**
 * 文档管理 Hook
 */
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

export type { DocumentListParams } from './use-document-shared'
export {
  clampUploadOption,
  collectRetryFiles,
  isTerminalDocumentStatus,
  matchesDocumentListParams,
  matchesLifecycleFilter,
  matchesStatusFilter,
  mergePolledDocument,
  replacePolledDocument,
} from './use-document-shared'

export function useDocuments(initialParams?: DocumentListParams) {
  const [actionError, setActionError] = useState<string | null>(null)
  const { parserBackend } = useParserBackendPreference()
  const { chunkStrategy } = useChunkStrategyPreference()
  const { enabled: pipelineOverridesEnabled, options: pipelineOptions } = usePipelineOptions()

  const listState = useDocumentList({ setActionError, initialParams })
  const polling = useDocumentPolling({
    updateCachedDocuments: listState.updateCachedDocuments,
  })
  const uploadState = useDocumentUpload({
    preferences: {
      parserBackend,
      chunkStrategy,
      pipelineOverridesEnabled,
      pipelineOptions,
    },
    lastListParamsRef: listState.lastListParamsRef,
    loadDocuments: listState.loadDocuments,
    pollDocumentStatus: polling.pollDocumentStatus,
    setActionError,
    updateCachedDocuments: listState.updateCachedDocuments,
  })
  const actionState = useDocumentActions({
    cancelDocumentPolling: polling.cancelDocumentPolling,
    setActionError,
    updateCachedDocuments: listState.updateCachedDocuments,
  })

  const isLoading =
    listState.isListLoading ||
    listState.isFetching ||
    uploadState.isUploading ||
    actionState.isActing
  const error =
    actionError || (listState.listError ? formatApiError(listState.listError, 'Failed to load documents') : null)

  return {
    documents: listState.documents,
    total: listState.total,
    isLoading,
    error,
    loadDocuments: listState.loadDocuments,
    refreshDocuments: listState.loadDocuments,
    uploadDocument: uploadState.uploadDocument,
    uploadDocuments: uploadState.uploadDocuments,
    uploadDocumentFromUrl: uploadState.uploadDocumentFromUrl,
    cancelDocument: actionState.cancelDocument,
    deleteDocument: actionState.deleteDocument,
  }
}
