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
  const canRetry = Boolean(doc && (doc.status === 'failed' || doc.status === 'cancelled'))
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
      <DialogContent className="max-w-3xl">
        <DialogHeader>
          <DialogTitle className="flex items-center justify-between gap-3">
            <span className="truncate">{doc?.filename || '入库详情'}</span>
            {doc && (
              <Badge variant={statusBadgeVariant(doc.status)} className="shrink-0">
                {doc.status}
              </Badge>
            )}
          </DialogTitle>
        </DialogHeader>

        {isLoading && (
          <div className="py-10 flex items-center justify-center text-muted-foreground">
            <Loader2 className="h-6 w-6 animate-spin" />
          </div>
        )}

        {isError && !isLoading && (
          <div className="rounded-xl border border-red-500/20 bg-red-500/5 p-4 text-sm text-red-700 dark:text-red-300">
            加载失败，请重试。
            <div className="mt-3">
              <Button size="sm" variant="outline" onClick={() => refetch()}>
                重新加载
              </Button>
            </div>
          </div>
        )}

        {!isLoading && doc && (
          <div className="space-y-6">
            <div className="rounded-2xl border border-border bg-background/60 p-4">
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-medium">处理流水线</div>
                <div className="text-xs text-muted-foreground tabular-nums">{doc.processing_progress ?? 0}%</div>
              </div>

              <div className="mt-3 grid grid-cols-5 gap-2">
                {STAGES.map((s, idx) => {
                  const isDone = doc.status === 'completed' ? true : idx < activeIndex
                  const isActive = doc.status !== 'completed' && idx === activeIndex
                  const isFailed = doc.status === 'failed' && isActive
                  const Icon = isDone ? CheckCircle2 : isFailed ? AlertCircle : null
                  return (
                    <div key={s.key} className="flex flex-col items-center gap-1.5">
                      <div
                        className={cn(
                          'h-8 w-8 rounded-full border flex items-center justify-center',
                          isDone && 'bg-emerald-500/10 border-emerald-500/30 text-emerald-600',
                          isActive && !isFailed && 'bg-sky-500/10 border-sky-500/30 text-sky-600',
                          isFailed && 'bg-red-500/10 border-red-500/30 text-red-600',
                          !isDone && !isActive && 'bg-muted/40 border-border text-muted-foreground'
                        )}
                      >
                        {Icon ? <Icon className={cn('h-4 w-4', isDone && 'text-emerald-600')} /> : <span className="text-xs">{idx + 1}</span>}
                      </div>
                      <div className={cn('text-[11px] font-medium', isActive ? 'text-foreground' : 'text-muted-foreground')}>
                        {s.label}
                      </div>
                    </div>
                  )
                })}
              </div>

              {(doc.status === 'processing' || doc.status === 'pending') && (
                <div className="mt-4">
                  <div className="h-2 w-full rounded-full bg-muted overflow-hidden">
                    <div
                      className="h-full bg-sky-600 dark:bg-sky-500 transition-all duration-500"
                      style={{ width: `${Math.max(0, Math.min(100, doc.processing_progress || 0))}%` }}
                    />
                  </div>
                </div>
              )}
            </div>

            {doc.status === 'failed' && doc.error_message && (
              <div className="rounded-2xl border border-red-500/20 bg-red-500/5 p-4">
                <div className="text-sm font-medium text-red-700 dark:text-red-300">错误信息</div>
                <pre className="mt-2 whitespace-pre-wrap break-words rounded-xl bg-background/60 p-3 text-xs text-red-700 dark:text-red-200">
                  {doc.error_message}
                </pre>
              </div>
            )}

            <div className="rounded-2xl border border-border bg-background/60 p-4">
              <div className="text-sm font-medium">运行信息</div>
              <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-3">
                {runtime.map((item) => (
                  <div key={item.k} className="rounded-xl border border-border bg-background p-3">
                    <div className="text-[11px] text-muted-foreground">{item.k}</div>
                    <div className="mt-1 text-xs font-mono text-foreground break-words">{item.v}</div>
                  </div>
                ))}
              </div>
            </div>

            <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-end gap-2">
              <Button
                variant="outline"
                disabled={!doc || isActing}
                onClick={() => doc && openDocument(doc.id)}
              >
                查看内容
              </Button>
              {canCancel && (
                <Button variant="destructive" disabled={isActing} onClick={handleCancel}>
                  取消任务
                </Button>
              )}
              {canRetry && (
                <Button disabled={isActing} onClick={() => handleRetry(false)}>
                  重试入库
                </Button>
              )}
              {canForceRetry && (
                <Button variant="outline" disabled={isActing} onClick={() => handleRetry(true)}>
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
