import { z } from 'zod'

import { dateTimeSchema, integerSchema, recordSchema } from '@/lib/response-schema'

function referenceTextSchema(maxCharacters: number) {
  return z.string().refine((value) => Array.from(value).length <= maxCharacters, `最多 ${maxCharacters} 个字符`)
}

const referenceSourceRecordSchema = z.looseObject({
  document_id: z.string().min(1),
  chunk_id: z.string().min(1),
  chunk_index: integerSchema.nonnegative().nullish(),
  page_number: integerSchema.positive().nullish(),
  start_char: integerSchema.nonnegative().nullish(),
  end_char: integerSchema.nonnegative().nullish(),
  family_collapse_key: z.string().nullish(),
  hierarchy_family_key: z.string().nullish(),
  doc_pipeline_key: z.string().nullish(),
  pipeline_hash: z.string().nullish(),
  record_identity: recordSchema.nullish(),
  semantic_keys: z.array(z.string()).optional(),
  quote: z.string().nullish(),
  label: z.string().nullish(),
})

export const regressionReferenceSourceSchema = referenceSourceRecordSchema.extend({
  family_collapse_key: referenceTextSchema(200).nullish(),
  hierarchy_family_key: referenceTextSchema(200).nullish(),
  doc_pipeline_key: referenceTextSchema(128).nullish(),
  pipeline_hash: referenceTextSchema(64).nullish(),
  semantic_keys: z.array(referenceTextSchema(200)).max(200).optional(),
  quote: referenceTextSchema(2000).nullish(),
  label: referenceTextSchema(100).nullish(),
})

export const regressionCaseSchema = z.looseObject({
  id: z.string().min(1),
  tenant_id: z.string().min(1),
  dataset_id: z.string().nullable(),
  document_ids: z.array(z.string()),
  question: z.string(),
  expected_answer: z.string().nullable(),
  reference_sources: z.array(referenceSourceRecordSchema),
  tags: z.array(z.string()),
  reasoning_hops: z.array(z.string()),
  evidence_chain: z.array(referenceSourceRecordSchema),
  extra: recordSchema,
  created_by: z.string().nullable(),
  created_at: dateTimeSchema,
  updated_at: dateTimeSchema,
})

export const regressionCaseListSchema = z
  .looseObject({
    total: integerSchema.nonnegative(),
    items: z.array(regressionCaseSchema),
  })
  .refine((page) => page.items.length <= page.total, '返回样本数超过总数，请重新读取')

const regressionCaseBundleItemSchema = z.looseObject({
  question: z.string(),
  expected_answer: z.string().nullable(),
  tags: z.array(z.string()),
  reference_sources: z.array(referenceSourceRecordSchema),
  reasoning_hops: z.array(z.string()).optional(),
  evidence_chain: z.array(referenceSourceRecordSchema).optional(),
  extra: z.record(z.string(), z.json()).optional(),
})

export const regressionCaseBundleSchema = z.looseObject({
  schema: z.literal('mimirq.regression_cases.v1'),
  dataset_id: z.string().min(1),
  items: z.array(regressionCaseBundleItemSchema),
})

const caseImportItemSchema = regressionCaseBundleItemSchema.extend({
  question: z.string().refine((value) => value.trim().length > 0, '样本问题不能为空'),
  expected_answer: z.string().nullish(),
  tags: z.array(z.string()).optional(),
  reference_sources: z.array(regressionReferenceSourceSchema).min(1, '每个导入样本至少需要一个证据引用'),
  reasoning_hops: z
    .array(referenceTextSchema(300).refine((value) => value.trim().length > 0, '推理步骤不能为空'))
    .max(20)
    .optional(),
  evidence_chain: z.array(regressionReferenceSourceSchema).max(20).optional(),
})

export const regressionCaseImportRequestSchema = z.object({
  dataset_id: z.string().min(1, '请选择目标数据集'),
  overwrite: z.boolean().optional(),
  max_items: integerSchema.min(1).max(2000).optional(),
  items: z.array(caseImportItemSchema).min(1, '请提供至少一个导入样本'),
})

export const regressionCaseImportResponseSchema = z
  .looseObject({
    created: integerSchema.nonnegative(),
    updated: integerSchema.nonnegative(),
    skipped: integerSchema.nonnegative(),
    errors: z.array(z.record(z.string(), z.json())),
    created_case_ids: z.array(z.string().min(1)),
    updated_case_ids: z.array(z.string().min(1)),
    skipped_case_ids: z.array(z.string().min(1)),
    case_ids: z.array(z.string().min(1)),
  })
  .refine((receipt) => {
    const acceptedIds = [...receipt.created_case_ids, ...receipt.updated_case_ids, ...receipt.skipped_case_ids]
    return (
      receipt.created === receipt.created_case_ids.length &&
      receipt.updated === receipt.updated_case_ids.length &&
      receipt.skipped >= receipt.skipped_case_ids.length &&
      new Set(acceptedIds).size === acceptedIds.length &&
      receipt.case_ids.length === acceptedIds.length &&
      receipt.case_ids.every((id, index) => id === acceptedIds[index])
    )
  }, '导入回执的数量或样本身份不一致，请先读取样本列表确认')

export type RegressionCase = z.infer<typeof regressionCaseSchema>
export type RegressionCaseList = z.infer<typeof regressionCaseListSchema>
export type RegressionReferenceSource = z.infer<typeof regressionReferenceSourceSchema>
export type RegressionCaseBundleItem = z.infer<typeof regressionCaseBundleItemSchema>
export type RegressionCaseBundleV1 = z.infer<typeof regressionCaseBundleSchema>
export type RegressionCaseImportRequest = z.infer<typeof regressionCaseImportRequestSchema>
export type RegressionCaseImportResponse = z.infer<typeof regressionCaseImportResponseSchema>

export type RegressionCaseWindow = {
  total: number | null
  items: RegressionCase[]
  fullyLoaded: boolean
}
