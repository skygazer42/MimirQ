'use client'

/**
 * RAG 数据加工台 - 终极版
 * 专业级的文档解析与切块可视化界面
 */

import { useState, useMemo, useCallback } from 'react'
import {
  Upload,
  FileText,
  Settings2,
  Sparkles,
  Database,
  Search,
  Code,
  Cpu,
  Layers,
  Trash2,
  CheckCircle2,
  Loader2,
  AlertCircle,
  X,
} from 'lucide-react'
import { documentApi } from '@/lib/api-client'
import { cn } from '@/lib/utils'
import type { ChunkPreviewResponse, ChunkPreviewItem } from '@/types'

export default function ChunkPreviewPage() {
  // 文件状态
  const [file, setFile] = useState<File | null>(null)
  const [isDragging, setIsDragging] = useState(false)

  // 参数状态
  const [chunkSize, setChunkSize] = useState(1000)
  const [chunkOverlap, setChunkOverlap] = useState(200)

  // 清洗规则
  const [cleaningRules, setCleaningRules] = useState({
    removeExtraSpaces: true,
    removeUrls: false,
    fixEncoding: false,
  })

  // 处理状态
  const [previewData, setPreviewData] = useState<ChunkPreviewResponse | null>(null)
  const [isProcessing, setIsProcessing] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitSuccess, setSubmitSuccess] = useState(false)
  const [error, setError] = useState<string | null>(null)

  // 视图状态
  const [searchQuery, setSearchQuery] = useState('')
  const [viewMode, setViewMode] = useState<'card' | 'json'>('card')
  const [hoveredChunkIndex, setHoveredChunkIndex] = useState<number | null>(null)

  // 过滤后的切块
  const filteredChunks = useMemo(() => {
    if (!previewData?.chunks) return []
    if (!searchQuery.trim()) return previewData.chunks
    return previewData.chunks.filter((chunk) =>
      chunk.content.toLowerCase().includes(searchQuery.toLowerCase())
    )
  }, [previewData, searchQuery])

  // 预估 Token 数
  const totalTokens = useMemo(() => {
    if (!previewData) return 0
    return Math.round(previewData.total_characters * 0.4)
  }, [previewData])

  // 文件拖放处理
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
      handleFileUpload(droppedFile)
    }
  }, [])

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFile = e.target.files?.[0]
    if (selectedFile) {
      handleFileUpload(selectedFile)
    }
    e.target.value = ''
  }, [])

  // 上传并解析文件
  const handleFileUpload = async (uploadedFile: File) => {
    setFile(uploadedFile)
    setPreviewData(null)
    setError(null)
    setSubmitSuccess(false)
    setIsProcessing(true)

    try {
      const data = await documentApi.chunkPreview(uploadedFile, {
        chunk_size: chunkSize,
        chunk_overlap: chunkOverlap,
      })
      setPreviewData(data)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || '解析失败')
    } finally {
      setIsProcessing(false)
    }
  }

  // 重新生成预览
  const handleRegenerate = async () => {
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
      setError(err.response?.data?.detail || err.message || '生成失败')
    } finally {
      setIsProcessing(false)
    }
  }

  // 确认入库
  const handleSubmit = async () => {
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
          cleaning_rules: cleaningRules,
          strategy: 'RecursiveCharacterTextSplitter',
        },
      })

      setSubmitSuccess(true)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || '入库失败')
    } finally {
      setIsSubmitting(false)
    }
  }

  // 删除文件
  const handleRemoveFile = () => {
    setFile(null)
    setPreviewData(null)
    setError(null)
    setSubmitSuccess(false)
  }

  // 格式化文件大小
  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return `${bytes} B`
    if (bytes < 1024 * 1024) return `${(bytes / 1024).toFixed(1)} KB`
    return `${(bytes / 1024 / 1024).toFixed(1)} MB`
  }

  // 高亮文本计算
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

  return (
    <div className="flex h-screen bg-[#F3F4F6] font-sans text-slate-800 overflow-hidden selection:bg-indigo-100 selection:text-indigo-700">
      {/* ================= 左侧导航栏 ================= */}
      <aside className="w-[72px] bg-[#0F172A] flex flex-col items-center py-6 z-50 shadow-2xl">
        <div className="w-10 h-10 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl flex items-center justify-center shadow-lg shadow-indigo-500/30 mb-8 cursor-pointer hover:scale-105 transition-transform">
          <Sparkles className="text-white w-5 h-5" />
        </div>

        <div className="flex flex-col gap-6 w-full items-center">
          <NavIcon icon={<Layers className="w-5 h-5" />} active tooltip="工作台" />
          <NavIcon icon={<Database className="w-5 h-5" />} tooltip="知识库管理" />
          <NavIcon icon={<Cpu className="w-5 h-5" />} tooltip="模型设置" />
        </div>

        <div className="mt-auto flex flex-col gap-6 w-full items-center mb-4">
          <div className="w-8 h-8 rounded-full bg-gradient-to-br from-emerald-400 to-cyan-500" />
        </div>
      </aside>

      {/* ================= 主体区域 ================= */}
      <div className="flex-1 flex flex-col min-w-0 bg-white/50 backdrop-blur-3xl">
        {/* 顶部 Header */}
        <header className="h-16 px-8 flex justify-between items-center bg-white/80 backdrop-blur-md border-b border-slate-200/60 sticky top-0 z-40">
          <div className="flex items-center gap-4">
            <h1 className="text-xl font-bold bg-clip-text text-transparent bg-gradient-to-r from-slate-800 to-slate-600">
              数据清洗与切分
            </h1>
            {file && (
              <span className="px-2 py-0.5 rounded-md bg-indigo-50 text-indigo-600 text-xs font-semibold border border-indigo-100">
                {submitSuccess ? 'Saved' : 'Draft'}
              </span>
            )}
          </div>

          <div className="flex items-center gap-4">
            {previewData && (
              <div className="text-xs text-slate-500 font-mono">
                Est. Cost:{' '}
                <span className="text-emerald-600 font-bold">
                  ${(totalTokens * 0.0000001).toFixed(6)}
                </span>
              </div>
            )}

            {error && (
              <div className="flex items-center gap-2 text-red-600 text-xs bg-red-50 px-3 py-1.5 rounded-lg">
                <AlertCircle className="w-3 h-3" />
                {error}
              </div>
            )}

            {submitSuccess && (
              <div className="flex items-center gap-2 text-emerald-600 text-xs bg-emerald-50 px-3 py-1.5 rounded-lg">
                <CheckCircle2 className="w-3 h-3" />
                入库成功
              </div>
            )}

            <button
              onClick={handleSubmit}
              disabled={!previewData || isSubmitting || submitSuccess}
              className={cn(
                'px-4 py-2 text-sm font-medium rounded-lg flex items-center gap-2 transition-all',
                previewData && !isSubmitting && !submitSuccess
                  ? 'bg-slate-900 text-white hover:bg-slate-800 shadow-lg shadow-slate-900/20'
                  : 'bg-slate-200 text-slate-400 cursor-not-allowed'
              )}
            >
              {isSubmitting ? (
                <Loader2 className="w-4 h-4 animate-spin" />
              ) : (
                <Database className="w-4 h-4" />
              )}
              确认入库
            </button>
          </div>
        </header>

        {/* 核心三栏布局 */}
        <div className="flex-1 flex overflow-hidden relative">
          {/* --- 第一栏: 智能配置 --- */}
          <div className="w-[340px] bg-white border-r border-slate-200 flex flex-col z-20 shadow-[4px_0_24px_rgba(0,0,0,0.02)]">
            <div className="p-6 overflow-y-auto space-y-8 flex-1">
              {/* 切分策略 */}
              <Section title="切分策略 (Splitting)">
                <div className="space-y-6">
                  <RangeControl
                    label="Chunk Size"
                    value={chunkSize}
                    unit="chars"
                    min={100}
                    max={4000}
                    step={100}
                    onChange={setChunkSize}
                    desc="模型单次能处理的最大上下文片段"
                  />
                  <RangeControl
                    label="Overlap Window"
                    value={chunkOverlap}
                    unit="chars"
                    min={0}
                    max={Math.min(1000, chunkSize - 100)}
                    step={50}
                    onChange={setChunkOverlap}
                    desc="重叠区域，防止上下文在切分处丢失"
                  />

                  {file && (
                    <button
                      onClick={handleRegenerate}
                      disabled={isProcessing}
                      className="w-full py-2.5 bg-slate-100 hover:bg-slate-200 text-slate-700 font-medium rounded-xl transition flex items-center justify-center gap-2 text-sm"
                    >
                      {isProcessing ? (
                        <Loader2 className="w-4 h-4 animate-spin" />
                      ) : (
                        <Sparkles className="w-4 h-4" />
                      )}
                      {isProcessing ? '生成中...' : '重新生成预览'}
                    </button>
                  )}
                </div>
              </Section>

              {/* 数据清洗 */}
              <Section title="数据清洗 (Cleaning)">
                <div className="space-y-2 bg-slate-50 p-4 rounded-xl border border-slate-100">
                  <ToggleItem
                    label="合并多余空格/换行"
                    active={cleaningRules.removeExtraSpaces}
                    onClick={() =>
                      setCleaningRules((p) => ({ ...p, removeExtraSpaces: !p.removeExtraSpaces }))
                    }
                  />
                  <ToggleItem
                    label="移除所有 URL 链接"
                    active={cleaningRules.removeUrls}
                    onClick={() =>
                      setCleaningRules((p) => ({ ...p, removeUrls: !p.removeUrls }))
                    }
                  />
                  <ToggleItem
                    label="强制修复 UTF-8 乱码"
                    active={cleaningRules.fixEncoding}
                    onClick={() =>
                      setCleaningRules((p) => ({ ...p, fixEncoding: !p.fixEncoding }))
                    }
                  />
                </div>
              </Section>

              {/* 统计仪表盘 */}
              <div className="bg-gradient-to-br from-indigo-500 to-violet-600 rounded-xl p-5 text-white shadow-lg shadow-indigo-500/20">
                <div className="text-xs font-medium text-indigo-100 mb-4 uppercase tracking-wider">
                  Estimated Stats
                </div>
                {previewData ? (
                  <div className="grid grid-cols-2 gap-4">
                    <div>
                      <div className="text-2xl font-bold">{previewData.total_chunks}</div>
                      <div className="text-[10px] text-indigo-200">Total Chunks</div>
                    </div>
                    <div>
                      <div className="text-2xl font-bold">{Math.round(totalTokens / 1000)}k</div>
                      <div className="text-[10px] text-indigo-200">Total Tokens</div>
                    </div>
                    <div>
                      <div className="text-2xl font-bold">
                        {Math.round(previewData.total_characters / previewData.total_chunks)}
                      </div>
                      <div className="text-[10px] text-indigo-200">Avg Chars/Chunk</div>
                    </div>
                    <div>
                      <div className="text-2xl font-bold">
                        {Math.round((chunkOverlap / chunkSize) * 100)}%
                      </div>
                      <div className="text-[10px] text-indigo-200">Overlap Rate</div>
                    </div>
                  </div>
                ) : (
                  <div className="text-center py-4 text-indigo-200 text-sm">
                    {isProcessing ? '正在分析...' : '上传文件查看统计'}
                  </div>
                )}
              </div>
            </div>
          </div>

          {/* --- 第二栏: 文件交互区 --- */}
          <div className="flex-1 flex flex-col bg-[#FAFAFA] relative min-w-0">
            {!file ? (
              <div className="absolute inset-0 flex items-center justify-center p-8">
                <div
                  className={cn(
                    'w-full max-w-lg aspect-[4/3] rounded-3xl border-2 border-dashed transition-all cursor-pointer flex flex-col items-center justify-center group bg-white',
                    isDragging
                      ? 'border-indigo-500 bg-indigo-50/50 scale-[1.02]'
                      : 'border-slate-300 hover:border-indigo-500 hover:bg-indigo-50/30'
                  )}
                  onDragOver={handleDragOver}
                  onDragLeave={handleDragLeave}
                  onDrop={handleDrop}
                  onClick={() => document.getElementById('file-input')?.click()}
                >
                  <input
                    id="file-input"
                    type="file"
                    accept=".pdf,.txt,.md"
                    className="hidden"
                    onChange={handleFileSelect}
                  />
                  <div className="w-20 h-20 bg-indigo-50 rounded-full flex items-center justify-center mb-6 group-hover:scale-110 transition-transform shadow-inner">
                    <Upload className="w-8 h-8 text-indigo-600" />
                  </div>
                  <h3 className="text-lg font-bold text-slate-700">点击上传知识文档</h3>
                  <p className="text-sm text-slate-400 mt-2">PDF, Markdown, TXT (Max 50MB)</p>
                </div>
              </div>
            ) : (
              <div className="flex flex-col h-full">
                {/* 文件信息栏 */}
                <div className="px-6 py-4 border-b border-slate-200 flex justify-between items-center bg-white">
                  <div className="flex items-center gap-3">
                    <div
                      className={cn(
                        'p-2 rounded-lg',
                        file.name.endsWith('.pdf')
                          ? 'bg-red-50'
                          : file.name.endsWith('.md')
                          ? 'bg-purple-50'
                          : 'bg-blue-50'
                      )}
                    >
                      <FileText
                        className={cn(
                          'w-5 h-5',
                          file.name.endsWith('.pdf')
                            ? 'text-red-500'
                            : file.name.endsWith('.md')
                            ? 'text-purple-500'
                            : 'text-blue-500'
                        )}
                      />
                    </div>
                    <div>
                      <div className="font-bold text-sm text-slate-800">{file.name}</div>
                      <div className="text-[10px] text-slate-400">
                        {formatFileSize(file.size)}
                        {previewData && ' · Parsed successfully'}
                        {isProcessing && ' · Processing...'}
                      </div>
                    </div>
                  </div>
                  <button
                    onClick={handleRemoveFile}
                    className="p-2 hover:bg-slate-100 rounded-full text-slate-400 hover:text-red-500 transition-colors"
                  >
                    <Trash2 className="w-4 h-4" />
                  </button>
                </div>

                {/* 原文预览 */}
                <div className="flex-1 p-6 overflow-y-auto">
                  {previewData?.original_text ? (
                    <div className="font-mono text-sm leading-7 text-slate-600 whitespace-pre-wrap">
                      {hoveredChunkIndex !== null && getHighlightedText ? (
                        <>
                          <span className="text-slate-300">{getHighlightedText.before}</span>
                          <mark className="bg-yellow-100 text-slate-800 px-0.5 rounded">
                            {getHighlightedText.highlighted}
                          </mark>
                          <span className="text-slate-300">{getHighlightedText.after}</span>
                        </>
                      ) : (
                        previewData.original_text
                      )}
                    </div>
                  ) : isProcessing ? (
                    <div className="flex items-center justify-center h-full">
                      <div className="text-center">
                        <Loader2 className="w-8 h-8 animate-spin text-indigo-500 mx-auto mb-3" />
                        <p className="text-slate-500">正在解析文档...</p>
                      </div>
                    </div>
                  ) : (
                    <div className="flex items-center justify-center h-full text-slate-400">
                      等待解析完成
                    </div>
                  )}
                </div>
              </div>
            )}
          </div>

          {/* --- 第三栏: 结果预览 --- */}
          <div className="w-[420px] bg-white border-l border-slate-200 flex flex-col z-20">
            {/* 顶部工具栏 */}
            <div className="p-4 border-b border-slate-100 space-y-3 bg-white/50 backdrop-blur">
              <div className="flex items-center justify-between">
                <span className="text-xs font-bold text-slate-500 flex items-center gap-2">
                  {previewData && <CheckCircle2 className="w-3 h-3 text-green-500" />}
                  PREVIEW {previewData && `(${filteredChunks.length})`}
                </span>
                <div className="flex bg-slate-100 rounded-lg p-0.5">
                  <button
                    onClick={() => setViewMode('card')}
                    className={cn(
                      'p-1.5 rounded-md transition-all',
                      viewMode === 'card' ? 'bg-white shadow text-slate-800' : 'text-slate-400'
                    )}
                  >
                    <Layers className="w-3 h-3" />
                  </button>
                  <button
                    onClick={() => setViewMode('json')}
                    className={cn(
                      'p-1.5 rounded-md transition-all',
                      viewMode === 'json' ? 'bg-white shadow text-slate-800' : 'text-slate-400'
                    )}
                  >
                    <Code className="w-3 h-3" />
                  </button>
                </div>
              </div>

              <div className="relative">
                <Search className="w-4 h-4 text-slate-400 absolute left-3 top-2.5" />
                <input
                  type="text"
                  placeholder="搜索切块内容..."
                  value={searchQuery}
                  onChange={(e) => setSearchQuery(e.target.value)}
                  className="w-full bg-slate-50 border border-slate-200 rounded-lg pl-9 pr-3 py-2 text-xs focus:ring-2 focus:ring-indigo-500 focus:border-transparent outline-none transition-all"
                />
              </div>
            </div>

            {/* 切块列表 */}
            <div className="flex-1 overflow-y-auto bg-slate-50/50 p-4">
              {viewMode === 'card' ? (
                filteredChunks.length > 0 ? (
                  <div className="space-y-3">
                    {filteredChunks.map((chunk, idx) => (
                      <div
                        key={chunk.index}
                        className={cn(
                          'group bg-white rounded-xl border p-4 transition-all cursor-default relative overflow-hidden',
                          hoveredChunkIndex === chunk.index
                            ? 'border-indigo-400 shadow-md shadow-indigo-500/10'
                            : 'border-slate-200 hover:shadow-md hover:border-indigo-300'
                        )}
                        onMouseEnter={() => setHoveredChunkIndex(chunk.index)}
                        onMouseLeave={() => setHoveredChunkIndex(null)}
                      >
                        {/* 左侧装饰条 */}
                        <div
                          className={cn(
                            'absolute left-0 top-0 bottom-0 w-1 transition-colors',
                            hoveredChunkIndex === chunk.index ? 'bg-indigo-500' : 'bg-slate-200'
                          )}
                        />

                        <div className="flex justify-between items-start mb-3 pl-2">
                          <span
                            className={cn(
                              'inline-flex items-center px-2 py-1 rounded text-[10px] font-medium transition-colors',
                              hoveredChunkIndex === chunk.index
                                ? 'bg-indigo-100 text-indigo-700'
                                : 'bg-slate-100 text-slate-600'
                            )}
                          >
                            CHUNK #{chunk.index + 1}
                          </span>
                          <span className="text-[10px] text-slate-400 font-mono flex items-center gap-1">
                            {chunk.page_number && (
                              <span className="bg-slate-100 px-1.5 py-0.5 rounded mr-1">
                                P{chunk.page_number}
                              </span>
                            )}
                            <Cpu className="w-3 h-3" />
                            {Math.round(chunk.length * 0.4)} tokens
                          </span>
                        </div>

                        <p className="text-xs text-slate-600 leading-relaxed pl-2 line-clamp-4">
                          {chunk.content}
                        </p>
                      </div>
                    ))}
                  </div>
                ) : previewData ? (
                  <div className="text-center text-slate-400 mt-20 text-xs">
                    {searchQuery ? '没有匹配的切块' : '暂无切块数据'}
                  </div>
                ) : isProcessing ? (
                  <div className="flex items-center justify-center h-full">
                    <div className="text-center">
                      <Loader2 className="w-8 h-8 animate-spin text-indigo-500 mx-auto mb-3" />
                      <p className="text-slate-500 text-sm">正在生成切块...</p>
                    </div>
                  </div>
                ) : (
                  <div className="flex items-center justify-center h-full text-slate-400">
                    <div className="text-center">
                      <Layers className="w-10 h-10 mx-auto mb-3 opacity-50" />
                      <p className="text-sm">上传文件查看切块预览</p>
                    </div>
                  </div>
                )
              ) : (
                <pre className="text-[10px] font-mono bg-slate-900 text-slate-300 p-4 rounded-xl overflow-x-auto">
                  {JSON.stringify(filteredChunks, null, 2)}
                </pre>
              )}
            </div>
          </div>
        </div>
      </div>
    </div>
  )
}

