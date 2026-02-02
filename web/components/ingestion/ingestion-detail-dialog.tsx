'use client'

import { useMemo, useState } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertCircle, CheckCircle2, Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { documentApi } from '@/lib/api-client'
import type { Document } from '@/types'
import { cn, formatDate, formatFileSize } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useDocumentView } from '@/store/document-view'
import { formatApiError } from '@/lib/api-errors'

const STAGES = [
  { key: 'queued', label: '排队' },
  { key: 'parsing', label: '解析' },
  { key: 'chunking', label: '切块' },
  { key: 'embedding', label: '向量化' },
  { key: 'completed', label: '完成' },
] as const

function inferStage(doc: Document): string {
  const raw = (doc.current_stage || '').toLowerCase()
  if (STAGES.some((s) => s.key === raw)) return raw
  if (doc.status === 'pending') return 'queued'
  if (doc.status === 'processing') return 'parsing'
  if (doc.status === 'completed') return 'completed'
  return raw || 'queued'
}

function statusBadgeVariant(status: Document['status']): 'default' | 'secondary' | 'destructive' | 'outline' {
  if (status === 'completed') return 'default'
  if (status === 'failed') return 'destructive'
  if (status === 'quarantined') return 'secondary'
  if (status === 'cancelled') return 'secondary'
  if (status === 'processing' || status === 'pending') return 'outline'
  return 'secondary'
}

