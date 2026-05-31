/**
 * 鏁版嵁娌荤悊宸ヤ綔鍙扮粍浠?
 * 鍔熻兘锛氳川閲忔娴嬨€佹櫤鑳芥竻娲椼€佹暟鎹爣娉ㄣ€佸垎绫诲綊妗?
 */
'use client'

import { useState, useCallback, useMemo, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  ShieldCheck,
  Sparkles,
  Tag,
  FolderTree,
  FileText,
  Upload,
  Save,
  RotateCcw,
  Trash2,
  Eye,
  Search,
  Wrench,
  ScanLine,
  FileSearch,
  Hash,
  Layers,
  X,
  Info,
  AlertTriangle,
  Copy,
  Check,
  PanelRightOpen,
  PanelRightClose,
} from 'lucide-react'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { PipelineRail, WorkbenchScaffold } from '@/components/workbench'
import { useSearchParams } from 'next/navigation'
import { toast } from 'sonner'
import { useRouter } from '@/i18n/navigation'
import {
  ROOT_FOLDER_ID,
  useParsedFiles,
  type ParsedFileData,
} from '@/store/use-parsed-files-store'
import { cn, formatFileSize, detachPromise } from '@/lib/utils'
import { getDocContentFromCache } from '@/lib/doc-content-cache'
import { QualityChecker } from '@/components/data-governance/quality-checker'
import { DataCleaner } from '@/components/data-governance/data-cleaner'
import { DataAnnotator } from '@/components/data-governance/data-annotator'
import { DataClassifier } from '@/components/data-governance/data-classifier'
import { datasetApi, documentApi, parsingApi } from '@/lib/api'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { MarkdownRenderer } from '@/components/markdown/markdown-renderer'

import {
  DocumentFolderTree,
  getFileIcon,
} from '@/components/document-library/folder-tree'
import { extractZipFiles, isZipFile } from '@/lib/zip'
import {
  UPLOAD_ACCEPT_WITH_ZIP,
  ZIP_ALLOWED_EXTENSIONS,
} from '@/lib/upload-extensions'
import { getParserLabel } from '@/lib/parser-options'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'

const GOVERNANCE_TAB_CONFIGS = [
  { id: 'quality', icon: ScanLine, color: 'info' },
  { id: 'clean', icon: Wrench, color: 'teal' },
  { id: 'annotate', icon: Tag, color: 'accent' },
  { id: 'classify', icon: FolderTree, color: 'orange' },
] as const

type GovernanceTab = (typeof GOVERNANCE_TAB_CONFIGS)[number]['id']
type GovernanceTabColor = (typeof GOVERNANCE_TAB_CONFIGS)[number]['color']

// Tailwind needs literal class strings — keep this map close to the consts.
const TAB_COLOR_CLASSES: Record<
  GovernanceTabColor,
  {
    active: string
    icon: string
    ring: string
    ringStatic: string
    dot: string
  }
> = {
  info: {
    active: 'bg-info/10 text-info ring-info/25',
    icon: 'text-info',
    ring: 'focus-visible:ring-info/30',
    ringStatic: 'ring-info/25',
    dot: 'bg-info',
  },
  teal: {
    active: 'bg-teal/10 text-teal ring-teal/25',
    icon: 'text-teal',
    ring: 'focus-visible:ring-teal/30',
    ringStatic: 'ring-teal/25',
    dot: 'bg-teal',
  },
  accent: {
    active: 'bg-accent/10 text-accent ring-accent/25',
    icon: 'text-accent',
    ring: 'focus-visible:ring-accent/30',
    ringStatic: 'ring-accent/25',
    dot: 'bg-accent',
  },
  orange: {
    active: 'bg-orange/10 text-orange ring-orange/25',
    icon: 'text-orange',
    ring: 'focus-visible:ring-orange/30',
    ringStatic: 'ring-orange/25',
    dot: 'bg-orange',
  },
}
type DatasetOption = {
  id: string
  name: string
}

type GovernanceDocument = Awaited<
  ReturnType<typeof documentApi.list>
>['items'][number]
type GovernanceParsingDocument = Awaited<
  ReturnType<typeof parsingApi.listDocuments>
>['items'][number]

const ALL_DATASETS_VALUE = '__all_datasets__'
const EMPTY_UPLOAD_FORMATS = ['PDF', 'Word', 'Excel', 'TXT', 'MD', 'ZIP'] as const
const EMPTY_UPLOAD_STEPS = ['parse', 'quality', 'clean'] as const

type DataGovernanceTranslator = ReturnType<typeof useTranslations>

function EmptyStructurePreview({
  t,
}: Readonly<{ t: DataGovernanceTranslator }>) {
  const previewNodes = [
    {
      label: t('emptyUpload.structureNodes.root'),
      value: '0',
      tone: 'primary',
    },
    {
      label: t('emptyUpload.structureNodes.sections'),
      value: '—',
      tone: 'info',
    },
    {
      label: t('emptyUpload.structureNodes.signals'),
      value: '—',
      tone: 'success',
    },
  ] as const

  return (
    <div
      data-governance-empty-structure-rail="true"
      className="relative border-l border-border/70 pl-4"
    >
      <div className="flex items-center justify-between gap-3">
        <div>
          <div className="text-[10px] font-semibold uppercase tracking-[0.22em] text-primary/75">
            {t('emptyUpload.structureTitle')}
          </div>
          <div className="mt-1 text-sm font-semibold tracking-[-0.01em] text-foreground">
            {t('emptyUpload.structureEmptyTitle')}
          </div>
        </div>
        <div className="grid size-9 place-items-center rounded-xl bg-primary/10 text-primary">
          <FolderTree className="size-4" />
        </div>
      </div>

      <p className="mt-2 text-xs leading-5 text-muted-foreground">
        {t('emptyUpload.structureEmptyDescription')}
      </p>

      <div className="mt-4 divide-y divide-border/50">
        {previewNodes.map((node, index) => (
          <div
            key={node.label}
            className="grid grid-cols-[2rem_minmax(0,1fr)_3.5rem] items-center gap-3 py-2.5"
          >
            <span
              aria-hidden
              className={cn(
                'text-[11px] font-semibold tabular-nums',
                node.tone === 'primary' && 'text-primary',
                node.tone === 'info' && 'text-info',
                node.tone === 'success' && 'text-success'
              )}
            >
              {node.value}
            </span>
            <span className="min-w-0 text-xs font-medium text-foreground/86">
              {node.label}
            </span>
            <span
              aria-hidden
              className={cn(
                'h-1.5 justify-self-end rounded-full',
                index === 0 && 'w-14 bg-primary/28',
                index === 1 && 'w-10 bg-info/22',
                index === 2 && 'w-8 bg-success/22'
              )}
            />
          </div>
        ))}
      </div>
    </div>
  )
}

function normalizeBackendCandidate(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}

function mapBackendStatusToGovernanceStatus(
  status: unknown
): ParsedFileData['status'] {
  const normalized = typeof status === 'string' ? status.toLowerCase() : ''
  if (
    ['completed', 'complete', 'ready', 'parsed', 'done', 'success'].includes(
      normalized
    )
  )
    return 'parsed'
  if (['processing', 'parsing', 'running'].includes(normalized))
    return 'parsing'
  if (['failed', 'failure', 'error'].includes(normalized)) return 'error'
  if (['pending', 'queued', 'waiting'].includes(normalized)) return 'pending'
  return 'parsed'
}

function isParsingWorkspaceDocument(doc: GovernanceDocument): boolean {
  const meta = doc.metadata
  return meta?.workspace === 'parsing'
}

function mapKnowledgeDocumentToGovernanceFile(
  doc: GovernanceDocument,
  datasetNameById: Map<string, string>
): ParsedFileData {
  const meta = doc.metadata
  const backendCandidate =
    normalizeBackendCandidate(meta?.parser_backend) ||
    normalizeBackendCandidate(meta?.parser_backend_requested) ||
    'auto'
  const resolved = resolveParserBackendForFilename(
    doc.filename || 'document',
    backendCandidate
  )
  const backend = resolved.backend || backendCandidate
  const datasetId = doc.dataset_id || null

  return {
    id: String(doc.id || '').trim(),
    filename: doc.filename || 'document',
    fileType: doc.file_type || '',
    fileSize: Number(doc.file_size || 0),
    markdownContent: '',
    originalMarkdownContent: '',
    parsedAt: String(
      doc.updated_at || doc.created_at || new Date().toISOString()
    ),
    parser: getParserLabel(backend),
    parserBackend: backend,
    folderId: ROOT_FOLDER_ID,
    datasetId,
    datasetName: datasetId ? datasetNameById.get(datasetId) || datasetId : null,
    source: 'knowledge_base',
    sourcePath: typeof meta?.source_path === 'string' ? meta.source_path : null,
    status: mapBackendStatusToGovernanceStatus(doc.status),
    error: doc.error_message || undefined,
  }
}

function mapParsingDocumentToGovernanceFile(
  doc: GovernanceParsingDocument
): ParsedFileData {
  const meta = doc.metadata
  const backendCandidate =
    normalizeBackendCandidate(meta?.parser_backend) ||
    normalizeBackendCandidate(meta?.parser_backend_requested) ||
    'auto'
  const resolved = resolveParserBackendForFilename(
    doc.filename || 'document',
    backendCandidate
  )
  const backend = resolved.backend || backendCandidate

  return {
    id: String(doc.id || '').trim(),
    filename: doc.filename || 'document',
    fileType: doc.file_type || '',
    fileSize: Number(doc.file_size || 0),
    markdownContent: '',
    originalMarkdownContent: '',
    parsedAt: String(
      doc.updated_at || doc.created_at || new Date().toISOString()
    ),
    parser: getParserLabel(backend),
    parserBackend: backend,
    folderId: ROOT_FOLDER_ID,
    datasetId: doc.dataset_id || null,
    datasetName: null,
    source: 'parsing_workspace',
    status: mapBackendStatusToGovernanceStatus(doc.status),
    error: doc.error_message || undefined,
  }
}

// 鏂囦欢娌荤悊鐘舵€?
interface FileGovernanceState {
  id: string
  originalContent: string
  cleanedContent: string
  annotations: Array<{
    id: string
    text: string
    type: 'entity' | 'keyword' | 'sensitive' | 'custom'
    label: string
    start: number
    end: number
  }>
  tags: string[]
  category: string | null
  qualityScore: number
  issues: Array<{
    id: string
    type: 'error' | 'warning' | 'info'
    message: string
    position?: { start: number; end: number }
  }>
  isModified: boolean
}

