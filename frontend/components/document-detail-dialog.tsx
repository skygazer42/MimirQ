/**
 * 文档详情对话框 - 展示最终切片结果
 */
'use client'

import { useEffect, useState } from 'react'
import { Loader2, FileText, Info, Database, Calendar, Tag, FileType, Hash } from 'lucide-react'

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
import { formatFileSize, formatDate } from '@/lib/utils'
import { getParserLabel } from '@/lib/parser-options'
import { getChunkStrategyLabel } from '@/lib/chunk-strategies'
import type { Document, DocumentChunk } from '@/types'
import { cn } from '@/lib/utils'

interface DocumentDetailDialogProps {
  document: Document
}

export function DocumentDetailDialog({ document }: DocumentDetailDialogProps) {
  const [open, setOpen] = useState(false)
  const [detail, setDetail] = useState<Document | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)

  useEffect(() => {
    if (!open) return

    let cancelled = false
    setIsLoading(true)
    setError(null)

    documentApi
      .get(document.id, { includeChunks: true })
      .then((data) => {
        if (!cancelled) {
          setDetail(data)
        }
      })
      .catch((err: any) => {
        if (!cancelled) {
          console.error('Load document detail error:', err)
          setError(err.message || '获取文档详情失败')
        }
      })
      .finally(() => {
        if (!cancelled) {
          setIsLoading(false)
        }
      })

    return () => {
      cancelled = true
    }
  }, [open, document.id])

  const chunks: DocumentChunk[] = detail?.chunks || []
  const parserBackend = (detail?.metadata?.parser_backend as string) || (document.metadata?.parser_backend as string) || ''
  const chunkStrategy = (detail?.metadata?.chunk_strategy as string) || (document.metadata?.chunk_strategy as string) || ''
  const parserLabel = parserBackend ? getParserLabel(parserBackend) : null
  const chunkStrategyLabel = chunkStrategy ? getChunkStrategyLabel(chunkStrategy) : null
  
  // 使用详情中的信息优先，否则回退到列表中的简略信息
  const displayDoc = detail || document

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-gray-400 hover:text-blue-600 hover:bg-blue-50 transition-colors"
          title="查看切片详情"
          onClick={(e) => {
            e.stopPropagation()
          }}
        >
          <Info className="h-4 w-4" />
        </Button>
      </DialogTrigger>

      <DialogContent className="max-w-4xl h-[80vh] flex flex-col p-0 gap-0 overflow-hidden bg-gray-50/50">
        {/* Header */}
        <div className="bg-white px-6 py-4 border-b border-gray-100 flex items-start justify-between shrink-0">
          <div className="flex items-start gap-4">
             <div className="p-3 bg-blue-50 rounded-xl">
               <Database className="h-6 w-6 text-blue-600" />
             </div>
             <div>
                <DialogTitle className="text-lg font-bold text-gray-900 leading-tight">
                  {displayDoc.filename}
                </DialogTitle>
                <div className="flex items-center gap-3 mt-1.5 text-xs text-gray-500">
                  <span className="flex items-center gap-1">
                    <FileType className="h-3 w-3" />
                    {displayDoc.file_type}
                  </span>
                  <span className="w-1 h-1 rounded-full bg-gray-300" />
                  <span>{formatFileSize(displayDoc.file_size)}</span>
                  <span className="w-1 h-1 rounded-full bg-gray-300" />
                  <span className="flex items-center gap-1">
                    <Calendar className="h-3 w-3" />
                    {formatDate(displayDoc.created_at)}
                  </span>
                </div>
             </div>
          </div>
          
          <div className="flex flex-col items-end gap-1.5">
             {parserLabel && (
               <div className="px-2.5 py-1 bg-gray-100 text-gray-600 text-xs font-medium rounded-full border border-gray-200">
                 解析: {parserLabel}
               </div>
             )}
             {chunkStrategyLabel && (
               <div className="px-2.5 py-1 bg-gray-100 text-gray-600 text-xs font-medium rounded-full border border-gray-200">
                 策略: {chunkStrategyLabel}
               </div>
             )}
          </div>
        </div>

        {/* Content Area */}
        <div className="flex-1 overflow-hidden flex flex-col p-6">
          {/* Stats Bar */}
          <div className="grid grid-cols-3 gap-4 mb-6 shrink-0">
            <div className="bg-white p-4 rounded-xl border border-gray-100 shadow-sm">
               <p className="text-xs text-gray-500 font-medium uppercase tracking-wider mb-1">总片段数</p>
               <p className="text-2xl font-bold text-gray-900">
                 {isLoading ? '-' : chunks.length}
               </p>
            </div>
             <div className="bg-white p-4 rounded-xl border border-gray-100 shadow-sm">
               <p className="text-xs text-gray-500 font-medium uppercase tracking-wider mb-1">总字符数</p>
               <p className="text-2xl font-bold text-gray-900">
                 {displayDoc.total_characters ? displayDoc.total_characters.toLocaleString() : '-'}
               </p>
            </div>
             <div className="bg-white p-4 rounded-xl border border-gray-100 shadow-sm">
               <p className="text-xs text-gray-500 font-medium uppercase tracking-wider mb-1">状态</p>
               <div className="flex items-center gap-2 mt-1">
                 <div className={cn("w-2 h-2 rounded-full", displayDoc.status === 'completed' ? "bg-green-500" : "bg-blue-500 animate-pulse")} />
                 <p className="text-base font-semibold text-gray-900 capitalize">
                   {displayDoc.status === 'completed' ? '已完成' : displayDoc.status}
                 </p>
               </div>
            </div>
          </div>

          {/* Chunks List */}
          <div className="flex-1 overflow-y-auto min-h-0 bg-white border border-gray-200 rounded-xl shadow-inner">
            {isLoading ? (
              <div className="h-full flex flex-col items-center justify-center gap-3">
                <Loader2 className="h-8 w-8 text-blue-500 animate-spin" />
                <p className="text-sm text-gray-500">正在加载切片数据...</p>
              </div>
            ) : error ? (
              <div className="h-full flex flex-col items-center justify-center gap-3 text-red-500">
                <p>{error}</p>
                <Button variant="outline" size="sm" onClick={() => setOpen(false)}>关闭</Button>
              </div>
            ) : chunks.length === 0 ? (
               <div className="h-full flex flex-col items-center justify-center gap-3 text-gray-400">
                <FileText className="h-10 w-10 opacity-20" />
                <p className="text-sm">暂无切片数据</p>
              </div>
            ) : (
              <div className="divide-y divide-gray-100">
                {chunks.map((chunk, index) => (
                  <div key={chunk.id} className="p-4 hover:bg-blue-50/30 transition-colors group">
                    <div className="flex items-center justify-between mb-2">
                       <div className="flex items-center gap-2">
                          <span className="px-2 py-0.5 bg-gray-100 text-gray-600 rounded text-xs font-mono font-medium">
                            #{chunk.chunk_index}
                          </span>
                          {typeof chunk.page_number === 'number' && (
                            <span className="flex items-center gap-1 text-xs text-gray-500 bg-gray-50 px-1.5 py-0.5 rounded border border-gray-100">
                               <FileText className="h-3 w-3" /> P.{chunk.page_number}
                            </span>
                          )}
                       </div>
                       <div className="text-xs text-gray-400 font-mono">
                          {chunk.content.length} chars
                       </div>
                    </div>
                    
                    <div className="text-sm text-gray-700 font-mono leading-relaxed whitespace-pre-wrap break-all pl-2 border-l-2 border-transparent group-hover:border-blue-200 transition-colors">
                      {chunk.content}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <DialogFooter className="bg-white p-4 border-t border-gray-100 shrink-0">
          <Button onClick={() => setOpen(false)} className="w-full sm:w-auto">
            关闭
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
