/**
 * TopBar - 工作台顶部栏
 */
'use client'

import { useRef, useState } from 'react'
import {
  Layers,
  FileText,
  SlidersHorizontal,
  ExternalLink,
  Save,
  RotateCcw,
  HelpCircle,
  MoreVertical,
  Download,
  Upload,
  Copy,
  X,
  Check,
  AlertCircle,
  Loader2,
  GitCompareArrows,
  TestTube2,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuCheckboxItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn, formatFileSize, detachPromise } from '@/lib/utils'
import { API_V1_BASE_URL } from '@/lib/env'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { isChunkOverrideDisabled } from '@/components/chunk-preview/utils/metadata'
import { getChunkStrategyLabel } from '@/lib/chunk-strategies'
import { getParserLabel } from '@/lib/parser-options'
import { applyChunkOverridesToPreview, chunkPreviewToCsv, chunkPreviewToJsonl, chunkPreviewToMarkdown, chunkPreviewToReviewMarkdown, chunkPreviewToReviewReport, downloadTextFile, sanitizeFilename, toChunkPreviewExport } from '@/components/chunk-preview/utils/export'
import { ChunkingHelpDialog } from '@/components/chunk-preview/components/chunking-help-dialog'
import { ChunkCompareDialog } from '@/components/chunk-preview/components/chunk-compare-dialog'
import { TestGenerationDialog } from '@/components/test-generation-dialog'
import { useRouter } from 'next/navigation'

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

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
}

