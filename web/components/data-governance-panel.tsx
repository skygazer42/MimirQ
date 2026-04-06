/**
 * 鏁版嵁娌荤悊宸ヤ綔鍙扮粍浠?
 * 鍔熻兘锛氳川閲忔娴嬨€佹櫤鑳芥竻娲椼€佹暟鎹爣娉ㄣ€佸垎绫诲綊妗?
 */
'use client'

import { useState, useCallback, useMemo, useEffect, useRef } from 'react'
import { ShieldCheck, Sparkles, Tag, FolderTree, FileText, Upload, Save, RotateCcw, Trash2, Eye, Search, Wrench, ScanLine, FileSearch, Hash, Layers, X, Info, AlertTriangle, Copy, PanelRightOpen, PanelRightClose } from 'lucide-react'
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
import { ROOT_FOLDER_ID, useParsedFiles } from '@/store/use-parsed-files-store'
import { cn, formatFileSize, detachPromise } from '@/lib/utils'
import { getDocContentFromCache } from '@/lib/doc-content-cache'
import { QualityChecker } from '@/components/data-governance/quality-checker'
import { DataCleaner } from '@/components/data-governance/data-cleaner'
import { DataAnnotator } from '@/components/data-governance/data-annotator'
import { DataClassifier } from '@/components/data-governance/data-classifier'
import { documentApi, parsingApi } from '@/lib/api'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { MarkdownRenderer } from '@/components/markdown/markdown-renderer'

import { DocumentFolderTree, getFileIcon } from '@/components/document-library/folder-tree'
import { extractZipFiles, isZipFile } from '@/lib/zip'
import { UPLOAD_ACCEPT_WITH_ZIP, ZIP_ALLOWED_EXTENSIONS } from '@/lib/upload-extensions'

const GOVERNANCE_TAB_CONFIGS = [
  { id: 'quality', icon: ScanLine, color: 'blue' },
  { id: 'clean', icon: Wrench, color: 'green' },
  { id: 'annotate', icon: Tag, color: 'purple' },
  { id: 'classify', icon: FolderTree, color: 'orange' },
] as const

