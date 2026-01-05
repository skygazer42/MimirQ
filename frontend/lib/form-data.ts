import type { DocumentPipelineOptions } from '@/types'

type FormValue = string | number | boolean | undefined | null

function appendIfDefined(formData: FormData, key: string, value: FormValue): void {
  if (value === undefined || value === null) return
  formData.append(key, String(value))
}

export function appendPipelineOptionsToFormData(formData: FormData, pipeline?: DocumentPipelineOptions): void {
  if (!pipeline) return

  appendIfDefined(formData, 'governance_enabled', pipeline.governance_enabled)
  appendIfDefined(formData, 'governance_remove_toc_lines', pipeline.governance_remove_toc_lines)
  appendIfDefined(formData, 'governance_remove_noise_lines', pipeline.governance_remove_noise_lines)
  appendIfDefined(formData, 'governance_unwrap_lines', pipeline.governance_unwrap_lines)
  appendIfDefined(formData, 'governance_remove_common_lines', pipeline.governance_remove_common_lines)
  appendIfDefined(formData, 'governance_unwrap_max_line_length', pipeline.governance_unwrap_max_line_length)
  appendIfDefined(formData, 'governance_noise_min_chars', pipeline.governance_noise_min_chars)
  appendIfDefined(formData, 'governance_noise_ratio_threshold', pipeline.governance_noise_ratio_threshold)
  appendIfDefined(formData, 'governance_common_lines_min_docs', pipeline.governance_common_lines_min_docs)
  appendIfDefined(formData, 'governance_common_lines_min_ratio', pipeline.governance_common_lines_min_ratio)

  appendIfDefined(formData, 'chunk_size', pipeline.chunk_size)
  appendIfDefined(formData, 'chunk_overlap', pipeline.chunk_overlap)
  appendIfDefined(formData, 'chunk_vector_enabled', pipeline.chunk_vector_enabled)
  appendIfDefined(formData, 'bm25_index_enabled', pipeline.bm25_index_enabled)
  appendIfDefined(formData, 'kg_enabled', pipeline.kg_enabled)
  appendIfDefined(formData, 'event_vector_enabled', pipeline.event_vector_enabled)
  appendIfDefined(formData, 'entity_vector_enabled', pipeline.entity_vector_enabled)
}

