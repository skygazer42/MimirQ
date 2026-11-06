/**
 * Feedback DTO types shared by feedback API and triage consumers.
 */

import type { JsonObject } from './common'

export type FeedbackCategory = 'retrieval_miss' | 'wrong_answer' | 'out_of_scope' | 'other'
export type FeedbackCategorySource = 'user' | 'llm_auto' | 'reviewer'

export type MessageFeedback = {
  id: string
  tenant_id: string
  conversation_id: string
  message_id: string
  account_id: string
  rating: number
  reason?: string
  tags: string[]
  expected_answer?: string
  category?: FeedbackCategory | null
  category_source?: FeedbackCategorySource | null
  query_hash?: string | null
  retrieval_trace_ref?: string | null
  profile?: string | null
  judge_score_ref?: string | null
  extra?: JsonObject
  created_at: string
  updated_at: string
}

export type MessageFeedbackCreate = {
  message_id: string
  rating: number
  reason?: string
  tags?: string[]
  expected_answer?: string
  category?: FeedbackCategory
  extra?: JsonObject
}

export type MessageFeedbackListResponse = {
  total: number
  items: MessageFeedback[]
}

export type MessageFeedbackEnriched = MessageFeedback & {
  conversation_title?: string
  message_content?: string
  message_created_at?: string
}

export type MessageFeedbackEnrichedListResponse = {
  total: number
  items: MessageFeedbackEnriched[]
}

export type FeedbackLoopCandidatesResponse = {
  schema: string
  summary: JsonObject
  hard_negative_records: JsonObject[]
  training_triples: JsonObject[]
  eval_case_candidates: JsonObject[]
  rules_suggestions: JsonObject
}

export type FeedbackLoopHardNegativeExportResponse = {
  schema: string
  trigger: string
  realtime_listener_enabled: boolean
  dry_run: boolean
  candidates: JsonObject
  hard_negative_export: JsonObject
  rules_suggestions: JsonObject
}
