import { z } from 'zod'

import type {
  ChatCostUsageSummary,
  ChatTokenQuotaStatus,
  ChatTokenUsageSummary,
  TenantQuotaSummary,
  UsageWindowParams,
} from '@/types/usage'
import { apiClient, type ApiRequestOptions } from '@/lib/api/core'
import { dateTimeSchema, integerSchema } from '@/lib/response-schema'
import { parseApiResponse } from '@/lib/openapi-request'

const tokenUsageSchema: z.ZodType<ChatTokenUsageSummary> = z.looseObject({
  window_start: dateTimeSchema,
  window_end: dateTimeSchema,
  total_assistant_messages: integerSchema,
  total_assistant_tokens: integerSchema,
  by_dataset: z.array(
    z.looseObject({
      dataset_id: z.string().nullable(),
      assistant_messages: integerSchema,
      assistant_tokens: integerSchema,
    }),
  ),
})
const costUsageSchema: z.ZodType<ChatCostUsageSummary> = z.looseObject({
  window_start: dateTimeSchema,
  window_end: dateTimeSchema,
  total_assistant_messages: integerSchema,
  total_llm_prompt_tokens: integerSchema,
  total_llm_completion_tokens: integerSchema,
  total_llm_total_tokens: integerSchema,
  total_embedding_query_tokens: integerSchema,
  total_embedding_query_chars: integerSchema,
  total_retrieval_elapsed_sec: z.number(),
  total_rerank_elapsed_sec: z.number(),
  by_dataset: z.array(
    z.looseObject({
      dataset_id: z.string().nullable(),
      assistant_messages: integerSchema,
      llm_prompt_tokens: integerSchema,
      llm_completion_tokens: integerSchema,
      llm_total_tokens: integerSchema,
      embedding_query_tokens: integerSchema,
      embedding_query_chars: integerSchema,
      retrieval_elapsed_sec_sum: z.number(),
      rerank_elapsed_sec_sum: z.number(),
    }),
  ),
})
const chatQuotaSchema: z.ZodType<ChatTokenQuotaStatus> = z.looseObject({
  enabled: z.boolean(),
  mode: z.string(),
  limit: integerSchema,
  used: integerSchema,
  remaining: integerSchema,
  exceeded: z.boolean(),
  window_hours: integerSchema,
  window_start: dateTimeSchema,
  window_end: dateTimeSchema,
})
const tenantQuotaSchema: z.ZodType<TenantQuotaSummary> = z.looseObject({
  documents: z.looseObject({
    enabled: z.boolean(),
    limit: integerSchema,
    used: integerSchema,
    remaining: integerSchema,
    exceeded: z.boolean(),
  }),
  storage: z.looseObject({
    enabled: z.boolean(),
    limit_bytes: integerSchema,
    used_bytes: integerSchema,
    remaining_bytes: integerSchema,
    exceeded: z.boolean(),
  }),
  embedding_chars: z.looseObject({
    enabled: z.boolean(),
    mode: z.string(),
    limit_chars: integerSchema,
    used_chars: integerSchema,
    remaining_chars: integerSchema,
    exceeded: z.boolean(),
    window_hours: integerSchema,
    window_start: dateTimeSchema,
    window_end: dateTimeSchema,
  }),
  qps: z.looseObject({
    enabled: z.boolean(),
    mode: z.string(),
    rps: z.number(),
    burst: integerSchema,
    scopes: z.array(z.string()),
  }),
})

export const usageApi = {
  async getChatTokenUsageSummary(
    params?: UsageWindowParams,
    options?: ApiRequestOptions,
  ): Promise<ChatTokenUsageSummary> {
    const response = await apiClient.get<unknown>('/usage/chat/tokens/summary', { params, signal: options?.signal })
    return parseApiResponse(response, tokenUsageSchema, 'ChatTokenUsageSummary')
  },

  async getChatCostUsageSummary(
    params?: UsageWindowParams,
    options?: ApiRequestOptions,
  ): Promise<ChatCostUsageSummary> {
    const response = await apiClient.get<unknown>('/usage/chat/cost/summary', { params, signal: options?.signal })
    return parseApiResponse(response, costUsageSchema, 'ChatCostUsageSummary')
  },

  async getChatTokenQuotaStatus(options?: ApiRequestOptions): Promise<ChatTokenQuotaStatus> {
    const response = await apiClient.get<unknown>('/usage/chat/tokens/quota', { signal: options?.signal })
    return parseApiResponse(response, chatQuotaSchema, 'ChatTokenQuotaStatus')
  },

  async getTenantQuotaSummary(options?: ApiRequestOptions): Promise<TenantQuotaSummary> {
    const response = await apiClient.get<unknown>('/usage/tenant/quotas', { signal: options?.signal })
    return parseApiResponse(response, tenantQuotaSchema, 'TenantQuotaSummary')
  },
}
