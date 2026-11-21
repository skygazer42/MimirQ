'use client'

import { useCallback, useEffect, useLayoutEffect, useMemo, useRef, useState, useSyncExternalStore } from 'react'
import { useParams } from 'next/navigation'
import { skipToken, useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import { toast } from 'sonner'
import {
  AlertCircle,
  ArrowLeft,
  BarChart3,
  MoreHorizontal,
  Download,
  FileSearch,
  FileText,
  Heart,
  History,
  Loader2,
  Play,
  Settings2,
  StopCircle,
  Table2,
  Wand2,
} from '@/components/icons'
import { Bar, BarChart, CartesianGrid, Pie, PieChart, Tooltip, XAxis, YAxis } from 'recharts'

import { AppFrame } from '@/components/app-frame'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { ScanConfigDialog } from './scan-config-dialog'
import { PolicySuggestionSummary } from './policy-suggestion-summary'
import styles from './precheck.module.css'
import { Panel } from '@/components/ui/panel'
import { Button } from '@/components/ui/button'
import { Badge } from '@/components/ui/badge'
import { Checkbox } from '@/components/ui/checkbox'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { SafeResponsiveChart } from '@/components/ui/safe-responsive-chart'

import { datasetApi, sseApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { downloadBlob } from '@/lib/download'
import { reportClientError, reportClientWarning } from '@/lib/client-logging'
import { normalizePrecheckEmbeddingAdvisories } from '@/lib/precheck-embedding-advisories'
import { queryKeys } from '@/lib/query-keys'
import { sanitizeFilename } from '@/lib/sanitize'
import { cn, formatFileSize, formatDate, detachPromise } from '@/lib/utils'
import { useRouter } from '@/i18n/navigation'

import type {
  DatasetPrecheckFileOut,
  DatasetPrecheckFindingSummary,
  DatasetPrecheckScanRunCreateRequest,
  DatasetPrecheckScanRunOut,
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
const POLICY_APPLY_TOAST_ID = 'precheck-policy-apply'

function findingBadgeVariant(severity: string): 'secondary' | 'outline' | 'soft' | 'destructive' {
  const normalized = severity.toLowerCase()
  if (normalized === 'error') return 'destructive'
  if (normalized === 'warning') return 'soft'
  return 'outline'
}

function readStringField(value: unknown, key: string): string {
  if (!value || typeof value !== 'object') return ''
  const raw = (value as Record<string, unknown>)[key]
  return typeof raw === 'string' ? raw : ''
}

function formatPrecheckTimestamp(value?: string | null): string {
  if (!value) return '--'
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return '--'
  return date.toLocaleString('zh-CN', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
    hour12: false,
  })
}

function formatRunStatus(status?: string | null): string {
  const normalized = status?.toLowerCase()
  if (normalized === 'pending') return '排队中'
  if (normalized === 'running') return '运行中'
  if (normalized === 'completed') return '已完成'
  if (normalized === 'failed') return '失败'
  if (normalized === 'cancelled' || normalized === 'canceled') return '已取消'
  return '未启动'
}

export function isPrecheckSseAbortError(error: unknown): boolean {
  if (typeof error !== 'object' || error === null) return false
  if ('code' in error && error.code === 'ERR_CANCELED') return true
  if ('name' in error && (error.name === 'AbortError' || error.name === 'CanceledError')) return true
  return 'message' in error && typeof error.message === 'string' && error.message.trim().toLowerCase() === 'canceled'
}

export function isCurrentPrecheckSseStream(
  controller: AbortController,
  activeController: AbortController | null,
  runId: string,
  activeRunId: string | null,
): boolean {
  return activeController === controller && activeRunId === runId && !controller.signal.aborted
}

export function shouldFallbackToPrecheckPolling(
  error: unknown,
  controller: AbortController,
  activeController: AbortController | null,
  runId: string,
  activeRunId: string | null,
): boolean {
  return isCurrentPrecheckSseStream(controller, activeController, runId, activeRunId) && !isPrecheckSseAbortError(error)
}

export default function DatasetPrecheckPage() {
  const { id: datasetId } = useParams<{ id: string }>()
  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  return <DatasetPrecheckWorkspace key={JSON.stringify([datasetId, sessionKey])} datasetId={datasetId} />
}

function DatasetPrecheckWorkspace({ datasetId }: Readonly<{ datasetId: string }>) {
  const router = useRouter()
  const queryClient = useQueryClient()

  const [selectedRun, setSelectedRun] = useState<DatasetPrecheckScanRunOut | null>(null)

  const scanRunning = selectedRun?.status === 'pending' || selectedRun?.status === 'running'
  const [starting, setStarting] = useState(false)
  const [cancelling, setCancelling] = useState(false)
  const [startError, setStartError] = useState<string | null>(null)
  const [cancelError, setCancelError] = useState<string | null>(null)
  const [policyApplyError, setPolicyApplyError] = useState<{ runId: string; message: string } | null>(null)
  const [trackingError, setTrackingError] = useState<{ runId: string; message: string } | null>(null)
  const [trackingRetry, setTrackingRetry] = useState(0)
  const configTriggerRef = useRef<HTMLButtonElement | null>(null)
  const sseAbortRef = useRef<AbortController | null>(null)
  const sseRunIdRef = useRef<string | null>(null)
  const exportControllerRef = useRef<AbortController | null>(null)
  const workspaceRef = useRef({ active: true })

  useLayoutEffect(() => {
    const workspace = { active: true }
    workspaceRef.current = workspace
    return () => {
      workspace.active = false
      exportControllerRef.current?.abort()
    }
  }, [])

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

  const datasetQuery = useQuery({
    queryKey: queryKeys.datasets.detail(datasetId),
    queryFn: ({ signal }) => datasetApi.get(datasetId, { signal }),
  })

  const runsQuery = useQuery({
    queryKey: queryKeys.datasets.precheckRuns(datasetId, PRECHECK_RUNS_PARAMS),
    queryFn: ({ signal }) => datasetApi.listPrecheckScanRuns(datasetId, PRECHECK_RUNS_PARAMS, { signal }),
  })

  const dataset = datasetQuery.data ?? null
  const filenameStem = sanitizeFilename(dataset?.name ?? datasetId).slice(0, 64)
  const datasetFilename = filenameStem === '' ? datasetId : filenameStem
  const runs = runsQuery.data?.items ?? []
  const latestRun = runs[0]
  const loading = datasetQuery.isPending || runsQuery.isPending
  const selectedRunId = selectedRun?.id
  const completedRunId = selectedRun?.status === 'completed' ? selectedRun.id : undefined
  const summaryQuery = useQuery({
    queryKey: queryKeys.datasets.precheckSummary(datasetId, completedRunId),
    queryFn:
      completedRunId === undefined
        ? skipToken
        : ({ signal }) => datasetApi.getPrecheckSummary(datasetId, completedRunId, { signal }),
  })
  const summary = summaryQuery.data ?? null
  const selectedFindingKey = selectedFinding?.key
  const runSampleSize = selectedRun?.config.sample_size
  const sampleParams = { size: typeof runSampleSize === 'number' ? runSampleSize : undefined, prefer_artifact: true }

  const samplesQuery = useQuery({
    queryKey: queryKeys.datasets.precheckSamples(datasetId, selectedRunId, sampleParams),
    enabled: false,
    queryFn:
      selectedRunId === undefined
        ? skipToken
        : ({ signal }) => datasetApi.getPrecheckSamples(datasetId, selectedRunId, sampleParams, { signal }),
  })
  const nearDupQuery = useQuery({
    queryKey: queryKeys.datasets.precheckNearDups(datasetId, selectedRunId),
    enabled: false,
    queryFn:
      selectedRunId === undefined
        ? skipToken
        : ({ signal }) => datasetApi.getPrecheckNearDups(datasetId, selectedRunId, { signal }),
  })
  const compareBaseRuns = runs.filter((run) => run.id !== selectedRunId && Object.keys(run.summary).length > 0)
  const diffParams = { base_scan_run_id: diffBaseRunId }
  const canCompareRuns = selectedRunId !== undefined && compareBaseRuns.some((run) => run.id === diffBaseRunId)
  const diffQuery = useQuery({
    queryKey: queryKeys.datasets.precheckDiff(datasetId, selectedRunId, diffParams),
    enabled: false,
    queryFn: !canCompareRuns
      ? skipToken
      : ({ signal }) => datasetApi.diffPrecheckScanRuns(datasetId, selectedRunId, diffParams, { signal }),
  })
  const policySuggestionQuery = useQuery({
    queryKey: queryKeys.datasets.precheckIngestionPolicySuggestion(
      datasetId,
      selectedRunId,
      PRECHECK_POLICY_SUGGESTION_PARAMS,
    ),
    enabled: false,
    queryFn:
      selectedRunId === undefined
        ? skipToken
        : ({ signal }) =>
            datasetApi.suggestPrecheckIngestionPolicy(datasetId, selectedRunId, PRECHECK_POLICY_SUGGESTION_PARAMS, {
              signal,
            }),
  })
  const findingItemsQuery = useInfiniteQuery({
    queryKey: queryKeys.datasets.precheckFindingFiles(datasetId, selectedRunId, selectedFindingKey, {
      limit: PRECHECK_FINDING_PAGE_SIZE,
    }),
    initialPageParam: 0,
    queryFn:
      !findingOpen || selectedRunId === undefined || selectedFindingKey === undefined
        ? skipToken
        : ({ pageParam, signal }) =>
            datasetApi.listPrecheckFinding(
              datasetId,
              selectedRunId,
              selectedFindingKey,
              { skip: pageParam, limit: PRECHECK_FINDING_PAGE_SIZE },
              { signal },
            ),
    getNextPageParam: (lastPage, _pages, pageOffset) => {
      const nextOffset = pageOffset + lastPage.items.length
      return lastPage.items.length > 0 && nextOffset < lastPage.total ? nextOffset : undefined
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
  const hasSuggestedRules = Array.isArray(policyRes?.policy.rules)
  const findingLoading = findingItemsQuery.isFetching
  const findingRes = useMemo(() => {
    const pages = findingItemsQuery.data?.pages
    const lastPage = pages?.at(-1)
    if (pages === undefined || lastPage === undefined) return null
    return {
      total: lastPage.total,
      items: pages.flatMap((page) => page.items),
    }
  }, [findingItemsQuery.data])

  useEffect(() => {
    const error = datasetQuery.error || runsQuery.error
    if (!error) return
    reportClientError('Failed to load dataset precheck', error)
    toast.error(formatApiError(error, '加载预检页面失败'))
  }, [datasetQuery.error, datasetQuery.errorUpdatedAt, runsQuery.error, runsQuery.errorUpdatedAt])

  useEffect(() => {
    const error = findingItemsQuery.error
    if (!error) return
    reportClientError('Failed to load precheck finding', error)
  }, [findingItemsQuery.error, findingItemsQuery.errorUpdatedAt])

  const { refetch: refetchRunsQuery } = runsQuery
  const { fetchNextPage: fetchNextFindingPage } = findingItemsQuery

  const refreshPrecheckRuns = useCallback(async () => {
    await refetchRunsQuery()
  }, [refetchRunsQuery])

  useEffect(() => {
    if (latestRun !== undefined) {
      setSelectedRun((current) => current ?? latestRun)
    }
  }, [latestRun])

  useEffect(() => {
    if (!scanRunning || selectedRunId === undefined) return
    const workspace = workspaceRef.current
    const runId = selectedRunId
    const controller = new AbortController()
    let pollTimer: number | undefined
    sseAbortRef.current = controller
    sseRunIdRef.current = runId
    const isCurrent = () =>
      workspace.active && isCurrentPrecheckSseStream(controller, sseAbortRef.current, runId, sseRunIdRef.current)

    function acceptRun(run: DatasetPrecheckScanRunOut) {
      if (!isCurrent()) return
      setSelectedRun((current) => (current?.id === runId ? run : current))
      if (run.status !== 'pending' && run.status !== 'running') {
        controller.abort()
        void refreshPrecheckRuns()
      }
    }

    async function pollRun() {
      try {
        const run = await datasetApi.getPrecheckScanRun(datasetId, runId, { signal: controller.signal })
        acceptRun(run)
        if (isCurrent()) pollTimer = window.setTimeout(pollRun, 2000)
      } catch (error) {
        if (!isCurrent()) return
        reportClientError('Failed to poll precheck run', error)
        setTrackingError({ runId, message: formatApiError(error, '预检状态读取失败') })
      }
    }

    detachPromise(
      sseApi.streamPrecheckScanEvents(datasetId, runId, acceptRun, { signal: controller.signal }).catch((error) => {
        if (
          workspace.active &&
          shouldFallbackToPrecheckPolling(error, controller, sseAbortRef.current, runId, sseRunIdRef.current)
        ) {
          reportClientWarning('Precheck SSE unavailable; fallback to polling', error)
          pollTimer = window.setTimeout(pollRun, 800)
        }
      }),
    )

    return () => {
      controller.abort()
      window.clearTimeout(pollTimer)
      sseAbortRef.current = null
      sseRunIdRef.current = null
    }
  }, [datasetId, refreshPrecheckRuns, scanRunning, selectedRunId, trackingRetry])

  const startScan = useCallback(async () => {
    const workspace = workspaceRef.current
    if (!workspace.active || starting) return false
    if (!scanConfig.root_path.trim()) {
      setStartError('请输入 API 或 Worker 能访问的扫描目录。')
      return false
    }
    setStartError(null)
    setStarting(true)
    try {
      const run = await datasetApi.startPrecheckScan(datasetId, scanConfig)
      if (!workspace.active) return false
      setSelectedRun(run)
      void refreshPrecheckRuns()
      toast.success('已启动预检扫描')
      return true
    } catch (e: unknown) {
      if (!workspace.active) return false
      reportClientError('Failed to start precheck scan', e)
      setStartError(formatApiError(e, '启动预检扫描失败'))
      return false
    } finally {
      if (workspace.active) setStarting(false)
    }
  }, [datasetId, refreshPrecheckRuns, scanConfig, starting])

  const cancelScan = useCallback(async () => {
    const workspace = workspaceRef.current
    if (!workspace.active || selectedRunId === undefined || cancelling) return
    setCancelling(true)
    setCancelError(null)
    try {
      const run = await datasetApi.cancelPrecheckScan(datasetId, selectedRunId)
      if (!workspace.active) return
      setSelectedRun((current) => (current?.id === selectedRunId ? run : current))
      void refreshPrecheckRuns()
      toast.success('已请求取消')
    } catch (e: unknown) {
      if (!workspace.active) return
      reportClientError('Failed to cancel precheck scan', e)
      setCancelError(formatApiError(e, '取消预检失败，请重试。'))
    } finally {
      if (workspace.active) setCancelling(false)
    }
  }, [cancelling, datasetId, refreshPrecheckRuns, selectedRunId])

  function openPolicy() {
    if (selectedRunId === undefined) return
    toast.dismiss(POLICY_APPLY_TOAST_ID)
    setPolicyApplyError(null)
    setPolicyOpen(true)
    void policySuggestionQuery.refetch()
  }

  function changePolicyOpen(open: boolean) {
    setPolicyOpen(open)
    if (!open) setPolicyApplyReplace(false)
  }

  const applyPolicy = useCallback(async () => {
    const workspace = workspaceRef.current
    if (selectedRunId === undefined || !workspace.active || policyApplying) return
    const sessionKey = getAuthSessionKey()
    toast.dismiss(POLICY_APPLY_TOAST_ID)
    setPolicyApplying(true)
    setPolicyApplyError(null)
    try {
      const res: IngestionPolicyImportResponse = await datasetApi.applyPrecheckIngestionPolicy(
        datasetId,
        selectedRunId,
        {
          replace: policyApplyReplace,
        },
      )
      if (getAuthSessionKey() !== sessionKey) return
      void queryClient.invalidateQueries({ queryKey: queryKeys.datasets.ingestionPolicy(datasetId), exact: true })
      if (!workspace.active) return
      toast.success(`已应用入库策略，共 ${res.rule_count} 条规则`, { id: POLICY_APPLY_TOAST_ID })
    } catch (e: unknown) {
      if (!workspace.active || getAuthSessionKey() !== sessionKey) return
      reportClientError('Failed to apply ingestion policy', e)
      setPolicyApplyError({ runId: selectedRunId, message: formatApiError(e, '应用入库策略失败') })
    } finally {
      if (workspace.active) setPolicyApplying(false)
    }
  }, [datasetId, policyApplyReplace, policyApplying, queryClient, selectedRunId])

  async function exportReport(format: 'json' | 'html') {
    if (selectedRunId === undefined || exportControllerRef.current !== null) return
    const controller = new AbortController()
    exportControllerRef.current = controller
    setIsExporting(true)
    try {
      const options = { signal: controller.signal }
      const blob =
        format === 'json'
          ? await datasetApi.exportPrecheckSummary(datasetId, selectedRunId, options)
          : await datasetApi.exportPrecheckHtml(datasetId, selectedRunId, { redact: true }, options)
      if (controller.signal.aborted) return
      downloadBlob(`${datasetFilename}.precheck.${format}`, blob)
      toast.success(`已开始下载 ${format.toUpperCase()} 报告`)
    } catch (error) {
      if (controller.signal.aborted) return
      reportClientError('Failed to export precheck report', error)
      toast.error(formatApiError(error, '导出失败'))
    } finally {
      exportControllerRef.current = null
      if (!controller.signal.aborted) setIsExporting(false)
    }
  }

  const downloadJsonObject = useCallback((obj: unknown, filename: string) => {
    try {
      const blob = new Blob([JSON.stringify(obj, null, 2)], { type: 'application/json' })
      downloadBlob(filename, blob)
    } catch {
      toast.error('无法生成下载文件，请重试。')
    }
  }, [])

  const fileTypeChartData = useMemo(() => {
    const m = summary?.by_file_type || {}
    const entries = Object.entries(m)
      .map(([name, value]) => ({ name, value }))
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
    const top = entries.slice(0, 10)
    const rest = entries.slice(10)
    const other = rest.reduce((acc, x) => acc + x.value, 0)
    if (other > 0) top.push({ name: '其他', value: other })
    return top.map((entry, idx) => ({ ...entry, fill: PIE_COLORS[idx % PIE_COLORS.length] }))
  }, [summary])

  const lengthHistogramData = useMemo(() => {
    return (summary?.length_histogram ?? []).map((bin) => ({ name: bin.label, value: bin.count }))
  }, [summary])

  const fileSizeHistogramData = useMemo(() => {
    return (summary?.file_size_histogram ?? []).map((bin) => ({ name: bin.label, value: bin.count }))
  }, [summary])

  const pdfScanData = useMemo(() => {
    const s = summary?.pdf_scan
    if (!s) return []
    return [
      { name: '扫描版', value: s.scanned, fill: 'hsl(var(--warning))' },
      { name: '文本版', value: s.not_scanned, fill: 'hsl(var(--chart-2))' },
      { name: '未确定', value: s.unknown, fill: 'hsl(var(--muted-foreground))' },
    ]
  }, [summary])

  const piiChartData = useMemo(() => {
    const m = summary?.pii_hits_total || {}
    return Object.entries(m)
      .map(([name, value]) => ({ name, value }))
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 10)
  }, [summary])

  const secretsChartData = useMemo(() => {
    const m = summary?.secrets_hits_total || {}
    return Object.entries(m)
      .map(([name, value]) => ({ name, value }))
      .filter((x) => x.value > 0)
      .sort((a, b) => b.value - a.value)
      .slice(0, 10)
  }, [summary])

  const openFinding = useCallback(
    (finding: DatasetPrecheckFindingSummary) => {
      if (selectedRunId === undefined) return
      setSelectedFinding(finding)
      setFindingOpen(true)
      setFileDetailOpen(false)
      setFileDetail(null)
    },
    [selectedRunId],
  )

  const loadMoreFindingPage = useCallback(async () => {
    if (!findingItemsQuery.hasNextPage) return
    await fetchNextFindingPage({ cancelRefetch: false })
  }, [fetchNextFindingPage, findingItemsQuery.hasNextPage])

  const runStatus = selectedRun?.status
  const runRootPath =
    readStringField(selectedRun?.config, 'root_path') || readStringField(selectedRun?.artifacts, 'root_path')
  const runUpdatedAt = selectedRun?.updated_at || selectedRun?.created_at
  const runProgress = Math.max(0, Math.min(100, selectedRun?.progress ?? 0))
  const embeddingAdvisories = useMemo(
    () => normalizePrecheckEmbeddingAdvisories(summary?.embedding_advisories),
    [summary?.embedding_advisories],
  )
  const openConfig = () => {
    toast.dismiss(POLICY_APPLY_TOAST_ID)
    setStartError(null)
    setAdvancedOpen(true)
  }

  return (
    <AppFrame>
      <section className={styles.workspace} data-precheck-workbench>
        <header className={styles.header}>
          <Button variant="ghost" size="icon" aria-label="返回数据集" onClick={() => router.push('/datasets')}>
            <ArrowLeft />
          </Button>
          <div className={styles.titleGroup}>
            <div className={styles.heading}>
              <PageTitleIcon name="profile-discovery" />
              <h1>文档预检</h1>
            </div>
            <span className={styles.datasetContext}>
              {dataset?.name ?? (datasetQuery.isPending ? '正在读取数据集…' : '数据集读取失败')}
            </span>
          </div>
          <div className={styles.headerActions}>
            <Button
              ref={configTriggerRef}
              aria-label="新建预检"
              disabled={starting || scanRunning}
              onClick={openConfig}
            >
              {starting ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <Play />}
              <span>{starting ? '正在启动…' : '新建预检'}</span>
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" aria-label="数据集操作">
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => router.push('/datasets')}>
                  <ArrowLeft />
                  返回数据集
                </DropdownMenuItem>
                <DropdownMenuSeparator />
                <DropdownMenuItem onSelect={() => router.push(`/datasets/${datasetId}/health`)}>
                  <Heart />
                  健康概览
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => router.push(`/datasets/${datasetId}/profile`)}>
                  <BarChart3 />
                  数据画像
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => router.push(`/datasets/${datasetId}/ingestion`)}>
                  <Settings2 />
                  入库策略
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => router.push(`/datasets/${datasetId}/tables`)}>
                  <Table2 />
                  表格资产
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </header>
        <div className={styles.toolbar}>
          <div className={styles.history}>
            <History className="size-4 text-muted-foreground" />
            <Label htmlFor="precheck-run-history">历史运行</Label>
            <Select
              value={selectedRunId ?? ''}
              disabled={!runs.length || starting || cancelling}
              onValueChange={(value) => {
                const run = runs.find((item) => item.id === value)
                if (run) {
                  setSelectedRun(run)
                  setDiffBaseRunId((current) => (current === run.id ? '' : current))
                  setCancelError(null)
                  setTrackingError(null)
                  setFileDetailOpen(false)
                  setFindingOpen(false)
                }
              }}
            >
              <SelectTrigger id="precheck-run-history" aria-label="历史运行" className={styles.historyTrigger}>
                <SelectValue>
                  {selectedRun
                    ? formatPrecheckTimestamp(selectedRun.created_at)
                    : loading
                      ? '正在读取运行…'
                      : '暂无运行'}
                </SelectValue>
              </SelectTrigger>
              <SelectContent>
                {runs.map((run) => (
                  <SelectItem key={run.id} value={run.id}>
                    {formatPrecheckTimestamp(run.created_at)} · {formatRunStatus(run.status)}
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          {selectedRun ? (
            <span className={styles.runStatus} data-state={runStatus}>
              {scanRunning ? (
                <Loader2 className="size-3.5 animate-spin motion-reduce:animate-none" />
              ) : (
                <span aria-hidden="true">●</span>
              )}
              {formatRunStatus(runStatus)}
            </span>
          ) : null}
          <div className={styles.toolbarActions}>
            {scanRunning ? (
              <Button
                variant="outline"
                disabled={cancelling}
                onClick={() => {
                  void cancelScan()
                }}
              >
                {cancelling ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <StopCircle />}
                {cancelling ? '正在取消…' : '取消预检'}
              </Button>
            ) : null}
            <Button variant="ghost" disabled={!summary} onClick={openPolicy}>
              <Wand2 />
              生成策略
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="outline" aria-label="导出报告" disabled={isExporting || !summary}>
                  {isExporting ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <Download />}导出
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  onSelect={() => {
                    void exportReport('json')
                  }}
                >
                  JSON 报告
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() => {
                    void exportReport('html')
                  }}
                >
                  HTML 报告
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </div>
        </div>
        {datasetQuery.isError || runsQuery.isError ? (
          <div role="alert" className={styles.notice}>
            <span>{formatApiError(datasetQuery.error || runsQuery.error, '预检页面读取失败')}</span>
            <button
              disabled={datasetQuery.isFetching || runsQuery.isFetching}
              onClick={() => {
                void datasetQuery.refetch()
                void runsQuery.refetch()
              }}
            >
              重新读取页面
            </button>
          </div>
        ) : null}
        {cancelError ? (
          <div role="alert" className={styles.notice}>
            {cancelError}
          </div>
        ) : null}
        {scanRunning && trackingError !== null && trackingError.runId === selectedRunId && (
          <div role="alert" className={styles.notice}>
            <span>{trackingError.message}</span>
            <Button
              size="sm"
              variant="outline"
              onClick={() => {
                setTrackingError(null)
                setTrackingRetry((count) => count + 1)
              }}
            >
              重读扫描状态
            </Button>
          </div>
        )}
        {selectedRun ? (
          <div className={styles.runMeta}>
            <span>
              扫描目录 <code>{runRootPath || '未返回目录'}</code>
            </span>
            <span>
              更新时间 <time>{formatPrecheckTimestamp(runUpdatedAt)}</time>
            </span>
            <span>
              运行编号 <code>{selectedRun.id.slice(0, 8)}</code>
            </span>
            {scanRunning ? (
              <>
                <span>进度 {runProgress}%</span>
                <div
                  className={styles.progress}
                  role="progressbar"
                  aria-label="预检进度"
                  aria-valuemin={0}
                  aria-valuemax={100}
                  aria-valuenow={runProgress}
                >
                  <div style={{ width: `${runProgress}%` }} />
                </div>
              </>
            ) : null}
          </div>
        ) : null}
        <div className={styles.content}>
          {loading ? (
            <div className={styles.empty} role="status">
              <Loader2 className="animate-spin motion-reduce:animate-none" />
              <p>正在读取预检记录…</p>
            </div>
          ) : !selectedRun && !runsQuery.isError ? (
            <div className={styles.empty}>
              <FileSearch />
              <h2>还没有预检记录</h2>
              <p>选择服务可访问的文件夹，检查文件格式、文本质量和风险，再决定入库方式。</p>
              <Button variant="outline" onClick={openConfig}>
                配置首次预检
              </Button>
            </div>
          ) : selectedRun?.status === 'completed' ? (
            <>
              {summaryQuery.isError ? (
                <div className={styles.notice} role="alert">
                  <span>{formatApiError(summaryQuery.error, '报告读取失败')}</span>
                  <button
                    disabled={summaryQuery.isFetching}
                    onClick={() => {
                      void summaryQuery.refetch()
                    }}
                  >
                    重新读取报告
                  </button>
                </div>
              ) : null}
              {!summary ? (
                <div className={styles.empty} role="status">
                  <FileText />
                  <p>{summaryQuery.isError ? '本次报告暂不可用，运行记录已保留。' : '正在读取本次报告…'}</p>
                </div>
              ) : (
                <Tabs defaultValue="report" className={styles.reportTabs}>
                  <TabsList aria-label="预检报告视图" className={styles.reportTabList}>
                    <TabsTrigger value="report">质量报告</TabsTrigger>
                    <TabsTrigger value="samples">样本与近重复</TabsTrigger>
                    <TabsTrigger value="compare">运行对比</TabsTrigger>
                  </TabsList>
                  <TabsContent value="report" className={styles.tabContent}>
                    <dl className={styles.metrics}>
                      <div>
                        <dt>文件总数</dt>
                        <dd data-precheck-total>
                          {summary.total_files}
                          <small>个</small>
                        </dd>
                      </div>
                      <div>
                        <dt>文件总大小</dt>
                        <dd>{formatFileSize(summary.total_size_bytes)}</dd>
                      </div>
                      <div>
                        <dt>正文长度中位数</dt>
                        <dd>
                          {summary.length_percentiles.p50}
                          <small>字符</small>
                        </dd>
                      </div>
                      <div>
                        <dt>正文长度 P90</dt>
                        <dd>
                          {summary.length_percentiles.p90}
                          <small>字符</small>
                        </dd>
                      </div>
                      <div>
                        <dt>扫描版 PDF</dt>
                        <dd>
                          {summary.pdf_scan.scanned}
                          <small>
                            / {summary.pdf_scan.scanned + summary.pdf_scan.not_scanned + summary.pdf_scan.unknown} 个
                          </small>
                        </dd>
                      </div>
                    </dl>
                    <section className={styles.section}>
                      <div className={styles.sectionHead}>
                        <h2>问题清单</h2>
                      </div>
                      {summary.findings.length ? (
                        <div className={styles.tableScroll}>
                          <table className={styles.findings} aria-label="预检问题清单">
                            <thead>
                              <tr>
                                <th scope="col">问题与说明</th>
                                <th scope="col">级别</th>
                                <th scope="col">文件数</th>
                                <th scope="col">
                                  <span className="sr-only">操作</span>
                                </th>
                              </tr>
                            </thead>
                            <tbody>
                              {summary.findings.map((finding) => (
                                <tr key={finding.key}>
                                  <td>
                                    <span className={styles.findingName}>{finding.label}</span>
                                    {finding.description ? <p>{finding.description}</p> : null}
                                  </td>
                                  <td>
                                    <Badge
                                      variant={findingBadgeVariant(finding.severity)}
                                      className={finding.severity === 'warning' ? styles.findingWarning : undefined}
                                    >
                                      {finding.severity === 'error'
                                        ? '错误'
                                        : finding.severity === 'warning'
                                          ? '注意'
                                          : '提示'}
                                    </Badge>
                                  </td>
                                  <td className="tabular-nums">{finding.count}</td>
                                  <td>
                                    <Button
                                      variant="ghost"
                                      size="sm"
                                      aria-label={`查看${finding.label}文件`}
                                      onClick={() => openFinding(finding)}
                                    >
                                      查看文件
                                    </Button>
                                  </td>
                                </tr>
                              ))}
                            </tbody>
                          </table>
                        </div>
                      ) : (
                        <p>当前报告没有问题条目。</p>
                      )}
                    </section>
                    {embeddingAdvisories.length > 0 ? (
                      <Panel variant="seamless" className={styles.section}>
                        <div className="flex items-start gap-3">
                          <div className="flex size-9 shrink-0 items-center justify-center rounded-2xl border border-warning/30 bg-warning/10 text-warning">
                            <AlertCircle className="size-4" />
                          </div>
                          <div className="min-w-0 flex-1 space-y-3">
                            <div>
                              <div className="text-sm font-semibold text-foreground">Embedding 建议</div>
                              <div className="mt-1 text-[12px] leading-5 text-muted-foreground">
                                根据本次报告检查向量模型，模型配置不会自动变更。
                              </div>
                            </div>
                            <div className="space-y-2">
                              {embeddingAdvisories.map((advisory) => (
                                <div
                                  key={`${advisory.code}-${advisory.effectiveEmbedding || 'none'}`}
                                  className="border-t border-border py-3"
                                >
                                  <div className="flex flex-wrap items-center gap-2">
                                    <Badge variant="soft" className="border-warning/20 bg-warning/10 text-warning">
                                      注意
                                    </Badge>
                                    <div className="text-[13px] font-semibold text-foreground">{advisory.title}</div>
                                    <div className="font-mono text-[11px] text-muted-foreground">
                                      code={advisory.code}
                                    </div>
                                  </div>
                                  <div className="mt-2 grid gap-2 text-[12px] leading-5 text-muted-foreground md:grid-cols-2">
                                    <div>
                                      <span className="font-medium text-foreground">当前模型：</span>
                                      {advisory.effectiveEmbedding || '未返回'}
                                    </div>
                                    <div>
                                      <span className="font-medium text-foreground">建议动作：</span>
                                      {advisory.recommendedAction || '未返回'}
                                    </div>
                                  </div>
                                  {advisory.recommendedModelIds.length > 0 ? (
                                    <div className="mt-2 flex flex-wrap gap-1.5">
                                      {advisory.recommendedModelIds.map((modelId) => (
                                        <Badge key={modelId} variant="outline" className="font-mono text-[11px]">
                                          {modelId}
                                        </Badge>
                                      ))}
                                    </div>
                                  ) : null}
                                </div>
                              ))}
                            </div>
                          </div>
                        </div>
                      </Panel>
                    ) : null}

                    <div className={styles.charts}>
                      <Panel variant="seamless" className={styles.section}>
                        <div className="flex items-center justify-between mb-4">
                          <h2>格式分布</h2>
                          <div className="text-xs text-muted-foreground font-mono">
                            {summary?.generated_at ? `更新于 ${formatDate(summary.generated_at)}` : ''}
                          </div>
                        </div>
                        <SafeResponsiveChart>
                          <PieChart>
                            <Tooltip
                              contentStyle={{
                                backgroundColor: 'hsl(var(--popover))',
                                borderColor: 'hsl(var(--border))',
                                color: 'hsl(var(--popover-foreground))',
                              }}
                              itemStyle={{ color: 'hsl(var(--popover-foreground))' }}
                            />
                            <Pie
                              isAnimationActive={false}
                              data={fileTypeChartData}
                              dataKey="value"
                              nameKey="name"
                              innerRadius={55}
                              outerRadius={95}
                              paddingAngle={2}
                            />
                          </PieChart>
                        </SafeResponsiveChart>
                        <div className={styles.chartLegend}>
                          {fileTypeChartData.map((item) => (
                            <span key={item.name}>
                              <i style={{ background: item.fill }} />
                              {item.name.toUpperCase()}
                              <strong>{item.value}</strong>
                            </span>
                          ))}
                        </div>
                      </Panel>

                      <Panel variant="seamless" className={styles.section}>
                        <div className="flex items-center justify-between mb-4">
                          <div className="font-semibold">正文长度分布（字符）</div>
                        </div>
                        <SafeResponsiveChart>
                          <BarChart data={lengthHistogramData}>
                            <CartesianGrid strokeDasharray="3 3" />
                            <XAxis dataKey="name" fontSize={12} />
                            <YAxis allowDecimals={false} fontSize={12} />
                            <Tooltip
                              contentStyle={{
                                backgroundColor: 'hsl(var(--popover))',
                                borderColor: 'hsl(var(--border))',
                                color: 'hsl(var(--popover-foreground))',
                              }}
                              itemStyle={{ color: 'hsl(var(--popover-foreground))' }}
                            />
                            <Bar
                              isAnimationActive={false}
                              dataKey="value"
                              fill="hsl(var(--chart-2))"
                              radius={[6, 6, 0, 0]}
                            />
                          </BarChart>
                        </SafeResponsiveChart>
                      </Panel>

                      <Panel variant="seamless" className={styles.section}>
                        <div className="flex items-center justify-between mb-4">
                          <h2>PDF 类型分布</h2>
                        </div>
                        <SafeResponsiveChart>
                          <PieChart>
                            <Tooltip
                              contentStyle={{
                                backgroundColor: 'hsl(var(--popover))',
                                borderColor: 'hsl(var(--border))',
                                color: 'hsl(var(--popover-foreground))',
                              }}
                              itemStyle={{ color: 'hsl(var(--popover-foreground))' }}
                            />
                            <Pie
                              isAnimationActive={false}
                              data={pdfScanData}
                              dataKey="value"
                              nameKey="name"
                              innerRadius={55}
                              outerRadius={95}
                              paddingAngle={2}
                            />
                          </PieChart>
                        </SafeResponsiveChart>
                        <div className={styles.chartLegend}>
                          {pdfScanData.map((item) => (
                            <span key={item.name}>
                              <i style={{ background: item.fill }} />
                              {item.name}
                              <strong>{item.value}</strong>
                            </span>
                          ))}
                        </div>
                      </Panel>

                      <Panel variant="seamless" className={styles.section}>
                        <div className="flex items-center justify-between mb-4">
                          <div className="font-semibold">文件大小分布</div>
                        </div>
                        <SafeResponsiveChart>
                          <BarChart data={fileSizeHistogramData}>
                            <CartesianGrid strokeDasharray="3 3" />
                            <XAxis dataKey="name" fontSize={12} />
                            <YAxis allowDecimals={false} fontSize={12} />
                            <Tooltip
                              contentStyle={{
                                backgroundColor: 'hsl(var(--popover))',
                                borderColor: 'hsl(var(--border))',
                                color: 'hsl(var(--popover-foreground))',
                              }}
                              itemStyle={{ color: 'hsl(var(--popover-foreground))' }}
                            />
                            <Bar
                              isAnimationActive={false}
                              dataKey="value"
                              fill="hsl(var(--chart-3))"
                              radius={[6, 6, 0, 0]}
                            />
                          </BarChart>
                        </SafeResponsiveChart>
                      </Panel>

                      <Panel variant="seamless" className={styles.section}>
                        <div className="flex items-center justify-between mb-4">
                          <div className="font-semibold">个人信息命中（次数）</div>
                        </div>
                        {piiChartData.length ? (
                          <SafeResponsiveChart>
                            <BarChart data={piiChartData}>
                              <CartesianGrid strokeDasharray="3 3" />
                              <XAxis dataKey="name" fontSize={12} />
                              <YAxis allowDecimals={false} fontSize={12} />
                              <Tooltip
                                contentStyle={{
                                  backgroundColor: 'hsl(var(--popover))',
                                  borderColor: 'hsl(var(--border))',
                                  color: 'hsl(var(--popover-foreground))',
                                }}
                                itemStyle={{ color: 'hsl(var(--popover-foreground))' }}
                              />
                              <Bar
                                isAnimationActive={false}
                                dataKey="value"
                                fill="hsl(var(--chart-4))"
                                radius={[6, 6, 0, 0]}
                              />
                            </BarChart>
                          </SafeResponsiveChart>
                        ) : (
                          <div className={styles.chartEmpty}>报告未返回命中项</div>
                        )}
                      </Panel>

                      <Panel variant="seamless" className={styles.section}>
                        <div className="flex items-center justify-between mb-4">
                          <div className="font-semibold">密钥命中（次数）</div>
                        </div>
                        {secretsChartData.length ? (
                          <SafeResponsiveChart>
                            <BarChart data={secretsChartData}>
                              <CartesianGrid strokeDasharray="3 3" />
                              <XAxis dataKey="name" fontSize={12} />
                              <YAxis allowDecimals={false} fontSize={12} />
                              <Tooltip
                                contentStyle={{
                                  backgroundColor: 'hsl(var(--popover))',
                                  borderColor: 'hsl(var(--border))',
                                  color: 'hsl(var(--popover-foreground))',
                                }}
                                itemStyle={{ color: 'hsl(var(--popover-foreground))' }}
                              />
                              <Bar
                                isAnimationActive={false}
                                dataKey="value"
                                fill="hsl(var(--chart-6))"
                                radius={[6, 6, 0, 0]}
                              />
                            </BarChart>
                          </SafeResponsiveChart>
                        ) : (
                          <div className={styles.chartEmpty}>报告未返回命中项</div>
                        )}
                      </Panel>
                    </div>
                  </TabsContent>
                  <TabsContent value="samples" className={styles.tabContent}>
                    {' '}
                    <Panel variant="seamless" className={styles.section}>
                      <div className={styles.sectionHead}>
                        <div className="min-w-0">
                          <h2>代表性样本</h2>
                        </div>
                        <div className="flex items-center gap-2">
                          <Button
                            variant="outline"
                            className="gap-2"
                            onClick={() => {
                              void samplesQuery.refetch()
                            }}
                            disabled={!selectedRun?.id || samplesLoading}
                          >
                            {samplesLoading ? (
                              <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" />
                            ) : (
                              <FileSearch className="w-4 h-4" />
                            )}
                            加载
                          </Button>
                          <Button
                            variant="outline"
                            className="gap-2"
                            onClick={() =>
                              downloadJsonObject(
                                samplesRes,
                                `${(dataset?.name || 'dataset')
                                  .replaceAll(/[^a-zA-Z0-9_.-]+/g, '_')
                                  .slice(0, 64)}.precheck.samples.json`,
                              )
                            }
                            disabled={!samplesRes}
                          >
                            <Download className="w-4 h-4" />
                            下载
                          </Button>
                        </div>
                      </div>

                      {samplesQuery.isError && (
                        <p role="alert" className={styles.notice}>
                          {formatApiError(samplesQuery.error, '样本读取失败，请重试。')}
                        </p>
                      )}
                      {samplesRes ? (
                        <div className="mt-4 grid grid-cols-1 lg:grid-cols-2 gap-4">
                          <div className={styles.tableScroll}>
                            <div className="px-3 py-2 text-sm font-medium bg-muted/40">
                              代表性样本（{samplesRes.representative?.length || 0}）
                            </div>
                            <div className="max-h-[260px] overflow-auto">
                              <table
                                aria-label="预检代表性样本"
                                className={cn('w-full text-sm text-left', styles.sampleTable)}
                              >
                                <thead className="bg-muted/20 text-muted-foreground">
                                  <tr>
                                    <th className="px-3 py-2 font-medium">文件</th>
                                    <th className="px-3 py-2 font-medium">类型</th>
                                    <th className="px-3 py-2 font-medium">大小</th>
                                  </tr>
                                </thead>
                                <tbody>
                                  {(samplesRes.representative || []).map((d) => (
                                    <tr
                                      key={`rep-${d.name}-${d.file_size}`}
                                      className="border-t border-border/60 hover:bg-muted/20 transition-colors"
                                    >
                                      <td className="px-3 py-2 font-mono text-xs">{d.name}</td>
                                      <td className="px-3 py-2 font-mono text-xs">{d.file_type}</td>
                                      <td className="px-3 py-2 font-mono text-xs">
                                        {formatFileSize(d.file_size || 0)}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </div>

                          <div className={styles.tableScroll}>
                            <div className="px-3 py-2 text-sm font-medium bg-muted/40">问题分桶样本</div>
                            <div className="max-h-[260px] overflow-auto">
                              <table
                                aria-label="预检问题分桶样本"
                                className={cn('w-full text-sm text-left', styles.sampleTable)}
                              >
                                <thead className="bg-muted/20 text-muted-foreground">
                                  <tr>
                                    <th className="px-3 py-2 font-medium">问题分组</th>
                                    <th className="px-3 py-2 font-medium">文件数</th>
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
                      ) : !samplesQuery.isError ? (
                        <div className="mt-4 text-[11px] text-muted-foreground/65">尚未读取样本</div>
                      ) : null}
                    </Panel>
                    <Panel variant="seamless" className={styles.section}>
                      <div className={styles.sectionHead}>
                        <div className="min-w-0">
                          <div className="font-semibold">近重复候选（版本冲突）</div>
                          <div className="mt-1 text-[11px] leading-4 text-muted-foreground/65">
                            根据抽样正文查找相似文件，保留人工确认。
                          </div>
                        </div>
                        <div className="flex items-center gap-2">
                          <Button
                            variant="outline"
                            className="gap-2"
                            onClick={() => {
                              void nearDupQuery.refetch()
                            }}
                            disabled={!selectedRun?.id || nearDupLoading}
                          >
                            {nearDupLoading ? (
                              <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" />
                            ) : (
                              <FileSearch className="w-4 h-4" />
                            )}
                            加载
                          </Button>
                          <Button
                            variant="outline"
                            className="gap-2"
                            onClick={() =>
                              downloadJsonObject(
                                nearDupRes,
                                `${(dataset?.name || 'dataset')
                                  .replaceAll(/[^a-zA-Z0-9_.-]+/g, '_')
                                  .slice(0, 64)}.precheck.near_dups.json`,
                              )
                            }
                            disabled={!nearDupRes}
                          >
                            <Download className="w-4 h-4" />
                            下载
                          </Button>
                        </div>
                      </div>

                      {nearDupQuery.isError && (
                        <p role="alert" className={styles.notice}>
                          {formatApiError(nearDupQuery.error, '近重复候选读取失败，请重试。')}
                        </p>
                      )}
                      {nearDupRes ? (
                        <div className="mt-4 text-[11px] text-muted-foreground/65">
                          候选分组 {nearDupRes.clusters_returned} · 相似对 {nearDupRes.pairs_returned} · 阈值{' '}
                          {nearDupRes.threshold}
                        </div>
                      ) : !nearDupQuery.isError ? (
                        <div className="mt-4 text-[11px] text-muted-foreground/65">
                          尚未读取候选，扫描时需要启用近重复检测。
                        </div>
                      ) : null}
                    </Panel>
                  </TabsContent>
                  <TabsContent value="compare" className={styles.tabContent}>
                    {' '}
                    <Panel variant="seamless" className={styles.section}>
                      <div className={styles.comparisonHead}>
                        <div className="min-w-0">
                          <div className="font-semibold">对比两次预检</div>
                          <div className="mt-1 text-[11px] leading-4 text-muted-foreground/65">
                            对照文件数量、扫描版 PDF 和问题条目的变化。
                          </div>
                        </div>
                        <div className={styles.comparisonControls}>
                          <Select value={diffBaseRunId} onValueChange={(v) => setDiffBaseRunId(v)}>
                            <SelectTrigger aria-label="选择对比运行">
                              <SelectValue placeholder="选择对比运行" />
                            </SelectTrigger>
                            <SelectContent>
                              {compareBaseRuns.map((r) => (
                                <SelectItem key={`base-${r.id}`} value={r.id}>
                                  {formatPrecheckTimestamp(r.created_at)} · {formatRunStatus(r.status)}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                          <Button
                            variant="outline"
                            className="gap-2"
                            onClick={() => {
                              void diffQuery.refetch()
                            }}
                            disabled={!canCompareRuns || diffLoading}
                          >
                            {diffLoading ? (
                              <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" />
                            ) : null}
                            开始对比
                          </Button>
                        </div>
                      </div>

                      {diffQuery.isError && (
                        <p role="alert" className={styles.notice}>
                          {formatApiError(diffQuery.error, '对比读取失败，请重试。')}
                        </p>
                      )}
                      {diffRes ? (
                        <div className="mt-4 grid grid-cols-1 md:grid-cols-2 gap-4">
                          <div className="py-3 text-sm">
                            <div className="font-mono text-xs text-muted-foreground">文件总数</div>
                            <div className="mt-1 font-mono text-lg">
                              {diffRes.total_files.before} → {diffRes.total_files.after} (Δ {diffRes.total_files.delta})
                            </div>
                            <div className="mt-2 font-mono text-xs text-muted-foreground">扫描版 PDF</div>
                            <div className="mt-1 font-mono">
                              {diffRes.pdf_scanned.before} → {diffRes.pdf_scanned.after} (Δ {diffRes.pdf_scanned.delta})
                            </div>
                            <div className="mt-2 font-mono text-xs text-muted-foreground">类型未确定的 PDF</div>
                            <div className="mt-1 font-mono">
                              {diffRes.pdf_unknown.before} → {diffRes.pdf_unknown.after} (Δ {diffRes.pdf_unknown.delta})
                            </div>
                          </div>

                          <div className={styles.tableScroll}>
                            <div className="px-3 py-2 text-sm font-medium bg-muted/40">问题条目变化</div>
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
                                      <td
                                        className={cn(
                                          'px-3 py-2 font-mono text-xs',
                                          (() => {
                                            if (it.delta > 0) {
                                              return 'text-warning'
                                            } else if (it.delta < 0) {
                                              return 'text-success'
                                            } else {
                                              return ''
                                            }
                                          })(),
                                        )}
                                      >
                                        {it.delta}
                                      </td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>
                          </div>
                        </div>
                      ) : !diffQuery.isError ? (
                        <p className="mt-4">选择另一次运行后开始对比。</p>
                      ) : null}
                    </Panel>
                  </TabsContent>
                </Tabs>
              )}
            </>
          ) : selectedRun ? (
            <div className={styles.empty}>
              {scanRunning ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <FileSearch />}
              <h2>{scanRunning ? '正在检查文件' : formatRunStatus(selectedRun.status)}</h2>
              <p>
                {selectedRun.error_message ||
                  (scanRunning
                    ? '此运行结束后会显示质量报告。可以稍后从历史运行继续查看。'
                    : '此次运行没有可读取的完整报告。')}
              </p>
            </div>
          ) : null}
        </div>
        <ScanConfigDialog
          open={advancedOpen}
          onOpenChange={setAdvancedOpen}
          config={scanConfig}
          setConfig={setScanConfig}
          starting={starting}
          error={startError}
          onStart={startScan}
          triggerRef={configTriggerRef}
        />
        <Dialog
          open={findingOpen}
          onOpenChange={(open) => {
            setFindingOpen(open)
            if (!open) {
              setSelectedFinding(null)
              setFileDetailOpen(false)
              setFileDetail(null)
            }
          }}
        >
          <DialogContent className={styles.reportDialog}>
            <DialogHeader className={styles.dialogHeader}>
              <DialogTitle>{fileDetailOpen ? '文件详情' : selectedFinding?.label || '问题清单'}</DialogTitle>
              <DialogDescription>
                {fileDetailOpen ? fileDetail?.name : selectedFinding?.description || '查看本次预检关联的文件。'}
              </DialogDescription>
            </DialogHeader>
            <div className={styles.dialogBody}>
              {fileDetailOpen ? (
                <>
                  <Button variant="ghost" className="mb-3" onClick={() => setFileDetailOpen(false)}>
                    <ArrowLeft />
                    返回问题清单
                  </Button>{' '}
                  {fileDetail ? (
                    <div className="space-y-3">
                      <div className="border-b border-border py-3 text-sm">
                        <div className="font-mono text-xs text-muted-foreground">meta</div>
                        <div className="mt-1 font-mono text-xs">
                          type={fileDetail.file_type} · size={formatFileSize(fileDetail.file_size)} · chars=
                          {fileDetail.text_characters} {fileDetail.estimated_text ? '(estimated)' : ''}
                        </div>
                        {fileDetail.error_message ? (
                          <div className="mt-2 text-xs text-destructive">{fileDetail.error_message}</div>
                        ) : null}
                      </div>

                      {fileDetail.pdf_pages ? (
                        <div className="border-b border-border py-3 text-sm">
                          <div className="font-mono text-xs text-muted-foreground">pdf_pages</div>
                          <div className="mt-1 font-mono text-xs">
                            pages={fileDetail.pdf_pages.page_count} · sampled={fileDetail.pdf_pages.sampled_pages} ·
                            scanned={fileDetail.pdf_pages.scanned_pages} · text={fileDetail.pdf_pages.text_pages} ·
                            low_density={fileDetail.pdf_pages.low_density_pages} · unknown=
                            {fileDetail.pdf_pages.unknown_pages}
                          </div>
                        </div>
                      ) : null}

                      {fileDetail.spreadsheet ? (
                        <div className="border-b border-border py-3 text-sm">
                          <div className="font-mono text-xs text-muted-foreground">spreadsheet</div>
                          <div className="mt-1 font-mono text-xs">
                            rows={fileDetail.spreadsheet.row_count} · cols={fileDetail.spreadsheet.col_count || 0} ·
                            sheets={fileDetail.spreadsheet.sheet_count} · merged_ratio=
                            {fileDetail.spreadsheet.merged_cell_ratio}
                            {fileDetail.spreadsheet.estimated_rows || fileDetail.spreadsheet.estimated_cols
                              ? ' (estimated)'
                              : ''}
                          </div>
                        </div>
                      ) : null}

                      <div className="border-b border-border overflow-hidden">
                        <div className="px-3 py-2 text-sm font-medium bg-muted/40">findings</div>
                        <div className="p-3 font-mono text-xs">{(fileDetail.findings || []).join(', ') || '-'}</div>
                      </div>

                      {(fileDetail.pii_samples || []).length ? (
                        <div className="border-b border-border overflow-hidden">
                          <div className="px-3 py-2 text-sm font-medium bg-muted/40">PII samples</div>
                          <pre className="p-3 text-xs overflow-auto max-h-[220px] bg-background font-mono">
                            {JSON.stringify(fileDetail.pii_samples, null, 2)}
                          </pre>
                        </div>
                      ) : null}

                      {(fileDetail.secrets_samples || []).length ? (
                        <div className="border-b border-border overflow-hidden">
                          <div className="px-3 py-2 text-sm font-medium bg-muted/40">Secrets samples</div>
                          <pre className="p-3 text-xs overflow-auto max-h-[220px] bg-background font-mono">
                            {JSON.stringify(fileDetail.secrets_samples, null, 2)}
                          </pre>
                        </div>
                      ) : null}
                    </div>
                  ) : (
                    <div className="py-10 text-center text-muted-foreground">暂无数据</div>
                  )}
                </>
              ) : (
                <>
                  <div className="mt-2 space-y-3">
                    {findingItemsQuery.isError && (
                      <div role="alert" className="space-y-3">
                        <p>{formatApiError(findingItemsQuery.error, '问题清单读取失败')}</p>
                        <Button
                          variant="outline"
                          disabled={findingLoading}
                          onClick={() => {
                            if (findingItemsQuery.isFetchNextPageError) void loadMoreFindingPage()
                            else void findingItemsQuery.refetch()
                          }}
                        >
                          重新读取清单
                        </Button>
                      </div>
                    )}
                    {(() => {
                      if (findingLoading && !findingRes) {
                        return (
                          <div className="py-10 flex items-center justify-center text-muted-foreground">
                            <Loader2 className="w-5 h-5 animate-spin motion-reduce:animate-none mr-2" />
                            加载中…
                          </div>
                        )
                      } else if (findingRes) {
                        return (
                          <div className="space-y-3">
                            <div className="text-xs text-muted-foreground font-mono">
                              已显示 {findingRes.items.length} / {findingRes.total} 个文件
                            </div>
                            <div className={styles.tableScroll}>
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
                                  {findingRes.items.map((d) => (
                                    <tr
                                      key={`${d.name}-${d.file_type}-${d.file_size}`}
                                      className="border-t border-border/60 hover:bg-muted/20 transition-colors cursor-pointer"
                                      onClick={() => {
                                        setFileDetail(d)
                                        setFileDetailOpen(true)
                                      }}
                                    >
                                      <td className="px-3 py-2 text-sm">
                                        <button
                                          className="text-left underline underline-offset-4"
                                          onClick={() => {
                                            setFileDetail(d)
                                            setFileDetailOpen(true)
                                          }}
                                        >
                                          {d.name}
                                        </button>
                                      </td>
                                      <td className="px-3 py-2 font-mono text-xs">{d.file_type}</td>
                                      <td className="px-3 py-2 font-mono text-xs">
                                        {formatFileSize(d.file_size || 0)}
                                      </td>
                                      <td className="px-3 py-2 font-mono text-xs">{d.text_characters}</td>
                                      <td className="px-3 py-2 font-mono text-xs">
                                        {d.file_type === 'pdf'
                                          ? (() => {
                                              if (d.pdf_scanned === true) {
                                                return 'scan'
                                              } else if (d.pdf_scanned === false) {
                                                return 'text'
                                              } else {
                                                return 'unknown'
                                              }
                                            })()
                                          : ''}
                                      </td>
                                      <td className="px-3 py-2 font-mono text-xs">
                                        {d.spreadsheet
                                          ? `${d.spreadsheet.row_count || 0}x${d.spreadsheet.col_count || 0}`
                                          : ''}
                                      </td>
                                      <td className="px-3 py-2 font-mono text-xs">{d.estimated_text ? 'yes' : ''}</td>
                                    </tr>
                                  ))}
                                </tbody>
                              </table>
                            </div>

                            <div className="flex items-center justify-between">
                              <div className="text-xs text-muted-foreground">
                                {findingRes.items.length >= findingRes.total ? '已加载全部' : ''}
                              </div>
                              <Button
                                variant="outline"
                                className="gap-2"
                                onClick={() => detachPromise(loadMoreFindingPage())}
                                disabled={findingLoading || !findingItemsQuery.hasNextPage}
                              >
                                {findingLoading ? (
                                  <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" />
                                ) : null}
                                加载更多
                              </Button>
                            </div>
                          </div>
                        )
                      } else if (!findingItemsQuery.isError) {
                        return <div className="py-10 text-center text-muted-foreground">暂无数据</div>
                      }
                      return null
                    })()}
                  </div>
                </>
              )}
            </div>
          </DialogContent>
        </Dialog>
        <Dialog open={policyOpen} onOpenChange={changePolicyOpen}>
          <DialogContent className={styles.reportDialog}>
            <DialogHeader className={styles.dialogHeader}>
              <DialogTitle>生成入库策略</DialogTitle>
              <DialogDescription>根据本次预检建议处理规则，应用前可检查并下载。</DialogDescription>
            </DialogHeader>
            <div className={styles.dialogBody}>
              {policyLoading ? (
                <p role="status" className="flex items-center gap-2 text-sm">
                  <Loader2 className="size-4 animate-spin motion-reduce:animate-none" />
                  正在生成建议…
                </p>
              ) : policySuggestionQuery.isError ? (
                <div role="alert" className="space-y-3 text-sm">
                  <p>{formatApiError(policySuggestionQuery.error, '生成入库策略失败')}</p>
                  <Button variant="outline" onClick={openPolicy}>
                    重新生成建议
                  </Button>
                </div>
              ) : policyRes ? (
                <div className="space-y-5">
                  <PolicySuggestionSummary policy={policyRes.policy} />
                  {policyRes.notes?.length ? (
                    <ul className="space-y-1 text-sm text-muted-foreground">
                      {policyRes.notes.map((note) => (
                        <li key={note}>{note}</li>
                      ))}
                    </ul>
                  ) : null}
                  <div>
                    <h3 className="mb-3 text-sm font-semibold">待人工复核</h3>
                    <div className={styles.tableScroll}>
                      <table className={styles.findings} aria-label="预检人工复核列表">
                        <thead>
                          <tr>
                            <th>问题分组</th>
                            <th>文件数</th>
                            <th>文件名称</th>
                          </tr>
                        </thead>
                        <tbody>
                          {policyRes.manual_review.map((bucket) => (
                            <tr key={bucket.key}>
                              <td>{bucket.key}</td>
                              <td>{bucket.total}</td>
                              <td>{bucket.sample_names.join('、')}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                    {!policyRes.manual_review.length ? (
                      <p className="text-sm text-muted-foreground">建议中没有待人工复核条目。</p>
                    ) : null}
                  </div>
                  <details>
                    <summary className="cursor-pointer text-sm font-medium">查看策略 JSON</summary>
                    <pre className="mt-3 max-h-64 overflow-auto bg-muted/30 p-3 text-xs">
                      {JSON.stringify(policyRes.policy, null, 2)}
                    </pre>
                  </details>
                  <div className="flex items-center gap-2">
                    <Checkbox
                      id="precheck-policy-replace"
                      checked={policyApplyReplace}
                      disabled={policyApplying}
                      onCheckedChange={(value) => setPolicyApplyReplace(value === true)}
                    />
                    <Label htmlFor="precheck-policy-replace">覆盖已有入库策略</Label>
                  </div>
                  <p className="text-sm leading-6 text-muted-foreground">
                    已有策略时需要勾选覆盖，应用后会替换整份策略。
                  </p>
                </div>
              ) : null}
            </div>
            {policyApplyError !== null && policyApplyError.runId === selectedRunId ? (
              <div role="alert" className={styles.formError}>
                {policyApplyError.message}
              </div>
            ) : null}
            <div className={styles.dialogFooter}>
              <Button variant="ghost" onClick={() => changePolicyOpen(false)}>
                关闭
              </Button>
              <Button
                variant="outline"
                disabled={policyRes === null || policyLoading || policySuggestionQuery.isError}
                onClick={() => {
                  if (policyRes !== null) {
                    downloadJsonObject(policyRes.policy, `${datasetFilename}.ingestion_policy.suggested.json`)
                  }
                }}
              >
                <Download />
                下载策略
              </Button>
              <Button
                disabled={!hasSuggestedRules || policyLoading || policyApplying || policySuggestionQuery.isError}
                onClick={() => {
                  void applyPolicy()
                }}
              >
                {policyApplying ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : null}
                {policyApplying ? '正在应用…' : '应用到数据集'}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
      </section>
    </AppFrame>
  )
}