type GovernanceTab = typeof GOVERNANCE_TAB_CONFIGS[number]['id']

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
  const updateParsedFile = useParsedFiles((state) => state.updateParsedFile)
  const removeFile = useParsedFiles((state) => state.removeFile)
  const { parserBackend } = useParserBackendPreference()

  // UI 鐘舵€?
  const [activeTab, setActiveTab] = useState<GovernanceTab>('quality')
  const [inboundBannerDismissed, setInboundBannerDismissed] = useState(false)
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<'edit' | 'preview' | 'original'>('preview')
  const [previewFormat, setPreviewFormat] = useState<'rendered' | 'markdown'>('rendered')
  const [isDragging, setIsDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const [deleteFileOpen, setDeleteFileOpen] = useState(false)
  const [deleteFileTarget, setDeleteFileTarget] = useState<{ id: string; filename: string } | null>(null)
  const uploadAbortRef = useRef<AbortController | null>(null)
  const headerTitle = t("header.title")
  const headerSubtitle = t("header.subtitle")
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
          <div className="text-[11px] uppercase  text-muted-foreground/80">{t('inbound.title')}</div>
          <div className="mt-1 flex flex-wrap items-center gap-2">
            {inboundContext.from ? (
              <span className="px-2 py-0.5 rounded-full border border-border/60 bg-muted/40 font-mono">
                {t('inbound.fromLabel')}: {inboundContext.from}
              </span>
            ) : null}
            {inboundContext.datasetId ? (
              <span className="px-2 py-0.5 rounded-full border border-border/60 bg-muted/40 font-mono">
                {t('inbound.datasetLabel')}: {inboundContext.datasetId}
              </span>
            ) : null}
            {inboundContext.governanceProfileRef ? (
              <span className="px-2 py-0.5 rounded-full border border-border/60 bg-muted/40 font-mono">
                {t('inbound.profileLabel')}: {inboundContext.governanceProfileRef}
              </span>
            ) : null}
          </div>
          <div className="mt-2 text-[11px] text-muted-foreground">
            {t('inbound.description')}
          </div>
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          className="h-8 w-8 p-0 rounded-full text-muted-foreground hover:text-foreground"
          aria-label={t('inbound.close')}
          onClick={() => setInboundBannerDismissed(true)}
        >
          <X className="w-4 h-4" />
        </Button>
      </div>
    )
  }, [
    inboundBannerDismissed,
    inboundContext.datasetId,
    inboundContext.from,
    inboundContext.governanceProfileRef,
    t,
  ])

  const cancelUploadAndParse = useCallback(() => {
    uploadAbortRef.current?.abort()
    uploadAbortRef.current = null
    setUploading(false)
    toast.info(t('toasts.uploadCancelled'))
  }, [t])

  // 鏂囦欢娌荤悊鐘舵€?
  const [governanceStates, setGovernanceStates] = useState<Record<string, FileGovernanceState>>({})

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

  // When switching the selected file, reset the main preview pane so it doesn't look "half scrolled".
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

  // 閫変腑鐨勬枃浠?
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

  // 鍒濆鍖栨枃浠舵不鐞嗙姸鎬?
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

      detachPromise((async () => {
        try {
          await parsingApi.delete(fileId)
        } catch {
          // ignore: some entries may be local-only or already deleted on the backend
        }
      })())

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

    const stillVisible = selectedFileId && visibleFiles.some((f) => f.id === selectedFileId)
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
                ? t('toasts.zipAddedWithSkipped', { added: addedInZip, skipped: skippedInZip })
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
        if (controller.signal.aborted || uploadAbortRef.current !== controller) return
        const data = await documentApi.preview(file, parserBackend, undefined, { signal: controller.signal })
        if (controller.signal.aborted || uploadAbortRef.current !== controller) return

        // 鎷兼帴 segments 鑾峰彇鍏ㄦ枃
        const markdownContent = data.segments.map((s) => s.content).join('\n\n')

        const newId = addParsedFile({
          filename: file.name,
          fileType: file.name.split('.').pop()?.toLowerCase() || '',
          fileSize: file.size,
          markdownContent,
          parser: data.parser_backend,
          folderId,
        })

        // 濡傛灉鏄涓€涓枃浠讹紝鑷姩閫変腑
        initializeGovernanceState({ id: newId, markdownContent })
        setSelectedFileId((prev) => prev ?? newId)
      }

      if (added > 0) toast.success(t('toasts.parsedAndAdded', { count: added }))
      if (skipped > 0) toast.warning(t('toasts.skippedUnsupported', { count: skipped }))
    } catch (error) {
      if (controller.signal.aborted || uploadAbortRef.current !== controller) return
      console.error('Failed to parse file:', error)
      toast.error(t('toasts.parseFailed'))
    } finally {
      if (uploadAbortRef.current === controller) {
        uploadAbortRef.current = null
        setUploading(false)
      }
    }
  }, [activeFolderId, addParsedFile, createFolder, initializeGovernanceState, libraryFolders, parserBackend, t])

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

  // 鑾峰彇褰撳墠鏄剧ず鍐呭
  const displayContent = useMemo(() => {
    if (!governanceState) return ''
    return viewMode === 'original' ? governanceState.originalContent : governanceState.cleanedContent
  }, [governanceState, viewMode])
  const libraryOnlyNotice = t('libraryFile.notice')


  // 鏂囦欢閫夋嫨
  const handleSelectFile = useCallback((fileId: string) => {
    const file = files.find((f) => f.id === fileId)
    if (file) {
      setSelectedFileId(fileId)
      initializeGovernanceState(file)
    }
  }, [files, initializeGovernanceState])

  // 鎵嬪姩缂栬緫鍥炶皟
  const handleManualEdit = useCallback((newContent: string) => {
    if (!selectedFileId) return
    setGovernanceStates((prev) => ({
      ...prev,
      [selectedFileId]: {
        ...prev[selectedFileId],
        cleanedContent: newContent,
        isModified: true, // 鎵嬪姩淇敼涔熻瑙嗕负宸蹭慨鏀?
      },
    }))
  }, [selectedFileId])

  // 璐ㄩ噺妫€娴嬪畬鎴愬洖璋?
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

  // 娓呮礂瀹屾垚鍥炶皟
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

  // 鏍囨敞瀹屾垚鍥炶皟
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

  // 鍒嗙被瀹屾垚鍥炶皟
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
  const persistGovernanceEdits = useCallback(() => {
    for (const f of files) {
      const state = governanceStates[f.id]
      if (!state) continue

      // 濡傛灉鍘嗗彶鏁版嵁娌℃湁淇濆瓨 originalMarkdownContent锛屽厛鐢ㄥ綋鍓嶅唴瀹硅ˉ榻愶紝閬垮厤琚悗缁繚瀛樿鐩栨帀銆?
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
    toast.success(t('toasts.resultsSaved'))
  }, [persistGovernanceEdits, t])


  const handlePushToChunkPreview = useCallback(() => {
    persistGovernanceEdits()
    router.push('/chunk-preview')
  }, [persistGovernanceEdits, router])


  // 缁熻鏁版嵁
  const stats = useMemo(() => {
    const totalFiles = files.length
    const completedFiles = Object.values(governanceStates).filter((s) => s.qualityScore > 0).length
    const modifiedFiles = Object.values(governanceStates).filter((s) => s.isModified).length
    const avgScore = Object.values(governanceStates)
      .filter((s) => s.qualityScore > 0)
      .reduce((sum, s) => sum + s.qualityScore, 0) / completedFiles || 0

    return { totalFiles, completedFiles, modifiedFiles, avgScore }
  }, [files, governanceStates])

  // 绌虹姸鎬?- 鏀逛负涓婁紶寮曞
  if (isLoaded && files.length === 0) {
    return (
      <WorkbenchScaffold
        title={headerTitle}
        badge={t('header.emptyBadge')}
        icon={ShieldCheck}
        iconColor="text-success"
        compactHeader
        description={
          <span className="flex items-center gap-2 text-[13px] text-muted-foreground/80">
            <span className="h-1.5 w-1.5 rounded-full bg-primary/20" aria-hidden="true" />
            <span>{headerSubtitle}</span>
          </span>
        }
        size="full"
        bodyClassName="px-0 pb-0"
        top={InboundBanner}
        pipelineRail={<PipelineRail />}
        mainPanel={
          <div className="flex-1 flex flex-col min-h-0">
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
			              <button
                      type="button"
                      className="flex flex-col items-center rounded-2xl bg-transparent text-center"
                      onClick={() => globalThis.document.getElementById('file-upload')?.click()}
                      disabled={uploading}
                      aria-label={t('emptyUpload.openUploadDialog')}
                    >
			                  <div className="mb-8 flex size-24 items-center justify-center rounded-full border border-primary/20 bg-primary/10 shadow-sm">
			                    {uploading ? (
			                      <Sparkles className="w-10 h-10 text-primary animate-spin motion-reduce:animate-none" />
			                    ) : (
			                      <Upload className="w-10 h-10 text-primary" />
			                    )}
			                  </div>

                      <h3 className="text-3xl font-bold text-foreground mb-4">
                        {uploading ? t('emptyUpload.uploadingTitle') : t('emptyUpload.idleTitle')}
                      </h3>
                      <p className="text-muted-foreground mb-10 max-w-lg mx-auto text-lg leading-relaxed">
                        {uploading
                          ? t('emptyUpload.uploadingDescription')
                          : t('emptyUpload.idleDescription')
                        }
                      </p>
                    </button>

	              <div className="relative z-20 mx-auto mb-10 w-full max-w-md text-left">
	                  <div className="mb-3 pl-2 text-xs font-medium text-muted-foreground">{t('emptyUpload.structureTitle')}</div>
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
                    {t('emptyUpload.selectLocalFiles')}
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
                    {t('emptyUpload.cancelParsing')}
                  </Button>
                )}
              </div>

              <div className="mt-12 flex items-center justify-center gap-8 text-xs font-mono text-muted-foreground uppercase ">
                <span className="flex items-center gap-2 hover:text-sky-400 transition-colors">
                  <FileText className="w-4 h-4" /> {t('emptyUpload.stages.parse')}
                </span>
                <span className="flex items-center gap-2 hover:text-sky-400 transition-colors">
                  <ShieldCheck className="w-4 h-4" /> {t('emptyUpload.stages.quality')}
                </span>
                <span className="flex items-center gap-2 hover:text-sky-400 transition-colors">
                  <Sparkles className="w-4 h-4" /> {t('emptyUpload.stages.clean')}
                </span>
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
          <div className="px-4 py-2 bg-muted border-b border-border text-xs font-semibold text-muted-foreground">
            {t('canvas.livePreview')}
          </div>
          <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar p-6">
            <MarkdownRenderer markdown={displayContent || ''} />
          </div>
        </div>
        <div className="flex flex-col bg-card rounded-xl border border-border shadow-sm overflow-hidden h-full">
          <div className="px-4 py-2 bg-muted border-b border-border text-xs font-semibold text-muted-foreground">
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
        <h3 className="text-lg font-bold text-foreground mb-2 truncate max-w-lg">
          {selectedFile?.filename || t('libraryFile.unknownFile')}
        </h3>
        <div className="flex items-center gap-2 mb-8">
          <span className="px-2.5 py-1 rounded-full bg-muted text-muted-foreground text-xs font-medium border border-border">
            {t('libraryFile.badge')}
          </span>
          <span className="px-2.5 py-1 rounded-full bg-amber-500/10 dark:bg-amber-500/20 text-amber-700 dark:text-amber-300 text-xs font-medium border border-amber-500/30 flex items-center gap-1">
            <div className="w-1.5 h-1.5 rounded-full bg-amber-500/10 dark:bg-amber-500/20" />
            {t('libraryFile.pending')}
          </span>
        </div>

        <div className="max-w-md bg-muted rounded-xl p-5 border border-border mb-8 text-left">
          <p className="text-sm text-muted-foreground leading-relaxed flex gap-3">
            <Info className="w-5 h-5 text-sky-500 flex-shrink-0 mt-0.5" />
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
              className="gap-2 bg-card hover:bg-red-500/10 dark:bg-red-500/20 text-foreground/80 hover:text-red-600 dark:text-red-300 border-border hover:border-red-500/30"
              disabled={!selectedFileId}
            >
              <Trash2 className="w-4 h-4" />
              {t('libraryFile.removeButton')}
            </Button>
          </ConfirmDialog>
        </div>
      </div>
    ) : previewFormat === 'rendered' ? (
      <div className="prose prose-slate dark:prose-invert max-w-none prose-headings:text-foreground prose-p:text-muted-foreground prose-a:text-sky-600 dark:prose-a:text-sky-300">
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
      icon={ShieldCheck}
      iconColor="text-sky-400"
      compactHeader
      description={
        <span className="flex items-center gap-2 text-[13px] text-muted-foreground/80">
          <span className="w-1.5 h-1.5 rounded-full bg-sky-500/10 dark:bg-sky-500/20" aria-hidden="true" />
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
          <div className="w-px h-4 bg-border dark:bg-card/10 mx-1" />
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
      top={InboundBanner}
      pipelineRail={<PipelineRail />}
      mainPanel={
        <div className="flex-1 flex flex-col bg-background text-foreground min-h-0">
          <div className="flex-1 flex overflow-hidden min-h-0 relative bg-background">
        {/* 宸︿晶鏂囦欢鍒楄〃 */}
	        <aside
	          ref={sidebarRef}
	          className={cn(
	            "group/sidebar relative flex flex-col flex-shrink-0 bg-card border-r border-border z-10",
	            isSidebarCollapsed ? "w-0 border-r-0" : ""
	          )}
	          style={{ width: isSidebarCollapsed ? 0 : sidebarWidth }}
	        >
          {/* 鎶樺彔/灞曞紑鎸夐挳 */}
	          <Button
	            variant="ghost"
	            size="icon"
            className={cn(
              "absolute -right-3 top-3 z-30 h-6 w-6 rounded-full border border-border bg-card shadow-sm text-muted-foreground hover:text-muted-foreground hover:bg-muted transition-opacity opacity-0 group-hover/sidebar:opacity-100",
              isSidebarCollapsed && "opacity-100 -right-8 translate-x-2"
            )}
	            onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
	            title={isSidebarCollapsed ? t('sidebar.expand') : t('sidebar.collapse')}
	            aria-label={isSidebarCollapsed ? t('sidebar.expand') : t('sidebar.collapse')}
	          >
            {isSidebarCollapsed ? <PanelRightOpen className="w-3 h-3" /> : <PanelRightClose className="w-3 h-3" />}
          </Button>

          <div className={cn("flex-1 flex flex-col min-h-0 w-full overflow-hidden", isSidebarCollapsed && "invisible")}>
            {/* 鐩綍鍒囨崲 & 鎼滅储 */}
            <div className="p-3 border-b border-border space-y-3">
              <Select value={activeFolderId || ROOT_FOLDER_ID} onValueChange={setActiveFolderId}>
                <SelectTrigger className="h-9 text-xs bg-muted border-border text-foreground/80 focus:bg-card focus-ring transition-colors duration-200 motion-reduce:transition-none">
                  <div className="flex items-center gap-2 truncate">
                    <FolderTree className="w-3.5 h-3.5 text-primary" />
                    <SelectValue placeholder={t('sidebar.folderPlaceholder')} />
                  </div>
                </SelectTrigger>
                <SelectContent className="bg-card border-border text-foreground/80">
                  <SelectItem value={ROOT_FOLDER_ID}>{t('sidebar.rootFolder')}</SelectItem>
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
                  placeholder={t('sidebar.searchPlaceholder')}
                  className="w-full rounded-lg border border-border bg-muted py-1.5 pl-9 pr-3 text-xs text-foreground/80 placeholder:text-muted-foreground focus:bg-card focus:outline-none focus:border-primary/30 focus-ring transition-colors duration-200 motion-reduce:transition-none"
                />
              </div>
            </div>

            {/* 鏂囦欢鐩綍鏍?- 鍙姌鍙犲尯鍩?*/}
            <div className="px-3 pt-2 pb-1 border-b border-border bg-muted/50">
              <div className="max-h-48 overflow-y-auto overscroll-contain no-scrollbar p-1">
                <DocumentFolderTree />
              </div>
            </div>

            <div className="flex items-center justify-between px-4 py-2 mt-2">
              <h3 className="text-xs font-bold text-muted-foreground uppercase  pl-1">
                {t('sidebar.filesTitle', { count: visibleFiles.length })}
              </h3>
            </div>

            <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar px-3 pb-3 space-y-2">
              {visibleFiles.length === 0 ? (
                <div className="text-xs text-muted-foreground text-center py-8">{t('sidebar.emptyDirectory')}</div>
              ) : (
                visibleFiles.map((file) => {
                  const state = governanceStates[file.id]
                  const hasIssue = state?.issues.some((i) => i.type === 'error')
                  const score = state?.qualityScore || 0

	                  return (
                      <div key={file.id} className="group relative">
                        <button
                          type="button"
                          onClick={() => handleSelectFile(file.id)}
                          className={cn(
                            "w-full text-left p-4 rounded-xl border transition-colors transition-shadow duration-200 motion-reduce:transition-none cursor-pointer",
                            selectedFileId === file.id
                              ? "bg-sky-500/10 dark:bg-sky-500/20 border-sky-200 shadow-md ring-1 ring-sky-100"
                              : "bg-card border-border hover:border-sky-200 hover:shadow-sm"
                          )}
                          aria-label={t('a11y.openFile', { filename: file.filename })}
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
                                (() => {
    if (score >= 80) {
        return "bg-emerald-500/10 dark:bg-emerald-500/20 text-emerald-700 border-emerald-500/30";
    }
    else if (score >= 60) {
            return "bg-amber-500/10 dark:bg-amber-500/20 text-amber-700 dark:text-amber-300 border-amber-500/30";
        }
        else {
            return "bg-rose-50 text-rose-700 border-rose-100";
        }
                                })()
                              )}>
                                {t('sidebar.scoreLabel', { score })}
                              </span>
                            ) : (
                              <span className="flex-shrink-0 text-[10px] text-muted-foreground bg-muted px-2 py-0.5 rounded-full border border-border font-medium">{t('sidebar.notScanned')}</span>
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
	                          <div className="flex items-center justify-between h-5 pr-8">
	                            <div className="flex items-center gap-2">
	                              {state?.isModified && (
	                                <span className="text-[9px] text-sky-600 dark:text-sky-300 flex items-center gap-1 bg-sky-500/10 dark:bg-sky-500/20 px-1.5 py-0.5 rounded border border-sky-500/30 font-bold">
                                  <Sparkles className="w-2.5 h-2.5" /> {t('sidebar.cleaned')}
                                </span>
                              )}
                              {hasIssue && (
                                <span className="text-[9px] text-rose-600 flex items-center gap-1 bg-rose-50 px-1.5 py-0.5 rounded border border-rose-100 font-bold">
	                                  <AlertTriangle className="w-2.5 h-2.5" /> {t('sidebar.needsAttention')}
	                                </span>
	                              )}
	                            </div>
	                          </div>
	                        </div>
	                      </div>
                        </button>
                        <button
                          type="button"
                          onClick={() => {
                            setDeleteFileTarget({ id: file.id, filename: file.filename })
                            setDeleteFileOpen(true)
                          }}
                          className="absolute bottom-3 right-3 opacity-0 group-hover:opacity-100 p-1 text-muted-foreground hover:text-rose-600 hover:bg-rose-50 rounded transition-opacity transition-colors duration-150 motion-reduce:transition-none"
                          aria-label={t('a11y.deleteFile', { filename: file.filename })}
                          title={t('dialogs.deleteFile.confirm')}
                        >
                          <Trash2 className="w-3.5 h-3.5" />
                        </button>
                      </div>
	                  )
	                })
              )}
            </div>

            {/* 搴曢儴缁熻鏍?*/}
            <div className="mt-auto border-t border-border bg-muted/50 p-3 space-y-2 backdrop-blur-sm">
              <div className="grid grid-cols-2 gap-2">
                <div className="bg-card p-2 rounded-lg border border-border hover:border-sky-500/30 transition-colors">
                  <div className="text-[10px] text-muted-foreground mb-0.5 uppercase ">{t('stats.storage')}</div>
                  <div className="text-sm font-bold text-foreground/80 flex items-baseline gap-1 font-mono">
                    {stats.completedFiles} <span className="text-muted-foreground font-normal text-xs">/ {stats.totalFiles}</span>
                  </div>
                </div>
                <div className="bg-card p-2 rounded-lg border border-border hover:border-emerald-500/30 transition-colors">
                  <div className="text-[10px] text-muted-foreground mb-0.5 uppercase ">{t('stats.avgScore')}</div>
                  <div className="text-sm font-bold text-foreground/80 font-mono">
                    {stats.avgScore > 0 ? stats.avgScore.toFixed(1) : '-'}
                  </div>
                </div>
              </div>
            </div>
          </div>

          {/* 鎷栨嫿鎵嬫焺 */}
          <button
            type="button"
            className={cn(
              "absolute right-0 top-0 w-1 h-full cursor-col-resize z-20 border-0 bg-transparent p-0 transition-colors opacity-0 hover:opacity-100 hover:bg-primary/10 dark:hover:bg-primary/20 active:bg-primary/30",
              isResizing && "bg-primary opacity-100"
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
                <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 flex items-center bg-card/80 backdrop-blur-md border border-border shadow-sm rounded-full px-2 py-1 gap-1 transition-colors duration-150 motion-reduce:transition-none hover:bg-card hover:border-border">
                  {/* 瑙嗗浘鍒囨崲 */}
                  <div className="flex items-center bg-muted rounded-full p-0.5 border border-border">
                    <button
                      onClick={() => setViewMode('preview')}
                      className={cn(
                        "px-3 py-1 rounded-full text-xs font-medium transition-colors duration-150 motion-reduce:transition-none",
                        viewMode === 'preview' ? "bg-card text-sky-600 dark:text-sky-300 shadow-sm ring-1 ring-black/5" : "text-muted-foreground hover:text-foreground/80 hover:bg-black/5"
                      )}
                    >
                      {t('canvas.viewModes.preview')}
                    </button>
                    <button
                      onClick={() => setViewMode('edit')}
                      className={cn(
                        "px-3 py-1 rounded-full text-xs font-medium transition-colors duration-150 motion-reduce:transition-none",
                        viewMode === 'edit' ? "bg-card text-sky-600 dark:text-sky-300 shadow-sm ring-1 ring-black/5" : "text-muted-foreground hover:text-foreground/80 hover:bg-black/5"
                      )}
                    >
                      {t('canvas.viewModes.edit')}
                    </button>
                    <button
                      onClick={() => setViewMode('original')}
                      className={cn(
                        "px-3 py-1 rounded-full text-xs font-medium transition-colors duration-150 motion-reduce:transition-none",
                        viewMode === 'original' ? "bg-card text-sky-600 dark:text-sky-300 shadow-sm ring-1 ring-black/5" : "text-muted-foreground hover:text-foreground/80 hover:bg-black/5"
                      )}
                    >
                      {t('canvas.viewModes.original')}
                    </button>
                  </div>

                  <div className="w-px h-3 bg-border mx-1" />

	                  <Button
	                    variant="ghost"
	                    size="icon"
	                    className="h-7 w-7 rounded-full text-muted-foreground hover:text-foreground/80 hover:bg-muted"
	                    onClick={() => setPreviewFormat(prev => prev === 'rendered' ? 'markdown' : 'rendered')}
	                    title={previewFormat === 'rendered' ? t('canvas.viewSource') : t('canvas.viewRendered')}
	                    aria-label={previewFormat === 'rendered' ? t('canvas.viewSource') : t('canvas.viewRendered')}
	                  >
	                    {previewFormat === 'rendered' ? <Hash className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
	                  </Button>
                </div>

                {/* 宸︿晶鏀惰捣鎸夐挳 (濡傛灉宸︿晶鏀惰捣) */}
                {isSidebarCollapsed && (
	                  <Button
	                    variant="ghost"
	                    size="icon"
	                    onClick={() => setIsSidebarCollapsed(false)}
	                    className="absolute left-4 top-4 z-20 h-8 w-8 bg-card/80 border border-border shadow-sm rounded-lg text-muted-foreground hover:text-sky-600 dark:text-sky-300 hover:bg-card backdrop-blur-md transition-colors duration-150 motion-reduce:transition-none"
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
	                    className="absolute right-4 top-4 z-20 h-8 w-8 bg-card/80 border border-border shadow-sm rounded-lg text-muted-foreground hover:text-sky-600 dark:text-sky-300 hover:bg-card backdrop-blur-md transition-colors duration-150 motion-reduce:transition-none"
	                    aria-label={t('panel.expand')}
	                    title={t('panel.expand')}
	                  >
	                    <PanelRightClose className="w-4 h-4 rotate-180" />
	                  </Button>
                )}

                {/* 鍐呭鍖哄煙 */}
                <div ref={contentScrollRef} className="flex-1 overflow-y-auto overscroll-contain no-scrollbar p-4 md:p-8">
                  <div className={cn(
                    "mx-auto",
                    viewMode === 'edit' ? 'max-w-full' : 'max-w-4xl'
                  )}>
                    {/* 绾稿紶鏁堟灉瀹瑰櫒 */}
                    <div className={cn(
                      "bg-card min-h-[800px] shadow-sm border border-border/60 rounded-xl overflow-hidden relative",
                      viewMode === 'edit' ? "h-[calc(100vh-140px)] border-0 shadow-none bg-transparent" : "p-10 md:p-14"
                    )}>
                      {/* 娌荤悊鐘舵€佹按鍗?寰界珷 */}
                      {viewMode !== 'edit' && governanceState.isModified && (
                        <div className="absolute top-0 right-0 p-4">
                          <span className="bg-purple-500/10 dark:bg-purple-500/20 text-purple-700 dark:text-purple-300 border border-purple-500/30 text-xs px-2 py-1 rounded-md font-medium shadow-sm">
                            {t('canvas.modified')}
                          </span>
                        </div>
                      )}

	                      {contentBody}
                    </div>
                  </div>
                </div>
              </div>

              {/* 鍙充晶锛氭不鐞嗗伐鍏烽潰鏉?(鏁村悎浜?Tabs) */}
                <div
                  ref={panelRef}
                  className={cn(
                  "group/panel relative flex-shrink-0 border-l border-border bg-card flex flex-col transition-transform duration-200 ease-out motion-reduce:transition-none z-10 shadow-strong",
                  isPanelCollapsed ? "w-0 border-l-0 translate-x-full" : ""
                )}
                  style={{ width: isPanelCollapsed ? 0 : panelWidth }}
                >
                {/* 宸ュ叿闈㈡澘澶撮儴锛氭不鐞嗛樁娈甸€夋嫨 */}
                <div className="flex-shrink-0 p-4 border-b border-border bg-card">
                  <div className="flex items-center justify-between mb-4">
                    <h2 className="text-sm font-bold text-foreground flex items-center gap-2">
                      <Sparkles className="w-4 h-4 text-sky-600 dark:text-sky-300" />
                      {t('panel.title')}
                    </h2>
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

                  {/* 鏂扮殑 Tab 閫夋嫨鍣?*/}
                  <div className="grid grid-cols-4 gap-1 p-1 bg-muted rounded-lg border border-border">
                    {governanceTabs.map((tab) => {
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
                          {/* 鐘舵€佺偣 */}
                          {tab.id === 'clean' && governanceState.isModified && (
                            <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 bg-purple-500/10 dark:bg-purple-500/20 rounded-full ring-1 ring-white shadow-sm" />
                          )}
                        </button>
                      )
                    })}
                  </div>

                  {/* 褰撳墠宸ュ叿鎻忚堪 */}
                  <div className="mt-3 text-xs text-muted-foreground bg-sky-500/10 dark:bg-sky-500/20 p-2 rounded border border-sky-500/30 flex items-start gap-2">
                    <Info className="w-3.5 h-3.5 text-sky-500 mt-0.5 flex-shrink-0" />
                    {governanceTabs.find(tab => tab.id === activeTab)?.desc}
                  </div>
                </div>

                {/* 宸ュ叿鍐呭鍖?*/}
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

                {/* 鎷栨嫿鎵嬫焺 */}
                <button
                  type="button"
                  className={cn(
                    "absolute left-0 top-0 w-1 h-full cursor-col-resize z-20 border-0 bg-transparent p-0 transition-colors opacity-0 hover:opacity-100 hover:bg-primary/10 dark:hover:bg-primary/20 active:bg-primary/30",
                    isPanelResizing && "bg-primary opacity-100"
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
              <h3 className="text-xl font-medium text-foreground mb-2">{t('emptySelection.title')}</h3>
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
            <AlertDialogTitle>{t('dialogs.deleteFile.title')}</AlertDialogTitle>
            <AlertDialogDescription>
              {t('dialogs.deleteFile.description', { filename: deleteFileTarget?.filename || '-' })}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel>{t('dialogs.deleteFile.cancel')}</AlertDialogCancel>
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
