import { z } from 'zod'

import type { BuiltinProcessingScriptListResponse, OpenApiSchema } from '@/types/backend'
import type { OpenApiRequestBody } from '@/types/openapi-helpers'
import type {
  AutoAnnotationRequest,
  AutoAnnotationResponse,
  CleanPreviewRequest,
  CleanPreviewResponse,
  CleanRulesResponse,
  GovernanceAnalyzeRequest,
  GovernanceAnalyzeResponse,
  GovernanceCommonLinesLearnResponse,
  GovernanceProfileCreate,
  GovernanceProfileImportResponse,
  GovernanceProfileListResponse,
  GovernanceProfileOut,
  GovernanceProfileResolvedResponse,
  GovernanceProfileUpdate,
  IngestionPreviewResponse,
  KeywordExtractRequest,
  KeywordExtractResponse,
  LLMCleanPreviewRequest,
  LLMCleanPreviewResponse,
  PipelineCapabilitiesResponse,
  PipelineChunkPreviewRequest,
  PipelineChunkPreviewResponse,
  PipelineParsePreviewResponse,
  ZipWithImagesResponse,
} from '@/types/processing'

import { API_LONG_TIMEOUT_MS } from '@/lib/env'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'
import { apiClient, openapiRequest, type ApiRequestOptions } from '@/lib/api/core'
import { parseApiResponse } from '@/lib/openapi-request'
import { regressionCaseBundleSchema, regressionCaseImportResponseSchema } from '@/lib/regression-case-schema'
import { dateTimeSchema, integerSchema, recordSchema } from '@/lib/response-schema'
import { matchesResourceId } from '@/lib/resource-id'

export type PipelinePluginSuggestedPatch = OpenApiSchema<'PipelinePluginSuggestedPatch'>
type PipelinePluginChunkReportRequestSchema = OpenApiSchema<'PipelinePluginChunkReportRequest'>
type PipelinePluginGoldenDraftRequestSchema = OpenApiSchema<'PipelinePluginGoldenDraftRequest'>
type PipelinePluginGoldenDraftImportRequestSchema = OpenApiSchema<'PipelinePluginGoldenDraftImportRequest'>

const pluginStageSchema = z.enum(['governance', 'chunk', 'kg'])
const pluginParamsSchema = z.record(z.string(), z.union([z.string(), z.number(), z.boolean(), z.null()])).nullish()
const pluginRegistryItemSchema = z.looseObject({
  id: z.string(),
  version: z.string(),
  name: z.string(),
  executable: z.boolean(),
  package_hash: z.string(),
  stages: z.array(pluginStageSchema),
  refs: z.object({
    governance: z.string().nullish(),
    chunk: z.string().nullish(),
    kg: z.string().nullish(),
  }),
  suggested_pipeline_patch: z.object({
    governance_enabled: z.boolean().nullish(),
    persist_parsed_content: z.boolean().nullish(),
    governance_python_params: pluginParamsSchema,
    chunk_python_params: pluginParamsSchema,
    kg_python_params: pluginParamsSchema,
  }) satisfies z.ZodType<PipelinePluginSuggestedPatch>,
  test_report: z.looseObject({
    plugin_id: z.string().nullish(),
    version: z.string().nullish(),
    tested_at: z.string().nullish(),
    golden_draft: z.looseObject({ items_total: integerSchema.nullish() }),
  }),
  contract: z.looseObject({ golden: z.looseObject({ enabled: z.boolean() }) }),
  processing_templates: z.looseObject({
    templates: z.array(z.looseObject({ key: z.string(), name: z.string(), stage: pluginStageSchema })),
  }),
})
const pluginRegistryErrorSchema = z.object({
  plugin_dir: z.string(),
  manifest_path: z.string(),
  error: z.string(),
}) satisfies z.ZodType<OpenApiSchema<'PipelinePluginListError'>>
const pluginRegistrySchema = z.object({
  items: z.array(pluginRegistryItemSchema),
  errors: z.array(pluginRegistryErrorSchema),
})

