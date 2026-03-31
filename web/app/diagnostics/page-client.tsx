'use client'

import { useCallback, useEffect, useMemo, useState } from 'react'
import { Activity, Copy, FileJson, FileText, RefreshCcw, Timer, Hash, FileSearch, Gauge, Package, Stethoscope, BarChart3, AlertTriangle } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Card, CardContent, CardHeader, CardTitle } from '@/components/ui/card'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { StatusBadge } from '@/components/ui/status-badge'
import { Textarea } from '@/components/ui/textarea'
import { useBackendHealth } from '@/hooks/use-backend-health'
import { useBackendMeta } from '@/hooks/use-backend-meta'
import { useBackendReady } from '@/hooks/use-backend-ready'
import { formatApiError } from '@/lib/api-errors'
import {
  classifyStoragePressure,
  getDocContentCacheStats,
  getDocSourceCacheStats,
  clearDocContentCache,
  clearDocSourceCache,
  pruneStaleDocCaches,
  type DocContentCacheStats,
  type DocSourceCacheStats,
} from '@/lib/doc-content-cache'
import { observabilityApi, ragApi } from '@/lib/api'
import { API_BASE_URL, API_LONG_TIMEOUT_MS, API_TIMEOUT_MS, API_V1_BASE_URL } from '@/lib/env'
import { formatFileSize } from '@/lib/utils'
import { EmptyState } from '@/components/ui/empty-state'
import type { OnlineQualitySummaryResponse, PromptPreviewResponse } from '@/types'

import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip, CartesianGrid } from 'recharts'

function prettyJson(value: unknown): string {
  try {
    return JSON.stringify(value, null, 2)
  } catch {
    return String(value)
  }
}

function formatTs(tsMs: number) {
  try {
    return new Date(tsMs).toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' })
  } catch {
    return String(tsMs)
  }
}

function fmtPercent(v?: number | null, digits = 1) {
  if (v == null || !Number.isFinite(Number(v))) return '—'
  return `${(Number(v) * 100).toFixed(digits)}%`
}

type CacheStats = {
  content: DocContentCacheStats
  source: DocSourceCacheStats
}

