'use client'

import { useQuery } from '@tanstack/react-query'
import { documentApi } from '@/lib/api/documents'
import { Loader2, AlertCircle, X, Ban, RotateCcw, ArrowUpRight, Settings2 } from '@/components/icons'
import { useTranslations } from 'next-intl'
import { useEffect, useId, useLayoutEffect, useRef, useState } from 'react'
import { cn } from '@/lib/utils'
import type { Document } from '@/types/documents'
import { Button } from './ui/button'
import { ScrollArea } from './ui/scroll-area'
import { toast } from 'sonner'
import { usePathname, useRouter } from '@/i18n/navigation'
import { formatApiError } from '@/lib/api-errors'
import { useAuth } from '@/hooks/use-auth'
import { useBackendMeta } from '@/hooks/use-backend-meta'
import { AUTH_SCOPE_CHANGED_EVENT, getAuthSessionRevision } from '@/lib/auth-storage'
import styles from './task-center.module.css'

const TASK_CENTER_ACTIVE_ROUTE_PREFIXES = ['/knowledge', '/parsing', '/chunk-preview', '/data-governance', '/datasets']

const ACTIVE_TASK_POLL_MS = 5000
const IDLE_TASK_DISCOVERY_POLL_MS = 60000

export function TaskCenter() {
  const panelId = useId()
  const dockRef = useRef<HTMLDivElement>(null)
  const panelRef = useRef<HTMLDivElement>(null)
  const triggerRef = useRef<HTMLButtonElement>(null)
  const [isOpen, setIsOpen] = useState(false)
  const [isActing, setIsActing] = useState(false)
  const pendingActionRef = useRef<{ authRevision: number } | null>(null)
  const router = useRouter()
  const pathname = usePathname()
  const { isAuthenticated } = useAuth()
  const { data: backendMeta } = useBackendMeta()
  const t = useTranslations('TaskCenter')
  const commonT = useTranslations('Common')
  useEffect(() => {
    const resetAction = () => {
      pendingActionRef.current = null
      setIsActing(false)
    }
    window.addEventListener(AUTH_SCOPE_CHANGED_EVENT, resetAction)
    return () => {
      pendingActionRef.current = null
      window.removeEventListener(AUTH_SCOPE_CHANGED_EVENT, resetAction)
    }
  }, [])
  const configuredAuthMode = backendMeta?.features?.auth_mode
  const authMode = typeof configuredAuthMode === 'string' ? configuredAuthMode.trim().toLowerCase() : undefined
  const isTaskRoute = TASK_CENTER_ACTIVE_ROUTE_PREFIXES.some(
    (prefix) => pathname === prefix || pathname.startsWith(`${prefix}/`),
  )
  const canLoadForAuthMode = authMode === 'header' || (authMode === 'jwt' && isAuthenticated)
  const canDiscoverTasks = !pathname.startsWith('/auth') && canLoadForAuthMode

  const { data: taskLists, refetch } = useQuery({
    queryKey: ['documents', 'task-center', 'status'],
    queryFn: async ({ signal }) => {
      const [active, failed, quarantined] = await Promise.all([
        documentApi.list({ status: 'processing', limit: 100 }, { signal }),
        documentApi.list({ status: 'failed', limit: 100 }, { signal }),
        documentApi.list({ status: 'quarantined', limit: 100 }, { signal }),
      ])
      return { active, failed, quarantined }
    },
    enabled: canDiscoverTasks,
    staleTime: ACTIVE_TASK_POLL_MS,
    refetchInterval: (query) => {
      if (!canDiscoverTasks) return false
      const hasActiveTasks = (query.state.data?.active.total ?? 0) > 0
      return isOpen || isTaskRoute || hasActiveTasks ? ACTIVE_TASK_POLL_MS : IDLE_TASK_DISCOVERY_POLL_MS
    },
  })

  const visibleTasks = canDiscoverTasks ? taskLists : undefined
  const activeTasks = visibleTasks?.active.items ?? []
  const failedTasks = [...(visibleTasks?.failed.items ?? []), ...(visibleTasks?.quarantined.items ?? [])].sort(
    (left, right) => Date.parse(right.created_at) - Date.parse(left.created_at),
  )
  const totalActive = visibleTasks?.active.total ?? 0
  const totalFailed = (visibleTasks?.failed.total ?? 0) + (visibleTasks?.quarantined.total ?? 0)
  const totalCount = totalActive + totalFailed
  const hasTasks = totalCount > 0

  useLayoutEffect(() => {
    if (!hasTasks) return
    const dock = dockRef.current!
    let anchors: HTMLElement[] = []
    const positionDock = () => {
      let bottom = 16
      for (const anchor of anchors) {
        const rect = anchor.getBoundingClientRect()
        if (
          rect.width > 0 &&
          rect.bottom > window.innerHeight - 80 &&
          rect.top < window.innerHeight &&
          rect.right > window.innerWidth - 80
        ) {
          bottom = Math.max(bottom, window.innerHeight - rect.top + 16)
        }
      }
      dock.style.setProperty('--task-center-bottom', `${bottom}px`)
    }
    const resize = new ResizeObserver(positionDock)
    const observeAnchors = () => {
      resize.disconnect()
      anchors = Array.from(document.querySelectorAll<HTMLElement>('[data-task-center-dock], [data-workspace-notice-stack], footer, #chat-composer'))
        .filter((element) => !element.closest('[role="dialog"]'))
        .map((element) => (element.id === 'chat-composer' ? element.parentElement! : element))
      for (const anchor of anchors) resize.observe(anchor)
      positionDock()
    }
    const mutations = new MutationObserver(observeAnchors)
    mutations.observe(document.body, { childList: true, subtree: true })
    observeAnchors()
    window.addEventListener('resize', positionDock)
    document.addEventListener('scroll', positionDock, true)
    return () => {
      resize.disconnect()
      mutations.disconnect()
      window.removeEventListener('resize', positionDock)
      document.removeEventListener('scroll', positionDock, true)
    }
  }, [hasTasks, pathname])

  useLayoutEffect(() => {
    if (isOpen) panelRef.current?.focus()
  }, [isOpen])

  function closePanel() {
    setIsOpen(false)
    triggerRef.current?.focus()
  }

  if (totalCount === 0) return null

  const stageLabels: Record<string, string> = {
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

  const getStageLabel = (doc: Document) => {
    const currentStage = doc.current_stage
    if (currentStage !== null && currentStage !== undefined) {
      const stage = currentStage.trim().toLowerCase()
      if (stage !== '') return Object.hasOwn(stageLabels, stage) ? stageLabels[stage] : currentStage
    }
    return stageLabels[doc.status] ?? ''
  }

  const clampProgress = (progress: unknown) => {
    const value = Number(progress)
    if (!Number.isFinite(value)) return 0
    return Math.max(0, Math.min(100, Math.round(value)))
  }

  const handleTaskAction = async (id: string, action: 'cancel' | 'retry') => {
    if (pendingActionRef.current?.authRevision === getAuthSessionRevision()) return
    const operation = { authRevision: getAuthSessionRevision() }
    pendingActionRef.current = operation
    setIsActing(true)
    const isCurrent = () =>
      pendingActionRef.current === operation && operation.authRevision === getAuthSessionRevision()
    try {
      if (action === 'cancel') await documentApi.cancel(id)
      else await documentApi.retry(id)
      if (!isCurrent()) return
      toast.success(t(action === 'cancel' ? 'cancelledTask' : 'retryTriggered'))
      await refetch()
    } catch (err: unknown) {
      if (isCurrent()) toast.error(formatApiError(err, t(action === 'cancel' ? 'cancelFailed' : 'retryFailed')))
    } finally {
      if (pendingActionRef.current === operation) {
        pendingActionRef.current = null
        setIsActing(false)
      }
    }
  }

  return (
    <div ref={dockRef} className={styles.root}>
      {isOpen && (
        <div
          id={panelId}
          ref={panelRef}
          tabIndex={-1}
          role="region"
          aria-labelledby={`${panelId}-title`}
          onKeyDown={(event) => {
            if (event.key !== 'Escape') return
            event.preventDefault()
            closePanel()
          }}
          data-task-center-panel="true"
          data-task-center-boundary="ruled"
          className={cn(
            styles.panel,
            'mb-2 overflow-hidden rounded-lg border border-foreground/15 bg-background text-foreground animate-in slide-in-from-bottom-5 fade-in motion-reduce:animate-none motion-reduce:transition-none',
          )}
        >
          <div className="flex shrink-0 items-center justify-between border-b border-foreground/10 bg-background px-4 py-3">
            <div className="min-w-0">
              <h4 id={`${panelId}-title`} className="text-sm font-semibold leading-none text-balance">
                {t('title')}
              </h4>
              <div className="mt-2 flex items-center gap-2">
                {totalActive > 0 && (
                  <span className="inline-flex items-center gap-1 rounded-md border border-info/20 bg-info/[0.08] px-2 py-0.5 text-xs font-medium text-info">
                    {t('activeBadge')} <span className="tabular-nums">{totalActive}</span>
                  </span>
                )}
                {totalFailed > 0 && (
                  <span className="inline-flex items-center gap-1 rounded-md border border-destructive/20 bg-destructive/[0.08] px-2 py-0.5 text-xs font-medium text-destructive">
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
                  router.push('/knowledge/ingestion?mode=execution-monitor')
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
                onClick={closePanel}
                aria-label={t('closeTaskCenter')}
                title={commonT('close')}
              >
                <X className="h-3 w-3" />
              </Button>
            </div>
          </div>
          <ScrollArea className="min-h-0 max-h-80 flex-1">
            <div className="p-3 space-y-4">
              {totalActive > 0 && (
                <div className="space-y-2">
                  <div className="flex items-center justify-between px-1">
                    <span className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                      {t('sectionActive')}
                    </span>
                    <span className="text-xs tabular-nums text-muted-foreground">{totalActive}</span>
                  </div>
                  <div className="space-y-2">
                    {activeTasks.map((doc) => {
                      const progress = clampProgress(doc.processing_progress)
                      const stageLabel = getStageLabel(doc)
                      return (
                        <div
                          key={doc.id}
                          className="group flex items-start gap-3 rounded-md border border-foreground/10 bg-background px-3 py-3 transition-colors hover:bg-muted/20"
                        >
                          <div className="mt-0.5 flex h-9 w-9 items-center justify-center rounded-md border border-foreground/10 bg-background text-info">
                            <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
                          </div>
                          <div className="flex-1 min-w-0">
                            <div className="flex items-start justify-between gap-2">
                              <p className="text-sm font-medium leading-snug truncate" title={doc.filename}>
                                {doc.filename}
                              </p>
                              <span className="shrink-0 text-xs tabular-nums text-muted-foreground">{progress}%</span>
                            </div>
                            <div className="mt-1 text-xs text-muted-foreground truncate">{stageLabel}</div>
                            <div className="mt-2 h-1.5 w-full overflow-hidden rounded-sm bg-secondary">
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
                            disabled={isActing}
                            onClick={() => handleTaskAction(doc.id, 'cancel')}
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
                    <span className="text-xs font-semibold uppercase tracking-[0.14em] text-muted-foreground">
                      {t('sectionFailed')}
                    </span>
                    <span className="text-xs tabular-nums text-muted-foreground">{totalFailed}</span>
                  </div>
                  <div className="space-y-2">
                    {failedTasks.map((doc) => {
                      const isQuarantine = doc.status === 'quarantined'
                      const containerClass = cn(
                        'group flex items-start gap-3 rounded-md border px-3 py-3 transition-colors',
                        isQuarantine
                          ? 'border-warning/20 bg-warning/[0.06] hover:bg-warning/[0.1]'
                          : 'border-destructive/20 bg-destructive/[0.06] hover:bg-destructive/[0.1]',
                      )
                      const iconClass = cn(
                        'mt-0.5 flex h-9 w-9 items-center justify-center rounded-md border bg-background',
                        isQuarantine ? 'border-warning/20 text-warning' : 'border-destructive/20 text-destructive',
                      )
                      const titleClass = cn(
                        'text-sm font-medium truncate leading-snug',
                        isQuarantine ? 'text-foreground' : 'text-destructive',
                      )
                      const messageClass = cn(
                        'mt-1 text-xs truncate',
                        isQuarantine ? 'text-muted-foreground' : 'text-destructive/80',
                      )
                      const retryClass = cn(
                        'mt-0.5 h-8 w-8 rounded-lg',
                        isQuarantine
                          ? 'text-warning/80 hover:text-warning'
                          : 'text-destructive/80 hover:text-destructive',
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
                            <p
                              className={messageClass}
                              title={
                                doc.error_message || (isQuarantine ? t('fallbackQuarantined') : t('fallbackFailed'))
                              }
                            >
                              {doc.error_message || (isQuarantine ? t('fallbackQuarantined') : t('fallbackFailed'))}
                            </p>
                          </div>
                          <Button
                            variant="ghost"
                            size="icon"
                            className={retryClass}
                            disabled={isActing}
                            onClick={() => handleTaskAction(doc.id, 'retry')}
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
        ref={triggerRef}
        variant="outline"
        size="icon"
        className={cn(
          'group relative size-12 rounded-md border-foreground/15 bg-background transition-colors duration-200 motion-reduce:transition-none hover:border-foreground/30',
          isOpen && 'bg-muted/40',
        )}
        onClick={() => (isOpen ? closePanel() : setIsOpen(true))}
        aria-label={t('title')}
        aria-expanded={isOpen}
        aria-controls={isOpen ? panelId : undefined}
        title={t('title')}
      >
        <Settings2 className="h-6 w-6 text-primary transition-transform duration-200 motion-reduce:transition-none group-hover:rotate-90" />
        <span
          className={cn(
            'absolute -right-2 -top-2 inline-flex h-5 min-w-5 items-center justify-center rounded-md border px-1 text-[11px] tabular-nums',
            totalFailed > 0 && totalActive === 0
              ? 'border-destructive/20 bg-destructive text-destructive-foreground'
              : 'border-primary/20 bg-primary text-primary-foreground',
          )}
        >
          {totalCount}
        </span>
        {totalActive > 0 ? <span className="absolute -left-1 -top-1 h-2 w-2 rounded-sm bg-primary" /> : null}
      </Button>
    </div>
  )
}
