'use client'

import {
  CancelledError,
  skipToken,
  useMutation,
  useMutationState,
  useQuery,
  useQueryClient,
} from '@tanstack/react-query'
import * as React from 'react'
import { toast } from 'sonner'

import { Copy, RefreshCw, Trash2 } from '@/components/icons'
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
import { getAuthSessionKey } from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'
import type { ConversationSummaryResponse } from '@/types/chat'

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
  const conversationIdForQuery = conversationId?.trim()
  const hasConversation = conversationIdForQuery !== undefined && conversationIdForQuery !== ''
  const summaryQueryKey = hasConversation
    ? queryKeys.chat.summary(conversationIdForQuery)
    : (['chat', 'summary'] as const)
  const view = React.useMemo(() => ({ open, conversationIdForQuery }), [open, conversationIdForQuery])
  const activeViewRef = React.useRef<typeof view | null>(view)

  const captureOperation = (targetConversationId: string) => {
    const sessionKey = getAuthSessionKey()
    const key = queryKeys.chat.summary(targetConversationId)
    const query = queryClient.getQueryCache().find({ queryKey: key, exact: true })
    const isActive = () =>
      sessionKey === getAuthSessionKey() &&
      query !== undefined &&
      queryClient.getQueryCache().find({ queryKey: key, exact: true }) === query
    return {
      conversationId: targetConversationId,
      view,
      key,
      isActive,
      isCurrent: () => isActive() && activeViewRef.current === view,
    }
  }

  const [clearTarget, setClearTarget] = React.useState<ReturnType<typeof captureOperation>>()
  const confirmation = clearTarget?.view === view && clearTarget.isActive() ? clearTarget : undefined

  React.useLayoutEffect(() => {
    activeViewRef.current = view
    setClearTarget(undefined)
    return () => {
      activeViewRef.current = null
    }
  }, [view])

  const summaryQuery = useQuery({
    queryKey: summaryQueryKey,
    enabled: open && hasConversation,
    retry: false,
    queryFn: hasConversation
      ? ({ signal }) => chatApi.getConversationSummary(conversationIdForQuery, { signal })
      : skipToken,
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
      queryClient.setQueryData<ConversationSummaryResponse>(operation.key, {
        available: res.summary.length > 0,
        summary: res.summary,
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
      queryClient.setQueryData<ConversationSummaryResponse>(operation.key, { available: false, summary: null })
      if (operation.isCurrent()) {
        setClearTarget(undefined)
        toast.success('摘要已清空')
      }
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
  const summary = summaryQuery.data?.summary
  const copyText = summary?.trim()
  const hasSummary = copyText !== undefined && copyText !== ''
  const reading = summaryQuery.fetchStatus !== 'idle'
  const updating = pendingUpdates.some(
    (operation) => operation.conversationId === conversationIdForQuery && operation.isActive(),
  )
  const clearing = pendingClears.some(
    (operation) => operation.conversationId === conversationIdForQuery && operation.isActive(),
  )
  const busy = updating || clearing
  const clearError = confirmation !== undefined && clearMutation.variables === confirmation ? clearMutation.error : null
  let statusText = '尚未读取'
  if (clearing) statusText = '清空中…'
  else if (updating) statusText = '更新中…'
  else if (summaryQuery.isPaused) statusText = '读取已暂停'
  else if (summaryQuery.isFetching) statusText = summaryQuery.data === undefined ? '加载中…' : '刷新中…'
  else if (summaryQuery.isError) statusText = summaryQuery.data === undefined ? '加载失败' : '刷新失败'
  else if (summaryQuery.isSuccess) statusText = hasSummary ? '可用' : '暂无摘要'

  async function copySummary() {
    if (!hasConversation || !hasSummary) return
    const operation = captureOperation(conversationIdForQuery)
    try {
      await navigator.clipboard.writeText(copyText)
      if (operation.isCurrent()) toast.success('已复制摘要')
    } catch {
      if (operation.isCurrent()) toast.error('复制失败')
    }
  }

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
            <div className="flex flex-wrap items-center justify-between gap-3">
              <div role="status" className="text-xs text-muted-foreground">
                状态：{statusText}
              </div>
              <div className="flex flex-wrap items-center gap-2">
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 gap-2"
                  onClick={() => void summaryQuery.refetch()}
                  disabled={reading || busy}
                >
                  <RefreshCw
                    className={summaryQuery.isFetching ? 'size-4 animate-spin motion-reduce:animate-none' : 'size-4'}
                  />
                  刷新
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 gap-2"
                  onClick={() => updateMutation.mutate(captureOperation(conversationIdForQuery))}
                  disabled={reading || busy}
                >
                  <RefreshCw className={updating ? 'size-4 animate-spin motion-reduce:animate-none' : 'size-4'} />
                  更新
                </Button>
                <Button
                  variant="outline"
                  size="sm"
                  className="h-8 gap-2"
                  onClick={() => void copySummary()}
                  disabled={!hasSummary}
                >
                  <Copy className="size-4" />
                  复制
                </Button>
                <AlertDialog
                  open={confirmation !== undefined}
                  onOpenChange={(nextOpen) => {
                    if (clearing) return
                    if (nextOpen) {
                      clearMutation.reset()
                      setClearTarget(captureOperation(conversationIdForQuery))
                    } else {
                      setClearTarget(undefined)
                    }
                  }}
                >
                  <AlertDialogTrigger asChild>
                    <Button
                      variant="outline"
                      size="sm"
                      className="h-8 gap-2 text-destructive hover:text-destructive"
                      disabled={reading || busy}
                    >
                      <Trash2 className={clearing ? 'size-4 animate-pulse motion-reduce:animate-none' : 'size-4'} />
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
                        disabled={confirmation === undefined || reading || busy}
                        aria-busy={clearing}
                        onClick={() => {
                          if (confirmation?.isCurrent()) clearMutation.mutate(confirmation)
                        }}
                      >
                        {clearing ? '清空中…' : '清空'}
                      </Button>
                    </AlertDialogFooter>
                  </AlertDialogContent>
                </AlertDialog>
              </div>
            </div>

            {summaryQuery.isError && !reading ? (
              <p role="alert" className="text-sm text-destructive">
                {formatApiError(summaryQuery.error, '加载摘要失败')}
              </p>
            ) : null}

            {hasSummary && (
              <div className="rounded-lg border border-border bg-background p-3">
                <pre className="text-xs whitespace-pre-wrap break-words leading-relaxed max-h-[420px] overflow-auto">
                  {summary}
                </pre>
              </div>
            )}
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
