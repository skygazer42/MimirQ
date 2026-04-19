'use client'

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  Activity,
  AlertCircle,
  BarChart3,
  CheckCircle2,
  Clock,
  HardDrive,
  LayoutList,
  Loader2,
  RefreshCw,
  Search,
  ShieldCheck,
} from 'lucide-react'
import { toast } from 'sonner'

import { AppFrame } from '@/components/app-frame'
import { DocumentViewerPanel } from '@/components/document-viewer-panel'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Button } from '@/components/ui/button'
import { SearchInput } from '@/components/ui/search-input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { documentApi, observabilityApi } from '@/lib/api'
import { cn, formatDate, formatFileSize, detachPromise } from '@/lib/utils'
import type { Document, IngestionDashboardSummaryResponse } from '@/types'
import { useDocumentView } from '@/store/document-view'
import { IngestionDetailDialog } from '@/components/ingestion/ingestion-detail-dialog'
import { formatApiError } from '@/lib/api-errors'
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts'

type StatusFilter = 'all' | Document['status']

const STATUS_LABEL: Record<StatusFilter, string> = {
  all: '全部',
  pending: '等待',
  processing: '处理中',
  completed: '已完成',
  failed: '失败',
  quarantined: '已隔离',
  cancelled: '已取消',
}

function formatTs(tsMs: number) {
  try {
    return new Date(tsMs).toLocaleString([], { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })
  } catch {
    return String(tsMs)
  }
}