export function TopBar() {
  const router = useRouter()
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
  const skippedCount = Object.values(chunkOverrides).reduce((acc, override) => acc + (isChunkOverrideDisabled(override) ? 1 : 0), 0)

  const exportPreviewEnabledOnly = previewData ? applyChunkOverridesToPreview(previewData, chunkOverrides) : null
  const exportPreviewAll = previewData
    ? applyChunkOverridesToPreview(previewData, chunkOverrides, { include_disabled: true })
    : null
  const exportPreview = includeSkippedInExports ? exportPreviewAll : exportPreviewEnabledOnly

  const shouldIncludeSeparatorSettings = effectiveChunkStrategy === 'separator'
  const shouldIncludeParentChildSettings = effectiveChunkStrategy === 'parent_child'
  const selectedPreviewChunk = selectedChunkIndex == null ? null : previewData?.chunks?.[selectedChunkIndex] || null
  const selectedChunkStart =
    typeof selectedPreviewChunk?.start_index === 'number' && Number.isFinite(selectedPreviewChunk.start_index)
      ? Math.trunc(selectedPreviewChunk.start_index)
      : null
  const selectedChunkEnd =
    typeof selectedPreviewChunk?.end_index === 'number' && Number.isFinite(selectedPreviewChunk.end_index)
      ? Math.trunc(selectedPreviewChunk.end_index)
      : null
  const canOpenSelectedChunkInChatPage =
    selectedChunkStart != null && selectedChunkEnd != null && selectedChunkEnd > selectedChunkStart
  const selectedDocumentChunkId = (() => {
    if (!selectedPreviewChunk || !isRecord(selectedPreviewChunk.metadata)) return undefined
    const chunkId = (getStringValue(selectedPreviewChunk.metadata, 'chunk_id') || '').trim()
    return chunkId || undefined
  })()
  const canCompare = Boolean(
    previewData &&
      (runHistory || []).filter(
        (item) => item.fileName === currentFile.name && typeof item.cacheKey === 'string' && Boolean(item.cacheKey)
      ).length >= 2
  )

  const serverTimingTitle = (() => {
    if (!previewData) return undefined
    const rows: string[] = []
    rows.push(`server_total: ${previewData.preview_duration_ms ?? '-'}ms`)
    if (typeof previewData.upload_duration_ms === 'number') rows.push(`upload: ${previewData.upload_duration_ms}ms`)
    if (previewData.parse_duration_ms != null) rows.push(`parse: ${previewData.parse_duration_ms}ms`)
    if (typeof previewData.governance_duration_ms === 'number') rows.push(`govern: ${previewData.governance_duration_ms}ms`)
    if (typeof previewData.chunking_duration_ms === 'number') rows.push(`chunk: ${previewData.chunking_duration_ms}ms`)
    if (typeof previewData.stats_duration_ms === 'number') rows.push(`stats: ${previewData.stats_duration_ms}ms`)
    rows.push(`parse_cache_hit: ${previewData.parse_cache_hit ? 'true' : 'false'}`)
    if (previewData.parse_cache_hit) rows.push(`parse_cache_age_ms: ${previewData.parse_cache_age_ms ?? '-'}`)
    return rows.join('\\n')
  })()

  const escapeForAnsiC = (value: string) => {
    // Used for bash $'...' strings in generated cURL.
    return value.replaceAll("\\", '\\\\').replaceAll("'", "\\\\'")
  }

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
    toast.error('复制失败：浏览器不支持 Clipboard API')
  }

  const applyConfigFromText = async (text: string) => {
    const parsed = JSON.parse(text || '{}') as unknown
    if (!isRecord(parsed)) {
      toast.error('配置格式错误：不是有效的 JSON 对象')
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
      ...(nextSize !== undefined ? { chunkSize: Math.max(50, Math.min(4000, Math.trunc(nextSize))) } : {}),
      ...(nextOverlap !== undefined ? { chunkOverlap: Math.max(0, Math.min(1000, Math.trunc(nextOverlap))) } : {}),
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

    const separatorMaxChunkSizeValue = getFiniteNumber(parsed, 'separator_max_chunk_size')
    if (separatorMaxChunkSizeValue !== undefined) {
      updateSeparatorSettings({
        separatorMaxChunkSize: Math.max(0, Math.min(20000, Math.trunc(separatorMaxChunkSizeValue))),
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
        toast.error(importResult.error || '配置格式错误：pipeline 配置无效')
        return false
      }
    }

    return true
  }

  return (
	    <div className="flex items-center justify-between gap-4 min-w-0">
	      <div className="flex items-center gap-4">
	        {/* Logo Icon */}
	        <div className="w-10 h-10 rounded-xl flex items-center justify-center bg-primary/10 text-primary shadow-soft ring-1 ring-border/60">
	          <Layers className="w-5 h-5" />
	        </div>
        
        <div className="flex flex-col justify-center min-w-0">
          {/* Row 1: Title & File Info */}
          <div className="flex items-center gap-3">
            <h1 className="text-sm font-semibold text-foreground whitespace-nowrap">切片预览</h1>
            <div className="h-3 w-px bg-muted-foreground/40" />
            <div className="flex items-center gap-2 min-w-0">
               <span className="text-sm font-bold text-foreground truncate max-w-[300px]" title={currentFileItem?.displayName || currentFile.name}>
                 {currentFileItem?.displayName || currentFile.name}
               </span>
               <div className="flex items-center gap-1.5">
                 <span className="text-[10px] font-bold bg-primary/15 text-primary px-1.5 py-0.5 rounded-md min-w-[2rem] text-center">
                   #{currentFileIndex + 1}
                 </span>
                 {currentFileItem?.originalFileType && (
                    <span className="text-[10px] font-mono font-medium text-muted-foreground border border-border px-1.5 py-0.5 rounded bg-muted">
                      {String(currentFileItem.originalFileType).toUpperCase()}
                    </span>
                 )}
                 <span className="text-[10px] text-muted-foreground font-mono">
                   {formatFileSize(currentFileItem?.originalFileSize ?? currentFile.size)}
                 </span>
               </div>
            </div>
          </div>

          {/* Row 2: Process Configs & Stats */}
          <div className="flex items-center gap-3 mt-1.5">
             <div className="flex items-center gap-2 text-[11px] text-muted-foreground bg-muted border border-border px-2 py-0.5 rounded-md">
                <span className="text-muted-foreground">解析:</span>
                <span className="font-medium text-primary" title={effectiveParserBackend}>
                  {getParserLabel(effectiveParserBackend)}
                </span>
                {effectiveChunkStrategy === 'auto' && previewData?.auto_selected_strategy ? (
                  <span
                    className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary border border-primary/20 font-medium"
                    title={`auto_selected_strategy: ${previewData.auto_selected_strategy}`}
                  >
                    → {getChunkStrategyLabel(previewData.auto_selected_strategy)}
                  </span>
                ) : null}
                <span className="w-px h-2.5 bg-border mx-0.5" />
                <span className="text-muted-foreground">策略:</span>
                <span className="font-medium text-primary" title={effectiveChunkStrategy}>
                  {getChunkStrategyLabel(effectiveChunkStrategy)}
                </span>
                <span className="w-px h-2.5 bg-border mx-0.5" />
                <span className="text-muted-foreground">参数:</span>
                <span className="font-medium font-mono text-foreground/80">{chunkSize}/{chunkOverlap}</span>
             </div>

             {(typeof lastPreviewDurationMs === 'number' || previewData) && (
               <div className="flex items-center gap-2 text-[11px]">
                  {typeof lastPreviewDurationMs === 'number' && (
                    <span className="text-muted-foreground flex items-center gap-1">
                       <span className="w-1.5 h-1.5 rounded-full bg-muted-foreground/40" />
                       <span title={serverTimingTitle}>{lastPreviewDurationMs}ms</span>
                    </span>
                  )}
                  {previewData && (
                    <span className="text-muted-foreground font-medium flex items-center gap-1">
                       <span className={cn('w-1.5 h-1.5 rounded-full', previewData.chunks_truncated ? 'bg-warning' : 'bg-success')} />
                       {(() => {
                         const shown = Number(previewData.total_chunks || 0)
                         const full = Number(previewData.total_chunks_full ?? shown)
                         return full && full !== shown ? `${shown}/${full}` : `${shown}`
                       })()} Chunks
                    </span>
                  )}
               </div>
             )}

             {cacheHit && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-success/10 text-success border border-success/30 font-medium">
                  Hit Cache
                </span>
             )}

             {previewData?.parse_cache_hit ? (
                <span
                  className="text-[10px] px-1.5 py-0.5 rounded bg-info/10 text-info border border-info/30 font-medium"
                  title={`parse_cache_age_ms: ${previewData.parse_cache_age_ms ?? '-'}`}
                >
                  Parse Cache
                </span>
             ) : null}

             {previewData?.quality_gate?.grade ? (
                <span
                  className={cn(
                    'text-[10px] px-1.5 py-0.5 rounded border font-medium',
                    (() => {
    if (previewData.quality_gate.grade === 'pass') {
        return 'bg-success/10 text-success border-success/30';
    }
    else if (previewData.quality_gate.grade === 'fail') {
            return 'bg-destructive/10 text-destructive border-destructive/30';
        }
        else {
            return 'bg-warning/10 text-warning border-warning/30';
        }
})()
                  )}
                  title={(previewData.quality_gate.reasons || []).join('\\n')}
                >
                  Quality: {String(previewData.quality_gate.grade).toUpperCase()}
                </span>
             ) : null}

             {previewData?.warnings?.length ? (
                <span
                  className="text-[10px] px-1.5 py-0.5 rounded bg-warning/10 text-warning border border-warning/30 font-medium"
                  title={(previewData.warnings || []).join('\\n')}
                >
                  Warnings: {previewData.warnings.length}
                </span>
             ) : null}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-3">
        {submitSuccess && (
          <div className="flex items-center gap-1.5 text-success text-xs font-medium bg-success/10 px-3 py-1.5 rounded-full border border-success/30 animate-in fade-in slide-in-from-right-4 motion-reduce:animate-none">
            <Check className="w-3.5 h-3.5" />
            已成功入库
          </div>
        )}

        {isPreviewDirty && !submitSuccess && !error ? (
          <div className="flex items-center gap-1.5 text-warning text-xs font-medium bg-warning/10 px-3 py-1.5 rounded-full border border-warning/30">
            <AlertCircle className="w-3.5 h-3.5" />
            配置已变更，未重新预览
          </div>
        ) : null}

        {error && (
          <div className="flex items-center gap-1.5 text-destructive text-xs bg-destructive/10 px-3 py-1.5 rounded-full border border-destructive/30 max-w-[300px] truncate">
            <AlertCircle className="w-3.5 h-3.5" />
            {error}
          </div>
        )}

        <div className="h-8 w-px bg-border mx-2" />

        <Button variant="ghost" size="sm" onClick={reset} className="text-muted-foreground hover:text-foreground h-9 px-3 text-xs font-medium hover:bg-muted">
          <RotateCcw className="w-3.5 h-3.5 mr-1.5" />
          重置
        </Button>

        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={toggleSettingsPanel}
          className="lg:hidden text-muted-foreground hover:text-foreground h-9 px-3 text-xs font-medium hover:bg-muted"
          aria-label="打开参数面板"
          title="打开参数面板"
        >
          <SlidersHorizontal className="w-3.5 h-3.5 mr-1.5" />
          参数
        </Button>

        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={toggleOriginalPanel}
          className="text-muted-foreground hover:text-foreground h-9 px-3 text-xs font-medium hover:bg-muted"
          aria-label={showOriginalPanel ? '隐藏原文面板' : '显示原文面板'}
          title={showOriginalPanel ? '隐藏原文面板' : '显示原文面板'}
        >
          <FileText className="w-3.5 h-3.5 mr-1.5" />
          {showOriginalPanel ? '隐藏原文' : '显示原文'}
        </Button>

        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => setHelpOpen(true)}
          className="text-muted-foreground hover:text-foreground h-9 px-3 text-xs font-medium hover:bg-muted"
          aria-label="切块指南"
          title="切块指南"
        >
          <HelpCircle className="w-3.5 h-3.5 mr-1.5" />
          <span className="hidden md:inline">指南</span>
        </Button>

        <DropdownMenu>
          <DropdownMenuTrigger asChild>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="text-muted-foreground hover:text-foreground/80 h-9 w-9 p-0 rounded-full hover:bg-muted"
              aria-label="更多操作"
              title="更多操作"
            >
              <MoreVertical className="w-4 h-4" />
            </Button>
          </DropdownMenuTrigger>
          <DropdownMenuContent align="end" className="w-56">
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
                    if (ok) toast.success('已从文件导入配置')
                  })
                  .catch((error: unknown) => toast.error(getErrorMessage(error, '读取配置文件失败')))
              }}
            />
            <DropdownMenuItem
              onSelect={() => {
                const config = {
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
                }
                detachPromise(copyText(JSON.stringify(config, null, 2), '已复制预览配置'))
              }}
            >
              <Copy className="mr-2 h-4 w-4" />
              复制预览配置
            </DropdownMenuItem>
            <DropdownMenuItem
              onSelect={() => {
                const config = {
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
                }
                const filename = `${sanitizeFilename(currentFileItem?.displayName || currentFile.name)}.chunk-preview.config.json`
                downloadTextFile(filename, JSON.stringify(config, null, 2), 'application/json;charset=utf-8')
                toast.success('已导出配置')
              }}
            >
              <Download className="mr-2 h-4 w-4" />
              导出配置.json
            </DropdownMenuItem>
            <DropdownMenuItem
              onSelect={() => {
                importConfigInputRef.current?.click()
              }}
            >
              <Upload className="mr-2 h-4 w-4" />
              从文件导入配置
            </DropdownMenuItem>
            <DropdownMenuItem
              onSelect={async () => {
                try {
                  if (!navigator.clipboard?.readText) {
                    toast.error('读取剪贴板失败：浏览器不支持 Clipboard API')
                    return
                  }
                  const text = await navigator.clipboard.readText()
                  const ok = await applyConfigFromText(text)
                  if (ok) toast.success('已从剪贴板导入配置')
                } catch (error: unknown) {
                  toast.error(getErrorMessage(error, '导入配置失败'))
                }
              }}
            >
              <Copy className="mr-2 h-4 w-4" />
              从剪贴板导入配置
            </DropdownMenuItem>
            {previewData && skippedCount > 0 ? (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuCheckboxItem
                  checked={includeSkippedInExports}
                  onCheckedChange={(checked) => setIncludeSkippedInExports(Boolean(checked))}
                >
                  Include SKIP chunks in exports ({skippedCount})
                </DropdownMenuCheckboxItem>
              </>
            ) : null}

            <DropdownMenuItem
              disabled={!previewData}
              onSelect={() => {
                if (!exportPreview) return
                const filename = `${sanitizeFilename(exportPreview.filename)}.chunks.json`
                downloadTextFile(filename, JSON.stringify(toChunkPreviewExport(exportPreview), null, 2), 'application/json;charset=utf-8')
                toast.success('已导出 JSON')
              }}
            >
              <Download className="mr-2 h-4 w-4" />
              导出 chunks.json
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={!previewData}
              onSelect={() => {
                if (!exportPreview) return
                const filename = `${sanitizeFilename(exportPreview.filename)}.chunks.md`
                downloadTextFile(filename, chunkPreviewToMarkdown(exportPreview), 'text/markdown;charset=utf-8')
                toast.success('已导出 Markdown')
              }}
            >
              <Download className="mr-2 h-4 w-4" />
              导出 chunks.md
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={!previewData}
              onSelect={() => {
                if (!exportPreview) return
                const filename = `${sanitizeFilename(exportPreview.filename)}.chunks.csv`
                downloadTextFile(filename, chunkPreviewToCsv(exportPreview), 'text/csv;charset=utf-8')
                toast.success('已导出 CSV')
              }}
            >
              <Download className="mr-2 h-4 w-4" />
              导出 chunks.csv
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={!previewData}
              onSelect={() => {
                if (!exportPreview) return
                const filename = `${sanitizeFilename(exportPreview.filename)}.chunks.jsonl`
                downloadTextFile(filename, chunkPreviewToJsonl(exportPreview), 'application/x-ndjson;charset=utf-8')
                toast.success('已导出 JSONL')
              }}
            >
              <Download className="mr-2 h-4 w-4" />
              导出 chunks.jsonl
            </DropdownMenuItem>
             <DropdownMenuItem
               disabled={!previewData}
               onSelect={() => {
                 if (!previewData) return
                 const report = chunkPreviewToReviewReport(previewData, chunkOverrides, {
                   include_disabled: includeSkippedInExports,
                 })
                 const filename = `${sanitizeFilename(previewData.filename)}.chunk-review.json`
                 downloadTextFile(filename, JSON.stringify(report, null, 2), 'application/json;charset=utf-8')
                 toast.success('Review report exported')
               }}
             >
               <Download className="mr-2 h-4 w-4" />
               Export review-report.json
             </DropdownMenuItem>
             <DropdownMenuItem
               disabled={!previewData}
               onSelect={() => {
                 if (!previewData) return
                 const md = chunkPreviewToReviewMarkdown(previewData, chunkOverrides, {
                   include_disabled: includeSkippedInExports,
                 })
                 const filename = `${sanitizeFilename(previewData.filename)}.chunk-review.md`
                 downloadTextFile(filename, md, 'text/markdown;charset=utf-8')
                 toast.success('Review report exported')
               }}
             >
               <Download className="mr-2 h-4 w-4" />
               Export review-report.md
             </DropdownMenuItem>
            <DropdownMenuItem
              disabled={!previewData}
              onSelect={() => {
                const payloadPreview = exportPreviewEnabledOnly
                if (!payloadPreview) return
                const payload = {
                  filename: payloadPreview.filename,
                  file_type: payloadPreview.file_type,
                  file_size: payloadPreview.file_size,
                  dataset_id: datasetId || undefined,
                  chunks: (payloadPreview.chunks || []).map((c) => ({
                    content: c.content ?? '',
                    page_number: c.page_number,
                    start_char: c.start_index,
                    end_char: c.end_index,
                    metadata: c.metadata ?? {},
                  })),
                  pipeline: pipelineOverridesEnabled
                    ? {
                        ...pipelineOptions,
                        chunk_size: chunkSize,
                        chunk_overlap: chunkOverlap,
                      }
                    : undefined,
                }
                detachPromise(copyText(JSON.stringify(payload, null, 2), '已复制手动入库 payload'))
              }}
            >
              <Copy className="mr-2 h-4 w-4" />
              复制手动入库 payload
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={!canCompare}
              onSelect={() => {
                setCompareOpen(true)
              }}
            >
              <GitCompareArrows className="mr-2 h-4 w-4" />
              预览对比（A/B）
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={() => {
                const url = `${API_V1_BASE_URL}/documents/chunk-preview?chunk_size=${encodeURIComponent(
                  String(chunkSize)
                )}&chunk_overlap=${encodeURIComponent(String(chunkOverlap))}`
                const pipeline = pipelineOverridesEnabled ? JSON.stringify(pipelineOptions || {}) : null
                const lines = [
                  `curl -X POST "${url}" \\`,
                  `  -H "X-User-ID: demo" \\`,
                  `  -F "file=@/path/to/your-file" \\`,
                  `  -F "parser_backend=${effectiveParserBackend}" \\`,
                  `  -F "chunk_strategy=${effectiveChunkStrategy}"`,
                ]
                if (datasetId) {
                  lines.push(`  -F "dataset_id=${datasetId}"`)
                }
                if (shouldIncludeParentChildSettings) {
                                    lines.push(`  -F "child_ratio=${parentChildRatio}"`, `  -F "min_child_size=${parentChildMinChildSize}"`)
                }
                if (shouldIncludeSeparatorSettings) {
                  lines.push(`  -F "separator_preset=${separatorPreset}"`)
                  if (separatorPreset === 'custom') {
                    lines.push(`  -F $'separator=${escapeForAnsiC(separatorCustom)}'`)
                  }
                  lines.push(`  -F "keep_separator=${keepSeparator ? 'true' : 'false'}"`)
                  if (typeof separatorMaxChunkSize === 'number' && separatorMaxChunkSize > 0) {
                    lines.push(`  -F "separator_max_chunk_size=${separatorMaxChunkSize}"`)
                  }
                }
                if (pipeline) {
                  lines[lines.length - 1] = `${lines[lines.length - 1]} \\`
                  lines.push(`  -F 'pipeline=${pipeline}'`)
                }
                const curl = lines.join('\n')
                detachPromise(copyText(curl, '已复制 cURL'))
              }}
            >
              <Copy className="mr-2 h-4 w-4" />
              复制 cURL（chunk-preview）
            </DropdownMenuItem>
            {createdDocumentId ? (
              <>
                <DropdownMenuSeparator />
                <DropdownMenuItem
                  onSelect={() => {
                    detachPromise(copyText(createdDocumentId, '已复制文档 ID'))
                  }}
                >
                  <Copy className="mr-2 h-4 w-4" />
                  复制文档 ID
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() => {
                    setTestGenOpen(true)
                  }}
                >
                  <TestTube2 className="mr-2 h-4 w-4" />
                  生成评测问题（RAGAS）
                </DropdownMenuItem>
                <DropdownMenuItem
                  disabled={!canOpenSelectedChunkInChatPage}
                  onSelect={() => {
                    if (!canOpenSelectedChunkInChatPage) return
                    const params = new URLSearchParams()
                    params.set('doc', createdDocumentId)
                    if (selectedDocumentChunkId) params.set('chunk', selectedDocumentChunkId)
                    params.set('start', String(selectedChunkStart))
                    params.set('end', String(selectedChunkEnd))
                    router.push(`/?${params.toString()}`)
                    toast.success('已跳转到对话页并定位当前切片')
                  }}
                >
                  <ExternalLink className="mr-2 h-4 w-4" />
                  打开当前切片（对话页）
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() => {
                    const url = `/?doc=${encodeURIComponent(createdDocumentId)}`
                    router.push(url)
                    toast.success('已跳转到对话页并打开文档面板')
                  }}
                >
                  <ExternalLink className="mr-2 h-4 w-4" />
                  打开文档（对话页）
                </DropdownMenuItem>
              </>
            ) : null}
          </DropdownMenuContent>
        </DropdownMenu>

        {onClose && (
          <Button
            variant="ghost"
            size="sm"
            onClick={onClose}
            className="text-muted-foreground hover:text-foreground/80 h-9 w-9 p-0 rounded-full hover:bg-muted"
            aria-label="关闭"
            title="关闭"
          >
            <X className="w-4 h-4" />
          </Button>
        )}

        <Button
          onClick={submitChunks}
          disabled={!previewData || isSubmitting || submitSuccess}
          className={cn(
            'h-9 px-5 text-xs font-semibold rounded-lg shadow-sm transition-colors transition-shadow duration-150 motion-reduce:transition-none',
            submitSuccess
              ? 'bg-success text-success-foreground hover:bg-success/90 shadow-success/20'
              : 'bg-primary text-primary-foreground hover:bg-primary/90 shadow-primary/20'
          )}
        >
          {(() => {
    if (isSubmitting) {
        return (<Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none mr-2"/>);
    }
    else if (submitSuccess) {
            return (<Check className="w-3.5 h-3.5 mr-2"/>);
        }
        else {
            return (<Save className="w-3.5 h-3.5 mr-2"/>);
        }
})()}
          {submitSuccess ? '已完成' : '确认入库'}
	        </Button>
	      </div>
	      <div className="absolute inset-x-6 bottom-0 h-px bg-border/60" />

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
        onGenerated={() => toast.success('已生成评测用例，可在「评测」页查看')}
        initialSourceType="documents"
        initialDatasetId={datasetId || undefined}
        initialDocumentIds={createdDocumentId ? [createdDocumentId] : undefined}
	      />
	    </div>
	  )
}
