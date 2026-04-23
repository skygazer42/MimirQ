'use client'

import { useEffect, useMemo, useState } from 'react'
import { keepPreviousData, useQuery } from '@tanstack/react-query'
import { usePathname, useRouter, useSearchParams } from 'next/navigation'
import {
  Activity,
  AlertCircle,
  Eye,
  Files,
  FileWarning,
  PieChart as PieChartIcon,
  RefreshCw,
  Search,
  ShieldAlert,
  Sparkles,
} from 'lucide-react'
import { PieChart, Pie, Cell, ResponsiveContainer, BarChart, Bar, CartesianGrid, Tooltip as RechartsTooltip, XAxis, YAxis } from 'recharts'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { IngestionDetailDialog } from '@/components/ingestion/ingestion-detail-dialog'
import { EmptyState } from '@/components/ingestion/empty-state'
import { buildDemoDocuments } from './demo-documents'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Button } from '@/components/ui/button'
import { SearchInput } from '@/components/ui/search-input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Badge } from '@/components/ui/badge'
import { documentApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { cn, formatDate, formatFileSize } from '@/lib/utils'
import { getDocumentKind, getDocumentKindAccent } from '@/components/ingestion/monitor-utils'
import type { Document } from '@/types'

type StatusFilter = 'all' | 'pending' | 'processing' | 'completed' | 'failed' | 'quarantined' | 'cancelled'
type RouteBucketFilter = 'all' | 'Clean_Markdown' | 'Scan_PDF' | 'Parse_Failed' | 'Sensitive_Review'

const KIND_LABEL: Record<string, string> = {
  pdf: 'PDF',
  markdown: 'Markdown / Text',
  spreadsheet: 'Spreadsheet',
  html: 'HTML',
  text: 'Text',
}

const KIND_COLOR: Record<string, string> = {
  pdf: '#f97316',
  markdown: '#0ea5e9',
  spreadsheet: '#10b981',
  html: '#8b5cf6',
  text: '#64748b',
}

const ROUTE_COPY: Record<Exclude<RouteBucketFilter, 'all'>, { title: string; basis: string; action: string; tone: 'info' | 'warning' | 'danger' }> = {
  Clean_Markdown: {
    title: 'Clean_Markdown',
    basis: '结构清晰，可直接解析',
    action: '直接分块入库',
    tone: 'info',
  },
  Scan_PDF: {
    title: 'Scan_PDF',
    basis: '扫描型或混合型 PDF',
    action: '先 OCR / 预清洗',
    tone: 'warning',
  },
  Parse_Failed: {
    title: 'Parse_Failed',
    basis: '解析失败或格式不兼容',
    action: '人工检查 / 重试',
    tone: 'danger',
  },
  Sensitive_Review: {
    title: 'Sensitive_Review',
    basis: '命中敏感信息或治理规则',
    action: '进入待审核清单',
    tone: 'warning',
  },
}

function StatusBadge({ status }: Readonly<{ status: Document['status'] }>) {
  const label =
    status === 'completed'
      ? '可直通'
      : status === 'failed'
        ? '解析失败'
        : status === 'quarantined'
          ? '待确认'
          : status === 'processing'
            ? '处理中'
            : status === 'pending'
              ? '待处理'
              : '已取消'

  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full border px-2.5 py-1 text-[11px] font-semibold',
        status === 'completed' && 'border-emerald-500/20 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300',
        status === 'failed' && 'border-red-500/20 bg-red-500/10 text-red-600 dark:text-red-300',
        status === 'quarantined' && 'border-amber-500/20 bg-amber-500/10 text-amber-700 dark:text-amber-300',
        status === 'processing' && 'border-sky-500/20 bg-sky-500/10 text-sky-700 dark:text-sky-300',
        status === 'pending' && 'border-sky-500/20 bg-sky-500/10 text-sky-700 dark:text-sky-300',
        status === 'cancelled' && 'border-border/60 bg-muted/60 text-muted-foreground'
      )}
    >
      {label}
    </span>
  )
}

