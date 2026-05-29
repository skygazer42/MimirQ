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
} from '@/types/backend'

import { API_LONG_TIMEOUT_MS } from '@/lib/env'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'
import { apiClient, openapiRequest } from '@/lib/api/core'

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

function normalizeGovernanceProfilePayload(payload: any): GovernanceProfileOut['payload'] {
  const p = payload || {}
  const inputFormatsRaw = p.input_formats
  const input_formats =
    Array.isArray(inputFormatsRaw) && inputFormatsRaw.length > 0 ? inputFormatsRaw : ['markdown']
  const regex_rules = Array.isArray(p.regex_rules) ? p.regex_rules.map(normalizeRegexRuleForApi) : []
  const processing_scripts = Array.isArray(p.processing_scripts) ? p.processing_scripts : []

  return {
    version: typeof p.version === 'string' && p.version ? p.version : '1',
    extends: p.extends ?? null,
    input_formats,
    pipeline_patch: p.pipeline_patch ?? {},
    regex_rules,
    processing_scripts,
  }
}

function normalizeGovernanceProfileOut(profile: any): GovernanceProfileOut {
  const pr = profile || {}
  return { ...pr, payload: normalizeGovernanceProfilePayload(pr.payload) }
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
