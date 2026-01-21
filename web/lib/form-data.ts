import type { DocumentPipelineOptions } from '@/types'

type FormValue = string | number | boolean | undefined | null

function appendIfDefined(formData: FormData, key: string, value: FormValue): void {
  if (value === undefined || value === null) return
  formData.append(key, String(value))
}

export function appendPipelineOptionsToFormData(formData: FormData, pipeline?: DocumentPipelineOptions): void {
  if (!pipeline) return

  try {
    formData.append('pipeline', JSON.stringify(pipeline))
  } catch {
    // ignore non-serializable pipeline (should not happen for plain objects)
  }
}
