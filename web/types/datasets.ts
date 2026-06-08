/**
 * Dataset, reporting, and analysis types re-exported by `@/types`.
 */

import type { JsonObject, PermissionEnum } from './common'
import type { DocumentFolderTreeResponse } from './documents'
import type { DocumentPipelineOptions, IngestionPolicy } from './processing'

// ==================== 数据集相关类型 ====================

export interface DatasetEmbeddingDefaults {
  provider?: string | null
  model?: string | null
  api_base?: string | null
}

export interface Dataset {
  id: string
  tenant_id: string
  name: string
  description?: string | null
  permission: PermissionEnum
  owner_id?: string | null
  partial_member_list?: string[] | null
  partial_group_list?: string[] | null
  embedding_defaults?: DatasetEmbeddingDefaults | null
  pipeline?: DocumentPipelineOptions | null
}

export interface DatasetCreate {
  name: string
  description?: string | null
  permission: PermissionEnum
  partial_member_list?: string[] | null
  partial_group_list?: string[] | null
  embedding_defaults?: DatasetEmbeddingDefaults | null
  pipeline?: DocumentPipelineOptions | null
}

export interface DatasetUpdate {
  name?: string | null
  description?: string | null
  permission?: PermissionEnum | null
  partial_member_list?: string[] | null
  partial_group_list?: string[] | null
  embedding_defaults?: DatasetEmbeddingDefaults | null
  pipeline?: DocumentPipelineOptions | null
}

export interface DatasetListResponse {
  total: number
  items: Dataset[]
}

export interface DatasetCategoryNode {
  id: string
  name: string
  parent_id?: string | null
  sort_order: number
  depth: number
  datasets: number
  children?: DatasetCategoryNode[]
}

export interface DatasetCategoryTreeResponse {
  total: number
  items: DatasetCategoryNode[]
}

export interface DatasetCategoryCreate {
  name: string
  parent_id?: string | null
  sort_order?: number | null
}

export interface DatasetCategoryUpdate {
  name?: string | null
  sort_order?: number | null
}

export interface DatasetCategoryMoveRequest {
  parent_id?: string | null
  sort_order?: number | null
}

export interface DatasetCategoryOut {
  id: string
  tenant_id: string
  name: string
  parent_id?: string | null
  sort_order: number
  created_at: string
  updated_at?: string | null
}

export interface DatasetCategoryAssignmentRequest {
  category_ids?: string[]
}

export interface DatasetCategoryAssignmentResponse {
  dataset_id: string
  category_ids?: string[]
}

export interface DatasetIngestionStats {
  dataset_id: string
  total_documents: number
  by_status?: Record<string, number>
  total_chunks: number
  total_size: number
  total_characters: number
  last_processed_at?: string | null
}

export interface DatasetHealthIngestionSummary {
  total_documents: number
  by_status?: Record<string, number>
  pending: number
  processing: number
  completed: number
  failed: number
  quarantined: number
  cancelled: number
}

export type DatasetHealthResponse = import('./backend').DatasetHealthResponse

export interface DatasetReportCompliance {
  pii_hits_total: Record<string, number>
  secrets_hits_total: Record<string, number>
  quarantined_documents: number
  failed_documents: number
}

export interface DatasetReportPipelineVersion {
  pipeline_hash: string
  documents: number
}

export interface DatasetReportConnectorRun {
  id: string
  connector_id: string
  status: string
  created_at: string
  finished_at?: string | null
  error_message?: string | null
  stats: Record<string, unknown>
}

export interface DatasetReportDataProvenance {
  source: string
  mocked: boolean
  generated_by?: string | null
  sections: Record<string, string>
}

export interface DatasetGovernanceMetrics {
  total_documents: number
  used_documents: number
  truncated: boolean
  docs_with_governance: number
  rules_applied_total: number
  changed_documents_total: number
  dropped_documents_total: number
  drop_reasons_total: Record<string, number>
  rule_packs_docs: Record<string, number>
}

