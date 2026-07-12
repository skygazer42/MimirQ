/**
 * TopBar - 工作台顶部栏
 */
'use client'

import { useRef, useState } from 'react'
import {
  AlertCircle,
  Check,
  Copy,
  Database,
  Download,
  ExternalLink,
  FileText,
  GitCompareArrows,
  HelpCircle,
  Loader2,
  MoreVertical,
  RotateCcw,
  Save,
  SlidersHorizontal,
  TestTube2,
  Upload,
  X,
} from 'lucide-react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'

import { toTrimmedPrimitiveString } from '@/lib/primitive-text'
import { ChunkCompareDialog } from '@/components/chunk-preview/components/chunk-compare-dialog'
import { ChunkingHelpDialog } from '@/components/chunk-preview/components/chunking-help-dialog'
import { useChunkPreview } from '@/components/chunk-preview/context'
import {
  applyChunkOverridesToPreview,
  chunkPreviewToCsv,
  chunkPreviewToJsonl,
  chunkPreviewToMarkdown,
  chunkPreviewToReviewMarkdown,
  chunkPreviewToReviewReport,
  downloadTextFile,
  sanitizeFilename,
  toChunkPreviewExport,
} from '@/components/chunk-preview/utils/export'
import { isChunkOverrideDisabled } from '@/components/chunk-preview/utils/metadata'
import { TestGenerationDialog } from '@/components/test-generation-dialog'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuCheckboxItem,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { useRouter } from '@/i18n/navigation'
import { getAuthHeaders } from '@/lib/auth-headers'
import { API_V1_BASE_URL } from '@/lib/env'
import { getChunkStrategyLabel } from '@/lib/chunk-strategies'
import { cn, detachPromise, formatFileSize } from '@/lib/utils'

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function getStringValue(record: Record<string, unknown>, key: string): string | undefined {
  const value = record[key]
  return typeof value === 'string' ? value : undefined
}

function getFiniteNumber(record: Record<string, unknown>, key: string): number | undefined {
  const value = record[key]
  if (typeof value === 'number' && Number.isFinite(value)) return value
  if (typeof value === 'string') {
    const parsed = Number(value)
    return Number.isFinite(parsed) ? parsed : undefined
  }
  return undefined
}

