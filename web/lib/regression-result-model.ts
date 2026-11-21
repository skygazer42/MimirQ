import { z } from 'zod'

import { integerSchema, stringRecordSchema } from '@/lib/response-schema'

const countSchema = integerSchema.nonnegative()
const optionalCountSchema = countSchema.nullable().optional()
const fractionSchema = z.number().min(0).max(1)
const optionalFractionSchema = fractionSchema.nullable().optional()
const sliceCountsSchema = z.looseObject({
  chart: countSchema,
  formula: countSchema,
  table_math: countSchema,
  image: countSchema,
  text: countSchema,
})
const sliceCoverageSchema = z.looseObject({
  chart: fractionSchema,
  formula: fractionSchema,
  table_math: fractionSchema,
  image: fractionSchema,
  text: fractionSchema,
})
const multimodalSlicesSchema = z.looseObject({
  schema: z.literal('mimirq.multimodal_golden_slices.v1'),
  items: countSchema,
  counts: sliceCountsSchema,
  evaluatable: sliceCountsSchema,
  abstained: sliceCountsSchema,
  coverage: sliceCoverageSchema,
})
const qualityBucketSchema = z.looseObject({
  key: z.string(),
  items: countSchema,
  retrieval_recall: optionalFractionSchema,
  retrieval_mrr: optionalFractionSchema,
  retrieval_ndcg_at_10: optionalFractionSchema,
})
const qualityGroupSchema = z.looseObject({ buckets: z.array(qualityBucketSchema), truncated: z.boolean() })
const summarySchema = z.looseObject({
  items: optionalCountSchema,
  total_tokens: optionalCountSchema,
  total_cost: z.number().nonnegative().nullable().optional(),
  retrieval_recall: optionalFractionSchema,
  retrieval_mrr: optionalFractionSchema,
  retrieval_ndcg_at_10: optionalFractionSchema,
  expected_metadata_hit_rate: optionalFractionSchema,
  expected_metadata_recall: optionalFractionSchema,
  expected_metadata_cases_total: optionalCountSchema,
  expected_metadata_fields_total: optionalCountSchema,
  expected_metadata_fields_matched: optionalCountSchema,
  multimodal_slices: multimodalSlicesSchema.optional(),
  retrieval_slices: z
    .looseObject({
      parse_quality: qualityGroupSchema.optional(),
      chunk_quality: qualityGroupSchema.optional(),
    })
    .optional(),
})

const judgePartSchema = z.looseObject({
  score: optionalFractionSchema,
  reason: z.string().nullable().optional(),
  evidence_quotes: z.array(z.string()).optional(),
})
export const regressionItemMetadataSchema = z.looseObject({
  expected_metadata_hit: z.boolean().nullable().optional(),
  expected_metadata_recall: optionalFractionSchema,
  expected_metadata_fields_matched: optionalCountSchema,
  expected_metadata_fields_total: optionalCountSchema,
  expected_metadata_missing_keys: z.array(z.string()).optional(),
  explanations: stringRecordSchema.nullable().optional(),
  llm_judge: z
    .looseObject({
      enabled: z.boolean(),
      overall_score: optionalFractionSchema,
      model_used: z.string().nullable().optional(),
      retrieval: judgePartSchema.nullable().optional(),
      generation: judgePartSchema.nullable().optional(),
    })
    .nullable()
    .optional(),
})

const MULTIMODAL_SLICES = [
  { key: 'chart', label: 'Chart' },
  { key: 'formula', label: 'Formula' },
  { key: 'table_math', label: 'Table-Math' },
  { key: 'image', label: 'Image' },
  { key: 'text', label: 'Text' },
] as const

export function formatRegressionMetric(value: number | null | undefined): string {
  return value == null ? '未提供' : value.toFixed(3)
}

export function formatRegressionCount(value: number | null | undefined): string {
  return value == null ? '未提供' : String(value)
}

export function formatRegressionValue(value: unknown): string {
  if (value == null) return '未提供'
  if (typeof value === 'string') return value
  if (typeof value === 'number') return Number.isFinite(value) ? String(value) : '无效数值'
  const text = JSON.stringify(value)
  return text === undefined ? '无效值' : text
}

const INLINE_SUMMARY_KEYS = new Set([
  'items',
  'total_tokens',
  'total_cost',
  'expected_metadata_hit_rate',
  'expected_metadata_recall',
  'expected_metadata_cases_total',
  'expected_metadata_fields_total',
  'expected_metadata_fields_matched',
])

export function buildRegressionSummaryModel(raw: Readonly<Record<string, unknown>>) {
  const parsed = summarySchema.safeParse(raw)
  if (!parsed.success) return { status: 'invalid', message: '运行统计字段格式不正确，原始结果已保留。' } as const
  const summary = parsed.data
  const metrics = Object.entries(raw).flatMap(([key, value]) =>
    !INLINE_SUMMARY_KEYS.has(key) && typeof value === 'number' && Number.isFinite(value) ? [{ key, value }] : [],
  )
  const multimodal = summary.multimodal_slices
  const slices =
    multimodal === undefined
      ? []
      : MULTIMODAL_SLICES.map((slice) => ({
          ...slice,
          count: multimodal.counts[slice.key],
          evaluatable: multimodal.evaluatable[slice.key],
          coverage: multimodal.coverage[slice.key],
        })).filter((slice) => slice.count > 0 || slice.evaluatable > 0 || slice.coverage > 0)
  const textOnlyFullCoverage =
    slices.length === 1 &&
    slices[0].key === 'text' &&
    slices[0].count > 0 &&
    slices[0].evaluatable === slices[0].count &&
    slices[0].coverage === 1
  let sliceSummary = '未提供非零切片记录'
  if (slices.length === 1) {
    const [slice] = slices
    sliceSummary = `${slice.label} ${slice.evaluatable}/${slice.count}`
  } else if (slices.length > 1) {
    const lowestCoverage = Math.min(...slices.map((slice) => slice.coverage))
    sliceSummary = `${slices.length} 类 · 最低 ${(lowestCoverage * 100).toFixed(2)}%`
  }
  const qualityGroups = [
    { title: 'parse_quality → retrieval', group: summary.retrieval_slices?.parse_quality },
    { title: 'chunk_quality → retrieval', group: summary.retrieval_slices?.chunk_quality },
  ].flatMap(({ title, group }) => (group === undefined ? [] : [{ title, ...group }]))
  const hasExpectedMetadata = [
    summary.expected_metadata_hit_rate,
    summary.expected_metadata_recall,
    summary.expected_metadata_cases_total,
    summary.expected_metadata_fields_total,
    summary.expected_metadata_fields_matched,
  ].some((value) => value != null)
  return {
    status: 'ready',
    summary,
    metrics,
    slices,
    sliceSummary,
    textOnlyFullCoverage,
    qualityGroups,
    hasExpectedMetadata,
    hasSummary: Object.keys(raw).length > 0,
  } as const
}
