'use client'

import { useId, useMemo, useRef, useState, type ReactNode } from 'react'
import { FileJson, FileText, FolderInput, Loader2, Search } from '@/components/icons'
import type { PlatformIcon } from '@/components/icons'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { documentApi } from '@/lib/api/documents'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionKey } from '@/lib/auth-storage'
import { detachPromise } from '@/lib/utils'
import type { DocumentBatchMoveResponse } from '@/types/backend'
import type { Dataset } from '@/types/datasets'

type DocumentOperationsPanelProps = {
  selectedDocumentIds: string[]
  datasetId?: string | null
  datasets?: Dataset[]
  onRefresh: () => Promise<void>
}

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
  onRefresh,
}: Readonly<DocumentOperationsPanelProps>) {
  const targetSelectId = useId()
  const operationRef = useRef<object | null>(null)
  const [targetDatasetId, setTargetDatasetId] = useState('')
  const [resultDetailsOpen, setResultDetailsOpen] = useState(false)
  const [busy, setBusy] = useState<string | null>(null)
  const [result, setResult] = useState<{ title: string; payload: unknown; summary: string } | null>(null)

  const ids = selectedDocumentIds
  const firstDocumentId = ids.at(0)
  const trimmedDatasetId = datasetId?.trim()
  const effectiveDatasetId = trimmedDatasetId === '' ? undefined : trimmedDatasetId
  const currentDatasetLabel = useMemo(() => {
    const dataset = datasets.find((item) => item.id === effectiveDatasetId)
    if (dataset?.name) return dataset.name
    return effectiveDatasetId || '全部知识库'
  }, [datasets, effectiveDatasetId])
  const targetDatasetOptions = useMemo(
    () => datasets.filter((dataset) => dataset.id && dataset.id !== effectiveDatasetId),
    [datasets, effectiveDatasetId],
  )
  const normalizedTargetDatasetId = targetDatasetId.trim()
  const targetDatasetValue = normalizedTargetDatasetId || NO_TARGET_DATASET
  const selectedScopeLabel = ids.length ? `${ids.length} 个文档` : '未勾选文档'
  async function runAction<Payload>(
    key: string,
    title: string,
    action: () => Promise<Payload>,
    onResult?: (payload: Payload) => string,
  ) {
    if (operationRef.current !== null) return
    const operation = {}
    const sessionKey = getAuthSessionKey()
    operationRef.current = operation
    setBusy(key)
    try {
      const payload = await action()
      if (getAuthSessionKey() !== sessionKey) return
      const summary = onResult === undefined ? formatResultSummary(payload) : onResult(payload)
      setResult({ title, payload, summary })
      setResultDetailsOpen(false)
      if (onResult === undefined) toast.success(`${title}完成`)
    } catch (error) {
      if (getAuthSessionKey() === sessionKey) toast.error(formatApiError(error, `${title}失败`))
    } finally {
      if (operationRef.current === operation) {
        operationRef.current = null
        setBusy(null)
      }
    }
  }

  function showMoveResult(payload: DocumentBatchMoveResponse): string {
    const skipped = (payload.not_found?.length ?? 0) + (payload.denied?.length ?? 0) + (payload.conflicts?.length ?? 0)
    const summary =
      skipped > 0 ? `移动了 ${payload.moved} 个文档，${skipped} 个未移动。` : `移动了 ${payload.moved} 个文档。`
    if (skipped > 0) toast.warning(summary)
    else if (payload.moved > 0) toast.success(summary)
    else toast.info(summary)
    if (payload.moved > 0) {
      const sessionKey = getAuthSessionKey()
      detachPromise(
        onRefresh().catch((error) => {
          if (getAuthSessionKey() === sessionKey) toast.error(formatApiError(error, '刷新文档列表失败'))
        }),
      )
    }
    return summary
  }

  return (
    <div className="space-y-6">
      <dl className="grid grid-cols-2 gap-4 border-b pb-5 text-[13px]">
        <div className="min-w-0">
          <dt className="text-muted-foreground">当前知识库</dt>
          <dd className="mt-1 break-words">{currentDatasetLabel}</dd>
        </div>
        <div>
          <dt className="text-muted-foreground">当前选择</dt>
          <dd className="mt-1">{selectedScopeLabel}</dd>
        </div>
      </dl>

      <section className="space-y-3" aria-label="读取与诊断">
        <h3 className="text-[13px] font-medium">读取与诊断</h3>
        <div className="grid gap-2 sm:grid-cols-2">
          <ActionButton
            icon={FileJson}
            busy={busy === 'stats'}
            disabled={Boolean(busy)}
            label="文档统计"
            onClick={() => runAction('stats', '文档统计', () => documentApi.stats({ dataset_id: effectiveDatasetId }))}
          />
          <ActionButton
            icon={FileText}
            busy={busy === 'parsed'}
            disabled={Boolean(busy) || !firstDocumentId}
            label="查看解析内容"
            onClick={async () => {
              if (!firstDocumentId) return
              return runAction('parsed', '解析内容', () =>
                documentApi.getParsedContent(firstDocumentId, { max_chars: 20_000 }),
              )
            }}
          />
          <ActionButton
            icon={Search}
            busy={busy === 'duplicates'}
            disabled={Boolean(busy) || !effectiveDatasetId}
            label="重复文档"
            onClick={async () => {
              if (effectiveDatasetId === undefined) return
              return runAction('duplicates', '重复文档', () =>
                documentApi.listDuplicates({
                  dataset_id: effectiveDatasetId,
                  min_count: 2,
                  max_groups: 20,
                  max_docs_per_group: 10,
                }),
              )
            }}
          />
          <ActionButton
            icon={FileJson}
            busy={busy === 'lifecycle'}
            disabled={Boolean(busy) || !firstDocumentId}
            label="生命周期元数据"
            onClick={async () => {
              if (!firstDocumentId) return
              return runAction('lifecycle', '生命周期元数据', () => documentApi.getLifecycleMetadata(firstDocumentId))
            }}
          />
        </div>
        <p className="text-xs leading-5 text-muted-foreground">
          解析内容与生命周期读取首个勾选文档；重复文档需先选择数据集。
        </p>
      </section>

      <section className="space-y-3 border-t pt-5" aria-label="批量移动">
        <h3 className="text-[13px] font-medium">批量移动</h3>
        <Field id={targetSelectId} label="移动到知识库">
          <div className="flex flex-wrap items-center gap-2">
            <Select
              value={targetDatasetValue}
              onValueChange={(value) => setTargetDatasetId(value === NO_TARGET_DATASET ? '' : value)}
              disabled={Boolean(busy)}
            >
              <SelectTrigger id={targetSelectId} className="h-9 min-w-0 flex-1 text-[13px]">
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
            <ActionButton
              icon={FolderInput}
              busy={busy === 'move'}
              disabled={Boolean(busy) || ids.length === 0 || normalizedTargetDatasetId === ''}
              label="批量移动"
              onClick={async () => {
                if (ids.length === 0 || normalizedTargetDatasetId === '') return
                return runAction(
                  'move',
                  '批量移动',
                  () => documentApi.batchMove({ document_ids: ids, target_dataset_id: normalizedTargetDatasetId }),
                  showMoveResult,
                )
              }}
            />
          </div>
        </Field>
        <p className="text-xs leading-5 text-muted-foreground">仅移动当前勾选文档。</p>
      </section>

      {result ? (
        <section className="space-y-3 border-t pt-5" aria-label="操作结果">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0 text-[13px] leading-6">
              <h3 className="font-medium">{result.title}</h3>
              <p className="text-muted-foreground">{result.summary}</p>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              aria-expanded={resultDetailsOpen}
              onClick={() => setResultDetailsOpen((open) => !open)}
            >
              原始响应
            </Button>
          </div>
          {resultDetailsOpen ? (
            <pre className="max-h-56 overflow-auto whitespace-pre-wrap break-words rounded-md bg-muted/50 p-3 text-xs leading-5">
              {prettyJson(result.payload)}
            </pre>
          ) : null}
        </section>
      ) : null}
    </div>
  )
}

function Field({ id, label, children }: Readonly<{ id: string; label: string; children: ReactNode }>) {
  return (
    <div className="space-y-2">
      <Label htmlFor={id} className="text-[13px] font-normal text-muted-foreground">
        {label}
      </Label>
      {children}
    </div>
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
    <Button
      size="sm"
      variant="outline"
      className="min-h-9 justify-start gap-2 text-[13px] max-sm:min-h-11"
      disabled={disabled}
      onClick={() => detachPromise(onClick())}
    >
      {busy ? <Loader2 className="size-4 animate-spin motion-reduce:animate-none" /> : <Icon className="size-4" />}
      {label}
    </Button>
  )
}
