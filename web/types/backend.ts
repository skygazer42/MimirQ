/**
 * Backend API response type aliases (generated OpenAPI types).
 */
import type { components, paths } from './openapi'

export type OpenApiSchemas = components['schemas']
export type OpenApiSchema<K extends keyof OpenApiSchemas> = OpenApiSchemas[K]

export type HealthResponse = paths['/api/v1/health']['get']['responses'][200]['content']['application/json']
export type ReadyResponse = paths['/api/v1/health/ready']['get']['responses'][200]['content']['application/json']
export type MetaResponse = paths['/api/v1/meta']['get']['responses'][200]['content']['application/json']

// ==================== Auth ====================

export type UserProfile = OpenApiSchema<'UserPublic'>
export type AuthToken = OpenApiSchema<'TokenResponse'>
export type AuthResponse = OpenApiSchema<'AuthResponse'>
export type RegisterRequest = OpenApiSchema<'RegisterRequest'>
export type LoginRequest = OpenApiSchema<'LoginRequest'>

// ==================== Groups (Tenant Directory) ====================

export type TenantGroupOut = OpenApiSchema<'TenantGroupOut'>
export type TenantGroupListResponse = OpenApiSchema<'TenantGroupListResponse'>
export type TenantGroupCreateRequest = OpenApiSchema<'TenantGroupCreateRequest'>
export type TenantGroupUpdateRequest = OpenApiSchema<'TenantGroupUpdateRequest'>
export type TenantGroupMemberOut = OpenApiSchema<'TenantGroupMemberOut'>
export type TenantGroupMemberListResponse = OpenApiSchema<'TenantGroupMemberListResponse'>
export type TenantGroupMembersUpdateRequest = OpenApiSchema<'TenantGroupMembersUpdateRequest'>
export type TenantGroupMembersUpdateResponse = OpenApiSchema<'TenantGroupMembersUpdateResponse'>

// ==================== Documents ====================

export type Document = OpenApiSchema<'DocumentDetail'>
export type DocumentList = OpenApiSchema<'DocumentList'>
export type DocumentStatus = OpenApiSchema<'DocumentStatus'>
export type DocumentStatusEnum = OpenApiSchema<'DocumentStatusEnum'>
export type IngestDeadLetterItem = OpenApiSchema<'IngestDeadLetterItem'>
export type IngestDeadLetterList = OpenApiSchema<'IngestDeadLetterList'>
export type IngestDeadLetterReplayResponse = OpenApiSchema<'IngestDeadLetterReplayResponse'>
export type GovernanceInfo = OpenApiSchema<'GovernanceInfo'>

export type DocumentFolderNode = OpenApiSchema<'DocumentFolderNode'>
export type DocumentFolderTreeResponse = OpenApiSchema<'DocumentFolderTreeResponse'>
export type DocumentStats = OpenApiSchema<'DocumentStats'>

export type DocumentAccessInfo = OpenApiSchema<'DocumentAccessInfo'>
export type DocumentAccessUpdateRequest = OpenApiSchema<'DocumentAccessUpdateRequest'>

export type DocumentChunk = OpenApiSchema<'DocumentChunkSchema'>
export type DocumentChunkList = OpenApiSchema<'DocumentChunkList'>
export type DocumentChunkUpdateRequest = OpenApiSchema<'DocumentChunkUpdateRequest'>
export type DocumentChunkCreateRequest = OpenApiSchema<'DocumentChunkCreateRequest'>
export type DocumentChunkMatch = OpenApiSchema<'DocumentChunkMatch'>
export type DocumentChunkMatchList = OpenApiSchema<'DocumentChunkMatchList'>
export type DocumentChunkReembedRequest = OpenApiSchema<'DocumentChunkReembedRequest'>
export type DocumentChunkReembedResponse = OpenApiSchema<'DocumentChunkReembedResponse'>

export type DocumentPipelineOptions = OpenApiSchema<'DocumentPipelineOptions'>
export type DocumentPipelineProvenance = OpenApiSchema<'DocumentPipelineProvenance'>

