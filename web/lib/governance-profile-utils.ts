import type { CleanPreviewRequest, GovernanceProfileCreate, GovernanceProfileOut, GovernanceProfilePayload, RegexRuleModel } from '@/types'

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
  const raw = String(profileKey || '').trim()
  const safe = (raw || 'profile').replaceAll(/[^a-zA-Z0-9_.-]+/g, '_').slice(0, 64) || 'profile'
  return `${safe}.ingestion_policy.json`
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
  options: BuildCleanPreviewOptions = {}
): CleanPreviewRequest {
  const patch = payload?.pipeline_patch || {}

  const inputFormat =
    options.inputFormat ||
    (Array.isArray(payload?.input_formats) && payload.input_formats.length ? payload.input_formats[0] : 'markdown')

  const rules: RegexRuleModel[] = [
    ...normalizeRegexRules(patch?.governance_regex_rules),
    ...normalizeRegexRules(payload?.regex_rules),
  ]

  return {
    markdown: String(markdown ?? ''),
    rules,
    rule_packs: Array.isArray(patch?.governance_rule_packs) && patch.governance_rule_packs.length ? patch.governance_rule_packs : undefined,
    use_default_rules: options.useDefaultRules ?? true,
    include_diff: Boolean(options.includeDiff),
    diff_max_lines: typeof options.diffMaxLines === 'number' ? options.diffMaxLines : 2000,
    input_format: inputFormat,
    html_xpath: options.htmlXPath || patch?.governance_html_xpath || undefined,
    normalize_line_endings: true,
    trim_trailing_spaces: true,
    collapse_blank_lines: true,
    max_blank_lines: typeof patch?.governance_max_blank_lines === 'number' ? patch.governance_max_blank_lines : 1,
    remove_control_chars: true,
    remove_toc_lines: patch?.governance_remove_toc_lines ?? true,
    remove_noise_lines: patch?.governance_remove_noise_lines ?? true,
    remove_common_lines: patch?.governance_remove_common_lines ?? true,
    unwrap_lines: patch?.governance_unwrap_lines ?? true,
    remove_boilerplate: patch?.governance_remove_boilerplate ?? false,
    remove_images: patch?.governance_remove_images ?? 'none',
    extract_frontmatter: patch?.governance_extract_frontmatter ?? false,
    strip_frontmatter: patch?.governance_strip_frontmatter ?? false,
    detect_language: patch?.governance_detect_language ?? false,
    language_min_chars: typeof patch?.governance_language_min_chars === 'number' ? patch.governance_language_min_chars : 40,
    normalize_urls: patch?.governance_normalize_urls ?? false,
    normalize_urls_strip_tracking: patch?.governance_normalize_urls_strip_tracking ?? true,
    drop_duplicate_paragraphs: patch?.governance_drop_duplicate_paragraphs ?? false,
    drop_duplicate_paragraphs_min_occurrences:
      typeof patch?.governance_drop_duplicate_paragraphs_min_occurrences === 'number'
        ? patch.governance_drop_duplicate_paragraphs_min_occurrences
        : 3,
    drop_duplicate_paragraphs_min_chars:
      typeof patch?.governance_drop_duplicate_paragraphs_min_chars === 'number'
        ? patch.governance_drop_duplicate_paragraphs_min_chars
        : 40,
    drop_duplicate_paragraphs_max_chars:
      typeof patch?.governance_drop_duplicate_paragraphs_max_chars === 'number'
        ? patch.governance_drop_duplicate_paragraphs_max_chars
        : 1200,
    trim_references: patch?.governance_trim_references ?? false,
    extract_keywords: patch?.governance_extract_keywords ?? false,
    keywords_provider: typeof patch?.governance_keywords_provider === 'string' ? patch.governance_keywords_provider : 'auto',
    keywords_top_k: typeof patch?.governance_keywords_top_k === 'number' ? patch.governance_keywords_top_k : 10,
    keywords_max_chars: typeof patch?.governance_keywords_max_chars === 'number' ? patch.governance_keywords_max_chars : 20000,
    normalize_tables: patch?.governance_normalize_tables ?? false,
    strip_code_line_numbers: patch?.governance_strip_code_line_numbers ?? false,
    pii_anonymize: patch?.governance_pii_anonymize ?? false,
    pii_mode: patch?.governance_pii_mode ?? 'mask',
    pii_mask: typeof patch?.governance_pii_mask === 'string' ? patch.governance_pii_mask : '[REDACTED]',
    secrets_redact: patch?.governance_secrets_redact ?? false,
    secrets_mode: patch?.governance_secrets_mode ?? 'mask',
    secrets_mask: typeof patch?.governance_secrets_mask === 'string' ? patch.governance_secrets_mask : '[SECRET]',
    drop_outline_only: patch?.governance_drop_outline_only ?? false,
    drop_outline_min_content_chars:
      typeof patch?.governance_drop_outline_min_content_chars === 'number'
        ? patch.governance_drop_outline_min_content_chars
        : 200,
    drop_outline_max_heading_ratio:
      typeof patch?.governance_drop_outline_max_heading_ratio === 'number'
        ? patch.governance_drop_outline_max_heading_ratio
        : 0.85,
    drop_low_density: patch?.governance_drop_low_density ?? false,
    drop_low_density_threshold:
      typeof patch?.governance_drop_low_density_threshold === 'number'
        ? patch.governance_drop_low_density_threshold
        : 0.12,
    unwrap_max_line_length:
      typeof patch?.governance_unwrap_max_line_length === 'number' ? patch.governance_unwrap_max_line_length : 120,
    noise_min_chars: typeof patch?.governance_noise_min_chars === 'number' ? patch.governance_noise_min_chars : 2,
    noise_ratio_threshold:
      typeof patch?.governance_noise_ratio_threshold === 'number' ? patch.governance_noise_ratio_threshold : 0.2,
    common_lines_min_occurrences:
      typeof patch?.governance_common_lines_min_docs === 'number' ? patch.governance_common_lines_min_docs : 3,
  }
}

export function buildGovernanceProfileCreateFromExisting(profile: GovernanceProfileOut): GovernanceProfileCreate {
  const name = String(profile?.name || '').trim() || 'Untitled'
  const descriptionRaw = typeof profile?.description === 'string' ? profile.description.trim() : ''

  return {
    name: `${name} (copy)`,
    description: descriptionRaw || undefined,
    // Leave `key` empty by default; the backend will validate and store it as optional.
    payload: (profile?.payload || { version: '1', input_formats: ['markdown'], pipeline_patch: {}, regex_rules: [] }),
  }
}