// ================== 子组件 ==================

function NavIcon({
  icon,
  active,
  tooltip,
}: {
  icon: React.ReactNode
  active?: boolean
  tooltip: string
}) {
  return (
    <div className="group relative flex justify-center">
      <button
        className={cn(
          'p-3 rounded-xl transition-all duration-300',
          active
            ? 'bg-indigo-600 text-white shadow-lg shadow-indigo-500/40'
            : 'text-slate-400 hover:bg-slate-800 hover:text-white'
        )}
      >
        {icon}
      </button>
      <span className="absolute left-14 top-1/2 -translate-y-1/2 bg-slate-800 text-white text-[10px] px-2 py-1 rounded opacity-0 group-hover:opacity-100 transition-opacity pointer-events-none whitespace-nowrap z-50">
        {tooltip}
      </span>
    </div>
  )
}

function Section({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <div>
      <h3 className="text-xs font-bold text-slate-900 mb-4 flex items-center gap-2 uppercase tracking-wider">
        <Settings2 className="w-3 h-3 text-slate-400" />
        {title}
      </h3>
      {children}
    </div>
  )
}

function RangeControl({
  label,
  value,
  min,
  max,
  step,
  onChange,
  unit,
  desc,
}: {
  label: string
  value: number
  min: number
  max: number
  step: number
  onChange: (v: number) => void
  unit: string
  desc: string
}) {
  return (
    <div className="group">
      <div className="flex justify-between mb-2">
        <label className="text-xs font-medium text-slate-600 group-hover:text-indigo-600 transition-colors">
          {label}
        </label>
        <span className="text-xs font-mono bg-slate-100 px-1.5 rounded text-slate-600">
          {value} {unit}
        </span>
      </div>
      <input
        type="range"
        min={min}
        max={max}
        step={step}
        value={value}
        onChange={(e) => onChange(Number(e.target.value))}
        className="w-full h-1.5 bg-slate-200 rounded-lg appearance-none cursor-pointer accent-indigo-600 hover:accent-indigo-500 transition-all"
      />
      <p className="text-[10px] text-slate-400 mt-1.5">{desc}</p>
    </div>
  )
}

function ToggleItem({
  label,
  active,
  onClick,
}: {
  label: string
  active: boolean
  onClick: () => void
}) {
  return (
    <div
      onClick={onClick}
      className={cn(
        'flex items-center justify-between p-2.5 rounded-lg cursor-pointer transition-all',
        active
          ? 'bg-indigo-50 border border-indigo-100'
          : 'hover:bg-slate-100 border border-transparent'
      )}
    >
      <span className={cn('text-xs', active ? 'text-indigo-700 font-medium' : 'text-slate-600')}>
        {label}
      </span>
      <div
        className={cn(
          'w-8 h-4 rounded-full relative transition-colors',
          active ? 'bg-indigo-500' : 'bg-slate-300'
        )}
      >
        <div
          className={cn(
            'absolute top-0.5 w-3 h-3 bg-white rounded-full shadow transition-all',
            active ? 'left-[18px]' : 'left-0.5'
          )}
        />
      </div>
    </div>
  )
}
