/**
 * Sidebar - 左侧配置栏
 */
'use client'

import { useEffect, useMemo, useState, type ReactNode } from 'react'
import {
  Settings,
  Folder,
  Upload,
  FileIcon,
  Trash2,
  Check,
  AlertCircle,
  Sparkles,
  BarChart3,
  Loader2,
  Wand2,
  type LucideIcon,
} from 'lucide-react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn, formatFileSize } from '@/lib/utils'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { ChunkStrategyDropdown } from '@/components/business/chunk-strategy-dropdown'
import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { getChunkStrategyOption } from '@/lib/chunk-strategies'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { UPLOAD_ACCEPT } from '@/lib/upload-extensions'
import { computeChunkLengthStats } from '@/components/chunk-preview/utils/stats'
import { datasetApi, pipelineApi } from '@/lib/api'
import { SEPARATOR_PRESET_OPTIONS } from '@/components/chunk-preview/constants'
import { IngestionPreviewDetailsDialog } from '@/components/chunk-preview/components/ingestion-preview-details-dialog'
import { ChunkPresetPanel } from '@/components/chunk-preview/components/chunk-preset-panel'
import { ChunkAutoTuneDialog } from '@/components/chunk-preview/components/chunk-auto-tune-dialog'
import type {
  ChunkPreviewHistogramBin,
  ChunkPreviewRecommendationPatch,
  Dataset,
  DocumentPipelineOptions,
  IngestionPreviewResponse,
  JsonObject,
} from '@/types'
import {
  ResponsiveContainer,
  BarChart,
  Bar,
  XAxis,
  YAxis,
  Tooltip,
  CartesianGrid,
} from 'recharts'

function clampInt(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, Math.trunc(value)))
}

const DATASET_DEFAULT_VALUE = '__mimirq_dataset_default__'

type SidebarVariant = 'panel' | 'dialog' | 'pane'
type SidebarProps = Readonly<{ variant?: SidebarVariant }>
type HistogramDatum = { label: string; min: number | null; max: number | null; count: number }
type AccentTone = 'sky' | 'amber' | 'emerald' | 'violet' | 'cyan'

const SIDEBAR_TONE_STYLES: Record<AccentTone, { chip: string; icon: string; note: string }> = {
  sky: {
    chip: 'border-sky-200/80 bg-sky-50/90 text-sky-700 dark:border-sky-900/60 dark:bg-sky-950/40 dark:text-sky-200',
    icon: 'border-sky-200/80 bg-sky-50 text-sky-700 dark:border-sky-900/60 dark:bg-sky-950/40 dark:text-sky-200',
    note: 'border-sky-200/70 bg-sky-50/70 text-sky-700/90 dark:border-sky-900/60 dark:bg-sky-950/30 dark:text-sky-200/90',
  },
  amber: {
    chip: 'border-amber-200/80 bg-amber-50/90 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/35 dark:text-amber-200',
    icon: 'border-amber-200/80 bg-amber-50 text-amber-700 dark:border-amber-900/60 dark:bg-amber-950/35 dark:text-amber-200',
    note: 'border-amber-200/70 bg-amber-50/70 text-amber-700/90 dark:border-amber-900/60 dark:bg-amber-950/25 dark:text-amber-200/90',
  },
  emerald: {
    chip: 'border-emerald-200/80 bg-emerald-50/90 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/35 dark:text-emerald-200',
    icon: 'border-emerald-200/80 bg-emerald-50 text-emerald-700 dark:border-emerald-900/60 dark:bg-emerald-950/35 dark:text-emerald-200',
    note: 'border-emerald-200/70 bg-emerald-50/70 text-emerald-700/90 dark:border-emerald-900/60 dark:bg-emerald-950/25 dark:text-emerald-200/90',
  },
  violet: {
    chip: 'border-violet-200/80 bg-violet-50/90 text-violet-700 dark:border-violet-900/60 dark:bg-violet-950/35 dark:text-violet-200',
    icon: 'border-violet-200/80 bg-violet-50 text-violet-700 dark:border-violet-900/60 dark:bg-violet-950/35 dark:text-violet-200',
    note: 'border-violet-200/70 bg-violet-50/70 text-violet-700/90 dark:border-violet-900/60 dark:bg-violet-950/25 dark:text-violet-200/90',
  },
  cyan: {
    chip: 'border-cyan-200/80 bg-cyan-50/90 text-cyan-700 dark:border-cyan-900/60 dark:bg-cyan-950/35 dark:text-cyan-200',
    icon: 'border-cyan-200/80 bg-cyan-50 text-cyan-700 dark:border-cyan-900/60 dark:bg-cyan-950/35 dark:text-cyan-200',
    note: 'border-cyan-200/70 bg-cyan-50/70 text-cyan-700/90 dark:border-cyan-900/60 dark:bg-cyan-950/25 dark:text-cyan-200/90',
  },
}

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function SidebarChip({
  tone = 'sky',
  children,
  className,
}: Readonly<{ tone?: AccentTone; children: ReactNode; className?: string }>) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full border px-1.5 py-0.5 text-[9px] font-semibold tracking-[0.04em]',
        SIDEBAR_TONE_STYLES[tone].chip,
        className
      )}
    >
      {children}
    </span>
  )
}

function SidebarNote({
  tone = 'sky',
  children,
  className,
}: Readonly<{ tone?: AccentTone; children: ReactNode; className?: string }>) {
  return (
    <div
      className={cn(
        'rounded-lg border px-2.5 py-1.5 text-[10px] leading-4',
        SIDEBAR_TONE_STYLES[tone].note,
        className
      )}
    >
      {children}
    </div>
  )
}

function SidebarSectionHeader({
  icon: Icon,
  label,
  tone = 'sky',
  aside,
}: Readonly<{ icon: LucideIcon; label: string; tone?: AccentTone; aside?: string }>) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="flex min-w-0 items-center gap-1.5">
        <span
          className={cn(
            'flex h-5 w-5 items-center justify-center rounded-md border',
            SIDEBAR_TONE_STYLES[tone].icon
          )}
        >
          <Icon className="h-3 w-3" />
        </span>
        <h2 className="truncate text-[11px] font-semibold text-foreground/88">{label}</h2>
      </div>
      {aside ? <SidebarChip tone={tone}>{aside}</SidebarChip> : null}
    </div>
  )
}

