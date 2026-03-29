import type {
  ChatCostUsageSummary,
  ChatTokenQuotaStatus,
  ChatTokenUsageSummary,
  TenantQuotaSummary,
} from '@/types'

import { apiClient } from '@/lib/api/core'

export const usageApi = {
  async getChatTokenUsageSummary(params: { window_days?: number; since?: string; until?: string } = {}): Promise<ChatTokenUsageSummary> {
    const { data } = await apiClient.get('/usage/chat/tokens/summary', { params })
    return data
  },

  async getChatCostUsageSummary(params: { window_days?: number; since?: string; until?: string } = {}): Promise<ChatCostUsageSummary> {
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