export interface DatasetGovernanceAudit {
  total_documents: number
  used_documents: number
  truncated: boolean
  docs_with_parsed_content_persisted: number
  parsed_content_truncated_docs: number
  docs_with_char_stats: number
  original_chars_total: number
  cleaned_chars_total: number
  char_reduction_ratio: number
  char_reduction_pct_percentiles: DatasetProfilePercentiles
  char_reduction_pct_histogram: DatasetProfileHistogramBin[]
  docs_changed: number
  docs_dropped: number
  docs_with_governance_quality: number
  density_pct_percentiles: DatasetProfilePercentiles
  density_pct_histogram: DatasetProfileHistogramBin[]
  heading_ratio_pct_percentiles: DatasetProfilePercentiles
  heading_ratio_pct_histogram: DatasetProfileHistogramBin[]
  paragraphs_dropped_total: number
  references_removed_lines_total: number
  urls_changed_total: number
  boilerplate_removed_sections_total: number
  boilerplate_removed_lines_total: number
  images_removed_total: number
  tables_normalized_total: number
  table_rows_changed_total: number
  code_lines_stripped_total: number
}

export interface DatasetRetrievalAuditGate {
  name: string
  status: string
  metrics: Record<string, unknown>
  failed_conditions: string[]
  generated_at?: string | null
  source?: string | null
}

export interface DatasetRetrievalAudit {
  status: string
  plugin_refs: string[]
  plugin_package_hashes: string[]
  gates: DatasetRetrievalAuditGate[]
  failure_categories: Record<string, number>
  kg_recommendation?: string | null
  recommended_next_action?: string | null
}

export interface DatasetReport {
  dataset_id: string
  dataset_name?: string | null
  pipeline_hash?: string | null
  generated_at: string
  data_provenance?: DatasetReportDataProvenance | null
  profile: DatasetProfileSummary
  compliance: DatasetReportCompliance
  pipeline_versions: DatasetReportPipelineVersion[]
  connectors: DatasetReportConnectorRun[]
  dataset_metadata: Record<string, unknown>
  folder_tree?: DocumentFolderTreeResponse | null
  governance_metrics?: DatasetGovernanceMetrics | null
  governance_audit?: DatasetGovernanceAudit | null
  retrieval_audit?: DatasetRetrievalAudit | null
}

export interface DatasetConfigBundle {
  default_parser_backend?: string | null
  default_chunk_strategy?: string | null
  rag_defaults?: Record<string, unknown> | null
  embedding_defaults?: DatasetEmbeddingDefaults | null
  default_prompt_template_id?: string | null
  default_prompt_template_key?: string | null
  default_prompt_ab_experiment_key?: string | null
  pipeline?: DocumentPipelineOptions | null
  ingestion_policy?: IngestionPolicy | null
  workflow_layout?: Record<string, unknown> | null
}

export interface DatasetConfigExport {
  version: string
  dataset_id: string
  name: string
  exported_at: string
  config: DatasetConfigBundle
}

export interface DatasetConfigImportRequest {
  config: DatasetConfigBundle
  replace: boolean
}

export interface DatasetCloneRequest {
  name: string
  description?: string | null
  copy_permission: boolean
  copy_partial_members: boolean
}

// ==================== Dataset Profile (Ingestion Scan) ====================

export type DatasetProfileFindingSeverity = 'info' | 'warning' | 'error'

export interface DatasetProfileHistogramBin {
  label: string
  min?: number | null
  max?: number | null
  count: number
}

export interface DatasetProfilePercentiles {
  p25: number
  p50: number
  p75: number
  p90: number
  p99: number
}

export interface DatasetProfilePdfScanStats {
  scanned: number
  not_scanned: number
  unknown: number
}

export interface DatasetProfileParsingProvenanceStats {
  docs_with_provenance: number
  by_resolved_backend: Record<string, number>
  fallback_docs: number
  elapsed_ms_percentiles: DatasetProfilePercentiles
}

export type DatasetProfileTargetCheckStatus = 'pass' | 'warn' | 'fail'

export interface DatasetProfileTargetCheck {
  key: string
  label: string
  status: DatasetProfileTargetCheckStatus
  observed: JsonObject
  target: JsonObject
  message?: string | null
  suggestions: string[]
}

