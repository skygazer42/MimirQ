/**
 * 文档详情对话框 - 展示最终切片结果
 */
'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Calendar, Copy, Database, Eye, FileText, FileType, Hash, Loader2, Search, X } from 'lucide-react'
import { toast } from 'sonner'

import { Alert, AlertDescription, AlertTitle } from '@/components/ui/alert'
import { Button } from '@/components/ui/button'
import { Dialog, DialogContent, DialogDescription, DialogTitle, DialogTrigger } from '@/components/ui/dialog'
import { EmptyState } from '@/components/ui/empty-state'
import { IconButton } from '@/components/ui/icon-button'
import { Input } from '@/components/ui/input'
import { Panel } from '@/components/ui/panel'
import { StatusBadge, type StatusBadgeStatus } from '@/components/ui/status-badge'
import { documentApi, kgApi } from '@/lib/api-client'
import { formatApiError } from '@/lib/api-errors'
import { getChunkStrategyLabel } from '@/lib/chunk-strategies'
import { getParserLabel } from '@/lib/parser-options'
import { cn, formatDate, formatFileSize } from '@/lib/utils'
import type { Document, DocumentChunk } from '@/types'

interface DocumentDetailDialogProps {
  document: Document
  trigger?: React.ReactNode
}

const EMPTY_CHUNKS: DocumentChunk[] = []

function asStatusBadgeStatus(status: string | undefined): StatusBadgeStatus {
  switch (status) {
    case 'pending':
    case 'processing':
    case 'completed':
    case 'failed':
    case 'quarantined':
    case 'cancelled':
      return status
    default:
      return 'pending'
  }
}

function highlightText(text: string, query: string) {
  const needle = query.trim()
  if (!needle) return text

  const haystack = text
  const haystackLower = haystack.toLowerCase()
  const needleLower = needle.toLowerCase()

  const nodes: Array<string | JSX.Element> = []
  let cursor = 0

  while (cursor < haystack.length) {
    const matchAt = haystackLower.indexOf(needleLower, cursor)
    if (matchAt === -1) {
      nodes.push(haystack.slice(cursor))
      break
    }

    if (matchAt > cursor) {
      nodes.push(haystack.slice(cursor, matchAt))
    }

    const matched = haystack.slice(matchAt, matchAt + needle.length)
    nodes.push(
      <mark key={`${matchAt}-${matched.length}`} className="rounded bg-primary/15 px-0.5 text-foreground">
        {matched}
      </mark>
    )

    cursor = matchAt + needle.length
  }

  return nodes
}

