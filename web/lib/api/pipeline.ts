import type {
  AutoAnnotationRequest,
  AutoAnnotationResponse,
  CleanPreviewRequest,
  CleanPreviewResponse,
  CleanRulesResponse,
  GovernanceAnalyzeRequest,
  GovernanceAnalyzeResponse,
  GovernanceCommonLinesLearnRequest,
  GovernanceCommonLinesLearnResponse,
  DocumentPipelineOptions,
  GovernanceProfileCreate,
  GovernanceProfileImportResponse,
  GovernanceProfileListResponse,
  GovernanceProfileOut,
  GovernanceProfileResolvedResponse,
  GovernanceProcessingScript,
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
} from '@/types'
import type {
  BuiltinProcessingScriptListResponse,
  OpenApiSchema,
} from '@/types/backend'
import type { OpenApiRequestBody } from '@/types/openapi-helpers'

import { API_LONG_TIMEOUT_MS } from '@/lib/env'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'
import { apiClient, openapiRequest } from '@/lib/api/core'

type GovernanceProfileUpdateBody = OpenApiRequestBody<
  '/api/v1/pipeline/governance-profiles/{profile_ref}',
  'patch'
>
type GovernanceProfileCreateBody = OpenApiRequestBody<
  '/api/v1/pipeline/governance-profiles',
  'post'
>

type PipelinePluginItemSchema = OpenApiSchema<'PipelinePluginItem'>
export type PipelinePluginSuggestedPatch = OpenApiSchema<'PipelinePluginSuggestedPatch'>
type PipelinePluginChunkReportRequestSchema = OpenApiSchema<'PipelinePluginChunkReportRequest'>
type PipelinePluginChunkReportResponseSchema = OpenApiSchema<'PipelinePluginChunkReportResponse'>
type PipelinePluginGoldenDraftRequestSchema = OpenApiSchema<'PipelinePluginGoldenDraftRequest'>
type PipelinePluginGoldenDraftImportRequestSchema = OpenApiSchema<'PipelinePluginGoldenDraftImportRequest'>

export type PipelinePluginProcessingTemplate = OpenApiSchema<'PipelinePluginProcessingTemplate'>
export type PipelinePluginProcessingTemplates = OpenApiSchema<'PipelinePluginProcessingTemplates'>
export type PipelinePluginRefs = OpenApiSchema<'PipelinePluginRefs'>
export type PipelinePluginStage = NonNullable<PipelinePluginItemSchema['stages']>[number]

export type PipelinePluginItem = Omit<PipelinePluginItemSchema, 'suggested_pipeline_patch' | 'refs' | 'stages'> & {
  stages: PipelinePluginStage[]
  refs: PipelinePluginRefs
  suggested_pipeline_patch: PipelinePluginSuggestedPatch
}

export type PipelinePluginListError = OpenApiSchema<'PipelinePluginListError'>

export type PipelinePluginListResponse = Omit<OpenApiSchema<'PipelinePluginListResponse'>, 'items' | 'errors'> & {
  items: PipelinePluginItem[]
  errors: PipelinePluginListError[]
}

export type PipelinePluginGoldenDraftRequest = Pick<
  PipelinePluginGoldenDraftRequestSchema,
  'dataset_id' | 'plugin_ref'
> &
  Partial<Omit<PipelinePluginGoldenDraftRequestSchema, 'dataset_id' | 'plugin_ref'>>

export type PipelinePluginGoldenDraftImportRequest = Pick<
  PipelinePluginGoldenDraftImportRequestSchema,
  'dataset_id' | 'plugin_ref'
> &
  Partial<Omit<PipelinePluginGoldenDraftImportRequestSchema, 'dataset_id' | 'plugin_ref'>>

export type PipelinePluginGoldenDraftResponse = OpenApiSchema<'PipelinePluginGoldenDraftResponse'>

export type PipelinePluginGoldenDraftImportResponse = OpenApiSchema<'PipelinePluginGoldenDraftImportResponse'>

export type PipelinePluginChunkReportExample = {
  title: string
  chunk_kind: string
  content_chars: number
  metadata_focus: Record<string, unknown>
  content_preview: string
} & Record<string, unknown>

export type PipelinePluginChunkReportSection = {
  knowledge_section: string
  governed_records: number
  chunks: number
  kg_events: number
  chunk_kinds: Record<string, number>
  metadata_fields: string[]
  kg_entity_types: string[]
  examples: PipelinePluginChunkReportExample[]
} & Record<string, unknown>

export type PipelinePluginChunkReportReadinessCheck = OpenApiSchema<'PipelinePluginChunkReportReadinessCheck'>
export type PipelinePluginChunkReportReadiness = OpenApiSchema<'PipelinePluginChunkReportReadiness'>

