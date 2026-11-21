import { z } from 'zod'

import type { EvidenceItem } from '@/types/backend'
import type {
  FeedbackCategory,
  FeedbackLoopCandidatesResponse,
  MessageFeedback,
  MessageFeedbackCreate,
  MessageFeedbackEnrichedListResponse,
} from '@/types/feedback'

import { apiClient, type ApiRequestOptions } from '@/lib/api/core'
import { dateTimeSchema, recordSchema } from '@/lib/response-schema'
import { parseApiResponse } from '@/lib/openapi-request'

const feedbackSchema = z.looseObject({
  id: z.string().min(1),
  tenant_id: z.string(),
  conversation_id: z.string().min(1),
  message_id: z.string().min(1),
  account_id: z.string(),
  rating: z.number().int(),
  reason: z.string().nullable(),
  tags: z.array(z.string()),
  expected_answer: z.string().nullable(),
  category: z.enum(['retrieval_miss', 'wrong_answer', 'out_of_scope', 'other']).nullable(),
  category_source: z.enum(['user', 'llm_auto', 'reviewer']).nullable(),
  query_hash: z.string().nullable(),
  retrieval_trace_ref: z.string().nullable(),
  profile: z.string().nullable(),
  judge_score_ref: z.string().nullable(),
  extra: recordSchema,
  created_at: dateTimeSchema,
  updated_at: dateTimeSchema,
})
const enrichedFeedbackSchema = feedbackSchema.extend({
  conversation_title: z.string().nullable(),
  message_content: z.string().nullable(),
  message_created_at: dateTimeSchema.nullable(),
})
const enrichedFeedbackListSchema = z.looseObject({
  total: z.number().int().nonnegative(),
  items: z.array(enrichedFeedbackSchema),
})
const feedbackCandidatesSchema: z.ZodType<FeedbackLoopCandidatesResponse> = z.looseObject({
  schema: z.string(),
  summary: z.looseObject({
    feedback_total: z.number().int().nonnegative(),
    negative_feedback_total: z.number().int().nonnegative(),
    hard_negative_records: z.number().int().nonnegative(),
    training_triples: z.number().int().nonnegative(),
    eval_case_candidates: z.number().int().nonnegative(),
    rules_glossary_candidates: z.number().int().nonnegative(),
    rules_pattern_candidates: z.number().int().nonnegative(),
    rules_intent_candidates: z.number().int().nonnegative(),
  }),
  hard_negative_records: z.array(recordSchema),
  training_triples: z.array(recordSchema),
  eval_case_candidates: z.array(recordSchema),
  rules_suggestions: z.looseObject({
    schema: z.string(),
    ruleset: z.string().nullable(),
    glossary_suggestions: z.array(recordSchema),
    pattern_suggestions: z.array(recordSchema),
    intent_suggestions: z.array(recordSchema),
  }),
})
const createdCaseSchema = z.looseObject({ id: z.string().min(1) })
const referenceSourceSchema = z.looseObject({
  document_id: z.string(),
  chunk_id: z.string(),
  chunk_index: z.number().int().nonnegative().nullable(),
  family_collapse_key: z.string().nullable(),
  hierarchy_family_key: z.string().nullable(),
  page_number: z.number().int().positive().nullable(),
  start_char: z.number().int().nonnegative().nullable(),
  end_char: z.number().int().nonnegative().nullable(),
  doc_pipeline_key: z.string().nullable(),
  pipeline_hash: z.string().nullable(),
  record_identity: recordSchema.nullable(),
  semantic_keys: z.array(z.string()),
  quote: z.string().nullable(),
  label: z.string().nullable(),
})
const evidenceItemSchema: z.ZodType<EvidenceItem> = z.looseObject({
  id: z.string().min(1),
  tenant_id: z.string(),
  dataset_id: z.string(),
  suite_id: z.string(),
  status: z.enum(['draft', 'reviewed', 'approved', 'archived']),
  query: z.string(),
  expected_answer: z.string().nullable(),
  tags: z.array(z.string()),
  source_metadata: recordSchema,
  reference_sources: z.array(referenceSourceSchema),
  retrieval_snapshot: recordSchema,
  rag_config_snapshot: recordSchema,
  notes: z.string().nullable(),
  regression_case_id: z.string().nullable(),
  created_by: z.string().nullable(),
  reviewed_by: z.string().nullable(),
  approved_by: z.string().nullable(),
  archived_by: z.string().nullable(),
  reviewed_at: dateTimeSchema.nullable(),
  approved_at: dateTimeSchema.nullable(),
  archived_at: dateTimeSchema.nullable(),
  created_at: dateTimeSchema,
  updated_at: dateTimeSchema,
})

export const feedbackApi = {
  async create(params: MessageFeedbackCreate): Promise<MessageFeedback> {
    const response = await apiClient.post<unknown>('/feedback/messages', params)
    return parseApiResponse(response, feedbackSchema, 'MessageFeedback')
  },

  async listEnriched(
    params?: {
      skip?: number
      limit?: number
      conversation_id?: string
      message_id?: string
      min_rating?: number
      max_rating?: number
    },
    options?: ApiRequestOptions,
  ): Promise<MessageFeedbackEnrichedListResponse> {
    const response = await apiClient.get<unknown>('/feedback/messages/enriched', { params, signal: options?.signal })
    return parseApiResponse(response, enrichedFeedbackListSchema, 'EnrichedFeedbackList')
  },

  async loopCandidates(
    params?: {
      max_rating?: number
      limit?: number
      ruleset?: string
    },
    options?: ApiRequestOptions,
  ): Promise<FeedbackLoopCandidatesResponse> {
    const response = await apiClient.get<unknown>('/feedback/loop/candidates', { params, signal: options?.signal })
    return parseApiResponse(response, feedbackCandidatesSchema, 'FeedbackLoopCandidates')
  },

  async toRegressionCase(
    feedbackId: string,
    body: { include_document_scope?: boolean; tags?: string[]; extra?: Record<string, unknown> } = {},
  ): Promise<{ id: string }> {
    const response = await apiClient.post<unknown>(
      `/feedback/messages/${encodeURIComponent(feedbackId)}/to-regression-case`,
      body,
    )
    return parseApiResponse(response, createdCaseSchema, 'FeedbackRegressionCase')
  },

  async update(
    feedbackId: string,
    body: { archived?: boolean; category?: FeedbackCategory },
  ): Promise<MessageFeedback> {
    const response = await apiClient.patch<unknown>(`/feedback/messages/${encodeURIComponent(feedbackId)}`, body)
    return parseApiResponse(response, feedbackSchema, 'MessageFeedback')
  },

  async toEvidenceItem(
    feedbackId: string,
    body: { suite_id: string; tags?: string[]; extra?: Record<string, unknown> },
  ): Promise<EvidenceItem> {
    const response = await apiClient.post<unknown>(
      `/feedback/messages/${encodeURIComponent(feedbackId)}/to-evidence-item`,
      body,
    )
    return parseApiResponse(response, evidenceItemSchema, 'FeedbackEvidenceItem')
  },
}