export type DocumentBatchUploadResponse = OpenApiSchema<'DocumentBatchUploadResponse'>
export type DocumentBatchUploadSuccess = OpenApiSchema<'DocumentBatchUploadSuccess'>
export type DocumentBatchUploadFailure = OpenApiSchema<'DocumentBatchUploadFailure'>
export type DocumentBatchLifecycleRequest = OpenApiSchema<'DocumentBatchLifecycleRequest'>
export type DocumentBatchLifecycleResponse = OpenApiSchema<'DocumentBatchLifecycleResponse'>
export type DocumentBatchRetryRequest = OpenApiSchema<'DocumentBatchRetryRequest'>
export type DocumentBatchRetryResponse = OpenApiSchema<'DocumentBatchRetryResponse'>
export type DocumentBatchReingestRequest = OpenApiSchema<'DocumentBatchReingestRequest'>
export type DocumentBatchMoveRequest = OpenApiSchema<'DocumentBatchMoveRequest'>
export type DocumentBatchMoveResponse = OpenApiSchema<'DocumentBatchMoveResponse'>
export type DocumentBatchAccessUpdateRequest = OpenApiSchema<'DocumentBatchAccessUpdateRequest'>
export type DocumentBatchAccessUpdateResponse = OpenApiSchema<'DocumentBatchAccessUpdateResponse'>

export type DocumentUserMetadataPatchRequest = OpenApiSchema<'DocumentUserMetadataPatchRequest'>
export type DocumentBatchUserMetadataPatchRequest = OpenApiSchema<'DocumentBatchUserMetadataPatchRequest'>
export type DocumentBatchUserMetadataPatchResponse = OpenApiSchema<'DocumentBatchUserMetadataPatchResponse'>

export type DocumentPipelinePatchRequest = OpenApiSchema<'DocumentPipelinePatchRequest'>

export type DocumentDuplicateList = OpenApiSchema<'DocumentDuplicateList'>
export type DocumentDuplicateGroup = OpenApiSchema<'DocumentDuplicateGroup'>
export type DuplicateDocumentItem = OpenApiSchema<'DuplicateDocumentItem'>

export type DocumentVersionList = OpenApiSchema<'DocumentVersionList'>
export type DocumentVersionInfo = OpenApiSchema<'DocumentVersionInfo'>
export type DocumentVersionDiff = OpenApiSchema<'DocumentVersionDiff'>

export type DocumentTimelineItem = OpenApiSchema<'DocumentTimelineItem'>
export type DocumentTimelineResponse = OpenApiSchema<'DocumentTimelineResponse'>

export type DocumentParsedContentResponse = OpenApiSchema<'DocumentParsedContentResponse'>

export type DocumentQAGenerateRequest = OpenApiSchema<'DocumentQAGenerateRequest'>
export type DocumentQAGenerateResponse = OpenApiSchema<'DocumentQAGenerateResponse'>
export type QAPairPreview = OpenApiSchema<'QAPairPreview'>

// ==================== Datasets ====================

export type Dataset = OpenApiSchema<'DatasetOut'>
export type DatasetCreate = OpenApiSchema<'DatasetCreate'>
export type DatasetUpdate = OpenApiSchema<'DatasetUpdate'>
export type DatasetListResponse = OpenApiSchema<'DatasetListResponse'>
export type DatasetIngestionStats = OpenApiSchema<'DatasetIngestionStats'>
export type DatasetHealthResponse = OpenApiSchema<'DatasetHealthResponse'>

export type DatasetConfigExport = OpenApiSchema<'DatasetConfigExport'>
export type DatasetConfigImportRequest = OpenApiSchema<'DatasetConfigImportRequest'>
export type DatasetCloneRequest = OpenApiSchema<'DatasetCloneRequest'>

// Ingestion policy uses distinct input/output shapes in OpenAPI.
export type IngestionPolicyInput = OpenApiSchema<'IngestionPolicy-Input'>
export type IngestionPolicyOutput = OpenApiSchema<'IngestionPolicy-Output'>
// Backwards-compat alias (most callers treat it as the server-returned shape).
export type IngestionPolicy = IngestionPolicyOutput
export type IngestionPolicyImportResponse = OpenApiSchema<'IngestionPolicyImportResponse'>
export type IngestionPolicyRollbackRequest = OpenApiSchema<'IngestionPolicyRollbackRequest'>
export type IngestionPolicyVersionListResponse = OpenApiSchema<'IngestionPolicyVersionListResponse'>

