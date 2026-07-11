export { apiClient, coerceRetryAfterSeconds, formatRateLimitLogMessage } from '@/lib/api/core'

export { authApi } from '@/lib/api/auth'
export { authApi as authApiLegacy } from '@/lib/api/auth'
export { chatApi } from '@/lib/api/chat'
export { connectorApi } from '@/lib/api/connectors'
export { connectorApi as connectorApiLegacy } from '@/lib/api/connectors'
export { ingestionRunApi } from '@/lib/api/connectors'
export { datasetApi } from '@/lib/api/datasets'
export { datasetApi as datasetApiLegacy } from '@/lib/api/datasets'
export { datasetCategoryApi } from '@/lib/api/datasets'
export { datasetCategoryApi as datasetCategoryApiLegacy } from '@/lib/api/datasets'
export { appendChunkPreviewFormFields, buildChunkPreviewQueryParams } from '@/lib/api/document-helpers'
export { documentApi } from '@/lib/api/documents'
export { evaluationApi } from '@/lib/api/evaluation'
export { evaluationApi as evaluationApiLegacy } from '@/lib/api/evaluation'
export { evidenceApi } from '@/lib/api/evidence'
export { feedbackApi } from '@/lib/api/feedback'
export { governanceApi } from '@/lib/api/governance'
export { chunkPresetApi } from '@/lib/api/governance'
export { kgApi } from '@/lib/api/graph'
export { kgApi as kgApiLegacy } from '@/lib/api/graph'
export { healthApi } from '@/lib/api/health'
export { industryRulesApi } from '@/lib/api/industry-rules'
export { integrationApi } from '@/lib/api/integrations'
export { lineageApi } from '@/lib/api/lineage'
export { ltrApi } from '@/lib/api/ltr'
export { metaApi } from '@/lib/api/meta'
export { observabilityApi } from '@/lib/api/observability'
export { observabilityApi as observabilityApiLegacy } from '@/lib/api/observability'
export { parsingApi } from '@/lib/api/parsing'
export { pipelineApi } from '@/lib/api/pipeline'
export { pipelineApi as pipelineApiLegacy } from '@/lib/api/pipeline'
export { promptTemplateApi } from '@/lib/api/prompts'
export { ragApi } from '@/lib/api/rag'
export { ragConfigTemplateApi } from '@/lib/api/rag'
export { ragvizApi } from '@/lib/api/rag'
export { retrievalApi } from '@/lib/api/rag'
export { reportApi } from '@/lib/api/reports'
export { reportApi as reportApiLegacy } from '@/lib/api/reports'
export { rbacApi } from '@/lib/api/access'
export { rtbfApi } from '@/lib/api/rtbf'
export { groupApi } from '@/lib/api/access'
export { scimApi } from '@/lib/api/scim'
export { settingsApi } from '@/lib/api/settings'
export { settingsApi as settingsApiLegacy } from '@/lib/api/settings'
export { sseApi } from '@/lib/api/streaming'
export { usageApi } from '@/lib/api/usage'
export { auditApi } from '@/lib/api/audit'

export type { ChunkPreviewRequestParams, DocumentLifecycleFilter } from '@/lib/api/document-helpers'
export type {
  DatasetAnalysisDashboardParams,
  DatasetAnalysisExamplesParams,
  DatasetAnalysisFilters,
  DatasetAnalysisGlossaryWritebackParams,
  DatasetAnalysisResponse,
  DatasetAnalysisRuleSuggestionParams,
  DatasetRetrievalAuditPayload,
} from '@/lib/api/datasets'
export type { FrontendTraceReportRequest, FrontendWebVitalReportOptions, FrontendWebVitalReportRequest } from '@/lib/api/observability'
export type { ParsingContentResponse, ParsingContentUpdateRequest } from '@/lib/api/parsing'
export type { BackendMeta, BackendMetaDetails } from '@/lib/api/meta'
export type { TenantMember, TenantMemberListResponse } from '@/lib/api/access'
export type { TenantAccess, TenantPermission } from '@/lib/tenant-permissions'
export type { LTRModelActivateResponse, LTRModelInfo, LTRModelListResponse, LTRModelRegisterResponse } from '@/lib/api/ltr'
export type { KGNetworkEdge, KGNetworkRequest, KGNetworkResponse } from '@/lib/api/graph'
export type {
  IndustryRulesGlossaryUpdateRequest,
  IndustryRulesIntentsUpdateRequest,
  IndustryRulesPatternsUpdateRequest,
  IndustryRulesRewritePreviewRequest,
  IndustryRulesRewritePreviewResponse,
  IndustryRulesUpdateResponse,
  IndustryRulesetDetail,
  IndustryRulesetDetailResponse,
  IndustryRulesetListResponse,
  IndustryRulesetSummary,
} from '@/lib/api/industry-rules'
export type {
  ExternalConversationIngestRequest,
  ExternalConversationIngestResponse,
  ExternalConversationMessageInput,
} from '@/lib/api/integrations'
export type { LineageResponse } from '@/lib/api/lineage'
export type { RtbfCascadeResponse, RtbfRequest, RtbfStatusResponse } from '@/lib/api/rtbf'
export type {
  KGHardcaseMode,
  KGSearchDiagnosticsRequest,
  KGSearchDiagnosticsResponse,
  KGSearchDiagnosticsRunDetail,
  KGSearchDiagnosticsRunList,
  KGSearchDiagnosticsRunOut,
  RagasItem,
  RagasRun,
  RagasRunDetail,
} from '@/lib/api/evaluation'
export type {
  PromptTemplate,
  PromptTemplateCreate,
  PromptTemplateNewVersion,
  PromptTemplateUpdate,
} from '@/lib/api/prompts'
export type {
  ClipImageIndexRequest,
  ClipImageIndexResponse,
  ClipImageSearchRequest,
  ClipImageSearchResponse,
  RagConfigTemplate,
  RagConfigTemplateCreate,
  RagConfigTemplateNewVersion,
  RagConfigTemplateUpdate,
} from '@/lib/api/rag'
export type {
  CacheConfig,
  ChatConfig,
  Etl4LlmConfig,
  FeatureFlags,
  KGConfig,
  LangGraphConfig,
  MagicPDFConfig,
  MarkerConfig,
  ObservabilityConfig,
  PaddleVLConfig,
  SafetyConfig,
  SystemSettings,
  SystemStatus,
  TestLLMRequest,
  TestLLMResponse,
} from '@/lib/api/settings'

export { default } from '@/lib/api/core'