export function DocumentDetailDialog({ document: initialDocument, trigger }: DocumentDetailDialogProps) {
  const [open, setOpen] = useState(false)
  const [detail, setDetail] = useState<Document | null>(null)
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [isKgWorking, setIsKgWorking] = useState(false)
  const [chunkQuery, setChunkQuery] = useState('')

  const loadDetail = useCallback(async () => {
    setIsLoading(true)
    setError(null)
    try {
      const data = await documentApi.get(initialDocument.id, { includeChunks: true })
      setDetail(data)
    } catch (err: any) {
      console.error('Load document detail error:', err)
      setError(formatApiError(err, '获取文档详情失败'))
    } finally {
      setIsLoading(false)
    }
  }, [initialDocument.id])

  useEffect(() => {
    if (!open) return
    void loadDetail()
  }, [open, loadDetail])

  const chunks = detail?.chunks ?? EMPTY_CHUNKS
  const parserBackend =
    (detail?.metadata?.parser_backend as string) || (initialDocument.metadata?.parser_backend as string) || ''
  const chunkStrategy =
    (detail?.metadata?.chunk_strategy as string) || (initialDocument.metadata?.chunk_strategy as string) || ''
  const parserLabel = parserBackend ? getParserLabel(parserBackend) : null
  const chunkStrategyLabel = chunkStrategy ? getChunkStrategyLabel(chunkStrategy) : null

  // 使用详情中的信息优先，否则回退到列表中的简略信息
  const displayDoc = detail || initialDocument
  const status = asStatusBadgeStatus(displayDoc.status)
  const canRunKg = displayDoc.status === 'completed' && !isKgWorking

  const filteredChunks = useMemo(() => {
    const q = chunkQuery.trim().toLowerCase()
    if (!q) return chunks
    return chunks.filter((chunk) => {
      const content = chunk.content || ''
      if (content.toLowerCase().includes(q)) return true
      if (String(chunk.chunk_index).includes(q)) return true
      if (typeof chunk.page_number === 'number' && String(chunk.page_number).includes(q)) return true
      return false
    })
  }, [chunks, chunkQuery])

  const copyToClipboard = useCallback(async (text: string) => {
    const content = text || ''
    try {
      if (navigator.clipboard?.writeText) {
        await navigator.clipboard.writeText(content)
      } else {
        const textarea = window.document.createElement('textarea')
        textarea.value = content
        textarea.style.position = 'fixed'
        textarea.style.left = '0'
        textarea.style.top = '0'
        textarea.style.opacity = '0'
        window.document.body.appendChild(textarea)
        textarea.focus()
        textarea.select()
        const ok = window.document.execCommand('copy')
        window.document.body.removeChild(textarea)
        if (!ok) throw new Error('copy failed')
      }
      toast.success('已复制到剪贴板')
    } catch (err) {
      console.error('Copy failed:', err)
      toast.error('复制失败')
    }
  }, [])

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
          <IconButton
            label="预览文档内容"
            variant="ghost"
            className="h-8 w-8 text-muted-foreground hover:text-primary hover:bg-muted"
            onClick={(e) => {
              e.stopPropagation()
            }}
          >
            <Eye className="h-4 w-4" />
          </IconButton>
        )}
      </DialogTrigger>

      <DialogContent className="!max-w-5xl h-[80vh] !p-0 !gap-0 overflow-hidden">
        {/* Header */}
        <header className="flex items-start justify-between gap-6 border-b border-border bg-muted/20 px-6 py-4">
          <div className="flex items-start gap-4 min-w-0">
            <div className="grid h-12 w-12 place-items-center rounded-2xl border border-border bg-primary/10 text-primary">
              <Database className="h-6 w-6" />
            </div>
            <div className="min-w-0">
              <DialogTitle className="truncate">{displayDoc.filename}</DialogTitle>
              <DialogDescription className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-xs">
                <span className="inline-flex items-center gap-1">
                  <FileType className="h-3.5 w-3.5" />
                  {displayDoc.file_type}
                </span>
                <span className="text-muted-foreground/40">|</span>
                <span>{formatFileSize(displayDoc.file_size)}</span>
                <span className="text-muted-foreground/40">|</span>
                <span className="inline-flex items-center gap-1">
                  <Calendar className="h-3.5 w-3.5" />
                  {formatDate(displayDoc.created_at)}
                </span>
                <span className="text-muted-foreground/40">|</span>
                <span className="inline-flex items-center gap-1">
                  <Hash className="h-3.5 w-3.5" />
                  {chunks.length} 切片
                </span>
              </DialogDescription>
            </div>
          </div>

          <div className="flex flex-col items-end gap-2">
            <StatusBadge status={status} />
            <div className="flex flex-wrap justify-end gap-2">
              {parserLabel ? (
                <span className="rounded-full border border-border/60 bg-muted/60 px-2.5 py-1 text-xs font-medium text-muted-foreground">
                  解析：{parserLabel}
                </span>
              ) : null}
              {chunkStrategyLabel ? (
                <span className="rounded-full border border-border/60 bg-muted/60 px-2.5 py-1 text-xs font-medium text-muted-foreground">
                  切块：{chunkStrategyLabel}
                </span>
              ) : null}
            </div>
          </div>
        </header>

        {/* Body */}
        <main className="min-h-0 p-6">
          <Panel padding="none" className="h-full overflow-hidden rounded-2xl">
            <div className="flex items-center gap-3 border-b border-border/60 bg-background/40 px-4 py-3">
              <div className="relative flex-1">
                <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                <Input
                  value={chunkQuery}
                  onChange={(e) => setChunkQuery(e.target.value)}
                  placeholder="搜索切片内容 / 页码 / 编号..."
                  className="h-10 pl-9"
                />
              </div>
              <span className="hidden sm:inline-flex rounded-full border border-border/60 bg-muted/60 px-2 py-1 text-xs text-muted-foreground">
                {filteredChunks.length}/{chunks.length}
              </span>
              {chunkQuery ? (
                <IconButton
                  label="清除搜索"
                  variant="ghost"
                  className="h-10 w-10 text-muted-foreground hover:text-foreground"
                  onClick={() => setChunkQuery('')}
                >
                  <X className="h-4 w-4" />
                </IconButton>
              ) : null}
            </div>

            <div className="h-full overflow-y-auto overscroll-contain no-scrollbar p-4">
              {isLoading ? (
                <div className="flex h-full flex-col items-center justify-center gap-3 text-muted-foreground">
                  <Loader2 className="h-8 w-8 animate-spin motion-reduce:animate-none" />
                  <p className="text-sm">正在加载切片数据...</p>
                </div>
              ) : error ? (
                <div className="mx-auto max-w-2xl py-10">
                  <Alert variant="destructive">
                    <AlertTitle>加载失败</AlertTitle>
                    <AlertDescription>{error}</AlertDescription>
                  </Alert>
                  <div className="mt-4 flex items-center justify-end gap-2">
                    <Button variant="outline" onClick={() => void loadDetail()}>
                      重试
                    </Button>
                    <Button variant="secondary" onClick={() => setOpen(false)}>
                      关闭
                    </Button>
                  </div>
                </div>
              ) : chunks.length === 0 ? (
                <EmptyState
                  icon={FileText}
                  title="暂无切片数据"
                  description="该文档暂未生成可用切片，或后端未返回切片内容。"
                  className="min-h-[320px]"
                />
              ) : filteredChunks.length === 0 ? (
                <EmptyState
                  icon={Search}
                  title="未找到匹配切片"
                  description={<span>尝试更换关键词，或清空筛选条件。</span>}
                  className="min-h-[320px]"
                >
                  <Button variant="outline" onClick={() => setChunkQuery('')}>
                    清空筛选
                  </Button>
                </EmptyState>
              ) : (
                <div className="space-y-3 pb-6">
                  {filteredChunks.map((chunk) => (
                    <div
                      key={chunk.id}
                      className={cn(
                        "group rounded-xl border border-border/60 bg-card p-4 transition-colors",
                        "hover:border-primary/25 hover:shadow-soft/30"
                      )}
                    >
                      <div className="flex items-start justify-between gap-3">
                        <div className="flex flex-wrap items-center gap-2 text-xs">
                          <span className="rounded-full border border-border/60 bg-muted px-2 py-0.5 font-mono font-medium text-muted-foreground">
                            #{chunk.chunk_index}
                          </span>
                          {typeof chunk.page_number === 'number' ? (
                            <span className="rounded-full border border-border/60 bg-muted/60 px-2 py-0.5 text-muted-foreground">
                              P.{chunk.page_number}
                            </span>
                          ) : null}
                          <span className="text-muted-foreground">{(chunk.content || '').length} chars</span>
                        </div>
                        <IconButton
                          label="复制切片内容"
                          variant="ghost"
                          className="h-9 w-9 text-muted-foreground hover:text-foreground"
                          onClick={() => void copyToClipboard(chunk.content)}
                        >
                          <Copy className="h-4 w-4" />
                        </IconButton>
                      </div>

                      <div className="mt-2 whitespace-pre-wrap break-words font-mono text-xs leading-relaxed text-foreground/90">
                        {highlightText(chunk.content || '', chunkQuery)}
                      </div>
                    </div>
                  ))}
                </div>
              )}
            </div>
          </Panel>
        </main>

        {/* Footer */}
        <footer className="border-t border-border bg-muted/20 px-6 py-4">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
            <div className="flex flex-col gap-2 sm:flex-row">
              <Button variant="outline" onClick={handleExtractKG} disabled={!canRunKg} className="w-full gap-2 sm:w-auto">
                {isKgWorking && canRunKg ? (
                  <Loader2 className="h-4 w-4 animate-spin motion-reduce:animate-none" />
                ) : null}
                抽取 KG
              </Button>
              <Button
                variant="outline"
                onClick={handleDeleteKG}
                disabled={isKgWorking}
                className="w-full gap-2 text-destructive hover:bg-destructive/10 hover:text-destructive sm:w-auto"
              >
                清理 KG
              </Button>
            </div>

            <Button variant="secondary" onClick={() => setOpen(false)} className="w-full sm:w-auto">
              关闭
            </Button>
          </div>
        </footer>
      </DialogContent>
    </Dialog>
  )
}
