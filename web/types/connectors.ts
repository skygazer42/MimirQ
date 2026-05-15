import type { DocumentAccessMode, JsonObject } from './common'
import type { DocumentPipelineOptions } from './backend'
import type { DocumentAccessUpdateRequest } from './documents'

// Backend may add connector ids over time; keep this open-ended.
export type ConnectorId = string
export type ConnectorRunStatus = 'pending' | 'running' | 'completed' | 'failed' | 'cancelled'

export interface ConnectorInfo {
  id: ConnectorId
  name: string
  description?: string
  supports_incremental?: boolean
  supports_resume?: boolean
}

export interface UrlBatchConnectorConfig {
  [key: string]: unknown
  urls: string[]
  filename?: string | null
  parser_backend?: string
  chunk_strategy?: string
  pipeline?: DocumentPipelineOptions
  access?: DocumentAccessUpdateRequest | null
}

export interface MinioBucketConnectorConfig {
  [key: string]: unknown
  bucket?: string | null
  prefix?: string | null
  include_extensions?: string[]
  max_objects?: number
  presign_expiry_sec?: number
  parser_backend?: string
  chunk_strategy?: string
  pipeline?: DocumentPipelineOptions
  access?: DocumentAccessUpdateRequest | null
}

export interface WebCrawlAuthConfig {
  type: 'none' | 'cookie' | 'bearer' | 'basic'
  cookie?: string | null
  token?: string | null
  username?: string | null
  password?: string | null
}

export interface SourcePrincipal {
  system: 'github' | 'confluence' | 'jira' | 'drive' | 'generic'
  kind: 'user' | 'group' | 'team' | 'role' | 'policy' | 'domain' | 'anyone'
  id: string
  display?: string | null
}

export interface ConnectorSourceAclGroupMappingRule {
  source: SourcePrincipal
  group_id: string
}

export interface ConnectorSourceAclConfig {
  mode?: 'disabled' | 'inherit'
  group_mappings?: ConnectorSourceAclGroupMappingRule[]
  allow_anyone?: boolean
  fallback_mode?: DocumentAccessMode
}

export interface WebCrawlConnectorConfig {
  [key: string]: unknown
  start_urls: string[]
  max_pages?: number
  max_depth?: number
  same_host_only?: boolean
  include_patterns?: string[]
  exclude_patterns?: string[]
  use_sitemaps?: boolean
  sitemap_urls?: string[]
  respect_robots?: boolean
  dedup_canonical?: boolean
  user_agent?: string | null
  auth?: WebCrawlAuthConfig | null

  filename?: string | null
  parser_backend?: string
  chunk_strategy?: string
  pipeline?: DocumentPipelineOptions
  access?: DocumentAccessUpdateRequest | null
}

export interface MySQLCatalogConnectorConfig {
  [key: string]: unknown
  host: string
  port?: number
  database: string
  username: string
  password: string
  include_schemas?: string[]
  include_tables?: string[]
  max_tables?: number
  profile_enabled?: boolean
}

export interface SQLServerCatalogConnectorConfig {
  [key: string]: unknown
  host: string
  port?: number
  database: string
  username: string
  password: string
  include_schemas?: string[]
  include_tables?: string[]
  max_tables?: number
  profile_enabled?: boolean
}

export interface JiraProjectConnectorConfig {
  [key: string]: unknown
  base_url: string
  project_key: string
  jql?: string | null
  auth?: WebCrawlAuthConfig | null
  sync_mode?: 'auto' | 'full' | 'incremental'
  max_issues?: number
  page_size?: number
  include_comments?: boolean
  max_comments_per_issue?: number
  user_agent?: string | null
  parser_backend?: string
  chunk_strategy?: string
  pipeline?: DocumentPipelineOptions
  access?: DocumentAccessUpdateRequest | null
  source_acl?: ConnectorSourceAclConfig | null
}

