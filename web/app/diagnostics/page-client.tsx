'use client'

import { useCallback, useEffect, useMemo, useState, type ComponentProps, type ReactNode } from 'react'
import {
  Activity,
  BarChart3,
  CheckCircle2,
  ClipboardCheck,
  Clock,
  Copy,
  Cpu,
  Database,
  FileJson,
  FileSearch,
  Gauge,
  Hash,
  RefreshCcw,
  ShieldCheck,
  Stethoscope,
  Timer,
  Zap,
  type LucideIcon,
} from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { StatusBadge } from '@/components/ui/status-badge'
import { Textarea } from '@/components/ui/textarea'
import { useBackendHealth } from '@/hooks/use-backend-health'
import { useBackendMeta } from '@/hooks/use-backend-meta'
import { useBackendReady } from '@/hooks/use-backend-ready'
import { formatApiError } from '@/lib/api-errors'
import { observabilityApi, ragApi } from '@/lib/api'
import { cn } from '@/lib/utils'
import { EmptyState } from '@/components/ui/empty-state'
import { systemPageTokens } from '@/components/ui/system-page-tokens'
import type { OnlineQualitySummaryResponse, PromptPreviewResponse } from '@/types'

const DENSE_OUTLINE_BUTTON = 'h-8 gap-1.5 rounded-lg border-border/70 bg-background px-3 text-xs font-medium'
const DENSE_ICON_BUTTON = 'h-8 w-8 rounded-lg'
const DENSE_CARD_CLASS = 'rounded-lg border-border/70 shadow-none transition-none hover:translate-y-0 hover:shadow-none'
const DENSE_JSON_SUMMARY = cn(
  'cursor-pointer select-none text-xs font-medium transition-colors hover:text-foreground',
  systemPageTokens.subtle,
)
const WORKBENCH_CARD_CLASS =
  'rounded-xl border border-slate-200/80 bg-white shadow-[0_1px_0_rgba(15,23,42,0.03)]'

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function fmtPercent(v?: number | null, digits = 1) {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  return `${(Number(v) * 100).toFixed(digits)}%`
}

function fmtScore(v?: number | null, digits = 2) {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  return Number(v).toFixed(digits)
}

function pickMetricNumber(source: unknown, keys: string[]): number | null {
  if (!source || typeof source !== 'object') return null
  const record = source as Record<string, unknown>
  for (const key of keys) {
    const value = record[key]
    if (typeof value === 'number' && Number.isFinite(value)) return value
    if (typeof value === 'string') {
      const parsed = Number(value)
      if (Number.isFinite(parsed)) return parsed
    }
  }
  return null
}

function metricTone(value: number | null, good = 0.8): 'slate' | 'green' | 'amber' | 'red' {
  if (value == null) return 'slate'
  if (value >= good) return 'green'
  if (value >= good * 0.72) return 'amber'
  return 'red'
}

async function copyToClipboard(text = ''): Promise<void> {
  try {
    if (typeof navigator === 'undefined' || !navigator.clipboard?.writeText) {
      throw new Error('Clipboard API unavailable')
    }
    await navigator.clipboard.writeText(text)
    toast.success('已复制到剪贴板')
  } catch (err) {
    console.error('Copy failed:', err)
    toast.error('复制失败')
  }
}

function DenseCard({ className, ...props }: Readonly<ComponentProps<typeof Card>>) {
  return <Card className={cn(DENSE_CARD_CLASS, className)} {...props} />
}

function DenseCardHeader({ className, ...props }: Readonly<ComponentProps<typeof CardHeader>>) {
  return <CardHeader className={cn('space-y-0 px-3 py-2.5', className)} {...props} />
}

function DenseCardContent({ className, ...props }: Readonly<ComponentProps<typeof CardContent>>) {
  return <CardContent className={cn('px-3 pb-3 pt-0', className)} {...props} />
}

function OverviewMetric({
  icon: Icon,
  label,
  value,
  detail,
  tone = 'slate',
}: Readonly<{
  icon: LucideIcon
  label: string
  value: string
  detail?: string
  tone?: 'slate' | 'green' | 'amber' | 'red' | 'blue'
}>) {
  const toneClass = {
    slate: 'border-slate-200 bg-slate-50 text-slate-500',
    green: 'border-emerald-200 bg-emerald-50/80 text-emerald-600',
    amber: 'border-amber-200 bg-amber-50/80 text-amber-600',
    red: 'border-red-200 bg-red-50/80 text-red-600',
    blue: 'border-blue-200 bg-blue-50/80 text-blue-600',
  }[tone]

  return (
    <div className={cn(WORKBENCH_CARD_CLASS, 'px-3 py-2.5')}>
      <div className="flex items-center gap-2.5">
        <span className={cn('flex size-8 shrink-0 items-center justify-center rounded-full border', toneClass)}>
          <Icon className="size-4" />
        </span>
        <div className="min-w-0">
          <div className="truncate text-[11px] font-normal text-slate-500">{label}</div>
          <div className="mt-0.5 truncate text-[16px] font-medium leading-none tracking-[-0.015em] text-slate-950">
            {value}
          </div>
          {detail ? <div className="mt-0.5 truncate text-[10px] text-slate-500">{detail}</div> : null}
        </div>
      </div>
    </div>
  )
}