// Dataset categories
export type DatasetCategoryTreeResponse = OpenApiSchema<'DatasetCategoryTreeResponse'>
export type DatasetCategoryCreate = OpenApiSchema<'DatasetCategoryCreate'>
export type DatasetCategoryUpdate = OpenApiSchema<'DatasetCategoryUpdate'>
export type DatasetCategoryMoveRequest = OpenApiSchema<'DatasetCategoryMoveRequest'>
export type DatasetCategoryOut = OpenApiSchema<'DatasetCategoryOut'>
export type DatasetCategoryAssignmentRequest = OpenApiSchema<'DatasetCategoryAssignmentRequest'>
export type DatasetCategoryAssignmentResponse = OpenApiSchema<'DatasetCategoryAssignmentResponse'>

// Dataset Profile / Precheck (used by knowledge workbench)
export type DatasetProfileSummary = OpenApiSchema<'DatasetProfileSummary'>
export type DatasetProfileDocumentListResponse = OpenApiSchema<'DatasetProfileDocumentListResponse'>
export type DatasetProfileFindingListResponse = OpenApiSchema<'DatasetProfileFindingListResponse'>
export type DatasetProfileScanRunCreateRequest = OpenApiSchema<'DatasetProfileScanRunCreateRequest'>
export type DatasetProfileScanRunListResponse = OpenApiSchema<'DatasetProfileScanRunListResponse'>
export type DatasetProfileScanRunOut = OpenApiSchema<'DatasetProfileScanRunOut'>

export type DatasetPrecheckSummary = OpenApiSchema<'DatasetPrecheckSummary'>
export type DatasetPrecheckFindingListResponse = OpenApiSchema<'DatasetPrecheckFindingListResponse'>
export type DatasetPrecheckScanRunCreateRequest = OpenApiSchema<'DatasetPrecheckScanRunCreateRequest'>
export type DatasetPrecheckScanRunListResponse = OpenApiSchema<'DatasetPrecheckScanRunListResponse'>
export type DatasetPrecheckScanRunOut = OpenApiSchema<'DatasetPrecheckScanRunOut'>
export type DatasetPrecheckSamplesResponse = OpenApiSchema<'DatasetPrecheckSamplesResponse'>
export type DatasetPrecheckNearDupResponse = OpenApiSchema<'DatasetPrecheckNearDupResponse'>
export type DatasetPrecheckDiffResponse = OpenApiSchema<'DatasetPrecheckDiffResponse'>
export type DatasetPrecheckIngestionSuggestionResponse = OpenApiSchema<'DatasetPrecheckIngestionSuggestionResponse'>

// ==================== Connectors ====================

export type ConnectorInfo = OpenApiSchema<'ConnectorInfo'>
export type ConnectorValidateRequest = OpenApiSchema<'ConnectorValidateRequest'>
export type ConnectorValidateResponse = OpenApiSchema<'ConnectorValidateResponse'>

export type ConnectorConfigCreateRequest = OpenApiSchema<'ConnectorConfigCreateRequest'>
export type ConnectorConfigListResponse = OpenApiSchema<'ConnectorConfigListResponse'>
export type ConnectorConfigOut = OpenApiSchema<'ConnectorConfigOut'>
export type ConnectorConfigUpdateRequest = OpenApiSchema<'ConnectorConfigUpdateRequest'>

export type ConnectorRunCreateRequest = OpenApiSchema<'ConnectorRunCreateRequest'>
export type ConnectorRunListResponse = OpenApiSchema<'ConnectorRunListResponse'>
export type ConnectorRunOut = OpenApiSchema<'ConnectorRunOut'>
// This endpoint returns a dict-like payload (best-effort tick hook), so OpenAPI emits `unknown`.
export type ConnectorScheduledTickResponse =
  paths['/api/v1/connectors/scheduled/tick']['post']['responses'][200]['content']['application/json']

export type IngestionRunCompareResponse = OpenApiSchema<'IngestionRunCompareResponse'>
export type IngestionRunListResponse = OpenApiSchema<'IngestionRunListResponse'>
export type IngestionRunOut = OpenApiSchema<'IngestionRunOut'>

// ==================== RAG / Evidence ====================

export type RetrievePreviewRequest = OpenApiSchema<'RetrievePreviewRequest'>
export type RetrievePreviewResponse = OpenApiSchema<'RetrievePreviewResponse'>
export type EvidenceRetrieveRequest = OpenApiSchema<'EvidenceRetrieveRequest'>
export type EvidenceRetrieveResponse = OpenApiSchema<'EvidenceRetrieveResponse'>
export type PromptPreviewRequest = OpenApiSchema<'PromptPreviewRequest'>
export type PromptPreviewResponse = OpenApiSchema<'PromptPreviewResponse'>

