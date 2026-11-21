import type { DocumentBatchUploadFailure, DocumentPipelineOptions } from '@/types/backend'

import { resolveParserBackendForFilename } from '@/lib/parser-compat'

export type DocumentLifecycleFilter = 'active' | 'archived' | 'disabled' | 'all'

export const DOCUMENT_UPLOAD_BATCH_LIMIT = 50
const UPLOAD_SOURCE_PATH_LIMIT = 500

export function getUploadFilename(file: File): string {
  const relativePath = file.webkitRelativePath
  return relativePath === undefined || relativePath === '' ? file.name : relativePath
}

function getUploadSourceKey(file: File): string {
  // Match the source path returned by the upload service for relative paths.
  const parts = getUploadFilename(file)
    .replaceAll('\\', '/')
    .split('/')
    .map((part) => part.trim())
    .filter((part) => part !== '' && part !== '.')
  const firstPart = parts[0]
  if (firstPart !== undefined && /^[a-zA-Z]:$/.test(firstPart)) parts.shift()
  const normalized: string[] = []
  for (const part of parts) {
    if (part === '..') normalized.pop()
    else normalized.push(part)
  }
  if (normalized.length === 2 && normalized[0].toLowerCase() === 'fakepath') normalized.shift()
  return Array.from(normalized.join('/')).slice(0, UPLOAD_SOURCE_PATH_LIMIT).join('')
}

type UploadReceiptFile = Pick<DocumentBatchUploadFailure, 'filename' | 'source_path'>

export function getUploadReceiptKey({ filename, source_path }: UploadReceiptFile): string {
  return source_path === undefined || source_path === null || source_path === '' ? filename.trim() : source_path
}

export function matchUploadReceipts<Receipt extends UploadReceiptFile>(
  files: readonly File[],
  receipts: readonly Receipt[],
) {
  const filesByKey = new Map<string, File | null>()
  for (const file of files) {
    const key = getUploadSourceKey(file)
    if (key !== '') filesByKey.set(key, filesByKey.has(key) ? null : file)
  }

  const receiptCounts = new Map<string, number>()
  for (const receipt of receipts) {
    const key = getUploadReceiptKey(receipt)
    receiptCounts.set(key, (receiptCounts.get(key) ?? 0) + 1)
  }

  const matched = new Map<Receipt, File>()
  for (const receipt of receipts) {
    const key = getUploadReceiptKey(receipt)
    const file = filesByKey.get(key)
    if (file && receiptCounts.get(key) === 1) matched.set(receipt, file)
  }
  return matched
}

export type ChunkPreviewRequestParams = {
  chunk_size?: number
  chunk_overlap?: number
  parser_backend?: string
  chunk_strategy?: string
  child_ratio?: number
  min_child_size?: number
  pipeline?: DocumentPipelineOptions
  dataset_id?: string
  include_original_text?: boolean
  include_chunks?: boolean
  include_review_signals?: boolean
  original_text_max_chars?: number
  max_chunks?: number
  use_parse_cache?: boolean
  separator_preset?: string
  separator?: string
  keep_separator?: boolean
  separator_max_chunk_size?: number
}

function appendOptionalFormField(
  form: FormData | URLSearchParams,
  key: string,
  value: string | number | boolean | undefined,
) {
  if (value !== undefined) form.append(key, String(value))
}

export function appendPipelineOptionsToForm(
  form: FormData | URLSearchParams,
  pipeline?: DocumentPipelineOptions,
): void {
  if (pipeline === undefined) return
  form.append('pipeline', JSON.stringify(pipeline))
}

export function appendChunkPreviewSettings(
  form: FormData | URLSearchParams,
  filename: string,
  params: ChunkPreviewRequestParams,
) {
  const parser = resolveParserBackendForFilename(filename, params.parser_backend)
  form.append('parser_backend', parser.backend)
  appendOptionalFormField(form, 'chunk_strategy', params.chunk_strategy)
  appendOptionalFormField(form, 'dataset_id', params.dataset_id)
  appendOptionalFormField(form, 'child_ratio', params.child_ratio)
  appendOptionalFormField(form, 'min_child_size', params.min_child_size)
  appendOptionalFormField(form, 'separator_preset', params.separator_preset)
  appendOptionalFormField(form, 'separator', params.separator)
  appendOptionalFormField(form, 'keep_separator', params.keep_separator)
  appendOptionalFormField(form, 'separator_max_chunk_size', params.separator_max_chunk_size)
  appendPipelineOptionsToForm(form, params.pipeline)
}

export function buildChunkPreviewQueryParams(params: ChunkPreviewRequestParams) {
  return {
    chunk_size: params.chunk_size ?? params.pipeline?.chunk_size,
    chunk_overlap: params.chunk_overlap ?? params.pipeline?.chunk_overlap,
    include_original_text: params.include_original_text,
    include_chunks: params.include_chunks,
    include_review_signals: params.include_review_signals,
    original_text_max_chars: params.original_text_max_chars,
    max_chunks: params.max_chunks,
    use_parse_cache: params.use_parse_cache,
  }
}
