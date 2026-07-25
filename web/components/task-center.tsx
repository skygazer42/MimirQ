"use client"

import { useQuery } from '@tanstack/react-query'
import { documentApi } from '@/lib/api'
import { Loader2, AlertCircle, X, Ban, RotateCcw, ArrowUpRight, Settings2 } from 'lucide-react'
import { useTranslations } from 'next-intl'
import { useState } from 'react'
import { cn } from '@/lib/utils'
import type { Document } from '@/types'
import { Button } from './ui/button'
import { ScrollArea } from './ui/scroll-area'
import { toast } from 'sonner'
import { usePathname, useRouter } from '@/i18n/navigation'
import { formatApiError } from '@/lib/api-errors'
import { useAuth } from '@/hooks/use-auth'
import { useBackendMeta } from '@/hooks/use-backend-meta'

const TASK_CENTER_ACTIVE_ROUTE_PREFIXES = [
  '/knowledge',
  '/parsing',
  '/chunk-preview',
  '/data-governance',
  '/datasets',
]

export function TaskCenter() {
  const [isOpen, setIsOpen] = useState(false)
  const [acting, setActing] = useState<{ id: string; action: 'cancel' | 'retry' } | null>(null)
  const router = useRouter()
  const pathname = usePathname()
  const { isAuthenticated } = useAuth()
  const { data: backendMeta } = useBackendMeta()
  const t = useTranslations('TaskCenter')
  const commonT = useTranslations('Common')
  const authMode = String(backendMeta?.features?.auth_mode || '').trim().toLowerCase()
  const isTaskRoute = TASK_CENTER_ACTIVE_ROUTE_PREFIXES.some((prefix) =>
    pathname === prefix || pathname.startsWith(`${prefix}/`)
  )
  const canLoadForAuthMode =
    authMode === 'header' ? true : authMode === 'jwt' ? isAuthenticated : false
  const shouldLoadTasks =
    !pathname.startsWith('/auth') && canLoadForAuthMode && (isOpen || isTaskRoute)
  
  const { data: documents = [], refetch } = useQuery<Document[]>({
    queryKey: ['documents', 'task-center'],
    queryFn: async ({ signal }) => {
      const res = await documentApi.list({ limit: 100 }, { signal })
      return res.items
    },
    enabled: shouldLoadTasks,
    staleTime: 5000,
    refetchInterval: shouldLoadTasks ? 5000 : false,
  })

  const activeTasks = documents.filter(d => d.status === 'processing' || d.status === 'pending')
  const failedTasks = documents.filter(d => d.status === 'failed' || d.status === 'quarantined')
  
  const totalActive = activeTasks.length
  const totalFailed = failedTasks.length
  const totalCount = totalActive + totalFailed
  
  if (totalCount === 0) return null

  const getStageLabel = (doc: Document) => {
    const stageMap: Record<string, string> = {
      queued: t('stages.queued'),
      parsing: t('stages.parsing'),
      chunking: t('stages.chunking'),
      embedding: t('stages.embedding'),
      indexing: t('stages.indexing'),
      completed: t('stages.completed'),
      failed: t('stages.failed'),
      cancelled: t('stages.cancelled'),
      quarantined: t('stages.quarantined'),
      pending: t('stages.pending'),
      processing: t('stages.processing'),
    }
    const stage = String(doc.current_stage || '').trim().toLowerCase()
    if (stage) return stageMap[stage] || String(doc.current_stage)
    if (doc.status === 'pending') return stageMap.pending
    if (doc.status === 'processing') return stageMap.processing
    if (doc.status === 'failed') return stageMap.failed
    if (doc.status === 'quarantined') return stageMap.quarantined
    return ''
  }

  const clampProgress = (progress: unknown) => {
    const value = Number(progress)
    if (!Number.isFinite(value)) return 0
    return Math.max(0, Math.min(100, Math.round(value)))
  }

  const handleCancel = async (id: string) => {
    if (acting) return
    setActing({ id, action: 'cancel' })
    try {
      await documentApi.cancel(id)
      toast.success(t('cancelledTask'))
      await refetch()
    } catch (err: unknown) {
      toast.error(formatApiError(err, t('cancelFailed')))
    } finally {
      setActing(null)
    }
  }

  const handleRetry = async (id: string) => {
    if (acting) return
    setActing({ id, action: 'retry' })
    try {
      await documentApi.retry(id)
      toast.success(t('retryTriggered'))
      await refetch()
    } catch (err: unknown) {
      toast.error(formatApiError(err, t('retryFailed')))
    } finally {
      setActing(null)
    }
  }

  return (
	      <div className="fixed bottom-4 right-4 z-50 flex flex-col items-end supports-[padding:env(safe-area-inset-bottom)]:bottom-[calc(env(safe-area-inset-bottom)+1rem)] supports-[padding:env(safe-area-inset-right)]:right-[calc(env(safe-area-inset-right)+1rem)]">
	        {isOpen && (
	            <div className="mb-2 w-[26rem] bg-popover/90 text-popover-foreground backdrop-blur-md border border-border/60 rounded-2xl shadow-strong ring-1 ring-border/40 overflow-hidden animate-in slide-in-from-bottom-5 fade-in motion-reduce:animate-none motion-reduce:transition-none">
                <div className="px-4 py-3 border-b border-border/60 bg-muted/35 flex justify-between items-center">
                    <div className="min-w-0">
                      <h4 className="text-sm font-semibold leading-none text-balance">{t('title')}</h4>
                      <div className="mt-2 flex items-center gap-2">
                        {totalActive > 0 && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-primary/10 text-primary px-2 py-0.5 text-xs font-medium ring-1 ring-primary/20">
                            {t('activeBadge')} <span className="tabular-nums">{totalActive}</span>
                          </span>
                        )}
                        {totalFailed > 0 && (
                          <span className="inline-flex items-center gap-1 rounded-full bg-destructive/10 text-destructive px-2 py-0.5 text-xs font-medium ring-1 ring-destructive/20">
                            {t('failedBadge')} <span className="tabular-nums">{totalFailed}</span>
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-1">
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-8 px-2.5 text-xs gap-1"
                        onClick={() => {
                          router.push('/knowledge/ingestion')
                          setIsOpen(false)
                        }}
                      >
                        {t('monitor')}
                        <ArrowUpRight className="h-3.5 w-3.5" />
                      </Button>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-6 w-6"
                        onClick={() => setIsOpen(false)}
                        aria-label={t('closeTaskCenter')}
                        title={commonT('close')}
                      >
                          <X className="h-3 w-3" />
                      </Button>
                    </div>
                </div>
                <ScrollArea className="max-h-80">
                    <div className="p-3 space-y-4">
                        {totalActive > 0 && (
                          <div className="space-y-2">
                            <div className="flex items-center justify-between px-1">
                              <span className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">{t('sectionActive')}</span>
                              <span className="text-xs tabular-nums text-muted-foreground">{totalActive}</span>
                            </div>
                            <div className="space-y-2">
                              {activeTasks.map(doc => {
                                const progress = clampProgress(doc.processing_progress)
                                const stageLabel = getStageLabel(doc)
                                return (
                                  <div
                                    key={doc.id}
                                    className="group flex items-start gap-3 p-3 rounded-xl border border-border/50 bg-background/50 hover:bg-muted/20 transition-colors"
                                  >
	                                    <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-lg bg-primary/10 text-primary">
	                                      <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
	                                    </div>
                                    <div className="flex-1 min-w-0">
                                      <div className="flex items-start justify-between gap-2">
                                        <p className="text-sm font-medium leading-snug truncate" title={doc.filename}>
                                          {doc.filename}
                                        </p>
                                        <span className="shrink-0 text-xs tabular-nums text-muted-foreground">
                                          {progress}%
                                        </span>
                                      </div>
                                      <div className="mt-1 text-xs text-muted-foreground truncate">
                                        {stageLabel}
                                      </div>
                                      <div className="mt-2 w-full h-1.5 bg-secondary rounded-full overflow-hidden">
                                        <div
                                          className="h-full bg-primary origin-left transition-transform duration-200 ease-out motion-reduce:transition-none"
                                          style={{ transform: `scaleX(${progress / 100})` }}
                                        />
                                      </div>
                                    </div>
                                    <Button
                                      variant="ghost"
                                      size="icon"
                                      className="mt-0.5 h-8 w-8 rounded-lg text-muted-foreground hover:text-foreground"
                                      disabled={acting?.id === doc.id}
                                      onClick={() => handleCancel(doc.id)}
                                      aria-label={t('cancelTask')}
                                      title={commonT('cancel')}
                                    >
                                      <Ban className="h-4 w-4" />
                                    </Button>
                                  </div>
                                )
                              })}
                            </div>
                          </div>
                        )}

                        {totalFailed > 0 && (
                          <div className="space-y-2">
                            <div className="flex items-center justify-between px-1">
                              <span className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">{t('sectionFailed')}</span>
                              <span className="text-xs tabular-nums text-muted-foreground">{totalFailed}</span>
                            </div>
                            <div className="space-y-2">
                              {failedTasks.map((doc) => {
                                const isQuarantine = doc.status === 'quarantined'
                                const containerClass = cn(
                                  "group flex items-start gap-3 p-3 rounded-xl transition-colors",
                                  isQuarantine
                                    ? "border border-warning/20 bg-warning/5 hover:bg-warning/10"
                                    : "border border-destructive/20 bg-destructive/5 hover:bg-destructive/10"
                                )
                                const iconClass = cn(
                                  "mt-0.5 flex h-9 w-9 items-center justify-center rounded-lg",
                                  isQuarantine ? "bg-warning/10 text-warning" : "bg-destructive/10 text-destructive"
                                )
                                const titleClass = cn(
                                  "text-sm font-medium truncate leading-snug",
                                  isQuarantine ? "text-warning" : "text-destructive"
                                )
                                const messageClass = cn(
                                  "mt-1 text-xs truncate",
                                  isQuarantine ? "text-warning/80" : "text-destructive/80"
                                )
                                const retryClass = cn(
                                  "mt-0.5 h-8 w-8 rounded-lg",
                                  isQuarantine
                                    ? "text-warning/80 hover:text-warning"
                                    : "text-destructive/80 hover:text-destructive"
                                )

                                return (
                                  <div key={doc.id} className={containerClass}>
                                    <div className={iconClass}>
                                      <AlertCircle className="h-4 w-4" />
                                    </div>
                                    <div className="flex-1 min-w-0">
                                      <p className={titleClass} title={doc.filename}>
                                        {doc.filename}
                                      </p>
                                      <p className={messageClass} title={doc.error_message || (isQuarantine ? t('fallbackQuarantined') : t('fallbackFailed'))}>
                                        {doc.error_message || (isQuarantine ? t('fallbackQuarantined') : t('fallbackFailed'))}
                                      </p>
                                    </div>
                                    <Button
                                      variant="ghost"
                                      size="icon"
                                      className={retryClass}
                                      disabled={acting?.id === doc.id}
                                      onClick={() => handleRetry(doc.id)}
                                      aria-label={t('retryTask')}
                                      title={commonT('retry')}
                                    >
                                      <RotateCcw className="h-4 w-4" />
                                    </Button>
                                  </div>
                                )
                              })}
                            </div>
                          </div>
                        )}
                    </div>
                </ScrollArea>
            </div>
        )}

        <Button
          variant="outline"
          size="icon"
          className={cn(
            "group relative rounded-full size-12 shadow-strong bg-background/90 border-primary/20 hover:border-primary transition-colors transition-shadow duration-200 motion-reduce:transition-none",
            isOpen && "bg-primary/10"
          )}
          onClick={() => setIsOpen(v => !v)}
          aria-label={t('title')}
          title={t('title')}
        >
          <Settings2 className="h-6 w-6 text-primary transition-transform duration-200 motion-reduce:transition-none group-hover:rotate-90" />
          <span
            className={cn(
              "absolute -top-2 -right-2 inline-flex min-w-5 h-5 items-center justify-center rounded-full text-[11px] px-1 tabular-nums",
              totalFailed > 0 && totalActive === 0
                ? "bg-destructive text-destructive-foreground"
                : "bg-primary text-primary-foreground"
            )}
          >
            {totalCount}
          </span>
          {totalActive > 0 && (
            <span className="absolute -top-1 -left-1 flex h-2 w-2">
              <span className="animate-ping motion-reduce:animate-none absolute inline-flex h-full w-full rounded-full bg-primary/60 opacity-75"></span>
              <span className="relative inline-flex rounded-full h-2 w-2 bg-primary"></span>
            </span>
          )}
        </Button>
    </div>
  )
}
