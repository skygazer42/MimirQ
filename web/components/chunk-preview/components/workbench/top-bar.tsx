/**
 * TopBar - 工作台顶部栏
 */
'use client'

import { useLayoutEffect, useRef, useState } from 'react'
import {
  Check,
  Copy,
  Download,
  ExternalLink,
  ChevronDown,
  FolderOpen,
  GitCompareArrows,
  HelpCircle,
  Loader2,
  RotateCcw,
  TestTube2,
  Upload,
  X,
} from '@/components/icons'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { FeedbackToast } from '@/components/feedback-toast'

import { toTrimmedPrimitiveString } from '@/lib/primitive-text'
import { ChunkCompareDialog } from '@/components/chunk-preview/components/chunk-compare-dialog'
import { ChunkingHelpDialog } from '@/components/chunk-preview/components/chunking-help-dialog'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { useChunkPreviewConfig } from '@/components/chunk-preview/use-chunk-preview-config'
import {
  applyChunkOverridesToPreview,
  chunkPreviewToCsv,
  chunkPreviewToJsonl,
  chunkPreviewToMarkdown,
  downloadTextFile,
  sanitizeFilename,
  toChunkPreviewExport,
} from '@/components/chunk-preview/utils/export'
import { isChunkOverrideDisabled, readMetadataString } from '@/components/chunk-preview/utils/metadata'
import { getComparisonCandidates } from '@/components/chunk-preview/utils/ab-diff'
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
import { useRouter } from '@/i18n/navigation'
import { getAuthHeaders } from '@/lib/auth-headers'
import { getAuthCacheScope, getAuthSessionRevision } from '@/lib/auth-storage'
import { API_V1_BASE_URL } from '@/lib/env'
import { appendChunkPreviewSettings, buildChunkPreviewQueryParams } from '@/lib/api/document-helpers'
import { getChunkStrategyLabel } from '@/lib/chunk-strategies'
import { cn, detachPromise, formatFileSize } from '@/lib/utils'

function getFiniteNumberValue(value: unknown): number | undefined {
  return typeof value === 'number' && Number.isFinite(value) ? value : undefined
}

function getVisibleFileSize(previewFileSize: unknown, originalFileSize: unknown, fallbackFileSize: number): number {
  const previewSize = getFiniteNumberValue(previewFileSize)
  if (previewSize !== undefined) return previewSize

  const originalSize = getFiniteNumberValue(originalFileSize)
  if (originalSize !== undefined) return originalSize

  return fallbackFileSize
}

function getQualityGradeLabel(grade: unknown, labels: { pass: string; warn: string; fail: string }): string {
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
    asciiColon < 0 ? fullwidthColon : fullwidthColon < 0 ? asciiColon : Math.min(asciiColon, fullwidthColon)

  if (colonIndex < 0) return null

  const title = cleaned.slice(0, colonIndex).trim()
  const detail = cleaned.slice(colonIndex + 1).trim()
  if (title.length < 2 || title.length > 24 || !detail) return null

  return { title, detail }
}

function formatTopBarError(message: string): {
  title: string
  detail: string | null
} {
  const cleaned = message.trim()
  const split = splitTopBarErrorMessage(cleaned)
  const title = split?.title ?? '操作失败'
  const detail = split?.detail ?? cleaned

  return {
    title,
    detail: detail === '' ? null : detail,
  }
}

const SHELL_BACKSLASH = String.fromCodePoint(92)
const DOUBLE_SHELL_BACKSLASH = SHELL_BACKSLASH.repeat(2)

