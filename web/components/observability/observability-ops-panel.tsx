'use client'
import { useLayoutEffect, useRef, useState, type ReactNode } from 'react'
import { Activity, Download, RefreshCw, ShieldCheck } from '@/components/icons'
import type { PlatformIcon } from '@/components/icons'
import { toast } from 'sonner'
import { Input } from '@/components/ui/input'
import { LoadingButton } from '@/components/ui/loading-button'
import { WorkspaceNotice } from '@/components/ui/operational-workspace'
import { DatasetSelectField } from '@/components/ops/dataset-select-field'
import { OperationResultPanel } from '@/components/ops/operation-result-panel'
import { observabilityApi } from '@/lib/api/observability'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionKey } from '@/lib/auth-storage'
import { downloadBlob } from '@/lib/download'
import { boundedNumberDraft } from '@/lib/number-draft-schema'
import { detachPromise } from '@/lib/utils'

type ResultState = {
  title: string
  payload: unknown
}

const MAX_WINDOW_MINUTES = 7 * 24 * 60
const MAX_PERF_ITERATIONS = 200
const metricsWindowSchema = boundedNumberDraft('时间窗口', 1, MAX_WINDOW_MINUTES).refine(Number.isInteger)
const perfIterationsSchema = boundedNumberDraft('性能迭代次数', 1, MAX_PERF_ITERATIONS).refine(Number.isInteger)

