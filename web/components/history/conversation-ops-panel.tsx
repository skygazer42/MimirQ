'use client'

import { useLayoutEffect, useRef, useState, useSyncExternalStore } from 'react'
import { useQueryClient } from '@tanstack/react-query'
import { ChevronDown, Download, GitCommitVertical, Loader2, MessageSquarePlus, Trash2 } from '@/components/icons'
import type { PlatformIcon } from '@/components/icons'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Panel } from '@/components/ui/panel'
import { chatApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { cn, formatFileSize } from '@/lib/utils'
import { downloadBlob } from '@/lib/download'
import { queryKeys } from '@/lib/query-keys'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import type { Conversation } from '@/types/chat'

type ActionName = 'create' | 'export-md' | 'export-json' | 'checkpoints' | 'clear-checkpoints'
type ActionResult = { summary: string; payload?: unknown }
type ActionOutcome = { status: 'done' } | { status: 'failed'; error: unknown } | { status: 'retired' }
type ConversationOpsPanelProps = {
  conversationId: string
  onConversationCreated: (conversation: Conversation) => void
  initiallyExpanded?: boolean
}

export function ConversationOpsPanel(props: Readonly<ConversationOpsPanelProps>) {
  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  return <ConversationOpsContent key={sessionKey} {...props} sessionKey={sessionKey} />
}

function ConversationOpsContent({
  conversationId,
  onConversationCreated,
  initiallyExpanded = false,
  sessionKey,
}: Readonly<ConversationOpsPanelProps & { sessionKey: string }>) {
  const queryClient = useQueryClient()
  const [panelOpen, setPanelOpen] = useState(initiallyExpanded)
  const [resultDetailsOpen, setResultDetailsOpen] = useState(false)
  const [busy, setBusy] = useState<ActionName | null>(null)
  const [result, setResult] = useState<(ActionResult & { title: string }) | null>(null)
  const [actionError, setActionError] = useState<string | undefined>()
  const operationRef = useRef<AbortController | null>(null)
  const hasResultDetails = result?.payload !== undefined

  useLayoutEffect(() => {
    return () => {
      const operation = operationRef.current
      operationRef.current = null
      operation?.abort()
    }
  }, [])

  async function runAction<T>(
    name: ActionName,
    title: string,
    request: (signal: AbortSignal) => Promise<T>,
    present: (payload: T) => ActionResult,
  ): Promise<ActionOutcome> {
    const isCurrentSession = () => sessionKey === getAuthSessionKey()
    if (!isCurrentSession()) return { status: 'retired' }
    if (operationRef.current !== null) {
      return { status: 'failed', error: new Error('请等待当前对话操作完成') }
    }
    const operation = new AbortController()
    const isCurrent = () => operationRef.current === operation && isCurrentSession()
    operationRef.current = operation
    setBusy(name)
    setActionError(undefined)
    try {
      const payload = await request(operation.signal)
      if (!isCurrentSession()) return { status: 'retired' }
      if (name === 'create') {
        const listKeys = [queryKeys.chat.conversationsAll, queryKeys.chat.conversationPagesAll]
        await Promise.all(listKeys.map((queryKey) => queryClient.cancelQueries({ queryKey })))
        if (!isCurrentSession()) return { status: 'retired' }
        await Promise.all(listKeys.map((queryKey) => queryClient.invalidateQueries({ queryKey })))
      }
      if (!isCurrent()) return { status: 'retired' }
      const nextResult = present(payload)
      setResult({ title, ...nextResult })
      setResultDetailsOpen(false)
      toast.success(nextResult.summary)
      return { status: 'done' }
    } catch (error) {
      if (!isCurrent()) return { status: 'retired' }
      if (name !== 'clear-checkpoints') {
        setActionError(`${title}失败：${formatApiError(error, '操作失败')}`)
      }
      return { status: 'failed', error }
    } finally {
      if (operationRef.current === operation) {
        operationRef.current = null
        setBusy(null)
      }
    }
  }

  function exportConversation(format: 'markdown' | 'json') {
    const isMarkdown = format === 'markdown'
    const label = isMarkdown ? 'Markdown' : 'JSON'
    const extension = isMarkdown ? 'md' : 'json'
    return runAction(
      isMarkdown ? 'export-md' : 'export-json',
      `导出 ${label}`,
      (signal) => chatApi.exportConversation(conversationId, { fmt: format, include_citations: true }, { signal }),
      (blob) => {
        downloadBlob(`conversation-${conversationId}.${extension}`, blob)
        return {
          summary: `已开始下载 ${label}，${formatFileSize(blob.size)}`,
          payload: { bytes: blob.size, type: blob.type },
        }
      },
    )
  }

  return (
    <Panel
      data-history-ops-panel="true"
      data-history-ops-boundary="ruled"
      variant="seamless"
      padding="none"
      className="border-border pb-2"
    >
      <Button
        type="button"
        variant="ghost"
        className="h-11 w-full justify-start gap-2 px-2 text-[13px] sm:h-9"
        aria-expanded={panelOpen}
        aria-controls="history-conversation-actions"
        onClick={() => setPanelOpen((open) => !open)}
      >
        <ChevronDown
          className={cn(
            'size-4 text-muted-foreground transition-transform motion-reduce:transition-none',
            panelOpen ? 'rotate-0' : '-rotate-90',
          )}
        />
        <span>对话操作</span>
        <span className="hidden text-xs font-normal text-muted-foreground sm:inline">导出与检查点</span>
        <span className="ml-auto text-xs font-normal text-muted-foreground">{panelOpen ? '收起' : '展开'}</span>
        {busy ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground motion-reduce:animate-none" /> : null}
      </Button>

      {panelOpen ? (
        <div id="history-conversation-actions">
          <div className="mt-3 flex flex-wrap gap-2">
            <ActionButton
              icon={MessageSquarePlus}
              busy={busy === 'create'}
              disabled={busy !== null}
              label="创建空白对话"
              onClick={() =>
                runAction(
                  'create',
                  '创建对话',
                  () => chatApi.createConversation({ title: '新建对话' }),
                  (conversation) => {
                    onConversationCreated(conversation)
                    return { summary: '已创建并打开新对话', payload: conversation }
                  },
                )
              }
            />
            <ActionButton
              icon={Download}
              busy={busy === 'export-md'}
              disabled={busy !== null}
              label="导出 Markdown"
              onClick={() => exportConversation('markdown')}
            />
            <ActionButton
              icon={Download}
              busy={busy === 'export-json'}
              disabled={busy !== null}
              label="导出 JSON"
              onClick={() => exportConversation('json')}
            />
            <ActionButton
              icon={GitCommitVertical}
              busy={busy === 'checkpoints'}
              disabled={busy !== null}
              label="检查点列表"
              onClick={() =>
                runAction(
                  'checkpoints',
                  '检查点列表',
                  (signal) => chatApi.listCheckpoints(conversationId, { limit: 20, include_values: false }, { signal }),
                  (checkpoints) => ({ summary: `读取了 ${checkpoints.items.length} 个检查点`, payload: checkpoints }),
                )
              }
            />
            <ConfirmDialog
              title="清理该对话的检查点？"
              description="将删除当前对话的持久化检查点。此操作不可撤销。"
              confirmLabel="清理"
              confirmDisabled={busy !== null}
              onConfirm={async () => {
                const outcome = await runAction(
                  'clear-checkpoints',
                  '清理检查点',
                  () => chatApi.deleteCheckpoints(conversationId),
                  () => ({ summary: '已清理当前对话的检查点' }),
                )
                if (outcome.status === 'failed') throw outcome.error
              }}
            >
              <Button type="button" variant="outline" className="h-11 px-3 text-[13px] sm:h-9" disabled={busy !== null}>
                <Trash2 className="size-4" />
                清理检查点
              </Button>
            </ConfirmDialog>
          </div>
        </div>
      ) : null}

      {actionError !== undefined && (
        <p role="alert" className="mt-3 text-sm text-destructive">
          {actionError}
        </p>
      )}
      {result ? (
        <div className="mt-4 border-t border-border pt-4">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="text-sm font-medium text-foreground">{result.title}</div>
              <p className="mt-1 text-[13px] leading-5 text-muted-foreground">{result.summary}</p>
            </div>
            {hasResultDetails && (
              <Button
                variant="ghost"
                size="sm"
                className="h-11 w-fit px-2 text-xs sm:h-8"
                aria-expanded={resultDetailsOpen}
                onClick={() => setResultDetailsOpen((open) => !open)}
              >
                查看结果详情
              </Button>
            )}
          </div>
          {hasResultDetails && resultDetailsOpen ? (
            <pre
              className={cn(
                'mt-2 max-h-48 overflow-auto rounded-md border border-border/60 bg-background p-2 text-xs',
                'whitespace-pre-wrap break-words',
              )}
            >
              {JSON.stringify(result.payload, null, 2)}
            </pre>
          ) : null}
        </div>
      ) : null}
    </Panel>
  )
}

function ActionButton({
  busy,
  disabled,
  icon: Icon,
  label,
  onClick,
}: Readonly<{
  busy: boolean
  disabled: boolean
  icon: PlatformIcon
  label: string
  onClick: () => Promise<ActionOutcome>
}>) {
  return (
    <Button
      variant="outline"
      className="h-11 px-3 text-[13px] sm:h-9"
      disabled={disabled}
      onClick={() => void onClick()}
    >
      {busy ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> : <Icon className="size-4" />}
      {label}
    </Button>
  )
}