export type PipelinePluginChunkReportRequest = Pick<PipelinePluginChunkReportRequestSchema, 'plugin_ref'> &
  Partial<Omit<PipelinePluginChunkReportRequestSchema, 'plugin_ref'>>

export type PipelinePluginChunkReportResponse = Omit<
  PipelinePluginChunkReportResponseSchema,
  'plugin' | 'summary' | 'readiness' | 'sections'
> & {
  plugin: Record<string, unknown>
  summary: Record<string, unknown>
  readiness: PipelinePluginChunkReportReadiness
  sections: PipelinePluginChunkReportSection[]
}

function normalizeStringArray(value: unknown): string[] {
  if (!Array.isArray(value)) return []
  return value.map((item) => String(item ?? '').trim()).filter(Boolean)
}

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

function normalizeProcessingScriptForApi(
  script: GovernanceProcessingScript
): GovernanceProcessingScript & { enabled: boolean } {
  return {
    ...script,
    enabled: script.enabled ?? false,
  }
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function isInputFormat(value: unknown): value is 'markdown' | 'html' {
  return value === 'markdown' || value === 'html'
}

function isRegexRuleInput(value: unknown): value is { pattern: string; repl?: string; flags?: number } {
  return isRecord(value) && typeof value.pattern === 'string'
}

function isProcessingScript(value: unknown): value is GovernanceProcessingScript {
  return (
    isRecord(value) &&
    typeof value.name === 'string' &&
    typeof value.content === 'string' &&
    (value.language === 'javascript' ||
      value.language === 'typescript' ||
      value.language === 'python' ||
      value.language === 'rust') &&
    (value.stage === 'post_parse' || value.stage === 'post_governance')
  )
}

function isPipelinePluginStage(value: unknown): value is PipelinePluginStage {
  return value === 'governance' || value === 'chunk' || value === 'kg'
}

function normalizePipelinePluginRefs(value: unknown): PipelinePluginRefs {
  const raw = isRecord(value) ? value : {}
  const refs: PipelinePluginRefs = {}
  if (typeof raw.governance === 'string' || raw.governance === null) refs.governance = raw.governance
  if (typeof raw.chunk === 'string' || raw.chunk === null) refs.chunk = raw.chunk
  if (typeof raw.kg === 'string' || raw.kg === null) refs.kg = raw.kg
  return refs
}

function normalizePluginPrimitiveParams(value: unknown): Record<string, string | number | boolean | null> | undefined {
  if (!isRecord(value)) return undefined
  const out: Record<string, string | number | boolean | null> = {}
  for (const [key, param] of Object.entries(value)) {
    if (!key) continue
    if (param === null || typeof param === 'string' || typeof param === 'number' || typeof param === 'boolean') {
      out[key] = param
    }
  }
  return Object.keys(out).length > 0 ? out : undefined
}

function normalizePipelinePluginSuggestedPatch(value: unknown): PipelinePluginSuggestedPatch {
  const raw = isRecord(value) ? value : {}
  const patch: PipelinePluginSuggestedPatch = {}
  if (typeof raw.governance_enabled === 'boolean') patch.governance_enabled = raw.governance_enabled
  if (typeof raw.persist_parsed_content === 'boolean') patch.persist_parsed_content = raw.persist_parsed_content
  const governanceParams = normalizePluginPrimitiveParams(raw.governance_python_params)
  if (governanceParams) patch.governance_python_params = governanceParams
  const chunkParams = normalizePluginPrimitiveParams(raw.chunk_python_params)
  if (chunkParams) patch.chunk_python_params = chunkParams
  const kgParams = normalizePluginPrimitiveParams(raw.kg_python_params)
  if (kgParams) patch.kg_python_params = kgParams
  return patch
}

function normalizePipelinePluginItem(value: unknown): PipelinePluginItem {
  const raw = isRecord(value) ? value : {}
  return {
    ...(raw as PipelinePluginItemSchema),
    stages: Array.isArray(raw.stages) ? raw.stages.filter(isPipelinePluginStage) : [],
    refs: normalizePipelinePluginRefs(raw.refs),
    suggested_pipeline_patch: normalizePipelinePluginSuggestedPatch(raw.suggested_pipeline_patch),
  }
}

function normalizeNumberRecord(value: unknown): Record<string, number> {
  if (!isRecord(value)) return {}
  const out: Record<string, number> = {}
  for (const [key, item] of Object.entries(value)) {
    if (!key) continue
    const n = Number(item)
    if (Number.isFinite(n)) out[key] = n
  }
  return out
}

function normalizePipelinePluginChunkReportExample(value: unknown): PipelinePluginChunkReportExample {
  const raw = isRecord(value) ? value : {}
  return {
    ...raw,
    title: typeof raw.title === 'string' ? raw.title : '',
    chunk_kind: typeof raw.chunk_kind === 'string' ? raw.chunk_kind : 'unknown',
    content_chars: Number(raw.content_chars ?? 0),
    metadata_focus: isRecord(raw.metadata_focus) ? raw.metadata_focus : {},
    content_preview: typeof raw.content_preview === 'string' ? raw.content_preview : '',
  }
}

function normalizePipelinePluginChunkReportSection(value: unknown): PipelinePluginChunkReportSection {
  const raw = isRecord(value) ? value : {}
  return {
    ...raw,
    knowledge_section: typeof raw.knowledge_section === 'string' ? raw.knowledge_section : '',
    governed_records: Number(raw.governed_records ?? 0),
    chunks: Number(raw.chunks ?? 0),
    kg_events: Number(raw.kg_events ?? 0),
    chunk_kinds: normalizeNumberRecord(raw.chunk_kinds),
    metadata_fields: normalizeStringArray(raw.metadata_fields),
    kg_entity_types: normalizeStringArray(raw.kg_entity_types),
    examples: Array.isArray(raw.examples) ? raw.examples.map(normalizePipelinePluginChunkReportExample) : [],
  }
}

function normalizePipelinePluginChunkReportReadinessCheck(value: unknown): PipelinePluginChunkReportReadinessCheck {
  const raw = isRecord(value) ? value : {}
  return {
    name: typeof raw.name === 'string' ? raw.name : '',
    passed: raw.passed === true,
    value: Number(raw.value ?? 0),
    required: raw.required !== false,
    errors: Array.isArray(raw.errors) ? raw.errors.filter(isRecord) : [],
  }
}

function normalizePipelinePluginChunkReportReadiness(value: unknown): PipelinePluginChunkReportReadiness {
  const raw = isRecord(value) ? value : {}
  return {
    status: raw.status === 'passed' ? 'passed' : 'failed',
    checks: Array.isArray(raw.checks) ? raw.checks.map(normalizePipelinePluginChunkReportReadinessCheck) : [],
  }
}

function normalizePipelinePluginChunkReport(value: unknown): PipelinePluginChunkReportResponse {
  const raw = isRecord(value) ? value : {}
  return {
    schema: typeof raw.schema === 'string' ? raw.schema : '',
    generated_at: typeof raw.generated_at === 'string' ? raw.generated_at : '',
    passed: raw.passed === true,
    plugin: isRecord(raw.plugin) ? raw.plugin : {},
    summary: isRecord(raw.summary) ? raw.summary : {},
    readiness: normalizePipelinePluginChunkReportReadiness(raw.readiness),
    sections: Array.isArray(raw.sections) ? raw.sections.map(normalizePipelinePluginChunkReportSection) : [],
  }
}

function normalizeGovernanceProfilePayload(payload: unknown): GovernanceProfileOut['payload'] {
  const p = isRecord(payload) ? payload : {}
  const inputFormatsRaw = p.input_formats
  const validInputFormats = Array.isArray(inputFormatsRaw) ? inputFormatsRaw.filter(isInputFormat) : []
  const input_formats =
    validInputFormats.length > 0
      ? validInputFormats
      : (['markdown'] satisfies Array<'markdown' | 'html'>)
  const regex_rules = Array.isArray(p.regex_rules)
    ? p.regex_rules.filter(isRegexRuleInput).map(normalizeRegexRuleForApi)
    : []
  const processing_scripts = Array.isArray(p.processing_scripts)
    ? p.processing_scripts.filter(isProcessingScript)
    : []
  const pipeline_patch = isRecord(p.pipeline_patch)
    ? (p.pipeline_patch as DocumentPipelineOptions)
    : {}

  return {
    version: typeof p.version === 'string' && p.version ? p.version : '1',
    extends: typeof p.extends === 'string' ? p.extends : null,
    input_formats,
    pipeline_patch,
    regex_rules,
    processing_scripts,
  }
}

function normalizeGovernanceProfileOut(profile: unknown): GovernanceProfileOut {
  const pr = isRecord(profile) ? profile : {}
  return { ...pr, payload: normalizeGovernanceProfilePayload(pr.payload) } as GovernanceProfileOut
}

export const pipelineApi = {
  async getCapabilities(): Promise<PipelineCapabilitiesResponse> {
    const data = await openapiRequest({ path: '/api/v1/pipeline/capabilities', method: 'get' })
    return {
      ...data,
      pdf_backends: data.pdf_backends ?? [],
      chunk_strategies: data.chunk_strategies ?? [],
    }
  },

  async listPipelinePlugins(): Promise<PipelinePluginListResponse> {
    const { data } = await apiClient.get('/pipeline/plugins')
    return {
      items: Array.isArray(data?.items) ? data.items.map(normalizePipelinePluginItem) : [],
      errors: Array.isArray(data?.errors)
        ? data.errors
            .filter((item: unknown) => isRecord(item))
            .map((item: Record<string, unknown>) => ({
              plugin_dir: typeof item.plugin_dir === 'string' ? item.plugin_dir : '',
              manifest_path: typeof item.manifest_path === 'string' ? item.manifest_path : '',
              error: typeof item.error === 'string' ? item.error : '',
            }))
        : [],
    }
  },

  async buildPluginGoldenDraft(
    payload: PipelinePluginGoldenDraftRequest
  ): Promise<PipelinePluginGoldenDraftResponse> {
    const { data } = await apiClient.post('/pipeline/plugins/golden-draft', payload)
    return {
      ...data,
      items_total: typeof data?.items_total === 'number' ? data.items_total : 0,
      bundle: isRecord(data?.bundle) ? data.bundle : { items: [] },
    } as PipelinePluginGoldenDraftResponse
  },

  async generateAndImportPluginGoldenDraft(
    payload: PipelinePluginGoldenDraftImportRequest
  ): Promise<PipelinePluginGoldenDraftImportResponse> {
    const { data } = await apiClient.post('/pipeline/plugins/golden-draft/import', payload)
    const draft = isRecord(data?.draft) ? data.draft : {}
    const importResult = isRecord(data?.import_result) ? data.import_result : {}
    return {
      draft: {
        ...draft,
        items_total: typeof draft.items_total === 'number' ? draft.items_total : 0,
        bundle: isRecord(draft.bundle) ? draft.bundle : { items: [] },
      } as PipelinePluginGoldenDraftResponse,
      import_result: {
        created: Number(importResult.created ?? 0),
        updated: Number(importResult.updated ?? 0),
        skipped: Number(importResult.skipped ?? 0),
        errors: Array.isArray(importResult.errors) ? importResult.errors : [],
        created_case_ids: normalizeStringArray(importResult.created_case_ids),
        updated_case_ids: normalizeStringArray(importResult.updated_case_ids),
        skipped_case_ids: normalizeStringArray(importResult.skipped_case_ids),
        case_ids: normalizeStringArray(importResult.case_ids),
      } as PipelinePluginGoldenDraftImportResponse['import_result'],
    }
  },

  async buildPluginChunkReport(
    payload: PipelinePluginChunkReportRequest
  ): Promise<PipelinePluginChunkReportResponse> {
    const { data } = await apiClient.post('/pipeline/plugins/chunk-report', payload)
    return normalizePipelinePluginChunkReport(data)
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
        processing_scripts: (payload.payload.processing_scripts ?? []).map(normalizeProcessingScriptForApi),
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
            processing_scripts: (payload.payload.processing_scripts ?? []).map(normalizeProcessingScriptForApi),
          },
        }
      : payload

    const data = await openapiRequest({
      path: '/api/v1/pipeline/governance-profiles/{profile_ref}',
      method: 'patch',
      pathParams: { profile_ref: profileRef },
      body: body as unknown as GovernanceProfileUpdateBody,
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
      { responseType: 'blob' }
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

  async autoAnnotations(params: AutoAnnotationRequest): Promise<AutoAnnotationResponse> {
    const body = {
      text: params.text,
      mode: params.mode ?? 'document_focus',
      providers: params.providers ?? ['cpu'],
      enable_llm: params.enable_llm ?? false,
      enable_llm_topics: params.enable_llm_topics ?? false,
      llm_model: params.llm_model ?? null,
      enable_keywords: params.enable_keywords ?? true,
      enable_entities: params.enable_entities ?? true,
      enable_sensitive: params.enable_sensitive ?? false,
      keyword_provider: params.keyword_provider ?? 'simple',
      keyword_top_k: params.keyword_top_k ?? 12,
      max_chars: params.max_chars ?? 20_000,
      max_annotations: params.max_annotations ?? 80,
    }
    const data = await openapiRequest({
      path: '/api/v1/pipeline/auto-annotations',
      method: 'post',
      body,
      timeoutMs: API_LONG_TIMEOUT_MS,
    })
    return {
      ...data,
      annotations: data.annotations ?? [],
      document_tags: data.document_tags ?? [],
      providers_used: data.providers_used ?? [],
      warnings: data.warnings ?? [],
    }
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

  async listBuiltinProcessingScripts(): Promise<BuiltinProcessingScriptListResponse> {
    const { data } = await apiClient.get('/pipeline/governance-processing-scripts/builtins')
    return { total: data?.total ?? 0, items: Array.isArray(data?.items) ? data.items : [] }
  },
}

// Re-exported from generated OpenAPI types (see web/types/backend.ts) so existing
// imports from '@/lib/api/pipeline' keep working without a hand-written duplicate.
export type { BuiltinProcessingScript, BuiltinProcessingScriptListResponse } from '@/types/backend'
