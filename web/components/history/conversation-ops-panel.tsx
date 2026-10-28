'use client'

import { useEffect, useState } from 'react'
import { ChevronDown, Download, GitCommitVertical, Loader2, MessageSquarePlus, Trash2 } from '@/components/icons'
import type { PlatformIcon } from '@/components/icons'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Panel } from '@/components/ui/panel'
import { chatApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { cn, detachPromise } from '@/lib/utils'

function prettyJson(value: unknown) {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return Object.prototype.toString.call(value)
  }
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

function formatBytes(bytes: number) {
  if (!Number.isFinite(bytes) || bytes <= 0) return '0 B'
  const units = ['B', 'KB', 'MB', 'GB']
  const unitIndex = Math.min(Math.floor(Math.log(bytes) / Math.log(1024)), units.length - 1)
  const value = bytes / 1024 ** unitIndex
  return `${value.toFixed(unitIndex === 0 ? 0 : 1)} ${units[unitIndex]}`
}

function formatResultSummary(payload: unknown) {
  if (payload == null) return '操作已完成。'
  if (Array.isArray(payload)) return `返回 ${payload.length} 条记录。`
  if (typeof payload === 'string') return payload.trim() || '操作已完成。'
  if (typeof payload === 'number' || typeof payload === 'boolean' || typeof payload === 'bigint') {
    return String(payload)
  }
  if (typeof payload !== 'object') return Object.prototype.toString.call(payload)

  const record = payload as Record<string, unknown>
  if (typeof record.message === 'string' && record.message.trim()) return record.message.trim()
  if (typeof record.bytes === 'number') return `文件已生成，大小 ${formatBytes(record.bytes)}。`
  if (Array.isArray(record.items)) return `返回 ${record.items.length} 个检查点。`
  if (record.deleted === true) return '已清理当前对话的检查点。'
  if (typeof record.id === 'string') return '新对话已创建，后续操作会自动使用该对话。'
  return `操作已完成，返回 ${Object.keys(record).length} 个字段。`
}

export function ConversationOpsPanel({ conversationId, initiallyExpanded = false }: Readonly<{ conversationId?: string | null; initiallyExpanded?: boolean }>) {
  const [manualConversationId, setManualConversationId] = useState(conversationId || '')
  const [panelOpen, setPanelOpen] = useState(initiallyExpanded)
  const [resultDetailsOpen, setResultDetailsOpen] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [result, setResult] = useState<{ title: string; payload: unknown } | null>(null)

  useEffect(() => {
    setManualConversationId(conversationId || '')
  }, [conversationId])

  const effectiveConversationId = manualConversationId.trim() || String(conversationId || '').trim()
  const hasConversation = Boolean(effectiveConversationId)

  async function runAction(key: string, title: string, action: () => Promise<unknown>) {
    setBusy(key)
    try {
      const payload = await action()
      setResult({ title, payload })
      setResultDetailsOpen(false)
      const createdId = typeof (payload as { id?: unknown })?.id === 'string' ? String((payload as { id: string }).id) : ''
      if (createdId) setManualConversationId(createdId)
      toast.success(`${title}完成`)
    } catch (error) {
      toast.error(formatApiError(error, `${title}失败`))
    } finally {
      setBusy(null)
    }
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
          <ChevronDown className={cn('size-4 text-muted-foreground transition-transform motion-reduce:transition-none', panelOpen ? 'rotate-0' : '-rotate-90')} />
          <span>对话操作</span>
          <span className="hidden text-xs font-normal text-muted-foreground sm:inline">导出与检查点</span>
          <span className="ml-auto text-xs font-normal text-muted-foreground">
            {panelOpen ? '收起' : '展开'}
          </span>
          {busy ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground motion-reduce:animate-none" /> : null}
        </Button>

      {panelOpen ? (
        <div id="history-conversation-actions">
          {!hasConversation && (
            <p className="mt-3 text-sm leading-6 text-muted-foreground">
              请先选择一段对话。
            </p>
          )}

          <div className="mt-3 flex flex-wrap gap-2">
            <ActionButton
              icon={MessageSquarePlus}
              busy={busy === 'create'}
              disabled={Boolean(busy)}
              label="创建空白对话"
              onClick={() => runAction('create', '创建对话', () => chatApi.createConversation({ title: '新建对话' }))}
            />
            <Button
              variant="outline"
              className="h-11 px-3 text-[13px] sm:h-9"
              disabled={Boolean(busy) || !effectiveConversationId}
              onClick={() =>
                detachPromise(
                  runAction('export-md', '导出 Markdown', async () => {
                    const blob = await chatApi.exportConversation(effectiveConversationId, {
                      fmt: 'markdown',
                      include_citations: true,
                    })
                    downloadBlob(blob, 'conversation.md')
                    return { bytes: blob.size, type: blob.type }
                  })
                )
              }
            >
              <Download className="size-4" />
              导出 Markdown
            </Button>
            <Button
              variant="outline"
              className="h-11 px-3 text-[13px] sm:h-9"
              disabled={Boolean(busy) || !effectiveConversationId}
              onClick={() =>
                detachPromise(
                  runAction('export-json', '导出 JSON', async () => {
                    const blob = await chatApi.exportConversation(effectiveConversationId, {
                      fmt: 'json',
                      include_citations: true,
                    })
                    downloadBlob(blob, 'conversation.json')
                    return { bytes: blob.size, type: blob.type }
                  })
                )
              }
            >
              <Download className="size-4" />
              导出 JSON
            </Button>
            <ActionButton
              icon={GitCommitVertical}
              busy={busy === 'checkpoints'}
              disabled={Boolean(busy) || !effectiveConversationId}
              label="检查点列表"
              onClick={() =>
                runAction('checkpoints', '检查点列表', () =>
                  chatApi.listCheckpoints(effectiveConversationId, { limit: 20, include_values: false })
                )
              }
            />
            <ConfirmDialog
              title="清理该对话的检查点？"
              description="将删除当前对话的持久化检查点。此操作不可撤销。"
              confirmLabel="清理"
              onConfirm={() =>
                runAction('delete-checkpoints', '清理检查点', async () => {
                  await chatApi.deleteCheckpoints(effectiveConversationId)
                  return { deleted: true }
                })
              }
            >
              <Button
                variant="outline"
                className="h-11 px-3 text-[13px] sm:h-9"
                disabled={Boolean(busy) || !effectiveConversationId}
              >
                {busy === 'delete-checkpoints' ? (
                  <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
                ) : (
                  <Trash2 className="size-4" />
                )}
                清理检查点
              </Button>
            </ConfirmDialog>
          </div>
        </div>
      ) : null}

      {result ? (
        <div className="mt-4 border-t border-border pt-4">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="text-sm font-medium text-foreground">{result.title}</div>
              <p className="mt-1 text-[13px] leading-5 text-muted-foreground">{formatResultSummary(result.payload)}</p>
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="h-11 w-fit px-2 text-xs sm:h-8"
              aria-expanded={resultDetailsOpen}
              onClick={() => setResultDetailsOpen((open) => !open)}
            >
              查看原始响应
            </Button>
          </div>
          {resultDetailsOpen ? (
            <pre
              className={cn(
                'mt-2 max-h-48 overflow-auto rounded-md border border-border/60 bg-background p-2 text-xs',
                'whitespace-pre-wrap break-words'
              )}
            >
              {prettyJson(result.payload)}
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
  onClick: () => Promise<void>
}>) {
  return (
    <Button variant="outline" className="h-11 px-3 text-[13px] sm:h-9" disabled={disabled} onClick={() => detachPromise(onClick())}>
      {busy ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> : <Icon className="size-4" />}
      {label}
    </Button>
  )
}
