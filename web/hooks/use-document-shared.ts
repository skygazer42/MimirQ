'use client'

import { CancelledError } from '@tanstack/react-query'

import { DOCUMENT_UPLOAD_BATCH_LIMIT, matchUploadReceipts } from '@/lib/api/document-helpers'
import { documentApi } from '@/lib/api/documents'
import type { Document, DocumentBatchUploadFailure, DocumentBatchUploadSuccess } from '@/types/backend'

export type DocumentListParams = NonNullable<Parameters<typeof documentApi.list>[0]>

type UploadBatchRequestOptions = NonNullable<Parameters<typeof documentApi.uploadBatch>[1]>

type DocumentStatusSnapshot = Pick<Document, 'status' | 'processing_progress' | 'current_stage' | 'error_message'>

export type DocumentListResponse = Awaited<ReturnType<typeof documentApi.list>>

export type UpdateCachedDocuments = (
  updater: (current: DocumentListResponse | undefined) => DocumentListResponse | undefined,
) => void

export type DocumentListOperation = {
  params: DocumentListParams
  isActive: () => boolean
  isCurrent: () => boolean
  updateCachedDocuments: UpdateCachedDocuments
  refresh: () => Promise<void>
}

export type CaptureDocumentListOperation = () => DocumentListOperation

const TERMINAL_DOCUMENT_STATUSES = new Set(['completed', 'failed', 'cancelled', 'quarantined'])

export function isTerminalDocumentStatus(status: Document['status']): boolean {
  return TERMINAL_DOCUMENT_STATUSES.has(status)
}

export function mergePolledDocumentList(
  documents: Document[],
  documentId: string,
  status: DocumentStatusSnapshot,
): Document[] {
  return documents.map((doc) => {
    if (doc.id !== documentId) return doc
    return {
      ...doc,
      status: status.status,
      processing_progress: status.processing_progress,
      current_stage: status.current_stage,
      error_message: status.error_message,
    }
  })
}

export function replacePolledDocumentList(
  documents: Document[],
  documentId: string,
  nextDocument: Document,
): Document[] {
  return documents.map((doc) => (doc.id === documentId ? nextDocument : doc))
}

export function clampUploadOption(value: number | undefined, fallback: number, min: number, max: number): number {
  const count = value === undefined || Number.isNaN(value) ? fallback : Math.trunc(value)
  return Math.max(min, Math.min(max, count))
}

export type UploadBatchItem = { file: File; previousFailure?: DocumentBatchUploadFailure }

export async function uploadBatchRound(
  items: readonly UploadBatchItem[],
  options: UploadBatchRequestOptions,
  { isActive, retryFailures }: Readonly<{ isActive: () => boolean; retryFailures: boolean }>,
): Promise<{
  successful: DocumentBatchUploadSuccess[]
  failed: DocumentBatchUploadFailure[]
  retryItems: UploadBatchItem[]
  interruption?: { error: unknown }
}> {
  const successful: DocumentBatchUploadSuccess[] = []
  const failed: DocumentBatchUploadFailure[] = []
  const retries: Array<{ file: File; previousFailure: DocumentBatchUploadFailure }> = []

  for (let offset = 0; offset < items.length; offset += DOCUMENT_UPLOAD_BATCH_LIMIT) {
    if (!isActive()) throw new CancelledError()
    const batch = items.slice(offset, offset + DOCUMENT_UPLOAD_BATCH_LIMIT).map(({ file }) => file)
    let response: Awaited<ReturnType<typeof documentApi.uploadBatch>>
    try {
      response = await documentApi.uploadBatch(batch, options)
    } catch (error) {
      if (!isActive()) throw new CancelledError()
      for (const { previousFailure } of items.slice(offset + batch.length)) {
        if (previousFailure !== undefined) failed.push(previousFailure)
      }
      return {
        successful,
        failed: [...failed, ...retries.map(({ previousFailure }) => previousFailure)],
        retryItems: [],
        interruption: { error },
      }
    }
    if (!isActive()) throw new CancelledError()
    const { successful: uploaded, failed: batchFailures } = response
    successful.push(...uploaded)
    if (batchFailures.length === 0) continue
    if (!retryFailures) {
      failed.push(...batchFailures)
      continue
    }

    const filesByReceipt = matchUploadReceipts(batch, [...uploaded, ...batchFailures])
    for (const failure of batchFailures) {
      const retryFile = filesByReceipt.get(failure)
      if (retryFile !== undefined) retries.push({ file: retryFile, previousFailure: failure })
      else failed.push(failure)
    }
  }

  return {
    successful,
    failed,
    retryItems: retries,
  }
}