function FileKindGlyph({
  kind,
  className,
}: Readonly<{
  kind: ReturnType<typeof getDocumentKind>
  className?: string
}>) {
  if (kind === 'pdf') {
    return (
      <svg viewBox="0 0 24 24" className={cn('h-4 w-4', className)} aria-hidden="true">
        <path d="M7 3.5h7l4 4V20.5H7z" fill="currentColor" opacity="0.18" />
        <path d="M14 3.5v4h4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
        <path d="M8.5 15.5h7" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <path d="M8.5 18h5" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    )
  }

  if (kind === 'markdown') {
    return (
      <svg viewBox="0 0 24 24" className={cn('h-4 w-4', className)} aria-hidden="true">
        <rect x="5" y="5" width="14" height="14" rx="3" fill="currentColor" opacity="0.12" />
        <path d="M8 16V9l2.5 3 2.5-3v7" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
        <path d="M15.5 10.5v4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
        <path d="m14 13 1.5 1.5L17 13" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    )
  }

  if (kind === 'spreadsheet') {
    return (
      <svg viewBox="0 0 24 24" className={cn('h-4 w-4', className)} aria-hidden="true">
        <rect x="5" y="4.5" width="14" height="15" rx="2.5" fill="currentColor" opacity="0.12" />
        <path d="M5 9.5h14M10 4.5v15M14.5 9.5v10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
      </svg>
    )
  }

  if (kind === 'html') {
    return (
      <svg viewBox="0 0 24 24" className={cn('h-4 w-4', className)} aria-hidden="true">
        <path d="m8.5 8.5-3 3 3 3M15.5 8.5l3 3-3 3M13.5 7l-3 10" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round" />
      </svg>
    )
  }

  return (
    <svg viewBox="0 0 24 24" className={cn('h-4 w-4', className)} aria-hidden="true">
      <rect x="6" y="4.5" width="12" height="15" rx="2.5" fill="currentColor" opacity="0.12" />
      <path d="M9 9h6M9 12.5h6M9 16h4" fill="none" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" />
    </svg>
  )
}

function MetricCard({
  label,
  value,
  hint,
  icon: Icon,
  tone = 'neutral',
}: Readonly<{
  label: string
  value: string | number
  hint: string
  icon: typeof Activity
  tone?: 'neutral' | 'success' | 'warning' | 'danger'
}>) {
  return (
    <div
      className={cn(
        'rounded-[1.5rem] border bg-card px-5 py-4 shadow-sm',
        tone === 'neutral' && 'border-border/60',
        tone === 'success' && 'border-emerald-500/10',
        tone === 'warning' && 'border-amber-500/10',
        tone === 'danger' && 'border-red-500/10'
      )}
    >
      <div className="flex items-start justify-between gap-4">
        <div className="space-y-2">
          <div className="text-[11px] font-semibold tracking-wide text-muted-foreground">{label}</div>
          <div className="text-[2rem] font-semibold leading-none tracking-[-0.04em] text-foreground">{value}</div>
        </div>
        <div
          className={cn(
            'flex size-11 shrink-0 items-center justify-center rounded-2xl border',
            tone === 'neutral' && 'border-sky-500/10 bg-sky-500/10 text-sky-600',
            tone === 'success' && 'border-emerald-500/10 bg-emerald-500/10 text-emerald-600',
            tone === 'warning' && 'border-amber-500/10 bg-amber-500/10 text-amber-600',
            tone === 'danger' && 'border-red-500/10 bg-red-500/10 text-red-600'
          )}
        >
          <Icon className="size-5" />
        </div>
      </div>
      <div className="mt-4 text-xs leading-5 text-muted-foreground">{hint}</div>
    </div>
  )
}

function SectionCard({
  eyebrow,
  title,
  children,
  action,
}: Readonly<{
  eyebrow: string
  title: string
  children: React.ReactNode
  action?: React.ReactNode
}>) {
  return (
    <section className="rounded-[1.75rem] border border-border/60 bg-card p-6 shadow-sm">
      <div className="mb-5 flex items-start justify-between gap-4">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground">{eyebrow}</div>
          <div className="mt-2 text-lg font-semibold tracking-[-0.03em] text-foreground">{title}</div>
        </div>
        {action}
      </div>
      {children}
    </section>
  )
}

