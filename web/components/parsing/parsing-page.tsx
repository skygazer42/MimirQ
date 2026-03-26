'use client'

import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { FileText, Sparkles, FileStack, Settings2 } from 'lucide-react'
import { AppFrame } from '@/components/app-frame'
import { PipelineRail, WorkbenchPanelDialog, WorkbenchScaffold } from '@/components/workbench'
import { Button } from '@/components/ui/button'
import { parsingApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { detachPromise } from '@/lib/utils'
import { ROOT_FOLDER_ID, useParsedFiles, type ParsedFileData } from '@/store/use-parsed-files-store'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { getParserLabel } from '@/lib/parser-options'
import { FileStatus } from '@/components/ui/file-queue-item'
import { extractMarkdownHeadings } from '@/lib/markdown'
import { UPLOAD_ACCEPT, UPLOAD_ACCEPT_WITH_ZIP } from '@/lib/upload-extensions'
import { toast } from 'sonner'
import { getDocContentFromCache, getDocSourceFromCache } from '@/lib/doc-content-cache'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'
import { ParsingActiveFilePane } from '@/components/parsing/parsing-active-file-pane'
import { ParsingLibraryBrowser } from '@/components/parsing/parsing-library-browser'
import { ParsingLibraryPreviewPane } from '@/components/parsing/parsing-library-preview-pane'
import { ParsingLeftPanel } from '@/components/parsing/parsing-left-panel'
import { ParsingMainPanel } from '@/components/parsing/parsing-main-panel'
import { ParsingMobileInspectorContent } from '@/components/parsing/parsing-mobile-inspector-content'
import { ParsingMobileQueueContent } from '@/components/parsing/parsing-mobile-queue-content'
import { ParsingSidebarPane } from '@/components/parsing/parsing-sidebar-pane'
import { useParsingLibraryActions } from '@/components/parsing/use-parsing-library-actions'
import { useParsingRunActions } from '@/components/parsing/use-parsing-run-actions'
import type { ParsedFile } from '@/components/parsing/parsing-types'

// 解析后的文件（扩展版）
function countMarkdownHeadings(markdown: string) {
  const md = String(markdown || '').trim()
  if (!md) return 0
  return (md.match(/^#{1,6}\s+\S+/gm) || []).length
}

function bumpParsingProgress(prev: ParsedFile[], fileId: string): ParsedFile[] {
  return prev.map((f) =>
    f.id === fileId && f.status === 'parsing'
      ? { ...f, progress: Math.min((f.progress || 0) + 5, 90) }
      : f
  )
}

function applyEditedMarkdown(
  prev: ParsedFile[],
  fileId: string,
  targetRunId: string | undefined,
  editedContent: string
): ParsedFile[] {
  return prev.map((f) => {
    if (f.id !== fileId) return f

    const runs =
      targetRunId && f.runs
        ? f.runs.map((run) =>
            run.id === targetRunId
              ? {
                  ...run,
                  cleanedMarkdown: editedContent,
                  rawMarkdown: editedContent,
                  blocks: [],
                }
              : run
          )
        : f.runs

    return {
      ...f,
      markdownContent: editedContent,
      runs,
      stats: f.stats
        ? {
            ...f.stats,
            charCount: editedContent.length,
            lineCount: editedContent.split('\n').length,
            headingCount: countMarkdownHeadings(editedContent),
            blockCount: 0,
          }
        : undefined,
    }
  })
}

export default function ParsingPage() {
  const router = useRouter()

  // 文件状态
  const [files, setFiles] = useState<ParsedFile[]>([])
  const [activeFileId, setActiveFileId] = useState<string | null>(null)
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false)
  const [queueOpen, setQueueOpen] = useState(false)
  const [inspectorOpen, setInspectorOpen] = useState(false)
  const [copied, setCopied] = useState(false)
  const [dragOverFolderId, setDragOverFolderId] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const folderInputRef = useRef<HTMLInputElement>(null)
  const uploadTargetFolderIdRef = useRef<string | null>(null)
  const fileIdSetRef = useRef<Set<string>>(new Set())
  const filesRef = useRef<ParsedFile[]>([])
  const rehydratedFolderIdsRef = useRef<Set<string>>(new Set())
  const didSyncLibraryFromServerRef = useRef(false)
  const parseControllersRef = useRef<Map<string, AbortController>>(new Map())
  const parseProgressIntervalsRef = useRef<Map<string, ReturnType<typeof setInterval>>>(new Map())
  const rebindInputRef = useRef<HTMLInputElement>(null)
  const rebindTargetRef = useRef<{ libraryId: string; autoParse: boolean } | null>(null)
  const [isQueueRehydrating, setIsQueueRehydrating] = useState(false)
  const [autoParseFileId, setAutoParseFileId] = useState<string | null>(null)
  const [activeLibrarySourceStatus, setActiveLibrarySourceStatus] = useState<'unknown' | 'available' | 'missing'>(
    'unknown'
  )

  const cancelParse = useCallback((fileId: string) => {
    const controller = parseControllersRef.current.get(fileId)
    if (controller) {
      controller.abort()
      parseControllersRef.current.delete(fileId)
    }

    const interval = parseProgressIntervalsRef.current.get(fileId)
    if (interval) {
      clearInterval(interval)
      parseProgressIntervalsRef.current.delete(fileId)
    }
  }, [])

  useEffect(() => {
    fileIdSetRef.current = new Set(files.map((f) => f.id))
    filesRef.current = files
  }, [files])

  useEffect(() => {
    const controllers = parseControllersRef.current
    const intervals = parseProgressIntervalsRef.current
    return () => {
      for (const controller of controllers.values()) {
        controller.abort()
      }
      controllers.clear()
      for (const interval of intervals.values()) {
        clearInterval(interval)
      }
      intervals.clear()
    }
  }, [])

  // 预览模式 & 编辑模式
  const [previewMode, setPreviewMode] = useState<'raw' | 'rendered'>('rendered')
  const [isEditing, setIsEditing] = useState(false)
  const [editedContent, setEditedContent] = useState('')
  const [rightPanelMode, setRightPanelMode] = useState<'blocks' | 'markdown'>('blocks')
  const [activeBlockId, setActiveBlockId] = useState<string | null>(null)
  const [hoveredBlockId, setHoveredBlockId] = useState<string | null>(null)

  // 解析器设置
  const { parserBackend, setParserBackend } = useParserBackendPreference()
  const [imageCaptionEnabled, setImageCaptionEnabled] = useState(false)

  useEffect(() => {
    if (globalThis.window === undefined) return
    const stored = globalThis.window.localStorage.getItem('mimirq_parsing_image_caption_enabled')
    if (stored === 'true') setImageCaptionEnabled(true)
  }, [])

  useEffect(() => {
    if (globalThis.window === undefined) return
    globalThis.window.localStorage.setItem(
      'mimirq_parsing_image_caption_enabled',
      imageCaptionEnabled ? 'true' : 'false'
    )
  }, [imageCaptionEnabled])
  const setQueueFileParserBackend = useCallback(
    (params: { fileId: string; filename: string; backend: string }) => {
      const resolved = resolveParserBackendForFilename(params.filename, params.backend)
      const nextBackend = resolved.backend
      const nextLabel = getParserLabel(nextBackend)
      setFiles((prev) =>
        prev.map((f) =>
          f.id === params.fileId ? { ...f, parserBackend: nextBackend, parserLabel: nextLabel } : f
        )
      )
      // Remember the last selection as a default for subsequent uploads/parses.
      setParserBackend(params.backend)
    },
    [setParserBackend]
  )

  // 共享存储
  const addParsedFile = useParsedFiles((state) => state.addParsedFile)
  const upsertParsedFile = useParsedFiles((state) => state.upsertParsedFile)
  const setParsedFiles = useParsedFiles((state) => state.setParsedFiles)
  const libraryFiles = useParsedFiles((state) => state.files)
  const updateParsedFile = useParsedFiles((state) => state.updateParsedFile)
  const removeParsedFile = useParsedFiles((state) => state.removeFile)
  const moveFolder = useParsedFiles((state) => state.moveFolder)
  const activeFolderId = useParsedFiles((state) => state.activeFolderId)
  const folders = useParsedFiles((state) => state.folders)
  const createFolder = useParsedFiles((state) => state.createFolder)
  const setActiveFolderId = useParsedFiles((state) => state.setActiveFolderId)
  const isLibraryLoaded = useParsedFiles((state) => state.isLoaded)

  const mapBackendStatusToLibraryStatus = useCallback((status?: string): FileStatus => {
    const normalized = (status || '').toLowerCase()
    if (normalized === 'processing') return 'parsing'
    if (normalized === 'completed') return 'parsed'
    if (normalized === 'failed' || normalized === 'cancelled') return 'error'
    return 'pending'
  }, [])

  const getLibraryStatusBadge = (status: FileStatus = 'pending') => {
    switch (status) {
      case 'parsed':
        return { label: '已解析', cls: 'bg-emerald-500/10 text-emerald-700 dark:text-emerald-300 border-emerald-500/20' }
      case 'parsing':
        return { label: '解析中', cls: 'bg-sky-500/10 text-sky-700 dark:text-sky-300 border-sky-500/20' }
      case 'error':
        return { label: '失败', cls: 'bg-red-500/10 text-red-700 dark:text-red-300 border-red-500/20' }
      case 'pending':
      default:
        return { label: '待解析', cls: 'bg-amber-500/10 text-amber-700 dark:text-amber-300 border-amber-500/20' }
    }
  }

	  const syncLibraryFromServer = useCallback(async () => {
	    try {
	      const { items } = await parsingApi.listDocuments({ skip: 0, limit: 500 })
	      const current = useParsedFiles.getState().files || []
	      const byId = new Map(current.map((f) => [f.id, f]))

	      const next = items.map((doc) => {
	        const id = String(doc.id || '').trim()
	        const existing = byId.get(id)
	        const meta = (doc.metadata || {}) as Record<string, any>
	        const rawDuration = meta?.parse_duration_sec
	        const durationSec = Number.isFinite(Number(rawDuration)) ? Number(rawDuration) : existing?.durationSec
	        const backendFromServer = String(meta?.parser_backend || meta?.parser_backend_requested || 'auto')
	        const preferredBackend = backendFromServer === 'auto' ? (existing?.parserBackend || backendFromServer) : backendFromServer
	        const resolved = resolveParserBackendForFilename(doc.filename || existing?.filename || 'document', preferredBackend)
	        const backend = resolved.backend
	        const status = mapBackendStatusToLibraryStatus(doc.status)

	        return {
	          id,
	          filename: doc.filename || existing?.filename || 'document',
	          fileType: doc.file_type || existing?.fileType || '',
	          fileSize: Number(doc.file_size || existing?.fileSize || 0),
	          markdownContent: existing?.markdownContent || '',
	          originalMarkdownContent: existing?.originalMarkdownContent || '',
	          parsedAt: String(doc.updated_at || doc.created_at || existing?.parsedAt || new Date().toISOString()),
	          parser: getParserLabel(backend),
	          parserBackend: backend,
	          durationSec,
	          folderId: existing?.folderId || ROOT_FOLDER_ID,
	          status,
	          error: status === 'error' ? String(doc.error_message || existing?.error || '解析失败') : undefined,
	        }
	      })

      setParsedFiles(next)
    } catch (err) {
      console.warn('Failed to sync parsing library from server:', err)
    }
  }, [mapBackendStatusToLibraryStatus, setParsedFiles])

  useEffect(() => {
    if (!isLibraryLoaded) return
    if (didSyncLibraryFromServerRef.current) return
    didSyncLibraryFromServerRef.current = true
    detachPromise(syncLibraryFromServer())
  }, [isLibraryLoaded, syncLibraryFromServer])

  // 获取当前选中的文件
  const activeFile = files.find((f) => f.id === activeFileId) || null
  const [activeLibraryFileId, setActiveLibraryFileId] = useState<string | null>(null)
  const activeLibraryFile = useMemo(() => {
    if (!activeLibraryFileId) return null
    return libraryFiles.find((f) => f.id === activeLibraryFileId) || null
  }, [activeLibraryFileId, libraryFiles])

  // Lazy-load persisted markdown from IndexedDB / backend when a library entry is selected.
  useEffect(() => {
    const id = (activeLibraryFileId || '').trim()
    if (!id) return
    const file = activeLibraryFile
    if (!file) return
    if ((file.markdownContent || '').trim()) return

    let cancelled = false
      ; (async () => {
        try {
          const cached = await getDocContentFromCache(id)
          if (cancelled) return
          const markdown = (cached?.markdownContent || '').trim()
          const original = (cached?.originalMarkdownContent || '').trim()
          if (markdown || original) {
            updateParsedFile(id, {
              markdownContent: markdown || original,
              originalMarkdownContent: original || markdown,
              status: file.status || 'parsed',
            })
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
	          const rawDuration = remote?.parse_duration_sec
	          const durationSec = Number.isFinite(Number(rawDuration)) ? Number(rawDuration) : undefined
	          if (!markdown && !original) return
	          updateParsedFile(id, {
	            markdownContent: markdown || original,
	            originalMarkdownContent: original || markdown,
	            status: file.status || 'parsed',
	            parser: getParserLabel(remote?.parser_backend || 'auto'),
	            parserBackend: String(remote?.parser_backend || 'auto'),
	            durationSec,
	          })
	        } catch {
	          // ignore
	        }
      })()

    return () => {
      cancelled = true
    }
  }, [activeLibraryFileId, activeLibraryFile, updateParsedFile])

  useEffect(() => {
    const id = (activeLibraryFileId || '').trim()
    if (!id) {
      setActiveLibrarySourceStatus('unknown')
      return
    }

    // Source files are persisted on the backend; local cache is optional.
    setActiveLibrarySourceStatus('available')
  }, [activeLibraryFileId])

  const activeRun = useMemo(() => {
    if (!activeFile) return null
    const runs = activeFile.runs || []
    if (!runs.length) return null
    const selected = runs.find((run) => run.id === activeFile.activeRunId)
    return selected || runs[runs.length - 1]
  }, [activeFile])

  const activeMarkdown =
    activeRun?.cleanedMarkdown || activeFile?.markdownContent || activeLibraryFile?.markdownContent || ''
  const activeQualityGate = activeRun?.qualityGate || activeFile?.qualityGate || null
  const activePdfQuality = activeRun?.pdfQuality || activeFile?.pdfQuality || null
  const activeBlocksWithPositions = useMemo(
    () => (activeRun?.blocks || []).filter((block) => (block.positions || []).length > 0),
    [activeRun?.blocks]
  )
  const isPdf = Boolean(activeFile?.file?.name?.toLowerCase().endsWith('.pdf'))

  const tocEnabled = useMemo(
    () => extractMarkdownHeadings(activeMarkdown, { maxDepth: 4 }).length > 0,
    [activeMarkdown]
  )

  const folderPathById = useMemo(() => {
    const byId = new Map(folders.map((f) => [f.id, f]))
    const cache = new Map<string, string>()

    const getPath = (folderId: string): string => {
      if (!folderId || folderId === ROOT_FOLDER_ID) return '根目录'
      const cached = cache.get(folderId)
      if (cached) return cached
      const node = byId.get(folderId)
      if (!node) return '根目录'
      const parentPath = node.parentId && node.parentId !== ROOT_FOLDER_ID ? getPath(node.parentId) : '根目录'
      const path = `${parentPath} / ${node.name}`
      cache.set(folderId, path)
      return path
    }

    const result: Record<string, string> = { [ROOT_FOLDER_ID]: '根目录' }
    for (const f of folders) result[f.id] = getPath(f.id)
    return result
  }, [folders])

  const activeFolderPathLabel = folderPathById[activeFolderId || ROOT_FOLDER_ID] || '根目录'
  const activeLibraryFolderId = activeLibraryFile?.folderId || ROOT_FOLDER_ID
  const activeLibraryFolderPathLabel = folderPathById[activeLibraryFolderId] || '根目录'
  const activeLibraryFolderName = (activeLibraryFolderPathLabel.split('/').pop() || '').trim() || activeLibraryFolderPathLabel
  const activeLibraryStatusBadge = activeLibraryFile?.status ? getLibraryStatusBadge(activeLibraryFile.status) : null

  const {
    addFiles,
    handleRebindFileSelect,
    mountLibraryFileToQueue,
    removeLibraryCaches,
    requestRebindForLibraryFile,
    requestUploadFolder,
    requestUploadToFolder,
    restoreLibraryFileFromCache,
  } = useParsingLibraryActions({
    activeFolderId,
    countMarkdownHeadings,
    createFolder,
    fileInputRef,
    filesRef,
    folderInputRef,
    folders,
    libraryFiles,
    mapBackendStatusToLibraryStatus,
    parserBackend,
    rebindInputRef,
    rebindTargetRef,
    setActiveBlockId,
    setActiveFileId,
    setActiveFolderId,
    setActiveLibraryFileId,
    setActiveLibrarySourceStatus,
    setAutoParseFileId,
    setFiles,
    setHoveredBlockId,
    setRightPanelMode,
    updateParsedFile,
    uploadTargetFolderIdRef,
    upsertParsedFile,
  })

  const currentFolderId = activeFolderId || ROOT_FOLDER_ID

  const visibleQueueFiles = useMemo(() => {
    return files
      .filter((f) => (f.folderId || ROOT_FOLDER_ID) === currentFolderId)
      .sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0))
  }, [files, currentFolderId])

  const visibleLibraryFiles = useMemo(() => {
    return libraryFiles
      .filter((f) => (f.folderId || ROOT_FOLDER_ID) === currentFolderId)
      .sort((a, b) => Date.parse(b.parsedAt) - Date.parse(a.parsedAt))
  }, [libraryFiles, currentFolderId])

  const queueLibraryIdSet = useMemo(() => {
    const ids = new Set<string>()
    for (const f of files) {
      if (f.libraryId) ids.add(f.libraryId)
    }
    return ids
  }, [files])

  const visibleLibraryOnlyFiles = useMemo(() => {
    return visibleLibraryFiles.filter((f) => !queueLibraryIdSet.has(f.id))
  }, [visibleLibraryFiles, queueLibraryIdSet])

  // Auto-rehydrate queue items from IndexedDB when returning to /parsing.
  // This allows resuming pending/error parses after route changes / refresh.
  useEffect(() => {
    if (!isLibraryLoaded) return

    const folderId = currentFolderId
    if (!folderId) return
    if (rehydratedFolderIdsRef.current.has(folderId)) return

    const candidates = visibleLibraryOnlyFiles.filter((f) => {
      const status = (f.status || 'parsed') as FileStatus
      return status === 'pending' || status === 'error' || status === 'parsing'
    })

    rehydratedFolderIdsRef.current.add(folderId)
    if (candidates.length === 0) return

    let cancelled = false
    setIsQueueRehydrating(true)
      ; (async () => {
        let missing = 0

        for (const entry of candidates) {
          if (cancelled) return

          try {
            const cached = await getDocSourceFromCache(entry.id)
            if (!cached) {
              missing += 1
              continue
            }

            const file = new File([cached.blob], cached.filename || entry.filename, {
              type: cached.mimeType || 'application/octet-stream',
              lastModified: cached.lastModified || Date.now(),
            })

            await mountLibraryFileToQueue(entry.id, file, { select: false })
          } catch {
            missing += 1
          }
        }

        if (cancelled) return
        if (missing > 0) toast.warning(`有 ${missing} 个文件未在本地缓存源文件，需要预览时将从服务器下载`)
      })()
        .finally(() => {
          if (!cancelled) setIsQueueRehydrating(false)
        })

    return () => {
      cancelled = true
    }
  }, [currentFolderId, isLibraryLoaded, mountLibraryFileToQueue, visibleLibraryOnlyFiles])

  useEffect(() => {
    if (visibleQueueFiles.length === 0) {
      if (activeFileId) setActiveFileId(null)
      return
    }

    const stillVisible = activeFileId && visibleQueueFiles.some((f) => f.id === activeFileId)
    if (!stillVisible) {
      // Don't override the selection if user is browsing a persisted library entry.
      if (!activeLibraryFileId) setActiveFileId(visibleQueueFiles[0].id)
    }
  }, [visibleQueueFiles, activeFileId, activeLibraryFileId])

  // 拖放处理
  const handleFileSelect = useCallback(async (e: React.ChangeEvent<HTMLInputElement>) => {
    const targetFolderId = uploadTargetFolderIdRef.current
    uploadTargetFolderIdRef.current = null
    const selectedFiles = e.target.files ? Array.from(e.target.files) : []
    if (selectedFiles.length > 0) {
      await addFiles(selectedFiles, targetFolderId || undefined)
    }
    e.target.value = ''
  }, [addFiles])

  // 移除文件
  const removeFile = (fileId: string) => {
    // `fileId` could be a queue id or a persisted library id.
    const queue = files.find((f) => f.id === fileId) || null
    const libId = queue?.libraryId || (libraryFiles.some((f) => f.id === fileId) ? fileId : null)

    if (queue) {
      cancelParse(queue.id)
      setFiles((prev) => prev.filter((f) => f.id !== queue.id))
      if (activeFileId === queue.id) setActiveFileId(null)
    }
    if (libId) {
      detachPromise((async () => {
        try {
          await parsingApi.delete(libId)
        } catch (err: any) {
          toast.error(formatApiError(err, '删除失败'))
        }
      })())
      removeParsedFile(libId)
      removeLibraryCaches(libId)
      if (activeLibraryFileId === libId) setActiveLibraryFileId(null)
    }
  }

  const moveFileToFolder = useCallback((fileId: string, folderId: string) => {
    const targetId = folderId || ROOT_FOLDER_ID
    setFiles((prev) =>
      prev.map((f) => (f.id === fileId ? { ...f, folderId: targetId } : f))
    )

    // Keep the persisted library entry in sync.
    const queueMatch = files.find((f) => f.id === fileId) || null
    const libId = queueMatch?.libraryId || (libraryFiles.some((f) => f.id === fileId) ? fileId : null)
    if (libId) updateParsedFile(libId, { folderId: targetId })
  }, [files, libraryFiles, updateParsedFile])

  const handleFileDragStart = useCallback((e: React.DragEvent, fileId: string) => {
    e.dataTransfer.setData('text/plain', fileId)
    e.dataTransfer.effectAllowed = 'move'
  }, [])

  const handleFolderDragOver = useCallback((e: React.DragEvent, folderId: string) => {
    e.preventDefault()
    setDragOverFolderId(folderId)
  }, [])

  const handleFolderDrop = useCallback((e: React.DragEvent, folderId: string) => {
    e.preventDefault()
    const targetId = folderId || ROOT_FOLDER_ID

    const draggedFolderId = e.dataTransfer.getData('application/x-mimirq-folder')
    if (draggedFolderId) {
      const ok = moveFolder(draggedFolderId, targetId)
      if (ok) toast.success('文件夹已移动')
      else toast.error('移动失败：目标目录不合法（可能是自身/子目录/不存在）')
      setDragOverFolderId(null)
      return
    }

    const fileId = e.dataTransfer.getData('text/plain')
    if (fileId) moveFileToFolder(fileId, targetId)
    setDragOverFolderId(null)
  }, [moveFileToFolder, moveFolder])

  const { handleSelectRun, parseAllPending, parseFile } = useParsingRunActions({
    activeFile,
    autoParseFileId,
    bumpParsingProgress,
    cancelParse,
    countMarkdownHeadings,
    fileIdSetRef,
    filesRef,
    imageCaptionEnabled,
    mapBackendStatusToLibraryStatus,
    parseControllersRef,
    parseProgressIntervalsRef,
    parserBackend,
    setActiveBlockId,
    setAutoParseFileId,
    setFiles,
    setHoveredBlockId,
    setRightPanelMode,
    updateParsedFile,
    upsertParsedFile,
    visibleQueueFiles,
  })

  // 复制 Markdown
  const copyMarkdown = async () => {
    if (!activeMarkdown) return
    await navigator.clipboard.writeText(activeMarkdown)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  // 下载 Markdown
  const downloadMarkdown = () => {
    if (!activeFile || !activeMarkdown) return
    const blob = new Blob([activeMarkdown], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = activeFile.file.name.replace(/\.[^/.]+$/, '') + '.md'
    a.click()
    URL.revokeObjectURL(url)
  }

  // 开始编辑
  const handleStartEdit = () => {
    if (!activeMarkdown) return
    setEditedContent(activeMarkdown)
    setIsEditing(true)
  }

  // 取消编辑
  const handleCancelEdit = () => {
    setIsEditing(false)
    setEditedContent('')
  }

  // 保存编辑
  const handleSaveEdit = async () => {
    if (!activeFile) return
    const targetRunId = activeRun?.id ?? activeFile.activeRunId

	    // 更新文件内容
	    setFiles((prev) => applyEditedMarkdown(prev, activeFile.id, targetRunId, editedContent))

    setRightPanelMode('markdown')
    setActiveBlockId(null)
    setHoveredBlockId(null)

    setIsEditing(false)

    const libId = (activeFile.libraryId || '').trim()
    if (!libId) return

    try {
      const saved = await parsingApi.updateContent(libId, { markdown_content: editedContent })
      updateParsedFile(libId, {
        markdownContent: saved.markdown_content || editedContent,
        originalMarkdownContent: saved.original_markdown_content || editedContent,
        status: 'parsed',
        error: undefined,
        parser: getParserLabel(saved.parser_backend || 'auto'),
      })
      toast.success('已保存到服务器')
    } catch (err: any) {
      toast.error(formatApiError(err, '保存失败'))
    }
  }

  // 提交到数据治理
  const handleSubmitToGovernance = () => {
    if (!activeFile || !activeMarkdown) return

    // 使用当前内容（可能是编辑后的）提交到数据治理
    if (activeFile.libraryId) {
      updateParsedFile(activeFile.libraryId, {
        markdownContent: activeMarkdown,
        originalMarkdownContent: activeMarkdown,
        parser: activeFile.parserLabel,
        status: 'parsed',
        error: undefined,
      })
    } else {
      const libId = addParsedFile({
        filename: activeFile.file.name,
        fileType: activeFile.file.name.split('.').pop()?.toLowerCase() || '',
        fileSize: activeFile.file.size,
        markdownContent: activeMarkdown,
        originalMarkdownContent: activeMarkdown,
        parser: activeFile.parserLabel,
        folderId: activeFile.folderId,
        status: 'parsed',
        error: undefined,
      })
      setFiles((prev) => prev.map((f) => (f.id === activeFile.id ? { ...f, libraryId: libId } : f)))
    }

    router.push('/data-governance')
  }

  const handleDeleteFolder = useCallback((folderIds: string[]) => {
    setFiles((prev) => prev.filter((f) => !f.folderId || !folderIds.includes(f.folderId)))
  }, [])

  // 计算统计数据
  const pendingCount = visibleQueueFiles.filter((f) => f.status === 'pending').length
  const parsingCount = visibleQueueFiles.filter((f) => f.status === 'parsing').length
  const parsedCount = visibleQueueFiles.filter((f) => f.status === 'parsed').length
  const parseableCount = visibleQueueFiles.filter((f) => f.status === 'pending' || f.status === 'error').length
  const queueCountLabel = visibleQueueFiles.length === 0 ? '0' : `${parsedCount}/${visibleQueueFiles.length}`
  const libraryFileListContent = (
    <ParsingLibraryBrowser
      currentFolderId={currentFolderId}
      activeFolderId={activeFolderId || ROOT_FOLDER_ID}
      activeFileId={activeFileId}
      activeLibraryFileId={activeLibraryFileId}
      dragOverFolderId={dragOverFolderId}
      isLibraryLoaded={isLibraryLoaded}
      isQueueRehydrating={isQueueRehydrating}
      folders={folders}
      files={files}
      libraryFiles={libraryFiles}
      visibleQueueFiles={visibleQueueFiles}
      visibleLibraryOnlyFiles={visibleLibraryOnlyFiles}
      folderPathById={folderPathById}
      onFolderSelect={setActiveFolderId}
      onFolderDragOver={handleFolderDragOver}
      onFolderDragLeave={() => setDragOverFolderId(null)}
      onFolderDrop={handleFolderDrop}
      onQueueFileDragStart={handleFileDragStart}
      onSelectQueueFile={(fileId) => {
        setActiveLibraryFileId(null)
        setActiveFileId(fileId)
      }}
      onSelectLibraryFile={(fileId) => {
        setActiveFileId(null)
        setActiveLibraryFileId(fileId)
      }}
      onRemoveFile={removeFile}
      onRetryParse={(fileId) => detachPromise(parseFile(fileId))}
    />
  )

  return (
    <AppFrame>
      <WorkbenchScaffold
        title="文档解析工作台"
        description="上传文件并转换为 Markdown 格式，为数据治理做准备"
        icon={Sparkles}
        iconColor="text-primary"
        size="full"
        bodyClassName="px-0 pb-0"
        pipelineRail={<PipelineRail />}
        actions={
          <div className="flex items-center gap-2">
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="gap-2 lg:hidden"
              onClick={() => setQueueOpen(true)}
            >
              <FileStack className="w-4 h-4" />
              队列
            </Button>
            <Button
              type="button"
              variant="outline"
              size="sm"
              className="gap-2 lg:hidden"
              onClick={() => setInspectorOpen(true)}
            >
              <Settings2 className="w-4 h-4" />
              工具
            </Button>
          </div>
        }
        mainPanel={
          <>
        <ParsingMainPanel>
          <ParsingSidebarPane
            collapsed={isSidebarCollapsed}
            onToggleCollapsed={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
            className="hidden lg:flex"
            activeFolderId={activeFolderId || ROOT_FOLDER_ID}
            activeFolderPathLabel={activeFolderPathLabel}
            currentFolderId={currentFolderId}
            visibleQueueFilesCount={visibleQueueFiles.length}
            pendingCount={pendingCount}
            parsingCount={parsingCount}
            parsedCount={parsedCount}
            parseableCount={parseableCount}
            parserBackend={parserBackend}
            imageCaptionEnabled={imageCaptionEnabled}
            isLibraryLoaded={isLibraryLoaded}
            libraryFileListContent={libraryFileListContent}
            fileAccept={UPLOAD_ACCEPT_WITH_ZIP}
            rebindAccept={UPLOAD_ACCEPT}
            fileInputRef={fileInputRef}
            folderInputRef={folderInputRef}
            rebindInputRef={rebindInputRef}
            onRequestUploadToCurrentFolder={() => requestUploadToFolder(currentFolderId)}
            onRequestUploadToFolder={requestUploadToFolder}
            onRequestUploadFolder={requestUploadFolder}
            onParseAllPending={() => detachPromise(parseAllPending())}
            onParserBackendChange={setParserBackend}
            onImageCaptionEnabledChange={setImageCaptionEnabled}
            onFolderDragOver={handleFolderDragOver}
            onFolderDragLeave={() => setDragOverFolderId(null)}
            onFolderDrop={handleFolderDrop}
            onFolderTreeSelectFile={(fileId) => {
              const queueMatch = files.find((file) => file.libraryId === fileId)
              if (queueMatch) {
                setActiveLibraryFileId(null)
                setActiveFileId(queueMatch.id)
                return
              }
              setActiveFileId(null)
              setActiveLibraryFileId(fileId)
            }}
            onDeleteFolder={handleDeleteFolder}
            onMoveFileToFolder={moveFileToFolder}
            onFileSelect={handleFileSelect}
            onRebindFileSelect={handleRebindFileSelect}
          />

          {/* 右侧：预览区域 */}
          <div className="flex-1 min-w-0 flex flex-col overflow-hidden min-h-0 bg-card ring-1 ring-border/40 shadow-sm dark:bg-background dark:shadow-none">
            {activeFile || activeLibraryFile ? (
              <>
                {!activeFile && activeLibraryFile ? (
                  <ParsingLibraryPreviewPane
                    file={activeLibraryFile}
                    activeMarkdown={activeMarkdown}
                    folderName={activeLibraryFolderName}
                    folderPathLabel={activeLibraryFolderPathLabel}
                    sourceStatus={activeLibrarySourceStatus}
                    defaultParserBackend={parserBackend}
                    statusBadge={activeLibraryStatusBadge}
                    onClose={() => setActiveLibraryFileId(null)}
                    onUpdateParser={(backend) => {
                      const resolved = resolveParserBackendForFilename(activeLibraryFile.filename, backend)
                      updateParsedFile(activeLibraryFile.id, {
                        parserBackend: resolved.backend,
                        parser: getParserLabel(resolved.backend),
                      })
                    }}
                    onRestoreSource={(autoParse) => restoreLibraryFileFromCache(activeLibraryFile.id, autoParse)}
                    onRequestRebind={(autoParse) => requestRebindForLibraryFile(activeLibraryFile.id, autoParse)}
                  />
                ) : null}

                {activeFile ? (
                  <ParsingActiveFilePane
                    activeFile={activeFile}
                    activeRun={activeRun}
                    activeMarkdown={activeMarkdown}
                    activeQualityGate={activeQualityGate}
                    activePdfQuality={activePdfQuality}
                    activeBlocksWithPositions={activeBlocksWithPositions}
                    isPdf={isPdf}
                    tocEnabled={tocEnabled}
                    previewMode={previewMode}
                    rightPanelMode={rightPanelMode}
                    isEditing={isEditing}
                    editedContent={editedContent}
                    copied={copied}
                    activeBlockId={activeBlockId}
                    hoveredBlockId={hoveredBlockId}
                    onSelectRun={handleSelectRun}
                    onPreviewModeChange={setPreviewMode}
                    onRightPanelModeChange={setRightPanelMode}
                    onStartEdit={handleStartEdit}
                    onCancelEdit={handleCancelEdit}
                    onSaveEdit={() => detachPromise(handleSaveEdit())}
                    onCopyMarkdown={() => detachPromise(copyMarkdown())}
                    onDownloadMarkdown={downloadMarkdown}
                    onParseFile={parseFile}
                    onSetQueueFileParserBackend={setQueueFileParserBackend}
                    onSubmitToGovernance={handleSubmitToGovernance}
                    onEditedContentChange={setEditedContent}
                    onActiveBlockIdChange={setActiveBlockId}
                    onHoveredBlockIdChange={setHoveredBlockId}
                  />
                ) : null}
              </>
            ) : (
              <div className="flex flex-1 items-center justify-center">
                <div className="max-w-md text-center">
                  <div className="mx-auto mb-4 flex size-20 items-center justify-center rounded-2xl border border-border/60 bg-card shadow-soft">
                    <FileText className="h-10 w-10 text-muted-foreground dark:text-muted-foreground" />
                  </div>
                  <h3 className="mb-2 text-lg font-medium text-foreground/80 dark:text-muted-foreground">选择文件开始</h3>
                  <p className="text-sm text-muted-foreground dark:text-muted-foreground">
                    从左侧上传或选择文件，系统将使用 AI 智能解析文档结构
                  </p>
                </div>
              </div>
            )}
          </div>
        </ParsingMainPanel>
          </>
        }
      />

      {/* Mobile: expose the left queue panel via a dialog */}
      <WorkbenchPanelDialog open={queueOpen} onOpenChange={setQueueOpen} title="队列">
        <ParsingMobileQueueContent
          queueCountLabel={queueCountLabel}
          parseableCount={parseableCount}
          activeFileId={activeFileId}
          activeLibraryFileId={activeLibraryFileId}
          visibleQueueFiles={visibleQueueFiles}
          visibleLibraryOnlyFiles={visibleLibraryOnlyFiles as ParsedFileData[]}
          folderPathById={folderPathById}
          files={files}
          onParseAllPending={() => detachPromise(parseAllPending())}
          onRequestUploadToFolder={requestUploadToFolder}
          onRequestUploadFolder={requestUploadFolder}
          onSelectQueueFile={(fileId) => {
            setActiveLibraryFileId(null)
            setActiveFileId(fileId)
            setQueueOpen(false)
          }}
          onSelectLibraryFile={(fileId) => {
            setActiveFileId(null)
            setActiveLibraryFileId(fileId)
            setQueueOpen(false)
          }}
          onDeleteFolder={handleDeleteFolder}
          onMoveFileToFolder={moveFileToFolder}
          onRemoveFile={removeFile}
          onRetryParse={(fileId) => detachPromise(parseFile(fileId))}
          onFileDragStart={handleFileDragStart}
        />
      </WorkbenchPanelDialog>

      {/* Mobile: expose inspector/navigation helpers via a dialog */}
      <WorkbenchPanelDialog open={inspectorOpen} onOpenChange={setInspectorOpen} title="工具">
        {activeFile && activeMarkdown ? (
          <ParsingMobileInspectorContent
            activeMarkdown={activeMarkdown}
            rightPanelMode={rightPanelMode}
            previewMode={previewMode}
            activeBlocksWithPositions={activeBlocksWithPositions}
            activeBlockId={activeBlockId}
            onRightPanelModeChange={setRightPanelMode}
            onPreviewModeChange={setPreviewMode}
            onSelectBlock={(blockId) => {
              setActiveBlockId(blockId)
              setInspectorOpen(false)
            }}
            onCopyMarkdown={() => detachPromise(copyMarkdown())}
            onDownloadMarkdown={downloadMarkdown}
          />
        ) : (
          <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain no-scrollbar bg-muted/10 p-4">
            <div className="text-sm text-muted-foreground">
              选择文件后可在此查看定位块、目录和快捷操作。
            </div>
          </div>
        )}
      </WorkbenchPanelDialog>
    </AppFrame>
  )
}
