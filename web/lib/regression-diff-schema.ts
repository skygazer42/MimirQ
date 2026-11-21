import { z } from 'zod'

import { dateTimeSchema, integerSchema } from '@/lib/response-schema'

const jsonRecordSchema = z.record(z.string(), z.json())

const regressionRunMetricDiffSchema = z.looseObject({
  key: z.string(),
  before: z.json().optional(),
  after: z.json().optional(),
  delta: z.number().nullable(),
})

const regressionRunDiffScoreSchema = z.looseObject({
  version: z.string(),
  used_metric_keys: z.array(z.string()),
  weights: z.record(z.string(), z.number()),
  base_score: z.number().nullable(),
  target_score: z.number().nullable(),
  delta: z.number().nullable(),
  base_metrics: z.record(z.string(), z.number()),
  target_metrics: z.record(z.string(), z.number()),
})

const regressionRunSliceBucketDiffSchema = z.looseObject({
  key: z.string(),
  items_before: integerSchema.nonnegative(),
  items_after: integerSchema.nonnegative(),
  metrics: z.array(regressionRunMetricDiffSchema),
})

const regressionRunSliceDiffSchema = z.looseObject({
  truncated_before: z.boolean(),
  truncated_after: z.boolean(),
  buckets: z.array(regressionRunSliceBucketDiffSchema),
})

const caseMetricDiffSchema = regressionRunMetricDiffSchema.extend({
  before: z.number(),
  after: z.number(),
  delta: z.number(),
})

const regressionRunCaseDiffSchema = z.looseObject({
  case_id: z.string(),
  question: z.string(),
  metric_diffs: z.array(caseMetricDiffSchema),
  mean_delta: z.number().nullable(),
  label: z.string(),
})

const probabilitySchema = z.number().min(0).max(1).nullable()

const significanceSummarySchema = z
  .object({
    paired_cases: integerSchema.nonnegative().optional(),
    metrics_compared: integerSchema.nonnegative().optional(),
    bh_corrected: z.boolean().optional(),
  })
  .catchall(z.json())

const regressionRunMetricSignificanceSchema = z.looseObject({
  key: z.string(),
  compared: integerSchema.nonnegative(),
  base_mean: z.number().nullable(),
  target_mean: z.number().nullable(),
  delta_mean: z.number().nullable(),
  bootstrap_ci_low: z.number().nullable(),
  bootstrap_ci_high: z.number().nullable(),
  p_value: probabilitySchema,
  p_value_method: z.string().nullable(),
  p_value_bh: probabilitySchema,
  wilcoxon_p_value: probabilitySchema,
  mcnemar_p_value: probabilitySchema,
  cohen_d: z.number().nullable(),
  significant: z.boolean(),
})

export const regressionRunDiffSchema = z
  .looseObject({
    base_run_id: z.string().min(1),
    target_run_id: z.string().min(1),
    generated_at: dateTimeSchema,
    base_params: jsonRecordSchema,
    target_params: jsonRecordSchema,
    metric_diffs: z.array(regressionRunMetricDiffSchema),
    diff_score: regressionRunDiffScoreSchema.nullable(),
    slice_diffs: z.record(z.string(), regressionRunSliceDiffSchema),
    significance: z.array(regressionRunMetricSignificanceSchema),
    case_diffs: z.array(regressionRunCaseDiffSchema),
    significance_summary: significanceSummarySchema,
  })
  .refine(
    (diff) =>
      diff.significance_summary.paired_cases === undefined ||
      diff.case_diffs.length <= diff.significance_summary.paired_cases,
    '返回的配对样本数超过统计总数，请重新读取',
  )

export type RegressionRunMetricDiff = z.infer<typeof regressionRunMetricDiffSchema>
export type RegressionRunDiffScore = z.infer<typeof regressionRunDiffScoreSchema>
export type RegressionRunSliceBucketDiff = z.infer<typeof regressionRunSliceBucketDiffSchema>
export type RegressionRunSliceDiff = z.infer<typeof regressionRunSliceDiffSchema>
export type RegressionRunCaseDiff = z.infer<typeof regressionRunCaseDiffSchema>
export type RegressionRunMetricSignificance = z.infer<typeof regressionRunMetricSignificanceSchema>
export type RagasRegressionRunDiffResponse = z.infer<typeof regressionRunDiffSchema>
