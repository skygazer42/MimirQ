/**
 * Feedback DTO types shared by feedback API and triage consumers.
 */

import type { OpenApiSchema } from './backend'

export type MessageFeedback = Required<OpenApiSchema<'MessageFeedbackOut'>>
export type FeedbackCategory = NonNullable<MessageFeedback['category']>
export type FeedbackCategorySource = NonNullable<MessageFeedback['category_source']>
export type MessageFeedbackCreate = OpenApiSchema<'MessageFeedbackCreateRequest'>
export type MessageFeedbackEnriched = Required<OpenApiSchema<'MessageFeedbackEnrichedOut'>>

export type MessageFeedbackEnrichedListResponse = Omit<OpenApiSchema<'MessageFeedbackEnrichedList'>, 'items'> & {
  items: MessageFeedbackEnriched[]
}

export type FeedbackLoopCandidatesResponse = OpenApiSchema<'FeedbackLoopCandidatesResponse'>
