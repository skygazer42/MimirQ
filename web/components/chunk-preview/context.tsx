/**
 * ChunkPreview Context
 * 管理切片预览的状态和业务逻辑
 */
'use client'

import {
  createContext,
  useContext,
  useState,
  useCallback,
  useRef,
  useEffect,
  useLayoutEffect,
  useMemo,
  useSyncExternalStore,
  type ReactNode,
} from 'react'
import { useQueryClient, type Query } from '@tanstack/react-query'
import { useSearchParams } from 'next/navigation'
import { toast } from 'sonner'
import { useRouter } from '@/i18n/navigation'
import { documentApi, parsingApi } from '@/lib/api'
import type { ChunkPreviewRequestParams } from '@/lib/api/document-helpers'
import { formatApiError } from '@/lib/api-errors'
import { readClientStorage, removeClientStorage, writeClientStorage } from '@/lib/client-storage'
import { generateRequestId } from '@/lib/request-id'
import { AUTH_SCOPE_CHANGED_EVENT, getAuthCacheScope, getAuthSessionRevision } from '@/lib/auth-storage'
import { queryKeys } from '@/lib/query-keys'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { usePipelineCapabilities } from '@/contexts/pipeline-capabilities-context'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import { useParsedFiles } from '@/store/use-parsed-files-store'
import type { ParsedFileData } from '@/store/use-parsed-files-store'
import { getChunkStrategyLabel, isRetiredChunkStrategy } from '@/lib/chunk-strategies'
import { isRetiredParserBackend } from '@/lib/parser-compat'
import { getParserLabel } from '@/lib/parser-options'
import { assertCompleteDocumentContent, hasParsedFileMemoryContent } from '@/lib/document-library'
import { readMetadataString } from '@/components/chunk-preview/utils/metadata'
import type { ChunkPreviewResponse, ManualChunk } from '@/types'
import { applyChunkEdits } from '@/components/chunk-preview/utils/chunk-edits'
import type {
  ChunkOverride,
  ChunkOverrides,
  ChunkPreviewProcessedStatus,
  ChunkPreviewState,
  ChunkPreviewFileItem,
  ChunkPreviewContextType,
  ChunkPreviewRunSettings,
  ChunkPreviewProps,
} from './types'
import { EXAMPLE_TEXT } from './constants'
import {
  createFileWorkspace,
  selectWorkspaceFile,
  isChunkPreviewFileInScope,
  mergeScopedFiles,
  type FileWorkspaceState,
} from './file-workspace'
import { scanFiles } from './utils/file-scanner'
import { decodeSeparatorInput } from './utils/separators'
import {
  getStoredOriginalPreviewMode,
  shouldRevealPdfPreviewOnChunkSelect,
  isPdfOriginalFile,
} from './components/workbench/preview/pdf-dock'

const ChunkPreviewContext = createContext<ChunkPreviewContextType | null>(null)
const STORAGE_DATASET_ID_KEY = 'mimirq_chunk_preview_dataset_id'
const STORAGE_SEPARATOR_SETTINGS_KEY = 'mimirq_chunk_preview_separator_settings'
const STORAGE_FOCUS_FILE_ID_KEY = 'mimirq_chunk_preview_focus_file_id'
const STORAGE_PERF_SETTINGS_KEY = 'mimirq_chunk_preview_perf_settings'
const STORAGE_PARENT_CHILD_SETTINGS_KEY = 'mimirq_chunk_preview_parent_child_settings'
const CHUNK_PREVIEW_SCOPE_DOCUMENT_LIMIT = 8
const MANUAL_INGEST_STATUS_POLL_INTERVAL_MS = 1500
const MANUAL_INGEST_STATUS_MAX_WAIT_MS = 30 * 60 * 1000
const MANUAL_INGEST_STILL_PROCESSING_MESSAGE = '入库已提交，后端仍在处理。请稍后刷新列表确认结果。'
const PREVIEW_UPDATE_REQUIRED_MESSAGE = '当前预览需要更新，请重新生成后再入库。'
const COMPLETE_PREVIEW_REQUIRED_MESSAGE = '当前预览只包含部分切块，请将“最多返回切块”设为 0，重新生成完整预览后再入库。'
type MarkdownChunkFileSource = {
  id: string
  markdown: string
  filename: string
  fileType?: string | null
  fileSize?: number | null
  sourceTimeMs?: number
  source: 'parsing_workspace' | 'knowledge_base'
  datasetId?: string | null
  datasetName?: string | null
  documentId: string | null
}

type MarkdownFileSnapshot = { markdown: string; file: File; revision: string }
type ScopeSyncControl = { datasetId: string; cancelled: boolean; removedIds: Set<string> }
type ChunkParamNavigation = Readonly<{ from: string | null; to: string | null }>

type ScopedChunkFiles = Readonly<{ sources: MarkdownChunkFileSource[]; error: string | null }>

const scopedChunkFilesInFlight = new Map<string, Promise<ScopedChunkFiles>>()

type PreviewSnapshot = Readonly<{
  data: ChunkPreviewResponse
  file: File
  sessionRevision: number
  requestId: number
}>

type PreviewSubmissionView = Readonly<{
  data: ChunkPreviewResponse | null
  overrides: ChunkOverrides
  cacheKey: string | null
}>

type PreviewIngestResult = Readonly<{
  view: PreviewSubmissionView
  documentId: string
  completed: boolean
}>

type IngestReceipt = Pick<Awaited<ReturnType<typeof documentApi.createFromChunks>>, 'id' | 'status'> & {
  previewRequestId: number | null
}

function ingestReceiptKey(cacheKey: string, datasetId: string, overrides: ChunkOverrides): string {
  return JSON.stringify([cacheKey, datasetId, overrides])
}

function isLocallyWrittenChunkParam(chunkParam: string, navigation: ChunkParamNavigation | null): boolean {
  return navigation !== null && (chunkParam === navigation.from || chunkParam === navigation.to)
}

function buildChunkPreviewHref(params: URLSearchParams): string {
  const query = params.toString()
  return query.length === 0 ? '/chunk-preview' : `/chunk-preview?${query}`
}

function buildPreviewCacheKey(fileItem: ChunkPreviewFileItem, params: ChunkPreviewRequestParams): string {
  const { id, fileRevision, file } = fileItem
  return JSON.stringify({
    authScope: getAuthCacheScope(),
    sessionRevision: getAuthSessionRevision(),
    fileId: id,
    fileRevision,
    filename: file.name,
    fileSize: file.size,
    lastModified: file.lastModified,
    params,
  })
}

function isSamePreviewSubmissionView(current: PreviewSubmissionView, submitted: PreviewSubmissionView): boolean {
  return (
    current.data === submitted.data &&
    current.overrides === submitted.overrides &&
    current.cacheKey === submitted.cacheKey
  )
}

class ManualIngestStillProcessingError extends Error {
  constructor() {
    super(MANUAL_INGEST_STILL_PROCESSING_MESSAGE)
    this.name = 'ManualIngestStillProcessingError'
  }
}

class ManualIngestFailedError extends Error {}

function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => {
    globalThis.setTimeout(resolve, ms)
  })
}

async function waitForDocumentIngestCompletion(
  documentId: string,
  initialStatus: string,
  isSessionCurrent: () => boolean,
): Promise<void> {
  let status = initialStatus.trim().toLowerCase()
  const startedAt = Date.now()
  while (Date.now() - startedAt <= MANUAL_INGEST_STATUS_MAX_WAIT_MS) {
    if (!isSessionCurrent()) return
    if (status === 'completed') return
    if (status === 'failed' || status === 'cancelled' || status === 'quarantined') {
      throw new ManualIngestFailedError(`入库失败：后端状态为 ${status}`)
    }

    await sleep(MANUAL_INGEST_STATUS_POLL_INTERVAL_MS)
    if (!isSessionCurrent()) return
    const latest = await documentApi.getStatus(documentId)
    status = latest.status.trim().toLowerCase()
    if (status === 'completed') return
    if (status === 'failed' || status === 'cancelled' || status === 'quarantined') {
      throw new ManualIngestFailedError(latest.error_message ?? `入库失败：后端状态为 ${status}`)
    }
  }

  throw new ManualIngestStillProcessingError()
}

function makeMarkdownChunkFileItem(
  params: MarkdownChunkFileSource,
  snapshots: Map<string, MarkdownFileSnapshot>,
): ChunkPreviewFileItem {
  const originalFilename = params.filename
  const base = originalFilename.toLowerCase().endsWith('.md')
    ? originalFilename
    : originalFilename.replace(/\.[^/.]+$/, '')
  const internalFilename = originalFilename.toLowerCase().endsWith('.md') ? originalFilename : `${base}.md`
  const markdown = params.markdown
  let snapshot = snapshots.get(params.id)
  if (snapshot === undefined || snapshot.markdown !== markdown || snapshot.file.name !== internalFilename) {
    snapshot = {
      markdown,
      file: new File([markdown], internalFilename, { type: 'text/markdown' }),
      revision: generateRequestId(),
    }
    snapshots.set(params.id, snapshot)
  }

  return {
    id: params.id,
    file: snapshot.file,
    fileRevision: snapshot.revision,
    displayName: originalFilename,
    originalFileType: params.fileType ?? undefined,
    originalFileSize: params.fileSize ?? undefined,
    sourceTimeMs: params.sourceTimeMs,
    source: params.source,
    datasetId: params.datasetId ?? null,
    datasetName: params.datasetName ?? null,
    documentId: params.documentId,
  }
}

function makeMarkdownChunkFileItems(
  sources: readonly MarkdownChunkFileSource[],
  snapshots: Map<string, MarkdownFileSnapshot>,
): ChunkPreviewFileItem[] {
  const seen = new Set<string>()
  const items: ChunkPreviewFileItem[] = []
  for (const source of sources) {
    if (seen.has(source.id)) continue
    seen.add(source.id)
    items.push(makeMarkdownChunkFileItem(source, snapshots))
  }
  return items
}

