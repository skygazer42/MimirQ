/**
 * API 客户端
 */
import type { Document, DocumentList, DocumentChunk, DocumentChunkList, DocumentChunkCreateRequest, DocumentChunkMatchList, DocumentChunkReembedRequest, DocumentChunkReembedResponse, DocumentChunkUpdateRequest, DocumentQAGenerateRequest, DocumentQAGenerateResponse, DocumentStatus, DocumentTimelineResponse, DocumentFolderTreeResponse, DocumentStats, DocumentAccessInfo, DocumentAccessUpdateRequest, DocumentBatchLifecycleResponse, DocumentHealthCard, DocumentBatchReingestRequest, DocumentBatchRetryRequest, DocumentBatchRetryResponse, DocumentBatchMoveRequest, DocumentBatchMoveResponse, DocumentBatchAccessUpdateRequest, DocumentBatchAccessUpdateResponse, DocumentDuplicateList, DocumentVersionList, DocumentVersionDiff, ConnectorInfo, ConnectorConfigCreateRequest, ConnectorConfigListResponse, ConnectorConfigOut, ConnectorConfigUpdateRequest, ConnectorScheduledTickResponse, ConnectorRunCreateRequest, ConnectorRunListResponse, ConnectorRunOut, IngestionRunCompareResponse, IngestionRunListResponse, IngestionRunOut, ConnectorValidateRequest, ConnectorValidateResponse, DocumentUserMetadataPatchRequest, DocumentBatchUserMetadataPatchRequest, DocumentBatchUserMetadataPatchResponse, DocumentPipelinePatchRequest, DocumentLifecycleMetadata, DocumentLifecycleMetadataUpdateRequest, ChatTokenUsageSummary, ChatCostUsageSummary, ChatTokenQuotaStatus, TenantQuotaSummary, AuditLogListResponse, DocumentPreview, DocumentParsedContentResponse, ManualChunk, DocumentPipelineOptions, ChunkPreviewResponse, ChunkPreset, ChunkPresetCreateRequest, ChunkPresetUpdateRequest, ChunkPresetListResponse, DocumentBatchUploadResponse, Dataset, DatasetCreate, DatasetUpdate, DatasetListResponse, DatasetCategoryTreeResponse, DatasetCategoryCreate, DatasetCategoryUpdate, DatasetCategoryMoveRequest, DatasetCategoryOut, DatasetCategoryAssignmentRequest, DatasetCategoryAssignmentResponse, DatasetIngestionStats, DatasetHealthResponse, DatasetReport, DatasetConfigExport, DatasetConfigImportRequest, DatasetCloneRequest, DatasetProfileSummary, DatasetProfileDocumentListResponse, DatasetProfileFindingListResponse, DatasetProfileScanRunCreateRequest, DatasetProfileScanRunListResponse, DatasetProfileScanRunOut, DatasetPrecheckSummary, DatasetPrecheckFindingListResponse, DatasetPrecheckScanRunCreateRequest, DatasetPrecheckScanRunListResponse, DatasetPrecheckScanRunOut, DatasetPrecheckSamplesResponse, DatasetPrecheckNearDupResponse, DatasetPrecheckDiffResponse, DatasetPrecheckIngestionSuggestionResponse, DatasetTablesListResponse, DatasetTableAsset, TableQueryRequest, TableQueryResponse, TableAskRequest, TableAskResponse, LotusSemFilterRequest, DbCatalogTablesListResponse, DbCatalogTableDetail, DbProfileSnapshotListResponse, MessageFeedback, MessageFeedbackCreate, MessageFeedbackListResponse, MessageFeedbackEnrichedListResponse, KGDeleteResponse, KGEntityDetailResponse, KGEntityMergeRequest, KGEntityMergePreviewResponse, KGEntityMergeResponse, KGEntityResolutionUndoResponse, KGEntitySplitRequest, KGEntitySplitResponse, KGEntityAliasCreateRequest, KGEntityAliasItem, KGEntityAliasesResponse, KGEntityAliasSuggestionsResponse, KGPredicateOntologyCreateRequest, KGPredicateOntologyItem, KGPredicateOntologyListResponse, KGPredicateOntologyUpdateRequest, KGEventDetailResponse, KGExtractResponse, KGGraphNode, KGGraphResponse, KGSearchRequest, KGSearchResponse, KGStatsResponse, BatchUploadResponse, BatchTaskStatus, BatchFileInfo, CleanPreviewRequest, CleanPreviewResponse, CleanRulesResponse, HealthResponse, KeywordExtractRequest, KeywordExtractResponse, LLMCleanPreviewRequest, LLMCleanPreviewResponse, PipelineCapabilitiesResponse, GovernanceAnalyzeRequest, GovernanceAnalyzeResponse, GovernanceRulePackListResponse, StaleDocumentsByDatasetResponse, GovernanceCommonLinesLearnRequest, GovernanceCommonLinesLearnResponse, GovernanceProfileListResponse, GovernanceProfileOut, GovernanceProfileCreate, GovernanceProfileUpdate, GovernanceProfileImportResponse, GovernanceProfileResolvedResponse, PipelineChunkPreviewRequest, PipelineChunkPreviewResponse, PipelineParsePreviewResponse, ReadyResponse, EvidenceItem, EvidenceItemCreate, EvidenceItemImportResponse, EvidenceItemList, EvidenceItemPatch, EvidenceReferenceDriftAudit, EvidenceReferenceRepairRequest, EvidenceReferenceRepairResponse, EvidenceHardcaseDiscovery, EvidenceSuite, EvidenceSuiteCreate, EvidenceSuiteExportV1, EvidenceSuiteDashboard, EvidenceSuiteList, EvidenceSuitePatch, EvidenceSuiteSyncRegressionResponse, RegressionCase, RegressionCaseCreate, RegressionCaseBundleV1, RegressionCaseImportResponse, RegressionCaseList, RegressionCasePatch, TestGenFromDocsRequest, TestGenFromConversationsRequest, TestGenResponse, RegressionRun, RegressionRunCreate, RegressionRunList, RegressionRunDetail, AuthResponse, LoginRequest, RegisterRequest, UserProfile, ZipWithImagesResponse, IngestionPolicy, IngestionPolicyImportResponse, IngestionPolicyRollbackRequest, IngestionPolicyVersionListResponse, IngestionPreviewResponse, RagvizSimilarityCollectionsResponse, RagvizSimilarityRequest, RagvizSimilarityCalculateResponse, RagMetricsSummaryResponse, OnlineQualitySummaryResponse, QuerysetHealthRunsResponse, QuerysetHealthDiffResponse, RagQueryAnalyticsResponse, RagCostAttributionResponse, RagTraceBundleResponse, RagTraceBundleDiffResponse, OpsConfigSnapshotResponse, PeriodicJobFreshnessResponse, DepsDiagnosticsResponse, TaskQueueObservabilitySnapshotResponse, SloSnapshotResponse, IndexAuditResponse, IngestionDashboardSummaryResponse, RagasRegressionRunDiffResponse } from '@/types'
import type {
  MetaResponse,
  TenantGroupCreateRequest,
  TenantGroupListResponse,
  TenantGroupMemberListResponse,
  TenantGroupMembersUpdateRequest,
  TenantGroupMembersUpdateResponse,
  TenantGroupOut,
  TenantGroupUpdateRequest,
} from '@/types/backend'
import { getAuthHeaders } from '@/lib/auth-headers'
import { buildFetchError } from '@/lib/fetch-errors'
import { API_LONG_TIMEOUT_MS, API_V1_BASE_URL } from '@/lib/env'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'
import { withPreferredLanguageHeader } from '@/lib/preferred-language'
import { generateRequestId } from '@/lib/request-id'
import { readSseDataStrings } from '@/lib/sse-reader'
import {
  apiClient,
  coerceRetryAfterSeconds,
  formatRateLimitLogMessage,
  openapiRequest,
  type ApiRequestOptions,
} from '@/lib/api/core'

export { apiClient, coerceRetryAfterSeconds, formatRateLimitLogMessage } from '@/lib/api/core'
export { authApi } from '@/lib/api/auth'
export { chatApi } from '@/lib/api/chat'
export { connectorApi } from '@/lib/api/connectors'
export { datasetApi } from '@/lib/api/datasets'
export { datasetCategoryApi } from '@/lib/api/datasets'
export { appendChunkPreviewFormFields, buildChunkPreviewQueryParams } from '@/lib/api/document-helpers'
export { evaluationApi } from '@/lib/api/evaluation'
export { kgApi } from '@/lib/api/graph'
export { observabilityApi } from '@/lib/api/observability'
export { pipelineApi } from '@/lib/api/pipeline'
export { ragApi } from '@/lib/api/rag'
export { reportApi } from '@/lib/api/reports'
export { settingsApi } from '@/lib/api/settings'
export type { ChunkPreviewRequestParams, DocumentLifecycleFilter } from '@/lib/api/document-helpers'
export type {
  ClipImageIndexRequest,
  ClipImageIndexResponse,
  ClipImageSearchRequest,
  ClipImageSearchResponse,
} from '@/lib/api/rag'

export type FrontendWebVitalReportRequest = {
  id: string
  name: 'LCP' | 'CLS' | 'FID' | 'INP'
  value: number
  rating?: string
  navigation_type?: string
  page?: string
}

export type FrontendWebVitalReportOptions = {
  keepalive?: boolean
  signal?: AbortSignal
}

export type FrontendTraceReportRequest = {
  event: string
  duration_ms: number
  component?: string
  page?: string
  input_node_count?: number
  input_link_count?: number
  output_node_count?: number
  output_link_count?: number
  active_filter_count?: number
}

// ==================== Health API ====================

export const healthApi = {
  async health(): Promise<HealthResponse> {
    return openapiRequest({ path: '/api/v1/health', method: 'get' })
  },
  async ready(): Promise<ReadyResponse> {
    return openapiRequest({ path: '/api/v1/health/ready', method: 'get' })
  },
}

// ==================== 文档管理 API ====================

export { documentApi } from '@/lib/api/documents'

// ==================== Parsing Workspace API ====================

export interface ParsingContentResponse {
  document_id: string
  parser_backend: string
  markdown_content: string
  original_markdown_content: string
  stats?: {
    page_count?: number
    table_count?: number
    image_count?: number
    block_count?: number
  } | null
  parse_duration_sec?: number | null
  pdf_quality?: {
    score: number
    text_quality_score: number
    format_consistency_score: number
    table_quality_score: number
    is_scanned: boolean
    page_count: number
  } | null
  quality_gate?: {
    grade: 'pass' | 'warn' | 'fail'
    reasons: string[]
    evidence?: Record<string, any>
  } | null
}

export interface ParsingContentUpdateRequest {
  markdown_content: string
  original_markdown_content?: string | null
}

export const parsingApi = {
  async listDocuments(params?: { skip?: number; limit?: number; status?: string }): Promise<{ total: number; items: Document[] }> {
    const { data } = await apiClient.get('/parsing/documents', { params })
    return data
  },

  async upload(file: File, options?: { parser_backend?: string }): Promise<Document> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('parser_backend', (options?.parser_backend || 'auto').toString())
    const { data } = await apiClient.post('/parsing/documents', formData)
    return data
  },

  async parse(
    documentId: string,
    options?: { parser_backend?: string; image_caption_enabled?: boolean; signal?: AbortSignal }
  ): Promise<ParsingContentResponse> {
    const params: Record<string, any> = {}
    if (options?.parser_backend) params.parser_backend = options.parser_backend
    if (options?.image_caption_enabled) params.image_caption_enabled = true
    const { data } = await apiClient.post(
      `/parsing/documents/${documentId}/parse`,
      null,
      {
        timeout: API_LONG_TIMEOUT_MS,
        signal: options?.signal,
        params: Object.keys(params).length ? params : undefined,
      }
    )
    return data
  },

  async getContent(documentId: string): Promise<ParsingContentResponse> {
    const { data } = await apiClient.get(`/parsing/documents/${documentId}/content`)
    return data
  },

  async updateContent(documentId: string, payload: ParsingContentUpdateRequest): Promise<ParsingContentResponse> {
    const { data } = await apiClient.patch(`/parsing/documents/${documentId}/content`, payload)
    return data
  },

  async delete(documentId: string): Promise<void> {
    await apiClient.delete(`/parsing/documents/${documentId}`)
  },
}

// ==================== Auth API ====================

export const authApiLegacy = {
  async register(payload: RegisterRequest): Promise<AuthResponse> {
    return openapiRequest({ path: '/api/v1/auth/register', method: 'post', body: payload })
  },
  async login(payload: LoginRequest): Promise<AuthResponse> {
    return openapiRequest({ path: '/api/v1/auth/login', method: 'post', body: payload })
  },
  async me(): Promise<UserProfile> {
    return openapiRequest({ path: '/api/v1/auth/me', method: 'get' })
  },
  async samlMetadata(params?: { provider_id?: string | null }): Promise<string> {
    const { data } = await apiClient.get('/auth/saml/metadata', { params, responseType: 'text' })
    return String(data ?? '')
  },
  async samlExchange(body: {
    provider_id?: string | null
    saml_response: string
    relay_state?: string | null
    acs_url?: string | null
  }) {
    const { data } = await apiClient.post('/auth/saml/exchange', body)
    return data
  },
}

