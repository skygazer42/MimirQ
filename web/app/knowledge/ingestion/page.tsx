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
  cancelled: '已取消',
}

function StatusPill({ status }: { status: Document['status'] }) {
  const cfg = (() => {
    switch (status) {
      case 'completed':
        return { icon: CheckCircle2, cls: 'bg-emerald-500/10 text-emerald-600 border-emerald-500/20' }
      case 'failed':
        return { icon: AlertCircle, cls: 'bg-red-500/10 text-red-600 border-red-500/20' }
      case 'cancelled':
        return { icon: AlertCircle, cls: 'bg-slate-500/10 text-slate-600 border-slate-500/20' }
      case 'pending':
        return { icon: Clock, cls: 'bg-sky-500/10 text-sky-600 border-sky-500/20' }
      case 'processing':
      default:
        return { icon: Loader2, cls: 'bg-sky-500/10 text-sky-600 border-sky-500/20' }
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

  const documents = data?.items || []

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
    let cancelled = 0
    let totalSize = 0

    for (const d of documents) {
      totalSize += d.file_size || 0
      if (d.status === 'pending') pending += 1
      else if (d.status === 'processing') processing += 1
      else if (d.status === 'completed') completed += 1
      else if (d.status === 'failed') failed += 1
      else if (d.status === 'cancelled') cancelled += 1
    }

    return { pending, processing, completed, failed, cancelled, totalSize }
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
    <div className="flex min-h-screen overflow-hidden bg-background font-sans selection:bg-primary/20 selection:text-primary">
      {/* Ambient Background */}
      <div className="fixed inset-0 z-0 pointer-events-none">
        <div className="absolute top-[-20%] right-[-10%] w-[800px] h-[800px] bg-primary/5 rounded-full blur-[120px] animate-pulse-subtle" />
        <div className="absolute bottom-[-10%] left-[-20%] w-[600px] h-[600px] bg-purple-500/5 rounded-full blur-[120px] animate-pulse-subtle" style={{ animationDelay: '2s' }} />
      </div>

      <Navbar />

      <main
        className={cn(
          'relative z-10 flex-1 flex flex-col overflow-hidden transition-all duration-300 ease-[cubic-bezier(0.32,0.72,0,1)]',
          isOpen ? 'mr-0 md:mr-[40vw] xl:mr-[40vw] lg:mr-[500px]' : 'mr-0'
        )}
      >
        <header className="px-8 pt-8 pb-6 flex-shrink-0">
          <div className="flex items-start justify-between gap-4">
            <div>
              <h1 className="text-3xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-primary to-blue-400 tracking-tight flex items-center gap-3">
                <Search className="w-8 h-8 text-primary animate-pulse-subtle" />
                入库监控中心
              </h1>
              <p className="text-sm text-muted-foreground mt-2 max-w-2xl">
                SYSTEM_STATUS: <span className="text-primary">ONLINE</span> // 实时追踪解析、切块、向量化与索引构建进度。
              </p>
            </div>

            <div className="flex items-center gap-3">
              <Button
                variant="outline"
                className="gap-2 border-primary/20 hover:bg-primary/10 hover:text-primary transition-all duration-300 group"
                onClick={() => refetch()}
              >
                <RefreshCw className={cn('h-4 w-4 transition-transform group-hover:rotate-180', isFetching ? 'animate-spin' : '')} />
                刷新状态
              </Button>
              <div className="flex items-center gap-3 rounded-full border border-white/10 bg-white/5 backdrop-blur-md px-4 py-2 hover:border-primary/30 transition-colors">
                <span className="text-xs font-medium text-muted-foreground">自动同步</span>
                <Switch
                  checked={autoRefresh}
                  onCheckedChange={setAutoRefresh}
                  className="data-[state=checked]:bg-primary"
                />
              </div>
            </div>
          </div>

          <div className="mt-8 grid grid-cols-2 md:grid-cols-5 gap-4">
            {[
              { label: '等待队列', value: stats.pending, color: 'text-primary', border: 'border-primary/20', bg: 'from-primary/5 to-transparent' },
              { label: '正在处理', value: stats.processing, color: 'text-blue-400', border: 'border-blue-500/20', bg: 'from-blue-500/5 to-transparent' },
              { label: '已完成', value: stats.completed, color: 'text-emerald-400', border: 'border-emerald-500/20', bg: 'from-emerald-500/5 to-transparent' },
              { label: '失败任务', value: stats.failed, color: 'text-red-400', border: 'border-red-500/20', bg: 'from-red-500/5 to-transparent' },
              { label: '总存储量', value: formatFileSize(stats.totalSize), color: 'text-purple-400', border: 'border-purple-500/20', bg: 'from-purple-500/5 to-transparent' },
            ].map((stat, idx) => (
              <div key={idx} className={cn("relative overflow-hidden rounded-2xl border bg-gradient-to-br backdrop-blur-sm p-5 transition-all duration-300 hover:scale-105 hover:shadow-lg", stat.border, stat.bg)}>
                <div className="text-xs font-bold text-muted-foreground uppercase tracking-wider mb-1">{stat.label}</div>
                <div className={cn("text-2xl font-black tracking-tight", stat.color)}>{stat.value}</div>
                {/* Decorative corner */}
                <div className={cn("absolute top-0 right-0 w-8 h-8 opacity-20", stat.color)}>
                  <svg viewBox="0 0 24 24" fill="currentColor"><path d="M0 0h24v24H0z" fill="none" /><path d="M21 3H3v18h18V3zm-2 16H5V5h14v14z" opacity=".3" /><path d="M21 3h-8v2h8v8h2V5c0-1.1-.9-2-2-2z" /></svg>
                </div>
              </div>
            ))}
          </div>
        </header>

        <div className="px-8 pb-6 flex-shrink-0 z-10">
          <div className="flex flex-col md:flex-row md:items-center gap-4 bg-white/5 backdrop-blur-md border border-white/10 p-2 rounded-2xl">
            <div className="relative flex-1 group">
              <Search className="absolute left-4 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground group-hover:text-primary transition-colors" />
              <Input
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="搜索任务ID或文件名..."
                className="pl-11 bg-transparent border-0 focus-visible:ring-0 text-foreground placeholder:text-muted-foreground/50 h-11"
              />
            </div>
            <div className="w-px h-8 bg-white/10 hidden md:block" />
            <Select value={status} onValueChange={(v) => setStatus(v as StatusFilter)}>
              <SelectTrigger className="w-full md:w-48 bg-transparent border-0 focus:ring-0 h-11 text-muted-foreground hover:text-foreground">
                <SelectValue placeholder="筛选状态" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value="all">全部状态</SelectItem>
                <SelectItem value="pending">等待中</SelectItem>
                <SelectItem value="processing">处理中</SelectItem>
                <SelectItem value="completed">已完成</SelectItem>
                <SelectItem value="failed">失败</SelectItem>
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
                  'group w-full text-left rounded-2xl border transition-all duration-300 relative overflow-hidden',
                  'bg-white/5 border-white/10 hover:bg-white/10 hover:border-primary/30 hover:shadow-[0_0_30px_-10px_rgba(var(--primary),0.2)]'
                )}
              >
                {/* Progress Background Mesh for Processing */}
                {doc.status === 'processing' && (
                  <div className="absolute inset-0 z-0 opacity-5 pointer-events-none bg-[url('/grid.svg')] bg-center [mask-image:linear-gradient(to_right,white,transparent)]" />
                )}

                <div className="flex items-center justify-between gap-4 p-5 relative z-10">
                  <div className="min-w-0 flex-1">
                    <div className="flex items-center gap-3 mb-2">
                      <StatusPill status={doc.status} />
                      <span className="font-mono text-[10px] text-muted-foreground/50">ID: {doc.id.slice(0, 8)}</span>
                    </div>
                    <div className="flex items-center gap-3">
                      <p className="font-bold text-lg text-foreground truncate group-hover:text-primary transition-colors">{doc.filename}</p>
                    </div>
                    <div className="mt-2 text-xs text-muted-foreground flex flex-wrap gap-x-6 gap-y-1 font-medium">
                      <div className="flex items-center gap-1.5">
                        <div className="w-1.5 h-1.5 rounded-full bg-slate-500/50" />
                        更新于 {formatDate(doc.updated_at)}
                      </div>
                      <div className="flex items-center gap-1.5">
                        <div className="w-1.5 h-1.5 rounded-full bg-slate-500/50" />
                        {formatFileSize(doc.file_size)}
                      </div>
                      <div className="flex items-center gap-1.5">
                        <div className="w-1.5 h-1.5 rounded-full bg-slate-500/50" />
                        {doc.chunk_count ?? 0} 切片
                      </div>
                      {doc.current_stage && (
                        <div className="flex items-center gap-1.5 text-primary">
                          <div className="w-1.5 h-1.5 rounded-full bg-primary animate-pulse" />
                          {doc.current_stage}
                        </div>
                      )}
                    </div>
                  </div>

                  {/* Actions & Progress Area */}
                  <div className="flex flex-col items-end gap-3 min-w-[120px]">

                    <div className="flex items-center gap-2">
                      <Button
                        size="sm"
                        variant="ghost"
                        className="h-8 text-xs hover:bg-white/10 hover:text-primary"
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
                          className="h-8 text-xs text-red-400 hover:text-red-300 hover:bg-red-500/10"
                          disabled={acting?.id === doc.id}
                          onClick={(e) => {
                            e.stopPropagation()
                            handleCancel(doc.id)
                          }}
                        >
                          {acting?.id === doc.id && acting.action === 'cancel' ? <Loader2 className="w-3 h-3 animate-spin" /> : '终止'}
                        </Button>
                      )}

                      {(doc.status === 'failed' || doc.status === 'cancelled') && (
                        <Button
                          size="sm"
                          variant="ghost"
                          className="h-8 text-xs text-primary hover:text-primary/80 hover:bg-primary/10"
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
                    {/* {(doc.status === 'processing' || doc.status === 'pending') && ( */}
                    <div className="w-full max-w-[160px] space-y-1.5">
                      <div className="flex items-center justify-between text-[10px] font-medium text-muted-foreground">
                        <span>PROGRESS</span>
                        <span>{doc.processing_progress || 0}%</span>
                      </div>
                      <div className="h-1.5 w-full rounded-full bg-white/5 overflow-hidden border border-white/5">
                        <div
                          className={cn(
                            "h-full transition-all duration-500 relative",
                            doc.status === 'failed' ? "bg-red-500" : "bg-primary"
                          )}
                          style={{ width: `${Math.max(0, Math.min(100, doc.processing_progress || 0))}%` }}
                        >
                          <div className="absolute inset-0 bg-white/20 animate-pulse-subtle" />
                        </div>
                      </div>
                    </div>
                    {/* )} */}
                  </div>
                </div>

                {/* Error Message Panel */}
                {doc.status === 'failed' && doc.error_message && (
                  <div className="mx-5 mb-5 mt-0 rounded-lg border border-red-500/20 bg-red-500/10 p-3 flex items-start gap-3">
                    <AlertCircle className="w-4 h-4 text-red-400 flex-shrink-0 mt-0.5" />
                    <div className="space-y-1">
                      <div className="text-xs font-bold text-red-400">错误日志</div>
                      <div className="text-xs font-mono text-red-300/80 break-all">{doc.error_message}</div>
                    </div>
                  </div>
                )}
              </div>
            ))}

            {!filtered.length && (
              <div className="flex flex-col items-center justify-center py-20 text-center">
                <div className="w-20 h-20 rounded-full bg-white/5 flex items-center justify-center mb-4">
                  <Search className="w-8 h-8 text-muted-foreground/30" />
                </div>
                <p className="text-muted-foreground">没有找到相关的入库任务</p>
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