function getFiniteNumberValue(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function getVisibleFileSize(
  previewFileSize: unknown,
  originalFileSize: unknown,
  fallbackFileSize: number
): number {
  const previewSize = getFiniteNumberValue(previewFileSize)
  if (previewSize !== undefined) return previewSize

  const originalSize = getFiniteNumberValue(originalFileSize)
  if (originalSize !== undefined) return originalSize

  return fallbackFileSize
}

function getQualityGradeLabel(
  grade: unknown,
  labels: { pass: string; warn: string; fail: string }
): string {
  if (grade === 'pass') return labels.pass
  if (grade === 'warn') return labels.warn
  if (grade === 'fail') return labels.fail
  return toTrimmedPrimitiveString(grade).toUpperCase()
}

function getQualityGradeClass(grade: unknown): string {
  if (grade === 'pass') return 'border-success/20 bg-success/10 text-success'
  if (grade === 'fail') {
    return 'border-destructive/20 bg-destructive/10 text-destructive'
  }
  return 'border-warning/20 bg-warning/10 text-warning'
}

function getSubmitIcon(isSubmitting: boolean, submitSuccess: boolean) {
  if (isSubmitting) return Loader2
  if (submitSuccess) return Check
  return Save
}

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

function splitTopBarErrorMessage(cleaned: string): {
  title: string
  detail: string
} | null {
  const asciiColon = cleaned.indexOf(':')
  const fullwidthColon = cleaned.indexOf('：')
  const colonIndex =
    asciiColon < 0
      ? fullwidthColon
      : fullwidthColon < 0
        ? asciiColon
        : Math.min(asciiColon, fullwidthColon)

  if (colonIndex < 0) return null

  const title = cleaned.slice(0, colonIndex).trim()
  const detail = cleaned.slice(colonIndex + 1).trim()
  if (title.length < 2 || title.length > 24 || !detail) return null

  return { title, detail }
}

function formatTopBarError(message: string): {
  title: string
  detail: string | null
  badge: string | null
} {
  const cleaned = String(message || '').trim()
  const split = splitTopBarErrorMessage(cleaned)
  const title = split?.title || '操作失败'
  const detail = split?.detail || cleaned
  const lower = cleaned.toLowerCase()
  const badge = cleaned.includes('请求超时') || lower.includes('timeout') ? '请求超时' : null

  return {
    title,
    detail: detail || null,
    badge,
  }
}

const ESCAPED_NEWLINE = String.raw`\n`
const SHELL_BACKSLASH = String.fromCodePoint(92)
const DOUBLE_SHELL_BACKSLASH = SHELL_BACKSLASH.repeat(2)
const BACKTICK = String.fromCodePoint(96)

export function TopBar() {
  const router = useRouter()
  const t = useTranslations('ChunkPreview')
  const workbenchTitle = t('workbench.title')
  const [helpOpen, setHelpOpen] = useState(false)
  const [compareOpen, setCompareOpen] = useState(false)
  const [testGenOpen, setTestGenOpen] = useState(false)
  const [includeSkippedInExports, setIncludeSkippedInExports] = useState(false)
  const pipelineCtx = usePipelineOptions()
  const { enabled: pipelineOverridesEnabled, options: pipelineOptions } = pipelineCtx
  const importConfigInputRef = useRef<HTMLInputElement>(null)
  const {
    currentFileIndex,
    currentFileItem,
    currentFile,
    datasetId,
    previewData,
    chunkOverrides,
    parserBackend,
    chunkStrategy,
    chunkSize,
    chunkOverlap,
    separatorPreset,
    separatorCustom,
    keepSeparator,
    separatorMaxChunkSize,
    parentChildRatio,
    parentChildMinChildSize,
    lastPreviewDurationMs,
    cacheHit,
    isPreviewDirty,
    runHistory,
    getCachedPreview,
    submitSuccess,
    error,
    isSubmitting,
    showOriginalPanel,
    createdDocumentId,
    selectedChunkIndex,
    submitChunks,
    toggleOriginalPanel,
    toggleSettingsPanel,
    reset,
    setDatasetId,
    setParserBackend,
    updateSettings,
    updateSeparatorSettings,
    onClose,
  } = useChunkPreview()

  if (!currentFile || !currentFileItem) return null

  const effectiveParserBackend = previewData?.parser_backend || parserBackend
  const effectiveChunkStrategy = previewData?.chunk_strategy || chunkStrategy
  const skippedCount = Object.values(chunkOverrides).reduce(
    (acc, override) => acc + (isChunkOverrideDisabled(override) ? 1 : 0),
    0
  )

  const exportPreviewEnabledOnly = previewData
    ? applyChunkOverridesToPreview(previewData, chunkOverrides)
    : null
  const exportPreviewAll = previewData
    ? applyChunkOverridesToPreview(previewData, chunkOverrides, { include_disabled: true })
    : null
  const exportPreview = includeSkippedInExports
    ? exportPreviewAll
    : exportPreviewEnabledOnly

  const shouldIncludeSeparatorSettings = effectiveChunkStrategy === 'separator'
  const shouldIncludeParentChildSettings =
    effectiveChunkStrategy === 'parent_child'
  const selectedPreviewChunk =
    selectedChunkIndex == null ? null : previewData?.chunks?.[selectedChunkIndex] || null
  const selectedChunkStart =
    typeof selectedPreviewChunk?.start_index === 'number' &&
    Number.isFinite(selectedPreviewChunk.start_index)
      ? Math.trunc(selectedPreviewChunk.start_index)
      : null
  const selectedChunkEnd =
    typeof selectedPreviewChunk?.end_index === 'number' &&
    Number.isFinite(selectedPreviewChunk.end_index)
      ? Math.trunc(selectedPreviewChunk.end_index)
      : null
  const canOpenSelectedChunkInChatPage =
    selectedChunkStart != null &&
    selectedChunkEnd != null &&
    selectedChunkEnd > selectedChunkStart
  const selectedDocumentChunkId = (() => {
    if (!selectedPreviewChunk || !isRecord(selectedPreviewChunk.metadata)) {
      return undefined
    }
    const chunkId =
      (getStringValue(selectedPreviewChunk.metadata, 'chunk_id') || '').trim()
    return chunkId || undefined
  })()
  const canCompare = Boolean(
    previewData &&
      (runHistory || []).filter(
        (item) =>
          item.fileName === currentFile.name &&
          typeof item.cacheKey === 'string' &&
          Boolean(item.cacheKey)
      ).length >= 2
  )

  const serverTimingTitle = (() => {
    if (!previewData) return undefined
    const rows: string[] = []
    rows.push(`server_total: ${previewData.preview_duration_ms ?? '-'}ms`)
    if (typeof previewData.upload_duration_ms === 'number') {
      rows.push(`upload: ${previewData.upload_duration_ms}ms`)
    }
    if (previewData.parse_duration_ms != null) {
      rows.push(`parse: ${previewData.parse_duration_ms}ms`)
    }
    if (typeof previewData.governance_duration_ms === 'number') {
      rows.push(`govern: ${previewData.governance_duration_ms}ms`)
    }
    if (typeof previewData.chunking_duration_ms === 'number') {
      rows.push(`chunk: ${previewData.chunking_duration_ms}ms`)
    }
    if (typeof previewData.stats_duration_ms === 'number') {
      rows.push(`stats: ${previewData.stats_duration_ms}ms`)
    }
    rows.push(`parse_cache_hit: ${previewData.parse_cache_hit ? 'true' : 'false'}`)
    if (previewData.parse_cache_hit) {
      rows.push(`parse_cache_age_ms: ${previewData.parse_cache_age_ms ?? '-'}`)
    }
    return rows.join(ESCAPED_NEWLINE)
  })()

  const escapeForAnsiC = (value: string) => {
    // Used for bash $'...' strings in generated cURL.
    return value
      .replaceAll(SHELL_BACKSLASH, DOUBLE_SHELL_BACKSLASH)
      .replaceAll("'", String.raw`\\'`)
  }
  const escapeForDoubleQuotedShell = (value: string) =>
    value
      .replaceAll(SHELL_BACKSLASH, DOUBLE_SHELL_BACKSLASH)
      .replaceAll('"', String.raw`\"`)
      .replaceAll('$', String.raw`\$`)
      .replaceAll(BACKTICK, SHELL_BACKSLASH + BACKTICK)

  const summaryChipClass =
    'inline-flex h-7 items-center gap-1.5 rounded-lg border border-border/55 bg-muted/20 px-2.5 text-[10.5px] font-bold uppercase tracking-[-0.01em] text-muted-foreground/90 antialiased shadow-[0_1px_0_rgba(255,255,255,0.7)_inset]'
  const fileMetaChipClass =
    'inline-flex h-5 min-w-0 items-center gap-1 rounded-md border border-border/45 bg-background/60 px-1.5 text-[9px] font-bold tracking-[-0.01em] text-muted-foreground/80 antialiased'
  const stateChipClass =
    'inline-flex h-7 items-center gap-1.5 rounded-lg border px-2.5 text-[10.5px] font-bold uppercase tracking-[-0.01em] antialiased shadow-[0_1px_0_rgba(255,255,255,0.7)_inset]'
  const actionButtonClass =
    'h-8 rounded-lg px-2.5 text-[11px] font-bold uppercase tracking-[-0.01em] text-muted-foreground/90 hover:bg-primary/8 hover:text-primary transition-all antialiased'
  const visibleFileName =
    currentFileItem.displayName || previewData?.filename || currentFile.name
  const visibleFileType =
    previewData?.file_type ||
    currentFileItem.originalFileType ||
    currentFile.name.split('.').pop() ||
    ''
  const visibleFileSize = getVisibleFileSize(
    previewData?.file_size,
    currentFileItem.originalFileSize,
    currentFile.size
  )
  const visibleChunkSize =
    typeof previewData?.params?.chunk_size === 'number' &&
    Number.isFinite(previewData.params.chunk_size)
      ? Math.trunc(previewData.params.chunk_size)
      : chunkSize
  const visibleChunkOverlap =
    typeof previewData?.params?.chunk_overlap === 'number' &&
    Number.isFinite(previewData.params.chunk_overlap)
      ? Math.trunc(previewData.params.chunk_overlap)
      : chunkOverlap
  const visibleChunkUnit = previewData?.params?.unit || 'chars'
  const visiblePreviewDurationMs =
    typeof previewData?.preview_duration_ms === 'number' &&
    Number.isFinite(previewData.preview_duration_ms)
      ? Math.max(0, Math.round(previewData.preview_duration_ms))
      : lastPreviewDurationMs
  const visibleQualityGrade = previewData?.quality_gate?.grade
  const visibleQualityLabel = getQualityGradeLabel(visibleQualityGrade, {
    pass: t('topBar.status.qualityGrades.pass'),
    warn: t('topBar.status.qualityGrades.warn'),
    fail: t('topBar.status.qualityGrades.fail'),
  })
  const visibleQualityClass = getQualityGradeClass(visibleQualityGrade)
  const SubmitIcon = getSubmitIcon(isSubmitting, submitSuccess)
  const topBarError = error ? formatTopBarError(error) : null

  const buildConfig = () => ({
    dataset_id: datasetId || undefined,
    chunk_size: chunkSize,
    chunk_overlap: chunkOverlap,
    parser_backend: effectiveParserBackend,
    chunk_strategy: effectiveChunkStrategy,
    pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
    ...(shouldIncludeSeparatorSettings
      ? {
          separator_preset: separatorPreset,
          separator: separatorPreset === 'custom' ? separatorCustom : undefined,
          keep_separator: keepSeparator,
          separator_max_chunk_size: separatorMaxChunkSize,
        }
      : {}),
  })

  const copyText = async (value: string, okMessage: string) => {
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(value)
        toast.success(okMessage)
        return
      }
    } catch {
      // ignore
    }
    toast.error(t('topBar.toasts.clipboardUnsupported'))
  }

  const applyConfigFromText = async (text: string) => {
    const parsed = JSON.parse(text || '{}') as unknown
    if (!isRecord(parsed)) {
      toast.error(t('topBar.toasts.invalidJsonObject'))
      return false
    }

    const datasetIdValue = getStringValue(parsed, 'dataset_id')
    if (datasetIdValue !== undefined) {
      setDatasetId(datasetIdValue)
    } else if (parsed.dataset_id == null) {
      setDatasetId('')
    }

    const parserBackendValue = getStringValue(parsed, 'parser_backend')
    if (parserBackendValue !== undefined) {
      setParserBackend(parserBackendValue)
    }

    const nextStrategy = getStringValue(parsed, 'chunk_strategy')
    const nextSize = getFiniteNumber(parsed, 'chunk_size')
    const nextOverlap = getFiniteNumber(parsed, 'chunk_overlap')

    updateSettings({
      ...(nextStrategy ? { strategy: nextStrategy } : {}),
      ...(nextSize === undefined
        ? {}
        : { chunkSize: Math.max(50, Math.min(4000, Math.trunc(nextSize))) }),
      ...(nextOverlap === undefined
        ? {}
        : { chunkOverlap: Math.max(0, Math.min(1000, Math.trunc(nextOverlap))) }),
    })

    const separatorPresetValue = getStringValue(parsed, 'separator_preset')
    if (separatorPresetValue !== undefined) {
      updateSeparatorSettings({ separatorPreset: separatorPresetValue })
    }

    const separatorValue = getStringValue(parsed, 'separator')
    if (separatorValue !== undefined) {
      updateSeparatorSettings({ separatorCustom: separatorValue })
    }

    if (typeof parsed.keep_separator === 'boolean') {
      updateSeparatorSettings({ keepSeparator: parsed.keep_separator })
    }

    const separatorMaxChunkSizeValue = getFiniteNumber(
      parsed,
      'separator_max_chunk_size'
    )
    if (separatorMaxChunkSizeValue !== undefined) {
      updateSeparatorSettings({
        separatorMaxChunkSize: Math.max(
          0,
          Math.min(20000, Math.trunc(separatorMaxChunkSizeValue))
        ),
      })
    }

    const pipeline = parsed.pipeline
    if (isRecord(pipeline)) {
      const importResult = pipelineCtx.importJson(
        JSON.stringify({
          enabled: true,
          options: {
            ...pipelineCtx.options,
            ...pipeline,
          },
        })
      )

      if (!importResult.ok) {
        toast.error(importResult.error || t('topBar.toasts.invalidPipelineConfig'))
        return false
      }
    }

    return true
  }

  return (
    <section
      aria-label={workbenchTitle}
      className="relative flex min-w-0 flex-col gap-3 rounded-2xl border border-border/60 bg-background/95 px-3.5 py-3 shadow-[0_12px_32px_-12px_rgba(15,23,42,0.12)] xl:flex-row xl:items-center xl:justify-between antialiased backdrop-blur-xl"
    >
      <div className="flex min-w-0 flex-1 flex-col gap-2.5">
        <div data-current-file-summary className="flex min-w-0 items-center gap-3">
          <div className="relative flex h-10 w-10 shrink-0 items-center justify-center rounded-xl border border-primary/20 bg-primary/5 text-primary shadow-[0_1px_0_rgba(255,255,255,0.8)_inset,0_4px_12px_-4px_rgba(var(--primary-rgb),0.2)]">
            <FileText className="h-5 w-5" strokeWidth={2.5} />
            <div className="absolute -bottom-1 -right-1 flex h-4 w-4 items-center justify-center rounded-full border border-background bg-primary text-[8px] font-black text-primary-foreground shadow-sm">
              {currentFileIndex + 1}
            </div>
          </div>
          <div className="min-w-0">
            <div className="flex min-w-0 items-center gap-2">
              <span
                className="max-w-full truncate text-[13px] font-black tracking-[-0.01em] text-foreground sm:max-w-[28rem] xl:max-w-[34rem]"
                title={visibleFileName}
              >
                {visibleFileName}
              </span>
            </div>
            <div className="mt-1 flex min-w-0 flex-wrap items-center gap-1.5">
              {visibleFileType ? (
                <span className={cn(fileMetaChipClass, 'border-primary/20 bg-primary/5 text-primary/90')}>
                  <span className="font-black uppercase tracking-[0.18em]">{String(visibleFileType).toUpperCase()}</span>
                </span>
              ) : null}
              <span className={fileMetaChipClass}>
                <span className="opacity-60">{t('topBar.fileMeta.size')}</span>
                <span className="font-black tabular-nums">{formatFileSize(visibleFileSize)}</span>
              </span>
              <span className={cn(fileMetaChipClass, 'max-w-[10rem]')}>
                <span className="opacity-60">{t('topBar.fileMeta.parser')}</span>
                <span className="min-w-0 truncate font-black" title={effectiveParserBackend}>
                  {effectiveParserBackend}
                </span>
              </span>
            </div>
          </div>
        </div>

        <div className="flex min-w-0 flex-wrap items-center gap-2 px-0.5">
          <div className="flex items-center gap-1 rounded-lg border border-border/50 bg-muted/10 p-0.5 shadow-[inset_0_1px_2px_rgba(0,0,0,0.03)]">
            <span className={summaryChipClass}>
              <span className="opacity-50 tracking-[0.18em]">{t('topBar.strategyLabel')}</span>
              <span className="text-foreground" title={effectiveChunkStrategy}>
                {getChunkStrategyLabel(effectiveChunkStrategy)}
              </span>
              {effectiveChunkStrategy === 'auto' && previewData?.auto_selected_strategy ? (
                <>
                  <span className="h-2.5 w-px bg-border/80" />
                  <span
                    className="inline-flex items-center rounded-md bg-primary/10 px-1 py-0.5 text-[9px] font-black text-primary"
                    title={t('topBar.status.autoSelectedStrategyTitle', {
                      strategy: previewData.auto_selected_strategy,
                    })}
                  >
                    {getChunkStrategyLabel(previewData.auto_selected_strategy)}
                  </span>
                </>
              ) : null}
            </span>

            <span className={summaryChipClass}>
              <span className="opacity-50 tracking-[0.18em]">{t('topBar.paramsLabel')}</span>
              <span
                className="font-black tabular-nums text-foreground"
                title={visibleChunkUnit}
              >
                {visibleChunkSize}/{visibleChunkOverlap}
              </span>
            </span>
          </div>

          <div className="flex items-center gap-2">
            {typeof visiblePreviewDurationMs === 'number' ? (
              <span className={summaryChipClass} title={serverTimingTitle}>
                <div className="h-1.5 w-1.5 rounded-full bg-muted-foreground/30" />
                <span className="tabular-nums">{visiblePreviewDurationMs}ms</span>
              </span>
            ) : null}

            {previewData ? (
              <span className={cn(summaryChipClass, 'border-primary/10')}>
                <div
                  className={cn(
                    'h-1.5 w-1.5 rounded-full shadow-[0_0_8px_rgba(var(--primary-rgb),0.4)]',
                    previewData.chunks_truncated ? 'bg-warning' : 'bg-primary'
                  )}
                />
                <span className="font-black tabular-nums text-foreground/90">
                  {(() => {
                    const shown = Number(previewData.total_chunks || 0)
                    const full = Number(previewData.total_chunks_full ?? shown)
                    return t('topBar.status.chunks', {
                      count: full && full !== shown ? `${shown}/${full}` : `${shown}`,
                    })
                  })()}
                </span>
              </span>
            ) : null}

            {cacheHit ? (
              <span className={cn(stateChipClass, 'border-primary/20 bg-primary/5 text-primary')}>
                <Check className="h-3 w-3" strokeWidth={3} />
                {t('topBar.status.cacheHit')}
              </span>
            ) : null}

            {previewData?.parse_cache_hit ? (
              <span
                className={cn(stateChipClass, 'border-accent/20 bg-accent/5 text-accent')}
                title={t('topBar.status.parseCacheAgeTitle', {
                  age: previewData.parse_cache_age_ms ?? '-',
                })}
              >
                <Database className="h-3 w-3" strokeWidth={3} />
                {t('topBar.status.parseCache')}
              </span>
            ) : null}

            {visibleQualityGrade ? (
              <span
                className={cn(
                  stateChipClass,
                  visibleQualityClass,
                  'border-opacity-30'
                )}
                title={(previewData?.quality_gate?.reasons || []).join(ESCAPED_NEWLINE)}
              >
                <div className="flex items-center gap-1.5">
                  <div className={cn('h-1.5 w-1.5 rounded-full', 
                    visibleQualityGrade === 'pass' ? 'bg-success' : 
                    visibleQualityGrade === 'fail' ? 'bg-destructive' : 'bg-warning'
                  )} />
                  {t('topBar.status.quality', {
                    grade: visibleQualityLabel,
                  })}
                </div>
              </span>
            ) : null}
          </div>
        </div>
      </div>

      <div className="flex flex-wrap items-center gap-2 xl:justify-end">
        {submitSuccess ? (
          <div className="flex items-center gap-2 rounded-xl border border-success/30 bg-success/10 px-3 py-1.5 text-xs font-black uppercase tracking-[0.18em] text-success animate-in fade-in slide-in-from-right-4 motion-reduce:animate-none shadow-[0_2px_12px_-4px_rgba(16,185,129,0.2)]">
            <Check className="w-4 h-4" strokeWidth={3} />
            {t('topBar.submitSuccess')}
          </div>
        ) : null}

        {isPreviewDirty && !submitSuccess && !error ? (
          <div className="flex items-center gap-2 rounded-xl border border-warning/30 bg-warning/10 px-3 py-1.5 text-xs font-black uppercase tracking-[0.18em] text-warning dark:text-warning shadow-[0_2px_12px_-4px_hsl(var(--warning)/0.24)]">
            <AlertCircle className="w-4 h-4" strokeWidth={3} />
            {t('topBar.dirtyWarning')}
          </div>
        ) : null}

        {topBarError ? (
          <div
            role="alert"
            aria-live="polite"
            className="flex min-w-[min(100%,18rem)] max-w-xl items-start gap-2.5 rounded-2xl border border-destructive/30 bg-destructive/5 px-3.5 py-2.5 text-destructive shadow-[inset_0_1px_0_rgba(255,255,255,0.6),0_4px_16px_-8px_rgba(239,68,68,0.2)] backdrop-blur-md"
          >
            <span className="mt-0.5 grid size-7 shrink-0 place-items-center rounded-xl bg-destructive/10">
              <AlertCircle className="size-4" strokeWidth={2.5} />
            </span>
            <div className="min-w-0 flex-1">
              <div className="flex flex-wrap items-center gap-2">
                <span className="text-xs font-black uppercase tracking-[-0.01em] leading-none">
                  {topBarError.title}
                </span>
                {topBarError.badge ? (
                  <span className="rounded-full border border-destructive/30 bg-background/80 px-2 py-0.5 text-[9px] font-black uppercase tracking-[0.18em] leading-none text-destructive/90 antialiased">
                    {topBarError.badge}
                  </span>
                ) : null}
              </div>
              {topBarError.detail ? (
                <p className="mt-1.5 max-w-[42rem] break-words text-[11px] font-bold leading-relaxed text-destructive/80 antialiased">
                  {topBarError.detail}
                </p>
              ) : null}
            </div>
          </div>
        ) : null}

        <div className="flex items-center gap-1.5 rounded-2xl border border-border/60 bg-muted/20 p-1 shadow-[inset_0_1px_2px_rgba(0,0,0,0.03)] backdrop-blur-sm">
          <Button
            variant="ghost"
            size="sm"
            onClick={reset}
            className={cn(actionButtonClass, "hover:bg-background hover:shadow-sm")}
          >
            <RotateCcw className="w-3.5 h-3.5 mr-1.5 text-muted-foreground/60" strokeWidth={2.5} />
            {t('topBar.actions.reset')}
          </Button>

          <div className="w-px h-4 bg-border/60 mx-0.5" />

          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={toggleSettingsPanel}
            className={cn(actionButtonClass, 'lg:hidden hover:bg-background hover:shadow-sm')}
            aria-label={t('topBar.actions.openSettingsPanel')}
            title={t('topBar.actions.openSettingsPanel')}
          >
            <SlidersHorizontal className="w-3.5 h-3.5 mr-1.5" strokeWidth={2.5} />
            {t('topBar.actions.settings')}
          </Button>

          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={toggleOriginalPanel}
            className={cn(
              actionButtonClass,
              showOriginalPanel 
                ? 'bg-primary/10 text-primary hover:bg-primary/15' 
                : 'hover:bg-background hover:shadow-sm'
            )}
            aria-label={
              showOriginalPanel
                ? t('topBar.actions.hideOriginalPanel')
                : t('topBar.actions.showOriginalPanel')
            }
            title={
              showOriginalPanel
                ? t('topBar.actions.hideOriginalPanel')
                : t('topBar.actions.showOriginalPanel')
            }
          >
            <FileText className={cn("w-3.5 h-3.5 mr-1.5", showOriginalPanel ? "text-primary" : "text-muted-foreground/60")} strokeWidth={2.5} />
            {showOriginalPanel
              ? t('topBar.actions.hideOriginal')
              : t('topBar.actions.showOriginal')}
          </Button>

          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => setHelpOpen(true)}
            className={cn(actionButtonClass, "hover:bg-background hover:shadow-sm")}
            aria-label={t('topBar.actions.helpTitle')}
            title={t('topBar.actions.helpTitle')}
          >
            <HelpCircle className="w-3.5 h-3.5 mr-1.5 text-muted-foreground/60" strokeWidth={2.5} />
            <span className="hidden md:inline">{t('topBar.actions.help')}</span>
          </Button>

          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-8 w-8 rounded-lg p-0 text-muted-foreground/60 hover:bg-background hover:text-foreground hover:shadow-sm transition-all"
                aria-label={t('topBar.actions.moreActions')}
                title={t('topBar.actions.moreActions')}
              >
                <MoreVertical className="w-4 h-4" strokeWidth={2.5} />
              </Button>
            </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-60 rounded-2xl border-border/80 bg-popover/98 backdrop-blur-2xl shadow-strong p-1.5 ring-1 ring-black/5 animate-in fade-in zoom-in-95">
            <input
              ref={importConfigInputRef}
              type="file"
              accept="application/json"
              className="hidden"
              onChange={(e) => {
                const file = e.target.files?.[0]
                e.target.value = ''
                if (!file) return
                file
                  .text()
                  .then(async (text) => {
                    const ok = await applyConfigFromText(text)
                    if (ok) {
                      toast.success(t('topBar.toasts.importedFromFile'))
                    }
                  })
                  .catch((error: unknown) =>
                    toast.error(
                      getErrorMessage(error, t('topBar.toasts.readConfigFileFailed'))
                    )
                  )
              }}
            />
            <DropdownMenuItem
              className="rounded-xl py-2 font-bold text-xs"
              onSelect={() => {
                detachPromise(
                  copyText(
                    JSON.stringify(buildConfig(), null, 2),
                    t('topBar.toasts.copiedConfig')
                  )
                )
              }}
            >
              <Copy className="mr-2.5 h-4 w-4 opacity-60" strokeWidth={2.5} />
              {t('topBar.actions.copyConfig')}
            </DropdownMenuItem>
            <DropdownMenuItem
              className="rounded-xl py-2 font-bold text-xs"
              onSelect={() => {
                const filename = `${sanitizeFilename(
                  currentFileItem?.displayName || currentFile.name
                )}.chunk-preview.config.json`
                downloadTextFile(
                  filename,
                  JSON.stringify(buildConfig(), null, 2),
                  'application/json;charset=utf-8'
                )
                toast.success(t('topBar.toasts.exportedConfig'))
              }}
            >
              <Download className="mr-2.5 h-4 w-4 opacity-60" strokeWidth={2.5} />
              {t('topBar.actions.exportConfig')}
            </DropdownMenuItem>
            <DropdownMenuItem className="rounded-xl py-2 font-bold text-xs" onSelect={() => importConfigInputRef.current?.click()}>
              <Upload className="mr-2.5 h-4 w-4 opacity-60" strokeWidth={2.5} />
              {t('topBar.actions.importConfigFromFile')}
            </DropdownMenuItem>
            <DropdownMenuItem
              className="rounded-xl py-2 font-bold text-xs"
              onSelect={async () => {
                try {
                  if (!navigator.clipboard?.readText) {
                    toast.error(t('topBar.toasts.clipboardReadUnsupported'))
                    return
                  }
                  const text = await navigator.clipboard.readText()
                  const ok = await applyConfigFromText(text)
                  if (ok) {
                    toast.success(t('topBar.toasts.importedFromClipboard'))
                  }
                } catch (error: unknown) {
                  toast.error(
                    getErrorMessage(error, t('topBar.toasts.importConfigFailed'))
                  )
                }
              }}
            >
              <Copy className="mr-2.5 h-4 w-4 opacity-60" strokeWidth={2.5} />
              {t('topBar.actions.importConfigFromClipboard')}
            </DropdownMenuItem>
            {previewData && skippedCount > 0 ? (
              <>
                <DropdownMenuSeparator className="bg-border/60 mx-1 my-1.5" />
                <DropdownMenuCheckboxItem
                  className="rounded-xl py-2 font-bold text-xs"
                  checked={includeSkippedInExports}
                  onCheckedChange={(checked) =>
                    setIncludeSkippedInExports(Boolean(checked))
                  }
                >
                  {t('topBar.actions.includeSkippedInExports', {
                    count: skippedCount,
                  })}
                </DropdownMenuCheckboxItem>
              </>
            ) : null}

            <DropdownMenuSeparator className="bg-border/60 mx-1 my-1.5" />

            <DropdownMenuItem
              className="rounded-xl py-2 font-bold text-xs"
              disabled={!previewData}
              onSelect={() => {
                if (!exportPreview) return
                const filename = `${sanitizeFilename(exportPreview.filename)}.chunks.json`
                downloadTextFile(
                  filename,
                  JSON.stringify(toChunkPreviewExport(exportPreview), null, 2),
                  'application/json;charset=utf-8'
                )
                toast.success(t('topBar.toasts.exportedJson'))
              }}
            >
              <Download className="mr-2.5 h-4 w-4 opacity-60" strokeWidth={2.5} />
              {t('topBar.actions.exportJson')}
            </DropdownMenuItem>
            <DropdownMenuItem
              className="rounded-xl py-2 font-bold text-xs"
              disabled={!previewData}
              onSelect={() => {
                if (!exportPreview) return
                const filename = `${sanitizeFilename(exportPreview.filename)}.chunks.md`
                downloadTextFile(
                  filename,
                  chunkPreviewToMarkdown(exportPreview),
                  'text/markdown;charset=utf-8'
                )
                toast.success(t('topBar.toasts.exportedMarkdown'))
              }}
            >
              <Download className="mr-2.5 h-4 w-4 opacity-60" strokeWidth={2.5} />
              {t('topBar.actions.exportMarkdown')}
            </DropdownMenuItem>
            <DropdownMenuItem
              className="rounded-xl py-2 font-bold text-xs"
              disabled={!previewData}
              onSelect={() => {
                if (!exportPreview) return
                const filename = `${sanitizeFilename(exportPreview.filename)}.chunks.csv`
                downloadTextFile(
                  filename,
                  chunkPreviewToCsv(exportPreview),
                  'text/csv;charset=utf-8'
                )
                toast.success(t('topBar.toasts.exportedCsv'))
              }}
            >
              <Download className="mr-2.5 h-4 w-4 opacity-60" strokeWidth={2.5} />
              {t('topBar.actions.exportCsv')}
            </DropdownMenuItem>
            <DropdownMenuItem
              className="rounded-xl py-2 font-bold text-xs"
              disabled={!previewData}
              onSelect={() => {
                if (!exportPreview) return
                const filename = `${sanitizeFilename(exportPreview.filename)}.chunks.jsonl`
                downloadTextFile(
                  filename,
                  chunkPreviewToJsonl(exportPreview),
                  'application/x-ndjson;charset=utf-8'
                )
                toast.success(t('topBar.toasts.exportedJsonl'))
              }}
            >
              <Download className="mr-2.5 h-4 w-4 opacity-60" strokeWidth={2.5} />
              {t('topBar.actions.exportJsonl')}
            </DropdownMenuItem>
            <DropdownMenuItem
              className="rounded-xl py-2 font-bold text-xs text-primary"
              disabled={!previewData}
              onSelect={() => {
                const payloadPreview = exportPreviewEnabledOnly
                if (!payloadPreview) return
                const payload = {
                  filename: payloadPreview.filename,
                  file_type: payloadPreview.file_type,
                  file_size: payloadPreview.file_size,
                  dataset_id: datasetId || undefined,
                  chunks: (payloadPreview.chunks || []).map((chunk) => ({
                    content: chunk.content ?? '',
                    page_number: chunk.page_number,
                    start_char: chunk.start_index,
                    end_char: chunk.end_index,
                    metadata: chunk.metadata ?? {},
                  })),
                  pipeline: pipelineOverridesEnabled
                    ? {
                        ...pipelineOptions,
                        chunk_size: chunkSize,
                        chunk_overlap: chunkOverlap,
                      }
                    : undefined,
                }
                detachPromise(
                  copyText(
                    JSON.stringify(payload, null, 2),
                    t('topBar.toasts.copiedIngestPayload')
                  )
                )
              }}
            >
              <Copy className="mr-2.5 h-4 w-4 opacity-80" strokeWidth={2.5} />
              {t('topBar.actions.copyIngestPayload')}
            </DropdownMenuItem>
            <DropdownMenuItem
              className="rounded-xl py-2 font-bold text-xs"
              disabled={!canCompare}
              onSelect={() => setCompareOpen(true)}
            >
              <GitCompareArrows className="mr-2.5 h-4 w-4 opacity-60" strokeWidth={2.5} />
              {t('topBar.actions.comparePreview')}
            </DropdownMenuItem>
            <DropdownMenuSeparator className="bg-border/60 mx-1 my-1.5" />
            <DropdownMenuItem
              className="rounded-xl py-2 font-bold text-xs"
              onSelect={() => {
                const url = `${API_V1_BASE_URL}/documents/chunk-preview?chunk_size=${encodeURIComponent(
                  String(chunkSize)
                )}&chunk_overlap=${encodeURIComponent(String(chunkOverlap))}`
                const pipeline = pipelineOverridesEnabled
                  ? JSON.stringify(pipelineOptions || {})
                  : null
                const authHeaders = getAuthHeaders()
                const lines = [
                  `curl -X POST "${url}" \\`,
                  ...Object.entries(authHeaders).map(
                    ([name, value]) => `  -H "${name}: ${escapeForDoubleQuotedShell(value)}" \\`
                  ),
                  `  -F "file=@/path/to/your-file" \\`,
                  `  -F "parser_backend=${effectiveParserBackend}" \\`,
                  `  -F "chunk_strategy=${effectiveChunkStrategy}"`,
                ]
                if (datasetId) {
                  lines.push(`  -F "dataset_id=${datasetId}"`)
                }
                if (shouldIncludeParentChildSettings) {
                  lines.push(
                    `  -F "child_ratio=${parentChildRatio}"`,
                    `  -F "min_child_size=${parentChildMinChildSize}"`
                  )
                }
                if (shouldIncludeSeparatorSettings) {
                  lines.push(`  -F "separator_preset=${separatorPreset}"`)
                  if (separatorPreset === 'custom') {
                    lines.push(`  -F $'separator=${escapeForAnsiC(separatorCustom)}'`)
                  }
                  lines.push(`  -F "keep_separator=${keepSeparator ? 'true' : 'false'}"`)
                  if (
                    typeof separatorMaxChunkSize === 'number' &&
                    separatorMaxChunkSize > 0
                  ) {
                    lines.push(`  -F "separator_max_chunk_size=${separatorMaxChunkSize}"`)
                  }
                }
                if (pipeline) {
                  const lastLine = lines.at(-1)
                  if (lastLine) lines.splice(-1, 1, `${lastLine} ${SHELL_BACKSLASH}`)
                  lines.push(`  -F 'pipeline=${pipeline}'`)
                }
                detachPromise(
                  copyText(lines.join('\n'), t('topBar.toasts.copiedCurl'))
                )
              }}
            >
              <Copy className="mr-2.5 h-4 w-4 opacity-60" strokeWidth={2.5} />
              {t('topBar.actions.copyCurl')}
            </DropdownMenuItem>
            {createdDocumentId ? (
              <>
                <DropdownMenuSeparator className="bg-border/60 mx-1 my-1.5" />
                <DropdownMenuItem
                  className="rounded-xl py-2 font-bold text-xs"
                  onSelect={() => {
                    detachPromise(
                      copyText(createdDocumentId, t('topBar.toasts.copiedDocumentId'))
                    )
                  }}
                >
                  <Copy className="mr-2.5 h-4 w-4 opacity-60" strokeWidth={2.5} />
                  {t('topBar.actions.copyDocumentId')}
                </DropdownMenuItem>
                <DropdownMenuItem className="rounded-xl py-2 font-bold text-xs" onSelect={() => setTestGenOpen(true)}>
                  <TestTube2 className="mr-2.5 h-4 w-4 opacity-60" strokeWidth={2.5} />
                  {t('topBar.actions.generateEvalQuestions')}
                </DropdownMenuItem>
                <DropdownMenuItem
                  className="rounded-xl py-2 font-bold text-xs"
                  disabled={!canOpenSelectedChunkInChatPage}
                  onSelect={() => {
                    if (!canOpenSelectedChunkInChatPage) return
                    const params = new URLSearchParams()
                    params.set('doc', createdDocumentId)
                    if (selectedDocumentChunkId) {
                      params.set('chunk', selectedDocumentChunkId)
                    }
                    params.set('start', String(selectedChunkStart))
                    params.set('end', String(selectedChunkEnd))
                    router.push(`/?${params.toString()}`)
                    toast.success(t('topBar.toasts.openedCurrentChunkInChat'))
                  }}
                >
                  <ExternalLink className="mr-2.5 h-4 w-4 opacity-60" strokeWidth={2.5} />
                  {t('topBar.actions.openCurrentChunkInChat')}
                </DropdownMenuItem>
                <DropdownMenuItem
                  className="rounded-xl py-2 font-bold text-xs"
                  onSelect={() => {
                    router.push(`/?doc=${encodeURIComponent(createdDocumentId)}`)
                    toast.success(t('topBar.toasts.openedDocumentInChat'))
                  }}
                >
                  <ExternalLink className="mr-2.5 h-4 w-4 opacity-60" strokeWidth={2.5} />
                  {t('topBar.actions.openDocumentInChat')}
                </DropdownMenuItem>
              </>
            ) : null}
          </DropdownMenuContent>
          </DropdownMenu>
        </div>

        {onClose ? (
          <Button
            variant="ghost"
            size="sm"
            onClick={onClose}
            className="text-muted-foreground/60 hover:text-foreground/90 h-9 w-9 p-0 rounded-full hover:bg-muted/50 transition-colors"
            aria-label={t('topBar.actions.close')}
            title={t('topBar.actions.close')}
          >
            <X className="w-4 h-4" strokeWidth={2.5} />
          </Button>
        ) : null}

        <Button
          onClick={submitChunks}
          disabled={!previewData || isSubmitting || submitSuccess}
          className={cn(
            'h-9 px-6 text-xs font-black uppercase tracking-[0.1em] rounded-xl shadow-lg transition-all duration-300 motion-reduce:transition-none antialiased hover:scale-[1.02] active:scale-[0.98]',
            submitSuccess
              ? 'bg-success text-success-foreground hover:bg-success/90 shadow-success/20'
              : 'bg-primary text-primary-foreground hover:bg-primary/90 shadow-[0_4px_16px_-4px_rgba(var(--primary-rgb),0.4)]'
          )}
        >
          <SubmitIcon
            className={cn(
              'w-4 h-4 mr-2',
              isSubmitting && 'animate-spin motion-reduce:animate-none'
            )}
            strokeWidth={3}
          />
          {submitSuccess
            ? t('topBar.actions.completed')
            : t('topBar.actions.confirmIngest')}
        </Button>
      </div>

      <ChunkingHelpDialog open={helpOpen} onOpenChange={setHelpOpen} />
      {previewData ? (
        <ChunkCompareDialog
          open={compareOpen}
          onOpenChange={setCompareOpen}
          current={previewData}
          currentFileName={currentFile.name}
          runHistory={runHistory}
          getCachedPreview={getCachedPreview}
        />
      ) : null}
      <TestGenerationDialog
        open={testGenOpen}
        onClose={() => setTestGenOpen(false)}
        onGenerated={() => toast.success(t('topBar.toasts.generatedEvalCases'))}
        initialSourceType="documents"
        initialDatasetId={datasetId || undefined}
        initialDocumentIds={createdDocumentId ? [createdDocumentId] : undefined}
      />
    </section>
  )
}
