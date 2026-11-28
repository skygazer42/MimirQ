import { z } from 'zod'

import { dateTimeSchema, integerSchema, recordSchema } from '@/lib/response-schema'
import { boundedNumberDraft } from '@/lib/number-draft-schema'

const idSchema = z.string().min(1)
const countSchema = integerSchema.nonnegative()
const fractionSchema = z.number().min(0).max(1)
const kgHardcaseModeSchema = z.enum(['off', 'deterministic', 'llm'])

export const kgDiagnosticsRequestSchema = z.object({
  dataset_id: idSchema,
  case_ids: z.array(idSchema).optional(),
  max_cases: integerSchema.min(1).max(200).optional(),
  k: integerSchema.min(1).max(50).optional(),
  auto_extract_kg: z.boolean().optional(),
  extract_skills: z.boolean().nullish(),
  extract_relations: z.boolean().nullish(),
  hardcase_mode: kgHardcaseModeSchema.optional(),
  hardcases_per_failed_case: integerSchema.min(0).max(20).optional(),
  max_failed_cases_for_hardcase: integerSchema.min(0).max(200).optional(),
  llm_temperature: z.number().min(0).max(2).optional(),
  persist_run: z.boolean().optional(),
})

export const kgDiagnosticsFormSchema = z.object({
  datasetId: idSchema,
  maxCases: boundedNumberDraft('评测样本数', 1, 200).refine(Number.isInteger, '评测样本数必须是整数'),
  k: boundedNumberDraft('TOP-K', 1, 50).refine(Number.isInteger, 'TOP-K必须是整数'),
  autoExtractKg: z.boolean(),
  extractSkills: z.enum(['auto', 'on', 'off']),
  extractRelations: z.enum(['auto', 'on', 'off']),
  hardcaseMode: kgHardcaseModeSchema,
  hardcasesPerFailed: boundedNumberDraft('每条难例数', 0, 20).refine(Number.isInteger, '每条难例数必须是整数'),
  maxFailedForHardcase: boundedNumberDraft('难例种子上限', 0, 200).refine(Number.isInteger, '难例种子上限必须是整数'),
  llmTemperature: boundedNumberDraft('模型温度', 0, 2),
  persistRun: z.boolean(),
})

const kgSearchMetricsSchema = z.looseObject({
  hit_at_k: z.boolean(),
  mrr: fractionSchema,
  recall: fractionSchema,
  ndcg: fractionSchema,
  map: fractionSchema,
  matched_evidence_chunks: countSchema,
  total_evidence_chunks: countSchema,
  k: integerSchema.positive(),
})

const searchRunSchema = z.looseObject({
  query: z.string(),
  events: z.array(
    z.looseObject({
      id: z.string(),
      title: z.string(),
      summary: z.string(),
      content: z.string(),
      document_id: z.string().nullable(),
      chunk_id: z.string().nullable(),
      score: z.number(),
    }),
  ),
  entities: z.array(z.looseObject({ entity_id: z.string(), name: z.string(), type: z.string(), weight: z.number() })),
  clues: z.array(recordSchema),
  stats: recordSchema,
  metrics: kgSearchMetricsSchema,
  error: z.string().nullable(),
})
const attributionSchema = z.looseObject({ primary_cause: z.string(), signals: recordSchema })
const hardcaseKindSchema = z.enum(['knowledge_pressure', 'reasoning_pressure'])
const kgDiagnosticsItemSchema = z.looseObject({
  case_id: idSchema,
  question: z.string(),
  tags: z.array(z.string()),
  evidence_chunk_ids: z.array(z.string()),
  ground_truth_event_ids: z.array(z.string()),
  baseline: searchRunSchema,
  hardcases: z.array(
    z.looseObject({
      kind: hardcaseKindSchema,
      question: z.string(),
      rationale: z.string().nullable(),
      run: searchRunSchema.nullable(),
    }),
  ),
  attribution: attributionSchema,
})
const kgDiagnosticsSummarySchema = z.looseObject({
  dataset_id: idSchema,
  cases_total: countSchema,
  cases_evaluated: countSchema,
  hardcases_generated: countSchema,
  baseline_hit_rate: fractionSchema.nullable(),
  baseline_mrr: fractionSchema.nullable(),
  baseline_recall: fractionSchema.nullable(),
  baseline_ndcg: fractionSchema.nullable(),
  baseline_map: fractionSchema.nullable(),
  baseline_valid_searches: countSchema,
  baseline_search_errors: countSchema,
  hardcase_hit_rate: fractionSchema.nullable(),
  hardcase_mrr: fractionSchema.nullable(),
  hardcase_recall: fractionSchema.nullable(),
  hardcase_ndcg: fractionSchema.nullable(),
  hardcase_map: fractionSchema.nullable(),
  hardcase_valid_searches: countSchema,
  hardcase_search_errors: countSchema,
  failure_breakdown: z.record(z.string(), countSchema),
  preflight: recordSchema,
})
export const kgDiagnosticsResponseSchema = z
  .looseObject({
    run_id: idSchema.nullable(),
    summary: kgDiagnosticsSummarySchema,
    items: z.array(kgDiagnosticsItemSchema),
  })
  .refine(
    (report) =>
      report.items.length === report.summary.cases_evaluated &&
      report.summary.cases_evaluated <= report.summary.cases_total &&
      new Set(report.items.map((item) => item.case_id)).size === report.items.length,
    '诊断回执的数量或样本身份不一致，请重新读取记录确认',
  )

