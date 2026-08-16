import type { DocumentPipelineOptions } from '@/types'

import { validateChunkStrategyParams } from '@/lib/chunk-strategy-params'

type UnknownRecord = Record<string, unknown>

function isRecord(value: unknown): value is UnknownRecord {
  return Boolean(value) && typeof value === 'object' && !Array.isArray(value)
}

function toBool(value: unknown): boolean | undefined {
  return typeof value === 'boolean' ? value : undefined
}

function toInt(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const parsed = Number.parseInt(value, 10)
    return Number.isFinite(parsed) ? parsed : undefined
  }
  return undefined
}

function toFloat(value: unknown): number | undefined {
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const parsed = Number.parseFloat(value)
    return Number.isFinite(parsed) ? parsed : undefined
  }
  return undefined
}

function toString(value: unknown): string | undefined {
  return typeof value === 'string' ? value : undefined
}

function normalizeImageMode(value: unknown): 'none' | 'decorative' | 'all' {
  const v = (toString(value) || '').toLowerCase()
  if (v === 'decorative' || v === 'all' || v === 'none') return v
  return 'none'
}

function normalizeMaskingMode(value: unknown): 'mask' | 'token' {
  const v = (toString(value) || '').toLowerCase()
  if (v === 'token') return 'token'
  return 'mask'
}

function normalizeRegexRules(
  value: unknown
): Array<{ pattern: string; repl: string; flags: number }> {
  if (!Array.isArray(value)) return []
  const out: Array<{ pattern: string; repl: string; flags: number }> = []
  for (const item of value) {
    if (!isRecord(item)) continue
    const pattern = typeof item.pattern === 'string' ? item.pattern.trim() : ''
    if (!pattern) continue
    const repl = typeof item.repl === 'string' ? item.repl : ''
    const flags = typeof item.flags === 'number' ? item.flags : 0
    out.push({ pattern, repl, flags })
    if (out.length >= 60) break
  }
  return out
}

function normalizePluginParams(
  value: unknown
): Record<string, unknown> | undefined {
  const validated = validateChunkStrategyParams(value)
  return validated.ok ? validated.value : undefined
}

export const DEFAULT_DOCUMENT_PIPELINE_OPTIONS: DocumentPipelineOptions = {
  governance_enabled: false,
  governance_remove_toc_lines: true,
  governance_remove_noise_lines: true,
  governance_unwrap_lines: true,
  governance_remove_common_lines: true,
  governance_remove_boilerplate: false,
  governance_remove_images: 'none',
  governance_regex_rules: [],
  governance_extract_frontmatter: false,
  governance_strip_frontmatter: false,
  governance_detect_language: false,
  governance_language_min_chars: 40,
  governance_normalize_urls: false,
  governance_normalize_urls_strip_tracking: true,
  governance_drop_duplicate_paragraphs: false,
  governance_drop_duplicate_paragraphs_min_occurrences: 3,
  governance_drop_duplicate_paragraphs_min_chars: 40,
  governance_drop_duplicate_paragraphs_max_chars: 1200,
  governance_trim_references: false,
  governance_extract_keywords: false,
  governance_keywords_provider: 'auto',
  governance_keywords_top_k: 10,
  governance_keywords_max_chars: 20000,
  governance_normalize_tables: false,
  governance_strip_code_line_numbers: false,
  governance_pii_anonymize: false,
  governance_pii_mode: 'mask',
  governance_pii_mask: '[REDACTED]',
  governance_secrets_redact: false,
  governance_secrets_mode: 'mask',
  governance_secrets_mask: '[SECRET]',
  governance_max_blank_lines: 1,
  governance_html_xpath: '',
  governance_drop_outline_only: false,
  governance_drop_outline_min_content_chars: 200,
  governance_drop_outline_max_heading_ratio: 0.85,
  governance_drop_low_density: false,
  governance_drop_low_density_threshold: 0.12,
  governance_quarantine_on_drop: false,
  governance_unwrap_max_line_length: 120,
  governance_noise_min_chars: 2,
  governance_noise_ratio_threshold: 0.2,
  governance_common_lines_min_docs: 3,
  governance_common_lines_min_ratio: 0.35,
  governance_python_plugin: undefined,
  governance_python_params: undefined,
  parse_fallback_enabled: false,
  parse_fallback_min_content_chars: 120,
  parse_fallback_max_retries: 1,
  persist_parsed_content: false,
  persist_parsed_content_max_chars: 200000,
  near_dedup_enabled: false,
  near_dedup_hamming_threshold: 3,
  near_dedup_max_bucket_size: 256,
  chunk_size: 1000,
  chunk_overlap: 200,
  chunk_merge_small_min_chars: 0,
  chunk_strategy_params: undefined,
  chunk_python_plugin: undefined,
  chunk_python_params: undefined,
  embedding_context_prefix_enabled: false,
  chunk_vector_enabled: true,
  bm25_index_enabled: true,
  kg_enabled: true,
  kg_python_plugin: undefined,
  kg_python_params: undefined,
  event_vector_enabled: true,
  entity_vector_enabled: true,
}

