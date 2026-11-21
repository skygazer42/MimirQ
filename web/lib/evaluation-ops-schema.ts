import { z } from 'zod'

import { dateTimeSchema, integerSchema, recordSchema } from '@/lib/response-schema'

const idSchema = z.string().min(1)
const countSchema = integerSchema.nonnegative()

export const syntheticHardcaseRequestSchema = z.object({
  dataset_id: idSchema,
  case_ids: z.array(idSchema).optional(),
  max_cases: integerSchema.min(1).max(200).optional(),
  hardcases_per_case: integerSchema.min(0).max(20).optional(),
  max_created: integerSchema.min(0).max(5000).optional(),
  mode: z.literal('deterministic').optional(),
  dry_run: z.boolean().optional(),
  tag: z.string().max(64).optional(),
})
export const syntheticHardcaseResponseSchema = z
  .looseObject({
    dataset_id: idSchema,
    base_cases_total: countSchema,
    base_cases_evaluated: countSchema,
    hardcases_generated: countSchema,
    created: countSchema,
    skipped_duplicates: countSchema,
    created_case_ids: z.array(idSchema),
    errors: z.array(recordSchema),
  })
  .refine(
    (receipt) =>
      receipt.created === receipt.created_case_ids.length &&
      new Set(receipt.created_case_ids).size === receipt.created_case_ids.length &&
      receipt.base_cases_evaluated <= receipt.base_cases_total &&
      receipt.created + receipt.skipped_duplicates <= receipt.hardcases_generated,
    '困难样例回执数量或身份不一致，请先读取用例列表确认',
  )

export const regressionPurgeRequestSchema = z
  .object({
    retention_days: integerSchema.min(1).max(3650).optional(),
    max_delete: integerSchema.min(1).max(5000).optional(),
    dry_run: z.boolean().optional(),
    dataset_id: idSchema.optional(),
  })
  .optional()
export const regressionPurgeResponseSchema = z
  .looseObject({
    dry_run: z.boolean(),
    retention_days: integerSchema.positive(),
    cutoff: dateTimeSchema,
    max_delete: integerSchema.positive(),
    dataset_id: idSchema.nullable(),
    eligible_runs: countSchema,
    deleted_runs: countSchema,
    deleted_items: countSchema,
  })
  .refine(
    (receipt) =>
      receipt.deleted_runs <= receipt.max_delete &&
      (!receipt.dry_run || (receipt.deleted_runs === 0 && receipt.deleted_items === 0)),
    '清理回执数量或预演结果不一致，请先读取运行记录确认',
  )

export type SyntheticHardcaseGenerateRequest = z.infer<typeof syntheticHardcaseRequestSchema>
export type SyntheticHardcaseGenerateResponse = z.infer<typeof syntheticHardcaseResponseSchema>
export type RegressionRunPurgeRequest = z.infer<typeof regressionPurgeRequestSchema>
export type RegressionRunPurgeResponse = z.infer<typeof regressionPurgeResponseSchema>
