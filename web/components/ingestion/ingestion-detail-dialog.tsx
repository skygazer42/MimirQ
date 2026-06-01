'use client'

import { useMemo, useState, useEffect } from 'react'
import { useQuery } from '@tanstack/react-query'
import { AlertCircle, CheckCircle2, Loader2 } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'

import { documentApi } from '@/lib/api'
import type { Document, DocumentVersionDiff, DocumentVersionList } from '@/types'
import { cn, formatDate, formatFileSize } from '@/lib/utils'
import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { useDocumentView } from '@/store/document-view'
import { formatApiError } from '@/lib/api-errors'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

const STAGE_KEYS = ['queued', 'parsing', 'chunking', 'embedding', 'completed'] as const

function displayPrimitive(value: unknown, fallback: string = '-'): string {
  if (typeof value === 'string') return value || fallback
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') return String(value)
  return fallback
}

function inferStage(doc: Document): string {
  const raw = (doc.current_stage || '').toLowerCase()
  if (STAGE_KEYS.includes(raw as (typeof STAGE_KEYS)[number])) return raw
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
}: Readonly<{
  open: boolean
  onOpenChange: (open: boolean) => void
  documentId: string | null
}>) {
  const t = useTranslations('IngestionDetailDialog')
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
      const data = query.state.data
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
  const stages = useMemo(
    () =>
      STAGE_KEYS
        .map((key) => ({ key }))
        .map((stage) => ({
          ...stage,
          label: t(`stages.${stage.key}`),
        })),
    [t]
  )
  const activeIndex = Math.max(0, stages.findIndex((s) => s.key === stageKey))

  const runtime = useMemo(() => {
    if (!doc) return []
    const meta = (doc.metadata ?? {}) as Record<string, unknown>
    const pipeline = (meta.pipeline ?? {}) as unknown
    const user = (meta.user ?? {}) as Record<string, unknown>
    const userTags = user.tags
    return [
      { k: t('runtime.documentId'), v: doc.id },
      { k: t('runtime.datasetId'), v: doc.dataset_id || '-' },
      { k: t('runtime.file'), v: `${doc.file_type} · ${formatFileSize(doc.file_size)}` },
      { k: t('runtime.chunks'), v: String(doc.chunk_count ?? '-') },
      { k: t('runtime.progress'), v: `${doc.processing_progress ?? 0}%` },
      { k: t('runtime.stage'), v: doc.current_stage || '-' },
      { k: t('runtime.updated'), v: formatDate(doc.updated_at) },
      { k: t('runtime.parser'), v: displayPrimitive(meta.parser_backend) },
      { k: t('runtime.chunker'), v: displayPrimitive(meta.chunk_strategy) },
      { k: t('runtime.pipelineHash'), v: displayPrimitive(meta.pipeline_hash) },
      { k: t('runtime.taskId'), v: displayPrimitive(meta.task_id) },
      { k: t('runtime.kgTaskId'), v: displayPrimitive(meta.kg_task_id) },
      { k: t('runtime.userTags'), v: Array.isArray(userTags) ? userTags.join(', ') || '-' : displayPrimitive(userTags) },
      { k: t('runtime.pipeline'), v: typeof pipeline === 'object' ? JSON.stringify(pipeline) : displayPrimitive(pipeline) },
    ]
  }, [doc, t])

  const canCancel = Boolean(doc?.status === 'pending' || doc?.status === 'processing')
  const canRetry = Boolean(doc?.status === 'failed' || doc?.status === 'cancelled' || doc?.status === 'quarantined')
  const canForceRetry = Boolean(doc?.status === 'completed')

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
    } catch (err: unknown) {
      setDiffError(formatApiError(err, t("errors.diffFailed")))
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
      toast.success(t('toasts.cancelSuccess'))
      await refetch()
    } catch (err: unknown) {
      toast.error(formatApiError(err, t('errors.cancelFailed')))
    } finally {
      setIsActing(false)
    }
  }

  const handleRetry = async (force: boolean) => {
    if (!doc || isActing) return
    setIsActing(true)
    try {
      await documentApi.retry(doc.id, force ? { force: true } : undefined)
      toast.success(force ? t('toasts.retryForced') : t('toasts.retry'))
      await refetch()
    } catch (err: unknown) {
      toast.error(formatApiError(err, t('errors.retryFailed')))
    } finally {
      setIsActing(false)
    }
  }

  return (
    <Sheet open={open} onOpenChange={onOpenChange}>
      <SheetContent
        side="right"
        className="h-[100dvh] w-[min(820px,100vw)] max-w-[820px] overflow-hidden border-l border-border/60 bg-background/95 shadow-strong"
      >
        <SheetHeader className="sr-only">
          <SheetTitle>{doc?.filename || t("header.fallbackTitle")}</SheetTitle>
          <SheetDescription>{documentId || ''}</SheetDescription>
        </SheetHeader>

        <div className="flex h-full min-h-0 flex-col bg-background">
          <div className="border-b border-border/60 bg-card px-6 py-5">
            <div className="flex items-start justify-between gap-3 pr-10">
              <div className="min-w-0">
                <div className="text-[11px] font-semibold uppercase tracking-[0.16em] text-muted-foreground">
                  {t('pipeline.title')}
                </div>
                <div className="mt-1 truncate text-lg font-bold text-foreground">
                  {doc?.filename || t("header.fallbackTitle")}
                </div>
                <div className="mt-1 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                  <span className="font-mono">{documentId || '-'}</span>
                  {doc ? (
                    <>
                      <span className="text-muted-foreground/40">·</span>
                      <span>{formatDate(doc.updated_at)}</span>
                    </>
                  ) : null}
                </div>
              </div>
              {doc && (
                <Badge variant={statusBadgeVariant(doc.status)} className="shrink-0">
                  {t(`status.${doc.status}`)}
                </Badge>
              )}
            </div>
          </div>

	        {isLoading && (
	          <div className="flex flex-1 items-center justify-center text-muted-foreground">
	            <Loader2 className="h-8 w-8 animate-spin motion-reduce:animate-none" />
	          </div>
	        )}

          {isError && !isLoading && (
            <div className="flex-1 overflow-y-auto overscroll-contain p-6 no-scrollbar">
              <div className="rounded-xl border border-red-200 bg-red-50 p-6 text-sm text-red-700 relative z-10">
                <div className="mb-2 flex items-center gap-2">
                  <AlertCircle className="w-5 h-5 text-red-500" />
                  <span className="font-bold">{t('errors.loadTitle')}</span>
                </div>
                <p>{t('errors.loadDescription')}</p>
                <div className="mt-4">
                  <Button
                    size="sm"
                    variant="outline"
                    className="bg-card border-destructive/30 text-destructive hover:bg-destructive/10"
                    onClick={() => refetch()}
                  >
                    {t('actions.reload')}
                  </Button>
                </div>
              </div>
            </div>
          )}

          {!isLoading && doc && (
            <>
              <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar">
                <div className="space-y-6 p-6">

            {/* Pipeline Stage Card */}
            <div className="rounded-2xl border border-border bg-card shadow-sm p-6 relative overflow-hidden">
              <div className="flex items-center justify-between gap-3 mb-6">
                <div className="text-sm font-bold uppercase text-foreground">{t('pipeline.title')}</div>
                <div className="rounded-md bg-muted px-2 py-1 text-xs font-mono tabular-nums text-muted-foreground">
                  {t('pipeline.progress')}: {doc.processing_progress ?? 0}%
                </div>
              </div>

              <div className="relative z-10">
                <div className="grid grid-cols-5 gap-4">
                  {stages.map((s, idx) => {
                    const isDone = doc.status === 'completed' ? true : idx < activeIndex
                    const isActive = doc.status !== 'completed' && idx === activeIndex
                    const isFailed = (doc.status === 'failed' || doc.status === 'quarantined') && isActive
                    const Icon = (() => {
    if (isDone) {
        return CheckCircle2;
    }
    else if (isFailed) {
            return AlertCircle;
        }
        else {
            return null;
        }
})()
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
                  {doc.status === 'quarantined' ? t('errors.quarantineReason') : t('errors.errorMessage')}
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
              <div className="mb-4 text-sm font-semibold text-foreground">{t('runtime.title')}</div>
              <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {runtime.map((item) => (
                  <div key={item.k} className="bg-card rounded-xl border border-border p-3 shadow-sm hover:shadow-md transition-shadow duration-200 motion-reduce:transition-none">
                    <div className="mb-1 text-[11px] font-semibold text-muted-foreground">{item.k}</div>
                    <div className="break-words text-xs font-mono font-medium text-foreground">{item.v}</div>
                  </div>
                ))}
              </div>
            </div>

            {/* Pipeline Versions Diff */}
            <div className="rounded-2xl border border-border bg-card shadow-sm p-6">
              <div className="flex items-center justify-between gap-3">
                <div className="text-sm font-semibold text-foreground">{t('versions.title')}</div>
                <Button
                  size="sm"
                  variant="outline"
                  className="rounded-full"
                  disabled={versionsLoading}
                  onClick={() => refetchVersions()}
                >
                  {versionsLoading ? <Loader2 className="mr-2 h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : null}
                  {t('actions.refreshVersions')}
                </Button>
              </div>

              {versionsError ? (
                <div className="mt-3 text-xs text-destructive">{t('errors.loadVersions')}</div>
              ) : null}

              <div className="mt-4 grid grid-cols-1 md:grid-cols-3 gap-3 items-end">
                <div className="space-y-1">
                  <div className="text-[11px] font-semibold text-muted-foreground">{t('versions.fromLabel')}</div>
                  <Select value={diffFrom || ''} onValueChange={(v) => setDiffFrom(v || null)}>
                    <SelectTrigger className="h-9">
                      <SelectValue placeholder={t('versions.selectVersion')} />
                    </SelectTrigger>
                    <SelectContent>
                      {(versions?.items || []).map((it) => (
                        <SelectItem key={it.pipeline_hash} value={it.pipeline_hash}>
                          {it.pipeline_hash} {it.active ? `（${t('versions.activeTag')}）` : ''}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <div className="space-y-1">
                  <div className="text-[11px] font-semibold text-muted-foreground">{t('versions.toLabel')}</div>
                  <Select value={diffTo || ''} onValueChange={(v) => setDiffTo(v || null)}>
                    <SelectTrigger className="h-9">
                      <SelectValue placeholder={t('versions.selectVersion')} />
                    </SelectTrigger>
                    <SelectContent>
                      {(versions?.items || []).map((it) => (
                        <SelectItem key={it.pipeline_hash} value={it.pipeline_hash}>
                          {it.pipeline_hash} {it.active ? `（${t('versions.activeTag')}）` : ''}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </div>

                <Button className="rounded-full" disabled={diffLoading || !diffFrom || !diffTo} onClick={handleDiff}>
                  {diffLoading ? <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" /> : null}
                  {t('actions.compare')}
                </Button>
              </div>

              {diffError ? (
                <div className="mt-3 text-xs text-destructive">{diffError}</div>
              ) : null}

              {diff ? (
                <div className="mt-4 grid grid-cols-2 md:grid-cols-5 gap-3">
                  {[
                    { k: t('versions.metrics.fromChunks'), v: diff.from_chunk_count },
                    { k: t('versions.metrics.toChunks'), v: diff.to_chunk_count },
                    { k: t('versions.metrics.unchanged'), v: diff.unchanged_chunks },
                    { k: t('versions.metrics.added'), v: diff.added_chunks },
                    { k: t('versions.metrics.removed'), v: diff.removed_chunks },
                  ].map((x) => (
                    <div key={x.k} className="rounded-xl border border-border bg-muted/20 p-3">
                      <div className="text-[11px] font-semibold text-muted-foreground">{x.k}</div>
                      <div className="mt-1 text-sm font-mono font-bold text-foreground tabular-nums">{String(x.v)}</div>
                    </div>
                  ))}

                  {diff.changed_transforms?.length ? (
                    <div className="md:col-span-5 rounded-xl border border-border bg-background p-3">
                      <div className="text-[11px] font-semibold text-muted-foreground">{t('versions.metrics.changedTransforms')}</div>
                      <div className="mt-2 text-xs font-mono text-foreground break-words">
                        {diff.changed_transforms.join(', ')}
                      </div>
                    </div>
                  ) : null}
                </div>
              ) : (
                <div className="mt-3 text-[11px] text-muted-foreground">
                  {t('versions.diffHintPrefix')} <span className="font-mono">content_hash</span> {t('versions.diffHintSuffix')}
                </div>
              )}
            </div>
                </div>
              </div>

              <div className="border-t border-border/60 bg-card/95 px-6 py-4">
                <div className="flex flex-col items-stretch justify-end gap-3 sm:flex-row sm:flex-wrap sm:items-center">
                  <Button
                    variant="outline"
                    className="rounded-full"
                    disabled={!doc || isActing}
                    onClick={() => doc && openDocument(doc.id)}
                  >
                    {t('actions.viewParsedContent')}
                  </Button>
                  {canCancel && (
                    <Button variant="destructive" className="rounded-full" disabled={isActing} onClick={handleCancel}>
                      {t('actions.cancelTask')}
                    </Button>
                  )}
                  {canRetry && (
                    <Button className="rounded-full" disabled={isActing} onClick={() => handleRetry(false)}>
                      {t("actions.retry")}
                    </Button>
                  )}
                  {canForceRetry && (
                    <Button variant="outline" className="rounded-full hover:border-destructive/30 hover:text-destructive" disabled={isActing} onClick={() => handleRetry(true)}>
                      {t('actions.forceRetry')}
                    </Button>
                  )}
                </div>
              </div>
            </>
          )}
        </div>
      </SheetContent>
    </Sheet>

  )
}
