'use client'

import { useEffect, useMemo, useState } from 'react'
import { ChevronDown, History, Link2, Loader2, RefreshCw, RotateCcw, Terminal, X } from '@/components/icons'
import { useTranslations } from 'next-intl'
import { motion, AnimatePresence } from 'framer-motion'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { IconButton } from '@/components/ui/icon-button'
import { Switch } from '@/components/ui/switch'
import { toTrimmedPrimitiveString } from '@/lib/primitive-text'
import { cn, formatDate } from '@/lib/utils'
import type { ConnectorRunOut } from '@/types'

type ConnectorRunStatusFilter =
  | 'all'
  | 'pending'
  | 'running'
  | 'failed'
  | 'completed'
  | 'cancelled'
type TranslateValue = string | number | Date
type TranslateFn = (key: string, values?: Record<string, TranslateValue>) => string

type KnowledgeConnectorRunsPanelProps = {
  selectedDatasetId?: string
  connectorRuns: ConnectorRunOut[]
  connectorRunsLoading: boolean
  onCancelConnectorRun: (id: string) => void | Promise<void>
  onResumeConnectorRun: (id: string) => void | Promise<void>
  onRetryFailedConnectorRun: (id: string) => void | Promise<void>
  onLoadConnectorRuns: (params: { datasetId?: string }) => void | Promise<void>
}

