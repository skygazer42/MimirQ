/**
 * 文档详情对话框 - 展示最终切片结果
 */
'use client'

import { useEffect, useState } from 'react'
import { Loader2, FileText } from 'lucide-react'

import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
  DialogTrigger,
} from '@/components/ui/dialog'
import { Button } from '@/components/ui/button'
import { documentApi } from '@/lib/api-client'
import { formatFileSize, formatDate } from '@/lib/utils'
import type { Document, DocumentChunk } from '@/types'

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

  return (
    <Dialog open={open} onOpenChange={setOpen}>
      <DialogTrigger asChild>
        <Button
          variant="ghost"
          size="icon"
          className="h-7 w-7 text-gray-400 hover:text-gray-700"
          title="查看切片详情"
          onClick={(e) => {
            // 防止冒泡到卡片点击
            e.stopPropagation()
          }}
        >
          <FileText className="h-4 w-4" />
        </Button>
      </DialogTrigger>

      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>文档详情与切片</DialogTitle>
          <DialogDescription>
            查看该文档的基础信息以及后端已入库的所有切片内容，便于调试切片策略和召回效果。
          </DialogDescription>
        </DialogHeader>

        <div className="space-y-4 max-h-[70vh] overflow-y-auto">
          {/* 文档基础信息 */}
          <div className="border rounded-md p-3 bg-gray-50 text-sm">
            <div className="flex justify-between items-start gap-4">
              <div>
                <p className="font-medium text-gray-900 truncate">
                  {detail?.filename || document.filename}
                </p>
                <p className="text-xs text-gray-500 mt-1">
                  类型：{detail?.file_type || document.file_type} · 大小：
                  {formatFileSize(detail?.file_size ?? document.file_size)}
                </p>
                <p className="text-xs text-gray-500 mt-1">
                  创建时间：
                  {formatDate(detail?.created_at || document.created_at)}
                </p>
              </div>
              <div className="text-right text-xs text-gray-500">
                <p>
                  状态：{detail?.status || document.status} · 片段数：
                  {detail?.chunk_count ?? document.chunk_count}
                </p>
                <p className="mt-1">
                  总字符数：
                  {detail?.total_characters ?? document.total_characters}
                </p>
              </div>
            </div>
          </div>

          {/* 加载状态 / 错误 */}
          {isLoading && (
            <div className="flex items-center gap-2 text-sm text-gray-500">
              <Loader2 className="h-4 w-4 animate-spin" />
              正在加载切片详情...
            </div>
          )}

          {error && (
            <p className="text-xs text-red-500 whitespace-pre-line">{error}</p>
          )}

          {/* 切片列表 */}
          {!isLoading && !error && (
            <div className="space-y-2">
              <p className="text-sm text-gray-700">
                切片列表（{chunks.length} 个）
              </p>

              {chunks.length === 0 ? (
                <p className="text-xs text-gray-500">
                  暂无切片数据，可能文档仍在处理中或处理失败。
                </p>
              ) : (
                <div className="space-y-2">
                  {chunks.map((chunk) => (
                    <div
                      key={chunk.id}
                      className="border rounded-md p-2 bg-white text-xs text-gray-800"
                    >
                      <div className="flex justify-between mb-1">
                        <div className="flex items-center gap-2">
                          <span className="font-medium">
                            片段 #{chunk.chunk_index}
                          </span>
                          {typeof chunk.page_number === 'number' && (
                            <span className="text-gray-500">
                              页码：{chunk.page_number}
                            </span>
                          )}
                        </div>
                        <div className="text-gray-400">
                          {typeof chunk.start_char === 'number' &&
                            typeof chunk.end_char === 'number' && (
                              <span>
                                [{chunk.start_char} - {chunk.end_char}]
                              </span>
                            )}
                        </div>
                      </div>
                      <div className="max-h-32 overflow-y-auto whitespace-pre-wrap">
                        {chunk.content.slice(0, 500)}
                        {chunk.content.length > 500 && '...'}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          )}
        </div>

        <DialogFooter>
          <Button variant="outline" onClick={() => setOpen(false)}>
            关闭
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}