export type PipelinePluginItem = z.infer<typeof pluginRegistryItemSchema>
export type PipelinePluginListError = z.infer<typeof pluginRegistryErrorSchema>

type PipelinePluginGoldenDraftRequest = Pick<PipelinePluginGoldenDraftRequestSchema, 'dataset_id' | 'plugin_ref'> &
  Partial<Omit<PipelinePluginGoldenDraftRequestSchema, 'dataset_id' | 'plugin_ref'>>

type PipelinePluginGoldenDraftImportRequest = Pick<
  PipelinePluginGoldenDraftImportRequestSchema,
  'dataset_id' | 'plugin_ref'
> &
  Partial<Omit<PipelinePluginGoldenDraftImportRequestSchema, 'dataset_id' | 'plugin_ref'>>

const pluginGoldenDraftSchema = z
  .looseObject({
    dataset_id: z.string(),
    plugin_id: z.string(),
    plugin_version: z.string(),
    plugin_ref: z.string(),
    items_total: integerSchema.nonnegative(),
    bundle: regressionCaseBundleSchema.extend({ items: z.array(recordSchema) }),
  })
  .refine(
    (draft) => draft.dataset_id === draft.bundle.dataset_id && draft.items_total === draft.bundle.items.length,
    '插件评测草稿的数据集或样本数量不一致',
  ) satisfies z.ZodType<OpenApiSchema<'PipelinePluginGoldenDraftResponse'>>

const pluginGoldenDraftImportSchema = z.looseObject({
  draft: pluginGoldenDraftSchema,
  import_result: regressionCaseImportResponseSchema,
}) satisfies z.ZodType<OpenApiSchema<'PipelinePluginGoldenDraftImportResponse'>>

function assertPluginGoldenDraftScope(
  draft: z.infer<typeof pluginGoldenDraftSchema>,
  request: PipelinePluginGoldenDraftRequest,
): void {
  if (!matchesResourceId(draft.dataset_id, request.dataset_id) || draft.plugin_ref !== request.plugin_ref.trim()) {
    throw new Error('插件评测草稿与请求的数据集或插件不一致，请先刷新样本列表')
  }
}

type PipelinePluginChunkReportRequest = Pick<PipelinePluginChunkReportRequestSchema, 'plugin_ref'> &
  Partial<Omit<PipelinePluginChunkReportRequestSchema, 'plugin_ref'>>

const reportCountSchema = integerSchema.nonnegative()
const pluginChunkReportSchema = z.looseObject({
  schema: z.string(),
  generated_at: dateTimeSchema,
  passed: z.boolean(),
  plugin: recordSchema,
  summary: z.looseObject({
    governed_records: reportCountSchema,
    chunks: reportCountSchema,
    kg_events: reportCountSchema,
  }),
  readiness: z.object({
    status: z.enum(['passed', 'failed']),
    checks: z.array(
      z.object({
        name: z.string(),
        passed: z.boolean(),
        value: integerSchema,
        required: z.boolean(),
        errors: z.array(recordSchema),
      }),
    ),
  }),
  sections: z.array(
    z.looseObject({
      knowledge_section: z.string(),
      governed_records: reportCountSchema,
      chunks: reportCountSchema,
      kg_events: reportCountSchema,
      chunk_kinds: z.record(z.string(), reportCountSchema),
      metadata_fields: z.array(z.string()),
      kg_entity_types: z.array(z.string()),
      examples: z.array(
        z.looseObject({
          title: z.string(),
          chunk_kind: z.string(),
          content_chars: reportCountSchema,
          metadata_focus: recordSchema,
          content_preview: z.string(),
        }),
      ),
    }),
  ),
}) satisfies z.ZodType<OpenApiSchema<'PipelinePluginChunkReportResponse'>>

export type PipelinePluginChunkReportResponse = z.infer<typeof pluginChunkReportSchema>

const capabilityInfoSchema = z.object({
  name: z.string(),
  available: z.boolean(),
  notes: z.string().nullish(),
})
const pipelineCapabilitiesSchema = z.object({
  default_parser_backend: z.string(),
  default_chunk_strategy: z.string(),
  pdf_backends: z.array(capabilityInfoSchema),
  chunk_strategies: z.array(capabilityInfoSchema),
}) satisfies z.ZodType<PipelineCapabilitiesResponse>

