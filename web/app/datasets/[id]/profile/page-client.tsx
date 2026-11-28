'use client'

import { skipToken, useInfiniteQuery, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
  type ComponentProps,
  type ReactNode,
} from 'react'
import { useParams } from 'next/navigation'
import { toast } from 'sonner'
import {
  BarChart3,
  Download,
  FileSearch,
  Ingestion,
  Loader2,
  MoreHorizontal,
  RotateCcw,
  RefreshCw,
  Sparkles,
} from '@/components/icons'
import { Bar, BarChart, CartesianGrid, Cell, Pie, PieChart, Tooltip, XAxis, YAxis } from 'recharts'

import { AppFrame } from '@/components/app-frame'
import {
  OperationalWorkspace,
  WorkspaceNotice,
  WorkspaceNoticeStack,
  workspaceStyles as ws,
} from '@/components/ui/operational-workspace'
import { DropdownMenu, DropdownMenuContent, DropdownMenuItem, DropdownMenuTrigger } from '@/components/ui/dropdown-menu'
import { Panel } from '@/components/ui/panel'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { Badge } from '@/components/ui/badge'
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Label } from '@/components/ui/label'
import { Switch } from '@/components/ui/switch'
import { Input } from '@/components/ui/input'
import { DocumentDetailDialog } from '@/components/document-detail-dialog'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { SafeResponsiveChart } from '@/components/ui/safe-responsive-chart'

import { datasetApi, documentApi } from '@/lib/api'
import type { DatasetProfileBucketDimension } from '@/lib/api/datasets'
import { buildDatasetProfileModel } from '@/lib/dataset-profile-model'
import {
  profileScanSnapshotSchema,
  datasetProfileSchema,
  type DatasetProfileScanRunSummary,
  type DatasetProfileDocumentOut,
  type DatasetProfileDocumentListResponse,
  type DatasetProfileTargetCheckStatus,
} from '@/lib/dataset-profile-schema'
import { formatApiError, toApiErrorInfo } from '@/lib/api-errors'
import { getAuthSessionKey, subscribeAuthSession } from '@/lib/auth-storage'
import { reportClientError } from '@/lib/client-logging'
import { downloadBlob } from '@/lib/download'
import { queryKeys } from '@/lib/query-keys'
import { sanitizeFilename } from '@/lib/sanitize'
import { cn, formatFileSize, formatDate, detachPromise } from '@/lib/utils'
import { Link, useRouter } from '@/i18n/navigation'
import styles from './profile.module.css'

import type {
  DatasetProfileFindingSummary,
  DatasetProfileScanRunCreateRequest,
  DatasetProfileScanRunOut,
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
] as const

const PROFILE_DOCUMENT_PAGE_SIZE = 50
const PROFILE_RETRY_BATCH_SIZE = 200
const PROFILE_BUCKET_PREVIEW_MAX_CHARS = 360
const PROFILE_BUCKET_LABELS = {
  file_type: '格式',
  language: '语言',
  directory: '目录',
  quality_bucket: '质量桶',
} as const
const profilePanelClass = styles.chartPanel
const profileChartProps = { className: 'h-[220px]', minHeight: 220 } as const
const profileSectionTitleClass = ws.sectionTitle
const profileSectionCaptionClass = ws.sectionDescription

type ScanSubmission =
  Readonly<{ status: 'idle' | 'pending' }> | Readonly<{ status: 'rejected' | 'unconfirmed'; message: string }>

type ProfileRetryFeedback = Readonly<{
  findingKey: string
  documentIds: readonly string[]
  message: string
  failures: readonly Readonly<{ id: string; filename: string; reason: string }>[]
}>

function getNextProfileDocumentOffset(
  lastPage: DatasetProfileDocumentListResponse,
  pages: readonly DatasetProfileDocumentListResponse[],
): number | undefined {
  const loadedCount = pages.reduce((count, page) => count + page.items.length, 0)
  return lastPage.items.length > 0 && loadedCount < lastPage.total ? loadedCount : undefined
}

function mergeProfileDocumentPages(pages: readonly DatasetProfileDocumentListResponse[]) {
  const documentsById = new Map<string, DatasetProfileDocumentOut>()
  for (const page of pages) {
    for (const document of page.items) documentsById.set(document.id, document)
  }
  return { total: pages[pages.length - 1].total, items: [...documentsById.values()] }
}

function ProfileCardHeader({
  title,
  caption,
  action,
}: Readonly<{
  title: string
  caption?: string
  action?: ReactNode
}>) {
  return (
    <div className="mb-2.5 flex items-start justify-between gap-3">
      <div className="min-w-0">
        <div className={profileSectionTitleClass}>{title}</div>
        {caption ? <div className={profileSectionCaptionClass}>{caption}</div> : null}
      </div>
      {action ? <div className="shrink-0">{action}</div> : null}
    </div>
  )
}

