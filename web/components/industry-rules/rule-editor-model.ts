import type { IndustryRulesetDetail } from '@/types/backend'

export const RULE_SECTIONS = ['glossary', 'patterns', 'intents'] as const
export type RuleSection = (typeof RULE_SECTIONS)[number]

export function isRuleSection(value: string): value is RuleSection {
  return RULE_SECTIONS.some((section) => section === value)
}
type RuleValues = Required<Pick<IndustryRulesetDetail, RuleSection>>
type RowFields = {
  term: string
  words: string
  followup: string
  name: string
  route: string
  enabled: boolean
}
export type RuleRow = RowFields & {
  id: string
  source: Record<string, unknown> | string[] | null
  original: RowFields
}
export type RuleDraft = { rows: RuleRow[]; json: string | null; saved: string }
export type RulesetDraft = Record<RuleSection, RuleDraft>

const defaults: RowFields = { term: '', words: '', followup: '', name: '', route: 'default', enabled: true }
const asText = (value: unknown) => (typeof value === 'string' ? value : '')
const asList = (value: unknown) =>
  Array.isArray(value) ? value.filter((item): item is string => typeof item === 'string').join(', ') : ''
const splitWords = (value: string) =>
  value
    .split(/[,，、;；\n]+/)
    .map((word) => word.trim())
    .filter(Boolean)
const isRecord = (value: unknown): value is Record<string, unknown> =>
  typeof value === 'object' && value !== null && !Array.isArray(value)

export function createRuleRow(id: string): RuleRow {
  return { ...defaults, id, source: null, original: { ...defaults } }
}

export function rowsFromValue<T extends RuleSection>(section: T, value: RuleValues[T]): RuleRow[] {
  if (!Array.isArray(value)) {
    return Object.entries(value).map(([term, words], index) => {
      const fields = { ...defaults, term, words: words.join(', ') }
      return { ...fields, id: `glossary-${index}`, source: words, original: { ...fields } }
    })
  }
  return value.map((source, index) => {
    const fields = {
      ...defaults,
      words: asList(section === 'patterns' ? (source.markers ?? source.keywords) : source.keywords),
      followup: asText(source.followup ?? source.followup_template),
      name: asText(source.name),
      route: asText(source.route) || 'default',
      enabled: source.enabled !== false,
    }
    return { ...fields, id: `${section}-${index}`, source, original: { ...fields } }
  })
}

function validateGlossaryTerms(terms: readonly string[]) {
  const seen = new Set<string>()
  for (const [index, term] of terms.entries()) {
    const normalized = term.trim()
    if (normalized === '') throw new Error(`第 ${index + 1} 条：请填写术语。`)
    if (seen.has(normalized)) throw new Error(`术语「${normalized}」重复，请修改后保存。`)
    seen.add(normalized)
  }
}

// Each API write replaces a complete section. Keep every unedited field and row,
// including extensions and legacy key names that the form does not understand.
export function serializeRows<T extends RuleSection>(section: T, rows: readonly RuleRow[]): RuleValues[T] {
  if (section === 'glossary') {
    validateGlossaryTerms(rows.map((row) => row.term))
    const entries = rows.map((row) => {
      const term = row.term === row.original.term ? row.term : row.term.trim()
      const words = row.words === row.original.words && Array.isArray(row.source) ? row.source : splitWords(row.words)
      return [term, words]
    })
    return Object.fromEntries(entries) as RuleValues[T]
  }
  const records = rows.map((row, index) => {
    const source = Array.isArray(row.source) ? null : row.source
    const record = { ...source }
    const changed = (field: keyof RowFields) => source === null || row[field] !== row.original[field]
    if (section === 'patterns') {
      if (changed('words')) {
        const words = splitWords(row.words)
        if (!words.length) throw new Error(`第 ${index + 1} 条：请填写触发词。`)
        const markerKey =
          !Object.hasOwn(record, 'markers') && Object.hasOwn(record, 'keywords') ? 'keywords' : 'markers'
        record[markerKey] = words
      }
      if (changed('followup')) {
        const followupKey =
          !Object.hasOwn(record, 'followup') && Object.hasOwn(record, 'followup_template')
            ? 'followup_template'
            : 'followup'
        record[followupKey] = row.followup
      }
      if (changed('enabled')) record.enabled = row.enabled
    } else {
      if (changed('name')) {
        if (!row.name.trim()) throw new Error(`第 ${index + 1} 条：请填写意图名称。`)
        record.name = row.name.trim()
      }
      if (changed('words')) record.keywords = splitWords(row.words)
      if (changed('route')) record.route = row.route.trim() || 'default'
    }
    return record
  })
  return records as RuleValues[T]
}

export function parseRuleJson<T extends RuleSection>(section: T, raw: string): RuleValues[T] {
  let value: unknown
  try {
    value = JSON.parse(raw)
  } catch {
    throw new Error('JSON 格式有误，请检查引号、逗号和括号。')
  }
  if (section === 'glossary') {
    if (
      !isRecord(value) ||
      Object.values(value).some((words) => !Array.isArray(words) || words.some((word) => typeof word !== 'string'))
    ) {
      throw new Error('术语词库需要是对象，每个术语对应一组扩展词。')
    }
    validateGlossaryTerms(Object.keys(value))
  } else if (!Array.isArray(value) || value.some((item) => !isRecord(item))) {
    throw new Error('规则需要是数组，每条规则需要是对象。')
  }
  return value as RuleValues[T]
}

export function createRuleDraft(section: RuleSection, value: RuleValues[RuleSection]): RuleDraft {
  return { rows: rowsFromValue(section, value), json: null, saved: JSON.stringify(value) }
}

export function createRulesetDraft(value: RuleValues): RulesetDraft {
  return {
    glossary: createRuleDraft('glossary', value.glossary),
    patterns: createRuleDraft('patterns', value.patterns),
    intents: createRuleDraft('intents', value.intents),
  }
}

export function draftValue<T extends RuleSection>(section: T, draft: RuleDraft): RuleValues[T] {
  return draft.json === null ? serializeRows(section, draft.rows) : parseRuleJson(section, draft.json)
}

export function isRuleDraftDirty(section: RuleSection, draft: RuleDraft): boolean {
  try {
    return JSON.stringify(draftValue(section, draft)) !== draft.saved
  } catch {
    return true
  }
}