function NumberedPanel({
  index,
  title,
  subtitle,
  actions,
  className,
  children,
}: Readonly<{
  index: number
  title: string
  subtitle?: string
  actions?: ReactNode
  className?: string
  children: ReactNode
}>) {
  return (
    <section className={cn(WORKBENCH_CARD_CLASS, 'p-3', className)}>
      <div className="mb-2 flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex items-center gap-2">
            <span className="flex size-5 shrink-0 items-center justify-center rounded-md border border-blue-100 bg-blue-50 text-[11px] font-medium text-blue-700">
              {index}
            </span>
            <h2 className="truncate text-[13px] font-medium tracking-[-0.005em] text-slate-950">{title}</h2>
          </div>
          {subtitle ? <p className="mt-0.5 text-[10px] leading-4 text-slate-500">{subtitle}</p> : null}
        </div>
        {actions ? <div className="flex shrink-0 items-center gap-1.5">{actions}</div> : null}
      </div>
      {children}
    </section>
  )
}

function DimensionTile({
  icon: Icon,
  title,
  detail,
  active,
  tone = 'blue',
}: Readonly<{
  icon: LucideIcon
  title: string
  detail: string
  active?: boolean
  tone?: 'blue' | 'green' | 'amber' | 'slate'
}>) {
  const toneClass = {
    blue: active ? 'border-blue-200 bg-blue-50 text-blue-600' : 'border-slate-200 bg-white text-slate-400',
    green: active ? 'border-emerald-200 bg-emerald-50 text-emerald-600' : 'border-slate-200 bg-white text-slate-400',
    amber: active ? 'border-amber-200 bg-amber-50 text-amber-600' : 'border-slate-200 bg-white text-slate-400',
    slate: active ? 'border-slate-300 bg-slate-50 text-slate-600' : 'border-slate-200 bg-white text-slate-400',
  }[tone]

  return (
    <div
      className={cn(
        'flex items-center gap-2 rounded-lg border px-2.5 py-1.5 transition-colors',
        active ? 'border-slate-300 bg-slate-50/70' : 'border-slate-200 bg-white',
      )}
    >
      <span className={cn('flex size-6 shrink-0 items-center justify-center rounded-md border', toneClass)}>
        <Icon className="size-3.5" />
      </span>
      <div className="min-w-0">
        <div className="truncate text-[11px] font-normal text-slate-900">{title}</div>
        <div className="truncate text-[9px] text-slate-500">{detail}</div>
      </div>
    </div>
  )
}

function MetricTile({
  icon: Icon,
  label,
  value,
  detail,
  tone = 'slate',
}: Readonly<{
  icon: LucideIcon
  label: string
  value: string
  detail?: string
  tone?: 'slate' | 'green' | 'amber' | 'red' | 'blue'
}>) {
  const toneClass = {
    slate: 'border-slate-200 bg-slate-50 text-slate-500',
    green: 'border-emerald-200 bg-emerald-50 text-emerald-600',
    amber: 'border-amber-200 bg-amber-50 text-amber-600',
    red: 'border-red-200 bg-red-50 text-red-600',
    blue: 'border-blue-200 bg-blue-50 text-blue-600',
  }[tone]

  return (
    <div className="rounded-lg border border-slate-200/80 bg-white px-3 py-2">
      <div className="flex items-center gap-2.5">
        <span className={cn('flex size-7 shrink-0 items-center justify-center rounded-lg border', toneClass)}>
          <Icon className="size-4" />
        </span>
        <div className="min-w-0">
          <div className="truncate text-[11px] font-normal text-slate-500">{label}</div>
          <div className="mt-0.5 text-[15px] font-medium leading-none text-slate-950">{value}</div>
          {detail ? <div className="mt-1 truncate text-[10px] text-slate-500">{detail}</div> : null}
        </div>
      </div>
    </div>
  )
}

