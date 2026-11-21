import { z } from 'zod'
import {
  dateTimeSchema,
  integerSchema,
  integerRecordSchema,
  stringRecordSchema,
  recordSchema,
} from '@/lib/response-schema'
import { datasetProfileSchema, profileHistogramBinSchema, profilePercentilesSchema } from '@/lib/dataset-profile-schema'

const complianceSchema = z.looseObject({
  pii_hits_total: integerRecordSchema,
  secrets_hits_total: integerRecordSchema,
  quarantined_documents: integerSchema,
  failed_documents: integerSchema,
})
const pipelineVersionSchema = z.looseObject({ pipeline_hash: z.string(), documents: integerSchema })
const connectorRunSchema = z.looseObject({
  id: z.string().min(1),
  connector_id: z.string(),
  status: z.string(),
  created_at: dateTimeSchema,
  finished_at: dateTimeSchema.nullable(),
  error_message: z.string().nullable(),
  stats: recordSchema,
})
const provenanceSchema = z.looseObject({
  source: z.string(),
  mocked: z.boolean(),
  generated_by: z.string(),
  sections: stringRecordSchema,
})
const governanceSchema = z.looseObject({
  total_documents: integerSchema,
  used_documents: integerSchema,
  truncated: z.boolean(),
  docs_with_governance: integerSchema,
  rules_applied_total: integerSchema,
  changed_documents_total: integerSchema,
  dropped_documents_total: integerSchema,
  drop_reasons_total: integerRecordSchema,
  rule_packs_docs: integerRecordSchema,
})
const governanceAuditSchema = z.looseObject({
  total_documents: integerSchema,
  used_documents: integerSchema,
  truncated: z.boolean(),
  docs_with_parsed_content_persisted: integerSchema,
  parsed_content_truncated_docs: integerSchema,
  docs_with_char_stats: integerSchema,
  original_chars_total: integerSchema,
  cleaned_chars_total: integerSchema,
  char_reduction_ratio: z.number(),
  char_reduction_pct_percentiles: profilePercentilesSchema,
  char_reduction_pct_histogram: z.array(profileHistogramBinSchema),
  docs_changed: integerSchema,
  docs_dropped: integerSchema,
  docs_with_governance_quality: integerSchema,
  density_pct_percentiles: profilePercentilesSchema,
  density_pct_histogram: z.array(profileHistogramBinSchema),
  heading_ratio_pct_percentiles: profilePercentilesSchema,
  heading_ratio_pct_histogram: z.array(profileHistogramBinSchema),
  paragraphs_dropped_total: integerSchema,
  references_removed_lines_total: integerSchema,
  urls_changed_total: integerSchema,
  boilerplate_removed_sections_total: integerSchema,
  boilerplate_removed_lines_total: integerSchema,
  images_removed_total: integerSchema,
  tables_normalized_total: integerSchema,
  table_rows_changed_total: integerSchema,
  code_lines_stripped_total: integerSchema,
})
const auditGateSchema = z.looseObject({
  name: z.string(),
  status: z.string(),
  metrics: recordSchema,
  failed_conditions: z.array(z.string()),
  generated_at: dateTimeSchema.nullable(),
  source: z.string().nullable(),
})
const retrievalAuditSchema = z.looseObject({
  status: z.string(),
  plugin_refs: z.array(z.string()),
  plugin_package_hashes: z.array(z.string()),
  gates: z.array(auditGateSchema),
  failure_categories: integerRecordSchema,
  kg_recommendation: z.string().nullable(),
  recommended_next_action: z.string().nullable(),
})

export type ReportFolderNode = {
  name: string
  path: string
  depth: number
  documents: number
  children: ReportFolderNode[]
}
const folderNodeSchema: z.ZodType<ReportFolderNode> = z.lazy(() =>
  z.looseObject({
    name: z.string(),
    path: z.string(),
    depth: integerSchema.min(0).max(50),
    documents: integerSchema.min(0),
    children: z.array(folderNodeSchema),
  }),
)
const folderTreeSchema = z.looseObject({
  dataset_id: z.string().min(1),
  total_documents: integerSchema,
  total_with_source_path: integerSchema,
  root: folderNodeSchema,
})

export const datasetReportSchema = z.looseObject({
  dataset_id: z.string().min(1),
  dataset_name: z.string().nullable(),
  pipeline_hash: z.string().nullable(),
  generated_at: dateTimeSchema,
  data_provenance: provenanceSchema,
  profile: datasetProfileSchema,
  compliance: complianceSchema,
  pipeline_versions: z.array(pipelineVersionSchema),
  pipeline_snapshots: recordSchema,
  connectors: z.array(connectorRunSchema),
  dataset_metadata: recordSchema,
  folder_tree: folderTreeSchema.nullable(),
  governance_metrics: governanceSchema.nullable(),
  governance_audit: governanceAuditSchema.nullable(),
  retrieval_audit: retrievalAuditSchema.nullable(),
})

export type DatasetReport = z.infer<typeof datasetReportSchema>
export type DatasetReportPipelineVersion = z.infer<typeof pipelineVersionSchema>
export type DatasetReportDataProvenance = z.infer<typeof provenanceSchema>