type TaskCardProps = {
  run: ConnectorRunOut
  t: TranslateFn
  onCancel: (id: string) => void | Promise<void>
  onResume?: (id: string) => void | Promise<void>
  onRetry: (id: string) => void | Promise<void>
  isExpanded: boolean
  onToggleExpand: () => void
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function getConnectorRunProgress(rawStats: unknown) {
  const stats = isRecord(rawStats) ? rawStats : {}
  const total = Number(
    stats?.total_items || stats?.items_total || stats?.total_urls || 0
  )
  const processed = Number(
    stats?.processed_items ||
      stats?.items_processed ||
      stats?.processed_urls ||
      0
  )
  return { total, processed }
}

function getConnectorRunErrors(stats: unknown): Record<string, unknown>[] {
  const record = isRecord(stats) ? stats : {}
  return Array.isArray(record.errors) ? record.errors.filter(isRecord) : []
}

export function KnowledgeConnectorRunsPanel({
  selectedDatasetId,
  connectorRuns,
  connectorRunsLoading,
  onCancelConnectorRun,
  onResumeConnectorRun,
  onRetryFailedConnectorRun,
  onLoadConnectorRuns,
}: Readonly<KnowledgeConnectorRunsPanelProps>) {
  const t = useTranslations('KnowledgeConnectorRunsPanel')
  const [runStatusFilter, setRunStatusFilter] =
    useState<ConnectorRunStatusFilter>('all')
  const [autoRefresh, setAutoRefresh] = useState(true)
  const [expandedRunId, setExpandedRunId] = useState<string | null>(null)

  const stats = useMemo(
    () => ({
      total: connectorRuns.length,
      active: connectorRuns.filter(
        (r) => r.status === 'running' || r.status === 'pending'
      ).length,
      failed: connectorRuns.filter((r) => r.status === 'failed').length,
      completed: connectorRuns.filter((r) => r.status === 'completed').length,
    }),
    [connectorRuns]
  )

  const visibleRuns = useMemo(() => {
    let list =
      runStatusFilter === 'all'
        ? connectorRuns
        : connectorRuns.filter(
            (r) => String(r.status).toLowerCase() === runStatusFilter
          )

    return [...list].sort(
      (a, b) =>
        new Date(b.created_at).getTime() - new Date(a.created_at).getTime()
    )
  }, [connectorRuns, runStatusFilter])

  useEffect(() => {
    if (!autoRefresh || stats.active === 0) return
    const id = setInterval(
      () => onLoadConnectorRuns({ datasetId: selectedDatasetId }),
      5000
    )
    return () => clearInterval(id)
  }, [autoRefresh, stats.active, selectedDatasetId, onLoadConnectorRuns])

  return (
    <div className="flex flex-col h-full bg-background/50">
      {/* 头部：原子级操作岛 */}
      <div className="px-5 py-4 border-b border-border/40 space-y-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <Terminal className="size-3.5 text-primary/60" />
            <span className="text-[10px] font-medium uppercase tracking-[0.2em] text-foreground/80">
              {t('connectorRuns.title')}
            </span>
          </div>

          <div className="flex items-center gap-2">
            <div className="flex items-center gap-1.5 px-2 py-0.5 rounded-md bg-muted/30 border border-border/40">
              <div
                className={cn(
                  'size-1 rounded-full transition-all',
                  autoRefresh
                    ? 'bg-success animate-pulse shadow-[0_0_5px_rgba(16,185,129,0.4)]'
                    : 'bg-muted-foreground/30'
                )}
              />
              <span className="text-[9px] font-medium text-foreground/50 uppercase">
                {t('connectorRuns.liveBadge')}
              </span>
              <Switch
                checked={autoRefresh}
                onCheckedChange={setAutoRefresh}
                className="scale-[0.5] origin-right"
              />
            </div>
            <IconButton
              label="刷新"
              variant="ghost"
              className="h-6 w-6 rounded-md text-muted-foreground hover:text-foreground"
              onClick={() =>
                onLoadConnectorRuns({ datasetId: selectedDatasetId })
              }
            >
              <RefreshCw
                className={cn('size-3', connectorRunsLoading && 'animate-spin')}
              />
            </IconButton>
          </div>
        </div>

        {/* 高密度状态分段器 */}
        <div className="flex p-0.5 bg-muted/40 rounded-lg border border-border/40">
          {([
            {
              key: 'all',
              label: t('connectorRuns.summary.all'),
              count: stats.total,
              color: 'text-foreground',
            },
            {
              key: 'running',
              label: t('connectorRuns.summary.active'),
              count: stats.active,
              color: 'text-primary',
            },
            {
              key: 'failed',
              label: t('runStatus.failed'),
              count: stats.failed,
              color: 'text-destructive',
            },
            {
              key: 'completed',
              label: t('runStatus.completed'),
              count: stats.completed,
              color: 'text-success',
            },
          ] satisfies Array<{
            key: ConnectorRunStatusFilter
            label: string
            count: number
            color: string
          }>).map((item) => (
            <button
              key={item.key}
              onClick={() => setRunStatusFilter(item.key)}
              className={cn(
                'flex-1 flex items-center justify-center gap-1.5 py-1.5 rounded-md text-[10px] font-medium transition-all duration-200',
                runStatusFilter === item.key
                  ? 'bg-background text-primary shadow-sm ring-1 ring-border/10' +
                      item.color
                  : 'text-muted-foreground/50 hover:text-muted-foreground hover:bg-muted/40'
              )}
            >
              <span>{item.label}</span>
              <span className="tabular-nums opacity-40 text-[9px]">
                {item.count}
              </span>
            </button>
          ))}
        </div>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-2.5 no-scrollbar">
        <AnimatePresence mode="popLayout">
          {visibleRuns.length === 0 ? (
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              className="flex flex-col items-center justify-center gap-3 px-5 py-16 text-center"
            >
              {connectorRunsLoading ? <Loader2 className="size-6 animate-spin motion-reduce:animate-none text-muted-foreground" /> : <History className="size-7 text-muted-foreground" />}
              <p className="text-[13px] text-muted-foreground">{connectorRunsLoading ? t('connectorRuns.loading') : t('connectorRuns.empty.title')}</p>
            </motion.div>
          ) : (
            visibleRuns.map((run) => (
              <TaskCard
                key={run.id}
                run={run}
                t={t}
                onCancel={onCancelConnectorRun}
                onResume={onResumeConnectorRun}
                onRetry={onRetryFailedConnectorRun}
                isExpanded={expandedRunId === run.id}
                onToggleExpand={() =>
                  setExpandedRunId(expandedRunId === run.id ? null : run.id)
                }
              />
            ))
          )}
        </AnimatePresence>
      </div>
    </div>
  )
}

function TaskCard({
  run,
  t,
  onCancel,
  onResume,
  onRetry,
  isExpanded,
  onToggleExpand,
}: Readonly<TaskCardProps>) {
  const { total, processed } = getConnectorRunProgress(run.stats || {})
  const runErrors = getConnectorRunErrors(run.stats)
  const progressPct = total > 0 ? Math.round((processed / total) * 100) : 0
  const isFailed = run.status === 'failed'
  const isRunning = run.status === 'running' || run.status === 'pending'
  const isCancelled = run.status === 'cancelled'

  return (
    <motion.div
      layout
      initial={{ opacity: 0, scale: 0.98 }}
      animate={{ opacity: 1, scale: 1 }}
      exit={{ opacity: 0, scale: 0.95 }}
      className={cn(
        'group relative rounded-2xl border transition-all duration-300',
        isRunning
          ? 'border-primary/30 bg-primary/[0.03]'
          : 'border-border/40 bg-background/40 hover:border-border/80'
      )}
    >
      <div className="p-3 space-y-3">
        <div className="flex items-center justify-between gap-3">
          <div className="flex items-center gap-2.5 min-w-0">
            <div
              className={cn(
                'size-8 shrink-0 rounded-lg flex items-center justify-center border shadow-sm',
                isFailed
                  ? 'bg-destructive/10 border-destructive/20 text-destructive'
                  : isRunning
                    ? 'bg-primary/10 border-primary/20 text-primary'
                    : 'bg-muted/40 border-border/40 text-muted-foreground'
              )}
            >
              <Link2 className="size-4" />
            </div>
            <div className="min-w-0">
              <div className="flex items-center gap-1.5">
                <span className="text-[12px] font-medium text-foreground truncate max-w-[140px] leading-none">
                  {run.connector_id}
                </span>
                <div
                  className={cn(
                    'size-1.5 rounded-full',
                    isFailed
                      ? 'bg-destructive shadow-[0_0_6px_rgba(var(--destructive),0.5)]'
                      : isRunning
                        ? 'bg-primary animate-pulse'
                        : 'bg-muted-foreground/30'
                  )}
                />
              </div>
              <div className="flex items-center gap-1.5 text-[9px] font-medium text-muted-foreground/40 tabular-nums mt-1 uppercase">
                <span>{formatDate(run.created_at)}</span>
                <span>·</span>
                <span>{run.id.slice(0, 8)}</span>
              </div>
            </div>
          </div>

          <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
            {isRunning && (
              <IconButton
                label="取消"
                variant="ghost"
                className="h-7 w-7 rounded-md text-muted-foreground hover:text-destructive"
                onClick={() => onCancel(run.id)}
              >
                <X className="size-3.5" />
              </IconButton>
            )}
            {isFailed && (
              <IconButton
                label="重试"
                variant="ghost"
                className="h-7 w-7 rounded-md text-muted-foreground hover:text-primary"
                onClick={() => onRetry(run.id)}
              >
                <RotateCcw className="size-3.5" />
              </IconButton>
            )}
            {isCancelled && onResume ? (
              <IconButton
                label="继续"
                variant="ghost"
                className="h-7 w-7 rounded-md text-muted-foreground hover:text-primary"
                onClick={() => onResume(run.id)}
              >
                <RefreshCw className="size-3.5" />
              </IconButton>
            ) : null}
            <IconButton
              label="复制"
              variant="ghost"
              className="h-7 w-7 rounded-md text-muted-foreground"
              onClick={() => {
                navigator.clipboard.writeText(run.id)
                toast.success('Copied')
              }}
            >
              <Terminal className="size-3.5" />
            </IconButton>
          </div>
        </div>

        {total > 0 && (
          <div className="space-y-1.5">
            <div className="h-1 w-full bg-muted/40 rounded-full overflow-hidden">
              <motion.div
                initial={{ width: 0 }}
                animate={{ width: `${progressPct}%` }}
                className={cn(
                  'h-full transition-colors',
                  isFailed ? 'bg-destructive/60' : 'bg-primary/70'
                )}
              />
            </div>
            <div className="flex items-center justify-between px-0.5">
              <span className="text-[9px] font-medium text-foreground/40 uppercase">
                {progressPct}% Complete
              </span>
              <span className="text-[9px] font-medium text-muted-foreground/30 tabular-nums">
                {processed}/{total}
              </span>
            </div>
          </div>
        )}

        {isFailed && run.error_message && (
          <button
            onClick={onToggleExpand}
            className="w-full flex items-center justify-between px-2.5 py-1.5 rounded-lg bg-destructive/5 border border-destructive/10 text-destructive/80 hover:bg-destructive/10 transition-colors"
          >
            <span className="text-[9px] font-medium truncate uppercase">
              Error Details
            </span>
            <ChevronDown
              className={cn(
                'size-3 transition-transform',
                isExpanded && 'rotate-180'
              )}
            />
          </button>
        )}
      </div>

      <AnimatePresence>
        {isExpanded && isFailed && (
          <motion.div
            initial={{ height: 0, opacity: 0 }}
            animate={{ height: 'auto', opacity: 1 }}
            exit={{ height: 0, opacity: 0 }}
            className="overflow-hidden bg-foreground"
          >
            <div className="p-3 border-t border-border/5 font-mono text-[9px] leading-relaxed text-muted-foreground">
              <div className="text-rose/80 font-medium mb-1">
                ERR: {run.error_message}
              </div>
              {runErrors
                .slice(0, 2)
                .map((err) => (
	                  <div key={toTrimmedPrimitiveString(err.error ?? err.message ?? err.code, 'error')} className="mt-1 opacity-60 truncate">
	                    ! {toTrimmedPrimitiveString(err.error ?? err.message ?? err.code, 'error')}
                  </div>
                ))}
            </div>
          </motion.div>
        )}
      </AnimatePresence>
    </motion.div>
  )
}
