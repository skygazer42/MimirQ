import { z } from 'zod'

import { apiClient, openapiRequest, type ApiRequestOptions } from '@/lib/api/core'
import { parseApiResponse } from '@/lib/openapi-request'
import { recordSchema } from '@/lib/response-schema'
import type {
  SettingsUpdateResponse,
  SystemSettings,
  SystemStatus,
  TestLLMRequest,
  TestLLMResponse,
  UpdateSettingsRequest,
} from '@/types/settings'

const connectionStatusSchema = z.object({
  connected: z.boolean(),
  message: z.string(),
})

const modelStatusSchema = z.object({
  configured: z.boolean(),
  model: z.string(),
})

const systemStatusSchema = z.object({
  database: connectionStatusSchema,
  milvus: connectionStatusSchema,
  llm: modelStatusSchema,
  embedding: modelStatusSchema,
  parsers: z.record(
    z.string(),
    z.object({
      enabled: z.boolean(),
      available: z.boolean(),
      message: z.string(),
      health: recordSchema.nullish(),
    }),
  ),
}) satisfies z.ZodType<SystemStatus>

const settingsUpdateSchema = z.object({
  success: z.boolean(),
  message: z.string(),
  updated_keys: z.array(z.string()),
}) satisfies z.ZodType<SettingsUpdateResponse>

const llmTestSchema = z.object({
  success: z.boolean(),
  message: z.string(),
}) satisfies z.ZodType<TestLLMResponse>

export type {
  CacheConfig,
  ChatConfig,
  DifyExternalKnowledgeConfig,
  DoclingConfig,
  EmbeddingConfig,
  Etl4LlmConfig,
  FeatureFlags,
  GovernanceConfig,
  KGConfig,
  LangGraphConfig,
  LLMConfig,
  MagicPDFConfig,
  MarkerConfig,
  MilvusConfig,
  MinIOConfig,
  MinerUConfig,
  NavigationConfig,
  ObservabilityConfig,
  PaddleVLConfig,
  ParserBackendStatus,
  RAGConfig,
  SafetyConfig,
  SettingsUpdateResponse,
  SystemSettings,
  SystemStatus,
  TestLLMRequest,
  TestLLMResponse,
  TextInConfig,
  UpdateSettingsRequest,
  UrlIngestStatus,
} from '@/types/settings'

export const settingsApi = {
  get(options?: ApiRequestOptions): Promise<SystemSettings> {
    return openapiRequest({ path: '/api/v1/settings', method: 'get', signal: options?.signal })
  },

  update(settings: UpdateSettingsRequest): Promise<SettingsUpdateResponse> {
    return openapiRequest({
      path: '/api/v1/settings',
      method: 'put',
      body: settings,
      responseSchema: settingsUpdateSchema,
      responseSchemaName: 'UpdateSettingsResponse',
    })
  },

  getStatus(options?: ApiRequestOptions): Promise<SystemStatus> {
    return openapiRequest({
      path: '/api/v1/settings/status',
      method: 'get',
      signal: options?.signal,
      responseSchema: systemStatusSchema,
      responseSchemaName: 'SystemStatusResponse',
    })
  },

  async testLLM(params: TestLLMRequest, options?: ApiRequestOptions): Promise<TestLLMResponse> {
    const response = await apiClient.post<unknown>('/settings/llm/test', params, { signal: options?.signal })
    return parseApiResponse(response, llmTestSchema, 'TestLLMResponse')
  },
}
