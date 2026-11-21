import { z } from 'zod'
import { dateTimeSchema, integerSchema, integerRecordSchema, recordSchema } from '@/lib/response-schema'

export const profileHistogramBinSchema = z.looseObject({
  label: z.string(),
  min: integerSchema.nullable(),
  max: integerSchema.nullable(),
  count: integerSchema,
})
export const profilePercentilesSchema = z.looseObject({
  p25: integerSchema,
  p50: integerSchema,
  p75: integerSchema,
  p90: integerSchema,
  p99: integerSchema,
})
const profileFindingSchema = z.looseObject({
  key: z.string(),
  label: z.string(),
  severity: z.enum(['info', 'warning', 'error']),
  count: integerSchema,
  description: z.string().nullable(),
})
const profileTargetCheckSchema = z.looseObject({
  key: z.string(),
  label: z.string(),
  status: z.enum(['pass', 'warn', 'fail']),
  observed: recordSchema,
  target: recordSchema,
  message: z.string().nullable(),
  suggestions: z.array(z.string()),
})
const profileRecallRiskHintSchema = z.looseObject({
  key: z.string(),
  label: z.string(),
  severity: z.enum(['info', 'warning', 'error']),
  observed: recordSchema,
  target: recordSchema,
  message: z.string().nullable(),
  suggestions: z.array(z.string()),
})
const profileScanRunSummarySchema = z.looseObject({
  id: z.string().min(1),
  kind: z.string(),
  status: z.string(),
  progress: integerSchema,
  requested_by: z.string().nullable(),
  created_at: dateTimeSchema.nullable(),
  started_at: dateTimeSchema.nullable(),
  finished_at: dateTimeSchema.nullable(),
  error_message: z.string().nullable(),
})
export const datasetProfileSchema = z.looseObject({
  dataset_id: z.string().min(1),
  generated_at: dateTimeSchema,
  total_documents: integerSchema,
  total_size_bytes: integerSchema,
  by_status: integerRecordSchema,
  by_file_type: integerRecordSchema,
  by_directory: integerRecordSchema,
  by_quality_bucket: integerRecordSchema,
  file_size_histogram: z.array(profileHistogramBinSchema),
  length_percentiles: profilePercentilesSchema,
  length_histogram: z.array(profileHistogramBinSchema),
  chunk_count_percentiles: profilePercentilesSchema,
  chunk_count_histogram: z.array(profileHistogramBinSchema),
  avg_chunk_chars_percentiles: profilePercentilesSchema,
  avg_chunk_chars_histogram: z.array(profileHistogramBinSchema),
  chunk_length_percentiles: profilePercentilesSchema,
  chunk_length_histogram: z.array(profileHistogramBinSchema),
  chunk_token_percentiles: profilePercentilesSchema,
  chunk_token_histogram: z.array(profileHistogramBinSchema),
  avg_chunk_tokens_percentiles: profilePercentilesSchema,
  avg_chunk_tokens_histogram: z.array(profileHistogramBinSchema),
  chunk_coverage_percentiles: profilePercentilesSchema,
  chunk_coverage_histogram: z.array(profileHistogramBinSchema),
  chunk_overlap_waste_percentiles: profilePercentilesSchema,
  chunk_overlap_waste_histogram: z.array(profileHistogramBinSchema),
  page_number_histogram: z.array(profileHistogramBinSchema),
  parse_quality_histogram: z.array(profileHistogramBinSchema),
  language_mix: integerRecordSchema,
  pdf_scan: z.looseObject({ scanned: integerSchema, not_scanned: integerSchema, unknown: integerSchema }),
  parsing_provenance: z.looseObject({
    docs_with_provenance: integerSchema,
    by_resolved_backend: integerRecordSchema,
    fallback_docs: integerSchema,
    elapsed_ms_percentiles: profilePercentilesSchema,
  }),
  pii_hits_total: integerRecordSchema,
  secrets_hits_total: integerRecordSchema,
  findings: z.array(profileFindingSchema),
  recall_risk_hints: z.array(profileRecallRiskHintSchema),
  chunk_targets: z.array(profileTargetCheckSchema),
  latest_scan_run: profileScanRunSummarySchema.nullable(),
})

const profileDocumentSchema = z.looseObject({
  id: z.string().min(1),
  dataset_id: z.string().nullable(),
  filename: z.string(),
  file_type: z.string(),
  file_size: integerSchema,
  status: z.string(),
  chunk_count: integerSchema,
  total_characters: integerSchema,
  created_at: dateTimeSchema.nullable(),
  updated_at: dateTimeSchema.nullable(),
  error_message: z.string().nullable(),
  metadata: recordSchema,
  preview: z.string().nullable(),
  preview_truncated: z.boolean(),
})
export const profileDocumentsSchema = z.looseObject({ total: integerSchema, items: z.array(profileDocumentSchema) })
export const profileScanRunSchema = profileScanRunSummarySchema.extend({
  tenant_id: z.string().min(1),
  dataset_id: z.string().min(1),
  config: recordSchema,
  summary: recordSchema,
  updated_at: dateTimeSchema.nullable(),
})
export const profileScanRunsSchema = z.looseObject({ total: integerSchema, items: z.array(profileScanRunSchema) })
export const datasetHealthSchema = z.looseObject({
  dataset_id: z.string().min(1),
  generated_at: dateTimeSchema,
  profile: datasetProfileSchema,
  ingestion: z.looseObject({
    total_documents: integerSchema,
    by_status: integerRecordSchema,
    pending: integerSchema,
    processing: integerSchema,
    completed: integerSchema,
    failed: integerSchema,
    quarantined: integerSchema,
    cancelled: integerSchema,
  }),
})

export const profileScanSnapshotSchema = datasetProfileSchema
  .pick({ total_documents: true, total_size_bytes: true, pii_hits_total: true, secrets_hits_total: true })
  .extend({
    length_percentiles: profilePercentilesSchema.pick({ p90: true }),
    pdf_scan: datasetProfileSchema.shape.pdf_scan.pick({ scanned: true }),
  })

export type DatasetProfileSummary = z.infer<typeof datasetProfileSchema>
export type DatasetProfileHistogramBin = z.infer<typeof profileHistogramBinSchema>
export type DatasetProfilePercentiles = z.infer<typeof profilePercentilesSchema>
export type DatasetProfileFindingSummary = z.infer<typeof profileFindingSchema>
export type DatasetProfileTargetCheck = z.infer<typeof profileTargetCheckSchema>
export type DatasetProfileTargetCheckStatus = DatasetProfileTargetCheck['status']
export type DatasetProfilePdfScanStats = DatasetProfileSummary['pdf_scan']
export type DatasetProfileParsingProvenanceStats = DatasetProfileSummary['parsing_provenance']
export type DatasetProfileScanRunSummary = z.infer<typeof profileScanRunSummarySchema>
export type DatasetProfileDocumentOut = z.infer<typeof profileDocumentSchema>
export type DatasetProfileDocumentListResponse = z.infer<typeof profileDocumentsSchema>
export type DatasetProfileFindingListResponse = DatasetProfileDocumentListResponse
export type DatasetProfileScanRunOut = z.infer<typeof profileScanRunSchema>
export type DatasetProfileScanRunListResponse = z.infer<typeof profileScanRunsSchema>
export type DatasetHealthResponse = z.infer<typeof datasetHealthSchema>
