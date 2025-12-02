'use client'

/**
 * 切块预览工作台
 * 从已解析的文件中选择，调试切块参数，实时高亮预览
 */
import { useState, useEffect, useMemo, useCallback, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  FileText,
  Loader2,
  CheckCircle,
  Layers,
  Settings2,
  Eye,
  Code,
  Save,
  Trash2,
  ChevronLeft,
  Sliders,
  Database,
  Sparkles,
  Clock,
  ArrowRight,
} from 'lucide-react'
import { Navbar } from '@/components/navbar'
import { Button } from '@/components/ui/button'
import { documentApi } from '@/lib/api-client'
import { formatFileSize, formatDate, cn } from '@/lib/utils'
import { useParsedFiles, type ParsedFileData } from '@/hooks/use-parsed-files'
import type { ChunkPreviewItem } from '@/types'

export default function ChunkPreviewPage() {
  // 共享存储
  const { files: parsedFiles, isLoaded, removeFile } = useParsedFiles()

  // 当前选中的文件
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null)
  const selectedFile = parsedFiles.find((f) => f.id === selectedFileId) || null

  // 切块参数
  const [chunkSize, setChunkSize] = useState(500)
  const [chunkOverlap, setChunkOverlap] = useState(100)

  // 切块结果
  const [chunks, setChunks] = useState<ChunkPreviewItem[]>([])
  const [isChunking, setIsChunking] = useState(false)

  // 高亮状态
  const [activeChunkIndex, setActiveChunkIndex] = useState<number | null>(null)

  // 预览模式
  const [previewMode, setPreviewMode] = useState<'rendered' | 'source'>('source')

  // 入库状态
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitSuccess, setSubmitSuccess] = useState(false)

  // 原文容器引用（用于滚动定位）
  const sourceContainerRef = useRef<HTMLDivElement>(null)

  // 自动选中第一个文件
  useEffect(() => {
    if (isLoaded && parsedFiles.length > 0 && !selectedFileId) {
      setSelectedFileId(parsedFiles[0].id)
    }
  }, [isLoaded, parsedFiles, selectedFileId])

  // 前端模拟切块（实际项目中应调用后端 API）
  const computeChunks = useCallback(() => {
    if (!selectedFile) return

    setIsChunking(true)

    // 模拟异步处理
    setTimeout(() => {
      const text = selectedFile.markdownContent
      const computedChunks: ChunkPreviewItem[] = []
      const step = Math.max(chunkSize - chunkOverlap, 1)

      let index = 0
      for (let i = 0; i < text.length; i += step) {
        const end = Math.min(i + chunkSize, text.length)
        const content = text.slice(i, end)

        computedChunks.push({
          index,
          content,
          length: content.length,
          start_index: i,
          end_index: end,
          metadata: {},
        })

        index++
        if (end >= text.length) break
      }

      setChunks(computedChunks)
      setIsChunking(false)
      setActiveChunkIndex(null)
    }, 300)
  }, [selectedFile, chunkSize, chunkOverlap])

  // 参数变化时重新计算
  useEffect(() => {
    if (selectedFile) {
      computeChunks()
    }
  }, [selectedFile, chunkSize, chunkOverlap, computeChunks])

  // 高亮渲染
  const highlightedContent = useMemo(() => {
    if (!selectedFile || activeChunkIndex === null || !chunks[activeChunkIndex]) {
      return null
    }

    const chunk = chunks[activeChunkIndex]
    const text = selectedFile.markdownContent

    return {
      before: text.slice(0, chunk.start_index),
      highlighted: text.slice(chunk.start_index, chunk.end_index),
      after: text.slice(chunk.end_index),
    }
  }, [selectedFile, activeChunkIndex, chunks])

  // 确认入库
  const handleSubmit = async () => {
    if (!selectedFile || chunks.length === 0) return

    setIsSubmitting(true)

    try {
      const chunkData = chunks.map((chunk) => ({
        content: chunk.content,
        page_number: chunk.page_number,
        start_char: chunk.start_index,
        end_char: chunk.end_index,
        metadata: chunk.metadata,
      }))

      await documentApi.createFromChunks({
        filename: selectedFile.filename,
        file_type: selectedFile.fileType,
        file_size: selectedFile.fileSize,
        chunks: chunkData,
        metadata: {
          chunk_size: chunkSize,
          chunk_overlap: chunkOverlap,
          parser: selectedFile.parser,
        },
      })

      setSubmitSuccess(true)
      setTimeout(() => setSubmitSuccess(false), 3000)
    } catch (err) {
      console.error('Submit failed:', err)
    } finally {
      setIsSubmitting(false)
    }
  }

  // 滚动到高亮位置
  useEffect(() => {
    if (activeChunkIndex !== null && sourceContainerRef.current) {
      const container = sourceContainerRef.current
      const highlightEl = container.querySelector('.chunk-highlight')
      if (highlightEl) {
        highlightEl.scrollIntoView({ behavior: 'smooth', block: 'center' })
      }
    }
  }, [activeChunkIndex])

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <Navbar />

      <main className="flex-1 flex flex-col overflow-hidden">
        {/* 顶部标题栏 */}
        <header className="bg-white border-b px-6 py-4 flex-shrink-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="w-10 h-10 bg-gradient-to-br from-purple-500 to-indigo-600 rounded-xl flex items-center justify-center shadow-lg shadow-purple-200">
                <Layers className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-gray-900">切块预览</h1>
                <p className="text-sm text-gray-500">
                  {selectedFile
                    ? `${selectedFile.filename} · ${chunks.length} 个切块`
                    : '选择已解析的文件进行切块调试'}
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              {submitSuccess && (
                <div className="flex items-center gap-2 text-green-600 text-sm bg-green-50 px-3 py-1.5 rounded-lg">
                  <CheckCircle className="w-4 h-4" />
                  入库成功
                </div>
              )}

              <Button
                onClick={handleSubmit}
                disabled={!selectedFile || chunks.length === 0 || isSubmitting}
                className="gap-2 bg-indigo-600 hover:bg-indigo-700"
              >
                {isSubmitting ? (
                  <Loader2 className="w-4 h-4 animate-spin" />
                ) : (
                  <Database className="w-4 h-4" />
                )}
                确认入库
              </Button>
            </div>
          </div>
        </header>

        <div className="flex-1 flex overflow-hidden">
          {/* 左侧：已解析文件列表 */}
          <aside className="w-72 bg-white border-r flex flex-col flex-shrink-0">
            <div className="p-4 border-b">
              <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider flex items-center gap-2">
                <FileText className="w-3.5 h-3.5" />
                已解析文件 ({parsedFiles.length})
              </h3>
            </div>

            <div className="flex-1 overflow-y-auto p-3">
              {!isLoaded ? (
                <div className="flex items-center justify-center py-8">
                  <Loader2 className="w-5 h-5 animate-spin text-gray-400" />
                </div>
              ) : parsedFiles.length === 0 ? (
                <div className="text-center py-8 text-gray-400">
                  <FileText className="w-10 h-10 mx-auto mb-2 opacity-50" />
                  <p className="text-sm">暂无已解析文件</p>
                  <p className="text-xs mt-1">请先在「文档解析」页面解析文件</p>
                  <Button
                    variant="outline"
                    size="sm"
                    className="mt-4 gap-2"
                    onClick={() => (window.location.href = '/parsing')}
                  >
                    <ArrowRight className="w-4 h-4" />
                    去解析文档
                  </Button>
                </div>
              ) : (
                <div className="space-y-2">
                  {parsedFiles.map((file) => (
                    <div
                      key={file.id}
                      className={cn(
                        'group p-3 rounded-lg border cursor-pointer transition-all',
                        selectedFileId === file.id
                          ? 'bg-indigo-50 border-indigo-200'
                          : 'bg-white border-gray-200 hover:border-indigo-200 hover:bg-gray-50'
                      )}
                      onClick={() => setSelectedFileId(file.id)}
                    >
                      <div className="flex items-start gap-3">
                        <div className="p-2 bg-purple-50 rounded-lg">
                          <FileText className="w-4 h-4 text-purple-500" />
                        </div>
                        <div className="flex-1 min-w-0">
                          <p className="text-sm font-medium text-gray-900 truncate">
                            {file.filename}
                          </p>
                          <div className="flex items-center gap-2 mt-1 text-xs text-gray-400">
                            <span>{formatFileSize(file.fileSize)}</span>
                            <span>·</span>
                            <span>{file.parser}</span>
                          </div>
                          <div className="flex items-center gap-1 mt-1 text-xs text-gray-400">
                            <Clock className="w-3 h-3" />
                            {formatDate(file.parsedAt)}
                          </div>
                        </div>
                        <button
                          onClick={(e) => {
                            e.stopPropagation()
                            removeFile(file.id)
                            if (selectedFileId === file.id) {
                              setSelectedFileId(null)
                              setChunks([])
                            }
                          }}
                          className="opacity-0 group-hover:opacity-100 p-1 hover:bg-red-50 rounded transition-all"
                        >
                          <Trash2 className="w-4 h-4 text-gray-400 hover:text-red-500" />
                        </button>
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </aside>

          {/* 中间：原文预览 */}
          <div className="flex-1 flex flex-col bg-white border-r overflow-hidden">
            {/* 工具栏 */}
            <div className="h-10 border-b bg-gray-50 flex items-center justify-between px-4 flex-shrink-0">
              <span className="text-xs font-semibold text-gray-500 flex items-center gap-2">
                <Eye className="w-3.5 h-3.5" />
                {activeChunkIndex !== null ? '原文定位 (高亮模式)' : '文档预览'}
              </span>
              <div className="flex items-center bg-gray-200 rounded-lg p-0.5">
                <button
                  onClick={() => setPreviewMode('source')}
                  className={cn(
                    'px-2 py-1 text-xs rounded transition-all',
                    previewMode === 'source'
                      ? 'bg-white text-gray-900 shadow-sm'
                      : 'text-gray-500 hover:text-gray-700'
                  )}
                >
                  <Code className="w-3 h-3 inline mr-1" />
                  源码
                </button>
                <button
                  onClick={() => setPreviewMode('rendered')}
                  className={cn(
                    'px-2 py-1 text-xs rounded transition-all',
                    previewMode === 'rendered'
                      ? 'bg-white text-gray-900 shadow-sm'
                      : 'text-gray-500 hover:text-gray-700'
                  )}
                >
                  <Eye className="w-3 h-3 inline mr-1" />
                  渲染
                </button>
              </div>
            </div>

            {/* 内容区 */}
            <div ref={sourceContainerRef} className="flex-1 overflow-y-auto p-6">
              {!selectedFile ? (
                <div className="flex items-center justify-center h-full text-gray-400">
                  <div className="text-center">
                    <FileText className="w-12 h-12 mx-auto mb-3 opacity-50" />
                    <p>从左侧选择已解析的文件</p>
                  </div>
                </div>
              ) : previewMode === 'rendered' && activeChunkIndex === null ? (
                <div className="prose prose-slate max-w-none">
                  <ReactMarkdown remarkPlugins={[remarkGfm]}>
                    {selectedFile.markdownContent}
                  </ReactMarkdown>
                </div>
              ) : (
                <pre className="font-mono text-sm leading-relaxed whitespace-pre-wrap">
                  {activeChunkIndex !== null && highlightedContent ? (
                    <>
                      <span className="text-gray-400">{highlightedContent.before}</span>
                      <mark className="chunk-highlight bg-yellow-200 text-gray-900 px-0.5 rounded border-b-2 border-yellow-500 relative">
                        {highlightedContent.highlighted}
                        <span className="absolute -top-5 left-0 bg-yellow-500 text-white text-[10px] px-2 py-0.5 rounded whitespace-nowrap">
                          Chunk #{activeChunkIndex + 1} · {chunks[activeChunkIndex]?.length} chars
                        </span>
                      </mark>
                      <span className="text-gray-400">{highlightedContent.after}</span>
                    </>
                  ) : (
                    <span className="text-gray-700">{selectedFile.markdownContent}</span>
                  )}
                </pre>
              )}
            </div>
          </div>

          {/* 右侧：切块配置和预览 */}
          <aside className="w-96 bg-gray-50 flex flex-col flex-shrink-0">
            {/* 参数配置 */}
            <div className="p-5 bg-white border-b">
              <h3 className="text-xs font-bold text-gray-700 mb-4 flex items-center gap-2">
                <Sliders className="w-3.5 h-3.5" />
                切分参数
              </h3>

              <div className="space-y-5">
                {/* Chunk Size */}
                <div>
                  <div className="flex justify-between mb-2">
                    <span className="text-xs text-gray-500">Chunk Size</span>
                    <span className="text-xs font-mono bg-indigo-50 text-indigo-600 px-2 py-0.5 rounded">
                      {chunkSize}
                    </span>
                  </div>
                  <input
                    type="range"
                    min="100"
                    max="2000"
                    step="50"
                    value={chunkSize}
                    onChange={(e) => setChunkSize(Number(e.target.value))}
                    className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-indigo-600"
                  />
                  <div className="flex justify-between text-[10px] text-gray-400 mt-1">
                    <span>100</span>
                    <span>2000</span>
                  </div>
                </div>

                {/* Overlap */}
                <div>
                  <div className="flex justify-between mb-2">
                    <span className="text-xs text-gray-500">Overlap</span>
                    <span className="text-xs font-mono bg-indigo-50 text-indigo-600 px-2 py-0.5 rounded">
                      {chunkOverlap}
                    </span>
                  </div>
                  <input
                    type="range"
                    min="0"
                    max={Math.min(500, chunkSize - 50)}
                    step="25"
                    value={chunkOverlap}
                    onChange={(e) => setChunkOverlap(Number(e.target.value))}
                    className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-indigo-600"
                  />
                  <div className="flex justify-between text-[10px] text-gray-400 mt-1">
                    <span>0</span>
                    <span>{Math.min(500, chunkSize - 50)}</span>
                  </div>
                </div>
              </div>

              {/* 统计信息 */}
              {selectedFile && chunks.length > 0 && (
                <div className="mt-5 pt-5 border-t grid grid-cols-3 gap-3 text-center">
                  <div className="bg-indigo-50 p-3 rounded-lg">
                    <div className="text-xl font-bold text-indigo-600">{chunks.length}</div>
                    <div className="text-[10px] text-gray-500">切块数</div>
                  </div>
                  <div className="bg-green-50 p-3 rounded-lg">
                    <div className="text-xl font-bold text-green-600">
                      {Math.round(selectedFile.markdownContent.length / chunks.length)}
                    </div>
                    <div className="text-[10px] text-gray-500">平均长度</div>
                  </div>
                  <div className="bg-purple-50 p-3 rounded-lg">
                    <div className="text-xl font-bold text-purple-600">
                      {Math.round((chunkOverlap / chunkSize) * 100)}%
                    </div>
                    <div className="text-[10px] text-gray-500">重叠率</div>
                  </div>
                </div>
              )}
            </div>

            {/* 切块列表 */}
            <div className="flex-1 flex flex-col overflow-hidden">
              <div className="px-4 py-2 border-b bg-white flex items-center justify-between">
                <span className="text-xs font-semibold text-gray-500 flex items-center gap-2">
                  <Layers className="w-3.5 h-3.5" />
                  切块列表
                </span>
                {isChunking && (
                  <Loader2 className="w-4 h-4 animate-spin text-indigo-500" />
                )}
              </div>

              <div className="flex-1 overflow-y-auto p-3 space-y-2">
                {!selectedFile ? (
                  <div className="flex items-center justify-center h-full text-gray-400 text-sm">
                    <div className="text-center">
                      <Layers className="w-8 h-8 mx-auto mb-2 opacity-50" />
                      <p>选择文件后显示切块</p>
                    </div>
                  </div>
                ) : chunks.length === 0 ? (
                  <div className="flex items-center justify-center h-full">
                    <Loader2 className="w-6 h-6 animate-spin text-indigo-500" />
                  </div>
                ) : (
                  chunks.map((chunk, idx) => (
                    <div
                      key={idx}
                      onMouseEnter={() => setActiveChunkIndex(idx)}
                      onMouseLeave={() => setActiveChunkIndex(null)}
                      className={cn(
                        'group p-3 rounded-lg border cursor-default transition-all',
                        activeChunkIndex === idx
                          ? 'bg-yellow-50 border-yellow-400 shadow-md scale-[1.02] z-10'
                          : 'bg-white border-gray-200 hover:border-indigo-300 hover:shadow-sm'
                      )}
                    >
                      <div className="flex items-center justify-between mb-2">
                        <span
                          className={cn(
                            'text-[10px] font-bold px-2 py-0.5 rounded',
                            activeChunkIndex === idx
                              ? 'bg-yellow-500 text-white'
                              : 'bg-gray-100 text-gray-500'
                          )}
                        >
                          #{idx + 1}
                        </span>
                        <div className="flex items-center gap-2 text-[10px] text-gray-400">
                          <span className="font-mono">{chunk.length} chars</span>
                          {idx > 0 && chunkOverlap > 0 && (
                            <span className="bg-blue-100 text-blue-600 px-1.5 py-0.5 rounded">
                              +{chunkOverlap} overlap
                            </span>
                          )}
                        </div>
                      </div>
                      <p className="text-xs text-gray-600 line-clamp-3 leading-relaxed">
                        {chunk.content}
                      </p>
                      <div className="mt-2 pt-2 border-t border-gray-100 text-[10px] text-gray-300 font-mono">
                        [{chunk.start_index} - {chunk.end_index}]
                      </div>
                    </div>
                  ))
                )}
              </div>
            </div>
          </aside>
        </div>
      </main>
    </div>
  )
}
