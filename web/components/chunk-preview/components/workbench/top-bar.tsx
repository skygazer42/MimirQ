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
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { cn, formatFileSize } from '@/lib/utils'
import { API_V1_BASE_URL } from '@/lib/env'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { getChunkStrategyLabel } from '@/lib/chunk-strategies'
import { getParserLabel } from '@/lib/parser-options'
import { chunkPreviewToCsv, chunkPreviewToMarkdown, downloadTextFile, sanitizeFilename, toChunkPreviewExport } from '@/components/chunk-preview/utils/export'
import { IngestionWorkflowStepper } from '@/components/ui/ingestion-workflow-stepper'
import { ChunkingHelpDialog } from '@/components/chunk-preview/components/chunking-help-dialog'
import { useRouter } from 'next/navigation'

export function TopBar() {
  const router = useRouter()
  const [helpOpen, setHelpOpen] = useState(false)
  const pipelineCtx = usePipelineOptions()
  const { enabled: pipelineOverridesEnabled, options: pipelineOptions } = pipelineCtx
  const importConfigInputRef = useRef<HTMLInputElement>(null)
  const {
    currentFileIndex,
    currentFileItem,
    currentFile,
    datasetId,
    previewData,
    parserBackend,
    chunkStrategy,
    chunkSize,
    chunkOverlap,
    separatorPreset,
    separatorCustom,
    keepSeparator,
    separatorMaxChunkSize,
    lastPreviewDurationMs,
    cacheHit,
    isPreviewDirty,
    submitSuccess,
    error,
    isSubmitting,
    showOriginalPanel,
    createdDocumentId,
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

  const shouldIncludeSeparatorSettings = effectiveChunkStrategy === 'separator'

  const escapeForAnsiC = (value: string) => {
    // Used for bash $'...' strings in generated cURL.
    return value.replace(/\\/g, '\\\\').replace(/'/g, "\\\\'")
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
    const parsed = JSON.parse(text || '{}')
    if (!parsed || typeof parsed !== 'object') {
      toast.error('配置格式错误：不是有效的 JSON 对象')
      return
    }

    if (typeof (parsed as any).dataset_id === 'string') {
      setDatasetId(String((parsed as any).dataset_id))
    } else if ((parsed as any).dataset_id == null) {
      setDatasetId('')
    }

    if (typeof (parsed as any).parser_backend === 'string') {
      setParserBackend(String((parsed as any).parser_backend))
    }

    const nextStrategy = typeof (parsed as any).chunk_strategy === 'string' ? String((parsed as any).chunk_strategy) : undefined
    const nextSize = Number((parsed as any).chunk_size)
    const nextOverlap = Number((parsed as any).chunk_overlap)

    updateSettings({
      ...(nextStrategy ? { strategy: nextStrategy } : {}),
      ...(Number.isFinite(nextSize) ? { chunkSize: Math.max(50, Math.min(4000, Math.trunc(nextSize))) } : {}),
      ...(Number.isFinite(nextOverlap) ? { chunkOverlap: Math.max(0, Math.min(1000, Math.trunc(nextOverlap))) } : {}),
    })

    if (typeof (parsed as any).separator_preset === 'string') {
      updateSeparatorSettings({ separatorPreset: String((parsed as any).separator_preset) })
    }
    if (typeof (parsed as any).separator === 'string') {
      updateSeparatorSettings({ separatorCustom: String((parsed as any).separator) })
    }
    if (typeof (parsed as any).keep_separator === 'boolean') {
      updateSeparatorSettings({ keepSeparator: Boolean((parsed as any).keep_separator) })
    }
    if (Number.isFinite(Number((parsed as any).separator_max_chunk_size))) {
      updateSeparatorSettings({
        separatorMaxChunkSize: Math.max(0, Math.min(20000, Math.trunc(Number((parsed as any).separator_max_chunk_size)))),
      })
    }

    const pipeline = (parsed as any).pipeline
    if (pipeline && typeof pipeline === 'object') {
      pipelineCtx.setEnabled(true)
      for (const [k, v] of Object.entries(pipeline)) {
        if (k in pipelineCtx.options) {
          pipelineCtx.updateOption(k as any, v as any)
        }
      }
    }

  }

  return (
    <header className="flex-shrink-0 h-20 border-b border-border/60 flex justify-between items-center px-6 bg-card/80 backdrop-blur z-20 shadow-sm relative">
      <div className="flex items-center gap-4">
        {/* Logo Icon */}
        <div className="w-10 h-10 bg-gradient-to-br from-primary to-info rounded-xl flex items-center justify-center shadow-primary/20 dark:shadow-primary/10 shadow-lg ring-1 ring-border/60">
          <Layers className="text-primary-foreground w-5 h-5" />
        </div>
        
        <div className="flex flex-col justify-center min-w-0">
          {/* Row 1: Title & File Info */}
          <div className="flex items-center gap-3">
            <h1 className="text-xs font-bold text-muted-foreground uppercase tracking-wider">切片预览</h1>
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
                       {lastPreviewDurationMs}ms
                    </span>
                  )}
                  {previewData && (
                    <span className="text-muted-foreground font-medium flex items-center gap-1">
                       <span className="w-1.5 h-1.5 rounded-full bg-success" />
                       {previewData.total_chunks} Chunks
                    </span>
                  )}
               </div>
             )}

             {cacheHit && (
                <span className="text-[10px] px-1.5 py-0.5 rounded bg-success/10 text-success border border-success/30 font-medium">
                  Hit Cache
                </span>
             )}
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

        <div className="hidden 2xl:flex items-center gap-3">
          <IngestionWorkflowStepper />
        </div>

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
                    await applyConfigFromText(text)
                    toast.success('已从文件导入配置')
                  })
                  .catch((err: any) => toast.error((err?.message as string) || '读取配置文件失败'))
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
                void copyText(JSON.stringify(config, null, 2), '已复制预览配置')
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
                  await applyConfigFromText(text)
                  toast.success('已从剪贴板导入配置')
                } catch (e: any) {
                  toast.error((e?.message as string) || '导入配置失败')
                }
              }}
            >
              <Copy className="mr-2 h-4 w-4" />
              从剪贴板导入配置
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={!previewData}
              onSelect={() => {
                if (!previewData) return
                const filename = `${sanitizeFilename(previewData.filename)}.chunks.json`
                downloadTextFile(filename, JSON.stringify(toChunkPreviewExport(previewData), null, 2), 'application/json;charset=utf-8')
                toast.success('已导出 JSON')
              }}
            >
              <Download className="mr-2 h-4 w-4" />
              导出 chunks.json
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={!previewData}
              onSelect={() => {
                if (!previewData) return
                const filename = `${sanitizeFilename(previewData.filename)}.chunks.md`
                downloadTextFile(filename, chunkPreviewToMarkdown(previewData), 'text/markdown;charset=utf-8')
                toast.success('已导出 Markdown')
              }}
            >
              <Download className="mr-2 h-4 w-4" />
              导出 chunks.md
            </DropdownMenuItem>
            <DropdownMenuItem
              disabled={!previewData}
              onSelect={() => {
                if (!previewData) return
                const filename = `${sanitizeFilename(previewData.filename)}.chunks.csv`
                downloadTextFile(filename, chunkPreviewToCsv(previewData), 'text/csv;charset=utf-8')
                toast.success('已导出 CSV')
              }}
            >
              <Download className="mr-2 h-4 w-4" />
              导出 chunks.csv
            </DropdownMenuItem>
            <DropdownMenuSeparator />
            <DropdownMenuItem
              onSelect={() => {
                const url = `${API_V1_BASE_URL}/documents/chunk-preview?chunk_size=${encodeURIComponent(
                  String(chunkSize)
                )}&chunk_overlap=${encodeURIComponent(String(chunkOverlap))}`
                const pipeline = pipelineOverridesEnabled ? JSON.stringify(pipelineOptions || {}) : null
                const lines = [
                  `curl -X POST \"${url}\" \\`,
                  `  -H \"X-User-ID: demo\" \\`,
                  `  -F \"file=@/path/to/your-file\" \\`,
                  `  -F \"parser_backend=${effectiveParserBackend}\" \\`,
                  `  -F \"chunk_strategy=${effectiveChunkStrategy}\"`,
                ]
                if (datasetId) {
                  lines.push(`  -F \"dataset_id=${datasetId}\"`)
                }
                if (shouldIncludeSeparatorSettings) {
                  lines.push(`  -F \"separator_preset=${separatorPreset}\"`)
                  if (separatorPreset === 'custom') {
                    lines.push(`  -F $'separator=${escapeForAnsiC(separatorCustom)}'`)
                  }
                  lines.push(`  -F \"keep_separator=${keepSeparator ? 'true' : 'false'}\"`)
                  if (typeof separatorMaxChunkSize === 'number' && separatorMaxChunkSize > 0) {
                    lines.push(`  -F \"separator_max_chunk_size=${separatorMaxChunkSize}\"`)
                  }
                }
                if (pipeline) {
                  lines[lines.length - 1] = `${lines[lines.length - 1]} \\`
                  lines.push(`  -F 'pipeline=${pipeline}'`)
                }
                const curl = lines.join('\n')
                void copyText(curl, '已复制 cURL')
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
                    void copyText(createdDocumentId, '已复制文档 ID')
                  }}
                >
                  <Copy className="mr-2 h-4 w-4" />
                  复制文档 ID
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
            'h-9 px-5 text-xs font-semibold rounded-lg shadow-lg transition-all motion-reduce:transition-none',
            submitSuccess
              ? 'bg-success text-success-foreground hover:bg-success/90 shadow-success/20'
              : 'bg-primary text-primary-foreground hover:bg-primary/90 shadow-primary/20'
          )}
        >
          {isSubmitting ? (
            <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none mr-2" />
          ) : submitSuccess ? (
            <Check className="w-3.5 h-3.5 mr-2" />
          ) : (
            <Save className="w-3.5 h-3.5 mr-2" />
          )}
          {submitSuccess ? '已完成' : '确认入库'}
        </Button>
      </div>
      <div className="absolute inset-x-6 bottom-0 h-px bg-gradient-to-r from-transparent via-primary/20 to-transparent" />

      <ChunkingHelpDialog open={helpOpen} onOpenChange={setHelpOpen} />
    </header>
  )
}
