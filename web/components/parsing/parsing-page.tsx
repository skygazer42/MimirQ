'use client'

import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import { useRouter } from 'next/navigation'
import { FileText, FolderOpen, Loader2, Eye, Code, Download, Copy, Check, Sparkles, FileStack, Clock, Play, Paperclip, FolderUp, Plus, Settings2 } from 'lucide-react'
import { AppFrame } from '@/components/app-frame'
import { PipelineRail, WorkbenchPanelDialog, WorkbenchScaffold } from '@/components/workbench'
import { Button } from '@/components/ui/button'
import { documentApi, parsingApi } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import { cn, detachPromise } from '@/lib/utils'
import { generateRequestId } from '@/lib/request-id'
import { ROOT_FOLDER_ID, useParsedFiles } from '@/store/use-parsed-files-store'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { getParserLabel } from '@/lib/parser-options'
import { FileQueueItem, FileQueueItemData, FileStatus } from '@/components/ui/file-queue-item'
import { ParserDropdown } from '@/components/ui/parser-dropdown'
import { MarkdownToc } from '@/components/markdown/markdown-toc'
import { extractMarkdownHeadings } from '@/lib/markdown'
import { DocumentFolderTree } from '@/components/document-library/folder-tree'
import { extractZipFiles, isZipFile } from '@/lib/zip'
import { extractBlocksFromMarkdown, ParsingBlock } from '@/lib/parsing-positions'
import { UPLOAD_ACCEPT, UPLOAD_ACCEPT_WITH_ZIP, ZIP_ALLOWED_EXTENSIONS } from '@/lib/upload-extensions'
import { toast } from 'sonner'
import { deleteDocContentFromCache, deleteDocSourceFromCache, getDocContentFromCache, getDocSourceFromCache, saveDocSourceToCache } from '@/lib/doc-content-cache'
import { resolveParserBackendForFilename } from '@/lib/parser-compat'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { ParsingActiveFilePane } from '@/components/parsing/parsing-active-file-pane'
import { ParsingLibraryPreviewPane } from '@/components/parsing/parsing-library-preview-pane'
import { Switch } from '@/components/ui/switch'
import { ParsingLeftPanel } from '@/components/parsing/parsing-left-panel'
import { ParsingMainPanel } from '@/components/parsing/parsing-main-panel'
import type { ParsedFile, ParseFailureDiagnostics, ParseRun } from '@/components/parsing/parsing-types'

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

  const requestUploadToFolder = useCallback(
    (folderId: string) => {
      const targetId = folderId || ROOT_FOLDER_ID
      uploadTargetFolderIdRef.current = targetId
      setActiveFolderId(targetId)
      if (fileInputRef.current) {
        fileInputRef.current.value = ''
        fileInputRef.current.click()
      }
    },
    [setActiveFolderId]
  )

  const requestUploadFolder = useCallback(
    (folderId: string) => {
      const targetId = folderId || ROOT_FOLDER_ID
      uploadTargetFolderIdRef.current = targetId
      setActiveFolderId(targetId)
      if (folderInputRef.current) {
        folderInputRef.current.value = ''
        folderInputRef.current.click()
      }
    },
    [setActiveFolderId]
  )

  // 生成唯一 ID
  const generateId = useCallback(() => generateRequestId(), [])

  const requestRebindForLibraryFile = useCallback((libraryId: string, autoParse: boolean) => {
    const id = (libraryId || '').trim()
    if (!id) return
    rebindTargetRef.current = { libraryId: id, autoParse }
    if (rebindInputRef.current) {
      rebindInputRef.current.value = ''
      rebindInputRef.current.click()
    }
  }, [])

  const mountLibraryFileToQueue = useCallback(
    async (
      libraryId: string,
      sourceFile: File,
      options: { autoParse?: boolean; select?: boolean } = {}
    ) => {
      const id = (libraryId || '').trim()
      if (!id) return null
      if (!sourceFile) return null

      const libEntry = libraryFiles.find((f) => f.id === id) || null
      if (!libEntry) {
        toast.error('文档库条目不存在，无法恢复/重新绑定')
        return null
      }

      const preferredBackend = libEntry.parserBackend || parserBackend
      const resolved = resolveParserBackendForFilename(sourceFile.name, preferredBackend)
      const backend = resolved.backend
      const label = getParserLabel(backend)
      const folderId = libEntry.folderId || ROOT_FOLDER_ID
      const parsedAtTs = Date.parse(libEntry.parsedAt || '')
	      const createdAt = Number.isFinite(parsedAtTs) ? parsedAtTs : Date.now()
	      const queueId = generateId()
	      const autoParse = Boolean(options.autoParse)
	      const select = options.select ?? true
	      const restoredDurationSec =
	        !autoParse && Number.isFinite(Number(libEntry.durationSec)) ? Number(libEntry.durationSec) : undefined

      const libStatus = (libEntry.status || 'parsed') as FileStatus

	      let status: FileStatus
      let errorMessage: string | undefined
      let markdownContent: string | null = null
      let runs: ParseRun[] | undefined
      let activeRunId: string | undefined
      let stats: ParsedFile['stats'] | undefined
      let blocks: ParsingBlock[] = []

      if (autoParse) {
        status = 'pending'
        errorMessage = undefined
        updateParsedFile(id, {
          filename: sourceFile.name,
          fileType: sourceFile.name.split('.').pop()?.toLowerCase() || '',
          fileSize: sourceFile.size,
          folderId,
          status: 'pending',
          error: undefined,
          parser: label,
          parserBackend: backend,
        })
      } else if (libStatus === 'parsed') {
        try {
          const cached = await getDocContentFromCache(id)
          const raw = (cached?.originalMarkdownContent || cached?.markdownContent || libEntry.markdownContent || '').trim()
          if (raw) {
            const parsed = extractBlocksFromMarkdown(raw)
            markdownContent = parsed.cleanedMarkdown
            blocks = parsed.blocks.filter((block) => (block.positions || []).length > 0)
            const runId = `restored-${Date.now()}`
            runs = [
              {
                id: runId,
                parserBackend: backend,
                parserLabel: label,
                rawMarkdown: raw,
                cleanedMarkdown: markdownContent,
                blocks,
                createdAt: Date.now(),
              },
            ]
            activeRunId = runId
            stats = {
              charCount: markdownContent.length,
              lineCount: markdownContent.split('\n').length,
              headingCount: countMarkdownHeadings(markdownContent),
              tableCount: (markdownContent.match(/\|.*\|/g) || []).length > 0
                ? (markdownContent.match(/^\|/gm) || []).length / 2
                : 0,
              imageCount: (markdownContent.match(/!\[.*?\]\(.*?\)/g) || []).length,
              blockCount: blocks.length,
            }
          }
        } catch {
          // ignore
        }
        status = markdownContent ? 'parsed' : 'pending'
      } else if (libStatus === 'error') {
        status = 'error'
        errorMessage = (libEntry.error || '').trim() || '解析失败'
      } else if (libStatus === 'parsing') {
        status = 'error'
        errorMessage = '上次解析被中断，请重试'
        updateParsedFile(id, { status: 'error', error: errorMessage })
      } else {
        status = 'pending'
      }

	      const queueItem: ParsedFile = {
	        id: queueId,
	        file: sourceFile,
	        folderId,
	        name: sourceFile.name,
	        size: sourceFile.size,
	        status,
	        duration: restoredDurationSec,
	        markdownContent,
	        error: errorMessage,
	        parserBackend: backend,
	        parserLabel: label,
	        libraryId: id,
        createdAt,
        runs,
        activeRunId,
        stats,
      }

      setFiles((prev) => [...prev.filter((f) => f.libraryId !== id), queueItem])
      if (select) {
        setActiveFileId(queueId)
        setActiveLibraryFileId(null)
        setActiveBlockId(null)
        setHoveredBlockId(null)
        setRightPanelMode(blocks.length ? 'blocks' : 'markdown')
      }

      if (autoParse) setAutoParseFileId(queueId)
      return queueId
    },
    [generateId, libraryFiles, parserBackend, updateParsedFile]
  )

  const handleRebindFileSelect = useCallback(
    async (e: React.ChangeEvent<HTMLInputElement>) => {
      const target = rebindTargetRef.current
      rebindTargetRef.current = null

      const selectedFile = e.target.files?.[0] || null
      e.target.value = ''

      if (!target?.libraryId) return
      if (!selectedFile) return

      try {
        await saveDocSourceToCache({ id: target.libraryId, file: selectedFile })
        setActiveLibrarySourceStatus('available')
      } catch (err) {
        console.warn('Failed to cache source file:', err)
        toast.warning('源文件本地缓存失败：刷新后需要预览时将从服务器重新下载')
      }

      detachPromise(mountLibraryFileToQueue(target.libraryId, selectedFile, { autoParse: target.autoParse }))
    },
    [mountLibraryFileToQueue]
  )

  const restoreLibraryFileFromCache = useCallback(
    async (libraryId: string, autoParse: boolean) => {
      const id = (libraryId || '').trim()
      if (!id) return
      const existing = filesRef.current.find((f) => f.libraryId === id) || null
      if (existing) {
        setActiveFileId(existing.id)
        setActiveLibraryFileId(null)
        if (autoParse) setAutoParseFileId(existing.id)
        return
      }

      try {
        const nameFromLibrary = libraryFiles.find((f) => f.id === id)?.filename || 'document'

        const cached = await getDocSourceFromCache(id).catch(() => null)
        if (cached?.blob) {
          const file = new File([cached.blob], cached.filename || nameFromLibrary, {
            type: cached.mimeType || cached.blob.type || 'application/octet-stream',
            lastModified: cached.lastModified || Date.now(),
          })
          setActiveLibrarySourceStatus('available')
          detachPromise(mountLibraryFileToQueue(id, file, { autoParse }))
          return
        }

        const blob = await documentApi.download(id, { inline: true })
        const file = new File([blob], nameFromLibrary, {
          type: (blob as any)?.type || 'application/octet-stream',
          lastModified: Date.now(),
        })
        setActiveLibrarySourceStatus('available')
        detachPromise(mountLibraryFileToQueue(id, file, { autoParse }))
      } catch (err) {
        console.warn('Failed to restore source file:', err)
        setActiveLibrarySourceStatus('missing')
        toast.error('从服务器下载源文件失败，请稍后重试')
      }
    },
    [libraryFiles, mountLibraryFileToQueue]
  )

  // 添加文件（支持 .zip 批量解压，支持文件夹上传）
  const addFiles = useCallback(
    async (incomingFiles: File[], baseFolderIdOverride?: string) => {
      const baseFolderId = baseFolderIdOverride || activeFolderId || ROOT_FOLDER_ID
      const now = Date.now()

      const folderIdByKey = new Map<string, string>()
      // Pre-populate with existing folders
      for (const f of folders) {
        folderIdByKey.set(`${f.parentId || ROOT_FOLDER_ID}::${f.name}`, f.id)
      }

      const getOrCreateFolder = (parentId: string, name: string) => {
        const trimmed = name.trim()
        if (!trimmed) return parentId
        const key = `${parentId}::${trimmed}`
        const cached = folderIdByKey.get(key)
        if (cached) return cached

        // Check if exists in store but not in local map
        const existing = folders.find((f) => (f.parentId || ROOT_FOLDER_ID) === parentId && f.name === trimmed)
        if (existing) {
          folderIdByKey.set(key, existing.id)
          return existing.id
        }

        const newId = createFolder(trimmed, parentId)
        folderIdByKey.set(key, newId)
        return newId
      }

      const queued: ParsedFile[] = []
      let skipped = 0
      let added = 0

      for (const file of incomingFiles) {
        // Check for webkitRelativePath (Folder upload)
        const relativePath = (file as any).webkitRelativePath as string
        if (relativePath) {
          const parts = relativePath.split('/')
          const filename = parts.pop() // Remove filename
          // parts now contains the folder path relative to the upload root
          // For folder upload, the first part is the folder name itself.
          // E.g. "MyDocs/sub/file.txt".

          if (!filename) continue
          const ext = filename.split('.').pop()?.toLowerCase() || ''
          if (!ZIP_ALLOWED_EXTENSIONS.has(ext)) {
            skipped += 1
            continue
          }

          let currentFolderId = baseFolderId
          // Create folders recursively
          for (const segment of parts) {
            currentFolderId = getOrCreateFolder(currentFolderId, segment)
          }

          queued.push({
            id: generateId(),
            file,
            folderId: currentFolderId,
            name: filename,
            sourcePath: relativePath,
            size: file.size,
            status: 'pending' as FileStatus,
            markdownContent: null,
            error: undefined,
            parserBackend: resolveParserBackendForFilename(filename, parserBackend).backend,
            parserLabel: getParserLabel(resolveParserBackendForFilename(filename, parserBackend).backend),
            createdAt: now,
          })
          added += 1
          continue
        }

        // Regular file or ZIP
        if (isZipFile(file)) {
          let extractedCount = 0
          let addedInZip = 0
          let skippedInZip = 0
          try {
            const extracted = await extractZipFiles(file)
            extractedCount = extracted.length
            for (const item of extracted) {
              const path = item.path
              const parts = path.split('/').filter(Boolean)
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

              queued.push({
                id: generateId(),
                file: item.file,
                folderId,
                name: item.file.name,
                sourcePath: path,
                size: item.file.size,
                status: 'pending' as FileStatus,
                markdownContent: null,
                error: undefined,
                parserBackend: resolveParserBackendForFilename(filename, parserBackend).backend,
                parserLabel: getParserLabel(resolveParserBackendForFilename(filename, parserBackend).backend),
                createdAt: now,
              })
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

        const resolvedParser = resolveParserBackendForFilename(file.name, parserBackend)
        queued.push({
          id: generateId(),
          file,
          folderId: baseFolderId,
          name: file.name,
          size: file.size,
          status: 'pending' as FileStatus,
          markdownContent: null,
          error: undefined,
          parserBackend: resolvedParser.backend,
          parserLabel: getParserLabel(resolvedParser.backend),
          createdAt: now,
        })
        added += 1
      }

      if (queued.length === 0) {
        if (skipped > 0) toast.warning(`已跳过 ${skipped} 个不支持的文件`)
        return
      }

      // Enterprise persistence: upload sources to backend immediately so restarts keep the library.
      const queuedWithLibrary: ParsedFile[] = []
      let uploadFailed = 0

      for (const q of queued) {
        try {
          const doc = await parsingApi.upload(q.file, { parser_backend: q.parserBackend })
          const libId = String(doc.id || '').trim()
          if (!libId) throw new Error('Missing document id from backend')

          const requestedBackend = String((doc.metadata as any)?.parser_backend_requested || q.parserBackend || 'auto')

          upsertParsedFile({
            id: libId,
            filename: doc.filename || q.name,
            fileType: doc.file_type || q.name.split('.').pop()?.toLowerCase() || '',
            fileSize: Number(doc.file_size || q.size),
            markdownContent: '',
            originalMarkdownContent: '',
            parsedAt: String(doc.updated_at || doc.created_at || new Date().toISOString()),
            parser: getParserLabel(requestedBackend),
            parserBackend: requestedBackend,
            folderId: q.folderId,
            status: mapBackendStatusToLibraryStatus(doc.status),
            error: doc.error_message || undefined,
          })

          queuedWithLibrary.push({ ...q, libraryId: libId })
        } catch (err: any) {
          uploadFailed += 1
          queuedWithLibrary.push({
            ...q,
            status: 'error' as FileStatus,
            error: formatApiError(err, '上传失败'),
          })
        }
      }

      setFiles((prev) => [...prev, ...queuedWithLibrary])
      setActiveFileId((prev) => prev ?? queuedWithLibrary[0].id)

      if (added > 0) toast.success(`已加入队列：${added} 个文件`)
      if (uploadFailed > 0) toast.warning(`有 ${uploadFailed} 个文件上传失败（可稍后重试）`)
      if (skipped > 0) toast.warning(`已跳过 ${skipped} 个不支持的文件`)
    },
    [parserBackend, activeFolderId, folders, createFolder, generateId, mapBackendStatusToLibraryStatus, upsertParsedFile]
  )

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

  const childrenByParentId = useMemo(() => {
    const map = new Map<string, string[]>()
    for (const folder of folders) {
      const parentId = folder.parentId || ROOT_FOLDER_ID
      const list = map.get(parentId) || []
      list.push(folder.id)
      map.set(parentId, list)
    }
    return map
  }, [folders])

  const directFolders = useMemo(() => {
    return folders
      .filter((f) => (f.parentId || ROOT_FOLDER_ID) === currentFolderId)
      .sort((a, b) => Date.parse(b.createdAt) - Date.parse(a.createdAt))
  }, [folders, currentFolderId])

  const isLibraryEmpty =
    isLibraryLoaded &&
    directFolders.length === 0 &&
    visibleQueueFiles.length === 0 &&
    visibleLibraryOnlyFiles.length === 0

  const libraryFileListContent = isLibraryEmpty ? (
    <div className="h-full flex flex-col items-center justify-center text-muted-foreground">
      <div className="size-14 rounded-2xl border border-border/60 bg-card flex items-center justify-center mb-3 shadow-sm">
        <FolderOpen className="w-6 h-6 text-muted-foreground" />
      </div>
      <p className="text-sm font-medium text-muted-foreground dark:text-muted-foreground">暂无文件</p>
      <p className="text-xs text-muted-foreground dark:text-muted-foreground mt-1">
        拖拽文件到此处或点击上方按钮添加
      </p>
      {isQueueRehydrating ? (
        <p className="text-[11px] text-muted-foreground dark:text-muted-foreground mt-3">
          正在恢复队列…
        </p>
      ) : null}
    </div>
  ) : (
    <div className="space-y-1">
      {directFolders.map((folder) => {
        const stats = folderStatsById.get(folder.id)
        const latestTs = stats?.latestTs || Date.parse(folder.createdAt)
        return (
          <button
            key={folder.id}
            type="button"
            className={cn(
              "flex w-full items-center gap-3 p-2.5 rounded-xl border border-transparent hover:bg-muted dark:hover:bg-muted/40 group transition-colors cursor-pointer relative text-left",
              dragOverFolderId === folder.id &&
                "bg-muted dark:bg-muted/40 ring-1 ring-slate-200 dark:ring-slate-800",
              activeFolderId === folder.id &&
                "bg-muted dark:bg-muted/40 ring-1 ring-slate-200 dark:ring-slate-800"
            )}
            draggable
            onDragStart={(e) => {
              try {
                e.dataTransfer.setData('application/x-mimirq-folder', folder.id)
              } catch {
                // ignore
              }
              e.dataTransfer.effectAllowed = 'move'
            }}
            onClick={() => setActiveFolderId(folder.id)}
            onDragOver={(e) => handleFolderDragOver(e, folder.id)}
            onDragLeave={() => setDragOverFolderId(null)}
            onDrop={(e) => handleFolderDrop(e, folder.id)}
          >
            <div className="w-9 h-9 rounded-xl bg-muted dark:bg-muted text-muted-foreground dark:text-muted-foreground flex items-center justify-center flex-shrink-0">
              <FolderOpen className="w-4 h-4" />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-center justify-between">
                <div
                  className={cn(
                    "text-sm font-semibold truncate pr-6",
                    activeFolderId === folder.id
                      ? "text-foreground dark:text-foreground"
                      : "text-foreground/80 dark:text-muted-foreground"
                  )}
                >
                  {folder.name}
                </div>
                <span className="text-[10px] text-muted-foreground dark:text-muted-foreground flex-shrink-0">
                  {Number.isFinite(latestTs) && latestTs > 0
                    ? new Date(latestTs).toLocaleString([], {
                        month: '2-digit',
                        day: '2-digit',
                        hour: '2-digit',
                        minute: '2-digit',
                      })
                    : ''}
                </span>
              </div>
              <div className="flex items-center gap-2 mt-1 min-h-[16px]">
                <span className="text-[10px] text-muted-foreground dark:text-muted-foreground">
                  {stats?.count || 0} 项
                </span>
              </div>
            </div>
          </button>
        )
      })}

      {visibleLibraryOnlyFiles.map((f) => (
        <FileQueueItem
          key={f.id}
          file={{
            id: f.id,
            name: f.filename,
            size: f.fileSize,
            status: f.status || 'parsed',
            parser: f.parser,
            duration: f.durationSec,
            folderPathLabel:
              f.folderId && f.folderId !== ROOT_FOLDER_ID ? folderPathById[f.folderId] : undefined,
          }}
          isActive={activeLibraryFileId === f.id}
          onClick={() => {
            setActiveFileId(null)
            setActiveLibraryFileId(f.id)
          }}
          onRemove={() => removeFile(f.id)}
        />
      ))}

      {visibleQueueFiles.map((f) => (
        <FileQueueItem
          key={f.id}
          file={{
            id: f.id,
            name: f.name,
            size: f.size,
            status: f.status,
            progress: f.progress,
            parser: f.parserLabel,
            folderPathLabel:
              f.folderId && f.folderId !== ROOT_FOLDER_ID ? folderPathById[f.folderId] : undefined,
            sourcePath: f.sourcePath,
            error: f.error,
            duration: f.duration,
            pageCount: f.stats?.pageCount,
          }}
          draggable
          onDragStart={(e) => handleFileDragStart(e, f.id)}
          isActive={activeFileId === f.id}
          onClick={() => setActiveFileId(f.id)}
          onRemove={() => removeFile(f.id)}
          onRetry={f.status === 'error' ? () => parseFile(f.id) : undefined}
        />
      ))}
    </div>
  )

  const folderStatsById = useMemo(() => {
    const byFolder = new Map<string, { count: number; latestTs: number }>()
    const bump = (folderId: string, ts: number) => {
      const cur = byFolder.get(folderId) || { count: 0, latestTs: 0 }
      byFolder.set(folderId, { count: cur.count + 1, latestTs: Math.max(cur.latestTs, ts) })
    }

    // Library entries (persisted across routes)
    for (const f of libraryFiles) {
      bump(f.folderId || ROOT_FOLDER_ID, Math.max(0, Date.parse(f.parsedAt)))
    }
    // Current session queue entries (may include File object + status/progress)
    for (const f of files) {
      bump(f.folderId || ROOT_FOLDER_ID, f.createdAt || 0)
    }

    const stats = new Map<string, { count: number; latestTs: number }>()
    const collect = (folderId: string): { count: number; latestTs: number } => {
      if (stats.has(folderId)) return stats.get(folderId) as { count: number; latestTs: number }
      let count = 0
      let latestTs = 0
      const direct = byFolder.get(folderId)
      if (direct) {
        count += direct.count
        latestTs = Math.max(latestTs, direct.latestTs)
      }
      const children = childrenByParentId.get(folderId) || []
      for (const childId of children) {
        const child = collect(childId)
        count += child.count
        latestTs = Math.max(latestTs, child.latestTs)
      }
      const result = { count, latestTs }
      stats.set(folderId, result)
      return result
    }

    for (const folder of folders) {
      collect(folder.id)
    }
    return stats
  }, [files, folders, childrenByParentId, libraryFiles])

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
      detachPromise(deleteDocContentFromCache(libId))
      detachPromise(deleteDocSourceFromCache(libId))
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

  // 解析文件（支持删除中断）
  const parseFile = useCallback(async (fileId: string, backendOverride?: string) => {
    const file = filesRef.current.find((f) => f.id === fileId) || null
    if (!file) return

    cancelParse(fileId)
    const controller = new AbortController()
    parseControllersRef.current.set(fileId, controller)

    const resolvedRequested = resolveParserBackendForFilename(
      file.file.name,
      backendOverride || file.parserBackend || parserBackend
    )
    const requestedBackend = resolvedRequested.backend
    const requestedLabel = getParserLabel(requestedBackend)

    const startTime = Date.now()

    setFiles((prev) =>
      prev.map((f) =>
        f.id === fileId
          ? {
              ...f,
              status: 'parsing' as FileStatus,
              error: undefined,
              progress: 0,
              parseStartTime: startTime,
              parserBackend: requestedBackend,
              parserLabel: requestedLabel,
              parseDiagnostics: undefined,
            }
          : f
      )
    )
    if (file.libraryId) {
      updateParsedFile(file.libraryId, {
        status: 'parsing',
        error: undefined,
        parser: requestedLabel,
        parserBackend: requestedBackend,
      })
    }

	    const progressInterval = setInterval(() => {
	      setFiles((prev) => bumpParsingProgress(prev, fileId))
	    }, 300)
	    parseProgressIntervalsRef.current.set(fileId, progressInterval)

    const clearProgressInterval = () => {
      clearInterval(progressInterval)
      if (parseProgressIntervalsRef.current.get(fileId) === progressInterval) {
        parseProgressIntervalsRef.current.delete(fileId)
      }
    }

    let libraryId = (file.libraryId || '').trim()

    try {
      if (!libraryId) {
        const created = await parsingApi.upload(file.file, { parser_backend: requestedBackend })
        libraryId = String(created.id || '').trim()
        if (!libraryId) throw new Error('Missing document id from backend')

        upsertParsedFile({
          id: libraryId,
          filename: created.filename || file.file.name,
          fileType: created.file_type || file.file.name.split('.').pop()?.toLowerCase() || '',
          fileSize: Number(created.file_size || file.file.size),
          markdownContent: '',
          originalMarkdownContent: '',
          parsedAt: String(created.updated_at || created.created_at || new Date().toISOString()),
          parser: requestedLabel,
          parserBackend: requestedBackend,
          folderId: file.folderId,
          status: mapBackendStatusToLibraryStatus(created.status),
          error: created.error_message || undefined,
        })

        setFiles((prev) => prev.map((f) => (f.id === fileId ? { ...f, libraryId } : f)))
      }

      if (controller.signal.aborted) return
      if (parseControllersRef.current.get(fileId) !== controller) return
      if (!fileIdSetRef.current.has(fileId)) return

      updateParsedFile(libraryId, {
        status: 'parsing',
        error: undefined,
        parser: requestedLabel,
        parserBackend: requestedBackend,
        folderId: file.folderId,
      })

      const data = await parsingApi.parse(libraryId, {
        parser_backend: requestedBackend,
        image_caption_enabled: imageCaptionEnabled,
        signal: controller.signal,
      })
      if (controller.signal.aborted) return
      if (parseControllersRef.current.get(fileId) !== controller) return
      if (!fileIdSetRef.current.has(fileId)) return

      clearProgressInterval()

      const rawMarkdown = (data.original_markdown_content || data.markdown_content || '').toString()
      const resolvedBackend = data.parser_backend || requestedBackend
      const resolvedLabel = getParserLabel(resolvedBackend)
	      const fallbackDurationSec = Number.parseFloat(((Date.now() - startTime) / 1000).toFixed(1))
	      const parsed = extractBlocksFromMarkdown(rawMarkdown)
	      const markdownContent = (data.markdown_content || parsed.cleanedMarkdown).toString()
	      const blocks = parsed.blocks.filter((block) => (block.positions || []).length > 0)
      const durationSec = Number.isFinite(Number(data.parse_duration_sec))
        ? Number(data.parse_duration_sec)
        : fallbackDurationSec
      const runId = `${resolvedBackend}-${Date.now()}`
      const run = {
        id: runId,
        parserBackend: resolvedBackend,
        parserLabel: resolvedLabel,
        rawMarkdown,
        cleanedMarkdown: markdownContent,
        blocks,
        createdAt: Date.now(),
        pdfQuality: (data as any).pdf_quality ?? null,
        qualityGate: (data as any).quality_gate ?? null,
      }

      const apiStats = data.stats
      const stats = {
        charCount: markdownContent.length,
        lineCount: markdownContent.split('\n').length,
        headingCount: countMarkdownHeadings(markdownContent),
        pageCount: typeof apiStats?.page_count === 'number' ? apiStats.page_count : undefined,
        tableCount:
          (() => {
    if (typeof apiStats?.table_count === 'number') {
        return apiStats.table_count;
    }
    else if ((markdownContent.match(/\|.*\|/g) || []).length > 0) {
            return (markdownContent.match(/^\|/gm) || []).length / 2;
        }
        else {
            return 0;
        }
})(),
        imageCount:
          typeof apiStats?.image_count === 'number'
            ? apiStats.image_count
            : (markdownContent.match(/!\[.*?\]\(.*?\)/g) || []).length,
        blockCount: typeof apiStats?.block_count === 'number' ? apiStats.block_count : blocks.length,
      }

	      setFiles((prev) =>
	        prev.map((f) =>
	          f.id === fileId
	            ? {
	              ...f,
	              status: 'parsed' as FileStatus,
	              markdownContent,
	              parserBackend: resolvedBackend,
	              parserLabel: resolvedLabel,
	              parser: resolvedLabel,
	              progress: 100,
	              duration: durationSec,
	              stats,
                pdfQuality: (data as any).pdf_quality ?? null,
                qualityGate: (data as any).quality_gate ?? null,
	              runs: [...(f.runs || []), run],
	              activeRunId: runId,
	            }
            : f
        )
      )

      setActiveBlockId(null)
      setHoveredBlockId(null)
      setRightPanelMode(blocks.length ? 'blocks' : 'markdown')

      // Sync persisted library entry (backend + local store cache).
	      updateParsedFile(libraryId, {
	        filename: file.file.name,
	        fileType: file.file.name.split('.').pop()?.toLowerCase() || '',
	        fileSize: file.file.size,
	        markdownContent,
	        originalMarkdownContent: rawMarkdown,
	        parser: resolvedLabel,
	        parserBackend: resolvedBackend,
	        durationSec,
	        folderId: file.folderId,
	        parsedAt: new Date().toISOString(),
	        status: 'parsed',
	        error: undefined,
	      })
    } catch (err: any) {
      if (controller.signal.aborted) return
      if (parseControllersRef.current.get(fileId) !== controller) return
      if (!fileIdSetRef.current.has(fileId)) return
      const errorMessage = formatApiError(err, '文档解析失败')
      const detail = err?.response?.data?.detail
      const diagnostics: ParseFailureDiagnostics | undefined =
        detail && typeof detail === 'object' && !Array.isArray(detail)
          ? ((detail).diagnostics as ParseFailureDiagnostics | undefined)
          : undefined
      setFiles((prev) =>
        prev.map((f) =>
          f.id === fileId
            ? {
              ...f,
              status: 'error' as FileStatus,
              error: errorMessage,
              progress: 0,
              parseDiagnostics: diagnostics,
            }
            : f
        )
      )
      if (libraryId) {
        updateParsedFile(libraryId, { status: 'error', error: errorMessage, parserBackend: requestedBackend })
      }
    } finally {
      if (parseControllersRef.current.get(fileId) === controller) {
        parseControllersRef.current.delete(fileId)
      }
      clearProgressInterval()
    }
  }, [cancelParse, imageCaptionEnabled, mapBackendStatusToLibraryStatus, parserBackend, updateParsedFile, upsertParsedFile])

  useEffect(() => {
    if (!autoParseFileId) return
    const id = autoParseFileId
    setAutoParseFileId(null)
    detachPromise(parseFile(id))
  }, [autoParseFileId, parseFile])

  const parseAllPending = async () => {
    const targets = visibleQueueFiles.filter((f) => f.status === 'pending' || f.status === 'error')
    for (const file of targets) {
      await parseFile(file.id)
    }
  }

	  const handleSelectRun = (runId: string) => {
	    if (!activeFile) return
	    const nextRun = activeFile.runs?.find((run) => run.id === runId)
	    if (!nextRun) return

	    setFiles((prev) =>
      prev.map((f) =>
        f.id === activeFile.id
          ? {
            ...f,
            activeRunId: runId,
            markdownContent: nextRun.cleanedMarkdown,
            parserBackend: nextRun.parserBackend,
            parserLabel: nextRun.parserLabel,
          }
          : f
      )
    )

    setActiveBlockId(null)
    setHoveredBlockId(null)
    setRightPanelMode(nextRun.blocks.length ? 'blocks' : 'markdown')
  }

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
          {/* 左侧：文件列表面板 */}
          <ParsingLeftPanel
            collapsed={isSidebarCollapsed}
            onToggleCollapsed={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
            className="hidden lg:flex"
          >
            {/* Folder Navigation */}
                <div className="flex-none h-1/3 min-h-[200px] overflow-y-auto overscroll-contain no-scrollbar p-2 border-b border-border/60 bg-card dark:bg-background/40">
                  <div className="h-full rounded-2xl border border-border/60 bg-card dark:bg-background/40 p-2">
                    <DocumentFolderTree
                      onRequestUpload={requestUploadToFolder}
                      onRequestUploadFolder={requestUploadFolder}
                      showFiles="expanded"
                      onSelectFile={(fileId) => {
                        // `DocumentFolderTree` emits library ids by default.
                        // If we still have the File object in the current session, map back to queue id for PDF preview.
                        const queueMatch = files.find((f) => f.libraryId === fileId)
                        if (queueMatch) {
                          setActiveLibraryFileId(null)
                          setActiveFileId(queueMatch.id)
                          return
                        }
                        setActiveFileId(null)
                        setActiveLibraryFileId(fileId)
                      }}
                      onDeleteFolder={handleDeleteFolder}
                      onFileDrop={moveFileToFolder}
                    />
                  </div>
                </div>

                {/* File List Header & Toolbar */}
                <div
                  className={cn(
                    "px-4 py-3 border-b border-border/60 flex items-center justify-between z-10 sticky top-0",
                    "bg-card dark:bg-background/40"
                  )}
                >
                  <button
                    type="button"
                    className="flex items-center gap-3 min-w-0 group rounded-xl px-2 py-1 -mx-2 text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-primary/40"
                    onClick={() => requestUploadToFolder(currentFolderId)}
                    onDragOver={(e) => handleFolderDragOver(e, currentFolderId)}
                    onDragLeave={() => setDragOverFolderId(null)}
                    onDrop={(e) => handleFolderDrop(e, currentFolderId)}
                    title="拖拽文件到当前目录，或点击上传"
                  >
                    <div className="w-8 h-8 rounded-xl bg-muted dark:bg-muted text-muted-foreground dark:text-muted-foreground flex items-center justify-center">
                      <FileText className="w-4 h-4" />
                    </div>
                    <div className="min-w-0">
                      <div className="text-sm font-semibold text-foreground dark:text-foreground">文档列表</div>
                      <div className="mt-0.5">
                        <span
                          className="inline-flex max-w-[220px] items-center truncate rounded-full bg-muted dark:bg-muted px-2 py-0.5 text-[10px] font-medium text-muted-foreground dark:text-muted-foreground"
                          title={activeFolderPathLabel}
                        >
                          {activeFolderPathLabel}
                        </span>
                      </div>
                    </div>
                    <span className="bg-muted dark:bg-muted text-muted-foreground dark:text-muted-foreground px-2 py-0.5 rounded-full text-[11px] font-medium opacity-0 group-hover:opacity-100 transition-opacity">
                      {visibleQueueFiles.length}
                    </span>
                  </button>

                  <div className="flex items-center gap-1">
                    {parseableCount > 0 && (
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={parseAllPending}
                        className="h-7 text-xs gap-1.5 text-muted-foreground dark:text-muted-foreground hover:text-foreground dark:hover:text-foreground hover:bg-muted dark:hover:bg-muted mr-1 font-medium"
                      >
                        <Play className="w-3.5 h-3.5" />
                        解析
                      </Button>
                    )}

                    <Popover>
                      <PopoverTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-muted-foreground dark:text-muted-foreground hover:bg-muted dark:hover:bg-muted rounded-lg"
                          title="默认解析方式"
                          aria-label="默认解析方式"
                        >
                          <Settings2 className="w-4 h-4" />
                        </Button>
                      </PopoverTrigger>
                      <PopoverContent align="end" className="w-80 p-3">
                        <div className="space-y-3">
                          <div className="space-y-2">
                            <div className="flex items-center justify-between">
                              <div className="text-sm font-semibold">默认解析方式</div>
                              <div className="text-xs text-muted-foreground">新上传默认</div>
                            </div>
                            <ParserDropdown value={parserBackend} onChange={setParserBackend} />
                            <p className="text-xs text-muted-foreground leading-snug">
                              选中文件后，也可以在右侧顶部对单个文件单独修改。
                            </p>
                          </div>

                          <div className="h-px bg-border/60" />

                          <div className="flex items-start justify-between gap-3">
                            <div className="min-w-0">
                              <div className="text-sm font-semibold">图片 caption（可选）</div>
                              <div className="mt-1 text-xs text-muted-foreground leading-snug">
                                为图片引用行插入可检索文本（不做 OCR；默认关闭）
                              </div>
                            </div>
                            <Switch checked={imageCaptionEnabled} onCheckedChange={setImageCaptionEnabled} />
                          </div>
                        </div>
                      </PopoverContent>
                    </Popover>

                    <DropdownMenu>
                      <DropdownMenuTrigger asChild>
                        <Button
                          variant="ghost"
                          size="icon"
                          className="h-7 w-7 text-muted-foreground dark:text-muted-foreground hover:bg-muted dark:hover:bg-muted rounded-lg"
                          aria-label="上传操作"
                          title="上传操作"
                        >
                          <Plus className="w-4 h-4" />
                        </Button>
                      </DropdownMenuTrigger>
                      <DropdownMenuContent align="end" className="w-52">
                        <DropdownMenuItem onClick={() => requestUploadToFolder(activeFolderId || ROOT_FOLDER_ID)}>
                          <Paperclip className="w-4 h-4 mr-2 text-muted-foreground" />
                          上传文件
                        </DropdownMenuItem>
                        <DropdownMenuItem onClick={() => requestUploadFolder(activeFolderId || ROOT_FOLDER_ID)}>
                          <FolderUp className="w-4 h-4 mr-2 text-muted-foreground" />
                          上传文件夹
                        </DropdownMenuItem>
                      </DropdownMenuContent>
                    </DropdownMenu>
                  </div>
                </div>

                {/* File List */}
                <div className="flex-1 overflow-y-auto overscroll-contain no-scrollbar p-2 bg-card dark:bg-background/40">
                  <div className="min-h-full rounded-2xl border border-border/60 bg-card dark:bg-background/40 p-2">
                    {isLibraryLoaded ? libraryFileListContent : (
                      <div className="h-full flex flex-col items-center justify-center text-muted-foreground">
                        <div className="size-14 rounded-2xl border border-border/60 bg-card flex items-center justify-center mb-3 shadow-sm">
                          <Loader2 className="w-6 h-6 text-muted-foreground animate-spin motion-reduce:animate-none" />
                        </div>
                        <p className="text-sm font-medium text-muted-foreground dark:text-muted-foreground">
                          正在加载文档库…
                        </p>
                        <p className="text-xs text-muted-foreground dark:text-muted-foreground mt-1">
                          首次进入或刷新时会稍等片刻
                        </p>
                      </div>
                    )}
                  </div>
                </div>

                {/* 隐藏的文件上传 Input */}
                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept={UPLOAD_ACCEPT_WITH_ZIP}
                  className="hidden"
                  onChange={handleFileSelect}
                />
                <input
                  ref={folderInputRef}
                  type="file"
                  multiple
                  {...({ webkitdirectory: "" } as any)}
                  className="hidden"
                  onChange={handleFileSelect}
                />
                <input
                  ref={rebindInputRef}
                  type="file"
                  accept={UPLOAD_ACCEPT}
                  className="hidden"
                  onChange={handleRebindFileSelect}
                />

                {/* 底部统计 */}
                {visibleQueueFiles.length > 0 && (
                  <div className="p-4 border-t border-border/60 bg-muted/20 dark:bg-muted/40">
                    <div className="flex items-center justify-around text-xs text-muted-foreground dark:text-muted-foreground">
                      <span className="flex items-center gap-1">
                        <Clock className="w-3 h-3" />
                        {pendingCount} 等待
                      </span>
                      <span className="flex items-center gap-1">
                        <Loader2 className="w-3 h-3" />
                        {parsingCount} 处理
                      </span>
                      <span className="flex items-center gap-1 text-green-700 dark:text-green-400">
                        <Check className="w-3 h-3" />
                        {parsedCount} 完成
                      </span>
                    </div>
                  </div>
                )}
          </ParsingLeftPanel>

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
        <div className="flex-none p-3 border-b border-border/60 bg-card/70">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <div className="text-sm font-semibold text-foreground">文件队列</div>
              <div className="mt-0.5 text-[11px] text-muted-foreground font-mono tabular-nums">
                {queueCountLabel}
              </div>
            </div>

            {parseableCount > 0 ? (
              <Button type="button" variant="outline" size="sm" className="gap-2" onClick={parseAllPending}>
                <Play className="w-4 h-4" />
                全部解析
              </Button>
            ) : null}
          </div>
        </div>

        <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain no-scrollbar p-3 space-y-3 bg-muted/20">
          <div className="rounded-2xl border border-border/60 bg-card p-2">
            <DocumentFolderTree
              onRequestUpload={requestUploadToFolder}
              onRequestUploadFolder={requestUploadFolder}
              showFiles="expanded"
              onSelectFile={(fileId) => {
                const queueMatch = files.find((f) => f.libraryId === fileId)
                if (queueMatch) {
                  setActiveLibraryFileId(null)
                  setActiveFileId(queueMatch.id)
                  setQueueOpen(false)
                  return
                }
                setActiveFileId(null)
                setActiveLibraryFileId(fileId)
                setQueueOpen(false)
              }}
              onDeleteFolder={handleDeleteFolder}
              onFileDrop={moveFileToFolder}
            />
          </div>

          {visibleQueueFiles.length > 0 ? (
            <div className="rounded-2xl border border-border/60 bg-card p-2">
              <div className="flex items-center justify-between px-2 pb-2">
                <div className="text-sm font-semibold text-foreground">当前会话</div>
                <div className="text-[11px] text-muted-foreground font-mono tabular-nums">
                  {visibleQueueFiles.length}
                </div>
              </div>
	              <div className="space-y-1">
	                {visibleQueueFiles.map((f) => (
	                  <FileQueueItem
                      key={f.id}
	                      file={{
                        id: f.id,
                        name: f.name,
                        size: f.size,
                        status: f.status,
                        progress: f.progress,
                        parser: f.parserLabel,
                        folderPathLabel: f.folderId && f.folderId !== ROOT_FOLDER_ID ? folderPathById[f.folderId] : undefined,
                        sourcePath: f.sourcePath,
                        error: f.error,
                        duration: f.duration,
                        pageCount: f.stats?.pageCount,
                      }}
                      draggable
                      onDragStart={(e) => handleFileDragStart(e, f.id)}
                      isActive={activeFileId === f.id}
                      onClick={() => {
                        setActiveLibraryFileId(null)
                        setActiveFileId(f.id)
                        setQueueOpen(false)
                      }}
                      onRemove={() => removeFile(f.id)}
                      onRetry={f.status === 'error' ? () => parseFile(f.id) : undefined}
                    />
	                ))}
	              </div>
            </div>
          ) : null}

          {visibleLibraryOnlyFiles.length > 0 ? (
            <div className="rounded-2xl border border-border/60 bg-card p-2">
              <div className="flex items-center justify-between px-2 pb-2">
                <div className="text-sm font-semibold text-foreground">文档库</div>
                <div className="text-[11px] text-muted-foreground font-mono tabular-nums">
                  {visibleLibraryOnlyFiles.length}
                </div>
              </div>
              <div className="space-y-1">
                {visibleLibraryOnlyFiles.map((f) => (
                  <FileQueueItem
                    key={f.id}
                    file={{
                      id: f.id,
                      name: f.filename,
                      size: f.fileSize,
                      status: f.status || 'parsed',
                      parser: f.parser,
                      duration: f.durationSec,
                      folderPathLabel: f.folderId && f.folderId !== ROOT_FOLDER_ID ? folderPathById[f.folderId] : undefined,
                    }}
                    isActive={activeLibraryFileId === f.id}
                    onClick={() => {
                      setActiveFileId(null)
                      setActiveLibraryFileId(f.id)
                      setQueueOpen(false)
                    }}
                    onRemove={() => removeFile(f.id)}
                  />
                ))}
              </div>
            </div>
          ) : null}
        </div>
      </WorkbenchPanelDialog>

      {/* Mobile: expose inspector/navigation helpers via a dialog */}
      <WorkbenchPanelDialog open={inspectorOpen} onOpenChange={setInspectorOpen} title="工具">
        <div className="flex-1 min-h-0 overflow-y-auto overscroll-contain no-scrollbar p-4 space-y-5 bg-muted/10">
          {activeFile && activeMarkdown ? (
            <>
              <div className="space-y-2">
                <div className="text-xs font-semibold text-muted-foreground">视图</div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button
                    type="button"
                    size="sm"
                    variant={rightPanelMode === 'blocks' ? 'default' : 'outline'}
                    className="gap-2"
                    onClick={() => setRightPanelMode('blocks')}
                    disabled={activeBlocksWithPositions.length === 0}
                  >
                    <FileStack className="w-4 h-4" />
                    版面
                  </Button>
                  <Button
                    type="button"
                    size="sm"
                    variant={rightPanelMode === 'markdown' ? 'default' : 'outline'}
                    className="gap-2"
                    onClick={() => setRightPanelMode('markdown')}
                  >
                    <FileText className="w-4 h-4" />
                    Markdown
                  </Button>

                  {rightPanelMode === 'markdown' ? (
                    <>
                      <div className="w-px h-5 bg-border/60 mx-1" aria-hidden="true" />
                      <Button
                        type="button"
                        size="sm"
                        variant={previewMode === 'rendered' ? 'default' : 'outline'}
                        className="gap-2"
                        onClick={() => setPreviewMode('rendered')}
                      >
                        <Eye className="w-4 h-4" />
                        预览
                      </Button>
                      <Button
                        type="button"
                        size="sm"
                        variant={previewMode === 'raw' ? 'default' : 'outline'}
                        className="gap-2"
                        onClick={() => setPreviewMode('raw')}
                      >
                        <Code className="w-4 h-4" />
                        源码
                      </Button>
                    </>
                  ) : null}
                </div>
              </div>

              {(() => {
    if (rightPanelMode === 'blocks' && activeBlocksWithPositions.length > 0) {
        return (<div className="space-y-2">
                  <div className="text-xs font-semibold text-muted-foreground">定位块</div>
                  <div className="rounded-2xl border border-border/60 bg-card p-2">
                    <div className="max-h-[46vh] overflow-y-auto overscroll-contain no-scrollbar space-y-1">
                      {activeBlocksWithPositions.slice(0, 80).map((block, idx) => {
                const pageIndex = block.positions?.[0]?.pages?.[0];
                const isActive = block.id === activeBlockId;
                return (<button key={block.id} type="button" onClick={() => {
                        setActiveBlockId(block.id);
                        setInspectorOpen(false);
                    }} className={cn('w-full text-left rounded-xl border px-3 py-2 text-sm transition-colors', isActive
                        ? 'border-sky-400 bg-sky-50 dark:bg-sky-950/30'
                        : 'border-border/50 hover:bg-muted/40')}>
                            <div className="flex items-center justify-between gap-3">
                              <div className="font-medium truncate">块 {idx + 1}</div>
                              <div className="text-[11px] text-muted-foreground font-mono tabular-nums">
                                {Number.isFinite(pageIndex) ? `页 ${Number(pageIndex) + 1}` : ''}
                              </div>
                            </div>
                          </button>);
            })}
                    </div>
                  </div>
                </div>);
    }
    else if (rightPanelMode === 'markdown') {
            return (<div className="space-y-2">
                  <div className="text-xs font-semibold text-muted-foreground">目录</div>
                  <div className="rounded-2xl border border-border/60 bg-card p-3">
                    <MarkdownToc markdown={activeMarkdown}/>
                  </div>
                </div>);
        }
        else {
            return null;
        }
})()}

              <div className="space-y-2">
                <div className="text-xs font-semibold text-muted-foreground">快捷操作</div>
                <div className="flex flex-wrap items-center gap-2">
                  <Button type="button" variant="outline" size="sm" className="gap-2" onClick={copyMarkdown}>
                    <Copy className="w-4 h-4" />
                    复制 Markdown
                  </Button>
                  <Button type="button" variant="outline" size="sm" className="gap-2" onClick={downloadMarkdown}>
                    <Download className="w-4 h-4" />
                    下载 Markdown
                  </Button>
                </div>
              </div>
            </>
          ) : (
            <div className="text-sm text-muted-foreground">
              选择文件后可在此查看定位块、目录和快捷操作。
            </div>
          )}
        </div>
      </WorkbenchPanelDialog>
    </AppFrame>
  )
}
