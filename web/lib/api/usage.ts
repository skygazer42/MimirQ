import type { OpenApiSchema } from '@/types/backend'
import type { paths } from '@/types/openapi'

import { apiClient } from '@/lib/api/core'

type UsageWindowParams = NonNullable<paths['/api/v1/usage/chat/tokens/summary']['get']['parameters']['query']>
type ChatTokenUsageSummary = OpenApiSchema<'ChatTokenUsageSummary'>
type ChatCostUsageSummary = OpenApiSchema<'ChatCostUsageSummary'>
type ChatTokenQuotaStatus = OpenApiSchema<'ChatTokenQuotaStatus'>
type TenantQuotaSummary = OpenApiSchema<'TenantQuotaSummary'>

export const usageApi = {
  async getChatTokenUsageSummary(params: UsageWindowParams = {}): Promise<ChatTokenUsageSummary> {
    const { data } = await apiClient.get('/usage/chat/tokens/summary', { params })
    return data
  },

  async getChatCostUsageSummary(params: UsageWindowParams = {}): Promise<ChatCostUsageSummary> {
    const { data } = await apiClient.get('/usage/chat/cost/summary', { params })
    return data
  },

  async getChatTokenQuotaStatus(): Promise<ChatTokenQuotaStatus> {
    const { data } = await apiClient.get('/usage/chat/tokens/quota')
    return data
  },

  async getTenantQuotaSummary(): Promise<TenantQuotaSummary> {
    const { data } = await apiClient.get('/usage/tenant/quotas')
    return data
  },
}
