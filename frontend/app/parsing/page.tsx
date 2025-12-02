'use client'

/**
 * 知识加工工作台
 * 现代化的文档解析与切块预览界面
 */
import { useState, useMemo, useCallback } from 'react'
import {
  Upload,
  Loader2,
  CheckCircle,
  XCircle,
  Layers,
  Settings,
  Eye,
  FileText,
  AlertCircle,
  ArrowRight,
  Save,
  RotateCcw,
  Sparkles,
  Clock,
  Trash2,
  FolderOpen,
} from 'lucide-react'

import { Navbar } from '@/components/navbar'
import { DocumentDetailDialog } from '@/components/document-detail-dialog'
import { Button } from '@/components/ui/button'
import { useDocuments } from '@/hooks/use-documents'
import { documentApi } from '@/lib/api-client'
import { formatFileSize, formatDate, getFileIcon, cn } from '@/lib/utils'
import type { Document, ChunkPreviewResponse, ChunkPreviewItem } from '@/types'

// 分隔符配置
const SEPARATORS = ['\\n\\n', '\\n', '。', '！', '？', '.', '!', '?']

export default function ParsingPage() {
  const { documents, isLoading, uploadDocument, deleteDocument, refreshDocuments } = useDocuments()

  // 工作台模式: 'list' | 'workbench'
  const [mode, setMode] = useState<'list' | 'workbench'>('list')

  // 工作台状态
  const [file, setFile] = useState<File | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [chunkSize, setChunkSize] = useState(1000)
  const [chunkOverlap, setChunkOverlap] = useState(200)
  const [previewData, setPreviewData] = useState<ChunkPreviewResponse | null>(null)
  const [isProcessing, setIsProcessing] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitSuccess, setSubmitSuccess] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [hoveredChunkIndex, setHoveredChunkIndex] = useState<number | null>(null)

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
      // 如果在列表模式下拖放，进入工作台
      if (mode === 'list') {
        setMode('workbench')
      }
    }
  }, [mode])

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0]
    if (selectedFile) {
      setFile(selectedFile)
      setPreviewData(null)
      setError(null)
      setSubmitSuccess(false)
    }
    e.target.value = ''
  }, [])

  // 快速上传（自动处理）
  const handleQuickUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    for (const file of Array.from(files)) {
      try {
        await uploadDocument(file)
      } catch (error) {
        console.error('Upload failed:', error)
      }
    }
    e.target.value = ''
  }

  // 生成预览
  const handlePreview = useCallback(async () => {
    if (!file) return

    setIsProcessing(true)
    setError(null)

    try {
      const data = await documentApi.chunkPreview(file, {
        chunk_size: chunkSize,
        chunk_overlap: chunkOverlap,
      })
      setPreviewData(data)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || '预览失败')
    } finally {
      setIsProcessing(false)
    }
  }, [file, chunkSize, chunkOverlap])

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
          strategy: 'RecursiveCharacterTextSplitter',
        },
      })

      setSubmitSuccess(true)
      refreshDocuments()
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || '入库失败')
    } finally {
      setIsSubmitting(false)
    }
  }, [previewData, file, chunkSize, chunkOverlap, refreshDocuments])

  // 重置工作台
  const handleReset = useCallback(() => {
    setFile(null)
    setPreviewData(null)
    setError(null)
    setSubmitSuccess(false)
    setChunkSize(1000)
    setChunkOverlap(200)
    setHoveredChunkIndex(null)
  }, [])

  // 返回列表
  const handleBackToList = useCallback(() => {
    handleReset()
    setMode('list')
  }, [handleReset])

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

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="h-4 w-4 text-green-500" />
      case 'failed':
        return <XCircle className="h-4 w-4 text-red-500" />
      case 'processing':
      case 'pending':
        return <Loader2 className="h-4 w-4 text-indigo-500 animate-spin" />
      default:
        return <Clock className="h-4 w-4 text-gray-400" />
    }
  }

  return (
    <div className="flex h-screen overflow-hidden bg-gray-100">
      <Navbar />

      {/* 列表模式 */}
      {mode === 'list' && (
        <main className="flex-1 overflow-hidden flex flex-col">
          {/* 头部 */}
          <header className="flex-shrink-0 bg-white border-b px-8 py-6 shadow-sm">
            <div className="max-w-6xl mx-auto flex items-center justify-between">
              <div className="flex items-center gap-4">
                <div className="bg-indigo-100 p-3 rounded-xl">
                  <Layers className="text-indigo-600 w-6 h-6" />
                </div>
                <div>
                  <h1 className="text-2xl font-bold text-gray-900">知识加工工作台</h1>
                  <p className="text-gray-500 text-sm">上传文档、自定义切块策略、精准入库</p>
                </div>
              </div>

              <div className="flex items-center gap-3">
                {/* 快速上传 */}
                <label className="inline-flex items-center gap-2 px-4 py-2.5 bg-white border border-gray-200 text-gray-700 rounded-lg hover:bg-gray-50 cursor-pointer transition shadow-sm">
                  <Upload className="h-4 w-4" />
                  <span className="text-sm font-medium">快速上传</span>
                  <input
                    type="file"
                    multiple
                    accept=".pdf,.txt,.md"
                    className="hidden"
                    onChange={handleQuickUpload}
                  />
                </label>

                {/* 高级切块 - 点击进入工作台 */}
                <button
                  onClick={() => setMode('workbench')}
                  className="inline-flex items-center gap-2 px-4 py-2.5 bg-indigo-600 text-white rounded-lg hover:bg-indigo-700 transition shadow-sm"
                >
                  <Settings className="h-4 w-4" />
                  <span className="text-sm font-medium">高级切块</span>
                </button>
              </div>
            </div>
          </header>

          {/* 文档列表 */}
          <div className="flex-1 overflow-y-auto p-8">
            <div className="max-w-6xl mx-auto">
              {/* 拖放上传区 */}
              <div
                className={cn(
                  'mb-8 p-8 border-2 border-dashed rounded-2xl text-center transition-all cursor-pointer',
                  isDragging
                    ? 'border-indigo-500 bg-indigo-50'
                    : 'border-gray-300 bg-white hover:border-indigo-400 hover:bg-indigo-50/30'
                )}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onClick={() => document.getElementById('workbench-file-input')?.click()}
              >
                <input
                  id="workbench-file-input"
                  type="file"
                  accept=".pdf,.txt,.md"
                  className="hidden"
                  onChange={handleFileSelect}
                />
                <Upload className="w-10 h-10 mx-auto mb-3 text-gray-400" />
                <p className="text-gray-600 font-medium">拖放文件到此处，进入高级切块模式</p>
                <p className="text-gray-400 text-sm mt-1">支持 PDF、TXT、Markdown</p>
              </div>

              {/* 文档网格 */}
              <div className="bg-white rounded-2xl border shadow-sm">
                <div className="px-6 py-4 border-b flex items-center justify-between">
                  <h2 className="font-semibold text-gray-900 flex items-center gap-2">
                    <FolderOpen className="w-5 h-5 text-gray-500" />
                    已处理文档
                  </h2>
                  {isLoading && (
                    <div className="flex items-center gap-2 text-sm text-gray-500">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      加载中...
                    </div>
                  )}
                </div>

                {documents.length === 0 ? (
                  <div className="text-center py-16 text-gray-400">
                    <FileText className="w-12 h-12 mx-auto mb-4 opacity-50" />
                    <p>暂无文档</p>
                    <p className="text-sm mt-1">上传文件开始知识加工</p>
                  </div>
                ) : (
                  <div className="grid gap-4 p-6 md:grid-cols-2 lg:grid-cols-3">
                    {documents.map((doc) => (
                      <DocCard
                        key={doc.id}
                        document={doc}
                        onDelete={() => deleteDocument(doc.id)}
                        getStatusIcon={getStatusIcon}
                      />
                    ))}
                  </div>
                )}
              </div>
            </div>
          </div>
        </main>
      )}

      {/* 工作台模式 */}
      {mode === 'workbench' && (
        <main className="flex-1 overflow-hidden flex flex-col bg-gray-50">
          {/* 顶部栏 */}
          <header className="flex-shrink-0 bg-white border-b px-6 py-4 flex justify-between items-center shadow-sm">
            <div className="flex items-center gap-3">
              <div className="bg-indigo-100 p-2.5 rounded-xl">
                <Layers className="text-indigo-600 w-5 h-5" />
              </div>
              <div>
                <h1 className="text-lg font-bold text-gray-900">知识加工工作台</h1>
                <p className="text-xs text-gray-500">
                  {file ? (
                    <>
                      {file.name} · {formatFileSize(file.size)}
                      {previewData && (
                        <span className="ml-2 text-indigo-600">
                          · 已生成 {previewData.total_chunks} 个切块
                        </span>
                      )}
                    </>
                  ) : (
                    '上传文档开始自定义切块'
                  )}
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

              <Button variant="ghost" size="sm" onClick={handleBackToList} className="gap-2">
                <ArrowRight className="w-4 h-4 rotate-180" />
                返回列表
              </Button>

              {file && (
                <Button variant="ghost" size="sm" onClick={handleReset} className="gap-2">
                  <RotateCcw className="w-4 h-4" />
                  重置
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
            {/* 未上传文件时显示上传界面 */}
            {!file ? (
              <div className="flex-1 flex items-center justify-center p-8">
                <div
                  className={cn(
                    'max-w-xl w-full p-12 border-2 border-dashed rounded-2xl text-center transition-all cursor-pointer',
                    isDragging
                      ? 'border-indigo-500 bg-indigo-50 scale-[1.02]'
                      : 'border-gray-300 bg-white hover:border-indigo-400 hover:bg-indigo-50/50'
                  )}
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                  onClick={() => document.getElementById('workbench-upload-input')?.click()}
                >
                  <input
                    id="workbench-upload-input"
                    type="file"
                    accept=".pdf,.txt,.md"
                    className="hidden"
                    onChange={handleFileSelect}
                  />
                  <div className="w-20 h-20 mx-auto mb-6 bg-indigo-100 rounded-2xl flex items-center justify-center">
                    <Upload className="w-10 h-10 text-indigo-600" />
                  </div>
                  <h3 className="text-xl font-semibold text-gray-900 mb-2">上传文档</h3>
                  <p className="text-gray-500 mb-6">拖放文件到此处，或点击选择文件</p>
                  <div className="flex items-center justify-center gap-3">
                    <span className="px-3 py-1.5 bg-gray-100 text-gray-600 text-sm rounded-lg">PDF</span>
                    <span className="px-3 py-1.5 bg-gray-100 text-gray-600 text-sm rounded-lg">TXT</span>
                    <span className="px-3 py-1.5 bg-gray-100 text-gray-600 text-sm rounded-lg">Markdown</span>
                  </div>
                </div>
              </div>
            ) : (
              <>
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
                    <p className="text-[10px] text-gray-400 mt-2">
                      RecursiveCharacterTextSplitter 按优先级递归切分
                    </p>
                  </div>

                  {/* 预览按钮 */}
                  <Button
                    onClick={handlePreview}
                    disabled={isProcessing}
                    className="w-full gap-2"
                    variant="outline"
                  >
                    {isProcessing ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Eye className="w-4 h-4" />
                    )}
                    {isProcessing ? '正在切块...' : '生成预览'}
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
            <div className="flex-1 flex p-4 gap-4 overflow-hidden">
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
                  ) : isProcessing ? (
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
                  ) : isProcessing ? (
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
            </div>
              </>
            )}
          </div>
        </main>
      )}
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
        'group relative bg-white border p-4 rounded-lg shadow-sm transition-all duration-200 cursor-default',
        isHovered
          ? 'border-indigo-400 shadow-md ring-2 ring-indigo-100 scale-[1.01]'
          : 'border-gray-200 hover:border-indigo-300 hover:shadow-md'
      )}
      onMouseEnter={onMouseEnter}
      onMouseLeave={onMouseLeave}
    >
      <div className="flex items-center justify-between mb-2">
        <span
          className={cn(
            'text-[10px] font-bold px-2 py-0.5 rounded',
            isHovered ? 'bg-indigo-100 text-indigo-700' : 'bg-gray-100 text-gray-500'
          )}
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

      <p className="text-sm text-gray-700 leading-relaxed line-clamp-4">{chunk.content}</p>

      <div className="mt-2 pt-2 border-t border-gray-100 text-[10px] text-gray-300 font-mono">
        [{chunk.start_index} - {chunk.end_index}]
      </div>
    </div>
  )
}

