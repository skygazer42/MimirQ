'use client'

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  AlertCircle,
  CheckCircle2,
  Clock,
  Loader2,
  RefreshCw,
  Search,
} from 'lucide-react'
import { toast } from 'sonner'

import { Navbar } from '@/components/navbar'
import { PageHeader } from '@/components/ui/page-header'
import { DocumentViewerPanel } from '@/components/document-viewer-panel'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { documentApi } from '@/lib/api-client'
import { cn, formatDate, formatFileSize } from '@/lib/utils'
import type { Document } from '@/types'
import { useDocumentView } from '@/store/document-view'
import { IngestionDetailDialog } from '@/components/ingestion/ingestion-detail-dialog'
import { formatApiError } from '@/lib/api-errors'

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

function StatusPill({ status }: { status: Document['status'] }) {
  const cfg = (() => {
    switch (status) {
      case 'completed':
        return { icon: CheckCircle2, cls: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-400 border-emerald-500/20' }
      case 'failed':
        return { icon: AlertCircle, cls: 'bg-red-500/10 text-red-700 dark:text-red-400 border-red-500/20' }
      case 'quarantined':
        return { icon: AlertCircle, cls: 'bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/20' }
      case 'cancelled':
        return { icon: AlertCircle, cls: 'bg-slate-500/10 text-slate-700 dark:text-slate-300 border-slate-500/20' }
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
      <Icon className={cn('h-3.5 w-3.5', status === 'processing' ? 'animate-spin' : '')} />
      {STATUS_LABEL[status]}
    </span>
  )
}

export default function IngestionMonitorPage() {
  const { isOpen, openDocument } = useDocumentView()
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [status, setStatus] = useState<StatusFilter>('all')
  const [search, setSearch] = useState('')
  const [detailOpen, setDetailOpen] = useState(false)
  const [detailDocumentId, setDetailDocumentId] = useState<string | null>(null)
  const [acting, setActing] = useState<{ id: string; action: 'cancel' | 'retry' } | null>(null)

  const { data, isFetching, refetch } = useQuery({
    queryKey: ['ingestion-documents', status],
    queryFn: async () => {
      const res = await documentApi.list({
        limit: 200,
        status: status === 'all' ? undefined : status,
      })
      return res
    },
    staleTime: 3_000,
    refetchInterval: autoRefresh ? 5_000 : false,
  })

  const documents = useMemo(() => data?.items || [], [data])

  const filtered = useMemo(() => {
    const q = search.trim().toLowerCase()
    if (!q) return documents
    return documents.filter((d) => (d.filename || '').toLowerCase().includes(q))
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
    <div className="flex min-h-screen overflow-hidden bg-slate-50 dark:bg-slate-950 font-sans selection:bg-slate-200 dark:selection:bg-slate-800 selection:text-slate-900 dark:selection:text-slate-100">
      {/* Premium Texture Background - Dark mode reduced opacity */}
      <div className="fixed inset-0 z-0 opacity-40 dark:opacity-20 pointer-events-none" style={{ backgroundImage: 'radial-gradient(#cbd5e1 1px, transparent 1px)', backgroundSize: '32px 32px' }} />

      {/* Soft Ambient Light - Dark mode darker/adjusted */}
      <div className="fixed top-0 left-1/4 w-[800px] h-[800px] bg-sky-200/20 dark:bg-sky-900/10 rounded-full blur-[120px] pointer-events-none mix-blend-multiply dark:mix-blend-normal" />
      <div className="fixed bottom-0 right-1/4 w-[600px] h-[600px] bg-indigo-200/20 dark:bg-indigo-900/10 rounded-full blur-[100px] pointer-events-none mix-blend-multiply dark:mix-blend-normal" />

      <Navbar />

      <main
        className={cn(
          'relative z-10 flex-1 flex flex-col overflow-hidden transition-all duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]',
          isOpen ? 'mr-0 md:mr-[40vw] xl:mr-[40vw] lg:mr-[500px]' : 'mr-0'
        )}
      >
        <div className="sticky top-0 z-20 backdrop-blur-md bg-white/70 dark:bg-slate-950/70 border-b border-slate-200/50 dark:border-slate-800/50 transition-all duration-300">
          <PageHeader
            title="入库监控中心"
            icon={Search}
            iconColor="text-sky-500 dark:text-sky-400"
            className="!pt-6 !pb-6"
            description={
              <span className="flex items-center gap-2 text-slate-500 dark:text-slate-400">
                <span className="font-bold text-slate-700 dark:text-slate-200">SYSTEM_STATUS</span>
                <span className="px-1.5 py-0.5 rounded text-[10px] font-bold bg-emerald-50 dark:bg-emerald-500/10 text-emerald-600 dark:text-emerald-400 border border-emerald-100 dark:border-emerald-500/20 uppercase tracking-wider">Online</span>
                <span className="text-slate-300 dark:text-slate-600">|</span>
                实时追踪解析、切块、向量化与索引构建进度。
              </span>
            }
          >
            <div className="flex items-center gap-3">
              <Button
                variant="outline"
                className="gap-2 bg-white/50 dark:bg-slate-900/50 border-slate-200 dark:border-slate-800 hover:bg-white dark:hover:bg-slate-800 hover:border-slate-300 dark:hover:border-slate-700 text-slate-600 dark:text-slate-300 rounded-full transition-all duration-300 shadow-sm"
                onClick={() => refetch()}
              >
                <RefreshCw className={cn('h-3.5 w-3.5 transition-transform group-hover:rotate-180', isFetching ? 'animate-spin' : '')} />
                刷新状态
              </Button>
              <div className="flex items-center gap-3 rounded-full border border-slate-200 dark:border-slate-800 bg-white/50 dark:bg-slate-900/50 backdrop-blur-md px-4 py-1.5 hover:border-slate-300 dark:hover:border-slate-700 transition-colors shadow-sm">
                <span className="text-xs font-bold text-slate-500 dark:text-slate-400">自动同步</span>
                <Switch
                  checked={autoRefresh}
                  onCheckedChange={setAutoRefresh}
                  className="scale-75 data-[state=checked]:bg-sky-500"
                />
              </div>
            </div>
          </PageHeader>
        </div>

        <div className="px-8 pb-4 grid grid-cols-2 lg:grid-cols-5 gap-4 mt-4">
          {[
            { label: '等待队列', value: stats.pending, icon: Clock, color: 'text-amber-600 dark:text-amber-400', bg: 'bg-amber-50 dark:bg-amber-500/10', border: 'group-hover:border-amber-200 dark:group-hover:border-amber-800' },
            { label: '正在处理', value: stats.processing, icon: Loader2, color: 'text-sky-600 dark:text-sky-400', bg: 'bg-sky-50 dark:bg-sky-500/10', border: 'group-hover:border-sky-200 dark:group-hover:border-sky-800', spin: true },
            { label: '已完成', value: stats.completed, icon: CheckCircle2, color: 'text-emerald-600 dark:text-emerald-400', bg: 'bg-emerald-50 dark:bg-emerald-500/10', border: 'group-hover:border-emerald-200 dark:group-hover:border-emerald-800' },
            { label: '失败/隔离', value: stats.failed + stats.quarantined, icon: AlertCircle, color: 'text-red-600 dark:text-red-400', bg: 'bg-red-50 dark:bg-red-500/10', border: 'group-hover:border-red-200 dark:group-hover:border-red-800' },
            { label: '总存储量', value: formatFileSize(stats.totalSize), icon: Search, color: 'text-indigo-600 dark:text-indigo-400', bg: 'bg-indigo-50 dark:bg-indigo-500/10', border: 'group-hover:border-indigo-200 dark:group-hover:border-indigo-800' },
          ].map((stat, idx) => (
            <div key={idx} className={cn(
              "group relative overflow-hidden rounded-2xl bg-white dark:bg-slate-900 border border-slate-100 dark:border-slate-800 shadow-[0_2px_20px_rgba(0,0,0,0.04)] dark:shadow-none hover:shadow-[0_8px_30px_rgba(0,0,0,0.08)] transition-all duration-300 hover:-translate-y-1",
              stat.border
            )}>
              <div className="p-5 flex flex-col justify-between h-full relative z-10">
                <div className="flex items-center justify-between mb-4">
                  <div className={cn("p-2 rounded-lg transition-colors", stat.bg)}>
                    <stat.icon className={cn("w-5 h-5", stat.color, stat.spin && "animate-spin")} />
                  </div>
                  <div className="text-[10px] font-bold uppercase tracking-widest text-slate-400 dark:text-slate-500">{stat.label}</div>
                </div>
                <div className="flex items-baseline gap-1">
                  <span className={cn("text-3xl font-black tracking-tight", stat.color)}>{stat.value}</span>
                  {idx === 4 && <span className="text-xs font-medium text-slate-400 dark:text-slate-500">Total</span>}
                </div>
              </div>
            </div>
          ))}
        </div>

        <div className="px-8 pb-6 flex-shrink-0 z-10 sticky top-[88px] my-2">
          <div className="flex flex-col md:flex-row md:items-center gap-0 bg-white/80 dark:bg-slate-900/80 backdrop-blur-xl border border-slate-200 dark:border-slate-800 shadow-lg shadow-slate-200/50 dark:shadow-none rounded-full p-1.5 transition-all duration-300 hover:shadow-xl hover:shadow-sky-100 dark:hover:shadow-none hover:border-sky-100 dark:hover:border-slate-700 max-w-4xl mx-auto md:mx-0">
            <div className="relative flex-1 group pl-2">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-slate-400 dark:text-slate-500 group-hover:text-sky-500 dark:group-hover:text-sky-400 transition-colors" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="搜索任务ID或文件名..."
                className="pl-9 bg-transparent border-0 focus-visible:ring-0 text-slate-700 dark:text-slate-200 placeholder:text-slate-400 dark:placeholder:text-slate-600 h-10 rounded-full"
              />
            </div>

            <div className="w-px h-6 bg-slate-200 dark:bg-slate-800 hidden md:block mx-2" />

            <Select value={status} onValueChange={(v) => setStatus(v as StatusFilter)}>
              <SelectTrigger className="w-full md:w-48 bg-transparent border-0 focus:ring-0 h-10 text-slate-600 dark:text-slate-400 hover:text-slate-900 dark:hover:text-slate-200 rounded-full hover:bg-slate-50 dark:hover:bg-slate-800 transition-colors">
                <SelectValue placeholder="筛选状态" />
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

        <section className="flex-1 overflow-y-auto px-8 pb-10 z-10 custom-scrollbar">
          <div className="space-y-3">
            {filtered.map((doc) => (
              <div
                key={doc.id}
                role="button"
                tabIndex={0}
                onClick={() => {
                  setDetailDocumentId(doc.id)
                  setDetailOpen(true)
                }}
                className={cn(
                  'group w-full text-left rounded-xl border transition-all duration-300 relative overflow-hidden',
                  'bg-white dark:bg-slate-900 border-slate-100 dark:border-slate-800 hover:border-sky-200 dark:hover:border-sky-800 hover:shadow-[0_8px_30px_rgba(0,0,0,0.04)] hover:-translate-y-0.5'
                )}
              >
                {/* Progress Background Mesh for Processing */}
                {doc.status === 'processing' && (
                  <div className="absolute inset-0 z-0 opacity-[0.03] dark:opacity-[0.05] pointer-events-none bg-[url('https://grainy-gradients.vercel.app/noise.svg')] mix-blend-multiply dark:mix-blend-overlay" />
                )}

                {/* Status Bar Accent */}
                <div className={cn("absolute left-0 top-0 bottom-0 w-1",
                  doc.status === 'processing' ? "bg-sky-500" :
                    doc.status === 'completed' ? "bg-emerald-500" :
                      doc.status === 'failed' ? "bg-red-500" :
                        doc.status === 'quarantined' ? "bg-amber-500" :
                          "bg-slate-200 dark:bg-slate-700"
                )} />

                <div className="flex items-center justify-between gap-6 p-5 relative z-10 pl-6">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-3 mb-2">
                      <StatusPill status={doc.status} />
                      <span className="font-mono text-[10px] text-slate-400 dark:text-slate-500">ID: {doc.id.slice(0, 8)}</span>
                    </div>

                    <div className="flex items-center gap-3">
                      <p className="font-bold text-base text-slate-800 dark:text-slate-100 truncate group-hover:text-sky-600 dark:group-hover:text-sky-400 transition-colors tracking-tight">{doc.filename}</p>
                    </div>

                    <div className="mt-3 text-xs text-slate-500 dark:text-slate-400 flex flex-wrap gap-x-6 gap-y-1 font-medium items-center">
                      <div className="flex items-center gap-1.5 bg-slate-50 dark:bg-slate-800 px-2 py-0.5 rounded-md border border-slate-100 dark:border-slate-700">
                        <Clock className="w-3 h-3 text-slate-400 dark:text-slate-500" />
                        {formatDate(doc.updated_at)}
                      </div>
                      <div className="flex items-center gap-1.5">
                        <div className="w-1 h-1 rounded-full bg-slate-300 dark:bg-slate-600" />
                        {formatFileSize(doc.file_size)}
                      </div>
                      <div className="flex items-center gap-1.5">
                        <div className="w-1 h-1 rounded-full bg-slate-300 dark:bg-slate-600" />
                        {doc.chunk_count ?? 0} 切片
                      </div>
                      {doc.current_stage && (
                        <div className="flex items-center gap-1.5 text-sky-600 dark:text-sky-400 font-bold bg-sky-50 dark:bg-sky-500/10 px-2 py-0.5 rounded-full border border-sky-100 dark:border-sky-500/20 text-[10px] uppercase tracking-wider">
                          <div className="w-1.5 h-1.5 rounded-full bg-sky-500 animate-pulse" />
                          {doc.current_stage}
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Actions & Progress Area */}
                  <div className="flex flex-col items-end gap-3 min-w-[140px]">

                    <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-all duration-300 translate-x-2 group-hover:translate-x-0">
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-8 px-3 text-xs text-slate-500 dark:text-slate-400 hover:bg-slate-50 dark:hover:bg-slate-800 hover:text-sky-600 dark:hover:text-sky-400 rounded-lg"
                        onClick={(e) => {
                          e.stopPropagation()
                          openDocument(doc.id)
                        }}
                      >
                        查看详情
                      </Button>

                      {(doc.status === 'processing' || doc.status === 'pending') && (
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
                          {acting?.id === doc.id && acting.action === 'cancel' ? <Loader2 className="w-3 h-3 animate-spin" /> : '终止'}
                        </Button>
                      )}

                      {(doc.status === 'failed' || doc.status === 'cancelled' || doc.status === 'quarantined') && (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-8 px-3 text-xs text-sky-600 dark:text-sky-400 hover:text-sky-700 dark:hover:text-sky-300 hover:bg-sky-50 dark:hover:bg-sky-500/10 rounded-lg"
                          disabled={acting?.id === doc.id}
                          onClick={(e) => {
                            e.stopPropagation()
                            handleRetry(doc.id)
                          }}
                        >
                          {acting?.id === doc.id && acting.action === 'retry' ? <Loader2 className="w-3 h-3 animate-spin" /> : '重试'}
                        </Button>
                      )}
                    </div>

                    {/* Progress Bar */}
                    <div className="w-full max-w-[140px] space-y-1.5">
                      <div className="flex items-center justify-between text-[10px] font-bold text-slate-400 dark:text-slate-500 uppercase tracking-wider">
                        <span>Progress</span>
                        <span className={cn(doc.status === 'processing' ? "text-sky-600 dark:text-sky-400" : "text-slate-400")}>{doc.processing_progress || 0}%</span>
                      </div>
                      <div className="h-1.5 w-full rounded-full bg-slate-100 dark:bg-slate-800 overflow-hidden">
                        <div
                          className={cn(
                            "h-full transition-all duration-500 relative rounded-full",
                            doc.status === 'failed' ? "bg-red-400" :
                              doc.status === 'quarantined' ? "bg-amber-400" :
                              doc.status === 'completed' ? "bg-emerald-400" :
                                "bg-sky-500"
                          )}
                          style={{ width: `${Math.max(0, Math.min(100, doc.processing_progress || 0))}%` }}
                        >
                          {doc.status === 'processing' && <div className="absolute inset-0 bg-white/30 animate-pulse" />}
                        </div>
                      </div>
                    </div>
                  </div>
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
                        "text-xs font-bold uppercase tracking-wider",
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
            ))}

            {!filtered.length && (
              <div className="flex flex-col items-center justify-center py-20 text-center">
                <div className="w-20 h-20 rounded-full bg-slate-50 dark:bg-slate-900 flex items-center justify-center mb-4">
                  <Search className="w-8 h-8 text-slate-300 dark:text-slate-600" />
                </div>
                <p className="text-slate-500 dark:text-slate-400 font-medium">没有找到相关的入库任务</p>
              </div>
            )}
          </div>
        </section>
      </main>

      <DocumentViewerPanel />
      <IngestionDetailDialog
        open={detailOpen}
        onOpenChange={(next) => {
          setDetailOpen(next)
          if (!next) setDetailDocumentId(null)
        }}
        documentId={detailDocumentId}
      />
    </div>
  )
}