export interface DatasetProfileFindingSummary {
  key: string
  label: string
  severity: DatasetProfileFindingSeverity
  count: number
  description?: string | null
}

export interface DatasetProfileScanRunSummary {
  id: string
  kind: string
  status: string
  progress: number
  requested_by?: string | null
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
  error_message?: string | null
}

export interface DatasetProfileSummary {
  dataset_id: string
  generated_at: string

  total_documents: number
  total_size_bytes: number
  by_status: Record<string, number>
  by_file_type: Record<string, number>
  by_directory?: Record<string, number>
  by_quality_bucket?: Record<string, number>

  file_size_histogram: DatasetProfileHistogramBin[]
  length_percentiles: DatasetProfilePercentiles
  length_histogram: DatasetProfileHistogramBin[]
  chunk_count_percentiles?: DatasetProfilePercentiles
  chunk_count_histogram?: DatasetProfileHistogramBin[]
  avg_chunk_chars_percentiles?: DatasetProfilePercentiles
  avg_chunk_chars_histogram?: DatasetProfileHistogramBin[]
  chunk_length_percentiles?: DatasetProfilePercentiles
  chunk_length_histogram?: DatasetProfileHistogramBin[]
  chunk_token_percentiles?: DatasetProfilePercentiles
  chunk_token_histogram?: DatasetProfileHistogramBin[]
  avg_chunk_tokens_percentiles?: DatasetProfilePercentiles
  avg_chunk_tokens_histogram?: DatasetProfileHistogramBin[]
  chunk_coverage_percentiles?: DatasetProfilePercentiles
  chunk_coverage_histogram?: DatasetProfileHistogramBin[]
  chunk_overlap_waste_percentiles?: DatasetProfilePercentiles
  chunk_overlap_waste_histogram?: DatasetProfileHistogramBin[]
  page_number_histogram?: DatasetProfileHistogramBin[]
  parse_quality_histogram?: DatasetProfileHistogramBin[]
  language_mix?: Record<string, number>
  pdf_scan: DatasetProfilePdfScanStats
  parsing_provenance?: DatasetProfileParsingProvenanceStats

  pii_hits_total: Record<string, number>
  secrets_hits_total: Record<string, number>

  findings: DatasetProfileFindingSummary[]
  chunk_targets?: DatasetProfileTargetCheck[]
  latest_scan_run?: DatasetProfileScanRunSummary | null
}

export interface DatasetProfileDocumentOut {
  id: string
  dataset_id?: string | null
  filename: string
  file_type: string
  file_size: number
  status: string
  chunk_count: number
  total_characters: number
  created_at?: string | null
  updated_at?: string | null
  error_message?: string | null
  metadata: JsonObject
  preview?: string | null
  preview_truncated?: boolean
}

export interface DatasetProfileFindingListResponse {
  total: number
  items: DatasetProfileDocumentOut[]
}

export interface DatasetProfileDocumentListResponse {
  total: number
  items: DatasetProfileDocumentOut[]
}

export interface DatasetProfileScanRunCreateRequest {
  backfill_pdf_quality?: boolean
  backfill_text_quality?: boolean
  backfill_chunk_stats?: boolean
  compute_file_hash?: boolean
  max_documents?: number | null
}

