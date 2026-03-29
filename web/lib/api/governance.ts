import type {
  ChunkPreset,
  ChunkPresetCreateRequest,
  ChunkPresetListResponse,
  ChunkPresetUpdateRequest,
  GovernanceRulePackListResponse,
  StaleDocumentsByDatasetResponse,
} from '@/types'

import { apiClient } from '@/lib/api/core'

export const governanceApi = {
  async listRulePacks(): Promise<GovernanceRulePackListResponse> {
    const { data } = await apiClient.get('/governance/rule-packs')
    return data
  },

  async listStaleDocumentsByDataset(
    datasetId: string,
    params?: {
      mode?: 'overdue' | 'due_soon' | 'all'
      due_within_days?: number
      due_before?: string
      as_of?: string
      include_inactive?: boolean
      skip?: number
      limit?: number
      order_by?: 'review_due_at' | 'authority_level' | 'updated_at' | 'created_at' | 'filename'
      order_dir?: 'asc' | 'desc'
    }
  ): Promise<StaleDocumentsByDatasetResponse> {
    const { data } = await apiClient.get(`/governance/datasets/${encodeURIComponent(datasetId)}/stale-documents`, {
      params,
    })
    return data
  },
}

export const chunkPresetApi = {
  async list(params?: { q?: string; limit?: number; dataset_id?: string; include_global?: boolean }): Promise<ChunkPresetListResponse> {
    const { data } = await apiClient.get('/chunk-presets', { params })
    return data
  },

  async create(payload: ChunkPresetCreateRequest): Promise<ChunkPreset> {
    const { data } = await apiClient.post('/chunk-presets', payload)
    return data
  },

  async update(presetId: string, payload: ChunkPresetUpdateRequest): Promise<ChunkPreset> {
    const { data } = await apiClient.put(`/chunk-presets/${encodeURIComponent(presetId)}`, payload)
    return data
  },

  async delete(presetId: string): Promise<void> {
    await apiClient.delete(`/chunk-presets/${encodeURIComponent(presetId)}`)
  },
}
