'use client'

import {
  type ReactNode,
  type RefObject,
  useCallback,
  useEffect,
  useId,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from 'react'
import {
  Archive,
  ArrowRight,
  ChevronDown,
  ChevronRight,
  Cloud,
  Dataset as DatasetIcon,
  Folder,
  Link as LinkIcon,
  Loader2,
  Plus,
  Search,
  Trash2,
  UploadCloud,
  X,
  type PlatformIcon,
} from '@/components/icons'
import { useQuery, useQueryClient } from '@tanstack/react-query'
import { useRouter, useSearchParams } from 'next/navigation'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from '@/components/ui/dialog'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { WorkspaceNotice } from '@/components/ui/operational-workspace'
import { getFileTypeMeta } from '@/components/knowledge/file-type'
import { Select, SelectContent, SelectItem, SelectTrigger } from '@/components/ui/select'
import { Textarea } from '@/components/ui/textarea'
import { Tooltip, TooltipContent, TooltipProvider, TooltipTrigger } from '@/components/ui/tooltip'
import { connectorApi } from '@/lib/api/connectors'
import { datasetApi } from '@/lib/api/datasets'
import {
  DOCUMENT_UPLOAD_BATCH_LIMIT,
  getUploadFilename,
  getUploadReceiptKey,
  matchUploadReceipts,
} from '@/lib/api/document-helpers'
import { documentApi } from '@/lib/api/documents'
import { settingsApi } from '@/lib/api/settings'
import { useDocumentView } from '@/store/document-view'
import { formatApiError } from '@/lib/api-errors'
import { getAuthSessionRevision, subscribeAuthSession } from '@/lib/auth-storage'
import { readClientStorage } from '@/lib/client-storage'
import { getParserOption, PARSER_BACKEND_REGISTRY_OPTIONS } from '@/lib/parser-options'
import { readNonEmptyString } from '@/lib/primitive-text'
import { queryKeys } from '@/lib/query-keys'
import { createCodePointToUtf16Converter } from '@/lib/text-offsets'
import { cn, detachPromise, formatFileSize } from '@/lib/utils'
import type { Dataset, Document, DocumentFolderNode, DocumentPipelineOptions } from '@/types'

import { IngestionViewSwitch } from './view-switch'
import { isExecutionMonitorDocument } from './document-signals'
import styles from './operation.module.css'

const DRAFT_KEY = 'mimirq.knowledge.ingestion.operation.draft'
const DEFAULT_COLLECTION = 'default'
const NO_DATASET_FILE_BUCKET = '__mimirq_no_dataset__'
const EMPTY_FILES: File[] = []

type UploadSource = 'local' | 'folder' | 'url' | 'object' | 'api'
type ParserBackend = 'auto' | 'docling' | 'markitdown' | 'deepdoc' | 'csv' | 'json' | 'markdown'
type ChunkStrategy = 'semantic' | 'langchain_recursive' | 'markdown' | 'by_title'
type IngestExecutionMode = 'upload_only' | 'parse_only' | 'full_index'
type TaskStatus = 'idle' | 'prechecking' | 'uploading' | 'completed' | 'failed'
type UploadReceipt = {
  datasetId: string
  authRevision: number
  files: readonly File[]
  response: Awaited<ReturnType<typeof documentApi.uploadBatch>>
}
type SelectOption<T extends string> = {
  value: T
  title: string
  description: string
  badge?: string
}

type DraftState = {
  datasetId: string
  syncDataset: boolean
  executionMode: IngestExecutionMode
  parserBackend: ParserBackend
  chunkStrategy: ChunkStrategy
  chunkSize: number
  chunkOverlap: number
  dedupStrategy: string
  tags: string
  collection: string
  errorPolicy: string
  refreshStats: boolean
  keepFailureTasks: boolean
}

type DatasetIngestContext = Pick<DraftState, 'tags' | 'collection'>

const DEFAULT_DRAFT: DraftState = {
  datasetId: '',
  syncDataset: false,
  executionMode: 'upload_only',
  parserBackend: 'auto',
  chunkStrategy: 'semantic',
  chunkSize: 600,
  chunkOverlap: 100,
  dedupStrategy: 'content_hash',
  tags: '',
  collection: DEFAULT_COLLECTION,
  errorPolicy: 'skip_failed',
  refreshStats: true,
  keepFailureTasks: true,
}

const SOURCE_OPTIONS: Array<{
  value: UploadSource
  label: string
  icon: PlatformIcon
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

const SOFT_CONTROL_CLASS = styles.control
const CONFIG_INPUT_CLASS = styles.control
const SELECT_MENU_CLASS = styles.menu
const SELECT_OPTION_CLASS = styles.menuOption
const EXECUTION_MODE_OPTIONS: Array<SelectOption<IngestExecutionMode>> = [
  {
    value: 'upload_only',
    title: '仅传原件',
    description: '保存文件，暂不解析',
  },
  {
    value: 'parse_only',
    title: '仅解析',
    description: '提取正文，暂不索引',
  },
  {
    value: 'full_index',
    title: '完整入库',
    description: '解析并建立检索索引',
  },
]
const DEDUP_OPTIONS: Array<SelectOption<string>> = [
  {
    value: 'content_hash',
    title: '启用',
    description: '按当前管线处理相似内容。',
    badge: '推荐',
  },
  {
    value: 'none',
    title: '关闭',
    description: '直接写入，适合临时或隔离数据。',
  },
]
function isIngestExecutionMode(value: unknown): value is IngestExecutionMode {
  return value === 'upload_only' || value === 'parse_only' || value === 'full_index'
}

function loadDraft(): DraftState {
  if (globalThis.window === undefined) return DEFAULT_DRAFT
  try {
    const raw = readClientStorage(DRAFT_KEY)
    if (!raw) return DEFAULT_DRAFT
    const parsed = JSON.parse(raw) as Partial<DraftState>
    const draft = { ...DEFAULT_DRAFT, ...parsed }
    draft.dedupStrategy = draft.dedupStrategy === 'none' ? 'none' : DEFAULT_DRAFT.dedupStrategy
    if (!Object.prototype.hasOwnProperty.call(parsed, 'executionMode') || !isIngestExecutionMode(draft.executionMode)) {
      draft.executionMode = DEFAULT_DRAFT.executionMode
      draft.syncDataset = DEFAULT_DRAFT.syncDataset
    }
    return draft
  } catch {
    return DEFAULT_DRAFT
  }
}

function fileKey(file: File) {
  return `${getUploadFilename(file)}:${file.size}:${file.lastModified}`
}

function fileRelativeFolder(file: File) {
  const path = getUploadFilename(file)
  if (!path.includes('/')) return ''
  return path.split('/').slice(0, -1).join('/').trim()
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function normalizeListText(value: string) {
  return value
    .split(/[,\n，、]/g)
    .map((item) => item.trim())
    .filter(Boolean)
}

function getSelectOptionTitle<T extends string>(options: Array<SelectOption<T>>, value: T) {
  return options.find((option) => option.value === value)?.title ?? value
}

type SelectOptionBodyProps = {
  description: string
  title: string
}

function SelectOptionBody({ description, title }: Readonly<SelectOptionBodyProps>) {
  return (
    <span className={styles.optionBody}>
      <strong>{title}</strong>
      <small>{description}</small>
    </span>
  )
}

type DatasetOptionBodyProps = { dataset: Dataset }

function DatasetOptionBody({ dataset }: Readonly<DatasetOptionBodyProps>) {
  return (
    <span className={styles.optionBody}>
      <strong>{dataset.name}</strong>
      <small>{dataset.id.slice(0, 18).toUpperCase()}</small>
    </span>
  )
}

const DOCUMENT_STATUS_FILTERS = [
  { value: 'all', label: '全部状态' },
  { value: 'registered', label: '已登记' },
  { value: 'processing', label: '解析中' },
  { value: 'completed', label: '已入库' },
  { value: 'failed', label: '失败' },
]

function getIngestionDocumentStatus(document: Document) {
  if (!isExecutionMonitorDocument(document)) return { value: 'registered', label: '已登记' }
  const labels: Record<Document['status'], string> = {
    pending: '待处理',
    processing: '解析中',
    completed: '已入库',
    failed: '失败',
    quarantined: '已隔离',
    cancelled: '已取消',
    deleting: '删除中',
  }
  return { value: document.status, label: labels[document.status] }
}

function FormatPill({ filename, fileType }: Readonly<{ filename: string; fileType?: string }>) {
  const meta = getFileTypeMeta({ filename, file_type: fileType })
  return <span className={cn(styles.formatPill, meta.color, meta.bg)}>{meta.label}</span>
}

function DatasetSelector({
  datasetId,
  datasets,
  selectedDataset,
  loading,
  locked,
  onChange,
  className,
  ariaLabel = '目标数据集',
  id,
}: Readonly<{
  datasetId: string
  datasets: Dataset[]
  selectedDataset: Dataset | null
  loading: boolean
  locked: boolean
  onChange: (value: string) => void
  className?: string
  ariaLabel?: string
  id?: string
}>) {
  return (
    <Select value={datasetId} onValueChange={onChange} disabled={locked || loading || datasets.length === 0}>
      <SelectTrigger id={id} aria-label={ariaLabel} className={cn(SOFT_CONTROL_CLASS, className)}>
        <span className={styles.controlText}>
          <DatasetIcon aria-hidden="true" />
          <span>
            {selectedDataset?.name ?? (loading ? '正在加载数据集' : datasets.length ? '选择目标数据集' : '暂无数据集')}
          </span>
        </span>
      </SelectTrigger>
      <SelectContent className={SELECT_MENU_CLASS}>
        {datasets.map((dataset) => (
          <SelectItem key={dataset.id} value={dataset.id} textValue={dataset.name} className={SELECT_OPTION_CLASS}>
            <DatasetOptionBody dataset={dataset} />
          </SelectItem>
        ))}
      </SelectContent>
    </Select>
  )
}

function getDocumentUserTags(document: Document): string[] {
  const metadata = document.metadata
  if (!isRecord(metadata)) return []
  const user = metadata.user
  const rawTags = isRecord(user) ? user.tags : metadata.tags
  if (Array.isArray(rawTags)) {
    return rawTags
      .filter((tag): tag is string => typeof tag === 'string')
      .map((tag) => tag.trim())
      .filter((tag) => tag !== '')
  }
  if (typeof rawTags === 'string') return normalizeListText(rawTags)
  return []
}

function collectTagOptions(documents: Document[], draftTags: string): string[] {
  const options = new Set<string>()
  for (const tag of normalizeListText(draftTags)) options.add(tag)
  for (const document of documents) {
    for (const tag of getDocumentUserTags(document)) options.add(tag)
  }
  return Array.from(options).sort((a, b) => a.localeCompare(b, 'zh-CN'))
}

function collectFolderPaths(root?: DocumentFolderNode | null): string[] {
  if (!root) return []
  const out: string[] = []
  const stack = [...(root.children ?? [])].reverse()
  while (stack.length) {
    const node = stack.pop()
    if (!node) continue
    const path = node.path.trim()
    if (path !== '') out.push(path)
    for (const child of [...(node.children ?? [])].reverse()) stack.push(child)
  }
  return out
}

function collectCollectionOptions(
  root: DocumentFolderNode | null | undefined,
  files: File[],
  currentCollection: string,
): string[] {
  const options = new Set<string>([DEFAULT_COLLECTION])
  for (const path of collectFolderPaths(root)) options.add(path)
  for (const file of files) {
    const folder = fileRelativeFolder(file)
    if (folder) options.add(folder)
  }
  const normalizedCurrent = currentCollection.trim()
  if (normalizedCurrent) options.add(normalizedCurrent)
  return Array.from(options).sort((a, b) => {
    if (a === DEFAULT_COLLECTION) return -1
    if (b === DEFAULT_COLLECTION) return 1
    return a.localeCompare(b, 'zh-CN')
  })
}

function shouldBuildIndexes(draft: DraftState) {
  return draft.executionMode === 'full_index'
}

function shouldOpenExecutionMonitor(draft: DraftState, mode: 'upload_only' | 'ingest') {
  return mode === 'ingest' && draft.executionMode === 'parse_only'
}

function buildPipeline(draft: DraftState): DocumentPipelineOptions {
  return {
    chunk_size: draft.chunkSize,
    chunk_overlap: draft.chunkOverlap,
    near_dedup_enabled: draft.dedupStrategy !== 'none',
    persist_parsed_content: draft.executionMode !== 'upload_only',
    chunk_vector_enabled: shouldBuildIndexes(draft),
    bm25_index_enabled: shouldBuildIndexes(draft),
  }
}

function normalizeChunkStrategy(strategy: ChunkStrategy) {
  if (strategy === 'semantic') return 'langchain_recursive'
  if (strategy === 'by_title') return 'markdown'
  return strategy
}

function parseLineList(raw: string, max: number, separator: RegExp) {
  const seen = new Set<string>()
  const values: string[] = []
  for (const item of raw.split(separator)) {
    const value = item.trim()
    if (!value || seen.has(value)) continue
    seen.add(value)
    values.push(value)
    if (values.length >= max) break
  }
  return values
}

function parseUrlList(raw: string) {
  return parseLineList(raw, 50, /\r?\n/).filter((value) => /^https?:\/\//i.test(value))
}

function parseExtensions(raw: string) {
  const extensions = parseLineList(raw, 20, /[\n,;]+/)
    .map((value) => value.toLowerCase())
    .map((value) => (value.startsWith('.') ? value : `.${value}`))
    .filter((value) => /^\.[a-z0-9]{1,12}$/i.test(value))
  return extensions.length ? extensions : ['.pdf', '.md', '.txt']
}

function apiPayloadFileType(filename: string) {
  const ext = filename.split('.').pop()?.trim().toLowerCase()
  return ext || 'json'
}

export default function KnowledgeIngestionOperationPage({ active = true }: Readonly<{ active?: boolean }>) {
  const router = useRouter()
  const openDocument = useDocumentView((state) => state.openDocument)
  const queryClient = useQueryClient()
  const authRevision = useSyncExternalStore(subscribeAuthSession, getAuthSessionRevision, getAuthSessionRevision)
  const searchParams = useSearchParams()
  const routeDatasetId = searchParams.get('datasetId')
  const activeRef = useRef(active)
  const inputRef = useRef<HTMLInputElement | null>(null)
  const sourceNavRef = useRef<HTMLElement | null>(null)
  const defaultModeRef = useRef<HTMLDivElement | null>(null)
  const folderInputRef = useRef<HTMLInputElement | null>(null)
  const observedRouteDatasetIdRef = useRef(routeDatasetId)
  const appliedRouteDatasetIdRef = useRef<string | null>(null)
  const submissionRef = useRef<{ authRevision: number } | null>(null)
  const [draft, setDraft] = useState<DraftState>(DEFAULT_DRAFT)
  const [datasetIngestContextById, setDatasetIngestContextById] = useState<Record<string, DatasetIngestContext>>({})
  const [source, setSource] = useState<UploadSource>('local')
  const [filesByDatasetId, setFilesByDatasetId] = useState<Record<string, File[]>>({})
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
  const [uploadReceipt, setUploadReceipt] = useState<UploadReceipt | null>(null)
  const currentReceipt =
    uploadReceipt?.authRevision === authRevision && uploadReceipt.datasetId === draft.datasetId ? uploadReceipt : null
  const uploadResponse = currentReceipt?.response
  const [submissionError, setSubmissionError] = useState<string | null>(null)
  const [importOpen, setImportOpen] = useState(false)
  useEffect(() => {
    if (active && importOpen) {
      sourceNavRef.current?.querySelector<HTMLElement>('[aria-pressed="true"]')?.scrollIntoView({
        inline: 'nearest',
        block: 'nearest',
      })
    }
  }, [active, importOpen, source])
  const [documentSearch, setDocumentSearch] = useState('')
  const [documentStatus, setDocumentStatus] = useState('all')
  const [documentPage, setDocumentPage] = useState(1)

  useLayoutEffect(() => {
    activeRef.current = active
  }, [active])

  useEffect(() => {
    const nextDraft = loadDraft()
    setDraft(nextDraft)
    if (nextDraft.datasetId) {
      setDatasetIngestContextById({
        [nextDraft.datasetId]: {
          tags: nextDraft.tags,
          collection: nextDraft.collection || DEFAULT_COLLECTION,
        },
      })
    }
  }, [])

  const datasetsQuery = useQuery({
    queryKey: queryKeys.datasets.exhaustive(),
    queryFn: ({ signal }) => datasetApi.listAll(undefined, { signal }),
    staleTime: 30_000,
  })

  const datasets = useMemo(() => datasetsQuery.data ?? [], [datasetsQuery.data])

  useEffect(() => {
    if (!active) {
      observedRouteDatasetIdRef.current = routeDatasetId
      appliedRouteDatasetIdRef.current = routeDatasetId
      return
    }
    if (observedRouteDatasetIdRef.current !== routeDatasetId) {
      observedRouteDatasetIdRef.current = routeDatasetId
      appliedRouteDatasetIdRef.current = null
    }
    const routeDataset = datasets.find((dataset) => dataset.id === routeDatasetId)
    const fallbackDatasetId = datasets[0]?.id
    const applyRoute = routeDataset !== undefined && appliedRouteDatasetIdRef.current !== routeDataset.id
    if (applyRoute) appliedRouteDatasetIdRef.current = routeDataset.id
    setDraft((current) => {
      if (applyRoute && current.datasetId !== routeDataset.id) return { ...current, datasetId: routeDataset.id }
      if (current.datasetId || !fallbackDatasetId) return current
      return { ...current, datasetId: fallbackDatasetId }
    })
  }, [active, datasets, routeDatasetId])

  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.id === draft.datasetId) ?? null,
    [datasets, draft.datasetId],
  )
  const activeFileBucketKey = draft.datasetId || NO_DATASET_FILE_BUCKET
  const files = filesByDatasetId[activeFileBucketKey] ?? EMPTY_FILES

  useLayoutEffect(() => {
    setUploadReceipt(null)
    setSubmissionError(null)
    setStatus('idle')
    return () => {
      submissionRef.current = null
    }
  }, [authRevision, draft.datasetId])

  useEffect(() => {
    if (!draft.datasetId) return
    const context = datasetIngestContextById[draft.datasetId]
    const nextTags = context?.tags ?? DEFAULT_DRAFT.tags
    const nextCollection = context?.collection ?? DEFAULT_COLLECTION
    setDraft((current) => {
      if (current.datasetId !== draft.datasetId) return current
      if (current.tags === nextTags && current.collection === nextCollection) return current
      return { ...current, tags: nextTags, collection: nextCollection }
    })
  }, [datasetIngestContextById, draft.datasetId])

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

  const foldersQuery = useQuery({
    queryKey: ['knowledge-ingestion-operation-folders', draft.datasetId],
    queryFn: ({ signal }) => documentApi.folders({ dataset_id: draft.datasetId, max_depth: 20 }, { signal }),
    enabled: Boolean(draft.datasetId),
    staleTime: 10_000,
  })

  const tagOptions = useMemo(() => collectTagOptions(documents, draft.tags), [documents, draft.tags])
  const collectionOptions = useMemo(
    () => collectCollectionOptions(foldersQuery.data?.root, files, draft.collection),
    [draft.collection, files, foldersQuery.data?.root],
  )

  const settingsQuery = useQuery({
    queryKey: ['knowledge-ingestion-operation-settings'],
    queryFn: () => settingsApi.get(),
    staleTime: 30_000,
  })

  const urlIngestEnabled = Boolean(settingsQuery.data?.url_ingest?.enabled)

  const refreshDataset = useCallback(
    (datasetId: string, includeDocuments = true) =>
      Promise.all(
        [
          ...(includeDocuments ? ['knowledge-ingestion-operation-documents'] : []),
          'knowledge-ingestion-operation-folders',
          'knowledge-ingestion-operation-stats',
        ].map((prefix) =>
          queryClient.invalidateQueries({ queryKey: [prefix, datasetId], exact: true, refetchType: 'all' }),
        ),
      ),
    [queryClient],
  )

  const selectedTotalBytes = useMemo(() => files.reduce((sum, file) => sum + file.size, 0), [files])

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
    Boolean(selectedDataset) && status !== 'uploading' && pendingSourceCount > 0 && !connectorSourceBlocked

  const totalDocuments = ingestionStats?.total_documents ?? documents.length

  const fileRows = useMemo(() => files.map((file) => ({ file, key: fileKey(file) })), [files])

  const updateDraft = useCallback(
    <K extends keyof DraftState>(key: K, value: DraftState[K]) => {
      if ((key === 'tags' || key === 'collection') && draft.datasetId) {
        setDatasetIngestContextById((current) => {
          const previous = current[draft.datasetId] ?? {
            tags: DEFAULT_DRAFT.tags,
            collection: DEFAULT_COLLECTION,
          }
          return {
            ...current,
            [draft.datasetId]: {
              ...previous,
              [key]: String(value),
            },
          }
        })
      }
      setDraft((current) => ({ ...current, [key]: value }))
    },
    [draft.datasetId],
  )

  const addFiles = useCallback(
    (incoming: File[]) => {
      const supported = incoming.filter((file) => {
        const lower = file.name.toLowerCase()
        return ACCEPTED_EXTENSIONS.some((ext) => lower.endsWith(ext))
      })
      const rejected = incoming.length - supported.length
      setFilesByDatasetId((current) => {
        const activeFiles = current[activeFileBucketKey] ?? []
        const byKey = new Map(activeFiles.map((file) => [fileKey(file), file]))
        for (const file of supported) byKey.set(fileKey(file), file)
        return {
          ...current,
          [activeFileBucketKey]: Array.from(byKey.values()),
        }
      })
      if (rejected > 0) {
        toast.warning(`${rejected} 个文件格式未在允许列表中，已跳过`)
      }
    },
    [activeFileBucketKey],
  )

  const clearFiles = useCallback(() => {
    setFilesByDatasetId((current) => ({
      ...current,
      [activeFileBucketKey]: [],
    }))
    setUploadReceipt(null)
    setSubmissionError(null)
    setStatus('idle')
  }, [activeFileBucketKey])

  const removeFile = useCallback(
    (key: string) => {
      setFilesByDatasetId((current) => ({
        ...current,
        [activeFileBucketKey]: (current[activeFileBucketKey] ?? []).filter((file) => fileKey(file) !== key),
      }))
    },
    [activeFileBucketKey],
  )

  const submitConnectorRun = useCallback(async () => {
    if (submissionRef.current) return
    if (!draft.datasetId) {
      toast.error('请先选择目标数据集')
      return
    }
    if (!urlIngestEnabled) {
      toast.error('URL 导入未启用，请联系管理员启用后重试。')
      return
    }
    const submission = { authRevision: getAuthSessionRevision() }
    submissionRef.current = submission
    const ownsSubmission = () =>
      submissionRef.current === submission && submission.authRevision === getAuthSessionRevision()
    setStatus('uploading')
    setUploadReceipt(null)
    setSubmissionError(null)
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
                filename: readNonEmptyString(urlFilename),
                ...sharedConfig,
              },
            })
          : await connectorApi.createRun({
              connector_id: 'minio_bucket',
              dataset_id: draft.datasetId,
              config: {
                bucket: readNonEmptyString(objectBucket),
                prefix: readNonEmptyString(objectPrefix),
                include_extensions: parsedObjectExtensions,
                max_objects: objectMaxObjects,
                ...sharedConfig,
              },
            })
      if (submission.authRevision === getAuthSessionRevision()) await refreshDataset(draft.datasetId, false)
      if (!ownsSubmission()) return
      setStatus(run.status === 'failed' || run.status === 'cancelled' ? 'failed' : 'completed')
      toast.success(`连接器任务已创建：${run.id.slice(0, 8)}`)
      if (run.status !== 'failed' && shouldOpenExecutionMonitor(draft, 'ingest')) {
        if (activeRef.current) {
          router.push(`/knowledge/ingestion?mode=execution-monitor&datasetId=${encodeURIComponent(draft.datasetId)}`)
        }
      }
    } catch (error) {
      if (!ownsSubmission()) return
      setStatus('failed')
      const message = formatApiError(error, '连接器任务创建失败')
      setSubmissionError(message)
    } finally {
      if (submissionRef.current === submission) {
        submissionRef.current = null
        if (submission.authRevision !== getAuthSessionRevision()) setStatus('idle')
      }
    }
  }, [
    draft,
    objectBucket,
    objectMaxObjects,
    objectPrefix,
    parsedObjectExtensions,
    parsedUrls,
    router,
    refreshDataset,
    source,
    urlIngestEnabled,
    urlFilename,
  ])

  const handleSyncDatasets = useCallback(async () => {
    const authRevision = getAuthSessionRevision()
    try {
      await datasetsQuery.refetch({ throwOnError: true })
      if (authRevision !== getAuthSessionRevision()) return
      if (draft.datasetId) {
        await Promise.all(
          [
            'knowledge-ingestion-operation-documents',
            'knowledge-ingestion-operation-folders',
            'knowledge-ingestion-operation-stats',
          ].map((prefix) =>
            queryClient.refetchQueries(
              { queryKey: [prefix, draft.datasetId], exact: true, type: 'all' },
              { throwOnError: true },
            ),
          ),
        )
      }
      if (authRevision === getAuthSessionRevision()) toast.success('数据集状态已同步')
    } catch (error) {
      if (authRevision === getAuthSessionRevision()) toast.error(formatApiError(error, '数据集状态同步失败'))
    }
  }, [datasetsQuery, draft.datasetId, queryClient])

  const uploadFiles = useCallback(
    async (mode: 'upload_only' | 'ingest') => {
      if (submissionRef.current) return
      if (!draft.datasetId) {
        toast.error('请先选择目标数据集')
        return
      }
      if (mode === 'upload_only' && (source === 'url' || source === 'object')) {
        toast.error('URL/对象存储不能使用仅传原件，请先下载为本地文件或选择仅解析或完整入库')
        return
      }
      if (mode === 'upload_only' && source === 'api') {
        toast.error('API 导入没有原始文件可上传，请选择仅解析或完整入库')
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
      const submission = { authRevision: getAuthSessionRevision() }
      submissionRef.current = submission
      const ownsSubmission = () =>
        submissionRef.current === submission && submission.authRevision === getAuthSessionRevision()
      setStatus('uploading')
      setUploadReceipt(null)
      setSubmissionError(null)
      try {
        if (source === 'api') {
          const filename = readNonEmptyString(apiFilename) ?? 'api-payload.json'
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
            },
            chunks: [
              {
                content: apiContent,
                page_number: 1,
                start_char: 0,
                end_char: createCodePointToUtf16Converter(apiContent).codePointLength,
                metadata: {
                  source: 'api',
                  collection: draft.collection,
                },
              },
            ],
          })
          if (submission.authRevision === getAuthSessionRevision()) await refreshDataset(draft.datasetId)
          if (!ownsSubmission()) return
          setUploadReceipt({
            datasetId: draft.datasetId,
            authRevision: submission.authRevision,
            files: [],
            response: {
              total: 1,
              successful_count: 1,
              failed_count: 0,
              successful: [{ document_id: document.id, filename, status: document.status }],
              failed: [],
            },
          })
          setStatus('completed')
          toast.success(`API 导入已写入：${filename}`)
          return
        }
        const uploadOptions = {
          dataset_id: draft.datasetId,
          parser_backend: draft.parserBackend,
          chunk_strategy: normalizeChunkStrategy(draft.chunkStrategy),
          pipeline: buildPipeline(draft),
          upload_only: mode === 'upload_only',
          max_concurrent: 4,
          user_metadata_map: Object.fromEntries(
            uploadTargets.map((file) => [
              getUploadFilename(file),
              {
                tags: draft.tags
                  .split(',')
                  .map((tag) => tag.trim())
                  .filter(Boolean),
                collection: draft.collection,
                source,
              },
            ]),
          ),
        }
        const response = await documentApi.uploadBatch(uploadTargets, uploadOptions)
        if (submission.authRevision === getAuthSessionRevision()) await refreshDataset(draft.datasetId)
        if (!ownsSubmission()) return
        setUploadReceipt({
          datasetId: draft.datasetId,
          authRevision: submission.authRevision,
          files: uploadTargets,
          response,
        })
        setStatus(response.failed_count > 0 ? 'failed' : 'completed')
        if (response.successful_count === 0) {
          toast.error(`文件提交失败：${response.failed_count} 个文件`)
          return
        }
        if (response.failed_count > 0) {
          toast.warning(`已提交 ${response.successful_count} 个文件，失败 ${response.failed_count} 个`)
          return
        }
        toast.success(
          mode === 'upload_only'
            ? `已登记 ${response.successful_count} 个文件`
            : `已提交 ${response.successful_count} 个文件`,
        )
        if (shouldOpenExecutionMonitor(draft, mode)) {
          if (activeRef.current) {
            router.push(`/knowledge/ingestion?mode=execution-monitor&datasetId=${encodeURIComponent(draft.datasetId)}`)
          }
        }
      } catch (error) {
        if (!ownsSubmission()) return
        setStatus('failed')
        const message = formatApiError(error, '入库任务提交失败')
        setSubmissionError(message)
      } finally {
        if (submissionRef.current === submission) {
          submissionRef.current = null
          if (submission.authRevision !== getAuthSessionRevision()) setStatus('idle')
        }
      }
    },
    [apiContent, apiFilename, draft, files, parsedUrls.length, router, refreshDataset, source, submitConnectorRun],
  )

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

  const sourceExecutionBlocked =
    draft.executionMode === 'upload_only' && (source === 'url' || source === 'object' || source === 'api')
  const isFileSource = source === 'local' || source === 'folder'
  const exceedsBatchLimit = isFileSource && files.length > DOCUMENT_UPLOAD_BATCH_LIMIT
  const operationReady = canStartIngest && !sourceExecutionBlocked && !exceedsBatchLimit
  const actionLabel =
    draft.executionMode === 'upload_only'
      ? '上传原件'
      : draft.executionMode === 'full_index'
        ? '开始完整入库'
        : '上传并解析'
  const emptySourceMessage = isFileSource
    ? '请添加待入库文件'
    : source === 'url'
      ? '请填写至少一个有效 URL'
      : source === 'object'
        ? '请配置对象存储范围'
        : '请填写 API 导入内容'
  let preflightMessage = emptySourceMessage
  if (selectedDataset === null) preflightMessage = '请选择可用的数据集'
  else if (connectorSourceBlocked) preflightMessage = '当前环境未启用 URL/对象存储导入'
  else if (sourceExecutionBlocked) preflightMessage = '当前来源不支持“仅传原件”，请选择仅解析或完整入库'
  else if (exceedsBatchLimit) preflightMessage = `一次最多提交 ${DOCUMENT_UPLOAD_BATCH_LIMIT} 个文件，请分批提交`
  const submissionSummary = uploadResponse
    ? `上次提交：成功 ${uploadResponse.successful_count} · 失败 ${uploadResponse.failed_count}`
    : null
  const isSubmitting = status === 'uploading'

  useEffect(() => {
    if (!active || isSubmitting) return
    const onDragOver = (event: DragEvent) => {
      if (!event.dataTransfer?.types.includes('Files')) return
      event.preventDefault()
      setSource('local')
      setImportOpen(true)
      setDragging(true)
    }
    const onDrop = (event: DragEvent) => {
      if (!event.dataTransfer?.files.length) return
      event.preventDefault()
      setSource('local')
      setImportOpen(true)
      setDragging(false)
      addFiles(Array.from(event.dataTransfer.files))
    }
    const onDragEnd = () => setDragging(false)
    window.addEventListener('dragover', onDragOver)
    window.addEventListener('drop', onDrop)
    window.addEventListener('dragend', onDragEnd)
    return () => {
      window.removeEventListener('dragover', onDragOver)
      window.removeEventListener('drop', onDrop)
      window.removeEventListener('dragend', onDragEnd)
    }
  }, [active, addFiles, isSubmitting])

  const filteredDocuments = documents.filter(
    (document) =>
      document.filename.toLocaleLowerCase().includes(documentSearch.trim().toLocaleLowerCase()) &&
      (documentStatus === 'all' || getIngestionDocumentStatus(document).value === documentStatus),
  )
  const pageSize = 20
  const pageCount = Math.max(1, Math.ceil(filteredDocuments.length / pageSize))
  const currentPage = Math.min(documentPage, pageCount)
  const visibleDocuments = filteredDocuments.slice((currentPage - 1) * pageSize, currentPage * pageSize)
  const datasetSelectorProps = {
    datasetId: draft.datasetId,
    datasets,
    selectedDataset,
    loading: datasetsQuery.isLoading,
    locked: isSubmitting,
    onChange: (value: string) => {
      updateDraft('datasetId', value)
      setDocumentPage(1)
    },
  }
  const configurationProps = {
    draft,
    updateDraft,
    datasets,
    selectedDataset,
    documentCount: ingestionStatsQuery.isSuccess ? totalDocuments : undefined,
    loading: datasetsQuery.isLoading,
    loadError: datasetsQuery.isError,
    locked: isSubmitting,
    onRetry: () => detachPromise(handleSyncDatasets()),
    onCreate: () => router.push('/datasets'),
    tagOptions,
    collectionOptions,
  }
  const openImport = () => {
    setDragging(false)
    setImportOpen(true)
  }
  const openImportWithSource = (nextSource: UploadSource) => {
    setSource(nextSource)
    setDragging(false)
    setImportOpen(true)
  }
  const activeExecutionModeOption =
    EXECUTION_MODE_OPTIONS.find((option) => option.value === draft.executionMode) ?? EXECUTION_MODE_OPTIONS[0]

  return (
    <div data-ingestion-operation-root="true" className={styles.page} aria-busy={isSubmitting}>
      <header className={styles.header}>
        <div className={styles.title}>
          <PageTitleIcon name="ingestion-operation" className={styles.titleIcon} />
          <h1>入库管理</h1>
        </div>
        <IngestionViewSwitch className={styles.viewSwitch} />
        <div className={styles.headerActions}>
          <Button variant="ghost" className={styles.quietButton} onClick={() => router.push('/knowledge')}>
            查看文档
          </Button>
        </div>
      </header>
      <div className={styles.toolbar}>
        <div className={styles.datasetScope}>
          <DatasetSelector {...datasetSelectorProps} className={styles.scopeSelect} ariaLabel="当前数据集" />
          <span className={styles.documentCount}>共 {totalDocuments.toLocaleString()} 条文档</span>
          <Button
            variant="ghost"
            className={styles.quietButton}
            onClick={() => router.push('/datasets')}
            disabled={isSubmitting}
          >
            <Plus className="size-3.5" />
            新建
          </Button>
        </div>
        <div className={styles.filters}>
          <label className={styles.search}>
            <Search aria-hidden="true" className="size-4" />
            <Input
              placeholder="搜索文档名称"
              aria-label="搜索文档名称"
              value={documentSearch}
              onChange={(event) => {
                setDocumentSearch(event.target.value)
                setDocumentPage(1)
              }}
            />
          </label>
          <Select
            value={documentStatus}
            onValueChange={(value) => {
              setDocumentStatus(value)
              setDocumentPage(1)
            }}
          >
            <SelectTrigger className={cn(styles.control, styles.statusSelect)} aria-label="处理状态筛选">
              {DOCUMENT_STATUS_FILTERS.find((option) => option.value === documentStatus)?.label}
            </SelectTrigger>
            <SelectContent className={styles.menu}>
              {DOCUMENT_STATUS_FILTERS.map((option) => (
                <SelectItem key={option.value} value={option.value}>
                  {option.label}
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          <Button className={styles.submitButton} onClick={openImport} data-ingestion-import-trigger="true">
            <Plus className="size-4" />
            导入文档
          </Button>
        </div>
      </div>
      {datasetsQuery.isError ? (
        <WorkspaceNotice
          placement="floating"
          title="数据集加载失败"
          error={datasetsQuery.error}
          fallbackMessage="数据集加载失败"
          retry={() => detachPromise(handleSyncDatasets())}
          retryLabel="重试"
        />
      ) : null}
      <div data-ingestion-operation-workspace="true" className={styles.workspace}>
        {documentsQuery.isError ? (
          <div className={styles.emptyQueue} role="alert">
            <strong>文档加载失败</strong>
            <p>请重试以获取当前数据集的文档。</p>
            <Button variant="outline" onClick={() => detachPromise(documentsQuery.refetch())}>
              重试
            </Button>
          </div>
        ) : datasetsQuery.isLoading || (draft.datasetId && documentsQuery.isLoading) ? (
          <div className={styles.emptyQueue} role="status">
            <Loader2 className="size-5 animate-spin" />
            正在加载文档
          </div>
        ) : filteredDocuments.length === 0 ? (
          documentSearch || documentStatus !== 'all' ? (
            <div className={styles.emptyQueue} data-ingestion-document-empty="true">
              <UploadCloud aria-hidden="true" />
              <strong>没有匹配的文档</strong>
              <p>试试其他名称或处理状态。</p>
              <Button
                variant="outline"
                onClick={() => {
                  setDocumentSearch('')
                  setDocumentStatus('all')
                  setDocumentPage(1)
                }}
              >
                清除筛选
              </Button>
            </div>
          ) : (
            <div className={styles.emptySplitStudio} data-ingestion-document-empty="true">
              <section className={styles.emptyIntakeStage} aria-label="本地文档导入">
                <div className={styles.emptyDocIllust} aria-hidden="true">
                  <svg viewBox="0 0 184 134" fill="none">
                    <ellipse cx="92" cy="116" rx="68" ry="10" fill="hsl(var(--surface-2))" />
                    <rect
                      x="38"
                      y="26"
                      width="60"
                      height="76"
                      rx="7"
                      transform="rotate(-7 38 26)"
                      fill="hsl(var(--surface-2))"
                      stroke="currentColor"
                      strokeOpacity="0.14"
                      strokeWidth="1.2"
                    />
                    <rect
                      x="58"
                      y="18"
                      width="66"
                      height="84"
                      rx="7"
                      fill="hsl(var(--surface-2))"
                      stroke="currentColor"
                      strokeOpacity="0.15"
                      strokeWidth="1.2"
                    />
                    <rect
                      x="68"
                      y="24"
                      width="68"
                      height="86"
                      rx="7"
                      fill="hsl(var(--card))"
                      stroke="currentColor"
                      strokeOpacity="0.2"
                      strokeWidth="1.2"
                    />
                    <path d="M116 24V42H136" stroke="currentColor" strokeOpacity="0.2" strokeWidth="1.2" />
                    <rect x="82" y="44" width="26" height="4" rx="2" fill="currentColor" fillOpacity="0.18" />
                    <rect x="82" y="54" width="38" height="4" rx="2" fill="currentColor" fillOpacity="0.14" />
                    <path
                      d="M93 90.5H89.5C86.46 90.5 84 88.04 84 85C84 82.22 86.06 79.93 88.74 79.56C89.58 75.8 92.93 73 96.95 73C101.6 73 105.38 76.78 105.38 81.43C105.38 81.7 105.36 81.97 105.33 82.23C107.42 82.82 108.95 84.74 108.95 87.02C108.95 89.77 106.72 92 103.97 92H101.5"
                      stroke="hsl(var(--accent))"
                      strokeWidth="1.6"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                    <path
                      d="M96.5 92V81.5M96.5 81.5L92.5 85.5M96.5 81.5L100.5 85.5"
                      stroke="hsl(var(--accent))"
                      strokeWidth="1.6"
                      strokeLinecap="round"
                      strokeLinejoin="round"
                    />
                  </svg>
                </div>
                <h2>开始导入你的文档</h2>
                <p>选择文件或文件夹上传，系统将根据所选处理模式完成解析、切块与索引。</p>
                <div className={styles.emptyFormatRow} aria-label="支持的文件格式">
                  {['PDF', 'DOCX', 'XLSX', 'MD', 'ZIP'].map((format) => (
                    <span key={format}>{format}</span>
                  ))}
                </div>
                <div className={styles.emptyStageActions}>
                  <Button
                    className={styles.submitButton}
                    onClick={() => openImportWithSource('local')}
                    disabled={isSubmitting}
                  >
                    <UploadCloud className="size-4" />
                    选择文件
                  </Button>
                  <Button variant="outline" onClick={() => openImportWithSource('folder')} disabled={isSubmitting}>
                    <Folder className="size-4" />
                    选择文件夹
                  </Button>
                </div>
                <button
                  type="button"
                  className={styles.currentMode}
                  disabled={isSubmitting}
                  onClick={() =>
                    defaultModeRef.current?.querySelector<HTMLButtonElement>('[aria-pressed="true"]')?.focus()
                  }
                >
                  当前模式：{activeExecutionModeOption.title}
                  <span>切换</span>
                </button>
              </section>
              <aside className={styles.emptyOptionsStage} aria-label="处理模式与其他导入方式">
                <div className={styles.emptyOptionsGroup}>
                  <h3>处理模式</h3>
                  <div ref={defaultModeRef} className={styles.emptyModeSegment} role="group" aria-label="默认处理模式">
                    {EXECUTION_MODE_OPTIONS.map((option) => (
                      <button
                        key={option.value}
                        type="button"
                        aria-pressed={draft.executionMode === option.value}
                        disabled={isSubmitting}
                        onClick={() => updateDraft('executionMode', option.value)}
                      >
                        {option.title}
                      </button>
                    ))}
                  </div>
                  <p className={styles.emptyModeHint}>{activeExecutionModeOption.description}</p>
                </div>
                <div className={styles.emptyOptionsGroup}>
                  <h3>其他导入方式</h3>
                  <div className={styles.emptySourceList}>
                    {[
                      { source: 'folder' as const, label: '文件夹批量导入', icon: Folder },
                      { source: 'url' as const, label: 'URL 列表', icon: LinkIcon },
                      { source: 'object' as const, label: '对象存储（S3 / OSS）', icon: Cloud },
                      { source: 'api' as const, label: 'API 推送', icon: Archive },
                    ].map((item) => {
                      const SourceIcon = item.icon
                      return (
                        <button
                          key={item.source}
                          type="button"
                          className={styles.emptySourceRow}
                          disabled={isSubmitting}
                          onClick={() => openImportWithSource(item.source)}
                        >
                          <SourceIcon className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                          <span>{item.label}</span>
                          <ChevronRight className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                        </button>
                      )
                    })}
                  </div>
                </div>
              </aside>
            </div>
          )
        ) : (
          <div className={styles.documentTableWrap}>
            <table className={styles.documentTable} aria-label="数据集文档">
              <colgroup>
                <col className={styles.indexCol} />
                <col />
                <col className={styles.sizeCol} />
                <col className={styles.statusCol} />
                <col className={styles.dateCol} />
                <col className={styles.documentActionsCol} />
              </colgroup>
              <thead>
                <tr>
                  <th scope="col">#</th>
                  <th scope="col">文档名称</th>
                  <th scope="col" className={styles.numeric}>
                    大小
                  </th>
                  <th scope="col">处理状态</th>
                  <th scope="col">入库时间</th>
                  <th scope="col">
                    <span className="sr-only">操作</span>
                  </th>
                </tr>
              </thead>
              <tbody>
                {visibleDocuments.map((document, index) => {
                  const state = getIngestionDocumentStatus(document)
                  return (
                    <tr key={document.id}>
                      <td className={styles.rowIndex}>{(currentPage - 1) * pageSize + index + 1}</td>
                      <td>
                        <div className={styles.fileName}>
                          <FormatPill filename={document.filename} fileType={document.file_type} />
                          <strong title={document.filename}>{document.filename}</strong>
                        </div>
                      </td>
                      <td className={styles.numeric}>{formatFileSize(document.file_size)}</td>
                      <td>
                        <span className={styles.fileState} data-state={state.value}>
                          {state.label}
                        </span>
                      </td>
                      <td className={styles.documentDate}>
                        {new Date(document.created_at).toLocaleString('zh-CN', {
                          year: 'numeric',
                          month: '2-digit',
                          day: '2-digit',
                          hour: '2-digit',
                          minute: '2-digit',
                          hour12: false,
                        })}
                      </td>
                      <td>
                        <Button
                          variant="ghost"
                          className={styles.quietButton}
                          onClick={() => openDocument(document.id)}
                        >
                          查看文档
                        </Button>
                      </td>
                    </tr>
                  )
                })}
              </tbody>
            </table>
          </div>
        )}
      </div>
      <footer className={styles.pagination} data-task-center-dock="true">
        <span>
          {filteredDocuments.length} 条
          {totalDocuments > documents.length
            ? ` · 已加载 ${documents.length} / 共 ${totalDocuments} 条，搜索与筛选仅作用于已加载文档`
            : ''}
        </span>
        {totalDocuments > documents.length ? (
          <Button
            variant="ghost"
            className={styles.quietButton}
            onClick={() => router.push(`/knowledge?dataset=${encodeURIComponent(draft.datasetId)}`)}
          >
            查看全部文档
          </Button>
        ) : null}
        {pageCount > 1 ? (
          <div className={styles.pageControls}>
            <Button variant="outline" disabled={currentPage === 1} onClick={() => setDocumentPage(currentPage - 1)}>
              上一页
            </Button>
            <span aria-live="polite">
              {currentPage} / {pageCount}
            </span>
            <Button
              variant="outline"
              disabled={currentPage === pageCount}
              onClick={() => setDocumentPage(currentPage + 1)}
            >
              下一页
            </Button>
          </div>
        ) : null}
      </footer>

      <Dialog
        open={active && importOpen}
        onOpenChange={(open) => {
          if (!isSubmitting) {
            setImportOpen(open)
            setDragging(false)
          }
        }}
      >
        <DialogContent className={cn('max-w-[900px]', styles.importDialog)} showCloseButton={false}>
          <DialogHeader className={styles.dialogHeader}>
            <DialogTitle>导入文档</DialogTitle>
            <DialogDescription className="sr-only">添加导入内容，选择目标数据集和处理方式后提交。</DialogDescription>
            <Button
              variant="ghost"
              className={styles.dialogClose}
              aria-label="关闭导入文档"
              onClick={() => setImportOpen(false)}
              disabled={isSubmitting}
            >
              <X className="size-4" />
            </Button>
          </DialogHeader>
          <div className={styles.sourceNavFrame}>
            <nav ref={sourceNavRef} className={styles.sourceNav} aria-label="文件来源">
              {SOURCE_OPTIONS.map((option) => {
                const Icon = option.icon
                return (
                  <button
                    key={option.value}
                    type="button"
                    className={styles.sourceTab}
                    aria-pressed={source === option.value}
                    onFocus={(event) => event.currentTarget.scrollIntoView({ inline: 'nearest', block: 'nearest' })}
                    onClick={() => setSource(option.value)}
                    disabled={isSubmitting}
                  >
                    <Icon aria-hidden="true" />
                    {option.label}
                  </button>
                )
              })}
            </nav>
          </div>
          <div className={styles.dialogBody} data-ingestion-dialog-body="true">
            <section className={styles.filesPane} aria-label="导入内容">
              <h2 className={styles.sectionTitle}>导入内容</h2>
              <fieldset disabled={isSubmitting} className={styles.sourceContent} data-ingestion-file-stage="true">
                {source === 'local' ? (
                  <UploadDropArea
                    dragging={dragging}
                    onDragState={setDragging}
                    onClick={() => inputRef.current?.click()}
                    onFiles={addFiles}
                    disabled={isSubmitting}
                  />
                ) : null}
                {source === 'folder' ? <SourceConfiguration source="folder" {...sourceConfigurationProps} /> : null}
                {source === 'url' ? <SourceConfiguration source="url" {...sourceConfigurationProps} /> : null}
                {source === 'object' ? <SourceConfiguration source="object" {...sourceConfigurationProps} /> : null}
                {source === 'api' ? <SourceConfiguration source="api" {...sourceConfigurationProps} /> : null}
                <input
                  ref={inputRef}
                  type="file"
                  multiple
                  className="sr-only"
                  aria-label="选择待入库文件"
                  tabIndex={-1}
                  accept={ACCEPTED_EXTENSIONS.join(',')}
                  disabled={isSubmitting}
                  onChange={(event) => {
                    addFiles(Array.from(event.target.files ?? []))
                    event.target.value = ''
                  }}
                />
              </fieldset>
              {isFileSource && files.length > 0 ? (
                <SelectedFilesTable
                  rows={fileRows}
                  onClear={clearFiles}
                  onRemove={removeFile}
                  disabled={isSubmitting}
                  receipt={currentReceipt}
                />
              ) : null}
            </section>
            <aside data-ingestion-context-panel="true" className={styles.settingsPane} aria-label="入库配置">
              <IngestionConfiguration {...configurationProps} />
              {submissionError ? (
                <p role="alert" className={styles.submissionError}>
                  {submissionError}。文件和配置已保留，可再次提交。
                </p>
              ) : null}
              {submissionSummary ? (
                <p role="status" className={styles.receipt}>
                  {submissionSummary}
                </p>
              ) : null}
            </aside>
          </div>
          <footer data-ingestion-action-bar="true" className={styles.submitBar}>
            <div className={styles.submitSummary} aria-live="polite">
              <strong>
                {pendingSourceCount === 0
                  ? isFileSource
                    ? '尚未添加文件'
                    : '尚未添加内容'
                  : isFileSource
                    ? `已选择 ${files.length} 个文件 · ${formatFileSize(selectedTotalBytes)}`
                    : `已配置 ${pendingSourceCount} ${source === 'url' ? '个 URL' : source === 'api' ? '份 API 内容' : '个对象（上限）'}`}
              </strong>
              {!operationReady && !isSubmitting ? <span>{preflightMessage}</span> : null}
            </div>
            <div className={styles.footerActions}>
              <Button variant="outline" onClick={() => setImportOpen(false)} disabled={isSubmitting}>
                取消
              </Button>
              <Button
                data-ingestion-submit="true"
                className={styles.submitButton}
                onClick={() =>
                  detachPromise(uploadFiles(draft.executionMode === 'upload_only' ? 'upload_only' : 'ingest'))
                }
                disabled={!operationReady}
              >
                {isSubmitting ? <Loader2 className="size-4 animate-spin" /> : <ArrowRight className="size-4" />}
                {isSubmitting ? '正在提交' : actionLabel}
              </Button>
            </div>
          </footer>
        </DialogContent>
      </Dialog>
    </div>
  )
}
type FieldBlockProps = {
  label: string
  required?: boolean
  children: ReactNode
}

function FieldBlock({ label, required, children }: Readonly<FieldBlockProps>) {
  return (
    <label className={styles.fieldBlock}>
      <span className={styles.fieldBlockLabel}>
        {required ? <span>*</span> : null}
        {label}
      </span>
      {children}
    </label>
  )
}

function UploadDropArea({
  dragging,
  onDragState,
  onClick,
  onFiles,
  disabled,
}: Readonly<{
  dragging: boolean
  onDragState: (dragging: boolean) => void
  onClick: () => void
  onFiles: (files: File[]) => void
  disabled: boolean
}>) {
  return (
    <button
      type="button"
      className={styles.dropArea}
      data-dragging={dragging}
      data-ingestion-empty-file-drop="true"
      disabled={disabled}
      onClick={onClick}
      onDragOver={(event) => {
        event.preventDefault()
        event.stopPropagation()
        if (!disabled) onDragState(true)
      }}
      onDragLeave={() => onDragState(false)}
      onDrop={(event) => {
        event.preventDefault()
        event.stopPropagation()
        onDragState(false)
        if (!disabled) onFiles(Array.from(event.dataTransfer.files))
      }}
    >
      <span className={styles.uploadBadge} aria-hidden="true">
        <UploadCloud />
      </span>
      <span className={styles.dropCopy}>
        <strong>拖入或选择文件，添加到本次导入</strong>
        <span>支持批量上传，单文件 ≤ 2 GB</span>
      </span>
      <span className={styles.formatChips} aria-label="支持的文件格式">
        {['PDF', 'DOCX', 'XLSX', 'Markdown', 'HTML', 'ZIP'].map((format) => (
          <span key={format}>{format}</span>
        ))}
      </span>
      <span className={styles.addFiles}>
        <Plus aria-hidden="true" />
        选择文件
      </span>
    </button>
  )
}

type SourceConfigurationProps = {
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
}: Readonly<SourceConfigurationProps>) {
  if (source === 'folder') {
    return (
      <div className={styles.folderSource}>
        <div>
          <strong>选择本地文件夹</strong>
          <p>批量添加文件，保留文件夹中的相对路径。</p>
        </div>
        <Button variant="outline" className={styles.addFiles} onClick={() => folderInputRef.current?.click()}>
          <Folder className="size-4" />
          选择文件夹
        </Button>
        <input
          ref={(element) => {
            folderInputRef.current = element
            element?.setAttribute('webkitdirectory', '')
            element?.setAttribute('directory', '')
          }}
          type="file"
          multiple
          className="sr-only"
          aria-label="选择待入库文件夹"
          tabIndex={-1}
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
      <div className={styles.sourceForm}>
        <FieldBlock label="URL 列表">
          <Textarea
            className={cn('min-h-32', CONFIG_INPUT_CLASS)}
            value={urlList}
            onChange={(event) => setUrlList(event.target.value)}
            placeholder={'https://example.com/manual.pdf\nhttps://example.com/guide.md'}
          />
          <p>
            {urlIngestEnabled
              ? '每行一个文件地址，已识别 ' + parsedUrls.length + ' 个有效链接。'
              : 'URL 导入未启用，请联系管理员启用后重试。'}
          </p>
        </FieldBlock>
        <FieldBlock label="统一文件名（可选）">
          <Input
            className={CONFIG_INPUT_CLASS}
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
      <div className={cn(styles.sourceForm, styles.sourceFormColumns)}>
        {!urlIngestEnabled ? (
          <p className={styles.sourceNotice}>对象存储导入需要通过文件地址拉取内容，请联系管理员启用 URL 导入。</p>
        ) : null}
        <FieldBlock label="Bucket（可选）">
          <Input
            className={CONFIG_INPUT_CLASS}
            value={objectBucket}
            onChange={(event) => setObjectBucket(event.target.value)}
            placeholder="使用已配置的存储桶"
          />
        </FieldBlock>
        <FieldBlock label="对象前缀">
          <Input
            className={CONFIG_INPUT_CLASS}
            value={objectPrefix}
            onChange={(event) => setObjectPrefix(event.target.value)}
            placeholder="manuals/2026/"
          />
        </FieldBlock>
        <FieldBlock label="扩展名">
          <Input
            className={CONFIG_INPUT_CLASS}
            value={objectExtensions}
            onChange={(event) => setObjectExtensions(event.target.value)}
            placeholder=".pdf, .md, .txt"
          />
          <p>导入格式：{parsedObjectExtensions.join(', ')}</p>
        </FieldBlock>
        <FieldBlock label="最大对象数">
          <Input
            className={CONFIG_INPUT_CLASS}
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
    <div className={styles.sourceForm}>
      <FieldBlock label="生成文件名">
        <Input
          className={CONFIG_INPUT_CLASS}
          value={apiFilename}
          onChange={(event) => setApiFilename(event.target.value)}
          placeholder="api-payload.json"
        />
      </FieldBlock>
      <FieldBlock label="API Payload">
        <Textarea
          className={cn('min-h-52 font-mono', CONFIG_INPUT_CLASS)}
          value={apiContent}
          onChange={(event) => setApiContent(event.target.value)}
          placeholder='{"title":"产品说明","content":"这里粘贴接口推送内容"}'
        />
        <p>内容将作为一个文档导入当前数据集。</p>
      </FieldBlock>
    </div>
  )
}

type SelectedFilesTableProps = {
  rows: Array<{ file: File; key: string }>
  onClear: () => void
  onRemove: (key: string) => void
  disabled: boolean
  receipt: UploadReceipt | null
}

const FILE_SUBMISSION_LABELS = {
  pending: '待提交',
  uploading: '提交中',
  submitted: '已提交',
  failed: '提交失败',
  unconfirmed: '结果未确认',
}

function SelectedFilesTable({ rows, onClear, onRemove, disabled, receipt }: Readonly<SelectedFilesTableProps>) {
  const statesByFile = useMemo(() => {
    const states = new Map<File, keyof typeof FILE_SUBMISSION_LABELS>()
    if (receipt === null) return states
    const { files, response } = receipt
    const matches = matchUploadReceipts(files, [...response.successful, ...response.failed])
    for (const file of files) states.set(file, 'unconfirmed')
    for (const uploaded of response.successful) {
      const file = matches.get(uploaded)
      if (file !== undefined) states.set(file, 'submitted')
    }
    for (const failure of response.failed) {
      const file = matches.get(failure)
      if (file !== undefined) states.set(file, 'failed')
    }
    return states
  }, [receipt])

  return (
    <div data-ingestion-file-staging-workspace="true" className={styles.fileStaging}>
      <div className={styles.queueHeading}>
        <h2>已添加的文件 ({rows.length})</h2>
        <Button variant="ghost" className={styles.quietButton} onClick={onClear} disabled={disabled}>
          <Trash2 className="size-3.5" />
          清空
        </Button>
      </div>
      <div className={styles.stagedFilesScroll}>
        <table className={styles.fileTable} aria-label="本次待入库文件">
          <colgroup>
            <col />
            <col className={styles.stagedSizeCol} />
            <col className={styles.stagedStateCol} />
            <col className={styles.actionCol} />
          </colgroup>
          <thead className="sr-only">
            <tr>
              <th scope="col">文件名称</th>
              <th scope="col">大小</th>
              <th scope="col">状态</th>
              <th scope="col">移除</th>
            </tr>
          </thead>
          <tbody>
            {rows.map(({ file, key }) => {
              const state = statesByFile.get(file) ?? (disabled ? 'uploading' : 'pending')
              return (
                <tr key={key}>
                  <td>
                    <div className={styles.fileName}>
                      <FormatPill filename={file.name} />
                      <strong title={getUploadFilename(file)}>{file.name}</strong>
                    </div>
                  </td>
                  <td className={styles.numeric}>{formatFileSize(file.size)}</td>
                  <td>
                    <span className={styles.fileState} data-state={state}>
                      {FILE_SUBMISSION_LABELS[state]}
                    </span>
                  </td>
                  <td>
                    <Button
                      variant="ghost"
                      className={styles.removeFile}
                      aria-label={'移除文件 ' + file.name}
                      disabled={disabled}
                      onClick={() => onRemove(key)}
                    >
                      <X aria-hidden="true" />
                    </Button>
                  </td>
                </tr>
              )
            })}
          </tbody>
        </table>
      </div>
      {receipt !== null && receipt.response.failed.length > 0 ? (
        <details className={styles.failedFiles}>
          <summary>查看失败文件</summary>
          <ol>
            {receipt.response.failed.map((failure, index) => (
              <li key={index}>
                {getUploadReceiptKey(failure)} · {failure.error}
              </li>
            ))}
          </ol>
        </details>
      ) : null}
    </div>
  )
}

type IngestionConfigurationProps = Readonly<{
  draft: DraftState
  updateDraft: <K extends keyof DraftState>(key: K, value: DraftState[K]) => void
  datasets: Dataset[]
  selectedDataset: Dataset | null
  documentCount?: number
  loading: boolean
  loadError: boolean
  locked: boolean
  onRetry: () => void
  onCreate: () => void
  tagOptions: string[]
  collectionOptions: string[]
  idPrefix?: string
}>

const INGESTION_PARSERS = PARSER_BACKEND_REGISTRY_OPTIONS.filter((option) =>
  ['auto', 'docling', 'markitdown', 'deepdoc', 'csv', 'json', 'markdown'].includes(option.value),
)

function IngestionConfiguration({
  draft,
  updateDraft,
  datasets,
  selectedDataset,
  documentCount,
  loading,
  loadError,
  locked,
  onRetry,
  onCreate,
  tagOptions,
  collectionOptions,
  idPrefix = 'ingestion',
}: IngestionConfigurationProps) {
  const instanceId = useId()
  const datasetId = instanceId + '-dataset'
  const parserId = instanceId + '-parser'
  const dedupId = instanceId + '-dedup'
  const parsing = draft.executionMode !== 'upload_only'
  const activeModeOption =
    EXECUTION_MODE_OPTIONS.find((option) => option.value === draft.executionMode) ?? EXECUTION_MODE_OPTIONS[0]

  return (
    <div className={styles.configuration}>
      <h2 className={styles.configurationTitle}>入库配置</h2>
      <fieldset disabled={locked}>
        <legend className="sr-only">本次导入设置</legend>
        <div className={styles.destination}>
          <div className={styles.fieldHeading}>
            <label htmlFor={datasetId}>目标数据集</label>
            <Button variant="ghost" className={styles.quietButton} onClick={onCreate}>
              新建
            </Button>
          </div>
          <DatasetSelector
            id={datasetId}
            datasetId={draft.datasetId}
            datasets={datasets}
            selectedDataset={selectedDataset}
            loading={loading}
            locked={locked}
            onChange={(value) => updateDraft('datasetId', value)}
          />
          {loadError ? (
            <p role="alert" className={styles.datasetError}>
              数据集加载失败。
              <button type="button" onClick={onRetry}>
                重试
              </button>
            </p>
          ) : !loading && datasets.length === 0 ? (
            <p className={styles.destinationMeta}>先新建一个数据集，再添加文件。</p>
          ) : selectedDataset && documentCount !== undefined ? (
            <p className={styles.destinationMeta}>已有 {documentCount.toLocaleString()} 个文档</p>
          ) : null}
        </div>

        <fieldset className={styles.modeGroup} disabled={locked}>
          <legend>处理方式</legend>
          <TooltipProvider delayDuration={150}>
            <div className={styles.modeList}>
              {EXECUTION_MODE_OPTIONS.map((option) => {
                const selected = draft.executionMode === option.value
                return (
                  <Tooltip key={option.value}>
                    <TooltipTrigger asChild>
                      <label className={styles.modeOption} data-selected={selected} title={option.description}>
                        <input
                          type="radio"
                          name={idPrefix + '-execution-mode'}
                          value={option.value}
                          checked={selected}
                          onChange={() => updateDraft('executionMode', option.value)}
                        />
                        <strong>{option.title}</strong>
                      </label>
                    </TooltipTrigger>
                    <TooltipContent side="top">{option.description}</TooltipContent>
                  </Tooltip>
                )
              })}
            </div>
          </TooltipProvider>
          <p className={styles.modeHint}>{activeModeOption.description}</p>
        </fieldset>

        <div className={styles.processFields}>
          <div className={styles.inlineField}>
            <label htmlFor={parserId}>解析器</label>
            <Select
              value={draft.parserBackend}
              onValueChange={(value) => updateDraft('parserBackend', value as ParserBackend)}
              disabled={locked || !parsing}
            >
              <SelectTrigger
                id={parserId}
                className={SOFT_CONTROL_CLASS}
                title={!parsing ? '仅传原件时不使用解析器' : getParserOption(draft.parserBackend).label}
              >
                <span className="truncate">{getParserOption(draft.parserBackend).label}</span>
              </SelectTrigger>
              <SelectContent className={SELECT_MENU_CLASS}>
                {INGESTION_PARSERS.map((option) => (
                  <SelectItem
                    key={option.value}
                    value={option.value}
                    textValue={option.label}
                    className={SELECT_OPTION_CLASS}
                  >
                    <SelectOptionBody title={option.label} description={option.description} />
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className={styles.inlineField}>
            <label htmlFor={dedupId}>近重复检测</label>
            <Select
              value={draft.dedupStrategy}
              onValueChange={(value) => updateDraft('dedupStrategy', value)}
              disabled={locked || !parsing}
            >
              <SelectTrigger id={dedupId} className={SOFT_CONTROL_CLASS}>
                <span className="truncate">{getSelectOptionTitle(DEDUP_OPTIONS, draft.dedupStrategy)}</span>
              </SelectTrigger>
              <SelectContent className={SELECT_MENU_CLASS}>
                {DEDUP_OPTIONS.map((option) => (
                  <SelectItem
                    key={option.value}
                    value={option.value}
                    textValue={option.title}
                    className={SELECT_OPTION_CLASS}
                  >
                    <SelectOptionBody {...option} />
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <AdvancedIngestSettings
          draft={draft}
          updateDraft={updateDraft}
          tagOptions={tagOptions}
          collectionOptions={collectionOptions}
        />
      </fieldset>
    </div>
  )
}

function AdvancedIngestSettings({
  draft,
  updateDraft,
  tagOptions,
  collectionOptions,
}: Readonly<{
  draft: DraftState
  updateDraft: <K extends keyof DraftState>(key: K, value: DraftState[K]) => void
  tagOptions: string[]
  collectionOptions: string[]
}>) {
  const instanceId = useId()
  const tagListId = instanceId + '-tags'
  const collectionListId = instanceId + '-collections'

  return (
    <details data-ingestion-advanced-settings="true" className={styles.advanced}>
      <summary>
        <span>
          <strong>高级设置</strong>
          <small>标签与目录</small>
        </span>
        <ChevronDown aria-hidden="true" />
      </summary>
      <div className={styles.advancedFields}>
        <FieldBlock label="标签">
          <Input
            list={tagListId}
            className={CONFIG_INPUT_CLASS}
            value={draft.tags}
            onChange={(event) => updateDraft('tags', event.target.value)}
            placeholder="选择或输入标签"
          />
          <datalist id={tagListId}>
            {tagOptions.map((tag) => (
              <option key={tag} value={tag} />
            ))}
          </datalist>
        </FieldBlock>
        <FieldBlock label="目标目录">
          <Input
            list={collectionListId}
            className={CONFIG_INPUT_CLASS}
            value={draft.collection}
            onChange={(event) => updateDraft('collection', event.target.value)}
            placeholder="default"
          />
          <datalist id={collectionListId}>
            {collectionOptions.map((collection) => (
              <option key={collection} value={collection} />
            ))}
          </datalist>
        </FieldBlock>
      </div>
    </details>
  )
}
