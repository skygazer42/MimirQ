'use client'

/**
 * 文档解析页面 - 增强版
 * 支持上传解析、交互式切块参数调整、实时预览
 */
import { useState, useMemo, useRef, useCallback } from 'react'
import {
  Upload,
  Loader2,
  CheckCircle,
  XCircle,
  Clock,
  Scissors,
  Settings2,
  Eye,
  BarChart3,
  FileText,
  ChevronRight,
  Info,
  AlertCircle,
  CheckCircle2,
  X,
} from 'lucide-react'

import { Navbar } from '@/components/navbar'
import { ManualUploadDialog } from '@/components/manual-upload-dialog'
import { DocumentDetailDialog } from '@/components/document-detail-dialog'
import { Button } from '@/components/ui/button'
import { useDocuments } from '@/hooks/use-documents'
import { documentApi } from '@/lib/api-client'
import { formatFileSize, formatDate, getFileIcon, cn } from '@/lib/utils'
import type { Document, DocumentPreview, ManualChunk } from '@/types'

// ===================== 切块相关类型和函数 =====================

type ChunkStrategy = 'fixed' | 'semantic' | 'delimiter'

// 固定长度切块
const chunkByFixedLength = (text: string, size: number, overlap: number): string[] => {
  const chunks: string[] = []
  if (!text || size <= 0) return chunks

  let startIndex = 0
  while (startIndex < text.length) {
    const endIndex = Math.min(startIndex + size, text.length)
    chunks.push(text.slice(startIndex, endIndex))
    if (endIndex === text.length) break
    startIndex += size - overlap
    if (startIndex >= text.length) break
  }
  return chunks
}

// 分隔符切块
const chunkByDelimiter = (text: string, delimiter: string): string[] => {
  if (!text || !delimiter) return [text].filter(Boolean)
  const parts = text.split(delimiter)
  return parts
    .map((part, index) => {
      const trimmed = part.trim()
      if (!trimmed) return ''
      return index === 0 && !text.startsWith(delimiter) ? trimmed : `${delimiter}${trimmed}`
    })
    .filter(Boolean)
}

// 统计信息接口
interface ChunkStats {
  totalChunks: number
  totalChars: number
  avgLength: number
  minLength: number
  maxLength: number
}

const calculateStats = (chunks: string[]): ChunkStats => {
  if (chunks.length === 0) {
    return { totalChunks: 0, totalChars: 0, avgLength: 0, minLength: 0, maxLength: 0 }
  }
  const lengths = chunks.map((c) => c.length)
  const totalChars = lengths.reduce((a, b) => a + b, 0)
  return {
    totalChunks: chunks.length,
    totalChars,
    avgLength: Math.round(totalChars / chunks.length),
    minLength: Math.min(...lengths),
    maxLength: Math.max(...lengths),
  }
}

// ===================== 主页面组件 =====================

