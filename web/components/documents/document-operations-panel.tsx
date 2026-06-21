'use client'

import { useMemo, useState, type ReactNode } from 'react'
import { FileJson, FileText, FolderInput, Loader2 } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Panel } from '@/components/ui/panel'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { documentApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { cn, detachPromise } from '@/lib/utils'
import type { Dataset } from '@/types'

const NO_TARGET_DATASET = '__none__'

function prettyJson(value: unknown) {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function formatResultSummary(value: unknown) {
  if (value == null) return '操作已完成。'
  if (value instanceof Blob) return `已返回文件，大小 ${value.size} bytes。`
  if (Array.isArray(value)) return `已返回 ${value.length} 条记录。`
  if (typeof value === 'string') return value || '操作已完成。'
  if (typeof value === 'number' || typeof value === 'boolean') return String(value)
  if (typeof value !== 'object') return '操作已完成。'

  const record = value as Record<string, unknown>
  if (typeof record.message === 'string' && record.message.trim()) return record.message.trim()

  const itemCount = Array.isArray(record.items) ? record.items.length : null
  const documentCount = Array.isArray(record.documents) ? record.documents.length : null
  const duplicateCount = Array.isArray(record.groups) ? record.groups.length : null
  const count = getDocumentOperationCount(record)

  if (itemCount != null) return `已返回 ${itemCount} 条记录。`
  if (documentCount != null) return `已返回 ${documentCount} 个文档。`
  if (duplicateCount != null) return `发现 ${duplicateCount} 组结果。`
  if (count != null) return `本次返回 ${count} 条结果。`

  return `操作已完成，返回 ${Object.keys(record).length} 个字段。`
}

function getDocumentOperationCount(record: Record<string, unknown>): number | null {
  if (typeof record.count === 'number') return record.count
  if (typeof record.total === 'number') return record.total
  return null
}

export function DocumentOperationsPanel({
  selectedDocumentIds,
  datasetId,
  datasets = [],
}: Readonly<{
  selectedDocumentIds: string[]
  datasetId?: string | null
  datasets?: Dataset[]
}>) {
  const [targetDatasetId, setTargetDatasetId] = useState('')
  const [resultDetailsOpen, setResultDetailsOpen] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [result, setResult] = useState<{ title: string; payload: unknown } | null>(null)

  const ids = selectedDocumentIds
  const firstDocumentId = ids[0] || ''
  const effectiveDatasetId = String(datasetId || '').trim()
  const currentDatasetLabel = useMemo(() => {
    const dataset = datasets.find((item) => item.id === effectiveDatasetId)
    if (dataset?.name) return dataset.name
    return effectiveDatasetId || '全部知识库'
  }, [datasets, effectiveDatasetId])
  const targetDatasetOptions = useMemo(
    () => datasets.filter((dataset) => dataset.id && dataset.id !== effectiveDatasetId),
    [datasets, effectiveDatasetId]
  )
  const targetDatasetValue = targetDatasetId.trim() || NO_TARGET_DATASET
  const selectedScopeLabel = ids.length ? `${ids.length} 个文档` : '未勾选文档'
  const resultSummary = result ? formatResultSummary(result.payload) : null

  async function runAction(key: string, title: string, action: () => Promise<unknown>) {
    setBusy(key)
    try {
      const payload = await action()
      setResult({ title, payload })
      setResultDetailsOpen(false)
      toast.success(`${title}完成`)
    } catch (error) {
      toast.error(formatApiError(error, `${title}失败`))
    } finally {
      setBusy(null)
    }
  }

  return (
    <Panel
      padding="none"
      className="overflow-hidden border-border/50 bg-[linear-gradient(135deg,hsl(var(--card)/0.92),hsl(var(--surface-2)/0.58))] shadow-[0_14px_36px_-30px_hsl(var(--primary)/0.28)] ring-1 ring-card/70 dark:border-border/60 dark:bg-card/88 dark:ring-white/5"
    >
      <div className="flex flex-col gap-2 border-b border-border/50 px-3 py-2.5 lg:flex-row lg:items-start lg:justify-between dark:border-border/60">
        <div className="flex min-w-0 items-start gap-2.5">
          <div className="mt-0.5 flex size-7 shrink-0 items-center justify-center rounded-xl border border-info/18 bg-info/[0.08] text-info shadow-[inset_0_1px_0_hsl(var(--card)/0.86)] dark:border-info/25 dark:bg-info/10 dark:text-info">
            <FileJson className="size-4" />
          </div>
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <div className="text-[13px] font-semibold leading-none tracking-[-0.01em] text-foreground">文档高级操作</div>
              <span className="rounded-full border border-info/18 bg-info/[0.07] px-2 py-0.5 text-[10px] font-semibold leading-none text-info dark:border-info/25 dark:bg-info/10 dark:text-info">
                使用当前知识库和勾选文档
              </span>
            </div>
            <p className="mt-1 text-[11px] leading-4 text-muted-foreground">
              仅保留可直接执行的安全操作：统计、解析内容、重复文件、生命周期元数据和批量移动。
            </p>
          </div>
        </div>
        <div className="flex h-7 shrink-0 items-center gap-2 rounded-full border border-border/50 bg-background/72 px-2.5 text-[11px] text-muted-foreground shadow-[inset_0_1px_0_hsl(var(--card)/0.82)] dark:border-border/60 dark:bg-muted/20">
          {busy ? <Loader2 className="size-3.5 animate-spin text-info motion-reduce:animate-none" /> : <span className="size-1.5 rounded-full bg-success" />}
          <span>{busy ? '执行中' : '待操作'}</span>
        </div>
      </div>

      <div className="grid gap-2 px-3 py-2.5 lg:grid-cols-[minmax(0,1fr)_minmax(250px,0.58fr)]">
        <div className="rounded-[15px] border border-border/48 bg-card/66 p-2.5 shadow-[inset_0_1px_0_hsl(var(--card)/0.78)] dark:border-border/60 dark:bg-background/35">
          <div className="mb-2 flex items-center justify-between gap-2">
            <div className="text-[11px] font-semibold leading-none text-foreground/84">当前作用域</div>
            <div className="rounded-full bg-muted/45 px-2 py-0.5 text-[10px] text-muted-foreground">
              无需手填 ID
            </div>
          </div>
          <div className="grid gap-1.5 md:grid-cols-3">
            <ContextItem label="知识库" value={currentDatasetLabel} subValue={effectiveDatasetId || '全局范围'} />
            <ContextItem label="文档范围" value={selectedScopeLabel} subValue={firstDocumentId ? `默认文档 ${firstDocumentId.slice(0, 8)}` : '先在列表勾选文档'} />
            <ContextItem label="批量来源" value="当前勾选" subValue="无需手填文档 ID" />
          </div>
        </div>

        <div className="rounded-[15px] border border-border/48 bg-card/66 p-2.5 shadow-[inset_0_1px_0_hsl(var(--card)/0.78)] dark:border-border/60 dark:bg-background/35">
          <Field label="移动到知识库">
            <Select
              value={targetDatasetValue}
              onValueChange={(value) => setTargetDatasetId(value === NO_TARGET_DATASET ? '' : value)}
            >
              <SelectTrigger className="h-8 rounded-xl border-border/55 bg-background/78 text-[12px] shadow-none dark:border-border/60 dark:bg-background/70">
                <SelectValue placeholder="选择目标知识库" />
              </SelectTrigger>
              <SelectContent>
                <SelectItem value={NO_TARGET_DATASET}>不移动</SelectItem>
                {targetDatasetId && !targetDatasetOptions.some((dataset) => dataset.id === targetDatasetId) ? (
                  <SelectItem value={targetDatasetId}>自定义目标：{targetDatasetId.slice(0, 8)}</SelectItem>
                ) : null}
                {targetDatasetOptions.map((dataset) => (
                  <SelectItem key={dataset.id} value={dataset.id}>
                    {dataset.name || dataset.id}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
            <div className="mt-1.5 rounded-lg bg-muted/30 px-2 py-1 text-[10px] leading-4 text-muted-foreground dark:bg-muted/20">
              仅批量移动需要选择目标库；只读操作会自动使用当前知识库。
            </div>
          </Field>
        </div>
      </div>

      <div className="px-3 pb-2.5">
        <div className="rounded-[15px] border border-border/48 bg-muted/[0.14] p-2.5 shadow-[inset_0_1px_0_hsl(var(--card)/0.74)] dark:border-border/60 dark:bg-muted/10">
          <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
            <div className="text-[11px] font-semibold leading-none text-foreground/84">操作区</div>
            <div className="text-[10px] text-muted-foreground">按当前作用域自动带入参数</div>
          </div>
          <div className="grid gap-2 xl:grid-cols-[minmax(0,1fr)_minmax(260px,0.52fr)]">
            <ActionGroup icon={FileText} title="读取 / 诊断" description="只读操作，不改变文档。">
              <ActionButton icon={FileJson} busy={busy === 'stats'} disabled={Boolean(busy)} label="文档统计" onClick={() => runAction('stats', '文档统计', () => documentApi.stats({ dataset_id: effectiveDatasetId || undefined }))} />
              <ActionButton icon={FileJson} busy={busy === 'parsed'} disabled={Boolean(busy) || !firstDocumentId} label="查看解析内容" onClick={() => runAction('parsed', '解析内容', () => documentApi.getParsedContent(firstDocumentId, { max_chars: 20_000 }))} />
              <ActionButton icon={FileJson} busy={busy === 'duplicates'} disabled={Boolean(busy) || !effectiveDatasetId} label="重复文档" onClick={() => runAction('duplicates', '重复文档', () => documentApi.listDuplicates({ dataset_id: effectiveDatasetId, min_count: 2, max_groups: 20, max_docs_per_group: 10 }))} />
              <ActionButton icon={FileJson} busy={busy === 'lifecycle'} disabled={Boolean(busy) || !firstDocumentId} label="生命周期元数据" onClick={() => runAction('lifecycle', '生命周期元数据', () => documentApi.getLifecycleMetadata(firstDocumentId))} />
            </ActionGroup>
            <ActionGroup icon={FolderInput} title="批量变更" description="仅使用当前勾选文档。">
              <ActionButton icon={FolderInput} busy={busy === 'move'} disabled={Boolean(busy) || ids.length === 0 || !targetDatasetId.trim()} label="批量移动" onClick={() => runAction('move', '批量移动', () => documentApi.batchMove({ document_ids: ids, target_dataset_id: targetDatasetId.trim() }))} />
            </ActionGroup>
          </div>
        </div>
      </div>

      {result ? (
        <div className="mx-3 mb-3 overflow-hidden rounded-[15px] border border-success/22 bg-[linear-gradient(135deg,hsl(var(--success)/0.08),hsl(var(--card)/0.70))] shadow-[inset_0_1px_0_hsl(var(--card)/0.72)] dark:bg-success/[0.06]">
          <div className="flex flex-col gap-2 px-3 py-2.5 sm:flex-row sm:items-start sm:justify-between">
            <div className="flex min-w-0 gap-2.5">
              <span className="mt-1 size-2 shrink-0 rounded-full bg-success shadow-[0_0_0_4px_hsl(var(--success)/0.12)]" />
              <div className="min-w-0">
                <div className="flex flex-wrap items-center gap-2">
                  <div className="text-[12px] font-semibold text-foreground">{result.title}已完成</div>
                  <span className="rounded-full border border-success/22 bg-card/68 px-2 py-0.5 text-[10px] font-medium text-success dark:bg-success/10 dark:text-success">
                    完成
                  </span>
                </div>
                <div className="mt-1 text-[12px] leading-5 text-muted-foreground">{resultSummary}</div>
              </div>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 shrink-0 rounded-full border border-success/18 bg-card/58 px-2.5 text-[11px] font-medium text-success hover:bg-card/86 dark:bg-success/10 dark:text-success"
              aria-expanded={resultDetailsOpen}
              onClick={() => setResultDetailsOpen((open) => !open)}
            >
              原始响应
            </Button>
          </div>
          {resultDetailsOpen ? (
            <pre className={cn('max-h-56 overflow-auto border-t border-success/16 bg-background/78 p-2.5 text-[11px] leading-5 dark:bg-background/80', 'whitespace-pre-wrap break-words')}>
              {prettyJson(result.payload)}
            </pre>
          ) : null}
        </div>
      ) : null}
    </Panel>
  )
}

function Field({ label, children }: Readonly<{ label: string; children: ReactNode }>) {
  return (
    <div className="space-y-1">
      <Label className="text-[11px] font-semibold leading-none text-foreground/74 dark:text-muted-foreground">{label}</Label>
      {children}
    </div>
  )
}

function ContextItem({
  label,
  value,
  subValue,
}: Readonly<{
  label: string
  value: string
  subValue: string
}>) {
  return (
    <div className="min-w-0 rounded-xl border border-border/45 bg-background/70 px-2.5 py-2 shadow-[inset_0_1px_0_hsl(var(--card)/0.74)] dark:border-border/60 dark:bg-background/45">
      <div className="text-[10px] font-medium leading-none text-muted-foreground/62">{label}</div>
      <div className="mt-1.5 truncate text-[12px] font-semibold leading-none text-foreground/90" title={value}>
        {value}
      </div>
      <div className="mt-1 truncate text-[10px] leading-none text-muted-foreground/72" title={subValue}>
        {subValue}
      </div>
    </div>
  )
}

function ActionGroup({
  children,
  description,
  icon: Icon,
  title,
}: Readonly<{
  children: ReactNode
  description: string
  icon: LucideIcon
  title: string
}>) {
  return (
    <section className="rounded-[15px] border border-border/45 bg-card/70 p-2.5 shadow-[inset_0_1px_0_hsl(var(--card)/0.76)] dark:border-border/60 dark:bg-background/35">
      <div className="mb-2.5 flex items-start gap-2">
        <div className="flex size-7 shrink-0 items-center justify-center rounded-xl border border-border/50 bg-muted/28 text-muted-foreground dark:border-border/60 dark:bg-muted/20 dark:text-muted-foreground">
          <Icon className="size-3.5" />
        </div>
        <div className="min-w-0">
          <div className="text-[12px] font-semibold leading-none text-foreground/90">{title}</div>
          <div className="mt-1 text-[10px] leading-[14px] text-muted-foreground">{description}</div>
        </div>
      </div>
      <div className="grid gap-1.5 sm:grid-cols-2 xl:grid-cols-1 2xl:grid-cols-2">{children}</div>
    </section>
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
    <Button size="sm" variant="ghost" className="h-8 justify-start gap-1.5 rounded-xl border border-border/50 bg-background/74 px-2.5 text-[12px] font-medium text-foreground/78 shadow-[inset_0_1px_0_hsl(var(--card)/0.74)] hover:border-info/24 hover:bg-card/92 hover:text-foreground hover:shadow-sm disabled:border-border/35 disabled:bg-muted/25 disabled:text-muted-foreground/45 disabled:opacity-100 dark:border-border/60 dark:bg-background/45 dark:text-muted-foreground dark:hover:bg-muted/45 dark:hover:text-foreground" disabled={disabled} onClick={() => detachPromise(onClick())}>
      {busy ? <Loader2 className="size-3.5 animate-spin text-info motion-reduce:animate-none" /> : <Icon className="size-3.5" />}
      {label}
    </Button>
  )
}
