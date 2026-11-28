/**
 * Dataset, reporting, and analysis types re-exported by `@/types`.
 */

import type { DocumentPipelineOptions } from './backend'
import type { JsonObject, PermissionEnum } from './common'
import type { components } from './openapi'
import type { IngestionPolicy } from './processing'
import type { RAGConfig } from './settings'

// ==================== 数据集相关类型 ====================

export type DatasetEmbeddingDefaults = {
  provider?: string | null
  model?: string | null
  api_base?: string | null
}

export type DatasetRagDefaults = components['schemas']['DatasetRAGDefaults']

// The workbench combines system RAG settings with these dataset-only overrides.
export type DatasetRagViewConfig = RAGConfig &
  Pick<
    DatasetRagDefaults,
    | 'retrieval_profile'
    | 'retrieval_mode'
    | 'retrieval_contract_mode'
    | 'alpha'
    | 'fusion_strategy'
    | 'fusion_budgets'
    | 'fusion_min_scores'
    | 'fusion_weights'
    | 'enable_weight_rerank'
    | 'vector_weight'
    | 'keyword_weight'
    | 'mmr_lambda'
    | 'visible_evidence_only'
  >

export type Dataset = {
  id: string
  tenant_id: string
  name: string
  description?: string | null
  permission: PermissionEnum
  owner_id?: string | null
  partial_member_list?: string[] | null
  partial_group_list?: string[] | null
  rag_defaults?: DatasetRagDefaults | null
  embedding_defaults?: DatasetEmbeddingDefaults | null
  pipeline?: DocumentPipelineOptions | null
  ingestion_summary?: DatasetIngestionSummary | null
  operational_status?: DatasetOperationalStatus | null
}

export type DatasetCreate = {
  name: string
  description?: string | null
  permission: PermissionEnum
  partial_member_list?: string[] | null
  partial_group_list?: string[] | null
  rag_defaults?: DatasetRagDefaults | null
  embedding_defaults?: DatasetEmbeddingDefaults | null
  pipeline?: DocumentPipelineOptions | null
}

export type DatasetUpdate = {
  name?: string | null
  description?: string | null
  permission?: PermissionEnum | null
  partial_member_list?: string[] | null
  partial_group_list?: string[] | null
  rag_defaults?: DatasetRagDefaults | null
  embedding_defaults?: DatasetEmbeddingDefaults | null
  pipeline?: DocumentPipelineOptions | null
}

export type DatasetOperationalStatus = 'active' | 'anomaly' | 'pending' | 'testing'

export type DatasetIngestionSummary = {
  total_documents: number
  by_status?: Record<string, number>
  total_chunks: number
  total_size: number
  total_characters: number
  last_processed_at?: string | null
}

export type DatasetListFacets = {
  scope_total: number
  filtered_total: number
  status_counts?: Record<string, number>
}

export type DatasetListResponse = {
  total: number
  items: Dataset[]
  facets?: DatasetListFacets | null
}

export type DatasetCategoryNode = import('./backend').OpenApiSchema<'DatasetCategoryNode'>

export type DatasetCategoryTreeResponse = {
  total: number
  items: DatasetCategoryNode[]
}

export type DatasetCategoryCreate = {
  name: string
  parent_id?: string | null
  sort_order?: number | null
}

export type DatasetCategoryUpdate = {
  name?: string | null
  sort_order?: number | null
}

export type DatasetCategoryMoveRequest = {
  parent_id?: string | null
  sort_order?: number | null
}

export type DatasetCategoryOut = {
  id: string
  tenant_id: string
  name: string
  parent_id?: string | null
  sort_order: number
  created_at: string
  updated_at?: string | null
}

export type DatasetCategoryAssignmentRequest = {
  category_ids?: string[]
}

export type DatasetCategoryAssignmentResponse = {
  dataset_id: string
  category_ids?: string[]
}

export type DatasetIngestionStats = {
  dataset_id: string
  total_documents: number
  by_status?: Record<string, number>
  total_chunks: number
  total_size: number
  total_characters: number
  last_processed_at?: string | null
}

export type DatasetHealthIngestionSummary = {
  total_documents: number
  by_status?: Record<string, number>
  pending: number
  processing: number
  completed: number
  failed: number
  quarantined: number
  cancelled: number
}

export type { DatasetHealthResponse } from '@/lib/dataset-profile-schema'

export type DatasetConfigBundle = components['schemas']['DatasetConfigBundle-Input']
export type DatasetConfigExport = components['schemas']['DatasetConfigExport']
export type DatasetConfigImportRequest = components['schemas']['DatasetConfigImportRequest']

export type DatasetCloneRequest = {
  name: string
  description?: string | null
  copy_permission: boolean
  copy_partial_members: boolean
}

// ==================== Dataset Profile (Ingestion Scan) ====================

export type {
  DatasetProfileSummary,
  DatasetProfileHistogramBin,
  DatasetProfilePercentiles,
  DatasetProfilePdfScanStats,
  DatasetProfileParsingProvenanceStats,
  DatasetProfileTargetCheckStatus,
  DatasetProfileTargetCheck,
  DatasetProfileFindingSummary,
  DatasetProfileScanRunSummary,
  DatasetProfileDocumentOut,
  DatasetProfileFindingListResponse,
  DatasetProfileDocumentListResponse,
  DatasetProfileScanRunOut,
  DatasetProfileScanRunListResponse,
} from '@/lib/dataset-profile-schema'
export type DatasetProfileFindingSeverity =
  import('@/lib/dataset-profile-schema').DatasetProfileFindingSummary['severity']