export function IngestionDetailDialog({
  open,
  onOpenChange,
  documentId,
}: {
  open: boolean
  onOpenChange: (open: boolean) => void
  documentId: string | null
}) {
  const { openDocument } = useDocumentView()
  const [isActing, setIsActing] = useState(false)

  const { data: doc, isLoading, isError, refetch } = useQuery({
    queryKey: ['ingestion-doc-detail', documentId],
    queryFn: async () => {
      if (!documentId) throw new Error('missing document id')
      return await documentApi.get(documentId)
    },
    enabled: open && Boolean(documentId),
    staleTime: 1_000,
    refetchInterval: (query) => {
      const data = query.state.data as Document | undefined
      if (!open || !data) return false
      return data.status === 'pending' || data.status === 'processing' ? 2_000 : false
    },
  })

  const stageKey = doc ? inferStage(doc) : 'queued'
  const activeIndex = Math.max(0, STAGES.findIndex((s) => s.key === stageKey))

  const runtime = useMemo(() => {
    if (!doc) return []
    const meta = doc.metadata || {}
    const pipeline = meta.pipeline || {}
    const user = meta.user || {}
    return [
      { k: 'Document ID', v: doc.id },
      { k: 'Dataset ID', v: doc.dataset_id || '-' },
      { k: 'File', v: `${doc.file_type} · ${formatFileSize(doc.file_size)}` },
      { k: 'Chunks', v: String(doc.chunk_count ?? '-') },
      { k: 'Progress', v: `${doc.processing_progress ?? 0}%` },
      { k: 'Stage', v: doc.current_stage || '-' },
      { k: 'Updated', v: formatDate(doc.updated_at) },
      { k: 'Parser', v: String(meta.parser_backend || '-') },
      { k: 'Chunker', v: String(meta.chunk_strategy || '-') },
      { k: 'Pipeline Hash', v: String(meta.pipeline_hash || '-') },
      { k: 'Task ID', v: String(meta.task_id || '-') },
      { k: 'KG Task ID', v: String(meta.kg_task_id || '-') },
      { k: 'User Tags', v: Array.isArray(user.tags) ? user.tags.join(', ') || '-' : String(user.tags || '-') },
      { k: 'Pipeline', v: typeof pipeline === 'object' ? JSON.stringify(pipeline) : String(pipeline || '-') },
    ]
  }, [doc])

  const canCancel = Boolean(doc && (doc.status === 'pending' || doc.status === 'processing'))
  const canRetry = Boolean(doc && (doc.status === 'failed' || doc.status === 'cancelled' || doc.status === 'quarantined'))
  const canForceRetry = Boolean(doc && doc.status === 'completed')

  const handleCancel = async () => {
    if (!doc || isActing) return
    setIsActing(true)
    try {
      await documentApi.cancel(doc.id)
      toast.success('已取消入库任务')
      await refetch()
    } catch (err: any) {
      toast.error(formatApiError(err, '取消失败'))
    } finally {
      setIsActing(false)
    }
  }

  const handleRetry = async (force: boolean) => {
    if (!doc || isActing) return
    setIsActing(true)
    try {
      await documentApi.retry(doc.id, force ? { force: true } : undefined)
      toast.success(force ? '已触发重新入库（强制）' : '已触发重新入库')
      await refetch()
    } catch (err: any) {
      toast.error(formatApiError(err, '重试失败'))
    } finally {
      setIsActing(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-3xl bg-[#fafafa] border-slate-200 shadow-2xl sm:rounded-[2rem] p-0 overflow-hidden outline-none">
        {/* Paper Texture Overlay */}
        <div className="absolute inset-0 opacity-50 pointer-events-none mix-blend-multiply" style={{ backgroundImage: 'url("data:image/svg+xml,%3Csvg width=\'100\' height=\'100\' viewBox=\'0 0 100 100\' xmlns=\'http://www.w3.org/200\'%3E%3Cfilter id=\'noise\'%3E%3CfeTurbulence type=\'fractalNoise\' baseFrequency=\'0.8\' numOctaves=\'4\' stitchTiles=\'stitch\'/%3E%3C/filter%3E%3Crect width=\'100\' height=\'100\' filter=\'url(%23noise)\' opacity=\'0.08\'/%3E%3C/svg%3E")', backgroundSize: '200px 200px' }} />

        <DialogHeader className="px-8 pt-8 pb-6 border-b border-border/60 bg-card relative z-10">
          <DialogTitle className="flex items-center justify-between gap-3">
            <span className="truncate text-xl font-bold  text-slate-900">{doc?.filename || '入库详情'}</span>
            {doc && (
              <Badge variant={statusBadgeVariant(doc.status)} className="shrink-0">
                {doc.status}
              </Badge>
            )}
          </DialogTitle>
        </DialogHeader>

	        {isLoading && (
	          <div className="py-20 flex items-center justify-center text-slate-400">
	            <Loader2 className="h-8 w-8 animate-spin motion-reduce:animate-none" />
	          </div>
	        )}

        {isError && !isLoading && (
          <div className="m-8 rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-700 relative z-10">
            <div className="flex items-center gap-2 mb-2">
              <AlertCircle className="w-5 h-5 text-red-500" />
              <span className="font-bold">加载失败</span>
            </div>
            <p>无法获取文档详情，请重试。</p>
            <div className="mt-4">
              <Button
                size="sm"
                variant="outline"
                className="bg-card border-destructive/30 text-destructive hover:bg-destructive/10"
                onClick={() => refetch()}
              >
                重新加载
              </Button>
            </div>
          </div>
        )}

        {!isLoading && doc && (
          <div className="p-8 space-y-8 max-h-[70vh] overflow-y-auto overscroll-contain no-scrollbar relative z-10">

            {/* Pipeline Stage Card */}
            <div className="rounded-2xl border border-border bg-card shadow-sm p-6 relative overflow-hidden">
              <div className="flex items-center justify-between gap-3 mb-6">
                <div className="text-sm font-bold text-slate-900 uppercase ">Processing Pipeline</div>
                <div className="text-xs font-mono text-slate-500 bg-slate-100 px-2 py-1 rounded-md">Progress: {doc.processing_progress ?? 0}%</div>
              </div>

              <div className="relative z-10">
                <div className="grid grid-cols-5 gap-4">
                  {STAGES.map((s, idx) => {
                    const isDone = doc.status === 'completed' ? true : idx < activeIndex
                    const isActive = doc.status !== 'completed' && idx === activeIndex
                    const isFailed = (doc.status === 'failed' || doc.status === 'quarantined') && isActive
                    const Icon = isDone ? CheckCircle2 : isFailed ? AlertCircle : null
                    return (
                      <div key={s.key} className="flex flex-col items-center gap-3 group">
                        <div
                          className={cn(
                            'h-10 w-10 rounded-full border-2 flex items-center justify-center transition-all duration-300',
                            isDone && 'bg-emerald-50 border-emerald-500 text-emerald-600 shadow-[0_0_10px_rgba(16,185,129,0.2)]',
                            isActive && !isFailed && 'bg-sky-50 border-sky-500 text-sky-600 shadow-[0_0_10px_rgba(14,165,233,0.3)] scale-110',
                            isFailed && (doc.status === 'quarantined' ? 'bg-amber-50 border-amber-500 text-amber-700 shadow-[0_0_10px_rgba(245,158,11,0.25)]' : 'bg-red-50 border-red-500 text-red-600 shadow-[0_0_10px_rgba(239,68,68,0.3)]'),
                            !isDone && !isActive && 'bg-slate-50 border-slate-200 text-slate-300'
                          )}
                        >
                          {Icon ? <Icon className={cn('h-5 w-5', isDone && 'text-emerald-600')} /> : <span className="text-xs font-bold">{idx + 1}</span>}
                        </div>
                        <div className={cn('text-[11px] font-bold uppercase ', isActive ? 'text-slate-900' : 'text-slate-400')}>
                          {s.label}
                        </div>
                      </div>
                    )
                  })}
                </div>

                {(doc.status === 'processing' || doc.status === 'pending') && (
                  <div className="mt-8">
                    <div className="h-1.5 w-full rounded-full bg-slate-100 overflow-hidden">
                      <div
                        className="h-full bg-sky-500 transition-all duration-500 shadow-[0_0_10px_rgba(14,165,233,0.5)]"
                        style={{ width: `${Math.max(0, Math.min(100, doc.processing_progress || 0))}%` }}
                      />
                    </div>
                  </div>
                )}
              </div>
            </div>

            {(doc.status === 'failed' || doc.status === 'quarantined') && doc.error_message && (
              <div className={cn(
                "rounded-2xl border p-5 shadow-inner",
                doc.status === 'quarantined' ? "border-amber-200 bg-amber-50" : "border-red-200 bg-red-50"
              )}>
                <div className={cn(
                  "text-sm font-bold flex items-center gap-2 mb-2",
                  doc.status === 'quarantined' ? "text-amber-700" : "text-red-700"
                )}>
                  <AlertCircle className="w-4 h-4" />
                  {doc.status === 'quarantined' ? '隔离原因' : '错误信息'}
                </div>
	                <pre className={cn(
	                  "whitespace-pre-wrap break-words rounded-xl bg-card border p-4 text-xs font-mono leading-relaxed shadow-sm",
	                  doc.status === 'quarantined' ? "border-amber-100 text-amber-700" : "border-red-100 text-red-600"
	                )}>
	                  {doc.error_message}
	                </pre>
              </div>
            )}

            {/* Runtime Info - Ticket Style */}
            <div className="rounded-2xl border border-slate-200 bg-slate-50/50 p-6">
              <div className="text-sm font-bold text-slate-900 uppercase  mb-4">Runtime Details</div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {runtime.map((item) => (
                  <div key={item.k} className="bg-card rounded-xl border border-border p-3 shadow-sm hover:shadow-md transition-shadow duration-200 motion-reduce:transition-none">
                    <div className="text-[10px] font-bold text-slate-400 uppercase  mb-1">{item.k}</div>
                    <div className="text-xs font-mono text-slate-700 break-words font-medium">{item.v}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-end gap-3 pt-6 border-t border-slate-200/60 block">
              <Button
                variant="outline"
                className="rounded-full border-slate-200 hover:bg-slate-50 text-slate-700"
                disabled={!doc || isActing}
                onClick={() => doc && openDocument(doc.id)}
              >
                查看解析内容
              </Button>
              {canCancel && (
                <Button variant="destructive" className="rounded-full shadow-red-200 shadow-lg" disabled={isActing} onClick={handleCancel}>
                  取消任务
                </Button>
              )}
              {canRetry && (
                <Button className="rounded-full bg-sky-600 hover:bg-sky-700 shadow-sky-200 shadow-lg" disabled={isActing} onClick={() => handleRetry(false)}>
                  重试入库
                </Button>
              )}
              {canForceRetry && (
                <Button variant="outline" className="rounded-full border-slate-200 hover:text-red-600 hover:border-red-200" disabled={isActing} onClick={() => handleRetry(true)}>
                  强制重跑
                </Button>
              )}
            </div>
          </div>
        )}
      </DialogContent>
    </Dialog>

  )
}