export type EvidenceSuite = OpenApiSchema<'EvidenceSuiteOut'>
export type EvidenceSuiteCreate = OpenApiSchema<'EvidenceSuiteCreateRequest'>
export type EvidenceSuitePatch = OpenApiSchema<'EvidenceSuitePatchRequest'>
export type EvidenceSuiteList = OpenApiSchema<'EvidenceSuiteList'>
export type EvidenceSuiteDashboard = OpenApiSchema<'EvidenceSuiteDashboardOut'>
export type EvidenceSuiteExportV1 = OpenApiSchema<'EvidenceSuiteExportV1'>
export type EvidenceSuiteSyncRegressionResponse = OpenApiSchema<'EvidenceSuiteSyncRegressionResponse'>
export type EvidenceSuiteCoverage = OpenApiSchema<'EvidenceSuiteCoverage'>
export type EvidenceSuiteThroughput = OpenApiSchema<'EvidenceSuiteThroughput'>
export type EvidenceCoverageBucket = OpenApiSchema<'EvidenceCoverageBucket'>
export type EvidenceCoverageHeatmap = OpenApiSchema<'EvidenceCoverageHeatmap'>
export type EvidenceThroughputWindow = OpenApiSchema<'EvidenceThroughputWindow'>
export type EvidenceLeadTimeStats = OpenApiSchema<'EvidenceLeadTimeStats'>
export type EvidenceDriftSliceBucket = OpenApiSchema<'EvidenceDriftSliceBucketOut'>
export type EvidenceReferenceDriftDetail = OpenApiSchema<'EvidenceReferenceDriftDetailOut'>
export type EvidenceReferenceRepairChange = OpenApiSchema<'EvidenceReferenceRepairChangeOut'>

export type EvidenceItem = OpenApiSchema<'EvidenceItemOut'>
export type EvidenceItemCreate = OpenApiSchema<'EvidenceItemCreateRequest'>
export type EvidenceItemPatch = OpenApiSchema<'EvidenceItemPatchRequest'>
export type EvidenceItemList = OpenApiSchema<'EvidenceItemList'>
export type EvidenceItemImportResponse = OpenApiSchema<'EvidenceItemImportResponse'>

export type EvidenceReferenceDriftAudit = OpenApiSchema<'EvidenceReferenceDriftAuditOut'>
export type EvidenceReferenceRepairRequest = OpenApiSchema<'EvidenceReferenceRepairRequest'>
export type EvidenceReferenceRepairResponse = OpenApiSchema<'EvidenceReferenceRepairResponse'>

export type EvidenceHardcaseCandidate = OpenApiSchema<'EvidenceHardcaseCandidateOut'>
export type EvidenceHardcaseDiscovery = OpenApiSchema<'EvidenceHardcaseDiscoveryOut'>

// ==================== Governance processing scripts ====================

export type BuiltinProcessingScript = OpenApiSchema<'BuiltinProcessingScriptOut'>
export type BuiltinProcessingScriptListResponse = OpenApiSchema<'BuiltinProcessingScriptListResponse'>

// ==================== Industry rules ====================

export type IndustryRulesetSummary = OpenApiSchema<'IndustryRulesetSummary'>
export type IndustryRulesetDetail = OpenApiSchema<'IndustryRulesetDetail'>
export type IndustryRulesetListResponse = OpenApiSchema<'IndustryRulesetListResponse'>
export type IndustryRulesetDetailResponse = OpenApiSchema<'IndustryRulesetDetailResponse'>
export type IndustryRulesUpdateResponse = OpenApiSchema<'IndustryRulesUpdateResponse'>
export type IndustryRulesRewritePreviewResponse = OpenApiSchema<'IndustryRulesRewritePreviewResponse'>
export type IndustryRulesRewritePreviewRequest = OpenApiSchema<'IndustryRulesRewritePreviewRequest'>
export type IndustryRulesGlossaryUpdateRequest = OpenApiSchema<'IndustryRulesGlossaryUpdateRequest'>
export type IndustryRulesPatternsUpdateRequest = OpenApiSchema<'IndustryRulesPatternsUpdateRequest'>
export type IndustryRulesIntentsUpdateRequest = OpenApiSchema<'IndustryRulesIntentsUpdateRequest'>
