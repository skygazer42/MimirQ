'use client'

import { useEffect, useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'
import {
  ChevronDown,
  ChevronRight,
  Copy,
  FileText,
  Layers,
  Link2,
  Play,
  RefreshCw,
  RotateCcw,
  Settings,
  Trash2,
  Zap,
} from 'lucide-react'
import { toast } from 'sonner'

import type { ConnectorInfo, ConnectorRunOut } from '@/types'
import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { StatusBadge, type StatusBadgeStatus } from '@/components/ui/status-badge'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import { connectorApi, datasetApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { cn, formatDate, detachPromise } from '@/lib/utils'

type DatasetPurgePreview = {
  eligible?: number | string | null
  deleted?: number | string | null
  dataset_id?: string | null
  [key: string]: unknown
}

type KnowledgeSettingsPanelProps = {
  selectedDatasetId?: string

  connectorRuns: ConnectorRunOut[]
  connectorRunsLoading: boolean
  connectorRunsUpdatedAt?: number | null
  onLoadConnectorRuns: (params?: { datasetId?: string }) => void | Promise<void>

  expandedConnectorRunId: string | null
  onToggleExpandedConnectorRun: (runId: string) => void

  onCancelConnectorRun: (runId: string) => void | Promise<void>
  onResumeConnectorRun: (runId: string) => void | Promise<void>
  onRetryFailedConnectorRun: (runId: string) => void | Promise<void>
}

type ConnectorRunStatusFilter = 'all' | 'pending' | 'running' | 'failed' | 'completed' | 'cancelled'
type TranslateFn = (key: string, values?: Record<string, any>) => string

function getConnectorRunBadge(status: string, t: TranslateFn): { status: StatusBadgeStatus; label: string } {
  switch (String(status || '').toLowerCase()) {
    case 'pending':
      return { status: 'pending', label: t('runStatus.pending') }
    case 'running':
      return { status: 'processing', label: t('runStatus.running') }
    case 'completed':
      return { status: 'completed', label: t('runStatus.completed') }
    case 'failed':
      return { status: 'failed', label: t('runStatus.failed') }
    case 'cancelled':
      return { status: 'cancelled', label: t('runStatus.cancelled') }
    default:
      return { status: 'pending', label: String(status || t('runStatus.pending')) }
  }
}

function formatDurationMs(ms: number): string {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000))
  const s = totalSeconds % 60
  const totalMinutes = Math.floor(totalSeconds / 60)
  const m = totalMinutes % 60
  const h = Math.floor(totalMinutes / 60)
  if (h > 0) return `${h}h${String(m).padStart(2, '0')}m`
  if (m > 0) return `${m}m${String(s).padStart(2, '0')}s`
  return `${s}s`
}

function formatAclModeLabel(mode: string, t: TranslateFn): string {
  switch (String(mode || '').toLowerCase()) {
    case 'inherit':
      return t('aclModes.inherit')
    case 'only_me':
      return t('aclModes.onlyMe')
    case 'all_team_members':
      return t('aclModes.allTeamMembers')
    case 'partial_members':
      return t('aclModes.partialMembers')
    case 'mixed':
      return t('aclModes.mixed')
    default:
      return String(mode || 'inherit')
  }
}

function formatAclCountRange(min: number | null | undefined, max: number | null | undefined): string | null {
  if (min == null || max == null) return null
  const lo = Number(min)
  const hi = Number(max)
  if (!Number.isFinite(lo) || !Number.isFinite(hi)) return null
  if (lo === hi) return String(lo)
  return `${lo}-${hi}`
}

function formatAclModeBreakdown(counts: Record<string, number> | null | undefined, t: TranslateFn): string | null {
  if (!counts) return null
  const parts = Object.entries(counts)
    .filter(([, v]) => Number(v) > 0)
    .sort((a, b) => Number(b[1]) - Number(a[1]))
    .slice(0, 4)
    .map(([m, v]) => `${formatAclModeLabel(m, t)} ${Number(v)}`)
  return parts.length ? parts.join(' · ') : null
}

function getConnectorRunProgress(stats: Record<string, unknown>): { total: number; processed: number } {
  const total = Number(
    stats.total_urls ??
      stats.total_files ??
      stats.total_objects ??
      stats.discovered ??
      0
  )
  const processed = Number(
    stats.processed_urls ??
      stats.processed_files ??
      stats.processed_objects ??
      stats.cursor ??
      0
  )
  return {
    total: Number.isFinite(total) ? total : 0,
    processed: Number.isFinite(processed) ? processed : 0,
  }
}

function formatConnectorSyncCapabilities(info: ConnectorInfo | undefined, t: TranslateFn): string | null {
  if (!info) return null
  const supportsIncremental = Boolean(info.supports_incremental)
  const supportsResume = Boolean(info.supports_resume)
  if (supportsIncremental && supportsResume) return t('syncCapabilities.incrementalAndResume')
  if (supportsIncremental) return t('syncCapabilities.incremental')
  if (supportsResume) return t('syncCapabilities.resumeOnly')
  return t('syncCapabilities.full')
}

