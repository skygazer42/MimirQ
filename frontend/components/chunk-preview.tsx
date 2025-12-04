/**
 * 知识加工工作台 - 切块预览组件
 * 现代化的可视化切块预览界面
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
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { documentApi } from '@/lib/api-client'
import type { ChunkPreviewResponse, ChunkPreviewItem } from '@/types'
import { ParserBackendSelect } from '@/components/parser-backend-select'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { getParserLabel } from '@/lib/parser-options'

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
      })
      setPreviewData(data)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || '预览失败')
    } finally {
      setIsLoading(false)
    }
  }, [file, chunkSize, chunkOverlap, parserBackend])

  // 确认入库
  const handleSubmit = useCallback(async () => {
    if (!previewData || !file) return

    setIsSubmitting(true)
    setError(null)

    try {
      // 将预览的切块转换为手动切块格式
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
          strategy: 'RecursiveCharacterTextSplitter',
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

  // 格式化文件大小
  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  // 计算高亮文本
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

  // 未上传文件的空状态
  if (!file) {
    return (
      <div className="flex items-center justify-center h-full bg-gray-50 p-8">
        <div
          className={`
            max-w-lg w-full p-12 border-2 border-dashed rounded-2xl text-center
            transition-all duration-200 cursor-pointer
            ${isDragging
              ? 'border-indigo-500 bg-indigo-50 scale-[1.02]'
              : 'border-gray-300 bg-white hover:border-indigo-400 hover:bg-indigo-50/50'
            }
          `}
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
          <div className="w-16 h-16 mx-auto mb-6 bg-indigo-100 rounded-2xl flex items-center justify-center">
            <Upload className="w-8 h-8 text-indigo-600" />
          </div>
          <h3 className="text-xl font-semibold text-gray-900 mb-2">上传文档开始加工</h3>
          <p className="text-gray-500 mb-4">拖放文件到此处，或点击选择</p>
          <div className="flex items-center justify-center gap-2 text-sm text-gray-400">
            <span className="px-2 py-1 bg-gray-100 rounded">PDF</span>
            <span className="px-2 py-1 bg-gray-100 rounded">TXT</span>
            <span className="px-2 py-1 bg-gray-100 rounded">Markdown</span>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex flex-col h-full bg-gray-50">
      {/* 顶部栏 */}
      <header className="flex-shrink-0 bg-white border-b px-6 py-4 flex justify-between items-center shadow-sm">
        <div className="flex items-center gap-3">
          <div className="bg-indigo-100 p-2.5 rounded-xl">
            <Layers className="text-indigo-600 w-5 h-5" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-gray-900">知识加工工作台</h1>
            <p className="text-xs text-gray-500">
              {file.name} · {formatFileSize(file.size)}
              {previewData && (
                <>
                  <span className="ml-2 text-indigo-600">
                    · 已生成 {previewData.total_chunks} 个切块
                  </span>
                  <span className="ml-2 text-gray-500">
                    · 使用 {getParserLabel(previewData.parser_backend)}
                  </span>
                </>
              )}
            </p>
          </div>
        </div>
        <div className="w-64">
          <ParserBackendSelect compact />
        </div>
        <div className="flex items-center gap-3">
          {submitSuccess && (
            <div className="flex items-center gap-2 text-green-600 text-sm bg-green-50 px-3 py-1.5 rounded-lg">
              <Check className="w-4 h-4" />
              入库成功
            </div>
          )}

          <Button variant="ghost" size="sm" onClick={handleReset} className="gap-2">
            <RotateCcw className="w-4 h-4" />
            重置
          </Button>

          {onClose && (
            <Button variant="ghost" size="sm" onClick={onClose}>
              <X className="w-4 h-4" />
            </Button>
          )}

          <Button
            onClick={handleSubmit}
            disabled={!previewData || isSubmitting || submitSuccess}
            className="gap-2 bg-indigo-600 hover:bg-indigo-700"
          >
            {isSubmitting ? (
              <Loader2 className="w-4 h-4 animate-spin" />
            ) : (
              <Save className="w-4 h-4" />
            )}
            {submitSuccess ? '已入库' : '确认并入库'}
          </Button>
        </div>
      </header>

      {/* 错误提示 */}
      {error && (
        <div className="mx-6 mt-4 p-3 bg-red-50 border border-red-200 rounded-lg flex items-center gap-2 text-sm text-red-600">
          <AlertCircle className="w-4 h-4 flex-shrink-0" />
          {error}
        </div>
      )}

      <div className="flex flex-1 overflow-hidden">
        {/* 左侧边栏: 参数配置 */}
        <aside className="w-80 bg-white border-r flex flex-col flex-shrink-0">
          <div className="p-5 border-b">
            <h2 className="text-sm font-bold text-gray-700 flex items-center gap-2 mb-5">
              <Settings className="w-4 h-4" />
              切块策略配置
            </h2>

            <div className="space-y-6">
              {/* Chunk Size */}
              <div>
                <div className="flex justify-between mb-2">
                  <label className="text-xs font-medium text-gray-600">Chunk Size (块大小)</label>
                  <span className="text-xs bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded font-mono">
                    {chunkSize}
                  </span>
                </div>
                <input
                  type="range"
                  min="100"
                  max="4000"
                  step="100"
                  value={chunkSize}
                  onChange={(e) => setChunkSize(Number(e.target.value))}
                  className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-indigo-600"
                />
                <div className="flex justify-between text-[10px] text-gray-400 mt-1">
                  <span>100</span>
                  <span>4000</span>
                </div>
                <p className="text-[10px] text-gray-400 mt-1">每个切片的最大字符数</p>
              </div>

              {/* Overlap */}
              <div>
                <div className="flex justify-between mb-2">
                  <label className="text-xs font-medium text-gray-600">Overlap (重叠)</label>
                  <span className="text-xs bg-indigo-50 text-indigo-700 px-2 py-0.5 rounded font-mono">
                    {chunkOverlap}
                  </span>
                </div>
                <input
                  type="range"
                  min="0"
                  max={Math.min(1000, chunkSize - 100)}
                  step="50"
                  value={chunkOverlap}
                  onChange={(e) => setChunkOverlap(Number(e.target.value))}
                  className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-indigo-600"
                />
                <div className="flex justify-between text-[10px] text-gray-400 mt-1">
                  <span>0</span>
                  <span>{Math.min(1000, chunkSize - 100)}</span>
                </div>
                <p className="text-[10px] text-gray-400 mt-1">相邻切片间的重叠字符</p>
              </div>

              {/* 分隔符 */}
              <div>
                <label className="text-xs font-medium text-gray-600 mb-2 block">分隔符优先级</label>
                <div className="flex flex-wrap gap-1.5">
                  {SEPARATORS.map((sep) => (
                    <span
                      key={sep}
                      className="px-2 py-1 bg-gray-100 text-gray-600 text-xs rounded border border-gray-200 font-mono"
                    >
                      {sep}
                    </span>
                  ))}
                </div>
                <p className="text-[10px] text-gray-400 mt-2">RecursiveCharacterTextSplitter 按优先级递归切分</p>
              </div>

              {/* 预览按钮 */}
              <Button
                onClick={handlePreview}
                disabled={isLoading}
                className="w-full gap-2"
                variant="outline"
              >
                {isLoading ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Eye className="w-4 h-4" />
                )}
                {isLoading ? '正在切块...' : '生成预览'}
              </Button>
            </div>
          </div>

          {/* 统计信息 */}
          <div className="p-5 bg-gray-50 flex-1">
            <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-3 flex items-center gap-2">
              <Sparkles className="w-3 h-3" />
              预览统计
            </h3>

            {previewData ? (
              <div className="grid grid-cols-2 gap-3">
                <div className="bg-white p-3 rounded-lg border shadow-sm">
                  <div className="text-2xl font-bold text-indigo-600">{previewData.total_chunks}</div>
                  <div className="text-[10px] text-gray-400">生成切片数</div>
                </div>
                <div className="bg-white p-3 rounded-lg border shadow-sm">
                  <div className="text-2xl font-bold text-green-600">
                    {Math.round(previewData.total_characters / previewData.total_chunks)}
                  </div>
                  <div className="text-[10px] text-gray-400">平均字符/块</div>
                </div>
                <div className="bg-white p-3 rounded-lg border shadow-sm">
                  <div className="text-2xl font-bold text-amber-600">
                    {previewData.total_characters.toLocaleString()}
                  </div>
                  <div className="text-[10px] text-gray-400">总字符数</div>
                </div>
                <div className="bg-white p-3 rounded-lg border shadow-sm">
                  <div className="text-2xl font-bold text-purple-600">
                    {Math.round((chunkOverlap / chunkSize) * 100)}%
                  </div>
                  <div className="text-[10px] text-gray-400">重叠率</div>
                </div>
              </div>
            ) : (
              <div className="text-center py-8 text-gray-400 text-sm">
                <Eye className="w-8 h-8 mx-auto mb-2 opacity-50" />
                点击"生成预览"查看统计
              </div>
            )}
          </div>
        </aside>

        {/* 主区域: 对比视图 */}
        <main className="flex-1 flex p-4 gap-4 overflow-hidden">
          {/* 左屏: 原文 */}
          <div className="flex-1 bg-white rounded-xl shadow-sm border flex flex-col overflow-hidden">
            <div className="px-4 py-3 border-b bg-gray-50 flex justify-between items-center flex-shrink-0">
              <span className="text-xs font-bold text-gray-600 flex items-center gap-2">
                <FileText className="w-3.5 h-3.5" />
                解析后文本
              </span>
              {previewData && (
                <span className="text-[10px] text-gray-400">
                  {previewData.total_characters.toLocaleString()} 字符
                </span>
              )}
            </div>

            <div className="flex-1 overflow-y-auto p-5">
              {previewData?.original_text ? (
                <div className="font-mono text-sm leading-relaxed text-gray-700 whitespace-pre-wrap">
                  {hoveredChunkIndex !== null && getHighlightedText ? (
                    <>
                      <span className="text-gray-400">{getHighlightedText.before}</span>
                      <mark className="bg-indigo-100 text-indigo-900 px-0.5 rounded">
                        {getHighlightedText.highlighted}
                      </mark>
                      <span className="text-gray-400">{getHighlightedText.after}</span>
                    </>
                  ) : (
                    previewData.original_text
                  )}
                </div>
              ) : isLoading ? (
                <div className="flex items-center justify-center h-full text-gray-400">
                  <Loader2 className="w-6 h-6 animate-spin" />
                </div>
              ) : (
                <div className="flex items-center justify-center h-full text-gray-400 text-sm">
                  点击"生成预览"查看解析结果
                </div>
              )}
            </div>
          </div>

          {/* 中间箭头 */}
          <div className="flex flex-col justify-center items-center text-gray-300 flex-shrink-0">
            <ArrowRight className="w-6 h-6" />
          </div>

          {/* 右屏: 切块预览 */}
          <div className="flex-1 bg-white rounded-xl shadow-sm border flex flex-col overflow-hidden">
            <div className="px-4 py-3 border-b bg-gray-50 flex justify-between items-center flex-shrink-0">
              <span className="text-xs font-bold text-indigo-600 flex items-center gap-2">
                <Layers className="w-3.5 h-3.5" />
                切块预览
              </span>
              {previewData && (
                <span className="text-[10px] text-indigo-500 bg-indigo-50 px-2 py-0.5 rounded">
                  共 {previewData.total_chunks} 块
                </span>
              )}
            </div>

            <div className="flex-1 overflow-y-auto p-4 bg-slate-50">
              {previewData?.chunks ? (
                <div className="space-y-3">
                  {previewData.chunks.map((chunk, idx) => (
                    <ChunkCard
                      key={idx}
                      chunk={chunk}
                      index={idx}
                      isHovered={hoveredChunkIndex === idx}
                      onMouseEnter={() => setHoveredChunkIndex(idx)}
                      onMouseLeave={() => setHoveredChunkIndex(null)}
                    />
                  ))}
                </div>
              ) : isLoading ? (
                <div className="flex items-center justify-center h-full text-gray-400">
                  <div className="text-center">
                    <Loader2 className="w-8 h-8 animate-spin mx-auto mb-3" />
                    <p className="text-sm">正在切块...</p>
                  </div>
                </div>
              ) : (
                <div className="flex items-center justify-center h-full text-gray-400 text-sm">
                  <div className="text-center">
                    <Layers className="w-10 h-10 mx-auto mb-3 opacity-50" />
                    <p>调整参数后点击"生成预览"</p>
                    <p className="text-xs mt-1 text-gray-300">鼠标悬停卡片可高亮原文位置</p>
                  </div>
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
      className={`
        group relative bg-white border p-4 rounded-lg shadow-sm
        transition-all duration-200 cursor-default
        ${isHovered
          ? 'border-indigo-400 shadow-md ring-2 ring-indigo-100 scale-[1.01]'
          : 'border-gray-200 hover:border-indigo-300 hover:shadow-md'
        }
      `}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      {/* 头部标签 */}
      <div className="flex items-center justify-between mb-2">
        <span
          className={`
            text-[10px] font-bold px-2 py-0.5 rounded
            ${isHovered ? 'bg-indigo-100 text-indigo-700' : 'bg-gray-100 text-gray-500'}
          `}
        >
          #{index + 1}
        </span>
        <div className="flex items-center gap-2 text-[10px] text-gray-400">
          {chunk.page_number && (
            <span className="bg-gray-100 px-1.5 py-0.5 rounded">P{chunk.page_number}</span>
          )}
          <span className="font-mono">{chunk.length} chars</span>
        </div>
      </div>

      {/* 内容 */}
      <p className="text-sm text-gray-700 leading-relaxed line-clamp-4">
        {chunk.content}
      </p>

      {/* 位置信息 */}
      <div className="mt-2 pt-2 border-t border-gray-100 text-[10px] text-gray-300 font-mono">
        [{chunk.start_index} - {chunk.end_index}]
      </div>
    </div>
  )
}

export default ChunkPreview