// 文档卡片组件
function DocCard({
  document,
  onDelete,
  getStatusIcon,
}: {
  document: Document
  onDelete: () => void
  getStatusIcon: (s: string) => React.ReactNode
}) {
  return (
    <div className="group border rounded-xl p-4 bg-gray-50 hover:bg-white hover:shadow-md transition-all">
      <div className="flex items-start gap-3">
        <div className="text-2xl mt-0.5">{getFileIcon(document.file_type)}</div>
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2">
            <h3 className="text-sm font-semibold text-gray-900 truncate">{document.filename}</h3>
            {getStatusIcon(document.status)}
          </div>
          <p className="text-xs text-gray-500 mt-1">
            {formatFileSize(document.file_size)} · {formatDate(document.created_at)}
          </p>

          {(document.status === 'processing' || document.status === 'pending') && (
            <div className="mt-2">
              <div className="w-full bg-gray-200 rounded-full h-1.5">
                <div
                  className="bg-indigo-500 h-1.5 rounded-full transition-all"
                  style={{ width: `${document.processing_progress}%` }}
                />
              </div>
              <p className="text-xs text-gray-500 mt-1">
                {document.current_stage || '处理中'} · {document.processing_progress}%
              </p>
            </div>
          )}

          {document.status === 'completed' && (
            <p className="text-xs text-gray-600 mt-1">
              {document.chunk_count} 个块 · {document.total_characters?.toLocaleString()} 字
            </p>
          )}

          {document.status === 'failed' && (
            <p className="text-xs text-red-500 mt-1 truncate">失败：{document.error_message}</p>
          )}
        </div>

        <div className="flex flex-col items-end gap-2 opacity-0 group-hover:opacity-100 transition-opacity">
          <DocumentDetailDialog document={document} />
          {document.status !== 'processing' && (
            <button
              onClick={onDelete}
              className="p-1.5 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded transition"
            >
              <Trash2 className="w-4 h-4" />
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
