/**
 * 知识加工工作台 - 切块预览组件
 * 大厂风格设计：沉浸式、可视化、编辑器级体验
 */
'use client'

import { useState, useCallback, useMemo, useEffect } from 'react'
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
  MousePointer2,
  BookOpen,
  Folder,
  File as FileIcon,
  Trash2,
  ChevronRight,
  ChevronDown,
  Cpu,
  ScanLine,
  Database,
  MessageSquare,
  FileUp
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { documentApi } from '@/lib/api-client'
import type { ChunkPreviewResponse, ChunkPreviewItem } from '@/types'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { getParserLabel } from '@/lib/parser-options'
import { getChunkStrategyLabel, getChunkStrategyOption } from '@/lib/chunk-strategies'
import { ChunkStrategyDropdown } from '@/components/ui/chunk-strategy-dropdown'
import { ParserDropdown } from '@/components/ui/parser-dropdown'
import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { useParsedFiles } from '@/hooks/use-parsed-files'
import { cn } from '@/lib/utils'

// 分隔符配置
const SEPARATORS = ['\\n\\n', '\\n', '。', '！', '？', '.', '!', '?']

// 递归扫描文件
async function scanFiles(items: DataTransferItemList): Promise<File[]> {
  const files: File[] = []
  
  const entries: FileSystemEntry[] = []
  for (let i = 0; i < items.length; i++) {
    const entry = items[i].webkitGetAsEntry()
    if (entry) entries.push(entry)
  }

  const traverse = async (entry: FileSystemEntry) => {
    if (entry.isFile) {
      const file = await new Promise<File>((resolve, reject) => {
        (entry as FileSystemFileEntry).file(resolve, reject)
      })
      files.push(file)
    } else if (entry.isDirectory) {
      const dirReader = (entry as FileSystemDirectoryEntry).createReader()
      const entries = await new Promise<FileSystemEntry[]>((resolve, reject) => {
        dirReader.readEntries(resolve, reject)
      })
      for (const child of entries) {
        await traverse(child)
      }
    }
  }

  for (const entry of entries) {
    await traverse(entry)
  }

  return files
}

const EXAMPLE_TEXT = `# 检索增强生成 (RAG) 简介

检索增强生成（Retrieval-Augmented Generation，简称 RAG）是一种赋予大型语言模型（LLM）从外部知识库检索相关信息能力的技术。

## 为什么需要 RAG？
虽然 LLM 拥有强大的通用知识，但在处理特定领域、私有数据或最新信息时往往力不从心。RAG 通过连接外部数据源，解决了以下问题：
1. **幻觉问题**：模型不再凭空捏造，而是基于检索到的事实生成回答。
2. **知识时效性**：无需重新训练模型即可更新知识库。
3. **数据隐私**：可以将敏感数据保存在本地知识库中，仅在生成时检索相关片段。

## RAG 的工作流程
1. **文档加载与切分**：将长文档切分为较小的文本块（Chunks）。
2. **向量化（Embedding）**：将文本块转化为向量存储在向量数据库中。
3. **检索（Retrieval）**：根据用户问题的向量，在数据库中查找最相似的文本块。
4. **生成（Generation）**：将检索到的上下文和用户问题一起发送给 LLM，生成最终回答。

通过合理的切片策略（Chunking Strategy），我们可以显著提升 RAG 系统的检索准确率和回答质量。`

interface ChunkPreviewProps {
  onConfirm?: (params: { chunk_size: number; chunk_overlap: number }) => void
  onClose?: () => void
}