export function normalizeDocumentPipelineOptions(
  raw: unknown
): DocumentPipelineOptions {
  if (!isRecord(raw)) return { ...DEFAULT_DOCUMENT_PIPELINE_OPTIONS }

  const base = { ...(raw as DocumentPipelineOptions) }
  const validatedStrategyParams = validateChunkStrategyParams(
    raw.chunk_strategy_params
  )
  const chunkStrategyParams = validatedStrategyParams.ok
    ? validatedStrategyParams.value
    : undefined

  return {
    ...base,
    governance_enabled:
      toBool(raw.governance_enabled) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_enabled,
    governance_remove_toc_lines:
      toBool(raw.governance_remove_toc_lines) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_remove_toc_lines,
    governance_remove_noise_lines:
      toBool(raw.governance_remove_noise_lines) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_remove_noise_lines,
    governance_unwrap_lines:
      toBool(raw.governance_unwrap_lines) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_unwrap_lines,
    governance_remove_common_lines:
      toBool(raw.governance_remove_common_lines) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_remove_common_lines,
    governance_remove_boilerplate:
      toBool(raw.governance_remove_boilerplate) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_remove_boilerplate,
    governance_remove_images: normalizeImageMode(
      raw.governance_remove_images
    ),
    governance_regex_rules: normalizeRegexRules(raw.governance_regex_rules),
    governance_extract_frontmatter:
      toBool(raw.governance_extract_frontmatter) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_extract_frontmatter,
    governance_strip_frontmatter:
      toBool(raw.governance_strip_frontmatter) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_strip_frontmatter,
    governance_detect_language:
      toBool(raw.governance_detect_language) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_detect_language,
    governance_language_min_chars:
      toInt(raw.governance_language_min_chars) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_language_min_chars,
    governance_normalize_urls:
      toBool(raw.governance_normalize_urls) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_normalize_urls,
    governance_normalize_urls_strip_tracking:
      toBool(raw.governance_normalize_urls_strip_tracking) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_normalize_urls_strip_tracking,
    governance_drop_duplicate_paragraphs:
      toBool(raw.governance_drop_duplicate_paragraphs) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_drop_duplicate_paragraphs,
    governance_drop_duplicate_paragraphs_min_occurrences:
      toInt(raw.governance_drop_duplicate_paragraphs_min_occurrences) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_drop_duplicate_paragraphs_min_occurrences,
    governance_drop_duplicate_paragraphs_min_chars:
      toInt(raw.governance_drop_duplicate_paragraphs_min_chars) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_drop_duplicate_paragraphs_min_chars,
    governance_drop_duplicate_paragraphs_max_chars:
      toInt(raw.governance_drop_duplicate_paragraphs_max_chars) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_drop_duplicate_paragraphs_max_chars,
    governance_trim_references:
      toBool(raw.governance_trim_references) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_trim_references,
    governance_extract_keywords:
      toBool(raw.governance_extract_keywords) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_extract_keywords,
    governance_keywords_provider:
      toString(raw.governance_keywords_provider) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_keywords_provider,
    governance_keywords_top_k:
      toInt(raw.governance_keywords_top_k) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_keywords_top_k,
    governance_keywords_max_chars:
      toInt(raw.governance_keywords_max_chars) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_keywords_max_chars,
    governance_normalize_tables:
      toBool(raw.governance_normalize_tables) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_normalize_tables,
    governance_strip_code_line_numbers:
      toBool(raw.governance_strip_code_line_numbers) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_strip_code_line_numbers,
    governance_pii_anonymize:
      toBool(raw.governance_pii_anonymize) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_pii_anonymize,
    governance_pii_mode: normalizeMaskingMode(raw.governance_pii_mode),
    governance_pii_mask:
      toString(raw.governance_pii_mask) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_pii_mask,
    governance_secrets_redact:
      toBool(raw.governance_secrets_redact) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_secrets_redact,
    governance_secrets_mode: normalizeMaskingMode(raw.governance_secrets_mode),
    governance_secrets_mask:
      toString(raw.governance_secrets_mask) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_secrets_mask,
    governance_max_blank_lines:
      toInt(raw.governance_max_blank_lines) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_max_blank_lines,
    governance_html_xpath:
      toString(raw.governance_html_xpath) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_html_xpath,
    governance_drop_outline_only:
      toBool(raw.governance_drop_outline_only) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_drop_outline_only,
    governance_drop_outline_min_content_chars:
      toInt(raw.governance_drop_outline_min_content_chars) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_drop_outline_min_content_chars,
    governance_drop_outline_max_heading_ratio:
      toFloat(raw.governance_drop_outline_max_heading_ratio) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_drop_outline_max_heading_ratio,
    governance_drop_low_density:
      toBool(raw.governance_drop_low_density) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_drop_low_density,
    governance_drop_low_density_threshold:
      toFloat(raw.governance_drop_low_density_threshold) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_drop_low_density_threshold,
    governance_quarantine_on_drop:
      toBool(raw.governance_quarantine_on_drop) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_quarantine_on_drop,
    governance_unwrap_max_line_length:
      toInt(raw.governance_unwrap_max_line_length) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_unwrap_max_line_length,
    governance_noise_min_chars:
      toInt(raw.governance_noise_min_chars) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_noise_min_chars,
    governance_noise_ratio_threshold:
      toFloat(raw.governance_noise_ratio_threshold) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_noise_ratio_threshold,
    governance_common_lines_min_docs:
      toInt(raw.governance_common_lines_min_docs) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_common_lines_min_docs,
    governance_common_lines_min_ratio:
      toFloat(raw.governance_common_lines_min_ratio) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_common_lines_min_ratio,
    governance_python_plugin:
      toString(raw.governance_python_plugin) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_python_plugin,
    governance_python_params:
      normalizePluginParams(raw.governance_python_params) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.governance_python_params,
    parse_fallback_enabled:
      toBool(raw.parse_fallback_enabled) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.parse_fallback_enabled,
    parse_fallback_min_content_chars:
      toInt(raw.parse_fallback_min_content_chars) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.parse_fallback_min_content_chars,
    parse_fallback_max_retries:
      toInt(raw.parse_fallback_max_retries) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.parse_fallback_max_retries,
    persist_parsed_content:
      toBool(raw.persist_parsed_content) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.persist_parsed_content,
    persist_parsed_content_max_chars:
      toInt(raw.persist_parsed_content_max_chars) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.persist_parsed_content_max_chars,
    near_dedup_enabled:
      toBool(raw.near_dedup_enabled) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.near_dedup_enabled,
    near_dedup_hamming_threshold:
      toInt(raw.near_dedup_hamming_threshold) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.near_dedup_hamming_threshold,
    near_dedup_max_bucket_size:
      toInt(raw.near_dedup_max_bucket_size) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.near_dedup_max_bucket_size,
    chunk_size:
      toInt(raw.chunk_size) ?? DEFAULT_DOCUMENT_PIPELINE_OPTIONS.chunk_size,
    chunk_overlap:
      toInt(raw.chunk_overlap) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.chunk_overlap,
    chunk_merge_small_min_chars:
      toInt(raw.chunk_merge_small_min_chars) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.chunk_merge_small_min_chars,
    chunk_strategy_params:
      chunkStrategyParams ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.chunk_strategy_params,
    chunk_python_plugin:
      toString(raw.chunk_python_plugin) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.chunk_python_plugin,
    chunk_python_params:
      normalizePluginParams(raw.chunk_python_params) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.chunk_python_params,
    embedding_context_prefix_enabled:
      toBool(raw.embedding_context_prefix_enabled) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.embedding_context_prefix_enabled,
    chunk_vector_enabled:
      toBool(raw.chunk_vector_enabled) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.chunk_vector_enabled,
    bm25_index_enabled:
      toBool(raw.bm25_index_enabled) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.bm25_index_enabled,
    kg_enabled:
      toBool(raw.kg_enabled) ?? DEFAULT_DOCUMENT_PIPELINE_OPTIONS.kg_enabled,
    kg_python_plugin:
      toString(raw.kg_python_plugin) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.kg_python_plugin,
    kg_python_params:
      normalizePluginParams(raw.kg_python_params) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.kg_python_params,
    event_vector_enabled:
      toBool(raw.event_vector_enabled) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.event_vector_enabled,
    entity_vector_enabled:
      toBool(raw.entity_vector_enabled) ??
      DEFAULT_DOCUMENT_PIPELINE_OPTIONS.entity_vector_enabled,
  }
}
