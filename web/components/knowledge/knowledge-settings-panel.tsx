'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { useTranslations } from 'next-intl'
import {
  ChevronDown,
  ChevronRight,
  Copy,
  Link2,
  Loader2,
  Play,
  RefreshCw,
  RotateCcw,
  Settings,
  TriangleAlert,
  Trash2,
} from 'lucide-react'
import { toast } from 'sonner'

import type { ConnectorInfo, ConnectorRunOut } from '@/types'
import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
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
import { connectorApi, datasetApi, settingsApi, type SystemSettings } from '@/lib/api'
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
}

type KnowledgeConnectorRunsPanelProps = {
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

type KnowledgeSettingsConfig = Pick<SystemSettings, 'embedding' | 'rag'>
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

function cloneSettingsConfig(config: KnowledgeSettingsConfig): KnowledgeSettingsConfig {
  return {
    embedding: { ...config.embedding },
    rag: { ...config.rag },
  }
}

function buildSettingsConfig(settings: SystemSettings): KnowledgeSettingsConfig {
  return {
    embedding: { ...settings.embedding },
    rag: { ...settings.rag },
  }
}

function clampTopK(value: unknown): number {
  const next = Number(value)
  if (!Number.isFinite(next)) return 5
  return Math.max(1, Math.min(20, Math.round(next)))
}

function clampSimilarityThreshold(value: unknown): number {
  const next = Number(value)
  if (!Number.isFinite(next)) return 0.7
  return Math.max(0, Math.min(1, Number(next.toFixed(2))))
}

const EMBEDDING_MODEL_OPTIONS = ['text-embedding-v3', 'text-embedding-3-small', 'bge-large-zh'] as const

const EMBEDDING_MODEL_META: Record<(typeof EMBEDDING_MODEL_OPTIONS)[number], { description: string; chips: string[] }> = {
  'text-embedding-v3': {
    description: '兼顾精度与成本，适合作为系统默认模型。',
    chips: ['推荐默认', '中英混合', '通用语义'],
  },
  'text-embedding-3-small': {
    description: '响应更轻量，适合成本敏感或高频检索场景。',
    chips: ['低成本', '响应快', 'OpenAI 兼容'],
  },
  'bge-large-zh': {
    description: '中文语义更强，适合中文知识库和条款型文本。',
    chips: ['中文增强', '本地可部署', '长文本友好'],
  },
}

export function KnowledgeSettingsPanel({ selectedDatasetId }: Readonly<KnowledgeSettingsPanelProps>) {
  const t = useTranslations('KnowledgeSettingsPanel')
  const [savedConfig, setSavedConfig] = useState<KnowledgeSettingsConfig | null>(null)
  const [draftConfig, setDraftConfig] = useState<KnowledgeSettingsConfig | null>(null)
  const [settingsLoading, setSettingsLoading] = useState(true)
  const [settingsError, setSettingsError] = useState<string | null>(null)
  const [isSavingSettings, setIsSavingSettings] = useState(false)
  const [lastSavedAt, setLastSavedAt] = useState<number | null>(null)
  const [confirmEmbeddingSaveOpen, setConfirmEmbeddingSaveOpen] = useState(false)
  const [purgeWorking, setPurgeWorking] = useState(false)
  const [purgeMaxDelete, setPurgeMaxDelete] = useState(1000)
  const [purgePreview, setPurgePreview] = useState<DatasetPurgePreview | null>(null)
  const [purgeError, setPurgeError] = useState<string | null>(null)

  const loadSettings = useCallback(async () => {
    setSettingsLoading(true)
    setSettingsError(null)
    try {
      const settings = await settingsApi.get()
      const nextConfig = buildSettingsConfig(settings)
      setSavedConfig(nextConfig)
      setDraftConfig(cloneSettingsConfig(nextConfig))
    } catch (err) {
      setSettingsError(formatApiError(err, t('toasts.loadFailed')))
    } finally {
      setSettingsLoading(false)
    }
  }, [t])

  useEffect(() => {
    detachPromise(loadSettings())
  }, [loadSettings])

  const isDirty =
    savedConfig !== null &&
    draftConfig !== null &&
    (
      savedConfig.embedding.model !== draftConfig.embedding.model ||
      savedConfig.rag.retrieval_top_k !== draftConfig.rag.retrieval_top_k ||
      savedConfig.rag.similarity_threshold !== draftConfig.rag.similarity_threshold
    )

  const changedCount = useMemo(() => {
    if (!savedConfig || !draftConfig) return 0
    let count = 0
    if (savedConfig.embedding.model !== draftConfig.embedding.model) count += 1
    if (savedConfig.rag.retrieval_top_k !== draftConfig.rag.retrieval_top_k) count += 1
    if (savedConfig.rag.similarity_threshold !== draftConfig.rag.similarity_threshold) count += 1
    return count
  }, [draftConfig, savedConfig])

  const embeddingModelChanged =
    savedConfig !== null && draftConfig !== null && savedConfig.embedding.model !== draftConfig.embedding.model

  const saveSettings = async () => {
    if (!draftConfig) return

    const nextConfig = cloneSettingsConfig(draftConfig)
    const changedEmbedding = Boolean(savedConfig && savedConfig.embedding.model !== nextConfig.embedding.model)

    setIsSavingSettings(true)
    setSettingsError(null)
    try {
      await settingsApi.update({
        embedding: nextConfig.embedding,
        rag: nextConfig.rag,
      })
      setSavedConfig(nextConfig)
      setDraftConfig(cloneSettingsConfig(nextConfig))
      setLastSavedAt(Date.now())
      toast.success(changedEmbedding ? t('toasts.saveSuccessEmbeddingChanged') : t('toasts.saveSuccess'))
    } catch (err) {
      const msg = formatApiError(err, t('toasts.saveFailed'))
      setSettingsError(msg)
      toast.error(msg)
    } finally {
      setIsSavingSettings(false)
      setConfirmEmbeddingSaveOpen(false)
    }
  }

  const handleSaveSettings = async () => {
    if (!draftConfig || !savedConfig || !isDirty) return
    if (embeddingModelChanged) {
      setConfirmEmbeddingSaveOpen(true)
      return
    }
    await saveSettings()
  }

  const handleResetDraft = () => {
    if (!savedConfig) return
    setDraftConfig(cloneSettingsConfig(savedConfig))
    setSettingsError(null)
  }

  const updateEmbeddingModel = (model: (typeof EMBEDDING_MODEL_OPTIONS)[number]) => {
    setDraftConfig((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        embedding: {
          ...prev.embedding,
          model,
        },
      }
    })
  }

  const updateTopK = (value: unknown) => {
    setDraftConfig((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        rag: {
          ...prev.rag,
          retrieval_top_k: clampTopK(value),
        },
      }
    })
  }

  const updateSimilarity = (value: unknown) => {
    setDraftConfig((prev) => {
      if (!prev) return prev
      return {
        ...prev,
        rag: {
          ...prev.rag,
          similarity_threshold: clampSimilarityThreshold(value),
        },
      }
    })
  }

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
    } catch (err) {
      const msg = formatApiError(err, t('toasts.purgeFailed'))
      setPurgeError(msg)
      toast.error(msg)
    } finally {
      setPurgeWorking(false)
    }
  }

  return (
    <div className="w-full animate-in fade-in slide-in-from-bottom-2 duration-300 motion-reduce:animate-none motion-reduce:transition-none">
      <div className="overflow-hidden">
        <div className="border-b border-border/55 bg-muted/[0.12] px-5 py-4 md:px-6">
          <div className="space-y-2.5">
            <div className="space-y-1">
              <h3 className="text-[15px] font-semibold text-foreground">{t("header.title")}</h3>
              <p className="max-w-[42rem] text-[13px] leading-5 text-muted-foreground">{t('header.description')}</p>
            </div>

            <div className="flex flex-wrap items-center gap-2 text-[11px] leading-5">
              <span className="inline-flex items-center gap-1.5 rounded-full bg-foreground/[0.035] px-2.5 py-1 font-medium text-foreground/75">
                <span className="h-1.5 w-1.5 rounded-full bg-primary/50" />
                {t('scope.systemDefault')}
              </span>

              <span
                className={cn(
                  'inline-flex items-center gap-1.5 rounded-full px-2.5 py-1 font-medium',
                  selectedDatasetId
                    ? 'bg-foreground/[0.035] text-muted-foreground'
                    : 'bg-warning/[0.06] text-foreground/72 ring-1 ring-warning/10'
                )}
              >
                <span
                  className={cn(
                    'h-1.5 w-1.5 rounded-full',
                    selectedDatasetId ? 'bg-muted-foreground/35' : 'bg-warning/75'
                  )}
                />
                {selectedDatasetId
                  ? t('scope.datasetPurgeScoped', { datasetId: selectedDatasetId })
                  : t('scope.datasetPurgeUnselected')}
              </span>
            </div>
          </div>
        </div>

        <div className="space-y-6 p-5 md:p-6">
          <Alert
            variant="warning"
            className="border-warning/15 border-l-warning/40 bg-warning/[0.045] text-muted-foreground [&>svg]:text-warning/65"
          >
            <TriangleAlert className="h-3.5 w-3.5" />
            <AlertTitle className="text-[13px] font-medium text-foreground/80">
              {t('alerts.embeddingWarningTitle')}
            </AlertTitle>
            <AlertDescription className="text-[13px] leading-6 text-muted-foreground/90">
              {t('alerts.embeddingWarningDescription')}
            </AlertDescription>
          </Alert>

          {settingsError ? (
            <Alert variant="destructive">
              <TriangleAlert className="h-4 w-4" />
              <AlertTitle>{t('alerts.loadFailedTitle')}</AlertTitle>
              <AlertDescription className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
                <span>{settingsError}</span>
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="self-start"
                  onClick={() => detachPromise(loadSettings())}
                >
                  <RefreshCw className="h-3.5 w-3.5" />
                  {t('actions.reload')}
                </Button>
              </AlertDescription>
            </Alert>
          ) : null}

          {settingsLoading && !draftConfig ? (
            <div className="space-y-5">
              <div className="space-y-3">
                {[0, 1, 2].map((item) => (
                  <div key={item} className="animate-pulse rounded-[18px] border border-border/60 bg-background/70 px-3.5 py-3.5">
                    <div className="grid grid-cols-[1rem_minmax(0,1fr)] gap-3">
                      <div className="mt-1 h-4 w-4 rounded-full border border-muted/60 bg-muted/35" />
                      <div className="space-y-2">
                        <div className="flex flex-wrap items-center gap-2">
                          <div className="h-4 w-36 rounded bg-muted/60" />
                          <div className="h-5 w-24 rounded-full bg-muted/40" />
                        </div>
                        <div className="h-3 w-full rounded bg-muted/50" />
                        <div className="flex flex-wrap gap-3">
                          <div className="h-3 w-16 rounded bg-muted/40" />
                          <div className="h-3 w-14 rounded bg-muted/40" />
                          <div className="h-3 w-20 rounded bg-muted/40" />
                        </div>
                      </div>
                    </div>
                  </div>
                ))}
              </div>
              <div className="grid gap-4 lg:grid-cols-2">
                {[0, 1].map((item) => (
                  <div key={item} className="animate-pulse rounded-2xl border border-border/60 bg-background/70 p-4">
                    <div className="h-4 w-36 rounded bg-muted/60" />
                    <div className="mt-3 h-3 w-full rounded bg-muted/50" />
                    <div className="mt-5 h-2 rounded-full bg-muted/50" />
                    <div className="mt-4 h-10 w-24 rounded-xl bg-muted/40" />
                  </div>
                ))}
              </div>
            </div>
          ) : draftConfig ? (
            <>
              <section className="space-y-3">
                <div className="space-y-1">
                  <div className="text-sm font-semibold text-foreground">{t('embedding.title')}</div>
                  <p className="text-xs text-muted-foreground">{t('embedding.description')}</p>
                </div>
                <div className="space-y-2.5">
                  {EMBEDDING_MODEL_OPTIONS.map((model) => {
                    const isSelected = draftConfig.embedding.model === model
                    const meta = EMBEDDING_MODEL_META[model]

                    return (
                      <div key={model} className="relative">
                        <input
                          type="radio"
                          name="embedding_model"
                          id={`embedding-model-${model}`}
                          className="peer sr-only"
                          checked={isSelected}
                          onChange={() => updateEmbeddingModel(model)}
                        />
                        <label
                          htmlFor={`embedding-model-${model}`}
                          className={cn(
                            'grid cursor-pointer grid-cols-[1rem_minmax(0,1fr)] gap-3 rounded-[18px] border px-3.5 py-3 transition-all',
                            isSelected
                              ? 'border-primary/35 bg-primary/[0.065] shadow-[0_14px_36px_-32px_hsl(var(--primary)/0.4)]'
                              : 'border-border/55 bg-background/72 hover:border-border/80 hover:bg-background/88'
                          )}
                        >
                          <span
                            className={cn(
                              'mt-0.5 inline-flex h-4 w-4 items-center justify-center rounded-full border transition-colors',
                              isSelected
                                ? 'border-primary/55 bg-primary/10'
                                : 'border-border/70 bg-background/90'
                            )}
                            aria-hidden="true"
                          >
                            <span
                              className={cn(
                                'h-2 w-2 rounded-full transition-colors',
                                isSelected ? 'bg-primary' : 'bg-transparent'
                              )}
                            />
                          </span>

                          <div className="min-w-0 space-y-1.5">
                            <div className="flex flex-wrap items-center gap-2">
                              <div className="text-[13px] font-semibold text-foreground">{model}</div>
                              <span
                                className={cn(
                                  'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ring-1',
                                  isSelected
                                    ? 'bg-primary/[0.12] text-primary ring-primary/18'
                                    : 'bg-sky-500/10 text-sky-700 ring-sky-500/12 dark:text-sky-300'
                                )}
                              >
                                {t('embedding.modelHint')}
                              </span>
                            </div>

                            <p className="text-[12px] leading-5 text-muted-foreground">{meta.description}</p>

                            <div
                              className={cn(
                                'flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] leading-5',
                                isSelected ? 'text-primary/85' : 'text-muted-foreground/92'
                              )}
                            >
                              {meta.chips.map((chip) => (
                                <span key={chip} className="inline-flex items-center gap-1.5">
                                  <span
                                    className={cn(
                                      'h-1 w-1 rounded-full',
                                      isSelected ? 'bg-primary/65' : 'bg-muted-foreground/45'
                                    )}
                                  />
                                  {chip}
                                </span>
                              ))}
                            </div>
                          </div>
                        </label>
                      </div>
                    )
                  })}
                </div>
              </section>

              <div className="h-px bg-border/60" />

              <section className="grid gap-4 lg:grid-cols-2">
                <div className="rounded-[18px] border border-border/55 bg-background/72 px-3.5 py-3.5">
                  <div>
                    <div className="text-[13px] font-semibold text-foreground">{t('sliders.topK.title')}</div>
                    <p className="mt-0.5 text-[11px] leading-5 text-muted-foreground">{t('sliders.topK.description')}</p>
                  </div>
                  <div className="mt-3.5 flex flex-col gap-2 sm:flex-row sm:items-center">
                    <div className="min-w-0 flex-1">
                      <input
                        type="range"
                        min="1"
                        max="20"
                        step="1"
                        value={draftConfig.rag.retrieval_top_k}
                        onChange={(e) => updateTopK(e.target.value)}
                        aria-label={t('sliders.topK.title')}
                        className="block h-2 w-full cursor-pointer appearance-none rounded-full bg-muted accent-primary"
                      />
                    </div>
                    <Input
                      type="number"
                      min={1}
                      max={20}
                      step={1}
                      inputMode="numeric"
                      className="h-9 w-full shrink-0 rounded-xl border-border/65 bg-card/95 px-2.5 font-mono tabular-nums text-right shadow-none sm:w-[5rem]"
                      value={draftConfig.rag.retrieval_top_k}
                      onChange={(e) => updateTopK(e.target.value)}
                    />
                  </div>
                </div>

                <div className="rounded-[18px] border border-border/55 bg-background/72 px-3.5 py-3.5">
                  <div>
                    <div className="text-[13px] font-semibold text-foreground">{t('sliders.similarity.title')}</div>
                    <p className="mt-0.5 text-[11px] leading-5 text-muted-foreground">{t('sliders.similarity.description')}</p>
                  </div>
                  <div className="mt-3.5 flex flex-col gap-2 sm:flex-row sm:items-center">
                    <div className="min-w-0 flex-1">
                      <input
                        type="range"
                        min="0"
                        max="1"
                        step="0.01"
                        value={draftConfig.rag.similarity_threshold}
                        onChange={(e) => updateSimilarity(e.target.value)}
                        aria-label={t('sliders.similarity.title')}
                        className="block h-2 w-full cursor-pointer appearance-none rounded-full bg-muted accent-primary"
                      />
                    </div>
                    <Input
                      type="number"
                      min={0}
                      max={1}
                      step={0.01}
                      inputMode="decimal"
                      className="h-9 w-full shrink-0 rounded-xl border-border/65 bg-card/95 px-2.5 font-mono tabular-nums text-right shadow-none sm:w-[5rem]"
                      value={draftConfig.rag.similarity_threshold.toFixed(2)}
                      onChange={(e) => updateSimilarity(e.target.value)}
                    />
                  </div>
                </div>
              </section>

              <section className="rounded-[18px] border border-border/55 bg-muted/[0.12] px-3.5 py-3.5">
                <div className="flex flex-col gap-2.5 lg:flex-row lg:items-start lg:justify-between">
                  <div className="max-w-[38rem]">
                    <div className="text-[13px] font-semibold text-foreground">{t('runtimeMode.title')}</div>
                    <p className="mt-0.5 text-[11px] leading-5 text-muted-foreground">{t('runtimeMode.description')}</p>
                  </div>
                  <div className="flex flex-wrap items-center gap-x-3 gap-y-1 text-[11px] leading-5 text-muted-foreground/90">
                    <span className="inline-flex select-none items-center gap-1.5">
                      <span className="h-1 w-1 rounded-full bg-primary/55" />
                      {t('runtimeMode.chips.hybrid')}
                    </span>
                    <span className="inline-flex select-none items-center gap-1.5">
                      <span className="h-1 w-1 rounded-full bg-primary/45" />
                      {t('runtimeMode.chips.vector')}
                    </span>
                    <span className="inline-flex select-none items-center gap-1.5">
                      <span className="h-1 w-1 rounded-full bg-primary/35" />
                      {t('runtimeMode.chips.keyword')}
                    </span>
                  </div>
                </div>
              </section>
            </>
          ) : null}

          <div className="h-px bg-border/60" />

          <section className="rounded-[18px] border border-border/55 bg-background/58 px-3.5 py-3.5">
            <div className="flex flex-col gap-3 sm:flex-row sm:items-start sm:justify-between">
              <div className="max-w-[42rem]">
                <div className="text-[13px] font-semibold text-foreground">{t('dangerZone.title')}</div>
                <p className="mt-0.5 text-[11px] leading-5 text-muted-foreground">
                  {t('dangerZone.description')} <span className="font-mono">dry_run</span> {t('dangerZone.descriptionSuffix')}
                </p>
                <div
                  className={cn(
                    'mt-2 inline-flex items-center gap-1.5 text-[11px] leading-5',
                    selectedDatasetId ? 'text-muted-foreground' : 'text-warning'
                  )}
                >
                  <span
                    className={cn(
                      'h-1.5 w-1.5 rounded-full',
                      selectedDatasetId ? 'bg-muted-foreground/45' : 'bg-warning/80'
                    )}
                  />
                  {selectedDatasetId
                    ? `${t('dangerZone.datasetLabel')}: ${selectedDatasetId}`
                    : t('dangerZone.selectDatasetTitle')}
                </div>
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
                  className="h-9 shrink-0 gap-2 rounded-xl px-3 disabled:border-border/60 disabled:bg-background/72 disabled:text-muted-foreground"
                  disabled={!selectedDatasetId || purgeWorking}
                  title={selectedDatasetId ? undefined : t('dangerZone.selectDatasetTitle')}
                >
                  <Trash2 className="h-4 w-4" />
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
                    <div className="shrink-0 text-xs text-muted-foreground">{t('dangerZone.maxDelete')}</div>
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
                        {t('dangerZone.datasetLabel')}:{' '}
                        <span className="font-mono">{String(purgePreview.dataset_id || selectedDatasetId).slice(0, 8)}</span>
                      </div>
                    </div>
                  ) : (
                    <div className="text-xs text-muted-foreground">{t('dangerZone.previewHint')}</div>
                  )}

                  {purgeError ? (
                    <div className="rounded-lg border border-destructive/30 bg-destructive/5 p-3 text-xs text-destructive">
                      {purgeError}
                    </div>
                  ) : null}
                </div>

                <AlertDialogFooter>
                  <AlertDialogCancel disabled={purgeWorking}>{t('dangerZone.cancel')}</AlertDialogCancel>
                  <AlertDialogAction disabled={purgeWorking} onClick={() => detachPromise(runDatasetPurge({ dry_run: false }))}>
                    {t('dangerZone.confirm')}
                  </AlertDialogAction>
                </AlertDialogFooter>
              </AlertDialogContent>
            </AlertDialog>
            </div>
          </section>
        </div>

        <div className="flex flex-col gap-3 border-t border-border/60 bg-muted/[0.16] px-5 py-4 md:px-6 sm:flex-row sm:items-center sm:justify-between">
          <div className="text-xs text-muted-foreground">
            {settingsLoading
              ? t('footer.loading')
              : isDirty
                ? t('footer.unsaved', { count: changedCount })
                : lastSavedAt
                  ? t('footer.savedAt', { time: new Date(lastSavedAt).toLocaleTimeString() })
                  : t('footer.synced')}
          </div>
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              onClick={handleResetDraft}
              disabled={!isDirty || isSavingSettings || settingsLoading}
            >
              {t('actions.reset')}
            </Button>
            <Button
              type="button"
              className="gap-2"
              onClick={() => detachPromise(handleSaveSettings())}
              disabled={!isDirty || isSavingSettings || settingsLoading}
            >
              {isSavingSettings ? <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" /> : <Settings className="h-4 w-4" />}
              {t('actions.saveAll')}
            </Button>
          </div>
        </div>
      </div>

      <AlertDialog open={confirmEmbeddingSaveOpen} onOpenChange={setConfirmEmbeddingSaveOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('dialogs.embeddingChange.title')}</AlertDialogTitle>
            <AlertDialogDescription>{t('dialogs.embeddingChange.description')}</AlertDialogDescription>
          </AlertDialogHeader>
          <div className="rounded-xl border border-warning/25 bg-warning/10 p-3 text-xs leading-6 text-foreground">
            {t('dialogs.embeddingChange.impact')}
          </div>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={isSavingSettings}>{t('dialogs.embeddingChange.cancel')}</AlertDialogCancel>
            <AlertDialogAction
              className="bg-warning text-warning-foreground hover:bg-warning/90"
              disabled={isSavingSettings}
              onClick={() => detachPromise(saveSettings())}
            >
              {t('dialogs.embeddingChange.confirm')}
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}