export function DataGovernancePanel() {
  const t = useTranslations('DataGovernancePanel')
  const router = useRouter()
  const searchParams = useSearchParams()
  const files = useParsedFiles((state) => state.files)
  const libraryFolders = useParsedFiles((state) => state.folders)
  const activeFolderId = useParsedFiles((state) => state.activeFolderId)
  const setActiveFolderId = useParsedFiles((state) => state.setActiveFolderId)
  const createFolder = useParsedFiles((state) => state.createFolder)
  const isLoaded = useParsedFiles((state) => state.isLoaded)
  const addParsedFile = useParsedFiles((state) => state.addParsedFile)
  const setParsedFiles = useParsedFiles((state) => state.setParsedFiles)
  const updateParsedFile = useParsedFiles((state) => state.updateParsedFile)
  const removeFile = useParsedFiles((state) => state.removeFile)
  const { parserBackend } = useParserBackendPreference()

  // UI 鐘舵€?
  const [activeTab, setActiveTab] = useState<GovernanceTab>('quality')
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<'edit' | 'preview' | 'original'>(
    'preview'
  )
  const [previewFormat, setPreviewFormat] = useState<'rendered' | 'markdown'>(
    'rendered'
  )
  const [isDragging, setIsDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [deleteFileOpen, setDeleteFileOpen] = useState(false)
  const [deleteFileTarget, setDeleteFileTarget] = useState<{
    id: string
    filename: string
  } | null>(null)
  const [selectedDatasetId, setSelectedDatasetId] = useState<string | null>(
    () => {
      const fromUrl = (searchParams.get('dataset_id') || '').trim()
      return fromUrl || null
    }
  )
  const uploadAbortRef = useRef<AbortController | null>(null)
  const headerTitle = t('header.title')
  const headerSubtitle = t('header.subtitle')
  const governanceTabs = useMemo(
    () =>
      GOVERNANCE_TAB_CONFIGS.map(({ id, icon, color }) => ({
        id,
        icon,
        color,
        label: t(`tabs.${id}.label`),
        desc: t(`tabs.${id}.description`),
      })),
    [t]
  )

  useEffect(() => {
    return () => {
      uploadAbortRef.current?.abort()
    }
  }, [])

  // Optional deep link from /chunk-preview (best-effort, non-breaking).
  useEffect(() => {
    const raw = (searchParams.get('tab') || '').trim()
    if (!raw) return
    if (governanceTabs.some((tab) => tab.id === raw)) {
      setActiveTab(raw as GovernanceTab)
    }
  }, [governanceTabs, searchParams])

  const inboundDatasetId = useMemo(() => {
    const datasetId = (searchParams.get('dataset_id') || '').trim()
    return datasetId || null
  }, [searchParams])

  useEffect(() => {
    setSelectedDatasetId(inboundDatasetId)
    setActiveFolderId(ROOT_FOLDER_ID)
    setSelectedFileId(null)
  }, [inboundDatasetId, setActiveFolderId])

  const datasetsQuery = useQuery({
    queryKey: ['data-governance', 'datasets'],
    enabled: isLoaded,
    queryFn: async (): Promise<DatasetOption[]> => {
      const response = await datasetApi.list({ skip: 0, limit: 200 })
      return (response.items || []).map((dataset) => ({
        id: String(dataset.id),
        name: dataset.name || String(dataset.id),
      }))
    },
  })

  const availableDatasets = useMemo(
    () => datasetsQuery.data || [],
    [datasetsQuery.data]
  )
  const datasetNameById = useMemo(
    () =>
      new Map(availableDatasets.map((dataset) => [dataset.id, dataset.name])),
    [availableDatasets]
  )
  const datasetNameSignature = useMemo(
    () =>
      availableDatasets
        .map((dataset) => `${dataset.id}:${dataset.name}`)
        .join('|'),
    [availableDatasets]
  )
  const selectedDatasetName = selectedDatasetId
    ? datasetNameById.get(selectedDatasetId) || selectedDatasetId
    : null
  const activeFolderLabel = useMemo(() => {
    if (!activeFolderId || activeFolderId === ROOT_FOLDER_ID)
      return t('sidebar.allFolders')
    return (
      libraryFolders.find((folder) => folder.id === activeFolderId)?.name ||
      t('sidebar.rootFolder')
    )
  }, [activeFolderId, libraryFolders, t])

  const documentSyncQuery = useQuery({
    queryKey: [
      'data-governance',
      'library-documents',
      datasetNameSignature,
      selectedDatasetId,
    ],
    enabled: isLoaded,
    queryFn: async (): Promise<ParsedFileData[]> => {
      const [parsingResult, knowledgeResult] = await Promise.allSettled([
        parsingApi.listDocuments({ skip: 0, limit: 200 }),
        documentApi.list({
          skip: 0,
          limit: 200,
          dataset_id: selectedDatasetId,
        }),
      ])

      if (parsingResult.status === 'rejected') {
        console.warn(
          'Failed to sync parsing documents for governance:',
          parsingResult.reason
        )
      }
      if (knowledgeResult.status === 'rejected') {
        console.warn(
          'Failed to sync knowledge documents for governance:',
          knowledgeResult.reason
        )
      }

      const parsingItems =
        parsingResult.status === 'fulfilled'
          ? parsingResult.value.items || []
          : []
      const knowledgeItems =
        knowledgeResult.status === 'fulfilled'
          ? knowledgeResult.value.items || []
          : []
      return [
        ...parsingItems.map(mapParsingDocumentToGovernanceFile),
        ...knowledgeItems
          .filter((doc) => !isParsingWorkspaceDocument(doc))
          .map((doc) =>
            mapKnowledgeDocumentToGovernanceFile(doc, datasetNameById)
          ),
      ].filter((file) => file.id)
    },
  })

  useEffect(() => {
    if (!isLoaded || !documentSyncQuery.data) return

    const remoteById = new Map(
      documentSyncQuery.data.map((file) => [file.id, file])
    )
    const currentFiles = useParsedFiles.getState().files || []
    const merged = currentFiles.map((file) => {
      const remote = remoteById.get(file.id)
      if (!remote) return file
      remoteById.delete(file.id)
      return {
        ...remote,
        markdownContent: file.markdownContent || remote.markdownContent,
        originalMarkdownContent:
          file.originalMarkdownContent || remote.originalMarkdownContent,
        folderId: file.folderId || remote.folderId || ROOT_FOLDER_ID,
        governanceStatus: file.governanceStatus || remote.governanceStatus,
        chunkStatus: file.chunkStatus || remote.chunkStatus,
      }
    })

    setParsedFiles([...merged, ...remoteById.values()])
  }, [documentSyncQuery.data, isLoaded, setParsedFiles])

  const handleDatasetScopeChange = useCallback(
    (value: string) => {
      const nextDatasetId = value === ALL_DATASETS_VALUE ? null : value
      setSelectedDatasetId(nextDatasetId)
      setSelectedFileId(null)
      setActiveFolderId(ROOT_FOLDER_ID)

      const params = new URLSearchParams(searchParams.toString())
      if (nextDatasetId) params.set('dataset_id', nextDatasetId)
      else params.delete('dataset_id')
      const query = params.toString()
      router.replace(query ? `/data-governance?${query}` : '/data-governance')
    },
    [router, searchParams, setActiveFolderId]
  )

  const cancelUploadAndParse = useCallback(() => {
    uploadAbortRef.current?.abort()
    uploadAbortRef.current = null
    setUploading(false)
    toast.info(t('toasts.uploadCancelled'))
  }, [t])

  // 鏂囦欢娌荤悊鐘舵€?
  const [governanceStates, setGovernanceStates] = useState<
    Record<string, FileGovernanceState>
  >({})
  const [selectedChunkFileIds, setSelectedChunkFileIds] = useState<Set<string>>(
    () => new Set()
  )

  // 渚ц竟鏍忕姸鎬?
  const [sidebarWidth, setSidebarWidth] = useState(280)
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false)
  const [isResizing, setIsResizing] = useState(false)
  const sidebarRef = useRef<HTMLDivElement>(null)

  // 娌荤悊闈㈡澘鐘舵€?(鍙充晶)
  const [panelWidth, setPanelWidth] = useState(400)
  const [isPanelCollapsed, setIsPanelCollapsed] = useState(false)
  const [isPanelResizing, setIsPanelResizing] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)
  const contentScrollRef = useRef<HTMLDivElement>(null)

  // When switching the selected file, reset the main preview pane so it doesn't look"half scrolled".
  useEffect(() => {
    if (!selectedFileId) return
    const raf = globalThis.window.requestAnimationFrame(() => {
      contentScrollRef.current?.scrollTo({ top: 0, left: 0, behavior: 'auto' })
    })
    return () => globalThis.window.cancelAnimationFrame(raf)
  }, [selectedFileId])

  const startResizing = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setIsResizing(true)
  }, [])

  const startPanelResizing = useCallback((e: React.MouseEvent) => {
    e.preventDefault()
    setIsPanelResizing(true)
  }, [])

  const stopResizing = useCallback(() => {
    setIsResizing(false)
    setIsPanelResizing(false)
  }, [])

  const resize = useCallback(
    (mouseMoveEvent: MouseEvent) => {
      if (isResizing && sidebarRef.current) {
        // 璁＄畻鐩稿浜庤鍙ｇ殑浣嶇疆
        const sidebarLeft = sidebarRef.current.getBoundingClientRect().left
        const newWidth = mouseMoveEvent.clientX - sidebarLeft

        // 闄愬埗鏈€灏忓拰鏈€澶у搴?
        if (newWidth > 200 && newWidth < 500) {
          setSidebarWidth(newWidth)
        }
      }

      if (isPanelResizing && panelRef.current) {
        // 鍙充晶闈㈡澘瀹藉害 = 瑙嗗彛瀹藉害 - 榧犳爣X
        const newWidth = globalThis.window.innerWidth - mouseMoveEvent.clientX

        if (newWidth > 300 && newWidth < 800) {
          setPanelWidth(newWidth)
        }
      }
    },
    [isResizing, isPanelResizing]
  )

  useEffect(() => {
    if (isResizing || isPanelResizing) {
      globalThis.window.addEventListener('mousemove', resize)
      globalThis.window.addEventListener('mouseup', stopResizing)
    }
    return () => {
      globalThis.window.removeEventListener('mousemove', resize)
      globalThis.window.removeEventListener('mouseup', stopResizing)
    }
  }, [isResizing, isPanelResizing, resize, stopResizing])

  const scopedFiles = useMemo(() => {
    if (!selectedDatasetId) return files
    return files.filter((file) => file.datasetId === selectedDatasetId)
  }, [files, selectedDatasetId])

  const datasetDocumentCounts = useMemo(() => {
    const counts = new Map<string, number>()
    for (const file of files) {
      if (!file.datasetId) continue
      counts.set(file.datasetId, (counts.get(file.datasetId) || 0) + 1)
    }
    return counts
  }, [files])

  // 閫変腑鐨勬枃浠?
  const selectedFile = scopedFiles.find((f) => f.id === selectedFileId) || null
  const governanceState = selectedFileId
    ? governanceStates[selectedFileId]
    : null

  const visibleFiles = useMemo(() => {
    if (!activeFolderId || activeFolderId === ROOT_FOLDER_ID) return scopedFiles

    const childrenByParentId = new Map<string, string[]>()
    for (const folder of libraryFolders) {
      const parentId = folder.parentId || ROOT_FOLDER_ID
      const list = childrenByParentId.get(parentId) || []
      list.push(folder.id)
      childrenByParentId.set(parentId, list)
    }

    const allowedFolderIds = new Set<string>()
    const stack = [activeFolderId]
    while (stack.length > 0) {
      const current = stack.pop()
      if (!current) continue
      if (allowedFolderIds.has(current)) continue
      allowedFolderIds.add(current)
      const children = childrenByParentId.get(current) || []
      for (const childId of children) stack.push(childId)
    }

    return scopedFiles.filter((f) =>
      allowedFolderIds.has(f.folderId || ROOT_FOLDER_ID)
    )
  }, [scopedFiles, activeFolderId, libraryFolders])

  const readyChunkFiles = useMemo(
    () => visibleFiles.filter((file) => file.chunkStatus === 'ready'),
    [visibleFiles]
  )
  const selectedReadyChunkFiles = useMemo(
    () => readyChunkFiles.filter((file) => selectedChunkFileIds.has(file.id)),
    [readyChunkFiles, selectedChunkFileIds]
  )
  const selectedReadyChunkCount = selectedReadyChunkFiles.length

  useEffect(() => {
    const readyIds = new Set(readyChunkFiles.map((file) => file.id))
    setSelectedChunkFileIds((prev) => {
      const next = new Set(Array.from(prev).filter((id) => readyIds.has(id)))
      return next.size === prev.size ? prev : next
    })
  }, [readyChunkFiles])

  const toggleChunkFileSelection = useCallback((fileId: string) => {
    setSelectedChunkFileIds((prev) => {
      const next = new Set(prev)
      if (next.has(fileId)) next.delete(fileId)
      else next.add(fileId)
      return next
    })
  }, [])

  // 鍒濆鍖栨枃浠舵不鐞嗙姸鎬?
  const initializeGovernanceState = useCallback(
    (file: {
      id: string
      markdownContent: string
      originalMarkdownContent?: string
    }) => {
      const originalContent =
        file.originalMarkdownContent ?? file.markdownContent
      const cleanedContent = file.markdownContent
      setGovernanceStates((prev) => {
        const existing = prev[file.id]
        if (existing) {
          // If we initialized with empty content (e.g., after refresh), backfill once content is loaded.
          const hasAnyExistingContent = Boolean(
            (existing.originalContent || '').trim() ||
            (existing.cleanedContent || '').trim()
          )
          const hasIncomingContent = Boolean(
            originalContent.trim() || cleanedContent.trim()
          )
          if (hasAnyExistingContent || !hasIncomingContent) return prev
          return {
            ...prev,
            [file.id]: {
              ...existing,
              originalContent,
              cleanedContent,
              isModified: cleanedContent !== originalContent,
            },
          }
        }
        return {
          ...prev,
          [file.id]: {
            id: file.id,
            originalContent,
            cleanedContent,
            annotations: [],
            tags: [],
            category: null,
            qualityScore: 0,
            issues: [],
            isModified: cleanedContent !== originalContent,
          },
        }
      })
    },
    []
  )

  // Ensure markdown is available after refresh: load from IndexedDB cache first, fallback to backend.
  useEffect(() => {
    const file = selectedFile
    const id = (file?.id || '').trim()
    if (!id) return
    if ((file?.markdownContent || '').trim()) {
      initializeGovernanceState(file as any)
      return
    }

    let cancelled = false
    ;(async () => {
      try {
        const cached = await getDocContentFromCache(id)
        if (cancelled) return
        const markdown = (cached?.markdownContent || '').trim()
        const original = (cached?.originalMarkdownContent || '').trim()
        if (markdown || original) {
          const nextMarkdown = markdown || original
          const nextOriginal = original || markdown
          updateParsedFile(id, {
            markdownContent: nextMarkdown,
            originalMarkdownContent: nextOriginal,
          })
          initializeGovernanceState({
            id,
            markdownContent: nextMarkdown,
            originalMarkdownContent: nextOriginal,
          })
          return
        }
      } catch {
        // ignore
      }

      try {
        const remote =
          file?.source === 'knowledge_base'
            ? await documentApi.getParsedContent(id, { max_chars: 2_000_000 })
            : await parsingApi.getContent(id)
        if (cancelled) return
        const markdown = (remote?.markdown_content || '').trim()
        const original = (remote?.original_markdown_content || '').trim()
        if (!markdown && !original) return
        const nextMarkdown = markdown || original
        const nextOriginal = original || markdown
        updateParsedFile(id, {
          markdownContent: nextMarkdown,
          originalMarkdownContent: nextOriginal,
        })
        initializeGovernanceState({
          id,
          markdownContent: nextMarkdown,
          originalMarkdownContent: nextOriginal,
        })
      } catch {
        // ignore
      }
    })()

    return () => {
      cancelled = true
    }
  }, [initializeGovernanceState, selectedFile, updateParsedFile])

  const handleDeleteFile = useCallback(
    (fileId: string) => {
      const target = files.find((f) => f.id === fileId)
      if (!target) return

      detachPromise(
        (async () => {
          try {
            await parsingApi.delete(fileId)
          } catch {
            // ignore: some entries may be local-only or already deleted on the backend
          }
        })()
      )

      removeFile(fileId)
      setGovernanceStates((prev) => {
        if (!prev[fileId]) return prev
        const next = { ...prev }
        delete next[fileId]
        return next
      })
      if (selectedFileId === fileId) {
        setSelectedFileId(null)
      }
      toast.success(t('toasts.fileDeleted'))
    },
    [files, removeFile, selectedFileId, t]
  )

  // 鍒濆鍖栵細鑷姩閫夋嫨绗竴涓枃浠?
  useEffect(() => {
    if (!isLoaded) return

    if (visibleFiles.length === 0) {
      setSelectedFileId(null)
      return
    }

    const stillVisible =
      selectedFileId && visibleFiles.some((f) => f.id === selectedFileId)
    if (!stillVisible) {
      setSelectedFileId(visibleFiles[0].id)
      initializeGovernanceState(visibleFiles[0])
    }
  }, [isLoaded, visibleFiles, selectedFileId, initializeGovernanceState])

  // 鎷栨斁澶勭悊
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }, [])

  // 涓婁紶骞惰В鏋愰€昏緫锛堟敮鎸?.zip 鎵归噺瑙ｅ帇锛?
  const handleUploadAndParse = useCallback(
    async (incomingFiles: File[]) => {
      uploadAbortRef.current?.abort()
      const controller = new AbortController()
      uploadAbortRef.current = controller
      setUploading(true)
      try {
        const baseFolderId = activeFolderId || ROOT_FOLDER_ID

        const folderIdByKey = new Map<string, string>()
        for (const f of libraryFolders) {
          folderIdByKey.set(`${f.parentId || ROOT_FOLDER_ID}::${f.name}`, f.id)
        }

        const getOrCreateFolder = (parentId: string, name: string) => {
          const trimmed = name.trim()
          const key = `${parentId}::${trimmed}`
          const cached = folderIdByKey.get(key)
          if (cached) return cached

          const existing = libraryFolders.find(
            (f) =>
              (f.parentId || ROOT_FOLDER_ID) === parentId && f.name === trimmed
          )
          if (existing) {
            folderIdByKey.set(key, existing.id)
            return existing.id
          }

          const newId = createFolder(trimmed, parentId)
          folderIdByKey.set(key, newId)
          return newId
        }

        const expanded: Array<{ file: File; folderId: string }> = []
        let skipped = 0
        let added = 0

        for (const file of incomingFiles) {
          if (isZipFile(file)) {
            let extractedCount = 0
            let addedInZip = 0
            let skippedInZip = 0
            try {
              const extracted = await extractZipFiles(file)
              extractedCount = extracted.length
              for (const item of extracted) {
                const parts = item.path.split('/').filter(Boolean)
                const filename = parts.pop()
                if (!filename) continue

                const ext = filename.split('.').pop()?.toLowerCase() || ''
                if (!ZIP_ALLOWED_EXTENSIONS.has(ext)) {
                  skipped += 1
                  skippedInZip += 1
                  continue
                }

                let folderId = baseFolderId
                for (const segment of parts) {
                  folderId = getOrCreateFolder(folderId, segment)
                }

                expanded.push({ file: item.file, folderId })
                added += 1
                addedInZip += 1
              }
            } catch (e) {
              console.error('Failed to extract zip:', e)
              toast.error(t('toasts.zipExtractFailed', { filename: file.name }))
            }

            if (addedInZip === 0) {
              toast.warning(
                extractedCount === 0
                  ? t('toasts.zipNoFilesFound', { filename: file.name })
                  : t('toasts.zipNoSupportedFiles', { filename: file.name })
              )
            } else {
              toast.success(
                skippedInZip > 0
                  ? t('toasts.zipAddedWithSkipped', {
                      added: addedInZip,
                      skipped: skippedInZip,
                    })
                  : t('toasts.zipAdded', { added: addedInZip })
              )
            }
            continue
          }

          const ext = file.name.split('.').pop()?.toLowerCase() || ''
          if (!ZIP_ALLOWED_EXTENSIONS.has(ext)) {
            skipped += 1
            continue
          }

          expanded.push({ file, folderId: baseFolderId })
          added += 1
        }

        for (const { file, folderId } of expanded) {
          // 浣跨敤 preview 鎺ュ彛蹇€熻幏鍙?Markdown
          if (
            controller.signal.aborted ||
            uploadAbortRef.current !== controller
          )
            return
          const data = await documentApi.preview(
            file,
            parserBackend,
            undefined,
            {
              signal: controller.signal,
              dataset_id: selectedDatasetId || undefined,
            }
          )
          if (
            controller.signal.aborted ||
            uploadAbortRef.current !== controller
          )
            return

          // 鎷兼帴 segments 鑾峰彇鍏ㄦ枃
          const markdownContent = data.segments
            .map((s) => s.content)
            .join('\n\n')

          const newId = addParsedFile({
            filename: file.name,
            fileType: file.name.split('.').pop()?.toLowerCase() || '',
            fileSize: file.size,
            markdownContent,
            parser: data.parser_backend,
            folderId,
            datasetId: selectedDatasetId,
            datasetName: selectedDatasetName,
          })

          // 濡傛灉鏄涓€涓枃浠讹紝鑷姩閫変腑
          initializeGovernanceState({ id: newId, markdownContent })
          setSelectedFileId((prev) => prev ?? newId)
        }

        if (added > 0)
          toast.success(t('toasts.parsedAndAdded', { count: added }))
        if (skipped > 0)
          toast.warning(t('toasts.skippedUnsupported', { count: skipped }))
      } catch (error) {
        if (controller.signal.aborted || uploadAbortRef.current !== controller)
          return
        console.error('Failed to parse file:', error)
        toast.error(t('toasts.parseFailed'))
      } finally {
        if (uploadAbortRef.current === controller) {
          uploadAbortRef.current = null
          setUploading(false)
        }
      }
    },
    [
      activeFolderId,
      addParsedFile,
      createFolder,
      initializeGovernanceState,
      libraryFolders,
      parserBackend,
      selectedDatasetId,
      selectedDatasetName,
      t,
    ]
  )

  const handleDrop = useCallback(
    async (e: React.DragEvent) => {
      e.preventDefault()
      setIsDragging(false)
      const files = Array.from(e.dataTransfer.files)
      if (files.length > 0) {
        await handleUploadAndParse(files)
      }
    },
    [handleUploadAndParse]
  )

  const handleFileSelect = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files ? Array.from(e.target.files) : []
      if (files.length > 0) {
        await handleUploadAndParse(files)
      }
      e.target.value = ''
    },
    [handleUploadAndParse]
  )

  // 鑾峰彇褰撳墠鏄剧ず鍐呭
  const displayContent = useMemo(() => {
    if (!governanceState) return ''
    return viewMode === 'original'
      ? governanceState.originalContent
      : governanceState.cleanedContent
  }, [governanceState, viewMode])
  const libraryOnlyNotice = t('libraryFile.notice')

  // 鏂囦欢閫夋嫨
  const handleSelectFile = useCallback(
    (fileId: string) => {
      const file = scopedFiles.find((f) => f.id === fileId)
      if (file) {
        setSelectedFileId(fileId)
        initializeGovernanceState(file)
      }
    },
    [scopedFiles, initializeGovernanceState]
  )

  // 鎵嬪姩缂栬緫鍥炶皟
  const handleManualEdit = useCallback(
    (newContent: string) => {
      if (!selectedFileId) return
      setGovernanceStates((prev) => ({
        ...prev,
        [selectedFileId]: {
          ...prev[selectedFileId],
          cleanedContent: newContent,
          isModified: true, // 鎵嬪姩淇敼涔熻瑙嗕负宸蹭慨鏀?
        },
      }))
    },
    [selectedFileId]
  )

  // 璐ㄩ噺妫€娴嬪畬鎴愬洖璋?
  const handleQualityCheck = useCallback(
    (result: { score: number; issues: FileGovernanceState['issues'] }) => {
      if (!selectedFileId) return
      setGovernanceStates((prev) => ({
        ...prev,
        [selectedFileId]: {
          ...prev[selectedFileId],
          qualityScore: result.score,
          issues: result.issues,
        },
      }))
    },
    [selectedFileId]
  )

  // 娓呮礂瀹屾垚鍥炶皟
  const handleClean = useCallback(
    (cleanedContent: string) => {
      if (!selectedFileId) return
      setGovernanceStates((prev) => ({
        ...prev,
        [selectedFileId]: {
          ...prev[selectedFileId],
          cleanedContent,
          isModified: cleanedContent !== prev[selectedFileId].originalContent,
        },
      }))
    },
    [selectedFileId]
  )

  // 鏍囨敞瀹屾垚鍥炶皟
  const handleAnnotate = useCallback(
    (annotations: FileGovernanceState['annotations']) => {
      if (!selectedFileId) return
      setGovernanceStates((prev) => ({
        ...prev,
        [selectedFileId]: {
          ...prev[selectedFileId],
          annotations,
          isModified: true,
        },
      }))
    },
    [selectedFileId]
  )

  const handleDocumentTags = useCallback(
    (tags: string[]) => {
      if (!selectedFileId) return
      setGovernanceStates((prev) => {
        const current = prev[selectedFileId]
        const mergedTags = Array.from(
          new Set([...(current.tags || []), ...tags.filter(Boolean)])
        )
        return {
          ...prev,
          [selectedFileId]: {
            ...current,
            tags: mergedTags,
            isModified: true,
          },
        }
      })
    },
    [selectedFileId]
  )

  // 鍒嗙被瀹屾垚鍥炶皟
  const handleClassify = useCallback(
    (category: string, tags: string[]) => {
      if (!selectedFileId) return
      setGovernanceStates((prev) => ({
        ...prev,
        [selectedFileId]: {
          ...prev[selectedFileId],
          category,
          tags,
          isModified: true,
        },
      }))
    },
    [selectedFileId]
  )

  // 閲嶇疆鏂囦欢鐘舵€?
  const handleReset = useCallback(() => {
    if (!selectedFileId || !governanceState) return
    setGovernanceStates((prev) => ({
      ...prev,
      [selectedFileId]: {
        ...governanceState,
        cleanedContent: governanceState.originalContent,
        annotations: [],
        tags: [],
        category: null,
        qualityScore: 0,
        issues: [],
        isModified: false,
      },
    }))
  }, [selectedFileId, governanceState])

  // 灏嗘不鐞嗗悗鐨勫唴瀹瑰洖鍐欏埌鍏变韩瀛樺偍锛坙ocalStorage锛夛紝浠ヤ究 /chunk-preview 浣跨敤鏈€鏂扮増鏈?
  const persistGovernanceEdits = useCallback(
    (options?: {
      markReadyFileIds?: Set<string>
      markSubmittedFileIds?: Set<string>
    }) => {
      const markReadyFileIds = options?.markReadyFileIds || new Set<string>()
      const markSubmittedFileIds =
        options?.markSubmittedFileIds || new Set<string>()

      for (const f of files) {
        const state = governanceStates[f.id]
        const nextChunkStatus = markSubmittedFileIds.has(f.id)
          ? 'submitted'
          : markReadyFileIds.has(f.id)
            ? 'ready'
            : undefined
        if (!state && !nextChunkStatus) continue

        // 濡傛灉鍘嗗彶鏁版嵁娌℃湁淇濆瓨 originalMarkdownContent锛屽厛鐢ㄥ綋鍓嶅唴瀹硅ˉ榻愶紝閬垮厤琚悗缁繚瀛樿鐩栨帀銆?
        const originalMarkdownContent =
          typeof f.originalMarkdownContent === 'string'
            ? f.originalMarkdownContent
            : f.markdownContent

        const shouldUpdateMarkdown =
          state?.cleanedContent != null &&
          state.cleanedContent !== f.markdownContent
        const shouldSetOriginal =
          Boolean(state) && typeof f.originalMarkdownContent !== 'string'

        if (shouldUpdateMarkdown || shouldSetOriginal || nextChunkStatus) {
          updateParsedFile(f.id, {
            ...(shouldUpdateMarkdown
              ? { markdownContent: state?.cleanedContent }
              : {}),
            ...(shouldSetOriginal ? { originalMarkdownContent } : {}),
            ...(nextChunkStatus ? { chunkStatus: nextChunkStatus } : {}),
          })
        }
      }
    },
    [files, governanceStates, updateParsedFile]
  )

  const handleSave = useCallback(() => {
    if (!selectedFileId) return
    persistGovernanceEdits({
      markReadyFileIds: new Set([selectedFileId]),
    })
    setSelectedChunkFileIds((prev) => new Set(prev).add(selectedFileId))
    toast.success(t('toasts.resultsSaved'))
  }, [persistGovernanceEdits, selectedFileId, t])

  const handleSubmitSelectedToChunkPreview = useCallback(() => {
    if (!selectedReadyChunkFiles.length) {
      toast.error(t('toasts.noChunkReadySelection'))
      return
    }

    const targetIds = new Set(selectedReadyChunkFiles.map((file) => file.id))
    persistGovernanceEdits({
      markSubmittedFileIds: targetIds,
    })
    setSelectedChunkFileIds(new Set())
    toast.success(
      t('toasts.submittedToChunkPreview', {
        count: selectedReadyChunkFiles.length,
      })
    )
    const params = new URLSearchParams()
    if (selectedDatasetId) params.set('dataset_id', selectedDatasetId)
    const query = params.toString()
    router.push(query ? `/chunk-preview?${query}` : '/chunk-preview')
  }, [persistGovernanceEdits, router, selectedDatasetId, selectedReadyChunkFiles, t])

  const handlePushToChunkPreview = useCallback(() => {
    if (selectedReadyChunkFiles.length > 0) {
      handleSubmitSelectedToChunkPreview()
      return
    }
    if (selectedFileId) {
      persistGovernanceEdits({
        markSubmittedFileIds: new Set([selectedFileId]),
      })
    } else {
      persistGovernanceEdits()
    }
    const params = new URLSearchParams()
    if (selectedDatasetId) params.set('dataset_id', selectedDatasetId)
    const query = params.toString()
    router.push(query ? `/chunk-preview?${query}` : '/chunk-preview')
  }, [
    handleSubmitSelectedToChunkPreview,
    persistGovernanceEdits,
    router,
    selectedDatasetId,
    selectedFileId,
    selectedReadyChunkFiles.length,
  ])

  // 缁熻鏁版嵁
  const stats = useMemo(() => {
    const scopedIds = new Set(scopedFiles.map((file) => file.id))
    const scopedStates = Object.values(governanceStates).filter((state) =>
      scopedIds.has(state.id)
    )
    const totalFiles = scopedFiles.length
    const completedFiles = scopedStates.filter((s) => s.qualityScore > 0).length
    const modifiedFiles = scopedStates.filter((s) => s.isModified).length
    const avgScore =
      scopedStates
        .filter((s) => s.qualityScore > 0)
        .reduce((sum, s) => sum + s.qualityScore, 0) / completedFiles || 0

    return { totalFiles, completedFiles, modifiedFiles, avgScore }
  }, [governanceStates, scopedFiles])

  // 绌虹姸鎬?- 鏀逛负涓婁紶寮曞
  if (isLoaded && files.length === 0) {
    return (
      <WorkbenchScaffold
        title={headerTitle}
        badge={t('header.emptyBadge')}
        iconImage="data-governance"
        icon={ShieldCheck}
        iconColor="text-success"
        compactHeader
        description={
          <span className="flex items-center gap-2 text-[13px] text-muted-foreground/80">
            <span
              className="h-1.5 w-1.5 rounded-full bg-primary/20"
              aria-hidden="true"
            />
            <span>{headerSubtitle}</span>
          </span>
        }
        size="full"
        bodyClassName="px-0 pb-0"
        pipelineRail={<PipelineRail />}
        mainPanel={
          <div className="flex-1 flex flex-col min-h-0">
            <div className="relative flex flex-1 items-center justify-center overflow-hidden p-4 md:p-6">
              <div
                aria-hidden
                className="pointer-events-none absolute inset-0 bg-[radial-gradient(circle_at_16%_12%,hsl(var(--primary)/0.14),transparent_30%),radial-gradient(circle_at_82%_18%,hsl(var(--teal)/0.12),transparent_28%),linear-gradient(135deg,hsl(var(--background)),hsl(var(--surface-2)/0.62))]"
              />
              <div
                aria-hidden
                className="pointer-events-none absolute inset-x-8 top-8 h-px bg-[linear-gradient(90deg,transparent,hsl(var(--primary)/0.32),transparent)]"
              />
              <div
                data-governance-empty-workbench="true"
                className={cn(
                  'group relative w-full max-w-6xl px-1 transition-all duration-200 motion-reduce:transition-none md:px-2 xl:px-4',
                  isDragging
                    ? 'bg-primary/8'
                    : 'bg-transparent'
                )}
              >
                <div
                  aria-hidden
                  className="pointer-events-none absolute inset-0 bg-[url('/grid.svg')] opacity-[0.045]"
                />
                <div
                  aria-hidden
                  className="pointer-events-none absolute -left-24 top-16 h-64 w-64 rounded-full bg-primary/12 blur-3xl"
                />
                <div
                  aria-hidden
                  className="pointer-events-none absolute -right-24 -top-16 h-72 w-72 rounded-full bg-teal/12 blur-3xl"
                />

                <div className="relative z-10 grid gap-5 lg:grid-cols-[minmax(0,1fr)_340px] xl:grid-cols-[minmax(0,1fr)_380px]">
                  <div className="relative min-h-[520px] overflow-hidden border-y border-dashed border-primary/24 bg-transparent px-2 py-6 md:px-4 md:py-8">
                    <div
                      aria-hidden
                      className={cn(
                        'absolute inset-x-4 top-4 h-px bg-primary/18 opacity-70',
                        isDragging && 'bg-primary/45'
                      )}
                    />
                    <div
                      aria-hidden
                      className="absolute left-1/2 top-10 h-40 w-40 -translate-x-1/2 rounded-full border border-primary/12 bg-[conic-gradient(from_140deg,hsl(var(--primary)/0.08),hsl(var(--teal)/0.18),hsl(var(--primary)/0.08))] blur-[0.2px]"
                    />

                    <button
                      type="button"
                      className="relative z-10 flex w-full flex-col items-center rounded-[1.25rem] bg-transparent text-center focus-ring"
                      onDragOver={handleDragOver}
                      onDragLeave={handleDragLeave}
                      onDrop={handleDrop}
                      onClick={() =>
                        globalThis.document
                          .getElementById('file-upload')
                          ?.click()
                      }
                      disabled={uploading}
                      aria-label={t('emptyUpload.openUploadDialog')}
                    >
                      <div className="relative mb-5 mt-2 grid size-28 place-items-center">
                        <span
                          aria-hidden
                          className="absolute inset-0 rounded-full border border-primary/18 bg-primary/8 shadow-[inset_0_0_32px_hsl(var(--primary)/0.08)]"
                        />
                        <span
                          aria-hidden
                          className={cn(
                            'absolute inset-3 rounded-full border border-dashed border-teal/25',
                            uploading && 'animate-spin motion-reduce:animate-none'
                          )}
                        />
                        <span className="relative grid size-16 place-items-center rounded-3xl border border-primary/18 bg-card/90 text-primary shadow-[0_18px_42px_-28px_hsl(var(--primary)/0.8)]">
                          {uploading ? (
                            <Sparkles className="size-7 animate-spin motion-reduce:animate-none" />
                          ) : (
                            <Upload className="size-7" />
                          )}
                        </span>
                      </div>

                      <div className="mb-3 inline-flex items-center gap-2 rounded-full border border-primary/12 bg-primary/8 px-3 py-1 text-[10px] font-semibold uppercase tracking-[0.18em] text-primary">
                        <ScanLine className="size-3.5" />
                        {t('emptyUpload.scanRingLabel')}
                      </div>

                      <h3 className="max-w-xl text-balance text-3xl font-semibold tracking-[-0.04em] text-foreground md:text-4xl">
                        {uploading
                          ? t('emptyUpload.uploadingTitle')
                          : t('emptyUpload.idleTitle')}
                      </h3>
                      <p className="mx-auto mt-3 max-w-2xl text-sm leading-6 text-muted-foreground md:text-[15px]">
                        {uploading
                          ? t('emptyUpload.uploadingDescription')
                          : t('emptyUpload.idleDescription')}
                      </p>
                      <p className="mx-auto mt-2 max-w-xl text-xs leading-5 text-muted-foreground/78">
                        {t('emptyUpload.dropCta')}
                      </p>
                    </button>

                    <div className="relative z-20 mt-6 flex flex-wrap items-center justify-center gap-2">
                      {EMPTY_UPLOAD_FORMATS.map((format) => (
                        <span
                          key={format}
                          className="rounded-full border border-border/55 bg-card/78 px-3 py-1 text-[11px] font-semibold text-foreground/80 shadow-sm"
                        >
                          {format}
                        </span>
                      ))}
                    </div>

                    <div className="relative z-20 mt-7 flex flex-col items-center justify-center gap-3 sm:flex-row">
                      <div className="relative">
                        <input
                          type="file"
                          multiple
                          accept={UPLOAD_ACCEPT_WITH_ZIP}
                          className="hidden"
                          id="file-upload"
                          onChange={handleFileSelect}
                          disabled={uploading}
                        />
                        <label
                          htmlFor="file-upload"
                          className={cn(
                            'inline-flex cursor-pointer items-center gap-3 rounded-2xl border border-info/25 bg-info px-7 py-3.5 text-sm font-semibold text-info-foreground shadow-[0_18px_38px_-28px_hsl(var(--info)/0.88)] transition-all duration-150 hover:-translate-y-0.5 hover:bg-info/90 motion-reduce:transition-none',
                            uploading && 'cursor-not-allowed opacity-50'
                          )}
                        >
                          <Upload className="size-5" />
                          {t('emptyUpload.selectLocalFiles')}
                        </label>
                      </div>
                      {uploading && (
                        <Button
                          type="button"
                          variant="outline"
                          onClick={cancelUploadAndParse}
                          className="gap-2 rounded-2xl border-border/60 bg-background px-7 py-3.5 text-muted-foreground transition-colors duration-150 hover:border-destructive/30 hover:bg-destructive/10 hover:text-destructive motion-reduce:transition-none"
                        >
                          <X className="size-5" />
                          {t('emptyUpload.cancelParsing')}
                        </Button>
                      )}
                    </div>

                    <div className="relative z-20 mt-7 grid gap-3 border-t border-border/50 pt-4 md:grid-cols-3">
                      {EMPTY_UPLOAD_STEPS.map((step, index) => (
                        <div
                          key={step}
                          className="text-left"
                      >
                          <div className="mb-2 flex items-center gap-2">
                            <span className="grid size-6 place-items-center rounded-lg bg-primary/10 text-[10px] font-bold text-primary">
                              {index + 1}
                            </span>
                            <span className="text-xs font-semibold text-foreground">
                              {t(`emptyUpload.stages.${step}`)}
                            </span>
                          </div>
                          <div className="h-1.5 overflow-hidden rounded-full bg-muted/70">
                            <div
                              className={cn(
                                'h-full rounded-full',
                                index === 0 && 'w-10/12 bg-primary/55',
                                index === 1 && 'w-8/12 bg-info/55',
                                index === 2 && 'w-6/12 bg-teal/55'
                              )}
                            />
                          </div>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="space-y-5 py-2 lg:py-4">
                    <EmptyStructurePreview t={t} />
                    <div className="border-l border-border/70 pl-4">
                      <div className="flex items-center gap-2 text-[10px] font-semibold uppercase tracking-[0.18em] text-muted-foreground">
                        <Sparkles className="size-3.5 text-teal" />
                        {t('emptyUpload.intakeChecksTitle')}
                      </div>
                      <div className="mt-3 divide-y divide-border/50">
                        {[
                          t('emptyUpload.intakeChecks.structure'),
                          t('emptyUpload.intakeChecks.quality'),
                          t('emptyUpload.intakeChecks.cleaning'),
                        ].map((item) => (
                          <div
                            key={item}
                            className="flex items-center gap-2 py-2.5 text-xs text-foreground/82"
                          >
                            <Check className="size-3.5 text-success" />
                            <span>{item}</span>
                          </div>
                        ))}
                      </div>
                    </div>
                  </div>
                </div>
              </div>
            </div>
          </div>
        }
      />
    )
  }

  const contentBody =
    viewMode === 'edit' ? (
      <div className="grid grid-cols-2 gap-4 h-full">
        <div className="flex flex-col bg-muted rounded-xl border border-border shadow-sm overflow-hidden h-full">
          <div className="px-4 py-2 bg-muted border-b border-border text-xs font-medium text-muted-foreground">
            {t('canvas.livePreview')}
          </div>
          <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar p-6">
            <MarkdownRenderer markdown={displayContent || ''} />
          </div>
        </div>
        <div className="flex flex-col bg-card rounded-xl border border-border shadow-sm overflow-hidden h-full">
          <div className="px-4 py-2 bg-muted border-b border-border text-xs font-medium text-muted-foreground">
            {t('canvas.sourceEditor')}
          </div>
          <textarea
            value={displayContent}
            onChange={(e) => handleManualEdit(e.target.value)}
            className="flex-1 w-full p-6 resize-none outline-none font-mono text-sm leading-relaxed text-foreground"
            spellCheck={false}
          />
        </div>
      </div>
    ) : displayContent?.includes(libraryOnlyNotice) ? (
      <div className="flex flex-col items-center justify-center h-full p-8 text-center">
        <div className="w-16 h-16 bg-muted rounded-2xl flex items-center justify-center mb-6 border border-border shadow-sm">
          <FileText className="w-8 h-8 text-muted-foreground" />
        </div>
        <h3 className="text-lg font-medium text-foreground mb-2 truncate max-w-lg">
          {selectedFile?.filename || t('libraryFile.unknownFile')}
        </h3>
        <div className="flex items-center gap-2 mb-8">
          <span className="px-2.5 py-1 rounded-full bg-muted text-muted-foreground text-xs font-medium border border-border">
            {t('libraryFile.badge')}
          </span>
          <span className="px-2.5 py-1 rounded-full bg-warning/10 dark:bg-warning/20 text-warning dark:text-warning text-xs font-medium border border-warning/30 flex items-center gap-1">
            <div className="w-1.5 h-1.5 rounded-full bg-warning/10 dark:bg-warning/20" />
            {t('libraryFile.pending')}
          </span>
        </div>

        <div className="max-w-md bg-muted rounded-xl p-5 border border-border mb-8 text-left">
          <p className="text-sm text-muted-foreground leading-relaxed flex gap-3">
            <Info className="w-5 h-5 text-info flex-shrink-0 mt-0.5" />
            {t('libraryFile.description', { notice: libraryOnlyNotice })}
          </p>
        </div>

        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            className="gap-2 bg-card hover:bg-muted text-foreground/80 border-border"
            onClick={() => {
              if (selectedFile?.filename) {
                navigator.clipboard.writeText(selectedFile.filename)
                toast.success(t('toasts.filenameCopied'))
              }
            }}
          >
            <Copy className="w-4 h-4" />
            {t('libraryFile.copyName')}
          </Button>
          <ConfirmDialog
            title={t('libraryFile.removeDialog.title')}
            description={t('libraryFile.removeDialog.description')}
            confirmLabel={t('libraryFile.removeDialog.confirm')}
            cancelLabel={t('libraryFile.removeDialog.cancel')}
            confirmVariant="destructive"
            confirmDisabled={!selectedFileId}
            onConfirm={() => {
              if (!selectedFileId) return
              const { removeFile } = useParsedFiles.getState()
              removeFile(selectedFileId)
              setSelectedFileId(null)
              toast.success(t('toasts.fileRemoved'))
            }}
          >
            <Button
              variant="outline"
              className="gap-2 bg-card hover:bg-destructive/10 dark:bg-destructive/20 text-foreground/80 hover:text-destructive dark:text-destructive/85 border-border hover:border-destructive/30"
              disabled={!selectedFileId}
            >
              <Trash2 className="w-4 h-4" />
              {t('libraryFile.removeButton')}
            </Button>
          </ConfirmDialog>
        </div>
      </div>
    ) : previewFormat === 'rendered' ? (
      <div className="prose prose-slate dark:prose-invert max-w-none prose-headings:text-foreground prose-p:text-muted-foreground prose-a:text-info dark:prose-a:text-info">
        <MarkdownRenderer markdown={displayContent || ''} />
      </div>
    ) : (
      <pre className="font-mono text-sm leading-relaxed whitespace-pre-wrap break-words text-foreground">
        {displayContent || ''}
      </pre>
    )

  return (
    <WorkbenchScaffold
      title={headerTitle}
      badge={t('header.mainBadge')}
      iconImage="data-governance"
      icon={ShieldCheck}
      iconColor="text-info"
      compactHeader
      description={
        <span className="flex items-center gap-2 text-[13px] text-muted-foreground/80">
          <span
            className="w-1.5 h-1.5 rounded-full bg-info/10 dark:bg-info/20"
            aria-hidden="true"
          />
          <span>{t('header.workspaceSubtitle')}</span>
        </span>
      }
      actions={
        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            size="sm"
            onClick={handleReset}
            disabled={!governanceState?.isModified}
            className="gap-1.5 h-8 text-xs"
          >
            <RotateCcw className="w-3.5 h-3.5" />
            {t('actions.reset')}
          </Button>
          <Button
            variant="info"
            size="sm"
            onClick={handleSave}
            disabled={!governanceState}
            className="gap-2 h-8 text-xs"
          >
            <Save className="w-3.5 h-3.5" />
            {t('actions.save')}
          </Button>
          <div className="w-px h-4 bg-border dark:bg-card mx-1" />
          <Button
            variant="outline"
            size="sm"
            onClick={handleSubmitSelectedToChunkPreview}
            disabled={selectedReadyChunkCount === 0}
            className="gap-2 h-8 text-xs"
          >
            <Layers className="w-3.5 h-3.5" />
            {t('actions.submitSelectedToChunkPreview', {
              count: selectedReadyChunkCount,
            })}
          </Button>
          <Button
            variant="default"
            size="sm"
            onClick={handlePushToChunkPreview}
            disabled={!isLoaded || files.length === 0}
            className="gap-2 h-8 text-xs"
          >
            <Layers className="w-3.5 h-3.5" />
            {t('actions.pushToChunkPreview')}
          </Button>
        </div>
      }
      size="full"
      bodyClassName="px-0 pb-0"
      pipelineRail={<PipelineRail />}
      mainPanel={
        <div className="flex-1 flex flex-col bg-background text-foreground min-h-0">
          <div className="flex-1 flex overflow-hidden min-h-0 relative bg-background">
            {/* 宸︿晶鏂囦欢鍒楄〃 */}
            <aside
              ref={sidebarRef}
              className={cn(
                'group/sidebar relative flex flex-col flex-shrink-0 bg-card border-r border-border z-10',
                isSidebarCollapsed ? 'w-0 border-r-0' : ''
              )}
              style={{ width: isSidebarCollapsed ? 0 : sidebarWidth }}
            >
              {/* 鎶樺彔/灞曞紑鎸夐挳 */}
              <Button
                variant="ghost"
                size="icon"
                className={cn(
                  'absolute -right-3 top-3 z-30 h-6 w-6 rounded-full border border-border bg-card shadow-sm text-muted-foreground hover:text-muted-foreground hover:bg-muted transition-opacity opacity-0 group-hover/sidebar:opacity-100',
                  isSidebarCollapsed && 'opacity-100 -right-8 translate-x-2'
                )}
                onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
                title={
                  isSidebarCollapsed
                    ? t('sidebar.expand')
                    : t('sidebar.collapse')
                }
                aria-label={
                  isSidebarCollapsed
                    ? t('sidebar.expand')
                    : t('sidebar.collapse')
                }
              >
                {isSidebarCollapsed ? (
                  <PanelRightOpen className="w-3 h-3" />
                ) : (
                  <PanelRightClose className="w-3 h-3" />
                )}
              </Button>

              <div
                className={cn(
                  'flex-1 flex flex-col min-h-0 w-full overflow-hidden',
                  isSidebarCollapsed && 'invisible'
                )}
              >
                {/* 鐩綍鍒囨崲 & 鎼滅储 */}
                <div className="p-3 border-b border-border space-y-3">
                  <Select
                    value={activeFolderId || ROOT_FOLDER_ID}
                    onValueChange={setActiveFolderId}
                  >
                    <SelectTrigger className="h-9 text-xs bg-muted border-border text-foreground/80 focus:bg-card focus-ring transition-colors duration-200 motion-reduce:transition-none">
                      <div className="flex items-center gap-2 truncate">
                        <FolderTree className="w-3.5 h-3.5 text-primary" />
                        <span className="truncate">{activeFolderLabel}</span>
                      </div>
                    </SelectTrigger>
                    <SelectContent className="bg-card border-border text-foreground/80">
                      <SelectItem value={ROOT_FOLDER_ID}>
                        {t('sidebar.allFolders')}
                      </SelectItem>
                      {libraryFolders.map((f) => (
                        <SelectItem key={f.id} value={f.id}>
                          {f.name}
                        </SelectItem>
                      ))}
                    </SelectContent>
                  </Select>

                  <div className="relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
                    <input
                      type="text"
                      placeholder={t('sidebar.searchPlaceholder')}
                      className="w-full rounded-lg border border-border bg-muted py-1.5 pl-9 pr-3 text-xs text-foreground/80 placeholder:text-muted-foreground focus:bg-card focus:outline-none focus:border-primary/30 focus-ring transition-colors duration-200 motion-reduce:transition-none"
                    />
                  </div>
                </div>

                <div className="relative border-b border-border/40">
                  <div
                    aria-hidden
                    className="absolute left-0 top-2 bottom-2 w-[2px] rounded-full bg-info/70"
                  />
                  <div className="space-y-1.5 from-info/[0.08] via-info/[0.03] to-transparent py-2.5 pl-4 pr-3 dark:from-info/[0.14] dark:via-info/[0.05]">
                    <div className="flex items-center justify-between gap-2">
                      <span className="text-[10px] font-medium uppercase tracking-[0.16em] text-info/90 dark:text-info">
                        {t('scope.title')}
                      </span>
                      <span
                        className={cn(
                          'rounded-full border px-1.5 py-0.5 text-[10px] font-medium tabular-nums transition-colors',
                          selectedDatasetId
                            ? 'border-info/30 bg-info/15 text-info'
                            : 'border-border/60 bg-muted/60 text-muted-foreground'
                        )}
                      >
                        {selectedDatasetId
                          ? t('scope.datasetScoped')
                          : t('scope.datasetAll')}
                      </span>
                    </div>
                    <Select
                      value={selectedDatasetId || ALL_DATASETS_VALUE}
                      onValueChange={handleDatasetScopeChange}
                    >
                      <SelectTrigger
                        className={cn(
                          'h-8 text-[11px] font-medium bg-card border-border/60 text-foreground transition-colors duration-200 motion-reduce:transition-none',
                          'hover:border-info/40 focus:border-info/60 data-[state=open]:border-info/60',
                          'focus-visible:ring-2 focus-visible:ring-info/20 focus-visible:ring-offset-0',
                          'dark:bg-card'
                        )}
                      >
                        <div className="flex items-center gap-1.5 truncate">
                          <FolderTree className="w-3.5 h-3.5 text-info/80 flex-shrink-0" />
                          <SelectValue placeholder={t('scope.placeholder')} />
                        </div>
                      </SelectTrigger>
                      <SelectContent className="bg-card border-border/60 text-foreground">
                        <SelectItem
                          value={ALL_DATASETS_VALUE}
                          className="text-[12px]"
                        >
                          <span className="flex items-center gap-1.5">
                            <span
                              aria-hidden
                              className="size-1.5 rounded-full bg-muted-foreground/50"
                            />
                            {t('scope.allDatasets')}
                          </span>
                        </SelectItem>
                        {availableDatasets.map((dataset) => (
                          <SelectItem
                            key={dataset.id}
                            value={dataset.id}
                            className="text-[12px]"
                          >
                            <span className="flex items-center gap-1.5">
                              <span
                                aria-hidden
                                className="size-1.5 rounded-full bg-info/70"
                              />
                              <span className="truncate">{dataset.name}</span>
                              <span className="ml-auto pl-2 text-[10px] tabular-nums text-muted-foreground/70">
                                {datasetDocumentCounts.get(dataset.id) || 0}
                              </span>
                            </span>
                          </SelectItem>
                        ))}
                      </SelectContent>
                    </Select>
                  </div>
                </div>

                {/* 鏂囦欢鐩綍鏍?- 鍙姌鍙犲尯鍩?*/}
                {/* Folder tree section */}
                <div className="space-y-1.5 border-b border-border/40 px-3 py-2">
                  <div className="flex items-center gap-1.5 px-1">
                    <FolderTree className="size-3 text-muted-foreground/65" />
                    <span className="text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground/75">
                      {t('sidebar.foldersHeader')}
                    </span>
                    <span className="ml-auto text-[10px] tabular-nums text-muted-foreground/60">
                      {libraryFolders.length}
                    </span>
                  </div>
                  <div className="-mx-1 max-h-44 overflow-y-auto overscroll-contain no-scrollbar px-1">
                    <DocumentFolderTree />
                  </div>
                </div>

                <div className="flex items-center justify-between px-4 pt-3 pb-1.5">
                  <h3 className="text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground/75">
                    {t('sidebar.filesTitle', { count: visibleFiles.length })}
                  </h3>
                </div>

                <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar px-3 pb-3 space-y-2">
                  {visibleFiles.length === 0 ? (
                    <div className="text-xs text-muted-foreground text-center py-8">
                      {t('sidebar.emptyDirectory')}
                    </div>
                  ) : (
                    visibleFiles.map((file) => {
                      const state = governanceStates[file.id]
                      const hasIssue = state?.issues.some(
                        (i) => i.type === 'error'
                      )
                      const score = state?.qualityScore || 0
                      const isReadyForChunk = file.chunkStatus === 'ready'
                      const isSubmittedForChunk =
                        file.chunkStatus === 'submitted'
                      const isSelectedForChunk =
                        selectedChunkFileIds.has(file.id)

                      return (
                        <div key={file.id} className="group relative">
                          <button
                            type="button"
                            onClick={() => handleSelectFile(file.id)}
                            className={cn(
                              'relative w-full text-left p-3 rounded-lg border transition-[background,border,box-shadow,transform] duration-200 motion-reduce:transition-none cursor-pointer overflow-hidden',
                              selectedFileId === file.id
                                ? 'border-info/30 from-info/[0.08] via-info/[0.03] to-transparent shadow-soft dark:from-info/[0.14]'
                                : 'border-border/60 bg-card hover:border-info/25 hover:bg-muted/40 hover:translate-x-[1px]'
                            )}
                            aria-label={t('a11y.openFile', {
                              filename: file.filename,
                            })}
                          >
                            {selectedFileId === file.id ? (
                              <span
                                aria-hidden
                                className="absolute left-0 top-2 bottom-2 w-[2px] rounded-full bg-info"
                              />
                            ) : null}
                            <div className="flex items-start gap-3">
                              {/* File Icon */}
                              {getFileIcon(
                                file.filename,
                                cn(
                                  'size-10 rounded-lg border transition-colors motion-reduce:transition-none flex-shrink-0',
                                  selectedFileId === file.id
                                    ? 'border-info/30 ring-1 ring-info/15'
                                    : 'border-border/60 group-hover:border-info/30'
                                )
                              )}

                              <div className="flex-1 min-w-0">
                                {/* Row 1: Filename & Score */}
                                <div className="flex items-center justify-between mb-1">
                                  <div
                                    className={cn(
                                      'text-sm font-medium truncate transition-colors',
                                      selectedFileId === file.id
                                        ? 'text-foreground'
                                        : 'text-foreground/85 group-hover:text-foreground'
                                    )}
                                  >
                                    {file.filename}
                                  </div>
                                  {score > 0 ? (
                                    <span
                                      className={cn(
                                        'flex-shrink-0 text-[10px] px-1.5 py-0.5 rounded-md font-medium tabular-nums border',
                                        score >= 80
                                          ? 'bg-success/12 text-success border-success/25'
                                          : score >= 60
                                            ? 'bg-warning/15 text-warning border-warning/30'
                                            : 'bg-rose/12 text-rose border-rose/25'
                                      )}
                                    >
                                      {t('sidebar.scoreLabel', { score })}
                                    </span>
                                  ) : (
                                    <span className="flex-shrink-0 text-[10px] text-muted-foreground bg-muted/60 px-1.5 py-0.5 rounded-md border border-border/60 font-medium tabular-nums">
                                      {t('sidebar.notScanned')}
                                    </span>
                                  )}
                                </div>

                                {/* Row 2: Metadata (Size & Date) */}
                                <div className="flex items-center gap-1.5 text-[11px] text-muted-foreground/80 mb-1.5 tabular-nums">
                                  <span>{formatFileSize(file.fileSize)}</span>
                                  <span className="text-muted-foreground/40">
                                    ·
                                  </span>
                                  <span>
                                    {file.parsedAt
                                      ? new Date(
                                          file.parsedAt
                                        ).toLocaleDateString([], {
                                          year: 'numeric',
                                          month: '2-digit',
                                          day: '2-digit',
                                        })
                                      : ''}
                                  </span>
                                  {file.datasetName ? (
                                    <>
                                      <span className="text-muted-foreground/40">
                                        ·
                                      </span>
                                      <span className="truncate">
                                        {file.datasetName}
                                      </span>
                                    </>
                                  ) : null}
                                </div>

                                {/* Row 3: Badges & Actions */}
                                <div className="flex items-center justify-between h-5 pr-8">
                                  <div className="flex items-center gap-2">
                                    {file.source ? (
                                      <span className="text-[9px] text-muted-foreground flex items-center gap-1 bg-muted/60 px-1.5 py-0.5 rounded border border-border/60 font-medium uppercase">
                                        {file.source === 'knowledge_base'
                                          ? t('scope.sourceKnowledge')
                                          : t('scope.sourceParsing')}
                                      </span>
                                    ) : null}
                                    {state?.isModified && (
                                      <span className="text-[9px] text-accent flex items-center gap-1 bg-accent/10 px-1.5 py-0.5 rounded border border-accent/25 font-medium">
                                        <Sparkles className="w-2.5 h-2.5" />{' '}
                                        {t('sidebar.cleaned')}
                                      </span>
                                    )}
                                    {isReadyForChunk ? (
                                      <span className="text-[9px] text-info flex items-center gap-1 bg-info/10 px-1.5 py-0.5 rounded border border-info/20 font-medium">
                                        {t('sidebar.chunkReady')}
                                      </span>
                                    ) : null}
                                    {isSubmittedForChunk ? (
                                      <span className="text-[9px] text-success flex items-center gap-1 bg-success/10 px-1.5 py-0.5 rounded border border-success/20 font-medium">
                                        {t('sidebar.chunkSubmitted')}
                                      </span>
                                    ) : null}
                                    {hasIssue && (
                                      <span className="text-[9px] text-rose flex items-center gap-1 bg-rose/10 px-1.5 py-0.5 rounded border border-rose/25 font-medium">
                                        <AlertTriangle className="w-2.5 h-2.5" />{' '}
                                        {t('sidebar.needsAttention')}
                                      </span>
                                    )}
                                  </div>
                                </div>
                              </div>
                            </div>
                          </button>
                          {file.source !== 'knowledge_base' ? (
                            <button
                              type="button"
                              onClick={() => {
                                setDeleteFileTarget({
                                  id: file.id,
                                  filename: file.filename,
                                })
                                setDeleteFileOpen(true)
                              }}
                              className="absolute bottom-2.5 right-2.5 opacity-0 group-hover:opacity-100 p-1 text-muted-foreground hover:text-rose hover:bg-rose/10 rounded transition-opacity transition-colors duration-150 motion-reduce:transition-none"
                              aria-label={t('a11y.deleteFile', {
                                filename: file.filename,
                              })}
                              title={t('dialogs.deleteFile.confirm')}
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          ) : null}
                          {isReadyForChunk ? (
                            <button
                              type="button"
                              onClick={() => toggleChunkFileSelection(file.id)}
                              aria-pressed={isSelectedForChunk}
                              aria-label={t('a11y.toggleChunkFile', {
                                filename: file.filename,
                              })}
                              className={cn(
                                'absolute right-2.5 top-2.5 grid h-5 w-5 place-items-center rounded-md border text-[10px] transition-colors duration-150 motion-reduce:transition-none',
                                isSelectedForChunk
                                  ? 'border-info/45 bg-info text-info-foreground shadow-sm'
                                  : 'border-border/70 bg-background/90 text-muted-foreground hover:border-info/35 hover:bg-info/10 hover:text-info'
                              )}
                            >
                              {isSelectedForChunk ? <Check className="h-3 w-3" /> : null}
                            </button>
                          ) : null}
                        </div>
                      )
                    })
                  )}
                </div>

                {/* 搴曢儴缁熻鏍?*/}
                {/* Footer KPI bar */}
                <div className="mt-auto border-t border-border/60 from-muted/30 to-muted/55 backdrop-blur-sm px-3 py-2.5 space-y-1.5">
                  <div className="flex items-baseline justify-between gap-2">
                    <span className="text-[10px] font-medium uppercase tracking-[0.14em] text-muted-foreground/75">
                      {t('stats.storage')}
                    </span>
                    <span className="text-[10px] tabular-nums text-muted-foreground/80">
                      {t('stats.processedRatio', {
                        done: stats.completedFiles,
                        total: stats.totalFiles,
                      })}
                    </span>
                  </div>
                  <div className="relative h-1.5 w-full overflow-hidden rounded-full bg-muted/80 ring-1 ring-inset ring-border/50">
                    <div
                      className={cn(
                        'h-full rounded-full transition-[width] duration-500 motion-reduce:transition-none',
                        stats.avgScore >= 80
                          ? 'from-success/80 via-success to-success'
                          : stats.avgScore >= 60
                            ? 'from-warning/70 via-warning to-warning'
                            : stats.avgScore > 0
                              ? 'from-rose/70 via-rose to-rose'
                              : 'from-info/40 to-info/70'
                      )}
                      style={{
                        width:
                          stats.totalFiles > 0
                            ? `${Math.min(100, Math.round((stats.completedFiles / stats.totalFiles) * 100))}%`
                            : '0%',
                      }}
                    />
                  </div>
                  <div className="flex items-center justify-between text-[10px] text-muted-foreground/70 tabular-nums">
                    <span>
                      {stats.totalFiles > 0
                        ? `${Math.round((stats.completedFiles / stats.totalFiles) * 100)}%`
                        : '0%'}
                    </span>
                    <span>
                      {stats.avgScore > 0
                        ? t('stats.avgScoreInline', {
                            score: stats.avgScore.toFixed(1),
                          })
                        : `${t('stats.avgScore')} —`}
                    </span>
                  </div>
                </div>
              </div>

              {/* 鎷栨嫿鎵嬫焺 */}
              <button
                type="button"
                className={cn(
                  'absolute right-0 top-0 w-1 h-full cursor-col-resize z-20 border-0 bg-transparent p-0 transition-colors opacity-0 hover:opacity-100 hover:bg-primary/10 dark:hover:bg-primary/20 active:bg-primary/30',
                  isResizing && 'bg-primary opacity-100'
                )}
                aria-label={t('sidebar.adjustWidth')}
                onMouseDown={startResizing}
              />
            </aside>

            {/* 涓诲唴瀹瑰尯 (涓棿 + 鍙充晶闈㈡澘) */}
            <main className="flex-1 flex overflow-hidden min-h-0 relative">
              {selectedFile && governanceState ? (
                <>
                  {/* 涓棿锛氶瑙堢敾甯?*/}
                  <div className="flex-1 flex flex-col overflow-hidden relative z-0">
                    {/* 鐢诲竷宸ュ叿鏍?(鎮诞鎴栭泦鎴? */}
                    <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 flex items-center bg-card border border-border/60 shadow-soft rounded-full px-2 py-1 gap-1 transition-colors duration-150 motion-reduce:transition-none">
                      {/* Segmented view-mode control */}
                      <div className="flex items-center bg-muted/60 rounded-full p-0.5 border border-border/60">
                        {(['preview', 'edit', 'original'] as const).map(
                          (mode) => (
                            <button
                              key={mode}
                              type="button"
                              onClick={() => setViewMode(mode)}
                              aria-pressed={viewMode === mode}
                              className={cn(
                                'px-3 py-1 rounded-full text-xs font-medium transition-colors duration-150 motion-reduce:transition-none focus-ring-soft',
                                viewMode === mode
                                  ? 'bg-card text-foreground shadow-sm ring-1 ring-border/60'
                                  : 'text-muted-foreground hover:text-foreground hover:bg-foreground/[0.04]'
                              )}
                            >
                              {t(`canvas.viewModes.${mode}`)}
                            </button>
                          )
                        )}
                      </div>

                      <div className="w-px h-3 bg-border mx-1" />

                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 rounded-full text-muted-foreground hover:text-foreground/80 hover:bg-muted"
                        onClick={() =>
                          setPreviewFormat((prev) =>
                            prev === 'rendered' ? 'markdown' : 'rendered'
                          )
                        }
                        title={
                          previewFormat === 'rendered'
                            ? t('canvas.viewSource')
                            : t('canvas.viewRendered')
                        }
                        aria-label={
                          previewFormat === 'rendered'
                            ? t('canvas.viewSource')
                            : t('canvas.viewRendered')
                        }
                      >
                        {previewFormat === 'rendered' ? (
                          <Hash className="w-3.5 h-3.5" />
                        ) : (
                          <Eye className="w-3.5 h-3.5" />
                        )}
                      </Button>
                    </div>

                    {/* 宸︿晶鏀惰捣鎸夐挳 (濡傛灉宸︿晶鏀惰捣) */}
                    {isSidebarCollapsed && (
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setIsSidebarCollapsed(false)}
                        className="absolute left-4 top-4 z-20 h-8 w-8 bg-card border border-border/60 shadow-soft rounded-lg text-muted-foreground hover:text-info hover:bg-card transition-colors duration-150 motion-reduce:transition-none"
                        aria-label={t('sidebar.expand')}
                        title={t('sidebar.expand')}
                      >
                        <PanelRightOpen className="w-4 h-4" />
                      </Button>
                    )}

                    {isPanelCollapsed && (
                      <Button
                        variant="ghost"
                        size="icon"
                        onClick={() => setIsPanelCollapsed(false)}
                        className="absolute right-4 top-4 z-20 h-8 w-8 bg-card border border-border/60 shadow-soft rounded-lg text-muted-foreground hover:text-info hover:bg-card transition-colors duration-150 motion-reduce:transition-none"
                        aria-label={t('panel.expand')}
                        title={t('panel.expand')}
                      >
                        <PanelRightClose className="w-4 h-4 rotate-180" />
                      </Button>
                    )}

                    {/* 鍐呭鍖哄煙 */}
                    <div
                      ref={contentScrollRef}
                      className="flex-1 overflow-y-auto overscroll-contain no-scrollbar p-4 md:p-8"
                    >
                      <div
                        className={cn(
                          'mx-auto',
                          viewMode === 'edit' ? 'max-w-full' : 'max-w-4xl'
                        )}
                      >
                        {/* 绾稿紶鏁堟灉瀹瑰櫒 */}
                        <div
                          className={cn(
                            'bg-card min-h-[800px] shadow-sm border border-border/60 rounded-xl overflow-hidden relative',
                            viewMode === 'edit'
                              ? 'h-[calc(100vh-140px)] border-0 shadow-none bg-transparent'
                              : 'p-10 md:p-14'
                          )}
                        >
                          {/* 娌荤悊鐘舵€佹按鍗?寰界珷 */}
                          {viewMode !== 'edit' &&
                            governanceState.isModified && (
                              <div className="absolute top-0 right-0 p-4">
                                <span className="bg-accent/10 dark:bg-accent/20 text-accent dark:text-accent border border-accent/30 text-xs px-2 py-1 rounded-md font-medium shadow-sm">
                                  {t('canvas.modified')}
                                </span>
                              </div>
                            )}

                          <div data-governance-selection-root="true">
                            {contentBody}
                          </div>
                        </div>
                      </div>
                    </div>
                  </div>

                  {/* 鍙充晶锛氭不鐞嗗伐鍏烽潰鏉?(鏁村悎浜?Tabs) */}
                  <div
                    ref={panelRef}
                    className={cn(
                      'group/panel relative flex-shrink-0 border-l border-border bg-card flex flex-col transition-transform duration-200 ease-out motion-reduce:transition-none z-10 shadow-strong',
                      isPanelCollapsed ? 'w-0 border-l-0 translate-x-full' : ''
                    )}
                    style={{ width: isPanelCollapsed ? 0 : panelWidth }}
                  >
                    {/* Toolbox header — compact */}
                    <div className="flex-shrink-0 border-b border-border/60 bg-card">
                      <div className="flex items-center justify-between px-4 pt-3 pb-2 gap-2">
                        <div className="flex items-center gap-2 min-w-0">
                          <span
                            aria-hidden
                            className={cn(
                              'size-1.5 rounded-full flex-shrink-0 transition-colors',
                              TAB_COLOR_CLASSES[
                                governanceTabs.find((t) => t.id === activeTab)
                                  ?.color ?? 'info'
                              ].dot
                            )}
                          />
                          <h2 className="text-[11px] font-medium uppercase tracking-[0.16em] text-muted-foreground/85 truncate">
                            {t('panel.title')}
                          </h2>
                        </div>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-6 w-6 text-muted-foreground hover:text-muted-foreground hover:bg-muted"
                          aria-label={t('panel.collapse')}
                          title={t('panel.collapse')}
                          onClick={() => setIsPanelCollapsed(true)}
                        >
                          <PanelRightClose className="w-4 h-4 rotate-180" />
                        </Button>
                      </div>

                      {/* Token-colored tab pills */}
                      <div className="px-3 pb-2.5">
                        <div className="flex items-center gap-1 p-0.5 bg-muted/60 rounded-lg border border-border/60">
                          {governanceTabs.map((tab) => {
                            const Icon = tab.icon
                            const isActive = activeTab === tab.id
                            const palette = TAB_COLOR_CLASSES[tab.color]
                            return (
                              <button
                                key={tab.id}
                                onClick={() => setActiveTab(tab.id)}
                                className={cn(
                                  'relative flex-1 flex items-center justify-center gap-1.5 py-1.5 px-2 rounded-md text-[11px] font-medium transition-colors duration-150 motion-reduce:transition-none focus-ring-soft',
                                  isActive
                                    ? cn(
                                        'ring-1 shadow-sm bg-card',
                                        palette.icon,
                                        palette.ringStatic
                                      )
                                    : 'text-muted-foreground hover:text-foreground hover:bg-card/95'
                                )}
                                title={tab.label}
                                aria-pressed={isActive}
                              >
                                <Icon className="size-3.5" />
                                <span className="truncate">{tab.label}</span>
                                {tab.id === 'clean' &&
                                  governanceState.isModified && (
                                    <span
                                      className={cn(
                                        'absolute top-1 right-1 size-1.5 rounded-full ring-1 ring-card',
                                        palette.dot
                                      )}
                                    />
                                  )}
                              </button>
                            )
                          })}
                        </div>
                        {/* Active tool subhead — replaces the old info banner */}
                        <p className="mt-2 px-1 text-[11px] leading-snug text-muted-foreground/80 flex items-start gap-1.5">
                          <Info className="w-3 h-3 mt-0.5 flex-shrink-0 text-muted-foreground/50" />
                          <span>
                            {
                              governanceTabs.find((tab) => tab.id === activeTab)
                                ?.desc
                            }
                          </span>
                        </p>
                      </div>
                    </div>

                    {/* 宸ュ叿鍐呭鍖?*/}
                    <div
                      key={activeTab}
                      className="flex-1 overflow-y-auto overscroll-contain no-scrollbar bg-surface-2 animate-fade-in-up"
                    >
                      {activeTab === 'quality' && (
                        <QualityChecker
                          content={governanceState.originalContent}
                          initialScore={governanceState.qualityScore}
                          initialIssues={governanceState.issues}
                          onComplete={handleQualityCheck}
                        />
                      )}
                      {activeTab === 'clean' && (
                        <DataCleaner
                          content={governanceState.originalContent}
                          cleanedContent={governanceState.cleanedContent}
                          onClean={handleClean}
                        />
                      )}
                      {activeTab === 'annotate' && (
                        <DataAnnotator
                          content={governanceState.cleanedContent}
                          annotations={governanceState.annotations}
                          onAnnotate={handleAnnotate}
                          onDocumentTags={handleDocumentTags}
                        />
                      )}
                      {activeTab === 'classify' && (
                        <DataClassifier
                          content={governanceState.cleanedContent}
                          initialCategory={governanceState.category}
                          initialTags={governanceState.tags}
                          onClassify={handleClassify}
                        />
                      )}
                    </div>

                    {/* 鎷栨嫿鎵嬫焺 */}
                    <button
                      type="button"
                      className={cn(
                        'absolute left-0 top-0 w-1 h-full cursor-col-resize z-20 border-0 bg-transparent p-0 transition-colors opacity-0 hover:opacity-100 hover:bg-primary/10 dark:hover:bg-primary/20 active:bg-primary/30',
                        isPanelResizing && 'bg-primary opacity-100'
                      )}
                      aria-label={t('panel.adjustWidth')}
                      onMouseDown={startPanelResizing}
                    />
                  </div>
                </>
              ) : (
                // 绌虹姸鎬佸崰浣?
                <div className="flex-1 flex flex-col items-center justify-center bg-muted">
                  <div className="w-24 h-24 bg-card rounded-full border border-border flex items-center justify-center mb-6 shadow-sm">
                    <FileSearch className="w-10 h-10 text-muted-foreground" />
                  </div>
                  <h3 className="text-xl font-medium text-foreground mb-2">
                    {t('emptySelection.title')}
                  </h3>
                  <p className="text-muted-foreground max-w-sm text-center">
                    {t('emptySelection.description')}
                  </p>
                </div>
              )}
            </main>
          </div>

          <AlertDialog
            open={deleteFileOpen}
            onOpenChange={(open) => {
              setDeleteFileOpen(open)
              if (!open) setDeleteFileTarget(null)
            }}
          >
            <AlertDialogContent>
              <AlertDialogHeader>
                <AlertDialogTitle>
                  {t('dialogs.deleteFile.title')}
                </AlertDialogTitle>
                <AlertDialogDescription>
                  {t('dialogs.deleteFile.description', {
                    filename: deleteFileTarget?.filename || '-',
                  })}
                </AlertDialogDescription>
              </AlertDialogHeader>
              <AlertDialogFooter>
                <AlertDialogCancel>
                  {t('dialogs.deleteFile.cancel')}
                </AlertDialogCancel>
                <AlertDialogAction
                  onClick={() => {
                    const id = deleteFileTarget?.id
                    if (!id) return
                    handleDeleteFile(id)
                  }}
                >
                  {t('dialogs.deleteFile.confirm')}
                </AlertDialogAction>
              </AlertDialogFooter>
            </AlertDialogContent>
          </AlertDialog>
        </div>
      }
    />
  )
}