export type ConnectorRunCreateRequest =
  | {
      connector_id: 'url_batch'
      dataset_id?: string | null
      config: UrlBatchConnectorConfig
    }
  | {
      connector_id: 'web_crawl'
      dataset_id?: string | null
      config: WebCrawlConnectorConfig
    }
  | {
      connector_id: 'minio_bucket'
      dataset_id?: string | null
      config: MinioBucketConnectorConfig
    }
  | {
      connector_id: 'jira_project'
      dataset_id?: string | null
      config: JiraProjectConnectorConfig
    }
  | {
      connector_id: 'mysql_catalog'
      dataset_id?: string | null
      config: MySQLCatalogConnectorConfig
    }
  | {
      connector_id: 'sqlserver_catalog'
      dataset_id?: string | null
      config: SQLServerCatalogConnectorConfig
    }

export interface ConnectorValidateRequest {
  connector_id: string
  config?: Record<string, unknown>
  check_connectivity: boolean
}

export interface ConnectorValidateResponse {
  ok: boolean
  connector_id: string
  config?: Record<string, unknown>
  errors?: Record<string, unknown>[]
  warnings?: Record<string, unknown>[]
  checks?: Record<string, unknown>
}

export interface ConnectorRunDocumentOut {
  document_id: string
  source_ref?: string | null
  status?: string
}

export interface ConnectorRunAclSummaryOut {
  mode: string
  documents_total: number
  access_mode_counts?: Record<string, number>

  partial_members_doc_count?: number
  partial_member_count_min?: number | null
  partial_member_count_max?: number | null
  partial_group_count_min?: number | null
  partial_group_count_max?: number | null
}

export interface ConnectorRunOut {
  id: string
  tenant_id: string
  dataset_id?: string | null
  connector_id: string
  requested_by?: string | null
  status: ConnectorRunStatus
  config?: JsonObject
  stats?: JsonObject
  error_message?: string | null
  task_id?: string | null
  created_at: string
  started_at?: string | null
  finished_at?: string | null
  acl_summary?: ConnectorRunAclSummaryOut | null
  documents?: ConnectorRunDocumentOut[]
}

export interface ConnectorRunListResponse {
  total: number
  items: ConnectorRunOut[]
}

export interface IngestionRunDocumentOut {
  document_id: string
  status: string
  source_ref?: string | null
  created_at?: string | null
}

export interface IngestionRunOut {
  id: string
  tenant_id: string
  dataset_id?: string | null
  kind: string
  requested_by?: string | null
  status: string
  config?: JsonObject
  stats?: JsonObject
  error_message?: string | null
  created_at?: string | null
  started_at?: string | null
  finished_at?: string | null
  documents?: IngestionRunDocumentOut[]
}

export interface IngestionRunListResponse {
  total: number
  items: IngestionRunOut[]
}

export interface IngestionRunCompareResponse {
  run_a: IngestionRunOut
  run_b: IngestionRunOut
  diff: JsonObject
}

export interface ConnectorConfigCreateRequest {
  connector_id: string
  dataset_id: string
  name: string
  enabled: boolean
  schedule_cron?: string | null
  config?: Record<string, unknown>
}

export interface ConnectorConfigUpdateRequest {
  name?: string | null
  enabled?: boolean | null
  schedule_cron?: string | null
  config?: Record<string, unknown> | null
  state?: Record<string, unknown> | null
}

export interface ConnectorConfigOut {
  id: string
  tenant_id: string
  dataset_id: string
  connector_id: string
  name: string
  enabled: boolean
  schedule_cron?: string | null
  config?: Record<string, unknown>
  state?: Record<string, unknown>
  last_run_at?: string | null
  last_error?: string | null
  created_at: string
  updated_at: string
}

export interface ConnectorConfigListResponse {
  total: number
  items: ConnectorConfigOut[]
}

export type ConnectorScheduledTickResponse = unknown