const governanceProfileSummarySchema = z.looseObject({
  id: z.string().nullish(),
  key: z.string(),
  name: z.string(),
  description: z.string().nullish(),
  is_system: z.boolean(),
})
const processingScriptSchema = z.looseObject({
  name: z.string(),
  language: z.enum(['javascript', 'typescript', 'python', 'rust']),
  stage: z.enum(['post_parse', 'post_governance']),
  content: z.string(),
})
const governanceProfilePayloadSchema = z.looseObject({
  version: z.string(),
  extends: z.string().nullish(),
  input_formats: z.array(z.enum(['markdown', 'html'])),
  pipeline_patch: recordSchema,
  regex_rules: z.array(z.object({ pattern: z.string(), repl: z.string(), flags: integerSchema })),
  processing_scripts: z.array(
    processingScriptSchema.extend({
      enabled: z.boolean(),
      description: z.string().nullish(),
      created_at: dateTimeSchema.nullish(),
    }),
  ),
})
const governanceProfileSchema = governanceProfileSummarySchema.extend({
  payload: governanceProfilePayloadSchema,
  created_at: dateTimeSchema.nullish(),
  updated_at: dateTimeSchema.nullish(),
}) satisfies z.ZodType<GovernanceProfileOut>
const governanceProfileResolvedSchema = z.looseObject({
  profile: governanceProfileSchema,
  chain: z.array(governanceProfileSummarySchema),
  effective: governanceProfilePayloadSchema,
}) satisfies z.ZodType<GovernanceProfileResolvedResponse>
const governanceProfileListSchema = z.looseObject({
  total: integerSchema.nonnegative(),
  items: z.array(governanceProfileSummarySchema),
}) satisfies z.ZodType<GovernanceProfileListResponse>
const governanceProfileImportSchema = z.looseObject({
  created: integerSchema.nonnegative(),
  updated: integerSchema.nonnegative(),
  items: z.array(governanceProfileSummarySchema),
}) satisfies z.ZodType<GovernanceProfileImportResponse>

const builtinProcessingScriptsSchema = z.looseObject({
  total: integerSchema.nonnegative(),
  items: z.array(
    processingScriptSchema.extend({ key: z.string(), description: z.string(), tags: z.array(z.string()) }),
  ),
}) satisfies z.ZodType<BuiltinProcessingScriptListResponse>

const keywordExtractSchema = z.looseObject({
  provider: z.string(),
  keywords: z.array(z.string()),
}) satisfies z.ZodType<KeywordExtractResponse>

const autoAnnotationSchema = z.looseObject({
  annotations: z.array(
    z.looseObject({
      text: z.string(),
      type: z.enum(['entity', 'keyword', 'sensitive', 'custom']),
      label: z.string(),
      start: integerSchema.nonnegative(),
      end: integerSchema.nonnegative(),
      confidence: z.number().min(0).max(1),
      source: z.string(),
    }),
  ),
  document_tags: z.array(
    z.looseObject({
      type: z.enum(['topic', 'category', 'domain', 'industry', 'doc_type', 'sensitivity', 'quality', 'keyword']),
      value: z.string(),
      label: z.string(),
      confidence: z.number().min(0).max(1),
      source: z.string(),
    }),
  ),
  summary: z.string().nullish(),
  text_chars: integerSchema.nonnegative(),
  scanned_chars: integerSchema.nonnegative(),
  truncated: z.boolean(),
  keyword_provider: z.string().nullish(),
  strategy: z.enum(['llm', 'rules', 'hybrid']),
  providers_used: z.array(z.string()),
  warnings: z.array(z.string()),
}) satisfies z.ZodType<AutoAnnotationResponse>