function parsedFileToChunkFileSource(pf: ParsedFileData): MarkdownChunkFileSource | null {
  if (!hasParsedFileMemoryContent(pf)) return null

  return {
    id: pf.id,
    markdown: pf.markdownContent,
    filename: pf.filename,
    fileType: pf.fileType,
    fileSize: pf.fileSize,
    sourceTimeMs: Date.parse(pf.parsedAt),
    source: pf.source === 'knowledge_base' ? 'knowledge_base' : 'parsing_workspace',
    datasetId: pf.datasetId,
    datasetName: pf.datasetName,
    documentId: pf.source === undefined ? null : pf.id,
  }
}

function getParsedChunkFileSources(files: readonly ParsedFileData[], datasetId: string): MarkdownChunkFileSource[] {
  const sources: MarkdownChunkFileSource[] = []
  for (const file of files) {
    const source = parsedFileToChunkFileSource(file)
    if (source !== null && isChunkPreviewFileInScope(source, datasetId)) sources.push(source)
  }
  return sources
}

function isParsingWorkspaceDocument(doc: Awaited<ReturnType<typeof documentApi.list>>['items'][number]): boolean {
  const meta = doc.metadata
  return meta?.workspace === 'parsing'
}

async function loadKnowledgeChunkFiles(datasetId: string, isSessionCurrent: () => boolean): Promise<ScopedChunkFiles> {
  const response = await documentApi.list({ skip: 0, limit: CHUNK_PREVIEW_SCOPE_DOCUMENT_LIMIT, dataset_id: datasetId })
  const docs = response.items.filter((doc) => !isParsingWorkspaceDocument(doc))
  const sources: MarkdownChunkFileSource[] = []
  const errors: string[] = []
  for (const doc of docs) {
    if (!isSessionCurrent()) break
    const id = doc.id
    try {
      const content = await documentApi.getParsedContent(id, { max_chars: 2_000_000 })
      assertCompleteDocumentContent(content)
      sources.push({
        id,
        markdown: content.markdown_content,
        filename: doc.filename,
        fileType: doc.file_type,
        fileSize: doc.file_size,
        sourceTimeMs: doc.updated_at === null || doc.updated_at === undefined ? undefined : Date.parse(doc.updated_at),
        source: 'knowledge_base',
        datasetId: doc.dataset_id ?? datasetId,
        documentId: id,
      })
    } catch (error) {
      errors.push(`${doc.filename}：${formatApiError(error, '正文读取失败')}`)
    }
  }

  return { sources, error: errors.length === 0 ? null : errors.join('；') }
}

async function loadParsingWorkspaceChunkFiles(isSessionCurrent: () => boolean): Promise<MarkdownChunkFileSource[]> {
  const response = await parsingApi.listDocuments({ skip: 0, limit: CHUNK_PREVIEW_SCOPE_DOCUMENT_LIMIT })
  const docs = response.items

  const items: MarkdownChunkFileSource[] = []
  for (const doc of docs) {
    if (!isSessionCurrent()) return []
    const id = doc.id
    const content = await parsingApi.getContent(id)
    const meta = doc.metadata
    items.push({
      id,
      markdown: content.markdown_content,
      filename: doc.filename,
      fileType: doc.file_type,
      fileSize: doc.file_size,
      sourceTimeMs: doc.updated_at === null || doc.updated_at === undefined ? undefined : Date.parse(doc.updated_at),
      source: 'parsing_workspace',
      datasetId: doc.dataset_id ?? null,
      datasetName: readMetadataString(meta?.dataset_name) ?? null,
      documentId: id,
    })
  }

  return items
}

async function loadScopedChunkFiles(datasetId: string): Promise<ScopedChunkFiles> {
  const scopedDatasetId = datasetId.trim()
  const authScope = getAuthCacheScope()
  const sessionRevision = getAuthSessionRevision()
  const isSessionCurrent = () => getAuthCacheScope() === authScope && getAuthSessionRevision() === sessionRevision
  const scopeKey = JSON.stringify([authScope, sessionRevision, scopedDatasetId])
  const existing = scopedChunkFilesInFlight.get(scopeKey)
  if (existing) return existing

  const promise = scopedDatasetId
    ? loadKnowledgeChunkFiles(scopedDatasetId, isSessionCurrent)
    : loadParsingWorkspaceChunkFiles(isSessionCurrent).then((sources) => ({ sources, error: null }))
  scopedChunkFilesInFlight.set(scopeKey, promise)

  try {
    return await promise
  } finally {
    if (scopedChunkFilesInFlight.get(scopeKey) === promise) {
      scopedChunkFilesInFlight.delete(scopeKey)
    }
  }
}

function getApiErrorStatus(error: unknown): number | undefined {
  if (typeof error !== 'object' || error === null) return undefined
  const response = (error as { response?: { status?: unknown } }).response
  return typeof response?.status === 'number' ? response.status : undefined
}

export function useChunkPreview() {
  const context = useContext(ChunkPreviewContext)
  if (!context) {
    throw new Error('useChunkPreview must be used within ChunkPreviewProvider')
  }
  return context
}

type ChunkPreviewProviderProps = ChunkPreviewProps & {
  children: ReactNode
}

export function ChunkPreviewProvider({ children, onConfirm, onClose }: Readonly<ChunkPreviewProviderProps>) {
  const authScope = useSyncExternalStore(subscribeToAuthScope, getAuthCacheScope, getAuthCacheScope)
  return (
    <ChunkPreviewWorkspace key={authScope} onConfirm={onConfirm} onClose={onClose}>
      {children}
    </ChunkPreviewWorkspace>
  )
}

function subscribeToAuthScope(onChange: () => void) {
  globalThis.window.addEventListener(AUTH_SCOPE_CHANGED_EVENT, onChange)
  return () => globalThis.window.removeEventListener(AUTH_SCOPE_CHANGED_EVENT, onChange)
}

