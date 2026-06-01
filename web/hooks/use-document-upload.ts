'use client'

import { useCallback } from 'react'
import { useMutation } from '@tanstack/react-query'

import { documentApi } from '@/lib/api/documents'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'
import type {
  Document,
  DocumentBatchUploadFailure,
  DocumentBatchUploadResponse,
  DocumentBatchUploadSuccess,
  DocumentPipelineOptions,
} from '@/types'

import {
  clampUploadOption,
  getUploadFileKey,
  matchesDocumentListParams,
  uploadBatchRound,
  type DocumentListParams,
  type UpdateCachedDocuments,
} from './use-document-shared'

type DocumentUploadPreferences = {
  parserBackend: string
  chunkStrategy: string
  pipelineOverridesEnabled: boolean
  pipelineOptions: DocumentPipelineOptions
}

type UseDocumentUploadOptions = {
  preferences: DocumentUploadPreferences
  lastListParamsRef: { current: DocumentListParams }
  loadDocuments: (params?: DocumentListParams) => Promise<void>
  pollDocumentStatus: (documentId: string) => void
  setActionError: (error: string | null) => void
  updateCachedDocuments: UpdateCachedDocuments
}

function prependDocument(
  newDocument: Document,
  currentParams: DocumentListParams,
  updateCachedDocuments: UpdateCachedDocuments
) {
  if (!matchesDocumentListParams(newDocument, currentParams)) return

  updateCachedDocuments((current) => ({
    ...(current || { items: [], total: 0 }),
    items: [newDocument, ...(current?.items || [])],
    total: Number(current?.total || 0) + 1,
  }))
}

export function useDocumentUpload({
  preferences,
  lastListParamsRef,
  loadDocuments,
  pollDocumentStatus,
  setActionError,
  updateCachedDocuments,
}: UseDocumentUploadOptions) {
  const { parserBackend, chunkStrategy, pipelineOverridesEnabled, pipelineOptions } = preferences

  const {
    mutateAsync: uploadDocumentMutation,
    isPending: uploadDocumentPending,
  } = useMutation({
    mutationFn: async (file: File) => {
      const datasetId = String(lastListParamsRef.current.dataset_id || '').trim()
      return documentApi.upload(file, {
        parser_backend: parserBackend,
        chunk_strategy: chunkStrategy,
        dataset_id: datasetId || undefined,
        pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
      })
    },
    onMutate: () => {
      setActionError(null)
    },
    onSuccess: (newDoc) => {
      prependDocument(newDoc, lastListParamsRef.current, updateCachedDocuments)
      pollDocumentStatus(newDoc.id)
    },
    onError: (err) => {
      setActionError(formatApiError(err, 'Failed to upload document'))
      reportClientError('Upload document failed', err)
    },
  })

  const {
    mutateAsync: uploadDocumentsMutation,
    isPending: uploadDocumentsPending,
  } = useMutation({
    mutationFn: async ({
      files,
      options,
    }: {
      files: File[]
      options?: { maxRetries?: number; maxConcurrent?: number }
    }): Promise<DocumentBatchUploadResponse> => {
      const maxRetries = clampUploadOption(options?.maxRetries, 1, 0, 3)
      const maxConcurrent = clampUploadOption(options?.maxConcurrent, 5, 1, 10)
      const datasetId = String(lastListParamsRef.current.dataset_id || '').trim()

      const originalFiles = files.filter(Boolean)
      const total = originalFiles.length
      if (total === 0) {
        return { total: 0, successful_count: 0, failed_count: 0, successful: [], failed: [] }
      }

      const fileByKey = new Map<string, File>()
      for (const file of originalFiles) {
        const key = getUploadFileKey(file)
        if (key) fileByKey.set(key, file)
      }

      const successes: DocumentBatchUploadSuccess[] = []
      let failures: DocumentBatchUploadFailure[] = []
      let remaining = originalFiles
      let attempt = 0

      while (remaining.length > 0 && attempt <= maxRetries) {
        const round = await uploadBatchRound(
          remaining,
          {
            parser_backend: parserBackend,
            chunk_strategy: chunkStrategy,
            dataset_id: datasetId || undefined,
            pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
            max_concurrent: maxConcurrent,
          },
          fileByKey
        )

        successes.push(...round.successful)
        failures = round.failed
        if (round.nextRemaining.length === 0) break

        attempt += 1
        remaining = round.nextRemaining
      }

      await loadDocuments()
      for (const success of successes) {
        if (success?.document_id) {
          pollDocumentStatus(String(success.document_id))
        }
      }

      return {
        total,
        successful_count: successes.length,
        failed_count: failures.length,
        successful: successes,
        failed: failures,
      }
    },
    onMutate: () => {
      setActionError(null)
    },
    onError: (err) => {
      setActionError(formatApiError(err, 'Failed to upload documents'))
      reportClientError('Batch upload documents failed', err)
    },
  })

  const {
    mutateAsync: uploadDocumentFromUrlMutation,
    isPending: uploadDocumentFromUrlPending,
  } = useMutation({
    mutationFn: async (params: { url: string; filename?: string; dataset_id?: string }) => {
      return documentApi.uploadFromUrl({
        url: params.url,
        filename: params.filename,
        dataset_id: params.dataset_id,
        parser_backend: parserBackend,
        chunk_strategy: chunkStrategy,
        pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
      })
    },
    onMutate: () => {
      setActionError(null)
    },
    onSuccess: (newDoc) => {
      prependDocument(newDoc, lastListParamsRef.current, updateCachedDocuments)
      pollDocumentStatus(newDoc.id)
    },
    onError: (err) => {
      setActionError(formatApiError(err, 'Failed to upload document from URL'))
      reportClientError('Upload document from URL failed', err)
    },
  })

  const uploadDocument = useCallback(
    async (file: File) => uploadDocumentMutation(file),
    [uploadDocumentMutation]
  )

  const uploadDocuments = useCallback(
    async (
      files: File[],
      options: { maxRetries?: number; maxConcurrent?: number } = {}
    ) => uploadDocumentsMutation({ files, options }),
    [uploadDocumentsMutation]
  )

  const uploadDocumentFromUrl = useCallback(
    async (params: { url: string; filename?: string; dataset_id?: string }) => {
      return uploadDocumentFromUrlMutation(params)
    },
    [uploadDocumentFromUrlMutation]
  )

  return {
    uploadDocument,
    uploadDocuments,
    uploadDocumentFromUrl,
    isUploading: uploadDocumentPending || uploadDocumentsPending || uploadDocumentFromUrlPending,
  }
}