export const pipelineApi = {
  async getCapabilities(options?: ApiRequestOptions): Promise<PipelineCapabilitiesResponse> {
    const response = await apiClient.get<unknown>('/pipeline/capabilities', {
      signal: options?.signal,
    })
    return parseApiResponse(response, pipelineCapabilitiesSchema, 'PipelineCapabilities')
  },

  async listPipelinePlugins({ signal }: ApiRequestOptions = {}) {
    const response = await apiClient.get<unknown>('/pipeline/plugins', { signal })
    return parseApiResponse(response, pluginRegistrySchema, 'PipelinePluginRegistry')
  },

  async buildPluginGoldenDraft(payload: PipelinePluginGoldenDraftRequest) {
    const response = await apiClient.post<unknown>('/pipeline/plugins/golden-draft', payload)
    const draft = parseApiResponse(response, pluginGoldenDraftSchema, 'PipelinePluginGoldenDraft')
    assertPluginGoldenDraftScope(draft, payload)
    return draft
  },

  async generateAndImportPluginGoldenDraft(payload: PipelinePluginGoldenDraftImportRequest) {
    const response = await apiClient.post<unknown>('/pipeline/plugins/golden-draft/import', payload)
    const result = parseApiResponse(response, pluginGoldenDraftImportSchema, 'PipelinePluginGoldenDraftImport')
    assertPluginGoldenDraftScope(result.draft, payload)
    return result
  },

  async buildPluginChunkReport(payload: PipelinePluginChunkReportRequest): Promise<PipelinePluginChunkReportResponse> {
    const response = await apiClient.post<unknown>('/pipeline/plugins/chunk-report', payload)
    return parseApiResponse(response, pluginChunkReportSchema, 'PipelinePluginChunkReport')
  },

  async governanceAnalyze(params: GovernanceAnalyzeRequest): Promise<GovernanceAnalyzeResponse> {
    const { data } = await apiClient.post<GovernanceAnalyzeResponse>('/pipeline/governance-analyze', params)
    return data
  },

  async learnCommonLines(
    params: OpenApiRequestBody<'/api/v1/pipeline/learn-common-lines', 'post'>,
  ): Promise<GovernanceCommonLinesLearnResponse> {
    const data = await openapiRequest({
      path: '/api/v1/pipeline/learn-common-lines',
      method: 'post',
      body: params,
      timeoutMs: API_LONG_TIMEOUT_MS,
    })
    const { candidates } = data
    if (!Array.isArray(candidates)) throw new Error('重复内容扫描未返回候选列表')
    return { ...data, candidates }
  },

  async listGovernanceProfiles(
    params?: { q?: string; include_builtin?: boolean; limit?: number },
    options: ApiRequestOptions = {},
  ): Promise<GovernanceProfileListResponse> {
    const response = await apiClient.get<unknown>('/pipeline/governance-profiles', { params, signal: options.signal })
    return parseApiResponse(response, governanceProfileListSchema, 'GovernanceProfileList')
  },

  async getGovernanceProfile(profileRef: string, options: ApiRequestOptions = {}): Promise<GovernanceProfileOut> {
    const response = await apiClient.get<unknown>(`/pipeline/governance-profiles/${encodeURIComponent(profileRef)}`, {
      signal: options.signal,
    })
    return parseApiResponse(response, governanceProfileSchema, 'GovernanceProfile')
  },

  async getGovernanceProfileResolved(profileRef: string, options: ApiRequestOptions = {}) {
    const response = await apiClient.get<unknown>(
      `/pipeline/governance-profiles/${encodeURIComponent(profileRef)}/resolved`,
      { signal: options.signal },
    )
    return parseApiResponse(response, governanceProfileResolvedSchema, 'GovernanceProfileResolved')
  },

  async createGovernanceProfile(payload: GovernanceProfileCreate): Promise<GovernanceProfileOut> {
    const response = await apiClient.post<unknown>('/pipeline/governance-profiles', payload)
    return parseApiResponse(response, governanceProfileSchema, 'GovernanceProfile')
  },

  async updateGovernanceProfile(profileRef: string, payload: GovernanceProfileUpdate): Promise<GovernanceProfileOut> {
    const response = await apiClient.patch<unknown>(
      `/pipeline/governance-profiles/${encodeURIComponent(profileRef)}`,
      payload,
    )
    return parseApiResponse(response, governanceProfileSchema, 'GovernanceProfile')
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
    const response = await apiClient.post<unknown>('/pipeline/governance-profiles/import', formData, {
      timeout: API_LONG_TIMEOUT_MS,
    })
    return parseApiResponse(response, governanceProfileImportSchema, 'GovernanceProfileImport')
  },

  async exportGovernanceProfile(profileRef: string): Promise<Blob> {
    const { data } = await apiClient.get<Blob>(
      `/pipeline/governance-profiles/${encodeURIComponent(profileRef)}/export`,
      {
        responseType: 'blob',
      },
    )
    return data
  },

  async exportGovernanceProfileIngestionPolicy(profileRef: string): Promise<Blob> {
    const { data } = await apiClient.get<Blob>(
      `/pipeline/governance-profiles/${encodeURIComponent(profileRef)}/export-ingestion-policy`,
      { responseType: 'blob' },
    )
    return data
  },

  async parsePreview(
    file: File,
    parserBackend = 'auto',
    options?: { signal?: AbortSignal },
  ): Promise<PipelineParsePreviewResponse> {
    const resolvedParser = resolveParserBackendForFilename(file.name, parserBackend)
    const formData = new FormData()
    formData.append('file', file)
    formData.append('parser_backend', resolvedParser.backend)
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
    const response = await apiClient.post<unknown>('/pipeline/extract-keywords', params)
    return parseApiResponse(response, keywordExtractSchema, 'KeywordExtract')
  },

  async autoAnnotations(params: AutoAnnotationRequest): Promise<AutoAnnotationResponse> {
    const body = { ...params, providers: params.providers ?? ['cpu'] }
    const response = await apiClient.post<unknown>('/pipeline/auto-annotations', body, {
      timeout: API_LONG_TIMEOUT_MS,
    })
    return parseApiResponse(response, autoAnnotationSchema, 'AutoAnnotation')
  },

  async getCleanRules(): Promise<CleanRulesResponse> {
    return openapiRequest({ path: '/api/v1/pipeline/clean-rules', method: 'get' })
  },

  async cleanPreview(params: CleanPreviewRequest, options?: ApiRequestOptions): Promise<CleanPreviewResponse> {
    const { remove_images, pii_mode, secrets_mode, ...body } = params
    const { data } = await apiClient.post<CleanPreviewResponse>(
      '/pipeline/clean-preview',
      {
        ...body,
        // Saved pipeline patches allow strings outside the preview endpoint's enums.
        remove_images:
          remove_images === 'none' || remove_images === 'decorative' || remove_images === 'all'
            ? remove_images
            : undefined,
        pii_mode: pii_mode === 'mask' || pii_mode === 'token' ? pii_mode : undefined,
        secrets_mode: secrets_mode === 'mask' || secrets_mode === 'token' ? secrets_mode : undefined,
      },
      { signal: options?.signal },
    )
    return data
  },

  async llmCleanPreview(params: LLMCleanPreviewRequest, options?: ApiRequestOptions): Promise<LLMCleanPreviewResponse> {
    const { data } = await apiClient.post<LLMCleanPreviewResponse>('/pipeline/llm-clean-preview', params, {
      signal: options?.signal,
    })
    return data
  },

  async uploadZipWithImages(params: {
    file: File
    dataset_id: string
    document_id?: string
  }): Promise<ZipWithImagesResponse> {
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
    params: { dataset_id: string; parser_backend?: string; chunk_strategy?: string; diff_max_lines?: number },
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

  async listBuiltinProcessingScripts(): Promise<BuiltinProcessingScriptListResponse> {
    const response = await apiClient.get<unknown>('/pipeline/governance-processing-scripts/builtins')
    return parseApiResponse(response, builtinProcessingScriptsSchema, 'BuiltinProcessingScripts')
  },
}

// Re-exported from generated OpenAPI types (see web/types/backend.ts) so existing
// imports from '@/lib/api/pipeline' keep working without a hand-written duplicate.
export type { BuiltinProcessingScript, BuiltinProcessingScriptListResponse } from '@/types/backend'
