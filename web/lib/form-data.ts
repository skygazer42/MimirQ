import type { DocumentPipelineOptions } from '@/types'

export function appendPipelineOptionsToFormData(formData: FormData, pipeline?: DocumentPipelineOptions): void {
  if (!pipeline) return

  try {
    formData.append('pipeline', JSON.stringify(pipeline))
  } catch {
    // ignore non-serializable pipeline (should not happen for plain objects)
  }
}
