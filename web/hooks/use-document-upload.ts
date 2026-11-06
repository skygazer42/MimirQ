'use client'

import { useCallback } from 'react'
import { CancelledError, useMutation } from '@tanstack/react-query'

import { documentApi } from '@/lib/api/documents'
import { formatApiError } from '@/lib/api-errors'
import { reportClientError } from '@/lib/client-logging'
import type {
  Document,
  DocumentBatchUploadFailure,
  DocumentBatchUploadResponse,
  DocumentBatchUploadSuccess,
  DocumentPipelineOptions,
} from '@/types/backend'

import {
  clampUploadOption,
  getUploadFileKey,
  matchesDocumentListParams,
  uploadBatchRound,
  type CaptureDocumentListOperation,
  type DocumentListParams,
  type DocumentListOperation,
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
  captureDocumentListOperation: CaptureDocumentListOperation
  pollDocumentStatus: (documentId: string, operation: DocumentListOperation) => void
  setActionError: (error: string | null) => void
}

function prependDocument(
  newDocument: Document,
  currentParams: DocumentListParams,
  updateCachedDocuments: UpdateCachedDocuments,
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
  captureDocumentListOperation,
  pollDocumentStatus,
  setActionError,
}: UseDocumentUploadOptions) {
  const { parserBackend, chunkStrategy, pipelineOverridesEnabled, pipelineOptions } = preferences

  const { mutateAsync: uploadDocumentMutation, isPending: uploadDocumentPending } = useMutation({
    mutationFn: async ({ file, operation }: { file: File; operation: DocumentListOperation }) => {
      if (!operation.isActive()) throw new CancelledError()
      const datasetId = String(operation.params.dataset_id || '').trim()
      const document = await documentApi.upload(file, {
        parser_backend: parserBackend,
        chunk_strategy: chunkStrategy,
        dataset_id: datasetId || undefined,
        pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
      })
      if (!operation.isActive()) throw new CancelledError()
      return document
    },
    onMutate: ({ operation }) => {
      if (operation.isCurrent()) setActionError(null)
    },
    onSuccess: (newDoc, { operation }) => {
      if (!operation.isActive()) return
      prependDocument(newDoc, operation.params, operation.updateCachedDocuments)
      pollDocumentStatus(newDoc.id, operation)
    },
    onError: (err, { operation }) => {
      if (!operation.isActive()) return
      if (operation.isCurrent()) setActionError(formatApiError(err, 'Failed to upload document'))
      reportClientError('Upload document failed', err)
    },
  })

  const { mutateAsync: uploadDocumentsMutation, isPending: uploadDocumentsPending } = useMutation({
    mutationFn: async ({
      files,
      options,
      operation,
    }: {
      files: File[]
      options?: { maxRetries?: number; maxConcurrent?: number }
      operation: DocumentListOperation
    }): Promise<DocumentBatchUploadResponse> => {
      if (!operation.isActive()) throw new CancelledError()
      const maxRetries = clampUploadOption(options?.maxRetries, 1, 0, 3)
      const maxConcurrent = clampUploadOption(options?.maxConcurrent, 5, 1, 10)
      const datasetId = String(operation.params.dataset_id || '').trim()

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
          fileByKey,
          operation.isActive,
        )
        if (!operation.isActive()) throw new CancelledError()

        successes.push(...round.successful)
        failures = round.failed
        if (round.nextRemaining.length === 0) break

        attempt += 1
        remaining = round.nextRemaining
      }

      await operation.refresh()
      if (!operation.isActive()) throw new CancelledError()
      for (const success of successes) {
        if (success?.document_id) {
          pollDocumentStatus(String(success.document_id), operation)
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
    onMutate: ({ operation }) => {
      if (operation.isCurrent()) setActionError(null)
    },
    onError: (err, { operation }) => {
      if (!operation.isActive()) return
      if (operation.isCurrent()) setActionError(formatApiError(err, 'Failed to upload documents'))
      reportClientError('Batch upload documents failed', err)
    },
  })

  const { mutateAsync: uploadDocumentFromUrlMutation, isPending: uploadDocumentFromUrlPending } = useMutation({
    mutationFn: async ({
      params,
      operation,
    }: {
      params: { url: string; filename?: string; dataset_id?: string }
      operation: DocumentListOperation
    }) => {
      if (!operation.isActive()) throw new CancelledError()
      const document = await documentApi.uploadFromUrl({
        url: params.url,
        filename: params.filename,
        dataset_id: params.dataset_id,
        parser_backend: parserBackend,
        chunk_strategy: chunkStrategy,
        pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
      })
      if (!operation.isActive()) throw new CancelledError()
      return document
    },
    onMutate: ({ operation }) => {
      if (operation.isCurrent()) setActionError(null)
    },
    onSuccess: (newDoc, { operation }) => {
      if (!operation.isActive()) return
      prependDocument(newDoc, operation.params, operation.updateCachedDocuments)
      pollDocumentStatus(newDoc.id, operation)
    },
    onError: (err, { operation }) => {
      if (!operation.isActive()) return
      if (operation.isCurrent()) setActionError(formatApiError(err, 'Failed to upload document from URL'))
      reportClientError('Upload document from URL failed', err)
    },
  })

  const uploadDocument = useCallback(
    async (file: File) => uploadDocumentMutation({ file, operation: captureDocumentListOperation() }),
    [captureDocumentListOperation, uploadDocumentMutation],
  )

  const uploadDocuments = useCallback(
    async (files: File[], options: { maxRetries?: number; maxConcurrent?: number } = {}) =>
      uploadDocumentsMutation({ files, options, operation: captureDocumentListOperation() }),
    [captureDocumentListOperation, uploadDocumentsMutation],
  )

  const uploadDocumentFromUrl = useCallback(
    async (params: { url: string; filename?: string; dataset_id?: string }) => {
      return uploadDocumentFromUrlMutation({ params, operation: captureDocumentListOperation() })
    },
    [captureDocumentListOperation, uploadDocumentFromUrlMutation],
  )

  return {
    uploadDocument,
    uploadDocuments,
    uploadDocumentFromUrl,
    isUploading: uploadDocumentPending || uploadDocumentsPending || uploadDocumentFromUrlPending,
  }
}
