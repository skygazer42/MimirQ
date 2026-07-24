import { API_LONG_TIMEOUT_MS } from '@/lib/env'
import type { OpenApiSchema } from '@/types/backend'
import { apiClient } from '@/lib/api/core'

export type LTRModelInfo = OpenApiSchema<'LTRModelInfo'>
export type LTRModelListResponse = OpenApiSchema<'LTRModelListResponse'>
export type LTRModelRegisterResponse = OpenApiSchema<'LTRModelRegisterResponse'>
export type LTRModelActivateResponse = OpenApiSchema<'LTRModelActivateResponse'>

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