const storedMetricsSchema = kgSearchMetricsSchema.extend({
  ndcg: z.number().nonnegative().optional(),
  map: z.number().nonnegative().optional(),
})
const storedSummarySchema = kgDiagnosticsSummarySchema
  .extend({
    baseline_ndcg: z.number().nonnegative().nullable(),
    baseline_map: z.number().nonnegative().nullable(),
    hardcase_ndcg: z.number().nonnegative().nullable(),
    hardcase_map: z.number().nonnegative().nullable(),
  })
  .partial()

const kgDiagnosticsRunSchema = z.looseObject({
  id: idSchema,
  tenant_id: idSchema,
  account_id: z.string().nullable(),
  dataset_id: idSchema,
  status: z.string(),
  params: recordSchema,
  summary: storedSummarySchema,
  created_at: dateTimeSchema,
})
const storedCaseSchema = z.looseObject({
  case_id: idSchema,
  question: z.string(),
  tags: z.array(z.string()),
  evidence_chunk_ids: z.array(z.string()),
  attribution: attributionSchema,
  baseline: z.looseObject({
    metrics: storedMetricsSchema,
    error: z.string().nullable(),
    returned_events: countSchema,
    selected_entities: countSchema,
    clues_total: countSchema,
  }),
  hardcases: z.array(
    z.looseObject({
      kind: hardcaseKindSchema,
      metrics: z.union([storedMetricsSchema, z.strictObject({})]),
      error: z.string().nullable(),
    }),
  ),
})
export const kgDiagnosticsRunDetailSchema = z
  .looseObject({ run: kgDiagnosticsRunSchema, items: z.array(storedCaseSchema) })
  .refine(
    (detail) => new Set(detail.items.map((item) => item.case_id)).size === detail.items.length,
    '运行记录出现重复样本身份',
  )
export const kgDiagnosticsRunListSchema = z
  .looseObject({ total: countSchema, items: z.array(kgDiagnosticsRunSchema) })
  .refine(
    (page) => page.items.length <= page.total && new Set(page.items.map((item) => item.id)).size === page.items.length,
    '运行列表数量或身份不一致',
  )

export const kgDiagnosticsRunListRequestSchema = z.object({
  dataset_id: idSchema,
  skip: countSchema.optional(),
  limit: integerSchema.min(1).max(200).optional(),
})

export const kgQualityRequestSchema = z.object({
  dataset_id: idSchema,
  document_limit: integerSchema.min(1).max(2000).optional(),
  pipeline_hash: z.string().min(1).max(200).optional(),
})
export const kgQualityReportSchema = z
  .looseObject({
    summary: z.looseObject({
      documents: countSchema,
      events: countSchema,
      entities: countSchema,
      relations: countSchema,
      event_entity_links: countSchema,
      avg_relations_per_entity: z.number().nonnegative(),
      isolated_entities: countSchema.optional(),
      isolated_entity_ratio: fractionSchema,
    }),
    components: z.looseObject({
      nodes: countSchema,
      edges: countSchema,
      components: countSchema,
      largest_component_ratio: fractionSchema,
      largest_component_size: countSchema.optional(),
      components_top_sizes: z.array(countSchema).optional(),
    }),
    noise: z.looseObject({
      relations_total: countSchema,
      low_confidence_threshold: fractionSchema,
      low_confidence_relations: countSchema,
      missing_references_relations: countSchema,
      missing_chunk_relations: countSchema,
    }),
    truncation: z.looseObject({ relation_edges_truncated: z.boolean(), relation_edges_limit: countSchema }),
    scope: z.looseObject({ dataset_id: idSchema, documents_sampled: countSchema, documents_allowed: countSchema }),
  })
  .refine(
    (report) =>
      report.scope.documents_allowed <= report.scope.documents_sampled &&
      report.summary.documents === report.scope.documents_allowed,
    '质量报告的抽样范围不一致',
  )

export type KGHardcaseMode = z.infer<typeof kgHardcaseModeSchema>
export type KGSearchRunMetrics = z.infer<typeof kgSearchMetricsSchema>
export type KGSearchDiagnosticsRequest = z.infer<typeof kgDiagnosticsRequestSchema>
export type KGSearchDiagnosticsItem = z.infer<typeof kgDiagnosticsItemSchema>
export type KGSearchDiagnosticsSummary = z.infer<typeof kgDiagnosticsSummarySchema>
export type KGSearchDiagnosticsResponse = z.infer<typeof kgDiagnosticsResponseSchema>
export type KGSearchDiagnosticsRunOut = z.infer<typeof kgDiagnosticsRunSchema>
export type KGSearchDiagnosticsRunDetail = z.infer<typeof kgDiagnosticsRunDetailSchema>
export type KGSearchDiagnosticsRunList = z.infer<typeof kgDiagnosticsRunListSchema>
export type KGSearchDiagnosticsRunListParams = z.infer<typeof kgDiagnosticsRunListRequestSchema>
export type KGQualityReport = z.infer<typeof kgQualityReportSchema>
export type KGQualityRequest = z.infer<typeof kgQualityRequestSchema>