export function Sidebar({ variant = 'panel' }: SidebarProps = {}) {
  const t = useTranslations('ChunkPreview')
  const {
    fileList,
    currentFileIndex,
    currentFile,
    datasetId,
    previewData,
    isLoading,
    cacheHit,
    chunkSize,
    chunkOverlap,
    chunkStrategy,
    includeOriginalText,
    originalTextMaxChars,
    maxChunks,
    useParseCache,
    separatorPreset,
    separatorCustom,
    keepSeparator,
    separatorMaxChunkSize,
    parentChildRatio,
    parentChildMinChildSize,
    parserBackend,
    autoPreviewEnabled,
    runHistory,
    processedStatus,
    setCurrentFileIndex,
    removeFile,
    clearFiles,
    addFiles,
    setDatasetId,
    updateSettings,
    updatePerfSettings,
    updateSeparatorSettings,
    updateParentChildSettings,
    runPreview,
    cancelPreview,
    setParserBackend,
    toggleAutoPreview,
    clearRunHistory,
  } = useChunkPreview()
  const pipelineCtx = usePipelineOptions()
  type PreviewSettingsPatch = Parameters<typeof updateSettings>[0]
  type PerfSettingsPatch = Parameters<typeof updatePerfSettings>[0]
  type ChunkStrategyParams = NonNullable<DocumentPipelineOptions['chunk_strategy_params']>

  const chunkStrategyOption = getChunkStrategyOption(chunkStrategy)
  const resolvedChunkStrategy = previewData?.chunk_strategy || chunkStrategy
  const strategyForUi = resolvedChunkStrategy
  const isTokenStrategy = strategyForUi === 'langchain_token'
  const isSentenceStrategy = strategyForUi === 'llama_index'
  const isHierarchicalStrategy = strategyForUi === 'llama_index_hierarchical'
  const isIntegratedPipelineStrategy = strategyForUi.startsWith('integrated_')
  const isSeparatorStrategy = strategyForUi === 'separator'
  const isParentChildStrategy = strategyForUi === 'parent_child'
  const statsUnitLabel = isTokenStrategy ? 'tok' : 'chars'

  const hideChunkSizeControl = isSentenceStrategy || isIntegratedPipelineStrategy
  const showOverlapControl =
    !isSentenceStrategy && !isIntegratedPipelineStrategy && !isHierarchicalStrategy && !isSeparatorStrategy
  const chunkSizeLabel = isTokenStrategy ? t('sidebar.chunkControls.sizeTokenLabel') : t('sidebar.chunkControls.sizeCharsLabel')
  const chunkSizeAria = isTokenStrategy ? t('sidebar.chunkControls.sizeTokenAria') : t('sidebar.chunkControls.sizeCharsAria')
  const overlapLabel = isTokenStrategy ? t('sidebar.chunkControls.overlapTokenLabel') : t('sidebar.chunkControls.overlapCharsLabel')
  const overlapAria = isTokenStrategy ? t('sidebar.chunkControls.overlapTokenAria') : t('sidebar.chunkControls.overlapCharsAria')
  const averageStatLabel = isTokenStrategy ? t('sidebar.stats.averageTokens') : t('sidebar.stats.averageLength')
  const p95StatLabel = isTokenStrategy ? t('sidebar.stats.p95Tokens') : t('sidebar.stats.p95')
  const minMaxStatLabel = isTokenStrategy ? t('sidebar.stats.minMaxTokens') : t('sidebar.stats.minMaxLength')
  const histogramTitle = isTokenStrategy ? t('sidebar.stats.histogramTokens') : t('sidebar.stats.histogramLength')

  const chunkSizeMin = isTokenStrategy ? 50 : 100
  const chunkSizeMax = isTokenStrategy ? 2000 : 4000
  const chunkSizeStep = isTokenStrategy ? 50 : 100
  const overlapStep = isTokenStrategy ? 25 : 50
  const overlapMax = Math.min(isTokenStrategy ? 500 : 1000, Math.max(0, chunkSize - chunkSizeMin))

  const sortedFileList = [...fileList].sort(
    (a, b) => (b.addedAt || 0) - (a.addedAt || 0)
  )

  const activeFileItem = fileList[currentFileIndex] || null
  const currentFileId = fileList[currentFileIndex]?.id

  const chunkStats = useMemo(() => {
    if (!previewData?.chunks) return null

    const statSource = previewData.chunks.map((c) => {
      const tokensFallback = Math.max(0, Math.trunc((Number(c.length || 0) || 0) / 4))
      const chunkLength = (() => {
        if (!isTokenStrategy) return c.length
        return typeof c.tokens_est === 'number' ? c.tokens_est : tokensFallback
      })()
      return {
        content: c.content,
        length: chunkLength,
      }
    })

    return computeChunkLengthStats(statSource, {
      shortThreshold: isTokenStrategy ? 40 : 120,
      histogramBins: 8,
    })
  }, [previewData?.chunks, isTokenStrategy])

  const histogramData = useMemo(() => {
    const serverBins = previewData?.stats?.histogram
    if (Array.isArray(serverBins) && serverBins.length) {
      return serverBins.map((bin: ChunkPreviewHistogramBin): HistogramDatum => ({
        label: String(bin.label ?? ''),
        min: typeof bin.min === 'number' ? Math.trunc(bin.min) : null,
        max: typeof bin.max === 'number' ? Math.trunc(bin.max) : null,
        count: Math.max(0, Math.trunc(Number(bin.count ?? 0) || 0)),
      }))
    }

    const local = chunkStats?.histogram
    if (local?.length) {
      return local.map((b) => ({
        label: `${b.from}-${b.to}`,
        min: b.from,
        max: b.to,
        count: b.count,
      }))
    }

    return []
  }, [previewData?.stats?.histogram, chunkStats?.histogram])

  const histogramMax = useMemo(() => {
    const last = histogramData[histogramData.length - 1]
    if (!last) return chunkStats?.max ?? 0
    if (typeof last.max === 'number' && Number.isFinite(last.max)) return Math.trunc(last.max)
    return chunkStats?.max ?? 0
  }, [histogramData, chunkStats?.max])

  const overlapGuidance = useMemo(() => {
    if (!chunkSize || chunkSize <= 0) return null
    const min = Math.round(chunkSize * 0.1)
    const max = Math.round(chunkSize * 0.25)
    const ratio = chunkOverlap / chunkSize
    return {
      min,
      max,
      ratio,
      outOfRange: chunkOverlap < min || chunkOverlap > max,
    }
  }, [chunkOverlap, chunkSize])

  const coverageSignals = useMemo(() => {
    const ratioRaw = previewData?.stats?.coverage_ratio
    const wasteRaw = previewData?.stats?.overlap_waste_ratio
    const gapCountRaw = previewData?.stats?.gap_count
    const largestGapRaw = previewData?.stats?.largest_gap

    const ratio = typeof ratioRaw === 'number' && Number.isFinite(ratioRaw) ? ratioRaw : null
    const waste = typeof wasteRaw === 'number' && Number.isFinite(wasteRaw) ? wasteRaw : null
    const gapCount = typeof gapCountRaw === 'number' && Number.isFinite(gapCountRaw) ? gapCountRaw : null
    const largestGap = typeof largestGapRaw === 'number' && Number.isFinite(largestGapRaw) ? largestGapRaw : null

    if (ratio == null && waste == null && gapCount == null) return null
    return {
      coveragePct: ratio == null ? null : Math.max(0, Math.min(100, Math.round(ratio * 100))),
      overlapWastePct: waste == null ? null : Math.max(0, Math.min(100, Math.round(waste * 100))),
      gapCount: gapCount == null ? null : Math.max(0, Math.trunc(gapCount)),
      largestGap: largestGap == null ? null : Math.max(0, Math.trunc(largestGap)),
    }
  }, [previewData?.stats?.coverage_ratio, previewData?.stats?.overlap_waste_ratio, previewData?.stats?.gap_count, previewData?.stats?.largest_gap])

  const effectiveSeparator = useMemo(() => {
    if (!isSeparatorStrategy) return null

    const presetMap: Record<string, string> = {
      paragraph: '\n\n',
      line: '\n',
      sentence_cn: '。',
      sentence_en: '.',
      markdown_hr: '---',
      markdown_h1: '# ',
      markdown_h2: '## ',
    }

    if (separatorPreset && separatorPreset !== 'custom') {
      return presetMap[separatorPreset] ?? '\n\n'
    }

    const raw = String(separatorCustom || '').trim()
    if (!raw) return '\n\n'
    try {
      // Same trick as context.decodeSeparatorInput: support \n, \t, \uXXXX etc.
      return JSON.parse(`"${raw.replaceAll("\"", '\\"')}"`)
    } catch {
      return raw
    }
  }, [isSeparatorStrategy, separatorCustom, separatorPreset])

  const separatorPresetOptions = useMemo(() => {
    return SEPARATOR_PRESET_OPTIONS.map((opt) => {
      switch (opt.value) {
        case 'paragraph':
          return {
            ...opt,
            label: t('sidebar.separator.presets.paragraph.label'),
            hint: t('sidebar.separator.presets.paragraph.hint'),
          }
        case 'line':
          return {
            ...opt,
            label: t('sidebar.separator.presets.line.label'),
            hint: t('sidebar.separator.presets.line.hint'),
          }
        case 'sentence_cn':
          return {
            ...opt,
            label: t('sidebar.separator.presets.sentenceCn.label'),
            hint: t('sidebar.separator.presets.sentenceCn.hint'),
          }
        case 'sentence_en':
          return {
            ...opt,
            label: t('sidebar.separator.presets.sentenceEn.label'),
            hint: t('sidebar.separator.presets.sentenceEn.hint'),
          }
        case 'markdown_hr':
          return {
            ...opt,
            label: t('sidebar.separator.presets.markdownHr.label'),
            hint: t('sidebar.separator.presets.markdownHr.hint'),
          }
        case 'markdown_h1':
          return {
            ...opt,
            label: t('sidebar.separator.presets.markdownH1.label'),
            hint: t('sidebar.separator.presets.markdownH1.hint'),
          }
        case 'markdown_h2':
          return {
            ...opt,
            label: t('sidebar.separator.presets.markdownH2.label'),
            hint: t('sidebar.separator.presets.markdownH2.hint'),
          }
        case 'custom':
          return {
            ...opt,
            label: t('sidebar.separator.presets.custom.label'),
            hint: t('sidebar.separator.presets.custom.hint'),
          }
        default:
          return opt
      }
    })
  }, [t])

  const parentChildEffective = useMemo(() => {
    if (!isParentChildStrategy) return null
    const sp = previewData?.params?.strategy_params
    const ratio = typeof sp?.child_ratio === 'number' && Number.isFinite(sp.child_ratio) ? sp.child_ratio : parentChildRatio
    const minSize =
      typeof sp?.min_child_size === 'number' && Number.isFinite(sp.min_child_size) ? sp.min_child_size : parentChildMinChildSize
    const childSize =
      typeof sp?.child_size === 'number' && Number.isFinite(sp.child_size)
        ? sp.child_size
        : Math.max(Math.trunc(chunkSize * ratio), Math.trunc(minSize))
    const childOverlap =
      typeof sp?.child_overlap === 'number' && Number.isFinite(sp.child_overlap)
        ? sp.child_overlap
        : Math.min(Math.trunc(chunkOverlap * ratio), Math.max(0, Math.trunc(childSize / 4)))

    return {
      ratio: Number(ratio),
      minSize: Math.trunc(minSize),
      childSize: Math.trunc(childSize),
      childOverlap: Math.trunc(childOverlap),
    }
  }, [chunkOverlap, chunkSize, isParentChildStrategy, parentChildMinChildSize, parentChildRatio, previewData?.params])

  const [showAdvancedStats, setShowAdvancedStats] = useState(false)

  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [datasetsLoading, setDatasetsLoading] = useState(false)
  const [datasetsError, setDatasetsError] = useState<string | null>(null)
  const selectedDataset = useMemo(() => (datasetId ? datasets.find((ds) => ds.id === datasetId) || null : null), [datasetId, datasets])

  const [ingestionPreview, setIngestionPreview] = useState<IngestionPreviewResponse | null>(null)
  const [ingestionLoading, setIngestionLoading] = useState(false)
  const [ingestionError, setIngestionError] = useState<string | null>(null)
  const [ingestionDetailsOpen, setIngestionDetailsOpen] = useState(false)

  const applyPipelinePatch = (
    patch: DocumentPipelineOptions | JsonObject | null | undefined,
    options?: { successMessage?: string; errorMessage?: string }
  ) => {
    if (!patch || typeof patch !== 'object') return false

    const result = pipelineCtx.importJson(
      JSON.stringify({
        enabled: true,
        options: {
          ...pipelineCtx.options,
          ...patch,
        },
      })
    )

    if (!result.ok) {
      toast.error(result.error || options?.errorMessage || t('sidebar.errors.applyPipelinePatch'))
      return false
    }

    if (options?.successMessage) toast.success(options.successMessage)
    return true
  }

  const buildPreviewSettingsPatch = (patch: JsonObject): PreviewSettingsPatch => {
    const next: PreviewSettingsPatch = {}
    if (typeof patch.chunk_size === 'number' && Number.isFinite(patch.chunk_size)) next.chunkSize = Math.trunc(patch.chunk_size)
    if (typeof patch.chunk_overlap === 'number' && Number.isFinite(patch.chunk_overlap)) next.chunkOverlap = Math.trunc(patch.chunk_overlap)
    if (typeof patch.chunk_strategy === 'string' && patch.chunk_strategy.trim()) next.strategy = patch.chunk_strategy.trim()
    return next
  }

  const buildPerfSettingsPatch = (patch: JsonObject): PerfSettingsPatch => {
    const next: PerfSettingsPatch = {}
    if (typeof patch.include_original_text === 'boolean') next.includeOriginalText = patch.include_original_text
    if (typeof patch.original_text_max_chars === 'number' && Number.isFinite(patch.original_text_max_chars)) {
      next.originalTextMaxChars = Math.trunc(patch.original_text_max_chars)
    }
    if (typeof patch.max_chunks === 'number' && Number.isFinite(patch.max_chunks)) next.maxChunks = Math.trunc(patch.max_chunks)
    return next
  }

  useEffect(() => {
    let alive = true
    setDatasetsLoading(true)
    setDatasetsError(null)
    datasetApi
      .list({ limit: 100 })
      .then((res) => {
        if (!alive) return
        setDatasets(res.items || [])
      })
      .catch((error: unknown) => {
        if (!alive) return
        setDatasetsError(getErrorMessage(error, t('sidebar.dataset.loadError')))
      })
      .finally(() => {
        if (!alive) return
        setDatasetsLoading(false)
      })
    return () => {
      alive = false
    }
  }, [t])

  const content = (
    <div
      className={cn(
        'p-4',
        variant === 'pane' ? 'min-h-0' : 'flex-1 overflow-y-auto overscroll-contain no-scrollbar'
      )}
    >
        {/* 文件列表 */}
        <div className="mb-5 border-b border-border/60 pb-4">
          <div className="mb-3 flex items-center justify-between gap-3">
            <SidebarSectionHeader
              icon={Folder}
              label={t('sidebar.fileList.title', { count: fileList.length })}
              tone="sky"
              aside="文件"
            />
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => document.getElementById('add-file-input')?.click()}
                className="h-6 w-6 p-0 hover:bg-primary/10"
                aria-label={t('sidebar.fileList.addFile')}
                title={t('sidebar.fileList.addFile')}
              >
                <Upload className="w-3.5 h-3.5 text-primary" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  clearFiles()
                  toast.success(t('sidebar.fileList.clearFilesSuccess'))
                }}
                className="h-6 w-6 p-0 hover:bg-destructive/10 hover:text-destructive"
                disabled={fileList.length === 0}
                aria-label={t('sidebar.fileList.clearFiles')}
                title={t('sidebar.fileList.clearFiles')}
              >
                <Trash2 className="w-3.5 h-3.5" />
              </Button>
            </div>
            <input
              id="add-file-input"
              type="file"
              accept={UPLOAD_ACCEPT}
              multiple
              className="hidden"
              onChange={(e) => {
                const files = e.target.files ? Array.from(e.target.files) : []
                if (files.length > 0) addFiles(files)
                e.target.value = ''
              }}
            />
          </div>

          <div className="max-h-[168px] space-y-1 overflow-y-auto overscroll-contain rounded-lg border border-border/60 bg-card/70 p-1 pr-1 no-scrollbar">
            {sortedFileList.map((f) => {
              const isActive = currentFileId === f.id
              const displayTime = f.addedAt
                ? new Date(f.addedAt).toLocaleString([], {
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                  })
                : ''
              const fileIndex = fileList.findIndex((item) => item.id === f.id)
              return (
                <div
                  key={f.id}
                  className={cn(
                    'group flex items-center gap-1 rounded-md border text-[10.5px] transition-colors',
                    isActive
                      ? 'border-primary/25 bg-card shadow-sm ring-1 ring-ring/15'
                      : 'bg-transparent border-transparent hover:bg-primary/10 hover:border-primary/20'
                  )}
                >
                  <button
                    type="button"
                    onClick={() => {
                      if (fileIndex >= 0) setCurrentFileIndex(fileIndex)
                    }}
                    aria-label={t('sidebar.fileList.selectFile', { name: f.displayName })}
                    className="flex min-w-0 flex-1 cursor-pointer items-center justify-between gap-2 rounded-md px-1.5 py-1.5 text-left focus-ring"
                  >
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <FileIcon
                        className={cn('h-3.5 w-3.5 flex-shrink-0', isActive ? 'text-primary' : 'text-muted-foreground')}
                      />
                      <span className={cn('truncate font-medium', isActive ? 'text-foreground' : 'text-muted-foreground')}>
                        {f.displayName}
                      </span>
                    </div>

                    <div className="flex flex-shrink-0 items-center gap-1">
                      {displayTime && (
                        <span className="mr-1 text-[9px] text-muted-foreground/85">{displayTime}</span>
                      )}
                      {f.originalFileType && (
                        <span className="rounded border border-cyan-200/70 bg-cyan-50/85 px-1.5 py-0.5 font-mono text-[9px] text-cyan-700 dark:border-cyan-900/60 dark:bg-cyan-950/30 dark:text-cyan-200">
                          {String(f.originalFileType).toUpperCase()}
                        </span>
                      )}
                      {typeof f.originalFileSize === 'number' ? (
                        <span className="font-mono text-[9px] text-muted-foreground/80">{formatFileSize(f.originalFileSize)}</span>
                      ) : null}
                      {processedStatus[f.id] === 'success' && <Check className="w-3.5 h-3.5 text-success" />}
                      {processedStatus[f.id] === 'error' && <AlertCircle className="w-3.5 h-3.5 text-destructive" />}
                    </div>
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      if (fileIndex >= 0) removeFile(fileIndex)
                    }}
                    className="mr-1 cursor-pointer rounded p-1 opacity-0 transition-opacity transition-colors duration-150 motion-reduce:transition-none hover:bg-destructive/10 hover:text-destructive focus-ring focus-visible:opacity-100 group-hover:opacity-100"
                    aria-label={t('sidebar.fileList.removeFile', { name: f.displayName })}
                    title={t('sidebar.fileList.removeFile', { name: f.displayName })}
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              )
            })}
          </div>

          {activeFileItem ? (
            <SidebarNote tone="sky" className="mt-2 flex items-center gap-2 px-2 py-1.5">
              <span className="text-[9px] font-semibold uppercase tracking-[0.06em] text-sky-700/80 dark:text-sky-200/80">
                当前文件
              </span>
              <span className="min-w-0 flex-1 truncate text-[10px] font-medium text-sky-800/90 dark:text-sky-100/90">
                {activeFileItem.displayName}
              </span>
              {activeFileItem.originalFileType ? (
                <SidebarChip tone="cyan" className="font-mono">
                  {String(activeFileItem.originalFileType).toUpperCase()}
                </SidebarChip>
              ) : null}
              {typeof activeFileItem.originalFileSize === 'number' ? (
                <span className="font-mono text-[9px] text-sky-700/75 dark:text-sky-200/75">
                  {formatFileSize(activeFileItem.originalFileSize)}
                </span>
              ) : null}
            </SidebarNote>
          ) : null}
        </div>

        <div className="mb-3">
          <SidebarSectionHeader icon={Settings} label={t('sidebar.settings.title')} tone="violet" aside="调参" />
        </div>

        <div className="space-y-4">
          <div className="flex items-center justify-between rounded-lg border border-border/60 bg-card/75 px-2.5 py-1.5">
            <div>
              <div className="text-[11px] font-medium text-foreground/82">{t('sidebar.autoPreview.title')}</div>
              <div className="text-[10px] text-muted-foreground/85">{t('sidebar.autoPreview.description')}</div>
            </div>
            <label className="inline-flex items-center gap-2 text-[10px] text-muted-foreground">
              <input
                type="checkbox"
                checked={autoPreviewEnabled}
                onChange={(e) => toggleAutoPreview(e.target.checked)}
                className="h-3.5 w-3.5 rounded border-border/60 text-primary focus:ring-2 focus:ring-ring/20 focus:ring-offset-2 focus:ring-offset-background"
              />
              {autoPreviewEnabled ? t('sidebar.common.enabled') : t('sidebar.common.disabled')}
            </label>
          </div>

          <div className="flex items-center justify-between rounded-lg border border-border/60 bg-card/75 px-2.5 py-1.5">
            <div className="text-[10px] text-muted-foreground">{t('sidebar.shortcuts.label')}</div>
            <div className="text-[10px] text-muted-foreground/90">
              {t('sidebar.shortcuts.hint')}
            </div>
          </div>

          <div className="space-y-2.5 rounded-lg border border-border/60 bg-card/80 px-2.5 py-2">
            <div className="flex items-center justify-between gap-3">
              <div className="flex items-center gap-2">
                <span className={cn('flex h-6 w-6 items-center justify-center rounded-lg border', SIDEBAR_TONE_STYLES.amber.icon)}>
                  <Wand2 className="h-3.5 w-3.5" />
                </span>
                <div className="text-[11px] font-semibold text-foreground/84">{t('sidebar.performance.title')}</div>
              </div>
              <SidebarChip tone="amber">仅预览</SidebarChip>
            </div>
            <SidebarNote tone="amber">{t('sidebar.performance.description')}</SidebarNote>

            <div className="flex items-center justify-between gap-2">
              <div>
                <div className="text-[11px] font-medium text-foreground/82">{t('sidebar.performance.includeOriginalText.title')}</div>
                <div className="text-[10px] text-muted-foreground">{t('sidebar.performance.includeOriginalText.description')}</div>
              </div>
              <label className="inline-flex items-center gap-2 text-[10px] text-muted-foreground">
                <input
                  type="checkbox"
                  checked={includeOriginalText}
                  onChange={(e) => updatePerfSettings({ includeOriginalText: e.target.checked })}
                  className="h-3.5 w-3.5 rounded border-border/60 text-primary focus:ring-2 focus:ring-ring/20 focus:ring-offset-2 focus:ring-offset-background"
                />
                {includeOriginalText ? t('sidebar.common.enabled') : t('sidebar.common.disabled')}
              </label>
            </div>

            <div className="flex items-center justify-between gap-2">
              <div className="text-[11px] font-medium text-muted-foreground">{t('sidebar.performance.originalTextMaxChars')}</div>
              <Input
                type="number"
                inputMode="numeric"
                min={0}
                max={2000000}
                step={10000}
                value={originalTextMaxChars}
                onChange={(e) => updatePerfSettings({ originalTextMaxChars: Number(e.target.value) })}
                className="h-7 w-28 text-[11px] font-mono bg-background"
                aria-label={t('sidebar.performance.originalTextMaxCharsAria')}
                disabled={!includeOriginalText}
              />
            </div>

            <div className="flex items-center justify-between gap-2">
              <div className="text-[11px] font-medium text-muted-foreground">{t('sidebar.performance.maxChunks')}</div>
              <Input
                type="number"
                inputMode="numeric"
                min={0}
                max={20000}
                step={100}
                value={maxChunks}
                onChange={(e) => updatePerfSettings({ maxChunks: Number(e.target.value) })}
                className="h-7 w-28 text-[11px] font-mono bg-background"
                aria-label={t('sidebar.performance.maxChunksAria')}
              />
            </div>

            <div className="flex items-center justify-between gap-2">
              <div>
                <div className="text-[11px] font-medium text-foreground/82">{t('sidebar.performance.parseCache.title')}</div>
                <div className="text-[10px] text-muted-foreground">{t('sidebar.performance.parseCache.description')}</div>
              </div>
              <label className="inline-flex items-center gap-2 text-[10px] text-muted-foreground">
                <input
                  type="checkbox"
                  checked={useParseCache}
                  onChange={(e) => updatePerfSettings({ useParseCache: e.target.checked })}
                  className="h-3.5 w-3.5 rounded border-border/60 text-primary focus:ring-2 focus:ring-ring/20 focus:ring-offset-2 focus:ring-offset-background"
                />
                {useParseCache ? t('sidebar.common.enabled') : t('sidebar.common.disabled')}
              </label>
            </div>

            <SidebarNote tone="amber" className="py-1.5">{t('sidebar.performance.maxChunksGuidance')}</SidebarNote>

            {previewData?.chunks_truncated ? (
              <div className="text-[10px] text-warning bg-warning/10 border border-warning/25 rounded-lg px-2 py-1">
                {previewData.total_chunks_full && previewData.total_chunks_full !== previewData.total_chunks
                  ? t('sidebar.performance.truncatedSummaryWithFull', {
                    current: previewData.total_chunks,
                    full: previewData.total_chunks_full,
                  })
                  : t('sidebar.performance.truncatedSummary', {
                    current: previewData.total_chunks,
                  })}
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2 ml-2 text-[10px]"
                  onClick={() => {
                    updatePerfSettings({ maxChunks: 0 })
                    toast.success(t('sidebar.performance.clearLimitSuccess'))
                  }}
                >
                  {t('sidebar.performance.clearLimit')}
                </Button>
              </div>
            ) : null}

            {previewData?.warnings?.length ? (
              <div className="text-[10px] text-muted-foreground space-y-1">
                {(previewData.warnings || []).slice(0, 6).map((w) => (
                  <div key={w} className="px-2 py-1 rounded-lg border border-border/60 bg-muted/40">
                    {w}
                  </div>
                ))}
              </div>
            ) : null}
          </div>

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <div className="text-[11px] font-semibold text-foreground/82">{t('sidebar.dataset.title')}</div>
              <SidebarChip tone="cyan">可选</SidebarChip>
            </div>
            <Select
              value={datasetId || DATASET_DEFAULT_VALUE}
              onValueChange={(value) => {
                setIngestionPreview(null)
                setIngestionError(null)
                setDatasetId(value === DATASET_DEFAULT_VALUE ? '' : value)
              }}
            >
              <SelectTrigger className="h-8 bg-background/90 text-[11px]">
                <SelectValue placeholder={t('sidebar.dataset.selectPlaceholder')} />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={DATASET_DEFAULT_VALUE}>{t('sidebar.dataset.defaultOption')}</SelectItem>
                {datasets.map((ds) => (
                  <SelectItem key={ds.id} value={ds.id}>
                    {ds.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {(() => {
    if (datasetsLoading) {
        return (<div className="text-[10px] text-muted-foreground">{t('sidebar.dataset.loading')}</div>);
    }
    else if (datasetsError) {
            return (<SidebarNote tone="amber" className="py-1.5">
                {datasetsError}
              </SidebarNote>);
        }
        else {
            return null;
        }
})()}

            {selectedDataset?.pipeline ? (
              <div className="rounded-lg border border-border/60 bg-background p-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[10px] text-muted-foreground">{t('sidebar.dataset.pipelineSummary')}</div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 px-2 text-[11px]"
                    onClick={() => {
                      applyPipelinePatch(selectedDataset.pipeline, {
                        successMessage: t('sidebar.dataset.applyPipelineSuccess'),
                        errorMessage: t('sidebar.dataset.applyPipelineError'),
                      })
                    }}
                  >
                    {t('sidebar.dataset.applyPipeline')}
                  </Button>
                </div>
                <div className="mt-2 flex flex-wrap gap-2 text-[10px]">
                  {selectedDataset.pipeline.governance_enabled ? (
                    <span className="px-2 py-0.5 rounded-full bg-info/10 text-info border border-info/20">
                      {t('sidebar.dataset.badges.governanceOn')}
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 rounded-full bg-muted text-muted-foreground border border-border/60">
                      {t('sidebar.dataset.badges.governanceOff')}
                    </span>
                  )}
                  {selectedDataset.pipeline.chunk_vector_enabled ? (
                    <span className="px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20">
                      {t('sidebar.dataset.badges.vectorOn')}
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 rounded-full bg-muted text-muted-foreground border border-border/60">
                      {t('sidebar.dataset.badges.vectorOff')}
                    </span>
                  )}
                  {selectedDataset.pipeline.bm25_index_enabled ? (
                    <span className="px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20">
                      {t('sidebar.dataset.badges.bm25On')}
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 rounded-full bg-muted text-muted-foreground border border-border/60">
                      {t('sidebar.dataset.badges.bm25Off')}
                    </span>
                  )}
                  {selectedDataset.pipeline.kg_enabled ? (
                    <span className="px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-700 dark:text-purple-200 border border-purple-500/20">
                      {t('sidebar.dataset.badges.kg')}
                    </span>
                  ) : null}
                </div>
              </div>
            ) : null}

            <Button
              type="button"
              variant="outline"
              disabled={!datasetId || !currentFile || ingestionLoading}
              className="h-8 w-full justify-start text-[11px]"
              onClick={async () => {
                if (!datasetId) {
                  toast.error(t('sidebar.ingestionPreview.selectDatasetFirst'))
                  return
                }
                if (!currentFile) return
                setIngestionLoading(true)
                setIngestionError(null)
                try {
                  const result = await pipelineApi.ingestionPreview(currentFile, {
                    dataset_id: datasetId,
                    parser_backend: parserBackend || undefined,
                    chunk_strategy: chunkStrategy || undefined,
                    diff_max_lines: 300,
                  })
                  setIngestionPreview(result)
                  toast.success(t('sidebar.ingestionPreview.generatedSuccess'))
                } catch (error: unknown) {
                  setIngestionError(getErrorMessage(error, t('sidebar.ingestionPreview.requestFailed')))
                } finally {
                  setIngestionLoading(false)
                }
              }}
            >
              {ingestionLoading ? (
                <Loader2 className="w-4 h-4 mr-2 animate-spin motion-reduce:animate-none" />
              ) : (
                <Wand2 className="w-4 h-4 mr-2 text-primary" />
              )}
              {t('sidebar.ingestionPreview.trigger')}
            </Button>

            {ingestionError ? (
              <SidebarNote tone="amber" className="py-1.5">
                {ingestionError}
              </SidebarNote>
            ) : null}

	            {ingestionPreview ? (
	              <div className="space-y-2 rounded-lg border border-border/60 bg-background p-2">
	                <div className="flex items-center justify-between gap-2">
	                  <div className="text-[10px] text-muted-foreground">{t('sidebar.ingestionPreview.result.title')}</div>
	                  <div className="flex items-center gap-1">
	                    <Button
	                      type="button"
	                      variant="ghost"
	                      size="sm"
	                      className="h-7 px-2 text-[11px]"
	                      onClick={() => setIngestionDetailsOpen(true)}
	                    >
	                      {t('sidebar.ingestionPreview.result.details')}
	                    </Button>
	                    <Button
	                      type="button"
	                      variant="ghost"
	                      size="sm"
	                      className="h-7 px-2 text-[11px]"
	                      onClick={() => setIngestionPreview(null)}
	                    >
	                      {t('sidebar.ingestionPreview.result.clear')}
	                    </Button>
	                  </div>
	                </div>
                <div className="text-[11px] font-medium text-foreground/90">
                  {ingestionPreview.rule.matched
                    ? t('sidebar.ingestionPreview.result.matchedRule', {
                      name: ingestionPreview.rule.rule_name
                        || ingestionPreview.rule.rule_id
                        || t('sidebar.ingestionPreview.result.matchedRuleFallback'),
                    })
                    : t('sidebar.ingestionPreview.result.defaultRule')}
                </div>
                <div className="text-[10px] text-muted-foreground font-mono">
                  {t('sidebar.ingestionPreview.result.parserStrategy', {
                    parser: ingestionPreview.rule.parser_backend,
                    strategy: ingestionPreview.rule.chunk_strategy,
                  })}
                </div>
                {ingestionPreview.rule.governance_profile_ref ? (
                  <div className="text-[10px] text-muted-foreground">
                    {t('sidebar.ingestionPreview.result.governanceProfile', {
                      value: ingestionPreview.rule.governance_profile_ref,
                    })}
                  </div>
                ) : null}
	                <div className="text-[10px] text-muted-foreground">
	                  {t('sidebar.ingestionPreview.result.preprocessSteps', {
                      count: ingestionPreview.rule.preprocess_steps.length,
                    })}
	                </div>
	                <div className="text-[10px] text-muted-foreground">
	                  {t('sidebar.ingestionPreview.result.preprocessLabel')}{' '}
	                  <span className={cn(ingestionPreview.preprocess.changed ? 'text-warning' : 'text-muted-foreground')}>
	                    {ingestionPreview.preprocess.changed
                        ? t('sidebar.ingestionPreview.result.preprocessChanged')
                        : t('sidebar.ingestionPreview.result.preprocessUnchanged')}
	                  </span>{' '}
	                  ·{' '}
	                  <span className="font-mono">
	                    {formatFileSize(ingestionPreview.preprocess.size_before)} → {formatFileSize(ingestionPreview.preprocess.size_after)}
	                  </span>
	                  {ingestionPreview.preprocess.warnings?.length ? (
	                    <span className="text-warning">
                        {t('sidebar.ingestionPreview.result.preprocessWarnings', {
                          count: ingestionPreview.preprocess.warnings.length,
                        })}
                      </span>
	                  ) : null}
	                </div>
                <div className="flex items-center gap-2 pt-1">
                  <Button
                    type="button"
                    size="sm"
                    className="h-8 px-3 text-[11px]"
                    onClick={() => {
                      updateSettings({ strategy: ingestionPreview.rule.chunk_strategy })
                      toast.success(t('sidebar.ingestionPreview.result.applyRecommendationSuccess'))
                    }}
                  >
                    {t('sidebar.ingestionPreview.result.applyRecommendation')}
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-8 px-3 text-[11px]"
                    onClick={() => runPreview({ force: true })}
                  >
                    {t('sidebar.ingestionPreview.result.previewNow')}
                  </Button>
                </div>
	              </div>
	            ) : null}

	            <IngestionPreviewDetailsDialog
	              open={ingestionDetailsOpen}
	              onOpenChange={setIngestionDetailsOpen}
	              preview={ingestionPreview}
	              datasetId={datasetId}
	              onApplyPipelinePatch={(patch) => {
	                applyPipelinePatch(patch, { errorMessage: t('sidebar.ingestionPreview.applySuggestedPipelinePatchError') })
	              }}
	            />
	          </div>
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <div className="text-[11px] font-semibold text-foreground/82">切块预设</div>
              <SidebarChip tone="violet">预设</SidebarChip>
            </div>
            <ChunkPresetPanel className="mb-1" />
          </div>

          {/* 策略选择 */}
          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <div className="text-[11px] font-semibold text-foreground/82">{t('sidebar.strategy.title')}</div>
              <SidebarChip tone="emerald">核心</SidebarChip>
            </div>
            <ChunkStrategyDropdown
              value={chunkStrategy}
              onChange={(value) => {
                updateSettings({ strategy: value, ...(value === 'separator' ? { chunkOverlap: 0 } : {}) })
                if (value === 'separator' && !separatorPreset) {
                  updateSeparatorSettings({ separatorPreset: 'paragraph' })
                }
              }}
            />
            <SidebarNote tone="emerald" className="mt-1.5">{chunkStrategyOption.description}</SidebarNote>
            <div className="flex flex-wrap items-center gap-2 pt-1 text-[10px] text-muted-foreground">
              <span className="opacity-80">{t('sidebar.strategy.quickPresets')}</span>
              {[
                {
                  key: 'general',
                  label: t('sidebar.strategy.presets.general'),
                  apply: () => updateSettings({ strategy: 'auto', chunkSize: 1000, chunkOverlap: 200 }),
                },
                {
                  key: 'faq',
                  label: t('sidebar.strategy.presets.faq'),
                  apply: () => updateSettings({ strategy: 'qa_pairs', chunkSize: 800, chunkOverlap: 120 }),
                },
                {
                  key: 'code',
                  label: t('sidebar.strategy.presets.code'),
                  apply: () => updateSettings({ strategy: 'smart_code', chunkSize: 1000, chunkOverlap: 150 }),
                },
                {
                  key: 'contract',
                  label: t('sidebar.strategy.presets.contract'),
                  apply: () => updateSettings({ strategy: 'laws_structured', chunkSize: 1200, chunkOverlap: 200 }),
                },
                {
                  key: 'separator',
                  label: t('sidebar.strategy.presets.separator'),
                  apply: () => {
                    updateSettings({ strategy: 'separator', chunkSize: 1000, chunkOverlap: 0 })
                    updateSeparatorSettings({ separatorPreset: 'paragraph' })
                  },
                },
              ].map((item) => (
                <button
                  key={item.key}
                  type="button"
                  className="px-2 py-0.5 rounded-full border border-border/60 bg-muted/60 hover:bg-muted transition-colors focus-ring"
                  onClick={() => {
                    item.apply()
                    toast.success(t('sidebar.strategy.presetApplied', { label: item.label }))
                  }}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>

          {isSeparatorStrategy ? (
            <div className="space-y-3 rounded-lg border border-border/60 bg-background p-2 shadow-sm">
              <div className="flex items-center justify-between gap-2">
                <div className="text-[11px] font-semibold text-foreground/82">{t('sidebar.separator.title')}</div>
                <SidebarChip tone="cyan">分隔</SidebarChip>
              </div>

              <div className="flex items-center justify-between gap-2">
                <div className="text-[10px] text-muted-foreground">{t('sidebar.separator.syncToPipeline')}</div>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-7 px-2 text-[11px]"
                  onClick={() => {
                    const preset = separatorPreset || 'paragraph'
                    const patch: ChunkStrategyParams = {
                      separator_preset: preset,
                      keep_separator: !!keepSeparator,
                      separator_max_chunk_size: Number(separatorMaxChunkSize) || 0,
                    }
                    if (preset === 'custom') {
                      patch.separator = effectiveSeparator || '\n\n'
                    }
                    pipelineCtx.setEnabled(true)
                    pipelineCtx.updateOption('chunk_strategy_params', patch)
                    toast.success(t('sidebar.separator.writeSuccess'))
                  }}
                >
                  {t('sidebar.separator.write')}
                </Button>
              </div>
              {pipelineCtx.options.chunk_strategy_params ? (
                <div className="text-[10px] text-muted-foreground font-mono break-all">
                  {t('sidebar.separator.currentPipeline', {
                    value: JSON.stringify(pipelineCtx.options.chunk_strategy_params),
                  })}
                </div>
              ) : (
                <div className="text-[10px] text-muted-foreground font-mono">
                  {t('sidebar.separator.currentPipeline', {
                    value: t('sidebar.separator.currentPipelineEmpty'),
                  })}
                </div>
              )}

              <div className="space-y-2">
                <div className="text-[11px] font-medium text-muted-foreground">{t('sidebar.separator.presetLabel')}</div>
                <Select
                  value={separatorPreset}
                  onValueChange={(value) => updateSeparatorSettings({ separatorPreset: value })}
                >
                  <SelectTrigger className="h-8 bg-background text-[11px]">
                    <SelectValue placeholder={t('sidebar.separator.presetPlaceholder')} />
                  </SelectTrigger>
                  <SelectContent>
                    {separatorPresetOptions.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <SidebarNote tone="cyan" className="py-1.5">
                  {separatorPresetOptions.find((o) => o.value === separatorPreset)?.hint || ''}
                </SidebarNote>
                {effectiveSeparator ? (
                  <div className="text-[10px] text-muted-foreground font-mono">
                    {t('sidebar.separator.effectiveSeparator', {
                      value: JSON.stringify(effectiveSeparator).slice(1, -1) || t('sidebar.separator.currentPipelineEmpty'),
                      length: effectiveSeparator.length,
                    })}
                  </div>
                ) : null}
              </div>

              {separatorPreset === 'custom' ? (
                <div className="space-y-2">
                  <div className="text-[11px] font-medium text-muted-foreground">{t('sidebar.separator.customLabel')}</div>
                  <Input
                    value={separatorCustom}
                    onChange={(e) => updateSeparatorSettings({ separatorCustom: e.target.value })}
                    className="h-9 text-[11px] font-mono bg-background"
                    placeholder={t('sidebar.separator.customPlaceholder')}
                    aria-label={t('sidebar.separator.customAria')}
                  />
                  <SidebarNote tone="cyan" className="py-1.5">{t('sidebar.separator.customHelp')}</SidebarNote>
                </div>
              ) : null}

              <div className="flex items-center justify-between gap-2 rounded-lg border border-border/60 bg-card/75 px-2.5 py-1.5">
                <div>
                  <div className="text-[11px] font-medium text-foreground/82">{t('sidebar.separator.keepSeparator.title')}</div>
                  <div className="text-[10px] text-muted-foreground">{t('sidebar.separator.keepSeparator.description')}</div>
                </div>
                <label className="inline-flex items-center gap-2 text-[10px] text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={keepSeparator}
                    onChange={(e) => updateSeparatorSettings({ keepSeparator: e.target.checked })}
                    className="h-3.5 w-3.5 rounded border-border/60 text-primary focus:ring-2 focus:ring-ring/20 focus:ring-offset-2 focus:ring-offset-background"
                  />
                  {keepSeparator ? t('sidebar.common.enabled') : t('sidebar.common.disabled')}
                </label>
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[11px] font-medium text-muted-foreground">{t('sidebar.separator.maxChunkLength')}</div>
                  <Input
                    type="number"
                    inputMode="numeric"
                    min={0}
                    max={20000}
                    step={100}
                    value={separatorMaxChunkSize}
                    onChange={(e) => {
                      const n = Number(e.target.value)
                      if (!Number.isFinite(n)) return
                      updateSeparatorSettings({ separatorMaxChunkSize: clampInt(n, 0, 20000) })
                    }}
                    className="h-7 w-24 text-[11px] font-mono bg-background"
                    aria-label={t('sidebar.separator.maxChunkLengthAria')}
                  />
                </div>
                <SidebarNote tone="cyan" className="py-1.5">{t('sidebar.separator.maxChunkLengthHelp')}</SidebarNote>
              </div>
            </div>
          ) : null}

          {isParentChildStrategy ? (
            <div className="space-y-3 rounded-lg border border-border/60 bg-background p-2 shadow-sm">
              <div className="flex items-center justify-between gap-2">
                <div className="text-[11px] font-semibold text-foreground/82">{t('sidebar.parentChild.title')}</div>
                <SidebarChip tone="emerald">父子</SidebarChip>
              </div>

              <div className="flex items-center justify-between gap-2">
                <div className="text-[10px] text-muted-foreground">{t('sidebar.parentChild.syncToPipeline')}</div>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-7 px-2 text-[11px]"
                  onClick={() => {
                    const patch: ChunkStrategyParams = {
                      child_ratio: Number(parentChildRatio),
                      min_child_size: Number(parentChildMinChildSize),
                    }
                    pipelineCtx.setEnabled(true)
                    pipelineCtx.updateOption('chunk_strategy_params', patch)
                    toast.success(t('sidebar.parentChild.writeSuccess'))
                  }}
                >
                  {t('sidebar.parentChild.write')}
                </Button>
              </div>
              {pipelineCtx.options.chunk_strategy_params ? (
                <div className="text-[10px] text-muted-foreground font-mono break-all">
                  {t('sidebar.parentChild.currentPipeline', {
                    value: JSON.stringify(pipelineCtx.options.chunk_strategy_params),
                  })}
                </div>
              ) : (
                <div className="text-[10px] text-muted-foreground font-mono">
                  {t('sidebar.parentChild.currentPipeline', {
                    value: t('sidebar.parentChild.currentPipelineEmpty'),
                  })}
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <div className="text-[11px] font-medium text-muted-foreground">{t('sidebar.parentChild.ratioLabel')}</div>
                  <Input
                    type="number"
                    inputMode="decimal"
                    min={0.05}
                    max={1}
                    step={0.05}
                    value={parentChildRatio}
                    onChange={(e) => {
                      const n = Number(e.target.value)
                      if (!Number.isFinite(n)) return
                      updateParentChildSettings({ parentChildRatio: Math.max(0.05, Math.min(1, n)) })
                    }}
                    className="h-9 text-[11px] font-mono bg-background"
                    aria-label={t('sidebar.parentChild.ratioAria')}
                  />
                  <SidebarNote tone="emerald" className="py-1.5">{t('sidebar.parentChild.ratioHelp')}</SidebarNote>
                </div>

                <div className="space-y-2">
                  <div className="text-[11px] font-medium text-muted-foreground">{t('sidebar.parentChild.minChildSizeLabel')}</div>
                  <Input
                    type="number"
                    inputMode="numeric"
                    min={50}
                    max={4000}
                    step={50}
                    value={parentChildMinChildSize}
                    onChange={(e) => {
                      const n = Number(e.target.value)
                      if (!Number.isFinite(n)) return
                      updateParentChildSettings({ parentChildMinChildSize: clampInt(n, 50, 4000) })
                    }}
                    className="h-9 text-[11px] font-mono bg-background"
                    aria-label={t('sidebar.parentChild.minChildSizeAria')}
                  />
                  <SidebarNote tone="emerald" className="py-1.5">{t('sidebar.parentChild.minChildSizeHelp')}</SidebarNote>
                </div>
              </div>

              {parentChildEffective ? (
                <SidebarNote tone="emerald" className="font-mono">
                  {t('sidebar.parentChild.effectiveSummary', {
                    childSize: parentChildEffective.childSize,
                    childOverlap: parentChildEffective.childOverlap,
                    ratio: Math.round(parentChildEffective.ratio * 100),
                  })}
                </SidebarNote>
              ) : null}

              <SidebarNote tone="emerald">{t('sidebar.parentChild.description')}</SidebarNote>
            </div>
          ) : null}

          {/* Slider Controls */}
          {!hideChunkSizeControl && (
            <div className="space-y-3 rounded-lg border border-border/60 bg-card/70 p-2">
              <div className="flex items-center justify-between gap-2">
                <label className="text-[11px] font-medium text-muted-foreground">{chunkSizeLabel}</label>
                <div className="flex items-center gap-2">
                  <span className="rounded bg-primary/10 px-2 py-0.5 font-mono text-[10px] font-medium text-primary">{chunkSize}</span>
                  <Input
                    type="number"
                    inputMode="numeric"
                    min={chunkSizeMin}
                    max={chunkSizeMax}
                    step={chunkSizeStep}
                    value={chunkSize}
                    onChange={(e) => {
                      const n = Number(e.target.value)
                      if (!Number.isFinite(n)) return
                      const nextSize = clampInt(n, chunkSizeMin, chunkSizeMax)
                      const nextOverlapMax = Math.min(isTokenStrategy ? 500 : 1000, Math.max(0, nextSize - chunkSizeMin))
                      const nextOverlap = clampInt(chunkOverlap, 0, nextOverlapMax)
                      updateSettings({ chunkSize: nextSize, chunkOverlap: nextOverlap })
                    }}
                    className="h-7 w-24 text-[11px] font-mono bg-background"
                    aria-label={chunkSizeAria}
                  />
                </div>
              </div>
              <input
                type="range"
                min={chunkSizeMin}
                max={chunkSizeMax}
                step={chunkSizeStep}
                value={chunkSize}
                onChange={(e) => updateSettings({ chunkSize: Number(e.target.value) })}
                className="w-full h-1.5 bg-muted/60 rounded-full appearance-none cursor-pointer accent-primary transition-colors"
              />
              <div className="flex justify-between text-[10px] text-muted-foreground font-mono">
                <span>{chunkSizeMin}</span>
                <span>{chunkSizeMax}</span>
              </div>
              <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                <span>{t('sidebar.chunkControls.presets')}</span>
                {(isTokenStrategy ? [256, 512, 1024] : [600, 800, 1000, 1500]).map((size) => (
                  <button
                    key={size}
                    type="button"
                    className="px-2 py-0.5 rounded-full border border-border/60 bg-muted/60 hover:bg-muted transition-colors focus-ring font-mono"
                    onClick={() => {
                      const nextOverlapMax = Math.min(isTokenStrategy ? 500 : 1000, Math.max(0, size - chunkSizeMin))
                      const ratio = chunkSize > 0 ? chunkOverlap / chunkSize : 0.2
                      const desiredOverlap = Math.round(size * (Number.isFinite(ratio) ? ratio : 0.2))
                      updateSettings({
                        chunkSize: size,
                        chunkOverlap: clampInt(desiredOverlap, 0, nextOverlapMax),
                      })
                    }}
                  >
                    {size}
                  </button>
                ))}
              </div>
            </div>
          )}

          {showOverlapControl && (
            <div className="space-y-3 rounded-lg border border-border/60 bg-card/70 p-2">
              <div className="flex items-center justify-between gap-2">
                <label className="text-[11px] font-medium text-muted-foreground">{overlapLabel}</label>
                <div className="flex items-center gap-2">
                  <span className="rounded bg-primary/10 px-2 py-0.5 font-mono text-[10px] font-medium text-primary">{chunkOverlap}</span>
                  <Input
                    type="number"
                    inputMode="numeric"
                    min={0}
                    max={overlapMax}
                    step={overlapStep}
                    value={chunkOverlap}
                    onChange={(e) => {
                      const n = Number(e.target.value)
                      if (!Number.isFinite(n)) return
                      updateSettings({ chunkOverlap: clampInt(n, 0, overlapMax) })
                    }}
                    className="h-7 w-24 text-[11px] font-mono bg-background"
                    aria-label={overlapAria}
                  />
                </div>
              </div>
              <input
                type="range"
                min={0}
                max={overlapMax}
                step={overlapStep}
                value={chunkOverlap}
                onChange={(e) => updateSettings({ chunkOverlap: Number(e.target.value) })}
                className="w-full h-1.5 bg-muted/60 rounded-full appearance-none cursor-pointer accent-primary transition-colors"
              />
              {overlapGuidance ? (
                <div className="flex items-center justify-between text-[10px] text-muted-foreground">
                  <span>
                    {t('sidebar.chunkControls.overlapGuidance', {
                      min: overlapGuidance.min,
                      max: overlapGuidance.max,
                    })}
                  </span>
                  <span className={cn(overlapGuidance.outOfRange ? 'text-warning' : 'text-muted-foreground')}>
                    {t('sidebar.chunkControls.overlapCurrent', {
                      ratio: Math.round(overlapGuidance.ratio * 100),
                    })}
                  </span>
                </div>
              ) : null}
              <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                <span>{t('sidebar.chunkControls.overlapShortcuts')}</span>
                {[10, 15, 20, 25].map((pct) => (
                  <button
                    key={pct}
                    type="button"
                    className="px-2 py-0.5 rounded-full border border-border/60 bg-muted/60 hover:bg-muted transition-colors focus-ring"
                    onClick={() => {
                      const target = Math.round(chunkSize * (pct / 100))
                      updateSettings({ chunkOverlap: clampInt(target, 0, overlapMax) })
                    }}
                  >
                    {pct}%
                  </button>
                ))}
              </div>
            </div>
          )}

          <div className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <div className="text-[11px] font-semibold text-foreground/82">{t('sidebar.ingestionPipeline')}</div>
              <SidebarChip tone="violet">入库</SidebarChip>
            </div>
            <PipelineOptionsPanel compact />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <Button
              onClick={() => runPreview()}
              disabled={isLoading}
              className="h-10 rounded-lg border border-primary/20 shadow-sm"
            >
              {isLoading ? (
                <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none mr-2" />
              ) : (
                <Sparkles className="w-4 h-4 mr-2" />
              )}
              {isLoading ? t('sidebar.previewActions.loading') : t('sidebar.previewActions.run')}
            </Button>
            <Button
              variant="outline"
              onClick={() => {
                if (isLoading) {
                  cancelPreview()
                  return
                }
                runPreview({ force: true })
              }}
              className="h-10 rounded-lg"
            >
              {(() => {
    if (isLoading) {
        return t('sidebar.previewActions.cancel');
    }
    else if (cacheHit) {
            return t('sidebar.previewActions.ignoreCache');
        }
        else {
            return t('sidebar.previewActions.forceRefresh');
        }
})()}
            </Button>
          </div>
        </div>

        {/* 统计指标 */}
        {previewData && (
          <div className="mt-5 border-t border-border/60 pt-5">
            <div className="mb-3 flex items-center justify-between gap-3">
              <SidebarSectionHeader icon={BarChart3} label={t('sidebar.analysis.title')} tone="sky" aside="结果" />
              <div className="flex items-center gap-2">
                <ChunkAutoTuneDialog />
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-7 px-2 text-[11px]"
                  onClick={() => setShowAdvancedStats((v) => !v)}
                >
                  {showAdvancedStats ? t('sidebar.analysis.collapse') : t('sidebar.analysis.expand')}
                </Button>
              </div>
            </div>

            <div className="grid grid-cols-2 gap-2">
              <div className="rounded-lg border border-border/60 bg-card p-2 shadow-sm">
                <div className="text-[9px] font-medium uppercase tracking-[0.08em] text-muted-foreground">{t('sidebar.stats.totalChunks')}</div>
                <div className="mt-1 text-lg font-bold text-foreground">{previewData.total_chunks}</div>
              </div>
              <div className="rounded-lg border border-border/60 bg-card p-2 shadow-sm">
                <div className="text-[9px] font-medium uppercase tracking-[0.08em] text-muted-foreground">{averageStatLabel}</div>
                <div className="mt-1 text-lg font-bold text-foreground">
                  {previewData?.stats?.avg ?? chunkStats?.avg ?? '-'}
                  {isTokenStrategy ? (
                    <span className="ml-1 text-xs font-mono text-muted-foreground">{statsUnitLabel}</span>
                  ) : null}
                </div>
              </div>
              <div className="rounded-lg border border-border/60 bg-card p-2 shadow-sm">
                <div className="text-[9px] font-medium uppercase tracking-[0.08em] text-muted-foreground">{p95StatLabel}</div>
                <div className="mt-1 text-lg font-bold text-foreground">
                  {chunkStats?.p95 ?? chunkStats?.p90 ?? previewData?.stats?.p90 ?? '-'}
                  {isTokenStrategy ? (
                    <span className="ml-1 text-xs font-mono text-muted-foreground">{statsUnitLabel}</span>
                  ) : null}
                </div>
              </div>
              <div className="rounded-lg border border-border/60 bg-card p-2 shadow-sm" title={t('sidebar.stats.coverage')}>
                <div className="text-[9px] font-medium uppercase tracking-[0.08em] text-muted-foreground">{t('sidebar.stats.coverage')}</div>
                <div className="mt-1 text-lg font-bold text-foreground">
                  {coverageSignals?.coveragePct == null ? '-' : `${coverageSignals.coveragePct}%`}
                </div>
              </div>
              <div className="rounded-lg border border-border/60 bg-card p-2 shadow-sm" title={t('sidebar.stats.overlapWaste')}>
                <div className="text-[9px] font-medium uppercase tracking-[0.08em] text-muted-foreground">{t('sidebar.stats.overlapWaste')}</div>
                <div className="mt-1 text-lg font-bold text-foreground">
                  {coverageSignals?.overlapWastePct == null ? '-' : `${coverageSignals.overlapWastePct}%`}
                </div>
              </div>
              <div className="rounded-lg border border-border/60 bg-card p-2 shadow-sm" title={t('sidebar.stats.gaps')}>
                <div className="text-[9px] font-medium uppercase tracking-[0.08em] text-muted-foreground">{t('sidebar.stats.gaps')}</div>
                <div className="mt-1 text-lg font-bold text-foreground">
                  {coverageSignals?.gapCount == null ? '-' : String(coverageSignals.gapCount)}
                </div>
                {coverageSignals?.largestGap == null ? null : (
                  <div className="mt-1 text-[10px] text-muted-foreground font-mono">
                    {t('sidebar.stats.largestGap', { value: coverageSignals.largestGap })}
                  </div>
                )}
              </div>
            </div>

            {showAdvancedStats && chunkStats ? (
              <div className="mt-3 grid grid-cols-2 gap-3">
                <div className="bg-card p-3 rounded-xl border border-border/60 shadow-sm">
                  <div className="text-[10px] text-muted-foreground uppercase  font-medium">{minMaxStatLabel}</div>
                  <div className="mt-1 text-sm font-mono text-foreground/90">
                    {chunkStats.min} / {chunkStats.max}
                  </div>
                  <div className="mt-1 text-[10px] text-muted-foreground font-mono">{t('sidebar.stats.p10', { value: chunkStats.p10 })}</div>
                </div>
                <div className="bg-card p-3 rounded-xl border border-border/60 shadow-sm">
                  <div className="text-[10px] text-muted-foreground uppercase  font-medium">{t('sidebar.stats.qualitySignals')}</div>
                  <div className="mt-1 text-[11px] text-muted-foreground">
                    {t('sidebar.stats.qualitySummary', {
                      shortCount: chunkStats.shortCount,
                      duplicateCount: chunkStats.duplicateCount,
                    })}
                  </div>
                  {overlapGuidance ? (
                    <div className={cn('mt-1 text-[10px]', overlapGuidance.outOfRange ? 'text-warning' : 'text-muted-foreground')}>
                      {t('sidebar.stats.overlapSummary', {
                        ratio: Math.round(overlapGuidance.ratio * 100),
                        min: 10,
                        max: 25,
                      })}
                    </div>
                  ) : null}
                  {coverageSignals ? (
                    <div
                      className={cn(
                        'mt-1 text-[10px]',
                        coverageSignals.coveragePct != null && coverageSignals.coveragePct < 95 ? 'text-warning' : 'text-muted-foreground'
                      )}
                      title={coverageSignals.largestGap == null ? undefined : t('sidebar.stats.largestGap', { value: coverageSignals.largestGap })}
                    >
                      {t('sidebar.stats.coverageSummary', {
                        coverage: coverageSignals.coveragePct ?? '-',
                        waste: coverageSignals.overlapWastePct ?? '-',
                        gaps: coverageSignals.gapCount ?? '-',
                      })}
                    </div>
                  ) : null}
                </div>
                <div className="col-span-2 bg-card p-3 rounded-xl border border-border/60 shadow-sm">
                  <div className="text-[10px] text-muted-foreground uppercase  font-medium">{histogramTitle}</div>
                  {histogramData.length ? (
                    <div className="mt-2 h-[120px]">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={histogramData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" strokeOpacity={0.35} />
                          <XAxis dataKey="label" hide />
                          <YAxis hide />
                          <Tooltip
                            formatter={(value) => [value ?? 0, t('sidebar.stats.histogramCount')]}
                            labelFormatter={(label, payload) => {
                              const p = payload?.[0]?.payload
                              const min = typeof p?.min === 'number' ? p.min : null
                              const max = typeof p?.max === 'number' ? p.max : null
                              if (min != null && max != null) return `${min}-${max} ${statsUnitLabel}`
                              return String(label ?? '')
                            }}
                          />
                          <Bar dataKey="count" fill="hsl(var(--primary))" fillOpacity={0.25} radius={[2, 2, 0, 0]} />
                        </BarChart>
                      </ResponsiveContainer>
                    </div>
                  ) : (
                    <div className="mt-2 text-[11px] text-muted-foreground">{t('sidebar.stats.histogramEmpty')}</div>
                  )}
                  <div className="mt-2 flex items-center justify-between text-[10px] text-muted-foreground font-mono">
                    <span>0</span>
                    <span>{histogramMax || chunkStats.max}</span>
                  </div>
                </div>
                {previewData?.recommendations?.length || previewData?.recommendation_patches?.length ? (
                  <div className="col-span-2 bg-card p-3 rounded-xl border border-border/60 shadow-sm">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-[10px] text-muted-foreground uppercase  font-medium">{t('sidebar.recommendations.title')}</div>
                      {previewData?.recommendation_patches?.length ? (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="h-7 px-2 text-[11px]"
                          onClick={() => {
                            for (const item of previewData.recommendation_patches || []) {
                              const target = item.target || 'preview'
                              const patch = item.patch || {}
                              if (target === 'preview') {
                                const next = buildPreviewSettingsPatch(patch)
                                if (Object.keys(next).length) updateSettings(next)
                              } else if (target === 'pipeline') {
                                applyPipelinePatch(patch, { errorMessage: t('sidebar.recommendations.applyAllPipelineError') })
                              } else if (target === 'perf') {
                                const next = buildPerfSettingsPatch(patch)
                                if (Object.keys(next).length) updatePerfSettings(next)
                              }
                            }
                            toast.success(t('sidebar.recommendations.applyAllSuccess'))
                          }}
                        >
                          {t('sidebar.recommendations.applyAll')}
                        </Button>
                      ) : null}
                    </div>

                    {previewData?.recommendation_patches?.length ? (
                      <div className="mt-2 space-y-2">
                        {(previewData.recommendation_patches || []).slice(0, 6).map((patchItem: ChunkPreviewRecommendationPatch) => {
                          const title = patchItem.title || patchItem.id || t('sidebar.recommendations.patchFallback')
                          const desc = patchItem.description || ''
                          const target = patchItem.target || 'preview'
                          const patch = patchItem.patch || {}
                          const targetLabel =
                            target === 'preview'
                              ? t('sidebar.recommendations.targets.preview')
                              : target === 'pipeline'
                                ? t('sidebar.recommendations.targets.pipeline')
                                : target === 'perf'
                                  ? t('sidebar.recommendations.targets.perf')
                                  : target
                          return (
                            <div key={patchItem.id || title} className="rounded-lg border border-border/60 bg-background p-2">
                              <div className="flex items-center justify-between gap-2">
                                <div className="min-w-0">
                                  <div className="text-[11px] font-medium text-foreground/90">{title}</div>
                                  {desc ? <div className="mt-0.5 text-[10px] text-muted-foreground">{desc}</div> : null}
                                </div>
                                <Button
                                  type="button"
                                  size="sm"
                                  className="h-7 px-2 text-[11px]"
                                  onClick={() => {
                                    if (target === 'preview') {
                                      const next = buildPreviewSettingsPatch(patch)
                                      if (Object.keys(next).length) {
                                        updateSettings(next)
                                        toast.success(t('sidebar.recommendations.applyPreviewSuccess'))
                                      }
                                      return
                                    }
                                    if (target === 'pipeline') {
                                      if (applyPipelinePatch(patch, { errorMessage: t('sidebar.recommendations.applyPipelineError') })) {
                                        toast.success(t('sidebar.recommendations.applyPipelineSuccess'))
                                      }
                                      return
                                    }
                                    if (target === 'perf') {
                                      const next = buildPerfSettingsPatch(patch)
                                      if (Object.keys(next).length) {
                                        updatePerfSettings(next)
                                        toast.success(t('sidebar.recommendations.applyPerfSuccess'))
                                      }
                                    }
                                  }}
                                  title={Object.keys(patch || {}).length ? JSON.stringify(patch) : undefined}
                                >
                                  {t('sidebar.recommendations.apply')}
                                </Button>
                              </div>
                              <div className="mt-1 text-[10px] text-muted-foreground font-mono">
                                {t('sidebar.recommendations.target', { value: targetLabel })}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    ) : null}

                    {previewData?.recommendations?.length ? (
                      <div className="mt-2 space-y-1 text-[11px] text-muted-foreground">
                        {(previewData.recommendations || []).slice(0, 8).map((r) => (
                          <div key={String(r)} className="flex gap-2">
                            <span className="font-mono text-muted-foreground/70">-</span>
                            <span className="flex-1">{String(r)}</span>
                          </div>
                        ))}
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>
            ) : null}
          </div>
        )}

        {runHistory.length > 0 && (
          <div className="mt-5 border-t border-border/60 pt-5">
            <div className="mb-3 flex items-center justify-between gap-3">
              <SidebarSectionHeader icon={Sparkles} label={t('sidebar.history.title')} tone="amber" aside="记录" />
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-[11px]"
                onClick={() => {
                  clearRunHistory()
                  toast.success(t('sidebar.history.clearSuccess'))
                }}
              >
                {t('sidebar.history.clear')}
              </Button>
            </div>
            <div className="max-h-[180px] space-y-1.5 overflow-y-auto overscroll-contain pr-1 no-scrollbar">
              {runHistory.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className={cn(
                    "w-full rounded-lg border border-border/60 bg-card px-2.5 py-2 text-left text-[10px] text-muted-foreground shadow-sm",
                    "hover:border-primary/25 hover:bg-primary/5 transition-colors focus-ring"
                  )}
                  onClick={() => {
                    setParserBackend(item.parserBackend)
                    updateSettings({
                      strategy: item.strategy,
                      chunkSize: item.chunkSize,
                      chunkOverlap: item.chunkOverlap,
                    })
                    runPreview({ force: true })
                    toast.success(t('sidebar.history.restoreSuccess'))
                  }}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-foreground/80 truncate">{item.fileName}</span>
                    <span>{new Date(item.createdAt).toLocaleString([], { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-2">
                    <span className="px-2 py-0.5 rounded-full border border-border/60 bg-muted/60">
                      {t('sidebar.history.chunks', { count: item.totalChunks })}
                    </span>
                    <span className="px-2 py-0.5 rounded-full border border-border/60 bg-muted/60">
                      {t('sidebar.history.duration', { ms: item.durationMs })}
                    </span>
                    <span className="px-2 py-0.5 rounded-full border border-border/60 bg-muted/60">{item.strategy}</span>
                    {item.cacheHit && (
                      <span className="px-2 py-0.5 rounded-full bg-success/10 text-success border border-success/25">{t('sidebar.history.cacheHit')}</span>
                    )}
                  </div>
                </button>
              ))}
            </div>
          </div>
        )}
      </div>
    )

  if (variant === 'pane') return content

  return (
    <aside
      className={cn(
        'bg-card flex h-full min-h-0 overflow-hidden flex-col flex-shrink-0 z-10',
        variant === 'dialog' ? 'w-full border-0' : 'w-[19rem] border-r border-border/60'
      )}
    >
      {content}
    </aside>
  )
}
