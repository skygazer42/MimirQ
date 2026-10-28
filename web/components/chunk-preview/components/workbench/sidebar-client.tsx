/**
 * Sidebar - 左侧配置栏
 */
'use client'

import { useEffect, useMemo, useState, type ReactNode } from 'react'
import Link from 'next/link'
import { Folder, FileCode2, Check, AlertCircle, Sparkles, BarChart3, Loader2, Wand2, Database, Globe, Filter, type PlatformIcon } from '@/components/icons'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { FeedbackToast } from '@/components/feedback-toast'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { SafeResponsiveChart } from '@/components/ui/safe-responsive-chart'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'

import { cn, formatFileSize } from '@/lib/utils'
import { useChunkPreview } from '@/components/chunk-preview/context'

import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { datasetApi, evaluationApi, pipelineApi } from '@/lib/api'
import { SEPARATOR_PRESET_OPTIONS } from '@/components/chunk-preview/constants'
import { IngestionPreviewDetailsDialog } from '@/components/chunk-preview/components/ingestion-preview-details-dialog'

import { formatPreviewWarningMessage } from '@/components/chunk-preview/utils/preview-warnings'
import type {
  ChunkPreviewHistogramBin,
  ChunkPreviewRecommendationPatch,
  Dataset,
  DocumentPipelineOptions,
  IngestionPreviewResponse,
  JsonObject,
} from '@/types'
import type {
  PipelinePluginChunkReportResponse,
  PipelinePluginItem,
  PipelinePluginListError,
  PipelinePluginSuggestedPatch,
} from '@/lib/api/pipeline'
import { BarChart, Bar, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts'
import styles from './compare.module.css'
import configStyles from './config-dialog.module.css'
import { AdvancedConfigBody } from './advanced-config-body'

function clampInt(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, Math.trunc(value)))
}

const DATASET_DEFAULT_VALUE = '__mimirq_dataset_default__'
const PYTHON_PLUGIN_NONE_VALUE = '__mimirq_python_plugin_none__'
const REGISTERED_PLUGIN_BASE_PIPELINE_PATCH: DocumentPipelineOptions = {
  governance_enabled: true,
  persist_parsed_content: true,
}

type SidebarVariant = 'panel' | 'dialog' | 'pane'
type SidebarProps = Readonly<{ variant?: SidebarVariant; section?: 'all' | 'documents' | 'settings' }>
type HistogramDatum = { label: string; min: number | null; max: number | null; count: number }
type AccentTone = 'sky' | 'amber' | 'emerald' | 'violet' | 'cyan'
type SidebarToneStyle = { chip: string; icon: string; note: string; panel: string }
type EmptyFileListLabels = {
  syncing: string
  emptyDataset: string
  emptyAll: string
}

type PluginReadinessCheck = NonNullable<
  NonNullable<PipelinePluginChunkReportResponse['readiness']>['checks']
>[number]

const SIDEBAR_BASE_TONE: SidebarToneStyle = {
  chip: 'border-foreground/10 bg-background/82 text-muted-foreground antialiased shadow-none',
  icon: 'border-foreground/10 bg-background/82 text-muted-foreground antialiased shadow-none',
  note: 'border-info/10 bg-background/55 text-muted-foreground antialiased',
  panel: 'border-foreground/10 bg-background/72 antialiased shadow-none',
}

const SIDEBAR_PRIMARY_TONE: SidebarToneStyle = {
  chip: 'border-info/20 bg-info/[0.07] text-info antialiased shadow-none',
  icon: 'border-info/20 bg-info/[0.07] text-info antialiased shadow-none',
  note: 'border-info/15 bg-info/[0.035] text-muted-foreground antialiased',
  panel: 'border-info/20 bg-info/[0.045] antialiased shadow-none',
}

const SIDEBAR_TONE_STYLES: Record<AccentTone, SidebarToneStyle> = {
  sky: SIDEBAR_PRIMARY_TONE,
  amber: SIDEBAR_BASE_TONE,
  emerald: SIDEBAR_BASE_TONE,
  violet: SIDEBAR_BASE_TONE,
  cyan: SIDEBAR_BASE_TONE,
}

const SIDEBAR_LEAD_ICON_FRAME_CLASS =
  'relative flex size-6 shrink-0 items-center justify-center rounded-lg border shadow-none'
const SIDEBAR_LEAD_ICON_CLASS = 'size-3.5 shrink-0'
const SIDEBAR_COMPACT_ICON_FRAME_CLASS =
  'flex size-5 shrink-0 items-center justify-center rounded-md border shadow-none'
const SIDEBAR_COMPACT_ICON_CLASS = 'size-3 shrink-0'

function getEmptyFileListLabel({
  scopeSyncLoading,
  datasetId,
  labels,
}: {
  scopeSyncLoading: boolean
  datasetId?: string | null
  labels: EmptyFileListLabels
}): string {
  if (scopeSyncLoading) return labels.syncing
  if (datasetId) return labels.emptyDataset
  return labels.emptyAll
}

function getRecommendationTargetLabel(
  target: string,
  labels: Record<string, string>
): string {
  return labels[target] ?? target
}

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function getPluginParams(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  return value as Record<string, unknown>
}

function getReportNumber(value: Record<string, unknown> | undefined, key: string): number {
  const n = Number(value?.[key] ?? 0)
  return Number.isFinite(n) ? n : 0
}

function getFailedReadinessChecks(report: PipelinePluginChunkReportResponse | null): PluginReadinessCheck[] {
  const checks = report?.readiness?.checks
  if (!Array.isArray(checks)) return []
  return checks.filter((check) => check.required !== false && check.passed === false)
}

function getReadinessErrorReason(check: PluginReadinessCheck): string {
  const errors = Array.isArray(check.errors) ? check.errors : []
  for (const error of errors) {
    if (!error || typeof error !== 'object' || Array.isArray(error)) continue
    const reason = (error as Record<string, unknown>).reason
    if (typeof reason === 'string' && reason.trim()) return reason.trim()
  }
  return '-'
}

function getPrimitivePluginParams(value: unknown): Record<string, string | number | boolean | null> | undefined {
  const params = getPluginParams(value)
  const out: Record<string, string | number | boolean | null> = {}
  for (const [key, param] of Object.entries(params)) {
    if (!key) continue
    if (param === null || typeof param === 'string' || typeof param === 'number' || typeof param === 'boolean') {
      out[key] = param
    }
  }
  return Object.keys(out).length > 0 ? out : undefined
}

function getPluginSuggestedPipelinePatch(value: unknown): PipelinePluginSuggestedPatch {
  const raw = getPluginParams(value)
  const patch: PipelinePluginSuggestedPatch = {}
  if (typeof raw.governance_enabled === 'boolean') patch.governance_enabled = raw.governance_enabled
  if (typeof raw.persist_parsed_content === 'boolean') patch.persist_parsed_content = raw.persist_parsed_content
  const governanceParams = getPrimitivePluginParams(raw.governance_python_params)
  if (governanceParams) patch.governance_python_params = governanceParams
  const chunkParams = getPrimitivePluginParams(raw.chunk_python_params)
  if (chunkParams) patch.chunk_python_params = chunkParams
  const kgParams = getPrimitivePluginParams(raw.kg_python_params)
  if (kgParams) patch.kg_python_params = kgParams
  return patch
}

function SidebarChip({
  tone = 'sky',
  children,
  className,
}: Readonly<{ tone?: AccentTone; children: ReactNode; className?: string }>) {
  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full border px-1.5 py-0.5 text-[13px] font-semibold tracking-[0.04em]',
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
        'rounded-lg border px-2.5 py-1.5 text-[13px] leading-4',
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
}: Readonly<{ icon: PlatformIcon; label: string; tone?: AccentTone; aside?: string }>) {
  return (
    <div className="flex items-center justify-between gap-3">
      <div className="flex min-w-0 items-center gap-2">
        <span
          className={cn(
            SIDEBAR_COMPACT_ICON_FRAME_CLASS,
            SIDEBAR_TONE_STYLES[tone].icon
          )}
        >
          <Icon className={SIDEBAR_COMPACT_ICON_CLASS} strokeWidth={2.5} />
        </span>
        <h2 className="truncate text-[13px] font-medium text-foreground/90 antialiased">{label}</h2>
      </div>
      {aside ? <SidebarChip tone={tone}>{aside}</SidebarChip> : null}
    </div>
  )
}

