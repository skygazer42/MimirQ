/**
 * 知识加工工作台 - 切块预览组件
 * 大厂风格设计：沉浸式、可视化、编辑器级体验
 */
'use client'

import { useState, useCallback, useMemo } from 'react'
import {
  Upload,
  FileText,
  Layers,
  ArrowRight,
  Save,
  Eye,
  Settings,
  Loader2,
  RotateCcw,
  X,
  Check,
  AlertCircle,
  Sparkles,
  Zap,
  BarChart3,
  MousePointer2
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { documentApi } from '@/lib/api-client'
import type { ChunkPreviewResponse, ChunkPreviewItem } from '@/types'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { getParserLabel } from '@/lib/parser-options'
import { getChunkStrategyLabel, getChunkStrategyOption } from '@/lib/chunk-strategies'
import { ChunkStrategyDropdown } from '@/components/ui/chunk-strategy-dropdown'
import { cn } from '@/lib/utils'

// 分隔符配置
const SEPARATORS = ['\\n\\n', '\\n', '。', '！', '？', '.', '!', '?']

interface ChunkPreviewProps {
  onConfirm?: (params: { chunk_size: number; chunk_overlap: number }) => void
  onClose?: () => void
}

export function ChunkPreview({ onConfirm, onClose }: ChunkPreviewProps) {
  // 文件状态
  const [file, setFile] = useState<File | null>(null)
  const [isDragging, setIsDragging] = useState(false)

  // 参数状态
  const [chunkSize, setChunkSize] = useState(1000)
  const [chunkOverlap, setChunkOverlap] = useState(200)

  // 预览结果
  const [previewData, setPreviewData] = useState<ChunkPreviewResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitSuccess, setSubmitSuccess] = useState(false)

  // 选中的块索引（用于高亮联动）
  const [hoveredChunkIndex, setHoveredChunkIndex] = useState<number | null>(null)
  const { parserBackend } = useParserBackendPreference()
  const { chunkStrategy, setChunkStrategy } = useChunkStrategyPreference()
  const chunkStrategyOption = getChunkStrategyOption(chunkStrategy)
  const resolvedChunkStrategy = previewData?.chunk_strategy || chunkStrategy
  const resolvedChunkLabel = getChunkStrategyLabel(resolvedChunkStrategy)
  
  const strategyForUi = resolvedChunkStrategy
  const isTokenStrategy = strategyForUi === 'langchain_token'
  const isSentenceStrategy = strategyForUi === 'llama_index'
  const isHierarchicalStrategy = strategyForUi === 'llama_index_hierarchical'
  const isRagflowStrategy = strategyForUi.startsWith('ragflow_')

  // UI 参数显示控制
  const hideChunkSizeControl = isSentenceStrategy || isRagflowStrategy
  // 分层切块也不显示普通的 overlap，因为它依赖层级定义
  const showOverlapControl = !isSentenceStrategy && !isRagflowStrategy && !isHierarchicalStrategy && strategyForUi !== 'separator'

  // 处理文件拖放
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const droppedFile = e.dataTransfer.files[0]
    if (droppedFile) {
      setFile(droppedFile)
      setPreviewData(null)
      setError(null)
      setSubmitSuccess(false)
    }
  }, [])

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0]
    if (selectedFile) {
      setFile(selectedFile)
      setPreviewData(null)
      setError(null)
      setSubmitSuccess(false)
    }
  }, [])

  // 执行预览
  const handlePreview = useCallback(async () => {
    if (!file) return

    setIsLoading(true)
    setError(null)

    try {
      const data = await documentApi.chunkPreview(file, {
        chunk_size: chunkSize,
        chunk_overlap: chunkOverlap,
        parser_backend: parserBackend,
        chunk_strategy: chunkStrategy,
      })
      setPreviewData(data)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || '预览失败')
    } finally {
      setIsLoading(false)
    }
  }, [file, chunkSize, chunkOverlap, parserBackend, chunkStrategy])

  // 确认入库
  const handleSubmit = useCallback(async () => {
    if (!previewData || !file) return

    setIsSubmitting(true)
    setError(null)

    try {
      const chunks = previewData.chunks.map((chunk) => ({
        content: chunk.content,
        page_number: chunk.page_number,
        start_char: chunk.start_index,
        end_char: chunk.end_index,
        metadata: chunk.metadata,
      }))

      await documentApi.createFromChunks({
        filename: previewData.filename,
        file_type: previewData.file_type,
        file_size: previewData.file_size,
        chunks,
        metadata: {
          chunk_size: chunkSize,
          chunk_overlap: chunkOverlap,
          chunk_strategy: previewData.chunk_strategy,
          chunk_strategy_label: getChunkStrategyLabel(previewData.chunk_strategy),
          parser_backend: previewData.parser_backend,
        },
      })

      setSubmitSuccess(true)
      onConfirm?.({ chunk_size: chunkSize, chunk_overlap: chunkOverlap })
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || '入库失败')
    } finally {
      setIsSubmitting(false)
    }
  }, [previewData, file, chunkSize, chunkOverlap, onConfirm])

  // 重置
  const handleReset = useCallback(() => {
    setFile(null)
    setPreviewData(null)
    setError(null)
    setSubmitSuccess(false)
    setChunkSize(1000)
    setChunkOverlap(200)
  }, [])

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  const getHighlightedText = useMemo(() => {
    if (!previewData?.original_text || hoveredChunkIndex === null) return null

    const chunk = previewData.chunks[hoveredChunkIndex]
    if (!chunk) return null

    const text = previewData.original_text
    return {
      before: text.slice(0, chunk.start_index),
      highlighted: text.slice(chunk.start_index, chunk.end_index),
      after: text.slice(chunk.end_index),
    }
  }, [previewData, hoveredChunkIndex])

  // 空状态：文件上传
  if (!file) {
    return (
      <div className="flex items-center justify-center h-full bg-gray-50/50 p-8 animate-in fade-in duration-500">
        <div
          className={cn(
            "max-w-xl w-full p-16 border border-dashed rounded-3xl text-center transition-all duration-300 cursor-pointer group",
            isDragging 
              ? "border-blue-500 bg-blue-50/50 scale-[1.02] shadow-xl" 
              : "border-gray-200 bg-white hover:border-blue-400 hover:shadow-lg hover:-translate-y-1"
          )}
          onDragOver={handleDragOver}
          onDragLeave={handleDragLeave}
          onDrop={handleDrop}
          onClick={() => document.getElementById('chunk-file-input')?.click()}
        >
          <input
            id="chunk-file-input"
            type="file"
            accept=".pdf,.txt,.md"
            className="hidden"
            onChange={handleFileSelect}
          />
          <div className="w-20 h-20 mx-auto mb-8 bg-blue-50 rounded-2xl flex items-center justify-center group-hover:scale-110 transition-transform duration-300">
            <Upload className="w-10 h-10 text-blue-600" />
          </div>
          <h3 className="text-2xl font-bold text-gray-900 mb-3 tracking-tight">上传文档开始加工</h3>
          <p className="text-gray-500 mb-8 text-lg font-light">拖放文件到此处，或点击选择</p>
          <div className="flex items-center justify-center gap-3 text-xs font-medium text-gray-400 uppercase tracking-wider">
            <span className="px-3 py-1 bg-gray-100 rounded-full">PDF</span>
            <span className="px-3 py-1 bg-gray-100 rounded-full">TXT</span>
            <span className="px-3 py-1 bg-gray-100 rounded-full">Markdown</span>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-white text-gray-900 font-sans">
      {/* 顶部栏 */}
      <header className="flex-shrink-0 h-16 border-b border-gray-100 flex justify-between items-center px-6 bg-white z-20 shadow-sm relative">
        <div className="flex items-center gap-4">
          <div className="w-8 h-8 bg-blue-600 rounded-lg flex items-center justify-center shadow-blue-200 shadow-md">
            <Layers className="text-white w-5 h-5" />
          </div>
          <div>
            <h1 className="text-sm font-bold text-gray-900 tracking-tight">切片预览工作台</h1>
            <p className="text-[10px] text-gray-400 font-mono mt-0.5 flex items-center gap-2">
              <span>{file.name}</span>
              <span className="w-1 h-1 rounded-full bg-gray-300"/>
              <span>{formatFileSize(file.size)}</span>
              {previewData && (
                <>
                   <span className="w-1 h-1 rounded-full bg-gray-300"/>
                   <span className="text-blue-600 font-semibold">{previewData.total_chunks} Chunks</span>
                </>
              )}
            </p>
          </div>
        </div>
        
        <div className="flex items-center gap-3">
          {submitSuccess && (
            <div className="flex items-center gap-1.5 text-green-600 text-xs font-medium bg-green-50 px-3 py-1.5 rounded-full border border-green-100 animate-in fade-in slide-in-from-right-4">
              <Check className="w-3.5 h-3.5" />
              已成功入库
            </div>
          )}

          {error && (
            <div className="flex items-center gap-1.5 text-red-600 text-xs bg-red-50 px-3 py-1.5 rounded-full border border-red-100 max-w-[300px] truncate">
              <AlertCircle className="w-3.5 h-3.5" />
              {error}
            </div>
          )}

          <div className="h-6 w-px bg-gray-200 mx-2" />

          <Button variant="ghost" size="sm" onClick={handleReset} className="text-gray-500 hover:text-gray-900 h-8 text-xs font-medium">
            <RotateCcw className="w-3.5 h-3.5 mr-1.5" />
            重置
          </Button>

          {onClose && (
            <Button variant="ghost" size="sm" onClick={onClose} className="text-gray-500 hover:text-gray-900 h-8 w-8 p-0 rounded-full">
              <X className="w-4 h-4" />
            </Button>
          )}

          <Button
            onClick={handleSubmit}
            disabled={!previewData || isSubmitting || submitSuccess}
            className={cn(
              "h-9 px-5 text-xs font-semibold rounded-lg shadow-lg transition-all",
              submitSuccess ? "bg-green-600 hover:bg-green-700 shadow-green-200" : "bg-blue-600 hover:bg-blue-700 shadow-blue-200"
            )}
          >
            {isSubmitting ? (
              <Loader2 className="w-3.5 h-3.5 animate-spin mr-2" />
            ) : submitSuccess ? (
              <Check className="w-3.5 h-3.5 mr-2" />
            ) : (
              <Save className="w-3.5 h-3.5 mr-2" />
            )}
            {submitSuccess ? '已完成' : '确认入库'}
          </Button>
        </div>
      </header>

      <div className="flex flex-1 overflow-hidden">
        {/* 左侧配置栏 */}
        <aside className="w-80 bg-gray-50/50 border-r border-gray-200 flex flex-col flex-shrink-0 z-10">
          <div className="p-6 flex-1 overflow-y-auto">
            <div className="flex items-center gap-2 mb-6">
               <Settings className="w-4 h-4 text-gray-500" />
               <h2 className="text-xs font-bold text-gray-900 uppercase tracking-wider">配置参数</h2>
            </div>

            <div className="space-y-8">
              {/* 策略选择 */}
              <div className="space-y-2">
                <label className="text-xs font-medium text-gray-500">切块策略</label>
                <ChunkStrategyDropdown
                  value={chunkStrategy}
                  onChange={setChunkStrategy}
                />
                <p className="text-[10px] text-gray-400 leading-relaxed mt-1.5">
                  {chunkStrategyOption.description}
                </p>
              </div>

              {/* Slider Controls */}
              {!hideChunkSizeControl && (
                <div className="space-y-4">
                  <div className="flex justify-between items-center">
                    <label className="text-xs font-medium text-gray-600">
                      {isTokenStrategy ? 'Token 上限' : '块大小 (Chars)'}
                    </label>
                    <span className="text-xs font-mono font-medium text-blue-600 bg-blue-50 px-2 py-0.5 rounded">
                      {chunkSize}
                    </span>
                  </div>
                  <input
                    type="range"
                    min={isTokenStrategy ? 50 : 100}
                    max={isTokenStrategy ? 2000 : 4000}
                    step={isTokenStrategy ? 50 : 100}
                    value={chunkSize}
                    onChange={(e) => setChunkSize(Number(e.target.value))}
                    className="w-full h-1.5 bg-gray-200 rounded-full appearance-none cursor-pointer accent-blue-600 hover:accent-blue-700 transition-colors"
                  />
                  <div className="flex justify-between text-[10px] text-gray-400 font-mono">
                    <span>{isTokenStrategy ? 50 : 100}</span>
                    <span>{isTokenStrategy ? 2000 : 4000}</span>
                  </div>
                </div>
              )}

              {showOverlapControl && (
                <div className="space-y-4">
                   <div className="flex justify-between items-center">
                    <label className="text-xs font-medium text-gray-600">
                      {isTokenStrategy ? 'Token 重叠' : '重叠 (Chars)'}
                    </label>
                    <span className="text-xs font-mono font-medium text-blue-600 bg-blue-50 px-2 py-0.5 rounded">
                      {chunkOverlap}
                    </span>
                  </div>
                  <input
                    type="range"
                    min={0}
                    max={Math.min(isTokenStrategy ? 500 : 1000, chunkSize - (isTokenStrategy ? 50 : 100))}
                    step={isTokenStrategy ? 25 : 50}
                    value={chunkOverlap}
                    onChange={(e) => setChunkOverlap(Number(e.target.value))}
                    className="w-full h-1.5 bg-gray-200 rounded-full appearance-none cursor-pointer accent-blue-600 hover:accent-blue-700 transition-colors"
                  />
                </div>
              )}

              <Button
                onClick={handlePreview}
                disabled={isLoading}
                className="w-full bg-gradient-to-r from-indigo-600 to-blue-600 hover:from-indigo-700 hover:to-blue-700 text-white h-11 rounded-xl shadow-md shadow-blue-200/50 transition-all hover:scale-[1.02] active:scale-[0.98] border border-transparent"
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
              <div className="mt-8 pt-8 border-t border-gray-200">
                <div className="flex items-center gap-2 mb-4">
                  <BarChart3 className="w-4 h-4 text-gray-500" />
                  <h2 className="text-xs font-bold text-gray-900 uppercase tracking-wider">分析结果</h2>
                </div>
                
                <div className="grid grid-cols-2 gap-3">
                  <div className="bg-white p-3 rounded-xl border border-gray-100 shadow-sm">
                    <div className="text-[10px] text-gray-400 uppercase tracking-wider font-medium">切片数量</div>
                    <div className="text-xl font-bold text-gray-900 mt-1">{previewData.total_chunks}</div>
                  </div>
                  <div className="bg-white p-3 rounded-xl border border-gray-100 shadow-sm">
                     <div className="text-[10px] text-gray-400 uppercase tracking-wider font-medium">平均长度</div>
                     <div className="text-xl font-bold text-gray-900 mt-1">
                       {Math.round(previewData.total_characters / previewData.total_chunks)}
                     </div>
                  </div>
                </div>
              </div>
            )}
          </div>
        </aside>

        {/* 主区域：原文 vs 预览 */}
        <main className="flex-1 flex overflow-hidden bg-gray-100">
          {/* 左侧原文 */}
          <div className="flex-1 flex flex-col min-w-0 border-r border-gray-200 bg-white">
            <div className="h-10 border-b border-gray-100 bg-gray-50/50 flex items-center justify-between px-4 shrink-0">
               <span className="text-xs font-semibold text-gray-600 flex items-center gap-2">
                 <FileText className="w-3.5 h-3.5" />
                 解析原文
               </span>
               {previewData && (
                 <span className="text-[10px] font-mono text-gray-400">
                    {previewData.total_characters.toLocaleString()} chars
                 </span>
               )}
            </div>
            
            <div className="flex-1 overflow-y-auto p-6 scroll-smooth">
              {previewData?.original_text ? (
                <div className="font-mono text-sm leading-relaxed text-gray-600 whitespace-pre-wrap max-w-3xl mx-auto">
                  {hoveredChunkIndex !== null && getHighlightedText ? (
                    <>
                      <span className="opacity-40">{getHighlightedText.before}</span>
                      <mark className="bg-yellow-200 text-gray-900 rounded px-0.5 py-0.5 mx-0.5 shadow-sm font-medium">
                        {getHighlightedText.highlighted}
                      </mark>
                      <span className="opacity-40">{getHighlightedText.after}</span>
                    </>
                  ) : (
                    previewData.original_text
                  )}
                </div>
              ) : isLoading ? (
                 <div className="h-full flex flex-col items-center justify-center text-gray-400 gap-2">
                   <Loader2 className="w-8 h-8 animate-spin opacity-20" />
                   <p className="text-xs">解析中...</p>
                 </div>
              ) : (
                <div className="h-full flex flex-col items-center justify-center text-gray-300 gap-2">
                   <FileText className="w-12 h-12 opacity-10" />
                   <p className="text-xs">等待生成预览</p>
                </div>
              )}
            </div>
          </div>

          {/* 右侧切片 */}
          <div className="flex-1 flex flex-col min-w-0 bg-gray-50/30">
            <div className="h-10 border-b border-gray-200 bg-white flex items-center justify-between px-4 shrink-0">
               <span className="text-xs font-semibold text-blue-600 flex items-center gap-2">
                 <Layers className="w-3.5 h-3.5" />
                 切片结果
               </span>
               <div className="flex items-center gap-2 text-[10px] text-gray-400">
                  <MousePointer2 className="w-3 h-3" />
                  悬停卡片高亮原文
               </div>
            </div>

            <div className="flex-1 overflow-y-auto p-4 space-y-3 custom-scrollbar">
              {previewData?.chunks ? (
                previewData.chunks.map((chunk, idx) => (
                  <ChunkCard
                    key={idx}
                    chunk={chunk}
                    index={idx}
                    isHovered={hoveredChunkIndex === idx}
                    onMouseEnter={() => setHoveredChunkIndex(idx)}
                    onMouseLeave={() => setHoveredChunkIndex(null)}
                  />
                ))
              ) : isLoading ? (
                <div className="h-full flex flex-col items-center justify-center text-gray-400 gap-2">
                   <Loader2 className="w-8 h-8 animate-spin opacity-20" />
                   <p className="text-xs">切片中...</p>
                 </div>
              ) : (
                <div className="h-full flex flex-col items-center justify-center text-gray-300 gap-2">
                   <Layers className="w-12 h-12 opacity-10" />
                   <p className="text-xs">等待生成预览</p>
                </div>
              )}
            </div>
          </div>
        </main>
      </div>
    </div>
  )
}