function normalizeConnectorRunDocumentId(value: unknown): string | null {
  if (typeof value === 'string') {
    const trimmed = value.trim()
    return trimmed || null
  }
  if (typeof value === 'number' && Number.isFinite(value)) {
    return String(value)
  }
  return null
}

function collectConnectorRunDocumentIds(documents: Array<{ document_id?: unknown }>): string[] {
  return documents
    .map((d) => normalizeConnectorRunDocumentId(d?.document_id))
    .filter((documentId): documentId is string => Boolean(documentId))
}

export function KnowledgeSettingsPanel({
  selectedDatasetId,
  connectorRuns,
  connectorRunsLoading,
  connectorRunsUpdatedAt,
  onLoadConnectorRuns,
  expandedConnectorRunId,
  onToggleExpandedConnectorRun,
  onCancelConnectorRun,
  onResumeConnectorRun,
  onRetryFailedConnectorRun,
}: Readonly<KnowledgeSettingsPanelProps>) {
  const t = useTranslations('KnowledgeSettingsPanel')
  const [runStatusFilter, setRunStatusFilter] = useState<ConnectorRunStatusFilter>('all')
  const [autoRefreshRuns, setAutoRefreshRuns] = useState(false)
  const autoRefreshIntervalMs = 10_000
  const [purgeWorking, setPurgeWorking] = useState(false)
  const [purgeMaxDelete, setPurgeMaxDelete] = useState(1000)
  const [purgePreview, setPurgePreview] = useState<DatasetPurgePreview | null>(null)
  const [purgeError, setPurgeError] = useState<string | null>(null)
  const [connectorInfoById, setConnectorInfoById] = useState<Record<string, ConnectorInfo>>({})

  const runsUpdatedAtLabel = connectorRunsUpdatedAt
    ? new Date(connectorRunsUpdatedAt).toLocaleTimeString()
    : t('connectorRuns.emptyValue')
  const runStatusOptions = (['all', 'pending', 'running', 'failed', 'completed', 'cancelled'] as const).map((value) => ({
    value,
    label: t(`runStatus.${value}`),
  }))
  const embeddingModels = ['text-embedding-v3', 'text-embedding-3-small', 'bge-large-zh']
  const retrievalModes = [
    { value: 'vector', icon: Zap },
    { value: 'fulltext', icon: FileText },
    { value: 'hybrid', icon: Layers },
  ] as const

  useEffect(() => {
    let cancelled = false

    detachPromise((async () => {
      try {
        const items = await connectorApi.listConnectors()
        if (cancelled) return
        const next = Object.fromEntries(
          (items || []).map((item) => [String(item.id || '').toLowerCase(), item])
        )
        setConnectorInfoById(next)
      } catch (err) {
        console.warn('Load connector capabilities failed:', err)
      }
    })())

    return () => {
      cancelled = true
    }
  }, [])

  const copyText = async (text: string, okMsg: string) => {
    try {
      if (!navigator.clipboard?.writeText) {
        toast.error(t('toasts.copyUnsupported'))
        return
      }
      await navigator.clipboard.writeText(text)
      toast.success(okMsg)
    } catch {
      toast.error(t('toasts.copyFailed'))
    }
  }

  const visibleConnectorRuns = useMemo(() => {
    const filtered =
      runStatusFilter === 'all'
        ? connectorRuns
        : connectorRuns.filter((run) => String(run.status || '').toLowerCase() === runStatusFilter)

    // Operational ordering: keep active runs on top; then newest first.
    return [...filtered].sort((a, b) => {
      const statusA = String(a.status || '').toLowerCase()
      const statusB = String(b.status || '').toLowerCase()
      const activeA = statusA === 'pending' || statusA === 'running'
      const activeB = statusB === 'pending' || statusB === 'running'
      if (activeA !== activeB) return activeA ? -1 : 1

      const createdA = Number.isFinite(Date.parse(a.created_at)) ? Date.parse(a.created_at) : 0
      const createdB = Number.isFinite(Date.parse(b.created_at)) ? Date.parse(b.created_at) : 0
      return createdB - createdA
    })
  }, [connectorRuns, runStatusFilter])

  const hasActiveRuns = useMemo(() => {
    return connectorRuns.some((run) => {
      const status = String(run.status || '').toLowerCase()
      return status === 'pending' || status === 'running'
    })
  }, [connectorRuns])

  const expandedRun = useMemo(() => {
    if (!expandedConnectorRunId) return null
    return connectorRuns.find((r) => r.id === expandedConnectorRunId) ?? null
  }, [connectorRuns, expandedConnectorRunId])

  const expandedRunIsVisible = useMemo(() => {
    if (!expandedConnectorRunId) return false
    return visibleConnectorRuns.some((r) => r.id === expandedConnectorRunId)
  }, [expandedConnectorRunId, visibleConnectorRuns])

  useEffect(() => {
    if (!autoRefreshRuns) return
    if (!hasActiveRuns) return

    const id = globalThis.window.setInterval(() => {
      if (document.hidden) return
      if (connectorRunsLoading) return
      detachPromise(onLoadConnectorRuns({ datasetId: selectedDatasetId }))
    }, autoRefreshIntervalMs)

    return () => globalThis.window.clearInterval(id)
  }, [autoRefreshIntervalMs, autoRefreshRuns, connectorRunsLoading, hasActiveRuns, onLoadConnectorRuns, selectedDatasetId])

  useEffect(() => {
    if (!expandedConnectorRunId) return
    if (!connectorRuns.length) return

    const el = document.getElementById(`connector-run-${expandedConnectorRunId}`)
    if (!el) return

    const reduceMotion = globalThis.window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches ?? false
    el.scrollIntoView({ block: 'start', behavior: reduceMotion ? 'auto' : 'smooth' })
  }, [connectorRuns, expandedConnectorRunId])

  const runDatasetPurge = async (params: { dry_run: boolean }) => {
    if (!selectedDatasetId) {
      toast.error(t('toasts.selectDatasetFirst'))
      return
    }

    setPurgeWorking(true)
    setPurgeError(null)
    try {
      const maxDelete = Math.max(1, Math.min(10_000, Number(purgeMaxDelete) || 1000))
      const res = await datasetApi.purge(selectedDatasetId, {
        dry_run: params.dry_run,
        max_delete: maxDelete,
      })
      setPurgePreview(res)
      if (params.dry_run) {
        toast.success(t('toasts.purgePreviewReady', { eligible: String(res?.eligible ?? t('connectorRuns.emptyValue')) }))
      } else {
        toast.success(t('toasts.purgeCompleted', { deleted: String(res?.deleted ?? t('connectorRuns.emptyValue')) }))
      }
    } catch (err: any) {
      const msg = formatApiError(err, t('toasts.purgeFailed'))
      setPurgeError(msg)
      toast.error(msg)
    } finally {
      setPurgeWorking(false)
    }
  }

  return (
    <div className="max-w-3xl mx-auto animate-in fade-in slide-in-from-bottom-2 duration-300 motion-reduce:animate-none motion-reduce:transition-none">
      <Panel padding="none" className="rounded-xl overflow-hidden">
        <div className="p-6 border-b border-border/60 bg-muted/20">
          <h3 className="text-lg font-bold text-foreground">{t("header.title")}</h3>
          <p className="text-sm text-muted-foreground mt-1">{t('header.description')}</p>
        </div>

        <div className="p-8 space-y-8">
          <div className="space-y-3">
            <div className="text-sm font-semibold text-foreground">{t('embedding.title')}</div>
            <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
              {embeddingModels.map((model) => (
                <div key={model} className="relative">
                  <input type="radio" name="model" id={model} className="peer sr-only" defaultChecked={model === 'text-embedding-v3'} />
                  <label
                    htmlFor={model}
                    className="flex flex-col p-4 border-2 border-border/60 rounded-xl cursor-pointer transition-colors hover:border-border peer-checked:border-primary peer-checked:bg-primary/10"
                  >
                    <span className="font-medium text-sm text-foreground">{model}</span>
                    <span className="text-xs text-muted-foreground mt-1">{t('embedding.modelHint')}</span>
                  </label>
                </div>
              ))}
            </div>
          </div>

          <div className="h-px bg-border/60" />

          <div className="space-y-3">
            <div className="text-sm font-semibold text-foreground">{t('retrieval.title')}</div>
            <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
              {retrievalModes.map((mode) => (
                <div key={mode.value} className="relative">
                  <input
                    type="radio"
                    name="retrieval_mode"
                    id={mode.value}
                    className="peer sr-only"
                    defaultChecked={mode.value === 'hybrid'}
                  />
                  <label
                    htmlFor={mode.value}
                    className="flex flex-col p-4 border-2 border-border/60 rounded-xl cursor-pointer transition-colors hover:border-border peer-checked:border-primary peer-checked:bg-primary/10 h-full"
                  >
                    <div className="flex items-center gap-2 mb-2">
                      <mode.icon className="w-4 h-4 text-primary" />
                      <span className="font-medium text-sm text-foreground">{t(`retrieval.options.${mode.value}.label`)}</span>
                    </div>
                    <span className="text-xs text-muted-foreground leading-relaxed">{t(`retrieval.options.${mode.value}.description`)}</span>
                  </label>
                </div>
              ))}
            </div>
          </div>

          <div className="h-px bg-border/60" />

          <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
            <div className="space-y-3">
              <div className="flex justify-between">
                <div className="text-sm font-semibold text-foreground">{t('sliders.topK.title')}</div>
                <span className="text-sm font-mono text-primary">5</span>
              </div>
              <input
                type="range"
                min="1"
                max="20"
                defaultValue="5"
                className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
              />
              <p className="text-xs text-muted-foreground">{t('sliders.topK.description')}</p>
            </div>

            <div className="space-y-3">
              <div className="flex justify-between">
                <div className="text-sm font-semibold text-foreground">{t('sliders.similarity.title')}</div>
                <span className="text-sm font-mono text-primary">0.7</span>
              </div>
              <input
                type="range"
                min="0"
                max="1"
                step="0.1"
                defaultValue="0.7"
                className="w-full h-2 bg-muted rounded-lg appearance-none cursor-pointer accent-primary"
              />
              <p className="text-xs text-muted-foreground">{t('sliders.similarity.description')}</p>
            </div>
          </div>

          <div className="h-px bg-border/60" />

          <div className="space-y-3">
            <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
              <div>
                <div className="text-sm font-semibold text-foreground">{t("connectorRuns.title")}</div>
                <p className="text-xs text-muted-foreground mt-1">
                  {t('connectorRuns.description')}
                </p>
              </div>
              <div className="flex items-center gap-2">
                <Select value={runStatusFilter} onValueChange={(v) => setRunStatusFilter(v as ConnectorRunStatusFilter)}>
                  <SelectTrigger className="h-9 w-40" aria-label={t("connectorRuns.filter.ariaLabel")}>
                    <SelectValue placeholder={t('connectorRuns.filter.placeholder')} />
                  </SelectTrigger>
                  <SelectContent>
                    {runStatusOptions.map((option) => (
                      <SelectItem key={option.value} value={option.value}>
                        {option.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <Button
                  variant="outline"
                  className="gap-2"
                  onClick={() => detachPromise(onLoadConnectorRuns({ datasetId: selectedDatasetId }))}
                  disabled={connectorRunsLoading}
                >
                  <RefreshCw className={cn('w-4 h-4', connectorRunsLoading && 'animate-spin motion-reduce:animate-none')} />
                  {t('connectorRuns.actions.refresh')}
                </Button>
                <Button
                  type="button"
                  variant={autoRefreshRuns ? 'secondary' : 'outline'}
                  className="h-9"
                  aria-pressed={autoRefreshRuns}
                  onClick={() => setAutoRefreshRuns((v) => !v)}
                  disabled={!hasActiveRuns && !autoRefreshRuns}
                  title={!hasActiveRuns && !autoRefreshRuns ? t('connectorRuns.autoRefresh.onlyWhenActive') : undefined}
                >
                  {t("connectorRuns.autoRefresh.label")}
                </Button>
              </div>
            </div>
            <div className="text-[11px] text-muted-foreground">
              {t('connectorRuns.scopeLabel')}:{' '}
              <span
                className="font-mono tabular-nums"
                title={
                  selectedDatasetId
                    ? t('connectorRuns.scopeTitleScoped', { datasetId: selectedDatasetId })
                    : t('connectorRuns.scopeTitleAll')
                }
              >
                {selectedDatasetId || t('connectorRuns.allDatasets')}
              </span>
              <span className="text-muted-foreground/40">{` · ${t('connectorRuns.lastRefreshLabel')}: `}</span>
              <span className="font-mono tabular-nums">{runsUpdatedAtLabel}</span>
              <span className="text-muted-foreground/40">{` · ${t('connectorRuns.autoRefresh.statusLabel')}: `}</span>
              <span className="font-mono tabular-nums">
                {(() => {
    if (autoRefreshRuns) {
        if (hasActiveRuns) {
            return t('connectorRuns.autoRefresh.onInterval', { seconds: Math.round(autoRefreshIntervalMs / 1000) });
        }
        else {
            return t('connectorRuns.autoRefresh.waiting');
        }
    }
    else {
        return t('connectorRuns.autoRefresh.off');
    }
})()}
              </span>
            </div>

            {(() => {
    if (connectorRunsLoading) {
        return (<div className="rounded-xl border border-border/60 bg-background/60 p-4 text-sm text-muted-foreground">
                {t('connectorRuns.loading')}
              </div>);
    }
    else if (connectorRuns.length === 0) {
            return (<div className="rounded-xl border border-border/60 bg-background/60 p-4 text-sm text-muted-foreground">
                {t("connectorRuns.zeroState.description")}
              </div>);
        }
        else if (visibleConnectorRuns.length === 0) {
                return (<div className="rounded-xl border border-border/60 bg-background/60 p-4 text-sm text-muted-foreground flex items-center justify-between gap-3">
                <div>{t("connectorRuns.empty.description")}</div>
                <Button type="button" variant="outline" size="sm" onClick={() => setRunStatusFilter('all')}>
                  {t('connectorRuns.empty.clearFilters')}
                </Button>
              </div>);
            }
            else {
                return (<div className="space-y-3">
                {expandedConnectorRunId && !expandedRunIsVisible ? (<div className="rounded-xl border border-border/60 bg-muted/20 p-3 text-sm">
                    {expandedRun ? (<div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                        <div className="text-muted-foreground">
                          {t('connectorRuns.hidden.selectedRunHidden')} <span className="font-mono tabular-nums">{expandedConnectorRunId}</span>
                        </div>
                        <Button type="button" variant="outline" size="sm" onClick={() => setRunStatusFilter('all')}>
                          {t('connectorRuns.empty.clearFilters')}
                        </Button>
                      </div>) : (<div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                        <div className="text-muted-foreground">
                          {t('connectorRuns.hidden.selectedRunMissing')}{' '}
                          <span className="font-mono tabular-nums">{expandedConnectorRunId}</span>
                        </div>
                        <div className="flex items-center gap-2">
                          <Button type="button" variant="outline" size="sm" onClick={() => detachPromise(onLoadConnectorRuns({ datasetId: selectedDatasetId }))}>
                            {t('connectorRuns.actions.refresh')}
                          </Button>
                          <Button type="button" variant="outline" size="sm" onClick={() => onToggleExpandedConnectorRun(expandedConnectorRunId)}>
                            {t("connectorRuns.location.clear")}
                          </Button>
                        </div>
                      </div>)}
                  </div>) : null}
                {visibleConnectorRuns.map((run) => {
                        const badge = getConnectorRunBadge(run.status, t);
                        const status = String(run.status || '').toLowerCase();
                        const stats = run.stats ?? {};
                        const created = Number(stats.created || 0);
                        const failed = Number(stats.failed || 0);
                        const progress = getConnectorRunProgress(stats);
                        const totalItems = progress.total;
                        const processedItems = progress.processed;
                        const durationStartAt = run.started_at ?? run.created_at;
                        const durationEndAt = run.finished_at ? run.finished_at : new Date().toISOString();
                        const durationStartMs = Number.isFinite(Date.parse(durationStartAt)) ? Date.parse(durationStartAt) : null;
                        const durationEndMs = Number.isFinite(Date.parse(durationEndAt)) ? Date.parse(durationEndAt) : null;
                        const durationLabel = durationStartMs !== null && durationEndMs !== null && durationEndMs >= durationStartMs
                            ? formatDurationMs(durationEndMs - durationStartMs)
                            : null;
                        const progressPct = totalItems > 0 ? Math.max(0, Math.min(100, Math.round((processedItems / totalItems) * 100))) : 0;
                        const errors: any[] = Array.isArray(stats.errors) ? stats.errors : [];
                        const errorGroups: any[] = Array.isArray(stats.error_groups) ? stats.error_groups : [];
                        const isActive = status === 'pending' || status === 'running';
                        const canRetryFailed = !isActive && failed > 0;
                        const connectorInfo = connectorInfoById[String(run.connector_id || '').toLowerCase()];
                        const syncCapabilities = formatConnectorSyncCapabilities(connectorInfo, t);
                        const supportsResume = Boolean(connectorInfo?.supports_resume);
                        const hasRemainingResumeWork = totalItems > 0 ? totalItems > processedItems : processedItems > 0;
                        const canResume = !isActive &&
                            supportsResume &&
                            (status === 'cancelled' || status === 'failed') &&
                            hasRemainingResumeWork;
                        const documents = Array.isArray(run.documents) ? run.documents : [];
                        const hasDocs = documents.length > 0;
                        const acl = run.acl_summary;
                        const aclDocsTotal = Number(acl?.documents_total || 0);
                        const aclModeRaw = String(acl?.mode || '').trim();
                        const aclMode = aclModeRaw ? aclModeRaw.toLowerCase() : '';
                        const aclModeLabel = aclMode ? formatAclModeLabel(aclMode, t) : null;
                        const aclMemberRange = formatAclCountRange(acl?.partial_member_count_min, acl?.partial_member_count_max);
                        const aclGroupRange = formatAclCountRange(acl?.partial_group_count_min, acl?.partial_group_count_max);
                        const aclBreakdown = aclMode === 'mixed' ? formatAclModeBreakdown(acl?.access_mode_counts, t) : null;
                        const aclHasAllowlist = Number(acl?.partial_members_doc_count || 0) > 0 || aclMemberRange !== null || aclGroupRange !== null;
                        return (<div key={run.id} id={`connector-run-${run.id}`} className={cn('rounded-xl border border-border/60 bg-background/60 p-4 scroll-mt-6', expandedConnectorRunId === run.id && 'ring-1 ring-primary/30')}>
                      <div className="flex items-start justify-between gap-4">
                        <div className="min-w-0">
                          <div className="flex flex-wrap items-center gap-2">
                            <StatusBadge status={badge.status} label={badge.label} dense/>
                            <button type="button" className="text-xs font-mono text-muted-foreground truncate hover:text-foreground underline underline-offset-4" onClick={() => detachPromise(copyText(run.id, t('toasts.copyRunId')))} title={t('connectorRuns.actions.copyRunIdTitle')}>
                              {run.id}
                            </button>
                          </div>
                          <div className="mt-1 text-xs text-muted-foreground">
                            {formatDate(run.created_at)} · {run.connector_id} · {t('connectorRuns.datasetLabel')} {run.dataset_id || '-'}
                            {durationLabel ? (<>
                                <span className="text-muted-foreground/40">{` · ${t('connectorRuns.durationLabel')} `}</span>
                                <span className="font-mono tabular-nums">{durationLabel}</span>
                              </>) : null}
                          </div>
                          <div className="mt-2 text-xs text-foreground/80">
                            {t('connectorRuns.metrics.created')} <span className="font-mono">{created}</span> · {t('connectorRuns.metrics.failed')}{' '}
                            <span className={cn('font-mono', failed > 0 && 'text-destructive')}>{failed}</span>
                          </div>

                          {syncCapabilities ? (<div className="mt-1 text-xs text-muted-foreground">
                              {t('connectorRuns.metrics.sync')} <span className="font-mono">{syncCapabilities}</span>
                            </div>) : null}

                          {aclModeLabel && aclDocsTotal > 0 ? (<div className="mt-1 text-xs text-muted-foreground">
                              {t('connectorRuns.metrics.acl')} <span className="font-mono">{aclModeLabel}</span>
                              {aclBreakdown ? <span className="text-muted-foreground/60">（{aclBreakdown}）</span> : null}
                              <span className="text-muted-foreground/40">{` · ${t('connectorRuns.metrics.documents')} `}</span>
                              <span className="font-mono tabular-nums">{aclDocsTotal}</span>
                              {aclHasAllowlist ? (<>
                                  <span className="text-muted-foreground/40">{` · ${t('connectorRuns.metrics.members')} `}</span>
                                  <span className="font-mono tabular-nums">{aclMemberRange ?? t('connectorRuns.emptyValue')}</span>
                                  <span className="text-muted-foreground/40">{` · ${t('connectorRuns.metrics.groups')} `}</span>
                                  <span className="font-mono tabular-nums">{aclGroupRange ?? t('connectorRuns.emptyValue')}</span>
                                </>) : null}
                            </div>) : null}

                          <div className="mt-3 flex flex-wrap items-center gap-2">
                            <Button type="button" variant="outline" size="sm" className="h-7 px-2 gap-1.5" onClick={() => {
                                const url = new URL(`/knowledge?tab=settings&run=${run.id}`, globalThis.window.location.origin).toString();
                                detachPromise(copyText(url, t('toasts.copyTaskLink')));
                            }}>
                              <Link2 className="h-3.5 w-3.5"/>
                              {t("connectorRuns.actions.copyLink")}
                            </Button>
                          </div>

                          {totalItems > 0 ? (<div className="mt-2">
                              <div className="flex items-center justify-between text-xs text-muted-foreground">
                                <span>{t('connectorRuns.metrics.progress')}</span>
                                <span className="font-mono">
                                  {processedItems}/{totalItems} ({progressPct}%)
                                </span>
                              </div>
                              <div className="mt-1 h-2 w-full rounded-full bg-muted/60 overflow-hidden">
                                <div className={cn('h-2 w-full rounded-full origin-left transition-transform duration-200 ease-out motion-reduce:transition-none', failed > 0 ? 'bg-destructive/70' : 'bg-primary/70')} style={{ transform: `scaleX(${progressPct / 100})` }}/>
                              </div>
                            </div>) : null}

                          {run.error_message ? (<div className="mt-2 text-xs text-destructive">{run.error_message}</div>) : null}

                          {errorGroups.length > 0 ? (<div className="mt-2 text-xs text-muted-foreground">
                              <div className="font-medium text-foreground/80">{t('connectorRuns.errorGroupsTitle')}</div>
                              <div className="mt-1 space-y-1">
                                {errorGroups.slice(0, 3).map((g) => (<div key={`${String(g?.code || 'error')}-${String(g?.error || '')}`} className="font-mono truncate">
                                    [{String(g?.code || 'error')}] x{Number(g?.count || 0)} —{' '}
                                    {String(g?.error || '').slice(0, 140)}
                                  </div>))}
                              </div>
                            </div>) : null}

                          {errors.length > 0 ? (<div className="mt-2 text-xs text-muted-foreground">
                              <div className="font-medium text-foreground/80">{t('connectorRuns.errorSamplesTitle')}</div>
                              <div className="mt-1 space-y-1">
                                {errors.slice(0, 3).map((e) => (<div key={`${String(e?.url || '')}-${String(e?.code || '')}-${String(e?.error || '')}`} className="font-mono truncate">
                                    {String(e?.url || '').slice(0, 80)} — {e?.code ? `[${String(e.code)}] ` : ''}
                                    {String(e?.error || '').slice(0, 120)}
                                  </div>))}
                              </div>
                            </div>) : null}

                          {hasDocs ? (<div className="mt-3">
                              <button type="button" className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground/80" onClick={() => onToggleExpandedConnectorRun(run.id)}>
                                {expandedConnectorRunId === run.id ? (<ChevronDown className="h-4 w-4"/>) : (<ChevronRight className="h-4 w-4"/>)}
                                {t('connectorRuns.documentList.toggle', { count: documents.length })}
                              </button>

                              {expandedConnectorRunId === run.id ? (<div className="mt-2 rounded-lg border border-border/60 bg-background/40 p-3">
	                                    <div className="flex items-center justify-between gap-2">
	                                      <div className="text-xs font-medium text-foreground/80">{t('connectorRuns.documentList.title')}</div>
	                                      <Button type="button" variant="outline" size="sm" className="h-7 px-2 gap-1.5" onClick={() => {
	                                        const ids = collectConnectorRunDocumentIds(documents);
	                                        detachPromise(copyText(ids.join('\n'), t('toasts.copyDocumentIds')));
	                                    }}>
	                                        <Copy className="h-3.5 w-3.5"/>
	                                        {t('connectorRuns.actions.copyIds')}
                                    </Button>
                                  </div>
                                  <div className="mt-2 space-y-1">
                                    {documents.slice(0, 15).map((d, index) => {
                                      const documentId = normalizeConnectorRunDocumentId(d?.document_id) || ''
                                      return (
                                        <div key={documentId || `${run.id}:${index}`} className="flex items-start justify-between gap-3">
                                          <div className="min-w-0">
                                            <div className="text-[11px] font-mono text-foreground/90 truncate">
                                              {documentId}
                                            </div>
                                            {d?.source_ref ? (<div className="mt-0.5 text-[10px] text-muted-foreground font-mono truncate">
                                                {String(d.source_ref)}
                                              </div>) : null}
                                          </div>
                                          <div className="shrink-0 text-[10px] font-mono rounded-full border border-border/60 bg-background px-2 py-0.5">
                                            {String(d?.status || t('connectorRuns.documentList.defaultStatus'))}
                                          </div>
                                        </div>
                                      )
                                    })}
                                    {documents.length > 15 ? (<div className="text-[10px] text-muted-foreground">
                                        …(+{documents.length - 15})
                                      </div>) : null}
                                  </div>
                                </div>) : null}
                            </div>) : null}
                        </div>

                        <div className="flex flex-col gap-2">
                          {isActive ? (<AlertDialog>
                              <AlertDialogTrigger asChild>
                                <Button variant="outline" className="gap-2">
                                  <Trash2 className="w-4 h-4"/>
                                  {t('connectorRuns.actions.cancel')}
                                </Button>
                              </AlertDialogTrigger>
                              <AlertDialogContent>
                                <AlertDialogHeader>
                                  <AlertDialogTitle>{t('connectorRuns.dialogs.cancel.title')}</AlertDialogTitle>
                                  <AlertDialogDescription>
                                    {t('connectorRuns.dialogs.cancel.description')} <span className="font-mono">{run.id.slice(0, 8)}</span>
                                  </AlertDialogDescription>
                                </AlertDialogHeader>
                                <AlertDialogFooter>
                                  <AlertDialogCancel>{t('connectorRuns.dialogs.cancel.back')}</AlertDialogCancel>
                                  <AlertDialogAction onClick={() => detachPromise(onCancelConnectorRun(run.id))}>
                                    {t('connectorRuns.dialogs.cancel.confirm')}
                                  </AlertDialogAction>
                                </AlertDialogFooter>
                              </AlertDialogContent>
                            </AlertDialog>) : null}

                          {canResume ? (<AlertDialog>
                              <AlertDialogTrigger asChild>
                                <Button variant="outline" className="gap-2">
                                  <Play className="w-4 h-4"/>
                                  {t('connectorRuns.actions.resume')}
                                </Button>
                              </AlertDialogTrigger>
                              <AlertDialogContent>
                                <AlertDialogHeader>
                                  <AlertDialogTitle>{t('connectorRuns.dialogs.resume.title')}</AlertDialogTitle>
                                  <AlertDialogDescription>
                                    {t('connectorRuns.dialogs.resume.description')} <span className="font-mono">{run.id.slice(0, 8)}</span>
                                  </AlertDialogDescription>
                                </AlertDialogHeader>
                                <AlertDialogFooter>
                                  <AlertDialogCancel>{t('connectorRuns.dialogs.resume.back')}</AlertDialogCancel>
                                  <AlertDialogAction onClick={() => detachPromise(onResumeConnectorRun(run.id))}>{t('connectorRuns.dialogs.resume.confirm')}</AlertDialogAction>
                                </AlertDialogFooter>
                              </AlertDialogContent>
                            </AlertDialog>) : null}

                          {canRetryFailed ? (<AlertDialog>
                              <AlertDialogTrigger asChild>
                                <Button variant="outline" className="gap-2">
                                  <RotateCcw className="w-4 h-4"/>
                                  {t('connectorRuns.actions.retryFailed')}
                                </Button>
                              </AlertDialogTrigger>
                              <AlertDialogContent>
                                <AlertDialogHeader>
                                  <AlertDialogTitle>{t('connectorRuns.dialogs.retry.title')}</AlertDialogTitle>
                                  <AlertDialogDescription>
                                    {t('connectorRuns.dialogs.retry.description')} <span className="font-mono">{run.id.slice(0, 8)}</span>
                                  </AlertDialogDescription>
                                </AlertDialogHeader>
                                <AlertDialogFooter>
                                  <AlertDialogCancel>{t('connectorRuns.dialogs.retry.back')}</AlertDialogCancel>
                                  <AlertDialogAction onClick={() => detachPromise(onRetryFailedConnectorRun(run.id))}>
                                    {t('connectorRuns.dialogs.retry.confirm')}
                                  </AlertDialogAction>
                                </AlertDialogFooter>
                              </AlertDialogContent>
                            </AlertDialog>) : null}
                        </div>
                      </div>
                    </div>);
                    })}
              </div>);
            }
})()}
          </div>

          <div className="h-px bg-border/60" />

          <div className="space-y-3">
            <div>
              <div className="text-sm font-semibold text-foreground">{t('dangerZone.title')}</div>
              <p className="text-xs text-muted-foreground mt-1">
                {t('dangerZone.description')} <span className="font-mono">dry_run</span> {t('dangerZone.descriptionSuffix')}
              </p>
            </div>

            <AlertDialog
              onOpenChange={(open) => {
                if (open) {
                  setPurgePreview(null)
                  setPurgeMaxDelete(1000)
                  setPurgeError(null)
                }
              }}
            >
              <AlertDialogTrigger asChild>
                <Button
                  type="button"
                  variant="outline"
                  className="gap-2"
                  disabled={!selectedDatasetId || purgeWorking}
                  title={selectedDatasetId ? undefined : t('dangerZone.selectDatasetTitle')}
                >
                  <Trash2 className="w-4 h-4" />
                  {t("dangerZone.trigger")}
                </Button>
              </AlertDialogTrigger>
              <AlertDialogContent>
                <AlertDialogHeader>
                  <AlertDialogTitle>{t('dangerZone.dialog.title')}</AlertDialogTitle>
                  <AlertDialogDescription>
                    {t('dangerZone.dialog.descriptionPrefix')} <span className="font-mono">POST /api/v1/datasets/{'{id}'}/purge</span>{' '}
                    {t('dangerZone.dialog.descriptionMiddle')} <span className="font-mono">max_delete</span> {t('dangerZone.dialog.descriptionSuffix')}
                  </AlertDialogDescription>
                </AlertDialogHeader>

                <div className="space-y-3">
                  <div className="flex items-center gap-2">
                    <div className="text-xs text-muted-foreground shrink-0">{t('dangerZone.maxDelete')}</div>
                    <Input
                      type="number"
                      className="h-9"
                      min={1}
                      max={10_000}
                      value={purgeMaxDelete}
                      onChange={(e) => setPurgeMaxDelete(Number(e.target.value) || 0)}
                      inputMode="numeric"
                    />
                    <Button
                      type="button"
                      variant="secondary"
                      className="h-9"
                      disabled={purgeWorking}
                      onClick={() => detachPromise(runDatasetPurge({ dry_run: true }))}
                    >
                      {t('dangerZone.preview')}
                    </Button>
                  </div>

                  {purgePreview ? (
                    <div className="rounded-lg border border-border/60 bg-muted/10 p-3 text-xs">
                      <div className="flex items-center justify-between gap-3">
                        <div className="text-muted-foreground">{t('dangerZone.previewSummaryLabel')}</div>
                        <div className="font-mono tabular-nums text-foreground/90">
                          eligible={String(purgePreview.eligible ?? t('connectorRuns.emptyValue'))} deleted={String(purgePreview.deleted ?? 0)}
                        </div>
                      </div>
                      <div className="mt-1 text-[11px] text-muted-foreground">
                        {t('dangerZone.datasetLabel')}: <span className="font-mono">{String(purgePreview.dataset_id || selectedDatasetId).slice(0, 8)}</span>
                      </div>
                    </div>
                  ) : (
                    <div className="text-xs text-muted-foreground">
                      {t('dangerZone.previewHint')}
                    </div>
                  )}

                  {purgeError ? (
                    <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
                      {purgeError}
                    </div>
                  ) : null}
                </div>

                <AlertDialogFooter>
                  <AlertDialogCancel disabled={purgeWorking}>{t('dangerZone.cancel')}</AlertDialogCancel>
                  <AlertDialogAction
                    disabled={purgeWorking}
                    onClick={() => detachPromise(runDatasetPurge({ dry_run: false }))}
                  >
                    {t('dangerZone.confirm')}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
          </div>
        </div>

        <div className="p-6 bg-muted/20 border-t border-border/60 flex justify-end">
          <Button className="gap-2">
            <Settings className="w-4 h-4" />
            {t('actions.saveAll')}
          </Button>
        </div>
      </Panel>
    </div>
  )
}
