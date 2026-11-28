/**
 * 数据治理工作台组件
 * 功能：质量检测、智能清洗、数据标注、分类归档
 */
'use client'
import { FeedbackToast } from '@/components/feedback-toast'

import { useState, useCallback, useMemo, useEffect, useRef } from 'react'
import { useQuery } from '@tanstack/react-query'
import {
  BarChart3,
  Copy,
  ExternalLink,
  FolderOpen,
  Layers,
  Shield,
  Table2,
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
  ArrowLeft,
  ArrowRight,
  ChevronDown,
  ChevronRight,
  ListChecks,
  Loader2,
  Plus,
  SlidersHorizontal,
  PanelRightOpen,
  PanelRightClose,
} from '@/components/icons'
import { useTranslations } from 'next-intl'
import { Button } from '@/components/ui/button'
import { PageTitleIcon } from '@/components/ui/page-title-icon'
import { WorkbenchPanelDialog } from '@/components/workbench'
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
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import styles from '@/components/data-governance/governance-inbox.module.css'
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from '@/components/ui/sheet'
import { PipelineOptionsPanel } from '@/components/pipeline-options-panel'
import { GovernanceProfileSelector } from '@/components/governance-profile-selector'
import { usePipelineOptions } from '@/contexts/pipeline-options-context'
import type { DocumentPipelineOptions } from '@/types'
import { getAuthCacheScope } from '@/lib/auth-storage'
import { formatApiError } from '@/lib/api-errors'
import { listDocumentPages } from '@/lib/api/document-pages'
import { assertCompleteDocumentContent, hasParsedFileMemoryContent, mergeDocumentLibrary } from '@/lib/document-library'
import { useSearchParams } from 'next/navigation'
import { toast } from 'sonner'
import { useRouter } from '@/i18n/navigation'
import { ROOT_FOLDER_ID, useParsedFiles, type ParsedFileData } from '@/store/use-parsed-files-store'
import { cn, formatFileSize } from '@/lib/utils'
import { getDocContentFromCache } from '@/lib/doc-content-cache'
import { QualityChecker } from '@/components/data-governance/quality-checker'
import { DataCleaner } from '@/components/data-governance/data-cleaner'
import { DataAnnotator } from '@/components/data-governance/data-annotator'
import { DataClassifier } from '@/components/data-governance/data-classifier'
import { GovernanceEmptyPresets } from '@/components/data-governance/governance-empty-presets'
import { datasetApi } from '@/lib/api/datasets'
import { queryKeys } from '@/lib/query-keys'
import { documentApi } from '@/lib/api/documents'
import { parsingApi } from '@/lib/api/parsing'
import { reportClientError } from '@/lib/client-logging'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { MarkdownRenderer } from '@/components/markdown/markdown-renderer'

import { DocumentFolderTree, getFileIcon } from '@/components/document-library/folder-tree'
import { extractZipFiles, isZipFile } from '@/lib/zip'
import { UPLOAD_ACCEPT_WITH_ZIP, ZIP_ALLOWED_EXTENSIONS } from '@/lib/upload-extensions'
import { getParserLabel } from '@/lib/parser-options'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'

const GOVERNANCE_TAB_CONFIGS = [
  { id: 'quality', icon: ScanLine, color: 'process' },
  { id: 'clean', icon: Wrench, color: 'governance' },
  { id: 'annotate', icon: Tag, color: 'knowledge' },
  { id: 'classify', icon: FolderTree, color: 'source' },
] as const

type GovernanceTab = (typeof GOVERNANCE_TAB_CONFIGS)[number]['id']
type GovernanceDocument = Awaited<ReturnType<typeof documentApi.list>>['items'][number]
type GovernanceParsingDocument = Awaited<ReturnType<typeof parsingApi.listDocuments>>['items'][number]

const ALL_DATASETS_VALUE = '__all_datasets__'

function getAllowedUploadFileType(filename: string): string | undefined {
  const extensionStart = filename.lastIndexOf('.')
  if (extensionStart === -1) return undefined
  const extension = filename.slice(extensionStart + 1).toLowerCase()
  return ZIP_ALLOWED_EXTENSIONS.has(extension) ? extension : undefined
}

function normalizeBackendCandidate(value: unknown): string {
  return typeof value === 'string' && value.trim() ? value.trim() : ''
}

function mapBackendStatusToGovernanceStatus(status: unknown): ParsedFileData['status'] {
  const normalized = typeof status === 'string' ? status.trim().toLowerCase() : ''
  if (['completed', 'complete', 'ready', 'parsed', 'done', 'success'].includes(normalized)) return 'parsed'
  if (['processing', 'parsing', 'running'].includes(normalized)) return 'parsing'
  if (['failed', 'failure', 'error', 'cancelled', 'quarantined'].includes(normalized)) return 'error'
  return 'pending'
}

function isParsingWorkspaceDocument(doc: GovernanceDocument): boolean {
  const meta = doc.metadata
  return meta?.workspace === 'parsing'
}

function mapKnowledgeDocumentToGovernanceFile(
  doc: GovernanceDocument,
  existing: ParsedFileData | undefined,
  datasetNameById: Map<string, string>,
): ParsedFileData {
  const meta = doc.metadata
  const backendCandidate =
    normalizeBackendCandidate(meta?.parser_backend) ||
    normalizeBackendCandidate(meta?.parser_backend_requested) ||
    'auto'
  const resolved = resolveParserBackendForFilename(doc.filename, backendCandidate)
  const backend = resolved.backend || backendCandidate
  const datasetId = doc.dataset_id || null

  return {
    ...existing,
    id: doc.id,
    filename: doc.filename,
    fileType: doc.file_type,
    fileSize: doc.file_size,
    markdownContent: existing === undefined ? '' : existing.markdownContent,
    originalMarkdownContent: existing?.originalMarkdownContent,
    parsedAt: doc.updated_at,
    parser: getParserLabel(backend),
    parserBackend: backend,
    folderId: existing?.folderId ?? ROOT_FOLDER_ID,
    datasetId,
    datasetName: datasetId ? datasetNameById.get(datasetId) || datasetId : null,
    source: 'knowledge_base',
    sourcePath: typeof meta?.source_path === 'string' ? meta.source_path : null,
    status: mapBackendStatusToGovernanceStatus(doc.status),
    error: doc.error_message === null ? undefined : doc.error_message,
  }
}

function mapParsingDocumentToGovernanceFile(
  doc: GovernanceParsingDocument,
  existing: ParsedFileData | undefined,
): ParsedFileData {
  const meta = doc.metadata
  const backendCandidate =
    normalizeBackendCandidate(meta?.parser_backend) ||
    normalizeBackendCandidate(meta?.parser_backend_requested) ||
    'auto'
  const resolved = resolveParserBackendForFilename(doc.filename, backendCandidate)
  const backend = resolved.backend || backendCandidate

  return {
    ...existing,
    id: doc.id,
    filename: doc.filename,
    fileType: doc.file_type,
    fileSize: doc.file_size,
    markdownContent: existing === undefined ? '' : existing.markdownContent,
    originalMarkdownContent: existing?.originalMarkdownContent,
    parsedAt: doc.updated_at,
    parser: getParserLabel(backend),
    parserBackend: backend,
    folderId: existing?.folderId ?? ROOT_FOLDER_ID,
    datasetId: doc.dataset_id || null,
    datasetName: null,
    source: 'parsing_workspace',
    status: mapBackendStatusToGovernanceStatus(doc.status),
    error: doc.error_message === null ? undefined : doc.error_message,
  }
}

// 文件治理状态
type GovernanceReview = NonNullable<ParsedFileData['governanceReview']>

