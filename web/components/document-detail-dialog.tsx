/**
 * 文档详情对话框 - 展示最终切片结果
 */
'use client'

import { useEffect, useState } from 'react'
import { Loader2, FileText, Info, Database, Calendar, Tag, FileType, Hash, Eye } from 'lucide-react'
import { toast } from 'sonner'

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
import { documentApi, kgApi } from '@/lib/api-client'
import { formatFileSize, formatDate } from '@/lib/utils'
import { getParserLabel } from '@/lib/parser-options'
import { getChunkStrategyLabel } from '@/lib/chunk-strategies'
import type { Document, DocumentChunk } from '@/types'
import { cn } from '@/lib/utils'

interface DocumentDetailDialogProps {
  document: Document
  trigger?: React.ReactNode
}

export function DocumentDetailDialog({ document, trigger }: DocumentDetailDialogProps) {
  const [open, setOpen] = useState(false)
  const [detail, setDetail] = useState<Document | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isKgWorking, setIsKgWorking] = useState(false)

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
  const canRunKg = displayDoc.status === 'completed' && !isKgWorking

  const handleExtractKG = async () => {
    if (!canRunKg) return
    setIsKgWorking(true)
    try {
      await kgApi.extract(displayDoc.id, { async: true, replace_existing: true, prune_orphan_entities: true })
      toast.success('已提交 KG 抽取任务（可前往图谱页刷新查看）')
    } catch (err: any) {
      console.error('KG extract failed:', err)
      toast.error(err?.message || 'KG 抽取失败')
    } finally {
      setIsKgWorking(false)
    }
  }

  const handleDeleteKG = async () => {
    if (isKgWorking) return
    if (!confirm('确定要删除该文档的 KG 事件吗？')) return
    setIsKgWorking(true)
    try {
      const res = await kgApi.deleteDocumentKG(displayDoc.id, { prune_orphan_entities: true })
      toast.success(`已删除 KG 事件 ${res.events_deleted}，清理实体 ${res.entities_pruned}`)
    } catch (err: any) {
      console.error('KG delete failed:', err)
      toast.error(err?.message || '删除 KG 失败')
    } finally {
      setIsKgWorking(false)
    }
  }

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        {trigger || (
          <Button
            variant="ghost"
            size="icon"
            className="h-8 w-8 text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 transition-colors"
            title="预览文档内容"
            onClick={(e) => {
              e.stopPropagation()
            }}
          >
            <Eye className="h-4 w-4" />
          </Button>
        )}
      </DialogTrigger>

      <DialogContent className="max-w-4xl h-[80vh] flex flex-col p-0 gap-0 overflow-hidden bg-slate-50/50 dark:bg-slate-950 border-slate-200 dark:border-slate-800">
        {/* Header */}
        <div className="bg-white dark:bg-slate-900 px-6 py-4 border-b border-slate-100 dark:border-slate-800 flex items-start justify-between shrink-0">
          <div className="flex items-start gap-4">
             <div className="p-3 bg-indigo-50 dark:bg-indigo-900/20 rounded-xl">
               <Database className="h-6 w-6 text-indigo-600 dark:text-indigo-400" />
             </div>
             <div>
                <DialogTitle className="text-lg font-bold text-slate-900 dark:text-white leading-tight">
                  {displayDoc.filename}
                </DialogTitle>
                <div className="flex items-center gap-3 mt-1.5 text-xs text-slate-500 dark:text-slate-400">
                  <span className="flex items-center gap-1">
                    <FileType className="h-3 w-3" />
                    {displayDoc.file_type}
                  </span>
                  <span className="w-1 h-1 rounded-full bg-slate-300 dark:bg-slate-600" />
                  <span>{formatFileSize(displayDoc.file_size)}</span>
                  <span className="w-1 h-1 rounded-full bg-slate-300 dark:bg-slate-600" />
                  <span className="flex items-center gap-1">
                    <Calendar className="h-3 w-3" />
                    {formatDate(displayDoc.created_at)}
                  </span>
                </div>
             </div>
          </div>
          
          <div className="flex flex-col items-end gap-1.5">
             {parserLabel && (
               <div className="px-2.5 py-1 bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 text-xs font-medium rounded-full border border-slate-200 dark:border-slate-700">
                 解析: {parserLabel}
               </div>
             )}
             {chunkStrategyLabel && (
               <div className="px-2.5 py-1 bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 text-xs font-medium rounded-full border border-slate-200 dark:border-slate-700">
                 策略: {chunkStrategyLabel}
               </div>
             )}
          </div>
        </div>

        {/* Content Area */}
        <div className="flex-1 overflow-hidden flex flex-col p-6">
          {/* Stats Bar */}
          <div className="grid grid-cols-3 gap-4 mb-6 shrink-0">
            <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-100 dark:border-slate-800 shadow-sm">
               <p className="text-xs text-slate-500 dark:text-slate-400 font-medium uppercase tracking-wider mb-1">总片段数</p>
               <p className="text-2xl font-bold text-slate-900 dark:text-white">
                 {isLoading ? '-' : chunks.length}
               </p>
            </div>
             <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-100 dark:border-slate-800 shadow-sm">
               <p className="text-xs text-slate-500 dark:text-slate-400 font-medium uppercase tracking-wider mb-1">总字符数</p>
               <p className="text-2xl font-bold text-slate-900 dark:text-white">
                 {displayDoc.total_characters ? displayDoc.total_characters.toLocaleString() : '-'}
               </p>
            </div>
             <div className="bg-white dark:bg-slate-900 p-4 rounded-xl border border-slate-100 dark:border-slate-800 shadow-sm">
               <p className="text-xs text-slate-500 dark:text-slate-400 font-medium uppercase tracking-wider mb-1">状态</p>
               <div className="flex items-center gap-2 mt-1">
                 <div className={cn("w-2 h-2 rounded-full", displayDoc.status === 'completed' ? "bg-emerald-500" : "bg-indigo-500 animate-pulse")} />
                 <p className="text-base font-semibold text-slate-900 dark:text-white capitalize">
                   {displayDoc.status === 'completed' ? '已完成' : displayDoc.status}
                 </p>
               </div>
            </div>
          </div>

          {/* Chunks List */}
          <div className="flex-1 overflow-y-auto min-h-0 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-xl shadow-inner dark:shadow-none">
            {isLoading ? (
              <div className="h-full flex flex-col items-center justify-center gap-3">
                <Loader2 className="h-8 w-8 text-indigo-500 animate-spin" />
                <p className="text-sm text-slate-500 dark:text-slate-400">正在加载切片数据...</p>
              </div>
            ) : error ? (
              <div className="h-full flex flex-col items-center justify-center gap-3 text-red-500">
                <p>{error}</p>
                <Button variant="outline" size="sm" onClick={() => setOpen(false)}>关闭</Button>
              </div>
            ) : chunks.length === 0 ? (
               <div className="h-full flex flex-col items-center justify-center gap-3 text-slate-400 dark:text-slate-600">
                <FileText className="h-10 w-10 opacity-20" />
                <p className="text-sm">暂无切片数据</p>
              </div>
            ) : (
              <div className="divide-y divide-slate-100 dark:divide-slate-800">
                {chunks.map((chunk, index) => (
                  <div key={chunk.id} className="p-4 hover:bg-indigo-50/30 dark:hover:bg-indigo-900/10 transition-colors group">
                    <div className="flex items-center justify-between mb-2">
                       <div className="flex items-center gap-2">
                          <span className="px-2 py-0.5 bg-slate-100 dark:bg-slate-800 text-slate-600 dark:text-slate-300 rounded text-xs font-mono font-medium">
                            #{chunk.chunk_index}
                          </span>
                          {typeof chunk.page_number === 'number' && (
                            <span className="flex items-center gap-1 text-xs text-slate-500 dark:text-slate-400 bg-slate-50 dark:bg-slate-800/50 px-1.5 py-0.5 rounded border border-slate-100 dark:border-slate-700">
                               <FileText className="h-3 w-3" /> P.{chunk.page_number}
                            </span>
                          )}
                       </div>
                       <div className="text-xs text-slate-400 dark:text-slate-600 font-mono">
                          {chunk.content.length} chars
                       </div>
                    </div>
                    
                    <div className="text-sm text-slate-700 dark:text-slate-300 font-mono leading-relaxed whitespace-pre-wrap break-all pl-2 border-l-2 border-transparent group-hover:border-indigo-200 dark:group-hover:border-indigo-800 transition-colors">
                      {chunk.content}
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        <DialogFooter className="bg-white dark:bg-slate-900 p-4 border-t border-slate-100 dark:border-slate-800 shrink-0">
          <div className="w-full flex flex-col sm:flex-row gap-2 sm:items-center sm:justify-between">
            <div className="flex flex-col sm:flex-row gap-2">
              <Button
                variant="outline"
                onClick={handleExtractKG}
                disabled={!canRunKg}
                className="w-full sm:w-auto"
              >
                {isKgWorking ? 'KG 处理中...' : '抽取 KG'}
              </Button>
              <Button
                variant="outline"
                onClick={handleDeleteKG}
                disabled={isKgWorking}
                className="w-full sm:w-auto"
              >
                清理 KG
              </Button>
            </div>

            <Button
              onClick={() => setOpen(false)}
              className="w-full sm:w-auto bg-slate-900 dark:bg-slate-100 text-white dark:text-slate-900 hover:bg-slate-800 dark:hover:bg-slate-200"
            >
              关闭
            </Button>
          </div>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
