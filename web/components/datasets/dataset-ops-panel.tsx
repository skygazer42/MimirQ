'use client'

import { useState, type ReactNode } from 'react'
import { Download, FolderTree, Loader2, TableProperties } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Panel } from '@/components/ui/panel'
import { Textarea } from '@/components/ui/textarea'
import { OperationResultPanel } from '@/components/ops/operation-result-panel'
import { datasetApi, datasetCategoryApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { detachPromise } from '@/lib/utils'

function parseJson(raw: string) {
  const value = raw.trim()
  return value ? JSON.parse(value) : {}
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function DatasetOpsPanel({ datasetId, datasetName }: Readonly<{ datasetId: string | null; datasetName?: string | null }>) {
  const [cloneName, setCloneName] = useState(`${datasetName || 'dataset'} copy`)
  const [scanRunId, setScanRunId] = useState('')
  const [tableId, setTableId] = useState('')
  const [categoryId, setCategoryId] = useState('')
  const [payloadJson, setPayloadJson] = useState('{\n  "name": "分类名称"\n}')
  const [busy, setBusy] = useState<string | null>(null)
  const [result, setResult] = useState<{ title: string; payload: unknown } | null>(null)

  const dataset = String(datasetId || '').trim()
  const scan = scanRunId.trim()
  const table = tableId.trim()
  const category = categoryId.trim()

  async function runAction(key: string, title: string, action: () => Promise<unknown>) {
    setBusy(key)
    try {
      const payload = await action()
      setResult({ title, payload })
      toast.success(`${title}完成`)
    } catch (error) {
      toast.error(formatApiError(error, `${title}失败`))
    } finally {
      setBusy(null)
    }
  }

  return (
    <Panel className="space-y-3 p-5">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-sm font-semibold text-foreground">数据集运维与导出</div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            围绕当前数据集完成克隆、脱敏导出和高级维护；需要排查历史批次或分类结构时再打开高级参数。
          </p>
        </div>
        {busy ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground motion-reduce:animate-none" /> : null}
      </div>

      <div className="grid gap-2 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
        <Field label="克隆名称">
          <Input value={cloneName} onChange={(event) => setCloneName(event.target.value)} className="h-8 text-xs" />
        </Field>
        <ActionButton icon={FolderTree} busy={busy === 'clone'} disabled={Boolean(busy) || !dataset || !cloneName.trim()} label="克隆数据集" onClick={() => runAction('clone', '克隆数据集', () => datasetApi.clone(dataset, { name: cloneName.trim() } as any))} />
      </div>

      <div className="flex flex-wrap gap-2">
        <Button variant="outline" className="h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold" disabled={Boolean(busy) || !dataset} onClick={() => detachPromise(runAction('docs-export', '导出文档 NDJSON', async () => {
          const blob = await datasetApi.exportDocumentsNdjson(dataset, { limit: 10_000, include_sensitive: false, gzip: true })
          downloadBlob(blob, `${dataset.slice(0, 8)}.documents.ndjson.gz`)
          return { bytes: blob.size, type: blob.type }
        }))}>
          <Download className="h-3.5 w-3.5" />
          文档 NDJSON
        </Button>
        <Button variant="outline" className="h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold" disabled={Boolean(busy) || !dataset} onClick={() => detachPromise(runAction('bundle-export', '导出数据集 Bundle', async () => {
          const blob = await datasetApi.exportBundleZip(dataset, { limit: 10_000, include_sensitive: false })
          downloadBlob(blob, `${dataset.slice(0, 8)}.dataset-bundle.zip`)
          return { bytes: blob.size, type: blob.type }
        }))}>
          <Download className="h-3.5 w-3.5" />
          Bundle ZIP
        </Button>
      </div>

      <details className="rounded-lg border border-border/60 bg-background/70 p-3">
        <summary className="cursor-pointer text-xs font-semibold text-foreground">高级参数（可选）</summary>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">仅在需要按历史预检批次取文件、预览结构化表或维护分类树时填写。</p>
        <div className="mt-3 grid gap-2 md:grid-cols-3">
          <Field label="预检批次">
            <Input value={scanRunId} onChange={(event) => setScanRunId(event.target.value)} className="h-8 font-mono text-xs" />
          </Field>
          <Field label="表标识">
            <Input value={tableId} onChange={(event) => setTableId(event.target.value)} className="h-8 font-mono text-xs" />
          </Field>
          <Field label="分类标识">
            <Input value={categoryId} onChange={(event) => setCategoryId(event.target.value)} className="h-8 font-mono text-xs" />
          </Field>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <ActionButton icon={FolderTree} busy={busy === 'precheck-files'} disabled={Boolean(busy) || !dataset || !scan} label="预检文件" onClick={() => runAction('precheck-files', '预检文件列表', () => datasetApi.listPrecheckFiles(dataset, scan, { limit: 50 }))} />
          <ActionButton icon={TableProperties} busy={busy === 'table-preview'} disabled={Boolean(busy) || !dataset || !table} label="表预览" onClick={() => runAction('table-preview', '表预览', () => datasetApi.previewTable(dataset, table, { limit: 20 }))} />
          <ActionButton icon={FolderTree} busy={busy === 'category-update'} disabled={Boolean(busy) || !category} label="更新分类" onClick={() => runAction('category-update', '更新数据集分类', () => datasetCategoryApi.update(category, parseJson(payloadJson)))} />
          <ActionButton icon={FolderTree} busy={busy === 'category-move'} disabled={Boolean(busy) || !category} label="移动分类" onClick={() => runAction('category-move', '移动数据集分类', () => datasetCategoryApi.move(category, parseJson(payloadJson)))} />
        </div>
        <Field label="分类更新内容（JSON）">
          <Textarea value={payloadJson} onChange={(event) => setPayloadJson(event.target.value)} className="mt-2 min-h-[104px] font-mono text-xs" />
        </Field>
      </details>

      <OperationResultPanel title="数据集操作结果" result={result} emptyMessage="选择上方操作后，这里展示处理状态；原始响应默认收起，便于排查时展开。" />
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