export type DatasetProfileScanRunCreateRequest = Partial<components['schemas']['DatasetProfileScanRunCreateRequest']>

// ==================== Dataset Precheck (Local Folder Scan) ====================

export type DatasetPrecheckFindingSeverity = 'info' | 'warning' | 'error'

export type DatasetPrecheckHistogramBin = {
  label: string
  min?: number | null
  max?: number | null
  count: number
}

export type DatasetPrecheckPercentiles = {
  p25: number
  p50: number
  p75: number
  p90: number
  p99: number
}

export type DatasetPrecheckPdfScanStats = {
  scanned: number
  not_scanned: number
  unknown: number
}

export type DatasetPrecheckPdfPageBreakdown = {
  page_count: number
  sampled_pages: number
  scanned_pages: number
  text_pages: number
  low_density_pages: number
  unknown_pages: number
  scan_ratio: number
  low_density_ratio: number
}

export type DatasetPrecheckSpreadsheetStats = {
  row_count: number
  col_count: number
  sheet_count: number
  merged_cell_ratio: number
  estimated_rows: boolean
  estimated_cols: boolean
}

export type DatasetPrecheckMatchSample = {
  kind: string
  masked: string
  context: string
  start?: number | null
  end?: number | null
}

export type DatasetPrecheckFindingSummary = {
  key: string
  label: string
  severity: DatasetPrecheckFindingSeverity
  count: number
  description?: string | null
}

export type DatasetPrecheckSummary = {
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
  embedding_advisories?: DatasetPrecheckEmbeddingAdvisory[] | null
}

export type DatasetPrecheckFileOut = {
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

export type DatasetPrecheckFindingListResponse = {
  total: number
  items: DatasetPrecheckFileOut[]
}

type DatasetPrecheckScanRunInput = components['schemas']['DatasetPrecheckScanRunCreateRequest']

export type DatasetPrecheckScanRunCreateRequest = Pick<DatasetPrecheckScanRunInput, 'root_path'> &
  Partial<Omit<DatasetPrecheckScanRunInput, 'root_path'>>

export type DatasetPrecheckScanRunOut = {
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

export type DatasetPrecheckScanRunListResponse = {
  total: number
  items: DatasetPrecheckScanRunOut[]
}

export type DatasetPrecheckSamplesResponse = {
  requested: number
  strata_count: number
  representative: DatasetPrecheckFileOut[]
  needs_review: Record<string, DatasetPrecheckFileOut[]>
  top_large_files: DatasetPrecheckFileOut[]
  top_long_text: DatasetPrecheckFileOut[]
}

export type DatasetPrecheckSampleReviewPatchRequest = {
  file_name: string
  disposition: 'approved' | 'manual'
}

export type DatasetPrecheckSampleReviewOut = {
  file_name: string
  review_disposition: 'approved' | 'manual'
  reviewed_at: string
  reviewed_by?: string | null
}

export type DatasetPrecheckNearDupCluster = {
  id: string
  members: string[]
}

export type DatasetPrecheckNearDupPair = {
  a: string
  b: string
  distance: number
}

export type DatasetPrecheckNearDupResponse = {
  threshold: number
  max_pairs: number
  pairs_returned: number
  clusters_returned: number
  clusters: DatasetPrecheckNearDupCluster[]
  pairs: DatasetPrecheckNearDupPair[]
}

export type DatasetPrecheckDiffItem = {
  key: string
  before: number
  after: number
  delta: number
}

export type DatasetPrecheckDiffResponse = {
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

export type DatasetPrecheckManualReviewBucket = {
  key: string
  total: number
  sample_names: string[]
}

export type DatasetPrecheckEmbeddingAdvisory = {
  code: string
  effective_embedding?: string | null
  recommended_action?: string | null
  recommended_model_ids?: string[] | null
}
export type DatasetPrecheckIngestionSuggestionResponse = {
  generated_at: string
  policy: IngestionPolicy
  notes: string[]
  manual_review: DatasetPrecheckManualReviewBucket[]
}

// ==================== Dataset Tables (TAG) ====================

export type DatasetTableColumn = {
  name: string
  dtype?: string | null
}

export type DatasetTableAsset = {
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

export type DatasetTablesListResponse = {
  total: number
  items: DatasetTableAsset[]
  next_skip: number | null
}

export type TableQueryRequest = {
  sql: string
  max_rows?: number | null
  max_cols?: number | null
}

export type TableQueryResponse = import('./backend').OpenApiSchema<'TableQueryResponse'>

export type TableAskRequest = {
  question: string
  max_rows?: number | null
}

export type TableAskResponse = {
  answer: string
  sql?: string | null
  data?: TableQueryResponse | null
}

export type LotusSemFilterRequest = {
  user_instruction: string
  strategy?: string
  max_rows?: number | null
}

// ==================== DB Catalog (SQL) ====================

export type DbCatalogColumn = {
  id: string
  table_id: string
  ordinal: number
  name: string
  data_type?: string | null
  nullable?: boolean | null
  comment?: string | null
  created_at: string
}

export type DbCatalogTableSummary = {
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

export type DbCatalogTableDetail = {
  columns: DbCatalogColumn[]
} & DbCatalogTableSummary

export type DbCatalogTablesListResponse = {
  total: number
  items: DbCatalogTableSummary[]
}

export type DbProfileSnapshot = {
  id: string
  table_id: string
  entitlement_hash: string
  profile: JsonObject
  sample_meta: JsonObject
  created_at: string
}

export type DbProfileSnapshotListResponse = {
  total: number
  items: DbProfileSnapshot[]
}