function ChunkPreviewWorkspace({ children, onConfirm, onClose }: Readonly<ChunkPreviewProviderProps>) {
  const router = useRouter()
  const queryClient = useQueryClient()
  const searchParams = useSearchParams()
  // 外部依赖
  const parsedFiles = useParsedFiles((state) => state.files)
  const { parserBackend, setParserBackend } = useParserBackendPreference()
  const { chunkStrategy, setChunkStrategy } = useChunkStrategyPreference()
  const { enabled: pipelineOverridesEnabled, options: pipelineOptions, updateOption } = usePipelineOptions()
  const { capabilities, parserBackendAvailable, chunkStrategyAvailable } = usePipelineCapabilities()

  // 核心状态
  const [fileWorkspace, setFileWorkspace] = useState<FileWorkspaceState>(() => createFileWorkspace([], null, new Set()))
  const fileList = fileWorkspace.files
  const selectedIngestFileIds = fileWorkspace.selectedIngestFileIds
  const currentFileIndex =
    fileWorkspace.currentFileId === null ? 0 : fileList.findIndex((item) => item.id === fileWorkspace.currentFileId)
  const [isDragging, setIsDragging] = useState(false)

  const [isLoading, setIsLoading] = useState(false)
  const [isSubmitting, setIsSubmitting] = useState(false)
  const [showOriginalPanel, setShowOriginalPanel] = useState(true)
  const [showSettingsPanel, setShowSettingsPanel] = useState(false)
  const [gapReviewRequest, setGapReviewRequest] = useState(0)
  const [error, setError] = useState<string | null>(null)
  const [ingestResult, setIngestResult] = useState<PreviewIngestResult | null>(null)

  const [datasetId, setDatasetId] = useState<string>('')
  const [scopeSyncLoading, setScopeSyncLoading] = useState(false)
  const [scopeSyncError, setScopeSyncError] = useState<string | null>(null)
  const [scopeReloadRequest, setScopeReloadRequest] = useState(0)

  const [previewSnapshot, setPreviewSnapshot] = useState<PreviewSnapshot | null>(null)
  const previewData = previewSnapshot?.data ?? null
  const previewSourceFile = previewSnapshot?.file ?? null
  const [chunkOverrides, setChunkOverrides] = useState<ChunkOverrides>({})
  const [hoveredChunkIndex, setHoveredChunkIndex] = useState<number | null>(null)
  const [selectedChunkIndex, setSelectedChunkIndex] = useState<number | null>(null)
  const [lastPreviewAt, setLastPreviewAt] = useState<number | null>(null)
  const [lastPreviewDurationMs, setLastPreviewDurationMs] = useState<number | null>(null)
  const [cacheHit, setCacheHit] = useState(false)
  const [lastPreviewCacheKey, setLastPreviewCacheKey] = useState<string | null>(null)
  const [autoPreviewEnabled, setAutoPreviewEnabled] = useState(true)
  const [runHistory, setRunHistory] = useState<ChunkPreviewState['runHistory']>([])

  const [chunkSize, setChunkSize] = useState(pipelineOptions.chunk_size ?? 1000)
  const [chunkOverlap, setChunkOverlap] = useState(pipelineOptions.chunk_overlap ?? 200)

  // 控制预览载荷；手动入库要求完整预览，后台批量分块不使用预览数量上限。
  const [includeOriginalText, setIncludeOriginalText] = useState(true)
  const [originalTextMaxChars, setOriginalTextMaxChars] = useState(100000)
  const [maxChunks, setMaxChunks] = useState(2000)
  const [useParseCache, setUseParseCache] = useState(true)

  const [separatorPreset, setSeparatorPreset] = useState('paragraph')
  const [separatorCustom, setSeparatorCustom] = useState(String.raw`\n\n`)
  const [keepSeparator, setKeepSeparator] = useState(true)
  const [separatorMaxChunkSize, setSeparatorMaxChunkSize] = useState(0)

  // Strategy-specific options (preview tuning).
  const [parentChildRatio, setParentChildRatio] = useState(0.5)
  const [parentChildMinChildSize, setParentChildMinChildSize] = useState(200)

  // 其他状态
  const [ingestStatusByRevision, setIngestStatusByRevision] = useState<Record<string, ChunkPreviewProcessedStatus>>({})

  // Refs
  const previewRequestIdRef = useRef(0)
  const previewAbortRef = useRef<AbortController | null>(null)
  const previewCacheRef = useRef(
    new Map<string, Pick<PreviewSnapshot, 'data' | 'requestId'> & { createdAt: number; durationMs: number }>(),
  )
  const [separatorSettingsLoaded, setSeparatorSettingsLoaded] = useState(false)
  const [parentChildSettingsLoaded, setParentChildSettingsLoaded] = useState(false)
  const [perfSettingsLoaded, setPerfSettingsLoaded] = useState(false)
  const [fileSelectionReady, setFileSelectionReady] = useState(false)
  const [datasetScopeLoaded, setDatasetScopeLoaded] = useState(false)
  const datasetScopeLoadedRef = useRef(false)
  const mountedRef = useRef(false)
  const fileViewRevisionRef = useRef(0)
  const submissionRef = useRef<{ sessionRevision: number } | null>(null)
  const ingestReceiptsRef = useRef(new Map<string, IngestReceipt>())
  const autoPreviewAttemptRef = useRef<string | null>(null)
  const workspaceAuthScope = useRef(getAuthCacheScope()).current
  const fileListRef = useRef(fileList)
  const parsedFilesRef = useRef(parsedFiles)
  const markdownFileSnapshotsRef = useRef(new Map<string, MarkdownFileSnapshot>())
  const scopeSyncControlRef = useRef<ScopeSyncControl>({ datasetId, cancelled: false, removedIds: new Set() })
  const chunkParamNavigationRef = useRef<ChunkParamNavigation | null>(null)
  const chunkParam = searchParams.get('chunk')?.trim() ?? null
  const currentFileItem = fileList[currentFileIndex] ?? null
  const file = currentFileItem?.file ?? null
  const processedStatus = useMemo(() => {
    const entries: Array<[string, ChunkPreviewProcessedStatus]> = []
    for (const item of fileList) {
      const status = ingestStatusByRevision[item.fileRevision]
      if (status !== undefined) entries.push([item.id, status])
    }
    return Object.fromEntries(entries)
  }, [fileList, ingestStatusByRevision])

  useEffect(() => {
    const previous = fileListRef.current
    fileListRef.current = fileList
    if (previous === fileList) return
    const retained = new Set(fileList.map((item) => item.id))
    for (const key of markdownFileSnapshotsRef.current.keys()) {
      if (!retained.has(key)) markdownFileSnapshotsRef.current.delete(key)
    }
  }, [fileList])

  const retirePreview = useCallback(() => {
    previewRequestIdRef.current += 1
    previewAbortRef.current?.abort()
    previewAbortRef.current = null
    setIsLoading(false)
  }, [])

  const retireScopeSync = useCallback(() => {
    scopeSyncControlRef.current.cancelled = true
    setScopeSyncLoading(false)
  }, [])

  const reloadScopeDocuments = useCallback(() => {
    setScopeReloadRequest((request) => request + 1)
  }, [])

  useEffect(() => {
    mountedRef.current = true
    return () => {
      mountedRef.current = false
      previewRequestIdRef.current += 1
      previewAbortRef.current?.abort()
    }
  }, [])

  useEffect(() => {
    if (previewData === null) return
    if (chunkParam === null || !/^[0-9]+$/.test(chunkParam)) return
    if (isLocallyWrittenChunkParam(chunkParam, chunkParamNavigationRef.current)) return

    const position = Number(chunkParam) - 1
    if (!Number.isSafeInteger(position) || position < 0 || position >= previewData.chunks.length) return
    setSelectedChunkIndex((current) => (current === null ? position : current))
  }, [chunkParam, previewData])

  useEffect(() => {
    const isPdf = isPdfOriginalFile(previewData, previewSourceFile ?? file)
    const preferredPreviewMode = getStoredOriginalPreviewMode()
    setShowOriginalPanel(
      (visible) =>
        visible ||
        shouldRevealPdfPreviewOnChunkSelect({
          nextIndex: selectedChunkIndex,
          showOriginalPanel: visible,
          isPdf,
          preferredPreviewMode,
        }),
    )
  }, [file, previewData, previewSourceFile, selectedChunkIndex])

  useEffect(() => {
    const nextChunkParam = selectedChunkIndex === null ? null : String(selectedChunkIndex + 1)
    const navigation = chunkParamNavigationRef.current
    if (chunkParam === nextChunkParam && (navigation === null || navigation.to === nextChunkParam)) {
      chunkParamNavigationRef.current = nextChunkParam === null ? null : { from: nextChunkParam, to: nextChunkParam }
      return
    }

    // An incoming selection may need to wait for the preview response.
    if (nextChunkParam === null && chunkParam !== null && !isLocallyWrittenChunkParam(chunkParam, navigation)) return
    if (navigation !== null && navigation.from === chunkParam && navigation.to === nextChunkParam) return

    const params = new URLSearchParams(searchParams.toString())
    if (nextChunkParam === null) {
      params.delete('chunk')
    } else {
      params.set('chunk', nextChunkParam)
    }

    chunkParamNavigationRef.current = { from: chunkParam ?? navigation?.to ?? null, to: nextChunkParam }
    router.replace(buildChunkPreviewHref(params))
  }, [chunkParam, router, searchParams, selectedChunkIndex])

  useEffect(() => {
    if (datasetScopeLoadedRef.current) return
    const nextDatasetId =
      readMetadataString(searchParams.get('dataset_id')) ??
      readMetadataString(readClientStorage(STORAGE_DATASET_ID_KEY))
    if (nextDatasetId !== undefined) setDatasetId(nextDatasetId)
    datasetScopeLoadedRef.current = true
    setDatasetScopeLoaded(true)
  }, [searchParams])

  useEffect(() => {
    if (!datasetScopeLoaded) return
    if (datasetId.length > 0) writeClientStorage(STORAGE_DATASET_ID_KEY, datasetId)
    else removeClientStorage(STORAGE_DATASET_ID_KEY)
  }, [datasetId, datasetScopeLoaded])

  useEffect(() => {
    if (globalThis.window === undefined) return
    const raw = readClientStorage(STORAGE_SEPARATOR_SETTINGS_KEY)?.trim()
    if (!raw) {
      setSeparatorSettingsLoaded(true)
      return
    }
    try {
      const data = JSON.parse(raw)
      if (typeof data?.separatorPreset === 'string') setSeparatorPreset(data.separatorPreset)
      if (typeof data?.separatorCustom === 'string') setSeparatorCustom(data.separatorCustom)
      if (typeof data?.keepSeparator === 'boolean') setKeepSeparator(data.keepSeparator)
      if (typeof data?.separatorMaxChunkSize === 'number') setSeparatorMaxChunkSize(data.separatorMaxChunkSize)
    } catch {
      // ignore corrupted storage
    } finally {
      setSeparatorSettingsLoaded(true)
    }
  }, [])

  // Load parent-child strategy settings (best-effort).
  useEffect(() => {
    if (globalThis.window === undefined) return
    const raw = readClientStorage(STORAGE_PARENT_CHILD_SETTINGS_KEY)?.trim()
    if (!raw) {
      setParentChildSettingsLoaded(true)
      return
    }
    try {
      const data = JSON.parse(raw)
      if (typeof data?.parentChildRatio === 'number' && Number.isFinite(data.parentChildRatio)) {
        setParentChildRatio(Math.max(0.05, Math.min(1, data.parentChildRatio)))
      }
      if (typeof data?.parentChildMinChildSize === 'number' && Number.isFinite(data.parentChildMinChildSize)) {
        setParentChildMinChildSize(Math.max(50, Math.min(4000, Math.trunc(data.parentChildMinChildSize))))
      }
    } catch {
      // ignore corrupted storage
    } finally {
      setParentChildSettingsLoaded(true)
    }
  }, [])

  // Persist parent-child strategy settings.
  useEffect(() => {
    if (globalThis.window === undefined) return
    if (!parentChildSettingsLoaded) return
    const payload = JSON.stringify({
      parentChildRatio,
      parentChildMinChildSize,
    })
    writeClientStorage(STORAGE_PARENT_CHILD_SETTINGS_KEY, payload)
  }, [parentChildRatio, parentChildMinChildSize, parentChildSettingsLoaded])

  useEffect(() => {
    if (globalThis.window === undefined) return
    if (!separatorSettingsLoaded) return
    const payload = JSON.stringify({
      separatorPreset,
      separatorCustom,
      keepSeparator,
      separatorMaxChunkSize,
    })
    writeClientStorage(STORAGE_SEPARATOR_SETTINGS_KEY, payload)
  }, [separatorPreset, separatorCustom, keepSeparator, separatorMaxChunkSize, separatorSettingsLoaded])

  // Load preview perf settings (best-effort).
  useEffect(() => {
    if (globalThis.window === undefined) return
    const raw = readClientStorage(STORAGE_PERF_SETTINGS_KEY)?.trim()
    if (!raw) {
      setPerfSettingsLoaded(true)
      return
    }
    try {
      const data = JSON.parse(raw)
      if (typeof data?.includeOriginalText === 'boolean') setIncludeOriginalText(data.includeOriginalText)
      if (typeof data?.originalTextMaxChars === 'number' && Number.isFinite(data.originalTextMaxChars)) {
        setOriginalTextMaxChars(Math.max(0, Math.min(2_000_000, Math.trunc(data.originalTextMaxChars))))
      }
      if (typeof data?.maxChunks === 'number' && Number.isFinite(data.maxChunks)) {
        setMaxChunks(Math.max(0, Math.min(20000, Math.trunc(data.maxChunks))))
      }
      if (typeof data?.useParseCache === 'boolean') setUseParseCache(data.useParseCache)
    } catch {
      // ignore corrupted storage
    } finally {
      setPerfSettingsLoaded(true)
    }
  }, [])

  // Persist preview perf settings.
  useEffect(() => {
    if (globalThis.window === undefined) return
    if (!perfSettingsLoaded) return
    const payload = JSON.stringify({
      includeOriginalText,
      originalTextMaxChars,
      maxChunks,
      useParseCache,
    })
    writeClientStorage(STORAGE_PERF_SETTINGS_KEY, payload)
  }, [includeOriginalText, originalTextMaxChars, maxChunks, useParseCache, perfSettingsLoaded])

  // Persist the currently focused file (best-effort UX when coming back to the page).
  useEffect(() => {
    if (globalThis.window === undefined) return
    if (!fileSelectionReady) return
    if (!currentFileItem?.id) return
    writeClientStorage(STORAGE_FOCUS_FILE_ID_KEY, currentFileItem.id)
  }, [currentFileItem?.id, fileSelectionReady])

  // Restore focused file after fileList is initialized.
  useEffect(() => {
    if (globalThis.window === undefined) return
    if (fileSelectionReady) return
    if (fileList.length === 0) return
    const saved = readClientStorage(STORAGE_FOCUS_FILE_ID_KEY)?.trim()
    if (saved) {
      if (fileList.some((file) => file.id === saved)) setFileWorkspace((prev) => selectWorkspaceFile(prev, saved))
      else if (scopeSyncLoading || scopeSyncError !== null) return
    }
    setFileSelectionReady(true)
  }, [fileList, fileSelectionReady, scopeSyncLoading, scopeSyncError])

  // 初始化/切换范围：从解析工作台缓存加载。后端同步会在稍后补齐持久化内容。
  useEffect(() => {
    parsedFilesRef.current = parsedFiles
    if (!datasetScopeLoaded) return
    const control = scopeSyncControlRef.current
    if (control.datasetId === datasetId && control.cancelled) return
    const scoped = makeMarkdownChunkFileItems(
      getParsedChunkFileSources(parsedFiles, datasetId).filter(
        (source) => control.datasetId !== datasetId || !control.removedIds.has(source.id),
      ),
      markdownFileSnapshotsRef.current,
    )

    if (scoped.length === 0) return
    setFileWorkspace((prev) =>
      mergeScopedFiles(
        prev,
        [...scoped, ...prev.files.filter((item) => isChunkPreviewFileInScope(item, datasetId))],
        datasetId,
      ),
    )
  }, [datasetId, datasetScopeLoaded, parsedFiles])

  useEffect(() => {
    if (!datasetScopeLoaded) return
    const control: ScopeSyncControl = { datasetId, cancelled: false, removedIds: new Set() }
    scopeSyncControlRef.current = control
    const authScope = getAuthCacheScope()
    const sessionRevision = getAuthSessionRevision()
    const isCurrent = () =>
      !control.cancelled && getAuthCacheScope() === authScope && getAuthSessionRevision() === sessionRevision

    const loadScopedDocuments = async () => {
      setScopeSyncLoading(true)
      setScopeSyncError(null)
      setFileWorkspace((prev) =>
        createFileWorkspace(
          prev.files.filter((item) => isChunkPreviewFileInScope(item, datasetId)),
          prev.currentFileId,
          prev.selectedIngestFileIds,
        ),
      )

      try {
        const { sources, error } = await loadScopedChunkFiles(datasetId)

        if (!isCurrent()) return
        const scopedFiles = makeMarkdownChunkFileItems(
          [...getParsedChunkFileSources(parsedFilesRef.current, datasetId), ...sources].filter(
            (source) => !control.removedIds.has(source.id),
          ),
          markdownFileSnapshotsRef.current,
        )
        setFileWorkspace((prev) => mergeScopedFiles(prev, scopedFiles, datasetId))
        setScopeSyncError(error)
      } catch (err: unknown) {
        if (!isCurrent()) return
        setScopeSyncError(formatApiError(err, '加载范围文档失败'))
      } finally {
        if (!control.cancelled) setScopeSyncLoading(false)
      }
    }

    void loadScopedDocuments()
    return () => {
      control.cancelled = true
    }
  }, [datasetId, datasetScopeLoaded, scopeReloadRequest])

  // 同步 pipeline options
  useEffect(() => {
    if (typeof pipelineOptions.chunk_size === 'number' && pipelineOptions.chunk_size !== chunkSize) {
      setChunkSize(pipelineOptions.chunk_size)
    }
  }, [pipelineOptions.chunk_size, chunkSize])

  useEffect(() => {
    if (typeof pipelineOptions.chunk_overlap === 'number' && pipelineOptions.chunk_overlap !== chunkOverlap) {
      setChunkOverlap(pipelineOptions.chunk_overlap)
    }
  }, [pipelineOptions.chunk_overlap, chunkOverlap])

  // Keep overlap consistent for separator strategy (no overlap).
  useEffect(() => {
    if (chunkStrategy !== 'separator') return
    if (chunkOverlap === 0) return
    setChunkOverlap(0)
    updateOption('chunk_overlap', 0)
  }, [chunkOverlap, chunkStrategy, updateOption])

  useEffect(() => {
    if (isRetiredParserBackend(parserBackend)) {
      setError(`解析器已移除：${getParserLabel(parserBackend)}。请选择其他解析器。`)
      return
    }
    if (!capabilities || parserBackendAvailable(parserBackend) !== false) return
    const fallback = capabilities.default_parser_backend
    if (fallback === parserBackend) return

    setParserBackend(fallback)
    setError(`解析器不可用，已切换为 ${getParserLabel(fallback)}`)
  }, [capabilities, parserBackend, parserBackendAvailable, setParserBackend])

  useEffect(() => {
    if (isRetiredChunkStrategy(chunkStrategy)) {
      setError(`切块策略已移除：${getChunkStrategyLabel(chunkStrategy)}。请选择其他策略。`)
      return
    }
    if (!capabilities || chunkStrategyAvailable(chunkStrategy) !== false) return
    const fallback = capabilities.default_chunk_strategy
    if (fallback === chunkStrategy) return

    setChunkStrategy(fallback)
    setError(`切块策略不可用，已切换为 ${getChunkStrategyLabel(fallback)}`)
  }, [capabilities, chunkStrategy, chunkStrategyAvailable, setChunkStrategy])

  // Actions: 文件操作
  const addFiles = useCallback(
    (files: File[]) => {
      setFileSelectionReady(true)
      const sourceTimeMs = Date.now()
      const added = files.map<ChunkPreviewFileItem>((f) => {
        const id = generateRequestId()
        return {
          id,
          fileRevision: id,
          file: f,
          displayName: f.name,
          originalFileType: f.name.split('.').pop()?.toLowerCase(),
          originalFileSize: f.size,
          sourceTimeMs,
          source: 'local_upload',
          datasetId: datasetId === '' ? null : datasetId,
        }
      })
      setFileWorkspace((prev) =>
        createFileWorkspace([...prev.files, ...added], prev.currentFileId, prev.selectedIngestFileIds),
      )
      if (currentFileItem !== null) return

      retirePreview()
      autoPreviewAttemptRef.current = null
      fileViewRevisionRef.current += 1
      setPreviewSnapshot(null)
      setError(null)
      setHoveredChunkIndex(null)
      setSelectedChunkIndex(null)
      setIngestResult(null)
    },
    [currentFileItem, datasetId, retirePreview],
  )

  const removeFile = useCallback(
    (index: number) => {
      const removed = fileList[index]
      scopeSyncControlRef.current.removedIds.add(removed.id)
      if (removed.id === currentFileItem?.id) {
        retirePreview()
        fileViewRevisionRef.current += 1
      }
      setFileWorkspace((prev) => {
        const previousIndex = prev.files.findIndex((item) => item.id === removed.id)
        const neighbor = prev.files[previousIndex - 1] ?? prev.files[previousIndex + 1]
        const currentFileId = prev.currentFileId === removed.id ? (neighbor?.id ?? null) : prev.currentFileId
        return createFileWorkspace(
          prev.files.filter((item) => item.id !== removed.id),
          currentFileId,
          prev.selectedIngestFileIds,
        )
      })
      if (removed.id === currentFileItem?.id) {
        setPreviewSnapshot(null)
        setChunkOverrides({})
        setError(null)
        setHoveredChunkIndex(null)
        setSelectedChunkIndex(null)
        setIngestResult(null)
        setLastPreviewAt(null)
        setLastPreviewDurationMs(null)
        setCacheHit(false)
      }
    },
    [currentFileItem?.id, fileList, retirePreview],
  )

  const clearFiles = useCallback(() => {
    setFileSelectionReady(true)
    retireScopeSync()
    retirePreview()
    fileViewRevisionRef.current += 1
    removeClientStorage(STORAGE_FOCUS_FILE_ID_KEY)
    setFileWorkspace(createFileWorkspace([], null, new Set()))
    setPreviewSnapshot(null)
    setChunkOverrides({})
    setError(null)
    setIngestStatusByRevision({})
    setHoveredChunkIndex(null)
    setSelectedChunkIndex(null)
    setLastPreviewAt(null)
    setLastPreviewDurationMs(null)
    setCacheHit(false)
    setRunHistory([])
    previewCacheRef.current.clear()
    setIngestResult(null)
  }, [retirePreview, retireScopeSync])

  const selectFile = useCallback(
    (index: number) => {
      setFileSelectionReady(true)
      const selected = fileList[index]
      if (selected.id === currentFileItem?.id) return
      retirePreview()
      autoPreviewAttemptRef.current = null
      fileViewRevisionRef.current += 1
      setFileWorkspace((prev) => selectWorkspaceFile(prev, selected.id))
      setPreviewSnapshot(null)
      setChunkOverrides({})
      setError(null)
      setHoveredChunkIndex(null)
      setSelectedChunkIndex(null)
      setIngestResult(null)
      setLastPreviewAt(null)
      setLastPreviewDurationMs(null)
      setCacheHit(false)
    },
    [retirePreview, currentFileItem?.id, fileList],
  )

  const toggleIngestFileSelection = useCallback((fileId: string) => {
    setFileWorkspace((prev) => {
      if (!prev.files.some((item) => item.id === fileId)) return prev
      const next = new Set(prev.selectedIngestFileIds)
      if (next.has(fileId)) next.delete(fileId)
      else next.add(fileId)
      return { ...prev, selectedIngestFileIds: next }
    })
  }, [])

  // Actions: 拖放
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault()
      setIsDragging(false)
      const viewRevision = fileViewRevisionRef.current
      const sessionRevision = getAuthSessionRevision()
      const isCurrentDrop = () =>
        mountedRef.current &&
        fileViewRevisionRef.current === viewRevision &&
        getAuthCacheScope() === workspaceAuthScope &&
        getAuthSessionRevision() === sessionRevision

      const { items, files: droppedFiles } = e.dataTransfer
      let files: File[]
      try {
        files = items.length > 0 ? await scanFiles(items) : Array.from(droppedFiles)
      } catch (error) {
        if (isCurrentDrop()) throw error
        return
      }
      if (isCurrentDrop() && files.length > 0) addFiles(files)
    },
    [addFiles, workspaceAuthScope],
  )

  // Actions: 使用示例
  const loadExample = useCallback(() => {
    retireScopeSync()
    setFileSelectionReady(true)
    retirePreview()
    fileViewRevisionRef.current += 1
    const blob = new Blob([EXAMPLE_TEXT], { type: 'text/plain' })
    const exampleFile = new File([blob], 'rag-introduction.md', { type: 'text/markdown' })
    const id = generateRequestId()
    const files: ChunkPreviewFileItem[] = [
      {
        id,
        fileRevision: id,
        file: exampleFile,
        displayName: exampleFile.name,
        originalFileType: 'md',
        originalFileSize: exampleFile.size,
        sourceTimeMs: Date.now(),
        source: 'example',
        datasetId: datasetId || null,
      },
    ]
    setFileWorkspace(createFileWorkspace(files, id, new Set()))
    setPreviewSnapshot(null)
    setChunkOverrides({})
    setError(null)
    setHoveredChunkIndex(null)
    setSelectedChunkIndex(null)
    setIngestResult(null)
  }, [datasetId, retirePreview, retireScopeSync])

  const buildChunkPreviewRequestParams = useCallback(
    (settings: ChunkPreviewRunSettings = {}) => {
      const strategy = settings.strategy ?? chunkStrategy
      const isSeparator = strategy === 'separator'
      const isParentChild = strategy === 'parent_child'
      const separator = isSeparator && separatorPreset === 'custom' ? decodeSeparatorInput(separatorCustom) : undefined

      return {
        chunk_size: settings.chunkSize ?? chunkSize,
        chunk_overlap: isSeparator ? 0 : (settings.chunkOverlap ?? chunkOverlap),
        include_original_text: includeOriginalText,
        include_review_signals: true,
        original_text_max_chars: originalTextMaxChars,
        max_chunks: maxChunks,
        use_parse_cache: useParseCache,
        parser_backend: settings.parserBackend ?? parserBackend,
        chunk_strategy: strategy,
        child_ratio: isParentChild ? parentChildRatio : undefined,
        min_child_size: isParentChild ? parentChildMinChildSize : undefined,
        dataset_id: datasetId === '' ? undefined : datasetId,
        pipeline: pipelineOverridesEnabled ? pipelineOptions : undefined,
        separator_preset: isSeparator ? separatorPreset : undefined,
        separator: separator === '' ? '\n\n' : separator,
        keep_separator: isSeparator ? keepSeparator : undefined,
        separator_max_chunk_size: isSeparator ? separatorMaxChunkSize : undefined,
      } satisfies ChunkPreviewRequestParams
    },
    [
      chunkOverlap,
      chunkSize,
      chunkStrategy,
      datasetId,
      includeOriginalText,
      keepSeparator,
      maxChunks,
      originalTextMaxChars,
      parentChildMinChildSize,
      parentChildRatio,
      parserBackend,
      pipelineOptions,
      pipelineOverridesEnabled,
      separatorCustom,
      separatorMaxChunkSize,
      separatorPreset,
      useParseCache,
    ],
  )

  const currentPreviewCacheKey =
    currentFileItem === null ? null : buildPreviewCacheKey(currentFileItem, buildChunkPreviewRequestParams())
  const previewSubmissionView = useMemo<PreviewSubmissionView>(
    () => ({ data: previewData, overrides: chunkOverrides, cacheKey: currentPreviewCacheKey }),
    [previewData, chunkOverrides, currentPreviewCacheKey],
  )
  const previewSubmissionViewRef = useRef(previewSubmissionView)
  useLayoutEffect(() => {
    previewSubmissionViewRef.current = previewSubmissionView
  }, [previewSubmissionView])
  const isCurrentIngestResult =
    ingestResult !== null && isSamePreviewSubmissionView(previewSubmissionView, ingestResult.view)
  const createdDocumentId = isCurrentIngestResult ? ingestResult.documentId : null
  const submitSuccess = isCurrentIngestResult && ingestResult.completed
  const isPreviewDirty =
    previewData !== null &&
    lastPreviewCacheKey !== null &&
    currentPreviewCacheKey !== null &&
    currentPreviewCacheKey !== lastPreviewCacheKey

  // Actions: 执行预览
  const runPreview = useCallback<ChunkPreviewContextType['runPreview']>(
    async (options) => {
      if (!file) return
      setFileSelectionReady(true)
      if (!mountedRef.current || getAuthCacheScope() !== workspaceAuthScope) return
      if (!currentFileItem || !isChunkPreviewFileInScope(currentFileItem, datasetId)) {
        setError(datasetId ? '当前数据集暂无可预览文档，请先在该数据集完成入库。' : '当前范围暂无可预览文档。')
        return
      }
      const baseParams = buildChunkPreviewRequestParams(options?.settings)
      if (baseParams.chunk_overlap >= baseParams.chunk_size) {
        setError('重叠长度必须小于切块长度')
        return
      }
      const strategyAvailable = chunkStrategyAvailable(baseParams.chunk_strategy)
      if (strategyAvailable === false) {
        setError(`当前切块策略不可用：${getChunkStrategyLabel(baseParams.chunk_strategy)}`)
        return
      }

      const cacheKey = buildPreviewCacheKey(currentFileItem, baseParams)
      autoPreviewAttemptRef.current = cacheKey
      retirePreview()
      const sessionRevision = getAuthSessionRevision()
      const cached = previewCacheRef.current.get(cacheKey)
      if (cached && !options?.force) {
        if (previewSnapshot?.data !== cached.data) {
          setChunkOverrides({})
          setHoveredChunkIndex(null)
          setSelectedChunkIndex(null)
        }
        setPreviewSnapshot({ data: cached.data, file, sessionRevision, requestId: cached.requestId })
        setLastPreviewAt(cached.createdAt)
        setLastPreviewDurationMs(cached.durationMs)
        setCacheHit(true)
        setLastPreviewCacheKey(cacheKey)
        setError(null)
        const run = {
          id: generateRequestId(),
          fileName: file.name,
          fileId: currentFileItem.id,
          parserBackend: baseParams.parser_backend,
          strategy: baseParams.chunk_strategy,
          chunkSize: baseParams.chunk_size,
          chunkOverlap: baseParams.chunk_overlap,
          totalChunks: cached.data.total_chunks,
          durationMs: cached.durationMs,
          createdAt: Date.now(),
          cacheHit: true,
          cacheKey,
        }
        setRunHistory((prev) => [run, ...prev].slice(0, 20))
        return
      }

      const requestId = previewRequestIdRef.current
      const controller = new AbortController()
      previewAbortRef.current = controller
      setIsLoading(true)
      setError(null)
      setCacheHit(false)
      const startTime = performance.now()
      const isCurrent = () =>
        mountedRef.current &&
        previewRequestIdRef.current === requestId &&
        !controller.signal.aborted &&
        getAuthCacheScope() === workspaceAuthScope &&
        getAuthSessionRevision() === sessionRevision

      try {
        // Enterprise UX: when parse cache is enabled and we have a prior file_sha256, avoid re-uploading the file.
        // If server cache miss/disabled, fall back to uploading.
        let data: ChunkPreviewResponse
        const sha = previewSnapshot?.data.file_sha256
        if (
          useParseCache &&
          sha &&
          previewSnapshot?.file === file &&
          previewSnapshot.sessionRevision === sessionRevision
        ) {
          try {
            data = await documentApi.chunkPreviewBySha(
              {
                file_sha256: sha,
                file_type: previewSnapshot.data.file_type,
                filename: file.name,
                file_size: file.size,
                ...baseParams,
              },
              { signal: controller.signal },
            )
          } catch (err: unknown) {
            if (!isCurrent()) return
            const status = getApiErrorStatus(err)
            if (status === 400 || status === 404) {
              data = await documentApi.chunkPreview(file, baseParams, { signal: controller.signal })
            } else {
              throw err
            }
          }
        } else {
          data = await documentApi.chunkPreview(file, baseParams, { signal: controller.signal })
        }
        if (!isCurrent()) return
        setChunkOverrides({})
        setHoveredChunkIndex(null)
        setSelectedChunkIndex(null)
        setPreviewSnapshot({ data, file, sessionRevision, requestId })
        const durationMs = Math.max(0, Math.round(performance.now() - startTime))
        const createdAt = Date.now()
        setLastPreviewAt(createdAt)
        setLastPreviewDurationMs(durationMs)
        previewCacheRef.current.set(cacheKey, { data, createdAt, durationMs, requestId })
        setLastPreviewCacheKey(cacheKey)
        const run = {
          id: generateRequestId(),
          fileName: file.name,
          fileId: currentFileItem.id,
          parserBackend: baseParams.parser_backend,
          strategy: baseParams.chunk_strategy,
          chunkSize: baseParams.chunk_size,
          chunkOverlap: baseParams.chunk_overlap,
          totalChunks: data.total_chunks,
          durationMs,
          createdAt,
          cacheHit: false,
          cacheKey,
        }
        setRunHistory((prev) => [run, ...prev].slice(0, 20))
      } catch (err: unknown) {
        if (!isCurrent()) return
        setError(formatApiError(err, '预览失败'))
      } finally {
        if (previewAbortRef.current === controller) {
          previewAbortRef.current = null
        }
        if (mountedRef.current && previewRequestIdRef.current === requestId) {
          setIsLoading(false)
        }
      }
    },
    [
      file,
      currentFileItem,
      chunkStrategyAvailable,
      buildChunkPreviewRequestParams,
      retirePreview,
      workspaceAuthScope,
      datasetId,
      useParseCache,
      previewSnapshot,
    ],
  )

  const cancelPreview = useCallback(() => {
    autoPreviewAttemptRef.current =
      currentFileItem === null ? null : buildPreviewCacheKey(currentFileItem, buildChunkPreviewRequestParams())
    retirePreview()
  }, [buildChunkPreviewRequestParams, currentFileItem, retirePreview])

  const getCachedPreview = useCallback((cacheKey: string) => {
    return previewCacheRef.current.get(cacheKey)?.data ?? null
  }, [])

  const buildIngestPayload = useCallback<ChunkPreviewContextType['buildIngestPayload']>(
    (data, item, overrides) => {
      if (data.chunks_truncated === true) throw new Error(COMPLETE_PREVIEW_REQUIRED_MESSAGE)
      const chunks: ManualChunk[] = []
      for (const chunk of data.chunks) {
        const override = overrides[chunk.index]
        if (override?.disabled === true) continue
        const edited = applyChunkEdits(chunk, override)
        chunks.push({
          content: edited.content,
          page_number: chunk.page_number,
          start_char: chunk.start_index,
          end_char: chunk.end_index,
          metadata: edited.metadata,
        })
      }

      if (!chunks.length) {
        throw new Error('没有可入库的切块')
      }

      const pipeline = pipelineOverridesEnabled
        ? {
            ...pipelineOptions,
            chunk_size: chunkSize,
            chunk_overlap: chunkOverlap,
          }
        : undefined

      const separatorMeta =
        data.chunk_strategy === 'separator'
          ? {
              separator_preset: separatorPreset,
              separator_custom: separatorCustom,
              keep_separator: keepSeparator,
              separator_max_chunk_size: separatorMaxChunkSize,
            }
          : {}

      const targetDatasetId = datasetId === '' ? undefined : datasetId
      return {
        filename: data.filename,
        file_type: data.file_type,
        file_size: data.file_size,
        chunks,
        dataset_id: targetDatasetId,
        metadata: {
          chunk_size: chunkSize,
          chunk_overlap: chunkOverlap,
          chunk_strategy: data.chunk_strategy,
          chunk_strategy_label: getChunkStrategyLabel(data.chunk_strategy),
          parser_backend: data.parser_backend,
          dataset_id: targetDatasetId,
          source_document_id: item.documentId,
          source: item.source,
          ...separatorMeta,
        },
        pipeline,
      }
    },
    [
      chunkOverlap,
      chunkSize,
      datasetId,
      keepSeparator,
      pipelineOptions,
      pipelineOverridesEnabled,
      separatorCustom,
      separatorMaxChunkSize,
      separatorPreset,
    ],
  )

  const captureIngestDocumentLists = useCallback(
    () =>
      queryClient
        .getQueryCache()
        .findAll({ queryKey: queryKeys.documents.list().slice(0, 2) })
        .filter((query) => {
          const params = query.queryKey[2] as Parameters<typeof documentApi.list>[0]
          return !params?.dataset_id || params.dataset_id === datasetId
        }),
    [datasetId, queryClient],
  )

  const invalidateOriginalDocumentLists = useCallback(
    (queries: Query[]) => {
      for (const query of queries) {
        if (queryClient.getQueryCache().get(query.queryHash) === query) {
          void queryClient.invalidateQueries({ queryKey: query.queryKey, exact: true })
        }
      }
    },
    [queryClient],
  )

  // Actions: 提交入库
  const submitChunks = useCallback(async () => {
    if (previewSnapshot === null || !currentFileItem) return
    if (submitSuccess) return
    if (isLoading || isPreviewDirty) {
      setError(isLoading ? '请等待预览完成后再入库。' : PREVIEW_UPDATE_REQUIRED_MESSAGE)
      return
    }
    const sessionRevision = getAuthSessionRevision()
    if (getAuthCacheScope() !== workspaceAuthScope || submissionRef.current?.sessionRevision === sessionRevision) return
    const submission = { sessionRevision }
    submissionRef.current = submission
    const { data, requestId } = previewSnapshot
    const viewRevision = fileViewRevisionRef.current
    const cacheKey = buildPreviewCacheKey(currentFileItem, buildChunkPreviewRequestParams())
    const submittedView: PreviewSubmissionView = {
      data,
      overrides: chunkOverrides,
      cacheKey,
    }
    const isSessionCurrent = () =>
      getAuthCacheScope() === workspaceAuthScope && getAuthSessionRevision() === sessionRevision
    const canRecordFile = () =>
      mountedRef.current && isSessionCurrent() && fileListRef.current.some((item) => item.id === currentFileItem.id)
    const canPublish = () =>
      canRecordFile() &&
      fileViewRevisionRef.current === viewRevision &&
      isSamePreviewSubmissionView(previewSubmissionViewRef.current, submittedView)
    const originalLists = captureIngestDocumentLists()
    const fileRevision = currentFileItem.fileRevision
    const receiptKey = ingestReceiptKey(cacheKey, datasetId, chunkOverrides)
    let receipt = ingestReceiptsRef.current.get(receiptKey)
    if (receipt?.previewRequestId !== requestId) receipt = undefined

    setIsSubmitting(true)
    setError(null)

    try {
      setIngestStatusByRevision((prev) => ({ ...prev, [fileRevision]: 'pending' }))
      if (receipt === undefined) {
        const payload = buildIngestPayload(data, currentFileItem, chunkOverrides)
        const created = await documentApi.createFromChunks(payload)
        if (!isSessionCurrent()) return
        receipt = { id: created.id, status: created.status, previewRequestId: requestId }
        ingestReceiptsRef.current.set(receiptKey, receipt)
        invalidateOriginalDocumentLists(originalLists)
      }
      if (canPublish()) setIngestResult({ view: submittedView, documentId: receipt.id, completed: false })
      if (canRecordFile()) setIngestStatusByRevision((prev) => ({ ...prev, [fileRevision]: 'processing' }))
      await waitForDocumentIngestCompletion(receipt.id, receipt.status, isSessionCurrent)
      if (!isSessionCurrent()) return
      receipt.status = 'completed'
      invalidateOriginalDocumentLists(originalLists)
      if (canRecordFile()) setIngestStatusByRevision((prev) => ({ ...prev, [fileRevision]: 'success' }))
      if (canPublish()) {
        setIngestResult({ view: submittedView, documentId: receipt.id, completed: true })
        onConfirm?.({ chunk_size: chunkSize, chunk_overlap: chunkOverlap })
        toast.success('已成功入库')
      }
    } catch (err: unknown) {
      if (receipt?.status === 'completed') {
        if (canPublish()) setError(`入库已完成，后续更新失败。${formatApiError(err, '请刷新文档列表')}`)
      } else if (err instanceof ManualIngestStillProcessingError) {
        if (canRecordFile()) setIngestStatusByRevision((prev) => ({ ...prev, [fileRevision]: 'processing' }))
        if (canPublish()) toast.info(err.message)
      } else if (receipt !== undefined && !(err instanceof ManualIngestFailedError)) {
        if (canRecordFile()) setIngestStatusByRevision((prev) => ({ ...prev, [fileRevision]: 'processing' }))
        if (canPublish()) setError(`文档已创建，入库状态未确认。${formatApiError(err, '请重新查询状态')}`)
      } else {
        if (canPublish()) setError(formatApiError(err, '入库失败'))
        if (canRecordFile()) setIngestStatusByRevision((prev) => ({ ...prev, [fileRevision]: 'error' }))
      }
    } finally {
      if (submissionRef.current === submission) {
        submissionRef.current = null
        if (mountedRef.current) setIsSubmitting(false)
      }
    }
  }, [
    previewSnapshot,
    chunkOverrides,
    currentFileItem,
    datasetId,
    isLoading,
    isPreviewDirty,
    submitSuccess,
    buildChunkPreviewRequestParams,
    buildIngestPayload,
    chunkSize,
    chunkOverlap,
    onConfirm,
    captureIngestDocumentLists,
    invalidateOriginalDocumentLists,
    workspaceAuthScope,
  ])

  const submitSelectedFiles = useCallback(async () => {
    const sessionRevision = getAuthSessionRevision()
    if (getAuthCacheScope() !== workspaceAuthScope || submissionRef.current?.sessionRevision === sessionRevision) return
    const targets = fileList.filter(
      (item) => selectedIngestFileIds.has(item.id) && isChunkPreviewFileInScope(item, datasetId),
    )
    if (!targets.length) {
      setError('请先选择要入库的文件')
      toast.error('请先选择要入库的文件')
      return
    }
    if (targets.some((target) => target.id === currentFileItem?.id) && (isLoading || isPreviewDirty)) {
      const message = isLoading ? '请等待预览完成后再入库。' : PREVIEW_UPDATE_REQUIRED_MESSAGE
      setError(message)
      toast.error(message)
      return
    }

    const params = buildChunkPreviewRequestParams()
    if (params.chunk_overlap >= params.chunk_size) {
      setError('重叠长度必须小于切块长度')
      return
    }
    const strategyAvailable = chunkStrategyAvailable(params.chunk_strategy)
    if (strategyAvailable === false) {
      setError(`当前切块策略不可用：${getChunkStrategyLabel(params.chunk_strategy)}`)
      return
    }

    const submission = { sessionRevision }
    submissionRef.current = submission
    const viewRevision = fileViewRevisionRef.current
    const submittedView: PreviewSubmissionView = {
      data: previewData,
      overrides: chunkOverrides,
      cacheKey: currentFileItem === null ? null : buildPreviewCacheKey(currentFileItem, params),
    }
    const isSessionCurrent = () =>
      getAuthCacheScope() === workspaceAuthScope && getAuthSessionRevision() === sessionRevision
    const canPublish = () =>
      mountedRef.current &&
      isSessionCurrent() &&
      fileViewRevisionRef.current === viewRevision &&
      isSamePreviewSubmissionView(previewSubmissionViewRef.current, submittedView)
    const canRecordFile = (target: ChunkPreviewFileItem) =>
      mountedRef.current && isSessionCurrent() && fileListRef.current.some((item) => item.id === target.id)

    setIsSubmitting(true)
    setError(null)

    let successCount = 0
    let failureCount = 0
    let processingCount = 0
    let lastFailure: string | null = null
    const retryIds = new Set<string>()

    for (const target of targets) {
      if (!isSessionCurrent()) break
      if (canRecordFile(target)) setIngestStatusByRevision((prev) => ({ ...prev, [target.fileRevision]: 'pending' }))
      const isActive = target.id === currentFileItem?.id
      const activePreview = isActive ? previewSnapshot : null
      const overrides = isActive ? chunkOverrides : {}
      const receiptKey = ingestReceiptKey(buildPreviewCacheKey(target, params), datasetId, overrides)
      let receipt = ingestReceiptsRef.current.get(receiptKey)
      if (activePreview !== null && receipt?.previewRequestId !== activePreview.requestId) receipt = undefined
      try {
        const originalLists = captureIngestDocumentLists()
        if (receipt === undefined) {
          const data =
            activePreview !== null
              ? activePreview.data
              : await documentApi.chunkPreview(target.file, {
                  ...params,
                  max_chunks: 0,
                  include_original_text: false,
                  include_review_signals: false,
                })
          if (!isSessionCurrent()) break
          const payload = buildIngestPayload(data, target, overrides)
          const created = await documentApi.createFromChunks(payload)
          if (!isSessionCurrent()) break
          receipt = { id: created.id, status: created.status, previewRequestId: activePreview?.requestId ?? null }
          ingestReceiptsRef.current.set(receiptKey, receipt)
          invalidateOriginalDocumentLists(originalLists)
        }
        if (isActive && canPublish() && canRecordFile(target)) {
          setIngestResult({ view: submittedView, documentId: receipt.id, completed: false })
        }
        if (canRecordFile(target))
          setIngestStatusByRevision((prev) => ({ ...prev, [target.fileRevision]: 'processing' }))
        await waitForDocumentIngestCompletion(receipt.id, receipt.status, isSessionCurrent)
        if (!isSessionCurrent()) break
        receipt.status = 'completed'
        invalidateOriginalDocumentLists(originalLists)
        successCount += 1
        if (isActive && canPublish() && canRecordFile(target)) {
          setIngestResult({ view: submittedView, documentId: receipt.id, completed: true })
        }
        if (canRecordFile(target)) setIngestStatusByRevision((prev) => ({ ...prev, [target.fileRevision]: 'success' }))
      } catch (err: unknown) {
        retryIds.add(target.id)
        if (
          err instanceof ManualIngestStillProcessingError ||
          (receipt !== undefined && !(err instanceof ManualIngestFailedError))
        ) {
          processingCount += 1
          if (!(err instanceof ManualIngestStillProcessingError)) {
            lastFailure = `文档已创建，入库状态未确认。${formatApiError(err, '请重新查询状态')}`
          }
          if (canRecordFile(target))
            setIngestStatusByRevision((prev) => ({ ...prev, [target.fileRevision]: 'processing' }))
          continue
        }
        failureCount += 1
        lastFailure = formatApiError(err, '入库失败')
        if (canRecordFile(target)) setIngestStatusByRevision((prev) => ({ ...prev, [target.fileRevision]: 'error' }))
      }
    }

    if (mountedRef.current && isSessionCurrent())
      setFileWorkspace((prev) => {
        const next = new Set(prev.selectedIngestFileIds)
        for (const target of targets) {
          const currentTarget = prev.files.find((item) => item.id === target.id)
          if (!retryIds.has(target.id) && currentTarget?.fileRevision === target.fileRevision) next.delete(target.id)
        }
        return { ...prev, selectedIngestFileIds: next }
      })

    if (canPublish()) {
      if (lastFailure !== null) {
        setError(lastFailure)
        toast.error(`已入库 ${successCount} 个，处理中 ${processingCount} 个，失败 ${failureCount} 个`)
      } else if (processingCount > 0) {
        toast.info(`已提交 ${processingCount} 个文件，后端仍在处理`)
      } else {
        toast.success(`已批量入库 ${successCount} 个文件`)
      }
    }
    if (submissionRef.current === submission) {
      submissionRef.current = null
      if (mountedRef.current) setIsSubmitting(false)
    }
  }, [
    buildChunkPreviewRequestParams,
    chunkOverrides,
    chunkStrategyAvailable,
    buildIngestPayload,
    currentFileItem,
    datasetId,
    fileList,
    previewData,
    previewSnapshot,
    isLoading,
    isPreviewDirty,
    selectedIngestFileIds,
    captureIngestDocumentLists,
    invalidateOriginalDocumentLists,
    workspaceAuthScope,
  ])

  // Actions: 更新配置
  const updateChunkOverride = useCallback((index: number, override: ChunkOverride) => {
    const updatedAt = Date.now()
    setChunkOverrides((prev) => {
      const next = { ...prev }
      next[index] = { ...prev[index], ...override, updatedAt }
      return next
    })
  }, [])

  const toggleChunkDisabled = useCallback((index: number) => {
    const updatedAt = Date.now()
    setChunkOverrides((prev) => {
      const next = { ...prev }
      const cur = prev[index]
      if (cur?.disabled !== true) {
        next[index] = { ...cur, disabled: true, updatedAt }
        return next
      }

      const { disabled: _omit, ...rest } = cur
      const hasOther = rest.content !== undefined || rest.metadata !== undefined
      if (!hasOther) {
        delete next[index]
        return next
      }

      next[index] = { ...rest, updatedAt }
      return next
    })
  }, [])

  const setChunksDisabled = useCallback((indices: number[], disabled: boolean) => {
    const list = Array.from(new Set(indices))
    if (list.length === 0) return
    const now = Date.now()

    setChunkOverrides((prev) => {
      const next = { ...prev }
      let changed = false

      for (const idx of list) {
        const cur = prev[idx]
        const curDisabled = cur?.disabled === true

        if (disabled) {
          if (curDisabled) continue
          next[idx] = { ...cur, disabled: true, updatedAt: now }
          changed = true
          continue
        }

        if (!curDisabled) continue
        const { disabled: _omit, ...rest } = cur
        const hasOther = rest.content !== undefined || rest.metadata !== undefined
        if (hasOther) {
          next[idx] = { ...rest, updatedAt: now }
        } else {
          delete next[idx]
        }
        changed = true
      }

      return changed ? next : prev
    })
  }, [])

  const clearChunkOverride = useCallback((index: number) => {
    setChunkOverrides((prev) => {
      if (!Object.hasOwn(prev, index)) return prev
      const next = { ...prev }
      delete next[index]
      return next
    })
  }, [])

  const clearAllChunkOverrides = useCallback(() => {
    setChunkOverrides({})
  }, [])

  const updateSettings = useCallback(
    (settings: Partial<Pick<ChunkPreviewState, 'chunkSize' | 'chunkOverlap' | 'strategy'>>) => {
      const nextStrategy = settings.strategy ?? chunkStrategy

      if (settings.chunkSize !== undefined) {
        setChunkSize(settings.chunkSize)
        updateOption('chunk_size', settings.chunkSize)
      }
      if (settings.chunkOverlap !== undefined) {
        const nextOverlap = nextStrategy === 'separator' ? 0 : settings.chunkOverlap
        setChunkOverlap(nextOverlap)
        updateOption('chunk_overlap', nextOverlap)
      }
      if (settings.strategy !== undefined) {
        setChunkStrategy(settings.strategy)
        if (settings.strategy === 'separator') {
          // separator does not use overlap; keep state consistent so validation/API stay clean.
          setChunkOverlap(0)
          updateOption('chunk_overlap', 0)
        }
      }
    },
    [chunkStrategy, updateOption, setChunkStrategy],
  )

  const updatePerfSettings = useCallback(
    (
      settings: Partial<
        Pick<ChunkPreviewState, 'includeOriginalText' | 'originalTextMaxChars' | 'maxChunks' | 'useParseCache'>
      >,
    ) => {
      if (settings.includeOriginalText !== undefined) setIncludeOriginalText(settings.includeOriginalText)
      if (settings.originalTextMaxChars !== undefined) {
        const maxCharacters = settings.originalTextMaxChars
        if (Number.isFinite(maxCharacters))
          setOriginalTextMaxChars(Math.max(0, Math.min(2_000_000, Math.trunc(maxCharacters))))
      }
      if (settings.maxChunks !== undefined) {
        const maxChunks = settings.maxChunks
        if (Number.isFinite(maxChunks)) setMaxChunks(Math.max(0, Math.min(20000, Math.trunc(maxChunks))))
      }
      if (settings.useParseCache !== undefined) setUseParseCache(settings.useParseCache)
    },
    [],
  )

  const updateSeparatorSettings = useCallback(
    (
      settings: Partial<
        Pick<ChunkPreviewState, 'separatorPreset' | 'separatorCustom' | 'keepSeparator' | 'separatorMaxChunkSize'>
      >,
    ) => {
      if (settings.separatorPreset !== undefined) setSeparatorPreset(settings.separatorPreset)
      if (settings.separatorCustom !== undefined) setSeparatorCustom(settings.separatorCustom)
      if (settings.keepSeparator !== undefined) setKeepSeparator(settings.keepSeparator)
      if (settings.separatorMaxChunkSize !== undefined) setSeparatorMaxChunkSize(settings.separatorMaxChunkSize)
    },
    [],
  )

  // Actions: 重置
  const updateParentChildSettings = useCallback(
    (settings: Partial<Pick<ChunkPreviewState, 'parentChildRatio' | 'parentChildMinChildSize'>>) => {
      if (settings.parentChildRatio !== undefined) {
        const ratio = settings.parentChildRatio
        if (Number.isFinite(ratio)) setParentChildRatio(Math.max(0.05, Math.min(1, ratio)))
      }
      if (settings.parentChildMinChildSize !== undefined) {
        const minimumSize = settings.parentChildMinChildSize
        if (Number.isFinite(minimumSize))
          setParentChildMinChildSize(Math.max(50, Math.min(4000, Math.trunc(minimumSize))))
      }
    },
    [],
  )

  const reset = useCallback(() => {
    clearFiles()
    setChunkSize(1000)
    setChunkOverlap(200)
    setIncludeOriginalText(true)
    setOriginalTextMaxChars(100000)
    setMaxChunks(2000)
    setUseParseCache(true)
    updateOption('chunk_size', 1000)
    updateOption('chunk_overlap', 200)
    setIngestResult(null)
    setShowOriginalPanel(true)
    setShowSettingsPanel(false)
    setSeparatorPreset('paragraph')
    setSeparatorCustom(String.raw`\n\n`)
    setKeepSeparator(true)
    setSeparatorMaxChunkSize(0)
    setParentChildRatio(0.5)
    setParentChildMinChildSize(200)
  }, [clearFiles, updateOption])

  // 自动触发预览
  useEffect(() => {
    const fileInScope = currentFileItem ? isChunkPreviewFileInScope(currentFileItem, datasetId) : false
    if (
      autoPreviewEnabled &&
      file &&
      fileInScope &&
      fileSelectionReady &&
      !previewData &&
      !isLoading &&
      !isSubmitting &&
      !error &&
      autoPreviewAttemptRef.current !== currentPreviewCacheKey
    ) {
      runPreview()
    }
  }, [
    autoPreviewEnabled,
    currentFileItem,
    datasetId,
    file,
    fileSelectionReady,
    previewData,
    isLoading,
    isSubmitting,
    error,
    runPreview,
    currentPreviewCacheKey,
  ])

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if (event.defaultPrevented) return
      const isCmdOrCtrl = event.metaKey || event.ctrlKey
      if (!isCmdOrCtrl) return
      const key = event.key.toLowerCase()
      if (key !== 'enter' && key !== 's') return
      event.preventDefault()
      if (event.target instanceof Element && event.target.closest('[role="dialog"]') !== null) return
      if (key === 'enter') {
        runPreview({ force: true })
      } else {
        submitChunks()
      }
    }
    globalThis.window.addEventListener('keydown', handleKeyDown)
    return () => globalThis.window.removeEventListener('keydown', handleKeyDown)
  }, [runPreview, submitChunks])

  const toggleAutoPreview = useCallback((enabled?: boolean) => {
    autoPreviewAttemptRef.current = null
    setAutoPreviewEnabled((prev) => (typeof enabled === 'boolean' ? enabled : !prev))
  }, [])

  const clearRunHistory = useCallback(() => {
    setRunHistory([])
  }, [])

  const toggleOriginalPanel = useCallback(() => {
    setShowOriginalPanel((prev) => !prev)
  }, [])

  const setOriginalPanelVisible = useCallback((visible: boolean) => {
    setShowOriginalPanel(visible)
  }, [])

  const toggleSettingsPanel = useCallback(() => {
    setShowSettingsPanel((prev) => !prev)
  }, [])

  const focusGapReview = useCallback(() => {
    setGapReviewRequest((request) => request + 1)
    setShowSettingsPanel(false)
    setShowOriginalPanel(true)
  }, [])

  const selectDatasetId = useCallback(
    (value: string) => {
      const nextDatasetId = value.trim()
      if (nextDatasetId === datasetId) return
      setFileSelectionReady(true)
      retirePreview()
      fileViewRevisionRef.current += 1
      setDatasetId(nextDatasetId)
      setPreviewSnapshot(null)
      setChunkOverrides({})
      setFileWorkspace((prev) => ({ ...prev, selectedIngestFileIds: new Set() }))
      setError(null)
      setHoveredChunkIndex(null)
      setSelectedChunkIndex(null)
      setIngestResult(null)
      const params = new URLSearchParams(searchParams.toString())
      if (nextDatasetId.length > 0) params.set('dataset_id', nextDatasetId)
      else params.delete('dataset_id')
      params.delete('chunk')
      chunkParamNavigationRef.current = { from: chunkParam ?? chunkParamNavigationRef.current?.to ?? null, to: null }
      router.replace(buildChunkPreviewHref(params))
    },
    [chunkParam, router, searchParams, retirePreview, datasetId],
  )

  // 组装 Context Value
  const value = useMemo<ChunkPreviewContextType>(
    () => ({
      // State
      fileList,
      currentFileIndex,
      isDragging,
      datasetId,
      scopeSyncLoading,
      scopeSyncError,
      isLoading,
      isSubmitting,
      showOriginalPanel,
      showSettingsPanel,
      gapReviewRequest,
      error,
      createdDocumentId,
      previewData,
      previewSourceFile,
      chunkOverrides,
      hoveredChunkIndex,
      selectedChunkIndex,
      chunkSize,
      chunkOverlap,
      includeOriginalText,
      originalTextMaxChars,
      maxChunks,
      useParseCache,
      strategy: chunkStrategy,
      separatorPreset,
      separatorCustom,
      keepSeparator,
      separatorMaxChunkSize,
      parentChildRatio,
      parentChildMinChildSize,
      lastPreviewAt,
      lastPreviewDurationMs,
      cacheHit,
      isPreviewDirty,
      autoPreviewEnabled,
      runHistory,

      // Derived
      currentFile: file,
      currentFileItem,
      submitSuccess,
      processedStatus,
      selectedIngestFileIds,

      // Actions
      addFiles,
      removeFile,
      clearFiles,
      setCurrentFileIndex: selectFile,
      setDatasetId: selectDatasetId,
      reloadScopeDocuments,
      setIsDragging,
      setHoveredChunkIndex,
      setSelectedChunkIndex,
      updateChunkOverride,
      toggleChunkDisabled,
      setChunksDisabled,
      toggleIngestFileSelection,
      clearChunkOverride,
      clearAllChunkOverrides,
      toggleOriginalPanel,
      setOriginalPanelVisible,
      toggleSettingsPanel,
      focusGapReview,
      buildChunkPreviewRequestParams,
      buildIngestPayload,
      runPreview,
      cancelPreview,
      submitChunks,
      submitSelectedFiles,
      updateSettings,
      updatePerfSettings,
      updateSeparatorSettings,
      updateParentChildSettings,
      reset,
      toggleAutoPreview,
      clearRunHistory,
      getCachedPreview,
      loadExample,
      handleDragOver,
      handleDragLeave,
      handleDrop,

      // External context
      parserBackend,
      setParserBackend,
      chunkStrategy,
      setChunkStrategy,
      onClose,
    }),
    [
      addFiles,
      autoPreviewEnabled,
      cacheHit,
      cancelPreview,
      chunkOverrides,
      chunkOverlap,
      chunkSize,
      chunkStrategy,
      clearAllChunkOverrides,
      clearChunkOverride,
      clearFiles,
      clearRunHistory,
      createdDocumentId,
      currentFileIndex,
      currentFileItem,
      datasetId,
      error,
      file,
      fileList,
      focusGapReview,
      gapReviewRequest,
      getCachedPreview,
      handleDragLeave,
      handleDragOver,
      handleDrop,
      hoveredChunkIndex,
      includeOriginalText,
      isDragging,
      isLoading,
      isPreviewDirty,
      isSubmitting,
      keepSeparator,
      lastPreviewAt,
      lastPreviewDurationMs,
      loadExample,
      maxChunks,
      onClose,
      originalTextMaxChars,
      parentChildMinChildSize,
      parentChildRatio,
      parserBackend,
      previewData,
      previewSourceFile,
      processedStatus,
      removeFile,
      reloadScopeDocuments,
      reset,
      runHistory,
      buildChunkPreviewRequestParams,
      buildIngestPayload,
      runPreview,
      scopeSyncError,
      scopeSyncLoading,
      selectDatasetId,
      selectFile,
      selectedChunkIndex,
      selectedIngestFileIds,
      separatorCustom,
      separatorMaxChunkSize,
      separatorPreset,
      setChunkStrategy,
      setChunksDisabled,
      setHoveredChunkIndex,
      setIsDragging,
      setOriginalPanelVisible,
      setParserBackend,
      setSelectedChunkIndex,
      showOriginalPanel,
      showSettingsPanel,
      submitChunks,
      submitSelectedFiles,
      submitSuccess,
      toggleAutoPreview,
      toggleChunkDisabled,
      toggleIngestFileSelection,
      toggleOriginalPanel,
      toggleSettingsPanel,
      updateChunkOverride,
      updateParentChildSettings,
      updatePerfSettings,
      updateSeparatorSettings,
      updateSettings,
      useParseCache,
    ],
  )

  return <ChunkPreviewContext.Provider value={value}>{children}</ChunkPreviewContext.Provider>
}
