'use client'
import { FeedbackToast } from '@/components/feedback-toast'

import { type ReactNode, type RefObject, useCallback, useEffect, useId, useMemo, useRef, useState } from 'react'
import {
  Archive,
  ArrowRight,
  ChevronDown,
  CircleAlert,
  Cloud,
  Database,
  Dataset as DatasetIcon,
  Parsing,
  FileUp,
  Folder,
  Link as LinkIcon,
  Loader2,
  Plus,
  ShieldCheck,
  Settings2,
  Trash2,
  UploadCloud,
  X,
  type PlatformIcon,
} from '@/components/icons'
import { useQuery } from '@tanstack/react-query'
import { useRouter, useSearchParams } from 'next/navigation'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { getFileTypeMeta } from '@/components/knowledge/file-type'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from '@/components/ui/select'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle, SheetTrigger } from '@/components/ui/sheet'
import { Textarea } from '@/components/ui/textarea'
import { connectorApi, datasetApi, documentApi, settingsApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { readClientStorage } from '@/lib/client-storage'
import { getParserOption, PARSER_BACKEND_REGISTRY_OPTIONS } from '@/lib/parser-options'
import { cn, detachPromise, formatFileSize } from '@/lib/utils'
import type {
  Dataset,
  Document,
  DocumentBatchUploadResponse,
  DocumentFolderNode,
  DocumentPipelineOptions,
} from '@/types'

import { IngestionViewSwitch } from './view-switch'
import styles from './operation.module.css'

const DRAFT_KEY = 'mimirq.knowledge.ingestion.operation.draft'
const DEFAULT_COLLECTION = 'default'
const NO_DATASET_FILE_BUCKET = '__mimirq_no_dataset__'
const EMPTY_FILES: File[] = []

type UploadSource = 'local' | 'folder' | 'url' | 'object' | 'api'
type ParserBackend = 'auto' | 'docling' | 'markitdown' | 'deepdoc' | 'csv' | 'json' | 'markdown'
type ChunkStrategy = 'semantic' | 'langchain_recursive' | 'markdown' | 'by_title'
type IngestMode = 'append' | 'replace' | 'skip_duplicates'
type IngestExecutionMode = 'upload_only' | 'parse_only' | 'full_index'
type TaskStatus = 'idle' | 'prechecking' | 'uploading' | 'completed' | 'failed'
type SelectOption<T extends string> = {
  value: T
  title: string
  description: string
  badge?: string
}

type DraftState = {
  datasetId: string
  syncDataset: boolean
  ingestMode: IngestMode
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
  ingestMode: 'append',
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

const OPERATION_STAGES: Array<{
  label: string
  description: string
  icon: PlatformIcon
}> = [
  { label: '登记', description: '校验来源与文件', icon: FileUp },
  { label: '解析', description: '提取正文与结构', icon: Parsing },
  { label: '治理', description: '清洗、去重、切块', icon: ShieldCheck },
  { label: '建索引', description: '向量与关键词索引', icon: Database },
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
const INGEST_MODE_OPTIONS: Array<SelectOption<IngestMode>> = [
  {
    value: 'append',
    title: '追加导入',
    description: '保留现有数据，只写入本次文件。',
    badge: '默认',
  },
  {
    value: 'skip_duplicates',
    title: '跳过重复',
    description: '发现重复文件时跳过，适合批量补充。',
    badge: '稳妥',
  },
  {
    value: 'replace',
    title: '替换同名',
    description: '同名文件用新版本覆盖，适合重传修订。',
    badge: '谨慎',
  },
]
const EXECUTION_MODE_OPTIONS: Array<SelectOption<IngestExecutionMode>> = [
  {
    value: 'upload_only',
    title: '仅登记',
    description: '保存源文件，暂不解析',
    badge: '默认',
  },
  {
    value: 'parse_only',
    title: '入库并解析',
    description: '提取正文，暂不建立索引',
    badge: '监控',
  },
  {
    value: 'full_index',
    title: '解析 + 索引',
    description: '解析内容并加入知识库检索',
    badge: '完整',
  },
]
const DEDUP_OPTIONS: Array<SelectOption<string>> = [
  {
    value: 'content_hash',
    title: '内容哈希',
    description: '相同内容自动跳过，推荐默认使用。',
    badge: '推荐',
  },
  {
    value: 'filename',
    title: '文件名',
    description: '按同名文件判断重复。',
  },
  {
    value: 'none',
    title: '不检查',
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
  const path = (file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name
  return `${path}:${file.size}:${file.lastModified}`
}

function fileUploadName(file: File) {
  return String((file as File & { webkitRelativePath?: string }).webkitRelativePath || file.name)
}

function fileRelativeFolder(file: File) {
  const path = fileUploadName(file)
  if (!path.includes('/')) return ''
  return path.split('/').slice(0, -1).join('/').trim()
}

function formatFileType(file: File) {
  const ext = file.name.split('.').pop()
  return ext ? ext.toUpperCase() : 'FILE'
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === 'object' && value !== null && !Array.isArray(value)
}

function normalizeOption(value: unknown) {
  return String(value || '').trim()
}

function normalizeListText(value: string) {
  return value
    .split(/[,\n，、]/g)
    .map((item) => item.trim())
    .filter(Boolean)
}

function getSelectOptionTitle<T extends string>(
  options: Array<SelectOption<T>>,
  value: T
) {
  return options.find((option) => option.value === value)?.title ?? value
}

function SelectOptionBody({
  description,
  title,
}: Readonly<{
  badge?: string
  description: string
  title: string
}>) {
  return (
    <span className={styles.optionBody}>
      <strong>{title}</strong>
      <small>{description}</small>
    </span>
  )
}

function DatasetOptionBody({ dataset }: Readonly<{ dataset: Dataset }>) {
  return (
    <span className={styles.optionBody}>
      <strong>{dataset.name}</strong>
      <small>{datasetShortId(dataset)}</small>
    </span>
  )
}

function getDocumentUserTags(document: Document): string[] {
  const metadata = document.metadata
  if (!isRecord(metadata)) return []
  const user = metadata.user
  const rawTags = isRecord(user) ? user.tags : metadata.tags
  if (Array.isArray(rawTags)) {
    return rawTags.map(normalizeOption).filter(Boolean)
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
  const stack = [...(root.children || [])].reverse()
  while (stack.length) {
    const node = stack.pop()
    if (!node) continue
    const path = normalizeOption(node.path)
    if (path) out.push(path)
    for (const child of [...(node.children || [])].reverse()) stack.push(child)
  }
  return out
}

function collectCollectionOptions(
  root: DocumentFolderNode | null | undefined,
  files: File[],
  currentCollection: string
): string[] {
  const options = new Set<string>([DEFAULT_COLLECTION])
  for (const path of collectFolderPaths(root)) options.add(path)
  for (const file of files) {
    const folder = fileRelativeFolder(file)
    if (folder) options.add(folder)
  }
  const normalizedCurrent = normalizeOption(currentCollection)
  if (normalizedCurrent) options.add(normalizedCurrent)
  return Array.from(options).sort((a, b) => {
    if (a === DEFAULT_COLLECTION) return -1
    if (b === DEFAULT_COLLECTION) return 1
    return a.localeCompare(b, 'zh-CN')
  })
}

function getFileIcon(file: File) {
  return getFileTypeMeta({ filename: file.name, file_type: '' }).icon
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

function datasetShortId(dataset?: Dataset | null) {
  return dataset?.id ? String(dataset.id).slice(0, 18).toUpperCase() : '--'
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

export default function KnowledgeIngestionOperationPage() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const routeDatasetId = searchParams.get('datasetId') || ''
  const inputRef = useRef<HTMLInputElement | null>(null)
  const folderInputRef = useRef<HTMLInputElement | null>(null)
  const previousDatasetIdRef = useRef<string | null>(null)
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
  const [uploadResponse, setUploadResponse] = useState<DocumentBatchUploadResponse | null>(null)
  const [submissionError, setSubmissionError] = useState<string | null>(null)
  const [configurationOpen, setConfigurationOpen] = useState(false)

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
    queryKey: ['knowledge-ingestion-operation-datasets'],
    queryFn: () => datasetApi.listAll(),
    staleTime: 30_000,
  })

  const datasets = useMemo(() => datasetsQuery.data ?? [], [datasetsQuery.data])

  useEffect(() => {
    const routeDatasetExists = routeDatasetId && datasets.some((dataset) => dataset.id === routeDatasetId)
    const fallbackDatasetId = datasets[0]?.id
    setDraft((current) => {
      if (routeDatasetExists && current.datasetId !== routeDatasetId) return { ...current, datasetId: routeDatasetId }
      if (current.datasetId || !fallbackDatasetId) return current
      return { ...current, datasetId: fallbackDatasetId }
    })
  }, [datasets, routeDatasetId])

  const selectedDataset = useMemo(
    () => datasets.find((dataset) => dataset.id === draft.datasetId) ?? null,
    [datasets, draft.datasetId]
  )
  const activeFileBucketKey = draft.datasetId || NO_DATASET_FILE_BUCKET
  const files = filesByDatasetId[activeFileBucketKey] ?? EMPTY_FILES

  useEffect(() => {
    if (previousDatasetIdRef.current === null) {
      previousDatasetIdRef.current = draft.datasetId
      return
    }
    if (previousDatasetIdRef.current === draft.datasetId) return
    previousDatasetIdRef.current = draft.datasetId
    setUploadResponse(null)
    setSubmissionError(null)
    setStatus('idle')
  }, [draft.datasetId])

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
    queryFn: () => documentApi.folders({ dataset_id: draft.datasetId, max_depth: 20 }),
    enabled: Boolean(draft.datasetId),
    staleTime: 10_000,
  })

  const tagOptions = useMemo(
    () => collectTagOptions(documents, draft.tags),
    [documents, draft.tags]
  )
  const collectionOptions = useMemo(
    () => collectCollectionOptions(foldersQuery.data?.root, files, draft.collection),
    [draft.collection, files, foldersQuery.data?.root]
  )

  const settingsQuery = useQuery({
    queryKey: ['knowledge-ingestion-operation-settings'],
    queryFn: () => settingsApi.get(),
    staleTime: 30_000,
  })

  const urlIngestEnabled = Boolean(settingsQuery.data?.url_ingest?.enabled)

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
    Boolean(selectedDataset) &&
    status !== 'uploading' &&
    pendingSourceCount > 0 &&
    !connectorSourceBlocked

  const totalDocuments = ingestionStats?.total_documents ?? documents.length

  const fileRows = useMemo(
    () =>
      files.map((file) => {
        const Icon = getFileIcon(file)
        return { file, Icon, key: fileKey(file) }
      }),
    [files]
  )
  const activeSource = SOURCE_OPTIONS.find((item) => item.value === source) ?? SOURCE_OPTIONS[0]

  const updateDraft = useCallback(<K extends keyof DraftState>(key: K, value: DraftState[K]) => {
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
            [key]: String(value || ''),
          },
        }
      })
    }
    setDraft((current) => ({ ...current, [key]: value }))
  }, [draft.datasetId])

  const addFiles = useCallback((incoming: File[]) => {
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
  }, [activeFileBucketKey])

  const clearFiles = useCallback(() => {
    setFilesByDatasetId((current) => ({
      ...current,
      [activeFileBucketKey]: [],
    }))
    setUploadResponse(null)
    setSubmissionError(null)
    setStatus('idle')
  }, [activeFileBucketKey])

  const removeFile = useCallback((key: string) => {
    setFilesByDatasetId((current) => ({
      ...current,
      [activeFileBucketKey]: (current[activeFileBucketKey] ?? []).filter((file) => fileKey(file) !== key),
    }))
  }, [activeFileBucketKey])

  const submitConnectorRun = useCallback(async () => {
    if (!draft.datasetId) {
      toast.error('请先选择目标数据集')
      return
    }
    if (!urlIngestEnabled) {
      toast.error('URL 导入未启用，请联系管理员启用后重试。')
      return
    }
    setStatus('uploading')
    setUploadResponse(null)
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
      await Promise.all([foldersQuery.refetch(), ingestionStatsQuery.refetch()])
      toast.success(`连接器任务已创建：${String(run.id).slice(0, 8)}`)
      if (run.status !== 'failed' && shouldOpenExecutionMonitor(draft, 'ingest')) {
        router.push('/knowledge/ingestion?mode=execution-monitor')
      }
    } catch (error) {
      setStatus('failed')
      const message = formatApiError(error, '连接器任务创建失败')
      setSubmissionError(message)
    }
  }, [
    draft,
    foldersQuery,
    ingestionStatsQuery,
    objectBucket,
    objectMaxObjects,
    objectPrefix,
    parsedObjectExtensions,
    parsedUrls,
    router,
    source,
    urlIngestEnabled,
    urlFilename,
  ])

  const handleSyncDatasets = useCallback(async () => {
    await datasetsQuery.refetch()
    if (draft.datasetId) {
      await Promise.all([documentsQuery.refetch(), foldersQuery.refetch(), ingestionStatsQuery.refetch()])
    }
    toast.success('数据集状态已同步')
  }, [datasetsQuery, documentsQuery, draft.datasetId, foldersQuery, ingestionStatsQuery])

  const uploadFiles = useCallback(
    async (mode: 'upload_only' | 'ingest') => {
      if (!draft.datasetId) {
        toast.error('请先选择目标数据集')
        return
      }
      if (mode === 'upload_only' && (source === 'url' || source === 'object')) {
        toast.error('URL/对象存储不能使用仅登记模式，请先下载为本地文件或选择解析入库')
        return
      }
      if (mode === 'upload_only' && source === 'api') {
        toast.error('API 导入没有原始文件可登记，请选择“解析入库”')
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
      setStatus('uploading')
      setUploadResponse(null)
      setSubmissionError(null)
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
          await Promise.all([documentsQuery.refetch(), foldersQuery.refetch(), ingestionStatsQuery.refetch()])
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
              fileUploadName(file),
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
        await Promise.all([documentsQuery.refetch(), foldersQuery.refetch(), ingestionStatsQuery.refetch()])
        toast.success(
          mode === 'upload_only'
            ? `已登记到知识库：成功 ${response.successful_count} / 失败 ${response.failed_count}`
            : `入库任务已提交：成功 ${response.successful_count} / 失败 ${response.failed_count}`
        )
        if (response.successful_count > 0 && shouldOpenExecutionMonitor(draft, mode)) {
          router.push('/knowledge/ingestion?mode=execution-monitor')
        }
      } catch (error) {
        setStatus('failed')
        const message = formatApiError(error, '入库任务提交失败')
        setSubmissionError(message)
      }
    },
    [apiContent, apiFilename, documentsQuery, draft, files, foldersQuery, ingestionStatsQuery, parsedUrls.length, router, source, submitConnectorRun]
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

  const activeStageCount =
    draft.executionMode === 'upload_only'
      ? 1
      : draft.executionMode === 'parse_only'
        ? 2
        : OPERATION_STAGES.length
  const sourceExecutionBlocked =
    draft.executionMode === 'upload_only' &&
    (source === 'url' || source === 'object' || source === 'api')
  const operationReady = canStartIngest && !sourceExecutionBlocked
  const actionLabel =
    draft.executionMode === 'upload_only'
      ? '登记文件'
      : draft.executionMode === 'full_index'
        ? '解析并建索引'
        : '登记并解析'
  const emptySourceMessage =
    source === 'local' || source === 'folder'
      ? '请添加待入库文件'
      : source === 'url'
        ? '请填写至少一个有效 URL'
        : source === 'object'
          ? '请配置对象存储范围'
          : '请填写 API 导入内容'
  const preflightMessage = !draft.datasetId
    ? '请选择目标数据集'
    : connectorSourceBlocked
      ? '当前环境未启用 URL/对象存储导入'
      : sourceExecutionBlocked
        ? '当前来源不支持“仅登记”'
        : pendingSourceCount === 0
          ? emptySourceMessage
          : '0 阻断 · 可以提交'
  const submissionSummary = uploadResponse
    ? `上次提交：成功 ${uploadResponse.successful_count} · 失败 ${uploadResponse.failed_count}`
    : pendingSourceCount === 0
      ? `${emptySourceMessage}，完成后即可提交`
      : `将 ${pendingSourceCount} 项内容写入 ${selectedDataset?.name ?? '目标数据集'}，按“${getSelectOptionTitle(EXECUTION_MODE_OPTIONS, draft.executionMode)}”处理`

  const isSubmitting = status === 'uploading'
  const isFileSource = source === 'local' || source === 'folder'
  const executionPath = OPERATION_STAGES.slice(0, activeStageCount).map((stage) => stage.label).join(' → ')
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

  return (
    <div data-ingestion-operation-root="true" className={styles.page} aria-busy={isSubmitting}>
      <header className={styles.header}>
        <div className={styles.title}>
          <PageTitleIcon name="ingestion-operation" className={styles.titleIcon} />
          <h1>入库管理</h1>
        </div>
        <IngestionViewSwitch variant="tabs" className={styles.viewSwitch} />
        <div className={styles.headerActions}>
          <Button variant="ghost" className={styles.quietButton} onClick={() => router.push('/knowledge')}>
            查看文档
          </Button>
          <Sheet open={configurationOpen} onOpenChange={setConfigurationOpen}>
            <SheetTrigger asChild>
              <Button variant="ghost" className={cn(styles.quietButton, styles.configTrigger)}>
                <Settings2 className="size-4" />
                入库配置
              </Button>
            </SheetTrigger>
            <SheetContent className={styles.configSheet}>
              <SheetHeader className={styles.sheetHeader}>
                <SheetTitle>入库配置</SheetTitle>
                <SheetDescription className="sr-only">选择目标数据集与本次导入的处理方式。</SheetDescription>
              </SheetHeader>
              <div className={styles.sheetBody}>
                <IngestionConfiguration {...configurationProps} idPrefix="mobile-ingestion" />
              </div>
            </SheetContent>
          </Sheet>
        </div>
      </header>

      <div data-ingestion-operation-workspace="true" className={styles.workspace}>
        <section className={styles.filesPane} aria-label="导入内容">
          <nav className={styles.sourceNav} aria-label="文件来源">
            {SOURCE_OPTIONS.map((option) => {
              const Icon = option.icon
              return (
                <button
                  key={option.value}
                  type="button"
                  className={styles.sourceTab}
                  aria-pressed={source === option.value}
                  onClick={() => setSource(option.value)}
                  disabled={isSubmitting}
                >
                  <Icon aria-hidden="true" />
                  {option.label}
                </button>
              )
            })}
          </nav>

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
              accept={ACCEPTED_EXTENSIONS.join(',')}
              disabled={isSubmitting}
              onChange={(event) => {
                addFiles(Array.from(event.target.files ?? []))
                event.target.value = ''
              }}
            />
          </fieldset>

          {isFileSource ? (
            <SelectedFilesTable
              rows={fileRows}
              totalBytes={selectedTotalBytes}
              sourceName={activeSource.label}
              dragging={dragging}
              onDragState={setDragging}
              onFiles={addFiles}
              onClear={clearFiles}
              onRemove={removeFile}
              disabled={isSubmitting}
              response={uploadResponse}
            />
          ) : (
            <div className={styles.emptyQueue}>
              <activeSource.icon aria-hidden="true" />
              <strong>{source === 'url' ? '从文件地址导入' : source === 'object' ? '从对象存储导入' : '将内容导入知识库'}</strong>
              <p>{source === 'url' ? '填写文件链接后，确认右侧处理方式并提交。' : source === 'object' ? '按上方的前缀和扩展名选择待导入对象。' : '提交上方内容，在目标数据集中创建文档。'}</p>
            </div>
          )}
        </section>

        <aside data-ingestion-context-panel="true" className={styles.settingsPane} aria-label="入库配置">
          <IngestionConfiguration {...configurationProps} />
        </aside>
      </div>

      <FeedbackToast type="error" message={submissionError ? `${submissionError}。文件和配置已保留，可再次提交。` : null} id="ingestion-submit-feedback" />

      <footer data-ingestion-action-bar="true" data-task-center-dock="true" className={styles.submitBar}>
        <div className={styles.submitSummary} aria-live="polite">
          <strong>{uploadResponse ? submissionSummary : pendingSourceCount > 0 ? (
            isFileSource ? pendingSourceCount + ' 个文件 · ' + formatFileSize(selectedTotalBytes) : pendingSourceCount + ' 项内容'
          ) : '尚未添加内容'}</strong>
          <span>{!operationReady && !isSubmitting ? preflightMessage : (
            '目标：' + (selectedDataset?.name ?? '未选择') + ' · ' + executionPath
          )}</span>
        </div>
        <Button
          data-ingestion-submit="true"
          className={styles.submitButton}
          onClick={() => detachPromise(uploadFiles(draft.executionMode === 'upload_only' ? 'upload_only' : 'ingest'))}
          disabled={!operationReady}
        >
          {isSubmitting ? <Loader2 className="size-4 animate-spin" /> : <ArrowRight className="size-4" />}
          {isSubmitting ? '正在提交' : status === 'completed' ? '再次提交' : actionLabel}
        </Button>
      </footer>
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
      disabled={disabled}
      onClick={onClick}
      onDragEnter={(event) => {
        event.preventDefault()
        if (!disabled) onDragState(true)
      }}
      onDragOver={(event) => {
        event.preventDefault()
        if (!disabled) onDragState(true)
      }}
      onDragLeave={() => onDragState(false)}
      onDrop={(event) => {
        event.preventDefault()
        onDragState(false)
        if (!disabled) onFiles(Array.from(event.dataTransfer.files ?? []))
      }}
    >
      <UploadCloud aria-hidden="true" />
      <span className={styles.dropCopy}>
        <strong>添加文件到本次任务</strong>
        <span>拖入或选择 PDF、Word、表格等文件，单文件 ≤ 2 GB</span>
      </span>
      <span className={styles.addFiles}><Plus aria-hidden="true" />添加文件</span>
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
      <div className={styles.folderSource}>
        <div>
          <strong>选择本地文件夹</strong>
          <p>批量添加文件，保留文件夹中的相对路径。</p>
        </div>
        <Button variant="outline" className={styles.addFiles} onClick={() => folderInputRef.current?.click()}>
          <Folder className="size-4" />选择文件夹
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
            placeholder="https://example.com/manual.pdf&#10;https://example.com/guide.md"
          />
          <p>{urlIngestEnabled ? '每行一个文件地址，已识别 ' + parsedUrls.length + ' 个有效链接。' : 'URL 导入未启用，请联系管理员启用后重试。'}</p>
        </FieldBlock>
        <FieldBlock label="统一文件名（可选）">
          <Input className={CONFIG_INPUT_CLASS} value={urlFilename} onChange={(event) => setUrlFilename(event.target.value)} placeholder="remote-documents.md" />
        </FieldBlock>
      </div>
    )
  }

  if (source === 'object') {
    return (
      <div className={cn(styles.sourceForm, styles.sourceFormColumns)}>
        {!urlIngestEnabled ? <p className={styles.sourceNotice}>对象存储导入需要通过文件地址拉取内容，请联系管理员启用 URL 导入。</p> : null}
        <FieldBlock label="Bucket（可选）">
          <Input className={CONFIG_INPUT_CLASS} value={objectBucket} onChange={(event) => setObjectBucket(event.target.value)} placeholder="使用已配置的存储桶" />
        </FieldBlock>
        <FieldBlock label="对象前缀">
          <Input className={CONFIG_INPUT_CLASS} value={objectPrefix} onChange={(event) => setObjectPrefix(event.target.value)} placeholder="manuals/2026/" />
        </FieldBlock>
        <FieldBlock label="扩展名">
          <Input className={CONFIG_INPUT_CLASS} value={objectExtensions} onChange={(event) => setObjectExtensions(event.target.value)} placeholder=".pdf, .md, .txt" />
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
        <Input className={CONFIG_INPUT_CLASS} value={apiFilename} onChange={(event) => setApiFilename(event.target.value)} placeholder="api-payload.json" />
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

function SelectedFilesTable({
  rows,
  totalBytes,
  sourceName,
  dragging,
  onDragState,
  onFiles,
  onClear,
  onRemove,
  disabled,
  response,
}: Readonly<{
  rows: Array<{ file: File; Icon: PlatformIcon; key: string }>
  totalBytes: number
  sourceName: string
  dragging: boolean
  onDragState: (dragging: boolean) => void
  onFiles: (files: File[]) => void
  onClear: () => void
  onRemove: (key: string) => void
  disabled: boolean
  response: DocumentBatchUploadResponse | null
}>) {
  const submittedNames = useMemo(() => new Set(response?.successful?.map((item) => item.filename)), [response])
  const failedNames = useMemo(() => new Set(response?.failed?.map((item) => item.filename)), [response])

  return (
    <div data-ingestion-file-staging-workspace="true" data-selected-files-table="stable" className={styles.fileStaging}>
      <div className={styles.queueHeading}>
        <h2>本次任务文件</h2>
        <span className={styles.queueCount}>{rows.length}</span>
        {rows.length > 0 ? <span className={styles.queueSize}>共 {formatFileSize(totalBytes)}</span> : null}
        {rows.length > 0 ? (
          <Button variant="ghost" className={styles.quietButton} onClick={onClear} disabled={disabled}>
            <Trash2 className="size-3.5" />清空
          </Button>
        ) : null}
      </div>
      {rows.length > 0 ? (
        <div className={styles.tableWrap}>
          <table className={styles.fileTable} aria-label="本次待入库文件">
            <colgroup>
              <col className={styles.indexCol} /><col /><col className={styles.typeCol} />
              <col className={styles.sizeCol} /><col className={styles.statusCol} /><col className={styles.actionCol} />
            </colgroup>
            <thead>
              <tr>
                <th className={styles.rowIndex} scope="col">#</th>
                <th scope="col">文件名称</th>
                <th className={styles.fileFormat} scope="col">格式</th>
                <th className={styles.numeric} scope="col">大小</th>
                <th scope="col">状态</th>
                <th scope="col"><span className="sr-only">移除</span></th>
              </tr>
            </thead>
            <tbody>
              {rows.map(({ file, Icon, key }, index) => {
                const uploadName = fileUploadName(file)
                const submitted = submittedNames.has(uploadName)
                const failed = failedNames.has(uploadName)
                const label = failed ? '提交失败' : submitted ? '已提交' : disabled ? '提交中' : '待提交'
                return (
                  <tr key={key}>
                    <td className={styles.rowIndex}>{String(index + 1).padStart(2, '0')}</td>
                    <td>
                      <div className={styles.fileName}>
                        <Icon appearance="color" aria-hidden="true" />
                        <div>
                          <strong title={sourceName + ' · ' + uploadName}>{file.name}</strong>
                          <span className={styles.fileMobileMeta}>{formatFileSize(file.size)} · {formatFileType(file)}</span>
                        </div>
                      </div>
                    </td>
                    <td className={styles.fileFormat}>{formatFileType(file)}</td>
                    <td className={styles.numeric}>{formatFileSize(file.size)}</td>
                    <td><span className={styles.fileState} data-state={failed ? 'failed' : submitted ? 'submitted' : 'pending'}>{label}</span></td>
                    <td>
                      <Button
                        variant="ghost"
                        className={styles.removeFile}
                        aria-label={'移除文件 ' + file.name}
                        title={'移除文件 ' + file.name}
                        disabled={disabled}
                        onClick={() => onRemove(key)}
                      ><X aria-hidden="true" /></Button>
                    </td>
                  </tr>
                )
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div
          data-ingestion-empty-file-drop="true"
          className={styles.emptyQueue}
          data-dragging={dragging}
          onDragOver={(event) => {
            event.preventDefault()
            if (!disabled) onDragState(true)
          }}
          onDragLeave={() => onDragState(false)}
          onDrop={(event) => {
            event.preventDefault()
            onDragState(false)
            if (!disabled) onFiles(Array.from(event.dataTransfer.files ?? []))
          }}
        >
          <UploadCloud aria-hidden="true" />
          <strong>将文件拖到这里</strong>
          <p>支持 PDF、Word、Markdown、表格、文本与压缩包</p>
        </div>
      )}
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
  ['auto', 'docling', 'markitdown', 'deepdoc', 'csv', 'json', 'markdown'].includes(option.value)
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

  return (
    <div className={styles.configuration}>
      <h2 className={styles.configurationTitle}>入库配置</h2>
      <fieldset disabled={locked}>
        <legend className="sr-only">本次导入设置</legend>
        <div className={styles.destination}>
          <div className={styles.fieldHeading}>
            <label htmlFor={datasetId}>目标数据集</label>
            <Button variant="ghost" className={styles.quietButton} onClick={onCreate}>新建</Button>
          </div>
          <Select value={draft.datasetId} onValueChange={(value) => updateDraft('datasetId', value)} disabled={locked || loading || datasets.length === 0}>
            <SelectTrigger id={datasetId} className={SOFT_CONTROL_CLASS}>
              <span className={styles.controlText}><DatasetIcon aria-hidden="true" /><span>{selectedDataset?.name ?? (loading ? '正在加载数据集' : datasets.length ? '选择目标数据集' : '暂无数据集')}</span></span>
            </SelectTrigger>
            <SelectContent className={SELECT_MENU_CLASS}>
              {datasets.map((dataset) => (
                <SelectItem key={dataset.id} value={dataset.id} textValue={dataset.name} className={SELECT_OPTION_CLASS}>
                  <DatasetOptionBody dataset={dataset} />
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
          {loadError ? (
            <p role="alert" className={styles.datasetError}>数据集加载失败。<button type="button" onClick={onRetry}>重试</button></p>
          ) : !loading && datasets.length === 0 ? (
            <p className={styles.destinationMeta}>先新建一个数据集，再添加文件。</p>
          ) : selectedDataset && documentCount !== undefined ? <p className={styles.destinationMeta}>已有 {documentCount.toLocaleString()} 个文档</p> : null}
        </div>

        <fieldset className={styles.modeGroup} disabled={locked}>
          <legend>处理方式</legend>
          <div className={styles.modeList}>
            {EXECUTION_MODE_OPTIONS.map((option) => {
              const selected = draft.executionMode === option.value
              return (
                <label key={option.value} className={styles.modeOption} data-selected={selected}>
                  <input
                    type="radio"
                    name={idPrefix + '-execution-mode'}
                    value={option.value}
                    checked={selected}
                    onChange={() => updateDraft('executionMode', option.value)}
                  />
                  <span><strong>{option.title}</strong><small>{option.description}</small></span>
                </label>
              )
            })}
          </div>
        </fieldset>

        <div className={styles.processFields}>
          <div className={styles.inlineField}>
            <label htmlFor={parserId}>解析器</label>
            <Select value={draft.parserBackend} onValueChange={(value) => updateDraft('parserBackend', value as ParserBackend)} disabled={locked || !parsing}>
              <SelectTrigger id={parserId} className={SOFT_CONTROL_CLASS} title={!parsing ? '仅登记时不使用解析器' : getParserOption(draft.parserBackend).label}>
                <span className="truncate">{getParserOption(draft.parserBackend).label}</span>
              </SelectTrigger>
              <SelectContent className={SELECT_MENU_CLASS}>
                {INGESTION_PARSERS.map((option) => (
                  <SelectItem key={option.value} value={option.value} textValue={option.label} className={SELECT_OPTION_CLASS}>
                    <SelectOptionBody title={option.label} description={option.description} />
                  </SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
          <div className={styles.inlineField}>
            <label htmlFor={dedupId}>重复处理</label>
            <Select value={draft.dedupStrategy} onValueChange={(value) => updateDraft('dedupStrategy', value)} disabled={locked}>
              <SelectTrigger id={dedupId} className={SOFT_CONTROL_CLASS}><span className="truncate">{getSelectOptionTitle(DEDUP_OPTIONS, draft.dedupStrategy)}</span></SelectTrigger>
              <SelectContent className={SELECT_MENU_CLASS}>
                {DEDUP_OPTIONS.map((option) => (
                  <SelectItem key={option.value} value={option.value} textValue={option.title} className={SELECT_OPTION_CLASS}><SelectOptionBody {...option} /></SelectItem>
                ))}
              </SelectContent>
            </Select>
          </div>
        </div>

        <AdvancedIngestSettings draft={draft} updateDraft={updateDraft} tagOptions={tagOptions} collectionOptions={collectionOptions} />
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
        <span><strong>高级设置</strong><small>导入方式、标签与目录</small></span>
        <ChevronDown aria-hidden="true" />
      </summary>
      <div className={styles.advancedFields}>
        <FieldBlock label="入库模式">
          <Select value={draft.ingestMode} onValueChange={(value) => updateDraft('ingestMode', value as IngestMode)}>
            <SelectTrigger className={SOFT_CONTROL_CLASS} aria-label="入库模式"><span className="truncate">{getSelectOptionTitle(INGEST_MODE_OPTIONS, draft.ingestMode)}</span></SelectTrigger>
            <SelectContent className={SELECT_MENU_CLASS}>
              {INGEST_MODE_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value} textValue={option.title} className={SELECT_OPTION_CLASS}><SelectOptionBody {...option} /></SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FieldBlock>
        <FieldBlock label="标签">
          <Input list={tagListId} className={CONFIG_INPUT_CLASS} value={draft.tags} onChange={(event) => updateDraft('tags', event.target.value)} placeholder="选择或输入标签" />
          <datalist id={tagListId}>{tagOptions.map((tag) => <option key={tag} value={tag} />)}</datalist>
        </FieldBlock>
        <FieldBlock label="目标目录">
          <Input list={collectionListId} className={CONFIG_INPUT_CLASS} value={draft.collection} onChange={(event) => updateDraft('collection', event.target.value)} placeholder="default" />
          <datalist id={collectionListId}>{collectionOptions.map((collection) => <option key={collection} value={collection} />)}</datalist>
        </FieldBlock>
      </div>
    </details>
  )
}
