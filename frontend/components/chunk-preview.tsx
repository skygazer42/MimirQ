/**
 * 切块预览组件
 * 用于预览文档切块效果，支持参数调整和可视化展示
 */
'use client'

import { useState, useCallback, useMemo } from 'react'
import { Upload, FileText, Settings2, Eye, Loader2, ChevronLeft, ChevronRight } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { documentApi } from '@/lib/api-client'
import type { ChunkPreviewResponse, ChunkPreviewItem } from '@/types'

// 交替颜色用于区分相邻块
const CHUNK_COLORS = [
  'bg-blue-50 border-blue-200 hover:bg-blue-100',
  'bg-amber-50 border-amber-200 hover:bg-amber-100',
  'bg-green-50 border-green-200 hover:bg-green-100',
  'bg-purple-50 border-purple-200 hover:bg-purple-100',
]

interface ChunkPreviewProps {
  onConfirm?: (params: { chunk_size: number; chunk_overlap: number }) => void
}

export function ChunkPreview({ onConfirm }: ChunkPreviewProps) {
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

  // 视图模式: 'cards' | 'highlight'
  const [viewMode, setViewMode] = useState<'cards' | 'highlight'>('cards')

  // 高亮模式下的当前选中块
  const [selectedChunkIndex, setSelectedChunkIndex] = useState<number | null>(null)

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
    }
  }, [])

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0]
    if (selectedFile) {
      setFile(selectedFile)
      setPreviewData(null)
      setError(null)
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
      })
      setPreviewData(data)
      setSelectedChunkIndex(null)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || '预览失败')
    } finally {
      setIsLoading(false)
    }
  }, [file, chunkSize, chunkOverlap])

  // 格式化文件大小
  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  // 高亮显示原文中的块位置
  const highlightedText = useMemo(() => {
    if (!previewData?.original_text || selectedChunkIndex === null) return null

    const chunk = previewData.chunks[selectedChunkIndex]
    if (!chunk) return null

    const text = previewData.original_text
    const before = text.slice(0, chunk.start_index)
    const highlighted = text.slice(chunk.start_index, chunk.end_index)
    const after = text.slice(chunk.end_index)

    return { before, highlighted, after }
  }, [previewData, selectedChunkIndex])

  return (
    <div className="flex flex-col h-full">
      {/* 顶部控制区 */}
      <div className="flex-shrink-0 p-4 border-b bg-gray-50">
        <div className="flex flex-wrap items-center gap-4">
          {/* 文件上传区 */}
          <div
            className={`
              relative flex-1 min-w-[200px] max-w-[300px] p-4 border-2 border-dashed rounded-lg
              transition-colors cursor-pointer
              ${isDragging ? 'border-blue-500 bg-blue-50' : 'border-gray-300 hover:border-gray-400'}
              ${file ? 'bg-green-50 border-green-300' : ''}
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
            <div className="flex items-center gap-3">
              {file ? (
                <>
                  <FileText className="w-8 h-8 text-green-600" />
                  <div className="flex-1 min-w-0">
                    <p className="text-sm font-medium text-gray-900 truncate">{file.name}</p>
                    <p className="text-xs text-gray-500">{formatFileSize(file.size)}</p>
                  </div>
                </>
              ) : (
                <>
                  <Upload className="w-8 h-8 text-gray-400" />
                  <div className="flex-1">
                    <p className="text-sm text-gray-600">拖放文件或点击上传</p>
                    <p className="text-xs text-gray-400">支持 PDF, TXT, MD</p>
                  </div>
                </>
              )}
            </div>
          </div>

          {/* 参数调节 */}
          <div className="flex items-center gap-6">
            <div className="flex flex-col gap-1">
              <label className="text-xs text-gray-500 flex items-center gap-1">
                <Settings2 className="w-3 h-3" />
                切块大小
              </label>
              <div className="flex items-center gap-2">
                <input
                  type="range"
                  min="100"
                  max="4000"
                  step="100"
                  value={chunkSize}
                  onChange={(e) => setChunkSize(Number(e.target.value))}
                  className="w-32 h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
                />
                <span className="text-sm font-mono w-16 text-right">{chunkSize}</span>
              </div>
            </div>

            <div className="flex flex-col gap-1">
              <label className="text-xs text-gray-500">重叠大小</label>
              <div className="flex items-center gap-2">
                <input
                  type="range"
                  min="0"
                  max={Math.min(1000, chunkSize - 100)}
                  step="50"
                  value={chunkOverlap}
                  onChange={(e) => setChunkOverlap(Number(e.target.value))}
                  className="w-32 h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer"
                />
                <span className="text-sm font-mono w-16 text-right">{chunkOverlap}</span>
              </div>
            </div>
          </div>

          {/* 操作按钮 */}
          <div className="flex items-center gap-2">
            <Button
              onClick={handlePreview}
              disabled={!file || isLoading}
              className="gap-2"
            >
              {isLoading ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Eye className="w-4 h-4" />
              )}
              生成预览
            </Button>

            {previewData && onConfirm && (
              <Button
                variant="outline"
                onClick={() => onConfirm({ chunk_size: chunkSize, chunk_overlap: chunkOverlap })}
              >
                采用此配置
              </Button>
            )}
          </div>
        </div>

        {/* 错误提示 */}
        {error && (
          <div className="mt-3 p-3 bg-red-50 border border-red-200 rounded-lg text-sm text-red-600">
            {error}
          </div>
        )}
      </div>

      {/* 预览结果区 */}
      {previewData && (
        <div className="flex-1 overflow-hidden flex flex-col">
          {/* 统计信息栏 */}
          <div className="flex-shrink-0 px-4 py-2 bg-white border-b flex items-center justify-between">
            <div className="flex items-center gap-4 text-sm text-gray-600">
              <span>文件: <strong>{previewData.filename}</strong></span>
              <span>总字符: <strong>{previewData.total_characters.toLocaleString()}</strong></span>
              <span>切块数: <strong className="text-blue-600">{previewData.total_chunks}</strong></span>
              <span>平均长度: <strong>{Math.round(previewData.total_characters / previewData.total_chunks)}</strong></span>
            </div>

            {/* 视图切换 */}
            {previewData.original_text && (
              <div className="flex items-center gap-1 p-1 bg-gray-100 rounded-lg">
                <button
                  className={`px-3 py-1 text-sm rounded ${viewMode === 'cards' ? 'bg-white shadow-sm' : 'text-gray-600'}`}
                  onClick={() => setViewMode('cards')}
                >
                  卡片视图
                </button>
                <button
                  className={`px-3 py-1 text-sm rounded ${viewMode === 'highlight' ? 'bg-white shadow-sm' : 'text-gray-600'}`}
                  onClick={() => setViewMode('highlight')}
                >
                  高亮视图
                </button>
              </div>
            )}
          </div>

          {/* 内容区 */}
          {viewMode === 'cards' ? (
            // 卡片视图
            <div className="flex-1 overflow-auto p-4">
              <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
                {previewData.chunks.map((chunk, idx) => (
                  <ChunkCard
                    key={idx}
                    chunk={chunk}
                    colorClass={CHUNK_COLORS[idx % CHUNK_COLORS.length]}
                    isSelected={selectedChunkIndex === idx}
                    onClick={() => setSelectedChunkIndex(idx === selectedChunkIndex ? null : idx)}
                  />
                ))}
              </div>
            </div>
          ) : (
            // 高亮视图
            <div className="flex-1 overflow-hidden flex">
              {/* 左侧：块列表 */}
              <div className="w-80 flex-shrink-0 border-r overflow-auto p-2">
                <div className="space-y-2">
                  {previewData.chunks.map((chunk, idx) => (
                    <button
                      key={idx}
                      className={`
                        w-full text-left p-3 rounded-lg border transition-all
                        ${selectedChunkIndex === idx
                          ? 'border-blue-500 bg-blue-50 ring-2 ring-blue-200'
                          : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                        }
                      `}
                      onClick={() => setSelectedChunkIndex(idx)}
                    >
                      <div className="flex items-center justify-between mb-1">
                        <span className="text-xs font-medium text-gray-500">块 #{idx + 1}</span>
                        <span className="text-xs text-gray-400">{chunk.length} 字符</span>
                      </div>
                      <p className="text-sm text-gray-700 line-clamp-2">{chunk.content}</p>
                    </button>
                  ))}
                </div>
              </div>

              {/* 右侧：原文高亮 */}
              <div className="flex-1 overflow-auto p-4 bg-white">
                {selectedChunkIndex !== null && highlightedText ? (
                  <div className="max-w-3xl mx-auto">
                    {/* 导航 */}
                    <div className="flex items-center justify-between mb-4 pb-2 border-b">
                      <span className="text-sm text-gray-600">
                        块 #{selectedChunkIndex + 1} / {previewData.chunks.length}
                        {previewData.chunks[selectedChunkIndex].page_number && (
                          <span className="ml-2 text-gray-400">
                            (第 {previewData.chunks[selectedChunkIndex].page_number} 页)
                          </span>
                        )}
                      </span>
                      <div className="flex items-center gap-1">
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={selectedChunkIndex === 0}
                          onClick={() => setSelectedChunkIndex(Math.max(0, selectedChunkIndex - 1))}
                        >
                          <ChevronLeft className="w-4 h-4" />
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          disabled={selectedChunkIndex === previewData.chunks.length - 1}
                          onClick={() => setSelectedChunkIndex(Math.min(previewData.chunks.length - 1, selectedChunkIndex + 1))}
                        >
                          <ChevronRight className="w-4 h-4" />
                        </Button>
                      </div>
                    </div>

                    {/* 高亮文本 */}
                    <div className="text-sm leading-relaxed whitespace-pre-wrap font-mono">
                      <span className="text-gray-400">{highlightedText.before}</span>
                      <mark className="bg-yellow-200 px-0.5 rounded">{highlightedText.highlighted}</mark>
                      <span className="text-gray-400">{highlightedText.after}</span>
                    </div>
                  </div>
                ) : (
                  <div className="flex items-center justify-center h-full text-gray-400">
                    点击左侧块查看在原文中的位置
                  </div>
                )}
              </div>
            </div>
          )}
        </div>
      )}

      {/* 空状态 */}
      {!previewData && !isLoading && (
        <div className="flex-1 flex items-center justify-center text-gray-400">
          <div className="text-center">
            <FileText className="w-16 h-16 mx-auto mb-4 opacity-50" />
            <p>上传文件并点击"生成预览"查看切块效果</p>
            <p className="text-sm mt-2">调整切块大小和重叠参数，找到最佳配置</p>
          </div>
        </div>
      )}
    </div>
  )
}

// 切块卡片组件
function ChunkCard({
  chunk,
  colorClass,
  isSelected,
  onClick,
}: {
  chunk: ChunkPreviewItem
  colorClass: string
  isSelected: boolean
  onClick: () => void
}) {
  return (
    <div
      className={`
        relative p-4 rounded-lg border transition-all cursor-pointer
        ${colorClass}
        ${isSelected ? 'ring-2 ring-blue-400 shadow-md' : ''}
      `}
      onClick={onClick}
    >
      {/* 头部信息 */}
      <div className="flex items-center justify-between mb-2">
        <span className="text-xs font-semibold text-gray-600">
          块 #{chunk.index + 1}
        </span>
        <div className="flex items-center gap-2 text-xs text-gray-500">
          {chunk.page_number && (
            <span className="px-1.5 py-0.5 bg-white/50 rounded">第 {chunk.page_number} 页</span>
          )}
          <span>{chunk.length} 字符</span>
        </div>
      </div>

      {/* 内容预览 */}
      <p className="text-sm text-gray-700 line-clamp-4 whitespace-pre-wrap">
        {chunk.content}
      </p>

      {/* 位置信息 */}
      <div className="mt-2 pt-2 border-t border-current/10 text-xs text-gray-400">
        位置: {chunk.start_index} - {chunk.end_index}
      </div>
    </div>
  )
}

export default ChunkPreview
