/**
 * TopBar - 工作台顶部栏
 */
'use client'

import { useRef, useState } from 'react'
import { Check, Copy, Download, ExternalLink, ChevronDown, ChevronRight, FolderOpen, GitCompareArrows, HelpCircle, Loader2, RotateCcw, TestTube2, Upload, X } from '@/components/icons'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { FeedbackToast } from '@/components/feedback-toast'

import { toTrimmedPrimitiveString } from '@/lib/primitive-text'
import { ChunkCompareDialog } from '@/components/chunk-preview/components/chunk-compare-dialog'
import { ChunkingHelpDialog } from '@/components/chunk-preview/components/chunking-help-dialog'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { applyChunkOverridesToPreview, chunkPreviewToCsv, chunkPreviewToJsonl, chunkPreviewToMarkdown, downloadTextFile, sanitizeFilename, toChunkPreviewExport } from '@/components/chunk-preview/utils/export'
import { isChunkOverrideDisabled } from '@/components/chunk-preview/utils/metadata'
import { TestGenerationDialog } from '@/components/test-generation-dialog'
import { Button } from '@/components/ui/button'
import { FileTypeIcon } from '@/components/ui/file-type-icon'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import styles from './compare.module.css'
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

export function TopBar({ onOpenDocuments }: Readonly<{ onOpenDocuments: () => void }>) {
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
    fileList,
    currentFileIndex,
    setCurrentFileIndex,
    isLoading,
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

  const visibleFileName =
    currentFileItem.displayName || previewData?.filename || currentFile.name
  const visibleFileType =
    currentFileItem.originalFileType ||
    previewData?.file_type ||
    currentFile.name.split('.').pop() ||
    ''
  const visibleFileSize = getVisibleFileSize(
    currentFileItem.originalFileSize,
    previewData?.file_size,
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

  return <>
    <header className={styles.header} aria-label={workbenchTitle}>
      <div className={styles.title}><PageTitleIcon name="chunk-preview" /><div><h1>切块预览</h1><p>检查切分结果与原文位置</p></div></div>
      <div className={styles.headerActions}>
        <Button variant="ghost" size="icon" className={styles.headerHelp} onClick={() => setHelpOpen(true)} aria-label={t('topBar.actions.helpTitle')}><HelpCircle /></Button>
        <DropdownMenu><DropdownMenuTrigger asChild><Button variant="outline" disabled={isSubmitting} aria-label="导出与更多操作"><Download />导出<ChevronDown /></Button></DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="max-h-[72dvh] w-64 overflow-y-auto p-1.5">
            <div className="px-2 py-2 text-[13px] leading-6 text-muted-foreground" title={serverTimingTitle}>
              <p>{getChunkStrategyLabel(effectiveChunkStrategy)} · {visibleChunkSize} / {visibleChunkOverlap} {visibleChunkUnit === 'tokens' ? 'Token' : '字符'}</p>
              {typeof visiblePreviewDurationMs === 'number' && <p>预览耗时 {visiblePreviewDurationMs} ms{cacheHit ? ' · 结果来自缓存' : ''}{previewData?.parse_cache_hit ? ' · 已复用解析结果' : ''}</p>}
              {visibleQualityGrade && <span className={cn(visibleQualityClass, 'inline-block rounded px-1.5 text-[13px]')} title={(previewData?.quality_gate?.reasons || []).join('、')}>质量：{visibleQualityLabel}</span>}
            </div><DropdownMenuSeparator />
            <DropdownMenuItem onSelect={reset}><RotateCcw />重置预览</DropdownMenuItem>
            <DropdownMenuItem onSelect={toggleOriginalPanel}>{showOriginalPanel ? '隐藏原文面板' : '显示原文面板'}</DropdownMenuItem>
            <DropdownMenuItem onSelect={toggleSettingsPanel}>打开高级切块配置</DropdownMenuItem>
            <DropdownMenuSeparator />


            <DropdownMenuItem
              className="rounded-md py-2 text-[13px] font-normal"
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
              className="rounded-md py-2 text-[13px] font-normal"
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
            <DropdownMenuItem className="rounded-md py-2 text-[13px] font-normal" onSelect={() => importConfigInputRef.current?.click()}>
              <Upload className="mr-2.5 h-4 w-4 opacity-60" strokeWidth={2.5} />
              {t('topBar.actions.importConfigFromFile')}
            </DropdownMenuItem>
            <DropdownMenuItem
              className="rounded-md py-2 text-[13px] font-normal"
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
                  className="rounded-md py-2 text-[13px] font-normal"
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
              className="rounded-md py-2 text-[13px] font-normal"
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
              className="rounded-md py-2 text-[13px] font-normal"
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
              className="rounded-md py-2 text-[13px] font-normal"
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
              className="rounded-md py-2 text-[13px] font-normal"
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
              className="rounded-md py-2 text-[13px] font-normal text-primary"
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
              className="rounded-md py-2 text-[13px] font-normal"
              disabled={!canCompare}
              onSelect={() => setCompareOpen(true)}
            >
              <GitCompareArrows className="mr-2.5 h-4 w-4 opacity-60" strokeWidth={2.5} />
              {t('topBar.actions.comparePreview')}
            </DropdownMenuItem>
            <DropdownMenuSeparator className="bg-border/60 mx-1 my-1.5" />
            <DropdownMenuItem
              className="rounded-md py-2 text-[13px] font-normal"
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
                  className="rounded-md py-2 text-[13px] font-normal"
                  onSelect={() => {
                    detachPromise(
                      copyText(createdDocumentId, t('topBar.toasts.copiedDocumentId'))
                    )
                  }}
                >
                  <Copy className="mr-2.5 h-4 w-4 opacity-60" strokeWidth={2.5} />
                  {t('topBar.actions.copyDocumentId')}
                </DropdownMenuItem>
                <DropdownMenuItem className="rounded-md py-2 text-[13px] font-normal" onSelect={() => setTestGenOpen(true)}>
                  <TestTube2 className="mr-2.5 h-4 w-4 opacity-60" strokeWidth={2.5} />
                  {t('topBar.actions.generateEvalQuestions')}
                </DropdownMenuItem>
                <DropdownMenuItem
                  className="rounded-md py-2 text-[13px] font-normal"
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
                  className="rounded-md py-2 text-[13px] font-normal"
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
        {onClose && <Button variant="ghost" size="icon" onClick={onClose} aria-label={t('topBar.actions.close')}><X /></Button>}
        <Button className={styles.ingest} onClick={submitChunks} disabled={!previewData || isLoading || isSubmitting || submitSuccess || isPreviewDirty} title={isPreviewDirty ? '参数已变更，请先生成预览' : undefined}>{isSubmitting ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <Check />}{isSubmitting ? '正在入库…' : submitSuccess ? t('topBar.actions.completed') : t('topBar.actions.confirmIngest')}</Button>
      </div>
    </header>
    <div className={styles.docbar} data-current-file-summary>
      <span className={styles.sourceLabel}><FolderOpen />{datasetId ? currentFileItem.datasetName || '数据集文档' : '解析工作区'}<ChevronRight /></span>
      <div className={styles.fileSelect}><Select value={String(currentFileIndex)} onValueChange={value => setCurrentFileIndex(Number(value))} disabled={isSubmitting}><SelectTrigger aria-label="选择预览文档"><FileTypeIcon type={visibleFileType} filename={visibleFileName} className="size-4 shrink-0" /><SelectValue /><span className="sr-only">当前文档</span></SelectTrigger><SelectContent>{fileList.map((item,index) => <SelectItem value={String(index)} key={item.id}><span data-file-name title={item.displayName}>{item.displayName || item.file.name}</span></SelectItem>)}</SelectContent></Select></div>
      <span className={styles.docmeta} title={formatFileSize(visibleFileSize)}>{previewData ? `${Number(previewData.total_characters || previewData.original_text?.length || 0).toLocaleString()} 字符` : formatFileSize(visibleFileSize)}</span>
      <div className={styles.docActions}><Button variant="ghost" disabled={isSubmitting} onClick={onOpenDocuments}><FolderOpen />管理文档</Button></div>
    </div>
    <FeedbackToast type="error" id="chunk-preview-error" message={topBarError ? `${topBarError.title}${topBarError.detail && topBarError.detail !== topBarError.title ? `：${topBarError.detail}` : ''}` : null} />
    <FeedbackToast type="warning" id="chunk-preview-parameters" message={isPreviewDirty && !submitSuccess && !error ? '参数已变更，生成预览后可确认入库。' : null} />
            <input
              ref={importConfigInputRef}
              type="file"
              accept="application/json"
              aria-label="导入切块配置文件"
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

  </>
}