export default function ParsingPage() {
  const { documents, isLoading, uploadDocument, deleteDocument, refreshDocuments } = useDocuments()
  const fileInputRef = useRef<HTMLInputElement | null>(null)

  // 切块预览模式状态
  const [previewMode, setPreviewMode] = useState(false)
  const [previewFile, setPreviewFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<DocumentPreview | null>(null)
  const [isParsing, setIsParsing] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [success, setSuccess] = useState(false)

  // 切块参数
  const [strategy, setStrategy] = useState<ChunkStrategy>('fixed')
  const [chunkSize, setChunkSize] = useState(500)
  const [chunkOverlap, setChunkOverlap] = useState(50)
  const [delimiter, setDelimiter] = useState('## ')

  // 预览选中状态
  const [selectedChunkIndex, setSelectedChunkIndex] = useState<number | null>(null)

  // 自动上传处理
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
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

  // 手动切块预览 - 文件选择
  const handlePreviewFileSelect = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    const file = files[0]
    setPreviewFile(file)
    setPreview(null)
    setError(null)
    setSuccess(false)
    setIsParsing(true)
    setSelectedChunkIndex(null)
    setPreviewMode(true)

    try {
      const result = await documentApi.preview(file)
      setPreview(result)
    } catch (err: any) {
      console.error('Preview parse failed:', err)
      setError(err.message || '文档解析失败')
    } finally {
      setIsParsing(false)
      e.target.value = ''
    }
  }

  // 获取完整文本
  const fullText = useMemo(() => {
    if (!preview?.segments) return ''
    return preview.segments.map((s) => s.content).join('\n')
  }, [preview])

  // 计算切块结果
  const chunks = useMemo(() => {
    if (!fullText) return []
    switch (strategy) {
      case 'fixed':
        return chunkByFixedLength(fullText, chunkSize, chunkOverlap)
      case 'delimiter':
        return chunkByDelimiter(fullText, delimiter)
      case 'semantic':
        return fullText.split(/\n\n+/).filter(Boolean)
      default:
        return []
    }
  }, [fullText, strategy, chunkSize, chunkOverlap, delimiter])

  // 统计信息
  const stats = useMemo(() => calculateStats(chunks), [chunks])

  // 构建提交的切块数据
  const buildChunks = useCallback((): ManualChunk[] => {
    return chunks.map((content, index) => ({
      content,
      page_number: preview?.segments?.[0]?.page_number,
      start_char: 0,
      end_char: content.length,
      metadata: { chunk_index: index },
    }))
  }, [chunks, preview])

  // 提交切块
  const handleSubmitChunks = async () => {
    if (!preview) return

    const chunkData = buildChunks()
    if (!chunkData.length) {
      setError('没有可用的切片')
      return
    }

    setIsSubmitting(true)
    setError(null)

    try {
      await documentApi.createFromChunks({
        filename: preview.filename,
        file_type: preview.file_type,
        file_size: preview.file_size,
        chunks: chunkData,
        metadata: { strategy, chunkSize, chunkOverlap, delimiter },
      })
      setSuccess(true)
      refreshDocuments()
    } catch (err: any) {
      console.error('Upload failed:', err)
      setError(err.message || '上传失败')
    } finally {
      setIsSubmitting(false)
    }
  }

  // 退出预览模式
  const exitPreviewMode = () => {
    setPreviewMode(false)
    setPreviewFile(null)
    setPreview(null)
    setError(null)
    setSuccess(false)
    setSelectedChunkIndex(null)
  }

  const getStatusIcon = (status: string) => {
    switch (status) {
      case 'completed':
        return <CheckCircle className="h-4 w-4 text-green-500" />
      case 'failed':
        return <XCircle className="h-4 w-4 text-red-500" />
      case 'processing':
      case 'pending':
        return <Loader2 className="h-4 w-4 text-blue-500 animate-spin" />
      default:
        return <Clock className="h-4 w-4 text-gray-400" />
    }
  }

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <Navbar />
      <main className="flex-1 overflow-hidden flex flex-col">
        {/* 头部 */}
        <div className="bg-white border-b px-8 py-6 flex-shrink-0">
          <div className="max-w-7xl mx-auto">
            <div className="flex items-center justify-between flex-wrap gap-4">
              <div>
                <h1 className="text-2xl font-bold text-gray-900 flex items-center gap-3">
                  <Scissors className="h-7 w-7 text-blue-600" />
                  文档解析
                </h1>
                <p className="text-gray-600 mt-1">
                  上传文档自动解析，或使用高级模式自定义切块
                </p>
              </div>
              {!previewMode && (
                <div className="flex flex-wrap gap-3">
                  <button
                    onClick={() => fileInputRef.current?.click()}
                    className="inline-flex items-center gap-2 px-4 py-2 bg-blue-600 text-white rounded-lg hover:bg-blue-700 transition"
                  >
                    <Upload className="h-4 w-4" />
                    快速上传
                  </button>
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    accept=".pdf,.txt,.md,.docx"
                    className="hidden"
                    onChange={handleFileUpload}
                  />
                  <label className="inline-flex items-center gap-2 px-4 py-2 bg-white border border-gray-300 text-gray-700 rounded-lg hover:bg-gray-50 cursor-pointer transition">
                    <Settings2 className="h-4 w-4" />
                    高级切块
                    <input
                      type="file"
                      accept=".pdf,.txt,.md,.docx"
                      className="hidden"
                      onChange={handlePreviewFileSelect}
                    />
                  </label>
                </div>
              )}
              {previewMode && (
                <Button variant="outline" onClick={exitPreviewMode} className="gap-2">
                  <X className="h-4 w-4" />
                  返回列表
                </Button>
              )}
            </div>
          </div>
        </div>

        {/* 主内容区 */}
        <div className="flex-1 overflow-y-auto p-8">
          <div className="max-w-7xl mx-auto">
            {/* 普通模式：文档列表 */}
            {!previewMode && (
              <div className="bg-white rounded-xl border p-6">
                <div className="flex items-center justify-between mb-6">
                  <h2 className="text-lg font-semibold text-gray-900">文档列表</h2>
                  {isLoading && (
                    <div className="flex items-center gap-2 text-sm text-gray-500">
                      <Loader2 className="h-4 w-4 animate-spin" />
                      加载中...
                    </div>
                  )}
                </div>

                {documents.length === 0 ? (
                  <div className="text-center py-12 text-gray-500">
                    <FileText className="h-12 w-12 mx-auto mb-4 opacity-50" />
                    <p>暂无文档，点击上方按钮开始上传</p>
                  </div>
                ) : (
                  <div className="grid gap-4 md:grid-cols-2 lg:grid-cols-3">
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
            )}

            {/* 高级模式：切块预览 */}
            {previewMode && (
              <div className="space-y-6">
                {/* 解析中 */}
                {isParsing && (
                  <div className="bg-white rounded-xl border p-12 text-center">
                    <Loader2 className="h-12 w-12 animate-spin text-blue-600 mx-auto mb-4" />
                    <p className="text-gray-600">正在解析文档...</p>
                  </div>
                )}

                {/* 解析失败 */}
                {!isParsing && error && !preview && (
                  <div className="bg-white rounded-xl border p-12 text-center">
                    <AlertCircle className="h-12 w-12 text-red-500 mx-auto mb-4" />
                    <p className="text-red-600">{error}</p>
                    <Button variant="outline" onClick={exitPreviewMode} className="mt-4">
                      返回
                    </Button>
                  </div>
                )}

                {/* 解析成功 - 切块预览界面 */}
                {preview && !isParsing && (
                  <>
                    {/* 文件信息卡片 */}
                    <div className="bg-white rounded-xl border p-6">
                      <div className="flex items-center gap-4">
                        <div className="w-12 h-12 bg-blue-50 rounded-lg flex items-center justify-center">
                          <FileText className="h-6 w-6 text-blue-600" />
                        </div>
                        <div className="flex-1">
                          <h3 className="font-semibold text-gray-900">{preview.filename}</h3>
                          <p className="text-sm text-gray-500">
                            {formatFileSize(preview.file_size)} · {preview.segments?.length || 0} 个原始片段 · {fullText.length.toLocaleString()} 字符
                          </p>
                        </div>
                      </div>
                    </div>

                    {/* 三栏布局 */}
                    <div className="grid grid-cols-12 gap-6">
                      {/* 左侧：切块参数 */}
                      <div className="col-span-12 lg:col-span-3">
                        <div className="bg-white rounded-xl border p-6 sticky top-0">
                          <h3 className="font-semibold text-gray-900 flex items-center gap-2 mb-6">
                            <Settings2 className="h-5 w-5 text-gray-600" />
                            切块参数
                          </h3>

                          {/* 策略选择 */}
                          <div className="space-y-3 mb-6">
                            <label className="text-sm font-medium text-gray-700">切块策略</label>
                            <div className="space-y-2">
                              {[
                                { value: 'fixed', label: '固定长度', desc: '按字符数切分' },
                                { value: 'semantic', label: '语义分段', desc: '按段落切分' },
                                { value: 'delimiter', label: '自定义分隔符', desc: '按指定符号' },
                              ].map((item) => (
                                <button
                                  key={item.value}
                                  onClick={() => setStrategy(item.value as ChunkStrategy)}
                                  className={cn(
                                    'w-full text-left px-4 py-3 rounded-lg border transition-colors',
                                    strategy === item.value
                                      ? 'border-blue-500 bg-blue-50 text-blue-700'
                                      : 'border-gray-200 hover:border-gray-300'
                                  )}
                                >
                                  <div className="font-medium text-sm">{item.label}</div>
                                  <div className="text-xs text-gray-500">{item.desc}</div>
                                </button>
                              ))}
                            </div>
                          </div>

                          {/* 固定长度参数 */}
                          {strategy === 'fixed' && (
                            <div className="space-y-5">
                              {/* Chunk Size 滑块 */}
                              <div className="space-y-3">
                                <div className="flex items-center justify-between">
                                  <label className="text-sm font-medium text-gray-700">切块大小</label>
                                  <span className="text-sm font-semibold text-blue-600">
                                    {chunkSize} 字符
                                  </span>
                                </div>
                                <input
                                  type="range"
                                  min={100}
                                  max={2000}
                                  step={50}
                                  value={chunkSize}
                                  onChange={(e) => setChunkSize(parseInt(e.target.value))}
                                  className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
                                />
                                <div className="flex justify-between text-xs text-gray-400">
                                  <span>100</span>
                                  <span>2000</span>
                                </div>
                              </div>

                              {/* Overlap 滑块 */}
                              <div className="space-y-3">
                                <div className="flex items-center justify-between">
                                  <label className="text-sm font-medium text-gray-700">重叠大小</label>
                                  <span className="text-sm font-semibold text-blue-600">
                                    {chunkOverlap} 字符
                                  </span>
                                </div>
                                <input
                                  type="range"
                                  min={0}
                                  max={Math.min(500, chunkSize - 50)}
                                  step={10}
                                  value={chunkOverlap}
                                  onChange={(e) => setChunkOverlap(parseInt(e.target.value))}
                                  className="w-full h-2 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
                                />
                                <div className="flex justify-between text-xs text-gray-400">
                                  <span>0</span>
                                  <span>{Math.min(500, chunkSize - 50)}</span>
                                </div>
                              </div>

                              {/* 提示 */}
                              <div className="bg-amber-50 border border-amber-200 rounded-lg p-3 text-xs text-amber-800">
                                <div className="flex items-start gap-2">
                                  <Info className="h-4 w-4 flex-shrink-0 mt-0.5" />
                                  <div>
                                    <p className="font-medium mb-1">参数建议</p>
                                    <ul className="space-y-0.5 text-amber-700">
                                      <li>• 切块过小：上下文不足</li>
                                      <li>• 切块过大：噪音较多</li>
                                      <li>• 建议重叠：10-20%</li>
                                    </ul>
                                  </div>
                                </div>
                              </div>
                            </div>
                          )}

                          {/* 分隔符参数 */}
                          {strategy === 'delimiter' && (
                            <div className="space-y-3">
                              <label className="text-sm font-medium text-gray-700">分隔符</label>
                              <input
                                type="text"
                                value={delimiter}
                                onChange={(e) => setDelimiter(e.target.value)}
                                placeholder="如：## 或 ---"
                                className="w-full px-3 py-2 border rounded-lg text-sm focus:ring-2 focus:ring-blue-500 focus:border-transparent"
                              />
                              <p className="text-xs text-gray-500">
                                常用：Markdown 标题 "## "、分割线 "---"
                              </p>
                            </div>
                          )}
                        </div>
                      </div>

                      {/* 中间：切块列表 */}
                      <div className="col-span-12 lg:col-span-5">
                        <div className="bg-white rounded-xl border h-[600px] flex flex-col">
                          <div className="px-6 py-4 border-b flex items-center justify-between flex-shrink-0">
                            <h3 className="font-semibold text-gray-900 flex items-center gap-2">
                              <Eye className="h-5 w-5 text-gray-600" />
                              切块预览
                            </h3>
                            <span className="text-sm text-gray-500">
                              共 {stats.totalChunks} 个切块
                            </span>
                          </div>
                          <div className="flex-1 overflow-y-auto p-4 space-y-3">
                            {chunks.map((chunk, index) => (
                              <button
                                key={index}
                                onClick={() => setSelectedChunkIndex(index)}
                                className={cn(
                                  'w-full text-left p-4 rounded-lg border transition-all',
                                  selectedChunkIndex === index
                                    ? 'border-blue-500 bg-blue-50 ring-2 ring-blue-200'
                                    : 'border-gray-200 hover:border-gray-300 hover:bg-gray-50'
                                )}
                              >
                                <div className="flex items-center justify-between mb-2">
                                  <span className="text-xs font-medium text-blue-600 bg-blue-100 px-2 py-0.5 rounded">
                                    #{index + 1}
                                  </span>
                                  <span className="text-xs text-gray-500">
                                    {chunk.length} 字符
                                  </span>
                                </div>
                                <p className="text-sm text-gray-700 line-clamp-3">{chunk}</p>
                              </button>
                            ))}
                          </div>
                        </div>
                      </div>

                      {/* 右侧：统计和详情 */}
                      <div className="col-span-12 lg:col-span-4 space-y-6">
                        {/* 统计卡片 */}
                        <div className="bg-white rounded-xl border p-6">
                          <h3 className="font-semibold text-gray-900 flex items-center gap-2 mb-4">
                            <BarChart3 className="h-5 w-5 text-gray-600" />
                            切块统计
                          </h3>
                          <div className="grid grid-cols-2 gap-4">
                            <div className="bg-gray-50 rounded-lg p-4">
                              <p className="text-2xl font-bold text-blue-600">{stats.totalChunks}</p>
                              <p className="text-xs text-gray-500">切块总数</p>
                            </div>
                            <div className="bg-gray-50 rounded-lg p-4">
                              <p className="text-2xl font-bold text-green-600">{stats.avgLength}</p>
                              <p className="text-xs text-gray-500">平均长度</p>
                            </div>
                            <div className="bg-gray-50 rounded-lg p-4">
                              <p className="text-2xl font-bold text-amber-600">{stats.minLength}</p>
                              <p className="text-xs text-gray-500">最小长度</p>
                            </div>
                            <div className="bg-gray-50 rounded-lg p-4">
                              <p className="text-2xl font-bold text-purple-600">{stats.maxLength}</p>
                              <p className="text-xs text-gray-500">最大长度</p>
                            </div>
                          </div>
                        </div>

                        {/* 选中切块详情 */}
                        <div className="bg-white rounded-xl border p-6 h-[320px] flex flex-col">
                          <h3 className="font-semibold text-gray-900 mb-4 flex-shrink-0">切块详情</h3>
                          {selectedChunkIndex !== null ? (
                            <div className="flex-1 overflow-y-auto">
                              <div className="flex items-center gap-2 mb-3">
                                <span className="text-sm font-medium text-blue-600 bg-blue-100 px-2 py-1 rounded">
                                  切块 #{selectedChunkIndex + 1}
                                </span>
                                <span className="text-sm text-gray-500">
                                  {chunks[selectedChunkIndex]?.length} 字符
                                </span>
                              </div>
                              <div className="bg-gray-50 rounded-lg p-4">
                                <p className="text-sm text-gray-700 whitespace-pre-wrap leading-relaxed">
                                  {chunks[selectedChunkIndex]}
                                </p>
                              </div>
                            </div>
                          ) : (
                            <div className="flex-1 flex items-center justify-center text-gray-400 text-sm">
                              <div className="text-center">
                                <ChevronRight className="h-8 w-8 mx-auto mb-2 opacity-50" />
                                点击左侧切块查看详情
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    </div>

                    {/* 底部操作栏 */}
                    <div className="bg-white rounded-xl border p-6">
                      <div className="flex items-center justify-between">
                        <div className="flex items-center gap-4">
                          {error && (
                            <div className="flex items-center gap-2 text-red-600 text-sm">
                              <AlertCircle className="h-4 w-4" />
                              {error}
                            </div>
                          )}
                          {success && (
                            <div className="flex items-center gap-2 text-green-600 text-sm">
                              <CheckCircle2 className="h-4 w-4" />
                              文档已成功入库！
                            </div>
                          )}
                        </div>
                        <div className="flex items-center gap-3">
                          <Button variant="outline" onClick={exitPreviewMode}>
                            取消
                          </Button>
                          <Button
                            onClick={handleSubmitChunks}
                            disabled={isSubmitting || success || chunks.length === 0}
                            className="gap-2"
                          >
                            {isSubmitting && <Loader2 className="h-4 w-4 animate-spin" />}
                            {success ? '已完成' : '确认切块并入库'}
                          </Button>
                        </div>
                      </div>
                    </div>
                  </>
                )}
              </div>
            )}
          </div>
        </div>
      </main>
    </div>
  )
}

// ===================== 文档卡片组件 =====================

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
    <div className="border rounded-xl p-4 bg-gray-50 hover:bg-gray-100 transition">
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
                  className="bg-blue-500 h-1.5 rounded-full transition-all"
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
              {document.chunk_count} 个块 · {document.total_characters} 字
            </p>
          )}

          {document.status === 'failed' && (
            <p className="text-xs text-red-500 mt-1">处理失败：{document.error_message}</p>
          )}
        </div>

        <div className="flex flex-col items-end gap-2">
          <DocumentDetailDialog document={document} />
          {document.status !== 'processing' && (
            <button onClick={onDelete} className="text-xs text-red-500 hover:text-red-600">
              删除
            </button>
          )}
        </div>
      </div>
    </div>
  )
}
