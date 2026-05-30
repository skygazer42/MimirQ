'use client'

import { useState, type ReactNode } from 'react'
import { Download, Loader2, PackageCheck, ShieldCheck } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Panel } from '@/components/ui/panel'
import { Textarea } from '@/components/ui/textarea'
import { DatasetSelectField } from '@/components/ops/dataset-select-field'
import { OperationResultPanel } from '@/components/ops/operation-result-panel'
import { evidenceApi } from '@/lib/api'
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

export function EvidenceOpsPanel() {
  const [datasetId, setDatasetId] = useState('')
  const [suiteId, setSuiteId] = useState('')
  const [itemId, setItemId] = useState('')
  const [capsuleId, setCapsuleId] = useState('')
  const [payloadJson, setPayloadJson] = useState('{\n  "capsule": {\n    "schema": "mimirq.evidence_capsule.v1",\n    "claims": []\n  }\n}')
  const [busy, setBusy] = useState<string | null>(null)
  const [result, setResult] = useState<{ title: string; payload: unknown } | null>(null)

  const dataset = datasetId.trim()
  const suite = suiteId.trim()
  const item = itemId.trim()
  const capsule = capsuleId.trim()

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
    <Panel padding="md" className="mt-4 border-border/70 bg-card/95">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-sm font-semibold text-foreground">Evidence 管理操作</div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            围绕选中数据集完成证据漂移审计与训练集导出；suite/item/capsule 维护放在高级参数中。
          </p>
        </div>
        {busy ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground motion-reduce:animate-none" /> : null}
      </div>

      <div className="mt-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_auto_auto] md:items-end">
        <DatasetSelectField value={datasetId} onChange={setDatasetId} />
        <ActionButton icon={ShieldCheck} busy={busy === 'dataset-drift'} disabled={Boolean(busy) || !dataset} label="数据集 Drift" onClick={() => runAction('dataset-drift', '数据集 Drift Audit', () => evidenceApi.getDatasetDriftAudit(dataset, { include_details: true, details_limit: 20 }))} />
        <Button variant="outline" className="h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold" disabled={Boolean(busy) || !dataset} onClick={() => detachPromise(runAction('training-export', '导出训练集', async () => {
          const blob = await evidenceApi.exportTrainingDataset({ dataset_id: dataset, format: 'jsonl', include_feedback: true, include_evidence: true })
          downloadBlob(blob, `evidence-training.${dataset.slice(0, 8)}.jsonl`)
          return { bytes: blob.size, type: blob.type }
        }))}>
          <Download className="h-3.5 w-3.5" />
          导出训练集
        </Button>
      </div>

      <details className="mt-3 rounded-lg border border-border/60 bg-background/70 p-3">
        <summary className="cursor-pointer text-xs font-semibold text-foreground">高级参数（可选）</summary>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">仅在需要修复引用、Patch suite/item 或处理 Evidence Capsule 时填写。</p>
        <div className="mt-3 grid gap-2 md:grid-cols-3">
          <Field label="Suite 标识">
            <Input value={suiteId} onChange={(event) => setSuiteId(event.target.value)} className="h-8 font-mono text-xs" />
          </Field>
          <Field label="Item 标识">
            <Input value={itemId} onChange={(event) => setItemId(event.target.value)} className="h-8 font-mono text-xs" />
          </Field>
          <Field label="Capsule 标识">
            <Input value={capsuleId} onChange={(event) => setCapsuleId(event.target.value)} className="h-8 font-mono text-xs" />
          </Field>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
        <ActionButton icon={ShieldCheck} busy={busy === 'repair'} disabled={Boolean(busy) || !suite} label="修复引用" onClick={() => runAction('repair', '修复 Suite Reference Sources', () => evidenceApi.repairSuiteReferenceSources(suite, parseJson(payloadJson)))} />
        <ActionButton icon={ShieldCheck} busy={busy === 'patch-suite'} disabled={Boolean(busy) || !suite} label="Patch Suite" onClick={() => runAction('patch-suite', 'Patch Evidence Suite', () => evidenceApi.patchSuite(suite, parseJson(payloadJson)))} />
        <ActionButton icon={ShieldCheck} busy={busy === 'patch-item'} disabled={Boolean(busy) || !item} label="Patch Item" onClick={() => runAction('patch-item', 'Patch Evidence Item', () => evidenceApi.patchItem(item, parseJson(payloadJson)))} />
        <ActionButton icon={PackageCheck} busy={busy === 'persist'} disabled={Boolean(busy)} label="保存 Capsule" onClick={() => runAction('persist', '保存 Evidence Capsule', () => evidenceApi.persistCapsule(parseJson(payloadJson)))} />
        <ActionButton icon={PackageCheck} busy={busy === 'get-capsule'} disabled={Boolean(busy) || !capsule} label="读取 Capsule" onClick={() => runAction('get-capsule', '读取 Evidence Capsule', () => evidenceApi.getCapsule(capsule))} />
        <ActionButton icon={PackageCheck} busy={busy === 'verify'} disabled={Boolean(busy)} label="校验 Capsule" onClick={() => runAction('verify', '校验 Evidence Capsule', () => evidenceApi.verifyCapsule(parseJson(payloadJson)))} />
        </div>
        <Field label="高级载荷（JSON）">
          <Textarea value={payloadJson} onChange={(event) => setPayloadJson(event.target.value)} className="mt-3 min-h-[140px] font-mono text-xs" />
        </Field>
      </details>

      <OperationResultPanel className="mt-3" title="Evidence 操作结果" result={result} emptyMessage="选择上方操作后，这里展示执行摘要；原始响应默认收起。" />
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