function buildSizeBuckets(documents: Document[]) {
  const buckets = [
    { label: '<500KB', min: 0, max: 500 * 1024 },
    { label: '500KB-2MB', min: 500 * 1024, max: 2 * 1024 * 1024 },
    { label: '2MB-5MB', min: 2 * 1024 * 1024, max: 5 * 1024 * 1024 },
    { label: '5MB-10MB', min: 5 * 1024 * 1024, max: 10 * 1024 * 1024 },
    { label: '>10MB', min: 10 * 1024 * 1024, max: Number.POSITIVE_INFINITY },
  ]

  return buckets.map((bucket) => ({
    label: bucket.label,
    count: documents.filter((doc) => {
      const size = Number(doc.file_size || 0)
      return size >= bucket.min && size < bucket.max
    }).length,
  }))
}

function matchesRouteBucket(doc: Document, bucket: RouteBucketFilter) {
  const kind = getDocumentKind(doc.filename)

  if (bucket === 'Clean_Markdown') return kind === 'markdown' && doc.status === 'completed'
  if (bucket === 'Scan_PDF') return kind === 'pdf' && doc.status !== 'completed'
  if (bucket === 'Parse_Failed') return doc.status === 'failed'
  if (bucket === 'Sensitive_Review') return doc.status === 'quarantined'

  return true
}