// ==================== 解析/治理流水线 API ====================

function normalizeRegexRuleForApi(rule: { pattern: string; repl?: string; flags?: number }): {
  pattern: string
  repl: string
  flags: number
} {
  return {
    pattern: rule.pattern,
    repl: typeof rule.repl === 'string' ? rule.repl : '',
    flags: typeof rule.flags === 'number' ? rule.flags : 0,
  }
}

function normalizeGovernanceProfilePayload(payload: any): GovernanceProfileOut['payload'] {
  const p = (payload || {})
  const inputFormatsRaw = p.input_formats
  const input_formats =
    Array.isArray(inputFormatsRaw) && inputFormatsRaw.length > 0 ? inputFormatsRaw : ['markdown']
  const regex_rules = Array.isArray(p.regex_rules) ? p.regex_rules.map(normalizeRegexRuleForApi) : []

  return {
    version: typeof p.version === 'string' && p.version ? p.version : '1',
    extends: p.extends ?? null,
    input_formats,
    pipeline_patch: (p.pipeline_patch ?? {}),
    regex_rules,
  }
}

function normalizeGovernanceProfileOut(profile: any): GovernanceProfileOut {
  const pr = (profile || {})
  return { ...pr, payload: normalizeGovernanceProfilePayload(pr.payload) }
}

export const pipelineApiLegacy = {
  async getCapabilities(): Promise<PipelineCapabilitiesResponse> {
    const data = await openapiRequest({ path: '/api/v1/pipeline/capabilities', method: 'get' })
    return {
      ...data,
      pdf_backends: data.pdf_backends ?? [],
      chunk_strategies: data.chunk_strategies ?? [],
    }
  },

  async governanceAnalyze(params: GovernanceAnalyzeRequest): Promise<GovernanceAnalyzeResponse> {
    const body = {
      markdown: params.markdown,
      input_format: params.input_format ?? 'markdown',
      html_xpath: params.html_xpath ?? null,
      remove_images: params.remove_images ?? 'none',
      remove_control_chars: params.remove_control_chars ?? true,
      unwrap_lines: params.unwrap_lines ?? true,
      remove_common_lines: params.remove_common_lines ?? true,
      remove_boilerplate: params.remove_boilerplate ?? false,
      normalize_tables: params.normalize_tables ?? false,
      normalize_urls: params.normalize_urls ?? false,
      normalize_urls_strip_tracking: params.normalize_urls_strip_tracking ?? true,
      drop_outline_only: params.drop_outline_only ?? false,
      drop_outline_min_content_chars: params.drop_outline_min_content_chars ?? 200,
      drop_outline_max_heading_ratio: params.drop_outline_max_heading_ratio ?? 0.85,
      drop_low_density: params.drop_low_density ?? false,
      drop_low_density_threshold: params.drop_low_density_threshold ?? 0.12,
    }
    return openapiRequest({ path: '/api/v1/pipeline/governance-analyze', method: 'post', body })
  },

  async learnCommonLines(params: GovernanceCommonLinesLearnRequest): Promise<GovernanceCommonLinesLearnResponse> {
    const body = {
      dataset_id: params.dataset_id,
      limit_docs: params.limit_docs ?? 20,
      use_original: params.use_original ?? true,
      min_docs: params.min_docs ?? 3,
      min_ratio: params.min_ratio ?? 0.5,
      max_line_length: params.max_line_length ?? 120,
      max_candidates: params.max_candidates ?? 50,
    }
    const data = await openapiRequest({
      path: '/api/v1/pipeline/learn-common-lines',
      method: 'post',
      body,
      timeoutMs: API_LONG_TIMEOUT_MS,
    })
    return { ...data, candidates: data.candidates ?? [] }
  },

  async listGovernanceProfiles(params?: {
    q?: string
    include_builtin?: boolean
    limit?: number
  }): Promise<GovernanceProfileListResponse> {
    const data = await openapiRequest({
      path: '/api/v1/pipeline/governance-profiles',
      method: 'get',
      query: params,
    })
    return { ...data, items: data.items ?? [] }
  },

  async getGovernanceProfile(profileRef: string): Promise<GovernanceProfileOut> {
    const data = await openapiRequest({
      path: '/api/v1/pipeline/governance-profiles/{profile_ref}',
      method: 'get',
      pathParams: { profile_ref: profileRef },
    })
    return normalizeGovernanceProfileOut(data)
  },

  async getGovernanceProfileResolved(profileRef: string): Promise<GovernanceProfileResolvedResponse> {
    const data = await openapiRequest({
      path: '/api/v1/pipeline/governance-profiles/{profile_ref}/resolved',
      method: 'get',
      pathParams: { profile_ref: profileRef },
    })
    return {
      ...data,
      profile: normalizeGovernanceProfileOut(data.profile),
      chain: data.chain ?? [],
      effective: normalizeGovernanceProfilePayload(data.effective),
    }
  },

  async createGovernanceProfile(payload: GovernanceProfileCreate): Promise<GovernanceProfileOut> {
    const body = {
      ...payload,
      payload: {
        ...payload.payload,
        input_formats: payload.payload.input_formats ?? ['markdown'],
        pipeline_patch: payload.payload.pipeline_patch ?? {},
        regex_rules: (payload.payload.regex_rules ?? []).map(normalizeRegexRuleForApi),
      },
    }
    const data = await openapiRequest({
      path: '/api/v1/pipeline/governance-profiles',
      method: 'post',
      body,
    })
    return normalizeGovernanceProfileOut(data)
  },

  async updateGovernanceProfile(profileRef: string, payload: GovernanceProfileUpdate): Promise<GovernanceProfileOut> {
    const body = payload.payload
      ? {
          ...payload,
          payload: {
            ...payload.payload,
            input_formats: payload.payload.input_formats ?? ['markdown'],
            pipeline_patch: payload.payload.pipeline_patch ?? {},
            regex_rules: (payload.payload.regex_rules ?? []).map(normalizeRegexRuleForApi),
          },
        }
      : payload

    const data = await openapiRequest({
      path: '/api/v1/pipeline/governance-profiles/{profile_ref}',
      method: 'patch',
      pathParams: { profile_ref: profileRef },
      // `GovernanceProfileUpdate` in `web/types/index.ts` is a simplified helper type that allows
      // partial rule objects (repl/flags optional). OpenAPI requires repl/flags; we normalize above.
      body: body as any,
    })
    return normalizeGovernanceProfileOut(data)
  },

  async deleteGovernanceProfile(profileRef: string): Promise<void> {
    await openapiRequest({
      path: '/api/v1/pipeline/governance-profiles/{profile_ref}',
      method: 'delete',
      pathParams: { profile_ref: profileRef },
    })
  },

  async importGovernanceProfiles(file: File, overwrite = false): Promise<GovernanceProfileImportResponse> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('overwrite', overwrite ? 'true' : 'false')
    const data = await openapiRequest({
      path: '/api/v1/pipeline/governance-profiles/import',
      method: 'post',
      contentType: 'multipart/form-data',
      body: formData,
      timeoutMs: API_LONG_TIMEOUT_MS,
    })
    return { ...data, items: data.items ?? [] }
  },

  async exportGovernanceProfile(profileRef: string): Promise<Blob> {
    const { data } = await apiClient.get(`/pipeline/governance-profiles/${encodeURIComponent(profileRef)}/export`, {
      responseType: 'blob',
    })
    return data as Blob
  },

  async exportGovernanceProfileIngestionPolicy(profileRef: string): Promise<Blob> {
    const { data } = await apiClient.get(
      `/pipeline/governance-profiles/${encodeURIComponent(profileRef)}/export-ingestion-policy`,
      {
        responseType: 'blob',
      }
    )
    return data as Blob
  },

  async parsePreview(
    file: File,
    parserBackend = 'auto',
    options?: { signal?: AbortSignal }
  ): Promise<PipelineParsePreviewResponse> {
    const resolvedParser = resolveParserBackendForFilename(file.name, parserBackend)
    const formData = new FormData()
    formData.append('file', file)
    formData.append('parser_backend', resolvedParser.backend || 'auto')
    const { data } = await apiClient.post('/pipeline/parse-preview', formData, {
      timeout: API_LONG_TIMEOUT_MS,
      signal: options?.signal,
    })
    return data
  },

  async chunkPreview(params: PipelineChunkPreviewRequest): Promise<PipelineChunkPreviewResponse> {
    return openapiRequest({ path: '/api/v1/pipeline/chunk-preview', method: 'post', body: params })
  },

  async extractKeywords(params: KeywordExtractRequest): Promise<KeywordExtractResponse> {
    const body = { text: params.text, provider: params.provider ?? 'jieba', top_k: params.top_k ?? 10 }
    const data = await openapiRequest({ path: '/api/v1/pipeline/extract-keywords', method: 'post', body })
    return { ...data, keywords: data.keywords ?? [] }
  },

  async getCleanRules(): Promise<CleanRulesResponse> {
    return openapiRequest({ path: '/api/v1/pipeline/clean-rules', method: 'get' })
  },

  async cleanPreview(params: CleanPreviewRequest): Promise<CleanPreviewResponse> {
    let remove_images: 'none' | 'decorative' | 'all' = 'none'
    if (params.remove_images === 'decorative') {
      remove_images = 'decorative'
    } else if (params.remove_images === 'all') {
      remove_images = 'all'
    }
    const pii_mode: 'mask' | 'token' = params.pii_mode === 'token' ? 'token' : 'mask'
    const secrets_mode: 'mask' | 'token' = params.secrets_mode === 'token' ? 'token' : 'mask'

    const body = {
      markdown: params.markdown,
      rules: params.rules?.map(normalizeRegexRuleForApi),
      rule_packs: params.rule_packs,
      use_default_rules: params.use_default_rules ?? true,
      include_diff: params.include_diff ?? false,
      diff_max_lines: params.diff_max_lines ?? 2000,
      input_format: params.input_format ?? 'markdown',
      html_xpath: params.html_xpath ?? null,
      normalize_line_endings: params.normalize_line_endings ?? true,
      trim_trailing_spaces: params.trim_trailing_spaces ?? true,
      collapse_blank_lines: params.collapse_blank_lines ?? true,
      max_blank_lines: params.max_blank_lines ?? 1,
      remove_control_chars: params.remove_control_chars ?? true,
      remove_toc_lines: params.remove_toc_lines ?? true,
      remove_noise_lines: params.remove_noise_lines ?? true,
      remove_common_lines: params.remove_common_lines ?? true,
      unwrap_lines: params.unwrap_lines ?? true,
      remove_boilerplate: params.remove_boilerplate ?? false,
      remove_images,
      extract_frontmatter: params.extract_frontmatter ?? false,
      strip_frontmatter: params.strip_frontmatter ?? false,
      detect_language: params.detect_language ?? false,
      language_min_chars: params.language_min_chars ?? 40,
      normalize_urls: params.normalize_urls ?? false,
      normalize_urls_strip_tracking: params.normalize_urls_strip_tracking ?? true,
      drop_duplicate_paragraphs: params.drop_duplicate_paragraphs ?? false,
      drop_duplicate_paragraphs_min_occurrences: params.drop_duplicate_paragraphs_min_occurrences ?? 3,
      drop_duplicate_paragraphs_min_chars: params.drop_duplicate_paragraphs_min_chars ?? 40,
      drop_duplicate_paragraphs_max_chars: params.drop_duplicate_paragraphs_max_chars ?? 1200,
      trim_references: params.trim_references ?? false,
      extract_keywords: params.extract_keywords ?? false,
      keywords_provider: params.keywords_provider ?? 'auto',
      keywords_top_k: params.keywords_top_k ?? 10,
      keywords_max_chars: params.keywords_max_chars ?? 20000,
      normalize_tables: params.normalize_tables ?? false,
      strip_code_line_numbers: params.strip_code_line_numbers ?? false,
      pii_anonymize: params.pii_anonymize ?? false,
      pii_mode,
      pii_mask: params.pii_mask ?? '[REDACTED]',
      secrets_redact: params.secrets_redact ?? false,
      secrets_mode,
      secrets_mask: params.secrets_mask ?? '[SECRET]',
      drop_outline_only: params.drop_outline_only ?? false,
      drop_outline_min_content_chars: params.drop_outline_min_content_chars ?? 200,
      drop_outline_max_heading_ratio: params.drop_outline_max_heading_ratio ?? 0.85,
      drop_low_density: params.drop_low_density ?? false,
      drop_low_density_threshold: params.drop_low_density_threshold ?? 0.12,
      unwrap_max_line_length: params.unwrap_max_line_length ?? 120,
      noise_min_chars: params.noise_min_chars ?? 2,
      noise_ratio_threshold: params.noise_ratio_threshold ?? 0.2,
      common_lines_min_occurrences: params.common_lines_min_occurrences ?? 3,
    }

    return openapiRequest({ path: '/api/v1/pipeline/clean-preview', method: 'post', body })
  },

  async llmCleanPreview(params: LLMCleanPreviewRequest): Promise<LLMCleanPreviewResponse> {
    const body = { ...params, max_chars: params.max_chars ?? 15000 }
    return openapiRequest({ path: '/api/v1/pipeline/llm-clean-preview', method: 'post', body })
  },

  async uploadZipWithImages(params: { file: File; dataset_id: string; document_id?: string }): Promise<ZipWithImagesResponse> {
    const formData = new FormData()
    formData.append('file', params.file)
    formData.append('dataset_id', params.dataset_id)
    if (params.document_id) {
      formData.append('document_id', params.document_id)
    }
    const { data } = await apiClient.post('/pipeline/upload-zip-with-images', formData, {
      timeout: API_LONG_TIMEOUT_MS,
    })
    return data
  },

  async ingestionPreview(
    file: File,
    params: { dataset_id: string; parser_backend?: string; chunk_strategy?: string; diff_max_lines?: number }
  ): Promise<IngestionPreviewResponse> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('dataset_id', params.dataset_id)
    if (params.parser_backend) formData.append('parser_backend', params.parser_backend)
    if (params.chunk_strategy) formData.append('chunk_strategy', params.chunk_strategy)
    if (params.diff_max_lines != null) formData.append('diff_max_lines', String(params.diff_max_lines))
    const { data } = await apiClient.post('/pipeline/ingestion-preview', formData, { timeout: API_LONG_TIMEOUT_MS })
    return data
  },
}

