import { API_LONG_TIMEOUT_MS } from '@/lib/env'
import { apiClient } from '@/lib/api/core'

export interface LTRModelInfo {
  model_id: string
  model_sha256: string
  size_bytes: number
  created_at: string
  created_by?: string | null
  feature_spec_version: number
  feature_schema: string
  feature_names: string[]
  has_manifest: boolean
  active: boolean
}

export interface LTRModelListResponse {
  items: LTRModelInfo[]
}

export interface LTRModelRegisterResponse {
  model: LTRModelInfo
}

export interface LTRModelActivateResponse {
  active: Record<string, unknown>
}

export const ltrApi = {
  async listModels(): Promise<LTRModelListResponse> {
    const { data } = await apiClient.get('/ltr/models')
    return data
  },

  async registerModel(params: { modelFile: File; manifestFile: File }): Promise<LTRModelRegisterResponse> {
    const formData = new FormData()
    formData.append('model_file', params.modelFile)
    formData.append('manifest_file', params.manifestFile)
    const { data } = await apiClient.post('/ltr/models/register', formData, { timeout: API_LONG_TIMEOUT_MS })
    return data
  },

  async activateModel(modelId: string): Promise<LTRModelActivateResponse> {
    const { data } = await apiClient.post('/ltr/models/activate', { model_id: modelId })
    return data
  },

  async rollbackActiveModel(): Promise<LTRModelActivateResponse> {
    const { data } = await apiClient.post('/ltr/models/rollback')
    return data
  },
}