export default function KnowledgeIngestionPageClient() {
  const router = useRouter()
  const pathname = usePathname()
  const searchParams = useSearchParams()
  const datasetIdFromUrl = searchParams.get('dataset')
  const demoMode = searchParams.get('demo') === '1'

  const [search, setSearch] = useState('')
  const [status, setStatus] = useState<StatusFilter>('all')
  const [routeBucketFilter, setRouteBucketFilter] = useState<RouteBucketFilter>('all')
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailDocumentId, setDetailDocumentId] = useState<string | null>(null)
  const [demoDocuments, setDemoDocuments] = useState<Document[]>([])

  const { data, isInitialLoading, isFetching, refetch } = useQuery({
    queryKey: ['ingestion-documents', status, datasetIdFromUrl ?? 'all'],
    queryFn: ({ signal }) =>
      documentApi.list(
        {
          limit: 200,
          status: status === 'all' ? undefined : (status as Document['status']),
          dataset_id: datasetIdFromUrl ?? undefined,
        },
        { signal }
      ),
    staleTime: 3_000,
    placeholderData: keepPreviousData,
  })

  const documents = useMemo(() => data?.items || [], [data])

  useEffect(() => {
    if (demoMode) {
      setDemoDocuments(buildDemoDocuments(documents))
      return
    }
    setDemoDocuments([])
  }, [demoMode, documents])

  const activeDocuments = demoMode ? demoDocuments : documents

  const stats = useMemo(() => {
    const total = activeDocuments.length
    const completed = activeDocuments.filter((doc) => doc.status === 'completed').length
    const failed = activeDocuments.filter((doc) => doc.status === 'failed').length
    const quarantined = activeDocuments.filter((doc) => doc.status === 'quarantined').length
    const pdfCount = activeDocuments.filter((doc) => getDocumentKind(doc.filename) === 'pdf').length
    const totalSize = activeDocuments.reduce((sum, doc) => sum + Number(doc.file_size || 0), 0)

    return {
      total,
      completed,
      failed,
      quarantined,
      pdfCount,
      totalSize,
      manualReview: failed + quarantined,
      pdfShare: total ? Math.round((pdfCount / total) * 100) : 0,
    }
  }, [activeDocuments])

  const sizeBuckets = useMemo(() => buildSizeBuckets(activeDocuments), [activeDocuments])

  const sizePercentiles = useMemo(() => {
    const sizes = activeDocuments.map((doc) => Number(doc.file_size || 0)).sort((a, b) => a - b)
    if (!sizes.length) return { p50: 0, p90: 0 }
    return {
      p50: sizes[Math.floor(sizes.length * 0.5)],
      p90: sizes[Math.floor(sizes.length * 0.9)],
    }
  }, [activeDocuments])

  const formatDistribution = useMemo(() => {
    const counts = new Map<string, number>()
    activeDocuments.forEach((doc) => {
      const kind = getDocumentKind(doc.filename)
      counts.set(kind, (counts.get(kind) ?? 0) + 1)
    })

    return Array.from(counts.entries()).map(([kind, value]) => ({
      kind,
      label: KIND_LABEL[kind] ?? kind.toUpperCase(),
      value,
      fill: KIND_COLOR[kind] ?? KIND_COLOR.text,
    }))
  }, [activeDocuments])

  const routeSummary = useMemo(
    () =>
      (Object.keys(ROUTE_COPY) as Array<Exclude<RouteBucketFilter, 'all'>>).map((key) => {
        const count = activeDocuments.filter((doc) => matchesRouteBucket(doc, key)).length
        return {
          key,
          count,
          ...ROUTE_COPY[key],
        }
      }),
    [activeDocuments]
  )

  const filtered = useMemo(() => {
    const query = search.trim().toLowerCase()

    return activeDocuments.filter((doc) => {
      if (status !== 'all' && doc.status !== status) return false
      if (routeBucketFilter !== 'all' && !matchesRouteBucket(doc, routeBucketFilter)) return false

      if (!query) return true

      return [doc.filename, doc.id, doc.dataset_id ?? '', doc.error_message ?? '']
        .join(' ')
        .toLowerCase()
        .includes(query)
    })
  }, [activeDocuments, routeBucketFilter, search, status])

  const reviewQueue = useMemo(
    () =>
      activeDocuments
        .filter((doc) => doc.status === 'failed' || doc.status === 'quarantined' || matchesRouteBucket(doc, 'Scan_PDF'))
        .slice(0, 6)
        .map((doc) => ({
          doc,
          action:
            doc.status === 'quarantined'
              ? '进入待审核清单'
              : doc.status === 'failed'
                ? '人工检查 / 重试'
                : '先 OCR / 预清洗',
          reason:
            doc.status === 'quarantined'
              ? doc.error_message || '命中敏感信息或治理规则'
              : doc.status === 'failed'
                ? doc.error_message || '解析失败或格式不兼容'
                : '扫描型或混合型 PDF',
        })),
    [activeDocuments]
  )

  const keyFindings = useMemo(() => {
    const findings: string[] = []

    if (formatDistribution.length > 0) {
      const primary = [...formatDistribution].sort((a, b) => b.value - a.value)[0]
      findings.push(`主导格式是 ${primary.label}，共 ${primary.value} 份。`)
    }

    if (stats.pdfCount > 0) {
      findings.push(`PDF 占比 ${stats.pdfShare}% ，需要重点确认是否包含扫描件。`)
    }

    if (stats.manualReview > 0) {
      findings.push(`当前有 ${stats.manualReview} 份文档进入待确认或失败清单。`)
    }

    findings.push(`P50 文件体量为 ${formatFileSize(sizePercentiles.p50)}，P90 为 ${formatFileSize(sizePercentiles.p90)}。`)

    return findings
  }, [formatDistribution, sizePercentiles.p50, sizePercentiles.p90, stats.manualReview, stats.pdfCount, stats.pdfShare])

  const toggleDemoMode = () => {
    const params = new URLSearchParams(searchParams.toString())
    if (demoMode) params.delete('demo')
    else params.set('demo', '1')

    const next = params.toString()
    router.replace(next ? `${pathname}?${next}` : pathname)
  }

  const handleOpenDocument = (doc: Document) => {
    if (demoMode && doc.id.startsWith('demo-')) {
      toast.info('虚拟样本仅用于预检演示，不关联真实文档详情。')
      return
    }

    setDetailDocumentId(doc.id)
    setDetailOpen(true)
  }

  const downloadAuditReport = () => {
    toast.info('脱敏报告导出能力待接入，先保留入口。')
  }

  const routeFilterLabel = routeBucketFilter === 'all' ? '全部样本' : ROUTE_COPY[routeBucketFilter].title

  return (
    <AppFrame>
      <PageScaffold
        title="项目数据审计"
        icon={Activity}
        size="full"
        topClassName="px-3 md:px-4 xl:px-5 pb-4"
        description={
          <div className="flex flex-col gap-3">
            <div className="max-w-4xl text-sm leading-6 text-muted-foreground">
              这是入库前的摸底页面，只负责看格式分布、文件大小分布、规则分流和待确认样本。输出客观事实，不做主观评分。
            </div>
            <div className="flex flex-wrap items-center gap-2">
              <Badge variant="secondary" className="rounded-full px-3 py-1 text-xs font-medium">格式分布</Badge>
              <Badge variant="secondary" className="rounded-full px-3 py-1 text-xs font-medium">大小分布</Badge>
              <Badge variant="secondary" className="rounded-full px-3 py-1 text-xs font-medium">标签分流</Badge>
              <Badge variant="secondary" className="rounded-full px-3 py-1 text-xs font-medium">待确认清单</Badge>
              {demoMode ? (
                <Badge className="rounded-full bg-amber-500 px-3 py-1 text-xs font-medium text-white">虚拟样本模式</Badge>
              ) : null}
            </div>
          </div>
        }
        actions={
          <div className="flex flex-wrap items-center gap-2">
            <Button variant={demoMode ? 'default' : 'outline'} size="sm" className="h-9 gap-2 rounded-full px-4 text-xs font-bold" onClick={toggleDemoMode}>
              <Sparkles className="h-3.5 w-3.5" />
              {demoMode ? '退出虚拟模式' : '加载虚拟数据'}
            </Button>
            <Button variant="outline" size="sm" className="h-9 gap-2 rounded-full px-4 text-xs font-bold" onClick={() => refetch()}>
              <RefreshCw className={cn('h-3.5 w-3.5', isFetching && 'animate-spin motion-reduce:animate-none')} />
              刷新
            </Button>
            <Button size="sm" className="h-9 gap-2 rounded-full px-4 text-xs font-bold" onClick={downloadAuditReport}>
              <FileWarning className="h-3.5 w-3.5" />
              导出脱敏报告
            </Button>
          </div>
        }
      >
        {!activeDocuments.length ? (
          <EmptyState mode="truly-empty" />
        ) : (
          <div className="grid gap-5 xl:grid-cols-[22rem_minmax(0,1fr)]">
            <aside className="rounded-[1.75rem] border border-border/60 bg-card shadow-sm">
              <div className="border-b border-border/60 px-5 py-4">
                <div className="text-[10px] font-semibold uppercase tracking-[0.2em] text-muted-foreground">预检抽样</div>
                <div className="mt-2 text-lg font-semibold tracking-[-0.03em] text-foreground">代表样本</div>
              </div>

              <div className="space-y-3 border-b border-border/60 px-4 py-4">
                <SearchInput
                  value={search}
                  onValueChange={setSearch}
                  placeholder="搜索文件名 / ID / 原因"
                  containerClassName="w-full"
                  inputClassName="h-10 rounded-full border-border/60 bg-background/90"
                />
                <Select value={status} onValueChange={(value) => setStatus(value as StatusFilter)}>
                  <SelectTrigger className="h-10 w-full rounded-full border-border/60 bg-background/90 shadow-none">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="all">所有状态</SelectItem>
                    <SelectItem value="completed">可直通</SelectItem>
                    <SelectItem value="processing">处理中</SelectItem>
                    <SelectItem value="pending">待处理</SelectItem>
                    <SelectItem value="failed">解析失败</SelectItem>
                    <SelectItem value="quarantined">待确认</SelectItem>
                  </SelectContent>
                </Select>
              </div>

              <div className="border-b border-border/60 px-4 py-3 text-xs text-muted-foreground">
                当前筛选：{routeFilterLabel}
              </div>

              <div className="max-h-[calc(100dvh-20rem)] overflow-y-auto">
                {filtered.length === 0 ? (
                  <div className="p-4">
                    <EmptyState mode="filter-empty" onClearFilters={() => {
                      setSearch('')
                      setStatus('all')
                      setRouteBucketFilter('all')
                    }} />
                  </div>
                ) : (
                  filtered.map((doc) => {
                    const kind = getDocumentKind(doc.filename)

                    return (
                      <button
                        key={doc.id}
                        type="button"
                        className="group flex w-full items-start gap-3 border-b border-border/40 px-4 py-4 text-left transition-colors hover:bg-muted/30"
                        onClick={() => handleOpenDocument(doc)}
                      >
                        <div className={cn('flex h-9 w-9 shrink-0 items-center justify-center rounded-xl border', getDocumentKindAccent(kind))}>
                          <FileKindGlyph kind={kind} />
                        </div>
                        <div className="min-w-0 flex-1">
                          <div className="truncate text-sm font-semibold text-foreground group-hover:text-primary">{doc.filename}</div>
                          <div className="mt-1 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                            <span>{formatDate(doc.updated_at)}</span>
                            <span>·</span>
                            <span>{formatFileSize(doc.file_size)}</span>
                            {doc.chunk_count ? (
                              <>
                                <span>·</span>
                                <span>{doc.chunk_count} chunks</span>
                              </>
                            ) : null}
                          </div>
                          <div className="mt-2 flex items-center gap-2">
                            <StatusBadge status={doc.status} />
                            <span className="font-mono text-[10px] text-muted-foreground/70">{doc.id.slice(0, 8)}</span>
                          </div>
                        </div>
                        <Eye className="mt-1 h-4 w-4 shrink-0 text-muted-foreground/50 transition-colors group-hover:text-primary" />
                      </button>
                    )
                  })
                )}
              </div>
            </aside>

            <main className="space-y-5">
              <div className="grid gap-4 md:grid-cols-2 xl:grid-cols-4">
                <MetricCard
                  label="总文件数"
                  value={stats.total}
                  hint="本次预检纳入统计的文档总量"
                  icon={Files}
                />
                <MetricCard
                  label="PDF 占比"
                  value={`${stats.pdfShare}%`}
                  hint={`${stats.pdfCount} 份 PDF，优先确认是否包含扫描件`}
                  icon={PieChartIcon}
                  tone="warning"
                />
                <MetricCard
                  label="待确认"
                  value={stats.manualReview}
                  hint="解析失败或命中治理规则的样本数"
                  icon={ShieldAlert}
                  tone={stats.manualReview > 0 ? 'danger' : 'neutral'}
                />
                <MetricCard
                  label="可直通"
                  value={routeSummary.find((item) => item.key === 'Clean_Markdown')?.count ?? 0}
                  hint="结构清晰、可直接进入分块流程"
                  icon={Activity}
                  tone="success"
                />
              </div>

              <div className="grid gap-5 xl:grid-cols-[minmax(0,1.1fr)_minmax(24rem,0.9fr)]">
                <SectionCard eyebrow="客观分布" title="格式分布与文件大小分布">
                  <div className="grid gap-6 lg:grid-cols-2">
                    <div>
                      <div className="mb-3 text-sm font-semibold text-foreground">格式分布</div>
                      <div className="h-[240px] w-full">
                        <ResponsiveContainer width="100%" height="100%">
                          <PieChart>
                            <Pie data={formatDistribution} dataKey="value" nameKey="label" innerRadius={52} outerRadius={80} paddingAngle={3}>
                              {formatDistribution.map((entry) => (
                                <Cell key={entry.kind} fill={entry.fill} />
                              ))}
                            </Pie>
                            <RechartsTooltip formatter={(value: unknown, _name: unknown, item: any) => [`${Number(value || 0)} 份`, item?.payload?.label ?? '']} />
                          </PieChart>
                        </ResponsiveContainer>
                      </div>
                      <div className="mt-3 flex flex-wrap gap-2">
                        {formatDistribution.map((item) => (
                          <Badge key={item.kind} variant="secondary" className="rounded-full px-3 py-1 text-xs font-medium">
                            {item.label} {item.value}
                          </Badge>
                        ))}
                      </div>
                    </div>

                    <div>
                      <div className="mb-3 text-sm font-semibold text-foreground">文件大小分布</div>
                      <div className="h-[240px] w-full">
                        <ResponsiveContainer width="100%" height="100%">
                          <BarChart data={sizeBuckets} margin={{ top: 8, right: 8, left: -12, bottom: 8 }}>
                            <CartesianGrid strokeDasharray="3 3" vertical={false} opacity={0.15} />
                            <XAxis dataKey="label" tickLine={false} axisLine={false} fontSize={11} />
                            <YAxis allowDecimals={false} tickLine={false} axisLine={false} fontSize={11} />
                            <RechartsTooltip formatter={(value: unknown) => [`${Number(value || 0)} 份`, '文档数']} />
                            <Bar dataKey="count" radius={[10, 10, 0, 0]} fill="hsl(var(--chart-2))" />
                          </BarChart>
                        </ResponsiveContainer>
                      </div>
                      <div className="mt-3 text-xs leading-5 text-muted-foreground">
                        P50 体量 {formatFileSize(sizePercentiles.p50)}，P90 体量 {formatFileSize(sizePercentiles.p90)}。
                      </div>
                    </div>
                  </div>
                </SectionCard>

                <SectionCard eyebrow="标签体系" title="标签分流清单">
                  <div className="space-y-3">
                    {routeSummary.map((item) => (
                      <button
                        key={item.key}
                        type="button"
                        className={cn(
                          'w-full rounded-2xl border px-4 py-4 text-left transition-colors hover:bg-muted/20',
                          routeBucketFilter === item.key ? 'border-primary/40 bg-primary/5' : 'border-border/50 bg-background'
                        )}
                        onClick={() => setRouteBucketFilter((current) => (current === item.key ? 'all' : item.key))}
                      >
                        <div className="flex items-center justify-between gap-4">
                          <div>
                            <div className="text-sm font-semibold text-foreground">{item.title}</div>
                            <div className="mt-1 text-xs leading-5 text-muted-foreground">{item.basis}</div>
                          </div>
                          <div className="text-right">
                            <div className="font-mono text-lg font-semibold text-foreground">{item.count}</div>
                            <div className="text-[10px] uppercase tracking-[0.18em] text-muted-foreground">docs</div>
                          </div>
                        </div>
                        <div className="mt-3 text-xs font-medium text-foreground/75">推荐处理方式：{item.action}</div>
                      </button>
                    ))}
                  </div>
                </SectionCard>
              </div>

              <div className="grid gap-5 xl:grid-cols-[minmax(0,1fr)_minmax(24rem,0.95fr)]">
                <SectionCard eyebrow="当前观察" title="预检结论">
                  <div className="space-y-4">
                    <div className="rounded-2xl border border-border/50 bg-background px-4 py-4 text-sm leading-6 text-muted-foreground">
                      这页只回答三类问题：文档长什么样、哪些样本需要分流、哪些问题需要人工确认。它不是执行监控页，也不负责给出主观健康分。
                    </div>
                    <div className="space-y-3">
                      {keyFindings.map((finding) => (
                        <div key={finding} className="flex items-start gap-3 rounded-2xl border border-border/40 bg-background px-4 py-3">
                          <AlertCircle className="mt-0.5 h-4 w-4 shrink-0 text-amber-500" />
                          <div className="text-sm leading-6 text-foreground/80">{finding}</div>
                        </div>
                      ))}
                    </div>
                  </div>
                </SectionCard>

                <SectionCard eyebrow="待确认" title="待确认清单">
                  <div className="space-y-3">
                    {reviewQueue.length === 0 ? (
                      <div className="rounded-2xl border border-border/50 bg-background px-4 py-6 text-sm text-muted-foreground">
                        当前没有待确认样本，说明这批文档暂时没有明显的失败项或治理阻塞项。
                      </div>
                    ) : (
                      reviewQueue.map(({ doc, action, reason }) => (
                        <button
                          key={doc.id}
                          type="button"
                          className="w-full rounded-2xl border border-border/50 bg-background px-4 py-4 text-left transition-colors hover:bg-muted/20"
                          onClick={() => handleOpenDocument(doc)}
                        >
                          <div className="flex items-start justify-between gap-4">
                            <div className="min-w-0">
                              <div className="truncate text-sm font-semibold text-foreground">{doc.filename}</div>
                              <div className="mt-1 text-xs leading-5 text-muted-foreground">{reason}</div>
                            </div>
                            <StatusBadge status={doc.status} />
                          </div>
                          <div className="mt-3 flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                            <span>建议：{action}</span>
                            <span>·</span>
                            <span>{formatDate(doc.updated_at)}</span>
                          </div>
                        </button>
                      ))
                    )}
                  </div>
                </SectionCard>
              </div>
            </main>
          </div>
        )}
      </PageScaffold>

      <IngestionDetailDialog open={detailOpen} onOpenChange={setDetailOpen} documentId={detailDocumentId} />
    </AppFrame>
  )
}
