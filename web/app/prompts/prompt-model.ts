import type { PromptTemplate } from '@/lib/api/prompts'

export const PROMPT_SCENARIOS = [
  { key: 'all', label: '全部', tone: 'neutral' },
  { key: 'rag_answer', label: '问答', tone: 'blue' },
  { key: 'rag_query_rewrite', label: '查询改写', tone: 'teal' },
  { key: 'rag_post_retrieval', label: '后处理', tone: 'violet' },
  { key: 'kg', label: '知识图谱', tone: 'violet' },
  { key: 'chunk_meta', label: '切块元数据', tone: 'blue' },
  { key: 'evaluation', label: '评测', tone: 'green' },
  { key: 'vertical', label: '行业', tone: 'amber' },
  { key: 'other', label: '其他', tone: 'neutral' },
] as const
export type ScenarioKey = typeof PROMPT_SCENARIOS[number]['key']
export type PromptFilters = {
  query: string
  scenario: ScenarioKey
  status: 'all' | 'active' | 'inactive'
  source: 'all' | 'system' | 'custom'
  category: string
  sort: 'updated' | 'name' | 'usage'
}
export const INITIAL_FILTERS: PromptFilters = {query:'',scenario:'all',status:'all',source:'all',category:'all',sort:'updated'}

export function promptScenario(category?: string | null) {
  const key:ScenarioKey = category === 'rag_answer' || category === 'rag_query_rewrite' || category === 'rag_post_retrieval' || category === 'chunk_meta'
    ? category
    : ['kg_extract','kg_canonicalize','kg_verbalize'].includes(category || '') ? 'kg'
    : ['llm_judge','testset_generation'].includes(category || '') ? 'evaluation'
    : category?.startsWith('vertical_') ? 'vertical' : 'other'
  return PROMPT_SCENARIOS.find(s => s.key === key)!
}

export function filterPrompts(templates:PromptTemplate[], filters:PromptFilters) {
  const query = filters.query.trim().toLocaleLowerCase()
  return templates.filter(t => {
    if (filters.scenario !== 'all' && promptScenario(t.category).key !== filters.scenario) return false
    if (filters.category !== 'all' && t.category !== filters.category) return false
    if (filters.source === 'system' && !t.is_system || filters.source === 'custom' && t.is_system) return false
    if (filters.status === 'active' && !t.is_active || filters.status === 'inactive' && t.is_active) return false
    return !query || [t.name,t.description,t.content,t.template_key,...t.tags].some(value => value?.toLocaleLowerCase().includes(query))
  }).sort((a,b) => {
    if (filters.sort === 'name') return a.name.localeCompare(b.name,'zh-CN') || a.id.localeCompare(b.id)
    const difference = filters.sort === 'usage' ? b.usage_count-a.usage_count : (Date.parse(b.updated_at)||0)-(Date.parse(a.updated_at)||0)
    return difference || a.name.localeCompare(b.name,'zh-CN') || a.id.localeCompare(b.id)
  })
}

export function splitPromptValues(value:string) {
  return [...new Set(value.split(/[,，\n]/).map(v => v.trim()).filter(Boolean))]
}
export function promptDate(value:string, full=false) {
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '—'
  const pad = (n:number) => String(n).padStart(2,'0')
  return `${full ? `${date.getFullYear()}-` : ''}${pad(date.getMonth()+1)}-${pad(date.getDate())} ${pad(date.getHours())}:${pad(date.getMinutes())}`
}
export function promptPageNumbers(current:number,total:number) {
  return [...new Set([1,total,...Array.from({length:5},(_,i)=>current+i-2).filter(p=>p>0&&p<=total)])].sort((a,b)=>a-b)
}