type CacheCleanupState = {
  stale: boolean
  content: boolean
  source: boolean
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

type PerfScriptTiming = {
  name: string
  transfer_bytes: number
  decoded_bytes: number
  duration_ms: number
}

type PerfSnapshot = {
  captured_at_iso: string
  navigation?: {
    type: string
    ttfb_ms: number | null
    dom_content_loaded_ms: number | null
    load_ms: number | null
  }
  scripts: {
    count: number
    total_transfer_bytes: number
    total_decoded_bytes: number
    top: PerfScriptTiming[]
  }
}

function safeResourceName(raw: string): string {
  const input = String(raw || '').trim()
  if (!input) return ''
  try {
    const url = new URL(input)
    return url.pathname || input
  } catch {
    return input.split('?')[0] || input
  }
}

function takePerfSnapshot(): PerfSnapshot | null {
  if (typeof performance === 'undefined') return null

  const nav = performance.getEntriesByType('navigation')[0] as PerformanceNavigationTiming | undefined
  const navSnapshot = nav
    ? {
        type: String(nav.type || ''),
        ttfb_ms: Number.isFinite(nav.responseStart) ? Number(nav.responseStart) : null,
        dom_content_loaded_ms: Number.isFinite(nav.domContentLoadedEventEnd)
          ? Number(nav.domContentLoadedEventEnd)
          : null,
        load_ms: Number.isFinite(nav.loadEventEnd) ? Number(nav.loadEventEnd) : null,
      }
    : undefined

  const resources = performance.getEntriesByType('resource') as PerformanceResourceTiming[]
  const scripts = (resources || []).filter((r) => {
    const initiator = String((r as any)?.initiatorType || '')
    if (initiator === 'script') return true
    const name = String((r as any)?.name || '')
    return name.includes('/_next/static/') && name.includes('.js')
  })

  const rows: PerfScriptTiming[] = scripts.map((r) => {
    const name = safeResourceName(String((r as any)?.name || ''))
    const transfer = Number((r as any)?.transferSize || 0)
    const decoded = Number((r as any)?.decodedBodySize || 0)
    const duration = Number((r as any)?.duration || 0)
    return {
      name,
      transfer_bytes: Number.isFinite(transfer) ? transfer : 0,
      decoded_bytes: Number.isFinite(decoded) ? decoded : 0,
      duration_ms: Number.isFinite(duration) ? duration : 0,
    }
  })

  const sorted = rows
    .slice()
    .sort((a, b) => (b.transfer_bytes || b.decoded_bytes) - (a.transfer_bytes || a.decoded_bytes))

  const totalTransfer = rows.reduce((acc, r) => acc + (Number(r.transfer_bytes) || 0), 0)
  const totalDecoded = rows.reduce((acc, r) => acc + (Number(r.decoded_bytes) || 0), 0)

  return {
    captured_at_iso: new Date().toISOString(),
    navigation: navSnapshot,
    scripts: {
      count: rows.length,
      total_transfer_bytes: totalTransfer,
      total_decoded_bytes: totalDecoded,
      top: sorted.slice(0, 10),
    },
  }
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

  const [perfSnapshot, setPerfSnapshot] = useState<PerfSnapshot | null>(null)
  const [storageEstimate, setStorageEstimate] = useState<StorageEstimate | null>(null)
  const [cacheStats, setCacheStats] = useState<CacheStats | null>(null)
  const [cacheLoading, setCacheLoading] = useState(false)
  const [cleanupLoading, setCleanupLoading] = useState<CacheCleanupState>({
    stale: false,
    content: false,
    source: false,
  })

  const docsUrl = `${API_BASE_URL}/docs`
  const openapiUrl = `${API_BASE_URL}/openapi.json`
  const storageCapable =
    typeof navigator !== 'undefined' &&
    typeof navigator.storage?.estimate === 'function'

  const healthJson = prettyJson(health.data?.payload ?? { error: health.error ? String(health.error) : 'loading' })
  const metaJson = prettyJson(meta.data ?? { error: meta.error ? String(meta.error) : 'loading' })
  const readyJson = prettyJson(ready.data ?? { error: ready.error ? String(ready.error) : 'loading' })

  const envJson = prettyJson({
    API_BASE_URL,
    API_V1_BASE_URL,
    API_TIMEOUT_MS,
    API_LONG_TIMEOUT_MS,
  })

  const loadStorageEstimate = useCallback(async () => {
    if (!storageCapable) {
      setStorageEstimate(null)
      return
    }
    try {
      const estimate = await navigator.storage.estimate()
      setStorageEstimate(estimate)
    } catch (error) {
      console.warn('Storage estimate failed', error)
      setStorageEstimate(null)
    }
  }, [storageCapable])

  const refreshCacheStats = useCallback(async () => {
    if (globalThis.window === undefined) {
      setCacheStats(null)
      return
    }
    setCacheLoading(true)
    try {
      const [content, source] = await Promise.all([getDocContentCacheStats(), getDocSourceCacheStats()])
      setCacheStats({ content, source })
    } catch (error) {
      console.error('Cache stats failed', error)
      toast.error('读取缓存统计失败')
    } finally {
      setCacheLoading(false)
    }
  }, [])

  const refreshStorageAndCache = useCallback(() => {
    void loadStorageEstimate()
    void refreshCacheStats()
  }, [loadStorageEstimate, refreshCacheStats])

  useEffect(() => {
    refreshStorageAndCache()
  }, [refreshStorageAndCache])

  const handleClearContentCache = useCallback(async () => {
    setCleanupLoading((prev) => ({ ...prev, content: true }))
    try {
      await clearDocContentCache()
      toast.success('文档内容缓存已清理')
    } catch (error) {
      console.error('Clear content cache failed', error)
      toast.error('清理文档内容缓存失败')
    } finally {
      setCleanupLoading((prev) => ({ ...prev, content: false }))
      void refreshCacheStats()
    }
  }, [refreshCacheStats])

  const handleClearSourceCache = useCallback(async () => {
    setCleanupLoading((prev) => ({ ...prev, source: true }))
    try {
      await clearDocSourceCache()
      toast.success('文档源文件缓存已清理')
    } catch (error) {
      console.error('Clear source cache failed', error)
      toast.error('清理文档源文件缓存失败')
    } finally {
      setCleanupLoading((prev) => ({ ...prev, source: false }))
      void refreshCacheStats()
    }
  }, [refreshCacheStats])

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
      toast.error(formatApiError(err, '加载 Online Quality 失败（需要 ENABLE_METRICS_LOG + ONLINE_EVAL_ENABLED）'))
    } finally {
      setOnlineQualityLoading(false)
    }
  }

  useEffect(() => {
    setPerfSnapshot(takePerfSnapshot())
  }, [])

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

  const perfJson = useMemo(() => prettyJson(perfSnapshot ?? { error: 'perf snapshot not captured' }), [perfSnapshot])
  const driftJson = useMemo(() => prettyJson(driftSnapshot ?? { error: 'no drift snapshot yet' }), [driftSnapshot])
  const perfSuiteJson = useMemo(() => prettyJson(perfSuiteResult ?? { error: 'no perf suite run yet' }), [perfSuiteResult])
  const storageUsageRatio =
    storageEstimate?.usage != null && storageEstimate.quota ? storageEstimate.usage / storageEstimate.quota : null
  const docContentSize = cacheStats?.content.totalBytes ?? 0
  const docSourceSize = cacheStats?.source.totalBytes ?? 0
  const docContentEntries = cacheStats?.content.entries ?? 0
  const docSourceEntries = cacheStats?.source.entries ?? 0
  const docContentUpdatedAt = cacheStats?.content.lastUpdatedAt ?? null
  const docSourceUpdatedAt = cacheStats?.source.lastUpdatedAt ?? null
  const pressure = useMemo(
    () =>
      classifyStoragePressure({
        storageEstimate,
        cacheStats,
      }),
    [cacheStats, storageEstimate]
  )
  const shouldShowPressureWarning = pressure.level === 'high'
  const shouldShowCleanupCta = shouldShowPressureWarning || ((pressure.cacheShareOfUsage ?? 0) >= 0.65 && pressure.totalCacheBytes > 10 * 1024 * 1024)

  const onlineQualityChartData = useMemo(() => {
    const ts = onlineQuality?.timeseries?.ts_ms || []
    const samples = onlineQuality?.timeseries?.samples || []
    const faith = onlineQuality?.timeseries?.faithfulness_det_avg || []
    const util = onlineQuality?.timeseries?.chunk_utilization_avg || []
    const out: Array<Record<string, any>> = []
    for (let i = 0; i < ts.length; i++) {
      const t = Number(ts[i] || 0)
      out.push({
        t,
        time: formatTs(t),
        samples: Number(samples[i] || 0),
        faithfulness_det_avg: faith[i] == null ? null : Number(faith[i] || 0),
        chunk_utilization_avg: util[i] == null ? null : Number(util[i] || 0),
      })
    }
    return out
  }, [onlineQuality?.timeseries])

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
  const probeMetricsJson = prettyJson(probeMetrics || { error: 'no probe yet' })

  async function runPromptPreviewProbe(): Promise<void> {
    const query = (probeQuery || '').trim()
    if (!query) {
      toast.error('请输入 query')
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
      toast.error(formatApiError(err, 'RAG prompt-preview failed'))
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
      toast.error(formatApiError(err, 'Embedding drift snapshot failed'))
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
      toast.error(formatApiError(err, 'Perf suite run failed'))
    } finally {
      setPerfSuiteRunning(false)
    }
  }

  const handlePruneStaleCaches = useCallback(async () => {
    setCleanupLoading((prev) => ({ ...prev, stale: true }))
    try {
      const result = await pruneStaleDocCaches(14 * 24 * 60 * 60 * 1000)
      if (result.totalDeleted > 0) {
        toast.success(`已清理过期缓存 ${result.totalDeleted} 条（内容 ${result.contentDeleted}，源文件 ${result.sourceDeleted}）`)
      } else {
        toast.message('未发现可清理的过期缓存')
      }
    } catch (error) {
      console.error('Prune stale caches failed', error)
      toast.error('清理过期缓存失败')
    } finally {
      setCleanupLoading((prev) => ({ ...prev, stale: false }))
      void refreshStorageAndCache()
    }
  }, [refreshStorageAndCache])

  return (
    <AppFrame>
    <PageScaffold
      title="诊断"
      description="前后端联调信息（后端健康 / 依赖就绪 / 后端元数据 / 前端 API 配置）"
      icon={Activity}
      iconColor="text-info"
      size="5xl"
      actions={
        <div className="flex items-center gap-2">
          <Button asChild variant="outline" size="sm" className="gap-2">
            <a href={docsUrl} target="_blank" rel="noreferrer" aria-label="打开后端接口文档（/docs）">
              <FileText className="h-4 w-4" aria-hidden="true" />
              /docs
            </a>
          </Button>
          <Button asChild variant="outline" size="sm" className="gap-2">
            <a href={openapiUrl} target="_blank" rel="noreferrer" aria-label="打开后端 OpenAPI（/openapi.json）">
              <FileJson className="h-4 w-4" aria-hidden="true" />
              openapi.json
            </a>
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
      <div className="grid gap-4 md:grid-cols-2">
        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-sm">Frontend Env</CardTitle>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              onClick={async () => copyToClipboard(envJson)}
              title="复制 Frontend Env JSON"
              aria-label="复制 Frontend Env JSON"
            >
              <Copy className="h-4 w-4" />
            </Button>
          </CardHeader>
          <CardContent>
            <details>
              <summary className="text-xs font-medium text-muted-foreground cursor-pointer select-none hover:text-foreground transition-colors">展开 JSON</summary>
              <pre className="mt-2 text-xs whitespace-pre-wrap break-words">{envJson}</pre>
            </details>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-sm">Backend Meta</CardTitle>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => meta.refetch()}
                title="刷新 Backend Meta"
                aria-label="刷新 Backend Meta"
              >
                <RefreshCcw className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={async () => copyToClipboard(metaJson)}
                title="复制 Backend Meta JSON"
                aria-label="复制 Backend Meta JSON"
              >
                <Copy className="h-4 w-4" />
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <details>
              <summary className="text-xs font-medium text-muted-foreground cursor-pointer select-none hover:text-foreground transition-colors">展开 JSON</summary>
              <pre className="mt-2 text-xs whitespace-pre-wrap break-words">{metaJson}</pre>
            </details>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-sm">Backend Health</CardTitle>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => health.refetch()}
                title="刷新 Backend Health"
                aria-label="刷新 Backend Health"
              >
                <RefreshCcw className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={async () => copyToClipboard(healthJson)}
                title="复制 Backend Health JSON"
                aria-label="复制 Backend Health JSON"
              >
                <Copy className="h-4 w-4" />
              </Button>
            </div>
          </CardHeader>
          <CardContent>
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
              {typeof health.data?.latencyMs === 'number' ? (
                <span className="text-xs text-muted-foreground tabular-nums">{health.data.latencyMs}ms</span>
              ) : null}
            </div>
            <details>
              <summary className="text-xs font-medium text-muted-foreground cursor-pointer select-none hover:text-foreground transition-colors">展开 JSON</summary>
              <pre className="mt-2 text-xs whitespace-pre-wrap break-words">{healthJson}</pre>
            </details>
          </CardContent>
        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-sm">Deps Ready</CardTitle>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => ready.refetch()}
                title="刷新 Deps Ready"
                aria-label="刷新 Deps Ready"
              >
                <RefreshCcw className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={async () => copyToClipboard(readyJson)}
                title="复制 Deps Ready JSON"
                aria-label="复制 Deps Ready JSON"
              >
                <Copy className="h-4 w-4" />
              </Button>
            </div>
          </CardHeader>
          <CardContent>
            <details>
              <summary className="text-xs font-medium text-muted-foreground cursor-pointer select-none hover:text-foreground transition-colors">展开 JSON</summary>
              <pre className="mt-2 text-xs whitespace-pre-wrap break-words">{readyJson}</pre>
            </details>
          </CardContent>
        </Card>

        <Card className="md:col-span-2">
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-sm">Online Quality (sampled)</CardTitle>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => refreshOnlineQuality()}
                disabled={onlineQualityLoading}
                title="刷新 Online Quality 采样结果"
                aria-label="刷新 Online Quality 采样结果"
              >
                <RefreshCcw className="h-4 w-4" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={async () => copyToClipboard(prettyJson(onlineQuality))}
                disabled={!onlineQuality}
                title="复制 Online Quality JSON"
                aria-label="复制 Online Quality JSON"
              >
                <Copy className="h-4 w-4" />
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {onlineQuality?.enabled ? (
              <>
                <StatsGrid className="xl:grid-cols-4">
                  <StatCard
                    icon={Package}
                    label="Samples"
                    value={String(onlineQuality.sample_count ?? 0)}
                    subValue={`window=${onlineQuality.window_minutes}m · bucket=${onlineQuality.bucket_minutes}m`}
                    color="blue"
                  />
                  <StatCard
                    icon={BarChart3}
                    label="Faithfulness(det)"
                    value={fmtPercent(onlineQuality.faithfulness_det_avg, 1)}
                    subValue="avg"
                    color="teal"
                  />
                  <StatCard
                    icon={BarChart3}
                    label="Chunk Utilization"
                    value={fmtPercent(onlineQuality.chunk_utilization_avg, 1)}
                    subValue="avg"
                    color="sky"
                  />
                  <StatCard
                    icon={AlertTriangle}
                    label="Alerts"
                    value={String((onlineQuality.alerts || []).length)}
                    subValue="latest bucket"
                    color={(onlineQuality.alerts || []).length ? 'red' : 'green'}
                  />
                </StatsGrid>

                <div className="grid gap-4 md:grid-cols-2">
                  <div className="rounded-xl border border-border/60 p-3">
                    <div className="text-xs font-medium text-muted-foreground mb-2">Faithfulness(det) trend</div>
                    <div className="h-[220px]">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={onlineQualityChartData}>
                          <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                          <XAxis dataKey="time" tick={{ fontSize: 10 }} />
                          <YAxis tick={{ fontSize: 10 }} domain={[0, 1]} />
                          <Tooltip />
                          <Line
                            type="monotone"
                            dataKey="faithfulness_det_avg"
                            stroke="hsl(var(--info))"
                            strokeWidth={2}
                            dot={false}
                          />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  </div>

                  <div className="rounded-xl border border-border/60 p-3">
                    <div className="text-xs font-medium text-muted-foreground mb-2">Chunk utilization trend</div>
                    <div className="h-[220px]">
                      <ResponsiveContainer width="100%" height="100%">
                        <LineChart data={onlineQualityChartData}>
                          <CartesianGrid strokeDasharray="3 3" opacity={0.2} />
                          <XAxis dataKey="time" tick={{ fontSize: 10 }} />
                          <YAxis tick={{ fontSize: 10 }} domain={[0, 1]} />
                          <Tooltip />
                          <Line
                            type="monotone"
                            dataKey="chunk_utilization_avg"
                            stroke="hsl(var(--primary))"
                            strokeWidth={2}
                            dot={false}
                          />
                        </LineChart>
                      </ResponsiveContainer>
                    </div>
                  </div>
                </div>

                {(onlineQuality.alerts || []).length ? (
                  <div className="rounded-xl border border-destructive/30 bg-destructive/5 p-3">
                    <div className="text-xs font-medium text-destructive mb-2">Alerts</div>
                    <div className="space-y-1 text-[11px] text-muted-foreground">
                      {(onlineQuality.alerts || []).slice(0, 6).map((a: any, idx: number) => (
                        <div key={idx} className="flex items-center justify-between gap-3">
                          <span className="font-mono text-foreground/80">{String(a.metric || '')}</span>
                          <span className="tabular-nums">
                            {String(a.value ?? '—')} &lt; {String(a.threshold ?? '—')} · samples={String(a.samples ?? '—')}
                          </span>
                        </div>
                      ))}
                    </div>
                  </div>
                ) : null}
              </>
            ) : (
              <div className="text-xs text-muted-foreground">
                未启用 Online Eval：需要 `ENABLE_METRICS_LOG=true` 且 `ONLINE_EVAL_ENABLED=true`（并产生 `event=online_eval` 记录）。
              </div>
            )}
          </CardContent>
        </Card>

        <Card className="md:col-span-2">
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-sm">RAG Prompt Preview</CardTitle>
            <div className="flex items-center gap-1">
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => runPromptPreviewProbe()}
                disabled={probeRunning}
                title="运行 prompt-preview"
                aria-label="运行 prompt-preview"
              >
                <Activity className="h-4 w-4" aria-hidden="true" />
              </Button>
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={async () => copyToClipboard(probeMetricsJson)}
                disabled={!probeMetrics}
                title="复制 metrics"
                aria-label="复制 metrics"
              >
                <Copy className="h-4 w-4" aria-hidden="true" />
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid gap-3 md:grid-cols-3">
              <div className="space-y-1.5">
                <Label htmlFor="probe-dataset-id">dataset_id（可选）</Label>
                <Input
                  id="probe-dataset-id"
                  value={probeDatasetId}
                  onChange={(e) => setProbeDatasetId(e.target.value)}
                  placeholder="e.g. 9b2f…"
                />
              </div>
              <div className="space-y-1.5 md:col-span-2">
                <Label htmlFor="probe-document-ids">document_ids（可选，逗号分隔）</Label>
                <Input
                  id="probe-document-ids"
                  value={probeDocumentIdsRaw}
                  onChange={(e) => setProbeDocumentIdsRaw(e.target.value)}
                  placeholder="e.g. 3f1a…, 8c02…"
                />
              </div>
            </div>

            <div className="space-y-1.5">
              <Label htmlFor="probe-query">query</Label>
              <Textarea
                id="probe-query"
                value={probeQuery}
                onChange={(e) => setProbeQuery(e.target.value)}
                placeholder="Ask a question that should retrieve evidence from the corpus"
              />
              <div className="flex items-center justify-between gap-3">
                <p className="text-xs text-muted-foreground">
                  这个探针调用后端 `POST /api/v1/rag/prompt-preview`（不触发 LLM），用于查看 latency + token breakdown。
                </p>
                <Button variant="outline" size="sm" onClick={() => runPromptPreviewProbe()} disabled={probeRunning}>
                  {probeRunning ? '运行中…' : 'Run'}
                </Button>
              </div>
            </div>

            <StatsGrid className="xl:grid-cols-6">
              <StatCard
                icon={Timer}
                label="Latency (client)"
                value={probeLatencyMs == null ? '-' : `${probeLatencyMs}ms`}
                color="blue"
              />
              <StatCard
                icon={Activity}
                label="Retrieval"
                value={
                  typeof probeMetrics?.retrieval_elapsed_sec === 'number'
                    ? `${probeMetrics.retrieval_elapsed_sec.toFixed(3)}s`
                    : '-'
                }
                color="teal"
              />
              <StatCard
                icon={FileSearch}
                label="Context build"
                value={
                  typeof probeMetrics?.context_build_elapsed_sec === 'number'
                    ? `${probeMetrics.context_build_elapsed_sec.toFixed(3)}s`
                    : '-'
                }
                color="gray"
              />
              <StatCard
                icon={Activity}
                label="Prompt render"
                value={
                  typeof probeMetrics?.prompt_render_elapsed_sec === 'number'
                    ? `${probeMetrics.prompt_render_elapsed_sec.toFixed(3)}s`
                    : '-'
                }
                color="gray"
              />
              <StatCard
                icon={Hash}
                label="Prompt tokens"
                value={typeof probeMetrics?.prompt_tokens === 'number' ? probeMetrics.prompt_tokens : '-'}
                color="cyan"
              />
              <StatCard
                icon={Hash}
                label="Context tokens"
                value={typeof probeMetrics?.context_tokens === 'number' ? probeMetrics.context_tokens : '-'}
                color="cyan"
              />
              <StatCard
                icon={Hash}
                label="History tokens"
                value={typeof probeMetrics?.history_tokens === 'number' ? probeMetrics.history_tokens : '-'}
                color="cyan"
              />
              <StatCard
                icon={Hash}
                label="Prompt chars"
                value={typeof probeMetrics?.prompt_chars === 'number' ? probeMetrics.prompt_chars : '-'}
                color="gray"
              />
              <StatCard
                icon={Hash}
                label="Context chars"
                value={typeof probeMetrics?.context_chars === 'number' ? probeMetrics.context_chars : '-'}
                color="gray"
              />
              <StatCard
                icon={Hash}
                label="History chars"
                value={typeof probeMetrics?.history_chars === 'number' ? probeMetrics.history_chars : '-'}
                color="gray"
              />
            </StatsGrid>

            <div className="grid gap-4 md:grid-cols-2">
              <div className="space-y-1.5">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs font-medium text-muted-foreground">Prompt Preview Metrics</p>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2"
                    onClick={async () => copyToClipboard(probeMetricsJson)}
                    disabled={!probeMetrics}
                    aria-label="复制 Prompt Preview Metrics JSON"
                  >
                    <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                    <span className="sr-only">复制 Prompt Preview Metrics JSON</span>
                  </Button>
                </div>
                <details>
                  <summary className="text-xs font-medium text-muted-foreground cursor-pointer select-none hover:text-foreground transition-colors">展开 JSON</summary>
                  <pre className="mt-2 text-xs whitespace-pre-wrap break-words max-h-[280px] overflow-auto rounded-md border border-border/60 p-3">
                    {probeMetricsJson}
                  </pre>
                </details>
              </div>
              <div className="space-y-1.5">
                <div className="flex items-center justify-between gap-2">
                  <p className="text-xs font-medium text-muted-foreground">Query For Retrieval</p>
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-7 px-2"
                    onClick={async () => copyToClipboard(String(probeResult?.query_for_retrieval || ''))}
                    disabled={!probeResult?.query_for_retrieval}
                    aria-label="复制 Query For Retrieval"
                  >
                    <Copy className="h-3.5 w-3.5" aria-hidden="true" />
                    <span className="sr-only">复制 Query For Retrieval</span>
                  </Button>
                </div>
                <pre className="text-xs whitespace-pre-wrap break-words max-h-[280px] overflow-auto rounded-md border border-border/60 p-3">
                  {String(probeResult?.query_for_retrieval || '(not run)')}
                </pre>
              </div>
	            </div>
	          </CardContent>
	        </Card>

	        <Card className="md:col-span-2">
	          <CardHeader className="flex flex-row items-center justify-between space-y-0">
	            <CardTitle className="text-sm">Embedding drift</CardTitle>
	            <div className="flex items-center gap-1">
	              <Button
	                variant="ghost"
	                size="icon"
	                className="h-8 w-8"
	                onClick={() => runEmbeddingDriftSnapshotProbe()}
	                disabled={driftRunning}
	                title="运行 embedding drift snapshot"
	                aria-label="运行 Embedding Drift Snapshot"
	              >
	                <Activity className="h-4 w-4" aria-hidden="true" />
	              </Button>
	              <Button
	                variant="ghost"
	                size="icon"
	                className="h-8 w-8"
	                onClick={async () => copyToClipboard(driftJson)}
	                disabled={!driftSnapshot}
	                title="复制 Embedding Drift Snapshot JSON"
	                aria-label="复制 Embedding Drift Snapshot JSON"
	              >
	                <Copy className="h-4 w-4" aria-hidden="true" />
	              </Button>
	            </div>
	          </CardHeader>
	          <CardContent className="space-y-4">
	            <div className="grid gap-3 md:grid-cols-4">
	              <div className="space-y-1.5 md:col-span-2">
	                <Label htmlFor="drift-dataset-id">dataset_id（可选）</Label>
	                <Input
	                  id="drift-dataset-id"
	                  value={driftDatasetId}
	                  onChange={(e) => setDriftDatasetId(e.target.value)}
	                  placeholder="e.g. 9b2f…"
	                />
	              </div>
	              <div className="space-y-1.5 md:col-span-2">
	                <Label htmlFor="drift-document-id">document_id（可选）</Label>
	                <Input
	                  id="drift-document-id"
	                  value={driftDocumentId}
	                  onChange={(e) => setDriftDocumentId(e.target.value)}
	                  placeholder="e.g. 3f1a…"
	                />
	              </div>
	              <div className="space-y-1.5">
	                <Label htmlFor="drift-sample-n">sample_n</Label>
	                <Input
	                  id="drift-sample-n"
	                  value={String(driftSampleN)}
	                  onChange={(e) => setDriftSampleN(Number.parseInt(e.target.value || '0', 10) || 0)}
	                  inputMode="numeric"
	                />
	              </div>
	              <div className="space-y-1.5">
	                <Label htmlFor="drift-threshold">drift_threshold</Label>
	                <Input
	                  id="drift-threshold"
	                  value={String(driftThreshold)}
	                  onChange={(e) => setDriftThreshold(Number(e.target.value) || 0)}
	                  inputMode="decimal"
	                />
	              </div>
	            </div>

	            <div className="flex items-center justify-between gap-3">
	              <p className="text-xs text-muted-foreground">
	                这个探针调用后端 `GET /api/v1/observability/embedding-drift/snapshot`（admin-only / PII-safe）。
	              </p>
	              <Button
	                variant="outline"
	                size="sm"
	                onClick={() => runEmbeddingDriftSnapshotProbe()}
	                disabled={driftRunning}
	              >
	                {driftRunning ? '运行中…' : 'Run'}
	              </Button>
	            </div>

	            <StatsGrid className="xl:grid-cols-6">
	              <StatCard
	                icon={Timer}
	                label="Latency (client)"
	                value={driftLatencyMs == null ? '-' : `${driftLatencyMs}ms`}
	                color="gray"
	              />
	              <StatCard
	                icon={FileSearch}
	                label="Sampled items"
	                value={
	                  typeof (driftSnapshot as any)?.sampled_items === 'number'
	                    ? (driftSnapshot as any).sampled_items
	                    : '-'
	                }
	                color="cyan"
	              />
	              <StatCard
	                icon={Timer}
	                label="Drift p95"
	                value={
	                  typeof (driftSnapshot as any)?.drift?.p95 === 'number'
	                    ? `${(driftSnapshot as any).drift.p95.toFixed(4)}`
	                    : '-'
	                }
	                color="orange"
	              />
	              <StatCard
	                icon={Timer}
	                label="Drift p99"
	                value={
	                  typeof (driftSnapshot as any)?.drift?.p99 === 'number'
	                    ? `${(driftSnapshot as any).drift.p99.toFixed(4)}`
	                    : '-'
	                }
	                color="orange"
	              />
	              <StatCard
	                icon={Hash}
	                label="Above threshold"
	                value={
	                  typeof (driftSnapshot as any)?.above_threshold?.ratio === 'number'
	                    ? `${Math.round((driftSnapshot as any).above_threshold.ratio * 100)}%`
	                    : '-'
	                }
	                color="red"
	              />
	              <StatCard
	                icon={Hash}
	                label="Space hash"
	                value={String((driftSnapshot as any)?.current_embedding_space_hash || '-')}
	                color="gray"
	              />
	            </StatsGrid>

	            <div className="space-y-1.5">
	              <div className="flex items-center justify-between gap-2">
	                <p className="text-xs font-medium text-muted-foreground">Embedding drift snapshot (JSON)</p>
	                <Button
	                  variant="ghost"
	                  size="sm"
	                  className="h-7 px-2"
	                  onClick={async () => copyToClipboard(driftJson)}
	                  disabled={!driftSnapshot}
	                  aria-label="复制 Embedding Drift Snapshot JSON"
	                >
	                  <Copy className="h-3.5 w-3.5" aria-hidden="true" />
	                  <span className="sr-only">复制 Embedding Drift Snapshot JSON</span>
	                </Button>
	              </div>
	              <details>
	                <summary className="text-xs font-medium text-muted-foreground cursor-pointer select-none hover:text-foreground transition-colors">展开 JSON</summary>
	                <pre className="mt-2 text-xs whitespace-pre-wrap break-words max-h-[280px] overflow-auto rounded-md border border-border/60 p-3">
	                  {driftJson}
	                </pre>
	              </details>
		            </div>
		          </CardContent>
		        </Card>

		        <Card className="md:col-span-2">
		          <CardHeader className="flex flex-row items-center justify-between space-y-0">
		            <CardTitle className="text-sm">Perf Suite (API)</CardTitle>
		            <div className="flex items-center gap-1">
		              <Button
		                variant="ghost"
		                size="icon"
		                className="h-8 w-8"
		                onClick={() => runPerfSuiteProbe()}
		                disabled={perfSuiteRunning}
		                title="运行 perf suite"
		                aria-label="运行 Perf Suite"
		              >
		                <Gauge className="h-4 w-4" aria-hidden="true" />
		              </Button>
		              <Button
		                variant="ghost"
		                size="icon"
		                className="h-8 w-8"
		                onClick={async () => copyToClipboard(perfSuiteJson)}
		                disabled={!perfSuiteResult}
		                title="复制 Perf Suite JSON"
		                aria-label="复制 Perf Suite JSON"
		              >
		                <Copy className="h-4 w-4" aria-hidden="true" />
		              </Button>
		            </div>
		          </CardHeader>
		          <CardContent className="space-y-4">
		            <div className="grid gap-3 md:grid-cols-4">
		              <div className="space-y-1.5">
		                <Label htmlFor="perf-suite-iters">iterations</Label>
		                <Input
		                  id="perf-suite-iters"
		                  value={String(perfSuiteIterations)}
		                  onChange={(e) => setPerfSuiteIterations(Number.parseInt(e.target.value || '0', 10) || 0)}
		                  inputMode="numeric"
		                />
		              </div>
		              <div className="space-y-1.5">
		                <Label htmlFor="perf-suite-timeout">timeout_sec</Label>
		                <Input
		                  id="perf-suite-timeout"
		                  value={String(perfSuiteTimeoutSec)}
		                  onChange={(e) => setPerfSuiteTimeoutSec(Number(e.target.value) || 0)}
		                  inputMode="decimal"
		                />
		              </div>
		            </div>

		            <div className="flex items-center justify-between gap-3">
		              <p className="text-xs text-muted-foreground">
		                这个探针调用后端 `POST /api/v1/observability/perf-suite/run`（admin-only / PII-safe），对比 baseline 做 p95/p99 回归门禁。
		              </p>
		              <Button variant="outline" size="sm" onClick={() => runPerfSuiteProbe()} disabled={perfSuiteRunning}>
		                {perfSuiteRunning ? '运行中…' : 'Run'}
		              </Button>
		            </div>

		            <StatsGrid className="xl:grid-cols-6">
		              <StatCard
		                icon={Timer}
		                label="Latency (client)"
		                value={perfSuiteLatencyMs == null ? '-' : `${perfSuiteLatencyMs}ms`}
		                color="gray"
		              />
		              <StatCard
		                icon={Activity}
		                label="Strict gate"
		                value={
		                  typeof (perfSuiteResult as any)?.diff?.strict_gate?.passed === 'boolean'
		                    ? ((perfSuiteResult as any).diff.strict_gate.passed ? 'PASSED' : 'FAILED')
		                    : '-'
		                }
		                color={
		                  typeof (perfSuiteResult as any)?.diff?.strict_gate?.passed === 'boolean'
		                    ? ((perfSuiteResult as any).diff.strict_gate.passed ? 'teal' : 'red')
		                    : 'gray'
		                }
		              />
		              <StatCard
		                icon={Hash}
		                label="Regressions"
		                value={
		                  perfSuiteResult?.diff?.strict_gate && typeof (perfSuiteResult as any).diff.strict_gate.regressions === 'number'
		                    ? (perfSuiteResult as any).diff.strict_gate.regressions
		                    : '-'
		                }
		                color="orange"
		              />
		              <StatCard
		                icon={Timer}
		                label="Baseline ts"
		                value={String((perfSuiteResult as any)?.baseline_ts || '-')}
		                color="gray"
		              />
		              <StatCard
		                icon={Timer}
		                label="Run ts"
		                value={String((perfSuiteResult as any)?.current_report?.ts || '-')}
		                color="gray"
		              />
		            </StatsGrid>

		            <div className="space-y-2">
		              <p className="text-xs font-medium text-muted-foreground">Cases (p95 / p99)</p>
		              {perfSuiteResult?.diff?.cases && typeof (perfSuiteResult as any).diff.cases === 'object' ? (
		                <div className="space-y-1">
		                  {Object.values((perfSuiteResult as any).diff.cases as Record<string, any>).map((row: any) => {
		                    const name = String(row?.name || '')
		                    const regressed = Boolean(row?.regressed)
		                    const p95 = row?.p95 && typeof row.p95 === 'object' ? row.p95 : {}
		                    const p99 = row?.p99 && typeof row.p99 === 'object' ? row.p99 : {}
		                    return (
		                      <div key={name} className="flex items-center justify-between gap-3 text-xs">
		                        <span className="min-w-0 flex-1 truncate font-mono text-muted-foreground" title={name}>
		                          {name || '(case)'}
		                        </span>
		                        <span className={`shrink-0 font-mono tabular-nums ${regressed ? 'text-destructive' : 'text-foreground/80'}`}>
		                          p95 {p95?.baseline_ms ?? '-'}→{p95?.current_ms ?? '-'} · p99 {p99?.baseline_ms ?? '-'}→{p99?.current_ms ?? '-'}
		                        </span>
		                      </div>
		                    )
		                  })}
		                </div>
		              ) : (
		                <div className="text-xs text-muted-foreground">暂无 perf suite 结果（点击 Run 触发）。</div>
		              )}
		            </div>

		            <div className="space-y-1.5">
		              <div className="flex items-center justify-between gap-2">
		                <p className="text-xs font-medium text-muted-foreground">Perf suite run + diff (JSON)</p>
		                <Button
		                  variant="ghost"
		                  size="sm"
		                  className="h-7 px-2"
		                  onClick={async () => copyToClipboard(perfSuiteJson)}
		                  disabled={!perfSuiteResult}
		                  aria-label="复制 Perf Suite JSON"
		                >
		                  <Copy className="h-3.5 w-3.5" aria-hidden="true" />
		                  <span className="sr-only">复制 Perf Suite JSON</span>
		                </Button>
		              </div>
		              <details>
		                <summary className="text-xs font-medium text-muted-foreground cursor-pointer select-none hover:text-foreground transition-colors">展开 JSON</summary>
		                <pre className="mt-2 text-xs whitespace-pre-wrap break-words max-h-[280px] overflow-auto rounded-md border border-border/60 p-3">
		                  {perfSuiteJson}
		                </pre>
		              </details>
		            </div>
		          </CardContent>
		        </Card>

		        <Card>
		          <CardHeader className="flex flex-row items-center justify-between space-y-0">
		            <CardTitle className="text-sm">Perf Snapshot</CardTitle>
		            <div className="flex items-center gap-1">
	              <Button
	                variant="ghost"
	                size="icon"
	                className="h-8 w-8"
	                onClick={() => setPerfSnapshot(takePerfSnapshot())}
	                title="重新采样"
	                aria-label="重新采样 Perf Snapshot"
	              >
	                <RefreshCcw className="h-4 w-4" />
	              </Button>
	              <Button
	                variant="ghost"
	                size="icon"
	                className="h-8 w-8"
	                onClick={async () => copyToClipboard(perfJson)}
	                title="复制 Perf Snapshot JSON"
	                aria-label="复制 Perf Snapshot JSON"
	              >
	                <Copy className="h-4 w-4" />
	              </Button>
	            </div>
	          </CardHeader>
	          <CardContent className="space-y-3">
	            <StatsGrid className="xl:grid-cols-4">
	              <StatCard
	                icon={Gauge}
	                label="TTFB"
	                value={
	                  typeof perfSnapshot?.navigation?.ttfb_ms === 'number'
	                    ? `${Math.round(perfSnapshot.navigation.ttfb_ms)}ms`
	                    : '-'
	                }
	                color="gray"
	              />
	              <StatCard
	                icon={Timer}
	                label="DCL"
	                value={
	                  typeof perfSnapshot?.navigation?.dom_content_loaded_ms === 'number'
	                    ? `${Math.round(perfSnapshot.navigation.dom_content_loaded_ms)}ms`
	                    : '-'
	                }
	                color="gray"
	              />
	              <StatCard
	                icon={Timer}
	                label="Load"
	                value={
	                  typeof perfSnapshot?.navigation?.load_ms === 'number'
	                    ? `${Math.round(perfSnapshot.navigation.load_ms)}ms`
	                    : '-'
	                }
	                color="gray"
	              />
	              <StatCard
	                icon={Package}
	                label="Scripts xfer"
	                value={
	                  perfSnapshot?.scripts
	                    ? formatFileSize(perfSnapshot.scripts.total_transfer_bytes || perfSnapshot.scripts.total_decoded_bytes || 0)
	                    : '-'
	                }
	                color="orange"
	              />
	            </StatsGrid>
	
	            <details>
	              <summary className="text-xs font-medium text-muted-foreground cursor-pointer select-none hover:text-foreground transition-colors">展开 JSON</summary>
	              <pre className="mt-2 text-xs whitespace-pre-wrap break-words max-h-[240px] overflow-auto rounded-md border border-border/60 p-3">
	                {perfJson}
	              </pre>
	            </details>
	          </CardContent>
	        </Card>

        <Card>
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-sm">Bundle Hints</CardTitle>
            <Button
              variant="ghost"
              size="icon"
              className="h-8 w-8"
              onClick={async () => copyToClipboard(prettyJson(perfSnapshot?.scripts ?? { error: 'not captured' }))}
              title="复制 Bundle Hints JSON"
              aria-label="复制 Bundle Hints JSON"
            >
              <Copy className="h-4 w-4" />
            </Button>
          </CardHeader>
          <CardContent className="space-y-2">
            <p className="text-xs text-muted-foreground">
              基于浏览器 `PerformanceResourceTiming` 的粗略统计（受缓存/跨域限制影响，可能显示为 0）。
            </p>
            {perfSnapshot?.scripts?.top?.length ? (
              <div className="space-y-2">
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <span>Top scripts</span>
                  <span className="font-mono tabular-nums">
                    {perfSnapshot.scripts.count} items ·{' '}
                    {formatFileSize(perfSnapshot.scripts.total_transfer_bytes || perfSnapshot.scripts.total_decoded_bytes || 0)}
                  </span>
                </div>
                <div className="space-y-1">
                  {perfSnapshot.scripts.top.map((row) => (
                    <div key={row.name} className="flex items-center justify-between gap-3 text-xs">
                      <span className="min-w-0 flex-1 truncate font-mono text-muted-foreground" title={row.name}>
                        {row.name}
                      </span>
                      <span className="shrink-0 font-mono tabular-nums text-foreground/80">
                        {formatFileSize(row.transfer_bytes || row.decoded_bytes || 0)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>
            ) : (
              <div className="text-xs text-muted-foreground">暂无 bundle 数据（可点 “Perf Snapshot” 重新采样）。</div>
            )}
          </CardContent>
        </Card>

        <Card className="md:col-span-2">
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-sm">Browser Storage & Cache</CardTitle>
            <div className="flex items-center gap-1">
              <StatusBadge
                status={storageCapable ? 'completed' : 'failed'}
                label={storageCapable ? 'Storage estimate available' : 'Storage estimate unavailable'}
                dense
              />
              <StatusBadge
                status={cacheLoading ? 'processing' : 'completed'}
                label={cacheLoading ? 'Gathering cache stats' : 'Cache stats ready'}
                dense
              />
              <Button
                variant="ghost"
                size="icon"
                className="h-8 w-8"
                onClick={() => {
                  void refreshStorageAndCache()
                }}
                title="刷新"
                aria-label="刷新 storage 和 cache 统计"
              >
                <RefreshCcw className="h-4 w-4" />
              </Button>
            </div>
          </CardHeader>
          <CardContent className="space-y-4">
            {shouldShowPressureWarning ? (
              <div className="flex items-start gap-2 rounded-xl border border-amber-500/40 bg-amber-500/10 p-3">
                <AlertTriangle className="mt-0.5 h-4 w-4 shrink-0 text-amber-600" />
                <div className="space-y-1 text-xs">
                  <p className="font-medium text-amber-700">Storage pressure is high.</p>
                  <p className="text-amber-700/90">
                    {pressure.reasons[0] || 'Storage is close to quota or cache footprint dominates usage.'}
                  </p>
                </div>
              </div>
            ) : null}
            <StatsGrid className="xl:grid-cols-4">
              <StatCard
                icon={Activity}
                label="Storage usage"
                value={storageEstimate?.usage != null ? formatFileSize(storageEstimate.usage) : '—'}
                subValue={storageUsageRatio != null ? fmtPercent(storageUsageRatio) : undefined}
                color="gray"
              />
              <StatCard
                icon={BarChart3}
                label="Storage quota"
                value={storageEstimate?.quota != null ? formatFileSize(storageEstimate.quota) : '—'}
                color="gray"
              />
              <StatCard
                icon={FileText}
                label="Doc content entries"
                value={docContentEntries.toLocaleString()}
                color="gray"
              />
              <StatCard
                icon={FileJson}
                label="Doc source entries"
                value={docSourceEntries.toLocaleString()}
                color="gray"
              />
            </StatsGrid>

            <div className="grid gap-3 sm:grid-cols-3">
              <div className="rounded-xl border border-border/60 bg-muted/30 p-3">
                <p className="text-xs text-muted-foreground">Pressure level</p>
                <p className="font-mono text-sm text-foreground">{pressure.level.toUpperCase()}</p>
              </div>
              <div className="rounded-xl border border-border/60 bg-muted/30 p-3">
                <p className="text-xs text-muted-foreground">Cache share of storage usage</p>
                <p className="font-mono text-sm text-foreground">{pressure.cacheShareOfUsage != null ? fmtPercent(pressure.cacheShareOfUsage) : '—'}</p>
              </div>
              <div className="rounded-xl border border-border/60 bg-muted/30 p-3">
                <p className="text-xs text-muted-foreground">Combined cache footprint</p>
                <p className="font-mono text-sm text-foreground">{formatFileSize(pressure.totalCacheBytes)}</p>
              </div>
            </div>

            <div className="grid gap-3 sm:grid-cols-2">
              <div className="rounded-xl border border-border/60 bg-muted/30 p-3">
                <p className="text-xs text-muted-foreground">Doc content payload</p>
                <p className="font-mono text-sm text-foreground">{formatFileSize(docContentSize)}</p>
                <p className="text-xs text-muted-foreground">
                  Last updated: {docContentUpdatedAt ? formatTs(docContentUpdatedAt) : '—'}
                </p>
              </div>
              <div className="rounded-xl border border-border/60 bg-muted/30 p-3">
                <p className="text-xs text-muted-foreground">Doc source payload</p>
                <p className="font-mono text-sm text-foreground">{formatFileSize(docSourceSize)}</p>
                <p className="text-xs text-muted-foreground">
                  Last updated: {docSourceUpdatedAt ? formatTs(docSourceUpdatedAt) : '—'}
                </p>
              </div>
            </div>

            <div className="flex flex-wrap items-center gap-2">
              {shouldShowCleanupCta ? (
                <Button size="sm" onClick={handlePruneStaleCaches} disabled={cleanupLoading.stale || cacheLoading}>
                  {cleanupLoading.stale ? 'Pruning stale caches...' : 'Prune stale caches (14d)'}
                </Button>
              ) : null}
              <Button
                variant="outline"
                size="sm"
                onClick={handleClearContentCache}
                disabled={cleanupLoading.content || cleanupLoading.stale || cacheLoading}
              >
                Clear doc content cache
              </Button>
              <Button
                variant="outline"
                size="sm"
                onClick={handleClearSourceCache}
                disabled={cleanupLoading.source || cleanupLoading.stale || cacheLoading}
              >
                Clear doc source cache
              </Button>
            </div>
          </CardContent>
        </Card>

        <Card className="md:col-span-2">
          <CardHeader className="flex flex-row items-center justify-between space-y-0">
            <CardTitle className="text-sm">Quick Tips</CardTitle>
	            <Button
	              variant="ghost"
	              size="icon"
	              className="h-8 w-8"
	              onClick={async () =>
	                copyToClipboard(
	                  [
	                    'Diagnostics quick tips:',
	                    '- If Backend Health/Deps Ready fail, verify API_BASE_URL and auth/tenant headers.',
	                    '- If prompt/context tokens are high, reduce chunk size, enable context denoise/dedup, and tighten dataset scope.',
	                    '- If UI feels sluggish, prefer list virtualization and avoid rendering huge markdown without need.',
	                    '- For large bundles, keep heavy deps behind next/dynamic and check build output.',
	                  ].join(String.raw`\n`)
	                )
	              }
	              title="复制 Diagnostics Quick Tips"
	              aria-label="复制 Diagnostics Quick Tips"
	            >
	              <Copy className="h-4 w-4" />
	            </Button>
	          </CardHeader>
	          <CardContent>
	            <ul className="list-disc pl-5 space-y-2 text-sm text-muted-foreground">
	              <li>
	                <span className="text-foreground/90">后端连通性</span>：先看 <span className="font-mono">Backend Health</span> 与{' '}
	                <span className="font-mono">Deps Ready</span>；异常时优先排查 <span className="font-mono">API_BASE_URL</span>、反向代理与鉴权。
	              </li>
	              <li>
	                <span className="text-foreground/90">RAG 成本</span>：如果 <span className="font-mono">prompt_tokens</span> 或{' '}
	                <span className="font-mono">context_tokens</span> 很高，优先缩小数据集范围、降低 chunk size、启用 context denoise/dedup。
	              </li>
	              <li>
	                <span className="text-foreground/90">前端卡顿</span>：大列表优先虚拟化；大 Markdown 预览尽量避免频繁重渲染（可用 memo + deferred ToC）。
	              </li>
	              <li>
	                <span className="text-foreground/90">Bundle 体积</span>：把 monaco/plotly/pdfjs 等重依赖放到 route-level 动态 import，
	                并用 build 输出定位最大的 chunk。
	              </li>
	            </ul>
	          </CardContent>
	        </Card>
	      </div>
	    </PageScaffold>
    </AppFrame>
	  )
	}
