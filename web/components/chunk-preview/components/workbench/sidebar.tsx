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
  Database,
  Wand2,
  ChevronDown,
} from 'lucide-react'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn, formatFileSize } from '@/lib/utils'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { ChunkStrategyDropdown } from '@/components/ui/chunk-strategy-dropdown'
import { ParserDropdown } from '@/components/ui/parser-dropdown'
import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { getChunkStrategyOption } from '@/lib/chunk-strategies'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { UPLOAD_ACCEPT } from '@/lib/upload-extensions'
import { computeChunkLengthStats } from '@/components/chunk-preview/utils/stats'
import { datasetApi, pipelineApi } from '@/lib/api-client'
import type { Dataset, IngestionPreviewResponse } from '@/types'

function clampInt(value: number, min: number, max: number) {
  return Math.min(max, Math.max(min, Math.trunc(value)))
}

const DATASET_DEFAULT_VALUE = '__mimirq_dataset_default__'

export function Sidebar({ variant = 'panel' }: { variant?: 'panel' | 'dialog' } = {}) {
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
    parserBackend,
    autoPreviewEnabled,
    runHistory,
    processedStatus,
    setCurrentFileIndex,
    removeFile,
    addFiles,
    setDatasetId,
    updateSettings,
    runPreview,
    cancelPreview,
    setParserBackend,
    toggleAutoPreview,
  } = useChunkPreview()
  const { capabilities, parserBackendAvailable } = usePipelineCapabilities()
  const pipelineCtx = usePipelineOptions()

  const chunkStrategyOption = getChunkStrategyOption(chunkStrategy)
  const resolvedChunkStrategy = previewData?.chunk_strategy || chunkStrategy
  const strategyForUi = resolvedChunkStrategy
  const isTokenStrategy = strategyForUi === 'langchain_token'
  const isSentenceStrategy = strategyForUi === 'llama_index'
  const isHierarchicalStrategy = strategyForUi === 'llama_index_hierarchical'
  const isRagflowStrategy = strategyForUi.startsWith('ragflow_')

  const hideChunkSizeControl = isSentenceStrategy || isRagflowStrategy
  const showOverlapControl =
    !isSentenceStrategy && !isRagflowStrategy && !isHierarchicalStrategy && strategyForUi !== 'separator'

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
    return previewData?.chunks ? computeChunkLengthStats(previewData.chunks) : null
  }, [previewData?.chunks])

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

  const [showAdvancedStats, setShowAdvancedStats] = useState(false)

  const [datasets, setDatasets] = useState<Dataset[]>([])
  const [datasetsLoading, setDatasetsLoading] = useState(false)
  const [datasetsError, setDatasetsError] = useState<string | null>(null)
  const selectedDataset = useMemo(() => (datasetId ? datasets.find((ds) => ds.id === datasetId) || null : null), [datasetId, datasets])

  const [ingestionPreview, setIngestionPreview] = useState<IngestionPreviewResponse | null>(null)
  const [ingestionLoading, setIngestionLoading] = useState(false)
  const [ingestionError, setIngestionError] = useState<string | null>(null)

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
      .catch((err: any) => {
        if (!alive) return
        setDatasetsError((err?.message as string) || '加载数据集失败')
      })
      .finally(() => {
        if (!alive) return
        setDatasetsLoading(false)
      })
    return () => {
      alive = false
    }
  }, [])

  return (
    <aside
      className={cn(
        'bg-card/80 flex flex-col flex-shrink-0 z-10 backdrop-blur',
        variant === 'dialog' ? 'w-full border-0' : 'w-80 border-r border-border/60'
      )}
    >
      <div className="p-6 flex-1 overflow-y-auto overscroll-contain no-scrollbar">
        {/* 文件列表 */}
        <div className="mb-8 pb-8 border-b border-border/60">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Folder className="w-4 h-4 text-primary" />
              <h2 className="text-xs font-bold text-foreground uppercase tracking-wider">文件列表 ({fileList.length})</h2>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => document.getElementById('add-file-input')?.click()}
              className="h-6 w-6 p-0 hover:bg-primary/10"
            >
              <Upload className="w-3.5 h-3.5 text-primary" />
            </Button>
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

          <div className="space-y-2 max-h-[200px] overflow-y-auto overscroll-contain no-scrollbar pr-1 rounded-xl border border-border/60 bg-card/80 p-2 shadow-sm backdrop-blur">
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
                onClick={() => {
                  if (fileIndex >= 0) setCurrentFileIndex(fileIndex)
                }}
                className={cn(
                  'group flex items-center justify-between p-2 rounded-lg text-xs cursor-pointer transition-colors border',
                  isActive
                    ? 'bg-card border-primary/25 shadow-sm ring-1 ring-ring/15'
                    : 'bg-transparent border-transparent hover:bg-primary/10 hover:border-primary/20'
                )}
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

                  <button
                    type="button"
                    onClick={(e) => {
                      e.stopPropagation()
                      removeFile(fileIndex)
                    }}
                    className="opacity-0 group-hover:opacity-100 p-1 hover:bg-destructive/10 hover:text-destructive rounded transition-all focus-ring"
                  >
                    <Trash2 className="w-3 h-3" />
                  </button>
                </div>
              </div>
              )
            })}
          </div>
        </div>

        <div className="flex items-center gap-2 mb-6">
          <Settings className="w-4 h-4 text-primary" />
          <h2 className="text-xs font-bold text-foreground uppercase tracking-wider">配置参数</h2>
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

          <div className="space-y-2">
            <label className="text-xs font-medium text-muted-foreground">目标数据集（可选）</label>
            <Select
              value={datasetId || DATASET_DEFAULT_VALUE}
              onValueChange={(value) => {
                setIngestionPreview(null)
                setIngestionError(null)
                setDatasetId(value === DATASET_DEFAULT_VALUE ? '' : value)
              }}
            >
              <SelectTrigger className="h-10 bg-card/80">
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
            {datasetsLoading ? (
              <div className="text-[10px] text-muted-foreground">正在加载数据集...</div>
            ) : datasetsError ? (
              <div className="text-[10px] text-warning bg-warning/10 border border-warning/25 rounded-lg px-2 py-1">
                {datasetsError}
              </div>
            ) : null}

            {selectedDataset?.pipeline ? (
              <div className="rounded-xl border border-border/60 bg-card/70 p-3">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[10px] text-muted-foreground">数据集 Pipeline（摘要）</div>
                  <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    className="h-7 px-2 text-[11px]"
                    onClick={() => {
                      const patch = selectedDataset.pipeline as any
                      pipelineCtx.setEnabled(true)
                      for (const [k, v] of Object.entries(patch || {})) {
                        if (k in pipelineCtx.options) {
                          pipelineCtx.updateOption(k as any, v as any)
                        }
                      }
                      toast.success('已应用数据集 Pipeline 到当前预览')
                    }}
                  >
                    应用
                  </Button>
                </div>
                <div className="mt-2 flex flex-wrap gap-2 text-[10px]">
                  {(selectedDataset.pipeline as any).governance_enabled ? (
                    <span className="px-2 py-0.5 rounded-full bg-sky-500/10 text-sky-700 dark:text-sky-200 border border-sky-500/20">
                      Governance
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 rounded-full bg-muted text-muted-foreground border border-border/60">
                      Governance Off
                    </span>
                  )}
                  {(selectedDataset.pipeline as any).chunk_vector_enabled ? (
                    <span className="px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20">
                      Vector
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 rounded-full bg-muted text-muted-foreground border border-border/60">
                      Vector Off
                    </span>
                  )}
                  {(selectedDataset.pipeline as any).bm25_index_enabled ? (
                    <span className="px-2 py-0.5 rounded-full bg-primary/10 text-primary border border-primary/20">
                      BM25
                    </span>
                  ) : (
                    <span className="px-2 py-0.5 rounded-full bg-muted text-muted-foreground border border-border/60">
                      BM25 Off
                    </span>
                  )}
                  {(selectedDataset.pipeline as any).kg_enabled ? (
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
                } catch (err: any) {
                  setIngestionError((err?.message as string) || '入库策略预览失败')
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
              <div className="rounded-xl border border-border/60 bg-card/70 p-3 space-y-2">
                <div className="flex items-center justify-between gap-2">
                  <div className="text-[10px] text-muted-foreground">命中规则</div>
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
          </div>
          <div className="space-y-2">
            <label className="text-xs font-medium text-muted-foreground">解析器</label>
            <ParserDropdown value={parserBackend} onChange={setParserBackend} />
            {parserAvailable === false && (
              <div className="text-[10px] text-warning bg-warning/10 border border-warning/25 rounded-lg px-2 py-1">
                当前解析器不可用，建议切换为 {capabilities?.default_parser_backend || 'auto'}。
              </div>
            )}
          </div>

          {/* 策略选择 */}
          <div className="space-y-2">
            <label className="text-xs font-medium text-muted-foreground">切块策略</label>
            <ChunkStrategyDropdown value={chunkStrategy} onChange={(value) => updateSettings({ strategy: value })} />
            <p className="text-[10px] text-muted-foreground leading-relaxed mt-1.5">{chunkStrategyOption.description}</p>
          </div>

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
                    className="h-7 w-24 text-[11px] font-mono bg-card/80"
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
                    className="h-7 w-24 text-[11px] font-mono bg-card/80"
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
            <label className="text-xs font-medium text-muted-foreground">入库管线</label>
            <PipelineOptionsPanel compact />
          </div>

          <div className="grid grid-cols-2 gap-2">
            <Button
              onClick={() => runPreview()}
              disabled={isLoading}
              className="h-11 rounded-xl shadow-glow border border-primary/20"
            >
              {isLoading ? (
                <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none mr-2" />
              ) : (
                <Sparkles className="w-4 h-4 mr-2" />
              )}
              {isLoading ? '生成中...' : '生成预览'}
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
              {isLoading ? '取消' : cacheHit ? '忽略缓存' : '强制刷新'}
            </Button>
          </div>
        </div>

        {/* 统计指标 */}
        {previewData && (
          <div className="mt-8 pt-8 border-t border-border/60">
            <div className="flex items-center justify-between mb-4">
              <div className="flex items-center gap-2">
                <BarChart3 className="w-4 h-4 text-primary" />
                <h2 className="text-xs font-bold text-foreground uppercase tracking-wider">分析结果</h2>
              </div>
              <Button
                type="button"
                variant="ghost"
                size="sm"
                className="h-7 px-2 text-[11px]"
                onClick={() => setShowAdvancedStats((v) => !v)}
              >
                {showAdvancedStats ? '收起' : '更多'}
              </Button>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <div className="bg-card p-3 rounded-xl border border-border/60 shadow-sm">
                <div className="text-[10px] text-muted-foreground uppercase tracking-wider font-medium">切片数量</div>
                <div className="text-xl font-bold text-foreground mt-1">{previewData.total_chunks}</div>
              </div>
              <div className="bg-card p-3 rounded-xl border border-border/60 shadow-sm">
                <div className="text-[10px] text-muted-foreground uppercase tracking-wider font-medium">平均长度</div>
                <div className="text-xl font-bold text-foreground mt-1">{chunkStats?.avg ?? '-'}</div>
              </div>
              <div className="bg-card p-3 rounded-xl border border-border/60 shadow-sm">
                <div className="text-[10px] text-muted-foreground uppercase tracking-wider font-medium">中位数</div>
                <div className="text-xl font-bold text-foreground mt-1">{chunkStats?.median ?? '-'}</div>
              </div>
              <div className="bg-card p-3 rounded-xl border border-border/60 shadow-sm">
                <div className="text-[10px] text-muted-foreground uppercase tracking-wider font-medium">P90</div>
                <div className="text-xl font-bold text-foreground mt-1">{chunkStats?.p90 ?? '-'}</div>
              </div>
            </div>

            {showAdvancedStats && chunkStats ? (
              <div className="mt-3 grid grid-cols-2 gap-3">
                <div className="bg-card p-3 rounded-xl border border-border/60 shadow-sm">
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wider font-medium">最短 / 最长</div>
                  <div className="mt-1 text-sm font-mono text-foreground/90">
                    {chunkStats.min} / {chunkStats.max}
                  </div>
                  <div className="mt-1 text-[10px] text-muted-foreground font-mono">P10: {chunkStats.p10}</div>
                </div>
                <div className="bg-card p-3 rounded-xl border border-border/60 shadow-sm">
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wider font-medium">质量信号</div>
                  <div className="mt-1 text-[11px] text-muted-foreground">
                    <span className="font-mono text-foreground/90">{chunkStats.shortCount}</span> 个短切片 ·{' '}
                    <span className="font-mono text-foreground/90">{chunkStats.duplicateCount}</span> 个重复（估算）
                  </div>
                  {overlapGuidance ? (
                    <div className={cn('mt-1 text-[10px]', overlapGuidance.outOfRange ? 'text-warning' : 'text-muted-foreground')}>
                      overlap {Math.round(overlapGuidance.ratio * 100)}%（建议 10-25%）
                    </div>
                  ) : null}
                </div>
                <div className="col-span-2 bg-card p-3 rounded-xl border border-border/60 shadow-sm">
                  <div className="text-[10px] text-muted-foreground uppercase tracking-wider font-medium">长度分布</div>
                  <div className="mt-2 flex items-end gap-1 h-12">
                    {chunkStats.histogram.map((bin) => {
                      const ratio = chunkStats.count ? bin.count / chunkStats.count : 0
                      const h = Math.max(6, Math.round(ratio * 48))
                      return (
                        <div
                          key={`${bin.from}-${bin.to}`}
                          className="flex-1 rounded-sm bg-primary/20 hover:bg-primary/30 transition-colors"
                          style={{ height: `${h}px` }}
                          title={`${bin.from}-${bin.to}: ${bin.count}`}
                        />
                      )
                    })}
                  </div>
                  <div className="mt-2 flex items-center justify-between text-[10px] text-muted-foreground font-mono">
                    <span>0</span>
                    <span>{chunkStats.max}</span>
                  </div>
                </div>
              </div>
            ) : null}
          </div>
        )}

        {runHistory.length > 0 && (
          <div className="mt-8 pt-8 border-t border-border/60">
            <div className="flex items-center gap-2 mb-4">
              <Sparkles className="w-4 h-4 text-primary" />
              <h2 className="text-xs font-bold text-foreground uppercase tracking-wider">最近预览</h2>
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
    </aside>
  )
}