// ==================== Governance API ====================

export const governanceApi = {
  async listRulePacks(): Promise<GovernanceRulePackListResponse> {
    const { data } = await apiClient.get('/governance/rule-packs')
    return data
  },

  async listStaleDocumentsByDataset(
    datasetId: string,
    params?: {
      mode?: 'overdue' | 'due_soon' | 'all'
      due_within_days?: number
      due_before?: string
      as_of?: string
      include_inactive?: boolean
      skip?: number
      limit?: number
      order_by?: 'review_due_at' | 'authority_level' | 'updated_at' | 'created_at' | 'filename'
      order_dir?: 'asc' | 'desc'
    }
  ): Promise<StaleDocumentsByDatasetResponse> {
    const { data } = await apiClient.get(`/governance/datasets/${encodeURIComponent(datasetId)}/stale-documents`, {
      params,
    })
    return data
  },
}

// ==================== Chunk Presets (Chunk Preview) API ====================

export const chunkPresetApi = {
  async list(params?: { q?: string; limit?: number; dataset_id?: string; include_global?: boolean }): Promise<ChunkPresetListResponse> {
    const { data } = await apiClient.get('/chunk-presets', { params })
    return data
  },

  async create(payload: ChunkPresetCreateRequest): Promise<ChunkPreset> {
    const { data } = await apiClient.post('/chunk-presets', payload)
    return data
  },

  async update(presetId: string, payload: ChunkPresetUpdateRequest): Promise<ChunkPreset> {
    const { data } = await apiClient.put(`/chunk-presets/${encodeURIComponent(presetId)}`, payload)
    return data
  },

  async delete(presetId: string): Promise<void> {
    await apiClient.delete(`/chunk-presets/${encodeURIComponent(presetId)}`)
  },
}

// ==================== Connectors API ====================

export const connectorApiLegacy = {
  async listConnectors(): Promise<ConnectorInfo[]> {
    return openapiRequest({ path: '/api/v1/connectors', method: 'get' })
  },

  async validateConfig(payload: ConnectorValidateRequest): Promise<ConnectorValidateResponse> {
    return openapiRequest({ path: '/api/v1/connectors/validate', method: 'post', body: payload })
  },

  async listConfigs(params?: {
    skip?: number
    limit?: number
    dataset_id?: string
    connector_id?: string
    enabled?: boolean
  }): Promise<ConnectorConfigListResponse> {
    return openapiRequest({ path: '/api/v1/connectors/configs', method: 'get', query: params })
  },

  async createConfig(payload: ConnectorConfigCreateRequest): Promise<ConnectorConfigOut> {
    return openapiRequest({ path: '/api/v1/connectors/configs', method: 'post', body: payload })
  },

  async updateConfig(configId: string, payload: ConnectorConfigUpdateRequest): Promise<ConnectorConfigOut> {
    return openapiRequest({
      path: '/api/v1/connectors/configs/{config_id}',
      method: 'put',
      pathParams: { config_id: configId },
      body: payload,
    })
  },

  async deleteConfig(configId: string): Promise<void> {
    await openapiRequest({
      path: '/api/v1/connectors/configs/{config_id}',
      method: 'delete',
      pathParams: { config_id: configId },
    })
  },

  async runConfig(configId: string): Promise<ConnectorRunOut> {
    return openapiRequest({
      path: '/api/v1/connectors/configs/{config_id}/run',
      method: 'post',
      pathParams: { config_id: configId },
    })
  },

  async reconcileConfig(
    configId: string,
    params?: { apply?: boolean; sample_limit?: number }
  ): Promise<Record<string, unknown>> {
    const { data } = await apiClient.post(
      `/connectors/configs/${encodeURIComponent(configId)}/reconcile`,
      undefined,
      { params, timeout: API_LONG_TIMEOUT_MS }
    )
    return data
  },

  async scheduledTick(): Promise<ConnectorScheduledTickResponse> {
    return openapiRequest({ path: '/api/v1/connectors/scheduled/tick', method: 'post' })
  },

  async createRun(payload: ConnectorRunCreateRequest): Promise<ConnectorRunOut> {
    return openapiRequest({ path: '/api/v1/connectors/runs', method: 'post', body: payload })
  },

  async listRuns(params?: { skip?: number; limit?: number; dataset_id?: string }): Promise<ConnectorRunListResponse> {
    return openapiRequest({ path: '/api/v1/connectors/runs', method: 'get', query: params })
  },

  async getRun(runId: string): Promise<ConnectorRunOut> {
    return openapiRequest({
      path: '/api/v1/connectors/runs/{run_id}',
      method: 'get',
      pathParams: { run_id: runId },
    })
  },

  async cancelRun(runId: string): Promise<ConnectorRunOut> {
    return openapiRequest({
      path: '/api/v1/connectors/runs/{run_id}/cancel',
      method: 'post',
      pathParams: { run_id: runId },
    })
  },

  async retryFailed(runId: string): Promise<ConnectorRunOut> {
    return openapiRequest({
      path: '/api/v1/connectors/runs/{run_id}/retry-failed',
      method: 'post',
      pathParams: { run_id: runId },
    })
  },

  async resumeRun(runId: string): Promise<ConnectorRunOut> {
    return openapiRequest({
      path: '/api/v1/connectors/runs/{run_id}/resume',
      method: 'post',
      pathParams: { run_id: runId },
    })
  },
}

// ==================== Ingestion Runs API ====================

export const ingestionRunApi = {
  async listRuns(params?: {
    skip?: number
    limit?: number
    dataset_id?: string
    status?: string
    kind?: string
  }): Promise<IngestionRunListResponse> {
    const { data } = await apiClient.get('/ingestion/runs', { params })
    return data
  },

  async getRun(runId: string): Promise<IngestionRunOut> {
    const { data } = await apiClient.get(`/ingestion/runs/${runId}`)
    return data
  },

  async compareRuns(runId: string, otherRunId: string): Promise<IngestionRunCompareResponse> {
    const { data } = await apiClient.get(`/ingestion/runs/${runId}/compare/${otherRunId}`)
    return data
  },

  async replayRun(runId: string): Promise<IngestionRunOut> {
    const { data } = await apiClient.post(`/ingestion/runs/${runId}/replay`)
    return data
  },

  async exportRunJson(runId: string): Promise<Blob> {
    const { data } = await apiClient.get(`/ingestion/runs/${runId}/export`, { responseType: 'blob' })
    return data
  },

  async exportRunHtml(runId: string): Promise<Blob> {
    const { data } = await apiClient.get(`/ingestion/runs/${runId}/export-html`, { responseType: 'blob' })
    return data
  },
}

// ==================== Retrieval Explain API ====================

export const retrievalApi = {
  async listProfiles(): Promise<Record<string, unknown>> {
    const { data } = await apiClient.get('/retrieval/profiles')
    return data
  },

  async explain(body: Record<string, unknown>): Promise<Record<string, unknown>> {
    const { data } = await apiClient.post('/retrieval/explain', body, { timeout: API_LONG_TIMEOUT_MS })
    return data
  },

  async configHash(body: Record<string, unknown>): Promise<Record<string, unknown>> {
    const { data } = await apiClient.post('/retrieval/config-hash', body)
    return data
  },
}

// ==================== Evidence Workbench (Ground Truth) ====================

export const evidenceApi = {
  async createSuite(payload: EvidenceSuiteCreate): Promise<EvidenceSuite> {
    return openapiRequest({ path: '/api/v1/evidence/suites', method: 'post', body: payload })
  },

  async listSuites(params?: {
    skip?: number
    limit?: number
    dataset_id?: string
    include_archived?: boolean
  }): Promise<EvidenceSuiteList> {
    return openapiRequest({ path: '/api/v1/evidence/suites', method: 'get', query: params })
  },

  async getSuite(suiteId: string): Promise<EvidenceSuite> {
    return openapiRequest({
      path: '/api/v1/evidence/suites/{suite_id}',
      method: 'get',
      pathParams: { suite_id: suiteId },
    })
  },

  async getSuiteDashboard(
    suiteId: string,
    params?: { include_archived_items?: boolean; top_n?: number; heatmap_top_n?: number }
  ): Promise<EvidenceSuiteDashboard> {
    return openapiRequest({
      path: '/api/v1/evidence/suites/{suite_id}/dashboard',
      method: 'get',
      pathParams: { suite_id: suiteId },
      query: params,
    })
  },

  async getSuiteHardcaseCandidates(
    suiteId: string,
    params?: {
      window_minutes?: number
      max_bytes?: number
      max_feedback_rows?: number
      max_candidates?: number
      max_rating?: number
      include_existing?: boolean
    }
  ): Promise<EvidenceHardcaseDiscovery> {
    return openapiRequest({
      path: '/api/v1/evidence/suites/{suite_id}/hardcase-candidates',
      method: 'get',
      pathParams: { suite_id: suiteId },
      query: params,
    })
  },

  async getSuiteDriftAudit(
    suiteId: string,
    params?: {
      include_archived_items?: boolean
      include_details?: boolean
      details_limit?: number
      slice_top_n?: number
    }
  ): Promise<EvidenceReferenceDriftAudit> {
    return openapiRequest({
      path: '/api/v1/evidence/suites/{suite_id}/drift-audit',
      method: 'get',
      pathParams: { suite_id: suiteId },
      query: params,
    })
  },

  async getDatasetDriftAudit(
    datasetId: string,
    params?: {
      include_archived_items?: boolean
      include_details?: boolean
      details_limit?: number
      slice_top_n?: number
    }
  ): Promise<EvidenceReferenceDriftAudit> {
    return openapiRequest({
      path: '/api/v1/evidence/datasets/{dataset_id}/drift-audit',
      method: 'get',
      pathParams: { dataset_id: datasetId },
      query: params,
    })
  },

  async repairSuiteReferenceSources(
    suiteId: string,
    payload: EvidenceReferenceRepairRequest
  ): Promise<EvidenceReferenceRepairResponse> {
    return openapiRequest({
      path: '/api/v1/evidence/suites/{suite_id}/repair-reference-sources',
      method: 'post',
      pathParams: { suite_id: suiteId },
      body: payload,
      timeoutMs: API_LONG_TIMEOUT_MS,
    })
  },

  async patchSuite(suiteId: string, payload: EvidenceSuitePatch): Promise<EvidenceSuite> {
    return openapiRequest({
      path: '/api/v1/evidence/suites/{suite_id}',
      method: 'patch',
      pathParams: { suite_id: suiteId },
      body: payload,
    })
  },

  async createItem(suiteId: string, payload: EvidenceItemCreate): Promise<EvidenceItem> {
    return openapiRequest({
      path: '/api/v1/evidence/suites/{suite_id}/items',
      method: 'post',
      pathParams: { suite_id: suiteId },
      body: { ...payload, suite_id: suiteId },
    })
  },

  async listItems(
    suiteId: string,
    params?: { skip?: number; limit?: number; status?: string }
  ): Promise<EvidenceItemList> {
    return openapiRequest({
      path: '/api/v1/evidence/suites/{suite_id}/items',
      method: 'get',
      pathParams: { suite_id: suiteId },
      query: params,
    })
  },

  async patchItem(itemId: string, payload: EvidenceItemPatch): Promise<EvidenceItem> {
    return openapiRequest({
      path: '/api/v1/evidence/items/{item_id}',
      method: 'patch',
      pathParams: { item_id: itemId },
      body: payload,
    })
  },

  async reviewItem(itemId: string): Promise<EvidenceItem> {
    return openapiRequest({
      path: '/api/v1/evidence/items/{item_id}/review',
      method: 'post',
      pathParams: { item_id: itemId },
    })
  },

  async approveItem(itemId: string): Promise<EvidenceItem> {
    return openapiRequest({
      path: '/api/v1/evidence/items/{item_id}/approve',
      method: 'post',
      pathParams: { item_id: itemId },
    })
  },

  async archiveItem(itemId: string): Promise<EvidenceItem> {
    return openapiRequest({
      path: '/api/v1/evidence/items/{item_id}/archive',
      method: 'post',
      pathParams: { item_id: itemId },
    })
  },

  async syncSuiteToRegression(suiteId: string): Promise<EvidenceSuiteSyncRegressionResponse> {
    return openapiRequest({
      path: '/api/v1/evidence/suites/{suite_id}/sync-regression',
      method: 'post',
      pathParams: { suite_id: suiteId },
    })
  },

  async exportSuite(suiteId: string, params?: { include_archived_items?: boolean }): Promise<EvidenceSuiteExportV1> {
    return openapiRequest({
      path: '/api/v1/evidence/suites/{suite_id}/export',
      method: 'get',
      pathParams: { suite_id: suiteId },
      query: params,
    })
  },

  async exportSuiteLtrTrainingBundleZip(
    suiteId: string,
    params?: { include_archived_items?: boolean; max_items?: number }
  ): Promise<Blob> {
    const { data } = await apiClient.get(`/evidence/suites/${suiteId}/export-ltr-training`, {
      params,
      responseType: 'blob',
      timeout: API_LONG_TIMEOUT_MS,
    })
    return data as Blob
  },

  async exportTrainingDataset(params: {
    dataset_id: string
    format?: 'jsonl' | 'csv'
    include_feedback?: boolean
    include_evidence?: boolean
    include_archived_evidence?: boolean
    max_rows_per_source?: number
  }): Promise<Blob> {
    const { data } = await apiClient.get('/evidence/training-export', {
      params,
      responseType: 'blob',
      timeout: API_LONG_TIMEOUT_MS,
    })
    return data as Blob
  },

  async importItems(
    suiteId: string,
    file: File,
    params?: { max_items?: number }
  ): Promise<EvidenceItemImportResponse> {
    const formData = new FormData()
    formData.append('file', file)
    const { data } = await apiClient.post(`/evidence/suites/${suiteId}/items/import`, formData, {
      params,
      timeout: API_LONG_TIMEOUT_MS,
    })
    return data
  },

  async persistCapsule(payload: {
    capsule: Record<string, unknown>
    capsule_id?: string | null
    overwrite?: boolean
  }): Promise<{ capsule_id: string; capsule_hash: string; path: string; overwritten: boolean }> {
    const { data } = await apiClient.post('/evidence/capsules', payload)
    return data
  },

  async getCapsule(capsuleId: string): Promise<{ capsule_id: string; capsule_hash: string; capsule: Record<string, unknown> }> {
    const { data } = await apiClient.get(`/evidence/capsules/${encodeURIComponent(capsuleId)}`)
    return data
  },

  async verifyCapsule(payload: {
    capsule: Record<string, unknown>
    capsule_id?: string | null
    overwrite?: boolean
  }): Promise<{ capsule_id?: string | null; valid: boolean; reason: string }> {
    const { data } = await apiClient.post('/evidence/capsules/verify', payload)
    return data
  },
}

