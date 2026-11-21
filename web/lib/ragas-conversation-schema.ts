import { z } from 'zod'

import { dateTimeSchema, integerSchema, recordSchema } from '@/lib/response-schema'

export const ragasConversationReadinessRequestSchema = z.object({
  conversation_ids: z.array(z.uuid()).min(1).max(200),
})

const ragasConversationReadinessItemSchema = z.looseObject({
  conversation_id: z.uuid(),
  assistant_turns: integerSchema.nonnegative(),
  evaluable_turns: integerSchema.nonnegative(),
  citations_count: integerSchema.nonnegative(),
  is_evaluable: z.boolean(),
})

export const ragasConversationReadinessSchema = z
  .looseObject({
    total: integerSchema.nonnegative(),
    items: z.array(ragasConversationReadinessItemSchema),
  })
  .refine((result) => result.total === result.items.length, '对话评测状态数量不一致，请重新读取')

export const ragasRunCreateSchema = z.object({
  conversation_id: z.uuid(),
  metrics: z.array(z.string()).optional(),
  max_turns: integerSchema.min(1).max(200).optional(),
  skip_empty_contexts: z.boolean().optional(),
  include_contexts_in_response: z.boolean().optional(),
})

export const ragasRunSchema = z.looseObject({
  id: z.uuid(),
  conversation_id: z.uuid().nullable(),
  status: z.string(),
  metrics: z.array(z.string()),
  params: recordSchema,
  summary: recordSchema,
  error_message: z.string().nullable(),
  created_at: dateTimeSchema,
  started_at: dateTimeSchema.nullable(),
  finished_at: dateTimeSchema.nullable(),
})

const ragasItemSchema = z.looseObject({
  id: z.uuid(),
  run_id: z.uuid(),
  turn_index: integerSchema,
  user_message_id: z.uuid().nullable(),
  assistant_message_id: z.uuid().nullable(),
  user_input: z.string(),
  response: z.string(),
  retrieved_contexts: z.array(z.string()).nullable(),
  citations: z.array(recordSchema),
  scores: recordSchema,
  created_at: dateTimeSchema,
})

export const ragasRunListSchema = z.looseObject({
  total: integerSchema.nonnegative(),
  items: z.array(ragasRunSchema),
})

export const ragasRunDetailSchema = z.looseObject({
  run: ragasRunSchema,
  items: z.array(ragasItemSchema),
})

export type RagasConversationReadinessRequest = z.infer<typeof ragasConversationReadinessRequestSchema>
export type RagasConversationReadinessItem = z.infer<typeof ragasConversationReadinessItemSchema>
export type RagasConversationReadinessResponse = z.infer<typeof ragasConversationReadinessSchema>
export type RagasRunCreateRequest = z.infer<typeof ragasRunCreateSchema>
export type RagasRun = z.infer<typeof ragasRunSchema>
export type RagasItem = z.infer<typeof ragasItemSchema>
export type RagasRunList = z.infer<typeof ragasRunListSchema>
export type RagasRunDetail = z.infer<typeof ragasRunDetailSchema>