export function ChunkPreview({ onConfirm, onClose }: ChunkPreviewProps) {
  // 文件状态
  const [fileList, setFileList] = useState<File[]>([])
  const { files: parsedFiles } = useParsedFiles()
  const [currentFileIndex, setCurrentFileIndex] = useState<number>(0)
  const file = fileList[currentFileIndex] || null
  const [isDragging, setIsDragging] = useState(false)

  // Initialize from parsedFiles context
  useEffect(() => {
    // Only load if fileList is empty and we have parsed files
    // This prevents overwriting user's dropped files
    if (fileList.length === 0 && parsedFiles.length > 0) {
      const convertedFiles = parsedFiles.map(pf => {
        // Create a File object from the markdown content
        // Note: We use the original filename but enforce .md extension if it was converted
        // or keep original extension if it's treated as raw text
        const content = pf.markdownContent || ''
        const filename = pf.filename.endsWith('.md') ? pf.filename : `${pf.filename}.md`
        return new File([content], filename, { type: 'text/markdown' })
      })
      setFileList(convertedFiles)
    }
  }, [parsedFiles, fileList.length])

  // 批量处理状态
  const [processedStatus, setProcessedStatus] = useState<Record<string, 'pending' | 'success' | 'error'>>({})

  // 参数状态
  const { enabled: pipelineOverridesEnabled, options: pipelineOptions, updateOption } = usePipelineOptions()
  const [chunkSize, setChunkSize] = useState(pipelineOptions.chunk_size ?? 1000)
  const [chunkOverlap, setChunkOverlap] = useState(pipelineOptions.chunk_overlap ?? 200)

  // 预览结果
  const [previewData, setPreviewData] = useState<ChunkPreviewResponse | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [submitSuccess, setSubmitSuccess] = useState(false)

  // 选中的块索引（用于高亮联动）
  const [hoveredChunkIndex, setHoveredChunkIndex] = useState<number | null>(null)
  const { parserBackend, setParserBackend } = useParserBackendPreference()
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

  useEffect(() => {
    if (typeof pipelineOptions.chunk_size === 'number' && pipelineOptions.chunk_size !== chunkSize) {
      setChunkSize(pipelineOptions.chunk_size)
    }
  }, [pipelineOptions.chunk_size, chunkSize])

  useEffect(() => {
    if (typeof pipelineOptions.chunk_overlap === 'number' && pipelineOptions.chunk_overlap !== chunkOverlap) {
      setChunkOverlap(pipelineOptions.chunk_overlap)
    }
  }, [pipelineOptions.chunk_overlap, chunkOverlap])

  // 处理文件拖放
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    
    if (e.dataTransfer.items) {
      const files = await scanFiles(e.dataTransfer.items)
      if (files.length > 0) {
        setFileList(prev => [...prev, ...files])
        setPreviewData(null)
        setError(null)
        setSubmitSuccess(false)
      }
    } else if (e.dataTransfer.files.length > 0) {
       setFileList(prev => [...prev, ...Array.from(e.dataTransfer.files)])
       setPreviewData(null)
       setError(null)
       setSubmitSuccess(false)
    }
  }, [])

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = e.target.files
    if (selectedFiles && selectedFiles.length > 0) {
      setFileList(prev => [...prev, ...Array.from(selectedFiles)])
      setPreviewData(null)
      setError(null)
      setSubmitSuccess(false)
    }
  }, [])

  const handleUseExample = useCallback(() => {
    const blob = new Blob([EXAMPLE_TEXT], { type: 'text/plain' })
    const exampleFile = new File([blob], 'rag-introduction.md', { type: 'text/markdown' })
    setFileList([exampleFile])
    setCurrentFileIndex(0)
    setPreviewData(null)
    setError(null)
    setSubmitSuccess(false)
  }, [])

  const handleRemoveFile = useCallback((index: number) => {
    setFileList(prev => {
      const newList = [...prev]
      newList.splice(index, 1)
      return newList
    })
    if (currentFileIndex >= index && currentFileIndex > 0) {
      setCurrentFileIndex(prev => prev - 1)
    }
    setPreviewData(null)
  }, [currentFileIndex])

  const handleSelectFile = useCallback((index: number) => {
    setCurrentFileIndex(index)
    setPreviewData(null)
    setError(null)
    setSubmitSuccess(false)
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
        pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
      })
      setPreviewData(data)
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || '预览失败')
    } finally {
      setIsLoading(false)
    }
  }, [file, chunkSize, chunkOverlap, parserBackend, chunkStrategy, pipelineOverridesEnabled, pipelineOptions])

  // 自动触发预览
  useEffect(() => {
    if (file && !previewData && !isLoading && !isSubmitting) {
      handlePreview()
    }
  }, [file, previewData, isLoading, isSubmitting, handlePreview])

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

      const pipeline = pipelineOverridesEnabled
        ? {
            governance_enabled: pipelineOptions.governance_enabled,
            governance_remove_toc_lines: pipelineOptions.governance_remove_toc_lines,
            governance_remove_noise_lines: pipelineOptions.governance_remove_noise_lines,
            governance_unwrap_lines: pipelineOptions.governance_unwrap_lines,
            governance_remove_common_lines: pipelineOptions.governance_remove_common_lines,
            governance_unwrap_max_line_length: pipelineOptions.governance_unwrap_max_line_length,
            governance_noise_min_chars: pipelineOptions.governance_noise_min_chars,
            governance_noise_ratio_threshold: pipelineOptions.governance_noise_ratio_threshold,
            governance_common_lines_min_docs: pipelineOptions.governance_common_lines_min_docs,
            governance_common_lines_min_ratio: pipelineOptions.governance_common_lines_min_ratio,
            chunk_size: chunkSize,
            chunk_overlap: chunkOverlap,
            chunk_vector_enabled: pipelineOptions.chunk_vector_enabled,
            bm25_index_enabled: pipelineOptions.bm25_index_enabled,
            kg_enabled: pipelineOptions.kg_enabled,
            event_vector_enabled: pipelineOptions.event_vector_enabled,
            entity_vector_enabled: pipelineOptions.entity_vector_enabled,
          }
        : undefined

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
        pipeline,
      })

      setSubmitSuccess(true)
      setProcessedStatus(prev => ({ ...prev, [file.name]: 'success' }))
      onConfirm?.({ chunk_size: chunkSize, chunk_overlap: chunkOverlap })
    } catch (err: any) {
      setError(err.response?.data?.detail || err.message || '入库失败')
      setProcessedStatus(prev => ({ ...prev, [file.name]: 'error' }))
    } finally {
      setIsSubmitting(false)
    }
  }, [previewData, file, chunkSize, chunkOverlap, pipelineOverridesEnabled, pipelineOptions, onConfirm])

  // 重置
  const handleReset = useCallback(() => {
    setFileList([])
    setCurrentFileIndex(0)
    setPreviewData(null)
    setError(null)
    setSubmitSuccess(false)
    setChunkSize(1000)
    setChunkOverlap(200)
    updateOption('chunk_size', 1000)
    updateOption('chunk_overlap', 200)
  }, [updateOption])

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
  if (fileList.length === 0) {
    return (
      <div className="relative min-h-full w-full bg-[#FAFAFA] text-slate-900 font-sans flex flex-col items-center justify-center p-6 overflow-hidden selection:bg-indigo-100 selection:text-indigo-900">
        
        {/* 背景光晕 */}
        <div className="absolute top-[-20%] left-[-10%] w-[50%] h-[50%] rounded-full bg-gradient-to-br from-blue-100/40 to-indigo-100/40 blur-[120px] pointer-events-none mix-blend-multiply" />
        <div className="absolute bottom-[-20%] right-[-10%] w-[50%] h-[50%] rounded-full bg-gradient-to-tl from-purple-100/40 to-pink-100/40 blur-[120px] pointer-events-none mix-blend-multiply" />
        <div className="absolute inset-0 bg-[linear-gradient(to_right,#80808008_1px,transparent_1px),linear-gradient(to_bottom,#80808008_1px,transparent_1px)] bg-[size:32px_32px] [mask-image:radial-gradient(ellipse_60%_50%_at_50%_0%,#000_70%,transparent_100%)] pointer-events-none" />

        <div className="relative w-full max-w-4xl flex flex-col items-center z-10">
          
          {/* Header Section */}
          <div className="text-center mb-12 animate-in slide-in-from-bottom-8 fade-in duration-700">
            <div className="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white border border-slate-200 shadow-sm mb-6">
              <span className="relative flex h-2 w-2">
                <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-indigo-400 opacity-75"></span>
                <span className="relative inline-flex rounded-full h-2 w-2 bg-indigo-500"></span>
              </span>
              <span className="text-xs font-semibold text-slate-600 tracking-wide uppercase">MimirQ RAG Engine</span>
            </div>
            
            <h1 className="text-5xl md:text-6xl font-bold tracking-tight text-slate-900 mb-6 bg-clip-text text-transparent bg-gradient-to-r from-slate-900 via-slate-700 to-slate-900">
              构建您的专属<br className="hidden md:block"/>
              <span className="text-indigo-600">智能知识库</span>
            </h1>
            <p className="text-lg md:text-xl text-slate-500 max-w-2xl mx-auto leading-relaxed font-light">
              上传文档，体验可视化的智能切片与语义分析。<br/>
              让 AI 精准理解每一份知识。
            </p>
          </div>

          {/* Main Upload Area */}
          <div 
            className={cn(
              "w-full max-w-3xl bg-white rounded-3xl p-2 shadow-2xl shadow-indigo-100/50 border border-slate-100 transition-all duration-300 animate-in slide-in-from-bottom-10 fade-in duration-700 delay-100",
              isDragging ? "scale-[1.01] ring-4 ring-indigo-100 border-indigo-300" : "hover:border-indigo-200"
            )}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <div 
              className={cn(
                "relative w-full h-64 border-2 border-dashed rounded-2xl flex flex-col items-center justify-center transition-colors duration-200 cursor-pointer overflow-hidden group",
                isDragging ? "border-indigo-500 bg-indigo-50/30" : "border-slate-200 hover:border-indigo-300 hover:bg-slate-50/50"
              )}
              onClick={() => document.getElementById('chunk-file-input')?.click()}
            >
              <input
                id="chunk-file-input"
                type="file"
                accept=".pdf,.txt,.md,.doc,.docx,.xls,.xlsx,.csv,.html,.json"
                multiple
                className="hidden"
                onChange={handleFileSelect}
              />
              
              <div className="w-16 h-16 bg-white rounded-2xl shadow-sm border border-slate-100 flex items-center justify-center mb-6 group-hover:scale-110 group-hover:shadow-md transition-all duration-300">
                <FileUp className={cn("w-8 h-8 transition-colors duration-300", isDragging ? "text-indigo-600" : "text-slate-400 group-hover:text-indigo-500")} />
              </div>

              <div className="text-center space-y-2 z-10">
                <h3 className="text-lg font-semibold text-slate-700 group-hover:text-indigo-700 transition-colors">
                  {isDragging ? '松开鼠标上传文件' : '点击或拖拽上传文档'}
                </h3>
                <p className="text-sm text-slate-400">
                  支持 PDF, Markdown, TXT 文件夹批量上传
                </p>
              </div>

              {/* Decorative grid inside upload area */}
              <div className="absolute inset-0 opacity-[0.03] bg-[radial-gradient(#4f46e5_1px,transparent_1px)] [background-size:16px_16px] pointer-events-none" />
            </div>
          </div>

          {/* Quick Actions & Features */}
          <div className="w-full max-w-3xl mt-8 grid grid-cols-1 md:grid-cols-3 gap-4 animate-in slide-in-from-bottom-12 fade-in duration-700 delay-200">
            {/* Action Card: Example */}
            <div 
              onClick={(e) => {
                e.stopPropagation()
                handleUseExample()
              }}
              className="group bg-white p-5 rounded-2xl border border-slate-100 shadow-sm hover:shadow-md hover:border-indigo-100 cursor-pointer transition-all duration-200 flex flex-col items-start gap-3"
            >
              <div className="p-2 rounded-lg bg-orange-50 text-orange-600 group-hover:bg-orange-100 transition-colors">
                <BookOpen className="w-5 h-5" />
              </div>
              <div>
                <h4 className="font-semibold text-slate-800 text-sm">试用示例文档</h4>
                <p className="text-xs text-slate-500 mt-1">无需上传，一键体验 RAG 流程</p>
              </div>
            </div>

            {/* Feature: Smart Chunking */}
            <div className="bg-white/60 p-5 rounded-2xl border border-slate-100 flex flex-col items-start gap-3">
              <div className="p-2 rounded-lg bg-blue-50 text-blue-600">
                <ScanLine className="w-5 h-5" />
              </div>
              <div>
                <h4 className="font-semibold text-slate-800 text-sm">智能切片</h4>
                <p className="text-xs text-slate-500 mt-1">可视化调整 Chunk Size 与 Overlap</p>
              </div>
            </div>

            {/* Feature: Embedding */}
            <div className="bg-white/60 p-5 rounded-2xl border border-slate-100 flex flex-col items-start gap-3">
              <div className="p-2 rounded-lg bg-purple-50 text-purple-600">
                <Cpu className="w-5 h-5" />
              </div>
              <div>
                <h4 className="font-semibold text-slate-800 text-sm">深度解析</h4>
                <p className="text-xs text-slate-500 mt-1">支持多格式解析与语义向量化</p>
              </div>
            </div>
          </div>

        </div>
      </div>
    )
  }

  // Ensure file is not null for main view (though length check handles it)
  if (!file) return null

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
              <span className="bg-gray-100 px-1.5 rounded text-gray-600 font-bold">{currentFileIndex + 1}/{fileList.length}</span>
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
            {/* 文件列表 */}
            <div className="mb-8 pb-8 border-b border-gray-200">
               <div className="flex items-center justify-between mb-4">
                  <div className="flex items-center gap-2">
                    <Folder className="w-4 h-4 text-gray-500" />
                    <h2 className="text-xs font-bold text-gray-900 uppercase tracking-wider">文件列表 ({fileList.length})</h2>
                  </div>
                  <Button variant="ghost" size="sm" onClick={() => document.getElementById('add-file-input')?.click()} className="h-6 w-6 p-0">
                    <Upload className="w-3.5 h-3.5 text-gray-500" />
                  </Button>
                  <input
                    id="add-file-input"
                    type="file"
                    accept=".pdf,.txt,.md,.doc,.docx,.xls,.xlsx,.csv,.html,.json"
                    multiple
                    className="hidden"
                    onChange={handleFileSelect}
                  />
               </div>
               
               <div className="space-y-2 max-h-[200px] overflow-y-auto custom-scrollbar pr-1">
                 {fileList.map((f, idx) => (
                   <div 
                      key={`${f.name}-${idx}`}
                      onClick={() => handleSelectFile(idx)}
                      className={cn(
                        "group flex items-center justify-between p-2 rounded-lg text-xs cursor-pointer transition-colors border",
                        idx === currentFileIndex 
                          ? "bg-white border-blue-200 shadow-sm ring-1 ring-blue-100" 
                          : "bg-transparent border-transparent hover:bg-gray-100 hover:border-gray-200"
                      )}
                   >
                     <div className="flex items-center gap-2 min-w-0 flex-1">
                       <FileIcon className={cn("w-3.5 h-3.5 flex-shrink-0", idx === currentFileIndex ? "text-blue-600" : "text-gray-400")} />
                       <span className={cn("truncate font-medium", idx === currentFileIndex ? "text-gray-900" : "text-gray-600")}>{f.name}</span>
                     </div>
                     
                     <div className="flex items-center gap-1 flex-shrink-0">
                       {processedStatus[f.name] === 'success' && <Check className="w-3.5 h-3.5 text-green-500" />}
                       {processedStatus[f.name] === 'error' && <AlertCircle className="w-3.5 h-3.5 text-red-500" />}
                       
                       <div 
                         onClick={(e) => {
                           e.stopPropagation()
                           handleRemoveFile(idx)
                         }}
                         className="opacity-0 group-hover:opacity-100 p-1 hover:bg-red-50 hover:text-red-600 rounded transition-all"
                       >
                         <Trash2 className="w-3 h-3" />
                       </div>
                     </div>
                   </div>
                 ))}
               </div>
            </div>

            <div className="flex items-center gap-2 mb-6">
               <Settings className="w-4 h-4 text-gray-500" />
               <h2 className="text-xs font-bold text-gray-900 uppercase tracking-wider">配置参数</h2>
            </div>

            <div className="space-y-8">
              {/* 解析器选择 */}
              <div className="space-y-2">
                <label className="text-xs font-medium text-gray-500">解析器</label>
                <ParserDropdown value={parserBackend} onChange={setParserBackend} />
              </div>

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
                    onChange={(e) => {
                      const next = Number(e.target.value)
                      setChunkSize(next)
                      updateOption('chunk_size', next)
                    }}
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
                    onChange={(e) => {
                      const next = Number(e.target.value)
                      setChunkOverlap(next)
                      updateOption('chunk_overlap', next)
                    }}
                    className="w-full h-1.5 bg-gray-200 rounded-full appearance-none cursor-pointer accent-blue-600 hover:accent-blue-700 transition-colors"
                  />
                </div>
              )}

              <div className="space-y-2">
                <label className="text-xs font-medium text-gray-500">入库管线</label>
                <PipelineOptionsPanel compact />
              </div>

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
