import type { PromptTemplate } from '@/lib/api/prompts'

const SCENARIOS = {
  all: { key: 'all', label: '全部', tone: 'neutral' },
  rag_answer: { key: 'rag_answer', label: '问答', tone: 'blue' },
  rag_query_rewrite: { key: 'rag_query_rewrite', label: '查询改写', tone: 'teal' },
  rag_post_retrieval: { key: 'rag_post_retrieval', label: '后处理', tone: 'violet' },
  kg: { key: 'kg', label: '知识图谱', tone: 'violet' },
  chunk_meta: { key: 'chunk_meta', label: '切块元数据', tone: 'blue' },
  evaluation: { key: 'evaluation', label: '评测', tone: 'green' },
  vertical: { key: 'vertical', label: '行业', tone: 'amber' },
  other: { key: 'other', label: '其他', tone: 'neutral' },
} as const
export const PROMPT_SCENARIOS = Object.values(SCENARIOS)
export type ScenarioKey = keyof typeof SCENARIOS
export type PromptFilters = {
  query: string
  scenario: ScenarioKey
  status: 'all' | 'active' | 'inactive'
  source: 'all' | 'system' | 'custom'
  category: string | null
  sort: 'updated' | 'name' | 'usage'
}
export const INITIAL_FILTERS: PromptFilters = {
  query: '',
  scenario: 'all',
  status: 'all',
  source: 'all',
  category: null,
  sort: 'updated',
}

export function promptScenario(category?: string | null) {
  switch (category) {
    case 'rag_answer':
    case 'rag_query_rewrite':
    case 'rag_post_retrieval':
    case 'chunk_meta':
      return SCENARIOS[category]
    case 'kg_extract':
    case 'kg_canonicalize':
    case 'kg_verbalize':
      return SCENARIOS.kg
    case 'llm_judge':
    case 'testset_generation':
      return SCENARIOS.evaluation
    default:
      return category?.startsWith('vertical_') ? SCENARIOS.vertical : SCENARIOS.other
  }
}

export function filterPrompts(templates: readonly PromptTemplate[], filters: PromptFilters) {
  const query = filters.query.trim().toLocaleLowerCase()
  return templates
    .filter((t) => {
      if (filters.scenario !== 'all' && promptScenario(t.category).key !== filters.scenario) return false
      if (filters.category !== null && t.category !== filters.category) return false
      if ((filters.source === 'system' && !t.is_system) || (filters.source === 'custom' && t.is_system)) return false
      if ((filters.status === 'active' && !t.is_active) || (filters.status === 'inactive' && t.is_active)) return false
      return (
        !query ||
        [t.name, t.description, t.content, t.template_key, ...t.tags].some((value) =>
          value?.toLocaleLowerCase().includes(query),
        )
      )
    })
    .sort((a, b) => {
      if (filters.sort === 'name') return a.name.localeCompare(b.name, 'zh-CN') || a.id.localeCompare(b.id)
      const difference =
        filters.sort === 'usage'
          ? b.usage_count - a.usage_count
          : (Date.parse(b.updated_at) || 0) - (Date.parse(a.updated_at) || 0)
      return difference || a.name.localeCompare(b.name, 'zh-CN') || a.id.localeCompare(b.id)
    })
}

export function splitPromptValues(value: string) {
  return [
    ...new Set(
      value
        .split(/[,，\n]/)
        .map((v) => v.trim())
        .filter(Boolean),
    ),
  ]
}
export function promptDate(value: string, full = false) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const pad = (n: number) => String(n).padStart(2, '0')
  return `${full ? `${date.getFullYear()}-` : ''}${pad(date.getMonth() + 1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
export function promptPageNumbers(current: number, total: number) {
  return [
    ...new Set([1, total, ...Array.from({ length: 5 }, (_, i) => current + i - 2).filter((p) => p > 0 && p <= total)]),
  ].sort((a, b) => a - b)
}
