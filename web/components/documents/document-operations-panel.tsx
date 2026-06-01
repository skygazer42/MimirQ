'use client'

import { useEffect, useMemo, useState, type ReactNode } from 'react'
import { Download, FileJson, FolderInput, ImageIcon, Loader2, ShieldCheck } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Panel } from '@/components/ui/panel'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { documentApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { cn, detachPromise } from '@/lib/utils'
import type { BatchFileInfo, Dataset } from '@/types'

const NO_TARGET_DATASET = '__none__'

function prettyJson(value: unknown) {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function parseJson(raw: string) {
  const value = raw.trim()
  return value ? JSON.parse(value) : {}
}

function parseIds(raw: string) {
  return raw
    .split(/[,\n]/g)
    .map((item) => item.trim())
    .filter(Boolean)
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
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

function getBatchUploadFiles(parsed: unknown): BatchFileInfo[] {
  if (Array.isArray(parsed)) return parsed as BatchFileInfo[]
  if (Array.isArray((parsed as { files?: BatchFileInfo[] })?.files)) {
    return (parsed as { files: BatchFileInfo[] }).files
  }
  return []
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
  const [documentId, setDocumentId] = useState('')
  const [datasetInput, setDatasetInput] = useState(datasetId || '')
  const [targetDatasetId, setTargetDatasetId] = useState('')
  const [batchId, setBatchId] = useState('')
  const [imageId, setImageId] = useState('')
  const [imgId, setImgId] = useState('')
  const [documentIdsRaw, setDocumentIdsRaw] = useState('')
  const [advancedOpen, setAdvancedOpen] = useState(false)
  const [resultDetailsOpen, setResultDetailsOpen] = useState(false)
  const [payloadJson, setPayloadJson] = useState('{\n  "access": {},\n  "metadata": {},\n  "files": []\n}')
  const [busy, setBusy] = useState<string | null>(null)
  const [result, setResult] = useState<{ title: string; payload: unknown } | null>(null)

  useEffect(() => {
    setDatasetInput(datasetId || '')
  }, [datasetId])

  const ids = useMemo(() => {
    const manual = parseIds(documentIdsRaw)
    return manual.length ? manual : selectedDocumentIds
  }, [documentIdsRaw, selectedDocumentIds])
  const firstDocumentId = documentId.trim() || ids[0] || ''
  const effectiveDatasetId = datasetInput.trim() || String(datasetId || '').trim()
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
    <Panel padding="md" className="border-border/70 bg-card/95">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-sm font-semibold text-foreground">文档高级操作</div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            使用当前知识库和勾选文档执行统计、解析内容、权限、移动、重复文件、生命周期元数据和批量上传任务。
          </p>
        </div>
        {busy ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground motion-reduce:animate-none" /> : null}
      </div>

      <div className="mt-3 grid gap-2 lg:grid-cols-[minmax(0,1fr)_minmax(240px,0.72fr)]">
        <div className="rounded-xl border border-primary/15 bg-primary/[0.035] p-3">
          <div className="text-xs font-semibold text-foreground">使用当前知识库和勾选文档</div>
          <div className="mt-2 grid gap-2 md:grid-cols-3">
            <ContextItem label="知识库" value={currentDatasetLabel} subValue={effectiveDatasetId || '全局范围'} />
            <ContextItem label="文档范围" value={selectedScopeLabel} subValue={firstDocumentId ? `默认文档 ${firstDocumentId.slice(0, 8)}` : '先在列表勾选文档'} />
            <ContextItem label="批量来源" value={documentIdsRaw.trim() ? '手动覆盖' : '当前勾选'} subValue={documentIdsRaw.trim() ? `${ids.length} 个覆盖 ID` : '无需手填文档 ID'} />
          </div>
        </div>

        <Field label="移动到知识库">
          <Select
            value={targetDatasetValue}
            onValueChange={(value) => setTargetDatasetId(value === NO_TARGET_DATASET ? '' : value)}
          >
            <SelectTrigger className="h-10 rounded-xl border-border/70 bg-background text-xs">
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
          <div className="mt-1 text-[11px] leading-4 text-muted-foreground">
            批量移动时才需要选择；其他操作会自动使用当前知识库。
          </div>
        </Field>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <ActionButton icon={FileJson} busy={busy === 'stats'} disabled={Boolean(busy)} label="文档统计" onClick={() => runAction('stats', '文档统计', () => documentApi.stats({ dataset_id: effectiveDatasetId || undefined }))} />
        <ActionButton icon={FileJson} busy={busy === 'parsed'} disabled={Boolean(busy) || !firstDocumentId} label="查看解析内容" onClick={() => runAction('parsed', '解析内容', () => documentApi.getParsedContent(firstDocumentId, { max_chars: 20_000 }))} />
        <ActionButton icon={ShieldCheck} busy={busy === 'access'} disabled={Boolean(busy) || ids.length === 0} label="批量权限" onClick={() => runAction('access', '批量权限更新', () => documentApi.batchUpdateAccess({ document_ids: ids, ...parseJson(payloadJson) }))} />
        <ActionButton icon={FolderInput} busy={busy === 'move'} disabled={Boolean(busy) || ids.length === 0 || !targetDatasetId.trim()} label="批量移动" onClick={() => runAction('move', '批量移动', () => documentApi.batchMove({ document_ids: ids, target_dataset_id: targetDatasetId.trim() }))} />
        <ActionButton icon={FileJson} busy={busy === 'duplicates'} disabled={Boolean(busy) || !effectiveDatasetId} label="重复文档" onClick={() => runAction('duplicates', '重复文档', () => documentApi.listDuplicates({ dataset_id: effectiveDatasetId, min_count: 2, max_groups: 20, max_docs_per_group: 10 }))} />
        <ActionButton icon={FileJson} busy={busy === 'lifecycle'} disabled={Boolean(busy) || !firstDocumentId} label="生命周期元数据" onClick={() => runAction('lifecycle', '生命周期元数据', () => documentApi.getLifecycleMetadata(firstDocumentId))} />
        <ActionButton icon={FileJson} busy={busy === 'metadata'} disabled={Boolean(busy) || ids.length === 0} label="批量元数据" onClick={() => runAction('metadata', '批量用户元数据', () => documentApi.batchPatchUserMetadata({ document_ids: ids, ...parseJson(payloadJson) }))} />
        <ActionButton icon={FileJson} busy={busy === 'apply-urls'} disabled={Boolean(busy)} label="申请上传 URL" onClick={() => runAction('apply-urls', '申请批量上传 URL', () => {
          const parsed = parseJson(payloadJson)
          const files = getBatchUploadFiles(parsed)
          return documentApi.applyBatchUploadUrls(files)
        })} />
        <ActionButton icon={FileJson} busy={busy === 'batch-status'} disabled={Boolean(busy) || !batchId.trim()} label="批量任务状态" onClick={() => runAction('batch-status', '批量任务状态', () => documentApi.getBatchTaskStatus(batchId.trim()))} />
        <Button variant="outline" className="h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold" disabled={Boolean(busy) || !imageId.trim()} onClick={() => detachPromise(runAction('image', '读取 Image', async () => {
          const blob = await documentApi.fetchImage(imageId.trim())
          downloadBlob(blob, `document-image.${imageId.trim().slice(0, 12)}`)
          return { bytes: blob.size, type: blob.type }
        }))}>
          <ImageIcon className="h-3.5 w-3.5" />
          读取图片
        </Button>
        <Button variant="outline" className="h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold" disabled={Boolean(busy) || !imgId.trim()} onClick={() => detachPromise(runAction('img-id', '读取 Img ID', async () => {
          const blob = await documentApi.fetchImageByImgId(imgId.trim())
          downloadBlob(blob, `document-img.${imgId.trim().slice(0, 12)}`)
          return { bytes: blob.size, type: blob.type }
        }))}>
          <Download className="h-3.5 w-3.5" />
          读取备用图片
        </Button>
      </div>

      <div className="mt-3 rounded-xl border border-border/60 bg-muted/10">
        <button
          type="button"
          className="flex w-full items-center justify-between gap-3 px-3 py-2 text-left text-xs font-semibold text-foreground transition-colors hover:bg-muted/20"
          onClick={() => setAdvancedOpen((open) => !open)}
          aria-expanded={advancedOpen}
        >
          <span>高级覆盖（可选）</span>
          <span className="text-[11px] font-normal text-muted-foreground">
            仅在需要粘贴后端 ID、图片 ID 或自定义 JSON 时打开
          </span>
        </button>
        {advancedOpen ? (
          <div className="grid gap-2 border-t border-border/60 p-3 md:grid-cols-3">
            <Field label="单文档覆盖">
              <Input value={documentId} onChange={(event) => setDocumentId(event.target.value)} className="h-8 font-mono text-xs" placeholder={ids[0] || '可粘贴 document_id'} />
            </Field>
            <Field label="知识库覆盖">
              <Input value={datasetInput} onChange={(event) => setDatasetInput(event.target.value)} className="h-8 font-mono text-xs" placeholder="可粘贴 dataset_id" />
            </Field>
            <Field label="目标知识库覆盖">
              <Input value={targetDatasetId} onChange={(event) => setTargetDatasetId(event.target.value)} className="h-8 font-mono text-xs" placeholder="可粘贴 target_dataset_id" />
            </Field>
            <Field label="批量任务 ID">
              <Input value={batchId} onChange={(event) => setBatchId(event.target.value)} className="h-8 font-mono text-xs" />
            </Field>
            <Field label="图片文件 ID">
              <Input value={imageId} onChange={(event) => setImageId(event.target.value)} className="h-8 font-mono text-xs" placeholder="image_id" />
            </Field>
            <Field label="图片 img_id">
              <Input value={imgId} onChange={(event) => setImgId(event.target.value)} className="h-8 font-mono text-xs" placeholder="img_id" />
            </Field>
            <Field label="批量文档覆盖">
              <Textarea value={documentIdsRaw} onChange={(event) => setDocumentIdsRaw(event.target.value)} className="min-h-8 font-mono text-xs" placeholder="留空使用当前勾选文档" />
            </Field>
            <div className="md:col-span-2">
              <Field label="请求参数 JSON">
                <Textarea value={payloadJson} onChange={(event) => setPayloadJson(event.target.value)} className="min-h-[120px] font-mono text-xs" />
              </Field>
            </div>
          </div>
        ) : null}
      </div>

      {result ? (
        <div className="mt-3 rounded-xl border border-emerald-500/20 bg-emerald-500/[0.04] p-3">
          <div className="flex flex-col gap-2 sm:flex-row sm:items-start sm:justify-between">
            <div className="min-w-0">
              <div className="text-xs font-semibold text-foreground">{result.title}已完成</div>
              <div className="mt-1 text-xs leading-5 text-muted-foreground">{resultSummary}</div>
            </div>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              className="h-7 shrink-0 rounded-lg px-2 text-[11px] font-medium"
              aria-expanded={resultDetailsOpen}
              onClick={() => setResultDetailsOpen((open) => !open)}
            >
              查看原始响应
            </Button>
          </div>
          {resultDetailsOpen ? (
            <pre className={cn('mt-2 max-h-56 overflow-auto rounded-md border border-border/60 bg-background p-2 text-xs', 'whitespace-pre-wrap break-words')}>
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
      <Label className="text-[11px] font-medium text-muted-foreground">{label}</Label>
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
    <div className="rounded-lg border border-border/60 bg-background/80 px-3 py-2">
      <div className="text-[10px] font-medium text-muted-foreground">{label}</div>
      <div className="mt-1 truncate text-xs font-semibold text-foreground" title={value}>
        {value}
      </div>
      <div className="mt-0.5 truncate font-mono text-[10px] text-muted-foreground/72" title={subValue}>
        {subValue}
      </div>
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