function StatusPill({ status }: Readonly<{ status: Document['status'] }>) {
  const cfg = (() => {
    switch (status) {
      case 'completed':
        return { icon: CheckCircle2, cls: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20' }
      case 'failed':
        return { icon: AlertCircle, cls: 'bg-red-500/10 text-red-700 dark:text-red-400 border-red-500/20' }
      case 'quarantined':
        return { icon: AlertCircle, cls: 'bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/20' }
      case 'cancelled':
        return { icon: AlertCircle, cls: 'bg-muted/60 text-muted-foreground border-border/60' }
      case 'pending':
        return { icon: Clock, cls: 'bg-sky-500/10 text-sky-700 dark:text-sky-400 border-sky-500/20' }
      case 'processing':
      default:
        return { icon: Loader2, cls: 'bg-sky-500/10 text-sky-700 dark:text-sky-400 border-sky-500/20' }
    }
  })()

  const Icon = cfg.icon
  return (
    <span className={cn('inline-flex items-center gap-1.5 rounded-full border px-2 py-0.5 text-xs font-medium', cfg.cls)}>
      <Icon className={cn('h-3.5 w-3.5', status === 'processing' ? 'animate-spin motion-reduce:animate-none' : '')} />
      {STATUS_LABEL[status]}
    </span>
  )
}

export default function IngestionMonitorPage() {
  const { openDocument } = useDocumentView()
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [status, setStatus] = useState<StatusFilter>('all')
  const [search, setSearch] = useState('')
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailDocumentId, setDetailDocumentId] = useState<string | null>(null)
  const [acting, setActing] = useState<{ id: string; action: 'cancel' | 'retry' } | null>(null)
  const [dashboardWindowHours, setDashboardWindowHours] = useState<number>(24)

  const { data, isFetching, refetch } = useQuery({
    queryKey: ['ingestion-documents', status],
    queryFn: ({ signal }) =>
      documentApi.list(
        {
          limit: 200,
          status: status === 'all' ? undefined : status,
        },
        { signal }
      ),
    staleTime: 3_000,
    refetchInterval: autoRefresh ? 5_000 : false,
  })

  const ingestionDashboardQuery = useQuery({
    queryKey: ['ingestion-dashboard', dashboardWindowHours],
    queryFn: () => observabilityApi.getIngestionDashboardSummary({ window_hours: dashboardWindowHours }),
    staleTime: 30_000,
    retry: false,
    refetchOnWindowFocus: false,
  })

  const documents = useMemo(() => data?.items || [], [data])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return documents
    return documents.filter((d) => {
      const filename = (d.filename || '').toLowerCase()
      const id = d.id.toLowerCase()

      return filename.includes(q) || id.includes(q)
    })
  }, [documents, search])

  const stats = useMemo(() => {
    let pending = 0
    let processing = 0
    let completed = 0
    let failed = 0
    let quarantined = 0
    let cancelled = 0
    let totalSize = 0

    for (const d of documents) {
      totalSize += d.file_size || 0
      if (d.status === 'pending') pending += 1
      else if (d.status === 'processing') processing += 1
      else if (d.status === 'completed') completed += 1
      else if (d.status === 'failed') failed += 1
      else if (d.status === 'quarantined') quarantined += 1
      else if (d.status === 'cancelled') cancelled += 1
    }

    return { pending, processing, completed, failed, quarantined, cancelled, totalSize }
  }, [documents])

  const dashboard: IngestionDashboardSummaryResponse | null = ingestionDashboardQuery.data ?? null

  const dashboardChartData = useMemo(() => {
    const series = dashboard?.timeseries || {}
    const ts = (series as any)?.ts_ms || []
    const completed = (series as any)?.completed || []
    const failed = (series as any)?.failed || []
    const quarantined = (series as any)?.quarantined || []

    const out = []
    for (let i = 0; i < ts.length; i++) {
      const t = Number(ts[i] || 0)
      out.push({
        t,
        time: formatTs(t),
        completed: Number(completed[i] || 0),
        failed: Number(failed[i] || 0),
        quarantined: Number(quarantined[i] || 0),
      })
    }
    return out
  }, [dashboard?.timeseries])

  const topErrorReasons = useMemo(() => {
    const raw: Record<string, number> = (dashboard?.top_error_reasons || {}) as any
    const entries = Object.entries(raw).sort((a, b) => (b[1] ?? 0) - (a[1] ?? 0))
    return entries.slice(0, 12)
  }, [dashboard?.top_error_reasons])

  const dashboardCompletedCount = useMemo(
    () => dashboardChartData.reduce((acc, row: any) => acc + (Number(row?.completed) || 0), 0),
    [dashboardChartData]
  )

  const dashboardErrorCount = useMemo(
    () => dashboardChartData.reduce((acc, row: any) => acc + (Number(row?.failed) || 0) + (Number(row?.quarantined) || 0), 0),
    [dashboardChartData]
  )

  const handleCancel = async (docId: string) => {
    setActing({ id: docId, action: 'cancel' })
    try {
      await documentApi.cancel(docId)
      toast.success('已取消入库任务')
      await refetch()
    } catch (err: any) {
      toast.error(formatApiError(err, '取消失败'))
    } finally {
      setActing(null)
    }
  }

  const handleRetry = async (docId: string) => {
    setActing({ id: docId, action: 'retry' })
    try {
      await documentApi.retry(docId)
      toast.success('已触发重新入库')
      await refetch()
    } catch (err: any) {
      toast.error(formatApiError(err, '重试失败'))
    } finally {
      setActing(null)
    }
  }

  return (
    <AppFrame
      rightPanel={<DocumentViewerPanel />}
      withDocumentViewerPadding
    >
      <PageScaffold
        title="入库监控中心"
        icon={Search}
        iconColor="text-sky-500 dark:text-sky-400"
        size="full"
        topClassName="px-3 md:px-4 xl:px-5 pb-3"
        description={
          <span className="flex items-center gap-2 text-muted-foreground">
            <span className="inline-flex items-center gap-2 rounded-full border border-emerald-200/70 bg-emerald-50/80 px-2.5 py-1 text-[11px] font-semibold text-emerald-700 dark:border-emerald-500/20 dark:bg-emerald-500/10 dark:text-emerald-300">
              <span className="h-1.5 w-1.5 rounded-full bg-emerald-500 animate-pulse motion-reduce:animate-none" />
              运行正常
            </span>
            <span className="text-muted-foreground/50">·</span>
            <span>实时追踪解析、切块、向量化与索引构建进度。</span>
          </span>
        }
        actions={
          <>
            <Button
              variant="outline"
              className="group gap-2 rounded-full bg-background/60"
              onClick={() => {
                detachPromise(refetch())
                detachPromise(ingestionDashboardQuery.refetch())
              }}
            >
              <RefreshCw className={cn('h-3.5 w-3.5', isFetching ? 'animate-spin motion-reduce:animate-none' : '')} />
              刷新状态
            </Button>
	            <div className="flex items-center gap-3 rounded-full border border-border/60 bg-background/60 px-4 py-1.5 hover:border-primary/20 transition-colors shadow-sm">
	              <span className="text-xs font-bold text-muted-foreground">自动同步</span>
	              <Switch
	                checked={autoRefresh}
                onCheckedChange={setAutoRefresh}
                className="scale-75 data-[state=checked]:bg-sky-500"
              />
            </div>
          </>
        }
        top={
          <div className="mt-4 space-y-3">
            <div className="flex items-center gap-2 px-1 text-[11px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
              <Activity className="h-3.5 w-3.5" />
              实时状态
            </div>
            <div className="grid grid-cols-2 gap-3 xl:grid-cols-5">
              {[
                {
                  label: '等待队列',
                  value: stats.pending,
                  icon: Clock,
                  color: 'text-amber-600 dark:text-amber-400',
                  iconSurface: 'border-amber-200/70 bg-amber-50 dark:border-amber-500/20 dark:bg-amber-500/10',
                  border: 'hover:border-amber-200/80 dark:hover:border-amber-500/25',
                },
                {
                  label: '正在处理',
                  value: stats.processing,
                  icon: Loader2,
                  color: 'text-sky-600 dark:text-sky-400',
                  iconSurface: 'border-sky-200/70 bg-sky-50 dark:border-sky-500/20 dark:bg-sky-500/10',
                  border: 'hover:border-sky-200/80 dark:hover:border-sky-500/25',
                  spin: true,
                },
                {
                  label: '已完成',
                  value: stats.completed,
                  icon: CheckCircle2,
                  color: 'text-emerald-600 dark:text-emerald-400',
                  iconSurface: 'border-emerald-200/70 bg-emerald-50 dark:border-emerald-500/20 dark:bg-emerald-500/10',
                  border: 'hover:border-emerald-200/80 dark:hover:border-emerald-500/25',
                },
                {
                  label: '失败 / 隔离',
                  value: stats.failed + stats.quarantined,
                  icon: AlertCircle,
                  color: 'text-red-600 dark:text-red-400',
                  iconSurface: 'border-red-200/70 bg-red-50 dark:border-red-500/20 dark:bg-red-500/10',
                  border: 'hover:border-red-200/80 dark:hover:border-red-500/25',
                },
                {
                  label: '总存储量',
                  value: formatFileSize(stats.totalSize),
                  icon: HardDrive,
                  color: 'text-indigo-600 dark:text-indigo-400',
                  iconSurface: 'border-indigo-200/70 bg-indigo-50 dark:border-indigo-500/20 dark:bg-indigo-500/10',
                  border: 'hover:border-indigo-200/80 dark:hover:border-indigo-500/25',
                },
              ].map((stat) => (
                <div
                  key={stat.label}
                  className={cn(
                    'group rounded-2xl border border-border/60 bg-card/95 p-4 shadow-soft transition-colors duration-200 motion-reduce:transition-none',
                    stat.border
                  )}
                >
                  <div className="flex items-start justify-between gap-3">
                    <div className="min-w-0 space-y-2">
                      <div className="text-[11px] font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                        {stat.label}
                      </div>
                      <div className={cn('text-3xl font-semibold leading-none ', stat.color)}>{stat.value}</div>
                    </div>
                    <div className={cn('flex h-11 w-11 shrink-0 items-center justify-center rounded-xl border', stat.iconSurface)}>
                      <stat.icon className={cn('h-5 w-5', stat.color, stat.spin && 'animate-spin motion-reduce:animate-none')} />
                    </div>
                  </div>
                </div>
              ))}
            </div>
          </div>
        }
        bodyClassName="px-3 md:px-4 xl:px-5 pb-10 z-10"
      >
        <div className="space-y-5">
          <section className="space-y-4">
            <div className="flex flex-col gap-4 xl:flex-row xl:items-start xl:justify-between">
              <div className="flex items-start gap-3">
                <div className="rounded-xl border border-sky-100 bg-sky-50 p-2 dark:border-sky-500/20 dark:bg-sky-500/10">
                  <BarChart3 className="h-4 w-4 text-sky-600 dark:text-sky-400" />
                </div>
                <div className="min-w-0">
                  <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">历史窗口</div>
                  <div className="mt-1 flex flex-wrap items-center gap-2">
                    <div className="text-sm font-semibold text-foreground">吞吐与错误画像</div>
                  </div>
                  {/* 图表与错误画像直接铺在主画布上，避免额外外层卡片 */}
                  <div className="mt-1 text-xs text-muted-foreground">时间窗口聚合，不直接代表当前实时队列瞬时值。</div>
                </div>
              </div>

              <div className="flex items-center gap-2 self-start">
                <Select
                  value={String(dashboardWindowHours)}
                  onValueChange={(v) => setDashboardWindowHours(Number.parseInt(v, 10))}
                >
                  <SelectTrigger className="h-9 w-[148px] rounded-xl border-border/60 bg-background/70 shadow-none">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="24">最近 24 小时</SelectItem>
                    <SelectItem value="72">最近 3 天</SelectItem>
                    <SelectItem value="168">最近 7 天</SelectItem>
                    <SelectItem value="720">最近 30 天</SelectItem>
                  </SelectContent>
                </Select>
                <Button
                  size="sm"
                  variant="outline"
                  className="gap-2 rounded-xl bg-background/70"
                  disabled={ingestionDashboardQuery.isFetching}
                  onClick={() => detachPromise(ingestionDashboardQuery.refetch())}
                >
                  <RefreshCw className={cn('w-4 h-4', ingestionDashboardQuery.isFetching && 'animate-spin motion-reduce:animate-none')} />
                  刷新
                </Button>
              </div>
            </div>

            {dashboard ? (
              <div className="space-y-4">
                <div className="grid gap-x-6 gap-y-3 px-1 sm:grid-cols-2 xl:grid-cols-4">
                  <div className="space-y-1 border-l-2 border-border/50 pl-3">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">窗口内新建</div>
                    <div className="text-2xl font-semibold text-foreground">{dashboard.created_count ?? 0}</div>
                  </div>
                  <div className="space-y-1 border-l-2 border-emerald-200/80 pl-3 dark:border-emerald-500/20">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">窗口内完成</div>
                    <div className="text-2xl font-semibold text-emerald-600 dark:text-emerald-400">{dashboardCompletedCount}</div>
                  </div>
                  <div className="space-y-1 border-l-2 border-red-200/80 pl-3 dark:border-red-500/20">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">窗口内失败 / 隔离</div>
                    <div className="text-2xl font-semibold text-red-600 dark:text-red-400">{dashboardErrorCount}</div>
                  </div>
                  <div className="space-y-1 border-l-2 border-sky-200/80 pl-3 dark:border-sky-500/20">
                    <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">平均完成耗时</div>
                    <div className="text-2xl font-semibold text-foreground">
                      {dashboard.avg_completed_latency_sec == null ? '-' : `${(Number(dashboard.avg_completed_latency_sec || 0) / 60).toFixed(1)}m`}
                    </div>
                  </div>
                </div>

                <div className="grid gap-4 xl:grid-cols-[minmax(0,1.9fr)_minmax(20rem,1fr)]">
                  <div className="rounded-2xl border border-border/60 bg-card p-4 shadow-soft">
                    <div className="mb-3 text-xs font-bold text-muted-foreground">吞吐（按时间桶）</div>
                    <div className="h-[220px]">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={dashboardChartData}>
                          <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                          <XAxis dataKey="time" fontSize={10} tickMargin={8} />
                          <YAxis fontSize={10} tickMargin={8} />
                          <Tooltip />
                          <Bar dataKey="completed" stackId="a" fill="hsl(var(--chart-2))" />
                          <Bar dataKey="failed" stackId="a" fill="hsl(var(--chart-6))" />
                          <Bar dataKey="quarantined" stackId="a" fill="hsl(var(--chart-4))" />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  </div>

                  <div className="rounded-2xl border border-border/60 bg-card p-4 shadow-soft">
                    <div className="mb-3 text-xs font-bold text-muted-foreground">错误画像（Top）</div>
                    {topErrorReasons.length ? (
                      <div className="space-y-2">
                        {topErrorReasons.map(([reason, count]) => (
                          <div key={reason} className="flex items-center justify-between gap-3">
                            <div className="min-w-0 text-xs font-mono text-foreground truncate">{reason}</div>
                            <div className="text-xs font-bold text-muted-foreground tabular-nums">{count}</div>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="flex h-[220px] flex-col items-center justify-center rounded-xl border border-dashed border-emerald-200/70 bg-emerald-50/60 px-5 text-center dark:border-emerald-500/20 dark:bg-emerald-500/10">
                        <div className="mb-3 flex h-10 w-10 items-center justify-center rounded-full bg-emerald-100 text-emerald-600 dark:bg-emerald-500/15 dark:text-emerald-300">
                          <ShieldCheck className="h-5 w-5" />
                        </div>
                        <div className="text-sm font-semibold text-foreground">最近窗口内未发现错误任务</div>
                        <div className="mt-1 text-xs leading-5 text-muted-foreground">
                          当前错误画像为空，可以切换时间窗口或刷新统计查看历史波动。
                        </div>
                      </div>
                    )}
                  </div>
                </div>
              </div>
            ) : (
              <div className="rounded-2xl border border-dashed border-border/60 bg-card/70 px-6 py-10 shadow-soft">
                <div className="flex min-h-[180px] items-center justify-center text-center">
                  <div className="max-w-sm space-y-1.5">
                    <div className="text-sm font-semibold text-foreground">统计面板暂不可用</div>
                    <div className="text-xs leading-5 text-muted-foreground">
                      {(() => {
                        if (ingestionDashboardQuery.isFetching) {
                          return '加载中...'
                        }
                        if (ingestionDashboardQuery.error) {
                          return formatApiError(ingestionDashboardQuery.error as any, '无权限或暂不可用')
                        }
                        return '尚无数据'
                      })()}
                    </div>
                  </div>
                </div>
              </div>
            )}
          </section>

          <div className="overflow-hidden rounded-2xl border border-border/60 bg-card shadow-soft">
            <div className="border-b border-border/60 px-5 py-4">
              <div className="flex flex-col gap-4 xl:flex-row xl:items-center xl:justify-between">
                <div className="min-w-0">
                  <div className="flex items-center gap-3">
                    <div className="flex h-10 w-10 items-center justify-center rounded-xl border border-border/60 bg-background/70">
                      <LayoutList className="h-4 w-4 text-foreground" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-foreground">任务明细</div>
                      <div className="flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                        <span>文件维度的实时进度、异常和重试动作</span>
                        <span className="text-muted-foreground/40">·</span>
                        <span>{filtered.length} / {documents.length} 条</span>
                      </div>
                    </div>
                  </div>
                </div>

                <div className="flex w-full flex-col gap-2 lg:w-auto lg:flex-row lg:items-center">
                  <SearchInput
                    value={search}
                    onValueChange={setSearch}
                    placeholder="搜索任务 ID 或文件名"
                    containerClassName="w-full lg:min-w-[21rem]"
                    inputClassName="h-10 rounded-full border-border/60 bg-background/70 shadow-none"
                  />

                  <Select value={status} onValueChange={(value) => setStatus(value as StatusFilter)}>
                    <SelectTrigger className="h-10 w-full rounded-full border-border/60 bg-background/70 shadow-none lg:w-[11rem]">
                      <SelectValue placeholder="全部状态" />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value="all">全部状态</SelectItem>
                      <SelectItem value="pending">等待中</SelectItem>
                      <SelectItem value="processing">处理中</SelectItem>
                      <SelectItem value="completed">已完成</SelectItem>
                      <SelectItem value="failed">失败</SelectItem>
                      <SelectItem value="quarantined">已隔离</SelectItem>
                      <SelectItem value="cancelled">已取消</SelectItem>
                    </SelectContent>
                  </Select>
                </div>
              </div>
            </div>

            <div className="space-y-3 p-4">
              {filtered.map((doc) => {
                const isActiveStatus = doc.status === 'processing' || doc.status === 'pending'
                const canRetry = doc.status === 'failed' || doc.status === 'cancelled' || doc.status === 'quarantined'
                const activeProgressShellClass = doc.status === 'pending'
                  ? 'border-amber-200/60 bg-amber-50/80 dark:border-amber-500/20 dark:bg-amber-500/10'
                  : 'border-sky-200/60 bg-sky-50/80 dark:border-sky-500/20 dark:bg-sky-500/10'
                const activeProgressTextClass = doc.status === 'pending'
                  ? 'text-amber-700 dark:text-amber-300'
                  : 'text-sky-700 dark:text-sky-300'
                const activeProgressBarClass = doc.status === 'pending' ? 'bg-amber-500' : 'bg-sky-500'

                return (
                  <div
                    key={doc.id}
	                  className={cn(
	                    'group relative w-full overflow-hidden rounded-xl border transition-colors transition-shadow duration-200 motion-reduce:transition-none',
	                    'bg-card border-border hover:border-primary/30 hover:shadow-strong',
	                    'focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2 focus-within:ring-offset-background'
	                  )}
	                >
                {/* Progress Background Mesh for Processing */}
                {doc.status === 'processing' && (
                  <div className="absolute inset-0 z-0 opacity-[0.03] dark:opacity-[0.05] pointer-events-none bg-[url('/noise.svg')] mix-blend-multiply dark:mix-blend-overlay" />
                )}

                {/* Status Bar Accent */}
                <div className={cn("absolute left-0 top-0 bottom-0 w-1",
                  (() => {
    if (doc.status === 'processing') {
        return "bg-sky-500";
    }
    else if (doc.status === 'completed') {
            return "bg-emerald-500";
        }
        else if (doc.status === 'failed') {
                return "bg-red-500";
            }
            else if (doc.status === 'quarantined') {
                    return "bg-amber-500";
                }
                else {
                    return "bg-border";
                }
})()
                )} />

                <div className="absolute right-5 top-4 z-20 flex items-center gap-1 opacity-0 translate-x-2 transition-opacity transition-transform duration-200 ease-out motion-reduce:transition-none group-hover:translate-x-0 group-hover:opacity-100">
                  <Button
                    size="sm"
                    variant="ghost"
                    className="h-8 px-3 text-xs text-muted-foreground hover:text-primary rounded-lg"
                    onClick={(e) => {
                      e.stopPropagation()
                      openDocument(doc.id)
                    }}
                  >
                    查看详情
                  </Button>

                  {isActiveStatus && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-8 px-3 text-xs text-red-500 dark:text-red-400 hover:text-red-600 dark:hover:text-red-300 hover:bg-red-50 dark:hover:bg-red-500/10 rounded-lg"
                      disabled={acting?.id === doc.id}
                      onClick={(e) => {
                        e.stopPropagation()
                        handleCancel(doc.id)
                      }}
                    >
                      {acting?.id === doc.id && acting.action === 'cancel' ? <Loader2 className="w-3 h-3 animate-spin motion-reduce:animate-none" /> : '终止'}
                    </Button>
                  )}

                  {canRetry && (
                    <Button
                      size="sm"
                      variant="ghost"
                      className="h-8 px-3 text-xs text-primary hover:text-primary/90 rounded-lg"
                      disabled={acting?.id === doc.id}
                      onClick={(e) => {
                        e.stopPropagation()
                        handleRetry(doc.id)
                      }}
                    >
                      {acting?.id === doc.id && acting.action === 'retry' ? <Loader2 className="w-3 h-3 animate-spin motion-reduce:animate-none" /> : '重试'}
                    </Button>
                  )}
                </div>

                <div className="relative z-10 flex items-center justify-between gap-6 p-5 pl-6">
                  <button
                    type="button"
                    className="min-w-0 flex-1 rounded-lg pr-10 text-left focus-ring"
                    aria-label={`查看入库详情：${doc.filename}`}
                    onClick={() => {
                      setDetailDocumentId(doc.id)
                      setDetailOpen(true)
                    }}
                  >
                    <div className="flex items-center gap-3 mb-2">
                      <StatusPill status={doc.status} />
                      <span className="font-mono text-[11px] text-muted-foreground">ID: {doc.id.slice(0, 8)}</span>
                    </div>

                    <div className="flex items-center gap-3">
                      <p className="font-bold text-base text-foreground truncate group-hover:text-sky-600 dark:group-hover:text-sky-400 transition-colors ">{doc.filename}</p>
                    </div>

                    <div className="mt-3 flex flex-wrap items-center gap-x-6 gap-y-1 text-xs font-medium text-muted-foreground">
                      <div className="flex items-center gap-1.5 bg-muted/40 px-2 py-0.5 rounded-md border border-border/60">
                        <Clock className="w-3 h-3 text-muted-foreground" />
                        {formatDate(doc.updated_at)}
                      </div>
                      <div className="flex items-center gap-1.5">
                        <div className="w-1 h-1 rounded-full bg-muted-foreground/30" />
                        {formatFileSize(doc.file_size)}
                      </div>
                      <div className="flex items-center gap-1.5">
                        <div className="w-1 h-1 rounded-full bg-muted-foreground/30" />
                        {doc.chunk_count ?? 0} 切片
                      </div>
                    </div>
                  </button>

                  {isActiveStatus ? (
                    <div className={cn('w-full max-w-[190px] shrink-0 rounded-xl border px-3 py-3', activeProgressShellClass)}>
                      <div className="flex items-end justify-between gap-3">
                        <div className="space-y-1">
                          <div className={cn('text-[11px] font-bold uppercase tracking-[0.16em]', activeProgressTextClass)}>
                            入库进度
                          </div>
                          <div className={cn('text-base font-semibold leading-none', activeProgressTextClass)}>
                            {doc.processing_progress || 0}%
                          </div>
                        </div>
                        <div className={cn('text-[11px] font-semibold uppercase tracking-[0.14em]', activeProgressTextClass)}>
                          {isActiveStatus && doc.current_stage ? doc.current_stage : 'QUEUED'}
                        </div>
                      </div>

                      <div className="mt-3 h-1.5 w-full overflow-hidden rounded-full bg-background/70 dark:bg-background/40">
                        <div
                          className={cn('h-full w-full origin-left rounded-full transition-transform duration-200 ease-out motion-reduce:transition-none', activeProgressBarClass)}
                          style={{
                            transform: `scaleX(${Math.max(0, Math.min(100, doc.processing_progress || 0)) / 100})`,
                          }}
                        />
                      </div>
                    </div>
                  ) : null}
                </div>

                {/* Error Message Panel */}
                {(doc.status === 'failed' || doc.status === 'quarantined') && doc.error_message && (
                  <div className={cn(
                    "mx-6 mb-5 mt-0 rounded-xl border p-4 flex items-start gap-4",
                    doc.status === 'quarantined'
                      ? "border-amber-200 dark:border-amber-500/30 bg-amber-50/50 dark:bg-amber-500/10"
                      : "border-red-200 dark:border-red-500/30 bg-red-50/50 dark:bg-red-500/10"
                  )}>
                    <div className={cn(
                      "p-2 rounded-full",
                      doc.status === 'quarantined' ? "bg-amber-100 dark:bg-amber-900/30" : "bg-red-100 dark:bg-red-900/30"
                    )}>
                      <AlertCircle className={cn(
                        "w-4 h-4 flex-shrink-0",
                        doc.status === 'quarantined' ? "text-amber-600 dark:text-amber-300" : "text-red-500 dark:text-red-400"
                      )} />
                    </div>
                    <div className="space-y-1">
                      <div className={cn(
                        "text-xs font-bold uppercase ",
                        doc.status === 'quarantined' ? "text-amber-700 dark:text-amber-300" : "text-red-600 dark:text-red-400"
                      )}>
                        {doc.status === 'quarantined' ? 'Quarantined' : 'Error Log'}
                      </div>
                      <div className={cn(
                        "text-xs font-mono break-all leading-relaxed",
                        doc.status === 'quarantined' ? "text-amber-700/80 dark:text-amber-300/80" : "text-red-600/80 dark:text-red-400/80"
                      )}>
                        {doc.error_message}
                      </div>
                    </div>
                  </div>
                )}
              </div>
                )
              })}

              {!filtered.length && (
                <div className="flex flex-col items-center justify-center rounded-2xl border border-dashed border-border/60 bg-background/30 px-6 py-16 text-center">
                  <div className="mb-4 flex h-14 w-14 items-center justify-center rounded-full bg-muted/50">
                    <Search className="h-6 w-6 text-muted-foreground/60" />
                  </div>
                  <p className="text-sm font-semibold text-foreground">没有找到匹配的入库任务</p>
                  <p className="mt-1 max-w-md text-xs leading-5 text-muted-foreground">
                    可以尝试输入任务 ID 前缀、文件名关键词，或切换状态筛选查看历史处理记录。
                  </p>
                </div>
              )}
            </div>
          </div>
        </div>
      </PageScaffold>
      <IngestionDetailDialog
        open={detailOpen}
        onOpenChange={(next) => {
          setDetailOpen(next)
          if (!next) setDetailDocumentId(null)
        }}
        documentId={detailDocumentId}
      />
    </AppFrame>
  )
}