function ProfileBucketSelect({
  label,
  rows,
  onOpen,
}: Readonly<{
  label: string
  rows: readonly { key: string | null; name: string }[]
  onOpen: (key: string) => void
}>) {
  const choices = rows.flatMap(({ key, name }) => (key === null ? [] : [{ key, name }]))
  if (choices.length === 0) return null

  return (
    <Select value="" onValueChange={onOpen}>
      <SelectTrigger aria-label={label} className="h-8 max-w-40 text-xs">
        <SelectValue placeholder={label} />
      </SelectTrigger>
      <SelectContent>
        {choices.map(({ key, name }) => (
          <SelectItem key={key} value={key}>
            {name}
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function ProfileChart({
  rows,
  children,
}: Readonly<{ rows: readonly { value: number }[]; children: ComponentProps<typeof SafeResponsiveChart>['children'] }>) {
  return rows.some((row) => row.value > 0) ? (
    <SafeResponsiveChart {...profileChartProps}>{children}</SafeResponsiveChart>
  ) : (
    <p className={styles.chartEmpty}>暂无可展示的分布数据</p>
  )
}

function ProfileDistribution({
  categories,
  hasData,
  description,
  children,
}: Readonly<{
  categories: readonly string[]
  hasData: boolean
  description: ReactNode
  children: ReactNode
}>) {
  return hasData ? (
    <div className={styles.charts}>{children}</div>
  ) : (
    <section className={styles.distributionEmpty}>
      <h2>当前分类暂无分布统计</h2>
      {description}
      <ul aria-label="分布项目">
        {categories.map((category) => (
          <li key={category}>{category}</li>
        ))}
      </ul>
    </section>
  )
}

function formatProfileScanOption(value: unknown): string {
  if (value === true) return '开启'
  if (value === false) return '关闭'
  return '未提供'
}

function findingBadgeVariant(severity: DatasetProfileFindingSummary['severity']): 'outline' | 'soft' | 'destructive' {
  if (severity === 'error') return 'destructive'
  if (severity === 'warning') return 'soft'
  return 'outline'
}

function targetBadgeVariant(status: DatasetProfileTargetCheckStatus): 'outline' | 'soft' | 'destructive' {
  if (status === 'fail') return 'destructive'
  if (status === 'warn') return 'soft'
  return 'outline'
}

function formatChunkTargetLabel(value: string): string {
  return value
    .replace('Chunk tokens', '切片 token')
    .replace('Coverage', '正文覆盖')
    .replace('Overlap waste', '重叠成本')
}

function isProfileScanActive(run: Readonly<{ status: string }> | null): boolean {
  return run !== null && (run.status === 'pending' || run.status === 'running')
}

function resolveRemoteScanRun(
  summaryRun: DatasetProfileScanRunSummary | null,
  history: readonly DatasetProfileScanRunOut[] | undefined,
): DatasetProfileScanRunSummary | null {
  const activeRun = history?.find(isProfileScanActive)
  if (activeRun) return activeRun
  if (summaryRun && isProfileScanActive(summaryRun)) {
    return history?.find((run) => run.id === summaryRun.id) ?? summaryRun
  }
  const latest = history?.[0]
  if (!latest) return summaryRun
  if (
    summaryRun &&
    summaryRun.id !== latest.id &&
    summaryRun.created_at &&
    latest.created_at &&
    Date.parse(summaryRun.created_at) > Date.parse(latest.created_at)
  )
    return summaryRun
  return latest
}

function formatProfileRunStatus(status: string): string {
  if (status === 'pending') return '排队中'
  if (status === 'running') return '扫描中'
  if (status === 'completed') return '已完成'
  if (status === 'failed') return '失败'
  if (status === 'cancelled' || status === 'canceled') return '已取消'
  return status
}

export default function DatasetProfilePage() {
  const { id: datasetId } = useParams<{ id: string }>()
  const sessionKey = useSyncExternalStore(subscribeAuthSession, getAuthSessionKey, getAuthSessionKey)
  return (
    <DatasetProfileWorkspace
      key={JSON.stringify([datasetId, sessionKey])}
      datasetId={datasetId}
      sessionKey={sessionKey}
    />
  )
}

function DatasetProfileWorkspace({ datasetId, sessionKey }: Readonly<{ datasetId: string; sessionKey: string }>) {
  const router = useRouter()
  const queryClient = useQueryClient()
  const scanFormId = useId()

  const [scanConfigOpen, setScanConfigOpen] = useState(false)
  const [view, setView] = useState('overview')
  const [exporting, setExporting] = useState<'json' | 'html' | null>(null)

  const [scanConfig, setScanConfig] = useState({
    backfill_pdf_quality: true,
    backfill_text_quality: true,
    backfill_chunk_stats: true,
    compute_file_hash: false,
  })
  const [maxDocuments, setMaxDocuments] = useState('')
  const [scanRun, setScanRun] = useState<DatasetProfileScanRunOut | null>(null)
  const [scanSubmission, setScanSubmission] = useState<ScanSubmission>({ status: 'idle' })
  const [scanPollFailure, setScanPollFailure] = useState<Readonly<{ runId: string; message: string }> | null>(null)
  const ownerRef = useRef({ active: true })
  const scanRequestRef = useRef<Promise<DatasetProfileScanRunOut> | null>(null)
  const exportControllerRef = useRef<AbortController | null>(null)
  const [compareA, setCompareA] = useState<string | null>(null)
  const [compareB, setCompareB] = useState<string | null>(null)

  const [findingOpen, setFindingOpen] = useState(false)
  const [selectedFinding, setSelectedFinding] = useState<DatasetProfileFindingSummary | null>(null)
  const retryingIdsRef = useRef(new Set<string>())
  const [retryingIds, setRetryingIds] = useState<ReadonlySet<string>>(() => new Set())
  const [retryFeedback, setRetryFeedback] = useState<readonly ProfileRetryFeedback[]>([])

  const [bucketOpen, setBucketOpen] = useState(false)
  const [bucketSelection, setBucketSelection] = useState<Readonly<{
    dimension: DatasetProfileBucketDimension
    key: string
  }> | null>(null)

  useLayoutEffect(() => {
    const owner = { active: true }
    ownerRef.current = owner
    return () => {
      owner.active = false
      exportControllerRef.current?.abort()
    }
  }, [])

  const isCurrent = useCallback(
    (owner: { active: boolean }) => owner.active && getAuthSessionKey() === sessionKey,
    [sessionKey],
  )

  const datasetQuery = useQuery({
    queryKey: queryKeys.datasets.detail(datasetId),
    queryFn: ({ signal }) => datasetApi.get(datasetId, { signal }),
  })
  const summaryQuery = useQuery({
    queryKey: queryKeys.datasets.profileSummary(datasetId),
    queryFn: ({ signal }) => datasetApi.getProfileSummary(datasetId, { signal }),
  })
  const scanRunsQuery = useQuery({
    queryKey: queryKeys.datasets.profileScanRunOptions(datasetId),
    queryFn: ({ signal }) => datasetApi.listAllProfileScanRuns(datasetId, { signal }),
  })

  const dataset = datasetQuery.data ?? null
  const summary = summaryQuery.data ?? null
  const scanRuns = scanRunsQuery.data
  const isLoading = datasetQuery.isLoading || summaryQuery.isLoading
  const selectedFindingKey = selectedFinding === null ? null : selectedFinding.key

  const findingDocumentsQuery = useInfiniteQuery({
    queryKey: queryKeys.datasets.profileFindingDocuments(datasetId, selectedFindingKey, {
      limit: PROFILE_DOCUMENT_PAGE_SIZE,
    }),
    enabled: findingOpen,
    initialPageParam: 0,
    queryFn:
      selectedFindingKey === null
        ? skipToken
        : ({ pageParam, signal }) =>
            datasetApi.listProfileFinding(
              datasetId,
              selectedFindingKey,
              { skip: pageParam, limit: PROFILE_DOCUMENT_PAGE_SIZE },
              { signal },
            ),
    getNextPageParam: getNextProfileDocumentOffset,
  })
  const bucketDocumentsQuery = useInfiniteQuery({
    queryKey: queryKeys.datasets.profileBucketDocuments(datasetId, {
      selection: bucketSelection,
      include_preview: true,
      limit: PROFILE_DOCUMENT_PAGE_SIZE,
      preview_max_chars: PROFILE_BUCKET_PREVIEW_MAX_CHARS,
    }),
    enabled: bucketOpen,
    initialPageParam: 0,
    queryFn:
      bucketSelection === null
        ? skipToken
        : ({ pageParam, signal }) =>
            datasetApi.listProfileBucketDocuments(
              datasetId,
              {
                dimension: bucketSelection.dimension,
                bucket: bucketSelection.key,
                skip: pageParam,
                limit: PROFILE_DOCUMENT_PAGE_SIZE,
                include_preview: true,
                preview_max_chars: PROFILE_BUCKET_PREVIEW_MAX_CHARS,
              },
              { signal },
            ),
    getNextPageParam: getNextProfileDocumentOffset,
  })
  const findingLoading = findingDocumentsQuery.isFetching
  const findingRes = useMemo(() => {
    if (findingDocumentsQuery.data === undefined) return null
    return mergeProfileDocumentPages(findingDocumentsQuery.data.pages)
  }, [findingDocumentsQuery.data])
  const bucketLoading = bucketDocumentsQuery.isFetching
  const bucketRes = useMemo(() => {
    if (bucketDocumentsQuery.data === undefined) return null
    return mergeProfileDocumentPages(bucketDocumentsQuery.data.pages)
  }, [bucketDocumentsQuery.data])
  const findingRetryFeedback = retryFeedback.filter((feedback) => feedback.findingKey === selectedFindingKey)
  const { fetchNextPage: fetchNextFindingPage, hasNextPage: hasNextFindingPage } = findingDocumentsQuery
  const { fetchNextPage: fetchNextBucketPage, hasNextPage: hasNextBucketPage } = bucketDocumentsQuery

  const { refetch: refetchDataset } = datasetQuery
  const { refetch: refetchSummary } = summaryQuery
  const { refetch: refetchScanRuns } = scanRunsQuery
  const refreshProfileOverview = useCallback(async () => {
    await Promise.all([refetchDataset(), refetchSummary(), refetchScanRuns()])
  }, [refetchDataset, refetchSummary, refetchScanRuns])

  useEffect(() => {
    const firstError = datasetQuery.error ?? summaryQuery.error
    if (!firstError) return
    reportClientError('Failed to load dataset profile', firstError)
  }, [datasetQuery.error, summaryQuery.error])

  useEffect(() => {
    const error = findingDocumentsQuery.error
    if (error === null || !findingOpen) return
    reportClientError('Failed to load finding documents', error)
  }, [findingDocumentsQuery.error, findingDocumentsQuery.errorUpdatedAt, findingOpen])

  useEffect(() => {
    const error = bucketDocumentsQuery.error
    if (error === null || !bucketOpen) return
    reportClientError('Failed to load bucket documents', error)
  }, [bucketDocumentsQuery.error, bucketDocumentsQuery.errorUpdatedAt, bucketOpen])

  const charts = useMemo(
    () => (summary === null ? undefined : buildDatasetProfileModel(summary, PIE_COLORS)),
    [summary],
  )

  const parseLowQualityFinding = charts?.parseLowQualityFinding

  function openFinding(finding: DatasetProfileFindingSummary) {
    setSelectedFinding(finding)
    setFindingOpen(true)
  }

  function openBucket(dimension: DatasetProfileBucketDimension, key: string) {
    setBucketSelection({ dimension, key })
    setBucketOpen(true)
  }

  const loadMoreFindingPage = useCallback(async () => {
    if (!hasNextFindingPage) return
    await fetchNextFindingPage()
  }, [fetchNextFindingPage, hasNextFindingPage])

  async function retryDocuments(
    documents: readonly Pick<DatasetProfileDocumentOut, 'id' | 'filename'>[],
    findingKey: string,
  ) {
    const owner = ownerRef.current
    const targets = [...new Map(documents.map((document) => [document.id, document])).values()]
    const ids = targets.map((document) => document.id)
    const label = targets.length === 1 ? targets[0].filename : `已加载的 ${targets.length} 个文档`
    if (ids.length === 0 || !isCurrent(owner) || ids.some((id) => retryingIdsRef.current.has(id))) return
    for (const id of ids) retryingIdsRef.current.add(id)
    setRetryingIds(new Set(retryingIdsRef.current))
    setRetryFeedback((current) =>
      current.filter(
        (feedback) =>
          feedback.documentIds.length !== ids.length || feedback.documentIds.some((id, index) => id !== ids[index]),
      ),
    )

    let queued = 0
    let skipped = 0
    let notFound = 0
    let denied = 0
    let conflicts = 0
    let unconfirmed = 0
    let notSubmitted = 0
    let submissionError: string | null = null
    const failures: { id: string; filename: string; reason: string }[] = []
    try {
      for (let offset = 0; offset < ids.length; offset += PROFILE_RETRY_BATCH_SIZE) {
        if (!isCurrent(owner)) return
        const batch = ids.slice(offset, offset + PROFILE_RETRY_BATCH_SIZE)
        try {
          const result = await documentApi.batchRetry({ document_ids: batch, force: true, skip_if_unchanged: false })
          if (!isCurrent(owner)) return
          queued += result.queued
          skipped += result.skipped
          notFound += result.not_found.length
          denied += result.denied.length
          conflicts += result.conflicts.length
          for (const document of targets) {
            if (result.not_found.includes(document.id)) failures.push({ ...document, reason: '未找到' })
            if (result.denied.includes(document.id)) failures.push({ ...document, reason: '无权限' })
            if (result.conflicts.includes(document.id)) failures.push({ ...document, reason: '冲突' })
          }
        } catch (error) {
          if (!isCurrent(owner)) return
          reportClientError('Failed to confirm profile document retries', error)
          unconfirmed = batch.length
          notSubmitted = ids.length - offset - batch.length
          submissionError = formatApiError(error, '本批重试结果未确认')
          for (const document of targets.slice(offset)) {
            failures.push({
              ...document,
              reason: batch.includes(document.id) ? '结果未确认' : '尚未提交',
            })
          }
          break
        }
      }

      const message =
        `${label}重试回执：已排队 ${queued}，跳过 ${skipped}，未找到 ${notFound}，无权限 ${denied}，冲突 ${conflicts}。` +
        (submissionError === null
          ? ''
          : ` 本批 ${unconfirmed} 个结果未确认，后续 ${notSubmitted} 个未提交。${submissionError}`)
      setRetryFeedback((current) => [...current, { findingKey, documentIds: ids, message, failures }])
      if (submissionError !== null) toast.error(message)
      else if (notFound + denied + conflicts > 0) toast.warning(message)
      else toast.success(message)
      await Promise.all([
        refreshProfileOverview(),
        queryClient.invalidateQueries({
          queryKey: queryKeys.datasets.profileFindingDocuments(datasetId, findingKey, {
            limit: PROFILE_DOCUMENT_PAGE_SIZE,
          }),
          exact: true,
        }),
      ])
    } finally {
      for (const id of ids) retryingIdsRef.current.delete(id)
      if (isCurrent(owner)) setRetryingIds(new Set(retryingIdsRef.current))
    }
  }

  const loadMoreBucketPage = useCallback(async () => {
    if (!hasNextBucketPage) return
    await fetchNextBucketPage()
  }, [fetchNextBucketPage, hasNextBucketPage])

  const summaryRun = summary === null ? null : summary.latest_scan_run
  const latestSummaryRun = resolveRemoteScanRun(summaryRun, scanRuns)
  const summaryConfirmsCompletion =
    scanRun !== null &&
    isProfileScanActive(scanRun) &&
    latestSummaryRun !== null &&
    latestSummaryRun.id === scanRun.id &&
    ['completed', 'failed', 'cancelled', 'canceled'].includes(latestSummaryRun.status)
  const effectiveScanRun = summaryConfirmsCompletion
    ? latestSummaryRun
    : scanRun !== null &&
        (isProfileScanActive(scanRun) || latestSummaryRun === null || latestSummaryRun.id === scanRun.id)
      ? scanRun
      : latestSummaryRun
  const scanRunId = effectiveScanRun === null ? null : effectiveScanRun.id
  const scanPollError = scanPollFailure !== null && scanPollFailure.runId === scanRunId ? scanPollFailure.message : null
  const scanRunning = isProfileScanActive(effectiveScanRun)
  const scanBusy = scanSubmission.status === 'pending' || scanRunning

  useEffect(() => {
    if (scanRunId === null || !scanRunning || scanPollError !== null) return
    const runId = scanRunId
    const owner = ownerRef.current
    const controller = new AbortController()
    let timer = window.setTimeout(() => void pollScanRun(), 500)

    async function pollScanRun() {
      if (controller.signal.aborted || !isCurrent(owner)) return
      try {
        const next = await datasetApi.getProfileScanRun(datasetId, runId, { signal: controller.signal })
        if (controller.signal.aborted || !isCurrent(owner)) return
        setScanRun(next)
        if (isProfileScanActive(next)) {
          timer = window.setTimeout(() => void pollScanRun(), 2000)
        } else {
          await refreshProfileOverview()
        }
      } catch (error) {
        if (controller.signal.aborted || !isCurrent(owner)) return
        reportClientError('Failed to read dataset profile scan status', error)
        setScanPollFailure({ runId, message: formatApiError(error, '扫描状态读取失败，最后结果已保留') })
      }
    }

    return () => {
      controller.abort()
      window.clearTimeout(timer)
    }
  }, [datasetId, scanRunId, scanRunning, scanPollError, isCurrent, refreshProfileOverview])

  async function startDeepScan() {
    const owner = ownerRef.current
    if (
      summary === null ||
      summary.total_documents === 0 ||
      scanRequestRef.current !== null ||
      scanBusy ||
      !isCurrent(owner)
    )
      return
    const config: DatasetProfileScanRunCreateRequest = {
      ...scanConfig,
      max_documents: maxDocuments === '' ? null : Number(maxDocuments),
    }
    const request = datasetApi.startProfileScan(datasetId, config)
    scanRequestRef.current = request
    setScanSubmission({ status: 'pending' })
    try {
      const run = await request
      if (!isCurrent(owner)) return
      setScanRun(run)
      setScanPollFailure(null)
      setScanSubmission({ status: 'idle' })
      toast.success('已提交深度扫描')
    } catch (error) {
      if (!isCurrent(owner)) return
      reportClientError('Failed to submit dataset profile scan', error)
      const { status } = toApiErrorInfo(error, '扫描提交失败')
      const rejected = status !== undefined && status >= 400 && status < 500 && status !== 408
      const message = formatApiError(error, rejected ? '扫描提交被拒绝' : '扫描提交结果未确认')
      setScanSubmission({ status: rejected ? 'rejected' : 'unconfirmed', message })
      toast.error(message)
    } finally {
      if (scanRequestRef.current === request) scanRequestRef.current = null
    }
    if (isCurrent(owner)) await refreshProfileOverview()
  }

  async function exportProfile(format: 'json' | 'html') {
    const owner = ownerRef.current
    if (!canExport || dataset === null || exportControllerRef.current !== null || !isCurrent(owner)) return
    const controller = new AbortController()
    exportControllerRef.current = controller
    setExporting(format)
    try {
      const blob =
        format === 'json'
          ? await datasetApi.exportProfileSummary(datasetId, { signal: controller.signal })
          : await datasetApi.exportProfileHtml(datasetId, { redact: true }, { signal: controller.signal })
      if (!isCurrent(owner)) return
      downloadBlob(`${sanitizeFilename(dataset.name)}.profile.${format}`, blob)
      toast.success('画像报告已开始下载')
    } catch (error) {
      if (!isCurrent(owner)) return
      reportClientError('Failed to export dataset profile', error)
      toast.error(formatApiError(error, '画像报告导出失败'))
    } finally {
      if (exportControllerRef.current === controller) {
        exportControllerRef.current = null
        if (isCurrent(owner)) setExporting(null)
      }
    }
  }

  const totalSizeLabel = summary
    ? formatFileSize(summary.total_size_bytes).replace('Bytes', 'B')
    : isLoading
      ? '…'
      : '-'
  const scannedPdfCount = summary
    ? `${summary.pdf_scan.scanned}/${summary.pdf_scan.scanned + summary.pdf_scan.not_scanned + summary.pdf_scan.unknown}`
    : isLoading
      ? '…'
      : '-'
  const generatedAtLabel = summary === null ? '未取得' : formatDate(summary.generated_at)

  const completedRuns = useMemo(
    () => (scanRuns === undefined ? undefined : scanRuns.filter((run) => run.status === 'completed')),
    [scanRuns],
  )
  const latestValidScan = useMemo(
    () =>
      completedRuns?.find((run) => {
        const result = datasetProfileSchema.safeParse(run.summary)
        return result.success && result.data.dataset_id === datasetId && result.data.total_documents > 0
      }),
    [completedRuns, datasetId],
  )
  const hasDocuments = summary !== null && summary.total_documents > 0
  const uploadHref = `/knowledge/ingestion?datasetId=${encodeURIComponent(datasetId)}`
  const canExport = hasDocuments && latestValidScan !== undefined
  const completedAtLabel = latestValidScan?.finished_at ? formatDate(latestValidScan.finished_at) : '完成时间未记录'
  const distributionEmptyDescription =
    summary === null ? null : (
      <>
        <p>当前画像记录 {summary.total_documents.toLocaleString()} 篇文档，本分类的分布计数均为空或 0。</p>
        {effectiveScanRun !== null && <p>最近扫描：{formatProfileRunStatus(effectiveScanRun.status)}</p>}
        <p>{scanBusy ? '扫描结果保存后可重新读取分布统计。' : '可使用顶部“深度扫描”重新采集统计。'}</p>
      </>
    )

  let profileGate: ReactNode = null
  if (!hasDocuments) {
    profileGate = (
      <EmptyState
        icon={Ingestion}
        title="先上传入库文档"
        description="文档入库后才能扫描并查看数据画像。"
        className={styles.guide}
      >
        <Button className={styles.primaryAction} asChild>
          <Link href={uploadHref}>上传入库文档</Link>
        </Button>
      </EmptyState>
    )
  } else if (latestValidScan === undefined) {
    if (scanRunsQuery.isError) {
      profileGate = (
        <WorkspaceNotice
          retry={() => void scanRunsQuery.refetch()}
          retryLabel="重新读取扫描历史"
          pending={scanRunsQuery.isFetching}
        >
          {formatApiError(scanRunsQuery.error, '扫描记录读取失败，暂不能确认画像结果')}
        </WorkspaceNotice>
      )
    } else if (scanRuns === undefined) {
      profileGate = (
        <p className={styles.loading} role="status">
          正在读取扫描记录…
        </p>
      )
    } else {
      let title = '尚无可用扫描结果'
      let description = '可以重新读取结果，或配置一次新的扫描。'
      if (effectiveScanRun?.status === 'failed') {
        title = '扫描失败'
        description = effectiveScanRun.error_message ?? '请检查扫描配置后重试。'
      } else if (effectiveScanRun?.status === 'cancelled' || effectiveScanRun?.status === 'canceled') {
        title = '扫描已取消'
        description = '如需查看画像，请重新配置扫描。'
      } else if (scanRunning) {
        title = '扫描进行中'
        description = '结果保存后即可查看画像。'
      } else if (scanRuns.length === 0) {
        title = '启动首次深度扫描'
        description = `已有 ${summary.total_documents.toLocaleString()} 篇文档，尚无扫描记录。完成扫描后可查看画像。`
      }
      profileGate = (
        <EmptyState icon={BarChart3} title={title} description={description} className={styles.guide}>
          {scanRuns.length > 0 ? (
            <Button variant="outline" onClick={() => void refreshProfileOverview()}>
              重新读取结果
            </Button>
          ) : null}
          <Button className={styles.primaryAction} disabled={scanBusy} onClick={() => setScanConfigOpen(true)}>
            {scanRunning ? '正在扫描…' : '配置深度扫描'}
          </Button>
        </EmptyState>
      )
    }
  }
  useEffect(() => {
    if (completedRuns === undefined) return
    const baseline = completedRuns[0]
    const comparison = completedRuns[1]
    if (baseline === undefined || comparison === undefined) return
    setCompareA((current) => (current === null ? baseline.id : current))
    setCompareB((current) => (current === null ? comparison.id : current))
  }, [completedRuns])
  const baselineRun = completedRuns?.find((run) => run.id === compareA)
  const comparisonRun = completedRuns?.find((run) => run.id === compareB)

  const compareDelta = useMemo(() => {
    if (baselineRun === undefined || comparisonRun === undefined) {
      return { status: 'unselected', message: '请选择当前历史中的两个已完成扫描记录。' } as const
    }
    if (baselineRun.id === comparisonRun.id) {
      return { status: 'unselected', message: '请选择两个不同的扫描记录。' } as const
    }
    const baseline = profileScanSnapshotSchema.safeParse(baselineRun.summary)
    const comparison = profileScanSnapshotSchema.safeParse(comparisonRun.summary)
    if (!baseline.success) {
      return { status: 'invalid', message: '基准快照缺少有效统计，无法比较。请选择其他记录或重新扫描。' } as const
    }
    if (!comparison.success) {
      return { status: 'invalid', message: '对比快照缺少有效统计，无法比较。请选择其他记录或重新扫描。' } as const
    }
    const piiA = Object.values(baseline.data.pii_hits_total).reduce((total, count) => total + count, 0)
    const piiB = Object.values(comparison.data.pii_hits_total).reduce((total, count) => total + count, 0)
    const secretsA = Object.values(baseline.data.secrets_hits_total).reduce((total, count) => total + count, 0)
    const secretsB = Object.values(comparison.data.secrets_hits_total).reduce((total, count) => total + count, 0)
    return {
      status: 'ready',
      docs: comparison.data.total_documents - baseline.data.total_documents,
      bytes: comparison.data.total_size_bytes - baseline.data.total_size_bytes,
      p90: comparison.data.length_percentiles.p90 - baseline.data.length_percentiles.p90,
      scanned: comparison.data.pdf_scan.scanned - baseline.data.pdf_scan.scanned,
      pii: piiB - piiA,
      secrets: secretsB - secretsA,
    } as const
  }, [baselineRun, comparisonRun])

  const scanSubmissionNotice =
    scanSubmission.status === 'rejected' || scanSubmission.status === 'unconfirmed' ? (
      <WorkspaceNotice
        retry={() => void refreshProfileOverview()}
        retryLabel="重新读取扫描记录"
        pending={summaryQuery.isFetching || scanRunsQuery.isFetching}
      >
        {scanSubmission.message}
        {scanSubmission.status === 'unconfirmed' ? ' 重新提交会新建扫描，请先核对记录。' : null}
      </WorkspaceNotice>
    ) : null

  return (
    <AppFrame>
      <OperationalWorkspace
        title="数据画像"
        icon="dataset-profile"
        context={dataset?.name ?? (datasetQuery.isPending ? '正在读取数据集…' : '数据集未取得')}
        back={() => router.push('/datasets')}
        actions={
          <>
            <Button
              className={styles.primaryAction}
              disabled={!hasDocuments || scanBusy}
              onClick={() => setScanConfigOpen(true)}
            >
              <Sparkles />
              {scanSubmission.status === 'pending'
                ? '正在提交…'
                : scanRunning && effectiveScanRun !== null
                  ? `正在扫描（${effectiveScanRun.progress}%）`
                  : '深度扫描'}
            </Button>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button
                  variant="outline"
                  aria-label="导出画像"
                  disabled={!canExport || dataset === null || exporting !== null}
                  title={!canExport ? '完成有效的深度扫描后可导出当前画像' : '导出当前文档统计'}
                >
                  <Download />
                  导出
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem
                  onSelect={() => {
                    void exportProfile('json')
                  }}
                >
                  JSON 数据
                </DropdownMenuItem>
                <DropdownMenuItem
                  onSelect={() => {
                    void exportProfile('html')
                  }}
                >
                  脱敏 HTML 报告
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
            <DropdownMenu>
              <DropdownMenuTrigger asChild>
                <Button variant="ghost" size="icon" aria-label="数据集操作">
                  <MoreHorizontal />
                </Button>
              </DropdownMenuTrigger>
              <DropdownMenuContent align="end">
                <DropdownMenuItem onSelect={() => router.push(`/datasets/${datasetId}/health`)}>
                  健康概览
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => router.push(`/datasets/${datasetId}/precheck`)}>
                  文档预检
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => router.push(`/datasets/${datasetId}/ingestion`)}>
                  入库策略
                </DropdownMenuItem>
                <DropdownMenuItem onSelect={() => router.push(`/datasets/${datasetId}/tables`)}>
                  表格资产
                </DropdownMenuItem>
              </DropdownMenuContent>
            </DropdownMenu>
          </>
        }
      >
        <div className={styles.content}>
          {((datasetQuery.isError || summaryQuery.isError) && summary !== null) ||
          (!scanConfigOpen && scanSubmissionNotice !== null) ||
          (scanPollError !== null && scanRunning) ||
          (scanRunsQuery.isError && latestValidScan !== undefined) ? (
            <WorkspaceNoticeStack ariaLabel="数据画像状态提示">
              {(datasetQuery.isError || summaryQuery.isError) && summary !== null ? (
                <WorkspaceNotice
                  tone="warning"
                  title="画像读取失败"
                  error={datasetQuery.error ?? summaryQuery.error}
                  fallbackMessage="画像读取失败"
                  retry={() => {
                    void datasetQuery.refetch()
                    void summaryQuery.refetch()
                  }}
                  retryLabel="重新读取画像"
                  pending={datasetQuery.isFetching || summaryQuery.isFetching}
                />
              ) : null}
              {scanConfigOpen ? null : scanSubmissionNotice}
              {scanPollError !== null && scanRunning ? (
                <WorkspaceNotice
                  tone="warning"
                  title="扫描状态读取异常"
                  retry={() => setScanPollFailure(null)}
                  retryLabel="继续读取扫描状态"
                >
                  {scanPollError}。后台任务可能仍在运行。
                </WorkspaceNotice>
              ) : null}
              {scanRunsQuery.isError && latestValidScan !== undefined ? (
                <WorkspaceNotice
                  tone="warning"
                  title="扫描记录更新失败，保留上次有效结果"
                  error={scanRunsQuery.error}
                  fallbackMessage="扫描记录读取失败"
                  retry={() => void scanRunsQuery.refetch()}
                  retryLabel="重新读取扫描历史"
                  pending={scanRunsQuery.isFetching}
                />
              ) : null}
            </WorkspaceNoticeStack>
          ) : null}
          {(datasetQuery.isError || summaryQuery.isError) && summary === null ? (
            <WorkspaceNotice
              retry={() => {
                void datasetQuery.refetch()
                void summaryQuery.refetch()
              }}
              retryLabel="重新读取画像"
              pending={datasetQuery.isFetching || summaryQuery.isFetching}
            >
              {formatApiError(datasetQuery.error ?? summaryQuery.error, '画像读取失败')}
            </WorkspaceNotice>
          ) : null}
          {summary === null || charts === undefined ? (
            <div className={styles.loading} role="status">
              {summaryQuery.isPending ? '正在读取数据画像…' : '当前画像暂不可用。'}
            </div>
          ) : (
            <Tabs value={view} onValueChange={setView}>
              <TabsList className={ws.tabList} aria-label="数据画像视图">
                <TabsTrigger value="overview">问题与概览</TabsTrigger>
                <TabsTrigger value="distribution">分布分析</TabsTrigger>
                <TabsTrigger value="history">扫描历史</TabsTrigger>
              </TabsList>
              {profileGate && view !== 'history' ? (
                <TabsContent value={view} className={ws.tabContent}>
                  {profileGate}
                </TabsContent>
              ) : (
                <>
                  <TabsContent value="overview" className={ws.tabContent}>
                    <dl className={styles.metrics}>
                      {[
                        { label: '文档总数', value: summary.total_documents.toLocaleString(), unit: '篇' },
                        { label: '总存储体积', value: totalSizeLabel, unit: '' },
                        {
                          label: '正文长度中位数',
                          value: summary.length_percentiles.p50.toLocaleString(),
                          unit: '字符',
                        },
                        { label: '正文长度 P90', value: summary.length_percentiles.p90.toLocaleString(), unit: '字符' },
                        { label: '扫描版 PDF', value: scannedPdfCount, unit: '份' },
                      ].map(({ label, value, unit }) => (
                        <div key={label}>
                          <dt>{label}</dt>
                          <dd>
                            <span>{value}</span>
                            {unit ? <small>{unit}</small> : null}
                          </dd>
                        </div>
                      ))}
                    </dl>
                    <section className={ws.section}>
                      <div className={ws.sectionHeading}>
                        <h2 className={ws.sectionTitle}>问题清单</h2>
                        {charts.activeFindings.length ? (
                          <span className={ws.muted}>{charts.activeFindings.length} 类问题</span>
                        ) : null}
                      </div>
                      {charts.activeFindings.length ? (
                        <div className={ws.tableScroll}>
                          <table className={ws.table} aria-label="画像问题清单">
                            <thead>
                              <tr>
                                <th>问题与说明</th>
                                <th>级别</th>
                                <th>命中文件</th>
                                <th>
                                  <span className="sr-only">操作</span>
                                </th>
                              </tr>
                            </thead>
                            <tbody>
                              {charts.activeFindings.map((finding) => (
                                <tr key={finding.key}>
                                  <td>
                                    <strong className="font-medium">{finding.label}</strong>
                                    {finding.description ? <p>{finding.description}</p> : null}
                                  </td>
                                  <td>
                                    <span
                                      className={
                                        finding.severity === 'error'
                                          ? 'text-destructive'
                                          : finding.severity === 'warning'
                                            ? ws.warning
                                            : ws.muted
                                      }
                                    >
                                      {finding.severity === 'error'
                                        ? '错误'
                                        : finding.severity === 'warning'
                                          ? '注意'
                                          : '提示'}
                                    </span>
                                  </td>
                                  <td className="tabular-nums">{finding.count}</td>
                                  <td className="text-right">
                                    <Button
                                      variant="ghost"
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
                        <p className={ws.muted}>当前画像没有问题命中记录。</p>
                      )}
                      {charts.zeroFindings.length ? (
                        <details className="mt-4 text-sm">
                          <summary className="cursor-pointer text-muted-foreground">
                            未命中的问题类型 · {charts.zeroFindings.length} 项
                          </summary>
                          <p className="mt-2 text-xs text-muted-foreground">未采集的检测指标不计为通过。</p>
                          <div className="mt-3 flex flex-wrap gap-3">
                            {charts.zeroFindings.map((finding) => (
                              <span key={finding.key}>{finding.label}</span>
                            ))}
                          </div>
                        </details>
                      ) : null}
                    </section>
                    <section className={ws.section}>
                      <h2 className={ws.sectionTitle}>最近有效扫描</h2>
                      <div className="mt-3 flex flex-wrap items-center gap-4 text-sm">
                        <time dateTime={latestValidScan?.finished_at ?? undefined}>{completedAtLabel}</time>
                        <span className="text-muted-foreground">统计更新于 {generatedAtLabel}</span>
                        {scanRunning && effectiveScanRun !== null ? <span>{effectiveScanRun.progress}%</span> : null}
                      </div>
                      {effectiveScanRun !== null && effectiveScanRun.error_message !== null ? (
                        <p className="mt-3 text-sm text-destructive">
                          <span className="font-medium">
                            最近一次扫描尝试{formatProfileRunStatus(effectiveScanRun.status)}：
                          </span>
                          {effectiveScanRun.error_message}
                        </p>
                      ) : null}
                    </section>
                  </TabsContent>
                  <TabsContent value="distribution" className={ws.tabContent}>
                    <Tabs defaultValue="documents">
                      <TabsList className={styles.segmentedTabs} aria-label="分布分析分类">
                        <TabsTrigger value="documents">文档分布</TabsTrigger>
                        <TabsTrigger value="chunks">切片质量</TabsTrigger>
                        <TabsTrigger value="risk">解析与风险</TabsTrigger>
                      </TabsList>
                      <TabsContent value="documents" className={ws.tabContent}>
                        <ProfileDistribution
                          categories={[
                            '格式分布',
                            '状态分布',
                            '长度分布',
                            'PDF 扫描占比',
                            '文件大小分布',
                            '页数分布',
                            '语言分布',
                            '目录分布',
                          ]}
                          hasData={[
                            charts.fileTypes,
                            charts.statuses,
                            charts.lengths,
                            charts.pdfScans,
                            charts.fileSizes,
                            charts.pageCounts,
                            charts.languages,
                            charts.directories,
                          ].some((rows) => rows.some((row) => row.value > 0))}
                          description={distributionEmptyDescription}
                        >
                          <Panel variant="seamless" className={profilePanelClass}>
                            <ProfileCardHeader title="格式分布" caption="文件类型占比" />
                            <ProfileChart rows={charts.fileTypes}>
                              <PieChart>
                                <Tooltip
                                  contentStyle={{
                                    backgroundColor: 'hsl(var(--popover))',
                                    color: 'hsl(var(--popover-foreground))',
                                    borderColor: 'hsl(var(--border))',
                                  }}
                                  itemStyle={{ color: 'hsl(var(--popover-foreground))' }}
                                />
                                <Pie
                                  data={charts.fileTypes}
                                  dataKey="value"
                                  nameKey="name"
                                  innerRadius={42}
                                  outerRadius={72}
                                  paddingAngle={2}
                                />
                              </PieChart>
                            </ProfileChart>
                          </Panel>
                          <Panel variant="seamless" className={profilePanelClass}>
                            <ProfileCardHeader title="状态分布" caption="按文档处理状态聚合" />
                            <ProfileChart rows={charts.statuses}>
                              <BarChart data={charts.statuses}>
                                <CartesianGrid strokeDasharray="3 3" />
                                <XAxis dataKey="name" fontSize={12} />
                                <YAxis allowDecimals={false} fontSize={12} />
                                <Tooltip
                                  contentStyle={{
                                    backgroundColor: 'hsl(var(--popover))',
                                    color: 'hsl(var(--popover-foreground))',
                                    borderColor: 'hsl(var(--border))',
                                  }}
                                  itemStyle={{ color: 'hsl(var(--popover-foreground))' }}
                                />
                                <Bar
                                  isAnimationActive={false}
                                  dataKey="value"
                                  fill="hsl(var(--chart-1))"
                                  radius={[6, 6, 0, 0]}
                                />
                              </BarChart>
                            </ProfileChart>
                          </Panel>
                          <Panel variant="seamless" className={profilePanelClass}>
                            <ProfileCardHeader title="长度分布" caption="按字符长度区间统计" />
                            <ProfileChart rows={charts.lengths}>
                              <BarChart data={charts.lengths}>
                                <CartesianGrid strokeDasharray="3 3" />
                                <XAxis dataKey="name" fontSize={12} />
                                <YAxis allowDecimals={false} fontSize={12} />
                                <Tooltip
                                  contentStyle={{
                                    backgroundColor: 'hsl(var(--popover))',
                                    color: 'hsl(var(--popover-foreground))',
                                    borderColor: 'hsl(var(--border))',
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
                            </ProfileChart>
                          </Panel>
                          <Panel variant="seamless" className={profilePanelClass}>
                            <ProfileCardHeader title="PDF 扫描占比" caption="扫描件、文本型与未知类型" />
                            <ProfileChart rows={charts.pdfScans}>
                              <PieChart>
                                <Tooltip
                                  contentStyle={{
                                    backgroundColor: 'hsl(var(--popover))',
                                    color: 'hsl(var(--popover-foreground))',
                                    borderColor: 'hsl(var(--border))',
                                  }}
                                  itemStyle={{ color: 'hsl(var(--popover-foreground))' }}
                                />
                                <Pie
                                  isAnimationActive={false}
                                  data={charts.pdfScans}
                                  dataKey="value"
                                  nameKey="name"
                                  innerRadius={42}
                                  outerRadius={72}
                                  paddingAngle={2}
                                />
                              </PieChart>
                            </ProfileChart>
                          </Panel>
                          <Panel variant="seamless" className={profilePanelClass}>
                            <ProfileCardHeader title="文件大小分布" caption="用于发现异常大文件或碎片文件" />
                            <ProfileChart rows={charts.fileSizes}>
                              <BarChart data={charts.fileSizes}>
                                <CartesianGrid strokeDasharray="3 3" />
                                <XAxis dataKey="name" fontSize={12} />
                                <YAxis allowDecimals={false} fontSize={12} />
                                <Tooltip
                                  contentStyle={{
                                    backgroundColor: 'hsl(var(--popover))',
                                    color: 'hsl(var(--popover-foreground))',
                                    borderColor: 'hsl(var(--border))',
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
                            </ProfileChart>
                          </Panel>
                          <Panel variant="seamless" className={profilePanelClass}>
                            <ProfileCardHeader title="页数分布" caption="PDF / Office 页数画像" />
                            <ProfileChart rows={charts.pageCounts}>
                              <BarChart data={charts.pageCounts}>
                                <CartesianGrid strokeDasharray="3 3" />
                                <XAxis dataKey="name" fontSize={12} />
                                <YAxis allowDecimals={false} fontSize={12} />
                                <Tooltip
                                  contentStyle={{
                                    backgroundColor: 'hsl(var(--popover))',
                                    color: 'hsl(var(--popover-foreground))',
                                    borderColor: 'hsl(var(--border))',
                                  }}
                                  itemStyle={{ color: 'hsl(var(--popover-foreground))' }}
                                />
                                <Bar
                                  isAnimationActive={false}
                                  dataKey="value"
                                  fill="hsl(var(--chart-7))"
                                  radius={[6, 6, 0, 0]}
                                />
                              </BarChart>
                            </ProfileChart>
                          </Panel>
                          <Panel variant="seamless" className={profilePanelClass}>
                            <ProfileCardHeader title="语言分布" caption="中文、英文、混合和未知语言占比" />
                            <ProfileChart rows={charts.languages}>
                              <PieChart>
                                <Tooltip
                                  contentStyle={{
                                    backgroundColor: 'hsl(var(--popover))',
                                    color: 'hsl(var(--popover-foreground))',
                                    borderColor: 'hsl(var(--border))',
                                  }}
                                  itemStyle={{ color: 'hsl(var(--popover-foreground))' }}
                                />
                                <Pie
                                  data={charts.languages}
                                  dataKey="value"
                                  nameKey="name"
                                  innerRadius={42}
                                  outerRadius={72}
                                  paddingAngle={2}
                                />
                              </PieChart>
                            </ProfileChart>
                          </Panel>
                          <Panel variant="seamless" className={profilePanelClass}>
                            <ProfileCardHeader
                              title="目录分布"
                              action={
                                <ProfileBucketSelect
                                  label="选择目录"
                                  rows={charts.directories}
                                  onOpen={(key) => openBucket('directory', key)}
                                />
                              }
                            />
                            <ProfileChart rows={charts.directories}>
                              <BarChart data={charts.directories}>
                                <CartesianGrid strokeDasharray="3 3" />
                                <XAxis dataKey="name" fontSize={12} interval={0} />
                                <YAxis allowDecimals={false} fontSize={12} />
                                <Tooltip
                                  contentStyle={{
                                    backgroundColor: 'hsl(var(--popover))',
                                    color: 'hsl(var(--popover-foreground))',
                                    borderColor: 'hsl(var(--border))',
                                  }}
                                  itemStyle={{ color: 'hsl(var(--popover-foreground))' }}
                                />
                                <Bar
                                  dataKey="value"
                                  fill="hsl(var(--chart-5))"
                                  radius={[6, 6, 0, 0]}
                                  onClick={(entry) => {
                                    const key = entry.payload.key
                                    if (key !== null) openBucket('directory', key)
                                  }}
                                >
                                  {charts.directories.map((row) => (
                                    <Cell
                                      key={JSON.stringify([row.key])}
                                      cursor={row.key === null ? 'default' : 'pointer'}
                                    />
                                  ))}
                                </Bar>
                              </BarChart>
                            </ProfileChart>
                          </Panel>
                        </ProfileDistribution>
                      </TabsContent>
                      <TabsContent value="chunks" className={ws.tabContent}>
                        <ProfileDistribution
                          categories={['切片数量分布', '平均切片长度', '切片长度分布', '切块目标检查']}
                          hasData={
                            [charts.chunkCounts, charts.averageChunkChars, charts.chunkLengths].some((rows) =>
                              rows.some((row) => row.value > 0),
                            ) || charts.chunkTargets.length > 0
                          }
                          description={distributionEmptyDescription}
                        >
                          <Panel variant="seamless" className={profilePanelClass}>
                            <ProfileCardHeader title="切片数量分布" caption="每个文档生成的切片数量" />
                            <ProfileChart rows={charts.chunkCounts}>
                              <BarChart data={charts.chunkCounts}>
                                <CartesianGrid strokeDasharray="3 3" />
                                <XAxis dataKey="name" fontSize={12} />
                                <YAxis allowDecimals={false} fontSize={12} />
                                <Tooltip
                                  contentStyle={{
                                    backgroundColor: 'hsl(var(--popover))',
                                    color: 'hsl(var(--popover-foreground))',
                                    borderColor: 'hsl(var(--border))',
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
                            </ProfileChart>
                          </Panel>
                          <Panel variant="seamless" className={profilePanelClass}>
                            <ProfileCardHeader title="平均切片长度" caption="按文档聚合的平均切片长度" />
                            <ProfileChart rows={charts.averageChunkChars}>
                              <BarChart data={charts.averageChunkChars}>
                                <CartesianGrid strokeDasharray="3 3" />
                                <XAxis dataKey="name" fontSize={12} />
                                <YAxis allowDecimals={false} fontSize={12} />
                                <Tooltip
                                  contentStyle={{
                                    backgroundColor: 'hsl(var(--popover))',
                                    color: 'hsl(var(--popover-foreground))',
                                    borderColor: 'hsl(var(--border))',
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
                            </ProfileChart>
                          </Panel>
                          <Panel variant="seamless" className={profilePanelClass}>
                            <ProfileCardHeader title="切片长度分布" caption="按切片粒度统计字符长度" />
                            <ProfileChart rows={charts.chunkLengths}>
                              <BarChart data={charts.chunkLengths}>
                                <CartesianGrid strokeDasharray="3 3" />
                                <XAxis dataKey="name" fontSize={12} />
                                <YAxis allowDecimals={false} fontSize={12} />
                                <Tooltip
                                  contentStyle={{
                                    backgroundColor: 'hsl(var(--popover))',
                                    color: 'hsl(var(--popover-foreground))',
                                    borderColor: 'hsl(var(--border))',
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
                            </ProfileChart>
                          </Panel>
                          <Panel variant="seamless" className={cn(profilePanelClass, 'lg:col-span-2')}>
                            <div className="mb-3 flex items-start justify-between gap-4">
                              <div>
                                <div className={profileSectionTitleClass}>切块目标检查</div>
                                <div className={profileSectionCaptionClass}>
                                  检查 token 分布、正文覆盖和重叠成本；缺统计只提示补采集，不代表入库失败。
                                </div>
                              </div>
                              <Badge
                                variant="outline"
                                className="shrink-0 border-border bg-card/70 px-2 py-0.5 text-xs font-mono text-muted-foreground"
                              >
                                可选门禁
                              </Badge>
                            </div>

                            {charts.chunkTargets.length > 0 ? (
                              <div className="grid gap-2 md:grid-cols-3">
                                {charts.chunkTargets.map((target) => (
                                  <div
                                    key={target.key}
                                    className={cn(
                                      'relative overflow-hidden rounded-xl border bg-card/60 px-2.5 py-2 shadow-[inset_0_1px_0_rgba(255,255,255,0.7)] dark:bg-muted/20',
                                      target.status === 'fail'
                                        ? 'border-destructive/30'
                                        : target.status === 'warn'
                                          ? 'border-warning/30'
                                          : 'border-border/60 dark:border-border/60',
                                    )}
                                  >
                                    <div
                                      className={cn(
                                        'absolute inset-y-2 left-0 w-1 rounded-r-full',
                                        target.status === 'fail'
                                          ? 'bg-destructive'
                                          : target.status === 'warn'
                                            ? 'bg-warning'
                                            : 'bg-info/30',
                                      )}
                                    />
                                    <div className="min-w-0">
                                      <div className="flex min-w-0 items-center gap-1.5 pl-2">
                                        <div className="truncate text-[12px] font-semibold text-foreground/85">
                                          {formatChunkTargetLabel(target.label)}
                                        </div>
                                        <Badge
                                          variant={targetBadgeVariant(target.status)}
                                          className="h-5 shrink-0 px-1.5 text-xs font-mono uppercase"
                                        >
                                          {target.status}
                                        </Badge>
                                      </div>
                                      {target.message !== null ? (
                                        <div className="mt-1 line-clamp-2 pl-2 text-xs leading-4 text-muted-foreground text-pretty">
                                          {target.message}
                                        </div>
                                      ) : null}
                                    </div>

                                    {target.suggestions.length > 0 ? (
                                      <div className="mt-2 rounded-lg bg-muted/40 px-2.5 py-1.5 text-xs leading-4 text-muted-foreground/70 dark:bg-muted/30">
                                        {target.suggestions[0]}
                                        {target.suggestions.length > 1 ? (
                                          <span className="ml-1 text-muted-foreground/45">
                                            +{target.suggestions.length - 1}
                                          </span>
                                        ) : null}
                                      </div>
                                    ) : null}
                                  </div>
                                ))}
                              </div>
                            ) : (
                              <div className="py-8 text-center text-xs text-muted-foreground">
                                暂无数据（可运行深度扫描补齐 chunk token/coverage 等指标）
                              </div>
                            )}
                          </Panel>
                        </ProfileDistribution>
                      </TabsContent>
                      <TabsContent value="risk" className={ws.tabContent}>
                        <ProfileDistribution
                          categories={['解析质量分布', '解析路由', '质量桶分布', 'PII 命中', '密钥 / Token 命中']}
                          hasData={
                            [
                              charts.parseQuality,
                              charts.parsingBackends,
                              charts.qualityBuckets,
                              charts.pii,
                              charts.secrets,
                            ].some((rows) => rows.some((row) => row.value > 0)) ||
                            summary.parsing_provenance.docs_with_provenance > 0 ||
                            summary.parsing_provenance.fallback_docs > 0 ||
                            [
                              summary.parsing_provenance.elapsed_ms_percentiles.p25,
                              summary.parsing_provenance.elapsed_ms_percentiles.p50,
                              summary.parsing_provenance.elapsed_ms_percentiles.p75,
                              summary.parsing_provenance.elapsed_ms_percentiles.p90,
                              summary.parsing_provenance.elapsed_ms_percentiles.p99,
                            ].some((value) => value > 0)
                          }
                          description={distributionEmptyDescription}
                        >
                          <Panel variant="seamless" className={profilePanelClass}>
                            <ProfileCardHeader
                              title="解析质量分布"
                              caption="解析文本质量评分区间"
                              action={
                                parseLowQualityFinding ? (
                                  <Button
                                    variant="outline"
                                    className="h-8 px-2 gap-1 text-xs"
                                    onClick={() => detachPromise(openFinding(parseLowQualityFinding))}
                                  >
                                    <FileSearch className="w-3.5 h-3.5" />
                                    低质量
                                  </Button>
                                ) : null
                              }
                            />
                            <ProfileChart rows={charts.parseQuality}>
                              <BarChart data={charts.parseQuality}>
                                <CartesianGrid strokeDasharray="3 3" />
                                <XAxis dataKey="name" fontSize={12} />
                                <YAxis allowDecimals={false} fontSize={12} />
                                <Tooltip
                                  contentStyle={{
                                    backgroundColor: 'hsl(var(--popover))',
                                    color: 'hsl(var(--popover-foreground))',
                                    borderColor: 'hsl(var(--border))',
                                  }}
                                  itemStyle={{ color: 'hsl(var(--popover-foreground))' }}
                                />
                                <Bar
                                  isAnimationActive={false}
                                  dataKey="value"
                                  fill="hsl(var(--chart-1))"
                                  radius={[6, 6, 0, 0]}
                                />
                              </BarChart>
                            </ProfileChart>
                          </Panel>
                          <Panel variant="seamless" className={profilePanelClass}>
                            <ProfileCardHeader title="解析路由" />

                            <ProfileChart rows={charts.parsingBackends}>
                              <BarChart data={charts.parsingBackends}>
                                <CartesianGrid strokeDasharray="3 3" />
                                <XAxis dataKey="name" fontSize={12} />
                                <YAxis allowDecimals={false} fontSize={12} />
                                <Tooltip
                                  contentStyle={{
                                    backgroundColor: 'hsl(var(--popover))',
                                    color: 'hsl(var(--popover-foreground))',
                                    borderColor: 'hsl(var(--border))',
                                  }}
                                  itemStyle={{ color: 'hsl(var(--popover-foreground))' }}
                                />
                                <Bar
                                  isAnimationActive={false}
                                  dataKey="value"
                                  fill="hsl(var(--chart-1))"
                                  radius={[6, 6, 0, 0]}
                                />
                              </BarChart>
                            </ProfileChart>

                            <div className="mt-2 grid grid-cols-2 gap-2">
                              <div className="rounded-lg border border-border/50 bg-muted/20 p-2">
                                <div className="text-xs text-muted-foreground">覆盖文档</div>
                                <div className="mt-0.5 font-mono text-xs font-semibold tabular-nums">
                                  {summary.parsing_provenance.docs_with_provenance}
                                </div>
                              </div>
                              <div className="rounded-lg border border-border/50 bg-muted/20 p-2">
                                <div className="text-xs text-muted-foreground">后备解析</div>
                                <div className="mt-0.5 font-mono text-xs font-semibold tabular-nums">
                                  {summary.parsing_provenance.fallback_docs}
                                </div>
                              </div>
                              <div className="rounded-lg border border-border/50 bg-muted/20 p-2">
                                <div className="text-xs text-muted-foreground">P50 耗时 ms</div>
                                <div className="mt-0.5 font-mono text-xs font-semibold tabular-nums">
                                  {summary.parsing_provenance.elapsed_ms_percentiles.p50}
                                </div>
                              </div>
                              <div className="rounded-lg border border-border/50 bg-muted/20 p-2">
                                <div className="text-xs text-muted-foreground">P90 耗时 ms</div>
                                <div className="mt-0.5 font-mono text-xs font-semibold tabular-nums">
                                  {summary.parsing_provenance.elapsed_ms_percentiles.p90}
                                </div>
                              </div>

                              <div className="rounded-lg border border-border/50 bg-muted/20 p-2">
                                <div className="text-xs text-muted-foreground">后备率</div>
                                <div className="mt-0.5 font-mono text-xs font-semibold tabular-nums">
                                  {charts.fallbackRate === null ? '-' : `${(charts.fallbackRate * 100).toFixed(1)}%`}
                                </div>
                              </div>
                            </div>
                          </Panel>
                          <Panel variant="seamless" className={profilePanelClass}>
                            <ProfileCardHeader
                              title="质量桶分布"
                              action={
                                <ProfileBucketSelect
                                  label="选择质量桶"
                                  rows={charts.qualityBuckets}
                                  onOpen={(key) => openBucket('quality_bucket', key)}
                                />
                              }
                            />
                            <ProfileChart rows={charts.qualityBuckets}>
                              <BarChart data={charts.qualityBuckets}>
                                <CartesianGrid strokeDasharray="3 3" />
                                <XAxis dataKey="name" fontSize={12} interval={0} />
                                <YAxis allowDecimals={false} fontSize={12} />
                                <Tooltip
                                  contentStyle={{
                                    backgroundColor: 'hsl(var(--popover))',
                                    color: 'hsl(var(--popover-foreground))',
                                    borderColor: 'hsl(var(--border))',
                                  }}
                                  itemStyle={{ color: 'hsl(var(--popover-foreground))' }}
                                />
                                <Bar
                                  dataKey="value"
                                  fill="hsl(var(--chart-2))"
                                  radius={[6, 6, 0, 0]}
                                  cursor="pointer"
                                  onClick={(entry) => openBucket('quality_bucket', entry.payload.key)}
                                />
                              </BarChart>
                            </ProfileChart>
                          </Panel>
                          <Panel variant="seamless" className={profilePanelClass}>
                            <ProfileCardHeader title="PII 命中" caption="手机号、邮箱、身份证等敏感信息次数" />
                            <ProfileChart rows={charts.pii}>
                              <BarChart data={charts.pii}>
                                <CartesianGrid strokeDasharray="3 3" />
                                <XAxis dataKey="name" fontSize={12} />
                                <YAxis allowDecimals={false} fontSize={12} />
                                <Tooltip
                                  contentStyle={{
                                    backgroundColor: 'hsl(var(--popover))',
                                    color: 'hsl(var(--popover-foreground))',
                                    borderColor: 'hsl(var(--border))',
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
                            </ProfileChart>
                          </Panel>
                          <Panel variant="seamless" className={profilePanelClass}>
                            <ProfileCardHeader title="密钥 / Token 命中" caption="疑似密钥、Token 和凭证命中次数" />
                            <ProfileChart rows={charts.secrets}>
                              <BarChart data={charts.secrets}>
                                <CartesianGrid strokeDasharray="3 3" />
                                <XAxis dataKey="name" fontSize={12} />
                                <YAxis allowDecimals={false} fontSize={12} />
                                <Tooltip
                                  contentStyle={{
                                    backgroundColor: 'hsl(var(--popover))',
                                    color: 'hsl(var(--popover-foreground))',
                                    borderColor: 'hsl(var(--border))',
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
                            </ProfileChart>
                          </Panel>
                        </ProfileDistribution>
                      </TabsContent>
                    </Tabs>
                  </TabsContent>
                </>
              )}
              <TabsContent value="history" className={ws.tabContent}>
                <div className={styles.historyActions}>
                  <Button
                    variant="ghost"
                    disabled={scanRunsQuery.isFetching}
                    onClick={() => {
                      void scanRunsQuery.refetch()
                    }}
                  >
                    重新读取扫描历史
                  </Button>
                </div>
                {scanRunsQuery.isError && latestValidScan === undefined ? (
                  <WorkspaceNotice
                    retry={() => {
                      void scanRunsQuery.refetch()
                    }}
                    pending={scanRunsQuery.isFetching}
                  >
                    {scanRuns === undefined ? null : '更新失败，保留上次完整历史与选择。'}
                    {formatApiError(scanRunsQuery.error, '扫描历史读取失败')}
                  </WorkspaceNotice>
                ) : null}
                {scanRunsQuery.isFetching && scanRuns !== undefined ? (
                  <p role="status" className={ws.muted}>
                    正在重新读取历史，当前显示上次完整结果。
                  </p>
                ) : null}
                {scanRuns === undefined || completedRuns === undefined ? (
                  <div className={styles.loading} role="status">
                    {scanRunsQuery.isPending ? '正在读取完整扫描历史…' : '扫描历史暂不可用。'}
                  </div>
                ) : scanRuns.length === 0 ? (
                  <EmptyState
                    icon={BarChart3}
                    title="尚无扫描记录"
                    description={hasDocuments ? '首次扫描完成后可查看记录。' : '文档入库后才能扫描。'}
                    className={styles.guide}
                  >
                    {hasDocuments ? (
                      <Button className={styles.primaryAction} onClick={() => setScanConfigOpen(true)}>
                        配置深度扫描
                      </Button>
                    ) : (
                      <Button className={styles.primaryAction} asChild>
                        <Link href={uploadHref}>上传入库文档</Link>
                      </Button>
                    )}
                  </EmptyState>
                ) : (
                  <div id="prof-history">
                    <Panel variant="seamless" className={styles.historyPanel}>
                      <div className="mb-3">
                        <div>
                          <p className={profileSectionCaptionClass}>查看历史扫描记录，并对比两次扫描的指标变化。</p>
                        </div>
                      </div>

                      <div className={cn(ws.tableScroll, styles.scanTable)}>
                        <table aria-label="数据集画像扫描运行记录" className="w-full text-left text-xs">
                          <thead className="bg-muted/40 text-muted-foreground">
                            <tr>
                              <th className="px-2 py-1.5 font-medium">创建时间</th>
                              <th className="px-2 py-1.5 font-medium">状态</th>
                              <th className="px-2 py-1.5 font-medium">进度</th>
                              <th className="px-2 py-1.5 font-medium">配置</th>
                              <th className="px-2 py-1.5 font-medium">错误</th>
                            </tr>
                          </thead>
                          <tbody>
                            {scanRuns.map((r) => (
                              <tr key={r.id} className="border-t border-border/60">
                                <td className="px-2 py-1.5 font-mono text-xs">
                                  {r.created_at ? formatDate(r.created_at) : '-'}
                                </td>
                                <td className="px-2 py-1.5">
                                  <Badge variant="outline" className="font-mono text-xs">
                                    {formatProfileRunStatus(r.status)}
                                  </Badge>
                                </td>
                                <td className="px-2 py-1.5 font-mono text-xs">{r.progress}%</td>
                                <td className="px-2 py-1.5 font-mono text-xs text-muted-foreground">
                                  PDF:{formatProfileScanOption(r.config.backfill_pdf_quality)} · 文本:
                                  {formatProfileScanOption(r.config.backfill_text_quality)} · 切片:
                                  {formatProfileScanOption(r.config.backfill_chunk_stats)} · 哈希:
                                  {formatProfileScanOption(r.config.compute_file_hash)}
                                </td>
                                <td className="px-2 py-1.5 text-xs text-destructive">{r.error_message}</td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>

                      <div className={styles.historyComparison}>
                        <div>
                          <div className="mb-2 flex items-center justify-between gap-2">
                            <div className="text-[13px] font-semibold text-foreground/85">快照对比</div>
                            <Badge variant="outline" className="h-5 px-1.5 text-xs font-mono text-muted-foreground">
                              已完成 {completedRuns.length}
                            </Badge>
                          </div>

                          {completedRuns.length >= 2 || compareA !== null || compareB !== null ? (
                            <>
                              <div className="grid grid-cols-1 gap-2 md:grid-cols-2">
                                <div className="space-y-1.5">
                                  <Label htmlFor={`${scanFormId}-baseline`} className="text-xs text-muted-foreground">
                                    基准快照
                                  </Label>
                                  <Select value={compareA === null ? '' : compareA} onValueChange={setCompareA}>
                                    <SelectTrigger
                                      id={`${scanFormId}-baseline`}
                                      className="h-8 bg-card/70 text-xs dark:bg-card/60"
                                    >
                                      <SelectValue placeholder="选择基准快照" />
                                    </SelectTrigger>
                                    <SelectContent>
                                      {compareA !== null && baselineRun === undefined ? (
                                        <SelectItem value={compareA} disabled>
                                          {compareA}（当前历史未包含）
                                        </SelectItem>
                                      ) : null}
                                      {completedRuns.map((r) => (
                                        <SelectItem key={r.id} value={r.id} className="text-xs">
                                          {r.created_at ? formatDate(r.created_at) : r.id.slice(0, 8)} ·{' '}
                                          {r.id.slice(0, 8)}
                                        </SelectItem>
                                      ))}
                                    </SelectContent>
                                  </Select>
                                </div>
                                <div className="space-y-1.5">
                                  <Label htmlFor={`${scanFormId}-comparison`} className="text-xs text-muted-foreground">
                                    对比快照
                                  </Label>
                                  <Select value={compareB === null ? '' : compareB} onValueChange={setCompareB}>
                                    <SelectTrigger
                                      id={`${scanFormId}-comparison`}
                                      className="h-8 bg-card/70 text-xs dark:bg-card/60"
                                    >
                                      <SelectValue placeholder="选择对比快照" />
                                    </SelectTrigger>
                                    <SelectContent>
                                      {compareB !== null && comparisonRun === undefined ? (
                                        <SelectItem value={compareB} disabled>
                                          {compareB}（当前历史未包含）
                                        </SelectItem>
                                      ) : null}
                                      {completedRuns.map((r) => (
                                        <SelectItem key={r.id} value={r.id} className="text-xs">
                                          {r.created_at ? formatDate(r.created_at) : r.id.slice(0, 8)} ·{' '}
                                          {r.id.slice(0, 8)}
                                        </SelectItem>
                                      ))}
                                    </SelectContent>
                                  </Select>
                                </div>
                              </div>

                              {compareDelta.status === 'ready' ? (
                                <div className="mt-3 grid grid-cols-2 gap-2 lg:grid-cols-3">
                                  <div className="border-b border-border py-3">
                                    <div className="text-xs text-muted-foreground">文档数 Δ</div>
                                    <div className="mt-0.5 font-mono text-xs font-semibold">
                                      {compareDelta.docs >= 0 ? `+${compareDelta.docs}` : String(compareDelta.docs)}
                                    </div>
                                  </div>
                                  <div className="border-b border-border py-3">
                                    <div className="text-xs text-muted-foreground">总大小 Δ</div>
                                    <div className="mt-0.5 font-mono text-xs font-semibold">
                                      {compareDelta.bytes >= 0 ? '+' : '-'}
                                      {formatFileSize(Math.abs(compareDelta.bytes))}
                                    </div>
                                  </div>
                                  <div className="border-b border-border py-3">
                                    <div className="text-xs text-muted-foreground">P90 长度 Δ</div>
                                    <div className="mt-0.5 font-mono text-xs font-semibold">
                                      {compareDelta.p90 >= 0 ? `+${compareDelta.p90}` : String(compareDelta.p90)}
                                    </div>
                                  </div>
                                  <div className="border-b border-border py-3">
                                    <div className="text-xs text-muted-foreground">扫描 PDF Δ</div>
                                    <div className="mt-0.5 font-mono text-xs font-semibold">
                                      {compareDelta.scanned >= 0
                                        ? `+${compareDelta.scanned}`
                                        : String(compareDelta.scanned)}
                                    </div>
                                  </div>
                                  <div className="border-b border-border py-3">
                                    <div className="text-xs text-muted-foreground">PII 命中 Δ</div>
                                    <div className="mt-0.5 font-mono text-xs font-semibold">
                                      {compareDelta.pii >= 0 ? `+${compareDelta.pii}` : String(compareDelta.pii)}
                                    </div>
                                  </div>
                                  <div className="border-b border-border py-3">
                                    <div className="text-xs text-muted-foreground">Secrets 命中 Δ</div>
                                    <div className="mt-0.5 font-mono text-xs font-semibold">
                                      {compareDelta.secrets >= 0
                                        ? `+${compareDelta.secrets}`
                                        : String(compareDelta.secrets)}
                                    </div>
                                  </div>
                                </div>
                              ) : (
                                <div
                                  role={compareDelta.status === 'invalid' ? 'alert' : 'status'}
                                  className="mt-3 rounded-lg bg-muted/40 px-2.5 py-1.5 text-xs text-muted-foreground dark:bg-muted/20"
                                >
                                  {compareDelta.message}
                                </div>
                              )}
                            </>
                          ) : (
                            <div className="rounded-lg border border-dashed border-border/55 bg-muted/40 px-3 py-2 text-xs leading-4 text-muted-foreground dark:bg-muted/20">
                              <div className="font-medium text-foreground/75">暂无可对比快照</div>
                              <div className="mt-0.5">
                                至少需要 2 次已完成深度扫描；当前 {completedRuns.length}{' '}
                                次。完成后这里会出现基准/对比快照下拉。
                              </div>
                            </div>
                          )}
                        </div>
                      </div>
                    </Panel>
                  </div>
                )}
              </TabsContent>
            </Tabs>
          )}
        </div>
        <Dialog open={scanConfigOpen} onOpenChange={setScanConfigOpen}>
          <DialogContent className={ws.dialog}>
            <DialogHeader className={ws.dialogHeader}>
              <DialogTitle>深度扫描</DialogTitle>
              <DialogDescription>补齐现有文档的质量指标，不执行重新入库。</DialogDescription>
            </DialogHeader>
            <form
              id={scanFormId}
              className={ws.dialogBody}
              onSubmit={(event) => {
                event.preventDefault()
                void startDeepScan()
              }}
            >
              {scanSubmissionNotice}
              <div className={ws.formRows}>
                <div className={ws.formRow}>
                  <Label className="text-xs text-foreground/80">PDF 指标</Label>
                  <Switch
                    aria-label="PDF 指标"
                    checked={scanConfig.backfill_pdf_quality}
                    onCheckedChange={(value) => setScanConfig((prev) => ({ ...prev, backfill_pdf_quality: value }))}
                  />
                </div>
                <div className={ws.formRow}>
                  <Label className="text-xs text-foreground/80">文本质量</Label>
                  <Switch
                    aria-label="文本质量"
                    checked={scanConfig.backfill_text_quality}
                    onCheckedChange={(value) => setScanConfig((prev) => ({ ...prev, backfill_text_quality: value }))}
                  />
                </div>
                <div className={ws.formRow}>
                  <Label className="text-xs text-foreground/80">切片分布</Label>
                  <Switch
                    aria-label="切片分布"
                    checked={scanConfig.backfill_chunk_stats}
                    onCheckedChange={(value) => setScanConfig((prev) => ({ ...prev, backfill_chunk_stats: value }))}
                  />
                </div>
                <div className={ws.formRow}>
                  <Label className="text-xs text-foreground/80">文件哈希</Label>
                  <Switch
                    aria-label="文件哈希"
                    checked={scanConfig.compute_file_hash}
                    onCheckedChange={(value) => setScanConfig((prev) => ({ ...prev, compute_file_hash: value }))}
                  />
                </div>
                <div className={ws.formRow}>
                  <Label htmlFor={`${scanFormId}-max-documents`} className="text-xs text-foreground/80">
                    最大文档数
                  </Label>
                  <Input
                    id={`${scanFormId}-max-documents`}
                    aria-label="最大文档数"
                    type="number"
                    min={0}
                    max={1_000_000}
                    step={1}
                    value={maxDocuments}
                    placeholder="不限"
                    onChange={(event) => setMaxDocuments(event.target.value)}
                    className="h-7 w-20 font-mono text-xs"
                  />
                </div>
              </div>
            </form>
            <div className={ws.dialogFooter}>
              <Button variant="ghost" onClick={() => setScanConfigOpen(false)}>
                关闭
              </Button>
              <Button type="submit" form={scanFormId} disabled={scanBusy}>
                {scanBusy ? <Loader2 className="animate-spin motion-reduce:animate-none" /> : <Sparkles />}
                {scanSubmission.status === 'pending'
                  ? '正在提交…'
                  : scanRunning
                    ? '正在扫描…'
                    : scanSubmission.status === 'unconfirmed'
                      ? '重新提交扫描'
                      : '开始扫描'}
              </Button>
            </div>
          </DialogContent>
        </Dialog>
        <Dialog open={findingOpen} onOpenChange={setFindingOpen}>
          <DialogContent className={ws.dialog}>
            <DialogHeader className={ws.dialogHeader}>
              <DialogTitle className="text-xl font-bold text-foreground flex items-center justify-between gap-3">
                <span className="flex items-center gap-2">
                  {selectedFinding?.label}
                  {selectedFinding ? (
                    <Badge variant={findingBadgeVariant(selectedFinding.severity)} className="font-mono text-xs">
                      {selectedFinding.count}
                    </Badge>
                  ) : null}
                </span>
                {selectedFinding?.key === 'parse_low_quality' && findingRes !== null && findingRes.items.length > 0 ? (
                  <Button
                    variant="outline"
                    size="sm"
                    className="gap-2"
                    disabled={findingRes.items.some((row) => retryingIds.has(row.id))}
                    onClick={() => void retryDocuments(findingRes.items, 'parse_low_quality')}
                    title="仅提交当前已加载的文档，每批最多 200 个"
                  >
                    <RefreshCw className="w-4 h-4" />
                    重试已加载的 {findingRes.items.length} 个
                  </Button>
                ) : null}
              </DialogTitle>
              <DialogDescription className="text-muted-foreground">
                点击文件名可查看文档详情。{selectedFinding?.description}
              </DialogDescription>
            </DialogHeader>

            <div className={ws.dialogBody}>
              {findingDocumentsQuery.error !== null ? (
                <WorkspaceNotice
                  retry={() => void findingDocumentsQuery.refetch()}
                  retryLabel="重新读取问题文档"
                  pending={findingLoading}
                >
                  {findingRes === null ? null : '更新失败，已保留当前清单。'}
                  {formatApiError(findingDocumentsQuery.error, '问题文档读取失败')}
                </WorkspaceNotice>
              ) : null}
              {findingRetryFeedback.map((feedback) => (
                <div
                  key={JSON.stringify(feedback.documentIds)}
                  role="status"
                  className="mb-3 text-sm text-muted-foreground"
                >
                  <p>{feedback.message}</p>
                  {feedback.failures.length > 0 ? (
                    <details>
                      <summary>查看未接受的文档</summary>
                      <ul>
                        {feedback.failures.map((failure) => (
                          <li key={`${failure.id}:${failure.reason}`}>
                            {failure.filename}：{failure.reason}
                          </li>
                        ))}
                      </ul>
                    </details>
                  ) : null}
                </div>
              ))}
              {(() => {
                if (findingDocumentsQuery.isError && findingRes === null) return null
                if (findingLoading && findingRes === null) {
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
                        showing {findingRes.items.length}/{findingRes.total}
                      </div>
                      <div className={ws.tableScroll}>
                        {findingRes.items.length === 0 ? <p role="status">当前问题没有匹配文档。</p> : null}
                        <table
                          aria-label={selectedFinding === null ? undefined : `${selectedFinding.label}文档清单`}
                          className="w-full text-left text-xs"
                        >
                          <thead className="bg-muted/40 text-muted-foreground">
                            <tr>
                              <th className="px-2 py-1.5 font-medium">文件名</th>
                              <th className="px-2 py-1.5 font-medium">类型</th>
                              <th className="px-2 py-1.5 font-medium">大小</th>
                              <th className="px-2 py-1.5 font-medium">状态</th>
                              <th className="px-2 py-1.5 font-medium">长度</th>
                              {selectedFinding?.key === 'parse_low_quality' ? (
                                <th className="px-2 py-1.5 font-medium text-right">操作</th>
                              ) : null}
                            </tr>
                          </thead>
                          <tbody>
                            {findingRes.items.map((d) => (
                              <tr key={d.id} className="border-t border-border/60 hover:bg-muted/20 transition-colors">
                                <td className="px-2 py-1.5">
                                  <DocumentDetailDialog
                                    document={{
                                      id: d.id,
                                      filename: d.filename,
                                      file_type: d.file_type,
                                      file_size: d.file_size,
                                      status: d.status,
                                      created_at: d.created_at,
                                      metadata: d.metadata,
                                    }}
                                    trigger={
                                      <button type="button" className="text-primary hover:underline">
                                        {d.filename}
                                      </button>
                                    }
                                  />
                                </td>
                                <td className="px-2 py-1.5 font-mono text-xs">{d.file_type}</td>
                                <td className="px-2 py-1.5 font-mono text-xs">{formatFileSize(d.file_size)}</td>
                                <td className="px-2 py-1.5">
                                  <Badge variant="outline" className="font-mono text-xs">
                                    {d.status}
                                  </Badge>
                                </td>
                                <td className="px-2 py-1.5 font-mono text-xs">{d.total_characters}</td>
                                {selectedFinding?.key === 'parse_low_quality' ? (
                                  <td className="px-2 py-1.5 text-right">
                                    <Button
                                      variant="outline"
                                      size="sm"
                                      className="h-8 px-2 gap-2 text-xs"
                                      disabled={retryingIds.has(d.id)}
                                      onClick={() => void retryDocuments([d], 'parse_low_quality')}
                                    >
                                      {retryingIds.has(d.id) ? (
                                        <Loader2 className="w-3.5 h-3.5 animate-spin motion-reduce:animate-none" />
                                      ) : (
                                        <RotateCcw className="w-3.5 h-3.5" />
                                      )}
                                      重试
                                    </Button>
                                  </td>
                                ) : null}
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
                          disabled={findingLoading || !hasNextFindingPage}
                        >
                          {findingLoading ? (
                            <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" />
                          ) : null}
                          加载更多
                        </Button>
                      </div>
                    </div>
                  )
                } else {
                  return <div className="py-10 text-center text-[11px] text-muted-foreground/60">暂无数据</div>
                }
              })()}
            </div>
          </DialogContent>
        </Dialog>

        <Dialog open={bucketOpen} onOpenChange={setBucketOpen}>
          <DialogContent className={ws.dialog}>
            <DialogHeader className={ws.dialogHeader}>
              <DialogTitle className="text-xl font-bold text-foreground flex items-center gap-2">
                {bucketSelection === null
                  ? null
                  : `${PROFILE_BUCKET_LABELS[bucketSelection.dimension]}: ${bucketSelection.key}`}
                {bucketRes ? (
                  <Badge variant="outline" className="font-mono text-xs">
                    {bucketRes.total}
                  </Badge>
                ) : null}
              </DialogTitle>
              <DialogDescription className="text-muted-foreground">
                Preview 已做 PII/Secrets 脱敏（best-effort）。点击文件名可查看文档详情。
              </DialogDescription>
            </DialogHeader>

            <div className={ws.dialogBody}>
              {bucketDocumentsQuery.error !== null ? (
                <WorkspaceNotice
                  retry={() => void bucketDocumentsQuery.refetch()}
                  retryLabel="重新读取分桶文档"
                  pending={bucketLoading}
                >
                  {bucketRes === null ? null : '更新失败，已保留当前清单。'}
                  {formatApiError(bucketDocumentsQuery.error, '分桶文档读取失败')}
                </WorkspaceNotice>
              ) : null}
              {(() => {
                if (bucketDocumentsQuery.isError && bucketRes === null) return null
                if (bucketLoading && bucketRes === null) {
                  return (
                    <div className="py-10 flex items-center justify-center text-muted-foreground">
                      <Loader2 className="w-5 h-5 animate-spin motion-reduce:animate-none mr-2" />
                      加载中…
                    </div>
                  )
                } else if (bucketRes) {
                  return (
                    <div className="space-y-3">
                      <div className="text-xs text-muted-foreground font-mono">
                        showing {bucketRes.items.length}/{bucketRes.total}
                      </div>
                      <div className={ws.tableScroll}>
                        {bucketRes.items.length === 0 ? <p role="status">当前分桶没有匹配文档。</p> : null}
                        <table aria-label="画像分桶文档清单" className="w-full text-left text-xs">
                          <thead className="bg-muted/40 text-muted-foreground">
                            <tr>
                              <th className="px-2 py-1.5 font-medium">文件名</th>
                              <th className="px-2 py-1.5 font-medium">类型</th>
                              <th className="px-2 py-1.5 font-medium">大小</th>
                              <th className="px-2 py-1.5 font-medium">状态</th>
                              <th className="px-2 py-1.5 font-medium">长度</th>
                              <th className="px-2 py-1.5 font-medium">样例（脱敏）</th>
                            </tr>
                          </thead>
                          <tbody>
                            {bucketRes.items.map((d) => (
                              <tr key={d.id} className="border-t border-border/60 hover:bg-muted/20 transition-colors">
                                <td className="px-2 py-1.5">
                                  <DocumentDetailDialog
                                    document={{
                                      id: d.id,
                                      filename: d.filename,
                                      file_type: d.file_type,
                                      file_size: d.file_size,
                                      status: d.status,
                                      created_at: d.created_at,
                                      metadata: d.metadata,
                                    }}
                                    trigger={
                                      <button type="button" className="text-primary hover:underline">
                                        {d.filename}
                                      </button>
                                    }
                                  />
                                </td>
                                <td className="px-2 py-1.5 font-mono text-xs">{d.file_type}</td>
                                <td className="px-2 py-1.5 font-mono text-xs">{formatFileSize(d.file_size)}</td>
                                <td className="px-2 py-1.5">
                                  <Badge variant="outline" className="font-mono text-xs">
                                    {d.status}
                                  </Badge>
                                </td>
                                <td className="px-2 py-1.5 font-mono text-xs">{d.total_characters}</td>
                                <td className="px-2 py-1.5 max-w-[520px]">
                                  {d.preview !== null ? (
                                    <div className="text-xs text-muted-foreground line-clamp-2" title={d.preview}>
                                      {d.preview}
                                      {d.preview_truncated ? '…' : null}
                                    </div>
                                  ) : (
                                    <span className="text-xs text-muted-foreground">-</span>
                                  )}
                                </td>
                              </tr>
                            ))}
                          </tbody>
                        </table>
                      </div>

                      <div className="flex items-center justify-between">
                        <div className="text-xs text-muted-foreground">
                          {bucketRes.items.length >= bucketRes.total ? '已加载全部' : ''}
                        </div>
                        <Button
                          variant="outline"
                          className="gap-2"
                          onClick={() => detachPromise(loadMoreBucketPage())}
                          disabled={bucketLoading || !hasNextBucketPage}
                        >
                          {bucketLoading ? (
                            <Loader2 className="w-4 h-4 animate-spin motion-reduce:animate-none" />
                          ) : null}
                          加载更多
                        </Button>
                      </div>
                    </div>
                  )
                } else {
                  return <div className="py-10 text-center text-[11px] text-muted-foreground/60">暂无数据</div>
                }
              })()}
            </div>
          </DialogContent>
        </Dialog>
      </OperationalWorkspace>
    </AppFrame>
  )
}
