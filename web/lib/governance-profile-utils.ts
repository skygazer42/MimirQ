import { readNonEmptyString } from '@/lib/primitive-text'
import type {
  CleanPreviewRequest,
  GovernanceProfileCreate,
  GovernanceProfileOut,
  GovernanceProfilePayload,
  RegexRuleModel,
} from '@/types'

type BuildCleanPreviewOptions = {
  includeDiff?: boolean
  diffMaxLines?: number
  inputFormat?: 'markdown' | 'html'
  htmlXPath?: string
  useDefaultRules?: boolean
}

function normalizeRegexRules(rules: unknown): RegexRuleModel[] {
  if (!Array.isArray(rules)) return []
  const out: RegexRuleModel[] = []
  for (const item of rules) {
    if (!item || typeof item !== 'object') continue
    const raw = item
    const pattern = typeof raw.pattern === 'string' ? raw.pattern : ''
    if (!pattern) continue
    out.push({
      pattern,
      repl: typeof raw.repl === 'string' ? raw.repl : '',
      flags: typeof raw.flags === 'number' ? raw.flags : 0,
    })
  }
  return out
}

export function buildIngestionPolicyExportFilename(profileKey: string): string {
  const safe = profileKey
    .trim()
    .replaceAll(/[^a-zA-Z0-9_.-]+/g, '_')
    .slice(0, 64)
  return `${safe === '' ? 'profile' : safe}.ingestion_policy.json`
}

/**
 * Map a GovernanceProfile payload to the `pipeline/clean-preview` request shape.
 *
 * This intentionally mirrors backend mapping used by ingestion-preview so the UI “sandbox test”
 * can reproduce the same governance behavior.
 */
export function buildCleanPreviewRequestFromGovernanceProfile(
  payload: GovernanceProfilePayload,
  markdown: string,
  options: BuildCleanPreviewOptions = {},
): CleanPreviewRequest {
  const patch = payload.pipeline_patch

  const inputFormat = options.inputFormat ?? payload.input_formats[0]

  const rules: RegexRuleModel[] = [
    ...normalizeRegexRules(patch.governance_regex_rules),
    ...normalizeRegexRules(payload.regex_rules),
  ]

  return {
    markdown,
    rules,
    rule_packs:
      Array.isArray(patch.governance_rule_packs) && patch.governance_rule_packs.length
        ? patch.governance_rule_packs
        : undefined,
    use_default_rules: options.useDefaultRules,
    include_diff: options.includeDiff,
    diff_max_lines: options.diffMaxLines,
    input_format: inputFormat,
    html_xpath: readNonEmptyString(options.htmlXPath) ?? readNonEmptyString(patch.governance_html_xpath),
    max_blank_lines:
      typeof patch.governance_max_blank_lines === 'number' ? patch.governance_max_blank_lines : undefined,
    remove_toc_lines: patch.governance_remove_toc_lines ?? undefined,
    remove_noise_lines: patch.governance_remove_noise_lines ?? undefined,
    remove_common_lines: patch.governance_remove_common_lines ?? undefined,
    unwrap_lines: patch.governance_unwrap_lines ?? undefined,
    remove_boilerplate: patch.governance_remove_boilerplate ?? undefined,
    remove_images: patch.governance_remove_images ?? undefined,
    extract_frontmatter: patch.governance_extract_frontmatter ?? undefined,
    strip_frontmatter: patch.governance_strip_frontmatter ?? undefined,
    detect_language: patch.governance_detect_language ?? undefined,
    language_min_chars:
      typeof patch.governance_language_min_chars === 'number' ? patch.governance_language_min_chars : undefined,
    normalize_urls: patch.governance_normalize_urls ?? undefined,
    normalize_urls_strip_tracking: patch.governance_normalize_urls_strip_tracking ?? undefined,
    drop_duplicate_paragraphs: patch.governance_drop_duplicate_paragraphs ?? undefined,
    drop_duplicate_paragraphs_min_occurrences:
      typeof patch.governance_drop_duplicate_paragraphs_min_occurrences === 'number'
        ? patch.governance_drop_duplicate_paragraphs_min_occurrences
        : undefined,
    drop_duplicate_paragraphs_min_chars:
      typeof patch.governance_drop_duplicate_paragraphs_min_chars === 'number'
        ? patch.governance_drop_duplicate_paragraphs_min_chars
        : undefined,
    drop_duplicate_paragraphs_max_chars:
      typeof patch.governance_drop_duplicate_paragraphs_max_chars === 'number'
        ? patch.governance_drop_duplicate_paragraphs_max_chars
        : undefined,
    trim_references: patch.governance_trim_references ?? undefined,
    extract_keywords: patch.governance_extract_keywords ?? undefined,
    keywords_provider:
      typeof patch.governance_keywords_provider === 'string' ? patch.governance_keywords_provider : undefined,
    keywords_top_k: typeof patch.governance_keywords_top_k === 'number' ? patch.governance_keywords_top_k : undefined,
    keywords_max_chars:
      typeof patch.governance_keywords_max_chars === 'number' ? patch.governance_keywords_max_chars : undefined,
    normalize_tables: patch.governance_normalize_tables ?? undefined,
    strip_code_line_numbers: patch.governance_strip_code_line_numbers ?? undefined,
    pii_anonymize: patch.governance_pii_anonymize ?? undefined,
    pii_mode: patch.governance_pii_mode ?? undefined,
    pii_mask: typeof patch.governance_pii_mask === 'string' ? patch.governance_pii_mask : undefined,
    secrets_redact: patch.governance_secrets_redact ?? undefined,
    secrets_mode: patch.governance_secrets_mode ?? undefined,
    secrets_mask: typeof patch.governance_secrets_mask === 'string' ? patch.governance_secrets_mask : undefined,
    drop_outline_only: patch.governance_drop_outline_only ?? undefined,
    drop_outline_min_content_chars:
      typeof patch.governance_drop_outline_min_content_chars === 'number'
        ? patch.governance_drop_outline_min_content_chars
        : undefined,
    drop_outline_max_heading_ratio:
      typeof patch.governance_drop_outline_max_heading_ratio === 'number'
        ? patch.governance_drop_outline_max_heading_ratio
        : undefined,
    drop_low_density: patch.governance_drop_low_density ?? undefined,
    drop_low_density_threshold:
      typeof patch.governance_drop_low_density_threshold === 'number'
        ? patch.governance_drop_low_density_threshold
        : undefined,
    unwrap_max_line_length:
      typeof patch.governance_unwrap_max_line_length === 'number' ? patch.governance_unwrap_max_line_length : undefined,
    noise_min_chars:
      typeof patch.governance_noise_min_chars === 'number' ? patch.governance_noise_min_chars : undefined,
    noise_ratio_threshold:
      typeof patch.governance_noise_ratio_threshold === 'number' ? patch.governance_noise_ratio_threshold : undefined,
    common_lines_min_occurrences:
      typeof patch.governance_common_lines_min_docs === 'number' ? patch.governance_common_lines_min_docs : undefined,
  }
}

export function buildGovernanceProfileCreateFromExisting(profile: GovernanceProfileOut): GovernanceProfileCreate {
  const name = readNonEmptyString(profile.name) ?? 'Untitled'

  return {
    name: `${name} (copy)`,
    description: readNonEmptyString(profile.description),
    // Leave `key` empty by default; the backend will validate and store it as optional.
    payload: profile.payload,
  }
}
