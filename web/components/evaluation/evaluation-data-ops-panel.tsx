'use client'

import { useState, type ReactNode } from 'react'
import {
  ChevronDown,
  ClipboardList,
  Download,
  FileJson,
  FileText,
  ListChecks,
  Loader2,
  PlayCircle,
  Search,
  Sparkles,
  Trash2,
  Upload,
} from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Textarea } from '@/components/ui/textarea'
import { DatasetSelectField } from '@/components/ops/dataset-select-field'
import { evaluationApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { cn, detachPromise } from '@/lib/utils'

function prettyJson(value: unknown) {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function parseJson(raw: string) {
  const value = raw.trim()
  return value ? JSON.parse(value) : []
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

function describePayload(payload: unknown): string {
  if (Array.isArray(payload)) return `${payload.length} 条记录`
  if (!payload || typeof payload !== 'object') return '1 条响应'

  const record = payload as Record<string, unknown>
  const keys = ['total', 'count', 'created', 'deleted', 'updated', 'items', 'runs', 'cases']
  const parts = keys.flatMap((key) => {
    const value = record[key]
    if (Array.isArray(value)) return `${key}: ${value.length}`
    if (typeof value === 'number' || typeof value === 'string') return `${key}: ${value}`
    return []
  })

  return parts.length ? parts.slice(0, 3).join(' / ') : `${Object.keys(record).length} 个字段`
}

export function EvaluationDataOpsPanel() {
  const [datasetId, setDatasetId] = useState('')
  const [itemsJson, setItemsJson] = useState('')
  const [kgRunId, setKgRunId] = useState('')
  const [overwrite, setOverwrite] = useState(false)
  const [dryRun, setDryRun] = useState(true)
  const [maxItems, setMaxItems] = useState(100)
  const [retentionDays, setRetentionDays] = useState(30)
  const [busy, setBusy] = useState<string | null>(null)
  const [showRaw, setShowRaw] = useState(false)
  const [result, setResult] = useState<{ title: string; payload: unknown } | null>(null)

  const dataset = datasetId.trim()

  async function runAction(key: string, title: string, action: () => Promise<unknown>) {
    setBusy(key)
    setShowRaw(false)
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

  const runKgDiagnostics = () =>
    runAction('kg-run', 'KG 诊断', () =>
      evaluationApi.runKgSearchDiagnostics({
        dataset_id: dataset,
        max_cases: maxItems,
        k: 8,
        auto_extract_kg: true,
        persist_run: true,
        hardcase_mode: dryRun ? 'deterministic' : 'off',
      })
    )

  return (
    <div className="space-y-3">
      <section className="rounded-xl border border-slate-200/80 bg-card/95 p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
        <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
          <div className="flex min-w-0 gap-3">
            <span className="mt-0.5 inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-blue-50 text-blue-600 ring-1 ring-blue-100">
              <ClipboardList className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <h3 className="text-[15px] font-semibold tracking-tight text-slate-950">评测数据运维</h3>
              <p className="mt-1 text-[12px] leading-5 text-slate-500">
                围绕选中的数据集维护固定测试集、生成困难样例并清理旧运行；导入 JSON 和 run 明细排查默认收起。
              </p>
            </div>
          </div>
          {busy ? <Loader2 className="h-4 w-4 shrink-0 animate-spin text-slate-400 motion-reduce:animate-none" /> : null}
        </div>

        <div className="mt-4 grid gap-3 lg:grid-cols-[minmax(240px,1fr)_minmax(160px,240px)_minmax(160px,240px)_auto_auto] lg:items-end">
          <DatasetSelectField
            value={datasetId}
            onChange={setDatasetId}
            className="min-w-0 [&_button]:h-9 [&_button]:rounded-lg [&_button]:border-slate-200 [&_button]:bg-white [&_button]:text-[13px]"
          />
          <Field label="样例上限">
            <Input
              value={String(maxItems)}
              onChange={(event) => setMaxItems(Number.parseInt(event.target.value || '0', 10) || 100)}
              className="h-9 rounded-lg border-slate-200 bg-white text-[13px]"
              inputMode="numeric"
            />
          </Field>
          <Field label="保留天数">
            <Input
              value={String(retentionDays)}
              onChange={(event) => setRetentionDays(Number.parseInt(event.target.value || '0', 10) || 30)}
              className="h-9 rounded-lg border-slate-200 bg-white text-[13px]"
              inputMode="numeric"
            />
          </Field>
          <Toggle label="覆盖导入" checked={overwrite} onCheckedChange={setOverwrite} />
          <Toggle label="仅预演" checked={dryRun} onCheckedChange={setDryRun} />
        </div>

        <div className="mt-4 flex flex-col gap-3 border-t border-slate-200/70 pt-3 lg:flex-row lg:items-center lg:justify-between">
          <div className="flex flex-wrap gap-2">
            <Button
              variant="outline"
              className="h-9 gap-1.5 rounded-lg border-slate-200 bg-white px-3 text-[12px] font-medium text-slate-700 shadow-sm hover:bg-slate-50"
              disabled={Boolean(busy) || !dataset}
              onClick={() =>
                detachPromise(
                  runAction('export', '导出 cases', async () => {
                    const payload = await evaluationApi.exportRegressionCases({ dataset_id: dataset })
                    downloadJson(payload, `regression-cases.${dataset.slice(0, 8)}.json`)
                    return payload
                  })
                )
              }
            >
              <Download className="h-3.5 w-3.5" />
              导出 cases
            </Button>
            <ActionButton
              icon={Sparkles}
              busy={busy === 'hardcases'}
              disabled={Boolean(busy) || !dataset}
              label="生成 hardcases"
              onClick={() =>
                runAction('hardcases', '生成 hardcases', () =>
                  evaluationApi.generateSyntheticHardcases({
                    dataset_id: dataset,
                    max_cases: maxItems,
                    max_created: maxItems,
                    dry_run: dryRun,
                  })
                )
              }
            />
            <ConfirmDialog
              title={dryRun ? '执行 runs 清理预演？' : '清理旧 runs？'}
              description={dryRun ? '当前是仅预演，只返回将被清理的范围。' : `将真实清理保留天数 ${retentionDays} 之外的 runs，最多 ${maxItems} 条。此操作不可撤销。`}
              confirmLabel={dryRun ? '执行预演' : '清理'}
              confirmVariant={dryRun ? 'default' : 'destructive'}
              onConfirm={() =>
                runAction('purge', '清理旧 runs', () =>
                  evaluationApi.purgeRegressionRuns({
                    retention_days: retentionDays,
                    max_delete: maxItems,
                    dry_run: dryRun,
                    dataset_id: dataset || undefined,
                  })
                )
              }
            >
              <Button variant="outline" className="h-9 gap-1.5 rounded-lg border-slate-200 bg-white px-3 text-[12px] font-medium text-blue-700 shadow-sm hover:bg-blue-50" disabled={Boolean(busy)}>
                {busy === 'purge' ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <Trash2 className="h-3.5 w-3.5" />}
                清理旧 runs
              </Button>
            </ConfirmDialog>
            <ActionButton icon={Search} busy={busy === 'kg-run'} disabled={Boolean(busy) || !dataset} label="KG 诊断" onClick={runKgDiagnostics} />
            <ActionButton
              icon={ListChecks}
              busy={busy === 'kg-runs'}
              disabled={Boolean(busy) || !dataset}
              label="KG 诊断 Runs"
              onClick={() => runAction('kg-runs', 'KG 诊断 Runs', () => evaluationApi.listKgSearchDiagnosticsRuns({ dataset_id: dataset, limit: maxItems }))}
            />
            <ActionButton
              icon={FileText}
              busy={busy === 'kg-quality'}
              disabled={Boolean(busy) || !dataset}
              label="KG 质量报告"
              onClick={() => runAction('kg-quality', 'KG 质量报告', () => evaluationApi.getKgQualityReport({ dataset_id: dataset, document_limit: maxItems }))}
            />
          </div>
          <Button
            className="h-9 min-w-[110px] gap-1.5 rounded-lg bg-blue-600 px-4 text-[12px] font-semibold text-white shadow-[0_8px_18px_rgba(37,99,235,0.24)] hover:bg-blue-700"
            disabled={Boolean(busy) || !dataset}
            onClick={() => detachPromise(runKgDiagnostics())}
          >
            {busy === 'kg-run' ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <PlayCircle className="h-3.5 w-3.5" />}
            开始执行
          </Button>
        </div>
      </section>

      <details open className="group rounded-xl border border-slate-200/80 bg-card/95 p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
        <summary className="flex cursor-pointer list-none items-start gap-2.5 [&::-webkit-details-marker]:hidden">
          <ChevronDown className="mt-0.5 h-4 w-4 shrink-0 -rotate-90 text-blue-600 transition-transform group-open:rotate-0" />
          <div>
            <h3 className="text-[14px] font-semibold text-slate-950">高级参数（可选）</h3>
            <p className="mt-1 text-[12px] leading-5 text-slate-500">仅在导入外部 cases 或定位历史 KG 诊断 run 时使用。</p>
          </div>
        </summary>
        <div className="mt-3 space-y-3 border-t border-slate-200/70 pt-3">
          <div className="grid gap-3 md:grid-cols-[minmax(0,1fr)_auto] md:items-end">
            <Field label="KG 诊断运行">
              <Input
                value={kgRunId}
                onChange={(event) => setKgRunId(event.target.value)}
                placeholder="请输入 KG 诊断运行 ID 或名称"
                className="h-9 rounded-lg border-slate-200 bg-white font-mono text-[12px]"
              />
            </Field>
            <ActionButton
              icon={Search}
              busy={busy === 'kg-run-detail'}
              disabled={Boolean(busy) || !kgRunId.trim()}
              label="KG Run 详情"
              onClick={() => runAction('kg-run-detail', 'KG Run 详情', () => evaluationApi.getKgSearchDiagnosticsRun(kgRunId.trim()))}
            />
          </div>
          <Field label="导入数据（JSON）">
            <div className="overflow-hidden rounded-lg border border-slate-200 bg-white shadow-inner">
              <div className="flex">
                <div className="w-12 shrink-0 border-r border-slate-200 bg-slate-50 px-3 py-2 text-right font-mono text-[12px] leading-5 text-slate-400">1</div>
                <Textarea
                  value={itemsJson}
                  onChange={(event) => setItemsJson(event.target.value)}
                  placeholder="请输入或粘贴 JSON 数据..."
                  className="min-h-[62px] resize-y rounded-none border-0 bg-transparent px-4 py-2 font-mono text-[12px] leading-5 shadow-none focus-visible:border-transparent focus-visible:ring-0"
                />
              </div>
            </div>
          </Field>
          <ActionButton
            icon={Upload}
            busy={busy === 'import'}
            disabled={Boolean(busy) || !dataset}
            label="导入 cases"
            onClick={() =>
              runAction('import', '导入 cases', () =>
                evaluationApi.importRegressionCases({
                  dataset_id: dataset,
                  overwrite,
                  max_items: maxItems,
                  items: parseJson(itemsJson) as any[],
                })
              )
            }
          />
        </div>
      </details>

      <ResultCard
        result={result}
        showRaw={showRaw}
        onToggleRaw={() => setShowRaw((value) => !value)}
        onClear={() => {
          setResult(null)
          setShowRaw(false)
        }}
      />
    </div>
  )
}

function Field({ label, children }: Readonly<{ label: string; children: ReactNode }>) {
  return (
    <div className="space-y-1">
      <Label className="text-[11px] font-medium text-slate-500">{label}</Label>
      {children}
    </div>
  )
}

function Toggle({ label, checked, onCheckedChange }: Readonly<{ label: string; checked: boolean; onCheckedChange: (checked: boolean) => void }>) {
  return (
    <label className="flex h-9 items-center justify-end gap-2 text-[12px] font-medium text-slate-600">
      <span>{label}</span>
      <Switch checked={checked} onCheckedChange={onCheckedChange} className="scale-90 data-[state=unchecked]:bg-slate-300" />
    </label>
  )
}

function ActionButton({
  busy,
  className,
  disabled,
  icon: Icon,
  label,
  onClick,
}: Readonly<{
  busy: boolean
  className?: string
  disabled: boolean
  icon: LucideIcon
  label: string
  onClick: () => Promise<void>
}>) {
  return (
    <Button
      variant="outline"
      className={cn('h-9 gap-1.5 rounded-lg border-slate-200 bg-white px-3 text-[12px] font-medium text-slate-700 shadow-sm hover:bg-slate-50', className)}
      disabled={disabled}
      onClick={() => detachPromise(onClick())}
    >
      {busy ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <Icon className="h-3.5 w-3.5" />}
      {label}
    </Button>
  )
}

function ResultCard({
  onClear,
  onToggleRaw,
  result,
  showRaw,
}: Readonly<{
  onClear: () => void
  onToggleRaw: () => void
  result: { title: string; payload: unknown } | null
  showRaw: boolean
}>) {
  return (
    <section className="rounded-xl border border-slate-200/80 bg-card/95 p-4 shadow-[0_1px_2px_rgba(15,23,42,0.04)]">
      <div className="flex items-center gap-2">
        <span className="inline-flex h-5 w-5 items-center justify-center rounded-md bg-blue-50 text-blue-600 ring-1 ring-blue-100">
          <FileJson className="h-3.5 w-3.5" />
        </span>
        <h3 className="text-[14px] font-semibold text-slate-950">评测数据操作结果</h3>
      </div>

      <div className="mt-3 rounded-lg border border-slate-200/80 bg-slate-50/70 p-3">
        {result ? (
          <div className="flex items-center gap-3">
            <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white text-blue-600 shadow-sm ring-1 ring-slate-200">
              <FileJson className="h-4 w-4" />
            </span>
            <div className="min-w-0">
              <div className="text-[13px] font-semibold text-slate-900">{result.title}</div>
              <p className="mt-1 text-[12px] text-slate-500">接口已返回真实数据，摘要：{describePayload(result.payload)}。</p>
            </div>
          </div>
        ) : (
          <div className="flex items-center gap-3">
            <span className="inline-flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-white text-slate-400 shadow-sm ring-1 ring-slate-200">
              <FileJson className="h-4 w-4" />
            </span>
            <p className="text-[12px] leading-5 text-slate-500">选择上方操作后，这里展示执行摘要；原始接口响应默认收起。</p>
          </div>
        )}
      </div>

      <div className="mt-3 flex justify-end gap-2">
        <Button variant="outline" className="h-8 gap-1.5 rounded-lg border-slate-200 bg-white px-3 text-[12px] font-medium text-slate-700 shadow-sm hover:bg-slate-50" disabled={!result} onClick={onToggleRaw}>
          <Download className="h-3.5 w-3.5" />
          {showRaw ? '收起原始响应' : '展开原始响应'}
        </Button>
        <Button variant="outline" className="h-8 gap-1.5 rounded-lg border-slate-200 bg-white px-3 text-[12px] font-medium text-slate-700 shadow-sm hover:bg-slate-50" disabled={!result} onClick={onClear}>
          <Trash2 className="h-3.5 w-3.5" />
          清空
        </Button>
      </div>

      {result && showRaw ? (
        <pre className="mt-3 max-h-72 overflow-auto rounded-lg border border-slate-200 bg-slate-950 p-3 text-[11px] leading-5 text-slate-100">{prettyJson(result.payload)}</pre>
      ) : null}
    </section>
  )
}
