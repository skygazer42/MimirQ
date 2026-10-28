/**
 * 数据治理工作台组件
 * 功能：质量检测、智能清洗、数据标注、分类归档
 */
'use client'
import { FeedbackToast } from '@/components/feedback-toast'

import { useState, useCallback, useMemo, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import { DataGovernance } from '@/components/icons'
import {
  Tag,
  FolderTree,
  FileText,
  Upload,
  Save,
  RotateCcw,
  Trash2,
  Search,
  Wrench,
  ScanLine,
  FileSearch,
  X,
  AlertTriangle,
  Check,
  ArrowLeft, ArrowRight, ChevronRight, ListChecks, Loader2, Plus, SlidersHorizontal, PanelRightOpen, PanelRightClose,
} from '@/components/icons'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { ConfirmDialog } from '@/components/ui/confirm-dialog'
import {
  AlertDialog,
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
import styles from '@/components/data-governance/governance-inbox.module.css'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { GovernanceProfileSelector } from '@/components/governance-profile-selector'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import type { DocumentPipelineOptions } from '@/types'
import { getAuthCacheScope } from '@/lib/auth-storage'
import { formatApiError } from '@/lib/api-errors'
import { useSearchParams } from 'next/navigation'
import { toast } from 'sonner'
import { useRouter } from '@/i18n/navigation'
import {
  ROOT_FOLDER_ID,
  useParsedFiles,
  type ParsedFileData,
} from '@/store/use-parsed-files-store'
import { cn, formatFileSize } from '@/lib/utils'
import { saveDocContentToCache, getDocContentFromCache } from '@/lib/doc-content-cache'
import { QualityChecker } from '@/components/data-governance/quality-checker'
import { DataCleaner } from '@/components/data-governance/data-cleaner'
import { DataAnnotator } from '@/components/data-governance/data-annotator'
import { DataClassifier } from '@/components/data-governance/data-classifier'
import { datasetApi, documentApi, parsingApi } from '@/lib/api'
import { reportClientError, reportClientWarning } from '@/lib/client-logging'
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
  { id: 'quality', icon: ScanLine, color: 'process' },
  { id: 'clean', icon: Wrench, color: 'governance' },
  { id: 'annotate', icon: Tag, color: 'knowledge' },
  { id: 'classify', icon: FolderTree, color: 'source' },
] as const

type GovernanceTab = (typeof GOVERNANCE_TAB_CONFIGS)[number]['id']
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

// 文件治理状态
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
  qualityChecked: boolean
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
  const { updateOption, setEnabled } = usePipelineOptions()
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

  // UI 状态
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
      const datasets = await datasetApi.listAll()
      return datasets.map((dataset) => ({
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
        reportClientWarning(
          'Failed to sync parsing documents for governance:',
          parsingResult.reason
        )
      }
      if (knowledgeResult.status === 'rejected') {
        reportClientWarning(
          'Failed to sync knowledge documents for governance:',
          knowledgeResult.reason
        )
      }

      if (parsingResult.status === 'rejected' && knowledgeResult.status === 'rejected') throw new Error('文档队列加载失败，请检查 API 后重试。')

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
        governanceReview: file.governanceReview,
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

  // 文件治理状态
  const [governanceStates, setGovernanceStates] = useState<
    Record<string, FileGovernanceState>
  >({})
  const [selectedChunkFileIds, setSelectedChunkFileIds] = useState<Set<string>>(
    () => new Set()
  )

  const contentScrollRef = useRef<HTMLDivElement>(null)
  const toolboxScrollRef = useRef<HTMLDivElement>(null)
  const editorRef = useRef<HTMLTextAreaElement>(null)
  const queueItemRefs = useRef(new Map<string, HTMLButtonElement>())
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [search, setSearch] = useState('')
  const [mobileReader, setMobileReader] = useState(false)
  const [configOpen, setConfigOpen] = useState(false)
  const [toolsOpen, setToolsOpen] = useState(true)
  const [batchMode, setBatchMode] = useState(false)
  const [saving, setSaving] = useState(false)
  const [saveError, setSaveError] = useState<string | null>(null)
  const [activeIssueId, setActiveIssueId] = useState<string | null>(null)
  useEffect(() => {
    setActiveIssueId(null)
    setSaveError(null)
    setViewMode('preview')
    contentScrollRef.current?.scrollTo({ top: 0 })
  }, [selectedFileId])
  useEffect(() => {
    toolboxScrollRef.current?.scrollTo({ top: 0 })
  }, [selectedFileId, activeTab])

  const scopedFiles = useMemo(() => {
    if (!selectedDatasetId) return files
    return files.filter((file) => file.datasetId === selectedDatasetId)
  }, [files, selectedDatasetId])

  // 选中的文件
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

  // 初始化文件治理状态
  const initializeGovernanceState = useCallback(
    (file: {
      id: string
      markdownContent: string
      originalMarkdownContent?: string
      governanceReview?: ParsedFileData['governanceReview']
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
          if (existing.isModified || hasAnyExistingContent || !hasIncomingContent) return prev
          return {
            ...prev,
            [file.id]: {
              ...existing,
              originalContent,
              cleanedContent,
              isModified: false,
            },
          }
        }
        return {
          ...prev,
          [file.id]: {
            id: file.id,
            originalContent,
            cleanedContent,
            annotations: file.governanceReview?.annotations || [],
            tags: file.governanceReview?.tags || [],
            category: file.governanceReview?.category || null,
            qualityScore: file.governanceReview?.qualityScore ?? 0,
            qualityChecked: file.governanceReview?.qualityScore != null,
            issues: file.governanceReview?.issues || [],
            isModified: false,
          },
        }
      })
    },
    []
  )

  const hasStoredContent = Boolean(selectedFile?.markdownContent || selectedFile?.originalMarkdownContent)
  const contentQuery = useQuery({
    queryKey: ['data-governance', 'content', selectedFile?.id, selectedFile?.source],
    enabled: Boolean(selectedFile && !hasStoredContent),
    retry: false,
    queryFn: async () => {
      const file = selectedFile!
      const cached = await getDocContentFromCache(file.id).catch(() => null)
      if (cached) return {
        id: file.id, markdownContent: cached.markdownContent,
        originalMarkdownContent: cached.originalMarkdownContent ?? cached.markdownContent,
      }
      const remote = file.source === 'knowledge_base'
        ? await documentApi.getParsedContent(file.id, { max_chars: 2_000_000 })
        : await parsingApi.getContent(file.id)
      return { id: file.id, markdownContent: remote.markdown_content ?? '',
        originalMarkdownContent: remote.original_markdown_content ?? remote.markdown_content ?? '' }
    },
  })
  useEffect(() => {
    if (!selectedFile) return
    if (hasStoredContent) initializeGovernanceState(selectedFile)
    else if (contentQuery.data?.id === selectedFile.id) initializeGovernanceState({ ...selectedFile, ...contentQuery.data })
  }, [selectedFile, hasStoredContent, contentQuery.data, initializeGovernanceState])

  const handleDeleteFile = useCallback(async (fileId: string) => {
    const target = files.find(file => file.id === fileId)
    if (!target) return
    try {
      if (target.source === 'knowledge_base') await documentApi.delete(fileId)
      else if (target.source === 'parsing_workspace') await parsingApi.delete(fileId)
      removeFile(fileId)
      setGovernanceStates(prev => { const next = { ...prev }; delete next[fileId]; return next })
      setDeleteFileOpen(false)
      toast.success(t('toasts.fileDeleted'))
    } catch (error) {
      toast.error(formatApiError(error, '删除失败，文档已保留。'))
    }
  }, [files, removeFile, t])

  // 初始化时自动选择第一个文件
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

  // 拖放处理
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }, [])

  // 上传并解析（支持 .zip 批量解压）
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
              reportClientError('Failed to extract governance ZIP upload', e)
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
          // 使用 preview 接口快速获取 Markdown
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

          // 拼接 segments 获取全文
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

          // 如果是第一个文件，则自动选中
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
        reportClientError('Failed to parse governance file', error)
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

  // 获取当前显示内容
  const displayContent = useMemo(() => {
    if (!governanceState) return ''
    return viewMode === 'original'
      ? governanceState.originalContent
      : governanceState.cleanedContent
  }, [governanceState, viewMode])

  // 文件选择
  const handleSelectFile = useCallback(
    (fileId: string) => {
      const file = scopedFiles.find((f) => f.id === fileId)
      if (file) {
        setSelectedFileId(fileId)
        initializeGovernanceState(file)
        setMobileReader(true)
      }
    },
    [scopedFiles, initializeGovernanceState]
  )

  // 手动编辑回调
  const handleManualEdit = useCallback(
    (newContent: string) => {
      if (!selectedFileId) return
      setGovernanceStates((prev) => ({
        ...prev,
        [selectedFileId]: {
          ...prev[selectedFileId],
          cleanedContent: newContent,
          isModified: true,
          qualityChecked: false,
          issues: [],
          annotations: [],
        },
      }))
    },
    [selectedFileId]
  )

  const handleQualityCheck = useCallback(
    (result: { score: number; issues: FileGovernanceState['issues'] }) => {
      if (!selectedFileId) return
      const source = governanceState?.cleanedContent
      setGovernanceStates(prev => {
        const current = prev[selectedFileId]
        if (!current || current.cleanedContent !== source) return prev
        return { ...prev, [selectedFileId]: { ...current, qualityScore: result.score, qualityChecked: true, issues: result.issues, isModified: true } }
      })
    }, [selectedFileId, governanceState?.cleanedContent]
  )
  const handleClean = useCallback((cleanedContent: string) => {
    if (!selectedFileId) return
    const source = governanceState?.cleanedContent
    setGovernanceStates(prev => {
      const current = prev[selectedFileId]
      if (!current || current.cleanedContent !== source) return prev
      return { ...prev, [selectedFileId]: { ...current, cleanedContent, isModified: true, qualityChecked: false, issues: [], annotations: [] } }
    })
  }, [selectedFileId, governanceState?.cleanedContent])

  // 标注完成回调
  const handleAnnotate = useCallback(
    (annotations: FileGovernanceState['annotations']) => {
      if (!selectedFileId) return
      const source = governanceState?.cleanedContent
      setGovernanceStates(prev => {
        const current = prev[selectedFileId]
        if (!current || current.cleanedContent !== source) return prev
        return { ...prev, [selectedFileId]: { ...current, annotations, isModified: true } }
      })
    },
    [selectedFileId, governanceState?.cleanedContent]
  )

  const handleDocumentTags = useCallback(
    (tags: string[]) => {
      if (!selectedFileId) return
      const source = governanceState?.cleanedContent
      setGovernanceStates((prev) => {
        const current = prev[selectedFileId]
        if (!current || current.cleanedContent !== source) return prev
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
    [selectedFileId, governanceState?.cleanedContent]
  )

  // 分类完成回调
  const handleClassify = useCallback(
    (category: string, tags: string[]) => {
      if (!selectedFileId) return
      const source = governanceState?.cleanedContent
      setGovernanceStates(prev => {
        const current = prev[selectedFileId]
        if (!current || current.cleanedContent !== source) return prev
        return { ...prev, [selectedFileId]: { ...current, category, tags, isModified: true } }
      })
    },
    [selectedFileId, governanceState?.cleanedContent]
  )

  // 重置文件状态
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
        qualityChecked: false,
        issues: [],
        isModified: true,
      },
    }))
  }, [selectedFileId, governanceState])

  // Save the chosen documents only; drafts in other rows remain untouched.
  const persistGovernanceEdits = useCallback(async (ids: Set<string>, submitted = false) => {
    const scope = getAuthCacheScope()
    for (const id of ids) {
      const draft = governanceStates[id]
      const file = files.find(file => file.id === id)
      if (!file) throw new Error('文档已移除，请重新选择。')
      let markdown = draft?.cleanedContent ?? file.markdownContent
      let original = draft?.originalContent ?? file.originalMarkdownContent ?? markdown
      if (!draft && !markdown) {
        const cached = await getDocContentFromCache(id, scope)
        if (!cached) throw new Error('请先打开文档，等待正文加载完成。')
        markdown = cached.markdownContent
        original = cached.originalMarkdownContent ?? markdown
      }
      // This page must observe durable failure before displaying success or navigating.
      await saveDocContentToCache({ id, markdownContent: markdown, originalMarkdownContent: original }, scope)
      if (getAuthCacheScope() !== scope || !useParsedFiles.getState().files.some(item => item.id === id)) {
        throw new Error('当前账户或文档已变更，请重新打开文档。')
      }
      await updateParsedFile(id, {
        markdownContent: markdown, originalMarkdownContent: original,
        governanceStatus: submitted ? 'submitted' : 'ready',
        chunkStatus: submitted ? 'submitted' : 'ready',
        ...(draft ? { governanceReview: {
          qualityScore: draft.qualityChecked ? draft.qualityScore : null,
          issues: draft.issues, annotations: draft.annotations, tags: draft.tags, category: draft.category,
        } } : {}),
      })
      setGovernanceStates(prev => prev[id] === draft && draft
        ? { ...prev, [id]: { ...draft, isModified: false } } : prev)
    }
  }, [files, governanceStates, updateParsedFile])

  const saveDocuments = async (continueToChunks: boolean, batch = false) => {
    if (saving) return
    const ids = batch ? new Set(selectedReadyChunkFiles.map(file => file.id)) : new Set(selectedFileId ? [selectedFileId] : [])
    if (!ids.size) return
    setSaving(true)
    setSaveError(null)
    try {
      await persistGovernanceEdits(ids, continueToChunks)
      if (continueToChunks) {
        const params = new URLSearchParams()
        if (selectedDatasetId) params.set('dataset_id', selectedDatasetId)
        router.push(params.size ? '/chunk-preview?' + params : '/chunk-preview')
      } else toast.success(t('toasts.resultsSaved'))
    } catch (error) {
      setSaveError(formatApiError(error, '无法写入治理结果，请重试'))
    } finally { setSaving(false) }
  }

  const queueFiles = visibleFiles.filter(file => file.filename.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()))
  const statusFor = (file: ParsedFileData) => {
    const draft = governanceStates[file.id]
    const score = draft ? (draft.qualityChecked ? draft.qualityScore : null) : file.governanceReview?.qualityScore
    const issues = draft?.issues ?? file.governanceReview?.issues ?? []
    if (file.status === 'error') return { id: 'error', label: '解析失败', tone: styles.danger, score }
    if (file.status === 'pending' || file.status === 'parsing') return { id: 'processing', label: file.status === 'parsing' ? '解析中' : '等待解析', tone: styles.info, score }
    if (draft?.isModified) return { id: 'review', label: '待核对', tone: styles.warning, score }
    if (issues.length) return { id: 'review', label: '待核对', tone: styles.warning, score }
    if (file.governanceStatus === 'ready' || file.governanceStatus === 'submitted' || file.chunkStatus === 'ready' || file.chunkStatus === 'submitted') return { id: 'done', label: '已完成', tone: styles.success, score }
    if (score != null) return { id: 'review', label: '待核对', tone: styles.warning, score }
    return { id: 'pending', label: '待治理', tone: '', score: null }
  }
  const loadingContent = Boolean(selectedFile && !hasStoredContent && contentQuery.isPending)
  const contentError = !hasStoredContent && contentQuery.isError
  const canUseContent = Boolean(governanceState && !loadingContent && !contentError)
  const hasText = canUseContent && Boolean(governanceState?.cleanedContent.trim())
  const currentIndex = queueFiles.findIndex(file => file.id === selectedFileId)
  const activeIssue = governanceState?.issues.find(issue => issue.id === activeIssueId)
  const currentStatus = selectedFile ? statusFor(selectedFile) : null
  const nextFile = () => {
    const next = queueFiles[(currentIndex + 1) % queueFiles.length]
    if (next) handleSelectFile(next.id)
  }
  const returnToQueue = () => {
    setMobileReader(false)
    requestAnimationFrame(() => { if (selectedFileId) queueItemRefs.current.get(selectedFileId)?.focus() })
  }
  const locateIssue = (issue: FileGovernanceState['issues'][number]) => {
    setActiveIssueId(issue.id)
    if (!issue.position) return
    setViewMode('edit')
    requestAnimationFrame(() => {
      editorRef.current?.focus()
      editorRef.current?.setSelectionRange(issue.position!.start, issue.position!.end)
      editorRef.current?.scrollIntoView({ block: 'nearest', behavior: 'auto' })
    })
  }

  return (
    <div className={styles.page} data-governance-workbench onDragOver={handleDragOver} onDragLeave={handleDragLeave} onDrop={handleDrop}>
      <header className={styles.header}>
        <div className={styles.title}><DataGovernance appearance="color" className="size-6" /><div><h1>{headerTitle}</h1><p className={styles.subtitle}>{t('header.workspaceSubtitle')}</p></div></div>
        <div className={styles.headerActions}>
          <Button variant="ghost" size="sm" aria-label="治理配置" onClick={() => setConfigOpen(true)}><SlidersHorizontal className="size-4" /><span className={styles.actionLabel}>治理配置</span></Button>
          {uploading ? <Button variant="outline" size="sm" onClick={cancelUploadAndParse}><Loader2 className={styles.spinner} />取消解析</Button> : <Button variant="outline" size="sm" disabled={saving} onClick={() => fileInputRef.current?.click()}><Plus className="size-4" />添加文档</Button>}
          <input ref={fileInputRef} type="file" multiple accept={UPLOAD_ACCEPT_WITH_ZIP} onChange={handleFileSelect} className="hidden" aria-label="上传治理文档" />
        </div>
      </header>
      <div className={styles.workspace} data-mobile-reader={mobileReader}>
        <aside className={styles.queue} data-governance-queue aria-label="文档队列">
          <div className={styles.queueHeading}>
            <h2>文档目录</h2><span className={styles.count}>{visibleFiles.length}</span>
            <div className={styles.queueActions}>
              <Button variant="ghost" size="icon" className="size-7" aria-label="批量选择切块文档" aria-pressed={batchMode} onClick={() => { setBatchMode(value => !value); setSelectedChunkFileIds(new Set()) }}><ListChecks className="size-3.5" /></Button>
            </div>
          </div>
          <div className={styles.queueFilters}>
            <Select value={selectedDatasetId || ALL_DATASETS_VALUE} onValueChange={handleDatasetScopeChange} disabled={uploading || saving}>
              <SelectTrigger className={styles.scope} aria-label="数据集范围"><SelectValue placeholder="全部数据集" /></SelectTrigger>
              <SelectContent><SelectItem value={ALL_DATASETS_VALUE}>全部数据集</SelectItem>{availableDatasets.map(dataset => <SelectItem key={dataset.id} value={dataset.id}>{dataset.name}</SelectItem>)}</SelectContent>
            </Select>
            <div className={styles.search}><Search /><input type="search" aria-label="搜索治理文档" placeholder="搜索文件名" value={search} onChange={event => setSearch(event.target.value)} />{search && <button type="button" aria-label="清除文档搜索" onClick={() => setSearch('')}><X className="size-3" /></button>}</div>
          </div>
          <div className={styles.folderTree}><DocumentFolderTree /></div>
          <div className={styles.fileListHeading}><span>文件</span><span>{queueFiles.length}</span></div>
          {documentSyncQuery.isError && <div className={styles.inlineError} role="alert"><span>队列加载失败</span><Button size="sm" variant="ghost" onClick={() => void documentSyncQuery.refetch()}>重试</Button></div>}
          <div className={styles.queueScroll}>
            {!isLoaded || (documentSyncQuery.isPending && !visibleFiles.length) ? <div className={styles.emptySmall} role="status">正在加载文档…</div> : !queueFiles.length ? (
              <div className={styles.emptySmall}>{search ? '没有找到匹配的文档' : '当前范围没有文档'}{search && <Button size="sm" variant="link" onClick={() => setSearch('')}>清除搜索</Button>}</div>
            ) : queueFiles.map(file => {
                  const status = statusFor(file)
                  return <div className={styles.queueEntry} key={file.id}>
                    {batchMode && <input type="checkbox" aria-label={'选择切块文档 ' + file.filename} disabled={file.chunkStatus !== 'ready' || saving} checked={selectedChunkFileIds.has(file.id)} onChange={() => toggleChunkFileSelection(file.id)} />}
                    <button type="button" className={styles.queueItem} disabled={saving} ref={node => { if (node) queueItemRefs.current.set(file.id, node); else queueItemRefs.current.delete(file.id) }} aria-current={selectedFileId === file.id} data-governance-file={file.id} onClick={() => handleSelectFile(file.id)}>
                      {getFileIcon(file.filename, 'size-5')}<span className={styles.queueItemText}><strong className={styles.queueName} title={file.filename}>{file.filename}</strong><span className={styles.queueMeta}><span>{formatFileSize(file.fileSize)}</span><span className={status.score == null ? status.tone : status.score >= 80 ? styles.success : status.score >= 60 ? styles.warning : styles.danger}>{status.score != null ? status.score + ' 分' : status.label}</span></span></span>
                    </button>
                  </div>
            })}
          </div>
          <div className={styles.queueFooter}>
            {batchMode ? <><span>已选 {selectedReadyChunkCount} 份已保存文档</span><Button variant="ghost" size="sm" disabled={!selectedReadyChunkCount || saving} onClick={() => void saveDocuments(true, true)}>切块<ArrowRight className="size-3" /></Button></> : <><span>已保存</span><span>{queueFiles.filter(file => statusFor(file).id === 'done').length} / {queueFiles.length} 份</span></>}
          </div>
        </aside>
        <main className={styles.reader} data-governance-reader aria-label="文档治理工作区">
          {selectedFile && governanceState ? (
            <>
              <div className={styles.mobileDocumentHeading}>
                <Button size="icon" variant="ghost" className="size-8" aria-label="返回文档队列" onClick={returnToQueue}><ArrowLeft className="size-4" /></Button>
                <strong title={selectedFile.filename}>{selectedFile.filename}</strong>
              </div>
              <div className={styles.reviewColumns} data-tools-open={toolsOpen}>
                <section className={styles.documentPane} aria-label="文档正文">
              <div className={styles.fileHeading}>
                <span className={styles.fileIcon}>{getFileIcon(selectedFile.filename, 'size-6')}</span>
                <div className={styles.fileIdentity}><div className={styles.fileTitle}><h2 title={selectedFile.filename}>{selectedFile.filename}</h2><span className={cn(styles.status, currentStatus?.tone)}><i className={styles.dot} aria-hidden />{currentStatus?.label}</span></div><div className={styles.fileMeta}><span>{selectedFile.datasetName || (selectedFile.source === 'knowledge_base' ? '知识库' : '解析文档')}</span><span>{formatFileSize(selectedFile.fileSize)}</span>{canUseContent && <span>{governanceState.cleanedContent.length.toLocaleString()} 字</span>}</div></div>
                <div className={styles.fileActions}>
                  <ConfirmDialog title="重置当前修改？" description="将恢复解析原文，并清除本次检测、标注和分类。重置后仍需保存。" confirmLabel="重置" cancelLabel="取消" onConfirm={handleReset}><Button variant="ghost" size="icon" className="size-8" aria-label="重置文档修改" disabled={!canUseContent || saving}><RotateCcw className="size-3.5" /></Button></ConfirmDialog>
                  <Button variant="ghost" size="icon" className="size-8" aria-label="删除当前文档" disabled={saving} onClick={() => { setDeleteFileTarget({ id: selectedFile.id, filename: selectedFile.filename }); setDeleteFileOpen(true) }}><Trash2 className="size-3.5" /></Button>
                </div>
              </div>
              <div className={styles.readerScroll} ref={contentScrollRef}>
                {loadingContent ? <div className={styles.empty} role="status"><Loader2 className={styles.spinner} /><p>正在加载正文…</p></div> : contentError ? <div className={styles.empty} role="alert"><AlertTriangle /><h3>正文加载失败</h3><p>{formatApiError(contentQuery.error, '请确认文档已经解析，再重试。')}</p><Button size="sm" variant="outline" onClick={() => void contentQuery.refetch()}>重新加载正文</Button></div> : (
                  <>
                    <div className={styles.documentToolbar}>
                      <span><FileText />{viewMode === 'original' ? '原文' : viewMode === 'edit' ? '编辑 Markdown' : '正文预览'}</span>
                      <div className={styles.viewActions} aria-label="正文显示方式">
                        <button type="button" aria-pressed={viewMode === 'preview'} onClick={() => setViewMode('preview')}>预览</button>
                        <button type="button" aria-pressed={viewMode === 'original'} onClick={() => setViewMode('original')}>原文</button>
                        <button type="button" disabled={saving} aria-pressed={viewMode === 'edit'} onClick={() => setViewMode('edit')}>编辑</button>
                        {viewMode !== 'edit' && <button type="button" aria-pressed={previewFormat === 'markdown'} onClick={() => setPreviewFormat(value => value === 'rendered' ? 'markdown' : 'rendered')}>Markdown</button>}
                      </div>
                    </div>
                    <div className={styles.document} data-governance-selection-root="true" data-governance-document>
                      {viewMode === 'edit' ? <textarea ref={editorRef} aria-label="编辑文档正文" value={displayContent} onChange={event => handleManualEdit(event.target.value)} disabled={saving} className={styles.editor} spellCheck={false} /> : !displayContent ? <div className={styles.empty}><FileText /><h3>文档正文为空</h3><p>可切换到编辑模式补充内容，或重新解析原文件。</p></div> : previewFormat === 'markdown' ? <pre className={styles.raw}>{displayContent}</pre> : <MarkdownRenderer markdown={displayContent} />}
                    </div>
                  </>
                )}
              </div>
                </section>
                <aside className={styles.toolbox} data-governance-tools aria-label="治理工具箱">
                  <div className={styles.toolboxHeading}>
                    <h2>治理工具</h2>
                    <Button variant="ghost" size="icon" className="size-8" aria-label={toolsOpen ? '收起治理工具' : '展开治理工具'} aria-expanded={toolsOpen} aria-controls="governance-tools-content" onClick={() => setToolsOpen(value => !value)}>{toolsOpen ? <PanelRightClose className="size-4" /> : <PanelRightOpen className="size-4" />}</Button>
                  </div>
                  <div className={styles.toolboxContent} id="governance-tools-content" hidden={!toolsOpen}>
                    <div className={styles.tabs} role="tablist" aria-label="治理工具">
                      {governanceTabs.map((tab, index) => { const Icon = tab.icon; return <button type="button" key={tab.id} id={'governance-tab-' + tab.id} role="tab" data-tone={tab.color} aria-selected={activeTab === tab.id} aria-controls="governance-tool-panel" tabIndex={activeTab === tab.id ? 0 : -1} onClick={() => setActiveTab(tab.id)} onKeyDown={event => {
                        if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
                        event.preventDefault()
                        const next = event.key === 'Home' ? 0 : event.key === 'End' ? governanceTabs.length - 1 : (index + (event.key === 'ArrowRight' ? 1 : -1) + governanceTabs.length) % governanceTabs.length
                        setActiveTab(governanceTabs[next].id)
                        document.getElementById('governance-tab-' + governanceTabs[next].id)?.focus()
                      }}><Icon />{tab.label}</button> })}
                    </div>
                    <div className={styles.toolboxScroll} ref={toolboxScrollRef} id="governance-tool-panel" role="tabpanel" aria-labelledby={'governance-tab-' + activeTab}>
                      {canUseContent ? <fieldset disabled={saving} className={styles.tools} key={selectedFile.id + ':' + activeTab}>
                        {activeTab === 'quality' && <QualityChecker content={governanceState.cleanedContent} initialScore={governanceState.qualityScore} initialIssues={governanceState.issues} checked={governanceState.qualityChecked} disabled={saving || !hasText} onComplete={handleQualityCheck} activeIssueId={activeIssueId} onSelectIssue={issue => setActiveIssueId(issue.id)} onCleanRequest={() => setActiveTab('clean')} />}
                        {activeTab === 'clean' && <DataCleaner content={governanceState.cleanedContent} cleanedContent={governanceState.cleanedContent} onClean={handleClean} disabled={saving || !hasText} onConfigure={() => setConfigOpen(true)} />}
                        {activeTab === 'annotate' && <DataAnnotator content={governanceState.cleanedContent} annotations={governanceState.annotations} onAnnotate={handleAnnotate} onDocumentTags={handleDocumentTags} />}
                        {activeTab === 'classify' && <DataClassifier content={governanceState.cleanedContent} initialCategory={governanceState.category} initialTags={governanceState.tags} onClassify={handleClassify} />}
                        {activeTab === 'quality' && activeIssue && <div className={styles.issueDetail}><p>{activeIssue.message}</p>{activeIssue.position && <pre>{governanceState.cleanedContent.slice(Math.max(0, activeIssue.position.start - 45), Math.min(governanceState.cleanedContent.length, activeIssue.position.end + 100))}</pre>}<div className={styles.issueDetailActions}>{activeIssue.position && <Button size="sm" variant="ghost" onClick={() => locateIssue(activeIssue)}><Search className="size-3" />定位到正文</Button>}<Button size="sm" variant="ghost" disabled={saving} onClick={() => { setGovernanceStates(prev => ({ ...prev, [selectedFile.id]: { ...prev[selectedFile.id], issues: prev[selectedFile.id].issues.filter(issue => issue.id !== activeIssue.id), isModified: true } })); setActiveIssueId(null) }}>忽略此项</Button><Button size="sm" variant="outline" onClick={() => setActiveTab('clean')}><Wrench className="size-3" />清洗文档</Button></div></div>}
                      </fieldset> : <div className={styles.emptySmall}>{loadingContent ? '正在加载正文…' : '正文加载后可使用治理工具'}</div>}
                    </div>
                  </div>
                </aside>
              </div>
              <FeedbackToast type="error" message={saveError ? `保存失败：${saveError}。修改内容已保留。` : null} id="governance-save-feedback" />
              <footer className={styles.footer}>
                <span className={styles.saveState} role="status">{saving ? <Loader2 className={styles.spinner} /> : governanceState.isModified ? <span className={cn(styles.dot, styles.warning)} /> : <Check className="size-3.5" />}{saving ? '正在保存…' : governanceState.isModified ? '修改尚未保存' : selectedFile.governanceStatus === 'ready' || selectedFile.governanceStatus === 'submitted' ? '治理结果已保存' : '等待检查文档'}</span>
                <div className={styles.footerActions}><Button size="sm" variant="ghost" onClick={nextFile} disabled={queueFiles.length < 2 || saving}>下一份<ChevronRight className="size-3.5" /></Button><Button size="sm" variant="outline" onClick={() => void saveDocuments(false)} disabled={!canUseContent || saving}><Save className="size-3.5" />保存</Button><Button size="sm" onClick={() => void saveDocuments(true)} disabled={!hasText || saving}>保存并继续切块<ArrowRight className="size-3.5" /></Button></div>
              </footer>
            </>
          ) : <div className={styles.empty}><FileSearch /><h2>{documentSyncQuery.isPending || !isLoaded ? '正在加载文档…' : '选择需要治理的文档'}</h2><p>从左侧队列打开文档，或添加文档后开始检测和清洗。</p><Button size="sm" variant="outline" onClick={() => fileInputRef.current?.click()} disabled={uploading}><Plus className="size-4" />添加文档</Button></div>}
        </main>
      </div>
      <Sheet open={configOpen} onOpenChange={setConfigOpen}><SheetContent className={styles.configSheet}><SheetHeader className={styles.configHeader}><SheetTitle>治理配置</SheetTitle><SheetDescription>选择治理预设，调整当前使用的清洗规则。</SheetDescription></SheetHeader><div className={styles.configBody}><section className={styles.configGroup}><h3>治理预设</h3><GovernanceProfileSelector compact onApplyPatch={patch => { setEnabled(true); for (const key of Object.keys(patch) as Array<keyof DocumentPipelineOptions>) { const value = patch[key]; if (value !== undefined) updateOption(key, value) } }} /></section><section className={styles.configGroup}><h3>清洗规则</h3><PipelineOptionsPanel compact showJsonToolbar showIndexingControls={false} /></section></div></SheetContent></Sheet>
      <AlertDialog open={deleteFileOpen} onOpenChange={setDeleteFileOpen}><AlertDialogContent><AlertDialogHeader><AlertDialogTitle>{t('dialogs.deleteFile.title')}</AlertDialogTitle><AlertDialogDescription>{t('dialogs.deleteFile.description', { filename: deleteFileTarget?.filename || '' })}</AlertDialogDescription></AlertDialogHeader><AlertDialogFooter><AlertDialogCancel>{t('dialogs.deleteFile.cancel')}</AlertDialogCancel><Button variant="destructive" onClick={() => { if (deleteFileTarget) void handleDeleteFile(deleteFileTarget.id) }}>{t('dialogs.deleteFile.confirm')}</Button></AlertDialogFooter></AlertDialogContent></AlertDialog>
      {isDragging && <div className={styles.dropOverlay}><Upload className="mx-auto size-8" /><strong>松开以添加并解析文档</strong><span className="text-sm text-muted-foreground">PDF、Word、Excel、TXT、Markdown 或 ZIP</span></div>}
    </div>
  )
}
