/**
 * 数据治理工作台组件
 * 功能：质量检测、智能清洗、数据标注、分类归档
 */
'use client'

import { useState, useCallback, useMemo, useEffect, useRef } from 'react'
import {
  ShieldCheck,
  Sparkles,
  Tag,
  FolderTree,
  FileText,
  Upload,
  ChevronRight,
  ChevronLeft,
  Download,
  Save,
  RotateCcw,
  Check,
  AlertCircle,
  Trash2,
  Eye,
  EyeOff,
  Search,
  Filter,
  MoreHorizontal,
  Wrench,
  ScanLine,
  FileSearch,
  Replace,
  Eraser,
  Hash,
  Layers,
  ArrowRight,
  ArrowLeft,
  X,
  Info,
  AlertTriangle,
  CheckCircle,
  XCircle,
  Zap,
  Copy,
  Undo,
  Redo,
  PanelRightOpen,
  PanelRightClose,
  Maximize2,
  Minimize2,
  Layout,
  LayoutTemplate
} from 'lucide-react'
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
import { PageHeader } from '@/components/ui/page-header'
import { IngestionWorkflowStepper } from '@/components/ui/ingestion-workflow-stepper'
import { useRouter, useSearchParams } from 'next/navigation'
import { toast } from 'sonner'
import { ROOT_FOLDER_ID, useParsedFiles } from '@/store/use-parsed-files-store'
import { cn, formatFileSize } from '@/lib/utils'
import { getDocContentFromCache } from '@/lib/doc-content-cache'
import { QualityChecker } from '@/components/data-governance/quality-checker'
import { DataCleaner } from '@/components/data-governance/data-cleaner'
import { DataAnnotator } from '@/components/data-governance/data-annotator'
import { DataClassifier } from '@/components/data-governance/data-classifier'
import { documentApi, parsingApi } from '@/lib/api-client'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { MarkdownRenderer } from '@/components/markdown/markdown-renderer'
import { MarkdownToc } from '@/components/markdown/markdown-toc'
import { DocumentFolderTree, getFileIcon } from '@/components/document-library/folder-tree'
import { extractMarkdownHeadings } from '@/lib/markdown'
import { extractZipFiles, isZipFile } from '@/lib/zip'
import { UPLOAD_ACCEPT_WITH_ZIP, ZIP_ALLOWED_EXTENSIONS } from '@/lib/upload-extensions'

// 治理标签页
const GOVERNANCE_TABS = [
  { id: 'quality', label: '质量检测', icon: ScanLine, color: 'blue', desc: '检测文档质量与格式问题' },
  { id: 'clean', label: '智能清洗', icon: Wrench, color: 'green', desc: '修复格式错误与乱码' },
  { id: 'annotate', label: '数据标注', icon: Tag, color: 'purple', desc: '标记关键实体与敏感信息' },
  { id: 'classify', label: '分类归档', icon: FolderTree, color: 'orange', desc: '设置文档分类与标签' },
] as const

type GovernanceTab = typeof GOVERNANCE_TABS[number]['id']

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
  issues: Array<{
    id: string
    type: 'error' | 'warning' | 'info'
    message: string
    position?: { start: number; end: number }
  }>
  isModified: boolean
}

