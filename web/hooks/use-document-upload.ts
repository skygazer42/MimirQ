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
  uploadBatchRound,
  type CaptureDocumentListOperation,
  type DocumentListOperation,
  type UploadBatchItem,
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

type BatchUploadOptions = { maxRetries?: number; maxConcurrent?: number }
type DocumentUrlUploadInput = Pick<Parameters<typeof documentApi.uploadFromUrl>[0], 'url' | 'filename' | 'dataset_id'>
type DocumentUploadResult = Required<Omit<DocumentBatchUploadResponse, 'precheck_scan_run_id'>> & {
  interruption?: string
}

export function useDocumentUpload({
  preferences,
  captureDocumentListOperation,
  pollDocumentStatus,
  setActionError,
}: UseDocumentUploadOptions) {
  const { parserBackend, chunkStrategy, pipelineOverridesEnabled, pipelineOptions } = preferences
  const uploadOptions = {
    parser_backend: parserBackend,
    chunk_strategy: chunkStrategy,
    pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
  }

  function clearUploadError({ operation }: { operation: DocumentListOperation }) {
    if (operation.isCurrent()) setActionError(null)
  }

  async function refreshAfterUpload(document: Document, { operation }: { operation: DocumentListOperation }) {
    await operation.refresh()
    if (operation.isActive()) pollDocumentStatus(document.id, operation)
  }

  function reportUploadError(error: unknown, operation: DocumentListOperation, message: string) {
    if (!operation.isActive()) return
    if (operation.isCurrent()) setActionError(formatApiError(error, message))
    reportClientError(message, error)
  }

  const { mutateAsync: uploadDocumentsMutation, isPending: uploadDocumentsPending } = useMutation({
    mutationFn: async ({
      files,
      options,
      operation,
    }: {
      files: File[]
      options?: BatchUploadOptions
      operation: DocumentListOperation
    }): Promise<DocumentUploadResult> => {
      if (!operation.isActive()) throw new CancelledError()
      const maxRetries = clampUploadOption(options?.maxRetries, 1, 0, 3)
      const maxConcurrent = clampUploadOption(options?.maxConcurrent, 5, 1, 10)

      const successes: DocumentBatchUploadSuccess[] = []
      const failures: DocumentBatchUploadFailure[] = []
      let remaining: UploadBatchItem[] = files.map((file) => ({ file }))
      let interruption: string | undefined
      for (let attempt = 0; remaining.length > 0; attempt += 1) {
        const round = await uploadBatchRound(
          remaining,
          {
            ...uploadOptions,
            dataset_id: operation.params.dataset_id,
            max_concurrent: maxConcurrent,
          },
          { isActive: operation.isActive, retryFailures: attempt < maxRetries },
        )
        if (!operation.isActive()) throw new CancelledError()

        successes.push(...round.successful)
        failures.push(...round.failed)
        if (round.interruption !== undefined) {
          const { error } = round.interruption
          if (attempt === 0 && successes.length === 0 && failures.length === 0) throw error
          interruption = formatApiError(error, '批量上传中断')
          reportClientError('Batch upload interrupted', error)
        }
        remaining = round.retryItems
      }

      await operation.refresh()
      if (!operation.isActive()) throw new CancelledError()
      for (const success of successes) pollDocumentStatus(success.document_id, operation)

      return {
        total: files.length,
        successful_count: successes.length,
        failed_count: failures.length,
        successful: successes,
        failed: failures,
        ...(interruption === undefined ? {} : { interruption }),
      }
    },
    onMutate: clearUploadError,
    onError: (error, { operation }) => reportUploadError(error, operation, 'Failed to upload documents'),
  })

  const { mutateAsync: uploadDocumentFromUrlMutation, isPending: uploadDocumentFromUrlPending } = useMutation({
    mutationFn: async ({ params, operation }: { params: DocumentUrlUploadInput; operation: DocumentListOperation }) => {
      if (!operation.isActive()) throw new CancelledError()
      const document = await documentApi.uploadFromUrl({
        ...uploadOptions,
        url: params.url,
        filename: params.filename,
        dataset_id: params.dataset_id,
      })
      if (!operation.isActive()) throw new CancelledError()
      return document
    },
    onMutate: clearUploadError,
    onSuccess: refreshAfterUpload,
    onError: (error, { operation }) => reportUploadError(error, operation, 'Failed to upload document from URL'),
  })

  const uploadDocuments = useCallback(
    async (files: File[], options?: BatchUploadOptions): Promise<DocumentUploadResult> => {
      if (files.length === 0) {
        return { total: 0, successful_count: 0, failed_count: 0, successful: [], failed: [] }
      }
      return uploadDocumentsMutation({ files, options, operation: captureDocumentListOperation() })
    },
    [captureDocumentListOperation, uploadDocumentsMutation],
  )

  const uploadDocumentFromUrl = useCallback(
    (params: DocumentUrlUploadInput) =>
      uploadDocumentFromUrlMutation({ params, operation: captureDocumentListOperation() }),
    [captureDocumentListOperation, uploadDocumentFromUrlMutation],
  )

  return {
    uploadDocuments,
    uploadDocumentFromUrl,
    isUploading: uploadDocumentsPending || uploadDocumentFromUrlPending,
  }
}
