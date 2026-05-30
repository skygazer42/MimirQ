'use client'

import { useCallback, useEffect, useMemo, useRef, useState } from 'react'
import { useParams } from 'next/navigation'
import { useInfiniteQuery, useQuery } from '@tanstack/react-query'
import { toast } from 'sonner'
import { ArrowLeft, Download, FileSearch, Loader2, RefreshCw, Settings2, Sparkles, StopCircle, Table2, Wand2 } from 'lucide-react'
import {
  Bar,
  BarChart,
  CartesianGrid,
  Cell,
  Pie,
  PieChart,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts'

import { AppFrame } from '@/components/app-frame'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { SafeResponsiveChart } from '@/components/ui/safe-responsive-chart'

import { datasetApi, sseApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { queryKeys } from '@/lib/query-keys'
import { cn, formatFileSize, formatDate, detachPromise } from '@/lib/utils'
import { useRouter } from '@/i18n/navigation'

import type {
  DatasetPrecheckFileOut,
  DatasetPrecheckFindingSummary,
  DatasetPrecheckScanRunCreateRequest,
  DatasetPrecheckScanRunOut,
  DatasetPrecheckSummary,
  IngestionPolicyImportResponse,
} from '@/types'

const PIE_COLORS = [
  'hsl(var(--chart-1))',
  'hsl(var(--chart-2))',
  'hsl(var(--chart-4))',
  'hsl(var(--chart-6))',
  'hsl(var(--chart-3))',
  'hsl(var(--chart-7))',
  'hsl(var(--chart-5))',
  'hsl(var(--chart-8))',
]

const PRECHECK_RUNS_PARAMS = { skip: 0, limit: 20 } as const
const PRECHECK_POLICY_SUGGESTION_PARAMS = { max_names_per_bucket: 50 } as const
const PRECHECK_FINDING_PAGE_SIZE = 50

function asDatasetId(raw: unknown): string | null {
  if (typeof raw === 'string' && raw.trim()) return raw
  if (Array.isArray(raw) && typeof raw[0] === 'string') return raw[0]
  return null
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob)
  const a = document.createElement('a')
  a.href = url
  a.download = filename
  a.click()
  URL.revokeObjectURL(url)
}

function findingBadgeVariant(sev: string): 'secondary' | 'outline' | 'soft' | 'destructive' {
  const s = String(sev || '').toLowerCase()
  if (s === 'error') return 'destructive'
  if (s === 'warning') return 'soft'
  return 'outline'
}

export default function DatasetPrecheckPage() {
  const router = useRouter()
  const params = useParams()
  const datasetId = asDatasetId((params as any)?.id)

  const [selectedRun, setSelectedRun] = useState<DatasetPrecheckScanRunOut | null>(null)
  const [summary, setSummary] = useState<DatasetPrecheckSummary | null>(null)

  const [scanRunning, setScanRunning] = useState(false)
  const pollTimerRef = useRef<number | null>(null)
  const sseAbortRef = useRef<AbortController | null>(null)

  const [isExporting, setIsExporting] = useState(false)
  const [advancedOpen, setAdvancedOpen] = useState(false)

  const [policyOpen, setPolicyOpen] = useState(false)
  const [policyApplying, setPolicyApplying] = useState(false)
  const [policyApplyReplace, setPolicyApplyReplace] = useState(false)

  const [scanConfig, setScanConfig] = useState<DatasetPrecheckScanRunCreateRequest>({
    root_path: '',
    max_files: null,
    enable_pdf_quality: true,
    enable_text_extract: true,
    enable_pii: false,
    enable_secrets: false,
    compute_file_hash: false,
    pdf_sample_pages: null,
    text_extract_max_bytes: null,
    redact_paths: false,
    pdf_min_text_chars_per_page: null,
    pdf_text_chars_per_page: null,
    pdf_scan_ratio_threshold: null,
    enable_pii_samples: false,
    pii_context_chars: null,
    pii_max_samples_per_file: null,
    enable_secrets_samples: false,
    secrets_context_chars: null,
    secrets_max_samples_per_file: null,
    enable_near_dup: false,
    near_dup_hamming_threshold: null,
    near_dup_max_pairs: null,
    enable_sampling: true,
    sample_size: null,
    reuse_unchanged_files: false,
    reuse_from_scan_run_id: null,
  })

  const [findingOpen, setFindingOpen] = useState(false)
  const [selectedFinding, setSelectedFinding] = useState<DatasetPrecheckFindingSummary | null>(null)

  const [fileDetailOpen, setFileDetailOpen] = useState(false)
  const [fileDetail, setFileDetail] = useState<DatasetPrecheckFileOut | null>(null)

  const [diffBaseRunId, setDiffBaseRunId] = useState<string>('')

  const stopPolling = useCallback(() => {
    const t = pollTimerRef.current
    if (t) globalThis.window.clearTimeout(t)
    pollTimerRef.current = null
  }, [])

  const stopSse = useCallback(() => {
    const ctrl = sseAbortRef.current
    if (ctrl) ctrl.abort()
    sseAbortRef.current = null
  }, [])

  const datasetQuery = useQuery({
    queryKey: queryKeys.datasets.detail(datasetId || ''),
    queryFn: () => datasetApi.get(datasetId as string),
    enabled: Boolean(datasetId),
  })

  const runsQuery = useQuery({
    queryKey: queryKeys.datasets.precheckRuns(datasetId || '', PRECHECK_RUNS_PARAMS),
    queryFn: () => datasetApi.listPrecheckScanRuns(datasetId as string, PRECHECK_RUNS_PARAMS),
    enabled: Boolean(datasetId),
  })

  const dataset = datasetQuery.data ?? null
  const runs = useMemo(() => runsQuery.data?.items || [], [runsQuery.data?.items])
  const loading = Boolean(datasetId) && (datasetQuery.isPending || runsQuery.isPending)
  const refreshing = Boolean(datasetId) && (datasetQuery.isFetching || runsQuery.isFetching)
  const selectedRunId = selectedRun?.id || ''
  const selectedFindingKey = selectedFinding?.key || ''
  const sampleSize = scanConfig.sample_size ?? undefined

  const samplesQuery = useQuery({
    queryKey: queryKeys.datasets.precheckSamples(datasetId || '', selectedRunId, {
      size: sampleSize,
      prefer_artifact: true,
    }),
    enabled: false,
    queryFn: () =>
      datasetApi.getPrecheckSamples(datasetId as string, selectedRunId, {
        size: sampleSize,
        prefer_artifact: true,
      }),
  })
  const nearDupQuery = useQuery({
    queryKey: queryKeys.datasets.precheckNearDups(datasetId || '', selectedRunId),
    enabled: false,
    queryFn: () => datasetApi.getPrecheckNearDups(datasetId as string, selectedRunId),
  })
  const diffQuery = useQuery({
    queryKey: queryKeys.datasets.precheckDiff(datasetId || '', selectedRunId, {
      base_scan_run_id: diffBaseRunId,
    }),
    enabled: false,
    queryFn: () =>
      datasetApi.diffPrecheckScanRuns(datasetId as string, selectedRunId, {
        base_scan_run_id: diffBaseRunId,
      }),
  })
  const policySuggestionQuery = useQuery({
    queryKey: queryKeys.datasets.precheckIngestionPolicySuggestion(
      datasetId || '',
      selectedRunId,
      PRECHECK_POLICY_SUGGESTION_PARAMS
    ),
    enabled: false,
    queryFn: () => {
      if (!datasetId || !selectedRunId) throw new Error('缺少预检扫描 ID')
      return datasetApi.suggestPrecheckIngestionPolicy(
        datasetId,
        selectedRunId,
        PRECHECK_POLICY_SUGGESTION_PARAMS
      )
    },
  })
  const findingItemsQuery = useInfiniteQuery({
    queryKey: queryKeys.datasets.precheckFindingFiles(
      datasetId || '',
      selectedRunId,
      selectedFindingKey,
      { limit: PRECHECK_FINDING_PAGE_SIZE }
    ),
    enabled: Boolean(datasetId && selectedRunId && selectedFindingKey && findingOpen),
    initialPageParam: 0,
    queryFn: ({ pageParam }) => {
      if (!datasetId || !selectedRunId || !selectedFindingKey) throw new Error('缺少预检清单 ID')
      return datasetApi.listPrecheckFinding(
        datasetId,
        selectedRunId,
        selectedFindingKey,
        { skip: Number(pageParam) || 0, limit: PRECHECK_FINDING_PAGE_SIZE }
      )
    },
    getNextPageParam: (lastPage, allPages) => {
      const loaded = allPages.reduce((acc, page) => acc + (page.items?.length || 0), 0)
      return loaded < (lastPage.total || 0) ? loaded : undefined
    },
  })
  const samplesLoading = samplesQuery.isFetching
  const samplesRes = samplesQuery.data ?? null
  const nearDupLoading = nearDupQuery.isFetching
  const nearDupRes = nearDupQuery.data ?? null
  const diffLoading = diffQuery.isFetching
  const diffRes = diffQuery.data ?? null
  const policyLoading = policySuggestionQuery.isFetching
  const policyRes = policySuggestionQuery.data ?? null
  const findingLoading = findingItemsQuery.isFetching
  const findingRes = useMemo(() => {
    const pages = findingItemsQuery.data?.pages || []
    if (!pages.length) return null
    const items = pages.flatMap((page) => page.items || [])
    return {
      total: pages[pages.length - 1]?.total || 0,
      items,
    }
  }, [findingItemsQuery.data])

  useEffect(() => {
    const error = datasetQuery.error || runsQuery.error
    if (!error) return
    console.error('Failed to load dataset precheck', error)
    toast.error(formatApiError(error, '加载预检页面失败'))
  }, [datasetQuery.error, datasetQuery.errorUpdatedAt, runsQuery.error, runsQuery.errorUpdatedAt])

  useEffect(() => {
    const error = findingItemsQuery.error
    if (!error) return
    console.error('Failed to load precheck finding', error)
    toast.error(formatApiError(error, '加载清单失败'))
  }, [findingItemsQuery.error, findingItemsQuery.errorUpdatedAt])

  const { refetch: refetchDataset } = datasetQuery
  const { refetch: refetchRunsQuery } = runsQuery
  const { refetch: refetchPolicySuggestion } = policySuggestionQuery
  const { fetchNextPage: fetchNextFindingPage } = findingItemsQuery

  const refreshPrecheckRuns = useCallback(async () => {
    await refetchRunsQuery()
  }, [refetchRunsQuery])

  const refreshPrecheckPage = useCallback(async () => {
    await Promise.all([refetchDataset(), refetchRunsQuery()])
  }, [refetchDataset, refetchRunsQuery])

  const refetchPrecheckQuery = useCallback(
    async (
      action: () => Promise<{ error: unknown }>,
      errorMessage: string,
      logLabel: string
    ) => {
      const { error } = await action()
      if (!error) return
      console.error(logLabel, error)
      toast.error(formatApiError(error, errorMessage))
    },
    []
  )

  useEffect(() => {
    if (!selectedRun && runs.length) {
      setSelectedRun(runs[0])
    }
  }, [runs, selectedRun])

  useEffect(() => {
    return () => {
      stopPolling()
      stopSse()
    }
  }, [stopPolling, stopSse])

  const pollRun = useCallback(
    async (datasetIdValue: string, runId: string) => {
      try {
        const next = await datasetApi.getPrecheckScanRun(datasetIdValue, runId)
        setSelectedRun(next)
        const st = String(next.status || '').toLowerCase()
        if (st === 'pending' || st === 'running') {
          pollTimerRef.current = globalThis.window.setTimeout(() => detachPromise(pollRun(datasetIdValue, runId)), 2000)
          return
        }
        setScanRunning(false)
        stopPolling()
        await refreshPrecheckRuns()
        if (st === 'completed') {
          const s = await datasetApi.getPrecheckSummary(datasetIdValue, runId)
          setSummary(s)
        } else if (next.error_message) {
          toast.error(`预检扫描失败：${next.error_message}`)
        }
      } catch (e: any) {
        console.error('Failed to poll precheck run', e)
        setScanRunning(false)
        stopPolling()
      }
    },
    [refreshPrecheckRuns, stopPolling]
  )

  const startSse = useCallback(
    (datasetIdValue: string, runId: string) => {
      stopSse()
      const ctrl = new AbortController()
      sseAbortRef.current = ctrl

      detachPromise(sseApi
        .streamPrecheckScanEvents(
          datasetIdValue,
          runId,
          (jsonStr) => {
            try {
              const obj = JSON.parse(String(jsonStr || '') || '{}')
              if (obj?.id) setSelectedRun(obj)
              const st = String(obj?.status || '').toLowerCase()
              if (st === 'completed') {
                detachPromise(datasetApi.getPrecheckSummary(datasetIdValue, runId).then(setSummary).catch(() => setSummary(null)))
              }
              if (st && st !== 'pending' && st !== 'running') {
                setScanRunning(false)
                stopSse()
                stopPolling()
                detachPromise(refreshPrecheckRuns())
              }
            } catch {
              // ignore
            }
          },
          {
            onError: (err) => {
              console.error('Precheck SSE error', err)
            },
            signal: ctrl.signal,
          }
        )
        .catch((e) => {
          console.warn('Precheck SSE unavailable; fallback to polling', e)
          stopSse()
          pollTimerRef.current = globalThis.window.setTimeout(() => {
            detachPromise(pollRun(datasetIdValue, runId))
          }, 800)
        }))
    },
    [pollRun, refreshPrecheckRuns, stopPolling, stopSse]
  )

  // When selectedRun changes, load summary (if available) and resume polling (if running).
  useEffect(() => {
    if (!datasetId || !selectedRun?.id) return
    const st = String(selectedRun.status || '').toLowerCase()
    if (st === 'pending' || st === 'running') {
      setScanRunning(true)
      startSse(datasetId, selectedRun.id)
      return
    }
    setScanRunning(false)
    stopPolling()
    stopSse()
    if (st === 'completed') {
      detachPromise(datasetApi
        .getPrecheckSummary(datasetId, selectedRun.id)
        .then(setSummary)
        .catch(() => setSummary(null)))
      return
    }
    setSummary(null)
  }, [datasetId, selectedRun, startSse, stopPolling, stopSse])

  const startScan = useCallback(async () => {
    if (!datasetId) return
    if (!scanConfig.root_path?.trim()) {
      toast.error('请输入要扫描的文件夹路径（root_path）')
      return
    }
    setScanRunning(true)
    try {
      const run = await datasetApi.startPrecheckScan(datasetId, scanConfig)
      setSelectedRun(run)
      await refreshPrecheckRuns()
      const st = String(run.status || '').toLowerCase()
      if (st === 'pending' || st === 'running') {
        startSse(datasetId, run.id)
      } else {
        setScanRunning(false)
      }
      toast.success('已启动预检扫描')
    } catch (e: any) {
      console.error('Failed to start precheck scan', e)
      toast.error(formatApiError(e, '启动预检扫描失败'))
      setScanRunning(false)
    }
  }, [datasetId, refreshPrecheckRuns, scanConfig, startSse])

  const cancelScan = useCallback(async () => {
    if (!datasetId || !selectedRun?.id) return
    setScanRunning(true)
    try {
      const run = await datasetApi.cancelPrecheckScan(datasetId, selectedRun.id)
      setSelectedRun(run)
      toast.success('已请求取消')
    } catch (e: any) {
      console.error('Failed to cancel precheck scan', e)
      toast.error(formatApiError(e, '取消失败'))
    } finally {
      setScanRunning(false)
    }
  }, [datasetId, selectedRun?.id])

  const openPolicy = useCallback(async () => {
    if (!datasetId || !selectedRunId) return
    setPolicyOpen(true)
    const { error } = await refetchPolicySuggestion()
    if (error) {
      console.error('Failed to suggest ingestion policy', error)
      toast.error(formatApiError(error, '生成入库策略失败'))
    }
  }, [datasetId, refetchPolicySuggestion, selectedRunId])

  const applyPolicy = useCallback(async () => {
    if (!datasetId || !selectedRun?.id) return
    setPolicyApplying(true)
    try {
      const res: IngestionPolicyImportResponse = await datasetApi.applyPrecheckIngestionPolicy(datasetId, selectedRun.id, {
        replace: !!policyApplyReplace,
      })
      toast.success(`已应用入库策略（rules=${res.rule_count}）`)
    } catch (e: any) {
      console.error('Failed to apply ingestion policy', e)
      toast.error(formatApiError(e, '应用失败'))
    } finally {
      setPolicyApplying(false)
    }
  }, [datasetId, policyApplyReplace, selectedRun?.id])

  const exportJson = useCallback(async () => {
    if (!datasetId || !selectedRun?.id) return
    setIsExporting(true)
    try {
      const blob = await datasetApi.exportPrecheckSummary(datasetId, selectedRun.id)
      const safe = String(dataset?.name || 'dataset').replaceAll(/[^a-zA-Z0-9_.-]+/g, '_').slice(0, 64)
      downloadBlob(blob, `${safe}.precheck.json`)
      toast.success('已导出 JSON 报告')
    } catch (e: any) {
      console.error('Failed to export precheck json', e)
      toast.error(formatApiError(e, '导出失败'))
    } finally {
      setIsExporting(false)
    }
  }, [datasetId, dataset?.name, selectedRun?.id])

  const exportHtml = useCallback(async () => {
    if (!datasetId || !selectedRun?.id) return
    setIsExporting(true)
    try {
      const blob = await datasetApi.exportPrecheckHtml(datasetId, selectedRun.id, { redact: true })
      const safe = String(dataset?.name || 'dataset').replaceAll(/[^a-zA-Z0-9_.-]+/g, '_').slice(0, 64)
      downloadBlob(blob, `${safe}.precheck.html`)
      toast.success('已导出 HTML 报告')
    } catch (e: any) {
      console.error('Failed to export precheck html', e)
      toast.error(formatApiError(e, '导出失败'))
    } finally {
      setIsExporting(false)
    }
  }, [datasetId, dataset?.name, selectedRun?.id])

  const downloadJsonObject = useCallback((obj: any, filename: string) => {
    try {
      const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' })
      downloadBlob(blob, filename)
    } catch {
      // ignore
    }
  }, [])

  const fileTypeChartData = useMemo(() => {
    const m = summary?.by_file_type || {}
    const entries = Object.entries(m)
      .map(([name, value]) => ({ name, value: Number(value || 0) }))
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
    const top = entries.slice(0, 10)
    const rest = entries.slice(10)
    const other = rest.reduce((acc, x) => acc + x.value, 0)
    if (other > 0) top.push({ name: '其他', value: other })
    return top
  }, [summary])

  const lengthHistogramData = useMemo(() => {
    return (summary?.length_histogram || []).map((b) => ({ name: b.label, value: Number(b.count || 0) }))
  }, [summary])

  const fileSizeHistogramData = useMemo(() => {
    return (summary?.file_size_histogram || []).map((b) => ({ name: b.label, value: Number(b.count || 0) }))
  }, [summary])

  const pdfScanData = useMemo(() => {
    const s = summary?.pdf_scan
    if (!s) return []
    return [
      { name: 'scanned', value: Number(s.scanned || 0) },
      { name: 'text', value: Number(s.not_scanned || 0) },
      { name: 'unknown', value: Number(s.unknown || 0) },
    ]
  }, [summary])

  const piiChartData = useMemo(() => {
    const m = summary?.pii_hits_total || {}
    return Object.entries(m)
      .map(([name, value]) => ({ name, value: Number(value || 0) }))
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 10)
  }, [summary])

  const secretsChartData = useMemo(() => {
    const m = summary?.secrets_hits_total || {}
    return Object.entries(m)
      .map(([name, value]) => ({ name, value: Number(value || 0) }))
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 10)
  }, [summary])

  const openFinding = useCallback(
    (finding: DatasetPrecheckFindingSummary) => {
      if (!datasetId || !selectedRunId) return
      setSelectedFinding(finding)
      setFindingOpen(true)
      setFileDetailOpen(false)
      setFileDetail(null)
    },
    [datasetId, selectedRunId]
  )

  const loadMoreFindingPage = useCallback(async () => {
    if (!findingItemsQuery.hasNextPage) return
    await fetchNextFindingPage()
  }, [fetchNextFindingPage, findingItemsQuery.hasNextPage])

  const latestRunStatus = selectedRun?.status
  const latestRunProgress = selectedRun?.progress ?? 0

  return (
    <AppFrame>
      <PageScaffold
        title="预检扫描（未入库）"
        badge="Precheck"
        icon={FileSearch}
        iconColor="text-info"
        description={
          <span className="text-sm text-muted-foreground">
            数据集：<span className="text-foreground font-medium">{dataset?.name || datasetId}</span> · 扫描本地文件夹，生成结构/质量画像（格式、扫描件、长度、PII/Secrets 等）
          </span>
        }
        actions={
          <div className="flex items-center gap-2">
            <Button variant="outline" className="gap-2" onClick={() => router.push('/datasets')}>
              <ArrowLeft className="w-4 h-4" />
              返回
            </Button>
            {datasetId ? (
              <Button variant="outline" className="gap-2" onClick={() => router.push(`/datasets/${datasetId}/ingestion`)}>
                <Settings2 className="w-4 h-4" />
                入库策略
              </Button>
            ) : null}
            {datasetId ? (
              <Button variant="outline" className="gap-2" onClick={() => router.push(`/datasets/${datasetId}/tables`)}>
                <Table2 className="w-4 h-4" />
                表格 / TAG
              </Button>
            ) : null}
            <Button variant="outline" className="gap-2" onClick={() => detachPromise(refreshPrecheckPage())} disabled={refreshing}>
              <RefreshCw className={cn('w-4 h-4', refreshing && 'animate-spin motion-reduce:animate-none')} />
              刷新
            </Button>
            <Button variant="outline" className="gap-2" onClick={() => setAdvancedOpen(true)}>
              <Settings2 className="w-4 h-4" />
              高级
            </Button>
            <Button variant="outline" className="gap-2" onClick={() => detachPromise(openPolicy())} disabled={!selectedRun?.id}>
              <Wand2 className="w-4 h-4" />
              生成入库策略
            </Button>
            <Button variant="outline" className="gap-2" onClick={() => detachPromise(exportJson())} disabled={isExporting || !selectedRun?.id || !summary}>
              {isExporting ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <Download className="w-4 h-4" />}
              导出 JSON
            </Button>
            <Button variant="outline" className="gap-2" onClick={() => detachPromise(exportHtml())} disabled={isExporting || !selectedRun?.id || !summary}>
              {isExporting ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <Download className="w-4 h-4" />}
              导出 HTML
            </Button>
          </div>
        }
      >
        <div className="space-y-6">
          <Panel className="p-5">
            <div className="flex items-start justify-between gap-4">
              <div className="min-w-0">
                <div className="font-semibold flex items-center gap-2">
                  启动预检扫描
                  {latestRunStatus ? (
                    <Badge variant="outline" className="font-mono text-xs">
                      {String(latestRunStatus)}
                    </Badge>
                  ) : null}
                </div>
                <div className="text-sm text-muted-foreground mt-1">
                  说明：后端需要启用 <span className="font-mono">LOCAL_SCAN_ENABLED</span> 且扫描路径需在允许的根目录内（或 uploads 下）。
                </div>
              </div>

              <div className="flex items-center gap-2">
                {scanRunning && selectedRun?.id ? (
                  <Button variant="outline" className="gap-2" onClick={() => detachPromise(cancelScan())}>
                    <StopCircle className="w-4 h-4" />
                    取消
                  </Button>
                ) : null}
                <Button className="gap-2" onClick={() => detachPromise(startScan())} disabled={scanRunning}>
                  {scanRunning ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <Sparkles className="w-4 h-4" />}
                  启动
                </Button>
              </div>
            </div>

            <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>历史扫描（选择一个 run 查看/对比）</Label>
                <Select
                  value={selectedRun?.id || ''}
                  onValueChange={(v) => {
                    const next = (runs || []).find((r) => r.id === v) || null
                    setSelectedRun(next)
                  }}
                >
                  <SelectTrigger className="w-full">
                    <SelectValue placeholder="选择 scan run" />
                  </SelectTrigger>
                  <SelectContent>
                    {(runs || []).map((r) => (
                      <SelectItem key={r.id} value={r.id}>
                        {String(r.created_at || '').slice(0, 19) || r.id} · {String(r.status || '')} · {r.progress ?? 0}%
                      </SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
              <div className="space-y-2">
                <Label>增量复用（可选）</Label>
                <div className="flex items-center justify-between gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                  <div className="text-sm text-muted-foreground">复用未变文件的上次扫描结果（要求 root_path 相同且不脱敏）</div>
                  <Switch checked={!!scanConfig.reuse_unchanged_files} onCheckedChange={(v) => setScanConfig((p) => ({ ...p, reuse_unchanged_files: !!v }))} />
                </div>
              </div>
            </div>

            <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>root_path（文件夹路径）</Label>
                <Input
                  placeholder="例如：/data/docs 或 C:\\\\docs（需容器/进程可访问）"
                  value={scanConfig.root_path || ''}
                  onChange={(e) => setScanConfig((prev) => ({ ...prev, root_path: e.target.value }))}
                />
              </div>

              <div className="space-y-2">
                <Label>最大文件数（可选）</Label>
                <Input
                  placeholder="不限"
                  value={scanConfig.max_files ?? ''}
                  onChange={(e) => {
                    const raw = e.target.value.trim()
                    if (!raw) {
                      setScanConfig((prev) => ({ ...prev, max_files: null }))
                      return
                    }
                    const n = Number(raw)
                    setScanConfig((prev) => ({ ...prev, max_files: Number.isFinite(n) ? Math.max(0, Math.floor(n)) : null }))
                  }}
                  className="font-mono"
                />
              </div>
            </div>

            <div className="mt-4 grid grid-cols-1 md:grid-cols-4 gap-4">
              <div className="flex items-center justify-between gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                <Label className="text-sm">PDF 质量</Label>
                <Switch checked={!!scanConfig.enable_pdf_quality} onCheckedChange={(v) => setScanConfig((p) => ({ ...p, enable_pdf_quality: !!v }))} />
              </div>
              <div className="flex items-center justify-between gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                <Label className="text-sm">文本抽样</Label>
                <Switch checked={!!scanConfig.enable_text_extract} onCheckedChange={(v) => setScanConfig((p) => ({ ...p, enable_text_extract: !!v }))} />
              </div>
              <div className="flex items-center justify-between gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                <Label className="text-sm">PII 检测</Label>
                <Switch checked={!!scanConfig.enable_pii} onCheckedChange={(v) => setScanConfig((p) => ({ ...p, enable_pii: !!v }))} />
              </div>
              <div className="flex items-center justify-between gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                <Label className="text-sm">Secrets 检测</Label>
                <Switch checked={!!scanConfig.enable_secrets} onCheckedChange={(v) => setScanConfig((p) => ({ ...p, enable_secrets: !!v }))} />
              </div>
            </div>

            <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="flex items-center justify-between gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                <Label className="text-sm">计算 file_sha256（重复）</Label>
                <Switch checked={!!scanConfig.compute_file_hash} onCheckedChange={(v) => setScanConfig((p) => ({ ...p, compute_file_hash: !!v }))} />
              </div>
              <div className="flex items-center justify-between gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                <Label className="text-sm">脱敏路径（分享用）</Label>
                <Switch checked={!!scanConfig.redact_paths} onCheckedChange={(v) => setScanConfig((p) => ({ ...p, redact_paths: !!v }))} />
              </div>
            </div>

            <div className="mt-4 flex items-center justify-between gap-4">
              <div className="text-sm text-muted-foreground">
                进度：{(() => {
    if (scanRunning) {
        return `${latestRunProgress || 0}%`;
    }
    else if (latestRunProgress) {
            return `${latestRunProgress}%`;
        }
        else {
            return '-';
        }
})()}
                {selectedRun?.error_message ? <span className="ml-3 text-destructive">错误：{selectedRun.error_message}</span> : null}
              </div>
            </div>
          </Panel>

          <Panel className="p-5">
            <div className="flex items-center justify-between gap-4">
              <div className="min-w-0">
                <div className="font-semibold">对比扫描结果（Diff）</div>
                <div className="text-sm text-muted-foreground mt-1">用于复盘治理成效：格式分布、问题清单、扫描件占比等的变化</div>
              </div>
              <div className="flex items-center gap-2">
                <Select value={diffBaseRunId} onValueChange={(v) => setDiffBaseRunId(v)}>
                  <SelectTrigger className="w-[320px]">
                    <SelectValue placeholder="选择 base scan run" />
                  </SelectTrigger>
                  <SelectContent>
                    {(runs || [])
                      .filter((r) => r.id !== selectedRun?.id)
                      .map((r) => (
                        <SelectItem key={`base-${r.id}`} value={r.id}>
                          {String(r.created_at || '').slice(0, 19) || r.id} · {String(r.status || '')} · {r.progress ?? 0}%
                        </SelectItem>
                      ))}
                  </SelectContent>
                </Select>
                <Button
                  variant="outline"
                  className="gap-2"
                  onClick={() =>
                    detachPromise(
                      refetchPrecheckQuery(
                        () => diffQuery.refetch(),
                        '对比失败',
                        'Failed to diff precheck runs'
                      )
                    )
                  }
                  disabled={!diffBaseRunId || diffLoading || !selectedRun?.id}
                >
                  {diffLoading ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : null}
                  计算
                </Button>
              </div>
            </div>

            {diffRes ? (
              <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
                <div className="rounded-xl border border-border/60 bg-muted/10 p-3 text-sm">
                  <div className="font-mono text-xs text-muted-foreground">total_files</div>
                  <div className="mt-1 font-mono text-lg">{diffRes.total_files.before} → {diffRes.total_files.after} (Δ {diffRes.total_files.delta})</div>
                  <div className="mt-2 font-mono text-xs text-muted-foreground">pdf_scanned</div>
                  <div className="mt-1 font-mono">{diffRes.pdf_scanned.before} → {diffRes.pdf_scanned.after} (Δ {diffRes.pdf_scanned.delta})</div>
                  <div className="mt-2 font-mono text-xs text-muted-foreground">pdf_unknown</div>
                  <div className="mt-1 font-mono">{diffRes.pdf_unknown.before} → {diffRes.pdf_unknown.after} (Δ {diffRes.pdf_unknown.delta})</div>
                </div>

                <div className="rounded-xl border border-border/60 overflow-hidden">
                  <div className="px-3 py-2 text-sm font-medium bg-muted/40">Top Findings Δ</div>
                  <div className="max-h-[220px] overflow-auto">
                    <table aria-label="预检 Top Findings 差异" className="w-full text-sm text-left">
                      <thead className="bg-muted/20 text-muted-foreground">
                        <tr>
                          <th className="px-3 py-2 font-medium">key</th>
                          <th className="px-3 py-2 font-medium">before</th>
                          <th className="px-3 py-2 font-medium">after</th>
                          <th className="px-3 py-2 font-medium">delta</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(diffRes.findings || []).slice(0, 12).map((it) => (
                          <tr key={`diff-${it.key}`} className="border-t border-border/60">
                            <td className="px-3 py-2 font-mono text-xs">{it.key}</td>
                            <td className="px-3 py-2 font-mono text-xs">{it.before}</td>
                            <td className="px-3 py-2 font-mono text-xs">{it.after}</td>
                            <td className={cn('px-3 py-2 font-mono text-xs', (() => {
    if (it.delta > 0) {
        return 'text-warning';
    }
    else if (it.delta < 0) {
            return 'text-teal-400';
        }
        else {
            return '';
        }
})())}>
                              {it.delta}
                            </td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            ) : (
              <div className="mt-4 text-sm text-muted-foreground">未计算</div>
            )}
          </Panel>

          <Panel className="p-5">
            <StatsGrid>
              <StatCard icon={FileSearch} label="文件总数" value={summary?.total_files ?? (loading ? '…' : 0)} color="cyan" />
              <StatCard icon={FileSearch} label="总大小" value={(() => {
    if (summary) {
        return formatFileSize(summary.total_size_bytes || 0);
    }
    else if (loading) {
            return '…';
        }
        else {
            return '-';
        }
})()} color="teal" />
              <StatCard icon={Sparkles} label="P50 长度" value={summary?.length_percentiles?.p50 ?? (loading ? '…' : 0)} subValue="chars" color="blue" />
              <StatCard icon={Sparkles} label="P90 长度" value={summary?.length_percentiles?.p90 ?? (loading ? '…' : 0)} subValue="chars" color="blue" />
              <StatCard icon={Sparkles} label="扫描 PDF" value={(() => {
    if (summary) {
        return `${summary.pdf_scan.scanned}/${summary.pdf_scan.scanned + summary.pdf_scan.not_scanned + summary.pdf_scan.unknown}`;
    }
    else if (loading) {
            return '…';
        }
        else {
            return '-';
        }
})()} color="orange" />
            </StatsGrid>
          </Panel>

          <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">格式分布</div>
                <div className="text-xs text-muted-foreground font-mono">{summary?.generated_at ? `updated ${formatDate(summary.generated_at)}` : ''}</div>
              </div>
              <SafeResponsiveChart>
                  <PieChart>
                    <Tooltip />
                    <Pie data={fileTypeChartData} dataKey="value" nameKey="name" innerRadius={55} outerRadius={95} paddingAngle={2}>
                      {fileTypeChartData.map((entry, idx) => (
                        <Cell key={String(entry.name ?? 'file-type')} fill={PIE_COLORS[idx % PIE_COLORS.length]} />
                      ))}
                    </Pie>
                  </PieChart>
                </SafeResponsiveChart>
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">长度分布（chars）</div>
              </div>
              <SafeResponsiveChart>
                  <BarChart data={lengthHistogramData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" fontSize={12} />
                    <YAxis allowDecimals={false} fontSize={12} />
                    <Tooltip />
                    <Bar dataKey="value" fill="hsl(var(--chart-2))" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </SafeResponsiveChart>
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">PDF 扫描占比</div>
              </div>
              <SafeResponsiveChart>
                  <PieChart>
                    <Tooltip />
                    <Pie data={pdfScanData} dataKey="value" nameKey="name" innerRadius={55} outerRadius={95} paddingAngle={2}>
                      {pdfScanData.map((entry, idx) => (
                        <Cell key={String(entry.name ?? 'pdf-scan')} fill={['#fb7185', '#38bdf8', '#94a3b8'][idx % 3]} />
                      ))}
                    </Pie>
                  </PieChart>
                </SafeResponsiveChart>
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">文件大小分布</div>
              </div>
              <SafeResponsiveChart>
                  <BarChart data={fileSizeHistogramData}>
                    <CartesianGrid strokeDasharray="3 3" />
                    <XAxis dataKey="name" fontSize={12} />
                    <YAxis allowDecimals={false} fontSize={12} />
                    <Tooltip />
                    <Bar dataKey="value" fill="hsl(var(--chart-3))" radius={[6, 6, 0, 0]} />
                  </BarChart>
                </SafeResponsiveChart>
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">PII 命中（次数）</div>
              </div>
              {piiChartData.length ? (
                <SafeResponsiveChart>
                    <BarChart data={piiChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip />
                      <Bar dataKey="value" fill="hsl(var(--chart-4))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </SafeResponsiveChart>
              ) : (
                <div className="h-[280px] flex items-center justify-center text-muted-foreground">暂无数据</div>
              )}
            </Panel>

            <Panel className="p-5">
              <div className="flex items-center justify-between mb-4">
                <div className="font-semibold">Secrets/Token 命中（次数）</div>
              </div>
              {secretsChartData.length ? (
                <SafeResponsiveChart>
                    <BarChart data={secretsChartData}>
                      <CartesianGrid strokeDasharray="3 3" />
                      <XAxis dataKey="name" fontSize={12} />
                      <YAxis allowDecimals={false} fontSize={12} />
                      <Tooltip />
                      <Bar dataKey="value" fill="hsl(var(--chart-6))" radius={[6, 6, 0, 0]} />
                    </BarChart>
                  </SafeResponsiveChart>
              ) : (
                <div className="h-[280px] flex items-center justify-center text-muted-foreground">暂无数据</div>
              )}
            </Panel>
          </div>

          <Panel className="p-5">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="font-semibold">代表性样本（抽样）</div>
                <div className="text-sm text-muted-foreground mt-1">用于售前/交付对齐范围：分层代表性 + 问题分桶样本（不会做删留决策）</div>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  className="gap-2"
                  onClick={() =>
                    detachPromise(
                      refetchPrecheckQuery(
                        () => samplesQuery.refetch(),
                        '加载样本失败',
                        'Failed to load precheck samples'
                      )
                    )
                  }
                  disabled={!selectedRun?.id || samplesLoading}
                >
                  {samplesLoading ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <FileSearch className="w-4 h-4" />}
                  加载
                </Button>
                <Button
                  variant="outline"
                  className="gap-2"
                  onClick={() => downloadJsonObject(samplesRes, `${String(dataset?.name || 'dataset').replaceAll(/[^a-zA-Z0-9_.-]+/g, '_').slice(0, 64)}.precheck.samples.json`)}
                  disabled={!samplesRes}
                >
                  <Download className="w-4 h-4" />
                  下载
                </Button>
              </div>
            </div>

            {samplesRes ? (
              <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
                <div className="rounded-xl border border-border/60 overflow-hidden">
                  <div className="px-3 py-2 text-sm font-medium bg-muted/40">代表性样本（{samplesRes.representative?.length || 0}）</div>
                  <div className="max-h-[260px] overflow-auto">
                    <table aria-label="预检代表性样本" className="w-full text-sm text-left">
                      <thead className="bg-muted/20 text-muted-foreground">
                        <tr>
                          <th className="px-3 py-2 font-medium">文件</th>
                          <th className="px-3 py-2 font-medium">类型</th>
                          <th className="px-3 py-2 font-medium">大小</th>
                        </tr>
                      </thead>
                      <tbody>
                        {(samplesRes.representative || []).map((d) => (
                          <tr key={`rep-${d.name}-${d.file_size}`} className="border-t border-border/60 hover:bg-muted/20 transition-colors">
                            <td className="px-3 py-2 font-mono text-xs">{d.name}</td>
                            <td className="px-3 py-2 font-mono text-xs">{d.file_type}</td>
                            <td className="px-3 py-2 font-mono text-xs">{formatFileSize(d.file_size || 0)}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>

                <div className="rounded-xl border border-border/60 overflow-hidden">
                  <div className="px-3 py-2 text-sm font-medium bg-muted/40">问题分桶样本</div>
                  <div className="max-h-[260px] overflow-auto">
                    <table aria-label="预检问题分桶样本" className="w-full text-sm text-left">
                      <thead className="bg-muted/20 text-muted-foreground">
                        <tr>
                          <th className="px-3 py-2 font-medium">bucket</th>
                          <th className="px-3 py-2 font-medium">count</th>
                        </tr>
                      </thead>
                      <tbody>
                        {Object.entries(samplesRes.needs_review || {}).map(([k, v]) => (
                          <tr key={`need-${k}`} className="border-t border-border/60">
                            <td className="px-3 py-2 font-mono text-xs">{k}</td>
                            <td className="px-3 py-2 font-mono text-xs">{(v || []).length}</td>
                          </tr>
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </div>
            ) : (
              <div className="mt-4 text-sm text-muted-foreground">未加载</div>
            )}
          </Panel>

          <Panel className="p-5">
            <div className="flex items-center justify-between gap-3">
              <div className="min-w-0">
                <div className="font-semibold">近重复候选（版本冲突）</div>
                <div className="text-sm text-muted-foreground mt-1">基于抽样文本 SimHash；只输出待确认列表（不做删留决策）</div>
              </div>
              <div className="flex items-center gap-2">
                <Button
                  variant="outline"
                  className="gap-2"
                  onClick={() =>
                    detachPromise(
                      refetchPrecheckQuery(
                        () => nearDupQuery.refetch(),
                        '加载近重复失败（可能未开启）',
                        'Failed to load precheck near-dups'
                      )
                    )
                  }
                  disabled={!selectedRun?.id || nearDupLoading}
                >
                  {nearDupLoading ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" /> : <FileSearch className="w-4 h-4" />}
                  加载
                </Button>
                <Button
                  variant="outline"
                  className="gap-2"
                  onClick={() => downloadJsonObject(nearDupRes, `${String(dataset?.name || 'dataset').replaceAll(/[^a-zA-Z0-9_.-]+/g, '_').slice(0, 64)}.precheck.near_dups.json`)}
                  disabled={!nearDupRes}
                >
                  <Download className="w-4 h-4" />
                  下载
                </Button>
              </div>
            </div>

            {nearDupRes ? (
              <div className="mt-4 text-sm text-muted-foreground">
                clusters={nearDupRes.clusters_returned} · pairs={nearDupRes.pairs_returned} · threshold={nearDupRes.threshold}
              </div>
            ) : (
              <div className="mt-4 text-sm text-muted-foreground">未加载（需要在扫描时开启“近重复”）</div>
            )}
          </Panel>

          <Panel className="p-5">
            <div className="flex items-center justify-between gap-4 mb-4">
              <div className="font-semibold">问题清单（可操作）</div>
              <div className="text-xs text-muted-foreground">点击卡片查看文件列表（分页）</div>
            </div>

            <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
              {(summary?.findings || []).map((f) => (
                <button
                  key={f.key}
                  type="button"
                  className={cn(
                    'text-left px-4 py-3 rounded-xl border border-border/60 bg-card/40 hover:bg-card/70 transition-colors',
                    'focus:outline-none focus:ring-2 focus:ring-primary/30'
                  )}
                  onClick={() => detachPromise(openFinding(f))}
                >
                  <div className="flex items-center justify-between gap-2">
                    <div className="font-medium truncate">{f.label}</div>
                    <Badge variant={findingBadgeVariant(f.severity)} className="font-mono text-xs">
                      {f.count}
                    </Badge>
                  </div>
                  {f.description ? <div className="mt-1 text-xs text-muted-foreground line-clamp-2">{f.description}</div> : null}
                </button>
              ))}
            </div>
          </Panel>
        </div>

        <Dialog
          open={findingOpen}
          onOpenChange={(open) => {
            setFindingOpen(open)
            if (!open) {
              setSelectedFinding(null)
            }
          }}
        >
          <DialogContent className="max-w-4xl border-border bg-background/95 shadow-strong sm:rounded-2xl">
            <DialogHeader>
              <DialogTitle className="text-xl font-bold text-foreground flex items-center gap-2">
                {selectedFinding?.label || '清单'}
                {selectedFinding ? (
                  <Badge variant={findingBadgeVariant(selectedFinding.severity)} className="font-mono text-xs">
                    {selectedFinding.count}
                  </Badge>
                ) : null}
              </DialogTitle>
              <DialogDescription className="text-muted-foreground">
                {selectedFinding?.description || '预检扫描的文件列表（不入库，不产生切片）'}
              </DialogDescription>
            </DialogHeader>

            <div className="mt-2">
              {(() => {
    if (findingLoading && !findingRes) {
        return (<div className="py-10 flex items-center justify-center text-muted-foreground">
                  <Loader2 className="w-5 h-5 animate-spin motion-reduce:animate-none mr-2"/>
                  加载中…
                </div>);
    }
    else if (findingRes) {
            return (<div className="space-y-3">
                  <div className="text-xs text-muted-foreground font-mono">
                    showing {findingRes.items.length}/{findingRes.total}
                  </div>
                  <div className="rounded-xl border border-border/60 overflow-hidden">
                    <table aria-label="预检入库建议列表" className="w-full text-sm text-left">
                      <thead className="bg-muted/40 text-muted-foreground">
                        <tr>
                          <th className="px-3 py-2 font-medium">文件</th>
                          <th className="px-3 py-2 font-medium">类型</th>
                          <th className="px-3 py-2 font-medium">大小</th>
                          <th className="px-3 py-2 font-medium">长度</th>
                          <th className="px-3 py-2 font-medium">PDF</th>
                          <th className="px-3 py-2 font-medium">表格</th>
                          <th className="px-3 py-2 font-medium">估算</th>
                        </tr>
                      </thead>
                      <tbody>
                        {findingRes.items.map((d) => (<tr key={`${d.name}-${d.file_type}-${d.file_size}`} className="border-t border-border/60 hover:bg-muted/20 transition-colors cursor-pointer" onClick={() => {
                        setFileDetail(d);
                        setFileDetailOpen(true);
                    }}>
                            <td className="px-3 py-2 font-mono text-xs">{d.name}</td>
                            <td className="px-3 py-2 font-mono text-xs">{d.file_type}</td>
                            <td className="px-3 py-2 font-mono text-xs">{formatFileSize(d.file_size || 0)}</td>
                            <td className="px-3 py-2 font-mono text-xs">{d.text_characters}</td>
                            <td className="px-3 py-2 font-mono text-xs">
                              {d.file_type === 'pdf' ? ((() => {
                    if (d.pdf_scanned === true) {
                        return 'scan';
                    }
                    else if (d.pdf_scanned === false) {
                            return 'text';
                        }
                        else {
                            return 'unknown';
                        }
                })()) : ''}
                            </td>
                            <td className="px-3 py-2 font-mono text-xs">
                              {d.spreadsheet ? `${d.spreadsheet.row_count || 0}x${d.spreadsheet.col_count || 0}` : ''}
                            </td>
                            <td className="px-3 py-2 font-mono text-xs">{d.estimated_text ? 'yes' : ''}</td>
                          </tr>))}
                      </tbody>
                    </table>
                  </div>

                  <div className="flex items-center justify-between">
                    <div className="text-xs text-muted-foreground">
                      {findingRes.items.length >= findingRes.total ? '已加载全部' : ''}
                    </div>
                    <Button variant="outline" className="gap-2" onClick={() => detachPromise(loadMoreFindingPage())} disabled={findingLoading || !findingItemsQuery.hasNextPage}>
                      {findingLoading ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none"/> : null}
                      加载更多
                    </Button>
                  </div>
                </div>);
        }
        else {
            return (<div className="py-10 text-center text-muted-foreground">暂无数据</div>);
        }
})()}
            </div>
          </DialogContent>
        </Dialog>

        <Dialog
          open={fileDetailOpen}
          onOpenChange={(open) => {
            setFileDetailOpen(open)
            if (!open) setFileDetail(null)
          }}
        >
          <DialogContent className="max-w-4xl border-border bg-background/95 shadow-strong sm:rounded-2xl">
            <DialogHeader>
              <DialogTitle className="text-xl font-bold text-foreground">文件详情</DialogTitle>
              <DialogDescription className="text-muted-foreground">{fileDetail?.name || ''}</DialogDescription>
            </DialogHeader>

            {fileDetail ? (
              <div className="space-y-3">
                <div className="rounded-xl border border-border/60 bg-muted/10 p-3 text-sm">
                  <div className="font-mono text-xs text-muted-foreground">meta</div>
                  <div className="mt-1 font-mono text-xs">
                    type={fileDetail.file_type} · size={formatFileSize(fileDetail.file_size)} · chars={fileDetail.text_characters}{' '}
                    {fileDetail.estimated_text ? '(estimated)' : ''}
                  </div>
                  {fileDetail.error_message ? <div className="mt-2 text-xs text-destructive">{fileDetail.error_message}</div> : null}
                </div>

                {fileDetail.pdf_pages ? (
                  <div className="rounded-xl border border-border/60 bg-muted/10 p-3 text-sm">
                    <div className="font-mono text-xs text-muted-foreground">pdf_pages</div>
                    <div className="mt-1 font-mono text-xs">
                      pages={fileDetail.pdf_pages.page_count} · sampled={fileDetail.pdf_pages.sampled_pages} · scanned={fileDetail.pdf_pages.scanned_pages} · text={fileDetail.pdf_pages.text_pages} · low_density={fileDetail.pdf_pages.low_density_pages} · unknown={fileDetail.pdf_pages.unknown_pages}
                    </div>
                  </div>
                ) : null}

                {fileDetail.spreadsheet ? (
                  <div className="rounded-xl border border-border/60 bg-muted/10 p-3 text-sm">
                    <div className="font-mono text-xs text-muted-foreground">spreadsheet</div>
                    <div className="mt-1 font-mono text-xs">
                      rows={fileDetail.spreadsheet.row_count} · cols={fileDetail.spreadsheet.col_count || 0} · sheets={fileDetail.spreadsheet.sheet_count} · merged_ratio={fileDetail.spreadsheet.merged_cell_ratio}
                      {(fileDetail.spreadsheet.estimated_rows || fileDetail.spreadsheet.estimated_cols) ? ' (estimated)' : ''}
                    </div>
                  </div>
                ) : null}

                <div className="rounded-xl border border-border/60 overflow-hidden">
                  <div className="px-3 py-2 text-sm font-medium bg-muted/40">findings</div>
                  <div className="p-3 font-mono text-xs">{(fileDetail.findings || []).join(', ') || '-'}</div>
                </div>

                {(fileDetail.pii_samples || []).length ? (
                  <div className="rounded-xl border border-border/60 overflow-hidden">
                    <div className="px-3 py-2 text-sm font-medium bg-muted/40">PII samples</div>
                    <pre className="p-3 text-xs overflow-auto max-h-[220px] bg-background font-mono">{JSON.stringify(fileDetail.pii_samples, null, 2)}</pre>
                  </div>
                ) : null}

                {(fileDetail.secrets_samples || []).length ? (
                  <div className="rounded-xl border border-border/60 overflow-hidden">
                    <div className="px-3 py-2 text-sm font-medium bg-muted/40">Secrets samples</div>
                    <pre className="p-3 text-xs overflow-auto max-h-[220px] bg-background font-mono">{JSON.stringify(fileDetail.secrets_samples, null, 2)}</pre>
                  </div>
                ) : null}
              </div>
            ) : (
              <div className="py-10 text-center text-muted-foreground">暂无数据</div>
            )}
          </DialogContent>
        </Dialog>

        <Dialog open={advancedOpen} onOpenChange={setAdvancedOpen}>
          <DialogContent className="max-w-3xl border-border bg-background/95 shadow-strong sm:rounded-2xl">
            <DialogHeader>
              <DialogTitle className="text-xl font-bold text-foreground">预检扫描 · 高级配置</DialogTitle>
              <DialogDescription className="text-muted-foreground">
                提示：<span className="font-mono">redact_paths</span> 会禁用 PII/Secrets 上下文样本；<span className="font-mono">reuse_unchanged_files</span> 仅在非脱敏且 root_path 相同时生效。
              </DialogDescription>
            </DialogHeader>

            <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>PDF 抽样页数（pdf_sample_pages）</Label>
                <Input
                  placeholder="默认 3"
                  value={scanConfig.pdf_sample_pages ?? ''}
                  onChange={(e) => {
                    const raw = e.target.value.trim()
                    setScanConfig((p) => ({ ...p, pdf_sample_pages: raw ? Number(raw) : null }))
                  }}
                  className="font-mono"
                />
              </div>
              <div className="space-y-2">
                <Label>文本抽样最大字节（text_extract_max_bytes）</Label>
                <Input
                  placeholder="默认 2000000"
                  value={scanConfig.text_extract_max_bytes ?? ''}
                  onChange={(e) => {
                    const raw = e.target.value.trim()
                    setScanConfig((p) => ({ ...p, text_extract_max_bytes: raw ? Number(raw) : null }))
                  }}
                  className="font-mono"
                />
              </div>
            </div>

            <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="flex items-center justify-between gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                <Label className="text-sm">近重复候选（enable_near_dup）</Label>
                <Switch checked={!!scanConfig.enable_near_dup} onCheckedChange={(v) => setScanConfig((p) => ({ ...p, enable_near_dup: !!v }))} />
              </div>
              <div className="flex items-center justify-between gap-3 p-3 rounded-lg border border-border/60 bg-muted/20">
                <Label className="text-sm">抽样清单（enable_sampling）</Label>
                <Switch checked={!!scanConfig.enable_sampling} onCheckedChange={(v) => setScanConfig((p) => ({ ...p, enable_sampling: !!v }))} />
              </div>
            </div>

            <div className="mt-3 grid grid-cols-1 md:grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>抽样数量（sample_size）</Label>
                <Input
                  placeholder="默认 60"
                  value={scanConfig.sample_size ?? ''}
                  onChange={(e) => {
                    const raw = e.target.value.trim()
                    setScanConfig((p) => ({ ...p, sample_size: raw ? Number(raw) : null }))
                  }}
                  className="font-mono"
                />
              </div>
              <div className="space-y-2">
                <Label>近重复阈值（near_dup_hamming_threshold）</Label>
                <Input
                  placeholder="默认 5"
                  value={scanConfig.near_dup_hamming_threshold ?? ''}
                  onChange={(e) => {
                    const raw = e.target.value.trim()
                    setScanConfig((p) => ({ ...p, near_dup_hamming_threshold: raw ? Number(raw) : null }))
                  }}
                  className="font-mono"
                />
              </div>
            </div>
          </DialogContent>
        </Dialog>

        <Dialog
          open={policyOpen}
           onOpenChange={(open) => {
             setPolicyOpen(open)
             if (!open) {
               setPolicyApplyReplace(false)
             }
           }}
        >
          <DialogContent className="max-w-4xl border-border bg-background/95 shadow-strong sm:rounded-2xl">
            <DialogHeader>
              <DialogTitle className="text-xl font-bold text-foreground flex items-center gap-2">
                预检 → 入库策略（建议）
                {policyLoading ? (
                  <Badge variant="outline" className="font-mono text-xs">
                    loading…
                  </Badge>
                ) : null}
              </DialogTitle>
              <DialogDescription className="text-muted-foreground">
                把预检统计转成可导入的 ingestion policy（保守规则 + 待人工复核清单；表格默认启用 TAG 自动分流：大表→SQL，小表→RAG）
              </DialogDescription>
            </DialogHeader>

            {(() => {
    if (policyLoading) {
        return (<div className="py-10 flex items-center justify-center text-muted-foreground">
                <Loader2 className="w-5 h-5 animate-spin motion-reduce:animate-none mr-2"/>
                生成中…
              </div>);
    }
    else if (policyRes) {
            return (<div className="space-y-4">
                {policyRes.notes?.length ? (<div className="rounded-xl border border-border/60 bg-muted/20 p-3 text-sm text-muted-foreground space-y-1">
                    {policyRes.notes.map((n) => (<div key={n}>- {n}</div>))}
                  </div>) : null}

                <div className="rounded-xl border border-border/60 overflow-hidden">
                  <div className="px-3 py-2 text-sm font-medium bg-muted/40">待人工复核</div>
                  <table aria-label="预检人工复核列表" className="w-full text-sm text-left">
                    <thead className="bg-muted/20 text-muted-foreground">
                      <tr>
                        <th className="px-3 py-2 font-medium">bucket</th>
                        <th className="px-3 py-2 font-medium">total</th>
                        <th className="px-3 py-2 font-medium">sample_names</th>
                      </tr>
                    </thead>
                    <tbody>
                      {(policyRes.manual_review || []).map((b) => (<tr key={b.key} className="border-t border-border/60">
                          <td className="px-3 py-2 font-mono text-xs">{b.key}</td>
                          <td className="px-3 py-2 font-mono text-xs">{b.total}</td>
                          <td className="px-3 py-2 font-mono text-xs truncate">{(b.sample_names || []).slice(0, 5).join(', ')}</td>
                        </tr>))}
                    </tbody>
                  </table>
                </div>

                <div className="rounded-xl border border-border/60 overflow-hidden">
                  <div className="px-3 py-2 text-sm font-medium bg-muted/40">Policy（JSON）</div>
                  <pre className="p-3 text-xs overflow-auto max-h-[280px] bg-background font-mono">{JSON.stringify(policyRes.policy, null, 2)}</pre>
                </div>

                <div className="flex items-center justify-between">
                  <div className="flex items-center gap-2">
                    <Checkbox checked={policyApplyReplace} onCheckedChange={(v) => setPolicyApplyReplace(!!v)}/>
                    <div className="text-sm text-muted-foreground">覆盖已有 ingestion_policy（replace=true）</div>
                  </div>
                  <div className="flex items-center gap-2">
                    <Button variant="outline" className="gap-2" onClick={() => downloadJsonObject(policyRes.policy, `${String(dataset?.name || 'dataset').replaceAll(/[^a-zA-Z0-9_.-]+/g, '_').slice(0, 64)}.ingestion_policy.suggested.json`)}>
                      <Download className="w-4 h-4"/>
                      下载
                    </Button>
                    <Button className="gap-2" onClick={() => detachPromise(applyPolicy())} disabled={policyApplying}>
                      {policyApplying ? <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none"/> : null}
                      应用到数据集
                    </Button>
                  </div>
                </div>
              </div>);
        }
        else {
            return (<div className="py-10 text-center text-muted-foreground">暂无数据</div>);
        }
})()}
          </DialogContent>
        </Dialog>
      </PageScaffold>
    </AppFrame>
  )
}
