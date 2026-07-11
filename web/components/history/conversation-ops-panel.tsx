'use client'

import { useEffect, useState } from 'react'
import { ChevronDown, Download, GitCommitVertical, Loader2, MessageSquarePlus, Trash2 } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Panel } from '@/components/ui/panel'
import { chatApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { cn, detachPromise } from '@/lib/utils'

const QUICK_ACTIONS = ['Markdown', 'JSON', '检查点', '清缓存'] as const

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

export function ConversationOpsPanel({ conversationId }: Readonly<{ conversationId?: string | null }>) {
  const [manualConversationId, setManualConversationId] = useState(conversationId || '')
  const [panelOpen, setPanelOpen] = useState(false)
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
      padding="md"
      className={cn(
        'relative overflow-hidden border-border/60 shadow-[0_12px_36px_rgba(15,23,42,0.08)] transition-all duration-200 motion-reduce:transition-none',
        'bg-[linear-gradient(135deg,rgba(248,250,252,0.98),rgba(239,248,255,0.86)_48%,rgba(244,255,249,0.72))]',
        'dark:border-slate-800/90 dark:bg-[linear-gradient(135deg,rgba(15,23,42,0.96),rgba(8,47,73,0.72)_52%,rgba(6,78,59,0.46))]',
        panelOpen ? 'rounded-2xl' : 'rounded-[1.35rem] py-3'
      )}
    >
      <div className="pointer-events-none absolute inset-y-2 left-0 w-1 rounded-r-full bg-[linear-gradient(180deg,hsl(var(--info)/0.6),hsl(var(--primary)/0.72),hsl(var(--success)/0.6))]" />
      <div className="pointer-events-none absolute -right-10 -top-10 h-28 w-28 rounded-full bg-info/16 blur-2xl dark:bg-info/10" />
      <div className="pointer-events-none absolute inset-x-8 top-0 h-px bg-[linear-gradient(90deg,transparent,hsl(var(--info)/0.56),transparent)]" />
      <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
        <button
          type="button"
          className="group flex min-w-0 flex-1 items-center gap-3 rounded-2xl py-0.5 pl-1 text-left outline-none transition focus-visible:ring-2 focus-visible:ring-info/50 focus-visible:ring-offset-2 focus-visible:ring-offset-background"
          aria-expanded={panelOpen}
          onClick={() => setPanelOpen((open) => !open)}
        >
          <span
            className={cn(
              'flex h-9 w-9 shrink-0 items-center justify-center rounded-2xl border shadow-sm transition-all',
              panelOpen
                ? 'border-info/30 bg-info/14 text-info dark:text-info'
                : 'border-info/18 bg-background/85 text-info group-hover:-translate-y-0.5 group-hover:border-info/28 group-hover:bg-info/10 dark:text-info'
            )}
          >
            <ChevronDown className={cn('h-4 w-4 transition-transform', panelOpen ? 'rotate-0' : '-rotate-90')} />
          </span>
          <span className="min-w-0">
            <span className="flex flex-wrap items-center gap-2">
              <span className="text-sm font-semibold tracking-[-0.01em] text-foreground">对话运维工具箱</span>
              <span className="rounded-full border border-info/15 bg-info/10 px-2 py-0.5 text-[10px] font-semibold text-info dark:text-info">
                导出 · 检查点
              </span>
            </span>
            <span className="mt-1 block truncate text-xs text-muted-foreground">
              {panelOpen
                ? '当前对话已绑定，可执行导出、检查点查询和缓存清理。'
                : '已收起，展开后可导出对话、查看检查点或清理缓存。'}
            </span>
            {!panelOpen ? (
              <span className="mt-2 hidden flex-wrap items-center gap-1.5 sm:flex">
                {QUICK_ACTIONS.map((label) => (
                  <span
                    key={label}
                    className="rounded-full border border-border/55 bg-background/78 px-2.5 py-1 text-[11px] font-medium text-muted-foreground shadow-[0_1px_0_hsl(var(--background)/0.9)_inset] backdrop-blur dark:border-border/20 dark:bg-background/20 dark:text-slate-300"
                  >
                    {label}
                  </span>
                ))}
              </span>
            ) : null}
          </span>
        </button>
        <div className="flex items-center gap-2 sm:justify-end">
          <span
            className={cn(
              'w-fit rounded-full border px-2.5 py-1 text-[11px] font-semibold shadow-sm',
              hasConversation
                ? 'border-success/25 bg-success/10 text-success dark:text-emerald-200'
                : 'border-muted-foreground/15 bg-muted/40 text-muted-foreground'
            )}
          >
            {hasConversation ? '已绑定' : '未选择'}
          </span>
          <Button
            type="button"
            variant="outline"
            size="sm"
            className={cn(
              'h-8 rounded-full border-info/22 px-3 text-xs font-semibold shadow-sm transition',
              panelOpen
                ? 'bg-background/75 hover:border-info/38 hover:bg-info/10'
                : 'bg-foreground text-background hover:border-foreground hover:bg-foreground/86 dark:bg-info/80 dark:text-background dark:hover:bg-info/70'
            )}
            onClick={() => setPanelOpen((open) => !open)}
          >
            {panelOpen ? '收起面板' : '展开操作'}
          </Button>
          {busy ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground motion-reduce:animate-none" /> : null}
        </div>
      </div>

      {panelOpen ? (
        <>
          <div className="mt-3 rounded-2xl border border-info bg-background/70 p-3 shadow-[0_1px_0_rgba(255,255,255,0.7)_inset]">
            <div className="text-xs font-semibold text-foreground">当前对话自动绑定</div>
            <p className="mt-1 text-[11px] leading-5 text-muted-foreground">
              {hasConversation
                ? '可直接导出、查看检查点列表或清理缓存，不需要手动填写后端 ID。'
                : '请先在左侧选择一个对话，导出和检查点操作会自动启用。'}
            </p>
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
                className="h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold"
                disabled={Boolean(busy) || !effectiveConversationId}
              >
                {busy === 'delete-checkpoints' ? (
                  <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" />
                ) : (
                  <Trash2 className="h-3.5 w-3.5" />
                )}
                清理检查点
              </Button>
            </ConfirmDialog>
          </div>
        </>
      ) : null}

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