export function TopBar({ onOpenDocuments }: Readonly<{ onOpenDocuments: () => void }>) {
  const router = useRouter()
  const t = useTranslations('ChunkPreview')
  const workbenchTitle = t('workbench.title')
  const [helpOpen, setHelpOpen] = useState(false)
  const [compareOpen, setCompareOpen] = useState(false)
  const [testGenOpen, setTestGenOpen] = useState(false)
  const [includeSkippedInExports, setIncludeSkippedInExports] = useState(false)
  const { buildConfig, applyConfig } = useChunkPreviewConfig('workbench')
  const applyConfigRef = useRef(applyConfig)
  const importConfigInputRef = useRef<HTMLInputElement>(null)
  const configImportRef = useRef<object | null>(null)
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
    chunkStrategy,
    chunkSize,
    chunkOverlap,
    buildChunkPreviewRequestParams,
    buildIngestPayload,
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
    onClose,
  } = useChunkPreview()

  useLayoutEffect(() => {
    applyConfigRef.current = applyConfig
  }, [applyConfig])

  useLayoutEffect(
    () => () => {
      configImportRef.current = null
    },
    [currentFile, currentFileItem?.id, currentFileItem?.fileRevision, datasetId],
  )

  if (!currentFile || !currentFileItem) return null

  const effectiveChunkStrategy = previewData?.chunk_strategy || chunkStrategy
  const skippedCount = Object.values(chunkOverrides).reduce(
    (acc, override) => acc + (isChunkOverrideDisabled(override) ? 1 : 0),
    0,
  )

  const exportPreview =
    previewData === null
      ? null
      : applyChunkOverridesToPreview(previewData, chunkOverrides, { include_disabled: includeSkippedInExports })

  const selectedPreviewChunk = selectedChunkIndex === null ? undefined : previewData?.chunks[selectedChunkIndex]
  const selectedChunkStart = getFiniteNumberValue(selectedPreviewChunk?.start_index)
  const selectedChunkEnd = getFiniteNumberValue(selectedPreviewChunk?.end_index)
  const canOpenSelectedChunkInChatPage =
    selectedChunkStart !== undefined &&
    selectedChunkEnd !== undefined &&
    Math.trunc(selectedChunkEnd) > Math.trunc(selectedChunkStart)
  const selectedDocumentChunkId = readMetadataString(selectedPreviewChunk?.metadata?.chunk_id)
  const canCompare = Boolean(previewData && getComparisonCandidates(runHistory, currentFileItem.id).length >= 2)

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
    return rows.join('\n')
  })()

  const visibleFileName = currentFileItem.displayName || previewData?.filename || currentFile.name
  const visibleFileType =
    readMetadataString(currentFileItem.originalFileType) ?? readMetadataString(previewData?.file_type)
  const visibleFileSize = getVisibleFileSize(currentFileItem.originalFileSize, previewData?.file_size, currentFile.size)
  const visibleChunkSize =
    typeof previewData?.params?.chunk_size === 'number' && Number.isFinite(previewData.params.chunk_size)
      ? Math.trunc(previewData.params.chunk_size)
      : chunkSize
  const visibleChunkOverlap =
    typeof previewData?.params?.chunk_overlap === 'number' && Number.isFinite(previewData.params.chunk_overlap)
      ? Math.trunc(previewData.params.chunk_overlap)
      : chunkOverlap
  const visibleChunkUnit = previewData?.params?.unit
  const visiblePreviewDurationMs =
    typeof previewData?.preview_duration_ms === 'number' && Number.isFinite(previewData.preview_duration_ms)
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

  const copyIngestPayload = () => {
    if (previewData === null) return
    try {
      const payload = buildIngestPayload(previewData, currentFileItem, chunkOverrides)
      detachPromise(copyText(JSON.stringify(payload, null, 2), t('topBar.toasts.copiedIngestPayload')))
    } catch (error: unknown) {
      toast.error(getErrorMessage(error, '无法生成入库请求'))
    }
  }

  const copyCurl = () => {
    const params = buildChunkPreviewRequestParams()
    const query = new URLSearchParams()
    for (const [key, value] of Object.entries(buildChunkPreviewQueryParams(params))) {
      if (value !== undefined) query.set(key, String(value))
    }
    const formData = new FormData()
    appendChunkPreviewSettings(formData, currentFile.name, params)

    const quoteForBash = (value: string) => {
      const escaped = value
        .replaceAll(SHELL_BACKSLASH, DOUBLE_SHELL_BACKSLASH)
        .replaceAll("'", SHELL_BACKSLASH + "'")
        .replaceAll('\r', SHELL_BACKSLASH + 'r')
        .replaceAll('\n', SHELL_BACKSLASH + 'n')
        .replaceAll('\t', SHELL_BACKSLASH + 't')
      return `$'${escaped}'`
    }
    const url = `${API_V1_BASE_URL}/documents/chunk-preview?${query}`
    const lines = [
      `curl -X POST ${quoteForBash(url)}`,
      ...Object.entries(getAuthHeaders()).map(([key, value]) => `  -H ${quoteForBash(`${key}: ${value}`)}`),
      '  -F "file=@/path/to/your-file"',
      ...Array.from(formData, ([key, value]) => `  --form-string ${quoteForBash(`${key}=${value}`)}`),
    ]
    detachPromise(copyText(lines.join(` ${SHELL_BACKSLASH}\n`), t('topBar.toasts.copiedCurl')))
  }

  const importConfiguration = async (
    readText: () => Promise<string>,
    successMessage: string,
    failureMessage: string,
  ) => {
    const request = {}
    configImportRef.current = request
    const scope = getAuthCacheScope()
    const revision = getAuthSessionRevision()
    const isCurrent = () =>
      configImportRef.current === request && getAuthCacheScope() === scope && getAuthSessionRevision() === revision
    try {
      const text = await readText()
      if (!isCurrent()) return
      const payload: unknown = JSON.parse(text)
      const result = applyConfigRef.current(payload)
      if (result.ok) toast.success(successMessage)
      else toast.error(result.error)
    } catch (error: unknown) {
      if (isCurrent()) toast.error(getErrorMessage(error, failureMessage))
    } finally {
      if (configImportRef.current === request) configImportRef.current = null
    }
  }

  let ingestLabel = t('topBar.actions.confirmIngest')
  if (isSubmitting) ingestLabel = '正在入库…'
  else if (submitSuccess) ingestLabel = t('topBar.actions.completed')
  else if (createdDocumentId !== null) ingestLabel = '查询入库状态'

  return (
    <>
      <header className={styles.header} aria-label={workbenchTitle}>
        <div className={styles.title}>
          <PageTitleIcon name="chunk-preview" />
          <h1>切块预览</h1>
        </div>
        <div className={styles.fileSelect} data-current-file-summary>
          <Select
            value={String(currentFileIndex)}
            onValueChange={(value) => setCurrentFileIndex(Number(value))}
            disabled={isSubmitting}
          >
            <SelectTrigger aria-label="选择预览文档" title={`${visibleFileName} · ${formatFileSize(visibleFileSize)}`}>
              <FileTypeIcon type={visibleFileType} filename={visibleFileName} className="size-4 shrink-0" />
              <SelectValue className={styles.fileName} />
              <span className="sr-only">当前文档</span>
            </SelectTrigger>
            <SelectContent>
              {fileList.map((item, index) => (
                <SelectItem value={String(index)} key={item.id}>
                  <span data-file-name title={item.displayName}>
                    {item.displayName || item.file.name}
                  </span>
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </div>
        <div className={styles.headerActions}>
          <Button variant="ghost" disabled={isSubmitting} onClick={onOpenDocuments} aria-label="管理文档">
            <FolderOpen />
            管理文档
          </Button>
          <Button
            variant="ghost"
            size="icon"
            className={styles.headerHelp}
            onClick={() => setHelpOpen(true)}
            aria-label={t('topBar.actions.helpTitle')}
          >
            <HelpCircle />
          </Button>
          <DropdownMenu>
            <DropdownMenuTrigger asChild>
              <Button variant="outline" disabled={isSubmitting} aria-label="导出与更多操作">
                <Download />
                导出
                <ChevronDown />
              </Button>
            </DropdownMenuTrigger>
            <DropdownMenuContent align="end" className="max-h-[72dvh] w-64 overflow-y-auto p-1.5">
              <div className="px-2 py-2 text-[13px] leading-6 text-muted-foreground" title={serverTimingTitle}>
                <p>
                  {getChunkStrategyLabel(effectiveChunkStrategy)} · {visibleChunkSize} / {visibleChunkOverlap}{' '}
                  {visibleChunkUnit === 'tokens' ? 'Token' : '字符'}
                </p>
                {typeof visiblePreviewDurationMs === 'number' && (
                  <p>
                    预览耗时 {visiblePreviewDurationMs} ms{cacheHit ? ' · 结果来自缓存' : ''}
                    {previewData?.parse_cache_hit ? ' · 已复用解析结果' : ''}
                  </p>
                )}
                {visibleQualityGrade && (
                  <span
                    className={cn(visibleQualityClass, 'inline-block rounded px-1.5 text-[13px]')}
                    title={(previewData?.quality_gate?.reasons || []).join('、')}
                  >
                    质量：{visibleQualityLabel}
                  </span>
                )}
              </div>
              <DropdownMenuSeparator />
              <DropdownMenuItem onSelect={reset}>
                <RotateCcw />
                重置预览
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={toggleOriginalPanel}>
                {showOriginalPanel ? '隐藏原文面板' : '显示原文面板'}
              </DropdownMenuItem>
              <DropdownMenuItem onSelect={toggleSettingsPanel}>打开高级切块配置</DropdownMenuItem>
              <DropdownMenuSeparator />
              <DropdownMenuItem
                className="rounded-md py-2 text-[13px] font-normal"
                onSelect={() => {
                  detachPromise(copyText(JSON.stringify(buildConfig(), null, 2), t('topBar.toasts.copiedConfig')))
                }}
              >
                <Copy className="mr-2.5 h-4 w-4 opacity-60" strokeWidth={2.5} />
                {t('topBar.actions.copyConfig')}
              </DropdownMenuItem>
              <DropdownMenuItem
                className="rounded-md py-2 text-[13px] font-normal"
                onSelect={() => {
                  const filename = `${sanitizeFilename(
                    currentFileItem?.displayName || currentFile.name,
                  )}.chunk-preview.config.json`
                  downloadTextFile(filename, JSON.stringify(buildConfig(), null, 2), 'application/json;charset=utf-8')
                  toast.success(t('topBar.toasts.exportedConfig'))
                }}
              >
                <Download className="mr-2.5 h-4 w-4 opacity-60" strokeWidth={2.5} />
                {t('topBar.actions.exportConfig')}
              </DropdownMenuItem>
              <DropdownMenuItem
                className="rounded-md py-2 text-[13px] font-normal"
                onSelect={() => importConfigInputRef.current?.click()}
              >
                <Upload className="mr-2.5 h-4 w-4 opacity-60" strokeWidth={2.5} />
                {t('topBar.actions.importConfigFromFile')}
              </DropdownMenuItem>
              <DropdownMenuItem
                className="rounded-md py-2 text-[13px] font-normal"
                onSelect={() => {
                  if (!navigator.clipboard?.readText) {
                    toast.error(t('topBar.toasts.clipboardReadUnsupported'))
                    return
                  }
                  detachPromise(
                    importConfiguration(
                      () => navigator.clipboard.readText(),
                      t('topBar.toasts.importedFromClipboard'),
                      t('topBar.toasts.importConfigFailed'),
                    ),
                  )
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
                    onCheckedChange={setIncludeSkippedInExports}
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
                    'application/json;charset=utf-8',
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
                  downloadTextFile(filename, chunkPreviewToMarkdown(exportPreview), 'text/markdown;charset=utf-8')
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
                  downloadTextFile(filename, chunkPreviewToCsv(exportPreview), 'text/csv;charset=utf-8')
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
                  downloadTextFile(filename, chunkPreviewToJsonl(exportPreview), 'application/x-ndjson;charset=utf-8')
                  toast.success(t('topBar.toasts.exportedJsonl'))
                }}
              >
                <Download className="mr-2.5 h-4 w-4 opacity-60" strokeWidth={2.5} />
                {t('topBar.actions.exportJsonl')}
              </DropdownMenuItem>
              <DropdownMenuItem
                className="rounded-md py-2 text-[13px] font-normal text-primary"
                disabled={previewData === null || isLoading || isPreviewDirty}
                onSelect={copyIngestPayload}
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
              <DropdownMenuItem className="rounded-md py-2 text-[13px] font-normal" onSelect={copyCurl}>
                <Copy className="mr-2.5 h-4 w-4 opacity-60" strokeWidth={2.5} />
                {t('topBar.actions.copyCurl')}
              </DropdownMenuItem>
              {createdDocumentId ? (
                <>
                  <DropdownMenuSeparator className="bg-border/60 mx-1 my-1.5" />
                  <DropdownMenuItem
                    className="rounded-md py-2 text-[13px] font-normal"
                    onSelect={() => {
                      detachPromise(copyText(createdDocumentId, t('topBar.toasts.copiedDocumentId')))
                    }}
                  >
                    <Copy className="mr-2.5 h-4 w-4 opacity-60" strokeWidth={2.5} />
                    {t('topBar.actions.copyDocumentId')}
                  </DropdownMenuItem>
                  <DropdownMenuItem
                    className="rounded-md py-2 text-[13px] font-normal"
                    onSelect={() => setTestGenOpen(true)}
                  >
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
                      if (selectedDocumentChunkId !== undefined) {
                        params.set('chunk', selectedDocumentChunkId)
                      }
                      params.set('start', String(Math.trunc(selectedChunkStart)))
                      params.set('end', String(Math.trunc(selectedChunkEnd)))
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
          {onClose && (
            <Button variant="ghost" size="icon" onClick={onClose} aria-label={t('topBar.actions.close')}>
              <X />
            </Button>
          )}
          <Button
            className={styles.ingest}
            aria-label={ingestLabel}
            onClick={submitChunks}
            disabled={!previewData || isLoading || isSubmitting || submitSuccess || isPreviewDirty}
            title={isPreviewDirty ? '请先更新当前预览' : undefined}
          >
            {isSubmitting ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <Check />}
            {ingestLabel}
          </Button>
        </div>
      </header>
      <FeedbackToast
        type="error"
        id="chunk-preview-error"
        message={
          topBarError
            ? `${topBarError.title}${topBarError.detail && topBarError.detail !== topBarError.title ? `：${topBarError.detail}` : ''}`
            : null
        }
      />
      <FeedbackToast
        type="warning"
        id="chunk-preview-parameters"
        message={isPreviewDirty && !submitSuccess && !error ? '更新预览后可确认入库。' : null}
      />
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
          detachPromise(
            importConfiguration(
              () => file.text(),
              t('topBar.toasts.importedFromFile'),
              t('topBar.toasts.readConfigFileFailed'),
            ),
          )
        }}
      />
      <ChunkingHelpDialog open={helpOpen} onOpenChange={setHelpOpen} />
      {previewData ? (
        <ChunkCompareDialog
          open={compareOpen}
          onOpenChange={setCompareOpen}
          current={previewData}
          currentFileId={currentFileItem.id}
          currentFileName={currentFile.name}
          runHistory={runHistory}
          getCachedPreview={getCachedPreview}
        />
      ) : null}
      <TestGenerationDialog
        open={testGenOpen}
        onClose={() => setTestGenOpen(false)}
        onCasesSaved={() => toast.success(t('topBar.toasts.generatedEvalCases'))}
        initialSourceType="documents"
        initialDatasetId={datasetId}
        initialDocumentIds={createdDocumentId === null ? undefined : [createdDocumentId]}
      />
    </>
  )
}