type FileGovernanceState = {
  id: string
  originalContent: string
  cleanedContent: string
  contentLoaded: boolean
  annotations: GovernanceReview['annotations']
  tags: string[]
  category: string | null
  qualityScore: number
  qualityChecked: boolean
  issues: GovernanceReview['issues']
  isModified: boolean
  resetRevision: number
}

const STANDBY_CLEANING_RULES = [
  {
    key: 'governance_remove_noise_lines',
    icon: FileText,
    title: '去除噪声行',
    description: '识别并移除页眉、页脚、页码等与正文无关的内容',
  },
  {
    key: 'governance_unwrap_lines',
    icon: ScanLine,
    title: '修正断行与段落',
    description: '合并不合理的断行，重建段落结构并提升文本连贯性',
  },
  {
    key: 'governance_normalize_tables',
    icon: Table2,
    title: '规范表格结构',
    description: '识别并保留表格内容，维持行列结构与单元格关系',
  },
  {
    key: 'governance_drop_duplicate_paragraphs',
    icon: Copy,
    title: '检测重复内容',
    description: '识别文档内的重复段落或重复片段，避免冗余数据入库',
  },
  {
    key: 'governance_pii_anonymize',
    icon: Shield,
    title: '敏感信息脱敏',
    description: '自动识别并脱敏邮箱、电话等 PII 敏感字段',
  },
] as const satisfies ReadonlyArray<{
  key: keyof DocumentPipelineOptions
  icon: typeof FileText
  title: string
  description: string
}>