export function KnowledgeConnectorRunsPanel({
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
}: Readonly<KnowledgeConnectorRunsPanelProps>) {
  const t = useTranslations('KnowledgeSettingsPanel')
  const [runStatusFilter, setRunStatusFilter] = useState<ConnectorRunStatusFilter>('all')
  const [autoRefreshRuns, setAutoRefreshRuns] = useState(false)
  const [connectorInfoById, setConnectorInfoById] = useState<Record<string, ConnectorInfo>>({})
  const autoRefreshIntervalMs = 10_000

  const runsUpdatedAtLabel = connectorRunsUpdatedAt
    ? new Date(connectorRunsUpdatedAt).toLocaleTimeString()
    : t('connectorRuns.emptyValue')
  const runStatusOptions = (['all', 'pending', 'running', 'failed', 'completed', 'cancelled'] as const).map((value) => ({
    value,
    label: t(`runStatus.${value}`),
  }))

  useEffect(() => {
    detachPromise(onLoadConnectorRuns({ datasetId: selectedDatasetId }))
  }, [onLoadConnectorRuns, selectedDatasetId])

  useEffect(() => {
    let cancelled = false

    detachPromise((async () => {
      try {
        const items = await connectorApi.listConnectors()
        if (cancelled) return
        const next = Object.fromEntries((items || []).map((item) => [String(item.id || '').toLowerCase(), item]))
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
    return connectorRuns.find((run) => run.id === expandedConnectorRunId) ?? null
  }, [connectorRuns, expandedConnectorRunId])

  const expandedRunIsVisible = useMemo(() => {
    if (!expandedConnectorRunId) return false
    return visibleConnectorRuns.some((run) => run.id === expandedConnectorRunId)
  }, [expandedConnectorRunId, visibleConnectorRuns])

  useEffect(() => {
    if (!autoRefreshRuns || !hasActiveRuns) return

    const id = globalThis.window.setInterval(() => {
      if (document.hidden) return
      if (connectorRunsLoading) return
      detachPromise(onLoadConnectorRuns({ datasetId: selectedDatasetId }))
    }, autoRefreshIntervalMs)

    return () => globalThis.window.clearInterval(id)
  }, [autoRefreshIntervalMs, autoRefreshRuns, connectorRunsLoading, hasActiveRuns, onLoadConnectorRuns, selectedDatasetId])

  useEffect(() => {
    if (!expandedConnectorRunId || !connectorRuns.length) return

    const el = document.getElementById(`connector-run-${expandedConnectorRunId}`)
    if (!el) return

    const reduceMotion = globalThis.window.matchMedia?.('(prefers-reduced-motion: reduce)')?.matches ?? false
    el.scrollIntoView({ block: 'start', behavior: reduceMotion ? 'auto' : 'smooth' })
  }, [connectorRuns, expandedConnectorRunId])

  return (
    <Panel padding="none" className="overflow-hidden rounded-[24px] border-border/60 bg-card/95 shadow-soft">
      <div className="border-b border-border/60 bg-muted/[0.16] p-5">
        <div className="flex flex-col gap-3 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-sm font-semibold text-foreground">{t("connectorRuns.title")}</div>
            <p className="mt-1 text-xs text-muted-foreground">{t('connectorRuns.description')}</p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <Select value={runStatusFilter} onValueChange={(value) => setRunStatusFilter(value as ConnectorRunStatusFilter)}>
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
              <RefreshCw className={cn('h-4 w-4', connectorRunsLoading && 'animate-spin motion-reduce:animate-none')} />
              {t('connectorRuns.actions.refresh')}
            </Button>
            <Button
              type="button"
              variant={autoRefreshRuns ? 'secondary' : 'outline'}
              className="h-9"
              aria-pressed={autoRefreshRuns}
              onClick={() => setAutoRefreshRuns((prev) => !prev)}
              disabled={!hasActiveRuns && !autoRefreshRuns}
              title={!hasActiveRuns && !autoRefreshRuns ? t('connectorRuns.autoRefresh.onlyWhenActive') : undefined}
            >
              {t('connectorRuns.autoRefresh.label')}
            </Button>
          </div>
        </div>
      </div>

      <div className="space-y-4 p-5">
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
            {autoRefreshRuns
              ? hasActiveRuns
                ? t('connectorRuns.autoRefresh.onInterval', { seconds: Math.round(autoRefreshIntervalMs / 1000) })
                : t('connectorRuns.autoRefresh.waiting')
              : t('connectorRuns.autoRefresh.off')}
          </span>
        </div>

        {connectorRunsLoading ? (
          <div className="rounded-xl border border-border/60 bg-background/60 p-4 text-sm text-muted-foreground">
            {t('connectorRuns.loading')}
          </div>
        ) : connectorRuns.length === 0 ? (
          <div className="rounded-xl border border-border/60 bg-background/60 p-4 text-sm text-muted-foreground">
            {t("connectorRuns.zeroState.description")}
          </div>
        ) : visibleConnectorRuns.length === 0 ? (
          <div className="flex items-center justify-between gap-3 rounded-xl border border-border/60 bg-background/60 p-4 text-sm text-muted-foreground">
            <div>{t("connectorRuns.empty.description")}</div>
            <Button type="button" variant="outline" size="sm" onClick={() => setRunStatusFilter('all')}>
              {t('connectorRuns.empty.clearFilters')}
            </Button>
          </div>
        ) : (
          <div className="space-y-3">
            {expandedConnectorRunId && !expandedRunIsVisible ? (
              <div className="rounded-xl border border-border/60 bg-muted/20 p-3 text-sm">
                {expandedRun ? (
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <div className="text-muted-foreground">
                      {t('connectorRuns.hidden.selectedRunHidden')} <span className="font-mono tabular-nums">{expandedConnectorRunId}</span>
                    </div>
                    <Button type="button" variant="outline" size="sm" onClick={() => setRunStatusFilter('all')}>
                      {t('connectorRuns.empty.clearFilters')}
                    </Button>
                  </div>
                ) : (
                  <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
                    <div className="text-muted-foreground">
                      {t('connectorRuns.hidden.selectedRunMissing')}{' '}
                      <span className="font-mono tabular-nums">{expandedConnectorRunId}</span>
                    </div>
                    <div className="flex items-center gap-2">
                      <Button type="button" variant="outline" size="sm" onClick={() => detachPromise(onLoadConnectorRuns({ datasetId: selectedDatasetId }))}>
                        {t('connectorRuns.actions.refresh')}
                      </Button>
                      <Button type="button" variant="outline" size="sm" onClick={() => onToggleExpandedConnectorRun(expandedConnectorRunId)}>
                        {t('connectorRuns.location.clear')}
                      </Button>
                    </div>
                  </div>
                )}
              </div>
            ) : null}

            {visibleConnectorRuns.map((run) => {
              const badge = getConnectorRunBadge(run.status, t)
              const status = String(run.status || '').toLowerCase()
              const stats = run.stats ?? {}
              const created = Number(stats.created || 0)
              const failed = Number(stats.failed || 0)
              const progress = getConnectorRunProgress(stats)
              const totalItems = progress.total
              const processedItems = progress.processed
              const durationStartAt = run.started_at ?? run.created_at
              const durationEndAt = run.finished_at ? run.finished_at : new Date().toISOString()
              const durationStartMs = Number.isFinite(Date.parse(durationStartAt)) ? Date.parse(durationStartAt) : null
              const durationEndMs = Number.isFinite(Date.parse(durationEndAt)) ? Date.parse(durationEndAt) : null
              const durationLabel =
                durationStartMs !== null && durationEndMs !== null && durationEndMs >= durationStartMs
                  ? formatDurationMs(durationEndMs - durationStartMs)
                  : null
              const progressPct =
                totalItems > 0 ? Math.max(0, Math.min(100, Math.round((processedItems / totalItems) * 100))) : 0
              const errors: any[] = Array.isArray(stats.errors) ? stats.errors : []
              const errorGroups: any[] = Array.isArray(stats.error_groups) ? stats.error_groups : []
              const isActive = status === 'pending' || status === 'running'
              const canRetryFailed = !isActive && failed > 0
              const connectorInfo = connectorInfoById[String(run.connector_id || '').toLowerCase()]
              const syncCapabilities = formatConnectorSyncCapabilities(connectorInfo, t)
              const supportsResume = Boolean(connectorInfo?.supports_resume)
              const hasRemainingResumeWork = totalItems > 0 ? totalItems > processedItems : processedItems > 0
              const canResume =
                !isActive && supportsResume && (status === 'cancelled' || status === 'failed') && hasRemainingResumeWork
              const documents = Array.isArray(run.documents) ? run.documents : []
              const hasDocs = documents.length > 0
              const acl = run.acl_summary
              const aclDocsTotal = Number(acl?.documents_total || 0)
              const aclModeRaw = String(acl?.mode || '').trim()
              const aclMode = aclModeRaw ? aclModeRaw.toLowerCase() : ''
              const aclModeLabel = aclMode ? formatAclModeLabel(aclMode, t) : null
              const aclMemberRange = formatAclCountRange(acl?.partial_member_count_min, acl?.partial_member_count_max)
              const aclGroupRange = formatAclCountRange(acl?.partial_group_count_min, acl?.partial_group_count_max)
              const aclBreakdown = aclMode === 'mixed' ? formatAclModeBreakdown(acl?.access_mode_counts, t) : null
              const aclHasAllowlist =
                Number(acl?.partial_members_doc_count || 0) > 0 || aclMemberRange !== null || aclGroupRange !== null

              return (
                <div
                  key={run.id}
                  id={`connector-run-${run.id}`}
                  className={cn(
                    'scroll-mt-6 rounded-xl border border-border/60 bg-background/60 p-4',
                    expandedConnectorRunId === run.id && 'ring-1 ring-primary/30'
                  )}
                >
                  <div className="flex items-start justify-between gap-4">
                    <div className="min-w-0">
                      <div className="flex flex-wrap items-center gap-2">
                        <StatusBadge status={badge.status} label={badge.label} dense />
                        <button
                          type="button"
                          className="truncate text-xs font-mono text-muted-foreground underline underline-offset-4 hover:text-foreground"
                          onClick={() => detachPromise(copyText(run.id, t('toasts.copyRunId')))}
                          title={t('connectorRuns.actions.copyRunIdTitle')}
                        >
                          {run.id}
                        </button>
                      </div>
                      <div className="mt-1 text-xs text-muted-foreground">
                        {formatDate(run.created_at)} · {run.connector_id} · {t('connectorRuns.datasetLabel')} {run.dataset_id || '-'}
                        {durationLabel ? (
                          <>
                            <span className="text-muted-foreground/40">{` · ${t('connectorRuns.durationLabel')} `}</span>
                            <span className="font-mono tabular-nums">{durationLabel}</span>
                          </>
                        ) : null}
                      </div>
                      <div className="mt-2 text-xs text-foreground/80">
                        {t('connectorRuns.metrics.created')} <span className="font-mono">{created}</span> · {t('connectorRuns.metrics.failed')}{' '}
                        <span className={cn('font-mono', failed > 0 && 'text-destructive')}>{failed}</span>
                      </div>

                      {syncCapabilities ? (
                        <div className="mt-1 text-xs text-muted-foreground">
                          {t('connectorRuns.metrics.sync')} <span className="font-mono">{syncCapabilities}</span>
                        </div>
                      ) : null}

                      {aclModeLabel && aclDocsTotal > 0 ? (
                        <div className="mt-1 text-xs text-muted-foreground">
                          {t('connectorRuns.metrics.acl')} <span className="font-mono">{aclModeLabel}</span>
                          {aclBreakdown ? <span className="text-muted-foreground/60">（{aclBreakdown}）</span> : null}
                          <span className="text-muted-foreground/40">{` · ${t('connectorRuns.metrics.documents')} `}</span>
                          <span className="font-mono tabular-nums">{aclDocsTotal}</span>
                          {aclHasAllowlist ? (
                            <>
                              <span className="text-muted-foreground/40">{` · ${t('connectorRuns.metrics.members')} `}</span>
                              <span className="font-mono tabular-nums">{aclMemberRange ?? t('connectorRuns.emptyValue')}</span>
                              <span className="text-muted-foreground/40">{` · ${t('connectorRuns.metrics.groups')} `}</span>
                              <span className="font-mono tabular-nums">{aclGroupRange ?? t('connectorRuns.emptyValue')}</span>
                            </>
                          ) : null}
                        </div>
                      ) : null}

                      <div className="mt-3 flex flex-wrap items-center gap-2">
                        <Button
                          type="button"
                          variant="outline"
                          size="sm"
                          className="h-7 gap-1.5 px-2"
                          onClick={() => {
                            const url = new URL(`/knowledge?tab=documents&run=${run.id}`, globalThis.window.location.origin).toString()
                            detachPromise(copyText(url, t('toasts.copyTaskLink')))
                          }}
                        >
                          <Link2 className="h-3.5 w-3.5" />
                          {t('connectorRuns.actions.copyLink')}
                        </Button>
                      </div>

                      {totalItems > 0 ? (
                        <div className="mt-2">
                          <div className="flex items-center justify-between text-xs text-muted-foreground">
                            <span>{t('connectorRuns.metrics.progress')}</span>
                            <span className="font-mono">
                              {processedItems}/{totalItems} ({progressPct}%)
                            </span>
                          </div>
                          <div className="mt-1 h-2 w-full overflow-hidden rounded-full bg-muted/60">
                            <div
                              className={cn(
                                'h-2 w-full origin-left rounded-full transition-transform duration-200 ease-out motion-reduce:transition-none',
                                failed > 0 ? 'bg-destructive/70' : 'bg-primary/70'
                              )}
                              style={{ transform: `scaleX(${progressPct / 100})` }}
                            />
                          </div>
                        </div>
                      ) : null}

                      {run.error_message ? <div className="mt-2 text-xs text-destructive">{run.error_message}</div> : null}

                      {errorGroups.length > 0 ? (
                        <div className="mt-2 text-xs text-muted-foreground">
                          <div className="font-medium text-foreground/80">{t('connectorRuns.errorGroupsTitle')}</div>
                          <div className="mt-1 space-y-1">
                            {errorGroups.slice(0, 3).map((group) => (
                              <div key={`${String(group?.code || 'error')}-${String(group?.error || '')}`} className="truncate font-mono">
                                [{String(group?.code || 'error')}] x{Number(group?.count || 0)} —{' '}
                                {String(group?.error || '').slice(0, 140)}
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null}

                      {errors.length > 0 ? (
                        <div className="mt-2 text-xs text-muted-foreground">
                          <div className="font-medium text-foreground/80">{t('connectorRuns.errorSamplesTitle')}</div>
                          <div className="mt-1 space-y-1">
                            {errors.slice(0, 3).map((error) => (
                              <div
                                key={`${String(error?.url || '')}-${String(error?.code || '')}-${String(error?.error || '')}`}
                                className="truncate font-mono"
                              >
                                {String(error?.url || '').slice(0, 80)} — {error?.code ? `[${String(error.code)}] ` : ''}
                                {String(error?.error || '').slice(0, 120)}
                              </div>
                            ))}
                          </div>
                        </div>
                      ) : null}

                      {hasDocs ? (
                        <div className="mt-3">
                          <button
                            type="button"
                            className="inline-flex items-center gap-1 text-xs text-muted-foreground hover:text-foreground/80"
                            onClick={() => onToggleExpandedConnectorRun(run.id)}
                          >
                            {expandedConnectorRunId === run.id ? <ChevronDown className="h-4 w-4" /> : <ChevronRight className="h-4 w-4" />}
                            {t('connectorRuns.documentList.toggle', { count: documents.length })}
                          </button>

                          {expandedConnectorRunId === run.id ? (
                            <div className="mt-2 rounded-lg border border-border/60 bg-background/40 p-3">
                              <div className="flex items-center justify-between gap-2">
                                <div className="text-xs font-medium text-foreground/80">{t('connectorRuns.documentList.title')}</div>
                                <Button
                                  type="button"
                                  variant="outline"
                                  size="sm"
                                  className="h-7 gap-1.5 px-2"
                                  onClick={() => {
                                    const ids = collectConnectorRunDocumentIds(documents)
                                    detachPromise(copyText(ids.join('\n'), t('toasts.copyDocumentIds')))
                                  }}
                                >
                                  <Copy className="h-3.5 w-3.5" />
                                  {t('connectorRuns.actions.copyIds')}
                                </Button>
                              </div>
                              <div className="mt-2 space-y-1">
                                {documents.slice(0, 15).map((doc, index) => {
                                  const documentId = normalizeConnectorRunDocumentId(doc?.document_id) || ''
                                  return (
                                    <div key={documentId || `${run.id}:${index}`} className="flex items-start justify-between gap-3">
                                      <div className="min-w-0">
                                        <div className="truncate text-[11px] font-mono text-foreground/90">{documentId}</div>
                                        {doc?.source_ref ? (
                                          <div className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground">
                                            {String(doc.source_ref)}
                                          </div>
                                        ) : null}
                                      </div>
                                      <div className="shrink-0 rounded-full border border-border/60 bg-background px-2 py-0.5 text-[10px] font-mono">
                                        {String(doc?.status || t('connectorRuns.documentList.defaultStatus'))}
                                      </div>
                                    </div>
                                  )
                                })}
                                {documents.length > 15 ? (
                                  <div className="text-[10px] text-muted-foreground">…(+{documents.length - 15})</div>
                                ) : null}
                              </div>
                            </div>
                          ) : null}
                        </div>
                      ) : null}
                    </div>

                    <div className="flex flex-col gap-2">
                      {isActive ? (
                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button variant="outline" className="gap-2">
                              <Trash2 className="h-4 w-4" />
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
                        </AlertDialog>
                      ) : null}

                      {canResume ? (
                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button variant="outline" className="gap-2">
                              <Play className="h-4 w-4" />
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
                              <AlertDialogAction onClick={() => detachPromise(onResumeConnectorRun(run.id))}>
                                {t('connectorRuns.dialogs.resume.confirm')}
                              </AlertDialogAction>
                            </AlertDialogFooter>
                          </AlertDialogContent>
                        </AlertDialog>
                      ) : null}

                      {canRetryFailed ? (
                        <AlertDialog>
                          <AlertDialogTrigger asChild>
                            <Button variant="outline" className="gap-2">
                              <RotateCcw className="h-4 w-4" />
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
                        </AlertDialog>
                      ) : null}
                    </div>
                  </div>
                </div>
              )
            })}
          </div>
        )}
      </div>
    </Panel>
  )
}
