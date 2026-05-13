import type {
  EvidenceItem,
  MessageFeedback,
  MessageFeedbackCreate,
  MessageFeedbackEnrichedListResponse,
  FeedbackLoopHardNegativeExportResponse,
  FeedbackLoopCandidatesResponse,
  MessageFeedbackListResponse,
  RegressionCase,
} from '@/types'

import { apiClient, type ApiRequestOptions } from '@/lib/api/core'

export const feedbackApi = {
  async create(params: MessageFeedbackCreate): Promise<MessageFeedback> {
    const { data } = await apiClient.post('/feedback/messages', params)
    return data
  },

  async list(params?: {
    skip?: number
    limit?: number
    message_id?: string
  }): Promise<MessageFeedbackListResponse> {
    const { data } = await apiClient.get('/feedback/messages', { params })
    return data
  },

  async listEnriched(params?: {
    skip?: number
    limit?: number
    conversation_id?: string
    message_id?: string
    min_rating?: number
    max_rating?: number
  }, options?: ApiRequestOptions): Promise<MessageFeedbackEnrichedListResponse> {
    const { data } = await apiClient.get('/feedback/messages/enriched', { params, signal: options?.signal })
    return data
  },

  async loopCandidates(params?: {
    max_rating?: number
    limit?: number
    ruleset?: string
  }, options?: ApiRequestOptions): Promise<FeedbackLoopCandidatesResponse> {
    const { data } = await apiClient.get('/feedback/loop/candidates', { params, signal: options?.signal })
    return data
  },

  async exportHardNegatives(params?: {
    max_rating?: number
    limit?: number
    dry_run?: boolean
    append?: boolean
    ruleset?: string
  }, options?: ApiRequestOptions): Promise<FeedbackLoopHardNegativeExportResponse> {
    const { data } = await apiClient.post('/feedback/loop/hard-negatives/export', undefined, {
      params,
      signal: options?.signal,
    })
    return data
  },

  async toRegressionCase(
    feedbackId: string,
    body: { include_document_scope?: boolean; tags?: string[]; extra?: Record<string, any> } = {}
  ): Promise<RegressionCase> {
    const { data } = await apiClient.post(`/feedback/messages/${feedbackId}/to-regression-case`, body)
    return data
  },

  async update(
    feedbackId: string,
    body: { archived?: boolean }
  ): Promise<MessageFeedback> {
    const { data } = await apiClient.patch(`/feedback/messages/${feedbackId}`, body)
    return data
  },

  async toEvidenceItem(
    feedbackId: string,
    body: { suite_id: string; tags?: string[]; extra?: Record<string, any> }
  ): Promise<EvidenceItem> {
    const { data } = await apiClient.post(`/feedback/messages/${feedbackId}/to-evidence-item`, body)
    return data
  },
}