export interface DatasetProfileScanRunOut {
  id: string
  tenant_id: string
  dataset_id: string
  requested_by?: string | null
  kind: string
  status: string
  progress: number
  config: JsonObject
  summary: JsonObject
  error_message?: string | null
  started_at?: string | null
  finished_at?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface DatasetProfileScanRunListResponse {
  total: number
  items: DatasetProfileScanRunOut[]
}

// ==================== Dataset Precheck (Local Folder Scan) ====================

export type DatasetPrecheckFindingSeverity = 'info' | 'warning' | 'error'

export interface DatasetPrecheckHistogramBin {
  label: string
  min?: number | null
  max?: number | null
  count: number
}

export interface DatasetPrecheckPercentiles {
  p25: number
  p50: number
  p75: number
  p90: number
  p99: number
}

export interface DatasetPrecheckPdfScanStats {
  scanned: number
  not_scanned: number
  unknown: number
}

export interface DatasetPrecheckPdfPageBreakdown {
  page_count: number
  sampled_pages: number
  scanned_pages: number
  text_pages: number
  low_density_pages: number
  unknown_pages: number
  scan_ratio: number
  low_density_ratio: number
}

export interface DatasetPrecheckSpreadsheetStats {
  row_count: number
  col_count: number
  sheet_count: number
  merged_cell_ratio: number
  estimated_rows: boolean
  estimated_cols: boolean
}

export interface DatasetPrecheckMatchSample {
  kind: string
  masked: string
  context: string
  start?: number | null
  end?: number | null
}

export interface DatasetPrecheckFindingSummary {
  key: string
  label: string
  severity: DatasetPrecheckFindingSeverity
  count: number
  description?: string | null
}

export interface DatasetPrecheckSummary {
  dataset_id: string
  scan_run_id: string
  generated_at: string

  total_files: number
  total_size_bytes: number
  reused_files?: number
  by_file_type: Record<string, number>

  file_size_histogram: DatasetPrecheckHistogramBin[]
  length_percentiles: DatasetPrecheckPercentiles
  length_histogram: DatasetPrecheckHistogramBin[]

  pdf_scan: DatasetPrecheckPdfScanStats
  pdf_detection?: JsonObject

  pii_hits_total: Record<string, number>
  secrets_hits_total: Record<string, number>

  findings: DatasetPrecheckFindingSummary[]
}

export interface DatasetPrecheckFileOut {
  name: string
  file_type: string
  file_size: number
  file_mtime?: number | null
  text_characters: number
  estimated_text: boolean
  pdf_scanned?: boolean | null
  pdf_pages?: DatasetPrecheckPdfPageBreakdown | null
  spreadsheet?: DatasetPrecheckSpreadsheetStats | null
  text_simhash64?: string | null
  pii_hits: Record<string, number>
  secrets_hits: Record<string, number>
  pii_samples?: DatasetPrecheckMatchSample[]
  secrets_samples?: DatasetPrecheckMatchSample[]
  file_sha256?: string | null
  findings: string[]
  error_message?: string | null
  review_disposition?: 'approved' | 'manual' | null
  reviewed_at?: string | null
  reviewed_by?: string | null
}

export interface DatasetPrecheckFindingListResponse {
  total: number
  items: DatasetPrecheckFileOut[]
}

export interface DatasetPrecheckScanRunCreateRequest {
  root_path: string
  max_files?: number | null
  enable_pdf_quality?: boolean
  enable_text_extract?: boolean
  enable_pii?: boolean
  enable_secrets?: boolean
  compute_file_hash?: boolean
  pdf_sample_pages?: number | null
  text_extract_max_bytes?: number | null
  redact_paths?: boolean

  enable_pii_samples?: boolean
  pii_context_chars?: number | null
  pii_max_samples_per_file?: number | null

  enable_secrets_samples?: boolean
  secrets_context_chars?: number | null
  secrets_max_samples_per_file?: number | null

  pdf_min_text_chars_per_page?: number | null
  pdf_text_chars_per_page?: number | null
  pdf_scan_ratio_threshold?: number | null

  enable_near_dup?: boolean
  near_dup_hamming_threshold?: number | null
  near_dup_max_pairs?: number | null

  enable_sampling?: boolean
  sample_size?: number | null

