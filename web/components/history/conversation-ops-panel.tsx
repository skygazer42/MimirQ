'use client'

import { useEffect, useState } from 'react'
import { Download, GitCommitVertical, Loader2, MessageSquarePlus, Trash2 } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
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
  if (Array.isArray(record.items)) return `返回 ${record.items.length} 个 checkpoint。`
  if (record.deleted === true) return '已清理当前对话的 checkpoints。'
  if (typeof record.id === 'string') return '新对话已创建，后续操作会自动使用该对话。'
  return `操作已完成，返回 ${Object.keys(record).length} 个字段。`
}

export function ConversationOpsPanel({ conversationId }: Readonly<{ conversationId?: string | null }>) {
  const [manualConversationId, setManualConversationId] = useState(conversationId || '')
  const [checkpointId, setCheckpointId] = useState('')
  const [advancedOpen, setAdvancedOpen] = useState(false)
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
    <Panel padding="md" className="border-border/60 bg-background/82 shadow-sm">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-sm font-semibold text-foreground">对话导出与 Checkpoint</div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            当前对话已自动绑定，默认只保留可点击动作；单个 checkpoint 排查放在高级调试里。
          </p>
        </div>
        {busy ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground motion-reduce:animate-none" /> : null}
      </div>

      <div className="mt-3 rounded-xl border border-blue-500/15 bg-blue-500/[0.04] p-3">
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <div className="text-xs font-semibold text-foreground">当前对话已自动绑定</div>
            <p className="mt-1 text-[11px] leading-5 text-muted-foreground">
              {hasConversation
                ? '可直接导出、查看 checkpoint 列表或清理缓存，不需要手动填写后端 ID。'
                : '请先在左侧选择一个对话，导出和 checkpoint 操作会自动启用。'}
            </p>
          </div>
          <span
            className={cn(
              'w-fit rounded-full border px-2.5 py-1 text-[11px] font-semibold',
              hasConversation
                ? 'border-emerald-500/20 bg-emerald-500/10 text-emerald-700'
                : 'border-muted-foreground/15 bg-muted/40 text-muted-foreground'
            )}
          >
            {hasConversation ? '已就绪' : '未选择'}
          </span>
        </div>
      </div>

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
          className="h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold"
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
          <Download className="h-3.5 w-3.5" />
          导出 Markdown
        </Button>
        <Button
          variant="outline"
          className="h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold"
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
          <Download className="h-3.5 w-3.5" />
          导出 JSON
        </Button>
        <ActionButton
          icon={GitCommitVertical}
          busy={busy === 'checkpoints'}
          disabled={Boolean(busy) || !effectiveConversationId}
          label="Checkpoint 列表"
          onClick={() =>
            runAction('checkpoints', 'Checkpoint 列表', () =>
              chatApi.listCheckpoints(effectiveConversationId, { limit: 20, include_values: false })
            )
          }
        />
        <ConfirmDialog
          title="清理该对话的 Checkpoints？"
          description="将删除当前对话的持久化 checkpoints。此操作不可撤销。"
          confirmLabel="清理"
          onConfirm={() => runAction('delete-checkpoints', '清理 Checkpoints', async () => {
            await chatApi.deleteCheckpoints(effectiveConversationId)
            return { deleted: true }
          })}
        >
          <Button variant="outline" className="h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold" disabled={Boolean(busy) || !effectiveConversationId}>
            {busy === 'delete-checkpoints' ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <Trash2 className="h-3.5 w-3.5" />}
            清理 Checkpoints
          </Button>
        </ConfirmDialog>
      </div>

      <div className="mt-3 rounded-xl border border-border/60 bg-muted/15">
        <button
          type="button"
          className="flex w-full flex-col gap-1 p-3 text-left transition hover:bg-muted/20"
          aria-expanded={advancedOpen}
          onClick={() => setAdvancedOpen((open) => !open)}
        >
          <span className="text-xs font-semibold text-foreground">高级调试（可选）</span>
          <span className="text-[11px] leading-5 text-muted-foreground">
            仅在需要查看单个 checkpoint 详情时打开，普通运维不需要填写任何后端 ID。
          </span>
        </button>
        {advancedOpen ? (
          <div className="border-t border-border/60 p-3">
            <div className="grid gap-2 sm:grid-cols-[minmax(0,1fr)_auto] sm:items-end">
              <div className="space-y-1">
                <div className="text-[11px] font-medium text-muted-foreground">Checkpoint 编号</div>
                <Input
                  value={checkpointId}
                  onChange={(event) => setCheckpointId(event.target.value)}
                  placeholder="从 checkpoint 列表复制编号，仅排查时使用"
                  className="h-8 font-mono text-xs"
                />
              </div>
              <ActionButton
                icon={GitCommitVertical}
                busy={busy === 'checkpoint'}
                disabled={Boolean(busy) || !effectiveConversationId || !checkpointId.trim()}
                label="查看详情"
                onClick={() =>
                  runAction('checkpoint', 'Checkpoint 详情', () =>
                    chatApi.getCheckpoint(effectiveConversationId, checkpointId.trim(), { include_values: true })
                  )
                }
              />
            </div>
          </div>
        ) : null}
      </div>

      {result ? (
        <div className="mt-3 rounded-lg border border-border/60 bg-muted/20 p-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div>
              <div className="text-xs font-semibold text-foreground">{result.title}</div>
              <p className="mt-1 text-xs leading-5 text-muted-foreground">{formatResultSummary(result.payload)}</p>
            </div>
            <Button
              variant="ghost"
              size="sm"
              className="h-7 w-fit rounded-lg px-2 text-[11px] font-semibold"
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
  icon: LucideIcon
  label: string
  onClick: () => Promise<void>
}>) {
  return (
    <Button variant="outline" className="h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold" disabled={disabled} onClick={() => detachPromise(onClick())}>
      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <Icon className="h-3.5 w-3.5" />}
      {label}
    </Button>
  )
}
