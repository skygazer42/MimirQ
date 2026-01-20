/**
 * Sidebar - 左侧配置栏
 */
'use client'

import { useMemo, useState } from 'react'
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
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { cn } from '@/lib/utils'
import { useChunkPreview } from '@/components/chunk-preview/context'
import { ChunkStrategyDropdown } from '@/components/ui/chunk-strategy-dropdown'
import { ParserDropdown } from '@/components/ui/parser-dropdown'
import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { getChunkStrategyOption, getChunkStrategyLabel } from '@/lib/chunk-strategies'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'
import { UPLOAD_ACCEPT } from '@/lib/upload-extensions'

export function Sidebar() {
  const {
    fileList,
    currentFileIndex,
    currentFile,
    previewData,
    isLoading,
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
    updateSettings,
    runPreview,
    setParserBackend,
    toggleAutoPreview,
  } = useChunkPreview()
  const { capabilities, parserBackendAvailable } = usePipelineCapabilities()

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

  const sortedFileList = [...fileList].sort(
    (a, b) => (b.addedAt || 0) - (a.addedAt || 0)
  )

  const currentFileId = fileList[currentFileIndex]?.id
  const parserAvailable = parserBackendAvailable(parserBackend)

  const chunkStats = useMemo(() => {
    if (!previewData?.chunks || previewData.chunks.length === 0) return null
    const lengths = previewData.chunks.map((c: { content?: string | null }) => (c.content || '').length)
    const total = lengths.reduce((sum: number, n: number) => sum + n, 0)
    return {
      avg: Math.round(total / lengths.length),
      min: Math.min(...lengths),
      max: Math.max(...lengths),
    }
  }, [previewData])

  function formatFileSize(bytes: number) {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  return (
    <aside className="w-80 bg-card/80 border-r border-border/60 flex flex-col flex-shrink-0 z-10 backdrop-blur shadow-[inset_-1px_0_0_rgba(255,255,255,0.35)] dark:shadow-[inset_-1px_0_0_rgba(15,23,42,0.4)]">
      <div className="p-6 flex-1 overflow-y-auto">
        {/* 文件列表 */}
        <div className="mb-8 pb-8 border-b border-border/60">
          <div className="flex items-center justify-between mb-4">
            <div className="flex items-center gap-2">
              <Folder className="w-4 h-4 text-sky-600 dark:text-sky-300" />
              <h2 className="text-xs font-bold text-foreground uppercase tracking-wider">文件列表 ({fileList.length})</h2>
            </div>
            <Button
              variant="ghost"
              size="sm"
              onClick={() => document.getElementById('add-file-input')?.click()}
              className="h-6 w-6 p-0 hover:bg-sky-500/10 dark:hover:bg-sky-500/20"
            >
              <Upload className="w-3.5 h-3.5 text-sky-600 dark:text-sky-300" />
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

          <div className="space-y-2 max-h-[200px] overflow-y-auto custom-scrollbar pr-1 rounded-xl border border-border/60 bg-card/80 p-2 shadow-sm backdrop-blur">
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
                    ? 'bg-card border-sky-300/40 dark:border-sky-500/40 shadow-sm ring-1 ring-sky-500/20'
                    : 'bg-transparent border-transparent hover:bg-sky-500/10 dark:hover:bg-sky-500/20 hover:border-sky-300/40 dark:hover:border-sky-500/40'
                )}
              >
                <div className="flex items-center gap-2 min-w-0 flex-1">
                  <FileIcon
                    className={cn('w-3.5 h-3.5 flex-shrink-0', isActive ? 'text-sky-600 dark:text-sky-300' : 'text-muted-foreground')}
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
                    <span className="text-[10px] font-mono px-1.5 py-0.5 rounded bg-sky-500/20 dark:bg-sky-500/30 text-sky-600 dark:text-sky-300">
                      {String(f.originalFileType).toUpperCase()}
                    </span>
                  )}
                  {processedStatus[f.id] === 'success' && <Check className="w-3.5 h-3.5 text-green-500 dark:text-green-300" />}
                  {processedStatus[f.id] === 'error' && <AlertCircle className="w-3.5 h-3.5 text-red-500 dark:text-red-300" />}

                  <div
                    onClick={(e) => {
                      e.stopPropagation()
                      removeFile(fileIndex)
                    }}
                    className="opacity-0 group-hover:opacity-100 p-1 hover:bg-red-500/10 hover:text-red-600 dark:hover:text-red-300 rounded transition-all"
                  >
                    <Trash2 className="w-3 h-3" />
                  </div>
                </div>
              </div>
              )
            })}
          </div>
        </div>

        <div className="flex items-center gap-2 mb-6">
          <Settings className="w-4 h-4 text-sky-600 dark:text-sky-300" />
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
                className="h-3.5 w-3.5 rounded border-sky-300/40 dark:border-sky-500/40 text-sky-600 dark:text-sky-300 focus:ring-sky-500/20"
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
            <label className="text-xs font-medium text-muted-foreground">解析器</label>
            <ParserDropdown value={parserBackend} onChange={setParserBackend} />
            {parserAvailable === false && (
              <div className="text-[10px] text-sky-600 dark:text-sky-300 bg-sky-500/10 dark:bg-sky-500/20 border border-sky-500/30 rounded-lg px-2 py-1">
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
              <div className="flex justify-between items-center">
                <label className="text-xs font-medium text-muted-foreground">{isTokenStrategy ? 'Token 上限' : '块大小 (Chars)'}</label>
                <span className="text-xs font-mono font-medium text-sky-600 dark:text-sky-300 bg-sky-500/10 dark:bg-sky-500/20 px-2 py-0.5 rounded">{chunkSize}</span>
              </div>
              <input
                type="range"
                min={isTokenStrategy ? 50 : 100}
                max={isTokenStrategy ? 2000 : 4000}
                step={isTokenStrategy ? 50 : 100}
                value={chunkSize}
                onChange={(e) => updateSettings({ chunkSize: Number(e.target.value) })}
                className="w-full h-1.5 bg-sky-500/20 dark:bg-sky-500/30 rounded-full appearance-none cursor-pointer accent-sky-500 hover:accent-sky-600 transition-colors"
              />
              <div className="flex justify-between text-[10px] text-muted-foreground font-mono">
                <span>{isTokenStrategy ? 50 : 100}</span>
                <span>{isTokenStrategy ? 2000 : 4000}</span>
              </div>
            </div>
          )}

          {showOverlapControl && (
            <div className="space-y-4">
              <div className="flex justify-between items-center">
                <label className="text-xs font-medium text-muted-foreground">{isTokenStrategy ? 'Token 重叠' : '重叠 (Chars)'}</label>
                <span className="text-xs font-mono font-medium text-sky-600 dark:text-sky-300 bg-sky-500/10 dark:bg-sky-500/20 px-2 py-0.5 rounded">{chunkOverlap}</span>
              </div>
              <input
                type="range"
                min={0}
                max={Math.min(isTokenStrategy ? 500 : 1000, chunkSize - (isTokenStrategy ? 50 : 100))}
                step={isTokenStrategy ? 25 : 50}
                value={chunkOverlap}
                onChange={(e) => updateSettings({ chunkOverlap: Number(e.target.value) })}
                className="w-full h-1.5 bg-sky-500/20 dark:bg-sky-500/30 rounded-full appearance-none cursor-pointer accent-sky-500 hover:accent-sky-600 transition-colors"
              />
            </div>
          )}

          <div className="space-y-2">
            <label className="text-xs font-medium text-muted-foreground">入库管线</label>
            <PipelineOptionsPanel compact />
          </div>

          <Button
            onClick={() => runPreview()}
            disabled={isLoading}
            className="w-full bg-gradient-to-r from-sky-500 to-blue-600 hover:from-sky-600 hover:to-blue-700 text-white h-11 rounded-xl shadow-md shadow-sky-500/20 dark:shadow-sky-500/10 transition-all hover:scale-[1.02] active:scale-[0.98] border border-transparent"
          >
            {isLoading ? (
              <Loader2 className="w-4 h-4 animate-spin mr-2" />
            ) : (
              <Sparkles className="w-4 h-4 mr-2" />
            )}
            {isLoading ? '正在智能切分...' : '生成切片预览'}
          </Button>
        </div>

        {/* 统计指标 */}
        {previewData && (
          <div className="mt-8 pt-8 border-t border-border/60">
            <div className="flex items-center gap-2 mb-4">
              <BarChart3 className="w-4 h-4 text-sky-600 dark:text-sky-300" />
              <h2 className="text-xs font-bold text-foreground uppercase tracking-wider">分析结果</h2>
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
                <div className="text-[10px] text-muted-foreground uppercase tracking-wider font-medium">最长片段</div>
                <div className="text-xl font-bold text-foreground mt-1">{chunkStats?.max ?? '-'}</div>
              </div>
              <div className="bg-card p-3 rounded-xl border border-border/60 shadow-sm">
                <div className="text-[10px] text-muted-foreground uppercase tracking-wider font-medium">最短片段</div>
                <div className="text-xl font-bold text-foreground mt-1">{chunkStats?.min ?? '-'}</div>
              </div>
            </div>
          </div>
        )}

        {runHistory.length > 0 && (
          <div className="mt-8 pt-8 border-t border-border/60">
            <div className="flex items-center gap-2 mb-4">
              <Sparkles className="w-4 h-4 text-sky-600 dark:text-sky-300" />
              <h2 className="text-xs font-bold text-foreground uppercase tracking-wider">最近预览</h2>
            </div>
            <div className="space-y-2 max-h-[180px] overflow-y-auto custom-scrollbar pr-1">
              {runHistory.map((item) => (
                <div
                  key={item.id}
                  className="bg-card border border-border/60 rounded-xl px-3 py-2 text-[10px] text-muted-foreground shadow-sm"
                >
                  <div className="flex items-center justify-between">
                    <span className="font-medium text-foreground/80 truncate">{item.fileName}</span>
                    <span>{new Date(item.createdAt).toLocaleString([], { month: '2-digit', day: '2-digit', hour: '2-digit', minute: '2-digit' })}</span>
                  </div>
                  <div className="mt-1 flex flex-wrap gap-2">
                    <span className="px-2 py-0.5 rounded-full bg-sky-500/20 dark:bg-sky-500/30">Chunks: {item.totalChunks}</span>
                    <span className="px-2 py-0.5 rounded-full bg-sky-500/20 dark:bg-sky-500/30">耗时: {item.durationMs}ms</span>
                    <span className="px-2 py-0.5 rounded-full bg-sky-500/20 dark:bg-sky-500/30">{item.strategy}</span>
                    {item.cacheHit && (
                      <span className="px-2 py-0.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-100">缓存</span>
                    )}
                  </div>
                </div>
              ))}
            </div>
          </div>
        )}
      </div>
    </aside>
  )
}
