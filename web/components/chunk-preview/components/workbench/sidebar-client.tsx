/**
 * Sidebar - 左侧配置栏
 */
'use client'

import { useEffect, useMemo, useState } from 'react'
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
} from 'lucide-react'
import { useTranslations } from 'next-intl'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn, formatFileSize } from '@/lib/utils'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { ChunkStrategyDropdown } from '@/components/business/chunk-strategy-dropdown'
import { ParserDropdown } from '@/components/business/parser-dropdown'
import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { getChunkStrategyOption } from '@/lib/chunk-strategies'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'
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

function getErrorMessage(error: unknown, fallback: string): string {
  return error instanceof Error && error.message ? error.message : fallback
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
  const { capabilities, parserBackendAvailable } = usePipelineCapabilities()
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

  const chunkSizeMin = isTokenStrategy ? 50 : 100
  const chunkSizeMax = isTokenStrategy ? 2000 : 4000
  const chunkSizeStep = isTokenStrategy ? 50 : 100
  const overlapStep = isTokenStrategy ? 25 : 50
  const overlapMax = Math.min(isTokenStrategy ? 500 : 1000, Math.max(0, chunkSize - chunkSizeMin))

  const sortedFileList = [...fileList].sort(
    (a, b) => (b.addedAt || 0) - (a.addedAt || 0)
  )

  const currentFileId = fileList[currentFileIndex]?.id
  const parserAvailable = parserBackendAvailable(parserBackend)

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
      toast.error(result.error || options?.errorMessage || '应用入库管线 patch 失败')
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
        setDatasetsError(getErrorMessage(error, '加载数据集失败'))
      })
      .finally(() => {
        if (!alive) return
        setDatasetsLoading(false)
      })
    return () => {
      alive = false
    }
  }, [])

  const content = (
    <div
      className={cn(
        'p-6',
        variant === 'pane' ? 'min-h-0' : 'flex-1 overflow-y-auto overscroll-contain no-scrollbar'
      )}
    >
        {/* 文件列表 */}
        <div className="mb-8 pb-8 border-b border-border/60">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Folder className="w-4 h-4 text-primary" />
              <h2 className="text-sm font-semibold text-foreground">文件列表 ({fileList.length})</h2>
            </div>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => document.getElementById('add-file-input')?.click()}
                className="h-6 w-6 p-0 hover:bg-primary/10"
                aria-label="添加文件"
                title="添加文件"
              >
                <Upload className="w-3.5 h-3.5 text-primary" />
              </Button>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => {
                  clearFiles()
                  toast.success('已清空文件列表')
                }}
                className="h-6 w-6 p-0 hover:bg-destructive/10 hover:text-destructive"
                disabled={fileList.length === 0}
                aria-label="清空文件列表"
                title="清空文件列表"
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

          <div className="space-y-2 max-h-[200px] overflow-y-auto overscroll-contain no-scrollbar pr-1 rounded-xl border border-border/60 bg-card p-2 shadow-sm">
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
                    'group flex items-center gap-2 rounded-lg text-xs transition-colors border',
                    isActive
                      ? 'bg-card border-primary/25 shadow-sm ring-1 ring-ring/15'
                      : 'bg-transparent border-transparent hover:bg-primary/10 hover:border-primary/20'
                  )}
                >
                  <button
                    type="button"
                    onClick={() => {
                      if (fileIndex >= 0) setCurrentFileIndex(fileIndex)
                    }}
                    aria-label={`选择文件：${f.displayName}`}
                    className="flex flex-1 min-w-0 items-center justify-between gap-2 p-2 text-left rounded-lg cursor-pointer focus-ring"
                  >
                    <div className="flex items-center gap-2 min-w-0 flex-1">
                      <FileIcon
                        className={cn('w-3.5 h-3.5 flex-shrink-0', isActive ? 'text-primary' : 'text-muted-foreground')}
                      />
                      <span className={cn('truncate font-medium', isActive ? 'text-foreground' : 'text-muted-foreground')}>
                        {f.displayName}
                      </span>
                    </div>

                    <div className="flex items-center gap-1 flex-shrink-0">
                      {displayTime && (
                        <span className="text-[10px] text-muted-foreground mr-1">{displayTime}</span>
                      )}
                      {f.originalFileType && (
                        <span className="text-[10px] font-mono px-1.5 py-0.5 rounded border border-border/60 bg-muted/60 text-muted-foreground">
                          {String(f.originalFileType).toUpperCase()}
                        </span>
                      )}
                      {typeof f.originalFileSize === 'number' ? (
                        <span className="text-[10px] text-muted-foreground font-mono">{formatFileSize(f.originalFileSize)}</span>
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
                    className="opacity-0 group-hover:opacity-100 focus-visible:opacity-100 p-1.5 mr-1 hover:bg-destructive/10 hover:text-destructive rounded transition-opacity transition-colors duration-150 motion-reduce:transition-none cursor-pointer focus-ring"
                    aria-label={`移除文件：${f.displayName}`}
                    title="移除文件"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              )
            })}
          </div>
        </div>

        <div className="flex items-center gap-2 mb-6">
          <Settings className="w-4 h-4 text-primary" />
          <h2 className="text-sm font-semibold text-foreground">配置参数</h2>
        </div>

        <div className="space-y-8">
          <div className="flex items-center justify-between bg-card border border-border/60 rounded-xl px-3 py-2 shadow-sm">
            <div>
              <div className="text-xs font-medium text-foreground/80">自动预览</div>
              <div className="text-[10px] text-muted-foreground">切换文件后自动生成预览</div>
            </div>
            <label className="inline-flex items-center gap-2 text-[10px] text-muted-foreground">
              <input
                type="checkbox"
                checked={autoPreviewEnabled}
                onChange={(e) => toggleAutoPreview(e.target.checked)}
                className="h-3.5 w-3.5 rounded border-border/60 text-primary focus:ring-2 focus:ring-ring/20 focus:ring-offset-2 focus:ring-offset-background"
              />
              {autoPreviewEnabled ? '开启' : '关闭'}
            </label>
          </div>

          <div className="flex items-center justify-between bg-card border border-border/60 rounded-xl px-3 py-2 shadow-sm">
            <div className="text-[10px] text-muted-foreground">快捷键</div>
            <div className="text-[10px] text-muted-foreground">
              Ctrl/⌘ + Enter 预览 · Ctrl/⌘ + S 入库
            </div>
          </div>

          <div className="bg-card border border-border/60 rounded-xl px-3 py-3 shadow-sm space-y-3">
            <div className="flex items-center gap-2">
              <Wand2 className="w-4 h-4 text-primary" />
              <div className="text-xs font-medium text-foreground/80">预览性能</div>
              <div className="text-[10px] text-muted-foreground">仅影响预览载荷，不影响入库</div>
            </div>

            <div className="flex items-center justify-between gap-2">
              <div>
                <div className="text-xs font-medium text-foreground/80">返回原文（用于高亮）</div>
                <div className="text-[10px] text-muted-foreground">大文档建议关闭或降低上限</div>
              </div>
              <label className="inline-flex items-center gap-2 text-[10px] text-muted-foreground">
                <input
                  type="checkbox"
                  checked={includeOriginalText}
                  onChange={(e) => updatePerfSettings({ includeOriginalText: e.target.checked })}
                  className="h-3.5 w-3.5 rounded border-border/60 text-primary focus:ring-2 focus:ring-ring/20 focus:ring-offset-2 focus:ring-offset-background"
                />
                {includeOriginalText ? '开启' : '关闭'}
              </label>
            </div>

            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-medium text-muted-foreground">原文上限（chars）</div>
              <Input
                type="number"
                inputMode="numeric"
                min={0}
                max={2000000}
                step={10000}
                value={originalTextMaxChars}
                onChange={(e) => updatePerfSettings({ originalTextMaxChars: Number(e.target.value) })}
                className="h-7 w-28 text-[11px] font-mono bg-background"
                aria-label="原文上限"
                disabled={!includeOriginalText}
              />
            </div>

            <div className="flex items-center justify-between gap-2">
              <div className="text-xs font-medium text-muted-foreground">最多返回 chunks</div>
              <Input
                type="number"
                inputMode="numeric"
                min={0}
                max={20000}
                step={100}
                value={maxChunks}
                onChange={(e) => updatePerfSettings({ maxChunks: Number(e.target.value) })}
                className="h-7 w-28 text-[11px] font-mono bg-background"
                aria-label="最多返回 chunks"
              />
            </div>

            <div className="flex items-center justify-between gap-2">
              <div>
                <div className="text-xs font-medium text-foreground/80">后端解析缓存</div>
                <div className="text-[10px] text-muted-foreground">同一文件/解析器调参时可显著提速</div>
              </div>
              <label className="inline-flex items-center gap-2 text-[10px] text-muted-foreground">
                <input
                  type="checkbox"
                  checked={useParseCache}
                  onChange={(e) => updatePerfSettings({ useParseCache: e.target.checked })}
                  className="h-3.5 w-3.5 rounded border-border/60 text-primary focus:ring-2 focus:ring-ring/20 focus:ring-offset-2 focus:ring-offset-background"
                />
                {useParseCache ? '开启' : '关闭'}
              </label>
            </div>

            <div className="text-[10px] text-muted-foreground leading-relaxed">
              0 表示不限制。建议 1000-5000；太大可能导致浏览器卡顿。
            </div>

            {previewData?.chunks_truncated ? (
              <div className="text-[10px] text-warning bg-warning/10 border border-warning/25 rounded-lg px-2 py-1">
                已截断：当前显示 {previewData.total_chunks}
                {previewData.total_chunks_full && previewData.total_chunks_full !== previewData.total_chunks
                  ? ` / ${previewData.total_chunks_full}`
                  : ''}{' '}
                chunks
                <Button
                  type="button"
                  variant="ghost"
                  size="sm"
                  className="h-6 px-2 ml-2 text-[10px]"
                  onClick={() => {
                    updatePerfSettings({ maxChunks: 0 })
                    toast.success('已取消限制，请重新生成预览')
                  }}
                >
                  取消限制
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
            <div className="text-xs font-medium text-muted-foreground">目标数据集（可选）</div>
            <Select
              value={datasetId || DATASET_DEFAULT_VALUE}
              onValueChange={(value) => {
                setIngestionPreview(null)
                setIngestionError(null)
                setDatasetId(value === DATASET_DEFAULT_VALUE ? '' : value)
              }}
            >
              <SelectTrigger className="h-10 bg-background">
                <SelectValue placeholder="选择数据集" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={DATASET_DEFAULT_VALUE}>默认（自动选择可写数据集）</SelectItem>
                {datasets.map((ds) => (
                  <SelectItem key={ds.id} value={ds.id}>
                    {ds.name}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            {(() => {
    if (datasetsLoading) {
        return (<div className="text-[10px] text-muted-foreground">正在加载数据集...</div>);
    }
    else if (datasetsError) {
            return (<div className="text-[10px] text-warning bg-warning/10 border border-warning/25 rounded-lg px-2 py-1">
                {datasetsError}
              </div>);
        }
        else {
            return null;
        }
})()}

            {selectedDataset?.pipeline ? (
              <div className="rounded-xl border border-border/60 bg-background p-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[10px] text-muted-foreground">数据集 Pipeline（摘要）</div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 px-2 text-[11px]"
                    onClick={() => {
                      applyPipelinePatch(selectedDataset.pipeline, {
                        successMessage: '已应用数据集 Pipeline 到当前预览',
                        errorMessage: '应用数据集 Pipeline 失败',
                      })
                    }}
                  >
                    应用
                  </Button>
                </div>
                <div className="mt-2 flex flex-wrap gap-2 text-[10px]">
                  {selectedDataset.pipeline.governance_enabled ? (
                    <span className="px-2 py-0.5 rounded-full bg-sky-500/10 text-sky-700 dark:text-sky-200 border border-sky-500/20">
                      Governance
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 rounded-full bg-muted text-muted-foreground border border-border/60">
                      Governance Off
                    </span>
                  )}
                  {selectedDataset.pipeline.chunk_vector_enabled ? (
                    <span className="px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20">
                      Vector
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 rounded-full bg-muted text-muted-foreground border border-border/60">
                      Vector Off
                    </span>
                  )}
                  {selectedDataset.pipeline.bm25_index_enabled ? (
                    <span className="px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20">
                      BM25
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 rounded-full bg-muted text-muted-foreground border border-border/60">
                      BM25 Off
                    </span>
                  )}
                  {selectedDataset.pipeline.kg_enabled ? (
                    <span className="px-2 py-0.5 rounded-full bg-purple-500/10 text-purple-700 dark:text-purple-200 border border-purple-500/20">
                      KG
                    </span>
                  ) : null}
                </div>
              </div>
            ) : null}

            <Button
              type="button"
              variant="outline"
              disabled={!datasetId || !currentFile || ingestionLoading}
              className="w-full h-9 text-xs justify-start"
              onClick={async () => {
                if (!datasetId) {
                  toast.error('请先选择目标数据集')
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
                  toast.success('已生成入库策略预览（可应用推荐）')
                } catch (error: unknown) {
                  setIngestionError(getErrorMessage(error, '入库策略预览失败'))
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
              按入库策略智能推荐
            </Button>

            {ingestionError ? (
              <div className="text-[10px] text-warning bg-warning/10 border border-warning/25 rounded-lg px-2 py-1">
                {ingestionError}
              </div>
            ) : null}

	            {ingestionPreview ? (
	              <div className="rounded-xl border border-border/60 bg-background p-3 space-y-2">
	                <div className="flex items-center justify-between gap-2">
	                  <div className="text-[10px] text-muted-foreground">命中规则</div>
	                  <div className="flex items-center gap-1">
	                    <Button
	                      type="button"
	                      variant="ghost"
	                      size="sm"
	                      className="h-7 px-2 text-[11px]"
	                      onClick={() => setIngestionDetailsOpen(true)}
	                    >
	                      详情
	                    </Button>
	                    <Button
	                      type="button"
	                      variant="ghost"
	                      size="sm"
	                      className="h-7 px-2 text-[11px]"
	                      onClick={() => setIngestionPreview(null)}
	                    >
	                      清除
	                    </Button>
	                  </div>
	                </div>
                <div className="text-xs text-foreground/90 font-medium">
                  {ingestionPreview.rule.matched
                    ? (ingestionPreview.rule.rule_name || ingestionPreview.rule.rule_id || '已命中规则')
                    : '未命中策略规则（使用默认配置）'}
                </div>
                <div className="text-[10px] text-muted-foreground font-mono">
                  parser: {ingestionPreview.rule.parser_backend} · strategy: {ingestionPreview.rule.chunk_strategy}
                </div>
                {ingestionPreview.rule.governance_profile_ref ? (
                  <div className="text-[10px] text-muted-foreground">
                    governance profile: <span className="font-mono">{ingestionPreview.rule.governance_profile_ref}</span>
                  </div>
                ) : null}
	                <div className="text-[10px] text-muted-foreground">
	                  preprocess steps: <span className="font-mono">{ingestionPreview.rule.preprocess_steps.length}</span>
	                </div>
	                <div className="text-[10px] text-muted-foreground">
	                  preprocess:{' '}
	                  <span className={cn(ingestionPreview.preprocess.changed ? 'text-warning' : 'text-muted-foreground')}>
	                    {ingestionPreview.preprocess.changed ? 'changed' : 'no change'}
	                  </span>{' '}
	                  ·{' '}
	                  <span className="font-mono">
	                    {formatFileSize(ingestionPreview.preprocess.size_before)} → {formatFileSize(ingestionPreview.preprocess.size_after)}
	                  </span>
	                  {ingestionPreview.preprocess.warnings?.length ? (
	                    <span className="text-warning"> · warnings {ingestionPreview.preprocess.warnings.length}</span>
	                  ) : null}
	                </div>
                <div className="flex items-center gap-2 pt-1">
                  <Button
                    type="button"
                    size="sm"
                    className="h-8 px-3 text-[11px]"
                    onClick={() => {
                      setParserBackend(ingestionPreview.rule.parser_backend)
                      updateSettings({ strategy: ingestionPreview.rule.chunk_strategy })
                      toast.success('已应用推荐的解析器与切块策略')
                    }}
                  >
                    应用推荐
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant="outline"
                    className="h-8 px-3 text-[11px]"
                    onClick={() => runPreview({ force: true })}
                  >
                    立即预览
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
	                applyPipelinePatch(patch, { errorMessage: '应用 suggested pipeline patch 失败' })
	              }}
	            />
	          </div>
          <div className="space-y-2">
            <div className="text-xs font-medium text-muted-foreground">解析器</div>
            <ChunkPresetPanel className="mb-3" />
            <ParserDropdown value={parserBackend} onChange={setParserBackend} />
            {parserAvailable === false && (
              <div className="text-[10px] text-warning bg-warning/10 border border-warning/25 rounded-lg px-2 py-1">
                当前解析器不可用，建议切换为 {capabilities?.default_parser_backend || 'auto'}。
              </div>
            )}
          </div>

          {/* 策略选择 */}
          <div className="space-y-2">
            <div className="text-xs font-medium text-muted-foreground">切块策略</div>
            <ChunkStrategyDropdown
              value={chunkStrategy}
              onChange={(value) => {
                updateSettings({ strategy: value, ...(value === 'separator' ? { chunkOverlap: 0 } : {}) })
                if (value === 'separator' && !separatorPreset) {
                  updateSeparatorSettings({ separatorPreset: 'paragraph' })
                }
              }}
            />
            <p className="text-[10px] text-muted-foreground leading-relaxed mt-1.5">{chunkStrategyOption.description}</p>
            <div className="flex flex-wrap items-center gap-2 pt-1 text-[10px] text-muted-foreground">
              <span className="opacity-80">快速预设:</span>
              {[
                {
                  key: 'general',
                  label: '通用',
                  apply: () => updateSettings({ strategy: 'auto', chunkSize: 1000, chunkOverlap: 200 }),
                },
                {
                  key: 'faq',
                  label: 'FAQ/Q&A',
                  apply: () => updateSettings({ strategy: 'qa_pairs', chunkSize: 800, chunkOverlap: 120 }),
                },
                {
                  key: 'code',
                  label: '代码',
                  apply: () => updateSettings({ strategy: 'smart_code', chunkSize: 1000, chunkOverlap: 150 }),
                },
                {
                  key: 'contract',
                  label: '条款/合同',
                  apply: () => updateSettings({ strategy: 'laws_structured', chunkSize: 1200, chunkOverlap: 200 }),
                },
                {
                  key: 'separator',
                  label: '分隔符',
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
                    toast.success(`已应用预设：${item.label}`)
                  }}
                >
                  {item.label}
                </button>
              ))}
            </div>
          </div>

          {isSeparatorStrategy ? (
            <div className="space-y-4 rounded-xl border border-border/60 bg-background p-3 shadow-sm">
              <div className="text-[10px] text-muted-foreground uppercase  font-medium">分隔符策略参数</div>

              <div className="flex items-center justify-between gap-2">
                <div className="text-[10px] text-muted-foreground">同步到 Pipeline.chunk_strategy_params</div>
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
                    toast.success('已写入 Pipeline.chunk_strategy_params（separator）')
                  }}
                >
                  写入
                </Button>
              </div>
              {pipelineCtx.options.chunk_strategy_params ? (
                <div className="text-[10px] text-muted-foreground font-mono break-all">
                  当前 pipeline: {JSON.stringify(pipelineCtx.options.chunk_strategy_params)}
                </div>
              ) : (
                <div className="text-[10px] text-muted-foreground font-mono">当前 pipeline: (empty)</div>
              )}

              <div className="space-y-2">
                <div className="text-xs font-medium text-muted-foreground">分隔符预设</div>
                <Select
                  value={separatorPreset}
                  onValueChange={(value) => updateSeparatorSettings({ separatorPreset: value })}
                >
                  <SelectTrigger className="h-9 bg-background">
                    <SelectValue placeholder="选择分隔符预设" />
                  </SelectTrigger>
                  <SelectContent>
                    {SEPARATOR_PRESET_OPTIONS.map((opt) => (
                      <SelectItem key={opt.value} value={opt.value}>
                        {opt.label}
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
                <div className="text-[10px] text-muted-foreground">
                  {SEPARATOR_PRESET_OPTIONS.find((o) => o.value === separatorPreset)?.hint || ''}
                </div>
                {effectiveSeparator ? (
                  <div className="text-[10px] text-muted-foreground font-mono">
                    有效分隔符: {JSON.stringify(effectiveSeparator).slice(1, -1) || '(empty)'} · len: {effectiveSeparator.length}
                  </div>
                ) : null}
              </div>

              {separatorPreset === 'custom' ? (
                <div className="space-y-2">
                  <div className="text-xs font-medium text-muted-foreground">自定义分隔符</div>
                  <Input
                    value={separatorCustom}
                    onChange={(e) => updateSeparatorSettings({ separatorCustom: e.target.value })}
                    className="h-9 text-[11px] font-mono bg-background"
                    placeholder="例如：\\n\\n / --- / ##  / END_OF_SECTION"
                    aria-label="自定义分隔符"
                  />
                  <div className="text-[10px] text-muted-foreground">
                    支持转义：\\n \\r \\t \\uXXXX（会在发送到后端前解析）
                  </div>
                </div>
              ) : null}

              <div className="flex items-center justify-between gap-2 bg-card border border-border/60 rounded-xl px-3 py-2">
                <div>
                  <div className="text-xs font-medium text-foreground/80">保留分隔符</div>
                  <div className="text-[10px] text-muted-foreground">将分隔符附在前一块末尾</div>
                </div>
                <label className="inline-flex items-center gap-2 text-[10px] text-muted-foreground">
                  <input
                    type="checkbox"
                    checked={keepSeparator}
                    onChange={(e) => updateSeparatorSettings({ keepSeparator: e.target.checked })}
                    className="h-3.5 w-3.5 rounded border-border/60 text-primary focus:ring-2 focus:ring-ring/20 focus:ring-offset-2 focus:ring-offset-background"
                  />
                  {keepSeparator ? '开启' : '关闭'}
                </label>
              </div>

              <div className="space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-xs font-medium text-muted-foreground">最大块长度（可选）</div>
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
                    aria-label="最大块长度"
                  />
                </div>
                <div className="text-[10px] text-muted-foreground leading-relaxed">
                  0 表示自动：chunk_size × 3。注意：separator 策略不使用 overlap（重叠）。
                </div>
              </div>
            </div>
          ) : null}

          {isParentChildStrategy ? (
            <div className="space-y-4 rounded-xl border border-border/60 bg-background p-3 shadow-sm">
              <div className="text-[10px] text-muted-foreground uppercase  font-medium">PARENT-CHILD OPTIONS</div>

              <div className="flex items-center justify-between gap-2">
                <div className="text-[10px] text-muted-foreground">同步到 Pipeline.chunk_strategy_params</div>
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
                    toast.success('已写入 Pipeline.chunk_strategy_params（parent_child）')
                  }}
                >
                  写入
                </Button>
              </div>
              {pipelineCtx.options.chunk_strategy_params ? (
                <div className="text-[10px] text-muted-foreground font-mono break-all">
                  当前 pipeline: {JSON.stringify(pipelineCtx.options.chunk_strategy_params)}
                </div>
              ) : (
                <div className="text-[10px] text-muted-foreground font-mono">当前 pipeline: (empty)</div>
              )}

              <div className="grid grid-cols-2 gap-3">
                <div className="space-y-2">
                  <div className="text-xs font-medium text-muted-foreground">child_ratio</div>
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
                    aria-label="parent_child child_ratio"
                  />
                  <div className="text-[10px] text-muted-foreground">child_size = max(chunk_size × ratio, min_child_size)</div>
                </div>

                <div className="space-y-2">
                  <div className="text-xs font-medium text-muted-foreground">min_child_size</div>
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
                    aria-label="parent_child min_child_size"
                  />
                  <div className="text-[10px] text-muted-foreground">recommended: 200–600 for text docs</div>
                </div>
              </div>

              {parentChildEffective ? (
                <div className="text-[10px] text-muted-foreground font-mono">
                  effective child_size: {parentChildEffective.childSize} chars · child_overlap: {parentChildEffective.childOverlap} chars · ratio: {Math.round(parentChildEffective.ratio * 100)}%
                </div>
              ) : null}

              <div className="text-[10px] text-muted-foreground leading-relaxed">
                parent_child 会生成 parent/child 两类 chunks，并在 metadata 中写入 parent_id 与 chunk_role，便于后端 parent-child 检索/重排。
              </div>
            </div>
          ) : null}

          {/* Slider Controls */}
          {!hideChunkSizeControl && (
            <div className="space-y-4">
              <div className="flex items-center justify-between gap-2">
                <label className="text-xs font-medium text-muted-foreground">{isTokenStrategy ? 'Token 上限' : '块大小 (Chars)'}</label>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono font-medium text-primary bg-primary/10 px-2 py-0.5 rounded">{chunkSize}</span>
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
                    aria-label={isTokenStrategy ? 'Token 上限' : '块大小'}
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
                <span>预设:</span>
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
            <div className="space-y-4">
              <div className="flex items-center justify-between gap-2">
                <label className="text-xs font-medium text-muted-foreground">{isTokenStrategy ? 'Token 重叠' : '重叠 (Chars)'}</label>
                <div className="flex items-center gap-2">
                  <span className="text-xs font-mono font-medium text-primary bg-primary/10 px-2 py-0.5 rounded">{chunkOverlap}</span>
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
                    aria-label={isTokenStrategy ? 'Token 重叠' : '重叠'}
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
                    建议 {overlapGuidance.min}-{overlapGuidance.max}（10-25%）
                  </span>
                  <span className={cn(overlapGuidance.outOfRange ? 'text-warning' : 'text-muted-foreground')}>
                    当前 {Math.round(overlapGuidance.ratio * 100)}%
                  </span>
                </div>
              ) : null}
              <div className="flex items-center gap-2 text-[10px] text-muted-foreground">
                <span>快捷:</span>
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
            <div className="text-xs font-medium text-muted-foreground">{t('sidebar.ingestionPipeline')}</div>
            <PipelineOptionsPanel compact />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <Button
              onClick={() => runPreview()}
              disabled={isLoading}
              className="h-11 rounded-xl shadow-sm border border-primary/20"
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
              className="h-11 rounded-xl"
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
          <div className="mt-8 pt-8 border-t border-border/60">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-primary" />
                <h2 className="text-sm font-semibold text-foreground">{t('sidebar.analysis.title')}</h2>
              </div>
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

            <div className="grid grid-cols-2 gap-3">
              <div className="bg-card p-3 rounded-xl border border-border/60 shadow-sm">
                <div className="text-[10px] text-muted-foreground uppercase  font-medium">切片数量</div>
                <div className="text-xl font-bold text-foreground mt-1">{previewData.total_chunks}</div>
              </div>
              <div className="bg-card p-3 rounded-xl border border-border/60 shadow-sm">
                <div className="text-[10px] text-muted-foreground uppercase  font-medium">
                  {isTokenStrategy ? '平均 TOKENS' : '平均长度'}
                </div>
                <div className="text-xl font-bold text-foreground mt-1">
                  {previewData?.stats?.avg ?? chunkStats?.avg ?? '-'}
                  {isTokenStrategy ? (
                    <span className="ml-1 text-xs font-mono text-muted-foreground">{statsUnitLabel}</span>
                  ) : null}
                </div>
              </div>
              <div className="bg-card p-3 rounded-xl border border-border/60 shadow-sm">
                <div className="text-[10px] text-muted-foreground uppercase  font-medium">
                  {isTokenStrategy ? 'P95 TOKENS' : 'P95'}
                </div>
                <div className="text-xl font-bold text-foreground mt-1">
                  {chunkStats?.p95 ?? chunkStats?.p90 ?? previewData?.stats?.p90 ?? '-'}
                  {isTokenStrategy ? (
                    <span className="ml-1 text-xs font-mono text-muted-foreground">{statsUnitLabel}</span>
                  ) : null}
                </div>
              </div>
              <div className="bg-card p-3 rounded-xl border border-border/60 shadow-sm" title="coverage_ratio">
                <div className="text-[10px] text-muted-foreground uppercase  font-medium">覆盖率</div>
                <div className="text-xl font-bold text-foreground mt-1">
                  {coverageSignals?.coveragePct == null ? '-' : `${coverageSignals.coveragePct}%`}
                </div>
              </div>
              <div className="bg-card p-3 rounded-xl border border-border/60 shadow-sm" title="overlap_waste_ratio">
                <div className="text-[10px] text-muted-foreground uppercase  font-medium">重叠浪费</div>
                <div className="text-xl font-bold text-foreground mt-1">
                  {coverageSignals?.overlapWastePct == null ? '-' : `${coverageSignals.overlapWastePct}%`}
                </div>
              </div>
              <div className="bg-card p-3 rounded-xl border border-border/60 shadow-sm" title="gap_count / largest_gap">
                <div className="text-[10px] text-muted-foreground uppercase  font-medium">Gaps</div>
                <div className="text-xl font-bold text-foreground mt-1">
                  {coverageSignals?.gapCount == null ? '-' : String(coverageSignals.gapCount)}
                </div>
                {coverageSignals?.largestGap == null ? null : (
                  <div className="mt-1 text-[10px] text-muted-foreground font-mono">largest {coverageSignals.largestGap}</div>
                )}
              </div>
            </div>

            {showAdvancedStats && chunkStats ? (
              <div className="mt-3 grid grid-cols-2 gap-3">
                <div className="bg-card p-3 rounded-xl border border-border/60 shadow-sm">
                  <div className="text-[10px] text-muted-foreground uppercase  font-medium">
                    {isTokenStrategy ? '最小 / 最大 TOKENS' : '最短 / 最长'}
                  </div>
                  <div className="mt-1 text-sm font-mono text-foreground/90">
                    {chunkStats.min} / {chunkStats.max}
                  </div>
                  <div className="mt-1 text-[10px] text-muted-foreground font-mono">P10: {chunkStats.p10}</div>
                </div>
                <div className="bg-card p-3 rounded-xl border border-border/60 shadow-sm">
                  <div className="text-[10px] text-muted-foreground uppercase  font-medium">质量信号</div>
                  <div className="mt-1 text-[11px] text-muted-foreground">
                    <span className="font-mono text-foreground/90">{chunkStats.shortCount}</span> 个短切片 ·{' '}
                    <span className="font-mono text-foreground/90">{chunkStats.duplicateCount}</span> 个重复（估算）
                  </div>
                  {overlapGuidance ? (
                    <div className={cn('mt-1 text-[10px]', overlapGuidance.outOfRange ? 'text-warning' : 'text-muted-foreground')}>
                      overlap {Math.round(overlapGuidance.ratio * 100)}%（建议 10-25%）
                    </div>
                  ) : null}
                  {coverageSignals ? (
                    <div
                      className={cn(
                        'mt-1 text-[10px]',
                        coverageSignals.coveragePct != null && coverageSignals.coveragePct < 95 ? 'text-warning' : 'text-muted-foreground'
                      )}
                      title={coverageSignals.largestGap == null ? undefined : `largest_gap: ${coverageSignals.largestGap}`}
                    >
                      coverage {coverageSignals.coveragePct ?? '-'}% · waste {coverageSignals.overlapWastePct ?? '-'}% · gaps {coverageSignals.gapCount ?? '-'}
                    </div>
                  ) : null}
                </div>
                <div className="col-span-2 bg-card p-3 rounded-xl border border-border/60 shadow-sm">
                  <div className="text-[10px] text-muted-foreground uppercase  font-medium">
                    {isTokenStrategy ? 'TOKENS 分布' : '长度分布'}
                  </div>
                  {histogramData.length ? (
                    <div className="mt-2 h-[120px]">
                      <ResponsiveContainer width="100%" height="100%">
                        <BarChart data={histogramData} margin={{ top: 8, right: 8, bottom: 0, left: 0 }}>
                          <CartesianGrid strokeDasharray="3 3" vertical={false} stroke="hsl(var(--border))" strokeOpacity={0.35} />
                          <XAxis dataKey="label" hide />
                          <YAxis hide />
                          <Tooltip
                            formatter={(value) => [value ?? 0, 'count']}
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
                    <div className="mt-2 text-[11px] text-muted-foreground">No histogram data</div>
                  )}
                  <div className="mt-2 flex items-center justify-between text-[10px] text-muted-foreground font-mono">
                    <span>0</span>
                    <span>{histogramMax || chunkStats.max}</span>
                  </div>
                </div>
                {previewData?.recommendations?.length || previewData?.recommendation_patches?.length ? (
                  <div className="col-span-2 bg-card p-3 rounded-xl border border-border/60 shadow-sm">
                    <div className="flex items-center justify-between gap-2">
                      <div className="text-[10px] text-muted-foreground uppercase  font-medium">RECOMMENDATIONS</div>
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
                                applyPipelinePatch(patch, { errorMessage: '应用推荐的入库管线 patch 失败' })
                              } else if (target === 'perf') {
                                const next = buildPerfSettingsPatch(patch)
                                if (Object.keys(next).length) updatePerfSettings(next)
                              }
                            }
                            toast.success('已应用全部 recommendations（best-effort）')
                          }}
                        >
                          一键应用
                        </Button>
                      ) : null}
                    </div>

                    {previewData?.recommendation_patches?.length ? (
                      <div className="mt-2 space-y-2">
                        {(previewData.recommendation_patches || []).slice(0, 6).map((patchItem: ChunkPreviewRecommendationPatch) => {
                          const title = patchItem.title || patchItem.id || 'patch'
                          const desc = patchItem.description || ''
                          const target = patchItem.target || 'preview'
                          const patch = patchItem.patch || {}
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
                                        toast.success('已应用到预览参数')
                                      }
                                      return
                                    }
                                    if (target === 'pipeline') {
                                      if (applyPipelinePatch(patch, { errorMessage: '应用到入库管线失败' })) {
                                        toast.success('已应用到入库管线')
                                      }
                                      return
                                    }
                                    if (target === 'perf') {
                                      const next = buildPerfSettingsPatch(patch)
                                      if (Object.keys(next).length) {
                                        updatePerfSettings(next)
                                        toast.success('已应用到性能参数')
                                      }
                                    }
                                  }}
                                  title={Object.keys(patch || {}).length ? JSON.stringify(patch) : undefined}
                                >
                                  应用
                                </Button>
                              </div>
                              <div className="mt-1 text-[10px] text-muted-foreground font-mono">target: {target}</div>
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
          <div className="mt-8 pt-8 border-t border-border/60">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <Sparkles className="w-4 h-4 text-primary" />
                <h2 className="text-sm font-semibold text-foreground">最近预览</h2>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-[11px]"
                onClick={() => {
                  clearRunHistory()
                  toast.success('已清空最近预览')
                }}
              >
                清空
              </Button>
            </div>
            <div className="space-y-2 max-h-[180px] overflow-y-auto overscroll-contain no-scrollbar pr-1">
              {runHistory.map((item) => (
                <button
                  type="button"
                  key={item.id}
                  className={cn(
                    "w-full text-left bg-card border border-border/60 rounded-xl px-3 py-2 text-[10px] text-muted-foreground shadow-sm",
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
                    toast.success('已恢复历史预览配置')
                  }}
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-foreground/80 truncate">{item.fileName}</span>
                    <span>{new Date(item.createdAt).toLocaleString([], { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-2">
                    <span className="px-2 py-0.5 rounded-full border border-border/60 bg-muted/60">Chunks: {item.totalChunks}</span>
                    <span className="px-2 py-0.5 rounded-full border border-border/60 bg-muted/60">耗时: {item.durationMs}ms</span>
                    <span className="px-2 py-0.5 rounded-full border border-border/60 bg-muted/60">{item.strategy}</span>
                    {item.cacheHit && (
                      <span className="px-2 py-0.5 rounded-full bg-success/10 text-success border border-success/25">缓存</span>
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
        variant === 'dialog' ? 'w-full border-0' : 'w-80 border-r border-border/60'
      )}
    >
      {content}
    </aside>
  )
}