// ==================== 数据集 API ====================

export const datasetApiLegacy = {
  /**
   * 创建数据集
   */
  async create(params: DatasetCreate): Promise<Dataset> {
    return openapiRequest({ path: '/api/v1/datasets/', method: 'post', body: params })
  },

  /**
   * 获取数据集列表
   */
  async list(params?: {
    skip?: number
    limit?: number
    category_id?: string
    include_descendants?: boolean
  }): Promise<DatasetListResponse> {
    return openapiRequest({ path: '/api/v1/datasets/', method: 'get', query: params })
  },

  /**
   * 获取数据集详情
   */
  async get(datasetId: string): Promise<Dataset> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}',
      method: 'get',
      pathParams: { dataset_id: datasetId },
    })
  },

  async getIngestionStats(datasetId: string): Promise<DatasetIngestionStats> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/ingestion/stats',
      method: 'get',
      pathParams: { dataset_id: datasetId },
    })
  },

  async getHealth(datasetId: string): Promise<DatasetHealthResponse> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/health',
      method: 'get',
      pathParams: { dataset_id: datasetId },
    })
  },

  /**
   * 更新数据集
   */
  async update(datasetId: string, params: DatasetUpdate): Promise<Dataset> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}',
      method: 'patch',
      pathParams: { dataset_id: datasetId },
      body: params,
    })
  },

  async getCategories(datasetId: string): Promise<DatasetCategoryAssignmentResponse> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/categories',
      method: 'get',
      pathParams: { dataset_id: datasetId },
    })
  },

  async setCategories(datasetId: string, payload: DatasetCategoryAssignmentRequest): Promise<DatasetCategoryAssignmentResponse> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/categories',
      method: 'put',
      pathParams: { dataset_id: datasetId },
      body: payload,
    })
  },

  /**
   * 删除数据集
   */
  async delete(datasetId: string): Promise<void> {
    await openapiRequest({
      path: '/api/v1/datasets/{dataset_id}',
      method: 'delete',
      pathParams: { dataset_id: datasetId },
    })
  },

  /**
   * 管理员生命周期操作：批量清空数据集文档（默认 dry-run）
   */
  async purge(
    datasetId: string,
    params?: { max_delete?: number; dry_run?: boolean }
  ): Promise<any> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/purge`, undefined, { params })
    return data
  },

  async getIngestionPolicy(datasetId: string): Promise<IngestionPolicy> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/ingestion-policy',
      method: 'get',
      pathParams: { dataset_id: datasetId },
    })
  },

  async updateIngestionPolicy(datasetId: string, policy: IngestionPolicy): Promise<IngestionPolicy> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/ingestion-policy',
      method: 'put',
      pathParams: { dataset_id: datasetId },
      body: policy,
    })
  },

  async importIngestionPolicy(datasetId: string, file: File, replace = true): Promise<IngestionPolicyImportResponse> {
    const formData = new FormData()
    formData.append('file', file)
    formData.append('replace', replace ? 'true' : 'false')
    const { data } = await apiClient.post(`/datasets/${datasetId}/ingestion-policy/import`, formData, { timeout: API_LONG_TIMEOUT_MS })
    return data
  },

  async exportIngestionPolicy(datasetId: string): Promise<Blob> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/ingestion-policy/export`, { responseType: 'blob' })
    return data as Blob
  },

  async listIngestionPolicyVersions(datasetId: string): Promise<IngestionPolicyVersionListResponse> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/ingestion-policy/versions',
      method: 'get',
      pathParams: { dataset_id: datasetId },
    })
  },

  async rollbackIngestionPolicy(datasetId: string, body: IngestionPolicyRollbackRequest): Promise<IngestionPolicy> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/ingestion-policy/rollback',
      method: 'post',
      pathParams: { dataset_id: datasetId },
      body,
    })
  },

  async exportConfig(datasetId: string): Promise<DatasetConfigExport> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/config/export',
      method: 'get',
      pathParams: { dataset_id: datasetId },
    })
  },

  async importConfig(datasetId: string, payload: DatasetConfigImportRequest): Promise<Dataset> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/config/import',
      method: 'post',
      pathParams: { dataset_id: datasetId },
      body: payload,
    })
  },

  async clone(datasetId: string, payload: DatasetCloneRequest): Promise<Dataset> {
    return openapiRequest({
      path: '/api/v1/datasets/{dataset_id}/clone',
      method: 'post',
      pathParams: { dataset_id: datasetId },
      body: payload,
    })
  },

  async exportDocumentsNdjson(
    datasetId: string,
    params?: {
      limit?: number
      after_created_at?: string
      after_id?: string
      include_sensitive?: boolean
      gzip?: boolean
    }
  ): Promise<Blob> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/documents/export`, { params, responseType: 'blob' })
    return data as Blob
  },

  async exportBundleZip(
    datasetId: string,
    params?: { limit?: number; include_sensitive?: boolean }
  ): Promise<Blob> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/export`, { params, responseType: 'blob' })
    return data as Blob
  },

  // ==================== Dataset Profile (Ingestion Scan) ====================

  async getProfileSummary(datasetId: string): Promise<DatasetProfileSummary> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/profile/summary`)
    return data
  },

  async listProfileFinding(
    datasetId: string,
    findingKey: string,
    params?: { skip?: number; limit?: number }
  ): Promise<DatasetProfileFindingListResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/profile/findings/${findingKey}`, { params })
    return data
  },

  async listProfileBucketDocuments(
    datasetId: string,
    params: {
      dimension: 'file_type' | 'language' | 'directory' | 'quality_bucket'
      bucket: string
      skip?: number
      limit?: number
      include_preview?: boolean
      preview_max_chars?: number
    }
  ): Promise<DatasetProfileDocumentListResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/profile/buckets/documents`, { params })
    return data
  },

  async startProfileScan(datasetId: string, body: DatasetProfileScanRunCreateRequest): Promise<DatasetProfileScanRunOut> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/profile/scan-runs`, body || {})
    return data
  },

  async listProfileScanRuns(
    datasetId: string,
    params?: { skip?: number; limit?: number }
  ): Promise<DatasetProfileScanRunListResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/profile/scan-runs`, { params })
    return data
  },

  async getProfileScanRun(datasetId: string, scanRunId: string): Promise<DatasetProfileScanRunOut> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/profile/scan-runs/${scanRunId}`)
    return data
  },

  async exportProfileSummary(datasetId: string): Promise<Blob> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/profile/export`, { responseType: 'blob' })
    return data as Blob
  },

  async exportProfileHtml(datasetId: string, params?: { redact?: boolean }): Promise<Blob> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/profile/export-html`, { params, responseType: 'blob' })
    return data as Blob
  },

  // ==================== Dataset Precheck (Local Folder Scan) ====================

  async startPrecheckScan(datasetId: string, body: DatasetPrecheckScanRunCreateRequest): Promise<DatasetPrecheckScanRunOut> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/precheck/scan-runs`, body || {})
    return data
  },

  async listPrecheckScanRuns(
    datasetId: string,
    params?: { skip?: number; limit?: number }
  ): Promise<DatasetPrecheckScanRunListResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs`, { params })
    return data
  },

  async getPrecheckScanRun(datasetId: string, scanRunId: string): Promise<DatasetPrecheckScanRunOut> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}`)
    return data
  },

  async getPrecheckSummary(datasetId: string, scanRunId: string): Promise<DatasetPrecheckSummary> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/summary`)
    return data
  },

  async listPrecheckFiles(
    datasetId: string,
    scanRunId: string,
    params?: { dir_prefix?: string; skip?: number; limit?: number }
  ): Promise<DatasetPrecheckFindingListResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/files`, { params })
    return data
  },

  async listPrecheckFinding(
    datasetId: string,
    scanRunId: string,
    findingKey: string,
    params?: { skip?: number; limit?: number }
  ): Promise<DatasetPrecheckFindingListResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/findings/${findingKey}`, { params })
    return data
  },

  async exportPrecheckSummary(datasetId: string, scanRunId: string): Promise<Blob> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/export`, { responseType: 'blob' })
    return data as Blob
  },

  async exportPrecheckHtml(datasetId: string, scanRunId: string, params?: { redact?: boolean }): Promise<Blob> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/export-html`, { params, responseType: 'blob' })
    return data as Blob
  },

  async cancelPrecheckScan(datasetId: string, scanRunId: string): Promise<DatasetPrecheckScanRunOut> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/cancel`)
    return data
  },

  async getPrecheckSamples(
    datasetId: string,
    scanRunId: string,
    params?: { size?: number; prefer_artifact?: boolean }
  ): Promise<DatasetPrecheckSamplesResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/samples`, { params })
    return data
  },

  async getPrecheckNearDups(datasetId: string, scanRunId: string): Promise<DatasetPrecheckNearDupResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/near-dups`)
    return data
  },

  async diffPrecheckScanRuns(
    datasetId: string,
    scanRunId: string,
    params: { base_scan_run_id: string }
  ): Promise<DatasetPrecheckDiffResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/diff`, { params })
    return data
  },

  async suggestPrecheckIngestionPolicy(
    datasetId: string,
    scanRunId: string,
    params?: { max_names_per_bucket?: number }
  ): Promise<DatasetPrecheckIngestionSuggestionResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/suggest-ingestion-policy`, { params })
    return data
  },

  async applyPrecheckIngestionPolicy(
    datasetId: string,
    scanRunId: string,
    params?: { replace?: boolean }
  ): Promise<IngestionPolicyImportResponse> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/apply-ingestion-policy`, undefined, { params })
    return data
  },

  // ==================== Dataset Tables (TAG) ====================

  async listTables(
    datasetId: string,
    params?: { skip?: number; limit?: number; include_columns?: boolean; include_sample_rows?: boolean }
  ): Promise<DatasetTablesListResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/tables`, { params })
    return data
  },

  async getTable(
    datasetId: string,
    tableId: string,
    params?: { include_columns?: boolean; include_sample_rows?: boolean }
  ): Promise<DatasetTableAsset> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/tables/${encodeURIComponent(tableId)}`, { params })
    return data
  },

  async previewTable(datasetId: string, tableId: string, params?: { limit?: number }): Promise<TableQueryResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/tables/${encodeURIComponent(tableId)}/preview`, { params })
    return data
  },

  async queryTable(datasetId: string, tableId: string, body: TableQueryRequest): Promise<TableQueryResponse> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/tables/${encodeURIComponent(tableId)}/query`, body)
    return data
  },

  async askTable(datasetId: string, tableId: string, body: TableAskRequest): Promise<TableAskResponse> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/tables/${encodeURIComponent(tableId)}/ask`, body, { timeout: API_LONG_TIMEOUT_MS })
    return data
  },

  async lotusSemFilter(datasetId: string, tableId: string, body: LotusSemFilterRequest): Promise<TableQueryResponse> {
    const { data } = await apiClient.post(`/datasets/${datasetId}/tables/${encodeURIComponent(tableId)}/lotus/sem-filter`, body, { timeout: API_LONG_TIMEOUT_MS })
    return data
  },

  // ==================== DB Catalog (SQL) ====================

  async listDbCatalogTables(
    datasetId: string,
    params?: { skip?: number; limit?: number; engine?: string; q?: string }
  ): Promise<DbCatalogTablesListResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/db-catalog/tables`, { params })
    return data
  },

  async getDbCatalogTable(datasetId: string, tableId: string): Promise<DbCatalogTableDetail> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/db-catalog/tables/${encodeURIComponent(tableId)}`)
    return data
  },

  async listDbCatalogProfiles(
    datasetId: string,
    params: { table_id: string; entitlement_hash?: string; skip?: number; limit?: number }
  ): Promise<DbProfileSnapshotListResponse> {
    const { data } = await apiClient.get(`/datasets/${datasetId}/db-catalog/profiles`, { params })
    return data
  },
}

// ==================== 数据集分类（目录树） API ====================

export const datasetCategoryApiLegacy = {
  async listTree(): Promise<DatasetCategoryTreeResponse> {
    return openapiRequest({ path: '/api/v1/dataset-categories/', method: 'get' })
  },

  async create(payload: DatasetCategoryCreate): Promise<DatasetCategoryOut> {
    return openapiRequest({ path: '/api/v1/dataset-categories/', method: 'post', body: payload })
  },

  async update(categoryId: string, payload: DatasetCategoryUpdate): Promise<DatasetCategoryOut> {
    return openapiRequest({
      path: '/api/v1/dataset-categories/{category_id}',
      method: 'patch',
      pathParams: { category_id: categoryId },
      body: payload,
    })
  },

  async move(categoryId: string, payload: DatasetCategoryMoveRequest): Promise<DatasetCategoryOut> {
    return openapiRequest({
      path: '/api/v1/dataset-categories/{category_id}/move',
      method: 'post',
      pathParams: { category_id: categoryId },
      body: payload,
    })
  },

  async delete(categoryId: string): Promise<void> {
    await openapiRequest({
      path: '/api/v1/dataset-categories/{category_id}',
      method: 'delete',
      pathParams: { category_id: categoryId },
    })
  },
}

// ==================== Reports API ====================

export const reportApiLegacy = {
  async getDatasetReport(
    datasetId: string,
    params?: { pipeline_hash?: string; connector_runs_limit?: number }
  ): Promise<DatasetReport> {
    const { data } = await apiClient.get(`/reports/datasets/${datasetId}`, { params })
    return data
  },

  async exportDatasetReportJson(
    datasetId: string,
    params?: { pipeline_hash?: string; connector_runs_limit?: number }
  ): Promise<Blob> {
    const { data } = await apiClient.get(`/reports/datasets/${datasetId}/export`, { params, responseType: 'blob' })
    return data as Blob
  },

  async exportDatasetReportHtml(
    datasetId: string,
    params?: { pipeline_hash?: string; connector_runs_limit?: number; redact?: boolean }
  ): Promise<Blob> {
    const { data } = await apiClient.get(`/reports/datasets/${datasetId}/export-html`, { params, responseType: 'blob' })
    return data as Blob
  },

  async exportDatasetRagAuditHtml(
    datasetId: string,
    params?: { pipeline_hash?: string; connector_runs_limit?: number; redact?: boolean }
  ): Promise<Blob> {
    const { data } = await apiClient.get(`/reports/datasets/${datasetId}/rag-audit/export-html`, { params, responseType: 'blob' })
    return data as Blob
  },

  async exportDatasetReportBundleZip(
    datasetId: string,
    params?: { pipeline_hash?: string; connector_runs_limit?: number; redact?: boolean }
  ): Promise<Blob> {
    const { data } = await apiClient.get(`/reports/datasets/${datasetId}/export-bundle`, { params, responseType: 'blob' })
    return data as Blob
  },
}

// ==================== SSE helpers (scan progress) ====================

export const sseApi = {
  async streamPrecheckScanEvents(
    datasetId: string,
    scanRunId: string,
    onJson: (jsonStr: string) => void,
    options: { onError?: (error: unknown) => void; signal?: AbortSignal } = {}
  ): Promise<{ requestId: string }> {
    const requestId = generateRequestId()

    const response = await fetch(`${API_V1_BASE_URL}/datasets/${datasetId}/precheck/scan-runs/${scanRunId}/events`, {
      method: 'GET',
      headers: withPreferredLanguageHeader({
        Accept: 'text/event-stream',
        ...getAuthHeaders(),
        'X-Request-ID': requestId,
      }),
      signal: options.signal,
    })

    if (!response.ok) {
      throw await buildFetchError(response, 'Precheck SSE failed')
    }

    const reader = response.body?.getReader()
    if (!reader) {
      throw new Error('No response body')
    }

    const backendRequestId = response.headers.get('X-Request-ID') || requestId
    await readSseDataStrings(reader, onJson, options.onError)
    return { requestId: backendRequestId }
  },
}

// ==================== 反馈 API ====================

export const feedbackApi = {
  /**
   * 提交消息反馈
   */
  async create(params: MessageFeedbackCreate): Promise<MessageFeedback> {
    const { data } = await apiClient.post('/feedback/messages', params)
    return data
  },

  /**
   * 获取反馈列表
   */
  async list(params?: {
    skip?: number
    limit?: number
    message_id?: string
  }): Promise<MessageFeedbackListResponse> {
    const { data } = await apiClient.get('/feedback/messages', { params })
    return data
  },

  /**
   * 获取反馈列表（联表包含消息内容/对话标题，用于质检面板）
   */
  async listEnriched(params?: {
    skip?: number
    limit?: number
    conversation_id?: string
    message_id?: string
    min_rating?: number
    max_rating?: number
  }, options?: ApiRequestOptions): Promise<MessageFeedbackEnrichedListResponse> {
    const { data } = await apiClient.get('/feedback/messages/enriched', { params, signal: options?.signal })
    return data
  },

  /**
   * 将反馈转为回归用例（RAGAS regression case）
   */
  async toRegressionCase(
    feedbackId: string,
    body: { include_document_scope?: boolean; tags?: string[]; extra?: Record<string, any> } = {}
  ): Promise<RegressionCase> {
    const { data } = await apiClient.post(`/feedback/messages/${feedbackId}/to-regression-case`, body)
    return data
  },

  /**
   * 将反馈转为 Evidence Workbench 条目（Ground Truth）
   */
  async toEvidenceItem(
    feedbackId: string,
    body: { suite_id: string; tags?: string[]; extra?: Record<string, any> }
  ): Promise<EvidenceItem> {
    const { data } = await apiClient.post(`/feedback/messages/${feedbackId}/to-evidence-item`, body)
    return data
  },
}

// ==================== KG API ====================

export const kgApiLegacy = {
  /**
   * 触发 KG 实体/事件抽取
   */
  async extract(
    documentId: string,
    params?: {
      async?: boolean
      pipeline_hash?: string
      replace_existing?: boolean
      prune_orphan_entities?: boolean
      prompt_template_id?: string
      prompt_template_key?: string
      prompt_ab_experiment_key?: string
    }
  ): Promise<KGExtractResponse> {
    const { data } = await apiClient.post(`/kg/documents/${documentId}/extract`, null, { params })
    return data
  },

  async deleteDocumentKG(
    documentId: string,
    params?: { prune_orphan_entities?: boolean }
  ): Promise<KGDeleteResponse> {
    const { data } = await apiClient.delete(`/kg/documents/${documentId}`, { params })
    return data
  },

  /**
   * KG 搜索
   */
  async search(params: KGSearchRequest): Promise<KGSearchResponse> {
    const { data } = await apiClient.post('/kg/search', params)
    return data
  },

  async getStats(params?: { document_ids?: string[]; pipeline_hash?: string }): Promise<KGStatsResponse> {
    const { data } = await apiClient.get('/kg/stats', { params })
    return data
  },

  async getGraph(params?: {
    document_ids?: string[]
    pipeline_hash?: string
    max_events?: number
    max_entities?: number
    max_links?: number
    include_entity_links?: boolean
    include_relation_links?: boolean
    min_shared_events?: number
    max_entity_links?: number
  }): Promise<KGGraphResponse> {
    const { data } = await apiClient.get('/kg/graph', { params })
    return data
  },

  async expandGraph(params: {
    node_id: string
    document_ids?: string[]
    pipeline_hash?: string
    max_events?: number
    max_entities?: number
    max_links?: number
    include_entity_links?: boolean
    include_relation_links?: boolean
    min_shared_events?: number
    max_entity_links?: number
  }): Promise<KGGraphResponse> {
    const { data } = await apiClient.get('/kg/graph/expand', { params })
    return data
  },

  async exportGraphML(params?: {
    document_ids?: string[]
    pipeline_hash?: string
    max_events?: number
    max_entities?: number
    max_links?: number
    include_entity_links?: boolean
    include_relation_links?: boolean
    min_shared_events?: number
    max_entity_links?: number
  }): Promise<string> {
    const { data } = await apiClient.get('/kg/graph/export', {
      params,
      responseType: 'text',
    })
    return data as unknown as string
  },

  async exportSnapshot(params: { pipeline_hash: string; document_ids?: string[] }): Promise<any> {
    const { data } = await apiClient.get('/kg/snapshots/export', { params })
    return data
  },

  async diffSnapshots(body: { snapshot_a: Record<string, any>; snapshot_b: Record<string, any> }): Promise<any> {
    const { data } = await apiClient.post('/kg/snapshots/diff', body)
    return data
  },

  async compareSnapshots(params: {
    pipeline_hash_a: string
    pipeline_hash_b: string
    document_ids?: string[]
  }): Promise<any> {
    const { data } = await apiClient.get('/kg/snapshots/compare', { params })
    return data
  },

  async getEvent(
    eventId: string,
    params?: { document_ids?: string[]; pipeline_hash?: string }
  ): Promise<KGEventDetailResponse> {
    const { data } = await apiClient.get(`/kg/events/${eventId}`, { params })
    return data
  },

  async getEntity(
    entityId: string,
    params?: { document_ids?: string[]; pipeline_hash?: string; max_events?: number; max_neighbors?: number }
  ): Promise<KGEntityDetailResponse> {
    const { data } = await apiClient.get(`/kg/entities/${entityId}`, { params })
    return data
  },

  async listEntityAliases(entityId: string): Promise<KGEntityAliasesResponse> {
    const { data } = await apiClient.get(`/kg/entities/${entityId}/aliases`)
    return data
  },

  async createEntityAlias(entityId: string, body: KGEntityAliasCreateRequest): Promise<KGEntityAliasItem> {
    const { data } = await apiClient.post(`/kg/entities/${entityId}/aliases`, body)
    return data
  },

  async deleteEntityAlias(entityId: string, aliasId: string): Promise<KGEntityAliasesResponse> {
    const { data } = await apiClient.delete(`/kg/entities/${entityId}/aliases/${aliasId}`)
    return data
  },

  async suggestEntityAliases(
    entityId: string,
    params?: { mode?: string; k?: number; min_similarity?: number }
  ): Promise<KGEntityAliasSuggestionsResponse> {
    const { data } = await apiClient.get(`/kg/entities/${entityId}/alias_suggestions`, { params })
    return data
  },

  async listPredicateOntology(): Promise<KGPredicateOntologyListResponse> {
    const { data } = await apiClient.get('/kg/ontology/predicates')
    return data
  },

  async upsertPredicateOntology(body: KGPredicateOntologyCreateRequest): Promise<KGPredicateOntologyItem> {
    const { data } = await apiClient.post('/kg/ontology/predicates', body)
    return data
  },

  async updatePredicateOntology(
    predicateId: string,
    body: KGPredicateOntologyUpdateRequest
  ): Promise<KGPredicateOntologyItem> {
    const { data } = await apiClient.patch(`/kg/ontology/predicates/${predicateId}`, body)
    return data
  },

  async deletePredicateOntology(predicateId: string): Promise<KGPredicateOntologyListResponse> {
    const { data } = await apiClient.delete(`/kg/ontology/predicates/${predicateId}`)
    return data
  },

  async previewMergeEntities(body: KGEntityMergeRequest): Promise<KGEntityMergePreviewResponse> {
    const { data } = await apiClient.post('/kg/entities/merge/preview', body)
    return data
  },

  async mergeEntities(body: KGEntityMergeRequest): Promise<KGEntityMergeResponse> {
    const { data } = await apiClient.post('/kg/entities/merge', body)
    return data
  },

  async splitEntity(body: KGEntitySplitRequest): Promise<KGEntitySplitResponse> {
    const { data } = await apiClient.post('/kg/entities/split', body)
    return data
  },

  async undoResolutionAction(actionId: string): Promise<KGEntityResolutionUndoResponse> {
    const { data } = await apiClient.post(`/kg/entities/resolution/actions/${actionId}/undo`)
    return data
  },

  async searchGraphNodes(params: {
    q: string
    kind?: string
    limit?: number
    document_ids?: string[]
    pipeline_hash?: string
  }): Promise<KGGraphNode[]> {
    const { data } = await apiClient.get('/kg/graph/search', { params })
    return data
  },
}

// ==================== 设置 API ====================

export interface FeatureFlags {
  kg_enabled: boolean
  deepdoc_enabled: boolean
  docling_enabled: boolean
  etl4llm_enabled: boolean
  marker_enabled: boolean
  paddle_vl_enabled: boolean
  markitdown_enabled: boolean
  llama_index_enabled: boolean
  mineru_enabled: boolean
  magicpdf_enabled: boolean
}

export interface KGConfig {
  chat_enabled: boolean
  extract_prompt_template_id: string
  extract_prompt_template_key: string
  extract_prompt_ab_experiment_key: string
  extract_replace_existing: boolean
  extract_prune_orphan_entities: boolean
}

export interface LLMConfig {
  api_key: string
  api_base: string
  model: string
  temperature: number
  timeout: number
  max_retries: number
}

export interface EmbeddingConfig {
  provider: string
  model: string
  api_key: string
  api_base: string
}

export interface MilvusConfig {
  host: string
  port: number
  user: string
  password: string
  collection_name: string
}

export interface RAGConfig {
  chunk_size: number
  chunk_overlap: number
  chunk_min_chars: number
  retrieval_top_k: number
  similarity_threshold: number
  default_parser_backend: string
  default_chunk_strategy: string
  bm25_index_enabled: boolean
  enable_reranker: boolean
}

export interface CacheConfig {
  upload_dedup_enabled: boolean
  chat_response_cache_enabled: boolean
  chat_response_cache_ttl_sec: number
  chat_response_cache_max_value_bytes: number
  chat_response_cache_require_empty_history: boolean
}

export interface UrlIngestConfig {
  enabled: boolean
  max_bytes: number
  timeout_sec: number
  allow_private_ips: boolean
  follow_redirects: boolean
}

export interface GovernanceConfig {
  enabled: boolean
  pii_anonymize: boolean
  secrets_redact: boolean
  quarantine_on_drop: boolean
}

export interface MinerUConfig {
  api_token: string
  api_base: string
  model_version: string
}

export interface Etl4LlmConfig {
  api_url: string
  timeout_sec: number
  mode: string
  force_ocr: boolean
  enable_formula: boolean
  extract_images: boolean
  filter_page_header_footer: boolean
}

export interface MarkerConfig {
  api_url: string
  timeout_sec: number
}

export interface PaddleVLConfig {
  api_url: string
  timeout_sec: number
}

export interface MagicPDFConfig {
  cli: string
  method: string
  lang: string
  debug: boolean
  timeout_sec: number
  keep_artifacts: boolean
}

export interface ObservabilityConfig {
  tool_call_log_enabled: boolean
  tool_call_log_include_preview: boolean
  tool_call_log_max_preview_chars: number
  agent_log_enabled: boolean
  agent_log_include_execution_path: boolean
  agent_log_max_preview_chars: number
  metrics_log_enabled: boolean
  metrics_log_include_text: boolean
}

export interface SafetyConfig {
  pii_redaction_enabled: boolean
  pii_redaction_mask: string
  pii_stream_holdback_chars: number
}

export interface ChatConfig {
  stream_heartbeat_sec: number
  stream_cancel_on_disconnect: boolean
}

export interface LangGraphConfig {
  use_subgraphs: boolean
}

export interface SystemSettings {
  feature_flags: FeatureFlags
  kg: KGConfig
  llm: LLMConfig
  embedding: EmbeddingConfig
  milvus: MilvusConfig
  rag: RAGConfig
  cache: CacheConfig
  url_ingest: UrlIngestConfig
  governance: GovernanceConfig
  mineru: MinerUConfig
  etl4llm: Etl4LlmConfig
  marker: MarkerConfig
  paddle_vl: PaddleVLConfig
  magicpdf: MagicPDFConfig
  observability: ObservabilityConfig
  safety: SafetyConfig
  chat: ChatConfig
  langgraph: LangGraphConfig
}

export interface ParserBackendStatus {
  enabled: boolean
  available: boolean
  message: string
}

export interface SystemStatus {
  database: { connected: boolean; message: string }
  milvus: { connected: boolean; message: string }
  llm: { configured: boolean; model: string }
  embedding: { configured: boolean; model: string }
  parsers?: Record<string, ParserBackendStatus>
}

export interface TestLLMRequest {
  api_key: string
  api_base: string
  model: string
  temperature?: number
  timeout?: number
  max_retries?: number
}

export interface TestLLMResponse {
  success: boolean
  message: string
}

export type BackendMeta = MetaResponse

export const metaApi = {
  async get(): Promise<BackendMeta> {
    return openapiRequest({ path: '/api/v1/meta', method: 'get' })
  },
}

export const observabilityApiLegacy = {
  async reportFrontendVital(
    payload: FrontendWebVitalReportRequest,
    options: FrontendWebVitalReportOptions = {}
  ): Promise<void> {
    const requestId = generateRequestId()
    const response = await fetch(`${API_V1_BASE_URL}/observability/frontend-vitals`, {
      method: 'POST',
      headers: withPreferredLanguageHeader({
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
        'X-Request-ID': requestId,
      }),
      body: JSON.stringify(payload),
      keepalive: options.keepalive === true,
      signal: options.signal,
    })

    if (!response.ok) {
      throw await buildFetchError(response, 'Frontend vital report failed')
    }
  },

  async reportFrontendTrace(
    payload: FrontendTraceReportRequest,
    options: FrontendWebVitalReportOptions = {}
  ): Promise<void> {
    const requestId = generateRequestId()
    const response = await fetch(`${API_V1_BASE_URL}/observability/frontend-traces`, {
      method: 'POST',
      headers: withPreferredLanguageHeader({
        'Content-Type': 'application/json',
        ...getAuthHeaders(),
        'X-Request-ID': requestId,
      }),
      body: JSON.stringify(payload),
      keepalive: options.keepalive === true,
      signal: options.signal,
    })

    if (!response.ok) {
      throw await buildFetchError(response, 'Frontend trace report failed')
    }
  },

  async getRagMetricsSummary(params: { window_minutes?: number; max_bytes?: number }): Promise<RagMetricsSummaryResponse> {
    const { data } = await apiClient.get('/observability/rag-metrics/summary', { params })
    return data
  },

  async getOnlineQualitySummary(params: {
    window_minutes?: number
    bucket_minutes?: number
    max_bytes?: number
  }): Promise<OnlineQualitySummaryResponse> {
    const { data } = await apiClient.get('/observability/online-quality/summary', { params })
    return data
  },

  async getQuerysetHealthRuns(params: { limit?: number; profile_hash?: string } = {}): Promise<QuerysetHealthRunsResponse> {
    const { data } = await apiClient.get('/observability/queryset-health/runs', { params })
    return data
  },

  async getQuerysetHealthDiff(params: {
    baseline_generated_at: string
    current_generated_at: string
    max_hard_case_ids?: number
  }): Promise<QuerysetHealthDiffResponse> {
    const { data } = await apiClient.get('/observability/queryset-health/diff', { params })
    return data
  },

  async getRagQueryAnalytics(params: {
    window_minutes?: number
    slow_threshold_sec?: number
    top_n?: number
    max_bytes?: number
  }): Promise<RagQueryAnalyticsResponse> {
    const { data } = await apiClient.get('/observability/rag-metrics/query-analytics', { params })
    return data
  },

  async getRagCostAttribution(params: { window_minutes?: number; max_bytes?: number }): Promise<RagCostAttributionResponse> {
    const { data } = await apiClient.get('/observability/rag-metrics/cost-attribution', { params })
    return data
  },

  async getRagMetricsTail(params: { window_minutes?: number; max_bytes?: number }): Promise<ArrayBuffer> {
    const { data } = await apiClient.get('/observability/rag-metrics/tail', { params, responseType: 'arraybuffer' })
    return data
  },

  async getDepsDiagnosticsSnapshot(): Promise<DepsDiagnosticsResponse> {
    const { data } = await apiClient.get('/observability/diagnostics/deps')
    return data
  },

	  async getRagTraceBundle(params: { request_id: string; window_minutes?: number; max_bytes?: number }): Promise<RagTraceBundleResponse> {
	    const { data } = await apiClient.get('/observability/rag-metrics/trace-bundle', { params })
	    return data
	  },

	  async getRagTraceBundleDiff(params: {
	    request_id_a: string
	    request_id_b: string
	    window_minutes?: number
	    max_bytes?: number
	  }): Promise<RagTraceBundleDiffResponse> {
	    const { data } = await apiClient.get('/observability/rag-metrics/trace-bundle/diff', { params })
	    return data
	  },

	  async getOpsConfigSnapshot(): Promise<OpsConfigSnapshotResponse> {
	    const { data } = await apiClient.get('/observability/config/snapshot')
	    return data
	  },

	  async getPeriodicJobFreshness(): Promise<PeriodicJobFreshnessResponse> {
	    const { data } = await apiClient.get('/observability/periodic-jobs/freshness')
	    return data
	  },

	  async getTaskQueueSnapshot(params: { force_refresh?: boolean } = {}): Promise<TaskQueueObservabilitySnapshotResponse> {
	    const { data } = await apiClient.get('/observability/task-queue/snapshot', { params })
	    return data
	  },

	  async getSloSnapshot(): Promise<SloSnapshotResponse> {
	    const { data } = await apiClient.get('/observability/slo/snapshot')
	    return data
	  },

  async getIngestionDashboardSummary(params: {
    window_hours?: number
    bucket_minutes?: number
    dataset_id?: string
  } = {}): Promise<IngestionDashboardSummaryResponse> {
    const { data } = await apiClient.get('/observability/ingestion/summary', { params })
    return data
  },

  async getIndexAudit(params: {
    dataset_id: string
    max_check_ids?: number
    milvus_list_limit?: number
    sample_limit?: number
  }): Promise<IndexAuditResponse> {
    const { data } = await apiClient.get('/observability/index-audit', { params })
    return data
  },

  async getEmbeddingDriftSnapshot(params: {
    dataset_id?: string
    document_id?: string
    sample_n?: number
    drift_threshold?: number
  } = {}): Promise<Record<string, unknown>> {
    const { data } = await apiClient.get('/observability/embedding-drift/snapshot', { params })
    return data
  },

  async runPerfSuite(payload: { iterations?: number; timeout_sec?: number } = {}): Promise<Record<string, unknown>> {
    const { data } = await apiClient.post('/observability/perf-suite/run', {
      iterations: payload.iterations ?? 10,
      timeout_sec: payload.timeout_sec ?? 2,
    })
    return data
  },

  async invalidateDatasetCache(datasetId: string): Promise<Record<string, unknown>> {
    const { data } = await apiClient.post(
      `/observability/cache/datasets/${encodeURIComponent(datasetId)}/invalidate`
    )
    return data
  },

  async listIndexDrift(params: { dataset_id?: string; status?: string; limit?: number } = {}): Promise<Record<string, unknown>> {
    const { data } = await apiClient.get('/observability/index-drift', { params })
    return data
  },

  async resolveIndexDrift(itemId: string, payload: { resolution_note?: string } = {}): Promise<Record<string, unknown>> {
    const { data } = await apiClient.post(`/observability/index-drift/${encodeURIComponent(itemId)}/resolve`, {
      resolution_note: payload.resolution_note ?? '',
    })
    return data
  },
}

export const usageApi = {
  async getChatTokenUsageSummary(params: { window_days?: number; since?: string; until?: string } = {}): Promise<ChatTokenUsageSummary> {
    const { data } = await apiClient.get('/usage/chat/tokens/summary', { params })
    return data
  },

  async getChatCostUsageSummary(params: { window_days?: number; since?: string; until?: string } = {}): Promise<ChatCostUsageSummary> {
    const { data } = await apiClient.get('/usage/chat/cost/summary', { params })
    return data
  },

  async getChatTokenQuotaStatus(): Promise<ChatTokenQuotaStatus> {
    const { data } = await apiClient.get('/usage/chat/tokens/quota')
    return data
  },

  async getTenantQuotaSummary(): Promise<TenantQuotaSummary> {
    const { data } = await apiClient.get('/usage/tenant/quotas')
    return data
  },
}

export const auditApi = {
  async listLogs(params: {
    skip?: number
    limit?: number
    actor_id?: string
    action?: string
    resource_type?: string
    resource_id?: string
    request_id?: string
    since?: string
    until?: string
  } = {}): Promise<AuditLogListResponse> {
    const { data } = await apiClient.get('/audit/logs', { params })
    return data
  },

  async exportLogs(params: {
    limit?: number
    actor_id?: string
    action?: string
    resource_type?: string
    resource_id?: string
    request_id?: string
    since?: string
    until?: string
    after_created_at?: string
    after_id?: string
    include_sensitive?: boolean
    gzip?: boolean
  } = {}): Promise<Blob> {
    const { data } = await apiClient.get('/audit/logs/export', { params, responseType: 'blob' })
    return data as Blob
  },

  async purgeLogs(params: { retention_days?: number; max_delete?: number; dry_run?: boolean } = {}): Promise<any> {
    const { data } = await apiClient.post('/audit/logs/purge', undefined, { params })
    return data
  },

  async exportAccessGraph(params: {
    limit?: number
    after_kind?: string
    after_created_at?: string
    after_id?: string
    include_sensitive?: boolean
    export_format?: 'ndjson' | 'json'
    gzip?: boolean
  } = {}): Promise<Blob> {
    const { data } = await apiClient.get('/audit/access-graph/export', { params, responseType: 'blob' })
    return data as Blob
  },

  async exportAccessGraphPage(params: {
    limit?: number
    after_kind?: string
    after_created_at?: string
    after_id?: string
    include_sensitive?: boolean
    export_format?: 'ndjson' | 'json'
    gzip?: boolean
  } = {}): Promise<{
    blob: Blob
    nextCursor: { after_kind: string; after_created_at: string; after_id: string } | null
  }> {
    const resp = await apiClient.get('/audit/access-graph/export', { params, responseType: 'blob' })
    const headers: Record<string, any> = (resp as any)?.headers || {}
    const raw = headers['x-next-cursor'] || headers['X-Next-Cursor'] || ''
    let nextCursor: { after_kind: string; after_created_at: string; after_id: string } | null = null
    if (raw) {
      try {
        const obj = JSON.parse(String(raw))
        if (obj && typeof obj === 'object' && obj.after_kind && obj.after_created_at && obj.after_id) {
          nextCursor = {
            after_kind: String(obj.after_kind),
            after_created_at: String(obj.after_created_at),
            after_id: String(obj.after_id),
          }
        }
      } catch {
        // Ignore cursor parse errors; callers can treat it as "no more pages".
      }
    }
    return { blob: resp.data as Blob, nextCursor }
  },

  async getAccessGraphSummary(): Promise<any> {
    const { data } = await apiClient.get('/audit/access-graph/summary')
    return data
  },
}

// ==================== RBAC API ====================

export interface TenantMember {
  id: string
  tenant_id: string
  user_id?: string | null
  role: string
  is_current: boolean
  created_at?: string | null
  updated_at?: string | null
}

export interface TenantMemberListResponse {
  total: number
  items: TenantMember[]
}

export const rbacApi = {
  async listTenantMembers(params: { skip?: number; limit?: number } = {}): Promise<TenantMemberListResponse> {
    const { data } = await apiClient.get('/rbac/members', { params })
    return data
  },

  async patchTenantMemberRole(userId: string, payload: { role: string }): Promise<TenantMember> {
    const { data } = await apiClient.patch(`/rbac/members/${encodeURIComponent(userId)}`, payload)
    return data
  },
}

// ==================== Groups API ====================

export const groupApi = {
  async listGroups(params: { skip?: number; limit?: number } = {}): Promise<TenantGroupListResponse> {
    const { data } = await apiClient.get('/groups', { params })
    return data
  },

  async createGroup(payload: TenantGroupCreateRequest): Promise<TenantGroupOut> {
    const { data } = await apiClient.post('/groups', payload)
    return data
  },

  async getGroup(groupId: string): Promise<TenantGroupOut> {
    const { data } = await apiClient.get(`/groups/${encodeURIComponent(groupId)}`)
    return data
  },

  async patchGroup(groupId: string, payload: TenantGroupUpdateRequest): Promise<TenantGroupOut> {
    const { data } = await apiClient.patch(`/groups/${encodeURIComponent(groupId)}`, payload)
    return data
  },

  async deleteGroup(groupId: string): Promise<void> {
    await apiClient.delete(`/groups/${encodeURIComponent(groupId)}`)
  },

  async listGroupMembers(
    groupId: string,
    params: { skip?: number; limit?: number } = {}
  ): Promise<TenantGroupMemberListResponse> {
    const { data } = await apiClient.get(`/groups/${encodeURIComponent(groupId)}/members`, { params })
    return data
  },

  async addGroupMembers(groupId: string, payload: TenantGroupMembersUpdateRequest): Promise<TenantGroupMembersUpdateResponse> {
    const { data } = await apiClient.post(`/groups/${encodeURIComponent(groupId)}/members`, payload)
    return data
  },

  async removeGroupMembers(
    groupId: string,
    payload: TenantGroupMembersUpdateRequest
  ): Promise<TenantGroupMembersUpdateResponse> {
    const { data } = await apiClient.post(`/groups/${encodeURIComponent(groupId)}/members/remove`, payload)
    return data
  },
}

// ==================== SCIM v2 API (Enterprise) ====================

function buildScimHeaders(scimToken: string, tenantId: string): Record<string, string> {
  const token = String(scimToken || '').trim()
  const tid = String(tenantId || '').trim()
  if (!token) throw new Error('SCIM token required')
  if (!tid) throw new Error('tenantId required')
  return {
    Authorization: `Bearer ${token}`,
    'X-Tenant-ID': tid,
    'Content-Type': 'application/scim+json',
  }
}

export const scimApi = {
  async getServiceProviderConfig(params: { tenantId: string; scimToken: string }): Promise<any> {
    const { data } = await apiClient.get('/scim/v2/ServiceProviderConfig', {
      headers: buildScimHeaders(params.scimToken, params.tenantId),
    })
    return data
  },

  async listSchemas(params: { tenantId: string; scimToken: string }): Promise<any> {
    const { data } = await apiClient.get('/scim/v2/Schemas', {
      headers: buildScimHeaders(params.scimToken, params.tenantId),
    })
    return data
  },

  async listResourceTypes(params: { tenantId: string; scimToken: string }): Promise<any> {
    const { data } = await apiClient.get('/scim/v2/ResourceTypes', {
      headers: buildScimHeaders(params.scimToken, params.tenantId),
    })
    return data
  },

  async listGroups(params: { tenantId: string; scimToken: string; startIndex?: number; count?: number }): Promise<any> {
    const { tenantId, scimToken, ...query } = params
    const { data } = await apiClient.get('/scim/v2/Groups', {
      headers: buildScimHeaders(scimToken, tenantId),
      params: query,
    })
    return data
  },

  async getGroup(params: { tenantId: string; scimToken: string; groupId: string }): Promise<any> {
    const { data } = await apiClient.get(`/scim/v2/Groups/${encodeURIComponent(params.groupId)}`, {
      headers: buildScimHeaders(params.scimToken, params.tenantId),
    })
    return data
  },

  async createGroup(params: { tenantId: string; scimToken: string; payload: any }): Promise<any> {
    const { data } = await apiClient.post('/scim/v2/Groups', params.payload, {
      headers: buildScimHeaders(params.scimToken, params.tenantId),
    })
    return data
  },

  async updateGroup(params: { tenantId: string; scimToken: string; groupId: string; payload: any }): Promise<any> {
    const { data } = await apiClient.put(`/scim/v2/Groups/${encodeURIComponent(params.groupId)}`, params.payload, {
      headers: buildScimHeaders(params.scimToken, params.tenantId),
    })
    return data
  },

  async deleteGroup(params: { tenantId: string; scimToken: string; groupId: string }): Promise<any> {
    const { data } = await apiClient.delete(`/scim/v2/Groups/${encodeURIComponent(params.groupId)}`, {
      headers: buildScimHeaders(params.scimToken, params.tenantId),
    })
    return data
  },

  async listUsers(params: { tenantId: string; scimToken: string; startIndex?: number; count?: number }): Promise<any> {
    const { tenantId, scimToken, ...query } = params
    const { data } = await apiClient.get('/scim/v2/Users', {
      headers: buildScimHeaders(scimToken, tenantId),
      params: query,
    })
    return data
  },

  async getUser(params: { tenantId: string; scimToken: string; userId: string }): Promise<any> {
    const { data } = await apiClient.get(`/scim/v2/Users/${encodeURIComponent(params.userId)}`, {
      headers: buildScimHeaders(params.scimToken, params.tenantId),
    })
    return data
  },

  async createUser(params: { tenantId: string; scimToken: string; payload: any }): Promise<any> {
    const { data } = await apiClient.post('/scim/v2/Users', params.payload, {
      headers: buildScimHeaders(params.scimToken, params.tenantId),
    })
    return data
  },

  async patchUser(params: { tenantId: string; scimToken: string; userId: string; payload: any }): Promise<any> {
    const { data } = await apiClient.patch(`/scim/v2/Users/${encodeURIComponent(params.userId)}`, params.payload, {
      headers: buildScimHeaders(params.scimToken, params.tenantId),
    })
    return data
  },

  async patchGroup(params: { tenantId: string; scimToken: string; groupId: string; payload: any }): Promise<any> {
    const { data } = await apiClient.patch(`/scim/v2/Groups/${encodeURIComponent(params.groupId)}`, params.payload, {
      headers: buildScimHeaders(params.scimToken, params.tenantId),
    })
    return data
  },
}

export const settingsApiLegacy = {
  /**
   * 获取系统配置
   */
  async get(): Promise<SystemSettings> {
    const { data } = await apiClient.get('/settings')
    return data
  },

  /**
   * 更新系统配置
   */
  async update(settings: Partial<SystemSettings>): Promise<{ success: boolean; message: string; updated_keys: string[] }> {
    const { data } = await apiClient.put('/settings', settings)
    return data
  },

  /**
   * 获取系统状态
   */
  async getStatus(): Promise<SystemStatus> {
    const { data } = await apiClient.get('/settings/status')
    return data
  },

  /**
   * 测试 LLM 连接（不写入配置）
   */
  async testLLM(params: TestLLMRequest): Promise<TestLLMResponse> {
    const { data } = await apiClient.post('/settings/llm/test', params)
    return data
  },
}

// ==================== LTR 模型注册表 API ====================

export interface LTRModelInfo {
  model_id: string
  model_sha256: string
  size_bytes: number
  created_at: string
  created_by?: string | null
  feature_spec_version: number
  feature_schema: string
  feature_names: string[]
  has_manifest: boolean
  active: boolean
}

export interface LTRModelListResponse {
  items: LTRModelInfo[]
}

export interface LTRModelRegisterResponse {
  model: LTRModelInfo
}

export interface LTRModelActivateResponse {
  active: Record<string, any>
}

export const ltrApi = {
  async listModels(): Promise<LTRModelListResponse> {
    const { data } = await apiClient.get('/ltr/models')
    return data
  },

  async registerModel(params: { modelFile: File; manifestFile: File }): Promise<LTRModelRegisterResponse> {
    const formData = new FormData()
    formData.append('model_file', params.modelFile)
    formData.append('manifest_file', params.manifestFile)
    const { data } = await apiClient.post('/ltr/models/register', formData, { timeout: API_LONG_TIMEOUT_MS })
    return data
  },

  async activateModel(modelId: string): Promise<LTRModelActivateResponse> {
    const { data } = await apiClient.post('/ltr/models/activate', { model_id: modelId })
    return data
  },

  async rollbackActiveModel(): Promise<LTRModelActivateResponse> {
    const { data } = await apiClient.post('/ltr/models/rollback')
    return data
  },
}

// ==================== RAGAS 评测 API ====================

export interface RagasRun {
  id: string
  conversation_id?: string
  status: string
  metrics: string[]
  params: Record<string, any>
  summary: Record<string, any>
  error_message?: string
  created_at: string
  started_at?: string
  finished_at?: string
}

export interface RagasItem {
  id: string
  run_id: string
  turn_index: number
  user_message_id?: string
  assistant_message_id?: string
  user_input: string
  response: string
  retrieved_contexts?: string[] | null
  citations: any[]
  scores: Record<string, any>
  created_at: string
}

export interface RagasRunDetail {
  run: RagasRun
  items: RagasItem[]
}

// ==================== KG Search Diagnostics API ====================

export type KGHardcaseMode = 'off' | 'deterministic' | 'llm'

export interface KGSearchDiagnosticsRequest {
  dataset_id: string
  case_ids?: string[]
  max_cases?: number
  k?: number
  auto_extract_kg?: boolean
  extract_skills?: boolean | null
  extract_relations?: boolean | null
  hardcase_mode?: KGHardcaseMode
  hardcases_per_failed_case?: number
  max_failed_cases_for_hardcase?: number
  llm_temperature?: number
  persist_run?: boolean
}

export interface KGSearchDiagnosticsResponse {
  run_id?: string | null
  summary: Record<string, any>
  items: any[]
}

export interface KGSearchDiagnosticsRunOut {
  id: string
  tenant_id: string
  account_id?: string | null
  dataset_id: string
  status: string
  params: Record<string, any>
  summary: Record<string, any>
  created_at: string
}

export interface KGSearchDiagnosticsRunList {
  total: number
  items: KGSearchDiagnosticsRunOut[]
}

export interface KGSearchDiagnosticsRunDetail {
  run: KGSearchDiagnosticsRunOut
  items: any[]
}

export const evaluationApiLegacy = {
  async createRagasRun(params: {
    conversation_id: string
    metrics?: string[]
    max_turns?: number
    skip_empty_contexts?: boolean
    include_contexts_in_response?: boolean
  }): Promise<RagasRun> {
    const { data } = await apiClient.post('/evaluations/ragas/runs', params)
    return data
  },

  async listRagasRuns(params?: {
    skip?: number
    limit?: number
    conversation_id?: string
  }): Promise<{ total: number; items: RagasRun[] }> {
    const { data } = await apiClient.get('/evaluations/ragas/runs', { params })
    return data
  },

  async getRagasRun(
    runId: string,
    params?: { include_items?: boolean; include_contexts?: boolean }
  ): Promise<RagasRunDetail> {
    const { data } = await apiClient.get(`/evaluations/ragas/runs/${runId}`, {
      params,
    })
    return data
  },

  // ==================== 回归测试用例管理 ====================

  async createRegressionCase(params: RegressionCaseCreate): Promise<RegressionCase> {
    const { data } = await apiClient.post('/evaluations/ragas/regression/cases', params)
    return data
  },

  async listRegressionCases(params?: {
    skip?: number
    limit?: number
    dataset_id?: string
  }): Promise<RegressionCaseList> {
    const { data } = await apiClient.get('/evaluations/ragas/regression/cases', { params })
    return data
  },

  async exportRegressionCases(params: { dataset_id: string }): Promise<any> {
    const { data } = await apiClient.get('/evaluations/ragas/regression/cases/export', { params })
    return data as RegressionCaseBundleV1
  },

  async importRegressionCases(payload: {
    dataset_id: string
    overwrite?: boolean
    max_items?: number
    items: any[]
  }): Promise<RegressionCaseImportResponse> {
    const { data } = await apiClient.post('/evaluations/ragas/regression/cases/import', payload)
    return data as RegressionCaseImportResponse
  },

  async deleteRegressionCase(caseId: string): Promise<void> {
    await apiClient.delete(`/evaluations/ragas/regression/cases/${caseId}`)
  },

  async patchRegressionCase(caseId: string, payload: RegressionCasePatch): Promise<RegressionCase> {
    const { data } = await apiClient.patch(`/evaluations/ragas/regression/cases/${caseId}`, payload)
    return data
  },

  // ==================== Synthetic Hardcases (PII-safe) ====================

  async generateSyntheticHardcases(payload: {
    dataset_id: string
    case_ids?: string[]
    max_cases?: number
    hardcases_per_case?: number
    max_created?: number
    dry_run?: boolean
    tag?: string
  }): Promise<any> {
    const { data } = await apiClient.post('/evaluations/ragas/regression/cases/synthetic-hardcases', payload)
    return data
  },

  // ==================== AI 生成测试问题 ====================

  async generateFromDocuments(params: TestGenFromDocsRequest): Promise<TestGenResponse> {
    const { data } = await apiClient.post('/evaluations/ragas/test-gen/from-documents', params)
    return data
  },

  async generateFromConversations(params: TestGenFromConversationsRequest): Promise<TestGenResponse> {
    const { data } = await apiClient.post('/evaluations/ragas/test-gen/from-conversations', params)
    return data
  },

  // ==================== 回归测试运行 ====================

  async createRegressionRun(params: RegressionRunCreate): Promise<RegressionRun> {
    const { data } = await apiClient.post('/evaluations/ragas/regression/runs', params)
    return data
  },

  async listRegressionRuns(params?: {
    skip?: number
    limit?: number
  }): Promise<RegressionRunList> {
    const { data } = await apiClient.get('/evaluations/ragas/regression/runs', { params })
    return data
  },

  async getRegressionRunLeaderboard(params: {
    dataset_id: string
    metric_key?: string
    limit?: number
    include_incomplete?: boolean
    max_candidates?: number
  }): Promise<any> {
    const { data } = await apiClient.get('/evaluations/ragas/regression/runs/leaderboard', { params })
    return data
  },

  async getRegressionRun(
    runId: string,
    params?: { include_items?: boolean; include_contexts?: boolean }
  ): Promise<RegressionRunDetail> {
    const { data } = await apiClient.get(`/evaluations/ragas/regression/runs/${runId}`, {
      params,
    })
    return data
  },

  async diffRegressionRuns(runId: string, params: { base_run_id: string }): Promise<RagasRegressionRunDiffResponse> {
    const { data } = await apiClient.get(`/evaluations/ragas/regression/runs/${runId}/diff`, { params })
    return data
  },

  async exportRegressionRunDiffHtml(
    runId: string,
    params: { base_run_id: string; redact?: boolean }
  ): Promise<Blob> {
    const { data } = await apiClient.get(`/evaluations/ragas/regression/runs/${runId}/diff/export-html`, { params, responseType: 'blob' })
    return data as Blob
  },

  async exportRegressionRunBundle(
    runId: string,
    params?: {
      include_text?: boolean
      include_contexts?: boolean
      redact_ids?: boolean
      max_items?: number
      max_citations?: number
      download?: boolean
    }
  ): Promise<Blob> {
    const { data } = await apiClient.get(`/evaluations/ragas/regression/runs/${runId}/export-bundle`, {
      params,
      responseType: 'blob',
    })
    return data as Blob
  },

  async purgeRegressionRuns(params?: {
    retention_days?: number
    max_delete?: number
    dry_run?: boolean
    dataset_id?: string
  }): Promise<any> {
    const { data } = await apiClient.post('/evaluations/ragas/regression/runs/purge', null, { params })
    return data
  },

  // ==================== KG Search Diagnostics ====================

  async runKgSearchDiagnostics(payload: KGSearchDiagnosticsRequest): Promise<KGSearchDiagnosticsResponse> {
    const { data } = await apiClient.post('/evaluations/kg/search/diagnostics', payload)
    return data
  },

  async listKgSearchDiagnosticsRuns(params: { dataset_id: string; limit?: number }): Promise<KGSearchDiagnosticsRunList> {
    const { data } = await apiClient.get('/evaluations/kg/search/diagnostics/runs', { params })
    return data
  },

  async getKgSearchDiagnosticsRun(runId: string): Promise<KGSearchDiagnosticsRunDetail> {
    const { data } = await apiClient.get(`/evaluations/kg/search/diagnostics/runs/${runId}`)
    return data
  },

  async getKgQualityReport(params: {
    dataset_id: string
    document_limit?: number
    pipeline_hash?: string
  }): Promise<any> {
    const { data } = await apiClient.get('/evaluations/kg/quality/report', { params })
    return data
  },
}

// ==================== 提示词模板 API ====================

export interface PromptTemplate {
  id: string
  tenant_id: string
  template_key?: string | null
  name: string
  description?: string
  content: string
  variables: string[]
  is_system: boolean
  is_active: boolean
  category?: string
  tags: string[]
  usage_count: number
  version?: number
  parent_id?: string | null
  ab_experiment_key?: string | null
  ab_variant?: string | null
  ab_weight?: number
  created_at: string
  updated_at: string
}

export interface PromptTemplateCreate {
  name: string
  description?: string
  content: string
  variables?: string[]
  category?: string
  tags?: string[]
  is_active?: boolean
}

export interface PromptTemplateUpdate {
  name?: string
  description?: string
  content?: string
  variables?: string[]
  category?: string
  tags?: string[]
  is_active?: boolean
}

export interface PromptTemplateNewVersion {
  name?: string
  description?: string
  content?: string
  variables?: string[]
  category?: string
  tags?: string[]
  is_active?: boolean
  deactivate_previous?: boolean
  ab_experiment_key?: string
  ab_variant?: string
  ab_weight?: number
}

export const promptTemplateApi = {
  /**
   * 创建提示词模板
   */
  async create(params: PromptTemplateCreate): Promise<PromptTemplate> {
    const { data } = await apiClient.post('/prompt-templates', params)
    return data
  },

  /**
   * 获取提示词模板列表
   */
  async list(params?: {
    skip?: number
    limit?: number
    category?: string
    is_active?: boolean
  }): Promise<{ total: number; items: PromptTemplate[] }> {
    const { data } = await apiClient.get('/prompt-templates', { params })
    return data
  },

  /**
   * 获取单个提示词模板
   */
  async get(templateId: string): Promise<PromptTemplate> {
    const { data } = await apiClient.get(`/prompt-templates/${templateId}`)
    return data
  },

  /**
   * 更新提示词模板
   */
  async update(templateId: string, params: PromptTemplateUpdate): Promise<PromptTemplate> {
    const { data } = await apiClient.put(`/prompt-templates/${templateId}`, params)
    return data
  },

  /**
   * 删除提示词模板
   */
  async delete(templateId: string): Promise<void> {
    await apiClient.delete(`/prompt-templates/${templateId}`)
  },

  /**
   * 复制提示词模板
   */
  async duplicate(templateId: string): Promise<PromptTemplate> {
    const { data } = await apiClient.post(`/prompt-templates/${templateId}/duplicate`)
    return data
  },

  async createVersion(templateId: string, params: PromptTemplateNewVersion): Promise<PromptTemplate> {
    const { data } = await apiClient.post(`/prompt-templates/${templateId}/versions`, params)
    return data
  },
}

// ==================== RAG Config Templates API ====================

export interface RagConfigTemplate {
  id: string
  tenant_id: string
  template_key?: string | null
  name: string
  description?: string | null
  config_patch: Record<string, any>
  is_active: boolean
  usage_count: number
  version: number
  parent_id?: string | null
  ab_experiment_key?: string | null
  ab_variant?: string | null
  ab_weight: number
  created_at: string
  updated_at: string
}

export interface RagConfigTemplateCreate {
  template_key?: string
  name: string
  description?: string
  config_patch?: Record<string, any>
  is_active?: boolean
  parent_id?: string | null
  ab_experiment_key?: string | null
  ab_variant?: string | null
  ab_weight?: number
}

export interface RagConfigTemplateUpdate {
  template_key?: string | null
  name?: string
  description?: string | null
  config_patch?: Record<string, any>
  is_active?: boolean
  version?: number
  parent_id?: string | null
  ab_experiment_key?: string | null
  ab_variant?: string | null
  ab_weight?: number
}

export interface RagConfigTemplateNewVersion {
  name?: string
  description?: string | null
  config_patch?: Record<string, any>
  is_active?: boolean
  deactivate_previous?: boolean
  ab_experiment_key?: string | null
  ab_variant?: string | null
  ab_weight?: number
}

export const ragConfigTemplateApi = {
  async create(params: RagConfigTemplateCreate): Promise<RagConfigTemplate> {
    const { data } = await apiClient.post('/rag-config-templates', params)
    return data
  },

  async list(params?: {
    skip?: number
    limit?: number
    template_key?: string
    ab_experiment_key?: string
    is_active?: boolean
  }): Promise<{ total: number; items: RagConfigTemplate[] }> {
    const { data } = await apiClient.get('/rag-config-templates', { params })
    return data
  },

  async get(templateId: string): Promise<RagConfigTemplate> {
    const { data } = await apiClient.get(`/rag-config-templates/${templateId}`)
    return data
  },

  async update(templateId: string, params: RagConfigTemplateUpdate): Promise<RagConfigTemplate> {
    const { data } = await apiClient.patch(`/rag-config-templates/${templateId}`, params)
    return data
  },

  async createVersion(templateId: string, params: RagConfigTemplateNewVersion): Promise<RagConfigTemplate> {
    const { data } = await apiClient.post(`/rag-config-templates/${templateId}/versions`, params)
    return data
  },
}

// ==================== RAGViz (Similarity Heatmap) API ====================

export const ragvizApi = {
  async listSimilarityCollections(): Promise<RagvizSimilarityCollectionsResponse> {
    const { data } = await apiClient.get('/ragviz/similarity/collections')
    return data
  },

  async calculateSimilarityMatrix(params: RagvizSimilarityRequest): Promise<RagvizSimilarityCalculateResponse> {
    const { data } = await apiClient.post('/ragviz/similarity/calculate', params)
    return data
  },
}

export default apiClient
