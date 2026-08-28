'use client'

import { type ReactNode, type RefObject, useCallback, useEffect, useMemo, useRef, useState } from 'react'
import {
  Archive,
  ArrowRight,
  CheckCircle2,
  ChevronDown,
  CircleAlert,
  Cloud,
  Database,
  FileArchive,
  FileSpreadsheet,
  FileText,
  FileType,
  FileUp,
  Folder,
  Link as LinkIcon,
  Loader2,
  Play,
  Plus,
  RefreshCw,
  ShieldCheck,
  Trash2,
  UploadCloud,
  type LucideIcon,
} from 'lucide-react'
import { useQuery } from '@tanstack/react-query'
import { useRouter, useSearchParams } from 'next/navigation'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
} from '@/components/ui/select'
import { Tabs, TabsContent } from '@/components/ui/tabs'
import { Textarea } from '@/components/ui/textarea'
import { connectorApi, datasetApi, documentApi, settingsApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { readClientStorage } from '@/lib/client-storage'
import { cn, detachPromise, formatFileSize } from '@/lib/utils'
import type {
  Dataset,
  Document,
  DocumentBatchUploadResponse,
  DocumentFolderNode,
  DocumentPipelineOptions,
} from '@/types'

import { IngestionViewSwitch } from './view-switch'

const DRAFT_KEY = 'mimirq.knowledge.ingestion.operation.draft'
const DEFAULT_COLLECTION = 'default'
const NO_DATASET_FILE_BUCKET = '__mimirq_no_dataset__'
const EMPTY_FILES: File[] = []
const OPERATION_BACKGROUND_CLASS =
  'bg-background bg-[radial-gradient(circle_at_top,hsl(var(--info)/0.10),transparent_34rem)] dark:bg-background'
const OPERATION_HERO_PANEL_CLASS =
  'relative overflow-hidden border-b border-border/60 bg-transparent px-1 py-2 shadow-none dark:border-border/70'

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
  icon: LucideIcon
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
  icon: LucideIcon
}> = [
  { label: '登记', description: '校验来源与文件', icon: FileUp },
  { label: '解析', description: '提取正文与结构', icon: FileText },
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

const SOFT_CONTROL_CLASS =
  'rounded-[1rem] border-border/55 bg-background/76 text-[13px] shadow-[inset_0_1px_0_hsl(var(--card)/0.68)]'
const CONFIG_BOX_CLASS = 'border-y border-border/55 bg-transparent'
const CONFIG_INPUT_CLASS =
  'rounded-[1rem] border-border/55 bg-card/72 text-[13px] shadow-[inset_0_1px_0_hsl(var(--card)/0.66)]'
const TABLE_SHELL_CLASS = 'overflow-hidden border-b border-border/65 bg-transparent'
const TABLE_HEAD_CLASS = 'bg-muted/20 text-[10px] font-medium text-muted-foreground/72'
const TABLE_ROW_CLASS = 'border-t border-border/45 text-[12px] leading-5 transition-colors hover:bg-muted/[0.16]'
const SELECT_MENU_CLASS =
  'rounded-[18px] border-border/50 bg-popover/96 p-1 shadow-[0_22px_56px_-34px_hsl(var(--foreground)/0.28)] backdrop-blur-xl'
const SELECT_OPTION_CLASS =
  'min-h-[46px] items-start rounded-[14px] py-2 pl-8 pr-3 text-[12px] data-[highlighted]:bg-primary/[0.08] data-[state=checked]:bg-primary/[0.08] data-[state=checked]:text-primary'
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
    description: '仅登记到知识库（不解析），不启动解析队列。',
    badge: '默认',
  },
  {
    value: 'parse_only',
    title: '入库并解析',
    description: '入库并解析（不建索引），可进入执行监控。',
    badge: '监控',
  },
  {
    value: 'full_index',
    title: '解析 + 索引',
    description: '完整入库（解析 + 索引），直接写入检索索引。',
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
  badge,
  description,
  title,
}: Readonly<{
  badge?: string
  description: string
  title: string
}>) {
  return (
    <span className="flex min-w-0 flex-col gap-0.5">
      <span className="flex min-w-0 items-center gap-2">
        <span className="truncate text-[13px] font-semibold leading-4 text-foreground">
          {title}
        </span>
        {badge ? (
          <span className="shrink-0 rounded-full border border-primary/18 bg-primary/[0.07] px-1.5 py-0.5 text-[9px] font-medium leading-none text-primary">
            {badge}
          </span>
        ) : null}
      </span>
      <span className="line-clamp-2 text-[10px] leading-4 text-muted-foreground/68">
        {description}
      </span>
    </span>
  )
}

