import type { MessageFeedbackEnriched } from '@/types'

export type FeedbackView = 'all' | 'pending' | 'priority' | 'archived'
type FeedbackKind = 'positive' | 'negative' | 'neutral'
export type FeedbackRange = 'all' | '7d' | '30d' | '90d'
export type FeedbackSource = 'all' | 'web' | 'mobile' | 'enterprise' | 'api' | 'benchmark' | 'other'

export const SOURCE_LABELS: Record<FeedbackSource, string> = {
  all: '全部来源',
  web: 'Web 控制台',
  mobile: '移动端 APP',
  enterprise: '企业微信',
  api: 'API 接口',
  benchmark: '评测样本',
  other: '其他',
}
export const RANGE_LABELS: Record<FeedbackRange, string> = {
  all: '全部时间',
  '7d': '最近 7 天',
  '30d': '最近 30 天',
  '90d': '最近 90 天',
}

export function getFeedbackKind(item: MessageFeedbackEnriched): FeedbackKind {
  return item.rating >= 4 ? 'positive' : item.rating > 0 && item.rating <= 2 ? 'negative' : 'neutral'
}
export function isFeedbackArchived(item: MessageFeedbackEnriched): boolean {
  return item.extra.archived === true
}
export function getFeedbackStatus(item: MessageFeedbackEnriched): string {
  return isFeedbackArchived(item) ? '已归档' : getFeedbackKind(item) === 'negative' ? '优先分析' : '待分析'
}
export function getFeedbackQuestion(item: MessageFeedbackEnriched): string | undefined {
  const { query, question } = item.extra
  if (typeof query === 'string') return query
  return typeof question === 'string' ? question : undefined
}
export function getFeedbackLabel(item: MessageFeedbackEnriched): string {
  const question = getFeedbackQuestion(item)
  if (question !== undefined) return question.length === 0 ? '提问内容为空' : question
  if (item.conversation_title !== null) return `会话：${item.conversation_title}`
  return `反馈 ${item.id}`
}
export function getFeedbackIssue(item: MessageFeedbackEnriched): string {
  if (item.category !== null)
    return {
      retrieval_miss: '未命中知识库',
      wrong_answer: '回答错误',
      out_of_scope: '超出知识范围',
      other: '其他问题',
    }[item.category]
  if (typeof item.extra.feedback_issue === 'string') return item.extra.feedback_issue
  if (typeof item.extra.quality_label === 'string') return item.extra.quality_label
  return getFeedbackKind(item) === 'positive' ? '有帮助' : '未分类'
}
export function getFeedbackSource(item: MessageFeedbackEnriched): Exclude<FeedbackSource, 'all'> {
  const source = item.extra.source
  if (typeof source !== 'string') return 'other'
  switch (source.trim().toLowerCase()) {
    case 'benchmark':
    case '评测':
      return 'benchmark'
    case 'mobile':
    case 'ios':
    case 'android':
    case 'app':
    case '移动':
      return 'mobile'
    case 'api':
      return 'api'
    case 'wecom':
    case 'wx':
    case 'enterprise':
    case '企业微信':
      return 'enterprise'
    case 'web':
    case 'console':
    case 'browser':
      return 'web'
  }
  return 'other'
}
export function formatFeedbackTime(value: string, full = false): string {
  const date = new Date(value)
  return date.toLocaleString('zh-CN', {
    ...(full ? { year: 'numeric' as const } : {}),
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    hour12: false,
  })
}

export function filterFeedback(
  items: readonly MessageFeedbackEnriched[],
  filters: {
    view: FeedbackView
    rating: string
    kind: string
    source: FeedbackSource
    range: FeedbackRange
    search: string
  },
  now = Date.now(),
) {
  const query = filters.search.trim().toLowerCase()
  const rating = filters.rating === 'all' ? undefined : Number(filters.rating)
  const windowMs = filters.range === 'all' ? undefined : Number.parseInt(filters.range, 10) * 86_400_000
  return items.filter((item) => {
    const archived = isFeedbackArchived(item)
    const kind = getFeedbackKind(item)
    if (filters.view === 'pending' && archived) return false
    if (filters.view === 'archived' && !archived) return false
    if (filters.view === 'priority' && (archived || kind !== 'negative')) return false
    if (rating !== undefined && item.rating !== rating) return false
    if (filters.kind !== 'all' && kind !== filters.kind) return false
    if (filters.source !== 'all' && getFeedbackSource(item) !== filters.source) return false
    if (windowMs !== undefined) {
      const age = now - new Date(item.created_at).getTime()
      if (!Number.isFinite(age) || age < 0 || age > windowMs) return false
    }
    return (
      !query ||
      [
        getFeedbackQuestion(item),
        item.conversation_title,
        item.message_content,
        item.reason,
        item.account_id,
        item.id,
        ...item.tags,
      ]
        .join(' ')
        .toLowerCase()
        .includes(query)
    )
  })
}
