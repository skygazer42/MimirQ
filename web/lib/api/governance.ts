import { z } from 'zod'

import type {
  ChunkPreset,
  ChunkPresetCreateRequest,
  ChunkPresetListResponse,
  ChunkPresetUpdateRequest,
  GovernanceRulePackListResponse,
  StaleDocumentsByDatasetResponse,
} from '@/types/processing'

import { apiClient, type ApiRequestOptions } from '@/lib/api/core'
import { parseApiResponse } from '@/lib/openapi-request'
import { matchesResourceId } from '@/lib/resource-id'
import { dateTimeSchema, integerSchema, recordSchema } from '@/lib/response-schema'
import type { OpenApiQueryParams } from '@/types/openapi-helpers'

const rulePackListSchema = z.looseObject({ items: z.array(z.string()) })
const chunkPresetSchema = z.looseObject({
  id: z.string(),
  name: z.string(),
  description: z.string().nullish(),
  payload: recordSchema,
})
const chunkPresetListSchema = z.looseObject({ items: z.array(chunkPresetSchema) })
const staleDocumentsSchema = z.looseObject({
  dataset_id: z.string(),
  as_of: dateTimeSchema,
  due_before: dateTimeSchema,
  mode: z.enum(['overdue', 'due_soon', 'all']),
  skip: integerSchema,
  limit: integerSchema,
  total: integerSchema,
  items: z.array(
    z.looseObject({
      id: z.string(),
      filename: z.string(),
      file_type: z.string(),
      status: z.string(),
      lifecycle_owner: z.string().nullish(),
      review_due_at: dateTimeSchema.nullish(),
      authority_level: integerSchema.nullish(),
      supersedes_document_id: z.string().nullish(),
      created_at: dateTimeSchema.nullish(),
      updated_at: dateTimeSchema.nullish(),
    }),
  ),
})

export const governanceApi = {
  async listRulePacks(options?: ApiRequestOptions): Promise<GovernanceRulePackListResponse> {
    const response = await apiClient.get<unknown>('/governance/rule-packs', { signal: options?.signal })
    return parseApiResponse(response, rulePackListSchema, 'GovernanceRulePackList')
  },

  async listStaleDocumentsByDataset(
    datasetId: string,
    params?: OpenApiQueryParams<'/api/v1/governance/datasets/{dataset_id}/stale-documents', 'get'>,
    options?: ApiRequestOptions,
  ): Promise<StaleDocumentsByDatasetResponse> {
    const response = await apiClient.get<unknown>(
      `/governance/datasets/${encodeURIComponent(datasetId)}/stale-documents`,
      { params, signal: options?.signal },
    )
    const result = parseApiResponse(response, staleDocumentsSchema, 'StaleDocumentsByDataset')
    if (!matchesResourceId(result.dataset_id, datasetId)) throw new Error('复核结果的数据集不匹配，请重新读取')
    return result
  },
}

export const chunkPresetApi = {
  async list(params?: OpenApiQueryParams<'/api/v1/chunk-presets', 'get'>): Promise<ChunkPresetListResponse> {
    const response = await apiClient.get<unknown>('/chunk-presets', { params })
    return parseApiResponse(response, chunkPresetListSchema, 'ChunkPresetList')
  },

  async create(payload: ChunkPresetCreateRequest): Promise<ChunkPreset> {
    const response = await apiClient.post<unknown>('/chunk-presets', payload)
    return parseApiResponse(response, chunkPresetSchema, 'ChunkPreset')
  },

  async update(presetId: string, payload: ChunkPresetUpdateRequest): Promise<ChunkPreset> {
    const response = await apiClient.put<unknown>(`/chunk-presets/${encodeURIComponent(presetId)}`, payload)
    const preset = parseApiResponse(response, chunkPresetSchema, 'ChunkPreset')
    if (!matchesResourceId(preset.id, presetId)) throw new Error('更新回执的预设不匹配，请先刷新预设列表')
    return preset
  },

  async delete(presetId: string): Promise<void> {
    await apiClient.delete(`/chunk-presets/${encodeURIComponent(presetId)}`)
  },
}
