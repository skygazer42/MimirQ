import type { DocumentPipelineOptions } from '@/types'

import { appendPipelineOptionsToFormData } from '@/lib/form-data'

export type DocumentLifecycleFilter = 'active' | 'archived' | 'disabled' | 'all'

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

function appendFormDataIfString(formData: FormData, key: string, value: string | undefined, requireTruthy = false) {
  if (typeof value !== 'string') return
  if (requireTruthy && !value) return
  formData.append(key, value)
}

function appendFormDataIfNumber(formData: FormData, key: string, value: number | undefined) {
  if (typeof value === 'number') formData.append(key, String(value))
}

function appendFormDataIfBoolean(formData: FormData, key: string, value: boolean | undefined) {
  if (typeof value === 'boolean') formData.append(key, value ? 'true' : 'false')
}

export function appendChunkPreviewFormFields(
  formData: FormData,
  params: ChunkPreviewRequestParams,
  effectiveStrategy: string
) {
  appendFormDataIfString(formData, 'dataset_id', params.dataset_id, true)
  if (effectiveStrategy === 'parent_child') {
    appendFormDataIfNumber(formData, 'child_ratio', params.child_ratio)
    appendFormDataIfNumber(formData, 'min_child_size', params.min_child_size)
  }
  appendFormDataIfString(formData, 'separator_preset', params.separator_preset, true)
  appendFormDataIfString(formData, 'separator', params.separator)
  appendFormDataIfBoolean(formData, 'keep_separator', params.keep_separator)
  appendFormDataIfNumber(formData, 'separator_max_chunk_size', params.separator_max_chunk_size)
  appendPipelineOptionsToFormData(formData, params.pipeline)
}

export function buildChunkPreviewQueryParams(params: ChunkPreviewRequestParams) {
  return {
    chunk_size: params.chunk_size ?? params.pipeline?.chunk_size ?? 1000,
    chunk_overlap: params.chunk_overlap ?? params.pipeline?.chunk_overlap ?? 200,
    include_original_text:
      typeof params.include_original_text === 'boolean' ? params.include_original_text : undefined,
    include_chunks: typeof params.include_chunks === 'boolean' ? params.include_chunks : undefined,
    include_review_signals:
      typeof params.include_review_signals === 'boolean' ? params.include_review_signals : undefined,
    original_text_max_chars:
      typeof params.original_text_max_chars === 'number' ? params.original_text_max_chars : undefined,
    max_chunks: typeof params.max_chunks === 'number' ? params.max_chunks : undefined,
    use_parse_cache: typeof params.use_parse_cache === 'boolean' ? params.use_parse_cache : undefined,
  }
}
