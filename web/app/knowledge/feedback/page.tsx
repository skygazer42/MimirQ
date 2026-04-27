'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useSearchParams } from 'next/navigation'
import { useQuery } from '@tanstack/react-query'
import {
  ArrowUpRight,
  CalendarDays,
  CheckCheck,
  ChevronLeft,
  ChevronRight,
  Copy,
  Loader2,
  MessageSquare,
  MoreHorizontal,
  RefreshCw,
  Search,
  Star,
  TestTube2,
  ThumbsDown,
  ThumbsUp,
  UserRound,
} from 'lucide-react'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Button } from '@/components/ui/button'
import { SearchInput } from '@/components/ui/search-input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { usePathname, useRouter } from '@/i18n/navigation'
import { feedbackApi } from '@/lib/api'
import { cn, formatDate } from '@/lib/utils'
import type { MessageFeedbackEnriched } from '@/types'
import { formatApiError } from '@/lib/api-errors'
import { Badge } from '@/components/ui/badge'

type RatingFilter = 'all' | '1' | '2' | '3' | '4' | '5'
type FeedbackType = 'thumbs_up' | 'thumbs_down'
type FeedbackTypeFilter = 'all' | FeedbackType
type FeedbackBoardTab = 'all' | 'pending' | 'high-priority' | 'archived'
type FeedbackSourceFilter = 'all' | 'web' | 'mobile' | 'enterprise' | 'api' | 'other'
type FeedbackTimeRange = '7d' | '30d' | '90d' | 'all'

const FEEDBACK_PAGE_SIZE = 3

function classifyFeedback(rating: number): FeedbackType | 'neutral' {
  const v = Number(rating) || 0
  if (v >= 4) return 'thumbs_up'
  if (v > 0 && v <= 2) return 'thumbs_down'
  return 'neutral'
}

function getFeedbackSource(item: MessageFeedbackEnriched): FeedbackSourceFilter {
  const raw = `${String(item.account_id || '')} ${String((item.extra as Record<string, unknown> | undefined)?.source || '')}`.toLowerCase()
  if (raw.includes('mobile') || raw.includes('ios') || raw.includes('android') || raw.includes('app')) return 'mobile'
  if (raw.includes('api')) return 'api'
  if (raw.includes('wx') || raw.includes('wecom') || raw.includes('enterprise')) return 'enterprise'
  if (raw.includes('web') || raw.includes('console') || raw.includes('browser')) return 'web'
  return 'other'
}

function getFeedbackSourceLabel(source: FeedbackSourceFilter): string {
  switch (source) {
    case 'web':
      return 'Web 控制台'
    case 'mobile':
      return '移动端 APP'
    case 'enterprise':
      return '企业微信'
    case 'api':
      return 'API 接口'
    case 'other':
      return '其他'
    case 'all':
    default:
      return '全部来源'
  }
}

function getFeedbackIssueLabel(item: MessageFeedbackEnriched): string {
  const text = `${item.reason || ''} ${(item.tags || []).join(' ')} ${item.message_content || ''}`.toLowerCase()
  if (text.includes('知识库') || text.includes('未命中') || text.includes('找不到')) return '未命中知识库'
  if (text.includes('引用') || text.includes('来源')) return '引用不足'
  if (text.includes('答非所问') || text.includes('偏题') || text.includes('错误')) return '表达模糊'
  if (text.includes('完整') || text.includes('过于简略') || text.includes('配置示例')) return '答案不完整'
  return item.tags?.[0] || '答案不完整'
}

function isHighPriority(item: MessageFeedbackEnriched): boolean {
  const rating = Number(item.rating) || 0
  return rating > 0 && rating <= 2
}

function isWithinRange(value: string | undefined, range: FeedbackTimeRange): boolean {
  if (range === 'all') return true
  const ts = new Date(String(value || '')).getTime()
  if (!Number.isFinite(ts)) return false
  const now = Date.now()
  const days = range === '7d' ? 7 : range === '30d' ? 30 : 90
  return now - ts <= days * 24 * 60 * 60 * 1000
}

function buildSparklinePath(values: number[], width = 92, height = 28): string {
  if (!values.length) return ''
  if (values.length === 1) return `M 0 ${height / 2} L ${width} ${height / 2}`
  const max = Math.max(...values)
  const min = Math.min(...values)
  const range = max - min || 1
  return values
    .map((value, index) => {
      const x = (index / (values.length - 1)) * width
      const y = height - ((value - min) / range) * height
      return `${index === 0 ? 'M' : 'L'} ${x.toFixed(2)} ${y.toFixed(2)}`
    })
    .join(' ')
}

function buildConicGradient(values: number[], colors: string[]): string {
  const total = values.reduce((sum, value) => sum + value, 0)
  if (!total) return 'conic-gradient(rgba(148,163,184,0.18) 0deg 360deg)'
  let current = 0
  const stops = values.map((value, index) => {
    const start = current
    const end = current + (value / total) * 360
    current = end
    return `${colors[index]} ${start.toFixed(2)}deg ${end.toFixed(2)}deg`
  })
  return `conic-gradient(${stops.join(', ')})`
}

function FeedbackSummaryCard({
  label,
  value,
  delta,
  icon: Icon,
  tone,
  series,
}: Readonly<{
  label: string
  value: number
  delta: string
  icon: typeof ThumbsUp
  tone: 'indigo' | 'emerald' | 'rose' | 'blue'
  series: number[]
}>) {
  const accent =
    tone === 'indigo'
      ? 'text-indigo-500 border-indigo-500/10 bg-indigo-500/8'
      : tone === 'emerald'
        ? 'text-emerald-500 border-emerald-500/10 bg-emerald-500/8'
        : tone === 'rose'
          ? 'text-rose-500 border-rose-500/10 bg-rose-500/8'
          : 'text-sky-500 border-sky-500/10 bg-sky-500/8'
  const line =
    tone === 'indigo' ? 'stroke-indigo-500' : tone === 'emerald' ? 'stroke-emerald-500' : tone === 'rose' ? 'stroke-rose-500' : 'stroke-sky-500'

  return (
    <div className="rounded-[1rem] border border-border/55 bg-card px-3 py-2 shadow-[0_10px_24px_-30px_rgba(15,23,42,0.1)]">
      <div className="flex items-start justify-between gap-3">
        <div className="space-y-1">
          <div className="text-[9px] font-semibold text-foreground">{label}</div>
          <div className={cn('text-[1.12rem] font-semibold leading-none tracking-[-0.04em]', tone === 'indigo' ? 'text-indigo-500' : tone === 'emerald' ? 'text-emerald-500' : tone === 'rose' ? 'text-rose-500' : 'text-sky-500')}>
            {value}
          </div>
          <div className="text-[9px] text-muted-foreground">
            较昨日 <span className="font-semibold">{delta}</span>
          </div>
        </div>
        <div className={cn('flex h-6 w-6 items-center justify-center rounded-[0.8rem] border', accent)}>
          <Icon className="size-3" />
        </div>
      </div>
      <div className="mt-2 flex items-end justify-end">
        <svg viewBox="0 0 92 24" className="h-5 w-[84px]" aria-hidden="true">
          <path d={buildSparklinePath(series)} fill="none" className={cn('stroke-2', line)} />
        </svg>
      </div>
    </div>
  )
}

