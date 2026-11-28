import { z } from 'zod'

import { dateTimeSchema, integerSchema, recordSchema } from '@/lib/response-schema'
import { RERANKER_PROVIDER_OPTIONS } from '@/lib/reranker-provider-options'
import { boundedNumberDraft } from '@/lib/number-draft-schema'

export const regressionRunSchema = z.looseObject({
  id: z.string().min(1),
  tenant_id: z.string().min(1),
  account_id: z.string().nullable(),
  dataset_id: z.string().nullable(),
  status: z.string(),
  metrics: z.array(z.string()),
  params: recordSchema,
  summary: recordSchema,
  error_message: z.string().nullable(),
  created_at: dateTimeSchema,
  started_at: dateTimeSchema.nullable(),
  finished_at: dateTimeSchema.nullable(),
})

const regressionItemSchema = z.looseObject({
  id: z.string().min(1),
  run_id: z.string().min(1),
  case_id: z.string().min(1),
  question: z.string(),
  response: z.string(),
  retrieved_contexts: z.array(z.string()).nullable(),
  citations: z.array(recordSchema),
  scores: recordSchema,
  meta: recordSchema,
  created_at: dateTimeSchema,
})

export const regressionRunListSchema = z.looseObject({
  total: integerSchema.nonnegative(),
  items: z.array(regressionRunSchema),
})

export const regressionRunLeaderboardSchema = z
  .looseObject({
    metric_key: z.string().min(1),
    items: z.array(
      z.looseObject({
        run_id: z.string().min(1),
        status: z.string(),
        created_at: dateTimeSchema.nullish(),
        finished_at: dateTimeSchema.nullish(),
        metric_key: z.string().min(1),
        metric_value: z.number().nullish(),
        retrieval_config_hash: z.string().nullish(),
      }),
    ),
  })
  .refine(
    (board) =>
      new Set(board.items.map((item) => item.run_id)).size === board.items.length &&
      board.items.every((item) => item.metric_key === board.metric_key),
    '运行排行的身份或指标不一致，请重新读取',
  )

export const regressionRunDetailSchema = z.looseObject({
  run: regressionRunSchema,
  items: z.array(regressionItemSchema),
})

export const regressionAblationBatchSchema = z
  .looseObject({
    ablation_id: z.string().min(1),
    total: integerSchema.positive(),
    run_ids: z.array(z.string().min(1)).min(1),
    variants: z.array(recordSchema).min(1),
    status: z.literal('queued'),
  })
  .refine(
    (batch) =>
      batch.total === batch.run_ids.length &&
      batch.total === batch.variants.length &&
      new Set(batch.run_ids).size === batch.total,
    '消融批次回执数量或运行身份不一致，请先读取运行记录确认',
  )

export const regressionRunAblationParamsSchema = z.looseObject({
  top_k: integerSchema.min(1).max(50).nullish(),
  enable_reranker: z.boolean().nullish(),
  retrieval_mode: z.string().nullish(),
})

const ablationFormBaseSchema = z.object({
  datasetId: z.string().min(1, '请选择数据集'),
  retrievalOnly: z.boolean(),
  metricKeys: z.array(z.string()),
  skipEmptyContexts: z.boolean(),
  maxCases: boundedNumberDraft('样本上限', 1, 500).refine(Number.isInteger, '样本上限必须是整数'),
  topK: boundedNumberDraft('召回数量', 1, 50).refine(Number.isInteger, '召回数量必须是整数'),
  scoreThreshold: boundedNumberDraft('分数阈值', 0, 1),
  retrievalMode: z.enum(['hybrid', 'vector', 'keyword', 'mmr']),
  alpha: boundedNumberDraft('混合权重', 0, 1),
  enableWeightRerank: z.boolean(),
  vectorWeight: boundedNumberDraft('向量权重', 0, 1),
  keywordWeight: boundedNumberDraft('关键词权重', 0, 1),
  mmrLambda: boundedNumberDraft('多样性系数', 0, 1),
})

export const regressionAblationFormSchema = z
  .discriminatedUnion('rerankerMode', [
    ablationFormBaseSchema.extend({ rerankerMode: z.literal('system') }),
    ablationFormBaseSchema.extend({ rerankerMode: z.literal('disabled') }),
    ablationFormBaseSchema.extend({
      rerankerMode: z.literal('enabled'),
      rerankerProvider: z.enum(
        RERANKER_PROVIDER_OPTIONS.filter((option) => option.key !== 'none').map((option) => option.key),
        { error: '请选择可用的重排服务' },
      ),
      rerankerTopN: boundedNumberDraft('重排数量', 1, 200).refine(Number.isInteger, '重排数量必须是整数'),
    }),
  ])
  .refine((config) => config.retrievalOnly || config.metricKeys.length > 0, {
    message: '请至少选择一项生成质量指标',
    path: ['metricKeys'],
  })

export type RegressionRun = z.infer<typeof regressionRunSchema>
export type RegressionRunList = z.infer<typeof regressionRunListSchema>
export type RegressionRunLeaderboard = z.infer<typeof regressionRunLeaderboardSchema>
export type RegressionItem = z.infer<typeof regressionItemSchema>
export type RegressionRunDetail = z.infer<typeof regressionRunDetailSchema>
export type RegressionAblationBatchResponse = z.infer<typeof regressionAblationBatchSchema>
export type RegressionRunAblationParams = z.infer<typeof regressionRunAblationParamsSchema>
