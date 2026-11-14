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

import { CancelledError, useMutation, useMutationState, useQuery, useQueryClient } from '@tanstack/react-query'
import * as React from 'react'
import { Copy, RefreshCw, Trash2 } from '@/components/icons'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import {
  AlertDialog,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
  AlertDialogTrigger,
} from '@/components/ui/alert-dialog'
import {
  Dialog,
  DialogContent,
  DialogDescription,
  DialogFooter,
  DialogHeader,
  DialogTitle,
} from '@/components/ui/dialog'
import { chatApi } from '@/lib/api/chat'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'

const UPDATE_SUMMARY_MUTATION_KEY = ['chat', 'summary', 'update'] as const
const CLEAR_SUMMARY_MUTATION_KEY = ['chat', 'summary', 'clear'] as const

export function ConversationSummaryDialog(
  props: Readonly<{
    open: boolean
    onOpenChange: (open: boolean) => void
    conversationId?: string
  }>,
) {
  const { open, onOpenChange, conversationId } = props
  const queryClient = useQueryClient()
  const conversationIdForQuery = (conversationId || '').trim()
  const hasConversation = Boolean(conversationIdForQuery)
  const summaryQueryKey = queryKeys.chat.summary(conversationIdForQuery)
  const [confirmOpen, setConfirmOpen] = React.useState(false)
  const view = React.useMemo(() => ({ open, conversationIdForQuery }), [open, conversationIdForQuery])
  const activeViewRef = React.useRef<typeof view | null>(view)

  React.useEffect(() => {
    activeViewRef.current = view
    setConfirmOpen(false)
    return () => {
      activeViewRef.current = null
    }
  }, [view])

  const captureOperation = () => {
    const key = queryKeys.chat.summary(conversationIdForQuery)
    const query = queryClient.getQueryCache().find({ queryKey: key, exact: true })
    const isActive = () =>
      query !== undefined && queryClient.getQueryCache().find({ queryKey: key, exact: true }) === query
    return {
      conversationId: conversationIdForQuery,
      view,
      key,
      isActive,
      isCurrent: () => isActive() && activeViewRef.current === view,
    }
  }

  const summaryQuery = useQuery({
    queryKey: summaryQueryKey,
    enabled: open && hasConversation,
    retry: false,
    queryFn: async ({ signal }) => {
      try {
        return await chatApi.getConversationSummary(conversationIdForQuery)
      } catch (err: unknown) {
        if (!signal.aborted && activeViewRef.current === view) toast.error(formatApiError(err, '加载摘要失败'))
        throw err
      }
    },
  })

  const updateMutation = useMutation({
    mutationKey: UPDATE_SUMMARY_MUTATION_KEY,
    mutationFn: async (operation: ReturnType<typeof captureOperation>) => {
      if (!operation.isActive()) throw new CancelledError()
      return chatApi.updateConversationSummary(operation.conversationId)
    },
    onSuccess: async (res, operation) => {
      if (!operation.isActive()) return
      await queryClient.cancelQueries({ queryKey: operation.key, exact: true })
      if (!operation.isActive()) return
      queryClient.setQueryData(operation.key, {
        available: true,
        summary: String(res?.summary || ''),
      })
      if (operation.isCurrent()) toast.success('摘要已更新')
    },
    onError: (err, operation) => {
      if (operation.isCurrent()) toast.error(formatApiError(err, '更新摘要失败'))
    },
  })

  const clearMutation = useMutation({
    mutationKey: CLEAR_SUMMARY_MUTATION_KEY,
    mutationFn: async (operation: ReturnType<typeof captureOperation>) => {
      if (!operation.isActive()) throw new CancelledError()
      await chatApi.deleteConversationSummary(operation.conversationId)
    },
    onSuccess: async (_result, operation) => {
      if (!operation.isActive()) return
      await queryClient.cancelQueries({ queryKey: operation.key, exact: true })
      if (!operation.isActive()) return
      queryClient.setQueryData(operation.key, { available: false, summary: '' })
      if (operation.isCurrent()) {
        setConfirmOpen(false)
        toast.success('摘要已清空')
      }
    },
    onError: (err, operation) => {
      if (operation.isCurrent()) toast.error(formatApiError(err, '清空摘要失败'))
    },
  })

  const pendingUpdates = useMutationState({
    filters: { mutationKey: UPDATE_SUMMARY_MUTATION_KEY, exact: true, status: 'pending' },
    select: (mutation) => mutation.state.variables as ReturnType<typeof captureOperation>,
  })
  const pendingClears = useMutationState({
    filters: { mutationKey: CLEAR_SUMMARY_MUTATION_KEY, exact: true, status: 'pending' },
    select: (mutation) => mutation.state.variables as ReturnType<typeof captureOperation>,
  })
  const available = Boolean(summaryQuery.data?.available)
  const summary = String(summaryQuery.data?.summary || '')
  const loading = summaryQuery.isFetching
  const updating = pendingUpdates.some(
    (operation) => operation.conversationId === conversationIdForQuery && operation.isActive(),
  )
  const clearing = pendingClears.some(
    (operation) => operation.conversationId === conversationIdForQuery && operation.isActive(),
  )
  const busy = updating || clearing
  const clearError =
    clearMutation.variables?.view === view && clearMutation.variables.isActive() ? clearMutation.error : null
  const statusText = loading ? '加载中…' : summaryQuery.isError ? '加载失败' : available ? '可用' : '暂无'

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
    <Dialog
      open={open}
      onOpenChange={(nextOpen) => {
        if (!busy) onOpenChange(nextOpen)
      }}
    >
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle>摘要记忆</DialogTitle>
          <DialogDescription>持久化的会话摘要（用于压缩历史上下文）。更新操作可能触发一次 LLM 调用。</DialogDescription>
        </DialogHeader>

        {hasConversation ? (
          <div className="space-y-3">
            <div className="flex items-center justify-between gap-3">
              <div className="text-xs text-muted-foreground">状态：{statusText}</div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 gap-2"
                  onClick={() => {
                    summaryQuery.refetch()
                  }}
                  disabled={loading || busy || !hasConversation}
                >
                  <RefreshCw className={loading ? 'size-4 animate-spin motion-reduce:animate-none' : 'size-4'} />
                  刷新
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 gap-2"
                  onClick={() => updateMutation.mutate(captureOperation())}
                  disabled={loading || busy || !hasConversation}
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
                <AlertDialog
                  open={confirmOpen}
                  onOpenChange={(nextOpen) => {
                    if (clearing) return
                    if (nextOpen) clearMutation.reset()
                    setConfirmOpen(nextOpen)
                  }}
                >
                  <AlertDialogTrigger asChild>
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-8 gap-2 text-destructive hover:text-destructive"
                      disabled={loading || busy || !hasConversation}
                    >
                      <Trash2 className={clearing ? 'size-4 animate-pulse' : 'size-4'} />
                      清空
                    </Button>
                  </AlertDialogTrigger>
                  <AlertDialogContent>
                    <AlertDialogHeader>
                      <AlertDialogTitle>清空摘要记忆？</AlertDialogTitle>
                      <AlertDialogDescription>将删除该会话的持久化摘要。你可以稍后重新生成。</AlertDialogDescription>
                    </AlertDialogHeader>
                    {clearError ? (
                      <p role="alert" className="text-sm text-destructive">
                        {formatApiError(clearError, '清空摘要失败')}
                      </p>
                    ) : null}
                    <AlertDialogFooter>
                      <AlertDialogCancel disabled={clearing}>返回</AlertDialogCancel>
                      <Button
                        variant="destructive"
                        size="sm"
                        disabled={clearing || !hasConversation}
                        aria-busy={clearing}
                        onClick={() => clearMutation.mutate(captureOperation())}
                      >
                        {clearing ? '清空中…' : '清空'}
                      </Button>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
            </div>

            {summaryQuery.isError ? (
              <p role="alert" className="text-sm text-destructive">
                {formatApiError(summaryQuery.error, '加载摘要失败')}
              </p>
            ) : null}

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
          <Button variant="outline" disabled={busy} onClick={() => onOpenChange(false)}>
            关闭
          </Button>
        </DialogFooter>
      </DialogContent>
    </Dialog>
  )
}
