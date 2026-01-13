/**
 * 手动切片上传对话框
 */
'use client'

import { useState, useMemo, ChangeEvent, useRef, useEffect, useCallback } from 'react'
import { Upload, Loader2, FileText, Settings2, Scissors, AlignJustify, Hash, FileType } from 'lucide-react'

import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogDescription,
  DialogTrigger,
  DialogFooter,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { documentApi } from '@/lib/api-client'
import { formatFileSize } from '@/lib/utils'
import type { DocumentPreview, ManualChunk } from '@/types'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { getParserLabel } from '@/lib/parser-options'
import { cn } from '@/lib/utils'
import { formatApiError } from '@/lib/api-errors'
import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { ParserDropdown } from '@/components/ui/parser-dropdown'

interface ManualUploadDialogProps {
  onUploaded?: () => void
}

type ChunkMode = 'page' | 'length' | 'delimiter'

export function ManualUploadDialog({ onUploaded }: ManualUploadDialogProps) {
  const [open, setOpen] = useState(false)
  const [file, setFile] = useState<File | null>(null)
  const [preview, setPreview] = useState<DocumentPreview | null>(null)
  const [isParsing, setIsParsing] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [error, setError] = useState<string | null>(null)

  const [mode, setMode] = useState<ChunkMode>('page')
  const { enabled: pipelineOverridesEnabled, options: pipelineOptions, updateOption } = usePipelineOptions()
  const [chunkSize, setChunkSize] = useState(pipelineOptions.chunk_size ?? 1000)
  const [chunkOverlap, setChunkOverlap] = useState(pipelineOptions.chunk_overlap ?? 200)
  const [delimiter, setDelimiter] = useState('## ')
  const { parserBackend, setParserBackend } = useParserBackendPreference()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const previewAbortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    return () => {
      previewAbortRef.current?.abort()
    }
  }, [])

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

  const handleFileChange = async (e: ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    const selected = files[0]
    previewAbortRef.current?.abort()
    const controller = new AbortController()
    previewAbortRef.current = controller
    setFile(selected)
    setPreview(null)
    setError(null)
    setIsParsing(true)

    try {
      const result = await documentApi.preview(
        selected,
        parserBackend,
        pipelineOverridesEnabled ? pipelineOptions : undefined,
        { signal: controller.signal }
      )
      setPreview(result)
    } catch (err: any) {
      if (controller.signal.aborted) return
      console.error('Preview parse failed:', err)
      setError(formatApiError(err, '文档解析失败'))
    } finally {
      if (previewAbortRef.current === controller) {
        previewAbortRef.current = null
      }
      setIsParsing(false)
      // 清空 input，方便下次选同一文件
      e.target.value = ''
    }
  }

  const buildChunks = useCallback((): ManualChunk[] => {
    if (!preview) return []

    const segments = preview.segments || []

    if (mode === 'page') {
      // 每个解析片段直接作为一个 chunk
      return segments.map((seg) => ({
        content: seg.content,
        page_number: seg.page_number,
        start_char: 0,
        end_char: seg.content.length,
        metadata: seg.metadata || {},
      }))
    }

    if (mode === 'length') {
      // 按长度切片（在每个 segment 内部按字符数分段）
      const chunks: ManualChunk[] = []

      segments.forEach((seg) => {
        const content = seg.content || ''
        const len = content.length
        if (len === 0) return

        let start = 0
        while (start < len) {
          const end = Math.min(start + chunkSize, len)
          const piece = content.slice(start, end)

          chunks.push({
            content: piece,
            page_number: seg.page_number,
            start_char: start,
            end_char: end,
            metadata: seg.metadata || {},
          })

          if (end >= len) break
          const nextStart = end - chunkOverlap
          start = nextStart > start ? nextStart : end
        }
      })

      return chunks
    }

    if (mode === 'delimiter') {
      const chunks: ManualChunk[] = []
      const fullText = segments.map((s) => s.content).join('\n')

      if (!delimiter || !fullText) {
        if (fullText) {
          chunks.push({
            content: fullText,
            page_number: segments[0]?.page_number,
            metadata: segments[0]?.metadata || {},
          })
        }
        return chunks
      }

      const parts = fullText.split(delimiter)
      parts.forEach((part, index) => {
        const trimmed = part.trim()
        if (!trimmed) return

        const content =
          index === 0 && !fullText.startsWith(delimiter)
            ? trimmed
            : `${delimiter}${trimmed}`

        chunks.push({
          content,
          page_number: segments[0]?.page_number,
          metadata: segments[0]?.metadata || {},
        })
      })

      return chunks
    }

    return []
  }, [preview, mode, chunkSize, chunkOverlap, delimiter])

  const chunkPreview = useMemo<ManualChunk[]>(() => buildChunks(), [buildChunks])

  const handleSubmit = async () => {
    if (!preview) return

    const chunks = buildChunks()
    if (!chunks.length) {
      setError('没有可用的切片，请检查切片设置')
      return
    }

    setIsSubmitting(true)
    setError(null)

    try {
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
        filename: preview.filename,
        file_type: preview.file_type,
        file_size: preview.file_size,
        chunks,
        metadata: {
          parser_backend: preview.parser_backend,
        },
        pipeline,
      })

      setOpen(false)
      setPreview(null)
      setFile(null)

      if (onUploaded) onUploaded()
    } catch (err: any) {
      console.error('Manual upload failed:', err)
      setError(formatApiError(err, '手动切片上传失败'))
    } finally {
      setIsSubmitting(false)
    }
  }

  const resetState = () => {
    setFile(null)
    setPreview(null)
    setError(null)
    setIsParsing(false)
    setIsSubmitting(false)
    setMode('page')
  }

  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        setOpen(next)
        if (!next) resetState()
      }}
    >
      <DialogTrigger asChild>
        <Button variant="outline" className="w-full mt-3 justify-center gap-2 border-dashed border-2 hover:border-blue-300 hover:bg-blue-50 text-gray-600 hover:text-blue-600">
          <Settings2 className="h-4 w-4" />
          <span className="text-sm font-medium">高级切片上传</span>
        </Button>
      </DialogTrigger>

      <DialogContent className="max-w-5xl h-[85vh] p-0 flex flex-col gap-0 overflow-hidden bg-gray-50/50">
        {/* Header */}
        <div className="bg-white px-6 py-4 border-b border-gray-100 flex items-center justify-between shrink-0">
          <div>
            <DialogTitle className="text-lg font-bold text-gray-900 flex items-center gap-2">
              <Scissors className="h-5 w-5 text-blue-600" />
              智能切片工坊
            </DialogTitle>
            <DialogDescription className="text-xs text-gray-500 mt-0.5">
              上传文档，实时预览并调整切片策略
            </DialogDescription>
          </div>
          {preview && (
            <div className="px-3 py-1 bg-blue-50 text-blue-700 text-xs font-medium rounded-full border border-blue-100 flex items-center gap-1.5">
               <FileType className="h-3 w-3" />
               {getParserLabel(preview.parser_backend)}
            </div>
          )}
        </div>

        <div className="flex-1 flex overflow-hidden">
          {/* 左侧：配置区 */}
          <div className="w-[400px] flex-shrink-0 bg-white border-r border-gray-100 p-6 flex flex-col gap-6 overflow-y-auto">
            
            {/* 1. 文件上传 */}
            <div className="space-y-3">
              <label className="text-sm font-semibold text-gray-900 flex items-center gap-2">
                <span className="w-5 h-5 rounded-full bg-gray-100 text-gray-600 flex items-center justify-center text-xs">1</span>
                源文档
              </label>

              <div className="space-y-2">
                <div className="text-xs font-medium text-gray-500">解析器</div>
                <ParserDropdown value={parserBackend} onChange={setParserBackend} />
              </div>
              
              <div 
                className={cn(
                  "border-2 border-dashed rounded-xl p-6 transition-all text-center cursor-pointer",
                  file ? "border-blue-200 bg-blue-50/30" : "border-gray-200 hover:border-blue-300 hover:bg-gray-50"
                )}
                onClick={() => fileInputRef.current?.click()}
              >
                <input 
                  ref={fileInputRef}
                  type="file" 
                  accept=".pdf,.txt,.md,.doc,.docx,.xls,.xlsx,.csv,.html,.json" 
                  className="hidden" 
                  onChange={handleFileChange} 
                />
                
                {isParsing ? (
                  <div className="flex flex-col items-center gap-2 py-2">
                    <Loader2 className="h-8 w-8 text-blue-500 animate-spin" />
                    <p className="text-sm text-blue-600 font-medium">正在解析结构...</p>
                  </div>
                ) : file ? (
                  <div className="flex flex-col items-center gap-1">
                    <div className="p-2 bg-blue-100 rounded-lg mb-1">
                      <FileText className="h-6 w-6 text-blue-600" />
                    </div>
                    <p className="text-sm font-medium text-gray-900 line-clamp-1 break-all px-2">
                      {file.name}
                    </p>
                    <p className="text-xs text-gray-500">
                      {formatFileSize(file.size)}
                    </p>
                    <p className="text-xs text-blue-600 mt-2 hover:underline">点击更换</p>
                  </div>
                ) : (
                  <div className="flex flex-col items-center gap-2 py-2">
                    <div className="p-2 bg-gray-100 rounded-lg">
                      <Upload className="h-6 w-6 text-gray-400" />
                    </div>
                    <p className="text-sm text-gray-600">点击上传 PDF, TXT, MD</p>
                  </div>
                )}
              </div>
            </div>

            {/* 2. 切片策略 */}
            <div className={cn("space-y-4 transition-opacity duration-300", !preview && "opacity-50 pointer-events-none")}>
              <label className="text-sm font-semibold text-gray-900 flex items-center gap-2">
                <span className="w-5 h-5 rounded-full bg-gray-100 text-gray-600 flex items-center justify-center text-xs">2</span>
                切片策略
              </label>

              <div className="grid grid-cols-3 gap-2 bg-gray-100/50 p-1 rounded-lg">
                <button
                  onClick={() => setMode('page')}
                  className={cn(
                    "flex flex-col items-center gap-1 py-2 px-1 rounded-md text-xs font-medium transition-all",
                    mode === 'page' ? "bg-white text-blue-600 shadow-sm" : "text-gray-500 hover:text-gray-700"
                  )}
                >
                  <FileType className="h-4 w-4" />
                  按页/段
                </button>
                <button
                  onClick={() => setMode('length')}
                  className={cn(
                    "flex flex-col items-center gap-1 py-2 px-1 rounded-md text-xs font-medium transition-all",
                    mode === 'length' ? "bg-white text-blue-600 shadow-sm" : "text-gray-500 hover:text-gray-700"
                  )}
                >
                  <AlignJustify className="h-4 w-4" />
                  按长度
                </button>
                <button
                  onClick={() => setMode('delimiter')}
                  className={cn(
                    "flex flex-col items-center gap-1 py-2 px-1 rounded-md text-xs font-medium transition-all",
                    mode === 'delimiter' ? "bg-white text-blue-600 shadow-sm" : "text-gray-500 hover:text-gray-700"
                  )}
                >
                  <Hash className="h-4 w-4" />
                  分隔符
                </button>
              </div>

              {/* 参数配置 */}
              <div className="bg-gray-50 rounded-xl p-4 border border-gray-100">
                {mode === 'page' && (
                  <p className="text-xs text-gray-500 leading-relaxed">
                    使用解析器默认的输出片段。对于 PDF 通常按页分割，对于 Markdown/Text 通常按段落分割。
                  </p>
                )}

                {mode === 'length' && (
                  <div className="space-y-4">
                    <div className="space-y-1.5">
                      <div className="flex justify-between">
                        <label className="text-xs font-medium text-gray-600">块大小 (Chars)</label>
                        <span className="text-xs text-blue-600 font-mono">{chunkSize}</span>
                      </div>
                      <input
                        type="range"
                        min={100}
                        max={2000}
                        step={50}
                        value={chunkSize}
                        onChange={(e) => {
                          const next = parseInt(e.target.value)
                          setChunkSize(next)
                          updateOption('chunk_size', next)
                        }}
                        className="w-full h-1.5 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
                      />
                    </div>
                    <div className="space-y-1.5">
                      <div className="flex justify-between">
                         <label className="text-xs font-medium text-gray-600">重叠 (Chars)</label>
                         <span className="text-xs text-blue-600 font-mono">{chunkOverlap}</span>
                      </div>
                      <input
                        type="range"
                        min={0}
                        max={500}
                        step={10}
                        value={chunkOverlap}
                        onChange={(e) => {
                          const next = parseInt(e.target.value)
                          setChunkOverlap(next)
                          updateOption('chunk_overlap', next)
                        }}
                        className="w-full h-1.5 bg-gray-200 rounded-lg appearance-none cursor-pointer accent-blue-600"
                      />
                    </div>
                  </div>
                )}

                {mode === 'delimiter' && (
                  <div className="space-y-2">
                    <label className="text-xs font-medium text-gray-600">分隔符</label>
                    <input
                      type="text"
                      value={delimiter}
                      onChange={(e) => setDelimiter(e.target.value)}
                      className="w-full border border-gray-200 rounded-lg px-3 py-2 text-sm font-mono focus:ring-2 focus:ring-blue-100 outline-none"
                      placeholder="例如：## "
                    />
                    <p className="text-[10px] text-gray-400">
                      支持字符串匹配，常用于 Markdown 标题分割。
                    </p>
                  </div>
                )}
              </div>
            </div>

            <div className={cn("space-y-3 transition-opacity duration-300", !preview && "opacity-50 pointer-events-none")}>
              <label className="text-sm font-semibold text-gray-900 flex items-center gap-2">
                <span className="w-5 h-5 rounded-full bg-gray-100 text-gray-600 flex items-center justify-center text-xs">3</span>
                入库管线
              </label>
              <PipelineOptionsPanel compact />
            </div>

            {error && (
              <div className="p-3 bg-red-50 text-red-600 text-xs rounded-lg border border-red-100 flex items-start gap-2">
                <Settings2 className="h-4 w-4 flex-shrink-0 mt-0.5" />
                <p>{error}</p>
              </div>
            )}
          </div>

          {/* 右侧：预览区 */}
          <div className="flex-1 bg-gray-50/50 p-6 overflow-hidden flex flex-col">
            <div className="flex items-center justify-between mb-4 shrink-0">
               <h3 className="text-sm font-semibold text-gray-900">
                 切片预览 
                 {preview && <span className="ml-2 text-gray-400 font-normal">({chunkPreview.length} 个块)</span>}
               </h3>
               {preview && (
                 <span className="text-xs text-gray-400">
                    总字符: {formatFileSize(preview.file_size)}
                 </span>
               )}
            </div>

            <div className="flex-1 overflow-y-auto pr-2 space-y-3 custom-scrollbar">
              {!preview ? (
                <div className="h-full flex flex-col items-center justify-center text-gray-400">
                  <Scissors className="h-12 w-12 mb-3 opacity-20" />
                  <p className="text-sm">上传文档后在此处查看实时切片效果</p>
                </div>
              ) : chunkPreview.length === 0 ? (
                <div className="h-full flex items-center justify-center text-gray-500 text-sm">
                  当前规则未生成任何切片
                </div>
              ) : (
                chunkPreview.slice(0, 100).map((chunk, index) => (
                  <div key={index} className="bg-white border border-gray-200 rounded-xl p-4 shadow-sm hover:border-blue-300 transition-colors group">
                    <div className="flex items-center justify-between mb-2">
                      <div className="flex items-center gap-2">
                         <span className="px-1.5 py-0.5 bg-gray-100 text-gray-500 rounded text-[10px] font-mono">
                           #{index + 1}
                         </span>
                         {typeof chunk.page_number === 'number' && (
                           <span className="text-[10px] text-gray-400">P.{chunk.page_number}</span>
                         )}
                      </div>
                      <span className="text-[10px] text-gray-300 group-hover:text-blue-400 font-mono">
                        {chunk.content.length} chars
                      </span>
                    </div>
                    <div className="text-xs text-gray-600 font-mono leading-relaxed whitespace-pre-wrap break-all bg-gray-50/50 p-2 rounded-lg border border-gray-50">
                      {chunk.content}
                    </div>
                  </div>
                ))
              )}
              {chunkPreview.length > 100 && (
                 <div className="text-center py-4 text-xs text-gray-400">
                   仅展示前 100 个切片，实际共 {chunkPreview.length} 个
                 </div>
              )}
            </div>
          </div>
        </div>

        {/* Footer */}
        <div className="bg-white p-4 border-t border-gray-100 flex justify-end gap-3 shrink-0">
          <Button variant="ghost" onClick={() => setOpen(false)} disabled={isSubmitting}>
            取消
          </Button>
          <Button 
            onClick={handleSubmit} 
            disabled={!preview || isSubmitting || chunkPreview.length === 0}
            className="bg-blue-600 hover:bg-blue-700 text-white shadow-lg shadow-blue-100 rounded-lg px-6"
          >
            {isSubmitting && <Loader2 className="mr-2 h-4 w-4 animate-spin" />}
            开始处理 ({chunkPreview.length} 块)
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  )
}