function SidebarPanel({
  tone: _tone = 'sky',
  className,
  children,
}: Readonly<{ tone?: AccentTone; className?: string; children: ReactNode }>) {
  return (
    <section
      className={cn(
        styles.configurationSection,
        className
      )}
    >
      {children}
    </section>
  )
}

export function Sidebar({ variant = 'panel', section = 'all' }: SidebarProps = {}) {
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
    isSubmitting,
    chunkSize,
    chunkOverlap,
    chunkStrategy,
    separatorPreset,
    separatorCustom,
    keepSeparator,
    separatorMaxChunkSize,
    parentChildRatio,
    parentChildMinChildSize,
    parserBackend,
    processedStatus,
    selectedIngestFileIds,
    setCurrentFileIndex,
    removeFile,
    setDatasetId,
    updateSettings,
    updatePerfSettings,
    updateSeparatorSettings,
    updateParentChildSettings,
    runPreview,
    submitSelectedFiles,
    toggleIngestFileSelection,
  } = useChunkPreview()
  const pipelineCtx = usePipelineOptions()
  type PreviewSettingsPatch = Parameters<typeof updateSettings>[0]
  type PerfSettingsPatch = Parameters<typeof updatePerfSettings>[0]
  type ChunkStrategyParams = NonNullable<DocumentPipelineOptions['chunk_strategy_params']>

  const strategyForUi = chunkStrategy
  const isTokenStrategy = previewData?.params?.unit === 'tokens'

  const isSeparatorStrategy = strategyForUi === 'separator'
  const isParentChildStrategy = strategyForUi === 'parent_child'
  const statsUnitLabel = isTokenStrategy ? 'tok' : 'chars'

  const minMaxStatLabel = isTokenStrategy ? t('sidebar.stats.minMaxTokens') : t('sidebar.stats.minMaxLength')
  const histogramTitle = isTokenStrategy ? t('sidebar.stats.histogramTokens') : t('sidebar.stats.histogramLength')

  const sortedFileList = [...fileList].sort(
    (a, b) => (b.addedAt || 0) - (a.addedAt || 0)
  )

  const currentFileId = fileList[currentFileIndex]?.id
  const selectedIngestCount = selectedIngestFileIds.size

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
      const escapedValue = raw.replaceAll('"', String.raw`\"`)
      return JSON.parse(`"${escapedValue}"`)
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

  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [datasetsLoading, setDatasetsLoading] = useState(false)
  const [datasetsError, setDatasetsError] = useState<string | null>(null)
  const selectedDataset = useMemo(() => (datasetId ? datasets.find((ds) => ds.id === datasetId) || null : null), [datasetId, datasets])

  const [ingestionPreview, setIngestionPreview] = useState<IngestionPreviewResponse | null>(null)
  const [ingestionLoading, setIngestionLoading] = useState(false)
  const [ingestionError, setIngestionError] = useState<string | null>(null)
  const [ingestionDetailsOpen, setIngestionDetailsOpen] = useState(false)
  const [pipelinePlugins, setPipelinePlugins] = useState<PipelinePluginItem[]>([])
  const [pipelinePluginRegistryErrors, setPipelinePluginRegistryErrors] = useState<PipelinePluginListError[]>([])
  const [pipelinePluginsLoading, setPipelinePluginsLoading] = useState(false)
  const [pipelinePluginsError, setPipelinePluginsError] = useState<string | null>(null)
  const [goldenImportLoading, setGoldenImportLoading] = useState(false)
  const [goldenRegressionLoading, setGoldenRegressionLoading] = useState(false)
  const [pluginChunkReportLoading, setPluginChunkReportLoading] = useState(false)
  const [pluginChunkReport, setPluginChunkReport] = useState<PipelinePluginChunkReportResponse | null>(null)
  const [lastGoldenRegressionRun, setLastGoldenRegressionRun] = useState<{
    id: string
    href: string
    caseCount: number
  } | null>(null)

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

  const pythonPluginActive = Boolean(
    pipelineCtx.options.governance_python_plugin ||
      pipelineCtx.options.chunk_python_plugin ||
      pipelineCtx.options.kg_python_plugin
  )
  const governancePluginOptions = useMemo(
    () => pipelinePlugins.filter((plugin) => Boolean(plugin.refs.governance)),
    [pipelinePlugins]
  )
  const chunkPluginOptions = useMemo(
    () => pipelinePlugins.filter((plugin) => Boolean(plugin.refs.chunk)),
    [pipelinePlugins]
  )
  const kgPluginOptions = useMemo(
    () => pipelinePlugins.filter((plugin) => Boolean(plugin.refs.kg)),
    [pipelinePlugins]
  )
  const unreadyPluginCount = pipelinePlugins.filter((plugin) => !plugin.executable).length
  const firstPluginRegistryError = pipelinePluginRegistryErrors[0]
  const governancePluginValue = pipelineCtx.options.governance_python_plugin || PYTHON_PLUGIN_NONE_VALUE
  const chunkPluginValue = pipelineCtx.options.chunk_python_plugin || PYTHON_PLUGIN_NONE_VALUE
  const kgPluginValue = pipelineCtx.options.kg_python_plugin || PYTHON_PLUGIN_NONE_VALUE
  const governancePluginListed = governancePluginOptions.some(
    (plugin) => plugin.refs.governance === pipelineCtx.options.governance_python_plugin
  )
  const chunkPluginListed = chunkPluginOptions.some(
    (plugin) => plugin.refs.chunk === pipelineCtx.options.chunk_python_plugin
  )
  const kgPluginListed = kgPluginOptions.some(
    (plugin) => plugin.refs.kg === pipelineCtx.options.kg_python_plugin
  )
  const selectedChunkPlugin = useMemo(
    () => chunkPluginOptions.find((plugin) => plugin.refs.chunk === pipelineCtx.options.chunk_python_plugin) || null,
    [chunkPluginOptions, pipelineCtx.options.chunk_python_plugin]
  )
  const selectedGovernancePlugin = useMemo(
    () =>
      governancePluginOptions.find((plugin) => plugin.refs.governance === pipelineCtx.options.governance_python_plugin) ||
      null,
    [governancePluginOptions, pipelineCtx.options.governance_python_plugin]
  )
  const selectedKgPlugin = useMemo(
    () => kgPluginOptions.find((plugin) => plugin.refs.kg === pipelineCtx.options.kg_python_plugin) || null,
    [kgPluginOptions, pipelineCtx.options.kg_python_plugin]
  )
  const selectedGoldenPlugin = selectedChunkPlugin?.contract?.golden?.enabled ? selectedChunkPlugin : null
  const selectedGoldenPluginRef = selectedChunkPlugin?.refs.chunk || ''
  const selectedChunkPluginRef = selectedGoldenPluginRef
  const selectedAuditPlugin = selectedChunkPlugin || selectedGovernancePlugin || selectedKgPlugin
  const selectedAuditPackageHash = String(selectedAuditPlugin?.package_hash || '').trim()
  const selectedAuditReportOwner =
    selectedAuditPlugin?.test_report?.plugin_id && selectedAuditPlugin?.test_report?.version
      ? `${selectedAuditPlugin.test_report.plugin_id}@${selectedAuditPlugin.test_report.version}`
      : ''
  const selectedAuditTestedAt = String(selectedAuditPlugin?.test_report?.tested_at || '').trim()
  const selectedAuditGoldenTotal = selectedAuditPlugin?.test_report?.golden_draft?.items_total
  const failedReadinessChecks = useMemo(() => getFailedReadinessChecks(pluginChunkReport), [pluginChunkReport])
  const pluginChunkReportReadinessPassed =
    Boolean(pluginChunkReport?.passed) && pluginChunkReport?.readiness?.status === 'passed'
  const canImportGoldenDraft = Boolean(
    datasetId &&
    selectedGoldenPluginRef &&
    selectedGoldenPlugin?.executable &&
    selectedGoldenPlugin.contract?.golden?.enabled &&
    !goldenImportLoading
  )
  const selectedPipelinePlugin = selectedChunkPlugin || selectedGovernancePlugin || selectedKgPlugin
  const selectedPluginProcessingTemplates = Array.isArray(selectedPipelinePlugin?.processing_templates?.templates)
    ? selectedPipelinePlugin.processing_templates.templates.filter((template) => template.key && template.name)
    : []
  const selectedPipelinePluginPatch = useMemo<DocumentPipelineOptions | null>(() => {
    if (!selectedPipelinePlugin) return null
    return {
      ...REGISTERED_PLUGIN_BASE_PIPELINE_PATCH,
      ...getPluginSuggestedPipelinePatch(selectedPipelinePlugin.suggested_pipeline_patch),
      ...(selectedPipelinePlugin.refs.governance ? { governance_python_plugin: selectedPipelinePlugin.refs.governance } : {}),
      ...(selectedPipelinePlugin.refs.chunk ? { chunk_python_plugin: selectedPipelinePlugin.refs.chunk } : {}),
      ...(selectedPipelinePlugin.refs.kg ? { kg_python_plugin: selectedPipelinePlugin.refs.kg } : {}),
    }
  }, [selectedPipelinePlugin])

  const applySelectedPipelinePlugin = () => {
    if (!selectedPipelinePluginPatch || !selectedPipelinePlugin) {
      toast.error(t('sidebar.pythonPlugins.applySelectedPluginMissing'))
      return
    }
    applyPipelinePatch(selectedPipelinePluginPatch, {
      successMessage: t('sidebar.pythonPlugins.applySelectedSuccess', {
        name: `${selectedPipelinePlugin.name} v${selectedPipelinePlugin.version}`,
      })
    })
  }

  const clearPythonPlugins = () => {
    pipelineCtx.setEnabled(true)
    pipelineCtx.updateOption('governance_python_plugin', undefined)
    pipelineCtx.updateOption('governance_python_params', undefined)
    pipelineCtx.updateOption('chunk_python_plugin', undefined)
    pipelineCtx.updateOption('chunk_python_params', undefined)
    pipelineCtx.updateOption('kg_python_plugin', undefined)
    pipelineCtx.updateOption('kg_python_params', undefined)
    toast.success(t('sidebar.pythonPlugins.clearSuccess'))
  }

  const handleImportPluginGoldenDraft = async ({ runRegression = false }: { runRegression?: boolean } = {}) => {
    if (!datasetId) {
      toast.error(t('sidebar.pythonPlugins.importGoldenSelectDataset'))
      return
    }
    if (!selectedGoldenPluginRef) {
      toast.error(t('sidebar.pythonPlugins.importGoldenNoPlugin'))
      return
    }
    if (goldenImportLoading || goldenRegressionLoading) return

    const setLoading = runRegression ? setGoldenRegressionLoading : setGoldenImportLoading
    setLoading(true)
    try {
      const result = await pipelineApi.generateAndImportPluginGoldenDraft({
        dataset_id: datasetId,
        plugin_ref: selectedGoldenPluginRef,
        max_items: 500,
        overwrite: false,
      })
      const caseIds = result.import_result.case_ids ?? []
      const imported = caseIds.length
      if (result.draft.items_total <= 0 || imported <= 0) {
        toast.info(t('sidebar.pythonPlugins.importGoldenEmpty'))
        return
      }
      if (runRegression) {
        if (caseIds.length <= 0) {
          toast.info(t('sidebar.pythonPlugins.importGoldenRunNoCases'))
          return
        }
        const run = await evaluationApi.createRegressionRun({
          dataset_id: datasetId,
          case_ids: caseIds,
          metrics: [],
          use_llm_judge: false,
          skip_empty_contexts: true,
          enable_hierarchy_recall: true,
          hierarchy_sibling_window: 2,
          hierarchy_overfetch_factor: 4,
          max_cases: Math.max(1, Math.min(caseIds.length, 500)),
        })
        setLastGoldenRegressionRun({
          id: run.id,
          href: `/evaluations?tab=regression&dataset_id=${encodeURIComponent(datasetId)}&run_id=${encodeURIComponent(run.id)}`,
          caseCount: caseIds.length,
        })
        toast.success(
          t('sidebar.pythonPlugins.importGoldenRunSuccess', {
            count: caseIds.length,
            runId: run.id.slice(0, 8),
          })
        )
        return
      }
      toast.success(
        t('sidebar.pythonPlugins.importGoldenSuccess', {
          created: result.import_result.created,
          updated: result.import_result.updated,
          skipped: result.import_result.skipped,
        })
      )
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, t('sidebar.pythonPlugins.importGoldenError')))
    } finally {
      setLoading(false)
    }
  }

  const handleBuildPluginChunkReport = async () => {
    if (!selectedChunkPluginRef) {
      toast.error(t('sidebar.pythonPlugins.chunkReportNoPlugin'))
      return
    }
    if (pluginChunkReportLoading) return
    setPluginChunkReportLoading(true)
    try {
      const report = await pipelineApi.buildPluginChunkReport({
        plugin_ref: selectedChunkPluginRef,
        input_path: 'sample.json',
        max_examples_per_section: 2,
        preview_chars: 180,
      })
      setPluginChunkReport(report)
      if (report.passed) {
        toast.success(t('sidebar.pythonPlugins.chunkReportSuccess'))
      } else {
        toast.error(t('sidebar.pythonPlugins.chunkReportFailed'))
      }
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, t('sidebar.pythonPlugins.chunkReportError')))
    } finally {
      setPluginChunkReportLoading(false)
    }
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
    setPipelinePluginsLoading(true)
    setPipelinePluginsError(null)
    pipelineApi.listPipelinePlugins()
      .then((res) => {
        if (!alive) return
        setPipelinePlugins(res.items || [])
        setPipelinePluginRegistryErrors(res.errors || [])
      })
      .catch((error: unknown) => {
        if (!alive) return
        setPipelinePluginsError(getErrorMessage(error, t('sidebar.pythonPlugins.loadError')))
        setPipelinePluginRegistryErrors([])
      })
      .finally(() => {
        if (!alive) return
        setPipelinePluginsLoading(false)
      })
    return () => {
      alive = false
    }
  }, [t])

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
      className={section === 'settings' ? configStyles.shell : cn(styles.drawerBody, 'space-y-5')}
    >
        {section !== 'settings' && <SidebarPanel tone="sky" className="relative overflow-hidden p-0">
          <div
            data-dataset-scope-header="true"
            className="flex items-center px-3 py-3"
          >
            <div className="flex min-w-0 items-center gap-2.5">
              <div className={cn(SIDEBAR_LEAD_ICON_FRAME_CLASS, 'border-primary/20 bg-background')}>
                <Filter className={cn(SIDEBAR_LEAD_ICON_CLASS, 'text-primary')} strokeWidth={2.6} />
                {datasetId && (
                  <span className="absolute -right-0.5 -top-0.5 flex h-2 w-2">
                    <span className="absolute inline-flex h-full w-full animate-ping rounded-full bg-primary/40 opacity-75" />
                    <span className="relative inline-flex h-2 w-2 rounded-full bg-primary" />
                  </span>
                )}
              </div>
              <h2 className="truncate text-[13px] font-semibold text-foreground/90 antialiased">
                {t('sidebar.datasetScope.title')}
              </h2>
            </div>
          </div>

          <div
            data-dataset-scope-selector="true"
            className="border-t border-foreground/10 px-3 py-3"
          >
            <div className="relative group/select">
              <Select
                value={datasetId || DATASET_DEFAULT_VALUE}
                onValueChange={(value) => {
                  setIngestionPreview(null)
                  setIngestionError(null)
                  setDatasetId(value === DATASET_DEFAULT_VALUE ? '' : value)
                }}
              >
                <SelectTrigger
                  className={cn(
                    'h-9 rounded-md border-input/70 bg-background/70 px-3 text-[13px] font-medium text-foreground shadow-none transition-colors',
                    'hover:border-info/30 hover:bg-background',
                    'focus:ring-info/15',
                    datasetId && 'border-info/30 bg-info/[0.025]'
                  )}
                >
                  <SelectValue placeholder={t('sidebar.datasetScope.defaultOption')} />
                </SelectTrigger>
                <SelectContent className="rounded-lg border-info/20 bg-secondary p-1 shadow-lg">
                  <SelectItem value={DATASET_DEFAULT_VALUE} className="rounded-md py-2 text-[13px] font-medium focus:bg-info/[0.06] focus:text-info transition-colors">
                    <div className="flex items-center gap-3">
                      <div className={cn(SIDEBAR_LEAD_ICON_FRAME_CLASS, 'border-transparent bg-muted/10 text-muted-foreground')}>
                        <Globe className={SIDEBAR_LEAD_ICON_CLASS} strokeWidth={2.5} />
                      </div>
                      <span className="truncate">{t('sidebar.datasetScope.defaultOption')}</span>
                    </div>
                  </SelectItem>
                  <div className="mx-1 my-1 h-px bg-border/40" />
                  {datasets.map((ds) => (
                    <SelectItem key={ds.id} value={ds.id} className="rounded-md py-2 text-[13px] font-medium focus:bg-info/[0.06] focus:text-info transition-colors">
                      <div className="flex items-center gap-3">
                        <div className={cn(SIDEBAR_LEAD_ICON_FRAME_CLASS, 'border-transparent bg-info/[0.06] text-info')}>
                          <Database className={SIDEBAR_LEAD_ICON_CLASS} strokeWidth={2.5} />
                        </div>
                        <span className="truncate">{ds.name}</span>
                      </div>
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>

            <div className="mt-2 flex items-start gap-2 px-0.5 antialiased">
              <Sparkles className="mt-0.5 size-3 shrink-0 text-info/70" strokeWidth={2.4} />
              <p className="text-[13px] leading-4 text-muted-foreground/80">
                {datasetId ? t('sidebar.datasetScope.selectedHint') : t('sidebar.datasetScope.hint')}
              </p>
            </div>

            {(datasetsLoading || scopeSyncLoading) && (
              <div className="flex items-center gap-2.5 px-1 text-[13px] font-medium text-primary/80 antialiased">
                <div className="relative flex h-3 w-3">
                  <Loader2 className="h-full w-full animate-spin" strokeWidth={3} />
                </div>
                {datasetsLoading ? t('sidebar.dataset.loading') : t('sidebar.datasetScope.syncing')}
              </div>
            )}

            {(datasetsError || scopeSyncError) && (
              <SidebarNote tone="amber" className="py-2.5 border-warning/20 bg-warning/5 shadow-sm">
                <div className="flex items-start gap-2.5">
                  <div className="flex h-4 w-4 shrink-0 items-center justify-center rounded-full bg-warning/10 text-warning">
                    <AlertCircle className="h-3 w-3" strokeWidth={3} />
                  </div>
                  <span className="font-medium text-[13px] leading-relaxed text-warning">
                    {datasetsError || scopeSyncError}
                  </span>
                </div>
              </SidebarNote>
            )}
          </div>

          <div
            data-chunk-file-queue
            className="border-t border-foreground/10 px-3 py-3"
          >
            <div className="flex items-center justify-between gap-3">
              <SidebarSectionHeader
                icon={Folder}
                label={t('sidebar.fileList.title', { count: fileList.length })}
                tone="sky"
              />
            </div>

            <div
              data-chunk-file-list
              className="mt-2 max-h-[216px] space-y-1 overflow-y-auto overscroll-contain no-scrollbar"
            >
            {sortedFileList.length === 0 ? (
              <div className="py-3">
                <div className="text-[13px] font-medium text-foreground/75">
                  {getEmptyFileListLabel({
                    scopeSyncLoading,
                    datasetId,
                    labels: {
                      syncing: t('sidebar.datasetScope.syncing'),
                      emptyDataset: t('sidebar.fileList.emptyDataset'),
                      emptyAll: t('sidebar.fileList.emptyAll'),
                    },
                  })}
                </div>
                <div className="mt-1 text-[13px] leading-4 text-muted-foreground/70">
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
              return (
                <div
                  key={f.id}
                  className={cn(
                    'group relative overflow-hidden rounded-xl border text-[13px] transition-[background,border,box-shadow] duration-150',
                    isActive
                      ? 'border-primary/18 bg-background/78 shadow-none'
                      : 'border-transparent bg-background/45 hover:border-border/40 hover:bg-background/70'
                  )}
                >
                  <button
                    type="button"
                    onClick={() => {
                      if (fileIndex >= 0) setCurrentFileIndex(fileIndex)
                    }}
                    aria-label={t('sidebar.fileList.selectFile', { name: f.displayName })}
                    className="block w-full min-w-0 cursor-pointer rounded-xl py-2 pl-2.5 pr-24 text-left focus-ring"
                  >
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
                        {processedStatus[f.id] === 'processing' ? <Loader2 className="h-3 w-3 shrink-0 animate-spin text-info motion-reduce:animate-none" /> : null}
                        {processedStatus[f.id] === 'success' ? <Check className="h-3 w-3 shrink-0 text-success" /> : null}
                        {processedStatus[f.id] === 'error' ? <AlertCircle className="h-3 w-3 shrink-0 text-destructive" /> : null}
                      </span>
                      <span
                        className="mt-0.5 flex min-w-0 items-center gap-1 overflow-hidden text-[13px] leading-3 text-muted-foreground/75"
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
                      'absolute right-1.5 top-1/2 -translate-y-1/2 cursor-pointer rounded-md px-1.5 py-1 text-[13px] font-medium text-muted-foreground/62 opacity-0 transition-colors transition-opacity duration-150 motion-reduce:transition-none',
                      'hover:bg-destructive/8 hover:text-destructive focus-ring focus-visible:opacity-100 group-hover:opacity-100',
                      isActive ? 'opacity-80' : ''
                    )}
                    aria-label={t('sidebar.fileList.removeFile', { name: f.displayName })}
                    title={t('sidebar.fileList.removeFile', { name: f.displayName })}
                  >
                    {t('sidebar.fileList.removeShort')}
                  </button>
                  <button
                    type="button"
                    onClick={() => toggleIngestFileSelection(f.id)}
                    aria-pressed={isSelectedForIngest}
                    aria-label={t('sidebar.fileList.toggleForIngest', { name: f.displayName })}
                    title={t('sidebar.fileList.toggleForIngest', { name: f.displayName })}
                    className={cn(
                      'absolute right-10 top-1/2 h-5 -translate-y-1/2 cursor-pointer rounded-md border px-1.5 text-[13px] font-medium opacity-0 transition-colors transition-opacity duration-150 motion-reduce:transition-none focus-ring focus-visible:opacity-100 group-hover:opacity-100',
                      isSelectedForIngest || isActive ? 'opacity-100' : '',
                      isSelectedForIngest
                        ? 'border-primary/25 bg-primary/10 text-primary shadow-none'
                        : 'border-border/40 bg-background/70 text-muted-foreground hover:border-primary/20 hover:bg-background hover:text-primary'
                    )}
                  >
                    {isSelectedForIngest ? t('sidebar.fileList.selectedForIngestShort') : t('sidebar.fileList.selectForIngestShort')}
                  </button>
                </div>
              )
            })}
            </div>

            <div className="mt-2 flex items-center justify-between gap-2 border-t border-foreground/10 pt-2">
              <div className="flex min-w-0 items-center gap-1.5">
                <span
                  className={cn(
                    'h-1.5 w-1.5 shrink-0 rounded-full',
                    selectedIngestCount > 0 ? 'bg-primary shadow-[0_0_0_3px_hsl(var(--primary)/0.12)]' : 'bg-muted-foreground/35'
                  )}
                />
                <span className="min-w-0 truncate text-[13px] font-medium text-muted-foreground/85">
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
                className="h-6 shrink-0 rounded-lg px-2 text-[13px] shadow-none"
              >
                {selectedIngestCount > 0 ? t('sidebar.fileList.batchIngest') : t('sidebar.fileList.batchIngestShort')}
              </Button>
            </div>
          </div>

          <div className="space-y-2 border-t border-foreground/10 px-3 py-3">
            {selectedDataset?.pipeline ? (
              <div className="border-b border-foreground/10 pb-2">
                <div className="flex items-start justify-between gap-2">
                  <div className="min-w-0 flex-1">
                    <div className="text-[13px] font-medium text-foreground/82">{t('sidebar.dataset.pipelineSummary')}</div>
                    <div className="mt-1 flex flex-wrap gap-1.5 text-[13px]">
                      {selectedDataset.pipeline.governance_enabled ? (
                        <span className="rounded-full border border-primary/18 bg-primary/7 px-1.5 py-0.5 text-primary">
                          {t('sidebar.dataset.badges.governanceOn')}
                        </span>
                      ) : (
                        <span className="rounded-full border border-border/60 bg-muted px-1.5 py-0.5 text-muted-foreground">
                          {t('sidebar.dataset.badges.governanceOff')}
                        </span>
                      )}
                      {selectedDataset.pipeline.chunk_vector_enabled ? (
                        <span className="rounded-full border border-primary/20 bg-primary/10 px-1.5 py-0.5 text-primary">
                          {t('sidebar.dataset.badges.vectorOn')}
                        </span>
                      ) : (
                        <span className="rounded-full border border-border/60 bg-muted px-1.5 py-0.5 text-muted-foreground">
                          {t('sidebar.dataset.badges.vectorOff')}
                        </span>
                      )}
                      {selectedDataset.pipeline.bm25_index_enabled ? (
                        <span className="rounded-full border border-primary/20 bg-primary/10 px-1.5 py-0.5 text-primary">
                          {t('sidebar.dataset.badges.bm25On')}
                        </span>
                      ) : (
                        <span className="rounded-full border border-border/60 bg-muted px-1.5 py-0.5 text-muted-foreground">
                          {t('sidebar.dataset.badges.bm25Off')}
                        </span>
                      )}
                      {selectedDataset.pipeline.kg_enabled ? (
                        <span className="rounded-full border border-primary/18 bg-primary/7 px-1.5 py-0.5 text-primary">
                          {t('sidebar.dataset.badges.kg')}
                        </span>
                      ) : null}
                    </div>
                  </div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-6 shrink-0 rounded-lg px-2 text-[13px]"
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
              </div>
            ) : null}

            <Button
              type="button"
              variant="outline"
              disabled={!datasetId || !currentFile || ingestionLoading}
              className="h-8 w-full justify-start rounded-md border-info/15 bg-info/[0.04] text-[13px] shadow-none hover:bg-info/[0.08]"
              title={!datasetId ? t('sidebar.ingestionPreview.selectDatasetFirst') : undefined}
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
                <Loader2 className="mr-2 size-4 shrink-0 animate-spin motion-reduce:animate-none" />
              ) : (
                <Wand2 className="mr-2 size-4 shrink-0 text-primary" />
              )}
              {t('sidebar.ingestionPreview.trigger')}
            </Button>

            <FeedbackToast type="error" message={ingestionError} id="chunk-ingestion-preview-feedback" />

            {ingestionPreview ? (
              <div className="space-y-2 rounded-xl border border-border/50 bg-background p-2.5">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[13px] text-muted-foreground">{t('sidebar.ingestionPreview.result.title')}</div>
                  <div className="flex items-center gap-1">
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-7 px-2 text-[13px]"
                      onClick={() => setIngestionDetailsOpen(true)}
                    >
                      {t('sidebar.ingestionPreview.result.details')}
                    </Button>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      className="h-7 px-2 text-[13px]"
                      onClick={() => setIngestionPreview(null)}
                    >
                      {t('sidebar.ingestionPreview.result.clear')}
                    </Button>
                  </div>
                </div>
                <div className="text-[13px] font-medium text-foreground/90">
                  {ingestionPreview.rule.matched
                    ? t('sidebar.ingestionPreview.result.matchedRule', {
                      name: ingestionPreview.rule.rule_name
                        || ingestionPreview.rule.rule_id
                        || t('sidebar.ingestionPreview.result.matchedRuleFallback'),
                    })
                    : t('sidebar.ingestionPreview.result.defaultRule')}
                </div>
                <div className="text-[13px] text-muted-foreground font-mono">
                  {t('sidebar.ingestionPreview.result.parserStrategy', {
                    parser: ingestionPreview.rule.parser_backend,
                    strategy: ingestionPreview.rule.chunk_strategy,
                  })}
                </div>
                {ingestionPreview.rule.governance_profile_ref ? (
                  <div className="text-[13px] text-muted-foreground">
                    {t('sidebar.ingestionPreview.result.governanceProfile', {
                      value: ingestionPreview.rule.governance_profile_ref,
                    })}
                  </div>
                ) : null}
                <div className="text-[13px] text-muted-foreground">
                  {t('sidebar.ingestionPreview.result.preprocessSteps', {
                    count: ingestionPreview.rule.preprocess_steps.length,
                  })}
                </div>
                <div className="text-[13px] text-muted-foreground">
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
                    className="h-8 px-3 text-[13px]"
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
                    className="h-8 px-3 text-[13px]"
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
        </SidebarPanel>}

        {section !== 'documents' && <AdvancedConfigBody
          pluginSettings={<div
              data-python-pipeline-plugin-panel
              className={configStyles.pluginSettings}
            >
              <div className="flex items-start justify-between gap-3">
                <div className="flex min-w-0 items-start gap-2">
                  <span className={cn(SIDEBAR_LEAD_ICON_FRAME_CLASS, 'mt-0.5 border-accent/20 bg-accent/8 text-accent')}>
                    <FileCode2 className={SIDEBAR_LEAD_ICON_CLASS} strokeWidth={2.6} />
                  </span>
                  <div className="min-w-0">
                    <div className="text-[13px] font-medium leading-4 text-foreground">{t('sidebar.pythonPlugins.title')}</div>
                    <div className="text-[13px] font-medium leading-6 text-muted-foreground">
                      {t('sidebar.pythonPlugins.description')}
                    </div>
                  </div>
                </div>
                <SidebarChip tone={pythonPluginActive ? 'violet' : 'amber'}>
                  {pythonPluginActive ? t('sidebar.pythonPlugins.active') : t('sidebar.pythonPlugins.inactive')}
                </SidebarChip>
              </div>

              <div className="grid gap-2">
                <label className="grid gap-1">
                  <span className="text-[13px] font-medium text-muted-foreground">{t('sidebar.pythonPlugins.governancePluginLabel')}</span>
                  <Select
                    value={governancePluginValue}
                    onValueChange={(value) => {
                      pipelineCtx.setEnabled(true)
                      pipelineCtx.updateOption(
                        'governance_python_plugin',
                        value === PYTHON_PLUGIN_NONE_VALUE ? undefined : value
                      )
                    }}
                  >
                    <SelectTrigger className="h-8 rounded-lg bg-background/75 text-[13px] font-medium">
                      <SelectValue placeholder={t('sidebar.pythonPlugins.selectPlaceholder')} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={PYTHON_PLUGIN_NONE_VALUE}>
                        {t('sidebar.pythonPlugins.none')}
                      </SelectItem>
                      {pipelineCtx.options.governance_python_plugin && !governancePluginListed ? (
                        <SelectItem value={pipelineCtx.options.governance_python_plugin}>
                          {t('sidebar.pythonPlugins.currentImportPath')}
                        </SelectItem>
                      ) : null}
                      {governancePluginOptions.map((plugin) => (
                        <SelectItem
                          key={`${plugin.id}@${plugin.version}:governance`}
                          value={plugin.refs.governance || ''}
                          disabled={!plugin.executable}
                        >
                          {plugin.name} v{plugin.version}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </label>
                <label className="grid gap-1">
                  <span className="text-[13px] font-medium text-muted-foreground">{t('sidebar.pythonPlugins.chunkPluginLabel')}</span>
                  <Select
                    value={chunkPluginValue}
                    onValueChange={(value) => {
                      pipelineCtx.setEnabled(true)
                      pipelineCtx.updateOption(
                        'chunk_python_plugin',
                        value === PYTHON_PLUGIN_NONE_VALUE ? undefined : value
                      )
                    }}
                  >
                    <SelectTrigger className="h-8 rounded-lg bg-background/75 text-[13px] font-medium">
                      <SelectValue placeholder={t('sidebar.pythonPlugins.selectPlaceholder')} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={PYTHON_PLUGIN_NONE_VALUE}>
                        {t('sidebar.pythonPlugins.none')}
                      </SelectItem>
                      {pipelineCtx.options.chunk_python_plugin && !chunkPluginListed ? (
                        <SelectItem value={pipelineCtx.options.chunk_python_plugin}>
                          {t('sidebar.pythonPlugins.currentImportPath')}
                        </SelectItem>
                      ) : null}
                      {chunkPluginOptions.map((plugin) => (
                        <SelectItem
                          key={`${plugin.id}@${plugin.version}:chunk`}
                          value={plugin.refs.chunk || ''}
                          disabled={!plugin.executable}
                        >
                          {plugin.name} v{plugin.version}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </label>
                <label className="grid gap-1">
                  <span className="text-[13px] font-medium text-muted-foreground">{t('sidebar.pythonPlugins.kgPluginLabel')}</span>
                  <Select
                    value={kgPluginValue}
                    onValueChange={(value) => {
                      pipelineCtx.setEnabled(true)
                      pipelineCtx.updateOption(
                        'kg_python_plugin',
                        value === PYTHON_PLUGIN_NONE_VALUE ? undefined : value
                      )
                    }}
                  >
                    <SelectTrigger className="h-8 rounded-lg bg-background/75 text-[13px] font-medium">
                      <SelectValue placeholder={t('sidebar.pythonPlugins.selectPlaceholder')} />
                    </SelectTrigger>
                    <SelectContent>
                      <SelectItem value={PYTHON_PLUGIN_NONE_VALUE}>
                        {t('sidebar.pythonPlugins.none')}
                      </SelectItem>
                      {pipelineCtx.options.kg_python_plugin && !kgPluginListed ? (
                        <SelectItem value={pipelineCtx.options.kg_python_plugin}>
                          {t('sidebar.pythonPlugins.currentImportPath')}
                        </SelectItem>
                      ) : null}
                      {kgPluginOptions.map((plugin) => (
                        <SelectItem
                          key={`${plugin.id}@${plugin.version}:kg`}
                          value={plugin.refs.kg || ''}
                          disabled={!plugin.executable}
                        >
                          {plugin.name} v{plugin.version}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>
                </label>
                {pipelinePluginsLoading ? (
                  <SidebarNote tone="violet">{t('sidebar.pythonPlugins.loading')}</SidebarNote>
                ) : pipelinePluginsError ? (
                  <SidebarNote tone="amber">{pipelinePluginsError}</SidebarNote>
                ) : pipelinePlugins.length === 0 ? (
                  <SidebarNote tone="amber">{t('sidebar.pythonPlugins.empty')}</SidebarNote>
                ) : unreadyPluginCount > 0 ? (
                  <SidebarNote tone="amber">
                    {t('sidebar.pythonPlugins.unreadyCount', { count: unreadyPluginCount })}
                  </SidebarNote>
                ) : null}
                {!pipelinePluginsLoading && pipelinePluginRegistryErrors.length > 0 ? (
                  <SidebarNote tone="amber">
                    {t('sidebar.pythonPlugins.registryErrorCount', {
                      count: pipelinePluginRegistryErrors.length,
                      path: firstPluginRegistryError?.plugin_dir || '-',
                    })}
                  </SidebarNote>
                ) : null}
                {selectedAuditPlugin ? (
                  <div
                    data-python-pipeline-plugin-audit
                    className="grid gap-1 rounded-lg border border-border/40 bg-muted/12 px-2 py-1.5 text-[13px] font-medium leading-6 text-muted-foreground"
                  >
                    <div className="flex min-w-0 items-center justify-between gap-2">
                      <span className="truncate font-medium text-foreground">
                        {t('sidebar.pythonPlugins.auditTitle')}
                      </span>
                      <span className="shrink-0 font-mono text-muted-foreground">
                        {selectedAuditPackageHash ? selectedAuditPackageHash.slice(0, 12) : '-'}
                      </span>
                    </div>
                    <div className="flex min-w-0 items-center justify-between gap-2">
                      <span className="truncate">
                        {selectedAuditTestedAt
                          ? t('sidebar.pythonPlugins.auditTestedAt', { value: selectedAuditTestedAt })
                          : t('sidebar.pythonPlugins.auditUntested')}
                      </span>
                      {typeof selectedAuditGoldenTotal === 'number' ? (
                        <span className="shrink-0">
                          {t('sidebar.pythonPlugins.auditGoldenCount', { count: selectedAuditGoldenTotal })}
                        </span>
                      ) : null}
                    </div>
                    {selectedAuditReportOwner ? (
                      <div className="truncate font-mono text-[13px] text-muted-foreground">
                        {t('sidebar.pythonPlugins.auditReportOwner', { value: selectedAuditReportOwner })}
                      </div>
                    ) : null}
                  </div>
                ) : null}
                {selectedChunkPlugin ? (
                  <div
                    data-python-pipeline-plugin-chunk-report
                    className="grid gap-1.5 rounded-lg border border-border/40 bg-background/50 px-2 py-2 text-[13px] leading-6"
                  >
                    <div className="flex items-center justify-between gap-2">
                      <span className="truncate text-[13px] font-medium text-foreground">
                        {t('sidebar.pythonPlugins.chunkReportTitle')}
                      </span>
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-6 shrink-0 rounded-lg px-2 text-[13px] shadow-none"
                        disabled={!selectedChunkPluginRef || pluginChunkReportLoading}
                        onClick={handleBuildPluginChunkReport}
                      >
                        {pluginChunkReportLoading ? (
                          <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                        ) : (
                          <Check className="mr-1.5 h-3 w-3" />
                        )}
                        {t('sidebar.pythonPlugins.chunkReportBuild')}
                      </Button>
                    </div>
                    <div className="text-[13px] font-medium leading-3 text-muted-foreground">
                      {t('sidebar.pythonPlugins.chunkReportHint')}
                    </div>
                    {pluginChunkReport ? (
                      <div className="grid gap-1 rounded-md border border-border/35 bg-muted/18 px-1.5 py-1 text-muted-foreground">
                        <div className="flex items-center justify-between gap-2">
                          <span
                            className={cn(
                              'rounded-full border px-1.5 py-0.5 text-[13px] font-medium',
                              pluginChunkReportReadinessPassed
                                ? 'border-success/20 bg-success/8 text-success'
                                : 'border-destructive/20 bg-destructive/8 text-destructive'
                            )}
                          >
                            {pluginChunkReportReadinessPassed
                              ? t('sidebar.pythonPlugins.chunkReportReadinessPassed')
                              : t('sidebar.pythonPlugins.chunkReportReadinessFailed', {
                                  count: failedReadinessChecks.length,
                                })}
                          </span>
                        </div>
                        {failedReadinessChecks.length > 0 ? (
                          <div className="grid gap-0.5 rounded border border-destructive/15 bg-destructive/5 px-1.5 py-1 text-[13px] leading-3 text-destructive/85">
                            {failedReadinessChecks.slice(0, 3).map((check) => (
                              <div key={check.name} className="truncate">
                                {t('sidebar.pythonPlugins.chunkReportErrorSummary', {
                                  name: check.name,
                                  reason: getReadinessErrorReason(check),
                                })}
                              </div>
                            ))}
                          </div>
                        ) : null}
                        <div className="font-semibold text-foreground">
                          {t('sidebar.pythonPlugins.chunkReportSummary', {
                            records: getReportNumber(pluginChunkReport.summary, 'governed_records'),
                            chunks: getReportNumber(pluginChunkReport.summary, 'chunks'),
                            kgEvents: getReportNumber(pluginChunkReport.summary, 'kg_events'),
                          })}
                        </div>
                        <div className="flex flex-wrap gap-1">
                          {pluginChunkReport.sections.slice(0, 4).map((section) => (
                            <span
                              key={section.knowledge_section}
                              className="rounded-full border border-border/35 bg-background/65 px-1.5 py-0.5 font-mono text-[13px] text-muted-foreground"
                            >
                              {section.knowledge_section || '-'} · {section.chunks}
                            </span>
                          ))}
                        </div>
                      </div>
                    ) : null}
                  </div>
                ) : null}
                {selectedPipelinePlugin ? (
                  <div
                    data-python-pipeline-plugin-templates
                    className="grid gap-1.5 rounded-lg border border-border/40 bg-background/45 px-2 py-1.5 text-[13px] leading-6"
                  >
                    <div className="flex min-w-0 items-center justify-between gap-2">
                      <span className="truncate text-[13px] font-medium text-foreground">
                        {t('sidebar.pythonPlugins.processingTemplatesTitle')}
                      </span>
                      <SidebarChip tone="violet">
                        {selectedPluginProcessingTemplates.length}
                      </SidebarChip>
                    </div>
                    <div className="text-[13px] font-medium leading-3 text-muted-foreground">
                      {t('sidebar.pythonPlugins.processingTemplatesHint')}
                    </div>
                    {selectedPluginProcessingTemplates.length ? (
                      <div className="grid gap-1">
                        {selectedPluginProcessingTemplates.slice(0, 6).map((template) => (
                          <div
                            key={template.key}
                            className="flex min-w-0 items-center justify-between gap-2 rounded-md border border-border/35 bg-muted/18 px-1.5 py-1"
                          >
                            <span className="truncate font-semibold text-foreground">
                              {template.name}
                            </span>
                            <span className="shrink-0 rounded-full border border-border/40 bg-background/70 px-1.5 py-0.5 font-mono text-[13px] uppercase text-muted-foreground">
                              {template.stage}
                            </span>
                          </div>
                        ))}
                      </div>
                    ) : (
                      <div className="rounded-md border border-border/35 bg-muted/18 px-1.5 py-1 text-muted-foreground">
                        {t('sidebar.pythonPlugins.processingTemplatesEmpty')}
                      </div>
                    )}
                  </div>
                ) : null}
                {selectedGoldenPlugin?.contract?.golden?.enabled ? (
                  <div className="grid gap-1.5 rounded-lg border border-border/40 bg-muted/12 px-2 py-2">
                    <div className="flex items-center justify-between gap-2">
                      <span className="min-w-0 text-[13px] font-medium text-muted-foreground">
                        {t('sidebar.pythonPlugins.goldenTitle')}
                      </span>
                      <SidebarChip tone="violet">
                        {selectedGoldenPlugin.name} v{selectedGoldenPlugin.version}
                      </SidebarChip>
                    </div>
                    <div className="grid grid-cols-2 gap-1.5">
                      <Button
                        type="button"
                        size="sm"
                        variant="outline"
                        className="h-7 justify-center rounded-lg px-2 text-[13px] shadow-none"
                        disabled={!canImportGoldenDraft || goldenImportLoading || goldenRegressionLoading}
                        onClick={() => handleImportPluginGoldenDraft()}
                      >
                        {goldenImportLoading ? (
                          <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                        ) : (
                          <Sparkles className="mr-1.5 h-3 w-3" />
                        )}
                        {t('sidebar.pythonPlugins.importGolden')}
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        className="h-7 justify-center rounded-lg px-2 text-[13px] shadow-none"
                        disabled={!canImportGoldenDraft || goldenImportLoading || goldenRegressionLoading}
                        onClick={() => handleImportPluginGoldenDraft({ runRegression: true })}
                      >
                        {goldenRegressionLoading ? (
                          <Loader2 className="mr-1.5 h-3 w-3 animate-spin" />
                        ) : (
                          <BarChart3 className="mr-1.5 h-3 w-3" />
                        )}
                        {t('sidebar.pythonPlugins.importAndRunGolden')}
                      </Button>
                    </div>
                    <div className="text-[13px] font-medium leading-6 text-muted-foreground">
                      {datasetId ? t('sidebar.pythonPlugins.importGoldenHint') : t('sidebar.pythonPlugins.importGoldenSelectDataset')}
                    </div>
                    {lastGoldenRegressionRun ? (
                      <div className="flex items-center justify-between gap-2 rounded-lg border border-primary/15 bg-primary/5 px-2 py-1.5">
                        <div className="min-w-0">
                          <div className="truncate text-[13px] font-medium text-primary">
                            Run {lastGoldenRegressionRun.id.slice(0, 8)}
                          </div>
                          <div className="text-[13px] font-medium text-muted-foreground">
                            {t('sidebar.pythonPlugins.goldenRunCaseCount', {
                              count: lastGoldenRegressionRun.caseCount,
                            })}
                          </div>
                        </div>
                        <Button asChild size="sm" variant="outline" className="h-6 shrink-0 rounded-lg px-2 text-[13px] shadow-none">
                          <Link href={lastGoldenRegressionRun.href}>
                            {t('sidebar.pythonPlugins.viewGoldenRun')}
                          </Link>
                        </Button>
                      </div>
                    ) : null}
                  </div>
                ) : null}
              </div>

              <div className="flex items-center gap-2">
                <Button
                  type="button"
                  size="sm"
                  className="h-7 rounded-lg px-2 text-[13px] shadow-none"
                  disabled={pipelinePluginsLoading || !selectedPipelinePluginPatch}
                  onClick={applySelectedPipelinePlugin}
                >
                  {t('sidebar.pythonPlugins.applySelected')}
                </Button>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-7 rounded-lg px-2 text-[13px] shadow-none"
                  disabled={!pythonPluginActive}
                  onClick={clearPythonPlugins}
                >
                  {t('sidebar.pythonPlugins.clear')}
                </Button>
              </div>
            </div>}
          strategySettings={<>
            {isSeparatorStrategy ? (
            <SidebarPanel tone="cyan" className="space-y-3">
              <div className="flex items-center justify-between gap-2">
                <div className="text-[13px] font-semibold text-foreground/82">{t('sidebar.separator.title')}</div>
                <SidebarChip tone="cyan">分隔</SidebarChip>
              </div>

              <div className="flex items-center justify-between gap-2">
                <div className="text-[13px] text-muted-foreground">{t('sidebar.separator.syncToPipeline')}</div>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-7 px-2 text-[13px]"
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
                <div className="text-[13px] text-muted-foreground font-mono break-all">
                  {t('sidebar.separator.currentPipeline', {
                    value: JSON.stringify(pipelineCtx.options.chunk_strategy_params),
                  })}
                </div>
              ) : (
                <div className="text-[13px] text-muted-foreground font-mono">
                  {t('sidebar.separator.currentPipeline', {
                    value: t('sidebar.separator.currentPipelineEmpty'),
                  })}
                </div>
              )}

              <div className="space-y-2">
                <div className="text-[13px] font-medium text-muted-foreground">{t('sidebar.separator.presetLabel')}</div>
                <Select
                  value={separatorPreset}
                  onValueChange={(value) => updateSeparatorSettings({ separatorPreset: value })}
                >
                  <SelectTrigger className="h-8 bg-background text-[13px]">
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
                  <div className="text-[13px] text-muted-foreground font-mono">
                    {t('sidebar.separator.effectiveSeparator', {
                      value: JSON.stringify(effectiveSeparator).slice(1, -1) || t('sidebar.separator.currentPipelineEmpty'),
                      length: effectiveSeparator.length,
                    })}
                  </div>
                ) : null}
              </div>

              {separatorPreset === 'custom' ? (
                <div className="space-y-2">
                  <div className="text-[13px] font-medium text-muted-foreground">{t('sidebar.separator.customLabel')}</div>
                  <Input
                    value={separatorCustom}
                    onChange={(e) => updateSeparatorSettings({ separatorCustom: e.target.value })}
                    className="h-9 text-[13px] font-mono bg-background"
                    placeholder={t('sidebar.separator.customPlaceholder')}
                    aria-label={t('sidebar.separator.customAria')}
                  />
                  <SidebarNote tone="cyan" className="py-1.5">{t('sidebar.separator.customHelp')}</SidebarNote>
                </div>
              ) : null}

              <div className="flex items-center justify-between gap-2 rounded-lg border border-border/60 bg-card/75 px-2.5 py-1.5">
                <div>
                  <div className="text-[13px] font-medium text-foreground/82">{t('sidebar.separator.keepSeparator.title')}</div>
                  <div className="text-[13px] text-muted-foreground">{t('sidebar.separator.keepSeparator.description')}</div>
                </div>
                <label className="inline-flex items-center gap-2 text-[13px] text-muted-foreground">
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
                  <div className="text-[13px] font-medium text-muted-foreground">{t('sidebar.separator.maxChunkLength')}</div>
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
                    className="h-7 w-24 text-[13px] font-mono bg-background"
                    aria-label={t('sidebar.separator.maxChunkLengthAria')}
                  />
                </div>
                <SidebarNote tone="cyan" className="py-1.5">{t('sidebar.separator.maxChunkLengthHelp')}</SidebarNote>
              </div>
            </SidebarPanel>
          ) : null}
            {isParentChildStrategy ? (
            <SidebarPanel tone="emerald" className="space-y-3">
              <div className="text-[13px] font-semibold text-foreground/84">{t('sidebar.parentChild.title')}</div>

              <div className="flex items-center justify-between gap-2">
                <div className="text-[13px] text-muted-foreground">{t('sidebar.parentChild.syncToPipeline')}</div>
                <Button
                  type="button"
                  size="sm"
                  variant="outline"
                  className="h-6 px-2 text-[13px]"
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
                <div className="text-[13px] text-muted-foreground/80 font-mono break-all">
                  {t('sidebar.parentChild.currentPipeline', {
                    value: JSON.stringify(pipelineCtx.options.chunk_strategy_params),
                  })}
                </div>
              ) : (
                <div className="text-[13px] text-muted-foreground/80 font-mono">
                  {t('sidebar.parentChild.currentPipeline', {
                    value: t('sidebar.parentChild.currentPipelineEmpty'),
                  })}
                </div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <div className="text-[13px] font-medium text-muted-foreground">{t('sidebar.parentChild.ratioLabel')}</div>
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
                    className="h-8 text-[13px] font-mono bg-background"
                    aria-label={t('sidebar.parentChild.ratioAria')}
                  />
                  <SidebarNote tone="emerald" className="py-1">{t('sidebar.parentChild.ratioHelp')}</SidebarNote>
                </div>

                <div className="space-y-2">
                  <div className="text-[13px] font-medium text-muted-foreground">{t('sidebar.parentChild.minChildSizeLabel')}</div>
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
                    className="h-8 text-[13px] font-mono bg-background"
                    aria-label={t('sidebar.parentChild.minChildSizeAria')}
                  />
                  <SidebarNote tone="emerald" className="py-1">{t('sidebar.parentChild.minChildSizeHelp')}</SidebarNote>
                </div>
              </div>

              {parentChildEffective ? (
                <SidebarNote tone="emerald" className="font-mono text-[13px]">
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
          </>}
          analysisDetails={<>
            {serverStats ? (
                  <div className="mt-3 grid grid-cols-2 gap-3">
                <div className="border-b border-border py-3">
                  <div className="text-[13px] text-muted-foreground uppercase  font-medium">{minMaxStatLabel}</div>
                  <div className="mt-1 text-sm font-mono text-foreground/90">
                    {serverStats.min} / {serverStats.max}
                  </div>
                  <div className="mt-1 text-[13px] text-muted-foreground font-mono">{t('sidebar.stats.p10', { value: serverStats.p10 ?? '-' })}</div>
                </div>
                <div className="border-b border-border py-3">
                  <div className="text-[13px] text-muted-foreground uppercase  font-medium">{t('sidebar.stats.qualitySignals')}</div>
                  <div className="mt-1 text-[13px] text-muted-foreground">
                    {t('sidebar.stats.qualitySummary', {
                      shortCount: serverStats.short_count ?? 0,
                      duplicateCount: serverStats.duplicate_count ?? 0,
                    })}
                  </div>
                  {overlapGuidance ? (
                    <div className={cn('mt-1 text-[13px]', overlapGuidance.outOfRange ? 'text-warning' : 'text-muted-foreground')}>
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
                        'mt-1 text-[13px]',
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
                <div className="col-span-2 border-b border-border py-3">
                  <div className="text-[13px] text-muted-foreground uppercase  font-medium">{histogramTitle}</div>
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
                    <div className="mt-2 text-[13px] text-muted-foreground">{t('sidebar.stats.histogramEmpty')}</div>
                  )}
                  <div className="mt-2 flex items-center justify-between text-[13px] text-muted-foreground font-mono">
                    <span>0</span>
                    <span>{histogramMax || serverStats.max}</span>
                  </div>
                </div>
                {previewData?.recommendations?.length || previewData?.recommendation_patches?.length ? (
                  <div className="col-span-2 border-b border-border py-3">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-[13px] text-muted-foreground uppercase  font-medium">{t('sidebar.recommendations.title')}</div>
                      {previewData?.recommendation_patches?.length ? (
                        <Button
                          type="button"
                          size="sm"
                          variant="outline"
                          className="h-7 px-2 text-[13px]"
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
                          const targetLabel = getRecommendationTargetLabel(target, {
                            preview: t('sidebar.recommendations.targets.preview'),
                            pipeline: t('sidebar.recommendations.targets.pipeline'),
                            perf: t('sidebar.recommendations.targets.perf'),
                          })
                          return (
                            <div key={patchItem.id || title} className="rounded-lg border border-border/60 bg-background p-2">
                              <div className="flex items-center justify-between gap-2">
                                <div className="min-w-0">
                                  <div className="text-[13px] font-medium text-foreground/90">{title}</div>
                                  {desc ? <div className="mt-0.5 text-[13px] text-muted-foreground">{desc}</div> : null}
                                </div>
                                <Button
                                  type="button"
                                  size="sm"
                                  className="h-7 px-2 text-[13px]"
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
                              <div className="mt-1 text-[13px] text-muted-foreground font-mono">
                                {t('sidebar.recommendations.target', { value: targetLabel })}
                              </div>
                            </div>
                          )
                        })}
                      </div>
                    ) : null}

                    {previewData?.recommendations?.length ? (
                      <div className="mt-2 space-y-1 text-[13px] text-muted-foreground">
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
            {previewData?.warnings?.length ? <ul className="space-y-2">{previewData.warnings.map(warning => <li key={warning}>{formatPreviewWarningMessage(warning, { semanticNeedsReview: count => t('sidebar.performance.warnings.semanticNeedsReview', { count }) })}</li>)}</ul> : null}
          </>}
        />}
      </div>
    )

  if (variant === 'pane') return content

  return (
    <aside
      className={cn(
        'flex min-h-0 overflow-hidden flex-col',
        variant === 'dialog' ? 'w-full flex-1 border-0' : 'h-full w-[19rem] border-r border-border/60'
      )}
    >
      {content}
    </aside>
  )
}
