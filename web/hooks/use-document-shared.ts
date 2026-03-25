'use client'

import { documentApi } from '@/lib/api/documents'
import type {
  Document,
  DocumentBatchUploadFailure,
  DocumentBatchUploadSuccess,
  DocumentPipelineOptions,
} from '@/types'

export type DocumentListParams = {
  skip?: number
  limit?: number
  status?: string
  lifecycle?: 'active' | 'archived' | 'disabled' | 'all'
  dataset_id?: string
  source_path_prefix?: string
  q?: string
  order_by?: 'created_at' | 'filename' | 'file_size'
  order_dir?: 'asc' | 'desc'
}

export type UploadBatchRequestOptions = {
  parser_backend: string
  chunk_strategy: string
  dataset_id?: string
  pipeline?: DocumentPipelineOptions
  max_concurrent: number
}

export type DocumentStatusSnapshot = Pick<
  Document,
  'status' | 'processing_progress' | 'current_stage' | 'error_message'
>

export type DocumentListResponse = Awaited<ReturnType<typeof documentApi.list>>

export type UpdateCachedDocuments = (
  updater: (current: DocumentListResponse | undefined) => DocumentListResponse | undefined
) => void

const TERMINAL_DOCUMENT_STATUSES = new Set(['completed', 'failed', 'cancelled', 'quarantined'])

function getDocumentSourcePath(doc: Document): string {
  const metadata = doc.metadata
  if (!metadata || typeof metadata !== 'object') return ''

  const sourcePath = (metadata as Record<string, unknown>).source_path
  return typeof sourcePath === 'string' ? sourcePath.trim() : ''
}

export function matchesStatusFilter(doc: Document, statusFilter: string | undefined): boolean {
  const status = String(statusFilter || '').trim().toLowerCase()
  if (!status || status === 'all') return true
  if (status === 'processing') {
    return doc.status === 'pending' || doc.status === 'processing'
  }
  return doc.status === status
}

export function matchesLifecycleFilter(doc: Document, lifecycleFilter: string | undefined): boolean {
  const lifecycle = String(lifecycleFilter || '').trim().toLowerCase()
  if (!lifecycle || lifecycle === 'all') return true

  const isArchived = Boolean(doc.archived_at)
  const isDisabled = Boolean(doc.disabled_at)
  if (lifecycle === 'active') return !isArchived && !isDisabled
  if (lifecycle === 'archived') return isArchived
  if (lifecycle === 'disabled') return isDisabled
  return true
}

export function matchesDocumentListParams(doc: Document, params: DocumentListParams): boolean {
  if (!matchesStatusFilter(doc, params.status)) return false

  const datasetId = String(params.dataset_id || '').trim()
  if (datasetId && String(doc.dataset_id || '') !== datasetId) return false

  const sourcePathPrefix = String(params.source_path_prefix || '').trim()
  if (sourcePathPrefix && !getDocumentSourcePath(doc).startsWith(sourcePathPrefix)) {
    return false
  }

  if (!matchesLifecycleFilter(doc, params.lifecycle)) return false

  const query = String(params.q || '').trim().toLowerCase()
  if (query && !String(doc.filename || '').toLowerCase().includes(query)) return false

  return true
}

export function isTerminalDocumentStatus(status: string | undefined): boolean {
  return TERMINAL_DOCUMENT_STATUSES.has(String(status || '').toLowerCase())
}

export function mergePolledDocument(
  doc: Document,
  documentId: string,
  status: DocumentStatusSnapshot
): Document {
  if (doc.id !== documentId) return doc

  return {
    ...doc,
    status: status.status,
    processing_progress: status.processing_progress,
    current_stage: status.current_stage,
    error_message: status.error_message,
  }
}

export function replacePolledDocument(doc: Document, documentId: string, nextDocument: Document): Document {
  return doc.id === documentId ? nextDocument : doc
}

export function mergePolledDocumentList(
  documents: Document[],
  documentId: string,
  status: DocumentStatusSnapshot
): Document[] {
  return documents.map((doc) => mergePolledDocument(doc, documentId, status))
}

export function replacePolledDocumentList(
  documents: Document[],
  documentId: string,
  nextDocument: Document
): Document[] {
  return documents.map((doc) => replacePolledDocument(doc, documentId, nextDocument))
}

export function clampUploadOption(
  value: number | undefined,
  fallback: number,
  min: number,
  max: number
): number {
  return Math.max(min, Math.min(max, Number(value ?? fallback)))
}

export function getUploadFileKey(
  file: Pick<File, 'name'> & { webkitRelativePath?: string } | DocumentBatchUploadFailure
): string {
  if ('source_path' in file || 'filename' in file) {
    return String(file.source_path || file.filename || '').trim()
  }
  return String(file.webkitRelativePath || file.name || '').trim()
}

export function collectRetryFiles(
  failed: DocumentBatchUploadFailure[],
  fileByKey: Map<string, File>
): File[] {
  const nextRemaining: File[] = []
  for (const item of failed) {
    const retryFile = fileByKey.get(getUploadFileKey(item))
    if (retryFile) nextRemaining.push(retryFile)
  }
  return nextRemaining
}

export async function uploadBatchRound(
  files: File[],
  options: UploadBatchRequestOptions,
  fileByKey: Map<string, File>
): Promise<{
  successful: DocumentBatchUploadSuccess[]
  failed: DocumentBatchUploadFailure[]
  nextRemaining: File[]
}> {
  const successful: DocumentBatchUploadSuccess[] = []
  const failed: DocumentBatchUploadFailure[] = []

  for (let i = 0; i < files.length; i += 50) {
    const batch = files.slice(i, i + 50)
    const response = await documentApi.uploadBatch(batch, options)
    successful.push(...(response.successful || []))
    failed.push(...(response.failed || []))
  }

  return {
    successful,
    failed,
    nextRemaining: collectRetryFiles(failed, fileByKey),
  }
}
