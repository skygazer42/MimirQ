/**
 * ConversationSummaryDialog
 *
 * View / update / clear persistent summary memory for a conversation.
 *
 * Notes:
 * - Backend must enable PERSISTENT_SUMMARY_MEMORY_ENABLED=true.
 * - "Update" may trigger an LLM call and take a few seconds.
 */
'use client'

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import * as React from 'react'
import { Copy, RefreshCw, Trash2 } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { chatApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'


export function ConversationSummaryDialog(props: Readonly<{
  open: boolean
  onOpenChange: (open: boolean) => void
  conversationId?: string
}>) {
  const { open, onOpenChange, conversationId } = props
  const queryClient = useQueryClient()
  const conversationIdForQuery = (conversationId || '').trim()
  const hasConversation = Boolean(conversationIdForQuery)
  const summaryQueryKey = queryKeys.chat.summary(conversationIdForQuery)

  const summaryQuery = useQuery({
    queryKey: summaryQueryKey,
    enabled: open && hasConversation,
    retry: false,
    queryFn: async () => {
      try {
        return await chatApi.getConversationSummary(conversationIdForQuery)
      } catch (err: unknown) {
        toast.error(formatApiError(err, '加载摘要失败'))
        throw err
      }
    },
  })

  const updateMutation = useMutation({
    mutationFn: async () => chatApi.updateConversationSummary(conversationIdForQuery),
    onSuccess: (res) => {
      queryClient.setQueryData(summaryQueryKey, {
        available: true,
        summary: String(res?.summary || ''),
      })
      toast.success('摘要已更新')
    },
    onError: (err: unknown) => {
      toast.error(formatApiError(err, '更新摘要失败'))
    },
  })

  const clearMutation = useMutation({
    mutationFn: async () => chatApi.deleteConversationSummary(conversationIdForQuery),
    onSuccess: () => {
      queryClient.setQueryData(summaryQueryKey, { available: false, summary: '' })
      toast.success('摘要已清空')
    },
    onError: (err: unknown) => {
      toast.error(formatApiError(err, '清空摘要失败'))
    },
  })

  const available = Boolean(summaryQuery.data?.available)
  const summary = String(summaryQuery.data?.summary || '')
  const loading = summaryQuery.isFetching
  const updating = updateMutation.isPending
  const clearing = clearMutation.isPending
  const statusText = loading ? '加载中…' : available ? '可用' : '暂无'

  const copy = React.useCallback(async () => {
    const text = (summary || '').trim()
    if (!text) return
    try {
      await navigator.clipboard.writeText(text)
      toast.success('已复制摘要')
    } catch {
      toast.error('复制失败')
    }
  }, [summary])

  return (
    <Dialog open={open} onOpenChange={onOpenChange}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>摘要记忆</DialogTitle>
          <DialogDescription>
            持久化的会话摘要（用于压缩历史上下文）。更新操作可能触发一次 LLM 调用。
          </DialogDescription>
        </DialogHeader>

        {hasConversation ? (
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div className="text-xs text-muted-foreground">
                状态：{statusText}
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 gap-2"
                  onClick={() => {
                    summaryQuery.refetch()
                  }}
                  disabled={loading || !hasConversation}
                >
                  <RefreshCw className={loading ? 'size-4 animate-spin motion-reduce:animate-none' : 'size-4'} />
                  刷新
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 gap-2"
                  onClick={() => updateMutation.mutate()}
                  disabled={updating || !hasConversation}
                >
                  <RefreshCw className={updating ? 'size-4 animate-spin motion-reduce:animate-none' : 'size-4'} />
                  更新
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 gap-2"
                  onClick={() => {
                    copy()
                  }}
                  disabled={!summary.trim()}
                >
                  <Copy className="size-4" />
                  复制
                </Button>
                <ConfirmDialog
                  title="清空摘要记忆？"
                  description="将删除该会话的持久化摘要。你可以稍后重新生成。"
                  confirmLabel="清空"
                  cancelLabel="返回"
                  confirmVariant="destructive"
                  confirmDisabled={clearing || !hasConversation}
                  onConfirm={() => clearMutation.mutate()}
                >
                  <Button
                    variant="outline"
                    size="sm"
                    className="h-8 gap-2 text-destructive hover:text-destructive"
                    disabled={clearing || !hasConversation}
                  >
                    <Trash2 className={clearing ? 'size-4 animate-pulse' : 'size-4'} />
                    清空
                  </Button>
                </ConfirmDialog>
              </div>
            </div>

            <div className="rounded-lg border border-border bg-background p-3">
              <pre className="text-xs whitespace-pre-wrap break-words leading-relaxed max-h-[420px] overflow-auto">
                {summary.trim() ? summary : '(empty)'}
              </pre>
            </div>
          </div>
        ) : (
          <div className="rounded-lg border border-border bg-muted/20 p-4 text-sm text-muted-foreground">
            当前还没有会话 ID。请先发送一条消息，再查看/更新摘要。
          </div>
        )}

        <DialogFooter>
          <Button variant="outline" onClick={() => onOpenChange(false)}>
            关闭
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