function FeedbackDonutCard({
  title,
  items,
  colors,
  actionLabel,
}: Readonly<{
  title: string
  items: Array<{ label: string; value: number }>
  colors: string[]
  actionLabel?: string
}>) {
  const values = items.map((item) => item.value)
  const total = values.reduce((sum, value) => sum + value, 0)
  const gradient = buildConicGradient(values, colors)

  return (
    <div className="rounded-[1rem] border border-border/55 bg-card p-3 shadow-[0_12px_28px_-34px_rgba(15,23,42,0.12)]">
      <div className="flex items-center justify-between gap-2.5">
        <div className="text-[0.9rem] font-semibold text-foreground">{title}</div>
        {actionLabel ? (
          <button type="button" className="inline-flex items-center gap-1 text-[11px] font-medium text-muted-foreground hover:text-foreground">
            {actionLabel}
            <ChevronRight className="size-3" />
          </button>
        ) : null}
      </div>
      <div className="mt-3 grid gap-3 md:grid-cols-[104px_minmax(0,1fr)] md:items-center">
        <div className="flex items-center justify-center">
          <div className="relative h-[96px] w-[96px] rounded-full" style={{ backgroundImage: gradient }}>
            <div className="absolute inset-[15px] flex items-center justify-center rounded-full bg-background text-center">
              <div>
                <div className="text-[1.2rem] font-semibold text-foreground">{total}</div>
                <div className="text-[10px] text-muted-foreground">总量</div>
              </div>
            </div>
          </div>
        </div>
        <div className="space-y-1.5">
          {items.map((item, index) => (
            <div key={item.label} className="flex items-center justify-between gap-2 text-[11px]">
              <div className="flex items-center gap-2 text-muted-foreground">
                <span className="h-2 w-2 rounded-full" style={{ backgroundColor: colors[index] }} />
                <span>{item.label}</span>
              </div>
              <div className="font-mono text-foreground">
                {item.value} {total > 0 ? `(${((item.value / total) * 100).toFixed(1)}%)` : '(0%)'}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  )
}

function FeedbackTrendCard({
  title,
  labels,
  series,
  actionLabel,
}: Readonly<{
  title: string
  labels: string[]
  series: Array<{ label: string; values: number[]; color: string }>
  actionLabel?: string
}>) {
  const allValues = series.flatMap((item) => item.values)
  const max = Math.max(1, ...allValues)
  const width = 320
  const height = 170

  return (
    <div className="rounded-[1rem] border border-border/55 bg-card p-3 shadow-[0_12px_28px_-34px_rgba(15,23,42,0.12)]">
      <div className="flex items-center justify-between gap-2.5">
        <div className="text-[0.9rem] font-semibold text-foreground">{title}</div>
        {actionLabel ? (
          <button type="button" className="inline-flex items-center gap-1 text-[11px] font-medium text-muted-foreground hover:text-foreground">
            {actionLabel}
            <ChevronRight className="size-3" />
          </button>
        ) : null}
      </div>
      <div className="mt-2.5">
        <div className="mb-2.5 flex flex-wrap items-center gap-3 text-[10px] text-muted-foreground">
          {series.map((item) => (
            <span key={item.label} className="inline-flex items-center gap-1.5">
              <span className="h-2 w-2 rounded-full" style={{ backgroundColor: item.color }} />
              <span>{item.label}</span>
            </span>
          ))}
        </div>
        <svg viewBox={`0 0 ${width} ${height}`} className="h-[164px] w-full" aria-hidden="true">
          {Array.from({ length: 5 }).map((_, index) => {
            const y = 18 + index * 34
            return <line key={index} x1="0" y1={y} x2={width} y2={y} stroke="rgba(148,163,184,0.18)" />
          })}
          {series.map((item) => {
            const path = item.values
              .map((value, index) => {
                const x = (index / Math.max(1, item.values.length - 1)) * (width - 16) + 8
                const y = 152 - (value / max) * 110
                return `${index === 0 ? 'M' : 'L'} ${x} ${y}`
              })
              .join(' ')
            return <path key={item.label} d={path} fill="none" stroke={item.color} strokeWidth="2.2" strokeLinecap="round" strokeLinejoin="round" />
          })}
          {labels.map((label, index) => {
            const x = (index / Math.max(1, labels.length - 1)) * (width - 16) + 8
            return (
              <text key={label} x={x} y={181} textAnchor="middle" fontSize="11" fill="rgba(100,116,139,0.9)">
                {label}
              </text>
            )
          })}
        </svg>
      </div>
    </div>
  )
}

function FeedbackStatusBadge({
  label,
  tone,
}: Readonly<{ label: string; tone: 'positive' | 'negative' | 'neutral' | 'priority' }>) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full border px-2 py-0.5 text-[10px] font-semibold',
        tone === 'positive' && 'border-emerald-500/20 bg-emerald-500/10 text-emerald-700',
        tone === 'negative' && 'border-rose-500/20 bg-rose-500/10 text-rose-700',
        tone === 'neutral' && 'border-border/60 bg-muted/50 text-muted-foreground',
        tone === 'priority' && 'border-orange-500/20 bg-orange-500/10 text-orange-700'
      )}
    >
      {label}
    </span>
  )
}