  reuse_unchanged_files?: boolean
  reuse_from_scan_run_id?: string | null
}

export interface DatasetPrecheckScanRunOut {
  id: string
  tenant_id: string
  dataset_id: string
  requested_by?: string | null
  kind: string
  status: string
  progress: number
  config: JsonObject
  summary: JsonObject
  artifacts: JsonObject
  error_message?: string | null
  started_at?: string | null
  finished_at?: string | null
  created_at?: string | null
  updated_at?: string | null
}

export interface DatasetPrecheckScanRunListResponse {
  total: number
  items: DatasetPrecheckScanRunOut[]
}

export interface DatasetPrecheckSamplesResponse {
  requested: number
  strata_count: number
  representative: DatasetPrecheckFileOut[]
  needs_review: Record<string, DatasetPrecheckFileOut[]>
  top_large_files: DatasetPrecheckFileOut[]
  top_long_text: DatasetPrecheckFileOut[]
}

export interface DatasetPrecheckSampleReviewPatchRequest {
  file_name: string
  disposition: 'approved' | 'manual'
}

export interface DatasetPrecheckSampleReviewOut {
  file_name: string
  review_disposition: 'approved' | 'manual'
  reviewed_at: string
  reviewed_by?: string | null
}

export interface DatasetPrecheckNearDupCluster {
  id: string
  members: string[]
}

export interface DatasetPrecheckNearDupPair {
  a: string
  b: string
  distance: number
}

export interface DatasetPrecheckNearDupResponse {
  threshold: number
  max_pairs: number
  pairs_returned: number
  clusters_returned: number
  clusters: DatasetPrecheckNearDupCluster[]
  pairs: DatasetPrecheckNearDupPair[]
}

export interface DatasetPrecheckDiffItem {
  key: string
  before: number
  after: number
  delta: number
}

export interface DatasetPrecheckDiffResponse {
  base_scan_run_id: string
  target_scan_run_id: string
  generated_at: string
  total_files: DatasetPrecheckDiffItem
  total_size_bytes: DatasetPrecheckDiffItem
  pdf_scanned: DatasetPrecheckDiffItem
  pdf_unknown: DatasetPrecheckDiffItem
  by_file_type: DatasetPrecheckDiffItem[]
  findings: DatasetPrecheckDiffItem[]
}

export interface DatasetPrecheckManualReviewBucket {
  key: string
  total: number
  sample_names: string[]
}

export interface DatasetPrecheckIngestionSuggestionResponse {
  generated_at: string
  policy: IngestionPolicy
  notes: string[]
  manual_review: DatasetPrecheckManualReviewBucket[]
}

// ==================== Dataset Tables (TAG) ====================

export interface DatasetTableColumn {
  name: string
  dtype?: string | null
}

export interface DatasetTableAsset {
  table_id: string
  document_id: string
  document_filename?: string | null
  sheet_index: number
  sheet_name?: string | null
  row_count: number
  col_count: number
  truncated: boolean
  columns: DatasetTableColumn[]
  sample_rows: JsonObject[]
}

export interface DatasetTablesListResponse {
  total: number
  items: DatasetTableAsset[]
}

export interface TableQueryRequest {
  sql: string
  max_rows?: number | null
  max_cols?: number | null
}

export interface TableQueryResponse {
  sql: string
  columns: string[]
  rows: unknown[][]
  truncated: boolean
}

export interface TableAskRequest {
  question: string
  max_rows?: number | null
}

export interface TableAskResponse {
  answer: string
  sql?: string | null
  data?: TableQueryResponse | null
}

export interface LotusSemFilterRequest {
  user_instruction: string
  strategy?: string
  max_rows?: number | null
}

// ==================== DB Catalog (SQL) ====================

export interface DbCatalogColumn {
  id: string
  table_id: string
  ordinal: number
  name: string
  data_type?: string | null
  nullable?: boolean | null
  comment?: string | null
  created_at: string
}

export interface DbCatalogTableSummary {
  id: string
  connector_config_id?: string | null
  engine: string
  db_name: string
  schema_name?: string | null
  table_name: string
  table_type: string
  comment?: string | null
  fingerprint: string
  last_seen_at?: string | null
  created_at: string
  updated_at?: string | null
}

export interface DbCatalogTableDetail extends DbCatalogTableSummary {
  columns: DbCatalogColumn[]
}

export interface DbCatalogTablesListResponse {
  total: number
  items: DbCatalogTableSummary[]
}

export interface DbProfileSnapshot {
  id: string
  table_id: string
  entitlement_hash: string
  profile: JsonObject
  sample_meta: JsonObject
  created_at: string
}

export interface DbProfileSnapshotListResponse {
  total: number
  items: DbProfileSnapshot[]
}
