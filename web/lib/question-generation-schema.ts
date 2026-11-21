import { z } from 'zod'

import { integerSchema } from '@/lib/response-schema'

export const QUESTION_TYPE_OPTIONS = [
  { key: 'factual', label: '事实型', description: '询问具体信息' },
  { key: 'multi_hop', label: '多跳 / 推理', description: '组合多条信息推理' },
  { key: 'comparison', label: '对比型', description: '比较不同概念' },
  { key: 'conditional', label: '条件型', description: '判断条件变化的影响' },
  { key: 'unanswerable', label: '不可答 / 拒答', description: '识别文档无法回答的问题' },
] as const

const questionTypeSchema = z.enum(QUESTION_TYPE_OPTIONS.map((option) => option.key))
const identifierSchema = z.string().min(1)

export const documentQuestionRequestSchema = z
  .object({
    dataset_id: identifierSchema.nullish(),
    document_ids: z.array(identifierSchema).optional(),
    num_questions: integerSchema.min(1).max(50).optional(),
    question_types: z
      .array(z.union([questionTypeSchema, z.literal('reasoning')]))
      .min(1)
      .optional(),
    auto_save_as_cases: z.boolean().optional(),
    prompt_template_id: identifierSchema.nullish(),
    prompt_template_key: identifierSchema.nullish(),
    prompt_ab_experiment_key: identifierSchema.nullish(),
  })
  .refine(
    (request) => (request.document_ids !== undefined && request.document_ids.length > 0) || request.dataset_id != null,
    '请选择数据集或至少一个文档',
  )

export const conversationQuestionRequestSchema = z.object({
  conversation_ids: z.array(identifierSchema).min(1, '请至少选择一个对话'),
  num_questions: integerSchema.min(1).max(50).optional(),
  quality_threshold: z.number().min(0).max(1).optional(),
  auto_save_as_cases: z.boolean().optional(),
})

const autoSaveSchema = z.discriminatedUnion('saved', [
  z.looseObject({ saved: z.literal(true), case_id: identifierSchema }),
  z.looseObject({ saved: z.literal(false), reason: z.string() }),
])

const generatedQuestionSchema = z.looseObject({
  question: z.string(),
  expected_answer: z.string().nullable(),
  context: z.string().nullable(),
  source_type: z.enum(['document', 'conversation']),
  source_id: identifierSchema.nullable(),
  metadata: z.looseObject({
    question_type: questionTypeSchema.optional(),
    auto_save: autoSaveSchema.optional(),
  }),
})

const generationResponseBaseSchema = z.looseObject({
  generated_questions: z.array(generatedQuestionSchema),
  saved_case_ids: z.array(identifierSchema),
})

export const questionGenerationResponseSchema = z
  .discriminatedUnion('status', [
    generationResponseBaseSchema.extend({ status: z.literal('completed'), error_message: z.string().nullable() }),
    generationResponseBaseSchema.extend({ status: z.literal('failed'), error_message: z.string() }),
  ])
  .refine(
    (response) =>
      response.saved_case_ids.length <= response.generated_questions.length &&
      new Set(response.saved_case_ids).size === response.saved_case_ids.length,
    '保存回执数量或用例身份不一致，请先重新读取用例列表确认',
  )

export const questionDocumentPageSchema = z
  .looseObject({
    total: integerSchema.nonnegative(),
    items: z.array(
      z.looseObject({
        id: identifierSchema,
        filename: z.string(),
        dataset_id: identifierSchema.nullish(),
        chunk_count: integerSchema.nonnegative().nullish(),
      }),
    ),
  })
  .refine(
    (page) => page.items.length <= page.total && new Set(page.items.map((item) => item.id)).size === page.items.length,
    '文档页数量或身份不一致，请重新读取',
  )

export type QuestionType = z.infer<typeof questionTypeSchema>
export type GeneratedQuestion = z.infer<typeof generatedQuestionSchema>
export type TestGenFromDocsRequest = z.infer<typeof documentQuestionRequestSchema>
export type TestGenFromConversationsRequest = z.infer<typeof conversationQuestionRequestSchema>
export type TestGenResponse = z.infer<typeof questionGenerationResponseSchema>
