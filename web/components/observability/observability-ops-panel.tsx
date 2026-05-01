'use client'

import { useState, type ReactNode } from 'react'
import { Activity, Download, Loader2, RefreshCw, ShieldCheck } from 'lucide-react'
import type { LucideIcon } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Panel } from '@/components/ui/panel'
import { DatasetSelectField } from '@/components/ops/dataset-select-field'
import { OperationResultPanel } from '@/components/ops/operation-result-panel'
import { observabilityApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { detachPromise } from '@/lib/utils'

type ResultState = {
  title: string
  payload: unknown
}

function downloadArrayBuffer(data: ArrayBuffer, filename: string) {
  const blob = new Blob([data], { type: 'application/jsonl;charset=utf-8' })
  const url = URL.createObjectURL(blob)
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = filename
  anchor.click()
  globalThis.window.setTimeout(() => URL.revokeObjectURL(url), 1000)
}

export function ObservabilityOpsPanel() {
  const [datasetId, setDatasetId] = useState('')
  const [documentId, setDocumentId] = useState('')
  const [driftItemId, setDriftItemId] = useState('')
  const [resolutionNote, setResolutionNote] = useState('')
  const [windowMinutes, setWindowMinutes] = useState(60)
  const [iterations, setIterations] = useState(3)
  const [busy, setBusy] = useState<string | null>(null)
  const [result, setResult] = useState<ResultState | null>(null)

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

  const dataset = datasetId.trim()
  const doc = documentId.trim()
  const actionButtonClass = 'h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold'

  return (
    <Panel padding="md" className="mt-4 border-border/70 bg-card/95">
      <div className="flex flex-col gap-3 lg:flex-row lg:items-start lg:justify-between">
        <div>
          <div className="text-sm font-semibold text-foreground">观测运维操作</div>
          <p className="mt-1 text-xs leading-5 text-muted-foreground">
            聚合在线质量、成本、依赖、队列和 SLO；文档级漂移、Trace 上报和 drift 解决放到高级参数。
          </p>
        </div>
        {busy ? <Loader2 className="h-4 w-4 animate-spin text-muted-foreground motion-reduce:animate-none" /> : null}
      </div>

      <div className="mt-3 grid gap-2 md:grid-cols-4">
        <Field label="时间窗口（分钟）">
          <Input value={String(windowMinutes)} onChange={(event) => setWindowMinutes(Number.parseInt(event.target.value || '0', 10) || 60)} className="h-8 text-xs" inputMode="numeric" />
        </Field>
        <DatasetSelectField value={datasetId} onChange={setDatasetId} label="数据集范围" allowAll />
        <Field label="性能迭代次数">
          <Input value={String(iterations)} onChange={(event) => setIterations(Number.parseInt(event.target.value || '0', 10) || 3)} className="h-8 text-xs" inputMode="numeric" />
        </Field>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <ActionButton icon={Activity} label="在线质量" busy={busy === 'online'} disabled={Boolean(busy)} onClick={() => runAction('online', '在线质量摘要', () => observabilityApi.getOnlineQualitySummary({ window_minutes: windowMinutes }))} />
        <ActionButton icon={Activity} label="成本归因" busy={busy === 'cost'} disabled={Boolean(busy)} onClick={() => runAction('cost', 'RAG 成本归因', () => observabilityApi.getRagCostAttribution({ window_minutes: windowMinutes }))} />
        <Button variant="outline" className={actionButtonClass} disabled={Boolean(busy)} onClick={() => detachPromise(runAction('tail', '下载 metrics tail', async () => {
          const data = await observabilityApi.getRagMetricsTail({ window_minutes: windowMinutes })
          downloadArrayBuffer(data, `rag-metrics-tail.${Date.now()}.jsonl`)
          return { bytes: data.byteLength }
        }))}>
          {busy === 'tail' ? <Loader2 className="h-3.5 w-3.5 animate-spin motion-reduce:animate-none" /> : <Download className="h-3.5 w-3.5" />}
          Metrics Tail
        </Button>
        <ActionButton icon={ShieldCheck} label="依赖健康" busy={busy === 'deps'} disabled={Boolean(busy)} onClick={() => runAction('deps', '依赖诊断快照', () => observabilityApi.getDepsDiagnosticsSnapshot())} />
        <ActionButton icon={ShieldCheck} label="定时任务" busy={busy === 'jobs'} disabled={Boolean(busy)} onClick={() => runAction('jobs', '定时任务新鲜度', () => observabilityApi.getPeriodicJobFreshness())} />
        <ActionButton icon={ShieldCheck} label="任务队列" busy={busy === 'queue'} disabled={Boolean(busy)} onClick={() => runAction('queue', '任务队列快照', () => observabilityApi.getTaskQueueSnapshot({ force_refresh: true }))} />
        <ActionButton icon={ShieldCheck} label="SLO" busy={busy === 'slo'} disabled={Boolean(busy)} onClick={() => runAction('slo', 'SLO 快照', () => observabilityApi.getSloSnapshot())} />
        <ActionButton icon={RefreshCw} label="失效缓存" busy={busy === 'cache'} disabled={Boolean(busy) || !dataset} onClick={() => runAction('cache', '数据集缓存失效', () => observabilityApi.invalidateDatasetCache(dataset))} />
        <ActionButton icon={Activity} label="Index Drift" busy={busy === 'index'} disabled={Boolean(busy)} onClick={() => runAction('index', 'Index drift 列表', () => observabilityApi.listIndexDrift({ dataset_id: dataset || undefined, limit: 20 }))} />
      </div>

      <details className="mt-3 rounded-lg border border-border/60 bg-background/70 p-3">
        <summary className="cursor-pointer text-xs font-semibold text-foreground">高级参数（可选）</summary>
        <p className="mt-1 text-xs leading-5 text-muted-foreground">仅在排查单文档 embedding drift、性能探针、手动 trace 或解决 index drift 时使用。</p>
        <div className="mt-3 grid gap-2 md:grid-cols-3">
          <Field label="文档标识">
            <Input value={documentId} onChange={(event) => setDocumentId(event.target.value)} className="h-8 font-mono text-xs" placeholder="Embedding drift 可选" />
          </Field>
          <Field label="Drift 项">
            <Input value={driftItemId} onChange={(event) => setDriftItemId(event.target.value)} className="h-8 font-mono text-xs" />
          </Field>
          <Field label="处理备注">
            <Input value={resolutionNote} onChange={(event) => setResolutionNote(event.target.value)} className="h-8 text-xs" />
          </Field>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <ActionButton icon={Activity} label="Embedding Drift" busy={busy === 'embedding'} disabled={Boolean(busy)} onClick={() => runAction('embedding', 'Embedding drift 快照', () => observabilityApi.getEmbeddingDriftSnapshot({ dataset_id: dataset || undefined, document_id: doc || undefined }))} />
          <ActionButton icon={Activity} label="Perf Suite" busy={busy === 'perf'} disabled={Boolean(busy)} onClick={() => runAction('perf', '性能套件', () => observabilityApi.runPerfSuite({ iterations, timeout_sec: 2 }))} />
          <ActionButton icon={Activity} label="Trace 上报" busy={busy === 'frontend-trace'} disabled={Boolean(busy)} onClick={() => runAction('frontend-trace', '前端 Trace 上报', async () => {
            await observabilityApi.reportFrontendTrace({
              event: 'manual_observability_probe',
              duration_ms: 1,
              component: 'ObservabilityOpsPanel',
              page: '/observability',
              input_node_count: 0,
              input_link_count: 0,
              output_node_count: 0,
              output_link_count: 0,
              active_filter_count: 0,
            })
            return { reported: true, event: 'manual_observability_probe' }
          })} />
          <Button variant="outline" className={actionButtonClass} disabled={Boolean(busy) || !driftItemId.trim()} onClick={() => detachPromise(runAction('resolve-index', '解决 Index drift', () => observabilityApi.resolveIndexDrift(driftItemId.trim(), { resolution_note: resolutionNote.trim() })))}>
            <ShieldCheck className="h-3.5 w-3.5" />
            标记已解决
          </Button>
        </div>
      </details>

      <OperationResultPanel className="mt-3" title="观测运维结果" result={result} emptyMessage="选择上方操作后，这里展示执行摘要；原始响应默认收起。" />
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
