'use client'

import { type ReactNode, type RefObject, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Archive,
  BarChart3,
  Cloud,
  Copy,
  Database,
  FileArchive,
  FileSpreadsheet,
  FileText,
  FileType,
  FileUp,
  Folder,
  FolderSync,
  Link as LinkIcon,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  Trash2,
  UploadCloud,
  type LucideIcon,
} from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'

import { Badge } from '@/components/ui/badge'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { PageHeader } from '@/components/ui/page-header'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { Switch } from '@/components/ui/switch'
import { Tabs, TabsContent, TabsList, TabsTrigger } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { connectorApi, datasetApi, documentApi, settingsApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { cn, formatDate, formatFileSize } from '@/lib/utils'
import type { ConnectorRunOut, Dataset, DatasetIngestionStats, DocumentBatchUploadResponse, DocumentPipelineOptions } from '@/types'

import { IngestionViewSwitch } from './view-switch'

const DRAFT_KEY = 'mimirq.knowledge.ingestion.operation.draft'
const TASK_LIST_PAGE_SIZE = 6

type UploadSource = 'local' | 'folder' | 'url' | 'object' | 'api'
type ParserBackend = 'auto' | 'docling' | 'markitdown' | 'deepdoc' | 'csv' | 'json' | 'markdown'
type ChunkStrategy = 'semantic' | 'langchain_recursive' | 'markdown' | 'by_title'
type IngestMode = 'append' | 'replace' | 'skip_duplicates'
type TaskStatus = 'idle' | 'prechecking' | 'uploading' | 'completed' | 'failed'

type HistoryItem = {
  id: string
  rawId?: string
  kind?: 'upload' | 'document' | 'connector'
  status: string
  created_at: string
  files?: number
  filename?: string
  progress?: number
  sourceName?: string
}

type DraftState = {
  datasetId: string
  syncDataset: boolean
  ingestMode: IngestMode
  parserBackend: ParserBackend
  chunkStrategy: ChunkStrategy
  chunkSize: number
  chunkOverlap: number
  dedupStrategy: string
  tags: string
  collection: string
  errorPolicy: string
  autoSyncIndex: boolean
  refreshStats: boolean
  keepFailureTasks: boolean
}

const DEFAULT_DRAFT: DraftState = {
  datasetId: '',
  syncDataset: true,
  ingestMode: 'append',
  parserBackend: 'auto',
  chunkStrategy: 'semantic',
  chunkSize: 600,
  chunkOverlap: 100,
  dedupStrategy: 'content_hash',
  tags: '',
  collection: 'default',
  errorPolicy: 'skip_failed',
  autoSyncIndex: true,
  refreshStats: true,
  keepFailureTasks: true,
}

const SOURCE_OPTIONS: Array<{
  value: UploadSource
  label: string
  icon: LucideIcon
  description: string
}> = [
  { value: 'local', label: '本地文件', icon: UploadCloud, description: '上传文件' },
  { value: 'folder', label: '文件夹', icon: Folder, description: '批量导入文件夹' },
  { value: 'url', label: 'URL列表', icon: LinkIcon, description: '从链接批量导入' },
  { value: 'object', label: '对象存储', icon: Cloud, description: 'S3/OSS/MinIO 等' },
  { value: 'api', label: 'API导入', icon: Archive, description: '通过接口推送数据' },
]

const ACCEPTED_EXTENSIONS = [
  '.pdf',
  '.md',
  '.markdown',
  '.docx',
  '.html',
  '.htm',
  '.txt',
  '.csv',
  '.xlsx',
  '.xls',
  '.json',
  '.zip',
]

const WORKBENCH_SURFACE_CLASS =
  'rounded-[1.45rem] border border-border/60 bg-card/78 shadow-[0_18px_50px_hsl(var(--primary)/0.08)] backdrop-blur-2xl'
const SOFT_PANEL_CLASS =
  'rounded-[1.28rem] border border-border/55 bg-card/66 shadow-[0_12px_34px_hsl(var(--primary)/0.06)] backdrop-blur-xl'
const SOFT_CONTROL_CLASS =
  'rounded-[1rem] border-border/60 bg-background/82 shadow-[inset_0_1px_0_hsl(var(--card)/0.72)]'
const INLINE_FIELD_CLASS =
  'border border-border/55 bg-background/50 text-foreground shadow-[inset_0_1px_0_hsl(var(--card)/0.55)]'
const CONFIG_BOX_CLASS = 'rounded-[1.25rem] border border-border/60 bg-background/46'
const CONFIG_INPUT_CLASS =
  'rounded-[1rem] border-border/60 bg-card/78 shadow-[inset_0_1px_0_hsl(var(--card)/0.7)]'
const TABLE_SHELL_CLASS = 'overflow-hidden rounded-[1.15rem] border border-border/60 bg-card/72'
const TABLE_HEAD_CLASS = 'bg-muted/38 text-muted-foreground'
const TABLE_ROW_CLASS = 'border-t border-border/50'

function loadDraft(): DraftState {
  if (typeof window === 'undefined') return DEFAULT_DRAFT
  try {
    const raw = window.localStorage.getItem(DRAFT_KEY)
    if (!raw) return DEFAULT_DRAFT
    const parsed = JSON.parse(raw) as Partial<DraftState>
    return { ...DEFAULT_DRAFT, ...parsed }
  } catch {
    return DEFAULT_DRAFT
  }
}

function fileKey(file: File) {
  const path = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
  return `${path}:${file.size}:${file.lastModified}`
}

function formatFileType(file: File) {
  const ext = file.name.split('.').pop()
  return ext ? ext.toUpperCase() : 'FILE'
}

function getFileIcon(file: File) {
  const ext = file.name.split('.').pop()?.toLowerCase()
  if (['xlsx', 'xls', 'csv'].includes(ext || '')) return FileSpreadsheet
  if (['zip'].includes(ext || '')) return FileArchive
  if (['md', 'markdown', 'txt', 'html', 'docx', 'pdf'].includes(ext || '')) return FileText
  return FileType
}

function buildPipeline(draft: DraftState): DocumentPipelineOptions {
  return {
    chunk_size: draft.chunkSize,
    chunk_overlap: draft.chunkOverlap,
    near_dedup_enabled: draft.dedupStrategy !== 'none',
    persist_parsed_content: true,
    chunk_vector_enabled: draft.autoSyncIndex,
    bm25_index_enabled: draft.autoSyncIndex,
  }
}

function normalizeChunkStrategy(strategy: ChunkStrategy) {
  if (strategy === 'semantic') return 'langchain_recursive'
  if (strategy === 'by_title') return 'markdown'
  return strategy
}

function datasetShortId(dataset?: Dataset | null) {
  return dataset?.id ? String(dataset.id).slice(0, 18).toUpperCase() : '--'
}

function statusLabel(status: string) {
  if (status === 'completed' || status === 'ready') return '已完成'
  if (status === 'failed') return '失败'
  if (status === 'processing' || status === 'uploading') return '入库中'
  if (status === 'prechecking') return '检查中'
  if (status === 'pending') return '等待中'
  return '待开始'
}

function statusVariant(status: string): 'success' | 'warning' | 'destructive' | 'info' | 'soft' {
  if (status === 'completed' || status === 'ready') return 'success'
  if (status === 'failed') return 'destructive'
  if (status === 'processing' || status === 'uploading' || status === 'prechecking') return 'info'
  if (status === 'pending') return 'warning'
  return 'soft'
}

function progressForStatus(status: string, fallback = 0) {
  if (status === 'completed' || status === 'ready') return 100
  if (status === 'failed') return 100
  if (status === 'processing' || status === 'uploading') return Math.max(fallback, 62)
  if (status === 'prechecking') return Math.max(fallback, 38)
  if (status === 'pending') return 18
  return fallback
}

function parseLineList(raw: string, max = 100) {
  const seen = new Set<string>()
  const values: string[] = []
  for (const item of raw.split(/[\n,;]+/)) {
    const value = item.trim()
    if (!value || seen.has(value)) continue
    seen.add(value)
    values.push(value)
    if (values.length >= max) break
  }
  return values
}

function parseUrlList(raw: string) {
  return parseLineList(raw, 50).filter((value) => /^https?:\/\//i.test(value))
}

function parseExtensions(raw: string) {
  const extensions = parseLineList(raw, 20)
    .map((value) => value.toLowerCase())
    .map((value) => (value.startsWith('.') ? value : `.${value}`))
    .filter((value) => /^\.[a-z0-9]{1,12}$/i.test(value))
  return extensions.length ? extensions : ['.pdf', '.md', '.txt']
}

function apiPayloadFileType(filename: string) {
  const ext = filename.split('.').pop()?.trim().toLowerCase()
  return ext || 'json'
}

function connectorSourceLabel(connectorId: string) {
  if (connectorId === 'url_batch') return 'URL列表'
  if (connectorId === 'minio_bucket') return '对象存储'
  if (connectorId === 'drive_files') return '文件链接'
  if (connectorId === 'web_crawl') return '网站抓取'
  return connectorId
}

function connectorFileCount(run: ConnectorRunOut) {
  const stats = run.stats ?? {}
  const numeric =
    Number(stats.total_urls) ||
    Number(stats.total_objects) ||
    Number(stats.total_files) ||
    Number(stats.documents_total) ||
    Number(run.documents?.length ?? 0)
  return Number.isFinite(numeric) ? numeric : 0
}

function countStatus(stats: DatasetIngestionStats | null, statuses: string[]) {
  const byStatus = stats?.by_status ?? {}
  return statuses.reduce((sum, status) => sum + Number(byStatus[status] || 0), 0)
}

function isToday(value?: string | null) {
  if (!value) return false
  const date = new Date(value)
  if (Number.isNaN(date.getTime())) return false
  const today = new Date()
  return date.getFullYear() === today.getFullYear() && date.getMonth() === today.getMonth() && date.getDate() === today.getDate()
}

export default function KnowledgeIngestionOperationPage() {
  const router = useRouter()
  const inputRef = useRef<HTMLInputElement | null>(null)
  const folderInputRef = useRef<HTMLInputElement | null>(null)
  const [draft, setDraft] = useState<DraftState>(DEFAULT_DRAFT)
  const [source, setSource] = useState<UploadSource>('local')
  const [files, setFiles] = useState<File[]>([])
  const [urlList, setUrlList] = useState('')
  const [urlFilename, setUrlFilename] = useState('')
  const [objectBucket, setObjectBucket] = useState('')
  const [objectPrefix, setObjectPrefix] = useState('')
  const [objectExtensions, setObjectExtensions] = useState('.pdf, .md, .txt')
  const [objectMaxObjects, setObjectMaxObjects] = useState(50)
  const [apiFilename, setApiFilename] = useState('api-payload.json')
  const [apiContent, setApiContent] = useState('')
  const [dragging, setDragging] = useState(false)
  const [status, setStatus] = useState<TaskStatus>('idle')
  const [uploadResponse, setUploadResponse] = useState<DocumentBatchUploadResponse | null>(null)

  useEffect(() => {
    setDraft(loadDraft())
  }, [])

  useEffect(() => {
    folderInputRef.current?.setAttribute('webkitdirectory', '')
    folderInputRef.current?.setAttribute('directory', '')
  }, [])

  const datasetsQuery = useQuery({
    queryKey: ['knowledge-ingestion-operation-datasets'],
    queryFn: () => datasetApi.list({ limit: 200 }),
    staleTime: 30_000,
  })

  const datasets = useMemo(() => datasetsQuery.data?.items ?? [], [datasetsQuery.data?.items])

  useEffect(() => {
    if (draft.datasetId || !datasets[0]?.id) return
    setDraft((current) => ({ ...current, datasetId: datasets[0].id }))
  }, [datasets, draft.datasetId])

  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.id === draft.datasetId) ?? null,
    [datasets, draft.datasetId]
  )

  const ingestionStatsQuery = useQuery({
    queryKey: ['knowledge-ingestion-operation-stats', draft.datasetId],
    queryFn: () => datasetApi.getIngestionStats(draft.datasetId),
    enabled: Boolean(draft.datasetId),
    staleTime: 10_000,
  })

  const ingestionStats = ingestionStatsQuery.data ?? null

  const documentsQuery = useQuery({
    queryKey: ['knowledge-ingestion-operation-documents', draft.datasetId],
    queryFn: () =>
      documentApi.list({
        dataset_id: draft.datasetId,
        limit: 50,
        order_by: 'created_at',
        order_dir: 'desc',
      }),
    enabled: Boolean(draft.datasetId),
    staleTime: 10_000,
  })

  const documents = useMemo(() => documentsQuery.data?.items ?? [], [documentsQuery.data?.items])

  const connectorRunsQuery = useQuery({
    queryKey: ['knowledge-ingestion-operation-connector-runs', draft.datasetId],
    queryFn: () => connectorApi.listRuns({ dataset_id: draft.datasetId, limit: 20 }),
    enabled: Boolean(draft.datasetId),
    staleTime: 5_000,
  })

  const connectorRuns = useMemo(
    () => connectorRunsQuery.data?.items ?? [],
    [connectorRunsQuery.data?.items]
  )

  const settingsQuery = useQuery({
    queryKey: ['knowledge-ingestion-operation-settings'],
    queryFn: () => settingsApi.get(),
    staleTime: 30_000,
  })

  const urlIngestEnabled = Boolean(settingsQuery.data?.url_ingest.enabled)

  const selectedTotalBytes = useMemo(
    () => files.reduce((sum, file) => sum + file.size, 0),
    [files]
  )

  const parsedUrls = useMemo(() => parseUrlList(urlList), [urlList])
  const parsedObjectExtensions = useMemo(() => parseExtensions(objectExtensions), [objectExtensions])
  const pendingSourceCount = useMemo(() => {
    if (source === 'url') return parsedUrls.length
    if (source === 'object') return objectMaxObjects
    if (source === 'api') return apiContent.trim() ? 1 : 0
    return files.length
  }, [apiContent, files.length, objectMaxObjects, parsedUrls.length, source])

  const connectorSourceBlocked = (source === 'url' || source === 'object') && !urlIngestEnabled
  const canStartIngest =
    Boolean(draft.datasetId) &&
    status !== 'uploading' &&
    pendingSourceCount > 0 &&
    !connectorSourceBlocked

  const statusCounts = useMemo(() => {
    if (ingestionStats) {
      return {
        failed: countStatus(ingestionStats, ['failed']),
        processing: countStatus(ingestionStats, ['processing']),
        pending: countStatus(ingestionStats, ['pending']),
        completed: countStatus(ingestionStats, ['completed', 'ready']),
        quarantined: countStatus(ingestionStats, ['quarantined']),
        cancelled: countStatus(ingestionStats, ['cancelled']),
      }
    }
    const failed = documents.filter((item) => item.status === 'failed').length
    const pending = documents.filter((item) => String(item.status) === 'pending').length
    const processing = documents.filter((item) =>
      ['pending', 'processing', 'uploading'].includes(String(item.status))
    ).length
    const completed = documents.filter((item) =>
      ['completed', 'ready'].includes(String(item.status))
    ).length
    const quarantined = documents.filter((item) => String(item.status) === 'quarantined').length
    const cancelled = documents.filter((item) => String(item.status) === 'cancelled').length
    return { failed, processing, pending, completed, quarantined, cancelled }
  }, [documents, ingestionStats])

  const totalDocuments = ingestionStats?.total_documents ?? documents.length
  const totalChunks = ingestionStats?.total_chunks ?? documents.reduce((sum, item) => sum + Number(item.chunk_count || 0), 0)
  const datasetTotalBytes = ingestionStats?.total_size ?? documents.reduce((sum, item) => sum + Number(item.file_size || 0), 0)
  const statsSource = ingestionStats ? '后端统计' : '当前列表'

  const connectorRunningCount = connectorRuns.filter((run) => ['pending', 'running'].includes(run.status)).length
  const connectorFailedCount = connectorRuns.filter((run) => run.status === 'failed').length
  const connectorCompletedCount = connectorRuns.filter((run) => run.status === 'completed').length
  const runningCount = statusCounts.processing + statusCounts.pending + connectorRunningCount + (status === 'uploading' ? 1 : 0)
  const failedCount = statusCounts.failed + connectorFailedCount
  const completedCount = statusCounts.completed + connectorCompletedCount
  const terminalCount = completedCount + failedCount
  const successRateValue = terminalCount ? `${Math.round((completedCount / terminalCount) * 1000) / 10}%` : '暂无数据'
  const todayDocumentCount = documents.filter((document) => isToday(document.created_at)).length
  const todayConnectorCount = connectorRuns.filter((run) => isToday(run.created_at)).length
  const todayRecordCount = todayDocumentCount + todayConnectorCount

  const fileRows = useMemo(
    () =>
      files.map((file) => {
        const Icon = getFileIcon(file)
        return { file, Icon, key: fileKey(file) }
      }),
    [files]
  )
  const activeSource = SOURCE_OPTIONS.find((item) => item.value === source) ?? SOURCE_OPTIONS[0]

  const recentTasks: HistoryItem[] = useMemo(() => {
    const connectorItems = connectorRuns.map((run) => ({
      id: `#${String(run.id).slice(0, 12)}`,
      rawId: run.id,
      kind: 'connector' as const,
      status: run.status,
      files: connectorFileCount(run),
      created_at: run.finished_at || run.started_at || run.created_at,
      filename: `${connectorSourceLabel(run.connector_id)} 任务`,
      progress: progressForStatus(run.status),
      sourceName: connectorSourceLabel(run.connector_id),
    }))
    if (uploadResponse) {
      const firstDocumentId = uploadResponse.successful?.[0]?.document_id
      return [
        {
          id: firstDocumentId ? `#${String(firstDocumentId).slice(0, 12)}` : '批量提交结果',
          kind: 'upload',
          status,
          files: uploadResponse.total,
          created_at: new Date().toISOString(),
          filename: source === 'api' ? apiFilename : files[0]?.name ?? '批量文件',
          progress: progressForStatus(status),
          sourceName: activeSource.label,
        },
        ...connectorItems,
      ]
    }
    if (pendingSourceCount) {
      return [
        {
          id: '本地草稿',
          kind: 'upload',
          status,
          files: pendingSourceCount,
          created_at: new Date().toISOString(),
          filename: `${pendingSourceCount} 个当前选择来源`,
          progress: 0,
          sourceName: activeSource.label,
        },
        ...connectorItems,
      ]
    }
    if (connectorItems.length) return connectorItems
    return documents.map((document) => ({
      id: `#${String(document.id).slice(0, 12)}`,
      rawId: String(document.id),
      kind: 'document' as const,
      status: String(document.status),
      files: 1,
      created_at: document.updated_at || document.created_at,
      filename: document.filename,
      progress: progressForStatus(String(document.status), Number(document.processing_progress || 0)),
      sourceName: '文档库',
    }))
  }, [activeSource.label, apiFilename, connectorRuns, documents, files, pendingSourceCount, source, status, uploadResponse])

  const statusRailItems = [
    { icon: FileUp, label: '今日新增', value: `${todayRecordCount}`, helper: `文档 ${todayDocumentCount} · 任务 ${todayConnectorCount}`, tone: 'blue' as const },
    { icon: FolderSync, label: '队列状态', value: `${runningCount}`, helper: `处理中 ${statusCounts.processing} · 待处理 ${statusCounts.pending}`, tone: 'green' as const },
    { icon: RefreshCw, label: '待提交', value: `${pendingSourceCount + statusCounts.pending}`, helper: `${activeSource.label} · 当前选择 ${pendingSourceCount}`, tone: 'amber' as const },
    { icon: BarChart3, label: '入库成功率', value: successRateValue, helper: `完成 ${completedCount} / 失败 ${failedCount}`, tone: 'blue' as const },
  ]

  const updateDraft = useCallback(<K extends keyof DraftState>(key: K, value: DraftState[K]) => {
    setDraft((current) => ({ ...current, [key]: value }))
  }, [])

  const addFiles = useCallback((incoming: File[]) => {
    const supported = incoming.filter((file) => {
      const lower = file.name.toLowerCase()
      return ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext))
    })
    const rejected = incoming.length - supported.length
    setFiles((current) => {
      const byKey = new Map(current.map((file) => [fileKey(file), file]))
      for (const file of supported) byKey.set(fileKey(file), file)
      return Array.from(byKey.values())
    })
    if (rejected > 0) {
      toast.warning(`${rejected} 个文件格式未在允许列表中，已跳过`)
    }
  }, [])

  const clearFiles = useCallback(() => {
    setFiles([])
    setUploadResponse(null)
    setStatus('idle')
  }, [])

  const removeFile = useCallback((key: string) => {
    setFiles((current) => current.filter((file) => fileKey(file) !== key))
  }, [])

  const submitConnectorRun = useCallback(async () => {
    if (!draft.datasetId) {
      toast.error('请先选择目标数据集')
      return
    }
    if (!urlIngestEnabled) {
      toast.error('URL 导入未启用：请先在系统设置中开启 URL_INGEST_ENABLED')
      return
    }
    setStatus('uploading')
    setUploadResponse(null)
    try {
      const sharedConfig = {
        parser_backend: draft.parserBackend,
        chunk_strategy: normalizeChunkStrategy(draft.chunkStrategy),
        pipeline: buildPipeline(draft),
      }
      const run =
        source === 'url'
          ? await connectorApi.createRun({
              connector_id: 'url_batch',
              dataset_id: draft.datasetId,
              config: {
                urls: parsedUrls,
                filename: urlFilename.trim() || undefined,
                ...sharedConfig,
              },
            })
          : await connectorApi.createRun({
              connector_id: 'minio_bucket',
              dataset_id: draft.datasetId,
              config: {
                bucket: objectBucket.trim() || undefined,
                prefix: objectPrefix.trim() || undefined,
                include_extensions: parsedObjectExtensions,
                max_objects: objectMaxObjects,
                ...sharedConfig,
              },
            })
      setStatus(run.status === 'failed' ? 'failed' : run.status === 'completed' ? 'completed' : 'uploading')
      await Promise.all([connectorRunsQuery.refetch(), ingestionStatsQuery.refetch()])
      toast.success(`连接器任务已创建：${String(run.id).slice(0, 8)}`)
    } catch (error) {
      setStatus('failed')
      toast.error(formatApiError(error, '连接器任务创建失败'))
    }
  }, [
    connectorRunsQuery,
    draft,
    ingestionStatsQuery,
    objectBucket,
    objectMaxObjects,
    objectPrefix,
    parsedObjectExtensions,
    parsedUrls,
    source,
    urlIngestEnabled,
    urlFilename,
  ])

  const handleSyncDatasets = useCallback(async () => {
    await datasetsQuery.refetch()
    if (draft.datasetId) {
      await Promise.all([documentsQuery.refetch(), connectorRunsQuery.refetch(), ingestionStatsQuery.refetch()])
    }
    toast.success('数据集状态已同步')
  }, [connectorRunsQuery, datasetsQuery, documentsQuery, draft.datasetId, ingestionStatsQuery])

  const uploadFiles = useCallback(
    async (mode: 'precheck' | 'ingest') => {
      if (!draft.datasetId) {
        toast.error('请先选择目标数据集')
        return
      }
      if (source === 'url' || source === 'object') {
        if (source === 'url' && !parsedUrls.length) {
          toast.error('请先填写有效 URL')
          return
        }
        await submitConnectorRun()
        return
      }
      if (source === 'api' && !apiContent.trim()) {
        toast.error('请先填写 API 导入内容')
        return
      }
      if (source !== 'api' && !files.length) {
        toast.error('请先选择待入库文件')
        return
      }
      const uploadTargets = files
      const nextStatus: TaskStatus = mode === 'precheck' ? 'prechecking' : 'uploading'
      setStatus(nextStatus)
      setUploadResponse(null)
      try {
        if (source === 'api') {
          const filename = apiFilename.trim() || 'api-payload.json'
          const document = await documentApi.createFromChunks({
            dataset_id: draft.datasetId,
            filename,
            file_type: apiPayloadFileType(filename),
            file_size: new TextEncoder().encode(apiContent).length,
            pipeline: buildPipeline(draft),
            metadata: {
              source: 'api',
              collection: draft.collection,
              tags: draft.tags
                .split(',')
                .map((tag) => tag.trim())
                .filter(Boolean),
              ingest_mode: draft.ingestMode,
            },
            chunks: [
              {
                content: apiContent,
                page_number: 1,
                start_char: 0,
                end_char: apiContent.length,
                metadata: {
                  source: 'api',
                  collection: draft.collection,
                },
              },
            ],
          })
          setUploadResponse({
            total: 1,
            successful_count: 1,
            failed_count: 0,
            successful: [
              {
                document_id: document.id,
                filename,
                status: String(document.status || 'completed'),
              },
            ],
            failed: [],
          })
          setStatus('completed')
          await Promise.all([documentsQuery.refetch(), ingestionStatsQuery.refetch()])
          toast.success(`API 导入已写入：${filename}`)
          return
        }
        const uploadOptions = {
          dataset_id: draft.datasetId,
          parser_backend: draft.parserBackend,
          chunk_strategy: normalizeChunkStrategy(draft.chunkStrategy),
          pipeline: buildPipeline(draft),
          precheck_only: mode === 'precheck',
          max_concurrent: 4,
          user_metadata_map: Object.fromEntries(
            uploadTargets.map((file) => [
              (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name,
              {
                tags: draft.tags
                  .split(',')
                  .map((tag) => tag.trim())
                  .filter(Boolean),
                collection: draft.collection,
                ingest_mode: draft.ingestMode,
                source,
              },
            ])
          ),
        }
        const response = await documentApi.uploadBatch(files, uploadOptions)
        setUploadResponse(response)
        setStatus(response.failed_count > 0 ? 'failed' : 'completed')
        if (mode === 'ingest') {
          await Promise.all([documentsQuery.refetch(), ingestionStatsQuery.refetch()])
        }
        toast.success(`入库任务已提交：成功 ${response.successful_count} / 失败 ${response.failed_count}`)
      } catch (error) {
        setStatus('failed')
        toast.error(formatApiError(error, '入库任务提交失败'))
      }
    },
    [apiContent, apiFilename, documentsQuery, draft, files, ingestionStatsQuery, parsedUrls.length, source, submitConnectorRun]
  )

  const inspectTask = useCallback(async (task: HistoryItem) => {
    if (task.kind !== 'connector' || !task.rawId) {
      toast.message(`${task.filename ?? task.id}：${statusLabel(task.status)}`)
      return
    }
    try {
      const run = await connectorApi.getRun(task.rawId)
      toast.success(
        `任务 ${String(run.id).slice(0, 8)}：${statusLabel(run.status)}，产出文档 ${run.documents?.length ?? 0}`
      )
    } catch (error) {
      toast.error(formatApiError(error, '读取任务详情失败'))
    }
  }, [])

  const sourceConfigurationProps = {
    folderInputRef,
    onFiles: addFiles,
    urlList,
    setUrlList,
    urlFilename,
    setUrlFilename,
    parsedUrls,
    objectBucket,
    setObjectBucket,
    objectPrefix,
    setObjectPrefix,
    objectExtensions,
    setObjectExtensions,
    objectMaxObjects,
    setObjectMaxObjects,
    parsedObjectExtensions,
    urlIngestEnabled,
    apiFilename,
    setApiFilename,
    apiContent,
    setApiContent,
  }

  return (
    <div className="min-h-full overflow-y-auto bg-[radial-gradient(circle_at_14%_0%,hsl(var(--primary)/0.08),transparent_32%),radial-gradient(circle_at_86%_10%,hsl(var(--accent)/0.06),transparent_30%),linear-gradient(180deg,hsl(var(--background))_0%,hsl(var(--surface-2)/0.60)_46%,hsl(var(--background))_100%)] px-4 py-2.5 text-foreground lg:px-5">
      <div className="mx-auto flex max-w-[1680px] flex-col gap-2">
        <PageHeader
          title="入库中心"
          description="选择目标数据集、接入来源和入库策略，提交后在同一工作台跟踪进度并同步知识库。"
          iconImage="ingestion-operation"
          badge="INGESTION"
          compact
        >
          <IngestionViewSwitch />
        </PageHeader>

        <section className={cn(WORKBENCH_SURFACE_CLASS, 'space-y-2 p-2.5')}>
          <div className="grid gap-2 xl:grid-cols-[1.1fr_0.85fr_1.7fr_auto]">
            <FieldBlock label="目标数据集" required>
              <Select value={draft.datasetId} onValueChange={(value) => updateDraft('datasetId', value)}>
                <SelectTrigger className={cn('h-9', SOFT_CONTROL_CLASS)}>
                  <SelectValue placeholder={datasetsQuery.isLoading ? '正在加载数据集' : '选择目标数据集'} />
                </SelectTrigger>
                <SelectContent>
                  {datasets.map((dataset) => (
                    <SelectItem key={dataset.id} value={dataset.id}>
                      {dataset.name}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </FieldBlock>
            <FieldBlock label="入库模式">
              <Select value={draft.ingestMode} onValueChange={(value) => updateDraft('ingestMode', value as IngestMode)}>
                <SelectTrigger className={cn('h-9', SOFT_CONTROL_CLASS)}>
                  <SelectValue />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="append">追加导入（保留现有数据）</SelectItem>
                  <SelectItem value="skip_duplicates">跳过重复文件</SelectItem>
                  <SelectItem value="replace">替换同名文件</SelectItem>
                </SelectContent>
              </Select>
            </FieldBlock>
            <FieldBlock label="数据来源">
              <Tabs value={source} onValueChange={(value) => setSource(value as UploadSource)}>
                <TabsList className="grid h-10 grid-cols-5 overflow-hidden rounded-[1rem] border border-border/60 bg-muted/35 p-0.5">
                  {SOURCE_OPTIONS.map((item) => {
                    const Icon = item.icon
                    return (
                      <TabsTrigger
                        key={item.value}
                        value={item.value}
                        className="h-full gap-2 rounded-[0.85rem] text-xs text-muted-foreground data-[state=active]:bg-card/95 data-[state=active]:text-primary data-[state=active]:shadow-[0_8px_18px_hsl(var(--primary)/0.12)]"
                      >
                        <Icon className="size-4" />
                        <span className="hidden md:inline">{item.label}</span>
                      </TabsTrigger>
                    )
                  })}
                </TabsList>
              </Tabs>
            </FieldBlock>
            <div className="flex items-end gap-2">
              <Button variant="outline" className="h-9 rounded-[1rem] border-border/60 bg-card/82 text-foreground shadow-sm hover:bg-muted/50" onClick={() => router.push('/datasets')}>
                <Plus className="mr-2 size-4" />
                新建数据集
              </Button>
              <Button className="h-9 rounded-[1rem] bg-[linear-gradient(135deg,hsl(var(--primary)),hsl(var(--info)))] px-4 text-primary-foreground shadow-[0_12px_24px_hsl(var(--primary)/0.18)] hover:brightness-105" onClick={() => void uploadFiles('ingest')} disabled={!canStartIngest}>
                {status === 'uploading' ? <Loader2 className="mr-2 size-4 animate-spin" /> : <Play className="mr-2 size-4" />}
                开始入库
              </Button>
            </div>
          </div>
          <StatusRail items={statusRailItems} />
        </section>

        <div className="space-y-2">
          <main className="space-y-2">
            <section className={cn(SOFT_PANEL_CLASS, 'p-2.5')}>
              <SectionTitle title="入库任务创建" />
              <DatasetSummaryCard
                dataset={selectedDataset}
                documentCount={totalDocuments}
                chunkCount={totalChunks}
                totalBytes={datasetTotalBytes}
                statsSource={statsSource}
                syncEnabled={draft.syncDataset}
              />

              <Tabs value={source} onValueChange={(value) => setSource(value as UploadSource)}>
                <TabsContent value="local" className="mt-2">
                  <UploadDropArea dragging={dragging} onDragState={setDragging} onClick={() => inputRef.current?.click()} onFiles={addFiles} />
                </TabsContent>
                <TabsContent value="folder" className="mt-2">
                  <SourceConfiguration source="folder" {...sourceConfigurationProps} />
                </TabsContent>
                <TabsContent value="url" className="mt-2">
                  <SourceConfiguration source="url" {...sourceConfigurationProps} />
                </TabsContent>
                <TabsContent value="object" className="mt-2">
                  <SourceConfiguration source="object" {...sourceConfigurationProps} />
                </TabsContent>
                <TabsContent value="api" className="mt-2">
                  <SourceConfiguration source="api" {...sourceConfigurationProps} />
                </TabsContent>
              </Tabs>

              <input
                ref={inputRef}
                type="file"
                multiple
                className="sr-only"
                accept={ACCEPTED_EXTENSIONS.join(',')}
                onChange={(event) => {
                  addFiles(Array.from(event.target.files ?? []))
                  event.target.value = ''
                }}
              />

              <SelectedFilesTable
                rows={fileRows}
                totalBytes={selectedTotalBytes}
                onClear={clearFiles}
                onRemove={removeFile}
              />
            </section>

            <TaskListCard
              tasks={recentTasks}
              datasetName={selectedDataset?.name ?? '未选择数据集'}
              sourceName={activeSource.label}
              draft={draft}
              updateDraft={updateDraft}
              onRefresh={handleSyncDatasets}
              onInspectTask={inspectTask}
            />
          </main>
        </div>
      </div>
    </div>
  )
}

function FieldBlock({
  label,
  required,
  children,
}: Readonly<{
  label: string
  required?: boolean
  children: ReactNode
}>) {
  return (
    <label className="block">
      <div className="mb-2 text-xs font-semibold text-muted-foreground">
        {required ? <span className="mr-1 text-red-500">*</span> : null}
        {label}
      </div>
      {children}
    </label>
  )
}

function SectionTitle({ title }: Readonly<{ title: string }>) {
  return (
    <div className="mb-1.5 flex items-center justify-between">
      <h2 className="text-sm font-semibold tracking-[-0.01em] text-foreground">{title}</h2>
    </div>
  )
}

function StatusRail({
  items,
}: Readonly<{
  items: Array<{
    icon: LucideIcon
    label: string
    value: string
    helper: string
    tone: 'blue' | 'green' | 'amber'
  }>
}>) {
  return (
    <div className="grid gap-1 rounded-[1.1rem] border border-border/55 bg-background/42 px-2 py-1.5 md:grid-cols-4">
      {items.map((item) => (
        <StatusRailItem key={item.label} {...item} />
      ))}
    </div>
  )
}

function StatusRailItem({
  icon: Icon,
  label,
  value,
  helper,
  tone,
}: Readonly<{
  icon: LucideIcon
  label: string
  value: string
  helper: string
  tone: 'blue' | 'green' | 'amber'
}>) {
  const toneClass = {
    blue: 'bg-info/[0.10] text-info ring-1 ring-info/20',
    green: 'bg-emerald-50/80 text-emerald-600 ring-1 ring-emerald-100/80',
    amber: 'bg-amber-50/80 text-amber-600 ring-1 ring-amber-100/80',
  }[tone]
  return (
    <div className="flex min-w-0 items-center gap-2 rounded-[0.95rem] px-2 py-1.5 md:border-r md:border-border/55 md:last:border-r-0">
      <span className={cn('flex size-7 shrink-0 items-center justify-center rounded-[0.9rem]', toneClass)}>
        <Icon className="size-3.5" />
      </span>
      <div className="min-w-0">
        <div className="flex items-baseline gap-1.5">
          <span className="text-xs text-muted-foreground">{label}</span>
          <span className="text-[1.02rem] font-semibold leading-5 tracking-[-0.035em] text-foreground">{value}</span>
        </div>
        <div className="mt-0.5 truncate text-[11px] text-muted-foreground">{helper}</div>
      </div>
      <span className={cn('ml-auto hidden size-7 items-center justify-center rounded-[0.9rem] opacity-55 xl:flex', toneClass)}>
        <Icon className="size-4" />
      </span>
    </div>
  )
}

function DatasetSummaryCard({
  dataset,
  documentCount,
  chunkCount,
  totalBytes,
  statsSource,
  syncEnabled,
}: Readonly<{
  dataset: Dataset | null
  documentCount: number
  chunkCount: number
  totalBytes: number
  statsSource: string
  syncEnabled: boolean
}>) {
  const capacitySummary = dataset
    ? `${documentCount.toLocaleString()} 文档 · ${chunkCount.toLocaleString()} 分片 · ${formatFileSize(totalBytes)}`
    : '选择数据集后承接上传、解析、切块与索引同步'

  return (
    <div className="rounded-[1.2rem] border border-border/60 bg-[linear-gradient(135deg,hsl(var(--card)/0.92)_0%,hsl(var(--surface-2)/0.56)_52%,hsl(var(--background)/0.78)_100%)] px-3 py-2 shadow-[inset_0_1px_0_hsl(var(--card)/0.8)]">
      <div className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <div className="flex min-w-0 items-start gap-2.5">
          <span className="mt-0.5 flex size-8 shrink-0 items-center justify-center rounded-[1rem] border border-border/60 bg-card text-primary shadow-[0_10px_22px_hsl(var(--primary)/0.14)]">
            <Database className="size-4" />
          </span>
          <div className="min-w-0">
            <div className="flex min-w-0 flex-wrap items-center gap-2">
              <div className="truncate text-sm font-semibold text-foreground">{dataset?.name ?? '未选择数据集'}</div>
              <span className="flex items-center gap-1 text-[11px] text-muted-foreground">
                ID: <span className="font-mono">{datasetShortId(dataset)}</span>
                <Copy className="size-3" />
              </span>
            </div>
            <div className="mt-1 text-xs text-muted-foreground">
              当前目标数据集 · {capacitySummary} · {dataset ? statsSource : '等待选择'}
            </div>
          </div>
        </div>
        <div className="flex flex-wrap items-center gap-2 lg:justify-end [&_[data-slot=badge]]:rounded-full [&_[data-slot=badge]]:px-2.5">
          <Badge variant={dataset ? 'success' : 'warning'}>{dataset ? '数据集已选' : '待选择'}</Badge>
          <Badge variant={syncEnabled ? 'success' : 'warning'}>{syncEnabled ? '自动同步知识库' : '手动同步'}</Badge>
        </div>
      </div>
    </div>
  )
}

function UploadDropArea({
  dragging,
  onDragState,
  onClick,
  onFiles,
}: Readonly<{
  dragging: boolean
  onDragState: (dragging: boolean) => void
  onClick: () => void
  onFiles: (files: File[]) => void
}>) {
  return (
    <button
      type="button"
      onClick={onClick}
      onDragEnter={(event) => {
        event.preventDefault()
        onDragState(true)
      }}
      onDragOver={(event) => {
        event.preventDefault()
        onDragState(true)
      }}
      onDragLeave={() => onDragState(false)}
      onDrop={(event) => {
        event.preventDefault()
        onDragState(false)
        onFiles(Array.from(event.dataTransfer.files ?? []))
      }}
      className={cn(
        'flex min-h-[3.35rem] w-full flex-col items-center justify-center rounded-[1.35rem] border border-dashed bg-[radial-gradient(circle_at_center,hsl(var(--primary)/0.10),transparent_48%),linear-gradient(180deg,hsl(var(--card)/0.92),hsl(var(--background)/0.76))] px-4 py-2 text-center transition',
        dragging
          ? 'border-primary/45 shadow-[0_0_0_4px_hsl(var(--primary)/0.14)]'
          : 'border-border/70 hover:border-primary/35 hover:bg-primary/[0.04]'
      )}
    >
      <span className="flex size-7 items-center justify-center rounded-[0.95rem] bg-primary/10 text-primary ring-1 ring-primary/20">
        <UploadCloud className="size-3.5" />
      </span>
      <div className="mt-1 text-sm font-semibold text-foreground">点击选择文件，或将文件拖拽到此处</div>
      <div className="mt-0.5 text-[11px] text-muted-foreground">
        支持 pdf、docx、txt、md、xlsx、csv、pptx 等格式，单文件 ≤ 2GB
      </div>
    </button>
  )
}

function SourceConfiguration({
  source,
  folderInputRef,
  onFiles,
  urlList,
  setUrlList,
  urlFilename,
  setUrlFilename,
  parsedUrls,
  objectBucket,
  setObjectBucket,
  objectPrefix,
  setObjectPrefix,
  objectExtensions,
  setObjectExtensions,
  objectMaxObjects,
  setObjectMaxObjects,
  parsedObjectExtensions,
  urlIngestEnabled,
  apiFilename,
  setApiFilename,
  apiContent,
  setApiContent,
}: Readonly<{
  source: Exclude<UploadSource, 'local'>
  folderInputRef: RefObject<HTMLInputElement | null>
  onFiles: (files: File[]) => void
  urlList: string
  setUrlList: (value: string) => void
  urlFilename: string
  setUrlFilename: (value: string) => void
  parsedUrls: string[]
  objectBucket: string
  setObjectBucket: (value: string) => void
  objectPrefix: string
  setObjectPrefix: (value: string) => void
  objectExtensions: string
  setObjectExtensions: (value: string) => void
  objectMaxObjects: number
  setObjectMaxObjects: (value: number) => void
  parsedObjectExtensions: string[]
  urlIngestEnabled: boolean
  apiFilename: string
  setApiFilename: (value: string) => void
  apiContent: string
  setApiContent: (value: string) => void
}>) {
  if (source === 'folder') {
    return (
      <div className={cn(CONFIG_BOX_CLASS, 'border-dashed px-3 py-2')}>
        <div className="flex flex-col gap-2 md:flex-row md:items-center md:justify-between">
          <div className="flex min-w-0 items-center gap-2.5">
            <span className="flex size-8 shrink-0 items-center justify-center rounded-[1rem] bg-primary/10 text-primary ring-1 ring-primary/20">
              <Folder className="size-4" />
            </span>
            <div className="min-w-0">
              <div className="text-sm font-semibold text-foreground">选择本地文件夹</div>
              <div className="text-xs text-muted-foreground">浏览器会保留相对路径，后端按文件夹内文件批量上传到当前数据集。</div>
            </div>
          </div>
          <Button variant="outline" className={cn(CONFIG_INPUT_CLASS, 'hover:bg-background/92')} onClick={() => folderInputRef.current?.click()}>
            <Folder className="mr-2 size-4" />
            选择文件夹
          </Button>
        </div>
        <input
          ref={folderInputRef}
          type="file"
          multiple
          className="sr-only"
          accept={ACCEPTED_EXTENSIONS.join(',')}
          onChange={(event) => {
            onFiles(Array.from(event.target.files ?? []))
            event.target.value = ''
          }}
        />
      </div>
    )
  }

  if (source === 'url') {
    return (
      <div className={cn(CONFIG_BOX_CLASS, 'grid gap-2 p-2 md:grid-cols-[minmax(0,1fr)_15rem]')}>
        <FieldBlock label="URL 列表">
          <Textarea
            className={cn('min-h-[5.2rem]', CONFIG_INPUT_CLASS)}
            value={urlList}
            onChange={(event) => setUrlList(event.target.value)}
            placeholder="https://example.com/manual.pdf&#10;https://example.com/guide.md"
          />
          <div className="mt-1 text-[11px] text-muted-foreground">
            {urlIngestEnabled
              ? `已识别 ${parsedUrls.length} 个有效 http(s) 地址，提交后走后端 URL 批量导入任务。`
              : 'URL 导入未启用：请先在系统设置开启 URL_INGEST_ENABLED。'}
          </div>
        </FieldBlock>
        <FieldBlock label="统一文件名（可选）">
          <Input
            className={cn('h-9', CONFIG_INPUT_CLASS)}
            value={urlFilename}
            onChange={(event) => setUrlFilename(event.target.value)}
            placeholder="remote-documents.md"
          />
        </FieldBlock>
      </div>
    )
  }

  if (source === 'object') {
    return (
      <div className={cn(CONFIG_BOX_CLASS, 'grid gap-2 p-2 md:grid-cols-2 xl:grid-cols-4')}>
        {!urlIngestEnabled ? (
          <div className="md:col-span-2 xl:col-span-4 rounded-[1rem] border border-amber-100 bg-amber-50/70 px-3 py-2 text-xs text-amber-700">
            URL 导入未启用：对象存储需要后端通过 presigned URL 拉取文件，请先开启 URL_INGEST_ENABLED。
          </div>
        ) : null}
        <FieldBlock label="Bucket（可选）">
          <Input
            className={cn('h-9', CONFIG_INPUT_CLASS)}
            value={objectBucket}
            onChange={(event) => setObjectBucket(event.target.value)}
            placeholder="默认使用后端 MINIO_BUCKET_NAME"
          />
        </FieldBlock>
        <FieldBlock label="对象前缀">
          <Input
            className={cn('h-9', CONFIG_INPUT_CLASS)}
            value={objectPrefix}
            onChange={(event) => setObjectPrefix(event.target.value)}
            placeholder="manuals/2026/"
          />
        </FieldBlock>
        <FieldBlock label="扩展名">
          <Input
            className={cn('h-9', CONFIG_INPUT_CLASS)}
            value={objectExtensions}
            onChange={(event) => setObjectExtensions(event.target.value)}
            placeholder=".pdf, .md, .txt"
          />
          <div className="mt-1 text-[11px] text-muted-foreground">实际提交：{parsedObjectExtensions.join(', ')}</div>
        </FieldBlock>
        <FieldBlock label="最大对象数">
          <Input
            className={cn('h-9', CONFIG_INPUT_CLASS)}
            min={1}
            max={200}
            type="number"
            value={objectMaxObjects}
            onChange={(event) => setObjectMaxObjects(Math.min(200, Math.max(1, Number(event.target.value) || 1)))}
          />
        </FieldBlock>
      </div>
    )
  }

  return (
    <div className={cn(CONFIG_BOX_CLASS, 'grid gap-2 p-2 md:grid-cols-[16rem_minmax(0,1fr)]')}>
      <FieldBlock label="生成文件名">
        <Input
          className={cn('h-9', CONFIG_INPUT_CLASS)}
          value={apiFilename}
          onChange={(event) => setApiFilename(event.target.value)}
          placeholder="api-payload.json"
        />
        <div className="mt-1 text-[11px] text-muted-foreground">
          提交时直接调用后端手动入库接口，按单段内容写入当前数据集。
        </div>
      </FieldBlock>
      <FieldBlock label="API Payload">
        <Textarea
          className={cn('min-h-[5.2rem] font-mono text-xs', CONFIG_INPUT_CLASS)}
          value={apiContent}
          onChange={(event) => setApiContent(event.target.value)}
          placeholder='{"title":"产品说明","content":"这里粘贴接口推送内容"}'
        />
      </FieldBlock>
    </div>
  )
}

function SelectedFilesTable({
  rows,
  totalBytes,
  onClear,
  onRemove,
}: Readonly<{
  rows: Array<{ file: File; Icon: LucideIcon; key: string }>
  totalBytes: number
  onClear: () => void
  onRemove: (key: string) => void
}>) {
  if (!rows.length) return null

  return (
    <div className={cn('mt-2 rounded-[1.2rem] shadow-[0_12px_30px_hsl(var(--primary)/0.04)]', TABLE_SHELL_CLASS)}>
      <div className="flex items-center justify-between border-b border-border/50 px-3 py-1.5">
        <div className="text-sm font-semibold text-foreground">已选文件（{rows.length}）</div>
        <Button variant="ghost" className="h-7 rounded-[0.85rem] px-2 text-xs text-muted-foreground hover:bg-background/72" onClick={onClear} disabled={!rows.length}>
          清空列表
        </Button>
      </div>
      <div className="max-h-[7.5rem] overflow-auto">
        <table className="w-full text-left text-xs">
          <thead className={cn('sticky top-0', TABLE_HEAD_CLASS)}>
            <tr>
              <th className="px-3 py-1.5 font-medium">文件名</th>
              <th className="px-2.5 py-1.5 font-medium">大小</th>
              <th className="px-2.5 py-1.5 font-medium">类型</th>
              <th className="px-2.5 py-1.5 font-medium">来源</th>
              <th className="px-2.5 py-1.5 font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ file, Icon, key }) => (
              <tr key={key} className={TABLE_ROW_CLASS}>
                <td className="px-3 py-1.5">
                  <div className="flex min-w-0 items-center gap-2">
                    <span className="flex size-6 shrink-0 items-center justify-center rounded-[0.8rem] border border-border/60 bg-primary/10 text-primary">
                      <Icon className="size-3.5" />
                    </span>
                    <span className="truncate font-medium text-foreground">{file.name}</span>
                  </div>
                </td>
                <td className="px-2.5 py-1.5 font-mono text-muted-foreground">{formatFileSize(file.size)}</td>
                <td className="px-2.5 py-1.5 text-muted-foreground">{formatFileType(file)}</td>
                <td className="px-2.5 py-1.5 text-muted-foreground">本地上传</td>
                <td className="px-2.5 py-1.5">
                  <Button
                    variant="ghost"
                    size="icon"
                    aria-label={`移除文件 ${file.name}`}
                    title={`移除文件 ${file.name}`}
                    className="size-7 rounded-[0.85rem] text-muted-foreground hover:bg-destructive/10 hover:text-destructive"
                    onClick={() => onRemove(key)}
                  >
                    <Trash2 className="size-3.5" />
                  </Button>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <div className="border-t border-border/50 px-3 py-1.5 text-xs text-muted-foreground">
        共 {rows.length} 个文件，合计 {formatFileSize(totalBytes)}
      </div>
    </div>
  )
}

function IngestTaskControls({
  draft,
  updateDraft,
}: Readonly<{
  draft: DraftState
  updateDraft: <K extends keyof DraftState>(key: K, value: DraftState[K]) => void
}>) {
  return (
    <div className="flex min-w-0 flex-wrap items-center justify-end gap-1.5">
      <label className={cn('flex h-7 min-w-[10rem] items-center gap-1.5 rounded-[0.85rem] px-2', INLINE_FIELD_CLASS)}>
        <span className="shrink-0 text-[11px] font-medium text-muted-foreground">标签</span>
        <Input
          className="h-5 min-w-0 flex-1 border-0 bg-transparent px-0 text-xs shadow-none focus-visible:ring-1 focus-visible:ring-primary/30"
          value={draft.tags}
          onChange={(event) => updateDraft('tags', event.target.value)}
          placeholder="选择或输入标签"
        />
      </label>
      <label className={cn('flex h-7 min-w-[8.8rem] items-center gap-1.5 rounded-[0.85rem] px-2', INLINE_FIELD_CLASS)}>
        <span className="shrink-0 text-[11px] font-medium text-muted-foreground">目标目录</span>
        <Input
          className="h-5 min-w-0 flex-1 border-0 bg-transparent px-0 text-xs shadow-none focus-visible:ring-1 focus-visible:ring-primary/30"
          value={draft.collection}
          onChange={(event) => updateDraft('collection', event.target.value)}
          placeholder="default"
        />
      </label>
      <div className={cn('flex h-7 items-center gap-1.5 rounded-[0.85rem] px-2', INLINE_FIELD_CLASS)}>
        <span className="shrink-0 text-[11px] font-medium text-muted-foreground">重复处理</span>
        <Select value={draft.dedupStrategy} onValueChange={(value) => updateDraft('dedupStrategy', value)}>
          <SelectTrigger className="h-5 w-[7.8rem] border-0 bg-transparent px-0 text-xs shadow-none focus:ring-1 focus:ring-primary/30 focus:ring-offset-0">
            <SelectValue />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value="content_hash">跳过重复（推荐）</SelectItem>
            <SelectItem value="filename">按同名文件判断</SelectItem>
            <SelectItem value="none">不检查重复</SelectItem>
          </SelectContent>
        </Select>
      </div>
      <label className={cn('flex h-7 items-center gap-1.5 rounded-[0.85rem] px-2 text-xs text-muted-foreground', INLINE_FIELD_CLASS)}>
        <Switch
          checked={draft.syncDataset}
          className="h-5 w-9 data-[state=checked]:bg-primary data-[state=unchecked]:bg-muted [&>span]:h-4 [&>span]:w-4 [&>span[data-state=checked]]:translate-x-4"
          onCheckedChange={(checked) => updateDraft('syncDataset', checked)}
        />
        自动同步知识库
      </label>
    </div>
  )
}

function TaskListCard({
  tasks,
  datasetName,
  sourceName,
  draft,
  updateDraft,
  onRefresh,
  onInspectTask,
}: Readonly<{
  tasks: HistoryItem[]
  datasetName: string
  sourceName: string
  draft: DraftState
  updateDraft: <K extends keyof DraftState>(key: K, value: DraftState[K]) => void
  onRefresh: () => Promise<void>
  onInspectTask: (task: HistoryItem) => Promise<void>
}>) {
  const [page, setPage] = useState(1)
  const [statusFilter, setStatusFilter] = useState<'all' | 'running' | 'done'>('all')
  const filteredTasks = useMemo(() => {
    if (statusFilter === 'running') {
      return tasks.filter((task) => ['pending', 'running', 'processing', 'uploading', 'prechecking'].includes(task.status))
    }
    if (statusFilter === 'done') {
      return tasks.filter((task) => ['completed', 'ready'].includes(task.status))
    }
    return tasks
  }, [statusFilter, tasks])
  const totalPages = Math.max(1, Math.ceil(filteredTasks.length / TASK_LIST_PAGE_SIZE))
  const safePage = Math.min(page, totalPages)
  const paginatedTasks = useMemo(
    () =>
      filteredTasks.slice(
        (safePage - 1) * TASK_LIST_PAGE_SIZE,
        safePage * TASK_LIST_PAGE_SIZE
      ),
    [filteredTasks, safePage]
  )

  useEffect(() => {
    if (page !== safePage) setPage(safePage)
  }, [page, safePage])

  useEffect(() => {
    setPage(1)
  }, [statusFilter])

  return (
    <section className={cn(SOFT_PANEL_CLASS, 'p-2.5')}>
      <div className="mb-2 flex flex-wrap items-center justify-between gap-2">
        <SectionTitle title="入库进度与任务列表" />
        <div className="flex min-w-0 flex-wrap items-center justify-end gap-1.5">
          <IngestTaskControls draft={draft} updateDraft={updateDraft} />
          <Select value={statusFilter} onValueChange={(value) => setStatusFilter(value as 'all' | 'running' | 'done')}>
            <SelectTrigger className={cn('h-7 w-[7.6rem] text-xs', SOFT_CONTROL_CLASS)}>
              <SelectValue />
            </SelectTrigger>
            <SelectContent>
              <SelectItem value="all">状态：全部</SelectItem>
              <SelectItem value="running">入库中</SelectItem>
              <SelectItem value="done">已完成</SelectItem>
            </SelectContent>
          </Select>
          <Button
            variant="outline"
            size="icon"
            aria-label="刷新入库任务列表"
            title="刷新入库任务列表"
            className={cn('size-7 rounded-[0.85rem] hover:bg-background/92', CONFIG_INPUT_CLASS)}
            onClick={() => void onRefresh()}
          >
            <RefreshCw className="size-3.5" />
          </Button>
        </div>
      </div>
      <div className={TABLE_SHELL_CLASS}>
        <table className="w-full text-left text-xs">
          <thead className={TABLE_HEAD_CLASS}>
            <tr>
              <th className="px-2.5 py-1.5 font-medium">任务ID</th>
              <th className="px-2.5 py-1.5 font-medium">文件名（数量）</th>
              <th className="px-2.5 py-1.5 font-medium">目标数据集</th>
              <th className="px-2.5 py-1.5 font-medium">来源</th>
              <th className="px-2.5 py-1.5 font-medium">状态</th>
              <th className="px-2.5 py-1.5 font-medium">进度</th>
              <th className="px-2.5 py-1.5 font-medium">更新时间</th>
              <th className="px-2.5 py-1.5 font-medium">操作</th>
            </tr>
          </thead>
          <tbody>
            {paginatedTasks.length ? (
              paginatedTasks.map((task) => (
                <tr key={task.id} className={TABLE_ROW_CLASS}>
                  <td className="px-2.5 py-1.5 font-mono text-primary">{task.id}</td>
                  <td className="max-w-[16rem] truncate px-2.5 py-1.5 text-foreground">{task.filename ?? `${task.files ?? 1} 个文件`}</td>
                  <td className="max-w-[14rem] truncate px-2.5 py-1.5 text-muted-foreground">{datasetName}</td>
                  <td className="px-2.5 py-1.5 text-muted-foreground">{task.sourceName ?? sourceName}</td>
                  <td className="px-2.5 py-1.5">
                    <Badge variant={statusVariant(task.status)}>{statusLabel(task.status)}</Badge>
                  </td>
                  <td className="px-2.5 py-1.5">
                    <div className="flex min-w-[7rem] items-center gap-2">
                      <span className="h-1.5 flex-1 overflow-hidden rounded-full bg-muted/70">
                        <span
                          className={cn('block h-full rounded-full', task.status === 'failed' ? 'bg-destructive' : 'bg-primary')}
                          style={{ width: `${task.progress ?? 0}%` }}
                        />
                      </span>
                      <span className="w-8 text-right font-mono text-[11px] text-muted-foreground">{task.progress ?? 0}%</span>
                    </div>
                  </td>
                  <td className="px-2.5 py-1.5 text-muted-foreground">{formatDate(task.created_at)}</td>
                  <td className="px-2.5 py-1.5">
                    <Button variant="ghost" className="h-7 rounded-[0.85rem] px-2 text-xs hover:bg-background/72" onClick={() => void onInspectTask(task)}>
                      查看
                    </Button>
                  </td>
                </tr>
              ))
            ) : (
              <tr>
                <td colSpan={8} className="px-3 py-5 text-center text-muted-foreground">
                  暂无任务记录
                </td>
              </tr>
            )}
          </tbody>
        </table>
      </div>
      <div className="mt-2 flex flex-wrap items-center justify-end gap-2 border-t border-border/50 pt-2">
        <div className="items-center inline-flex gap-1 rounded-[0.95rem] border border-border/60 bg-card/72 px-1.5 py-1 text-xs text-muted-foreground shadow-sm">
          <span className="px-1 text-muted-foreground">共 {filteredTasks.length} 条</span>
          <Button
            type="button"
            variant="ghost"
            className="h-5 rounded-[0.7rem] px-1.5 text-xs hover:bg-background/72"
            disabled={safePage <= 1}
            onClick={() => setPage((current) => Math.max(1, current - 1))}
          >
            上一页
          </Button>
          <span className="min-w-[4.4rem] text-center font-mono text-[11px] text-foreground">
            第 {safePage} / {totalPages} 页
          </span>
          <Button
            type="button"
            variant="ghost"
            className="h-5 rounded-[0.7rem] px-1.5 text-xs hover:bg-background/72"
            disabled={safePage >= totalPages}
            onClick={() => setPage((current) => Math.min(totalPages, current + 1))}
          >
            下一页
          </Button>
        </div>
      </div>
    </section>
  )
}