export function DataGovernancePanel() {
  const t = useTranslations('DataGovernancePanel')
  const { options, updateOption, setEnabled } = usePipelineOptions()
  const router = useRouter()
  const searchParams = useSearchParams()
  const files = useParsedFiles((state) => state.files)
  const libraryFolders = useParsedFiles((state) => state.folders)
  const activeFolderId = useParsedFiles((state) => state.activeFolderId)
  const setActiveFolderId = useParsedFiles((state) => state.setActiveFolderId)
  const createFolder = useParsedFiles((state) => state.createFolder)
  const isLoaded = useParsedFiles((state) => state.isLoaded)
  const loadError = useParsedFiles((state) => state.loadError)
  const addParsedFile = useParsedFiles((state) => state.addParsedFile)
  const setParsedFiles = useParsedFiles((state) => state.setParsedFiles)
  const updateParsedFile = useParsedFiles((state) => state.updateParsedFile)
  const removeFile = useParsedFiles((state) => state.removeFile)
  const { parserBackend } = useParserBackendPreference()

  // UI 状态
  const [activeTab, setActiveTab] = useState<GovernanceTab>('quality')
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<'edit' | 'preview' | 'original'>('preview')
  const [previewFormat, setPreviewFormat] = useState<'rendered' | 'markdown'>('rendered')
  const [isDragging, setIsDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [deleteFileOpen, setDeleteFileOpen] = useState(false)
  const [deleteFileTarget, setDeleteFileTarget] = useState<{
    id: string
    filename: string
  } | null>(null)
  const requestedDatasetId = searchParams.get('dataset_id')?.trim()
  const inboundDatasetId = requestedDatasetId ? requestedDatasetId : null
  const [selectedDatasetId, setSelectedDatasetId] = useState(inboundDatasetId)
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
    [t],
  )

  useEffect(() => {
    return () => {
      uploadAbortRef.current?.abort()
    }
  }, [])

  useEffect(() => {
    const requestedTab = searchParams.get('tab')?.trim()
    const tab = GOVERNANCE_TAB_CONFIGS.find(({ id }) => id === requestedTab)
    if (tab !== undefined) setActiveTab(tab.id)
  }, [searchParams])

  useEffect(() => {
    setSelectedDatasetId(inboundDatasetId)
    setActiveFolderId(ROOT_FOLDER_ID)
    setSelectedFileId(null)
  }, [inboundDatasetId, setActiveFolderId])

  const datasetsQuery = useQuery({
    queryKey: queryKeys.datasets.exhaustive(),
    enabled: isLoaded,
    queryFn: ({ signal }) => datasetApi.listAll(undefined, { signal }),
    select: (datasets) => datasets.map((dataset) => ({ id: dataset.id, name: dataset.name || dataset.id })),
  })

  const availableDatasets = useMemo(() => datasetsQuery.data ?? [], [datasetsQuery.data])
  const datasetNameById = useMemo(
    () => new Map(availableDatasets.map((dataset) => [dataset.id, dataset.name])),
    [availableDatasets],
  )
  const datasetNameSignature = useMemo(
    () => availableDatasets.map((dataset) => `${dataset.id}:${dataset.name}`).join('|'),
    [availableDatasets],
  )
  const selectedDatasetName = selectedDatasetId ? datasetNameById.get(selectedDatasetId) || selectedDatasetId : null
  const documentSyncQuery = useQuery({
    queryKey: ['data-governance', 'library-snapshot', datasetNameSignature],
    enabled: isLoaded,
    queryFn: async ({ signal }) => {
      const knownFiles = new Map(useParsedFiles.getState().files.map((file) => [file.id, file]))
      const [parsingResult, knowledgeResult] = await Promise.allSettled([
        listDocumentPages((skip) => parsingApi.listDocuments({ skip, limit: 200 }, { signal }), signal).then(
          (documents) => documents.map((doc) => mapParsingDocumentToGovernanceFile(doc, knownFiles.get(doc.id))),
        ),
        listDocumentPages((skip) => documentApi.list({ skip, limit: 200 }, { signal }), signal).then((documents) =>
          documents
            .filter((doc) => !isParsingWorkspaceDocument(doc))
            .map((doc) => mapKnowledgeDocumentToGovernanceFile(doc, knownFiles.get(doc.id), datasetNameById)),
        ),
      ])
      signal.throwIfAborted()
      const errors: unknown[] = []
      if (parsingResult.status === 'rejected') errors.push(parsingResult.reason)
      if (knowledgeResult.status === 'rejected') errors.push(knowledgeResult.reason)
      return {
        knownFiles,
        parsingResult,
        knowledgeResult,
        error: errors.length === 0 ? null : new AggregateError(errors, '文档队列同步失败，已保留可用记录'),
      }
    },
  })

  useEffect(() => {
    if (!isLoaded || documentSyncQuery.isFetching || documentSyncQuery.data === undefined) return
    const current = useParsedFiles.getState().files
    const merged = mergeDocumentLibrary(current, documentSyncQuery.data)
    if (merged !== current) setParsedFiles(merged)
  }, [documentSyncQuery.data, documentSyncQuery.isFetching, isLoaded, setParsedFiles])

  const documentSyncError =
    documentSyncQuery.error === null && documentSyncQuery.data !== undefined
      ? documentSyncQuery.data.error
      : documentSyncQuery.error

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
    [router, searchParams, setActiveFolderId],
  )

  const cancelUploadAndParse = useCallback(() => {
    uploadAbortRef.current?.abort()
    uploadAbortRef.current = null
    setUploading(false)
    toast.info(t('toasts.uploadCancelled'))
  }, [t])

  // 文件治理状态
  const [governanceStates, setGovernanceStates] = useState<Record<string, FileGovernanceState>>({})
  const [selectedChunkFileIds, setSelectedChunkFileIds] = useState<Set<string>>(() => new Set())

  const contentScrollRef = useRef<HTMLDivElement>(null)
  const toolboxScrollRef = useRef<HTMLDivElement>(null)
  const editorRef = useRef<HTMLTextAreaElement>(null)
  const qualityScanRef = useRef<HTMLButtonElement>(null)
  const directoryTriggerRef = useRef<HTMLButtonElement>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const [search, setSearch] = useState('')
  const [directoryOpen, setDirectoryOpen] = useState(false)
  const handleDirectoryOpenChange = useCallback((open: boolean) => {
    setDirectoryOpen(open)
    if (!open) requestAnimationFrame(() => directoryTriggerRef.current?.focus())
  }, [])
  const [mobilePane, setMobilePane] = useState<'document' | 'tools'>('document')
  const [configOpen, setConfigOpen] = useState(false)
  const [toolsOpen, setToolsOpen] = useState(true)
  const [batchMode, setBatchMode] = useState(false)
  const [saving, setSaving] = useState(false)
  const [qualityScanning, setQualityScanning] = useState(false)
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
  const governanceState = selectedFileId ? governanceStates[selectedFileId] : null

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

    return scopedFiles.filter((f) => allowedFolderIds.has(f.folderId || ROOT_FOLDER_ID))
  }, [scopedFiles, activeFolderId, libraryFolders])

  const readyChunkFiles = useMemo(() => visibleFiles.filter((file) => file.chunkStatus === 'ready'), [visibleFiles])
  const selectedReadyChunkFiles = useMemo(
    () => readyChunkFiles.filter((file) => selectedChunkFileIds.has(file.id)),
    [readyChunkFiles, selectedChunkFileIds],
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
      contentLoaded?: true
      governanceReview?: ParsedFileData['governanceReview']
    }) => {
      const originalContent = file.originalMarkdownContent ?? file.markdownContent
      const cleanedContent = file.markdownContent
      const contentLoaded = hasParsedFileMemoryContent(file)
      setGovernanceStates((prev) => {
        const existing = prev[file.id]
        if (existing) {
          if (existing.isModified || existing.contentLoaded || !contentLoaded) return prev
          return {
            ...prev,
            [file.id]: {
              ...existing,
              originalContent,
              cleanedContent,
              contentLoaded,
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
            contentLoaded,
            annotations: file.governanceReview?.annotations ?? [],
            tags: file.governanceReview?.tags ?? [],
            category: file.governanceReview?.category ?? null,
            qualityScore: file.governanceReview?.qualityScore ?? 0,
            qualityChecked: file.governanceReview?.qualityScore != null,
            issues: file.governanceReview?.issues ?? [],
            isModified: false,
            resetRevision: 0,
          },
        }
      })
    },
    [],
  )

  const hasStoredContent = selectedFile !== null && hasParsedFileMemoryContent(selectedFile)
  const contentQuery = useQuery({
    queryKey: ['data-governance', 'content', selectedFile?.id, selectedFile?.source],
    enabled: Boolean(selectedFile && !hasStoredContent && !governanceState?.contentLoaded),
    retry: false,
    queryFn: async () => {
      const file = selectedFile!
      const cached = await getDocContentFromCache(file.id)
      if (cached)
        return {
          id: file.id,
          markdownContent: cached.markdownContent,
          originalMarkdownContent: cached.originalMarkdownContent ?? cached.markdownContent,
        }
      if (file.source === undefined) throw new Error('本地文档正文未找到，请重新导入文件')
      if (file.source === 'knowledge_base') {
        const remote = await documentApi.getParsedContent(file.id, { max_chars: 2_000_000 })
        assertCompleteDocumentContent(remote)
        return {
          id: file.id,
          markdownContent: remote.markdown_content,
          originalMarkdownContent: remote.original_markdown_content,
        }
      }
      const remote = await parsingApi.getContent(file.id)
      return {
        id: file.id,
        markdownContent: remote.markdown_content,
        originalMarkdownContent: remote.original_markdown_content,
      }
    },
  })
  useEffect(() => {
    if (!selectedFile) return
    if (hasStoredContent) initializeGovernanceState(selectedFile)
    else if (contentQuery.data?.id === selectedFile.id)
      initializeGovernanceState({ ...selectedFile, ...contentQuery.data, contentLoaded: true })
  }, [selectedFile, hasStoredContent, contentQuery.data, initializeGovernanceState])

  const handleDeleteFile = useCallback(
    async (fileId: string) => {
      const target = files.find((file) => file.id === fileId)
      if (!target) return
      try {
        if (target.source === 'knowledge_base') await documentApi.delete(fileId)
        else if (target.source === 'parsing_workspace') await parsingApi.delete(fileId)
        removeFile(fileId)
        setGovernanceStates((prev) => {
          const next = { ...prev }
          delete next[fileId]
          return next
        })
        setDeleteFileOpen(false)
        toast.success(t('toasts.fileDeleted'))
      } catch (error) {
        toast.error(formatApiError(error, '删除失败，文档已保留。'))
      }
    },
    [files, removeFile, t],
  )

  // 初始化时自动选择第一个文件
  useEffect(() => {
    if (!isLoaded) return

    if (visibleFiles.length === 0) {
      setSelectedFileId(null)
      return
    }

    const stillVisible = selectedFileId && visibleFiles.some((f) => f.id === selectedFileId)
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

          const existing = libraryFolders.find((f) => (f.parentId || ROOT_FOLDER_ID) === parentId && f.name === trimmed)
          if (existing) {
            folderIdByKey.set(key, existing.id)
            return existing.id
          }

          const newId = createFolder(trimmed, parentId)
          folderIdByKey.set(key, newId)
          return newId
        }

        const expanded: Array<{ file: File; folderId: string; fileType: string }> = []
        let skipped = 0
        let added = 0

        for (const file of incomingFiles) {
          if (isZipFile(file)) {
            let extractedCount = 0
            let addedInZip = 0
            let skippedInZip = 0
            try {
              const extracted = await extractZipFiles(file)
              if (controller.signal.aborted || uploadAbortRef.current !== controller) return
              extractedCount = extracted.length
              for (const item of extracted) {
                const parts = item.path.split('/').filter(Boolean)
                const filename = parts.pop()
                if (!filename) continue

                const fileType = getAllowedUploadFileType(filename)
                if (fileType === undefined) {
                  skipped += 1
                  skippedInZip += 1
                  continue
                }

                let folderId = baseFolderId
                for (const segment of parts) {
                  folderId = getOrCreateFolder(folderId, segment)
                }

                expanded.push({ file: item.file, folderId, fileType })
                added += 1
                addedInZip += 1
              }
            } catch (e) {
              if (controller.signal.aborted || uploadAbortRef.current !== controller) return
              reportClientError('Failed to extract governance ZIP upload', e)
              toast.error(t('toasts.zipExtractFailed', { filename: file.name }))
            }

            if (addedInZip === 0) {
              toast.warning(
                extractedCount === 0
                  ? t('toasts.zipNoFilesFound', { filename: file.name })
                  : t('toasts.zipNoSupportedFiles', { filename: file.name }),
              )
            } else {
              toast.success(
                skippedInZip > 0
                  ? t('toasts.zipAddedWithSkipped', {
                      added: addedInZip,
                      skipped: skippedInZip,
                    })
                  : t('toasts.zipAdded', { added: addedInZip }),
              )
            }
            continue
          }

          const fileType = getAllowedUploadFileType(file.name)
          if (fileType === undefined) {
            skipped += 1
            continue
          }

          expanded.push({ file, folderId: baseFolderId, fileType })
          added += 1
        }

        for (const { file, folderId, fileType } of expanded) {
          // 使用 preview 接口快速获取 Markdown
          if (controller.signal.aborted || uploadAbortRef.current !== controller) return
          const data = await documentApi.preview(
            file,
            parserBackend,
            { governance_enabled: false },
            {
              signal: controller.signal,
              dataset_id: selectedDatasetId ?? undefined,
            },
          )
          if (controller.signal.aborted || uploadAbortRef.current !== controller) return

          // 拼接 segments 获取全文
          const markdownContent = data.segments.map((s) => s.content).join('\n\n')

          const newId = await addParsedFile(
            {
              filename: file.name,
              fileType,
              fileSize: file.size,
              markdownContent,
              parser: data.parser_backend,
              folderId,
              datasetId: selectedDatasetId,
              datasetName: selectedDatasetName,
            },
            { signal: controller.signal },
          )
          if (controller.signal.aborted || uploadAbortRef.current !== controller) return

          // 如果是第一个文件，则自动选中
          initializeGovernanceState({ id: newId, markdownContent, contentLoaded: true })
          setSelectedFileId((prev) => prev ?? newId)
        }

        if (added > 0) toast.success(t('toasts.parsedAndAdded', { count: added }))
        if (skipped > 0) toast.warning(t('toasts.skippedUnsupported', { count: skipped }))
      } catch (error) {
        if (controller.signal.aborted || uploadAbortRef.current !== controller) return
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
    ],
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
    [handleUploadAndParse],
  )

  const handleFileSelect = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const files = e.target.files ? Array.from(e.target.files) : []
      if (files.length > 0) {
        await handleUploadAndParse(files)
      }
      e.target.value = ''
    },
    [handleUploadAndParse],
  )

  // 获取当前显示内容
  const displayContent = useMemo(() => {
    if (!governanceState) return ''
    return viewMode === 'original' ? governanceState.originalContent : governanceState.cleanedContent
  }, [governanceState, viewMode])

  // 文件选择
  const handleSelectFile = useCallback(
    (fileId: string) => {
      const file = scopedFiles.find((f) => f.id === fileId)
      if (file) {
        setSelectedFileId(fileId)
        initializeGovernanceState(file)
        if (directoryOpen) handleDirectoryOpenChange(false)
      }
    },
    [scopedFiles, initializeGovernanceState, directoryOpen, handleDirectoryOpenChange],
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
    [selectedFileId],
  )

  const handleQualityCheck = useCallback(
    (result: { score: number; issues: FileGovernanceState['issues'] }) => {
      if (!selectedFileId) return
      const source = governanceState?.cleanedContent
      setGovernanceStates((prev) => {
        const current = prev[selectedFileId]
        if (!current || current.cleanedContent !== source) return prev
        return {
          ...prev,
          [selectedFileId]: {
            ...current,
            qualityScore: result.score,
            qualityChecked: true,
            issues: result.issues,
            isModified: true,
          },
        }
      })
    },
    [selectedFileId, governanceState?.cleanedContent],
  )
  const handleClean = useCallback(
    (cleanedContent: string) => {
      if (!selectedFileId) return
      const source = governanceState?.cleanedContent
      setGovernanceStates((prev) => {
        const current = prev[selectedFileId]
        if (!current || current.cleanedContent !== source || current.cleanedContent === cleanedContent) return prev
        return {
          ...prev,
          [selectedFileId]: {
            ...current,
            cleanedContent,
            isModified: true,
            qualityChecked: false,
            issues: [],
            annotations: [],
          },
        }
      })
    },
    [selectedFileId, governanceState?.cleanedContent],
  )

  // 标注完成回调
  const handleAnnotate = useCallback(
    (annotations: FileGovernanceState['annotations']) => {
      if (!selectedFileId) return
      const source = governanceState?.cleanedContent
      setGovernanceStates((prev) => {
        const current = prev[selectedFileId]
        if (!current || current.cleanedContent !== source) return prev
        return { ...prev, [selectedFileId]: { ...current, annotations, isModified: true } }
      })
    },
    [selectedFileId, governanceState?.cleanedContent],
  )

  const handleDocumentTags = useCallback(
    (tags: string[]) => {
      if (!selectedFileId) return
      const source = governanceState?.cleanedContent
      setGovernanceStates((prev) => {
        const current = prev[selectedFileId]
        if (!current || current.cleanedContent !== source) return prev
        const mergedTags = Array.from(new Set([...(current.tags || []), ...tags.filter(Boolean)]))
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
    [selectedFileId, governanceState?.cleanedContent],
  )

  // 分类完成回调
  const handleClassify = useCallback(
    (category: string, tags: string[]) => {
      if (!selectedFileId) return
      const source = governanceState?.cleanedContent
      setGovernanceStates((prev) => {
        const current = prev[selectedFileId]
        if (!current || current.cleanedContent !== source) return prev
        return { ...prev, [selectedFileId]: { ...current, category, tags, isModified: true } }
      })
    },
    [selectedFileId, governanceState?.cleanedContent],
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
        resetRevision: governanceState.resetRevision + 1,
      },
    }))
  }, [selectedFileId, governanceState])

  // Save the chosen documents only; drafts in other rows remain untouched.
  const persistGovernanceEdits = useCallback(
    async (ids: Set<string>, submitted = false) => {
      const scope = getAuthCacheScope()
      for (const id of ids) {
        const draft = governanceStates[id]
        const file = files.find((file) => file.id === id)
        if (!file) throw new Error('文档已移除，请重新选择。')
        let markdown = draft?.contentLoaded ? draft.cleanedContent : file.markdownContent
        let original = draft?.contentLoaded ? draft.originalContent : (file.originalMarkdownContent ?? markdown)
        if (!draft?.contentLoaded && !markdown && !original) {
          const cached = await getDocContentFromCache(id, scope)
          if (!cached) throw new Error('请先打开文档，等待正文加载完成。')
          markdown = cached.markdownContent
          original = cached.originalMarkdownContent ?? markdown
        }
        if (getAuthCacheScope() !== scope || !useParsedFiles.getState().files.some((item) => item.id === id)) {
          throw new Error('当前账户或文档已变更，请重新打开文档。')
        }
        await updateParsedFile(
          id,
          {
            markdownContent: markdown,
            originalMarkdownContent: original,
            governanceStatus: submitted ? 'submitted' : 'ready',
            chunkStatus: submitted ? 'submitted' : 'ready',
            ...(draft
              ? {
                  governanceReview: {
                    qualityScore: draft.qualityChecked ? draft.qualityScore : null,
                    issues: draft.issues,
                    annotations: draft.annotations,
                    tags: draft.tags,
                    category: draft.category,
                  },
                }
              : {}),
          },
          { requirePersistence: true },
        )
        setGovernanceStates((prev) =>
          prev[id] === draft && draft
            ? {
                ...prev,
                [id]: {
                  ...draft,
                  cleanedContent: markdown,
                  originalContent: original,
                  contentLoaded: true,
                  isModified: false,
                },
              }
            : prev,
        )
      }
    },
    [files, governanceStates, updateParsedFile],
  )

  const saveDocuments = async (continueToChunks: boolean, batch = false) => {
    if (saving) return
    const ids = batch
      ? new Set(selectedReadyChunkFiles.map((file) => file.id))
      : new Set(selectedFileId ? [selectedFileId] : [])
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
    } finally {
      setSaving(false)
    }
  }

  const queueFiles = visibleFiles.filter((file) =>
    file.filename.toLocaleLowerCase().includes(search.trim().toLocaleLowerCase()),
  )
  const isLibraryLoading =
    loadError === undefined && (!isLoaded || (documentSyncQuery.isPending && visibleFiles.length === 0))
  const statusFor = (file: ParsedFileData) => {
    const draft = governanceStates[file.id]
    const score = draft ? (draft.qualityChecked ? draft.qualityScore : null) : file.governanceReview?.qualityScore
    const issues = draft?.issues ?? file.governanceReview?.issues ?? []
    if (file.status === 'error') return { id: 'error', label: '解析失败', tone: styles.danger, score }
    if (file.status === 'pending' || file.status === 'parsing')
      return { id: 'processing', label: file.status === 'parsing' ? '解析中' : '等待解析', tone: styles.info, score }
    if (draft?.isModified) return { id: 'review', label: '待核对', tone: styles.warning, score }
    if (issues.length) return { id: 'review', label: '待核对', tone: styles.warning, score }
    if (
      file.governanceStatus === 'ready' ||
      file.governanceStatus === 'submitted' ||
      file.chunkStatus === 'ready' ||
      file.chunkStatus === 'submitted'
    )
      return { id: 'done', label: '已保存', tone: styles.success, score }
    if (score != null) return { id: 'review', label: '待核对', tone: styles.warning, score }
    return { id: 'pending', label: '待治理', tone: '', score: null }
  }
  const loadingContent = Boolean(selectedFile && !governanceState?.contentLoaded && !contentQuery.isError)
  const contentError = !governanceState?.contentLoaded && contentQuery.isError
  const canUseContent = Boolean(governanceState?.contentLoaded)
  const hasText = canUseContent && Boolean(governanceState?.cleanedContent.trim())
  let saveStateText = '等待检查文档'
  if (saving) saveStateText = '正在保存…'
  else if (loadingContent) saveStateText = '等待正文加载'
  else if (contentError) saveStateText = '正文加载失败'
  else if (governanceState?.isModified) saveStateText = '修改尚未保存'
  else if (selectedFile?.governanceStatus === 'ready' || selectedFile?.governanceStatus === 'submitted')
    saveStateText = '治理结果已保存'
  const currentIndex = queueFiles.findIndex((file) => file.id === selectedFileId)
  const currentStatus = selectedFile ? statusFor(selectedFile) : null
  const documentActions =
    selectedFile === null ? null : (
      <div className={styles.fileActions}>
        <ConfirmDialog
          title="重置当前修改？"
          description="将恢复解析原文，并清除本次检测、标注和分类。重置后仍需保存。"
          confirmLabel="重置"
          cancelLabel="取消"
          onConfirm={handleReset}
        >
          <Button
            variant="ghost"
            size="icon"
            className="size-11 sm:size-9"
            aria-label="恢复原文"
            title="恢复原文"
            disabled={!canUseContent || saving}
          >
            <RotateCcw className="size-3.5" />
          </Button>
        </ConfirmDialog>
        <Button
          variant="ghost"
          size="icon"
          className="size-11 sm:size-9"
          aria-label="删除文档"
          title="删除文档"
          disabled={saving}
          onClick={() => {
            setDeleteFileTarget({ id: selectedFile.id, filename: selectedFile.filename })
            setDeleteFileOpen(true)
          }}
        >
          <Trash2 className="size-3.5" />
        </Button>
      </div>
    )
  const nextFile = () => {
    const next = queueFiles[(currentIndex + 1) % queueFiles.length]
    if (next) handleSelectFile(next.id)
  }
  const locateIssue = (issue: FileGovernanceState['issues'][number]) => {
    setActiveIssueId(issue.id)
    if (!issue.position) return
    setViewMode('edit')
    setMobilePane('document')
    requestAnimationFrame(() => {
      editorRef.current?.focus()
      editorRef.current?.setSelectionRange(issue.position!.start, issue.position!.end)
      editorRef.current?.scrollIntoView({ block: 'nearest', behavior: 'auto' })
    })
  }
  const ignoreIssue = (issue: FileGovernanceState['issues'][number]) => {
    if (!selectedFileId) return
    setGovernanceStates((prev) => ({
      ...prev,
      [selectedFileId]: {
        ...prev[selectedFileId],
        issues: prev[selectedFileId].issues.filter((item) => item.id !== issue.id),
        isModified: true,
      },
    }))
    setActiveIssueId(null)
  }
  const libraryFeedback = (
    <>
      {loadError !== undefined && (
        <div className={styles.inlineError} role="alert">
          <span>本地文档记录读取失败：{formatApiError(loadError, '无法读取文档目录')}</span>
          <Button size="sm" variant="ghost" onClick={() => void useParsedFiles.persist.rehydrate()}>
            重试读取文档
          </Button>
        </div>
      )}
      {documentSyncError !== null && (
        <div className={styles.inlineError} role="alert">
          <span>队列加载失败</span>
          <Button
            size="sm"
            variant="ghost"
            disabled={documentSyncQuery.isFetching}
            onClick={() => void documentSyncQuery.refetch()}
          >
            重试
          </Button>
        </div>
      )}
    </>
  )

  return (
    <div
      className={styles.page}
      data-governance-workbench
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      <header className={styles.header}>
        <div className={styles.title}>
          <PageTitleIcon name="data-governance" className="size-[18px]" />
          <h1>{headerTitle}</h1>
        </div>
        <Select
          value={selectedDatasetId || ALL_DATASETS_VALUE}
          onValueChange={handleDatasetScopeChange}
          disabled={uploading || saving}
        >
          <SelectTrigger className={styles.scope} aria-label="数据集范围">
            <SelectValue placeholder="全部数据集" />
          </SelectTrigger>
          <SelectContent>
            <SelectItem value={ALL_DATASETS_VALUE}>全部数据集</SelectItem>
            {availableDatasets.map((dataset) => (
              <SelectItem key={dataset.id} value={dataset.id}>
                {dataset.name}
              </SelectItem>
            ))}
          </SelectContent>
        </Select>
        <button
          ref={directoryTriggerRef}
          type="button"
          className={styles.filePicker}
          aria-label="选择文档"
          aria-describedby={selectedFile ? 'governance-file-name governance-file-size' : undefined}
          aria-haspopup="dialog"
          aria-expanded={directoryOpen}
          onClick={() => handleDirectoryOpenChange(true)}
        >
          {selectedFile ? getFileIcon(selectedFile.filename, 'size-5 shrink-0') : <FolderTree className="size-4" />}
          <span id="governance-file-name" className={styles.fileIdentity} title={selectedFile?.filename}>
            {selectedFile?.filename ?? '选择文档'}
          </span>
          {selectedFile && (
            <span id="governance-file-size" className={styles.fileSize}>
              {formatFileSize(selectedFile.fileSize)}
            </span>
          )}
          {currentStatus && (
            <span className={cn(styles.status, currentStatus.tone)}>
              <i className={styles.dot} aria-hidden="true" />
              {currentStatus.label}
            </span>
          )}
          <ChevronDown className="size-3.5 shrink-0 text-muted-foreground" />
        </button>
        <div className={styles.fileNavigation} aria-label="文档翻页">
          <Button
            variant="ghost"
            size="icon"
            aria-label="上一份文档"
            disabled={currentIndex <= 0 || saving}
            onClick={() => handleSelectFile(queueFiles[currentIndex - 1].id)}
          >
            <ArrowLeft className="size-3.5" />
          </Button>
          <span>
            {currentIndex + 1} / {queueFiles.length}
          </span>
          <Button
            variant="ghost"
            size="icon"
            aria-label="下一份文档"
            disabled={currentIndex < 0 || currentIndex >= queueFiles.length - 1 || saving}
            onClick={() => handleSelectFile(queueFiles[currentIndex + 1].id)}
          >
            <ArrowRight className="size-3.5" />
          </Button>
        </div>
        <div className={styles.headerActions}>
          <Button variant="ghost" size="sm" aria-label="治理配置" onClick={() => setConfigOpen(true)}>
            <SlidersHorizontal className="size-4" />
            <span className={styles.actionLabel}>治理配置</span>
          </Button>
          {uploading ? (
            <Button variant="outline" size="sm" onClick={cancelUploadAndParse}>
              <Loader2 className={styles.spinner} />
              取消解析
            </Button>
          ) : (
            <Button
              variant="outline"
              size="sm"
              aria-label="添加文档"
              disabled={saving}
              onClick={() => fileInputRef.current?.click()}
            >
              <Plus className="size-4" />
              <span className={styles.actionLabel}>添加文档</span>
            </Button>
          )}
          <Button
            size="sm"
            className="bg-accent text-accent-foreground hover:bg-accent/90"
            onClick={() => void saveDocuments(true)}
            disabled={!hasText || saving}
          >
            {saving ? <Loader2 className={styles.spinner} /> : <ArrowRight className="size-3.5" />}
            保存并继续切块
          </Button>
          <input
            ref={fileInputRef}
            type="file"
            multiple
            accept={UPLOAD_ACCEPT_WITH_ZIP}
            onChange={handleFileSelect}
            className="hidden"
            aria-label="上传治理文档"
          />
        </div>
      </header>
      {datasetsQuery.error && (
        <div role="alert" className={styles.inlineError}>
          {formatApiError(datasetsQuery.error, '加载数据集失败')}
        </div>
      )}
      {!directoryOpen && libraryFeedback}
      <WorkbenchPanelDialog
        open={directoryOpen}
        onOpenChange={handleDirectoryOpenChange}
        title="文档目录"
        className={styles.directoryDialog}
      >
        <aside className={styles.queue} data-governance-queue aria-label="文档队列">
          <div className={styles.queueHeading}>
            <h2>当前范围</h2>
            <span className={styles.count}>{visibleFiles.length}</span>
            <div className={styles.queueActions}>
              <Button
                variant="ghost"
                size="icon"
                className="size-11 sm:size-9"
                aria-label="批量选择切块文档"
                aria-pressed={batchMode}
                onClick={() => {
                  setBatchMode((value) => !value)
                  setSelectedChunkFileIds(new Set())
                }}
              >
                <ListChecks className="size-3.5" />
              </Button>
            </div>
          </div>
          <div className={styles.queueFilters}>
            <div className={styles.search}>
              <Search />
              <input
                type="search"
                aria-label="搜索治理文档"
                placeholder="搜索文件名"
                value={search}
                onChange={(event) => setSearch(event.target.value)}
              />
              {search && (
                <button type="button" aria-label="清除文档搜索" onClick={() => setSearch('')}>
                  <X className="size-3" />
                </button>
              )}
            </div>
          </div>
          <div className={styles.folderTree}>
            <DocumentFolderTree />
          </div>
          <div className={styles.fileListHeading}>
            <span>文件</span>
            <span>{queueFiles.length}</span>
          </div>
          {directoryOpen && libraryFeedback}
          <div className={styles.queueScroll}>
            {isLibraryLoading ? (
              <div className={styles.emptySmall} role="status">
                正在加载文档…
              </div>
            ) : !queueFiles.length && loadError === undefined && documentSyncError === null ? (
              <div className={styles.emptySmall}>
                {search ? '没有找到匹配的文档' : '当前范围没有文档'}
                {search && (
                  <Button size="sm" variant="link" onClick={() => setSearch('')}>
                    清除搜索
                  </Button>
                )}
              </div>
            ) : (
              queueFiles.map((file) => {
                const status = statusFor(file)
                return (
                  <div className={styles.queueEntry} key={file.id}>
                    {batchMode && (
                      <input
                        type="checkbox"
                        aria-label={'选择切块文档 ' + file.filename}
                        disabled={file.chunkStatus !== 'ready' || saving}
                        checked={selectedChunkFileIds.has(file.id)}
                        onChange={() => toggleChunkFileSelection(file.id)}
                      />
                    )}
                    <button
                      type="button"
                      className={styles.queueItem}
                      disabled={saving}
                      aria-current={selectedFileId === file.id}
                      data-governance-file={file.id}
                      onClick={() => handleSelectFile(file.id)}
                    >
                      {getFileIcon(file.filename, 'size-5')}
                      <span className={styles.queueItemText}>
                        <strong className={styles.queueName} title={file.filename}>
                          {file.filename}
                        </strong>
                        <span className={styles.queueMeta}>
                          <span>{formatFileSize(file.fileSize)}</span>
                          <span
                            className={
                              status.score == null
                                ? status.tone
                                : status.score >= 80
                                  ? styles.success
                                  : status.score >= 60
                                    ? styles.warning
                                    : styles.danger
                            }
                          >
                            {status.score != null ? status.score + ' 分' : status.label}
                          </span>
                        </span>
                      </span>
                    </button>
                  </div>
                )
              })
            )}
          </div>
          <div className={styles.queueFooter}>
            {batchMode ? (
              <>
                <span>已选 {selectedReadyChunkCount} 份已保存文档</span>
                <Button
                  variant="ghost"
                  size="sm"
                  disabled={!selectedReadyChunkCount || saving}
                  onClick={() => void saveDocuments(true, true)}
                >
                  切块
                  <ArrowRight className="size-3" />
                </Button>
              </>
            ) : (
              <>
                <span>已保存</span>
                <span>
                  {
                    queueFiles.filter(
                      (file) =>
                        !governanceStates[file.id]?.isModified &&
                        (file.governanceStatus === 'ready' ||
                          file.governanceStatus === 'submitted' ||
                          file.chunkStatus === 'ready' ||
                          file.chunkStatus === 'submitted'),
                    ).length
                  }{' '}
                  / {queueFiles.length} 份
                </span>
              </>
            )}
          </div>
        </aside>
      </WorkbenchPanelDialog>
      <div className={styles.workspace}>
        <main className={styles.reader} data-governance-reader aria-label="文档治理工作区">
          <div className={styles.paneSwitcher} aria-label="工作区视图">
            <button
              type="button"
              aria-pressed={mobilePane === 'document'}
              onClick={() => setMobilePane('document')}
            >
              <FileText className="size-4" />
              正文
            </button>
            <button
              type="button"
              aria-pressed={mobilePane === 'tools'}
              onClick={() => {
                setMobilePane('tools')
                setToolsOpen(true)
              }}
            >
              <ListChecks className="size-4" />
              治理工具
            </button>
          </div>
          <div className={styles.reviewColumns} data-tools-open={toolsOpen} data-mobile-pane={mobilePane}>
            <section className={styles.documentPane} aria-label="文档正文">
              <div className={styles.documentToolbar}>
                <h2>
                  <FileText />
                  {selectedFile && governanceState ? '文档预览与编辑' : '文档治理'}
                </h2>
                {selectedFile && governanceState ? (
                  <div className={styles.viewActions} aria-label="正文显示方式">
                    <button
                      type="button"
                      aria-pressed={viewMode === 'preview'}
                      onClick={() => setViewMode('preview')}
                    >
                      预览
                    </button>
                    <button
                      type="button"
                      aria-pressed={viewMode === 'original'}
                      onClick={() => setViewMode('original')}
                    >
                      原文
                    </button>
                    <button
                      type="button"
                      disabled={!canUseContent || saving}
                      aria-pressed={viewMode === 'edit'}
                      onClick={() => setViewMode('edit')}
                    >
                      编辑
                    </button>
                    {viewMode !== 'edit' && (
                      <button
                        type="button"
                        aria-pressed={previewFormat === 'markdown'}
                        onClick={() => setPreviewFormat((value) => (value === 'rendered' ? 'markdown' : 'rendered'))}
                      >
                        Markdown
                      </button>
                    )}
                  </div>
                ) : null}
                {documentActions}
              </div>
              <div
                className={styles.readerScroll}
                data-empty={!selectedFile || !governanceState}
                ref={contentScrollRef}
              >
                {selectedFile && governanceState ? (
                  loadingContent ? (
                    <div className={styles.emptyStage} role="status">
                      <div className={styles.emptyStageHero}>
                        <Loader2 className={styles.spinner} />
                        <p>正在加载正文…</p>
                      </div>
                    </div>
                  ) : contentError ? (
                    <div className={styles.emptyStage} role="alert">
                      <div className={styles.emptyStageHero}>
                        <AlertTriangle className={styles.emptyPaperIcon} />
                        <h3>正文加载失败</h3>
                        <p>{formatApiError(contentQuery.error, '请确认文档已经解析，再重试。')}</p>
                        <div className={styles.emptyStageActions}>
                          <Button
                            size="sm"
                            variant="outline"
                            disabled={contentQuery.isFetching}
                            onClick={() => void contentQuery.refetch()}
                          >
                            重新加载正文
                          </Button>
                        </div>
                      </div>
                    </div>
                  ) : (
                    <div className={styles.document} data-governance-selection-root="true" data-governance-document>
                      {viewMode === 'edit' ? (
                        <textarea
                          ref={editorRef}
                          aria-label="编辑文档正文"
                          value={displayContent}
                          onChange={(event) => handleManualEdit(event.target.value)}
                          disabled={saving}
                          className={styles.editor}
                          spellCheck={false}
                        />
                      ) : !displayContent ? (
                        <div className={styles.empty}>
                          <FileText />
                          <h3>文档正文为空</h3>
                          <p>可切换到编辑模式补充内容，或重新解析原文件。</p>
                        </div>
                      ) : previewFormat === 'markdown' ? (
                        <pre className={styles.raw}>{displayContent}</pre>
                      ) : (
                        <MarkdownRenderer markdown={displayContent} />
                      )}
                    </div>
                  )
                ) : isLibraryLoading ? (
                  <div className={styles.emptyStage} role="status">
                    <div className={styles.emptyStageHero}>
                      <Loader2 className={styles.spinner} />
                      <h3>正在加载文档…</h3>
                      <p>正在同步文档目录与已解析正文，请稍候。</p>
                    </div>
                  </div>
                ) : loadError !== undefined ? (
                  <div className={styles.emptyStage} role="alert">
                    <div className={styles.emptyStageHero}>
                      <AlertTriangle className={styles.emptyPaperIcon} />
                      <h3>文档目录暂不可用</h3>
                      <p>{formatApiError(loadError, '无法读取本地文档记录，可重试或前往文档解析。')}</p>
                      <div className={styles.emptyStageActions}>
                        <Button size="sm" variant="outline" onClick={() => void useParsedFiles.persist.rehydrate()}>
                          重试读取文档
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => router.push('/parsing')}>
                          <ExternalLink className="size-4" />
                          前往文档解析
                        </Button>
                      </div>
                    </div>
                  </div>
                ) : (
                  <div className={styles.emptyStage}>
                    <div className={styles.emptyStageHero}>
                      <div className={styles.emptyDocIllust} aria-hidden="true">
                        <svg viewBox="0 0 180 124" fill="none">
                          <path
                            d="M14 104C44 86 136 86 166 104"
                            stroke="currentColor"
                            strokeOpacity="0.14"
                            strokeWidth="1.2"
                          />
                          <rect
                            x="56"
                            y="14"
                            width="68"
                            height="84"
                            rx="7"
                            fill="hsl(var(--surface-2))"
                            stroke="currentColor"
                            strokeOpacity="0.18"
                            strokeWidth="1.2"
                          />
                          <path d="M104 14V32H124" stroke="currentColor" strokeOpacity="0.18" strokeWidth="1.2" />
                          <rect x="70" y="42" width="38" height="4.5" rx="2.25" fill="currentColor" fillOpacity="0.18" />
                          <rect x="70" y="55" width="42" height="4.5" rx="2.25" fill="currentColor" fillOpacity="0.14" />
                          <rect x="70" y="68" width="28" height="4.5" rx="2.25" fill="currentColor" fillOpacity="0.12" />
                        </svg>
                      </div>
                      <h3>暂无待治理文档</h3>
                      <p>选择文档后，即可开始质量检测、规则清洗与标签归档流程</p>
                      <div className={styles.emptyStageActions}>
                        <Button
                          size="sm"
                          className={styles.emptyPrimaryAction}
                          onClick={() => setDirectoryOpen(true)}
                        >
                          <FolderOpen className="size-4" />
                          打开文档目录
                        </Button>
                        <Button size="sm" variant="outline" onClick={() => router.push('/parsing')}>
                          <ExternalLink className="size-4" />
                          前往文档解析
                        </Button>
                      </div>
                    </div>
                    <div className={styles.emptyDeliverables} aria-label="治理产出说明">
                      <div>
                        <BarChart3 className="size-4" aria-hidden="true" />
                        <span>质量报告</span>
                      </div>
                      <div>
                        <Layers className="size-4" aria-hidden="true" />
                        <span>规则差异</span>
                      </div>
                      <div>
                        <Tag className="size-4" aria-hidden="true" />
                        <span>标签与分类</span>
                      </div>
                    </div>
                  </div>
                )}
              </div>
            </section>
            <aside className={styles.toolbox} data-governance-tools aria-label="治理工具箱">
              <div className={styles.toolboxHeading}>
                <h2>
                  <ListChecks className="size-4" />
                  治理工作台
                </h2>
                <Button
                  variant="ghost"
                  size="icon"
                  className="size-11 sm:size-9"
                  aria-label={toolsOpen ? '收起治理工具' : '展开治理工具'}
                  aria-expanded={toolsOpen}
                  aria-controls="governance-tools-content"
                  onClick={() => {
                    setToolsOpen((value) => !value)
                    setMobilePane('document')
                  }}
                >
                  {toolsOpen ? <PanelRightClose className="size-4" /> : <PanelRightOpen className="size-4" />}
                </Button>
              </div>
              <div className={styles.toolboxContent} id="governance-tools-content" hidden={!toolsOpen}>
                <div className={styles.tabs} role="tablist" aria-label="治理工具">
                  {governanceTabs.map((tab, index) => {
                    const Icon = tab.icon
                    return (
                      <button
                        type="button"
                        key={tab.id}
                        id={'governance-tab-' + tab.id}
                        role="tab"
                        data-tone={tab.color}
                        aria-selected={activeTab === tab.id}
                        aria-controls="governance-tool-panel"
                        tabIndex={activeTab === tab.id ? 0 : -1}
                        onClick={() => setActiveTab(tab.id)}
                        onKeyDown={(event) => {
                          if (!['ArrowLeft', 'ArrowRight', 'Home', 'End'].includes(event.key)) return
                          event.preventDefault()
                          const next =
                            event.key === 'Home'
                              ? 0
                              : event.key === 'End'
                                ? governanceTabs.length - 1
                                : (index + (event.key === 'ArrowRight' ? 1 : -1) + governanceTabs.length) %
                                  governanceTabs.length
                          setActiveTab(governanceTabs[next].id)
                          document.getElementById('governance-tab-' + governanceTabs[next].id)?.focus()
                        }}
                      >
                        <Icon />
                        {tab.label}
                      </button>
                    )
                  })}
                </div>
                <div
                  className={styles.toolboxScroll}
                  ref={toolboxScrollRef}
                  id="governance-tool-panel"
                  role="tabpanel"
                  aria-labelledby={'governance-tab-' + activeTab}
                >
                  {selectedFile && governanceState ? (
                    canUseContent ? (
                      <fieldset disabled={saving} className={styles.tools} key={selectedFile.id + ':' + activeTab}>
                        {activeTab === 'quality' && (
                          <QualityChecker
                            content={governanceState.cleanedContent}
                            initialScore={governanceState.qualityScore}
                            initialIssues={governanceState.issues}
                            checked={governanceState.qualityChecked}
                            resetRevision={governanceState.resetRevision}
                            disabled={saving || !hasText}
                            onComplete={handleQualityCheck}
                            activeIssueId={activeIssueId}
                            onSelectIssue={(issue) => setActiveIssueId(issue.id)}
                            onLocateIssue={locateIssue}
                            onIgnoreIssue={ignoreIssue}
                            onCleanRequest={() => setActiveTab('clean')}
                            scanButtonRef={qualityScanRef}
                            onScanningChange={setQualityScanning}
                          />
                        )}
                        {activeTab === 'clean' && (
                          <DataCleaner
                            key={selectedFile.id}
                            content={governanceState.cleanedContent}
                            resetRevision={governanceState.resetRevision}
                            onClean={handleClean}
                            disabled={saving || !hasText}
                            onConfigure={() => setConfigOpen(true)}
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
                      </fieldset>
                    ) : (
                      <div className={styles.emptySmall}>
                        {loadingContent ? '正在加载正文…' : '正文加载后可使用治理工具'}
                      </div>
                    )
                  ) : (
                    <div className={styles.tools} key={'empty:' + activeTab}>
                      {activeTab === 'quality' && (
                        <>
                          <div className={styles.standbyCard}>
                            <div className={styles.standbyRing} aria-hidden="true">
                              <svg viewBox="0 0 64 64">
                                <circle className={styles.standbyRingTrack} cx="32" cy="32" r="24" />
                                <circle className={styles.standbyRingArc} cx="32" cy="32" r="24" />
                              </svg>
                            </div>
                            <strong>等待文档</strong>
                            <p>请先选择已解析文档或前往文档解析，完成后将在此进行质量体检与治理</p>
                          </div>
                          <section className={styles.standbyRules} aria-label="清洗规则快捷开关">
                            <div className={styles.standbyRulesHeader}>
                              <h4>
                                <SlidersHorizontal className="size-3.5" aria-hidden="true" />
                                清洗规则
                              </h4>
                              <Button size="sm" variant="ghost" onClick={() => setConfigOpen(true)}>
                                全部配置
                              </Button>
                            </div>
                            <div className={styles.standbyRuleList}>
                              {STANDBY_CLEANING_RULES.map((rule) => {
                                const RuleIcon = rule.icon
                                const checked = options[rule.key] === true
                                return (
                                  <label key={rule.key} className={styles.standbyRuleRow}>
                                    <RuleIcon className="size-4 shrink-0 text-muted-foreground" aria-hidden="true" />
                                    <span className={styles.standbyRuleCopy}>
                                      <strong>{rule.title}</strong>
                                      <small>{rule.description}</small>
                                    </span>
                                    <input
                                      type="checkbox"
                                      checked={checked}
                                      onChange={(event) => {
                                        setEnabled(true)
                                        updateOption(rule.key, event.target.checked)
                                      }}
                                    />
                                  </label>
                                )
                              })}
                            </div>
                          </section>
                        </>
                      )}
                      {activeTab !== 'quality' && (
                        <GovernanceEmptyPresets
                          tab={activeTab}
                          onOpenConfig={() => setConfigOpen(true)}
                          onOpenDirectory={() => setDirectoryOpen(true)}
                        />
                      )}
                    </div>
                  )}
                </div>
              </div>
            </aside>
          </div>
          <FeedbackToast
            type="error"
            message={saveError ? `保存失败：${saveError}。修改内容已保留。` : null}
            id="governance-save-feedback"
          />
          <footer className={styles.footer}>
            <span className={styles.saveState} role="status">
              {selectedFile && governanceState ? (
                <>
                  {saving || loadingContent ? (
                    <Loader2 className={styles.spinner} />
                  ) : contentError ? (
                    <AlertTriangle className="size-3.5 text-destructive" />
                  ) : governanceState.isModified ? (
                    <span className={cn(styles.dot, styles.warning)} />
                  ) : (
                    <Check className="size-3.5" />
                  )}
                  {saveStateText}
                </>
              ) : (
                <>
                  <span className={cn(styles.dot, styles.success)} />
                  {isLibraryLoading ? '正在同步文档队列…' : '就绪 · 暂无文档，请选择文档并开始治理'}
                </>
              )}
            </span>
            <div className={styles.footerMeta}>
              {selectedFile && governanceState ? (
                <>
                  <span>文件大小 {formatFileSize(selectedFile.fileSize)}</span>
                  {canUseContent && (
                    <>
                      <span>字数 {governanceState.cleanedContent.length.toLocaleString()}</span>
                      <span>
                        段落数 {governanceState.cleanedContent.split(/\n\s*\n/).filter((value) => value.trim()).length}
                      </span>
                    </>
                  )}
                  <span
                    title={
                      selectedFile.datasetName || (selectedFile.source === 'knowledge_base' ? '知识库' : '解析文档')
                    }
                  >
                    {selectedFile.datasetName || (selectedFile.source === 'knowledge_base' ? '知识库' : '解析文档')}
                  </span>
                </>
              ) : (
                <span>当前范围 {queueFiles.length} 份文档</span>
              )}
            </div>
            <div className={styles.footerActions}>
              {selectedFile && governanceState && activeTab === 'quality' && toolsOpen && governanceState.qualityChecked && (
                <Button
                  size="sm"
                  variant="ghost"
                  aria-label="重新检测当前文档"
                  disabled={!hasText || saving || qualityScanning}
                  onClick={() => qualityScanRef.current?.click()}
                >
                  <RotateCcw className="size-3.5" />
                  重新检测
                </Button>
              )}
              <Button size="sm" variant="ghost" onClick={nextFile} disabled={!selectedFile || queueFiles.length < 2 || saving}>
                下一份
                <ChevronRight className="size-3.5" />
              </Button>
              <Button
                size="sm"
                variant="outline"
                onClick={() => void saveDocuments(false)}
                disabled={!selectedFile || !canUseContent || saving}
              >
                <Save className="size-3.5" />
                保存
              </Button>
            </div>
          </footer>
        </main>
      </div>
      <Sheet open={configOpen} onOpenChange={setConfigOpen}>
        <SheetContent className={styles.configSheet}>
          <SheetHeader className={styles.configHeader}>
            <SheetTitle>治理配置</SheetTitle>
            <SheetDescription>选择预设，或手动调整清洗规则。</SheetDescription>
          </SheetHeader>
          <div className={styles.configBody}>
            <section className={styles.configGroup}>
              <h3>治理预设</h3>
              <GovernanceProfileSelector
                compact
                onApplyPatch={(patch) => {
                  setEnabled(true)
                  for (const key of Object.keys(patch) as Array<keyof DocumentPipelineOptions>) {
                    const value = patch[key]
                    if (value !== undefined) updateOption(key, value)
                  }
                }}
              />
            </section>
            <section className={styles.configGroup}>
              <h3>清洗规则</h3>
              <PipelineOptionsPanel compact showJsonToolbar showIndexingControls={false} />
            </section>
          </div>
        </SheetContent>
      </Sheet>
      <AlertDialog open={deleteFileOpen} onOpenChange={setDeleteFileOpen}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>{t('dialogs.deleteFile.title')}</AlertDialogTitle>
            {deleteFileTarget !== null && (
              <AlertDialogDescription>
                {t('dialogs.deleteFile.description', { filename: deleteFileTarget.filename })}
              </AlertDialogDescription>
            )}
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('dialogs.deleteFile.cancel')}</AlertDialogCancel>
            <Button
              variant="destructive"
              onClick={() => {
                if (deleteFileTarget) void handleDeleteFile(deleteFileTarget.id)
              }}
            >
              {t('dialogs.deleteFile.confirm')}
            </Button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
      {isDragging && (
        <div className={styles.dropOverlay}>
          <Upload className="mx-auto size-8" />
          <strong>松开以添加并解析文档</strong>
          <span className="text-sm text-muted-foreground">PDF、Word、Excel、TXT、Markdown 或 ZIP</span>
        </div>
      )}
    </div>
  )
}