// 切块卡片组件
function ChunkCard({
  chunk,
  index,
  isHovered,
  onMouseEnter,
  onMouseLeave,
}: {
  chunk: ChunkPreviewItem
  index: number
  isHovered: boolean
  onMouseEnter: () => void
  onMouseLeave: () => void
}) {
  return (
    <div
      className={cn(
        "group relative bg-white p-4 rounded-xl border transition-all duration-200 cursor-default",
        isHovered
          ? "border-blue-400 shadow-md ring-1 ring-blue-100 -translate-y-0.5 z-10"
          : "border-gray-200 hover:border-blue-300 hover:shadow-sm"
      )}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <div className="flex items-center justify-between mb-2">
        <div className="flex items-center gap-2">
           <span className={cn(
             "text-[10px] font-mono font-bold px-1.5 py-0.5 rounded",
             isHovered ? "bg-blue-100 text-blue-700" : "bg-gray-100 text-gray-500"
           )}>
             #{index + 1}
           </span>
           <span className="text-[10px] text-gray-400 font-mono">
             {chunk.length} chars
           </span>
        </div>
        {chunk.page_number && (
          <span className="text-[10px] text-gray-400 bg-gray-50 px-1.5 py-0.5 rounded">
            P.{chunk.page_number}
          </span>
        )}
      </div>

      <div className={cn(
        "text-sm font-mono leading-relaxed whitespace-pre-wrap break-all transition-colors",
        isHovered ? "text-gray-900" : "text-gray-600"
      )}>
        {chunk.content}
      </div>
    </div>
  )
}

export default ChunkPreview