export function DataGovernancePanel() {
  const router = useRouter()
  const searchParams = useSearchParams()
  const files = useParsedFiles((state) => state.files)
  const libraryFolders = useParsedFiles((state) => state.folders)
  const activeFolderId = useParsedFiles((state) => state.activeFolderId)
  const setActiveFolderId = useParsedFiles((state) => state.setActiveFolderId)
  const createFolder = useParsedFiles((state) => state.createFolder)
  const isLoaded = useParsedFiles((state) => state.isLoaded)
  const addParsedFile = useParsedFiles((state) => state.addParsedFile)
  const updateParsedFile = useParsedFiles((state) => state.updateParsedFile)
  const removeFile = useParsedFiles((state) => state.removeFile)
  const { parserBackend } = useParserBackendPreference()

  // UI 状态
  const [activeTab, setActiveTab] = useState<GovernanceTab>('quality')
  const [inboundBannerDismissed, setInboundBannerDismissed] = useState(false)
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<'edit' | 'preview' | 'original'>('preview')
  const [previewFormat, setPreviewFormat] = useState<'rendered' | 'markdown'>('rendered')
  const [isProcessing, setIsProcessing] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [deleteFileOpen, setDeleteFileOpen] = useState(false)
  const [deleteFileTarget, setDeleteFileTarget] = useState<{ id: string; filename: string } | null>(null)
  const uploadAbortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    return () => {
      uploadAbortRef.current?.abort()
    }
  }, [])

  // Optional deep link from /chunk-preview (best-effort, non-breaking).
  useEffect(() => {
    const raw = (searchParams.get('tab') || '').trim()
    if (!raw) return
    if (GOVERNANCE_TABS.some((t) => t.id === raw)) {
      setActiveTab(raw as GovernanceTab)
    }
  }, [searchParams])

  const inboundContext = useMemo(() => {
    const from = (searchParams.get('from') || '').trim()
    const datasetId = (searchParams.get('dataset_id') || '').trim()
    const governanceProfileRef = (searchParams.get('governance_profile_ref') || '').trim()
    return {
      from: from || null,
      datasetId: datasetId || null,
      governanceProfileRef: governanceProfileRef || null,
    }
  }, [searchParams])

  const InboundBanner = useMemo(() => {
    if (inboundBannerDismissed) return null
    if (!inboundContext.from && !inboundContext.datasetId && !inboundContext.governanceProfileRef) return null
    return (
      <div className="mt-3 rounded-xl border border-border/60 bg-card px-4 py-3 text-[12px] text-muted-foreground flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="text-[11px] uppercase  text-muted-foreground/80">Inbound</div>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            {inboundContext.from ? (
              <span className="px-2 py-0.5 rounded-full border border-border/60 bg-muted/40 font-mono">
                from: {inboundContext.from}
              </span>
            ) : null}
            {inboundContext.datasetId ? (
              <span className="px-2 py-0.5 rounded-full border border-border/60 bg-muted/40 font-mono">
                dataset_id: {inboundContext.datasetId}
              </span>
            ) : null}
            {inboundContext.governanceProfileRef ? (
              <span className="px-2 py-0.5 rounded-full border border-border/60 bg-muted/40 font-mono">
                governance_profile_ref: {inboundContext.governanceProfileRef}
              </span>
            ) : null}
          </div>
          <div className="mt-2 text-[11px] text-muted-foreground">
            提示：该页当前仅做引导展示；如需精确复现清洗效果，请在入库配置/规则中应用对应的 pipeline/governance 配置。
          </div>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-8 w-8 p-0 rounded-full text-muted-foreground hover:text-foreground"
          aria-label="关闭提示"
          onClick={() => setInboundBannerDismissed(true)}
        >
          <X className="w-4 h-4" />
        </Button>
      </div>
    )
  }, [inboundBannerDismissed, inboundContext.datasetId, inboundContext.from, inboundContext.governanceProfileRef])

  const cancelUploadAndParse = useCallback(() => {
    uploadAbortRef.current?.abort()
    uploadAbortRef.current = null
    setUploading(false)
    toast.info('已取消解析')
  }, [])

  // 文件治理状态
  const [governanceStates, setGovernanceStates] = useState<Record<string, FileGovernanceState>>({})

  // 侧边栏状态
  const [sidebarWidth, setSidebarWidth] = useState(280)
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false)
  const [isResizing, setIsResizing] = useState(false)
  const sidebarRef = useRef<HTMLDivElement>(null)

  // 治理面板状态 (右侧)
  const [panelWidth, setPanelWidth] = useState(400)
  const [isPanelCollapsed, setIsPanelCollapsed] = useState(false)
  const [isPanelResizing, setIsPanelResizing] = useState(false)
  const panelRef = useRef<HTMLDivElement>(null)
  const contentScrollRef = useRef<HTMLDivElement>(null)

  // When switching the selected file, reset the main preview pane so it doesn't look "half scrolled".
  useEffect(() => {
    if (!selectedFileId) return
    const raf = window.requestAnimationFrame(() => {
      contentScrollRef.current?.scrollTo({ top: 0, left: 0, behavior: 'auto' })
    })
    return () => window.cancelAnimationFrame(raf)
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
        // 计算相对于视口的位置
        const sidebarLeft = sidebarRef.current.getBoundingClientRect().left
        const newWidth = mouseMoveEvent.clientX - sidebarLeft

        // 限制最小和最大宽度
        if (newWidth > 200 && newWidth < 500) {
          setSidebarWidth(newWidth)
        }
      }

      if (isPanelResizing && panelRef.current) {
        // 右侧面板宽度 = 视口宽度 - 鼠标X
        const newWidth = window.innerWidth - mouseMoveEvent.clientX

        if (newWidth > 300 && newWidth < 800) {
          setPanelWidth(newWidth)
        }
      }
    },
    [isResizing, isPanelResizing]
  )

  useEffect(() => {
    if (isResizing || isPanelResizing) {
      window.addEventListener('mousemove', resize)
      window.addEventListener('mouseup', stopResizing)
    }
    return () => {
      window.removeEventListener('mousemove', resize)
      window.removeEventListener('mouseup', stopResizing)
    }
  }, [isResizing, isPanelResizing, resize, stopResizing])

  // 选中的文件
  const selectedFile = files.find((f) => f.id === selectedFileId) || null
  const governanceState = selectedFileId ? governanceStates[selectedFileId] : null

  const visibleFiles = useMemo(() => {
    if (!activeFolderId || activeFolderId === ROOT_FOLDER_ID) return files

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

    return files.filter((f) => allowedFolderIds.has(f.folderId || ROOT_FOLDER_ID))
  }, [files, activeFolderId, libraryFolders])

  // 初始化文件治理状态
  const initializeGovernanceState = useCallback((file: { id: string; markdownContent: string; originalMarkdownContent?: string }) => {
    const originalContent = file.originalMarkdownContent ?? file.markdownContent
    const cleanedContent = file.markdownContent
    setGovernanceStates((prev) => {
      const existing = prev[file.id]
      if (existing) {
        // If we initialized with empty content (e.g., after refresh), backfill once content is loaded.
        const hasAnyExistingContent = Boolean((existing.originalContent || '').trim() || (existing.cleanedContent || '').trim())
        const hasIncomingContent = Boolean(originalContent.trim() || cleanedContent.trim())
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
  }, [])

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
          updateParsedFile(id, { markdownContent: nextMarkdown, originalMarkdownContent: nextOriginal })
          initializeGovernanceState({ id, markdownContent: nextMarkdown, originalMarkdownContent: nextOriginal })
          return
        }
      } catch {
        // ignore
      }

      try {
        const remote = await parsingApi.getContent(id)
        if (cancelled) return
        const markdown = (remote?.markdown_content || '').trim()
        const original = (remote?.original_markdown_content || '').trim()
        if (!markdown && !original) return
        const nextMarkdown = markdown || original
        const nextOriginal = original || markdown
        updateParsedFile(id, { markdownContent: nextMarkdown, originalMarkdownContent: nextOriginal })
        initializeGovernanceState({ id, markdownContent: nextMarkdown, originalMarkdownContent: nextOriginal })
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

      void (async () => {
        try {
          await parsingApi.delete(fileId)
        } catch {
          // ignore: some entries may be local-only or already deleted on the backend
        }
      })()

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
      toast.success('已删除文件')
    },
    [files, removeFile, selectedFileId]
  )

  // 初始化：自动选择第一个文件
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

  // 上传并解析逻辑（支持 .zip 批量解压）
  const handleUploadAndParse = useCallback(async (incomingFiles: File[]) => {
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
            toast.error(`ZIP 解压失败：${file.name}`)
          }

          if (addedInZip === 0) {
            toast.warning(
              extractedCount === 0
                ? `ZIP 中未找到文件：${file.name}`
                : `ZIP 中没有可解析文件：${file.name}`
            )
          } else {
            toast.success(
              skippedInZip > 0
                ? `已从 ZIP 添加 ${addedInZip} 个文件（跳过 ${skippedInZip} 个）`
                : `已从 ZIP 添加 ${addedInZip} 个文件`
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
        if (controller.signal.aborted || uploadAbortRef.current !== controller) return
        const data = await documentApi.preview(file, parserBackend, undefined, { signal: controller.signal })
        if (controller.signal.aborted || uploadAbortRef.current !== controller) return

        // 拼接 segments 获取全文
        const markdownContent = data.segments.map((s) => s.content).join('\n\n')

        const newId = addParsedFile({
          filename: file.name,
          fileType: file.name.split('.').pop()?.toLowerCase() || '',
          fileSize: file.size,
          markdownContent,
          parser: data.parser_backend,
          folderId,
        })

        // 如果是第一个文件，自动选中
        initializeGovernanceState({ id: newId, markdownContent })
        setSelectedFileId((prev) => prev ?? newId)
      }

      if (added > 0) toast.success(`已解析并加入：${added} 个文件`)
      if (skipped > 0) toast.warning(`已跳过 ${skipped} 个不支持的文件`)
    } catch (error) {
      if (controller.signal.aborted || uploadAbortRef.current !== controller) return
      console.error('Failed to parse file:', error)
      toast.error('解析失败，请稍后重试')
    } finally {
      if (uploadAbortRef.current === controller) {
        uploadAbortRef.current = null
        setUploading(false)
      }
    }
  }, [addParsedFile, initializeGovernanceState, parserBackend, activeFolderId, libraryFolders, createFolder])

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const files = Array.from(e.dataTransfer.files)
    if (files.length > 0) {
      await handleUploadAndParse(files)
    }
  }, [handleUploadAndParse])

  const handleFileSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files ? Array.from(e.target.files) : []
    if (files.length > 0) {
      await handleUploadAndParse(files)
    }
    e.target.value = ''
  }, [handleUploadAndParse])

  // 获取当前显示内容
  const displayContent = useMemo(() => {
    if (!governanceState) return ''
    return viewMode === 'original' ? governanceState.originalContent : governanceState.cleanedContent
  }, [governanceState, viewMode])

  const tocEnabled = useMemo(
    () => extractMarkdownHeadings(displayContent || '', { maxDepth: 4 }).length > 0,
    [displayContent]
  )

  // 文件选择
  const handleSelectFile = useCallback((fileId: string) => {
    const file = files.find((f) => f.id === fileId)
    if (file) {
      setSelectedFileId(fileId)
      initializeGovernanceState(file)
    }
  }, [files, initializeGovernanceState])

  // 手动编辑回调
  const handleManualEdit = useCallback((newContent: string) => {
    if (!selectedFileId) return
    setGovernanceStates((prev) => ({
      ...prev,
      [selectedFileId]: {
        ...prev[selectedFileId],
        cleanedContent: newContent,
        isModified: true, // 手动修改也被视为已修改
      },
    }))
  }, [selectedFileId])

  // 质量检测完成回调
  const handleQualityCheck = useCallback((result: { score: number; issues: FileGovernanceState['issues'] }) => {
    if (!selectedFileId) return
    setGovernanceStates((prev) => ({
      ...prev,
      [selectedFileId]: {
        ...prev[selectedFileId],
        qualityScore: result.score,
        issues: result.issues,
      },
    }))
  }, [selectedFileId])

  // 清洗完成回调
  const handleClean = useCallback((cleanedContent: string) => {
    if (!selectedFileId) return
    setGovernanceStates((prev) => ({
      ...prev,
      [selectedFileId]: {
        ...prev[selectedFileId],
        cleanedContent,
        isModified: cleanedContent !== prev[selectedFileId].originalContent,
      },
    }))
  }, [selectedFileId])

  // 标注完成回调
  const handleAnnotate = useCallback((annotations: FileGovernanceState['annotations']) => {
    if (!selectedFileId) return
    setGovernanceStates((prev) => ({
      ...prev,
      [selectedFileId]: {
        ...prev[selectedFileId],
        annotations,
        isModified: true,
      },
    }))
  }, [selectedFileId])

  // 分类完成回调
  const handleClassify = useCallback((category: string, tags: string[]) => {
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
  }, [selectedFileId])

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
        issues: [],
        isModified: false,
      },
    }))
  }, [selectedFileId, governanceState])

  // 将治理后的内容回写到共享存储（localStorage），以便 /chunk-preview 使用最新版本
  const persistGovernanceEdits = useCallback(() => {
    for (const f of files) {
      const state = governanceStates[f.id]
      if (!state) continue

      // 如果历史数据没有保存 originalMarkdownContent，先用当前内容补齐，避免被后续保存覆盖掉。
      const originalMarkdownContent =
        typeof f.originalMarkdownContent === 'string' ? f.originalMarkdownContent : f.markdownContent

      const shouldUpdateMarkdown = state.cleanedContent != null && state.cleanedContent !== f.markdownContent
      const shouldSetOriginal = typeof f.originalMarkdownContent !== 'string'

      if (shouldUpdateMarkdown || shouldSetOriginal) {
        updateParsedFile(f.id, {
          ...(shouldUpdateMarkdown ? { markdownContent: state.cleanedContent } : {}),
          ...(shouldSetOriginal ? { originalMarkdownContent } : {}),
        })
      }
    }
  }, [files, governanceStates, updateParsedFile])

  const handleSave = useCallback(() => {
    persistGovernanceEdits()
    toast.success('已保存治理结果')
  }, [persistGovernanceEdits])

  // 保存并下一份（留在治理页面）
  const handleSaveAndNextFile = useCallback(() => {
    persistGovernanceEdits()
    toast.success('已保存治理结果')

    // “继续”含义：继续处理下一份文件，而不是跳转回解析流程。
    if (!selectedFileId || files.length === 0) return
    const currentIndex = files.findIndex((f) => f.id === selectedFileId)
    const nextIndex = currentIndex >= 0 ? (currentIndex + 1) % files.length : 0
    const nextFile = files[nextIndex]
    if (nextFile) {
      setSelectedFileId(nextFile.id)
      setViewMode('edit')
      initializeGovernanceState(nextFile)
    }
  }, [persistGovernanceEdits, selectedFileId, files, initializeGovernanceState])

  const handlePushToChunkPreview = useCallback(() => {
    persistGovernanceEdits()
    router.push('/chunk-preview')
  }, [persistGovernanceEdits, router])

  // 返回解析页面
  const handleBackToParsing = useCallback(() => {
    router.push('/parsing')
  }, [router])

  // 统计数据
  const stats = useMemo(() => {
    const totalFiles = files.length
    const completedFiles = Object.values(governanceStates).filter((s) => s.qualityScore > 0).length
    const modifiedFiles = Object.values(governanceStates).filter((s) => s.isModified).length
    const avgScore = Object.values(governanceStates)
      .filter((s) => s.qualityScore > 0)
      .reduce((sum, s) => sum + s.qualityScore, 0) / completedFiles || 0

    return { totalFiles, completedFiles, modifiedFiles, avgScore }
  }, [files, governanceStates])

  // 空状态 - 改为上传引导
  if (isLoaded && files.length === 0) {
    return (
      <div className="flex-1 flex flex-col min-h-0">
        <div className="px-6 md:px-8 pt-6 md:pt-8 pb-5 md:pb-6 flex-shrink-0 relative z-10">
          <PageHeader
            title="数据治理工作台"
            badge="Governance"
            icon={ShieldCheck}
            iconColor="text-primary"
	            description={
	              <span className="flex items-center gap-2">
	                <span className="h-1.5 w-1.5 rounded-full bg-primary/20" />
	                智能文档清洗、标注与结构化处理中心
	              </span>
	            }
	          >
	            <div className="hidden xl:flex items-center gap-3">
	              <IngestionWorkflowStepper />
	            </div>
	          </PageHeader>
	          {InboundBanner}
	        </div>

        <div className="flex-1 flex items-center justify-center p-6 relative">
          <div
            className={cn(
              "group relative w-full max-w-3xl overflow-hidden rounded-3xl border border-dashed p-16 text-center transition-colors duration-200 motion-reduce:transition-none",
              isDragging
                ? "border-primary/50 bg-primary/10"
                : "border-border/50 bg-card/5 hover:border-primary/25 hover:bg-card/[0.07] hover:shadow-md"
            )}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
	            {/* Holographic Grid Background */}
	            <div className="absolute inset-0 bg-[url('/grid.svg')] opacity-[0.03] pointer-events-none" />

	            <div className="relative z-10 flex flex-col items-center">
		              <div className="mb-8 flex size-24 items-center justify-center rounded-full border border-primary/20 bg-primary/10 shadow-sm">
		                {uploading ? (
	                  <Sparkles className="w-10 h-10 text-primary animate-spin motion-reduce:animate-none" />
	                ) : (
	                  <Upload className="w-10 h-10 text-primary" />
	                )}
	              </div>

              <h3 className="text-3xl font-bold text-foreground mb-4 ">
                {uploading ? '正在解析文档...' : '拖拽文档至全息工作台'}
              </h3>
              <p className="text-muted-foreground mb-10 max-w-lg mx-auto text-lg leading-relaxed">
                {uploading
                  ? 'AI 正在分析文档结构并提取内容，请稍候...'
                  : '支持 PDF, Word, Excel, TXT, MD, ZIP 等格式。即刻开启智能治理流程。'
                }
              </p>

              <div className="relative z-20 mx-auto mb-10 w-full max-w-md text-left">
                <div className="mb-3 pl-2 text-xs font-medium text-muted-foreground">文档结构</div>
                <div className="max-h-48 overflow-y-auto overscroll-contain rounded-2xl border border-border/60 bg-muted/30 p-5 shadow-sm">
                  <DocumentFolderTree />
                </div>
              </div>

              <div className="flex justify-center gap-4 relative z-20">
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
                      "flex items-center gap-3 px-8 py-4 rounded-xl font-bold shadow-sm cursor-pointer border bg-info text-info-foreground hover:bg-info/90 border-info/25 dark:bg-info/20 dark:text-foreground dark:hover:bg-info/30 transition-colors duration-150 motion-reduce:transition-none",
                      uploading && "opacity-50 cursor-not-allowed"
                    )}
                  >
                    <Upload className="w-5 h-5" />
                    选择本地文件
                  </label>
                </div>
                {uploading && (
                  <Button
                    type="button"
                    variant="outline"
                    onClick={cancelUploadAndParse}
                    className="flex items-center gap-2 px-8 py-4 rounded-xl border-border/40 bg-card/5 hover:bg-red-500/10 dark:bg-red-500/20 hover:text-red-400 hover:border-red-500/30 transition-colors duration-150 motion-reduce:transition-none text-muted-foreground"
                  >
                    <X className="w-5 h-5" />
                    取消解析
                  </Button>
                )}
              </div>

              <div className="mt-12 flex items-center justify-center gap-8 text-xs font-mono text-muted-foreground uppercase ">
                <span className="flex items-center gap-2 hover:text-sky-400 transition-colors">
                  <FileText className="w-4 h-4" /> Smart Parse
                </span>
                <span className="flex items-center gap-2 hover:text-sky-400 transition-colors">
                  <ShieldCheck className="w-4 h-4" /> Quality Check
                </span>
                <span className="flex items-center gap-2 hover:text-sky-400 transition-colors">
                  <Sparkles className="w-4 h-4" /> Auto Clean
                </span>
              </div>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col bg-background text-foreground min-h-0">
      <div className="px-6 md:px-8 pt-6 md:pt-8 pb-5 md:pb-6 flex-shrink-0 relative z-10">
        <PageHeader
          title="数据治理工作台"
          badge="Workbench"
          icon={ShieldCheck}
          iconColor="text-sky-400"
	          description={
	            <span className="flex items-center gap-2">
	              <span className="w-1.5 h-1.5 rounded-full bg-sky-500/10 dark:bg-sky-500/20 animate-pulse motion-reduce:animate-none" />
	              智能文档结构化处理与质量修复
	            </span>
	          }
	        >
	          <div className="flex items-center gap-3">
            <Button
              variant="outline"
              size="sm"
              onClick={handleReset}
              disabled={!governanceState || !governanceState.isModified}
              className="gap-1.5 h-8 text-xs"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              重置
            </Button>
            <Button
              variant="info"
              size="sm"
              onClick={handleSave}
              disabled={!governanceState}
              className="gap-2 h-8 text-xs"
            >
              <Save className="w-3.5 h-3.5" />
              保存
            </Button>
            <div className="w-px h-4 bg-border dark:bg-card/10 mx-1" />
            <Button
              variant="default"
              size="sm"
              onClick={handlePushToChunkPreview}
              disabled={!isLoaded || files.length === 0}
              className="gap-2 h-8 text-xs"
            >
              <Layers className="w-3.5 h-3.5" />
              推送切块预览
            </Button>
          </div>
          <div className="hidden xl:flex items-center gap-3">
            <div className="w-px h-4 bg-border/60 mx-1" />
            <IngestionWorkflowStepper />
	          </div>
	        </PageHeader>
	        {InboundBanner}
	      </div>

      <div className="flex-1 flex overflow-hidden min-h-0 relative bg-background">
        {/* 左侧文件列表 */}
	        <aside
	          ref={sidebarRef}
	          className={cn(
	            "group/sidebar relative flex flex-col flex-shrink-0 bg-card border-r border-border z-10",
	            isSidebarCollapsed ? "w-0 border-r-0" : ""
	          )}
	          style={{ width: isSidebarCollapsed ? 0 : sidebarWidth }}
	        >
          {/* 折叠/展开按钮 */}
	          <Button
	            variant="ghost"
	            size="icon"
            className={cn(
              "absolute -right-3 top-3 z-30 h-6 w-6 rounded-full border border-border bg-card shadow-sm text-muted-foreground hover:text-muted-foreground hover:bg-muted transition-opacity opacity-0 group-hover/sidebar:opacity-100",
              isSidebarCollapsed && "opacity-100 -right-8 translate-x-2"
            )}
	            onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
	            title={isSidebarCollapsed ? "展开侧边栏" : "收起侧边栏"}
	            aria-label={isSidebarCollapsed ? "展开侧边栏" : "收起侧边栏"}
	          >
            {isSidebarCollapsed ? <PanelRightOpen className="w-3 h-3" /> : <PanelRightClose className="w-3 h-3" />}
          </Button>

          <div className={cn("flex-1 flex flex-col min-h-0 w-full overflow-hidden", isSidebarCollapsed && "invisible")}>
            {/* 目录切换 & 搜索 */}
            <div className="p-3 border-b border-border space-y-3">
              <Select value={activeFolderId || ROOT_FOLDER_ID} onValueChange={setActiveFolderId}>
                <SelectTrigger className="h-9 text-xs bg-muted border-border text-foreground/80 focus:bg-card focus-ring transition-colors duration-200 motion-reduce:transition-none">
                  <div className="flex items-center gap-2 truncate">
                    <FolderTree className="w-3.5 h-3.5 text-primary" />
                    <SelectValue placeholder="切换目录" />
                  </div>
                </SelectTrigger>
                <SelectContent className="bg-card border-border text-foreground/80">
                  <SelectItem value={ROOT_FOLDER_ID}>根目录</SelectItem>
                  {libraryFolders.map(f => (
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
                  placeholder="搜索当前目录文件..."
                  className="w-full rounded-lg border border-border bg-muted py-1.5 pl-9 pr-3 text-xs text-foreground/80 placeholder:text-muted-foreground focus:bg-card focus:outline-none focus:border-primary/30 focus-ring transition-colors duration-200 motion-reduce:transition-none"
                />
              </div>
            </div>

            {/* 文件目录树 - 可折叠区域 */}
            <div className="px-3 pt-2 pb-1 border-b border-border bg-muted/50">
              <div className="max-h-48 overflow-y-auto overscroll-contain no-scrollbar p-1">
                <DocumentFolderTree />
              </div>
            </div>

            <div className="flex items-center justify-between px-4 py-2 mt-2">
              <h3 className="text-xs font-bold text-muted-foreground uppercase  pl-1">
                Files ({visibleFiles.length})
              </h3>
            </div>

            <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar px-3 pb-3 space-y-2">
              {visibleFiles.length === 0 ? (
                <div className="text-xs text-muted-foreground text-center py-8">该目录暂无文件</div>
              ) : (
                visibleFiles.map((file) => {
                  const state = governanceStates[file.id]
                  const hasIssue = state?.issues.some((i) => i.type === 'error')
                  const score = state?.qualityScore || 0

                  return (
                    <div
                      key={file.id}
                      onClick={() => handleSelectFile(file.id)}
                      className={cn(
                        "w-full text-left p-4 rounded-xl border transition-colors transition-shadow duration-200 motion-reduce:transition-none cursor-pointer group relative",
                        selectedFileId === file.id
                          ? "bg-sky-500/10 dark:bg-sky-500/20 border-sky-200 shadow-md ring-1 ring-sky-100"
                          : "bg-card border-border hover:border-sky-200 hover:shadow-sm"
                      )}
                    >
                      <div className="flex items-start gap-4">
                        {/* File Icon */}
                        {getFileIcon(file.filename, cn(
                          "size-12 rounded-xl shadow-sm border transition-colors transition-shadow mr-0 motion-reduce:transition-none",
                          selectedFileId === file.id
                            ? "ring-2 ring-sky-100 ring-offset-1 border-sky-200"
                            : "border-border group-hover:border-sky-200 group-hover:shadow-md"
                        ))}

                        <div className="flex-1 min-w-0">
                          {/* Row 1: Filename & Score */}
                          <div className="flex items-center justify-between mb-1">
                            <div className={cn(
                              "text-sm font-bold truncate mr-2 transition-colors",
                              selectedFileId === file.id ? "text-sky-600 dark:text-sky-300" : "text-foreground/80 group-hover:text-foreground"
                            )}>
                              {file.filename}
                            </div>
                            {score > 0 ? (
                              <span className={cn(
                                "flex-shrink-0 text-[10px] px-2 py-0.5 rounded-full font-bold shadow-sm border",
                                score >= 80 ? "bg-emerald-500/10 dark:bg-emerald-500/20 text-emerald-700 border-emerald-500/30" :
                                  score >= 60 ? "bg-amber-500/10 dark:bg-amber-500/20 text-amber-700 dark:text-amber-300 border-amber-500/30" :
                                    "bg-rose-50 text-rose-700 border-rose-100"
                              )}>
                                {score}分
                              </span>
                            ) : (
                              <span className="flex-shrink-0 text-[10px] text-muted-foreground bg-muted px-2 py-0.5 rounded-full border border-border font-medium">未检测</span>
                            )}
                          </div>

                          {/* Row 2: Metadata (Size & Date) */}
                          <div className="flex items-center gap-2 text-[10px] text-muted-foreground mb-2 font-medium font-mono">
                            <span>{formatFileSize(file.fileSize)}</span>
                            <span className="text-muted-foreground">|</span>
                            <span>
                              {file.parsedAt ? new Date(file.parsedAt).toLocaleDateString([], {
                                year: 'numeric',
                                month: '2-digit',
                                day: '2-digit'
                              }) : ''}
                            </span>
                          </div>

                          {/* Row 3: Badges & Actions */}
                          <div className="flex items-center justify-between h-5">
                            <div className="flex items-center gap-2">
                              {state?.isModified && (
                                <span className="text-[9px] text-sky-600 dark:text-sky-300 flex items-center gap-1 bg-sky-500/10 dark:bg-sky-500/20 px-1.5 py-0.5 rounded border border-sky-500/30 font-bold">
                                  <Sparkles className="w-2.5 h-2.5" /> 已清洗
                                </span>
                              )}
                              {hasIssue && (
                                <span className="text-[9px] text-rose-600 flex items-center gap-1 bg-rose-50 px-1.5 py-0.5 rounded border border-rose-100 font-bold">
                                  <AlertTriangle className="w-2.5 h-2.5" /> 需关注
                                </span>
                              )}
                            </div>

                            <button
                              type="button"
                              onClick={(e) => {
                                e.stopPropagation()
                                setDeleteFileTarget({ id: file.id, filename: file.filename })
                                setDeleteFileOpen(true)
                              }}
                              className="opacity-0 group-hover:opacity-100 p-1 -mr-1 text-muted-foreground hover:text-rose-600 hover:bg-rose-50 rounded transition-opacity transition-colors duration-150 motion-reduce:transition-none"
                              aria-label={`删除文件：${file.filename}`}
                              title="删除文件"
                            >
                              <Trash2 className="w-3.5 h-3.5" />
                            </button>
                          </div>
                        </div>
                      </div>
                    </div>
                  )
                })
              )}
            </div>

            {/* 底部统计栏 */}
            <div className="mt-auto border-t border-border bg-muted/50 p-3 space-y-2 backdrop-blur-sm">
              <div className="grid grid-cols-2 gap-2">
                <div className="bg-card p-2 rounded-lg border border-border hover:border-sky-500/30 transition-colors">
                  <div className="text-[10px] text-muted-foreground mb-0.5 uppercase ">Storage</div>
                  <div className="text-sm font-bold text-foreground/80 flex items-baseline gap-1 font-mono">
                    {stats.completedFiles} <span className="text-muted-foreground font-normal text-xs">/ {stats.totalFiles}</span>
                  </div>
                </div>
                <div className="bg-card p-2 rounded-lg border border-border hover:border-emerald-500/30 transition-colors">
                  <div className="text-[10px] text-muted-foreground mb-0.5 uppercase ">Avg Score</div>
                  <div className="text-sm font-bold text-foreground/80 font-mono">
                    {stats.avgScore > 0 ? stats.avgScore.toFixed(1) : '-'}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* 拖拽手柄 */}
          <div
            className={cn(
              "absolute right-0 top-0 w-1 h-full cursor-col-resize z-20 transition-colors opacity-0 hover:opacity-100 hover:bg-primary/10 dark:hover:bg-primary/20 active:bg-primary/30",
              isResizing && "bg-primary opacity-100"
            )}
            onMouseDown={startResizing}
          />
        </aside>

        {/* 主内容区 (中间 + 右侧面板) */}
        <main className="flex-1 flex overflow-hidden min-h-0 relative">

          {selectedFile && governanceState ? (
            <>
              {/* 中间：预览画布 */}
              <div className="flex-1 flex flex-col overflow-hidden relative z-0">
                {/* 画布工具栏 (悬浮或集成) */}
                <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 flex items-center bg-card/80 backdrop-blur-md border border-border shadow-sm rounded-full px-2 py-1 gap-1 transition-colors duration-150 motion-reduce:transition-none hover:bg-card hover:border-border">
                  {/* 视图切换 */}
                  <div className="flex items-center bg-muted rounded-full p-0.5 border border-border">
                    <button
                      onClick={() => setViewMode('preview')}
                      className={cn(
                        "px-3 py-1 rounded-full text-xs font-medium transition-colors duration-150 motion-reduce:transition-none",
                        viewMode === 'preview' ? "bg-card text-sky-600 dark:text-sky-300 shadow-sm ring-1 ring-black/5" : "text-muted-foreground hover:text-foreground/80 hover:bg-black/5"
                      )}
                    >
                      预览
                    </button>
                    <button
                      onClick={() => setViewMode('edit')}
                      className={cn(
                        "px-3 py-1 rounded-full text-xs font-medium transition-colors duration-150 motion-reduce:transition-none",
                        viewMode === 'edit' ? "bg-card text-sky-600 dark:text-sky-300 shadow-sm ring-1 ring-black/5" : "text-muted-foreground hover:text-foreground/80 hover:bg-black/5"
                      )}
                    >
                      编辑
                    </button>
                    <button
                      onClick={() => setViewMode('original')}
                      className={cn(
                        "px-3 py-1 rounded-full text-xs font-medium transition-colors duration-150 motion-reduce:transition-none",
                        viewMode === 'original' ? "bg-card text-sky-600 dark:text-sky-300 shadow-sm ring-1 ring-black/5" : "text-muted-foreground hover:text-foreground/80 hover:bg-black/5"
                      )}
                    >
                      对比
                    </button>
                  </div>

                  <div className="w-px h-3 bg-border mx-1" />

	                  <Button
	                    variant="ghost"
	                    size="icon"
	                    className="h-7 w-7 rounded-full text-muted-foreground hover:text-foreground/80 hover:bg-muted"
	                    onClick={() => setPreviewFormat(prev => prev === 'rendered' ? 'markdown' : 'rendered')}
	                    title={previewFormat === 'rendered' ? "查看源码" : "查看渲染"}
	                    aria-label={previewFormat === 'rendered' ? "查看源码" : "查看渲染"}
	                  >
	                    {previewFormat === 'rendered' ? <Hash className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
	                  </Button>
                </div>

                {/* 左侧收起按钮 (如果左侧收起) */}
                {isSidebarCollapsed && (
	                  <Button
	                    variant="ghost"
	                    size="icon"
	                    onClick={() => setIsSidebarCollapsed(false)}
	                    className="absolute left-4 top-4 z-20 h-8 w-8 bg-card/80 border border-border shadow-sm rounded-lg text-muted-foreground hover:text-sky-600 dark:text-sky-300 hover:bg-card backdrop-blur-md transition-colors duration-150 motion-reduce:transition-none"
	                    aria-label="展开侧边栏"
	                    title="展开侧边栏"
	                  >
	                    <PanelRightOpen className="w-4 h-4" />
	                  </Button>
                )}

                {isPanelCollapsed && (
	                  <Button
	                    variant="ghost"
	                    size="icon"
	                    onClick={() => setIsPanelCollapsed(false)}
	                    className="absolute right-4 top-4 z-20 h-8 w-8 bg-card/80 border border-border shadow-sm rounded-lg text-muted-foreground hover:text-sky-600 dark:text-sky-300 hover:bg-card backdrop-blur-md transition-colors duration-150 motion-reduce:transition-none"
	                    aria-label="展开右侧面板"
	                    title="展开右侧面板"
	                  >
	                    <PanelRightClose className="w-4 h-4 rotate-180" />
	                  </Button>
                )}

                {/* 内容区域 */}
                <div ref={contentScrollRef} className="flex-1 overflow-y-auto overscroll-contain no-scrollbar p-4 md:p-8">
                  <div className={cn(
                    "mx-auto",
                    viewMode === 'edit' ? 'max-w-full' : 'max-w-4xl'
                  )}>
                    {/* 纸张效果容器 */}
                    <div className={cn(
                      "bg-card min-h-[800px] shadow-sm border border-border/60 rounded-xl overflow-hidden relative",
                      viewMode === 'edit' ? "h-[calc(100vh-140px)] border-0 shadow-none bg-transparent" : "p-10 md:p-14"
                    )}>
                      {/* 治理状态水印/徽章 */}
                      {viewMode !== 'edit' && governanceState.isModified && (
                        <div className="absolute top-0 right-0 p-4">
                          <span className="bg-purple-500/10 dark:bg-purple-500/20 text-purple-700 dark:text-purple-300 border border-purple-500/30 text-xs px-2 py-1 rounded-md font-medium shadow-sm">
                            已修改
                          </span>
                        </div>
                      )}

                      {viewMode === 'edit' ? (
                        <div className="grid grid-cols-2 gap-4 h-full">
                          {/* 编辑模式：左侧预览 */}
                          <div className="flex flex-col bg-muted rounded-xl border border-border shadow-sm overflow-hidden h-full">
                            <div className="px-4 py-2 bg-muted border-b border-border text-xs font-semibold text-muted-foreground">
                              实时预览
                            </div>
                            <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar p-6">
                              <MarkdownRenderer markdown={displayContent || ''} />
                            </div>
                          </div>
                          {/* 编辑模式：右侧源码 */}
                          <div className="flex flex-col bg-card rounded-xl border border-border shadow-sm overflow-hidden h-full">
                            <div className="px-4 py-2 bg-muted border-b border-border text-xs font-semibold text-muted-foreground">
                              源码编辑
                            </div>
                            <textarea
                              value={displayContent}
                              onChange={(e) => handleManualEdit(e.target.value)}
                              className="flex-1 w-full p-6 resize-none outline-none font-mono text-sm leading-relaxed text-foreground"
                              spellCheck={false}
                            />
                          </div>
                        </div>
                      ) : (
                        // 预览模式
                        displayContent?.includes('该条目来自文档库（未保留本地 PDF 原文件）') ? (
                          <div className="flex flex-col items-center justify-center h-full p-8 text-center">
                            <div className="w-16 h-16 bg-muted rounded-2xl flex items-center justify-center mb-6 border border-border shadow-sm">
                              <FileText className="w-8 h-8 text-muted-foreground" />
                            </div>
                            <h3 className="text-lg font-bold text-foreground mb-2 truncate max-w-lg">
                              {selectedFile?.filename || '未知文件'}
                            </h3>
                            <div className="flex items-center gap-2 mb-8">
                              <span className="px-2.5 py-1 rounded-full bg-muted text-muted-foreground text-xs font-medium border border-border">
                                文档库
                              </span>
                              <span className="px-2.5 py-1 rounded-full bg-amber-500/10 dark:bg-amber-500/20 text-amber-700 dark:text-amber-300 text-xs font-medium border border-amber-500/30 flex items-center gap-1">
                                <div className="w-1.5 h-1.5 rounded-full bg-amber-500/10 dark:bg-amber-500/20" />
                                Pending
                              </span>
                            </div>

                            <div className="max-w-md bg-muted rounded-xl p-5 border border-border mb-8 text-left">
                              <p className="text-sm text-muted-foreground leading-relaxed flex gap-3">
                                <Info className="w-5 h-5 text-sky-500 flex-shrink-0 mt-0.5" />
                                该条目来自文档库（未保留本地 PDF 原文件）。可查看解析后的 Markdown；如需 PDF 预览请重新上传该文件。
                              </p>
                            </div>

                            <div className="flex items-center gap-3">
                              <Button
                                variant="outline"
                                className="gap-2 bg-card hover:bg-muted text-foreground/80 border-border"
                                onClick={() => {
                                  if (selectedFile?.filename) {
                                    navigator.clipboard.writeText(selectedFile.filename)
                                    toast.success('文件名已复制')
                                  }
                                }}
                              >
                                <Copy className="w-4 h-4" />
                                复制名称
                              </Button>
                              <ConfirmDialog
                                title="移除该文件？"
                                description="将从文档库中移除该文件记录。此操作不可恢复。"
                                confirmLabel="移除"
                                cancelLabel="返回"
                                confirmVariant="destructive"
                                confirmDisabled={!selectedFileId}
                                onConfirm={() => {
                                  if (!selectedFileId) return
                                  const { removeFile } = useParsedFiles.getState()
                                  removeFile(selectedFileId)
                                  setSelectedFileId(null)
                                  toast.success('文件已移除')
                                }}
                              >
                                <Button
                                  variant="outline"
                                  className="gap-2 bg-card hover:bg-red-500/10 dark:bg-red-500/20 text-foreground/80 hover:text-red-600 dark:text-red-300 border-border hover:border-red-500/30"
                                  disabled={!selectedFileId}
                                >
                                  <Trash2 className="w-4 h-4" />
                                  移除文件
                                </Button>
                              </ConfirmDialog>
                            </div>
                          </div>
                        ) : (
                          previewFormat === 'rendered' ? (
                            <div className="prose prose-slate dark:prose-invert max-w-none prose-headings:text-foreground prose-p:text-muted-foreground prose-a:text-sky-600 dark:prose-a:text-sky-300">
                              <MarkdownRenderer markdown={displayContent || ''} />
                            </div>
                          ) : (
                            <pre className="font-mono text-sm leading-relaxed whitespace-pre-wrap break-words text-foreground">
                              {displayContent || ''}
                            </pre>
                          )
                        )
                      )}
                    </div>
                  </div>
                </div>
              </div>

              {/* 右侧：治理工具面板 (整合了 Tabs) */}
                <div
                  ref={panelRef}
                  className={cn(
                  "group/panel relative flex-shrink-0 border-l border-border bg-card flex flex-col transition-transform duration-200 ease-out motion-reduce:transition-none z-10 shadow-strong",
                  isPanelCollapsed ? "w-0 border-l-0 translate-x-full" : ""
                )}
                  style={{ width: isPanelCollapsed ? 0 : panelWidth }}
                >
                {/* 工具面板头部：治理阶段选择 */}
                <div className="flex-shrink-0 p-4 border-b border-border bg-card">
                  <div className="flex items-center justify-between mb-4">
                    <h2 className="text-sm font-bold text-foreground flex items-center gap-2">
                      <Sparkles className="w-4 h-4 text-sky-600 dark:text-sky-300" />
                      治理工具箱
                    </h2>
                    <Button
                      variant="ghost"
                      size="icon"
                      className="h-6 w-6 text-muted-foreground hover:text-muted-foreground hover:bg-muted"
                      onClick={() => setIsPanelCollapsed(true)}
                    >
                      <PanelRightClose className="w-4 h-4 rotate-180" />
                    </Button>
                  </div>

                  {/* 新的 Tab 选择器 */}
                  <div className="grid grid-cols-4 gap-1 p-1 bg-muted rounded-lg border border-border">
                    {GOVERNANCE_TABS.map((tab) => {
                      const Icon = tab.icon
                      const isActive = activeTab === tab.id
                      return (
                        <button
                          key={tab.id}
                          onClick={() => setActiveTab(tab.id)}
                          className={cn(
                            "flex flex-col items-center justify-center py-2 px-1 rounded-md transition-colors transition-shadow duration-150 motion-reduce:transition-none relative",
                            isActive
                              ? "bg-card text-sky-600 dark:text-sky-300 shadow-sm ring-1 ring-slate-200"
                              : "text-muted-foreground hover:text-foreground/80 hover:bg-border/50"
                          )}
                          title={tab.label}
                        >
                          <Icon className={cn("w-4 h-4 mb-1", isActive ? "text-sky-600 dark:text-sky-300" : "")} />
                          <span className="text-[10px] font-medium scale-90">{tab.label}</span>
                          {/* 状态点 */}
                          {tab.id === 'clean' && governanceState.isModified && (
                            <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 bg-purple-500/10 dark:bg-purple-500/20 rounded-full ring-1 ring-white shadow-sm" />
                          )}
                        </button>
                      )
                    })}
                  </div>

                  {/* 当前工具描述 */}
                  <div className="mt-3 text-xs text-muted-foreground bg-sky-500/10 dark:bg-sky-500/20 p-2 rounded border border-sky-500/30 flex items-start gap-2">
                    <Info className="w-3.5 h-3.5 text-sky-500 mt-0.5 flex-shrink-0" />
                    {GOVERNANCE_TABS.find(t => t.id === activeTab)?.desc}
                  </div>
                </div>

                {/* 工具内容区 */}
                <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar bg-muted/30">
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

                {/* 拖拽手柄 */}
                <div
                  className={cn(
                    "absolute left-0 top-0 w-1 h-full cursor-col-resize z-20 transition-colors opacity-0 hover:opacity-100 hover:bg-primary/10 dark:hover:bg-primary/20 active:bg-primary/30",
                    isPanelResizing && "bg-primary opacity-100"
                  )}
                  onMouseDown={startPanelResizing}
                />
              </div>
            </>
          ) : (
            // 空状态占位
            <div className="flex-1 flex flex-col items-center justify-center bg-muted">
              <div className="w-24 h-24 bg-card rounded-full border border-border flex items-center justify-center mb-6 shadow-sm">
                <FileSearch className="w-10 h-10 text-muted-foreground" />
              </div>
              <h3 className="text-xl font-medium text-foreground mb-2">选择文件开始治理</h3>
              <p className="text-muted-foreground max-w-sm text-center">
                从左侧列表选择一个文件，使用右侧工具箱进行质量检测、清洗与标注。
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
            <AlertDialogTitle>删除文件？</AlertDialogTitle>
            <AlertDialogDescription>
              你将删除文件 <span className="font-mono">{deleteFileTarget?.filename || '-'}</span>。此操作不可撤销。
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>取消</AlertDialogCancel>
            <AlertDialogAction
              onClick={() => {
                const id = deleteFileTarget?.id
                if (!id) return
                handleDeleteFile(id)
              }}
            >
              删除
            </AlertDialogAction>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  )
}