function buildDemoFeedbackItems(): MessageFeedbackEnriched[] {
  const seeds = [
    {
      title: '如何配置知识库的分段策略以提升召回效果？',
      reason: '回答不完整，没有提供具体的配置示例，参考资料也不足。',
      tags: ['答案不完整', '未命中知识库', '引用不足'],
      rating: 2,
      source: 'web',
      account: 'user_9847',
    },
    {
      title: '上传 PDF 后为什么只有部分分页面被解析？',
      reason: '不确定是文件问题还是系统限制，希望有更明确的说明。',
      tags: ['表达模糊', '待确认', '解析问题'],
      rating: 3,
      source: 'mobile',
      account: 'user_7632',
    },
    {
      title: 'RAG 与微调有什么区别？适合什么场景？',
      reason: '解释很清晰，例子也很实用，帮助我理解了两者的区别。',
      tags: ['表达清晰', '引用充分', '有帮助'],
      rating: 4,
      source: 'enterprise',
      account: 'user_5521',
    },
    {
      title: '多知识库权限隔离怎么做？',
      reason: '提到了方向，但是没有落到权限粒度和策略配置上。',
      tags: ['答案不完整', '权限配置', '高优先级'],
      rating: 2,
      source: 'api',
      account: 'user_4102',
    },
    {
      title: '为什么命中率下降后检索速度也变慢了？',
      reason: '分析比较准确，给出的排查路径对我有帮助。',
      tags: ['诊断清晰', '有帮助'],
      rating: 5,
      source: 'web',
      account: 'user_2048',
    },
  ] as const

  return Array.from({ length: 128 }, (_, index) => {
    const seed = seeds[index % seeds.length]
    const createdDate = new Date()
    createdDate.setHours(10 - (index % 5), Math.max(0, 24 - (index % 17)), 0, 0)
    createdDate.setDate(createdDate.getDate() - (index % 7))
    const createdAt = createdDate.toISOString()
    return {
      id: `fb_demo_${String(index + 1).padStart(4, '0')}`,
      tenant_id: 'demo-tenant',
      conversation_id: `conv_demo_${String(index + 1).padStart(4, '0')}`,
      message_id: `msg_demo_${String(index + 1).padStart(4, '0')}`,
      account_id: seed.account,
      rating: seed.rating,
      reason: seed.reason,
      tags: [...seed.tags],
      expected_answer: index % 4 === 0 ? '需要给出更完整的步骤、配置样例和适用范围。' : undefined,
      extra: { source: seed.source },
      created_at: createdAt,
      updated_at: createdAt,
      conversation_title: seed.title,
      message_content:
        seed.rating <= 2
          ? '当前回答主要覆盖了概念说明，但缺少配置步骤、示例和知识库命中依据，因此用户仍然无法直接完成设置。'
          : seed.rating === 3
            ? '回答提供了方向性解释，但对具体限制、适用条件和边界情况说明不足，用户需要进一步确认。'
            : '回答结构清晰，给出了对比关系、适用场景和操作建议，整体可读性较好。',
      message_created_at: createdAt,
    }
  })
}

function buildDemoFeedbackMetrics() {
  return {
    stats: {
      total: 128,
      upvotes: 84,
      downvotes: 23,
      neutral: 21,
    },
    topReasons: [
      { label: '答案不完整', value: 42 },
      { label: '未命中知识库', value: 31 },
      { label: '引用不足', value: 18 },
    ],
    sources: [
      { label: 'Web 控制台', value: 64 },
      { label: '移动端 APP', value: 32 },
      { label: '企业微信', value: 16 },
      { label: 'API 接口', value: 10 },
      { label: '其他', value: 6 },
    ],
    trend: {
      labels: ['04-09', '04-10', '04-11', '04-12', '04-13', '04-14', '04-15'],
      series: [
        { label: '点赞', values: [25, 33, 35, 34, 46, 38, 37], color: '#22c55e' },
        { label: '点踩', values: [14, 20, 23, 18, 28, 20, 19], color: '#ef4444' },
        { label: '中立', values: [6, 13, 13, 8, 13, 9, 8], color: '#3b82f6' },
      ],
    },
  }
}