function DatasetOptionBody({ dataset }: Readonly<{ dataset: Dataset }>) {
  return (
    <span className="flex min-w-0 flex-col gap-0.5">
      <span className="truncate text-[13px] font-semibold leading-4 text-foreground">
        {dataset.name}
      </span>
      <span className="font-mono text-[10px] leading-4 text-muted-foreground/58">
        ID {datasetShortId(dataset)}
      </span>
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
  const ext = file.name.split('.').pop()?.toLowerCase()
  if (['xlsx', 'xls', 'csv'].includes(ext || '')) return FileSpreadsheet
  if (['zip'].includes(ext || '')) return FileArchive
  if (['md', 'markdown', 'txt', 'html', 'docx', 'pdf'].includes(ext || '')) return FileText
  return FileType
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

  useEffect(() => {
    folderInputRef.current?.setAttribute('webkitdirectory', '')
    folderInputRef.current?.setAttribute('directory', '')
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
    Boolean(draft.datasetId) &&
    status !== 'uploading' &&
    pendingSourceCount > 0 &&
    !connectorSourceBlocked

  const totalDocuments = ingestionStats?.total_documents ?? documents.length
  const totalChunks = ingestionStats?.total_chunks ?? documents.reduce((sum, item) => sum + Number(item.chunk_count || 0), 0)
  const datasetTotalBytes = ingestionStats?.total_size ?? documents.reduce((sum, item) => sum + Number(item.file_size || 0), 0)

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
      await Promise.all([foldersQuery.refetch(), ingestionStatsQuery.refetch()])
      toast.success(`连接器任务已创建：${String(run.id).slice(0, 8)}`)
      if (run.status !== 'failed' && shouldOpenExecutionMonitor(draft, 'ingest')) {
        router.push('/knowledge/ingestion?mode=execution-monitor')
      }
    } catch (error) {
      setStatus('failed')
      toast.error(formatApiError(error, '连接器任务创建失败'))
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
        toast.error(formatApiError(error, '入库任务提交失败'))
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
  const ActiveSourceIcon = activeSource.icon
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

  return (
    <div
      data-ingestion-operation-root="true"
      className={cn(
        'flex h-full min-h-0 overflow-y-auto px-3 py-2.5 text-foreground',
        OPERATION_BACKGROUND_CLASS
      )}
    >
      <div className="mx-auto min-h-full w-full max-w-[1680px]">
        <div
          className={cn(
            'grid min-h-14 min-w-0 xl:grid-cols-[minmax(0,1fr)_auto]',
            OPERATION_HERO_PANEL_CLASS
          )}
        >
          <span className="pointer-events-none absolute -bottom-px left-1 h-px w-12 bg-info/70" aria-hidden="true" />
          <div className="relative flex min-w-0 items-center gap-2.5">
            <div className="flex size-7 shrink-0 items-center justify-center overflow-hidden rounded-md bg-info/10 text-info shadow-none">
              <PageTitleIcon name="ingestion-operation" className="size-6" />
            </div>
            <div className="min-w-0 sm:flex sm:items-center sm:gap-2.5">
              <h1 className="shrink-0 whitespace-nowrap text-[19px] font-semibold leading-6 tracking-[-0.02em] text-foreground">
                入库管理
              </h1>
              <p className="text-[12px] leading-5 text-muted-foreground/85">
                选择目标和来源，确认执行路径后提交。
              </p>
            </div>
          </div>
          <div className="flex min-w-[360px] items-center justify-end gap-2 border-t border-border/60 p-2 xl:border-t-0">
            <IngestionViewSwitch compact tone="info" />
            <Button
              variant="ghost"
              size="icon"
              title="同步数据集状态"
              aria-label="同步数据集状态"
              className="size-9 rounded-lg text-muted-foreground hover:bg-muted/35 hover:text-foreground"
              onClick={() => detachPromise(handleSyncDatasets())}
            >
              <RefreshCw className="size-4" />
            </Button>
          </div>
        </div>

        <div
          data-ingestion-operation-workspace="true"
          className={cn(
            'grid min-h-[calc(100vh-6.5rem)] xl:grid-cols-[300px_minmax(0,1fr)]'
          )}
        >
          <aside
            data-ingestion-context-panel="true"
            className="h-full border-b border-border/70 xl:border-b-0 xl:border-r"
            aria-label="入库任务上下文"
          >
            <section className="border-b border-border/70 px-5 py-4">
              <div className="flex items-center justify-between gap-3">
                <label htmlFor="ingestion-dataset" className="text-[13px] font-semibold">目标数据集</label>
                <Button variant="ghost" className="h-7 rounded-md px-2 text-[11px] text-muted-foreground" onClick={() => router.push('/datasets')}>
                  <Plus className="size-3.5" />
                  新建
                </Button>
              </div>
              <Select value={draft.datasetId} onValueChange={(value) => updateDraft('datasetId', value)}>
                <SelectTrigger id="ingestion-dataset" className={cn('mt-2 h-10 font-medium', SOFT_CONTROL_CLASS)}>
                  <span className="min-w-0 truncate text-[13px] font-semibold">
                    {selectedDataset?.name ?? (datasetsQuery.isLoading ? '正在加载数据集' : '选择目标数据集')}
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
              <div className="mt-2 flex flex-wrap gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
                <span>{totalDocuments.toLocaleString()} 文档</span>
                <span>{totalChunks.toLocaleString()} 分块</span>
                <span>{formatFileSize(datasetTotalBytes)}</span>
              </div>
            </section>

            <section className="border-b border-border/70 px-5 py-4">
              <label htmlFor="ingestion-source" className="text-[13px] font-semibold">文件来源</label>
              <Select value={source} onValueChange={(value) => setSource(value as UploadSource)}>
                <SelectTrigger id="ingestion-source" className={cn('mt-2 h-10 pl-3 font-medium', SOFT_CONTROL_CLASS)}>
                  <span className="flex min-w-0 items-center gap-2">
                    <ActiveSourceIcon className="size-4 shrink-0 text-info" />
                    <span className="truncate text-[13px] font-medium">{activeSource.label}</span>
                  </span>
                </SelectTrigger>
                <SelectContent className={SELECT_MENU_CLASS}>
                  {SOURCE_OPTIONS.map((item) => {
                    const Icon = item.icon
                    return (
                      <SelectItem key={item.value} value={item.value} textValue={item.label} className={SELECT_OPTION_CLASS}>
                        <span className="flex items-start gap-2">
                          <Icon className="mt-0.5 size-4 text-info" />
                          <span>
                            <span className="block font-medium">{item.label}</span>
                            <span className="block text-[10px] text-muted-foreground">{item.description}</span>
                          </span>
                        </span>
                      </SelectItem>
                    )
                  })}
                </SelectContent>
              </Select>
              <p className="mt-1.5 text-[10px] text-muted-foreground">{activeSource.description}</p>
            </section>

            <fieldset className="border-b border-border/70 px-5 py-4">
              <legend className="text-[13px] font-semibold">执行终点</legend>
              <div className="mt-2 space-y-1">
                {EXECUTION_MODE_OPTIONS.map((option) => {
                  const selected = draft.executionMode === option.value
                  return (
                    <label key={option.value} className={cn('flex min-h-10 cursor-pointer items-center gap-3 rounded-md px-2 transition-colors hover:bg-muted/30', selected && 'bg-info/5')}>
                      <input
                        type="radio"
                        name="ingestion-execution-mode"
                        value={option.value}
                        checked={selected}
                        onChange={() => updateDraft('executionMode', option.value)}
                        className="size-4 accent-[hsl(var(--info))]"
                      />
                      <span className="min-w-0">
                        <span className="block text-[12px] font-semibold">{option.title}</span>
                        <span className="block truncate text-[10px] text-muted-foreground">{option.description}</span>
                      </span>
                    </label>
                  )
                })}
              </div>
            </fieldset>

            <AdvancedIngestSettings
              draft={draft}
              updateDraft={updateDraft}
              tagOptions={tagOptions}
              collectionOptions={collectionOptions}
            />
          </aside>

          <main className="flex min-h-0 min-w-0 flex-col">
            <section data-ingestion-pipeline="true" className="border-b border-border/70">
              <div className="flex flex-wrap items-center justify-between gap-3 border-b border-border/65 px-5 py-2.5">
                <div>
                  <h2 className="text-[13px] font-semibold">执行路径</h2>
                  <p className="mt-0.5 text-[10px] text-muted-foreground">内容会依次经过已启用的处理阶段</p>
                </div>
                <div className="flex items-center gap-2 font-mono text-[10px] text-muted-foreground">
                  <span>{pendingSourceCount} 项</span>
                  <ArrowRight className="size-3.5" />
                  <span>{activeStageCount} 个阶段</span>
                </div>
              </div>
              <div className="grid sm:grid-cols-2 xl:grid-cols-4">
                {OPERATION_STAGES.map((stage, index) => {
                  const Icon = stage.icon
                  const enabled = index < activeStageCount
                  return (
                    <div key={stage.label} className={cn('relative min-h-20 border-b border-border/65 px-4 py-3 sm:border-r xl:border-b-0', enabled ? 'bg-info/[0.025]' : 'bg-muted/10 text-muted-foreground', index === OPERATION_STAGES.length - 1 && 'sm:border-r-0')}>
                      <span className={cn('absolute inset-x-0 top-0 h-0.5', enabled ? 'bg-info' : 'bg-border')} />
                      <div className="flex min-w-0 items-center gap-2">
                        <Icon className={cn('size-4', enabled ? 'text-info' : 'text-muted-foreground')} />
                        <div className="min-w-0 flex-1">
                          <div className="text-[12px] font-semibold">{stage.label}</div>
                          <div className="truncate text-[10px] text-muted-foreground">{stage.description}</div>
                        </div>
                        <span className="font-mono text-[9px] text-muted-foreground">0{index + 1}</span>
                      </div>
                      <div className={cn('mt-2 pl-6 text-[10px]', enabled ? 'text-success' : 'text-muted-foreground')}>{enabled ? '● 已启用' : '○ 跳过'}</div>
                    </div>
                  )
                })}
              </div>
            </section>

            <section data-ingestion-file-stage="true" className="grid border-b border-border/70 lg:grid-cols-[minmax(0,1fr)_260px]">
              <div className="min-w-0 border-b border-border/65 lg:border-b-0 lg:border-r">
                <Tabs value={source} onValueChange={(value) => setSource(value as UploadSource)}>
                  <TabsContent value="local" className="m-0">
                    <UploadDropArea dragging={dragging} onDragState={setDragging} onClick={() => inputRef.current?.click()} onFiles={addFiles} />
                  </TabsContent>
                  <TabsContent value="folder" className="m-0"><SourceConfiguration source="folder" {...sourceConfigurationProps} /></TabsContent>
                  <TabsContent value="url" className="m-0"><SourceConfiguration source="url" {...sourceConfigurationProps} /></TabsContent>
                  <TabsContent value="object" className="m-0"><SourceConfiguration source="object" {...sourceConfigurationProps} /></TabsContent>
                  <TabsContent value="api" className="m-0"><SourceConfiguration source="api" {...sourceConfigurationProps} /></TabsContent>
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
              </div>
              <div className="flex min-h-24 items-center justify-between gap-3 px-5">
                <div>
                  <div className="text-[10px] text-muted-foreground">预检结果</div>
                  <div className={cn('mt-1 text-[12px] font-semibold', operationReady ? 'text-success' : 'text-warning')}>{preflightMessage}</div>
                </div>
                {operationReady ? <CheckCircle2 className="size-5 text-success" /> : <CircleAlert className="size-5 text-warning" />}
              </div>
            </section>

            {source === 'local' || source === 'folder' ? (
              <SelectedFilesTable
                rows={fileRows}
                totalBytes={selectedTotalBytes}
                sourceName={activeSource.label}
                dragging={dragging}
                onDragState={setDragging}
                onFiles={addFiles}
                onChoose={() => inputRef.current?.click()}
                onClear={clearFiles}
                onRemove={removeFile}
              />
            ) : null}

            <footer data-ingestion-action-bar="true" className="sticky bottom-0 z-10 flex flex-col gap-3 border-t border-border/70 bg-background/95 px-5 py-3 backdrop-blur lg:flex-row lg:items-center lg:justify-between">
              <div className="flex min-h-10 flex-wrap items-center gap-x-5 gap-y-1 text-[12px] text-muted-foreground">
                <span>{submissionSummary}</span>
                <span className="text-[10px]">{getSelectOptionTitle(DEDUP_OPTIONS, draft.dedupStrategy)}</span>
                {status === 'uploading' ? <span className="text-info">正在提交…</span> : null}
              </div>
              <Button
                variant="info"
                className="h-10 min-w-36 rounded-lg px-5 text-[12px] font-semibold shadow-subtle active:scale-[0.98]"
                onClick={() => detachPromise(uploadFiles(draft.executionMode === 'upload_only' ? 'upload_only' : 'ingest'))}
                disabled={!operationReady}
              >
                {status === 'uploading' ? <Loader2 className="size-4 animate-spin" /> : <Play className="size-4" />}
                {status === 'uploading' ? '正在提交' : status === 'completed' ? '再次提交' : actionLabel}
              </Button>
            </footer>
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
      <div className="mb-1.5 flex items-center gap-1 text-[11px] font-medium leading-none text-muted-foreground/74">
        {required ? <span className="text-destructive">*</span> : null}
        {label}
      </div>
      {children}
    </label>
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
        'flex min-h-24 w-full items-center gap-4 border-0 bg-transparent px-5 py-4 text-left transition-colors',
        dragging
          ? 'bg-info/[0.08] ring-2 ring-inset ring-info/30'
          : 'hover:bg-info/[0.035]'
      )}
    >
      <span className="flex size-9 shrink-0 items-center justify-center rounded-md bg-info/10 text-info">
        <UploadCloud className="size-5" />
      </span>
      <span>
        <span className="block text-[13px] font-semibold leading-5 text-foreground">添加文件到本次任务</span>
        <span className="mt-0.5 block text-[10px] leading-4 text-muted-foreground/70">点击选择或拖入文件 · 单文件 ≤ 2GB</span>
      </span>
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
              <div className="text-[14px] font-semibold leading-5 text-foreground">选择本地文件夹</div>
              <div className="text-[11px] leading-4 text-muted-foreground/70">浏览器会保留相对路径，后端按文件夹内文件批量上传到当前数据集。</div>
            </div>
          </div>
          <Button variant="outline" className={cn(CONFIG_INPUT_CLASS, 'h-9 text-[13px] font-medium hover:bg-background/88')} onClick={() => folderInputRef.current?.click()}>
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
          <div className="mt-1 text-[11px] leading-4 text-muted-foreground/70">
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
        {urlIngestEnabled ? null : (
          <div className="rounded-[1rem] border border-warning/20 bg-warning/[0.08] px-3 py-2 text-[11px] leading-4 text-warning md:col-span-2 xl:col-span-4">
            URL 导入未启用：对象存储需要后端通过 presigned URL 拉取文件，请先开启 URL_INGEST_ENABLED。
          </div>
        )}
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
          <div className="mt-1 text-[11px] leading-4 text-muted-foreground/70">实际提交：{parsedObjectExtensions.join(', ')}</div>
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
        <div className="mt-1 text-[11px] leading-4 text-muted-foreground/70">
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
  sourceName,
  dragging,
  onDragState,
  onFiles,
  onChoose,
  onClear,
  onRemove,
}: Readonly<{
  rows: Array<{ file: File; Icon: LucideIcon; key: string }>
  totalBytes: number
  sourceName: string
  dragging: boolean
  onDragState: (dragging: boolean) => void
  onFiles: (files: File[]) => void
  onChoose: () => void
  onClear: () => void
  onRemove: (key: string) => void
}>) {
  const hasRows = rows.length > 0

  return (
    <div
      data-ingestion-file-staging-workspace="true"
      data-selected-files-table="stable"
      className={cn('flex min-h-0 flex-1 flex-col', TABLE_SHELL_CLASS)}
    >
      <div className="flex h-10 shrink-0 items-center justify-between border-b border-border/50 px-3 py-1.5">
        <div className="flex items-center gap-2 text-[12px] font-semibold leading-none text-foreground">
          <span>本次任务文件</span>
          <span className="rounded-md border border-foreground/10 bg-muted/20 px-1.5 py-0.5 font-mono text-[9px] text-muted-foreground tabular-nums">
            {rows.length}
          </span>
        </div>
        {hasRows ? (
          <Button variant="ghost" className="h-8 rounded-md px-2 text-[10px] text-muted-foreground/72 hover:bg-muted/35" onClick={onClear}>
            <Trash2 className="size-3.5" />
            清空
          </Button>
        ) : (
          <span className="text-[10px] text-muted-foreground">等待文件</span>
        )}
      </div>
      {hasRows ? (
        <>
          <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain [scrollbar-gutter:stable]">
            <table className="w-full table-fixed text-left text-[12px]">
              <colgroup>
                <col className="w-[46%]" />
                <col className="w-[16%]" />
                <col className="w-[12%]" />
                <col className="w-[16%]" />
                <col className="w-[10%]" />
              </colgroup>
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
                        <span className="min-w-0 truncate font-medium text-foreground" title={file.name}>{file.name}</span>
                      </div>
                    </td>
                    <td className="truncate px-2.5 py-1.5 font-mono text-muted-foreground">{formatFileSize(file.size)}</td>
                    <td className="truncate px-2.5 py-1.5 text-muted-foreground">{formatFileType(file)}</td>
                    <td className="px-2.5 py-1.5 text-muted-foreground">{sourceName}</td>
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
          <div className="h-8 shrink-0 border-t border-border/50 px-3 py-1.5 text-xs text-muted-foreground">
            共 {rows.length} 个文件，合计 {formatFileSize(totalBytes)}
          </div>
        </>
      ) : (
        <button
          type="button"
          data-ingestion-empty-file-drop="true"
          onClick={onChoose}
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
            'flex min-h-[20rem] flex-1 flex-col items-center justify-center px-6 py-10 text-center transition-colors focus-ring',
            dragging
              ? 'bg-info/[0.08] ring-2 ring-inset ring-info/30'
              : 'bg-transparent hover:bg-info/[0.025]'
          )}
        >
          <UploadCloud className="size-7 text-info" />
          <span className="mt-3 text-[14px] font-semibold text-foreground">
            将文件拖到这里
          </span>
          <span className="mt-1 text-[11px] leading-5 text-muted-foreground">
            点击选择文件，或直接拖放到当前暂存区
          </span>
          <span className="mt-3 text-[10px] leading-5 text-muted-foreground/75">
            支持 PDF、Word、Markdown、表格、文本与压缩包 · 单文件 ≤ 2GB
          </span>
        </button>
      )}
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
  const tagListId = 'knowledge-ingestion-tag-options'
  const collectionListId = 'knowledge-ingestion-collection-options'

  return (
    <details data-ingestion-advanced-settings="true" className="group border-b border-border/70">
      <summary className="flex cursor-pointer list-none items-center justify-between gap-3 px-5 py-3 text-[12px] font-semibold marker:content-none">
        <span>
          高级设置
          <span className="ml-2 text-[10px] font-normal text-muted-foreground">入库模式、标签、目录、重复处理</span>
        </span>
        <ChevronDown className="size-4 text-muted-foreground transition-transform group-open:rotate-180" />
      </summary>
      <div className="grid gap-3 border-t border-border/65 px-5 py-4">
        <FieldBlock label="入库模式">
          <Select value={draft.ingestMode} onValueChange={(value) => updateDraft('ingestMode', value as IngestMode)}>
            <SelectTrigger className={cn('h-9 font-medium', SOFT_CONTROL_CLASS)}>
              <span className="truncate text-[12px] font-medium">{getSelectOptionTitle(INGEST_MODE_OPTIONS, draft.ingestMode)}</span>
            </SelectTrigger>
            <SelectContent className={SELECT_MENU_CLASS}>
              {INGEST_MODE_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value} textValue={option.title} className={SELECT_OPTION_CLASS}>
                  <SelectOptionBody {...option} />
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FieldBlock>
        <FieldBlock label="标签">
          <Input
            list={tagListId}
            className={cn('h-9 text-[12px]', CONFIG_INPUT_CLASS)}
            value={draft.tags}
            onChange={(event) => updateDraft('tags', event.target.value)}
            placeholder="选择或输入标签"
          />
          <datalist id={tagListId}>{tagOptions.map((tag) => <option key={tag} value={tag} />)}</datalist>
        </FieldBlock>
        <FieldBlock label="目标目录">
          <Input
            list={collectionListId}
            className={cn('h-9 text-[12px]', CONFIG_INPUT_CLASS)}
            value={draft.collection}
            onChange={(event) => updateDraft('collection', event.target.value)}
            placeholder="default"
          />
          <datalist id={collectionListId}>{collectionOptions.map((collection) => <option key={collection} value={collection} />)}</datalist>
        </FieldBlock>
        <FieldBlock label="重复处理">
          <Select value={draft.dedupStrategy} onValueChange={(value) => updateDraft('dedupStrategy', value)}>
            <SelectTrigger className={cn('h-9 font-medium', SOFT_CONTROL_CLASS)}>
              <span className="truncate text-[12px] font-medium">{getSelectOptionTitle(DEDUP_OPTIONS, draft.dedupStrategy)}</span>
            </SelectTrigger>
            <SelectContent className={SELECT_MENU_CLASS}>
              {DEDUP_OPTIONS.map((option) => (
                <SelectItem key={option.value} value={option.value} textValue={option.title} className={SELECT_OPTION_CLASS}>
                  <SelectOptionBody {...option} />
                </SelectItem>
              ))}
            </SelectContent>
          </Select>
        </FieldBlock>
      </div>
    </details>
  )
}