export default function DiagnosticsPage() {
  const health = useBackendHealth()
  const meta = useBackendMeta()
  const ready = useBackendReady()

  const [onlineQuality, setOnlineQuality] = useState<OnlineQualitySummaryResponse | null>(null)
  const [onlineQualityLoading, setOnlineQualityLoading] = useState(false)

  const [probeDatasetId, setProbeDatasetId] = useState('')
  const [probeDocumentIdsRaw, setProbeDocumentIdsRaw] = useState('')
  const [probeQuery, setProbeQuery] = useState('Summarize what you know about this dataset.')
  const [probeResult, setProbeResult] = useState<PromptPreviewResponse | null>(null)
  const [probeLatencyMs, setProbeLatencyMs] = useState<number | null>(null)
  const [probeRunning, setProbeRunning] = useState(false)

  const [driftDatasetId, setDriftDatasetId] = useState('')
  const [driftDocumentId, setDriftDocumentId] = useState('')
  const [driftSampleN, setDriftSampleN] = useState(200)
  const [driftThreshold, setDriftThreshold] = useState(0.05)
  const [driftSnapshot, setDriftSnapshot] = useState<Record<string, any> | null>(null)
  const [driftLatencyMs, setDriftLatencyMs] = useState<number | null>(null)
  const [driftRunning, setDriftRunning] = useState(false)

  const [perfSuiteIterations, setPerfSuiteIterations] = useState(10)
  const [perfSuiteTimeoutSec, setPerfSuiteTimeoutSec] = useState(2.0)
  const [perfSuiteResult, setPerfSuiteResult] = useState<Record<string, any> | null>(null)
  const [perfSuiteLatencyMs, setPerfSuiteLatencyMs] = useState<number | null>(null)
  const [perfSuiteRunning, setPerfSuiteRunning] = useState(false)

  const healthJson = prettyJson(health.data?.payload ?? { error: health.error ? String(health.error) : 'loading' })
  const metaJson = prettyJson(meta.data ?? { error: meta.error ? String(meta.error) : 'loading' })
  const readyJson = prettyJson(ready.data ?? { error: ready.error ? String(ready.error) : 'loading' })

  async function refreshOnlineQuality(): Promise<void> {
    setOnlineQualityLoading(true)
    try {
      const res = await observabilityApi.getOnlineQualitySummary({
        window_minutes: 240,
        bucket_minutes: 5,
      })
      setOnlineQuality(res)
    } catch (err) {
      setOnlineQuality(null)
      toast.error(formatApiError(err, '加载在线质量失败（需要 ENABLE_METRICS_LOG + ONLINE_EVAL_ENABLED）'))
    } finally {
      setOnlineQualityLoading(false)
    }
  }

  useEffect(() => {
    let cancelled = false
    const run = async () => {
      try {
        setOnlineQualityLoading(true)
        const res = await observabilityApi.getOnlineQualitySummary({
          window_minutes: 240,
          bucket_minutes: 5,
        })
        if (cancelled) return
        setOnlineQuality(res)
      } catch (err) {
        if (cancelled) return
        setOnlineQuality(null)
      } finally {
        if (!cancelled) setOnlineQualityLoading(false)
      }
    }
    run()
    return () => {
      cancelled = true
    }
  }, [])

  const probeDocumentIds = useMemo(() => {
    const raw = (probeDocumentIdsRaw || '').trim()
    if (!raw) return []
    return raw
      .split(',')
      .map((s) => s.trim())
      .filter(Boolean)
  }, [probeDocumentIdsRaw])

  const probeMetrics =
    probeResult?.metrics && typeof probeResult.metrics === 'object'
      ? (probeResult.metrics as Record<string, unknown>)
      : null

  async function runPromptPreviewProbe(): Promise<void> {
    const query = (probeQuery || '').trim()
    if (!query) {
      toast.error('请输入问题')
      return
    }

    const datasetId = (probeDatasetId || '').trim()
    const documentIds = probeDocumentIds

    setProbeRunning(true)
    setProbeResult(null)
    setProbeLatencyMs(null)

    const start = Date.now()
    try {
      const result = await ragApi.promptPreview({
        query,
        dataset_id: datasetId || undefined,
        document_ids: documentIds.length ? documentIds : undefined,
        structured_output: false,
      })
      setProbeLatencyMs(Math.max(0, Date.now() - start))
      setProbeResult(result)
    } catch (err) {
      toast.error(formatApiError(err, '检索增强生成提示词预览失败（RAG）'))
    } finally {
      setProbeRunning(false)
    }
  }

  async function runEmbeddingDriftSnapshotProbe(): Promise<void> {
    const datasetId = (driftDatasetId || '').trim()
    const documentId = (driftDocumentId || '').trim()

    const sampleN = Math.max(1, Math.min(2000, Math.trunc(Number(driftSampleN || 0) || 200)))
    const threshold = Math.max(0, Math.min(1, Number(driftThreshold || 0.05) || 0.05))

    setDriftRunning(true)
    setDriftSnapshot(null)
    setDriftLatencyMs(null)

    const start = Date.now()
    try {
      const result = await observabilityApi.getEmbeddingDriftSnapshot({
        dataset_id: datasetId || undefined,
        document_id: documentId || undefined,
        sample_n: sampleN,
        drift_threshold: threshold,
      })
      setDriftLatencyMs(Math.max(0, Date.now() - start))
      setDriftSnapshot(result as any)
    } catch (err) {
      toast.error(formatApiError(err, '向量漂移快照失败'))
    } finally {
      setDriftRunning(false)
    }
  }

  async function runPerfSuiteProbe(): Promise<void> {
    const iterations = Math.max(1, Math.min(200, Math.trunc(Number(perfSuiteIterations || 0) || 10)))
    const timeoutSec = Math.max(0.05, Math.min(10, Number(perfSuiteTimeoutSec || 0) || 2.0))

    setPerfSuiteRunning(true)
    setPerfSuiteResult(null)
    setPerfSuiteLatencyMs(null)

    const start = Date.now()
    try {
      const result = await observabilityApi.runPerfSuite({
        iterations,
        timeout_sec: timeoutSec,
      })
      setPerfSuiteLatencyMs(Math.max(0, Date.now() - start))
      setPerfSuiteResult(result as any)
    } catch (err) {
      toast.error(formatApiError(err, '性能套件运行失败'))
    } finally {
      setPerfSuiteRunning(false)
    }
  }

  const healthOk = Boolean(health.data?.payload?.ok)
  const readyOk = Boolean(ready.data?.ok)
  const healthTone = health.isPending ? 'amber' : healthOk ? 'green' : 'red'
  const readyTone = ready.isPending ? 'amber' : readyOk ? 'green' : ready.error ? 'red' : 'slate'
  const healthBadgeStatus = health.isPending ? 'processing' : healthOk ? 'completed' : 'failed'
  const healthBadgeLabel = health.isPending ? '检查中' : healthOk ? 'OK' : health.error ? '网络/服务异常' : '异常'
  const systemStatusLabel =
    health.isPending || ready.isPending
      ? '检查中'
      : healthOk && readyOk
        ? '运行正常'
        : '需要排查'
  const systemStatusClass =
    health.isPending || ready.isPending
      ? 'border-amber-200 bg-amber-50 text-amber-700'
      : healthOk && readyOk
        ? 'border-emerald-200 bg-emerald-50 text-emerald-700'
        : 'border-red-200 bg-red-50 text-red-700'
  const promptTokens = pickMetricNumber(probeMetrics, ['prompt_tokens', 'total_prompt_tokens', 'total_tokens'])
  const contextTokens = pickMetricNumber(probeMetrics, ['context_tokens', 'retrieval_context_tokens'])
  const retrievalCount = Array.isArray(probeResult?.citations) ? probeResult.citations.length : null
  const driftRate = pickMetricNumber(driftSnapshot, ['drift_rate', 'drift_ratio', 'exceed_ratio', 'exceeded_ratio'])
  const driftMean = pickMetricNumber(driftSnapshot, ['mean_distance', 'avg_distance', 'distance_mean'])
  const strictGatePassed =
    typeof (perfSuiteResult as any)?.diff?.strict_gate?.passed === 'boolean'
      ? Boolean((perfSuiteResult as any).diff.strict_gate.passed)
      : null
  const regressionCount = pickMetricNumber((perfSuiteResult as any)?.diff?.strict_gate, ['regressions'])
  const backendName = meta.data?.name || '—'
  const apiVersion = meta.data?.api_version || '—'
  const serverTime = health.data?.payload?.time || meta.data?.time || '—'
  const vectorBackend = ready.data?.vector?.backend || health.data?.payload?.vector_backend || '—'
  const databaseStatus = ready.data?.database?.status || '—'
  const vectorStatus = ready.data?.vector?.status || '—'
  const redisStatus = ready.data?.redis?.status || '—'
  const minioStatus = ready.data?.minio?.status || '—'
  const perfGateLabel = strictGatePassed == null ? '—' : strictGatePassed ? '通过' : '未通过'
  const backendSummaryJson = prettyJson({
    health: health.data?.payload ?? null,
    meta: meta.data ?? null,
    ready: ready.data ?? null,
    online_quality: onlineQuality ?? null,
    prompt_preview: probeResult ?? null,
    embedding_drift: driftSnapshot ?? null,
    perf_suite: perfSuiteResult ?? null,
  })
  const backendRecommendationSource =
    (perfSuiteResult as any)?.recommendations ??
    (perfSuiteResult as any)?.diff?.recommendations ??
    (driftSnapshot as any)?.recommendations ??
    (onlineQuality as any)?.recommendations
  const backendRecommendations = Array.isArray(backendRecommendationSource)
    ? backendRecommendationSource.map((item) => String(item)).filter(Boolean).slice(0, 3)
    : []

  return (
    <AppFrame>
    <PageScaffold
      title="诊断中心"
      description="配置诊断参数，执行诊断任务，查看结果与系统状态。"
      icon={Activity}
      iconColor="text-info"
      size="full"
      density="system-dense"
      actions={
        <div className="flex items-center gap-2">
          <span
            className={cn(
              'inline-flex h-8 items-center rounded-full border px-3 text-[12px] font-medium',
              systemStatusClass,
            )}
          >
            <span className="mr-1.5 size-1.5 rounded-full bg-current" />
            服务{systemStatusLabel}
          </span>
          <Button
            variant="outline"
            size="sm"
            className={DENSE_OUTLINE_BUTTON}
            onClick={() => {
              health.refetch()
              meta.refetch()
              ready.refetch()
              void refreshOnlineQuality()
            }}
          >
            <RefreshCcw className="size-3.5" />
            刷新
          </Button>
        </div>
      }
    >
      {health.error && meta.error && ready.error ? (
        <EmptyState
          icon={Stethoscope}
          title="后端不可达"
          description="无法连接到后端服务，请检查后端是否已启动以及网络配置是否正确。"
          className="mb-4"
        />
      ) : null}
      <div className="space-y-2.5">
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-7">
          <OverviewMetric
            icon={ShieldCheck}
            label="系统健康"
            value={health.isPending ? '检查中' : healthOk ? '正常' : '异常'}
            detail={healthOk ? 'OK' : 'Health'}
            tone={healthTone}
          />
          <OverviewMetric
            icon={Clock}
            label="服务时间"
            value={serverTime}
            detail="health/meta"
            tone={healthTone}
          />
          <OverviewMetric icon={Database} label="API 版本" value={apiVersion} detail={backendName} tone="blue" />
          <OverviewMetric
            icon={ClipboardCheck}
            label="依赖就绪"
            value={ready.isPending ? '检查中' : readyOk ? '就绪' : ready.error ? '异常' : '未知'}
            detail="ready.ok"
            tone={readyTone}
          />
          <OverviewMetric icon={ShieldCheck} label="在线评估" value={onlineQuality?.enabled ? '已启用' : '未启用'} detail="online_quality.enabled" tone={onlineQuality?.enabled ? 'green' : 'slate'} />
          <OverviewMetric icon={Gauge} label="性能门禁" value={perfGateLabel} detail="perf_suite.diff.strict_gate" tone={strictGatePassed == null ? 'slate' : strictGatePassed ? 'green' : 'red'} />
          <OverviewMetric
            icon={Timer}
            label="向量后端"
            value={vectorBackend}
            detail="ready.vector.backend"
            tone="blue"
          />
        </div>

        <div className="grid gap-3 xl:grid-cols-12">
          <NumberedPanel index={1} title="诊断配置" subtitle="锁定诊断对象与问题上下文。" className="xl:col-span-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="workbench-probe-dataset-id">数据集</Label>
                <Input
                  id="workbench-probe-dataset-id"
                  value={probeDatasetId}
                  onChange={(e) => setProbeDatasetId(e.target.value)}
                  placeholder="例如：9b2f..."
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="workbench-probe-document-ids">文档范围</Label>
                <Input
                  id="workbench-probe-document-ids"
                  value={probeDocumentIdsRaw}
                  onChange={(e) => setProbeDocumentIdsRaw(e.target.value)}
                  placeholder="例如：3f1a..., 8c02..."
                />
              </div>
              <div className="space-y-1.5 sm:col-span-2">
                <Label htmlFor="workbench-probe-query">会话描述 / 问题</Label>
                <Textarea
                  id="workbench-probe-query"
                  value={probeQuery}
                  onChange={(e) => setProbeQuery(e.target.value)}
                  className="min-h-12 resize-none"
                  placeholder="输入要诊断的 RAG 问题..."
                />
              </div>
            </div>
            <div className="mt-3 flex flex-wrap items-center gap-2">
              <Button size="sm" onClick={() => runPromptPreviewProbe()} disabled={probeRunning}>
                <Activity className="size-3.5" />
                {probeRunning ? '运行中…' : '运行 RAG 预览'}
              </Button>
              <Button variant="outline" size="sm" onClick={() => refreshOnlineQuality()} disabled={onlineQualityLoading}>
                <RefreshCcw className="size-3.5" />
                刷新质量
              </Button>
            </div>
          </NumberedPanel>

          <NumberedPanel index={2} title="RAG 诊断维度选择" subtitle="多选维度，右侧结果区按真实状态回填。" className="xl:col-span-4">
            <div className="grid gap-2 sm:grid-cols-2 2xl:grid-cols-3">
              <DimensionTile icon={FileSearch} title="知识检索准确性" detail="提示词与引用" active={Boolean(probeResult)} tone="blue" />
              <DimensionTile icon={CheckCircle2} title="检索召回率" detail="引用数量" active={retrievalCount != null && retrievalCount > 0} tone="green" />
              <DimensionTile icon={BarChart3} title="上下文相关性" detail="上下文 token" active={contextTokens != null} tone="slate" />
              <DimensionTile icon={Gauge} title="生成质量" detail="在线质量采样" active={Boolean(onlineQuality?.enabled)} tone="green" />
              <DimensionTile icon={Zap} title="事实一致性" detail="忠实度 det" active={onlineQuality?.faithfulness_det_avg != null} tone="blue" />
              <DimensionTile icon={ShieldCheck} title="安全合规性" detail="后端未返回则不显示" active={false} tone="green" />
              <DimensionTile icon={Clock} title="延迟与性能" detail="性能门禁" active={Boolean(perfSuiteResult)} tone="amber" />
              <DimensionTile icon={Cpu} title="成本分析" detail="提示词 token" active={promptTokens != null} tone="slate" />
            </div>
          </NumberedPanel>

          <NumberedPanel index={3} title="诊断参数配置" subtitle="采样、漂移、性能回归等运行参数。" className="xl:col-span-4">
            <div className="grid gap-3 sm:grid-cols-2">
              <div className="space-y-1.5">
                <Label htmlFor="workbench-drift-threshold">相似度阈值</Label>
                <Input
                  id="workbench-drift-threshold"
                  value={String(driftThreshold)}
                  onChange={(e) => setDriftThreshold(Number(e.target.value) || 0)}
                  inputMode="decimal"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="workbench-drift-sample-n">采样数量</Label>
                <Input
                  id="workbench-drift-sample-n"
                  value={String(driftSampleN)}
                  onChange={(e) => setDriftSampleN(Number.parseInt(e.target.value || '0', 10) || 0)}
                  inputMode="numeric"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="workbench-perf-suite-iters">迭代次数</Label>
                <Input
                  id="workbench-perf-suite-iters"
                  value={String(perfSuiteIterations)}
                  onChange={(e) => setPerfSuiteIterations(Number.parseInt(e.target.value || '0', 10) || 0)}
                  inputMode="numeric"
                />
              </div>
              <div className="space-y-1.5">
                <Label htmlFor="workbench-perf-suite-timeout">超时（秒）</Label>
                <Input
                  id="workbench-perf-suite-timeout"
                  value={String(perfSuiteTimeoutSec)}
                  onChange={(e) => setPerfSuiteTimeoutSec(Number(e.target.value) || 0)}
                  inputMode="decimal"
                />
              </div>
            </div>
            <div className="mt-3 flex flex-wrap gap-2">
              <Button variant="outline" size="sm" onClick={() => runEmbeddingDriftSnapshotProbe()} disabled={driftRunning}>
                {driftRunning ? '采样中…' : '运行漂移'}
              </Button>
              <Button variant="outline" size="sm" onClick={() => runPerfSuiteProbe()} disabled={perfSuiteRunning}>
                {perfSuiteRunning ? '运行中…' : '运行性能门禁'}
              </Button>
            </div>
          </NumberedPanel>
        </div>

        <NumberedPanel index={4} title="关键指标（评分状态）" subtitle="从已返回的真实接口结果中汇总；未运行的维度显示为空值。">
          <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-5">
            <MetricTile
              icon={FileSearch}
              label="检索相关性"
              value={fmtScore(pickMetricNumber(probeMetrics, ['retrieval_score', 'retrieval_relevance', 'relevance']))}
              detail={probeResult ? 'RAG 预览' : '未运行'}
              tone={metricTone(pickMetricNumber(probeMetrics, ['retrieval_score', 'retrieval_relevance', 'relevance']))}
            />
            <MetricTile
              icon={CheckCircle2}
              label="召回引用"
              value={retrievalCount == null ? '—' : String(retrievalCount)}
              detail="citations"
              tone={retrievalCount != null && retrievalCount > 0 ? 'green' : 'slate'}
            />
            <MetricTile
              icon={Hash}
              label="提示词 token"
              value={promptTokens == null ? '—' : promptTokens.toLocaleString()}
              detail={contextTokens == null ? '等待 RAG 预览' : `上下文 ${contextTokens.toLocaleString()}`}
              tone={promptTokens == null ? 'slate' : promptTokens > 8000 ? 'amber' : 'green'}
            />
            <MetricTile
              icon={Gauge}
              label="漂移率"
              value={fmtPercent(driftRate)}
              detail={driftMean == null ? 'Embedding Drift' : `均值 ${fmtScore(driftMean)}`}
              tone={driftRate == null ? 'slate' : driftRate > driftThreshold ? 'amber' : 'green'}
            />
            <MetricTile
              icon={ShieldCheck}
              label="性能门禁"
              value={strictGatePassed == null ? '—' : strictGatePassed ? '通过' : '未通过'}
              detail={regressionCount == null ? 'Perf Suite' : `回归项 ${regressionCount}`}
              tone={strictGatePassed == null ? 'slate' : strictGatePassed ? 'green' : 'red'}
            />
          </div>
        </NumberedPanel>

        <div className="grid gap-3 xl:grid-cols-12">
          <NumberedPanel index={5} title="性能分析" subtitle="仅展示性能套件后端返回结果。" className="xl:col-span-3">
            <div className="grid gap-2">
              <MetricTile
                icon={Gauge}
                label="严格门禁"
                value={perfGateLabel}
                detail="diff.strict_gate.passed"
                tone={strictGatePassed == null ? 'slate' : strictGatePassed ? 'green' : 'red'}
              />
              <MetricTile
                icon={Hash}
                label="回归项"
                value={regressionCount == null ? '—' : String(regressionCount)}
                detail="diff.strict_gate.regressions"
                tone={regressionCount == null ? 'slate' : regressionCount > 0 ? 'amber' : 'green'}
              />
              <MetricTile
                icon={Timer}
                label="报告时间"
                value={String((perfSuiteResult as any)?.current_report?.ts || '—')}
                detail="current_report.ts"
                tone="slate"
              />
            </div>
          </NumberedPanel>

          <NumberedPanel index={6} title="依赖资源" subtitle="来自后端 ready 接口。" className="xl:col-span-4">
            <div className="grid gap-2 sm:grid-cols-2">
              <MetricTile icon={Database} label="数据库" value={databaseStatus} detail="ready.database.status" tone={databaseStatus === 'ok' ? 'green' : 'slate'} />
              <MetricTile icon={FileSearch} label="向量库" value={vectorStatus} detail={vectorBackend} tone={vectorStatus === 'ok' ? 'green' : 'slate'} />
              <MetricTile icon={Activity} label="Redis" value={redisStatus} detail="ready.redis.status" tone={redisStatus === 'ok' ? 'green' : 'slate'} />
              <MetricTile icon={FileJson} label="MinIO" value={minioStatus} detail="ready.minio.status" tone={minioStatus === 'ok' ? 'green' : 'slate'} />
            </div>
          </NumberedPanel>

          <NumberedPanel
            index={7}
            title="后端输出"
            subtitle="当前页面已拉取的后端响应摘要。"
            className="xl:col-span-5"
            actions={
              <Button variant="outline" size="sm" className="h-7 px-2 text-[11px]" onClick={async () => copyToClipboard(backendSummaryJson)}>
                <Copy className="size-3.5" />
                复制
              </Button>
            }
          >
            <pre className="max-h-[170px] overflow-auto rounded-xl bg-slate-950 p-3 font-mono text-[11px] leading-5 text-slate-100 shadow-inner">
              {backendSummaryJson}
            </pre>
          </NumberedPanel>
        </div>

        <div className="grid gap-3 xl:grid-cols-12">
          <NumberedPanel index={8} title="后端结论字段" subtitle="只展示后端已返回的状态字段。" className="xl:col-span-6">
            <div className="grid gap-2 sm:grid-cols-2">
              <MetricTile icon={ShieldCheck} label="health.ok" value={health.data?.payload ? String(health.data.payload.ok) : '—'} detail="GET /health" tone={healthOk ? 'green' : 'slate'} />
              <MetricTile icon={ClipboardCheck} label="ready.ok" value={ready.data ? String(ready.data.ok) : '—'} detail="GET /health/ready" tone={readyOk ? 'green' : 'slate'} />
              <MetricTile icon={BarChart3} label="online.enabled" value={onlineQuality ? String(Boolean(onlineQuality.enabled)) : '—'} detail="online quality" tone={onlineQuality?.enabled ? 'green' : 'slate'} />
              <MetricTile icon={Gauge} label="perf.gate" value={perfGateLabel} detail="perf suite" tone={strictGatePassed == null ? 'slate' : strictGatePassed ? 'green' : 'red'} />
            </div>
          </NumberedPanel>

          <NumberedPanel index={9} title="后端建议" subtitle="仅展示后端响应中的 recommendations 字段。" className="xl:col-span-6">
            {backendRecommendations.length ? (
              <div className="space-y-2">
                {backendRecommendations.map((item, index) => (
                  <div key={`${index}-${item}`} className="flex items-start gap-2 rounded-lg border border-slate-200 bg-white px-3 py-2">
                    <span className="flex size-5 shrink-0 items-center justify-center rounded-full bg-blue-50 text-[11px] font-medium text-blue-600">
                      {index + 1}
                    </span>
                    <p className="text-[12px] leading-5 text-slate-600">{item}</p>
                  </div>
                ))}
              </div>
            ) : (
              <div className="rounded-lg border border-slate-200 bg-slate-50 px-3 py-2 text-[12px] text-slate-500">
                后端当前未返回 recommendations。
              </div>
            )}
          </NumberedPanel>
        </div>

        <details className="rounded-2xl border border-slate-200/80 bg-white p-3 shadow-[0_1px_0_rgba(15,23,42,0.03)]">
          <summary className="cursor-pointer select-none text-[13px] font-medium text-slate-800">
            排障材料（原始响应）
            <span className="ml-2 text-[11px] font-normal text-slate-500">默认收起，仅在异常排查时复制给开发或运维。</span>
          </summary>
          <div className="mt-3 grid gap-4 md:grid-cols-2">
        <DenseCard>
          <DenseCardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-sm">后端响应汇总</CardTitle>
            <Button
              variant="ghost"
              size="icon"
              className={DENSE_ICON_BUTTON}
              onClick={async () => copyToClipboard(backendSummaryJson)}
              title="复制 Backend Summary JSON"
              aria-label="复制 Backend Summary JSON"
            >
              <Copy className="h-4 w-4" />
            </Button>
          </DenseCardHeader>
          <DenseCardContent>
            <details>
              <summary className={DENSE_JSON_SUMMARY}>展开 JSON</summary>
              <pre className="mt-2 text-xs whitespace-pre-wrap break-words">{backendSummaryJson}</pre>
            </details>
          </DenseCardContent>
        </DenseCard>

        <DenseCard>
          <DenseCardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-sm">后端元信息</CardTitle>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon"
                className={DENSE_ICON_BUTTON}
                onClick={() => meta.refetch()}
                title="刷新 Backend Meta"
                aria-label="刷新 Backend Meta"
              >
                <RefreshCcw className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className={DENSE_ICON_BUTTON}
                onClick={async () => copyToClipboard(metaJson)}
                title="复制 Backend Meta JSON"
                aria-label="复制 Backend Meta JSON"
              >
                <Copy className="h-4 w-4" />
              </Button>
            </div>
          </DenseCardHeader>
          <DenseCardContent>
            <details>
              <summary className={DENSE_JSON_SUMMARY}>展开 JSON</summary>
              <pre className="mt-2 text-xs whitespace-pre-wrap break-words">{metaJson}</pre>
            </details>
          </DenseCardContent>
        </DenseCard>

        <DenseCard>
          <DenseCardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-sm">后端健康检查</CardTitle>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon"
                className={DENSE_ICON_BUTTON}
                onClick={() => health.refetch()}
                title="刷新 Backend Health"
                aria-label="刷新 Backend Health"
              >
                <RefreshCcw className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className={DENSE_ICON_BUTTON}
                onClick={async () => copyToClipboard(healthJson)}
                title="复制 Backend Health JSON"
                aria-label="复制 Backend Health JSON"
              >
                <Copy className="h-4 w-4" />
              </Button>
            </div>
          </DenseCardHeader>
          <DenseCardContent>
            <div className="flex items-center justify-between gap-3 pb-2">
              <StatusBadge
                status={(() => {
    if (health.isPending) {
        return 'processing';
    }
    else if (health.data?.payload?.ok) {
            return 'completed';
        }
        else {
            return 'failed';
        }
})()}
                label={
                  (() => {
    if (health.isPending) {
        return '检查中';
    }
    else if (health.data?.payload?.ok) {
            return 'OK';
        }
        else if (health.error) {
                return '网络/服务异常';
            }
            else {
                return '异常';
            }
})()
                }
                dense
              />
            </div>
            <details>
              <summary className={DENSE_JSON_SUMMARY}>展开 JSON</summary>
              <pre className="mt-2 text-xs whitespace-pre-wrap break-words">{healthJson}</pre>
            </details>
          </DenseCardContent>
        </DenseCard>

        <DenseCard>
          <DenseCardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-sm">依赖就绪状态</CardTitle>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon"
                className={DENSE_ICON_BUTTON}
                onClick={() => ready.refetch()}
                title="刷新依赖就绪（Deps Ready）"
                aria-label="刷新依赖就绪（Deps Ready）"
              >
                <RefreshCcw className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className={DENSE_ICON_BUTTON}
                onClick={async () => copyToClipboard(readyJson)}
                title="复制依赖就绪 JSON（Deps Ready）"
                aria-label="复制依赖就绪 JSON（Deps Ready）"
              >
                <Copy className="h-4 w-4" />
              </Button>
            </div>
          </DenseCardHeader>
          <DenseCardContent>
            <details>
              <summary className={DENSE_JSON_SUMMARY}>展开 JSON</summary>
              <pre className="mt-2 text-xs whitespace-pre-wrap break-words">{readyJson}</pre>
            </details>
          </DenseCardContent>
        </DenseCard>
          </div>
        </details>
      </div>
	    </PageScaffold>
    </AppFrame>
	  )
	}
