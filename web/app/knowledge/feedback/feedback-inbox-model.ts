import { feedbackApi } from '@/lib/api'
import type { Message, MessageFeedbackEnriched } from '@/types'

export type FeedbackView = 'all' | 'pending' | 'priority' | 'archived'
export type FeedbackKind = 'positive' | 'negative' | 'neutral'
export type FeedbackRange = 'all' | '7d' | '30d' | '90d'
export type FeedbackSource = 'all' | 'web' | 'mobile' | 'enterprise' | 'api' | 'benchmark' | 'other'

export const SOURCE_LABELS: Record<FeedbackSource, string> = {
  all: '全部来源', web: 'Web 控制台', mobile: '移动端 APP', enterprise: '企业微信', api: 'API 接口', benchmark: '评测样本', other: '其他',
}
export const RANGE_LABELS: Record<FeedbackRange, string> = { all: '全部时间', '7d': '最近 7 天', '30d': '最近 30 天', '90d': '最近 90 天' }

export function displayText(...values: unknown[]): string {
  for (const value of values) {
    if (typeof value === 'string' && value.trim()) return value.trim()
    if (typeof value === 'number') return String(value)
  }
  return ''
}
export function feedbackKind(item: MessageFeedbackEnriched): FeedbackKind {
  return item.rating >= 4 ? 'positive' : item.rating > 0 && item.rating <= 2 ? 'negative' : 'neutral'
}
export function archived(item: MessageFeedbackEnriched): boolean { return item.extra?.archived === true }
export function feedbackStatus(item: MessageFeedbackEnriched): string {
  return archived(item) ? '已归档' : feedbackKind(item) === 'negative' ? '优先分析' : '待分析'
}
export function feedbackQuestion(item: MessageFeedbackEnriched): string {
  return displayText(item.extra?.query, item.extra?.question, item.conversation_title) || '未命名会话'
}
export function feedbackIssue(item: MessageFeedbackEnriched): string {
  if (item.category) return { retrieval_miss: '未命中知识库', wrong_answer: '回答错误', out_of_scope: '超出知识范围', other: '其他问题' }[item.category]
  return displayText(item.extra?.feedback_issue, item.extra?.quality_label) || (feedbackKind(item) === 'positive' ? '有帮助' : '未分类')
}
export function feedbackSource(item: MessageFeedbackEnriched): Exclude<FeedbackSource, 'all'> {
  const source = `${displayText(item.extra?.source, item.extra?.benchmark_source)} ${item.account_id} ${(item.tags || []).join(' ')}`.toLowerCase()
  if (/benchmark|评测/.test(source)) return 'benchmark'
  if (/mobile|ios|android|app|移动/.test(source)) return 'mobile'
  if (/api/.test(source)) return 'api'
  if (/wecom|wx|enterprise|企业微信/.test(source)) return 'enterprise'
  if (/web|console|browser/.test(source)) return 'web'
  return 'other'
}
export function feedbackTime(value: string, full = false): string {
  const date = new Date(value)
  return Number.isFinite(date.getTime()) ? date.toLocaleString('zh-CN', { ...(full ? { year: 'numeric' as const } : {}), month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit', hour12: false }) : '—'
}

// Load every API page so local filters and counts include older feedback.
export async function loadFeedback(signal: AbortSignal) {
  const items: MessageFeedbackEnriched[] = []
  let total = 0
  do {
    const page = await feedbackApi.listEnriched({ skip: items.length, limit: 200 }, { signal })
    total = page.total
    if (!page.items.length) break
    items.push(...page.items)
  } while (items.length < total)
  return { items, total }
}

export function filterFeedback(items: MessageFeedbackEnriched[], filters: { view: FeedbackView; rating: string; kind: string; source: FeedbackSource; range: FeedbackRange; search: string }, now = Date.now()) {
  const query = filters.search.trim().toLowerCase()
  return items.filter(item => {
    if (filters.view === 'pending' && archived(item)) return false
    if (filters.view === 'archived' && !archived(item)) return false
    if (filters.view === 'priority' && (archived(item) || feedbackKind(item) !== 'negative')) return false
    if (filters.rating !== 'all' && item.rating !== Number(filters.rating)) return false
    if (filters.kind !== 'all' && feedbackKind(item) !== filters.kind) return false
    if (filters.source !== 'all' && feedbackSource(item) !== filters.source) return false
    if (filters.range !== 'all') {
      const age = now - new Date(item.created_at).getTime()
      if (!Number.isFinite(age) || age < 0 || age > parseInt(filters.range, 10) * 86_400_000) return false
    }
    return !query || [feedbackQuestion(item), item.message_content, item.reason, item.account_id, item.id, ...(item.tags || [])].join(' ').toLowerCase().includes(query)
  })
}

export function feedbackContext(messages: Message[], messageId: string) {
  const index = messages.findIndex(message => message.id === messageId && message.role === 'assistant')
  if (index < 0) return null
  const question = messages.slice(0, index).reverse().find(message => message.role === 'user')?.content
  return { answer: messages[index], question }
}
