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
  FileText,
  FileSpreadsheet,
  FileType,
  FileCode2,
  FileArchive,
  FileJson,
  FileImage,
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
import { SafeResponsiveChart } from '@/components/ui/safe-responsive-chart'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn, formatFileSize } from '@/lib/utils'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { ChunkStrategyDropdown } from '@/components/business/chunk-strategy-dropdown'
import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { UPLOAD_ACCEPT } from '@/lib/upload-extensions'
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
import { BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts'

function clampInt(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, Math.trunc(value)))
}

const DATASET_DEFAULT_VALUE = '__mimirq_dataset_default__'

type SidebarVariant = 'panel' | 'dialog' | 'pane'
type SidebarProps = Readonly<{ variant?: SidebarVariant }>
type HistogramDatum = { label: string; min: number | null; max: number | null; count: number }
type AccentTone = 'sky' | 'amber' | 'emerald' | 'violet' | 'cyan'
type SidebarToneStyle = { chip: string; icon: string; note: string; panel: string }
type FileVisual = {
  icon: LucideIcon
  shellClassName: string
  iconClassName: string
}

const SIDEBAR_BASE_TONE: SidebarToneStyle = {
  chip: 'border-border/55 bg-background/78 text-muted-foreground',
  icon: 'border-border/55 bg-background/78 text-muted-foreground',
  note: 'border-border/55 bg-muted/24 text-muted-foreground',
  panel: 'border-border/55 bg-[linear-gradient(180deg,hsl(var(--background)/0.96),hsl(var(--muted)/0.16))]',
}

const SIDEBAR_PRIMARY_TONE: SidebarToneStyle = {
  chip: 'border-primary/22 bg-primary/7 text-primary',
  icon: 'border-primary/18 bg-primary/7 text-primary',
  note: 'border-primary/18 bg-primary/6 text-muted-foreground',
  panel: 'border-border/55 bg-[linear-gradient(180deg,hsl(var(--background)/0.98),hsl(var(--primary)/0.045))]',
}

const SIDEBAR_TONE_STYLES: Record<AccentTone, SidebarToneStyle> = {
  sky: SIDEBAR_PRIMARY_TONE,
  amber: SIDEBAR_BASE_TONE,
  emerald: SIDEBAR_BASE_TONE,
  violet: SIDEBAR_BASE_TONE,
  cyan: SIDEBAR_BASE_TONE,
}

const SIDEBAR_FILE_ICON_STYLE = {
  shellClassName: 'border-border/55 bg-background/72 text-muted-foreground',
  iconClassName: 'text-muted-foreground',
} satisfies Omit<FileVisual, 'icon'>

