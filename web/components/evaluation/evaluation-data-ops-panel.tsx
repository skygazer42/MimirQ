'use client'

import { useState, type ReactNode } from 'react'
import { Download, Loader2, Sparkles, Trash2, Upload } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Panel } from '@/components/ui/panel'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { DatasetSelectField } from '@/components/ops/dataset-select-field'
import { OperationResultPanel } from '@/components/ops/operation-result-panel'
import { evaluationApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { detachPromise } from '@/lib/utils'

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

function downloadJson(payload: unknown, filename: string) {
  const blob = new Blob([prettyJson(payload)], { type: 'application/json;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function EvaluationDataOpsPanel() {
  const [datasetId, setDatasetId] = useState('')
  const [itemsJson, setItemsJson] = useState('[]')
  const [kgRunId, setKgRunId] = useState('')
  const [overwrite, setOverwrite] = useState(false)
  const [dryRun, setDryRun] = useState(true)
  const [maxItems, setMaxItems] = useState(100)
  const [retentionDays, setRetentionDays] = useState(30)
  const [busy, setBusy] = useState<string | null>(null)
  const [result, setResult] = useState<{ title: string; payload: unknown } | null>(null)

  const dataset = datasetId.trim()

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
    <Panel padding="md" className="border-border/70 bg-card/95">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-sm font-semibold text-foreground">评测数据运维</div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            围绕选中的数据集维护固定测试集、生成困难样例并清理旧运行；导入 JSON 和 run 明细排查默认收起。
          </p>
        </div>
        {busy ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground motion-reduce:animate-none" /> : null}
      </div>

      <div className="mt-3 grid gap-2 md:grid-cols-4">
        <DatasetSelectField value={datasetId} onChange={setDatasetId} />
        <Field label="样例上限">
          <Input value={String(maxItems)} onChange={(event) => setMaxItems(Number.parseInt(event.target.value || '0', 10) || 100)} className="h-8 text-xs" inputMode="numeric" />
        </Field>
        <Field label="保留天数">
          <Input value={String(retentionDays)} onChange={(event) => setRetentionDays(Number.parseInt(event.target.value || '0', 10) || 30)} className="h-8 text-xs" inputMode="numeric" />
        </Field>
        <div className="flex items-end gap-3">
          <Toggle label="覆盖导入" checked={overwrite} onCheckedChange={setOverwrite} />
          <Toggle label="仅预演" checked={dryRun} onCheckedChange={setDryRun} />
        </div>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <Button variant="outline" className="h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold" disabled={Boolean(busy) || !dataset} onClick={() => detachPromise(runAction('export', '导出 Regression Cases', async () => {
          const payload = await evaluationApi.exportRegressionCases({ dataset_id: dataset })
          downloadJson(payload, `regression-cases.${dataset.slice(0, 8)}.json`)
          return payload
        }))}>
          <Download className="h-3.5 w-3.5" />
          导出 cases
        </Button>
        <ActionButton icon={Sparkles} busy={busy === 'hardcases'} disabled={Boolean(busy) || !dataset} label="生成 hardcases" onClick={() => runAction('hardcases', '生成 Synthetic Hardcases', () => evaluationApi.generateSyntheticHardcases({ dataset_id: dataset, max_cases: maxItems, max_created: maxItems, dry_run: dryRun }))} />
        <ConfirmDialog
          title={dryRun ? '执行 Regression Runs 清理预演？' : '清理旧 Regression Runs？'}
          description={dryRun ? '当前是 dry_run，只返回将被清理的范围。' : `将真实清理 retention_days=${retentionDays} 之外的 runs，最多 ${maxItems} 条。此操作不可撤销。`}
          confirmLabel={dryRun ? '执行预演' : '清理'}
          confirmVariant={dryRun ? 'default' : 'destructive'}
          onConfirm={() => runAction('purge', '清理 Regression Runs', () => evaluationApi.purgeRegressionRuns({ retention_days: retentionDays, max_delete: maxItems, dry_run: dryRun, dataset_id: dataset || undefined }))}
        >
          <Button variant="outline" className="h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold" disabled={Boolean(busy)}>
            {busy === 'purge' ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <Trash2 className="h-3.5 w-3.5" />}
            清理旧 runs
          </Button>
        </ConfirmDialog>
        <ActionButton icon={Sparkles} busy={busy === 'kg-run'} disabled={Boolean(busy) || !dataset} label="KG 诊断" onClick={() => runAction('kg-run', 'KG Search Diagnostics', () => evaluationApi.runKgSearchDiagnostics({ dataset_id: dataset, max_cases: maxItems, k: 8, auto_extract_kg: true, persist_run: true, hardcase_mode: dryRun ? 'deterministic' : 'off' }))} />
        <ActionButton icon={Sparkles} busy={busy === 'kg-runs'} disabled={Boolean(busy) || !dataset} label="KG 诊断 Runs" onClick={() => runAction('kg-runs', 'KG Diagnostics Runs', () => evaluationApi.listKgSearchDiagnosticsRuns({ dataset_id: dataset, limit: maxItems }))} />
        <ActionButton icon={Sparkles} busy={busy === 'kg-quality'} disabled={Boolean(busy) || !dataset} label="KG 质量报告" onClick={() => runAction('kg-quality', 'KG Quality Report', () => evaluationApi.getKgQualityReport({ dataset_id: dataset, document_limit: maxItems }))} />
      </div>

      <details className="mt-3 rounded-lg border border-border/60 bg-background/70 p-3">
        <summary className="cursor-pointer text-xs font-semibold text-foreground">高级参数（可选）</summary>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">仅在导入外部 cases 或定位历史 KG 诊断 run 时使用。</p>
        <div className="mt-3 grid gap-2 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
          <Field label="KG 诊断运行">
            <Input value={kgRunId} onChange={(event) => setKgRunId(event.target.value)} className="h-8 font-mono text-xs" />
          </Field>
          <ActionButton icon={Sparkles} busy={busy === 'kg-run-detail'} disabled={Boolean(busy) || !kgRunId.trim()} label="KG Run 详情" onClick={() => runAction('kg-run-detail', 'KG Diagnostics Run 详情', () => evaluationApi.getKgSearchDiagnosticsRun(kgRunId.trim()))} />
        </div>
        <Field label="导入数据（JSON）">
          <Textarea value={itemsJson} onChange={(event) => setItemsJson(event.target.value)} className="mt-3 min-h-[120px] font-mono text-xs" />
        </Field>
        <div className="mt-3">
          <ActionButton icon={Upload} busy={busy === 'import'} disabled={Boolean(busy) || !dataset} label="导入 cases" onClick={() => runAction('import', '导入 Regression Cases', () => evaluationApi.importRegressionCases({ dataset_id: dataset, overwrite, max_items: maxItems, items: parseJson(itemsJson) as any[] }))} />
        </div>
      </details>

      <OperationResultPanel className="mt-3" title="评测数据操作结果" result={result} emptyMessage="选择上方操作后，这里展示执行摘要；原始接口响应默认收起。" />
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

function Toggle({ label, checked, onCheckedChange }: Readonly<{ label: string; checked: boolean; onCheckedChange: (checked: boolean) => void }>) {
  return (
    <label className="flex items-center gap-1.5 text-[11px] font-medium text-muted-foreground">
      <Switch checked={checked} onCheckedChange={onCheckedChange} />
      {label}
    </label>
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