export default function FeedbackTriagePage() {
  const searchParams = useSearchParams()
  const pathname = usePathname()
  const router = useRouter()
  const demoMode = searchParams.get('demo') === '1'
  const [ratingFilter, setRatingFilter] = useState<RatingFilter>('all')
  const [filterType, setFilterType] = useState<FeedbackTypeFilter>('all')
  const [boardTab, setBoardTab] = useState<FeedbackBoardTab>('all')
  const [sourceFilter, setSourceFilter] = useState<FeedbackSourceFilter>('all')
  const [timeRange, setTimeRange] = useState<FeedbackTimeRange>('7d')
  const [searchTerm, setSearchTerm] = useState('')
  const [detail, setDetail] = useState<MessageFeedbackEnriched | null>(null)
  const [creatingCase, setCreatingCase] = useState(false)
  const [createdCaseId, setCreatedCaseId] = useState<string | null>(null)
  const [archivedIds, setArchivedIds] = useState<string[]>([])
  const [page, setPage] = useState(1)

  const params = useMemo(() => {
    const p: any = {}
    if (ratingFilter !== 'all') {
      const v = Number(ratingFilter)
      p.min_rating = v
      p.max_rating = v
    }
    return p
  }, [ratingFilter])

  const { data, isFetching, refetch } = useQuery({
    queryKey: ['feedback-enriched', params],
    queryFn: ({ signal }) => feedbackApi.listEnriched({ limit: 100, ...params }, { signal }),
    enabled: !demoMode,
    staleTime: 5_000,
  })

  const items = useMemo(() => (demoMode ? buildDemoFeedbackItems() : data?.items || []), [data, demoMode])
  const demoMetrics = useMemo(() => buildDemoFeedbackMetrics(), [])

  const stats = useMemo(() => {
    if (demoMode) {
      return {
        ...demoMetrics.stats,
        1: 12,
        2: 11,
        3: 21,
        4: 38,
        5: 46,
      }
    }
    const s = { 1: 0, 2: 0, 3: 0, 4: 0, 5: 0, total: 0, upvotes: 0, downvotes: 0 }
    for (const it of items) {
      s.total++
      const r = Number(it.rating) || 0
      if (r >= 1 && r <= 5) (s as any)[r] += 1
      const kind = classifyFeedback(r)
      if (kind === 'thumbs_up') s.upvotes++
      if (kind === 'thumbs_down') s.downvotes++
    }
    return s
  }, [demoMetrics.stats, demoMode, items])

  const topReasonStats = useMemo(() => {
    if (demoMode) return demoMetrics.topReasons
    const counts = new Map<string, number>()
    items.forEach((item) => {
      const key = getFeedbackIssueLabel(item)
      counts.set(key, (counts.get(key) ?? 0) + 1)
    })
    return Array.from(counts.entries())
      .map(([label, value]) => ({ label, value }))
      .sort((left, right) => right.value - left.value)
      .slice(0, 3)
  }, [demoMetrics.topReasons, demoMode, items])

  const sourceStats = useMemo(() => {
    if (demoMode) return demoMetrics.sources
    const counts = new Map<FeedbackSourceFilter, number>()
    items.forEach((item) => {
      const key = getFeedbackSource(item)
      counts.set(key, (counts.get(key) ?? 0) + 1)
    })
    return (['web', 'mobile', 'enterprise', 'api', 'other'] as const)
      .map((key) => ({ label: getFeedbackSourceLabel(key), value: counts.get(key) ?? 0 }))
      .filter((item) => item.value > 0)
  }, [demoMetrics.sources, demoMode, items])

  const trendStats = useMemo(() => {
    if (demoMode) return demoMetrics.trend
    const labels: string[] = []
    const up: number[] = []
    const down: number[] = []
    const neutral: number[] = []
    const now = new Date()
    for (let index = 6; index >= 0; index -= 1) {
      const day = new Date(now)
      day.setDate(now.getDate() - index)
      const key = `${day.getMonth() + 1}`.padStart(2, '0') + '-' + `${day.getDate()}`.padStart(2, '0')
      labels.push(key)
      const dayItems = items.filter((item) => {
        const itemDate = new Date(item.created_at)
        return itemDate.toDateString() === day.toDateString()
      })
      up.push(dayItems.filter((item) => classifyFeedback(item.rating) === 'thumbs_up').length)
      down.push(dayItems.filter((item) => classifyFeedback(item.rating) === 'thumbs_down').length)
      neutral.push(dayItems.filter((item) => classifyFeedback(item.rating) === 'neutral').length)
    }
    return {
      labels,
      series: [
        { label: '点赞', values: up, color: '#22c55e' },
        { label: '点踩', values: down, color: '#ef4444' },
        { label: '中立', values: neutral, color: '#3b82f6' },
      ],
    }
  }, [demoMetrics.trend, demoMode, items])

  const filtered = useMemo(() => {
    let res = items
    const q = searchTerm.trim().toLowerCase()

    if (filterType !== 'all') {
      res = res.filter((i) => classifyFeedback(i.rating) === filterType)
    }

    if (sourceFilter !== 'all') {
      res = res.filter((item) => getFeedbackSource(item) === sourceFilter)
    }

    if (timeRange !== 'all') {
      res = res.filter((item) => isWithinRange(item.created_at, timeRange))
    }

    if (boardTab === 'pending') {
      res = res.filter((item) => !archivedIds.includes(item.id))
    }
    if (boardTab === 'high-priority') {
      res = res.filter((item) => isHighPriority(item))
    }
    if (boardTab === 'archived') {
      res = res.filter((item) => archivedIds.includes(item.id))
    }

    if (q) {
      res = res.filter((it) => {
        const hay = [
          it.conversation_title,
          it.message_content,
          it.reason,
          (it.tags || []).join(' '),
          it.id,
          it.account_id
        ]
          .filter(Boolean)
          .join(' ')
          .toLowerCase()
        return hay.includes(q)
      })
    }
    return res
  }, [archivedIds, boardTab, items, searchTerm, filterType, sourceFilter, timeRange])

  const copyDetail = async (it: MessageFeedbackEnriched) => {
    try {
      await navigator.clipboard.writeText(JSON.stringify(it, null, 2))
      toast.success('已复制')
    } catch (err: any) {
      toast.error(formatApiError(err, '复制失败'))
    }
  }

  const toggleArchived = useCallback((feedbackId: string) => {
    setArchivedIds((previous) =>
      previous.includes(feedbackId) ? previous.filter((item) => item !== feedbackId) : [...previous, feedbackId]
    )
    toast.success('已更新处理状态')
  }, [])

  const createRegressionCase = useCallback(
    async (item: MessageFeedbackEnriched) => {
      if (demoMode) {
        toast.success('Demo 模式仅用于预览反馈分析布局，不写入真实回归用例')
        return
      }
      setCreatingCase(true)
      try {
        const rc = await feedbackApi.toRegressionCase(item.id, { include_document_scope: true })
        setCreatedCaseId(rc.id)
        toast.success('已创建回归用例')
      } catch (err: any) {
        toast.error(formatApiError(err, '创建回归用例失败'))
      } finally {
        setCreatingCase(false)
      }
    },
    [demoMode]
  )

  const handleToggleDemoMode = useCallback(() => {
    const params = new URLSearchParams(searchParams.toString())
    if (demoMode) params.delete('demo')
    else params.set('demo', '1')
    const query = params.toString()
    router.replace(query ? `${pathname}?${query}` : pathname)
  }, [demoMode, pathname, router, searchParams])

  // Reset per-detail UI state.
  useEffect(() => {
    setCreatedCaseId(null)
    setCreatingCase(false)
  }, [detail?.id])

  const hasActiveFilters = searchTerm.trim().length > 0 || filterType !== 'all' || ratingFilter !== 'all'
  const hasExtendedFilters = hasActiveFilters || sourceFilter !== 'all' || timeRange !== '7d' || boardTab !== 'all'
  const totalPages = useMemo(() => Math.max(1, Math.ceil(filtered.length / FEEDBACK_PAGE_SIZE)), [filtered.length])
  const paginated = useMemo(
    () => filtered.slice((page - 1) * FEEDBACK_PAGE_SIZE, page * FEEDBACK_PAGE_SIZE),
    [filtered, page]
  )
  const listSummary = useMemo(() => {
    if (!items.length) return null
    if (hasExtendedFilters) return `筛选 ${filtered.length} / ${items.length}`
    return `共 ${items.length} 条`
  }, [filtered.length, hasExtendedFilters, items.length])

  useEffect(() => {
    setPage(1)
  }, [boardTab, filterType, ratingFilter, sourceFilter, timeRange, searchTerm])

  useEffect(() => {
    if (page > totalPages) setPage(totalPages)
  }, [page, totalPages])

  const summaryCards = useMemo(
    () => [
      { label: '总反馈量', value: stats.total, delta: '+12%', icon: MessageSquare, tone: 'indigo' as const, series: trendStats.series[2].values.map((value, index) => value + index + 4) },
      { label: '点赞', value: stats.upvotes, delta: '+8%', icon: ThumbsUp, tone: 'emerald' as const, series: trendStats.series[0].values.map((value, index) => value + index + 6) },
      { label: '点踩', value: stats.downvotes, delta: '+21%', icon: ThumbsDown, tone: 'rose' as const, series: trendStats.series[1].values.map((value, index) => value + index + 3) },
      { label: '中立反馈', value: stats.total - stats.upvotes - stats.downvotes, delta: '-5%', icon: Star, tone: 'blue' as const, series: trendStats.series[2].values.map((value, index) => value + index + 2) },
    ],
    [stats.downvotes, stats.total, stats.upvotes, trendStats.series]
  )

  return (
    <AppFrame>
      <PageScaffold
        title="反馈分析中心"
        icon={MessageSquare}
        iconColor="text-indigo-500 dark:text-indigo-400"
        size="full"
        topClassName="mx-auto w-full max-w-[1480px] px-3 md:px-4 xl:px-5 pt-4 pb-3"
        description={
          <div className="flex flex-wrap items-center gap-2 text-[12px] leading-5 text-muted-foreground">
            <span>汇总点赞、点踩与低分原因，快速定位需要回归验证的反馈。</span>
            <span className="inline-flex items-center rounded-md border border-border/60 bg-background/70 px-1.5 py-0.5 text-[11px] font-semibold tracking-[0.04em] text-indigo-700/80 dark:text-indigo-300/80">
              实时分析
            </span>
            <span className="inline-flex items-center rounded-md border border-border/60 bg-background/70 px-1.5 py-0.5 text-[11px] font-semibold tracking-[0.04em] text-sky-700/80 dark:text-sky-300/80">
              长文本优先
            </span>
            <span className="inline-flex items-center rounded-md border border-border/60 bg-background/70 px-1.5 py-0.5 text-[11px] font-semibold tracking-[0.04em] text-emerald-700/80 dark:text-emerald-300/80">
              回归线索
            </span>
          </div>
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button
              variant="outline"
              className="gap-2 rounded-full bg-card/60 text-muted-foreground shadow-sm transition-colors duration-200 hover:border-border/80 hover:bg-card hover:text-foreground motion-reduce:transition-none"
              onClick={handleToggleDemoMode}
            >
              {demoMode ? '退出 Demo' : '打开 Demo'}
            </Button>
            <Button
              variant="outline"
              className="gap-2 rounded-full bg-card/60 text-muted-foreground shadow-sm transition-colors duration-200 hover:border-border/80 hover:bg-card hover:text-foreground motion-reduce:transition-none"
              onClick={() => {
                if (demoMode) {
                  toast.success('Demo 数据已刷新')
                  return
                }
                void refetch()
              }}
            >
              <RefreshCw className={cn('h-3.5 w-3.5', isFetching ? 'animate-spin motion-reduce:animate-none' : '')} />
              刷新数据
            </Button>
          </div>
        }
        top={
          <div className="pt-2">
            <div className="grid gap-4 lg:grid-cols-2 xl:grid-cols-4">
              {summaryCards.map((card) => (
                <FeedbackSummaryCard
                  key={card.label}
                  label={card.label}
                  value={card.value}
                  delta={card.delta}
                  icon={card.icon}
                  tone={card.tone}
                  series={card.series}
                />
              ))}
            </div>
          </div>
        }
        bodyClassName="mx-auto w-full max-w-[1480px] px-3 md:px-4 xl:px-5 pb-8 z-10"
      >
         <div className="grid gap-3 xl:h-[calc(100vh-16.5rem)] xl:min-h-0 xl:grid-cols-[2.08fr_0.68fr]">
          <div className="space-y-4 xl:flex xl:min-h-0 xl:flex-col xl:space-y-3">
            <div className="flex flex-wrap items-center gap-2">
              {([
                ['all', '全部'],
                ['pending', '待分析'],
                ['high-priority', '高优先级'],
                ['archived', '已归档'],
              ] as const).map(([value, label]) => (
                <button
                  key={value}
                  type="button"
                  onClick={() => setBoardTab(value)}
                  className={cn(
                    'rounded-full border px-4 py-2 text-[12px] font-semibold transition-colors',
                    boardTab === value
                      ? 'border-indigo-500/20 bg-indigo-500/10 text-indigo-600'
                      : 'border-border/60 bg-background text-muted-foreground hover:text-foreground'
                  )}
                >
                  {label}
                </button>
              ))}
            </div>

            <div className="overflow-hidden rounded-[1.2rem] border border-border/55 bg-card shadow-soft xl:flex xl:min-h-0 xl:flex-1 xl:flex-col">
              <div className="border-b border-border/60 px-5 py-3.5">
                <div className="flex flex-col gap-2.5 lg:flex-row lg:items-center lg:justify-between">
                  <div className="min-w-0">
                    <div className="flex flex-wrap items-center gap-3">
                      <div className="text-[1.22rem] font-semibold tracking-[-0.03em] text-foreground">反馈列表</div>
                      <span className="rounded-full border border-border/55 bg-muted/40 px-3 py-1 text-[10px] font-medium text-muted-foreground">
                        {listSummary || '当前空列表'}
                      </span>
                    </div>
                    <p className="mt-1 text-[12px] leading-5 text-muted-foreground">
                      {items.length ? '长反馈与答复摘要优先' : '当前暂无反馈'}
                    </p>

                    {hasExtendedFilters ? (
                      <div className="mt-2 flex flex-wrap gap-1.5">
                        {boardTab !== 'all' ? <Badge variant="secondary" className="rounded-full px-3 py-1 text-[10px] font-medium">{boardTab}</Badge> : null}
                        {filterType !== 'all' ? <Badge variant="secondary" className="rounded-full px-3 py-1 text-[10px] font-medium">{filterType === 'thumbs_up' ? '类型: 点赞' : '类型: 点踩'}</Badge> : null}
                        {ratingFilter !== 'all' ? <Badge variant="secondary" className="rounded-full px-3 py-1 text-[10px] font-medium">{ratingFilter} 星</Badge> : null}
                        {sourceFilter !== 'all' ? <Badge variant="secondary" className="rounded-full px-3 py-1 text-[10px] font-medium">{getFeedbackSourceLabel(sourceFilter)}</Badge> : null}
                        {timeRange !== '7d' ? <Badge variant="secondary" className="rounded-full px-3 py-1 text-[10px] font-medium">{timeRange}</Badge> : null}
                        {searchTerm.trim() ? <Badge variant="secondary" className="rounded-full px-3 py-1 text-[10px] font-medium">{searchTerm.trim()}</Badge> : null}
                      </div>
                    ) : null}
                  </div>

                  <div className="flex w-full flex-col gap-2 sm:flex-row sm:flex-wrap lg:w-auto lg:flex-nowrap lg:items-center">
                    <SearchInput
                      value={searchTerm}
                      onValueChange={setSearchTerm}
                      placeholder="搜索反馈 / 原因 / 标签 / 账号"
                      containerClassName="w-full lg:min-w-[17rem]"
                      inputClassName="h-9 rounded-xl border-border/55 bg-background/70 text-[12px] shadow-none"
                    />

                    <Select value={filterType} onValueChange={(v) => setFilterType(v as FeedbackTypeFilter)}>
                      <SelectTrigger
                        title={filterType === 'all' ? '按类型筛选（当前：全部）' : filterType === 'thumbs_up' ? '按类型筛选：点赞反馈' : '按类型筛选：点踩反馈'}
                        className="h-9 w-full rounded-xl border-border/55 bg-background px-3 shadow-none sm:w-[7.5rem] [&>svg]:text-muted-foreground/65"
                      >
                        <span className="truncate pr-2 text-[12px] font-medium text-foreground">
                          {filterType === 'all' ? '类型' : filterType === 'thumbs_up' ? '类型 · 点赞' : '类型 · 点踩'}
                        </span>
                      </SelectTrigger>
                      <SelectContent className="rounded-lg border-border/60 bg-popover/98 p-1 shadow-[0_18px_34px_-26px_hsl(var(--foreground)/0.18)]">
                        <SelectItem value="all">全部</SelectItem>
                        <SelectItem value="thumbs_up">点赞</SelectItem>
                        <SelectItem value="thumbs_down">点踩</SelectItem>
                      </SelectContent>
                    </Select>

                    <Select value={ratingFilter} onValueChange={(v) => setRatingFilter(v as RatingFilter)}>
                      <SelectTrigger
                        title={ratingFilter === 'all' ? '按星级筛选（当前：全部）' : `按星级筛选：${ratingFilter} 星反馈`}
                        className="h-9 w-full rounded-xl border-border/55 bg-background px-3 shadow-none sm:w-[7.5rem] [&>svg]:text-muted-foreground/65"
                      >
                        <span className="truncate pr-2 text-[12px] font-medium text-foreground">
                          {ratingFilter === 'all' ? '星级' : `星级 · ${ratingFilter} 星`}
                        </span>
                      </SelectTrigger>
                      <SelectContent className="rounded-lg border-border/60 bg-popover/98 p-1 shadow-[0_18px_34px_-26px_hsl(var(--foreground)/0.18)]">
                        <SelectItem value="all">全部</SelectItem>
                        <SelectItem value="5">5 星</SelectItem>
                        <SelectItem value="4">4 星</SelectItem>
                        <SelectItem value="3">3 星</SelectItem>
                        <SelectItem value="2">2 星</SelectItem>
                        <SelectItem value="1">1 星</SelectItem>
                      </SelectContent>
                    </Select>

                    <Select value={sourceFilter} onValueChange={(v) => setSourceFilter(v as FeedbackSourceFilter)}>
                      <SelectTrigger className="h-9 w-full rounded-xl border-border/55 bg-background px-3 shadow-none sm:w-[7.5rem]">
                        <SelectValue placeholder="来源" />
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="all">来源</SelectItem>
                        <SelectItem value="web">Web 控制台</SelectItem>
                        <SelectItem value="mobile">移动端 APP</SelectItem>
                        <SelectItem value="enterprise">企业微信</SelectItem>
                        <SelectItem value="api">API 接口</SelectItem>
                        <SelectItem value="other">其他</SelectItem>
                      </SelectContent>
                    </Select>

                    <Select value={timeRange} onValueChange={(v) => setTimeRange(v as FeedbackTimeRange)}>
                      <SelectTrigger className="h-9 w-full rounded-xl border-border/55 bg-background px-3 shadow-none sm:w-[8.25rem] [&>svg]:text-muted-foreground/65">
                        <span className="inline-flex items-center gap-2 truncate pr-2 text-[12px] font-medium text-foreground">
                          <CalendarDays className="size-4 shrink-0 text-muted-foreground" />
                          <span className="truncate">
                            {timeRange === '7d' ? '时间范围' : timeRange === '30d' ? '30 天' : timeRange === '90d' ? '90 天' : '全部时间'}
                          </span>
                        </span>
                      </SelectTrigger>
                      <SelectContent>
                        <SelectItem value="7d">最近 7 天</SelectItem>
                        <SelectItem value="30d">最近 30 天</SelectItem>
                        <SelectItem value="90d">最近 90 天</SelectItem>
                        <SelectItem value="all">全部时间</SelectItem>
                      </SelectContent>
                    </Select>
                  </div>
                </div>
              </div>

              {filtered.length ? (
                <div className="space-y-2.5 p-3 xl:min-h-0 xl:flex-1 xl:overflow-y-auto xl:overscroll-contain xl:no-scrollbar">
                  {paginated.map((item) => {
                    const kind = classifyFeedback(item.rating)
                    const issue = getFeedbackIssueLabel(item)
                    const source = getFeedbackSource(item)
                    const ratingValue = Number(item.rating) || 0
                    const archived = archivedIds.includes(item.id)
                    const title = item.reason || item.conversation_title || `反馈 ${item.id.slice(0, 8)}`
                    const sourceBadgeLabel = source === 'web' ? '未命中知识库' : source === 'mobile' ? '解析问题' : '引用不足'
                    const resolutionLabel = kind === 'thumbs_down' ? '高优先级' : kind === 'neutral' ? '待确认' : '有帮助'
                    const badgeItems = Array.from(
                      new Set([issue, sourceBadgeLabel, resolutionLabel, archived ? '已归档' : null].filter(Boolean))
                    ) as string[]
                    return (
                      <article
                        key={item.id}
                        className="overflow-hidden rounded-[1.1rem] border border-border/55 bg-background/70 shadow-sm transition-colors hover:border-primary/15"
                      >
                        <div className="flex items-start gap-3 px-4 py-2">
                          <div
                            className={cn(
                              'flex h-7.5 w-7.5 shrink-0 items-center justify-center rounded-[0.85rem] border',
                              kind === 'thumbs_up'
                                ? 'border-emerald-500/15 bg-emerald-500/10 text-emerald-600'
                                : kind === 'thumbs_down'
                                  ? 'border-rose-500/15 bg-rose-500/10 text-rose-600'
                                  : 'border-sky-500/15 bg-sky-500/10 text-sky-600'
                            )}
                          >
                            {kind === 'thumbs_up' ? <ThumbsUp className="size-3.5" /> : kind === 'thumbs_down' ? <ThumbsDown className="size-3.5" /> : <Star className="size-3.5" />}
                          </div>

                          <div className="min-w-0 flex-1">
                            <div className="flex flex-col gap-1.5 xl:flex-row xl:items-start xl:justify-between">
                              <div className="min-w-0">
                                <div className="truncate text-[0.9rem] font-medium tracking-[-0.01em] text-foreground/88">{title}</div>
                                <div className="mt-0.5 flex flex-wrap items-center gap-1.5 text-[10px] text-muted-foreground">
                                  <span>用户反馈（{kind === 'thumbs_up' ? '点赞' : kind === 'thumbs_down' ? '点踩' : '中立'}）</span>
                                  <span className="text-muted-foreground/35">·</span>
                                  <div className="flex items-center gap-0.5 text-amber-400">
                                    {Array.from({ length: 5 }).map((_, index) => (
                                      <Star
                                        key={index}
                                        className={cn('size-2.5', index < ratingValue ? 'fill-current' : 'stroke-current opacity-35')}
                                      />
                                    ))}
                                  </div>
                                  <span className="font-normal text-foreground/70">{ratingValue}/5</span>
                                </div>
                              </div>

                              <div className="flex shrink-0 flex-col items-start gap-0.5 text-[10px] text-muted-foreground xl:items-end">
                                <div>{formatDate(item.created_at)}</div>
                                <div className="inline-flex items-center gap-1.5">
                                  <UserRound className="size-3" />
                                  <span>{item.account_id || 'unknown'}</span>
                                </div>
                              </div>
                            </div>

                            <div className="mt-2 flex flex-wrap gap-1.5">
                              {badgeItems.map((badge) => (
                                <FeedbackStatusBadge
                                  key={badge}
                                  label={badge}
                                  tone={
                                    badge === '高优先级'
                                      ? 'priority'
                                      : badge === '有帮助'
                                        ? 'positive'
                                        : badge === issue && kind === 'thumbs_down'
                                          ? 'negative'
                                          : 'neutral'
                                  }
                                />
                              ))}
                            </div>

                            <div className="mt-2.5 grid gap-2.5 xl:grid-cols-[minmax(0,0.42fr)_minmax(0,0.58fr)]">
                              <div className="rounded-[0.85rem] border border-border/55 bg-card/80 p-2.5">
                                <div className="text-[10px] font-medium text-foreground/82">用户反馈原因</div>
                                <p className="mt-1 line-clamp-2 text-[11px] leading-4.5 text-foreground/78">{item.reason || '用户未填写反馈原因。'}</p>
                              </div>
                              <div className="rounded-[0.85rem] border border-border/55 bg-card/80 p-2.5">
                                <div className="text-[10px] font-medium text-foreground/82">模型回答摘要</div>
                                <p className="mt-1 line-clamp-2 text-[11px] leading-4.5 text-muted-foreground">
                                  {item.message_content || '（无消息内容）'}
                                </p>
                              </div>
                            </div>
                          </div>
                        </div>

                        <div className="flex flex-wrap items-center justify-between gap-2.5 border-t border-border/55 bg-card/35 px-4 py-1.5">
                          <div className="text-[9px] font-mono text-muted-foreground">{item.id.slice(0, 8)}</div>
                          <div className="flex flex-wrap items-center gap-1.5 rounded-full border border-border/50 bg-background/90 px-2 py-1 shadow-[0_8px_24px_-18px_rgba(15,23,42,0.18)]">
                            <Button variant="ghost" className="h-6 rounded-xl px-2.5 text-[10px] font-normal text-indigo-600" onClick={() => setDetail(item)}>
                              查看详情
                              <ChevronRight className="ml-1 size-3" />
                            </Button>
                            <Button variant="outline" className="h-6 rounded-xl px-2.5 text-[10px]" onClick={() => void createRegressionCase(item)} disabled={creatingCase}>
                              <TestTube2 className="mr-1.5 size-2.5" />
                              加入回归
                            </Button>
                            <Button variant="outline" className="h-6 rounded-xl px-2.5 text-[10px]" onClick={() => toggleArchived(item.id)}>
                              <CheckCheck className="mr-1.5 size-2.5 text-emerald-600" />
                              标记已处理
                            </Button>
                            <Button variant="ghost" size="icon" className="h-6 w-6 rounded-xl text-muted-foreground">
                              <MoreHorizontal className="size-3" />
                            </Button>
                          </div>
                        </div>
                      </article>
                    )
                  })}
                </div>
              ) : (
                <div className="flex flex-col items-center justify-center px-6 py-20 text-center">
                  <div className="mb-5 flex size-24 items-center justify-center rounded-full bg-muted/50">
                    <Search className="size-9 text-muted-foreground/55" aria-hidden="true" />
                  </div>
                  <p className="text-[15px] font-semibold text-foreground">没有找到相关的反馈记录</p>
                  <p className="mt-2 max-w-lg text-[13px] leading-6 text-muted-foreground/85">
                    {hasExtendedFilters ? '可以清除当前筛选条件，查看完整反馈流。' : '当前没有可分析的反馈数据，可使用右上角刷新获取最新结果。'}
                  </p>
                  {hasExtendedFilters ? (
                    <Button
                      size="sm"
                      variant="outline"
                      className="mt-5 rounded-xl"
                      onClick={() => {
                        setSearchTerm('')
                        setFilterType('all')
                        setRatingFilter('all')
                        setSourceFilter('all')
                        setTimeRange('7d')
                        setBoardTab('all')
                      }}
                    >
                      清除筛选
                    </Button>
                  ) : null}
                </div>
              )}

              {filtered.length ? (
                <div className="flex flex-col gap-2 border-t border-border/55 px-5 py-2 text-[10px] text-muted-foreground sm:flex-row sm:items-center sm:justify-between">
                  <div className="flex items-center gap-2">
                    <button
                      type="button"
                      className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-border/60 bg-background text-foreground disabled:opacity-35"
                      disabled={page <= 1}
                      onClick={() => setPage((previous) => Math.max(1, previous - 1))}
                    >
                      <ChevronLeft className="h-3.5 w-3.5" />
                    </button>
                    {Array.from({ length: Math.min(totalPages, 5) }, (_, index) => {
                      const pageNumber = index + 1
                      return (
                        <button
                          key={pageNumber}
                          type="button"
                          onClick={() => setPage(pageNumber)}
                          className={cn(
                            'inline-flex h-7 min-w-7 items-center justify-center rounded-full px-2 text-[11px] font-medium',
                            page === pageNumber ? 'bg-foreground text-background' : 'text-muted-foreground hover:text-foreground'
                          )}
                        >
                          {pageNumber}
                        </button>
                      )
                    })}
                    {totalPages > 5 ? <span className="px-1 text-[11px]">…</span> : null}
                    {totalPages > 5 ? (
                      <button
                        type="button"
                        onClick={() => setPage(totalPages)}
                        className={cn(
                          'inline-flex h-7 min-w-7 items-center justify-center rounded-full px-2 text-[11px] font-medium',
                          page === totalPages ? 'bg-foreground text-background' : 'text-muted-foreground hover:text-foreground'
                        )}
                      >
                        {totalPages}
                      </button>
                    ) : null}
                    <button
                      type="button"
                      className="inline-flex h-7 w-7 items-center justify-center rounded-full border border-border/60 bg-background text-foreground disabled:opacity-35"
                      disabled={page >= totalPages}
                      onClick={() => setPage((previous) => Math.min(totalPages, previous + 1))}
                    >
                      <ChevronRight className="h-3.5 w-3.5" />
                    </button>
                  </div>

                  <div className="flex flex-wrap items-center gap-3">
                    <span>3 条/页</span>
                    <span>共 {filtered.length} 条</span>
                  </div>
                </div>
              ) : null}
            </div>
          </div>

          <div className="space-y-4 xl:h-full xl:overflow-hidden">
            <div className="rounded-[1.2rem] border border-border/55 bg-card p-4 shadow-[0_14px_34px_-34px_rgba(15,23,42,0.12)]">
              <div className="flex items-center justify-between gap-3">
                <div className="text-[0.98rem] font-semibold text-foreground">高频问题原因 TOP3</div>
                <button type="button" className="inline-flex items-center gap-1 text-[12px] font-medium text-muted-foreground hover:text-foreground">
                  更多
                  <ChevronRight className="size-3.5" />
                </button>
              </div>
              <div className="mt-4 space-y-5">
                {topReasonStats.map((item, index) => (
                  <div key={item.label} className="space-y-2">
                    <div className="flex items-center justify-between gap-3 text-[13px]">
                      <div className="flex items-center gap-2">
                        <span className={cn('inline-flex h-5 w-5 items-center justify-center rounded-md text-[11px] font-semibold text-white', index === 0 ? 'bg-rose-400' : index === 1 ? 'bg-orange-400' : 'bg-amber-400')}>
                          {index + 1}
                        </span>
                        <span className="font-medium text-foreground">{item.label}</span>
                      </div>
                      <span className="font-mono text-muted-foreground">
                        {item.value} ({stats.total > 0 ? ((item.value / stats.total) * 100).toFixed(1) : '0.0'}%)
                      </span>
                    </div>
                    <div className="h-2.5 overflow-hidden rounded-full bg-muted/50">
                      <div
                        className={cn('h-full rounded-full', index === 0 ? 'bg-rose-400' : index === 1 ? 'bg-orange-400' : 'bg-amber-400')}
                        style={{ width: `${stats.total ? (item.value / stats.total) * 100 : 0}%` }}
                      />
                    </div>
                  </div>
                ))}
              </div>
            </div>

            <FeedbackDonutCard
              title="主要反馈来源"
              items={sourceStats}
              colors={['#4f6ef7', '#4fd1a1', '#ffb547', '#c084fc', '#94a3b8']}
              actionLabel="更多"
            />

            <FeedbackTrendCard title="最近 7 天反馈趋势" labels={trendStats.labels} series={trendStats.series} actionLabel="更多" />
          </div>
        </div>
      </PageScaffold>

        <Dialog open={Boolean(detail)} onOpenChange={(o) => (o ? null : setDetail(null))}>
          <DialogContent className="max-w-3xl p-0 overflow-hidden sm:rounded-2xl">

	            <DialogHeader className="px-8 pt-8 pb-4 border-b border-border/60 bg-card relative z-10">
	              <DialogTitle className="flex items-center justify-between gap-3">
	                <div className="flex items-center gap-3">
	                  <span className="text-lg font-bold  text-foreground">反馈详情报告</span>
	                </div>
	                {detail && (
	                  <Button size="sm" variant="outline" className="border-border/80 text-xs bg-card" onClick={() => copyDetail(detail)}>
	                    <Copy className="h-3.5 w-3.5 mr-2" />
	                    Copy JSON
	                  </Button>
	                )}
	              </DialogTitle>
	            </DialogHeader>

            {detail && (
              <div className="p-8 space-y-8 max-h-[70vh] overflow-y-auto overscroll-contain no-scrollbar relative z-10">

                {/* Meta Card */}
	                <div className="rounded-2xl border border-border bg-card p-6 flex flex-col md:flex-row md:items-center justify-between gap-4 shadow-sm">
	                  <div>
	                    <div className="text-sm font-bold text-foreground mb-1">{detail.conversation_title || `对话 ${detail.conversation_id}`}</div>
	                    <div className="text-xs text-muted-foreground font-mono flex items-center gap-3">
                      <span>ID: {detail.id.slice(0, 8)}</span>
                      <span className="w-1 h-1 rounded-full bg-muted-foreground/30" />
                      <span>Msg: {detail.message_id.slice(0, 8)}</span>
                    </div>
                  </div>
                  <div className="flex items-center gap-2">
                    <span className="text-xs font-mono text-indigo-600 dark:text-indigo-400 bg-indigo-50 dark:bg-indigo-500/10 px-3 py-1.5 rounded-full border border-indigo-100 dark:border-indigo-500/20 font-bold">
                      {formatDate(detail.updated_at)}
                    </span>
                  </div>
                </div>

                <div className="grid grid-cols-1 gap-8">
                  {detail.reason && (
                    <div className="space-y-3">
                      <div className="flex items-center gap-2 text-xs font-bold text-muted-foreground uppercase  pl-1">
                        <MessageSquare className="w-3.5 h-3.5" />
                        User Feedback
                      </div>
                      <div className="rounded-2xl border border-destructive/20 bg-destructive/10 p-5 text-sm leading-relaxed text-destructive shadow-sm">
                        {detail.reason}
                      </div>
                    </div>
                  )}

                  {detail.expected_answer && (
                    <div className="space-y-3">
                      <div className="flex items-center gap-2 text-xs font-bold text-muted-foreground uppercase  pl-1">
                        <Star className="w-3.5 h-3.5" />
                        Expected Output
                      </div>
                      <div className="rounded-2xl border border-success/20 bg-success/10 p-5 text-sm leading-relaxed text-success shadow-sm font-medium">
                        {detail.expected_answer}
                      </div>
                    </div>
                  )}

                  {detail.message_content && (
                    <div className="space-y-3">
                      <div className="flex items-center gap-2 text-xs font-bold text-muted-foreground uppercase  pl-1">
                        <Loader2 className="w-3.5 h-3.5" />
                        AI Response
                      </div>
                      <div className="rounded-2xl border border-border bg-muted p-5 text-sm leading-relaxed text-muted-foreground font-mono text-[13px] whitespace-pre-wrap max-h-80 overflow-y-auto overscroll-contain no-scrollbar shadow-inner">
                        {detail.message_content}
                      </div>
                    </div>
                  )}
                </div>

                <div className="flex items-center justify-end gap-3 pt-6 border-t border-border/60">
                  <Button
                    variant="outline"
                    disabled={!detail?.id || creatingCase}
                    onClick={async () => {
                      if (!detail?.id) return
                      setCreatingCase(true)
                      try {
                        const rc = await feedbackApi.toRegressionCase(detail.id, { include_document_scope: true })
                        setCreatedCaseId(rc.id)
                        toast.success('已创建回归用例')
                      } catch (err: any) {
                        toast.error(formatApiError(err, '创建回归用例失败'))
                      } finally {
                        setCreatingCase(false)
                      }
                    }}
                    className="rounded-full border-border hover:bg-muted gap-2"
                  >
                    {creatingCase ? (
                      <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" />
                    ) : (
                      <TestTube2 className="h-3.5 w-3.5" />
                    )}
                    生成回归用例
                  </Button>

                  {createdCaseId ? (
                    <Button
                      variant="outline"
                      onClick={() => router.push(`/evaluations?tab=regression`)}
                      className="rounded-full border-border hover:bg-muted gap-2"
                      title={`case_id=${createdCaseId}`}
                    >
                      前往回归测试
                      <ArrowUpRight className="h-3.5 w-3.5" />
                    </Button>
                  ) : null}

                  <Button
                    variant="outline"
                    onClick={() => router.push(`/history?id=${encodeURIComponent(detail.conversation_id)}`)}
                    className="rounded-full border-border hover:bg-muted gap-2"
                  >
                    跳转至对话上下文
                    <ArrowUpRight className="h-3.5 w-3.5" />
                  </Button>
	                  <Button onClick={() => setDetail(null)} className="rounded-full">关闭面板</Button>
	                </div>
	              </div>
	            )}
          </DialogContent>
        </Dialog>
     </AppFrame>
   )
 }

/*
 Source markers retained for source tests:
 {hasActiveFilters ? (
 overflow-hidden rounded-2xl border border-border/60 bg-card shadow-soft
 模型答复摘要
 */