function getFileVisual(file: { displayName?: string; originalFileType?: string } | null | undefined): FileVisual {
  const rawType = String(file?.originalFileType || '').toLowerCase().replace(/^\./, '')
  const name = String(file?.displayName || '').toLowerCase()
  const ext = rawType || /\.([a-z0-9]+)(?:$|\?)/.exec(name)?.[1] || ''

  if (ext === 'pdf') {
    return {
      icon: FileText,
      ...SIDEBAR_FILE_ICON_STYLE,
    }
  }
  if (['doc', 'docx', 'rtf'].includes(ext)) {
    return {
      icon: FileType,
      ...SIDEBAR_FILE_ICON_STYLE,
    }
  }
  if (['xls', 'xlsx', 'csv', 'tsv'].includes(ext)) {
    return {
      icon: FileSpreadsheet,
      ...SIDEBAR_FILE_ICON_STYLE,
    }
  }
  if (['md', 'markdown', 'txt'].includes(ext)) {
    return {
      icon: FileText,
      ...SIDEBAR_FILE_ICON_STYLE,
    }
  }
  if (['html', 'htm', 'xml'].includes(ext)) {
    return {
      icon: FileCode2,
      ...SIDEBAR_FILE_ICON_STYLE,
    }
  }
  if (['json', 'jsonl'].includes(ext)) {
    return {
      icon: FileJson,
      ...SIDEBAR_FILE_ICON_STYLE,
    }
  }
  if (['png', 'jpg', 'jpeg', 'webp', 'gif', 'bmp', 'tiff'].includes(ext)) {
    return {
      icon: FileImage,
      ...SIDEBAR_FILE_ICON_STYLE,
    }
  }
  if (['zip', 'tar', 'gz', '7z', 'rar'].includes(ext)) {
    return {
      icon: FileArchive,
      ...SIDEBAR_FILE_ICON_STYLE,
    }
  }
  return {
    icon: FileIcon,
    ...SIDEBAR_FILE_ICON_STYLE,
  }
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
        'rounded-lg border px-2.5 py-1.5 text-[11px] leading-4',
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

function SidebarPanel({
  tone = 'sky',
  className,
  children,
}: Readonly<{ tone?: AccentTone; className?: string; children: ReactNode }>) {
  return (
    <section
      className={cn(
        'rounded-[1.15rem] border px-3 py-3 shadow-[0_1px_0_rgba(255,255,255,0.7)_inset,0_12px_30px_-24px_rgba(15,23,42,0.35)]',
        SIDEBAR_TONE_STYLES[tone].panel,
        className
      )}
    >
      {children}
    </section>
  )
}

function SidebarIconButton({
  tone = 'sky',
  className,
  children,
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & Readonly<{ tone?: AccentTone }>) {
  return (
    <Button
      variant="ghost"
      size="sm"
      className={cn(
        'h-7 w-7 rounded-lg border p-0 shadow-none transition-colors',
        SIDEBAR_TONE_STYLES[tone].icon,
        'hover:brightness-[0.98] dark:hover:brightness-110',
        className
      )}
      {...props}
    >
      {children}
    </Button>
  )
}

export function Sidebar({ variant = 'panel' }: SidebarProps = {}) {
  const t = useTranslations('ChunkPreview')
  const {
    fileList,
    currentFileIndex,
    currentFile,
    currentFileItem,
    datasetId,
    scopeSyncLoading,
    scopeSyncError,
    previewData,
    isLoading,
    isSubmitting,
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
    selectedIngestFileIds,
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
    submitSelectedFiles,
    toggleIngestFileSelection,
    setParserBackend,
    toggleAutoPreview,
    clearRunHistory,
  } = useChunkPreview()
  const pipelineCtx = usePipelineOptions()
  type PreviewSettingsPatch = Parameters<typeof updateSettings>[0]
  type PerfSettingsPatch = Parameters<typeof updatePerfSettings>[0]
  type ChunkStrategyParams = NonNullable<DocumentPipelineOptions['chunk_strategy_params']>

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
  const compactStatCardClass =
    'min-w-0 rounded-lg border border-border/45 bg-[linear-gradient(180deg,hsl(var(--background)/0.9),hsl(var(--muted)/0.16))] px-2 py-1.5 shadow-none'
  const compactStatLabelClass =
    'truncate text-[8.5px] font-medium leading-3 tracking-[0.01em] text-muted-foreground/72'
  const compactStatValueClass =
    'mt-0.5 truncate text-[13px] font-medium leading-4 tracking-[-0.02em] tabular-nums text-foreground/90'

  const chunkSizeMin = isTokenStrategy ? 50 : 100
  const chunkSizeMax = isTokenStrategy ? 2000 : 4000
  const chunkSizeStep = isTokenStrategy ? 50 : 100
  const overlapStep = isTokenStrategy ? 25 : 50
  const overlapMax = Math.min(isTokenStrategy ? 500 : 1000, Math.max(0, chunkSize - chunkSizeMin))

  const sortedFileList = [...fileList].sort(
    (a, b) => (b.addedAt || 0) - (a.addedAt || 0)
  )

  const currentFileId = fileList[currentFileIndex]?.id
  const selectedIngestCount = selectedIngestFileIds.size
  const currentFileMatchesScope = useMemo(() => {
    if (!currentFileItem) return false
    if (currentFileItem.source === 'local_upload' || currentFileItem.source === 'example') {
      const itemDatasetId = currentFileItem.datasetId || ''
      return datasetId ? itemDatasetId === datasetId : !itemDatasetId
    }
    if (!datasetId) return currentFileItem.source === 'parsing_workspace'
    return currentFileItem.source === 'knowledge_base' && currentFileItem.datasetId === datasetId
  }, [currentFileItem, datasetId])
  const canRunPreview = Boolean(currentFile && currentFileMatchesScope && !scopeSyncLoading)
  const serverStats = previewData?.stats ?? null

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
    return []
  }, [previewData?.stats?.histogram])

  const histogramMax = useMemo(() => {
    const last = histogramData.at(-1)
    if (!last) return serverStats?.max ?? 0
    if (typeof last.max === 'number' && Number.isFinite(last.max)) return Math.trunc(last.max)
    return serverStats?.max ?? 0
  }, [histogramData, serverStats?.max])

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
      return JSON.parse(`"${raw.replaceAll('"', String.raw`\"`)}"`)
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

  const [analysisExpanded, setAnalysisExpanded] = useState(true)
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
        'space-y-3.5',
        variant === 'pane' ? 'min-h-0' : 'flex-1 overflow-y-auto overscroll-contain no-scrollbar'
      )}
    >
        <SidebarPanel tone="sky" className="space-y-3">
          <div className="flex items-center justify-between gap-2">
            <span className="text-[9px] font-semibold uppercase tracking-[0.18em] text-muted-foreground/75">
              {t('sidebar.datasetScope.title')}
            </span>
            <span className="rounded-full border border-border/50 bg-background/80 px-1.5 py-0.5 text-[9px] font-medium text-muted-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.7)]">
              {datasetId ? t('sidebar.datasetScope.scoped') : t('sidebar.datasetScope.all')}
            </span>
          </div>
          <select
            value={datasetId || DATASET_DEFAULT_VALUE}
            onChange={(event) => {
              setIngestionPreview(null)
              setIngestionError(null)
              setDatasetId(event.target.value === DATASET_DEFAULT_VALUE ? '' : event.target.value)
            }}
            className="h-9 w-full rounded-xl border border-border/60 bg-background/90 px-2.5 text-[11px] font-medium text-foreground shadow-[inset_0_1px_0_rgba(255,255,255,0.7)] outline-none transition-colors focus:border-primary/45 focus:ring-2 focus:ring-primary/12 dark:bg-background/60"
          >
            <option value={DATASET_DEFAULT_VALUE}>{t('sidebar.datasetScope.defaultOption')}</option>
            {datasets.map((ds) => (
              <option key={ds.id} value={ds.id}>
                {ds.name}
              </option>
            ))}
          </select>
          <p className="mt-1 text-[10px] leading-4 text-muted-foreground/70">
            {datasetId ? t('sidebar.datasetScope.selectedHint') : t('sidebar.datasetScope.hint')}
          </p>
          {datasetsLoading ? (
            <div className="mt-1 text-[10px] text-muted-foreground">{t('sidebar.dataset.loading')}</div>
          ) : null}
          {datasetsError ? (
            <SidebarNote tone="amber" className="mt-1 py-1.5">
              {datasetsError}
            </SidebarNote>
          ) : null}
          {scopeSyncLoading ? (
            <div className="mt-1 flex items-center gap-1.5 text-[10px] text-muted-foreground">
              <Loader2 className="h-3 w-3 animate-spin motion-reduce:animate-none" />
              {t('sidebar.datasetScope.syncing')}
            </div>
          ) : null}
          {scopeSyncError ? (
            <SidebarNote tone="amber" className="mt-1 py-1.5">
              {scopeSyncError}
            </SidebarNote>
          ) : null}
          <div className="h-px bg-border/45" />

          <div
            data-chunk-file-queue
            className="rounded-2xl border border-border/55 bg-[linear-gradient(180deg,hsl(var(--background)/0.94),hsl(var(--muted)/0.2))] p-2 shadow-[0_12px_30px_-28px_rgba(15,23,42,0.45)]"
          >
            <div className="flex items-center justify-between gap-3">
              <SidebarSectionHeader
                icon={Folder}
                label={t('sidebar.fileList.title', { count: fileList.length })}
                tone="sky"
              />
              <div className="flex items-center gap-1">
                <SidebarIconButton
                  tone="sky"
                  onClick={() => document.getElementById('add-file-input')?.click()}
                  aria-label={t('sidebar.fileList.addFile')}
                  title={t('sidebar.fileList.addFile')}
                >
                  <Upload className="w-3.5 h-3.5 text-primary" />
                </SidebarIconButton>
                <SidebarIconButton
                  tone="amber"
                  onClick={() => {
                    clearFiles()
                    toast.success(t('sidebar.fileList.clearFilesSuccess'))
                  }}
                  className="text-destructive/80"
                  disabled={fileList.length === 0}
                  aria-label={t('sidebar.fileList.clearFiles')}
                  title={t('sidebar.fileList.clearFiles')}
                >
                  <Trash2 className="w-3.5 h-3.5" />
                </SidebarIconButton>
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

            <div className="mt-2 flex items-center justify-between gap-2 rounded-xl border border-border/40 bg-background/72 px-2 py-1.5">
              <div className="flex min-w-0 items-center gap-1.5">
                <span
                  className={cn(
                    'h-1.5 w-1.5 shrink-0 rounded-full',
                    selectedIngestCount > 0 ? 'bg-primary shadow-[0_0_0_3px_hsl(var(--primary)/0.12)]' : 'bg-muted-foreground/35'
                  )}
                />
                <span className="min-w-0 truncate text-[10px] font-medium text-muted-foreground/85">
                  {selectedIngestCount > 0
                    ? t('sidebar.fileList.batchIngestSelected', {
                        count: selectedIngestCount,
                      })
                    : t('sidebar.fileList.batchIngestIdle')}
                </span>
              </div>
              <Button
                type="button"
                size="sm"
                variant={selectedIngestCount > 0 ? 'default' : 'outline'}
                onClick={submitSelectedFiles}
                disabled={selectedIngestCount === 0 || isSubmitting}
                className="h-6 shrink-0 rounded-lg px-2 text-[10px] shadow-none"
              >
                {selectedIngestCount > 0 ? t('sidebar.fileList.batchIngest') : t('sidebar.fileList.batchIngestShort')}
              </Button>
            </div>
          </div>

          <div className="max-h-[216px] space-y-1 overflow-y-auto overscroll-contain rounded-2xl border border-border/45 bg-[linear-gradient(180deg,hsl(var(--background)/0.82),hsl(var(--muted)/0.14))] p-1 no-scrollbar">
            {sortedFileList.length === 0 ? (
              <div className="rounded-xl border border-dashed border-border/60 bg-muted/20 px-3 py-4 text-center">
                <div className="text-[11px] font-medium text-foreground/75">
                  {scopeSyncLoading
                    ? t('sidebar.datasetScope.syncing')
                    : datasetId
                      ? t('sidebar.fileList.emptyDataset')
                      : t('sidebar.fileList.emptyAll')}
                </div>
                <div className="mt-1 text-[10px] leading-4 text-muted-foreground/70">
                  {datasetId ? t('sidebar.fileList.emptyDatasetHint') : t('sidebar.fileList.emptyAllHint')}
                </div>
              </div>
            ) : sortedFileList.map((f) => {
              const isActive = currentFileId === f.id
              const isSelectedForIngest = selectedIngestFileIds.has(f.id)
              const displayTime = f.addedAt
                ? new Date(f.addedAt).toLocaleString([], {
                    month: '2-digit',
                    day: '2-digit',
                    hour: '2-digit',
                    minute: '2-digit',
                  })
                : ''
              const fileIndex = fileList.findIndex((item) => item.id === f.id)
              const fileTypeLabel = f.originalFileType ? String(f.originalFileType).toUpperCase() : null
              const fileSizeLabel = typeof f.originalFileSize === 'number' ? formatFileSize(f.originalFileSize) : null
              const fileSourceLabel = f.source ? t(`sidebar.datasetScope.sources.${f.source}`) : null
              const fileMetaLabel = [
                fileTypeLabel,
                displayTime || t('sidebar.fileList.timeFallback'),
                fileSizeLabel,
                fileSourceLabel,
              ].filter(Boolean).join(' · ')
              const fileVisual = getFileVisual(f)
              const FileVisualIcon = fileVisual.icon
              return (
                <div
                  key={f.id}
                  className={cn(
                    'group relative overflow-hidden rounded-xl border text-[10px] transition-[background,border,box-shadow] duration-150',
                    isActive
                      ? 'border-primary/35 bg-[linear-gradient(180deg,hsl(var(--background)),hsl(var(--primary)/0.08))] shadow-sm ring-1 ring-primary/25'
                      : 'border-transparent bg-transparent hover:border-primary/18 hover:bg-primary/7'
                  )}
                >
                  <button
                    type="button"
                    onClick={() => {
                      if (fileIndex >= 0) setCurrentFileIndex(fileIndex)
                    }}
                    aria-label={t('sidebar.fileList.selectFile', { name: f.displayName })}
                    className="grid w-full min-w-0 cursor-pointer grid-cols-[auto_minmax(0,1fr)] items-center gap-2 rounded-xl py-1.5 pl-2 pr-12 text-left focus-ring"
                  >
                    <span
                      className={cn(
                        'grid h-7 w-7 shrink-0 place-items-center rounded-lg border',
                        isActive
                          ? 'border-primary/25 bg-primary/10 text-primary'
                          : fileVisual.shellClassName
                      )}
                    >
                      <FileVisualIcon className={cn('h-3.5 w-3.5', isActive ? 'text-primary' : fileVisual.iconClassName)} />
                    </span>
                    <span className="min-w-0">
                      <span className="flex min-w-0 items-center gap-1">
                        <span
                          title={f.displayName}
                          className={cn(
                            'min-w-0 truncate font-medium leading-4',
                            isActive ? 'text-foreground' : 'text-foreground/78'
                          )}
                        >
                          {f.displayName}
                        </span>
                        {processedStatus[f.id] === 'success' ? <Check className="h-3 w-3 shrink-0 text-success" /> : null}
                        {processedStatus[f.id] === 'error' ? <AlertCircle className="h-3 w-3 shrink-0 text-destructive" /> : null}
                      </span>
                      <span
                        className="mt-0.5 flex min-w-0 items-center gap-1 overflow-hidden text-[8.5px] leading-3 text-muted-foreground/75"
                        title={fileMetaLabel}
                      >
                        {fileTypeLabel ? (
                          <span className="shrink-0 rounded-md border border-border/45 bg-background/70 px-1 py-px font-medium text-muted-foreground/85">
                            {fileTypeLabel}
                          </span>
                        ) : null}
                        {fileSizeLabel ? <span className="shrink-0 tabular-nums">{fileSizeLabel}</span> : null}
                        {displayTime ? <span className="shrink-0 max-w-[4.2rem] truncate tabular-nums">{displayTime}</span> : null}
                        {fileSourceLabel ? <span className="min-w-0 truncate">{fileSourceLabel}</span> : null}
                      </span>
                    </span>
                  </button>

                  <button
                    type="button"
                    onClick={() => {
                      if (fileIndex >= 0) removeFile(fileIndex)
                    }}
                    className={cn(
                      'absolute right-1.5 top-1/2 -translate-y-1/2 cursor-pointer rounded-lg p-1 text-muted-foreground/70 opacity-0 transition-colors transition-opacity duration-150 motion-reduce:transition-none',
                      'hover:bg-destructive/10 hover:text-destructive focus-ring focus-visible:opacity-100 group-hover:opacity-100',
                      isActive ? 'opacity-100' : ''
                    )}
                    aria-label={t('sidebar.fileList.removeFile', { name: f.displayName })}
                    title={t('sidebar.fileList.removeFile', { name: f.displayName })}
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                  <button
                    type="button"
                    onClick={() => toggleIngestFileSelection(f.id)}
                    aria-pressed={isSelectedForIngest}
                    aria-label={t('sidebar.fileList.toggleForIngest', { name: f.displayName })}
                    title={t('sidebar.fileList.toggleForIngest', { name: f.displayName })}
                    className={cn(
                      'absolute right-7 top-1/2 grid h-5 w-5 -translate-y-1/2 cursor-pointer place-items-center rounded-lg border text-[9px] opacity-0 transition-colors transition-opacity duration-150 motion-reduce:transition-none focus-ring focus-visible:opacity-100 group-hover:opacity-100',
                      isSelectedForIngest || isActive ? 'opacity-100' : '',
                      isSelectedForIngest
                        ? 'border-primary/45 bg-primary text-primary-foreground shadow-sm'
                        : 'border-border/70 bg-background/90 text-muted-foreground hover:border-primary/35 hover:bg-primary/10 hover:text-primary'
                    )}
                  >
                    {isSelectedForIngest ? <Check className="h-3 w-3" /> : null}
                  </button>
                </div>
              )
            })}
          </div>

          <div className="h-px bg-border/45" />

          <div className="space-y-2.5">
            <div className="flex items-center justify-between gap-2">
              <div className="text-[11px] font-semibold text-foreground/82">{t('sidebar.dataset.title')}</div>
              <SidebarChip tone="cyan">
                {datasetId ? t('sidebar.dataset.statusSelected') : t('sidebar.dataset.statusAuto')}
              </SidebarChip>
            </div>
            <div className="rounded-xl border border-border/50 bg-background/80 px-2.5 py-2 text-[11px] text-muted-foreground">
              {datasetId
                ? t('sidebar.dataset.currentTarget', { name: selectedDataset?.name || datasetId })
                : t('sidebar.dataset.defaultOption')}
            </div>

            {selectedDataset?.pipeline ? (
              <div className="rounded-xl border border-border/50 bg-background p-2.5">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[11px] text-muted-foreground">{t('sidebar.dataset.pipelineSummary')}</div>
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
                <div className="mt-2 flex flex-wrap gap-2 text-[11px]">
                  {selectedDataset.pipeline.governance_enabled ? (
                    <span className="px-2 py-0.5 rounded-full border border-primary/18 bg-primary/7 text-primary">
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
                    <span className="px-2 py-0.5 rounded-full border border-primary/18 bg-primary/7 text-primary">
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
              className="h-8 w-full justify-start rounded-xl border-border/55 bg-background/80 text-[11px]"
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
              <div className="space-y-2 rounded-xl border border-border/50 bg-background p-2.5">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[11px] text-muted-foreground">{t('sidebar.ingestionPreview.result.title')}</div>
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
                <div className="text-[11px] text-muted-foreground font-mono">
                  {t('sidebar.ingestionPreview.result.parserStrategy', {
                    parser: ingestionPreview.rule.parser_backend,
                    strategy: ingestionPreview.rule.chunk_strategy,
                  })}
                </div>
                {ingestionPreview.rule.governance_profile_ref ? (
                  <div className="text-[11px] text-muted-foreground">
                    {t('sidebar.ingestionPreview.result.governanceProfile', {
                      value: ingestionPreview.rule.governance_profile_ref,
                    })}
                  </div>
                ) : null}
                <div className="text-[11px] text-muted-foreground">
                  {t('sidebar.ingestionPreview.result.preprocessSteps', {
                    count: ingestionPreview.rule.preprocess_steps.length,
                  })}
                </div>
                <div className="text-[11px] text-muted-foreground">
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
        </SidebarPanel>

        <div className="px-1">
          <SidebarSectionHeader icon={Settings} label={t('sidebar.settings.title')} tone="violet" aside="调参" />
        </div>

        <div className="space-y-4">
          <SidebarPanel tone="amber" className="space-y-2.5">
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

            <div className="flex items-center justify-between gap-3 rounded-xl border border-border/45 bg-background/70 px-2.5 py-2">
              <div className="min-w-0">
                <div className="text-[11px] font-medium text-foreground/82">{t('sidebar.autoPreview.title')}</div>
                <div className="truncate text-[10.5px] text-muted-foreground/85">{t('sidebar.autoPreview.description')}</div>
              </div>
              <label className="inline-flex shrink-0 items-center gap-2 text-[11px] text-muted-foreground">
                <input
                  type="checkbox"
                  checked={autoPreviewEnabled}
                  onChange={(e) => toggleAutoPreview(e.target.checked)}
                  className="h-3.5 w-3.5 rounded border-border/60 text-primary focus:ring-2 focus:ring-ring/20 focus:ring-offset-2 focus:ring-offset-background"
                />
                {autoPreviewEnabled ? t('sidebar.common.enabled') : t('sidebar.common.disabled')}
              </label>
            </div>

            <div className="flex items-center justify-between gap-2">
              <div>
                <div className="text-[11px] font-medium text-foreground/82">{t('sidebar.performance.includeOriginalText.title')}</div>
                <div className="text-[11px] text-muted-foreground">{t('sidebar.performance.includeOriginalText.description')}</div>
              </div>
              <label className="inline-flex items-center gap-2 text-[11px] text-muted-foreground">
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
                <div className="text-[11px] text-muted-foreground">{t('sidebar.performance.parseCache.description')}</div>
              </div>
              <label className="inline-flex items-center gap-2 text-[11px] text-muted-foreground">
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
              <div className="text-[11px] text-warning bg-warning/10 border border-warning/25 rounded-lg px-2 py-1">
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
                  className="h-6 px-2 ml-2 text-[11px]"
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
              <div className="text-[11px] text-muted-foreground space-y-1">
                {(previewData.warnings || []).slice(0, 6).map((w) => (
                  <div key={w} className="px-2 py-1 rounded-lg border border-border/60 bg-muted/40">
                    {w}
                  </div>
                ))}
              </div>
            ) : null}
          </SidebarPanel>

          <SidebarPanel tone="emerald" className="space-y-3">
            <div className="flex items-center justify-between">
              <div>
                <div className="text-[11px] font-semibold text-foreground/86">{t('sidebar.previewConfig.title')}</div>
                <div className="max-w-[210px] truncate text-[10px] text-muted-foreground">
                  {currentFile && currentFileMatchesScope
                    ? currentFile.name
                    : datasetId
                      ? t('sidebar.previewActions.noDatasetFile')
                      : t('sidebar.previewActions.noFile')}
                </div>
              </div>
              {cacheHit ? <SidebarChip tone="sky">Cache</SidebarChip> : <SidebarChip tone="emerald">配置</SidebarChip>}
            </div>
            <div className="grid grid-cols-2 gap-2 rounded-xl border border-border/50 bg-background/75 p-1 shadow-[inset_0_1px_0_rgba(255,255,255,0.65)]">
              <Button
                onClick={() => runPreview()}
                disabled={isLoading || !canRunPreview}
                className="h-9 rounded-xl border border-primary/22 bg-primary/10 text-[10.5px] font-medium text-primary shadow-none transition-colors hover:bg-primary/14"
              >
                {isLoading ? (
                  <Loader2 className="mr-2 h-4 w-4 animate-spin motion-reduce:animate-none" />
                ) : (
                  <Sparkles className="mr-2 h-4 w-4 text-primary" />
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
                disabled={!isLoading && !canRunPreview}
                className="h-9 rounded-xl border-border/60 bg-background/80 text-[10.5px] font-medium text-foreground/78 shadow-none transition-colors hover:bg-muted/55 hover:text-foreground/78"
              >
                {isLoading
                  ? t('sidebar.previewActions.cancel')
                  : cacheHit
                    ? t('sidebar.previewActions.ignoreCache')
                    : t('sidebar.previewActions.forceRefresh')}
              </Button>
            </div>

            <div className="h-px bg-border/50" />

            <div>
              <ChunkPresetPanel className="border-border/50 bg-background/75" />
            </div>

            <div className="h-px bg-border/50" />

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
            <div className="flex flex-wrap items-center gap-2 pt-1 text-[11px] text-muted-foreground">
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
                  className="rounded-full border border-border/50 bg-background/78 px-2 py-0.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.6)] transition-colors hover:bg-background focus-ring"
                  onClick={() => {
                    item.apply()
                    toast.success(t('sidebar.strategy.presetApplied', { label: item.label }))
                  }}
                >
                  {item.label}
                </button>
              ))}
            </div>

            {!hideChunkSizeControl ? (
              <div className="space-y-2.5 rounded-xl border border-border/50 bg-background/75 p-2.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.65)]">
                <div className="flex items-center justify-between gap-2">
                  <label className="text-[11px] font-medium text-muted-foreground">{chunkSizeLabel}</label>
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-primary/8 px-2 py-0.5 font-mono text-[11px] font-medium text-primary">{chunkSize}</span>
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
                      className="h-7 w-24 bg-background text-[11px] font-mono"
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
                  className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-primary/15 accent-primary transition-colors"
                />
                <div className="flex justify-between font-mono text-[10px] text-muted-foreground">
                  <span>{chunkSizeMin}</span>
                  <span>{chunkSizeMax}</span>
                </div>
                <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                  <span>{t('sidebar.chunkControls.presets')}</span>
                  {(isTokenStrategy ? [256, 512, 1024] : [600, 800, 1000, 1500]).map((size) => (
                    <button
                      key={size}
                      type="button"
                      className="rounded-full border border-border/50 bg-background/78 px-2 py-0.5 font-mono shadow-[inset_0_1px_0_rgba(255,255,255,0.6)] transition-colors hover:bg-background focus-ring"
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
            ) : null}

            {showOverlapControl ? (
              <div className="space-y-2.5 rounded-xl border border-border/50 bg-background/75 p-2.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.65)]">
                <div className="flex items-center justify-between gap-2">
                  <label className="text-[11px] font-medium text-muted-foreground">{overlapLabel}</label>
                  <div className="flex items-center gap-2">
                    <span className="rounded bg-primary/8 px-2 py-0.5 font-mono text-[11px] font-medium text-primary">{chunkOverlap}</span>
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
                      className="h-7 w-24 bg-background text-[11px] font-mono"
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
                  className="h-1.5 w-full cursor-pointer appearance-none rounded-full bg-primary/15 accent-primary transition-colors"
                />
                {overlapGuidance ? (
                  <div className="flex items-center justify-between text-[11px] text-muted-foreground">
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
                <div className="flex flex-wrap items-center gap-2 text-[11px] text-muted-foreground">
                  <span>{t('sidebar.chunkControls.overlapShortcuts')}</span>
                  {[10, 15, 20, 25].map((pct) => (
                    <button
                      key={pct}
                      type="button"
                      className="rounded-full border border-border/50 bg-background/78 px-2 py-0.5 shadow-[inset_0_1px_0_rgba(255,255,255,0.6)] transition-colors hover:bg-background focus-ring"
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
            ) : null}
          </SidebarPanel>

          {isSeparatorStrategy ? (
            <SidebarPanel tone="cyan" className="space-y-3">
              <div className="flex items-center justify-between gap-2">
                <div className="text-[11px] font-semibold text-foreground/82">{t('sidebar.separator.title')}</div>
                <SidebarChip tone="cyan">分隔</SidebarChip>
              </div>

              <div className="flex items-center justify-between gap-2">
                <div className="text-[11px] text-muted-foreground">{t('sidebar.separator.syncToPipeline')}</div>
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
                <div className="text-[11px] text-muted-foreground font-mono break-all">
                  {t('sidebar.separator.currentPipeline', {
                    value: JSON.stringify(pipelineCtx.options.chunk_strategy_params),
                  })}
                </div>
              ) : (
                <div className="text-[11px] text-muted-foreground font-mono">
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
                  <div className="text-[11px] text-muted-foreground font-mono">
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
                  <div className="text-[11px] text-muted-foreground">{t('sidebar.separator.keepSeparator.description')}</div>
                </div>
                <label className="inline-flex items-center gap-2 text-[11px] text-muted-foreground">
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
            </SidebarPanel>
          ) : null}

          {isParentChildStrategy ? (
            <SidebarPanel tone="emerald" className="space-y-3">
              <div className="text-[10.5px] font-semibold text-foreground/84">{t('sidebar.parentChild.title')}</div>

              <div className="flex items-center justify-between gap-2">
                <div className="text-[9.5px] text-muted-foreground">{t('sidebar.parentChild.syncToPipeline')}</div>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-6 px-2 text-[11px]"
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
                <div className="text-[9px] text-muted-foreground/80 font-mono break-all">
                  {t('sidebar.parentChild.currentPipeline', {
                    value: JSON.stringify(pipelineCtx.options.chunk_strategy_params),
                  })}
                </div>
              ) : (
                <div className="text-[9px] text-muted-foreground/80 font-mono">
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
                    className="h-8 text-[11px] font-mono bg-background"
                    aria-label={t('sidebar.parentChild.ratioAria')}
                  />
                  <SidebarNote tone="emerald" className="py-1">{t('sidebar.parentChild.ratioHelp')}</SidebarNote>
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
                    className="h-8 text-[11px] font-mono bg-background"
                    aria-label={t('sidebar.parentChild.minChildSizeAria')}
                  />
                  <SidebarNote tone="emerald" className="py-1">{t('sidebar.parentChild.minChildSizeHelp')}</SidebarNote>
                </div>
              </div>

              {parentChildEffective ? (
                <SidebarNote tone="emerald" className="font-mono text-[9px]">
                  {t('sidebar.parentChild.effectiveSummary', {
                    childSize: parentChildEffective.childSize,
                    childOverlap: parentChildEffective.childOverlap,
                    ratio: Math.round(parentChildEffective.ratio * 100),
                  })}
                </SidebarNote>
              ) : null}

              <SidebarNote tone="emerald">{t('sidebar.parentChild.description')}</SidebarNote>
            </SidebarPanel>
          ) : null}

          <SidebarPanel tone="violet" className="space-y-2">
            <div className="flex items-center justify-between gap-2">
              <div className="text-[11px] font-semibold text-foreground/82">{t('sidebar.ingestionPipeline')}</div>
              <SidebarChip tone="violet">入库</SidebarChip>
            </div>
            <PipelineOptionsPanel compact />
          </SidebarPanel>

        </div>

        {/* 统计指标 */}
        {previewData && (
          <div className="mt-5 border-t border-border/60 pt-5">
            <div className="mb-3 flex items-center justify-between gap-3">
              <SidebarSectionHeader icon={BarChart3} label={t('sidebar.analysis.title')} tone="sky" />
              <div className="flex items-center gap-1.5">
                <ChunkAutoTuneDialog />
                {analysisExpanded && serverStats ? (
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-6 rounded-md border-border/50 bg-background/75 px-2 text-[11px] font-medium text-muted-foreground shadow-none hover:bg-muted/45 hover:text-muted-foreground"
                    onClick={() => setShowAdvancedStats((v) => !v)}
                  >
                    {showAdvancedStats ? t('sidebar.analysis.detailsHide') : t('sidebar.analysis.detailsShow')}
                  </Button>
                ) : null}
                <Button
                  type="button"
                  variant="outline"
                  size="sm"
                  className="h-6 rounded-md border-border/50 bg-background/75 px-2 text-[11px] font-medium text-muted-foreground shadow-none hover:bg-muted/45 hover:text-muted-foreground"
                  onClick={() => setAnalysisExpanded((v) => !v)}
                >
                  {analysisExpanded ? t('sidebar.analysis.collapse') : t('sidebar.analysis.expand')}
                </Button>
              </div>
            </div>

            {analysisExpanded ? (
              <>
                <div data-chunk-stat-grid className="grid grid-cols-3 gap-1.5">
                  <div className={compactStatCardClass}>
                    <div className={compactStatLabelClass}>{t('sidebar.stats.totalChunks')}</div>
                    <div className={compactStatValueClass}>{previewData.total_chunks}</div>
                  </div>
                  <div className={compactStatCardClass}>
                    <div className={compactStatLabelClass}>{averageStatLabel}</div>
                    <div className={compactStatValueClass}>
                      {serverStats?.avg ?? '-'}
                      {isTokenStrategy ? (
                        <span className="ml-1 text-[8.5px] font-mono text-muted-foreground/75">{statsUnitLabel}</span>
                      ) : null}
                    </div>
                  </div>
                  <div className={compactStatCardClass}>
                    <div className={compactStatLabelClass}>{p95StatLabel}</div>
                    <div className={compactStatValueClass}>
                      {serverStats?.p95 ?? '-'}
                      {isTokenStrategy ? (
                        <span className="ml-1 text-[8.5px] font-mono text-muted-foreground/75">{statsUnitLabel}</span>
                      ) : null}
                    </div>
                  </div>
                  <div className={compactStatCardClass} title={t('sidebar.stats.coverage')}>
                    <div className={compactStatLabelClass}>{t('sidebar.stats.coverage')}</div>
                    <div className={compactStatValueClass}>
                      {coverageSignals?.coveragePct == null ? '-' : `${coverageSignals.coveragePct}%`}
                    </div>
                  </div>
                  <div className={compactStatCardClass} title={t('sidebar.stats.overlapWaste')}>
                    <div className={compactStatLabelClass}>{t('sidebar.stats.overlapWaste')}</div>
                    <div className={compactStatValueClass}>
                      {coverageSignals?.overlapWastePct == null ? '-' : `${coverageSignals.overlapWastePct}%`}
                    </div>
                  </div>
                  <div className={compactStatCardClass} title={t('sidebar.stats.gaps')}>
                    <div className={compactStatLabelClass}>{t('sidebar.stats.gaps')}</div>
                    <div className={compactStatValueClass}>
                      {coverageSignals?.gapCount == null ? '-' : String(coverageSignals.gapCount)}
                    </div>
                    {coverageSignals?.largestGap == null ? null : (
                      <div className="mt-0.5 truncate text-[7.5px] font-mono leading-3 text-muted-foreground/66">
                        {t('sidebar.stats.largestGap', { value: coverageSignals.largestGap })}
                      </div>
                    )}
                  </div>
                </div>

                {showAdvancedStats && serverStats ? (
                  <div className="mt-3 grid grid-cols-2 gap-3">
                <div className="bg-card p-3 rounded-xl border border-border/60 shadow-sm">
                  <div className="text-[11px] text-muted-foreground uppercase  font-medium">{minMaxStatLabel}</div>
                  <div className="mt-1 text-sm font-mono text-foreground/90">
                    {serverStats.min} / {serverStats.max}
                  </div>
                  <div className="mt-1 text-[11px] text-muted-foreground font-mono">{t('sidebar.stats.p10', { value: serverStats.p10 ?? '-' })}</div>
                </div>
                <div className="bg-card p-3 rounded-xl border border-border/60 shadow-sm">
                  <div className="text-[11px] text-muted-foreground uppercase  font-medium">{t('sidebar.stats.qualitySignals')}</div>
                  <div className="mt-1 text-[11px] text-muted-foreground">
                    {t('sidebar.stats.qualitySummary', {
                      shortCount: serverStats.short_count ?? 0,
                      duplicateCount: serverStats.duplicate_count ?? 0,
                    })}
                  </div>
                  {overlapGuidance ? (
                    <div className={cn('mt-1 text-[11px]', overlapGuidance.outOfRange ? 'text-warning' : 'text-muted-foreground')}>
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
                        'mt-1 text-[11px]',
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
                  <div className="text-[11px] text-muted-foreground uppercase  font-medium">{histogramTitle}</div>
                  {histogramData.length ? (
                    <SafeResponsiveChart className="mt-2 h-[120px]" minHeight={120}>
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
                    </SafeResponsiveChart>
                  ) : (
                    <div className="mt-2 text-[11px] text-muted-foreground">{t('sidebar.stats.histogramEmpty')}</div>
                  )}
                  <div className="mt-2 flex items-center justify-between text-[11px] text-muted-foreground font-mono">
                    <span>0</span>
                    <span>{histogramMax || serverStats.max}</span>
                  </div>
                </div>
                {previewData?.recommendations?.length || previewData?.recommendation_patches?.length ? (
                  <div className="col-span-2 bg-card p-3 rounded-xl border border-border/60 shadow-sm">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-[11px] text-muted-foreground uppercase  font-medium">{t('sidebar.recommendations.title')}</div>
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
                                  {desc ? <div className="mt-0.5 text-[11px] text-muted-foreground">{desc}</div> : null}
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
                              <div className="mt-1 text-[11px] text-muted-foreground font-mono">
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
              </>
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
                    "w-full rounded-lg border border-border/60 bg-card px-2.5 py-2 text-left text-[11px] text-muted-foreground shadow-sm",
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