export function ObservabilityOpsPanel({ initialWindowMinutes }: Readonly<{ initialWindowMinutes: number }>) {
  const [datasetId, setDatasetId] = useState('')
  const [documentId, setDocumentId] = useState('')
  const [driftItemId, setDriftItemId] = useState('')
  const [resolutionNote, setResolutionNote] = useState('')
  const [windowMinutes, setWindowMinutes] = useState(() => String(initialWindowMinutes))
  const [iterations, setIterations] = useState('3')
  const [busy, setBusy] = useState<string | null>(null)
  const [result, setResult] = useState<ResultState | null>(null)
  const [actionError, setActionError] = useState<string | null>(null)
  const activeActionRef = useRef<symbol | null>(null)
  useLayoutEffect(
    () => () => {
      activeActionRef.current = null
    },
    [],
  )

  async function runAction(key: string, title: string, action: (ownsAction: () => boolean) => Promise<unknown>) {
    if (activeActionRef.current !== null) return
    const request = Symbol()
    const sessionKey = getAuthSessionKey()
    activeActionRef.current = request
    const ownsAction = () => activeActionRef.current === request && getAuthSessionKey() === sessionKey
    setBusy(key)
    setActionError(null)
    try {
      const payload = await action(ownsAction)
      if (!ownsAction()) return
      setResult({ title, payload })
      toast.success(key === 'tail' ? '指标日志下载已开始' : `${title}完成`)
    } catch (error) {
      if (ownsAction()) setActionError(formatApiError(error, `${title}失败`))
    } finally {
      if (activeActionRef.current === request) {
        activeActionRef.current = null
        setBusy(null)
      }
    }
  }

  function metricsWindowParams() {
    const parsedWindow = metricsWindowSchema.safeParse(windowMinutes)
    if (!parsedWindow.success) throw new Error(`时间窗口必须是 1 到 ${MAX_WINDOW_MINUTES} 的整数`)
    return { window_minutes: parsedWindow.data }
  }

  const scopedDatasetId = datasetId === '' ? undefined : datasetId
  const documentFilter = documentId.trim()
  const driftTargetId = driftItemId.trim()

  return (
    <fieldset disabled={busy !== null} className="space-y-5">
      <legend className="sr-only">观测运维操作</legend>
      <div className="grid gap-4 md:grid-cols-3">
        <Field label="时间窗口（分钟）">
          <Input value={windowMinutes} onChange={(event) => setWindowMinutes(event.target.value)} inputMode="numeric" />
        </Field>
        <DatasetSelectField
          value={datasetId}
          onChange={setDatasetId}
          label="数据集范围"
          allowAll
          className="space-y-2"
          labelClassName="text-[13px]"
          triggerClassName="h-11 text-base sm:h-9 sm:text-sm"
        />
        <Field label="性能迭代次数">
          <Input value={iterations} onChange={(event) => setIterations(event.target.value)} inputMode="numeric" />
        </Field>
      </div>

      <div className="mt-3 flex flex-wrap gap-2">
        <ActionButton
          icon={Activity}
          label="在线质量"
          busy={busy === 'online'}
          onClick={() =>
            runAction('online', '在线质量摘要', () => observabilityApi.getOnlineQualitySummary(metricsWindowParams()))
          }
        />
        <ActionButton
          icon={Activity}
          label="成本归因"
          busy={busy === 'cost'}
          onClick={() =>
            runAction('cost', 'RAG 成本归因', () => observabilityApi.getRagCostAttribution(metricsWindowParams()))
          }
        />
        <ActionButton
          icon={Download}
          label="Metrics Tail"
          busy={busy === 'tail'}
          onClick={() =>
            runAction('tail', '指标日志导出', async (ownsAction) => {
              const data = await observabilityApi.getRagMetricsTail(metricsWindowParams())
              if (!ownsAction()) return
              downloadBlob(`rag-metrics-tail.${Date.now()}.jsonl.gz`, new Blob([data], { type: 'application/gzip' }))
              return { bytes: data.byteLength }
            })
          }
        />
        <ActionButton
          icon={ShieldCheck}
          label="依赖健康"
          busy={busy === 'deps'}
          onClick={() => runAction('deps', '依赖诊断快照', () => observabilityApi.getDepsDiagnosticsSnapshot())}
        />
        <ActionButton
          icon={ShieldCheck}
          label="定时任务"
          busy={busy === 'jobs'}
          onClick={() => runAction('jobs', '定时任务新鲜度', () => observabilityApi.getPeriodicJobFreshness())}
        />
        <ActionButton
          icon={ShieldCheck}
          label="任务队列"
          busy={busy === 'queue'}
          onClick={() =>
            runAction('queue', '任务队列快照', () => observabilityApi.getTaskQueueSnapshot({ force_refresh: true }))
          }
        />
        <ActionButton
          icon={ShieldCheck}
          label="SLO"
          busy={busy === 'slo'}
          onClick={() => runAction('slo', 'SLO 快照', () => observabilityApi.getSloSnapshot())}
        />
        <ActionButton
          icon={RefreshCw}
          label="失效缓存"
          busy={busy === 'cache'}
          disabled={datasetId === ''}
          onClick={() => runAction('cache', '数据集缓存失效', () => observabilityApi.invalidateDatasetCache(datasetId))}
        />
        <ActionButton
          icon={Activity}
          label="Index Drift"
          busy={busy === 'index'}
          onClick={() =>
            runAction('index', 'Index drift 列表', () =>
              observabilityApi.listIndexDrift({ dataset_id: scopedDatasetId, limit: 20 }),
            )
          }
        />
      </div>

      <details className="border-t border-border pt-4">
        <summary className="cursor-pointer text-[13px] font-medium text-foreground">高级参数</summary>
        <div className="mt-3 grid gap-2 md:grid-cols-3">
          <Field label="文档标识">
            <Input
              value={documentId}
              onChange={(event) => setDocumentId(event.target.value)}
              className="font-mono"
              placeholder="Embedding drift 可选"
            />
          </Field>
          <Field label="Drift 项">
            <Input value={driftItemId} onChange={(event) => setDriftItemId(event.target.value)} className="font-mono" />
          </Field>
          <Field label="处理备注">
            <Input value={resolutionNote} onChange={(event) => setResolutionNote(event.target.value)} />
          </Field>
        </div>
        <div className="mt-3 flex flex-wrap gap-2">
          <ActionButton
            icon={Activity}
            label="Embedding Drift"
            busy={busy === 'embedding'}
            onClick={() =>
              runAction('embedding', 'Embedding drift 快照', () =>
                observabilityApi.getEmbeddingDriftSnapshot({
                  dataset_id: scopedDatasetId,
                  document_id: documentFilter === '' ? undefined : documentFilter,
                }),
              )
            }
          />
          <ActionButton
            icon={Activity}
            label="Perf Suite"
            busy={busy === 'perf'}
            onClick={() =>
              runAction('perf', '性能套件', () => {
                const count = perfIterationsSchema.safeParse(iterations)
                if (!count.success) throw new Error(`性能迭代次数必须是 1 到 ${MAX_PERF_ITERATIONS} 的整数`)
                return observabilityApi.runPerfSuite({ iterations: count.data, timeout_sec: 2 })
              })
            }
          />
          <ActionButton
            icon={Activity}
            label="Trace 上报"
            busy={busy === 'frontend-trace'}
            onClick={() =>
              runAction('frontend-trace', '前端 Trace 上报', async () => {
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
              })
            }
          />
          <ActionButton
            icon={ShieldCheck}
            label="标记已解决"
            busy={busy === 'resolve-index'}
            disabled={driftTargetId === ''}
            onClick={() =>
              runAction('resolve-index', '解决 Index drift', () =>
                observabilityApi.resolveIndexDrift(driftTargetId, { resolution_note: resolutionNote.trim() }),
              )
            }
          />
        </div>
      </details>

      {result === null ? (
        <p className="text-[13px] text-muted-foreground">尚无执行结果。</p>
      ) : (
        <OperationResultPanel
          className="rounded-none border-0 bg-transparent p-0"
          title="观测运维结果"
          result={result}
          emptyMessage="尚无执行结果。"
        />
      )}
      {actionError ? <WorkspaceNotice placement="floating">{actionError}</WorkspaceNotice> : null}
    </fieldset>
  )
}

function Field({ label, children }: Readonly<{ label: string; children: ReactNode }>) {
  return (
    <label className="block space-y-2 text-[13px]">
      <span className="font-medium text-muted-foreground">{label}</span>
      {children}
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
  disabled?: boolean
  icon: PlatformIcon
  label: string
  onClick: () => Promise<void>
}>) {
  return (
    <LoadingButton
      variant="outline"
      className="gap-2 text-[13px]"
      loading={busy}
      disabled={disabled}
      onClick={() => detachPromise(onClick())}
    >
      <Icon className="size-4" />
      {label}
    </LoadingButton>
  )
}
