'use client'

import { useMemo, useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertCircle, CheckCircle2, Loader2 } from 'lucide-react'
import { toast } from 'sonner'

import { documentApi } from '@/lib/api-client'
import type { Document, DocumentVersionDiff, DocumentVersionList } from '@/types'
import { cn, formatDate, formatFileSize } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { useDocumentView } from '@/store/document-view'
import { formatApiError } from '@/lib/api-errors'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

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
  const [diffFrom, setDiffFrom] = useState<string | null>(null)
  const [diffTo, setDiffTo] = useState<string | null>(null)
  const [diffLoading, setDiffLoading] = useState(false)
  const [diff, setDiff] = useState<DocumentVersionDiff | null>(null)
  const [diffError, setDiffError] = useState<string | null>(null)

  const { data: doc, isLoading, isError, refetch } = useQuery({
    queryKey: ['ingestion-doc-detail', documentId],
    queryFn: async ({ signal }) => {
      if (!documentId) throw new Error('missing document id')
      return await documentApi.get(documentId, undefined, { signal })
    },
    enabled: open && Boolean(documentId),
    staleTime: 1_000,
    refetchInterval: (query) => {
      const data = query.state.data as Document | undefined
      if (!open || !data) return false
      return data.status === 'pending' || data.status === 'processing' ? 2_000 : false
    },
  })

  const {
    data: versions,
    isLoading: versionsLoading,
    isError: versionsError,
    refetch: refetchVersions,
  } = useQuery<DocumentVersionList>({
    queryKey: ['ingestion-doc-versions', documentId],
    queryFn: async ({ signal }) => {
      if (!documentId) throw new Error('missing document id')
      return await documentApi.listVersions(documentId, { signal })
    },
    enabled: open && Boolean(documentId),
    staleTime: 3_000,
  })

  // Default diff selection: active -> current (best-effort).
  useEffect(() => {
    if (!versions) return
    const active = versions.active_pipeline_hash || versions.pipeline_hash || null
    const current = versions.pipeline_hash || versions.active_pipeline_hash || null
    if (!diffFrom && active) setDiffFrom(active)
    if (!diffTo && current) setDiffTo(current)
  }, [versions, diffFrom, diffTo])

  const stageKey = doc ? inferStage(doc) : 'queued'
  const activeIndex = Math.max(0, STAGES.findIndex((s) => s.key === stageKey))

  const runtime = useMemo(() => {
    if (!doc) return []
    const meta = (doc.metadata ?? {}) as Record<string, unknown>
    const pipeline = (meta.pipeline ?? {}) as unknown
    const user = (meta.user ?? {}) as Record<string, unknown>
    const userTags = user.tags as unknown
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
      { k: 'User Tags', v: Array.isArray(userTags) ? userTags.join(', ') || '-' : String(userTags ?? '-') },
      { k: 'Pipeline', v: typeof pipeline === 'object' ? JSON.stringify(pipeline) : String(pipeline ?? '-') },
    ]
  }, [doc])

  const canCancel = Boolean(doc && (doc.status === 'pending' || doc.status === 'processing'))
  const canRetry = Boolean(doc && (doc.status === 'failed' || doc.status === 'cancelled' || doc.status === 'quarantined'))
  const canForceRetry = Boolean(doc && doc.status === 'completed')

  const handleDiff = async () => {
    if (!doc || !diffFrom || !diffTo || diffLoading) return
    setDiffLoading(true)
    setDiffError(null)
    try {
      const data = await documentApi.diffVersions({
        document_id: doc.id,
        from: diffFrom,
        to: diffTo,
        sample_limit: 50,
      })
      setDiff(data)
    } catch (err: any) {
      setDiffError(formatApiError(err, '对比失败'))
      setDiff(null)
    } finally {
      setDiffLoading(false)
    }
  }

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
      <DialogContent className="max-w-3xl p-0 overflow-hidden sm:rounded-2xl">

        <DialogHeader className="px-8 pt-8 pb-6 border-b border-border/60 bg-card relative z-10">
          <DialogTitle className="flex items-center justify-between gap-3">
            <span className="truncate text-xl font-bold text-foreground">{doc?.filename || '入库详情'}</span>
            {doc && (
              <Badge variant={statusBadgeVariant(doc.status)} className="shrink-0">
                {doc.status}
              </Badge>
            )}
          </DialogTitle>
        </DialogHeader>

	        {isLoading && (
	          <div className="flex items-center justify-center py-20 text-muted-foreground">
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
                <div className="text-sm font-bold uppercase text-foreground">Processing Pipeline</div>
                <div className="rounded-md bg-muted px-2 py-1 text-xs font-mono tabular-nums text-muted-foreground">
                  Progress: {doc.processing_progress ?? 0}%
                </div>
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
                            'flex size-10 items-center justify-center rounded-full border-2 text-sm font-semibold tabular-nums transition-colors duration-200 motion-reduce:transition-none',
                            isDone && 'border-success/40 bg-success/10 text-success',
                            isActive && !isFailed && 'border-primary/40 bg-primary/10 text-primary',
                            isFailed &&
                              (doc.status === 'quarantined'
                                ? 'border-warning/40 bg-warning/10 text-warning'
                                : 'border-destructive/40 bg-destructive/10 text-destructive'),
                            !isDone && !isActive && 'border-border/70 bg-muted/40 text-muted-foreground'
                          )}
                        >
                          {Icon ? (
                            <Icon className="size-5" aria-hidden="true" />
                          ) : (
                            <span>{idx + 1}</span>
                          )}
                        </div>
                        <div
                          className={cn(
                            'text-[11px] font-semibold',
                            isActive || isDone ? 'text-foreground' : 'text-muted-foreground'
                          )}
                        >
                          {s.label}
                        </div>
                      </div>
                    )
                  })}
                </div>

                {(doc.status === 'processing' || doc.status === 'pending') && (
                  <div className="mt-8">
                    <div className="h-1.5 w-full overflow-hidden rounded-full bg-muted">
                      <div
                        className="h-full origin-left bg-primary transition-transform duration-200 motion-reduce:transition-none"
                        style={{
                          transform: `scaleX(${
                            Math.max(0, Math.min(100, doc.processing_progress || 0)) / 100
                          })`,
                        }}
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
            <div className="rounded-2xl border border-border bg-muted/30 p-6">
              <div className="mb-4 text-sm font-semibold text-foreground">Runtime Details</div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {runtime.map((item) => (
                  <div key={item.k} className="bg-card rounded-xl border border-border p-3 shadow-sm hover:shadow-md transition-shadow duration-200 motion-reduce:transition-none">
                    <div className="mb-1 text-[10px] font-semibold text-muted-foreground">{item.k}</div>
                    <div className="break-words text-xs font-mono font-medium text-foreground">{item.v}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* Pipeline Versions Diff */}
            <div className="rounded-2xl border border-border bg-card shadow-sm p-6">
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-semibold text-foreground">版本对比（Pipeline Diff）</div>
                <Button
                  size="sm"
                  variant="outline"
                  className="rounded-full"
                  disabled={versionsLoading}
                  onClick={() => refetchVersions()}
                >
                  {versionsLoading ? <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : null}
                  刷新版本
                </Button>
              </div>

              {versionsError ? (
                <div className="mt-3 text-xs text-destructive">加载版本列表失败</div>
              ) : null}

              <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
                <div className="space-y-1">
                  <div className="text-[11px] font-semibold text-muted-foreground">From</div>
                  <Select value={diffFrom || ''} onValueChange={(v) => setDiffFrom(v || null)}>
                    <SelectTrigger className="h-9">
                      <SelectValue placeholder="选择版本" />
                    </SelectTrigger>
                    <SelectContent>
                      {(versions?.items || []).map((it) => (
                        <SelectItem key={it.pipeline_hash} value={it.pipeline_hash}>
                          {it.pipeline_hash} {it.active ? '（active）' : ''}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1">
                  <div className="text-[11px] font-semibold text-muted-foreground">To</div>
                  <Select value={diffTo || ''} onValueChange={(v) => setDiffTo(v || null)}>
                    <SelectTrigger className="h-9">
                      <SelectValue placeholder="选择版本" />
                    </SelectTrigger>
                    <SelectContent>
                      {(versions?.items || []).map((it) => (
                        <SelectItem key={it.pipeline_hash} value={it.pipeline_hash}>
                          {it.pipeline_hash} {it.active ? '（active）' : ''}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <Button className="rounded-full" disabled={diffLoading || !diffFrom || !diffTo} onClick={handleDiff}>
                  {diffLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" /> : null}
                  对比
                </Button>
              </div>

              {diffError ? (
                <div className="mt-3 text-xs text-destructive">{diffError}</div>
              ) : null}

              {diff ? (
                <div className="mt-4 grid grid-cols-2 md:grid-cols-5 gap-3">
                  {[
                    { k: 'From Chunks', v: diff.from_chunk_count },
                    { k: 'To Chunks', v: diff.to_chunk_count },
                    { k: 'Unchanged', v: diff.unchanged_chunks },
                    { k: 'Added', v: diff.added_chunks },
                    { k: 'Removed', v: diff.removed_chunks },
                  ].map((x) => (
                    <div key={x.k} className="rounded-xl border border-border bg-muted/20 p-3">
                      <div className="text-[10px] font-semibold text-muted-foreground">{x.k}</div>
                      <div className="mt-1 text-sm font-mono font-bold text-foreground tabular-nums">{String(x.v)}</div>
                    </div>
                  ))}

                  {diff.changed_transforms?.length ? (
                    <div className="md:col-span-5 rounded-xl border border-border bg-background p-3">
                      <div className="text-[10px] font-semibold text-muted-foreground">Changed Transforms</div>
                      <div className="mt-2 text-xs font-mono text-foreground break-words">
                        {diff.changed_transforms.join(', ')}
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className="mt-3 text-[11px] text-muted-foreground">
                  说明：对比基于 chunk <span className="font-mono">content_hash</span> 的多重集差异；不会返回切片文本。
                </div>
              )}
            </div>

            <div className="flex flex-col items-stretch justify-end gap-3 border-t border-border/60 pt-6 sm:flex-row sm:items-center">
              <Button
                variant="outline"
                className="rounded-full"
                disabled={!doc || isActing}
                onClick={() => doc && openDocument(doc.id)}
              >
                查看解析内容
              </Button>
              {canCancel && (
                <Button variant="destructive" className="rounded-full" disabled={isActing} onClick={handleCancel}>
                  取消任务
                </Button>
              )}
              {canRetry && (
                <Button className="rounded-full" disabled={isActing} onClick={() => handleRetry(false)}>
                  重试入库
                </Button>
              )}
              {canForceRetry && (
                <Button variant="outline" className="rounded-full hover:border-destructive/30 hover:text-destructive" disabled={isActing} onClick={() => handleRetry(true)}>
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
