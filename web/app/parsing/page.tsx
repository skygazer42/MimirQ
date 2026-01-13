'use client'

import { useState, useCallback, useEffect, useMemo, useRef } from 'react'
import { useRouter } from 'next/navigation'
import {
  Upload,
  FileText,
  Loader2,
  Eye,
  Code,
  Download,
  Copy,
  Check,
  RotateCcw,
  Sparkles,
  FileStack,
  Clock,
  Table2,
  Image,
  ChevronRight,
  Zap,
  ShieldCheck,
  Edit3,
  Save,
  X,
  PanelRightOpen,
  PanelRightClose,
  FolderOpen,
  Play,
  Trash2,
  AlertCircle,
  CheckCircle2,
  Paperclip,
  FolderUp,
  Plus,
} from 'lucide-react'
import { Navbar } from '@/components/navbar'
import { Button } from '@/components/ui/button'
import { documentApi } from '@/lib/api-client'
import { formatApiError } from '@/lib/api-errors'
import { formatFileSize, cn } from '@/lib/utils'
import { ROOT_FOLDER_ID, useParsedFiles } from '@/store/use-parsed-files-store'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { getParserLabel } from '@/lib/parser-options'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { FileQueueItem, FileQueueItemData, FileStatus } from '@/components/ui/file-queue-item'
import { ParserDropdown } from '@/components/ui/parser-dropdown'
import { MarkdownRenderer } from '@/components/markdown/markdown-renderer'
import { MarkdownToc } from '@/components/markdown/markdown-toc'
import { extractMarkdownHeadings } from '@/lib/markdown'
import { DocumentFolderTree, getFileIcon } from '@/components/document-library/folder-tree'
import { extractZipFiles, isZipFile } from '@/lib/zip'
import { PdfViewer } from '@/components/parsing/pdf-viewer'
import { extractBlocksFromMarkdown, ParsingBlock } from '@/lib/parsing-positions'
import { toast } from 'sonner'
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuTrigger,
} from '@/components/ui/dropdown-menu'

const ZIP_ALLOWED_EXTENSIONS = new Set([
  'pdf',
  'txt',
  'md',
  'doc',
  'docx',
  'xls',
  'xlsx',
  'csv',
  'html',
  'json',
])


interface ParseRun {
  id: string
  parserBackend: string
  parserLabel: string
  rawMarkdown: string
  cleanedMarkdown: string
  blocks: ParsingBlock[]
  createdAt: number
}

// 解析后的文件（扩展版）
interface ParsedFile extends FileQueueItemData {
  file: File
  folderId: string
  sourcePath?: string
  markdownContent: string | null
  parserBackend: string
  parserLabel: string
  runs?: ParseRun[]
  activeRunId?: string
  parseStartTime?: number
  createdAt?: number
  stats?: {
    charCount: number
    lineCount: number
    pageCount?: number
    tableCount?: number
    imageCount?: number
    blockCount?: number
  }
}

export default function ParsingPage() {
  const router = useRouter()

  // 文件状态
  const [files, setFiles] = useState<ParsedFile[]>([])
  const [activeFileId, setActiveFileId] = useState<string | null>(null)
  const [isSidebarCollapsed, setIsSidebarCollapsed] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const [copied, setCopied] = useState(false)
  const [dragOverFolderId, setDragOverFolderId] = useState<string | null>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const folderInputRef = useRef<HTMLInputElement>(null)
  const uploadTargetFolderIdRef = useRef<string | null>(null)
  const fileIdSetRef = useRef<Set<string>>(new Set())
  const parseControllersRef = useRef<Map<string, AbortController>>(new Map())
  const parseProgressIntervalsRef = useRef<Map<string, ReturnType<typeof setInterval>>>(new Map())

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

  // 共享存储
  const { addParsedFile, activeFolderId, folders, createFolder, setActiveFolderId } = useParsedFiles()

  // 获取当前选中的文件
  const activeFile = files.find((f) => f.id === activeFileId) || null

  const activeRun = useMemo(() => {
    if (!activeFile) return null
    const runs = activeFile.runs || []
    if (!runs.length) return null
    const selected = runs.find((run) => run.id === activeFile.activeRunId)
    return selected || runs[runs.length - 1]
  }, [activeFile])

  const activeMarkdown = activeRun?.cleanedMarkdown || activeFile?.markdownContent || ''
  const activeBlocks = activeRun?.blocks || []
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
  const generateId = () => Math.random().toString(36).substring(2, 15)

  // 添加文件（支持 .zip 批量解压，支持文件夹上传）
  const addFiles = useCallback(
    async (incomingFiles: File[], baseFolderIdOverride?: string) => {
      const defaultLabel = getParserLabel(parserBackend)
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
            parserBackend,
            parserLabel: defaultLabel,
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
                parserBackend,
                parserLabel: defaultLabel,
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

        queued.push({
          id: generateId(),
          file,
          folderId: baseFolderId,
          name: file.name,
          size: file.size,
          status: 'pending' as FileStatus,
          markdownContent: null,
          error: undefined,
          parserBackend,
          parserLabel: defaultLabel,
          createdAt: now,
        })
        added += 1
      }

      if (queued.length === 0) {
        if (skipped > 0) toast.warning(`已跳过 ${skipped} 个不支持的文件`)
        return
      }

      setFiles((prev) => [...prev, ...queued])
      setActiveFileId((prev) => prev ?? queued[0].id)

      if (added > 0) toast.success(`已加入队列：${added} 个文件`)
      if (skipped > 0) toast.warning(`已跳过 ${skipped} 个不支持的文件`)
    },
    [parserBackend, activeFolderId, folders, createFolder]
  )

  const currentFolderId = activeFolderId || ROOT_FOLDER_ID

  const visibleQueueFiles = useMemo(() => {
    return files
      .filter((f) => (f.folderId || ROOT_FOLDER_ID) === currentFolderId)
      .sort((a, b) => (b.createdAt || 0) - (a.createdAt || 0))
  }, [files, currentFolderId])

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

  const folderStatsById = useMemo(() => {
    const filesByFolder = new Map<string, ParsedFile[]>()
    for (const file of files) {
      const folderId = file.folderId || ROOT_FOLDER_ID
      const list = filesByFolder.get(folderId) || []
      list.push(file)
      filesByFolder.set(folderId, list)
    }

    const stats = new Map<string, { count: number; latestTs: number }>()
    const collect = (folderId: string): { count: number; latestTs: number } => {
      if (stats.has(folderId)) return stats.get(folderId) as { count: number; latestTs: number }
      let count = 0
      let latestTs = 0
      const directFiles = filesByFolder.get(folderId) || []
      for (const file of directFiles) {
        count += 1
        latestTs = Math.max(latestTs, file.createdAt || 0)
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
  }, [files, folders, childrenByParentId])

  useEffect(() => {
    if (visibleQueueFiles.length === 0) {
      setActiveFileId(null)
      return
    }

    const stillVisible = activeFileId && visibleQueueFiles.some((f) => f.id === activeFileId)
    if (!stillVisible) {
      setActiveFileId(visibleQueueFiles[0].id)
    }
  }, [visibleQueueFiles, activeFileId])

  // 拖放处理
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback(async (e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    uploadTargetFolderIdRef.current = null
    const droppedFiles = Array.from(e.dataTransfer.files)
    await addFiles(droppedFiles)
  }, [addFiles])

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
    cancelParse(fileId)
    setFiles((prev) => prev.filter((f) => f.id !== fileId))
  }

  const moveFileToFolder = useCallback((fileId: string, folderId: string) => {
    const targetId = folderId || ROOT_FOLDER_ID
    setFiles((prev) =>
      prev.map((f) => (f.id === fileId ? { ...f, folderId: targetId } : f))
    )
  }, [])

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
    const fileId = e.dataTransfer.getData('text/plain')
    if (fileId) {
      moveFileToFolder(fileId, folderId)
    }
    setDragOverFolderId(null)
  }, [moveFileToFolder])

  // 解析文件（支持删除中断）
  const parseFile = async (fileId: string) => {
    const file = files.find((f) => f.id === fileId)
    if (!file) return

    cancelParse(fileId)
    const controller = new AbortController()
    parseControllersRef.current.set(fileId, controller)

    const startTime = Date.now()

    setFiles((prev) =>
      prev.map((f) =>
        f.id === fileId
          ? { ...f, status: 'parsing' as FileStatus, error: undefined, progress: 0, parseStartTime: startTime }
          : f
      )
    )

    const progressInterval = setInterval(() => {
      setFiles((prev) =>
        prev.map((f) =>
          f.id === fileId && f.status === 'parsing'
            ? { ...f, progress: Math.min((f.progress || 0) + Math.random() * 15, 90) }
            : f
        )
      )
    }, 300)
    parseProgressIntervalsRef.current.set(fileId, progressInterval)

    const clearProgressInterval = () => {
      clearInterval(progressInterval)
      if (parseProgressIntervalsRef.current.get(fileId) === progressInterval) {
        parseProgressIntervalsRef.current.delete(fileId)
      }
    }

    try {
      const data = await documentApi.preview(file.file, parserBackend, undefined, {
        signal: controller.signal,
      })
      if (controller.signal.aborted) return
      if (parseControllersRef.current.get(fileId) !== controller) return
      if (!fileIdSetRef.current.has(fileId)) return

      clearProgressInterval()

      const rawMarkdown = data.segments.map((s) => s.content).join('\n\n')
      const resolvedBackend = data.parser_backend || parserBackend
      const resolvedLabel = getParserLabel(resolvedBackend)
      const duration = ((Date.now() - startTime) / 1000).toFixed(1)
      const parsed = extractBlocksFromMarkdown(rawMarkdown)
      const markdownContent = parsed.cleanedMarkdown
      const blocks = parsed.blocks
      const runId = `${resolvedBackend}-${Date.now()}`
      const run = {
        id: runId,
        parserBackend: resolvedBackend,
        parserLabel: resolvedLabel,
        rawMarkdown,
        cleanedMarkdown: markdownContent,
        blocks,
        createdAt: Date.now(),
      }

      const stats = {
        charCount: markdownContent.length,
        lineCount: markdownContent.split('\n').length,
        tableCount: (markdownContent.match(/\|.*\|/g) || []).length > 0
          ? (markdownContent.match(/^\|/gm) || []).length / 2
          : 0,
        imageCount: (markdownContent.match(/!\[.*?\]\(.*?\)/g) || []).length,
        blockCount: blocks.length,
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
                duration: parseFloat(duration),
                stats,
                runs: [...(f.runs || []), run],
                activeRunId: runId,
              }
            : f
        )
      )

      setActiveBlockId(null)
      setHoveredBlockId(null)
      setRightPanelMode(blocks.length ? 'blocks' : 'markdown')

      addParsedFile({
        filename: file.file.name,
        fileType: file.file.name.split('.').pop()?.toLowerCase() || '',
        fileSize: file.file.size,
        markdownContent,
        parser: resolvedLabel,
        folderId: file.folderId,
      })
    } catch (err: any) {
      if (controller.signal.aborted) return
      if (parseControllersRef.current.get(fileId) !== controller) return
      if (!fileIdSetRef.current.has(fileId)) return
      const errorMessage = formatApiError(err, '文档解析失败')
      setFiles((prev) =>
        prev.map((f) =>
          f.id === fileId
            ? {
                ...f,
                status: 'error' as FileStatus,
                error: errorMessage,
                progress: 0,
              }
            : f
        )
      )
    } finally {
      if (parseControllersRef.current.get(fileId) === controller) {
        parseControllersRef.current.delete(fileId)
      }
      clearProgressInterval()
    }
  }

  const parseAllPending = async () => {
    const targets = visibleQueueFiles.filter((f) => f.status === 'pending' || f.status === 'error')
    for (const file of targets) {
      await parseFile(file.id)
    }
  }

  const handleSelectRun = (runId: string) => {
    if (!activeFile || !activeFile.runs?.length) return
    const nextRun = activeFile.runs.find((run) => run.id === runId)
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
  const handleSaveEdit = () => {
    if (!activeFile) return
    const targetRunId = activeRun?.id ?? activeFile.activeRunId

    // 更新文件内容
    setFiles((prev) =>
      prev.map((f) => {
        if (f.id !== activeFile.id) return f
        const runs = targetRunId
          ? f.runs?.map((run) =>
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
                blockCount: 0,
              }
            : undefined,
        }
      })
    )

    setRightPanelMode('markdown')
    setActiveBlockId(null)
    setHoveredBlockId(null)

    setIsEditing(false)
  }

  // 提交到数据治理
  const handleSubmitToGovernance = () => {
    if (!activeFile || !activeMarkdown) return

    // 使用当前内容（可能是编辑后的）提交到数据治理
    addParsedFile({
      filename: activeFile.file.name,
      fileType: activeFile.file.name.split('.').pop()?.toLowerCase() || '',
      fileSize: activeFile.file.size,
      markdownContent: activeMarkdown,
      parser: activeFile.parserLabel,
      folderId: activeFile.folderId,
    })

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
  const parseAllLabel = activeFolderId && activeFolderId !== ROOT_FOLDER_ID ? '解析当前目录' : '全部解析'
  const queueCountLabel = visibleQueueFiles.length === 0 ? '0' : `${parsedCount}/${visibleQueueFiles.length}`

  return (
    <div className="relative flex h-screen overflow-hidden bg-amber-50/70">
      <div className="absolute inset-0 pointer-events-none">
        <div className="absolute inset-0 bg-[radial-gradient(circle_at_top_left,rgba(251,191,36,0.16),transparent_55%),radial-gradient(circle_at_top_right,rgba(244,114,182,0.12),transparent_50%),radial-gradient(circle_at_bottom_left,rgba(251,146,60,0.12),transparent_55%)]" />
        <div className="absolute inset-0 opacity-[0.04] bg-[radial-gradient(#92400e_1px,transparent_1px)] [background-size:18px_18px]" />
      </div>
      <div className="relative z-10 flex h-full w-full">
        <Navbar />

        <main className="flex-1 flex flex-col overflow-hidden min-h-0">
        {/* 顶部标题栏 */}
        <header className="flex-shrink-0 bg-white/80 border-b border-amber-100/70 px-6 py-4 h-16 flex items-center justify-between z-20 shadow-sm relative backdrop-blur">
          <div className="flex items-center gap-4">
            <div className="w-9 h-9 bg-gradient-to-br from-amber-500 to-rose-500 rounded-lg flex items-center justify-center shadow-lg shadow-amber-200/50">
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-stone-900 leading-tight">文档解析工作台</h1>
              <p className="text-xs text-stone-500 leading-none mt-1">
                上传文件并转换为 Markdown 格式，为数据治理做准备
              </p>
            </div>
          </div>
          <div className="absolute inset-x-6 bottom-0 h-px bg-gradient-to-r from-transparent via-amber-200/70 to-transparent" />
        </header>

        <div className="flex-1 flex overflow-hidden min-h-0">
          {/* 左侧：文件列表面板 */}
          <aside
            className={cn(
              "group/sidebar relative flex flex-col flex-shrink-0 bg-white/80 border-r border-amber-100/70 transition-all duration-300 ease-in-out z-10 backdrop-blur shadow-[inset_-1px_0_0_rgba(255,255,255,0.6)]",
              isSidebarCollapsed ? "w-0 border-r-0" : "w-80"
            )}
            style={{ width: isSidebarCollapsed ? 0 : 320 }}
          >
            {/* Toggle Button */}
            <Button
              variant="ghost"
              size="icon"
              className={cn(
                "absolute -right-3 top-3 z-30 h-6 w-6 rounded-full border border-amber-100/70 bg-white shadow-sm hover:bg-amber-50/70 text-stone-400 hover:text-stone-600 transition-opacity opacity-0 group-hover/sidebar:opacity-100",
                isSidebarCollapsed && "opacity-100 -right-8 translate-x-2"
              )}
              onClick={() => setIsSidebarCollapsed(!isSidebarCollapsed)}
              title={isSidebarCollapsed ? "展开侧边栏" : "收起侧边栏"}
            >
              {isSidebarCollapsed ? <PanelRightOpen className="w-3 h-3" /> : <PanelRightClose className="w-3 h-3" />}
            </Button>

            <div className={cn("flex-1 flex flex-col min-h-0 w-full overflow-hidden", isSidebarCollapsed && "invisible")}>
            {/* 解析器选择 */}
            <div className="p-4 border-b">
              <div className="flex items-center justify-between mb-3">
                <span className="text-xs font-semibold text-stone-500 uppercase tracking-wider">解析方式</span>
              </div>
              <ParserDropdown
                value={parserBackend}
                onChange={setParserBackend}
              />
            </div>

            {/* Folder Navigation */}
            <div className="flex-none h-1/3 min-h-[200px] overflow-y-auto p-2 border-b custom-scrollbar bg-amber-50/40">
               <div className="h-full rounded-2xl border border-amber-100/70 bg-white/70 p-2 shadow-sm backdrop-blur">
                 <DocumentFolderTree
                    onRequestUpload={requestUploadToFolder}
                    onRequestUploadFolder={requestUploadFolder}
                    fileItems={[]}
                    showFiles="expanded"
                    onSelectFile={(fileId) => setActiveFileId(fileId)}
                    onDeleteFolder={handleDeleteFolder}
                    onFileDrop={moveFileToFolder}
                 />
               </div>
            </div>

            {/* File List Header & Toolbar */}
            <div
              className={cn(
                "px-4 py-2 border-b flex items-center justify-between z-10 sticky top-0",
                "bg-amber-50/70 backdrop-blur border-amber-100/70"
              )}
              onDragOver={(e) => handleFolderDragOver(e, currentFolderId)}
              onDragLeave={() => setDragOverFolderId(null)}
              onDrop={(e) => handleFolderDrop(e, currentFolderId)}
            >
               <div className="flex items-center gap-3 min-w-0 group">
                  <div className="w-8 h-8 rounded-lg bg-amber-50 text-amber-700 flex items-center justify-center">
                    <FileText className="w-4 h-4" />
                  </div>
                  <div className="min-w-0">
                    <div className="text-sm font-semibold text-stone-800">文档列表</div>
                    <div className="mt-0.5">
                      <span
                        className="inline-flex max-w-[220px] items-center truncate rounded-full bg-amber-100/80 px-2 py-0.5 text-[10px] font-medium text-stone-600"
                        title={activeFolderPathLabel}
                      >
                        {activeFolderPathLabel}
                      </span>
                    </div>
                  </div>
                  <span className="bg-amber-100/70 text-stone-600 px-2 py-0.5 rounded-full text-[11px] font-medium opacity-0 group-hover:opacity-100 transition-opacity">
                    {visibleQueueFiles.length}
                  </span>
               </div>
               
               <div className="flex items-center gap-1">
                  {parseableCount > 0 && (
                    <Button
                      variant="ghost"
                      size="sm"
                      onClick={parseAllPending}
                      className="h-7 text-xs gap-1.5 text-amber-700 hover:text-amber-800 hover:bg-amber-50 mr-1 font-medium"
                    >
                      <Play className="w-3.5 h-3.5" />
                      解析
                    </Button>
                  )}
                  
                  <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                      <Button
                        variant="ghost"
                        size="icon"
                        className="h-7 w-7 text-stone-600 hover:bg-amber-100/70 rounded-lg"
                      >
                        <Plus className="w-4 h-4" />
                      </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end" className="w-52">
                      <DropdownMenuItem onClick={() => requestUploadToFolder(activeFolderId || ROOT_FOLDER_ID)}>
                        <Paperclip className="w-4 h-4 mr-2 text-amber-700" />
                        上传文件
                      </DropdownMenuItem>
                      <DropdownMenuItem onClick={() => requestUploadFolder(activeFolderId || ROOT_FOLDER_ID)}>
                        <FolderUp className="w-4 h-4 mr-2 text-amber-600" />
                        上传文件夹
                      </DropdownMenuItem>
                    </DropdownMenuContent>
                  </DropdownMenu>
               </div>
            </div>

            {/* File List */}
            <div className="flex-1 overflow-y-auto p-2 custom-scrollbar bg-amber-50/40">
               <div className="min-h-full rounded-2xl border border-amber-100/70 bg-white/70 p-2 shadow-sm backdrop-blur">
               {directFolders.length === 0 && visibleQueueFiles.length === 0 ? (
                 <div className="h-full flex flex-col items-center justify-center text-stone-400">
                    <div className="w-14 h-14 bg-gradient-to-br from-amber-100/70 to-white rounded-2xl flex items-center justify-center mb-3 shadow-sm">
                      <FolderOpen className="w-6 h-6 text-stone-300" />
                    </div>
                    <p className="text-sm font-medium text-stone-500">暂无文件</p>
                    <p className="text-xs text-stone-400 mt-1">拖拽文件到此处或点击上方按钮添加</p>
                 </div>
               ) : (
                 <div className="space-y-1">
                   {directFolders.map((folder) => {
                     const stats = folderStatsById.get(folder.id)
                     const latestTs = stats?.latestTs || Date.parse(folder.createdAt)
                     return (
                       <div
                         key={folder.id}
                         className={cn(
                           "flex items-center gap-3 p-2.5 rounded-xl border border-transparent hover:border-amber-100/70 hover:bg-amber-50/70 group transition-all cursor-pointer relative",
                           dragOverFolderId === folder.id && "border-amber-200 bg-amber-50/60",
                           activeFolderId === folder.id && "bg-amber-50 border-amber-100 ring-1 ring-amber-200"
                         )}
                         onClick={() => setActiveFolderId(folder.id)}
                         onDragOver={(e) => handleFolderDragOver(e, folder.id)}
                         onDragLeave={() => setDragOverFolderId(null)}
                         onDrop={(e) => handleFolderDrop(e, folder.id)}
                       >
                         <div className="w-9 h-9 rounded-xl bg-amber-50 text-amber-600 flex items-center justify-center flex-shrink-0 shadow-sm">
                           <FolderOpen className="w-4 h-4" />
                         </div>
                         <div className="flex-1 min-w-0">
                           <div className="flex items-center justify-between">
                             <div className={cn("text-sm font-semibold truncate pr-6", activeFolderId === folder.id ? "text-amber-900" : "text-stone-700")}>
                               {folder.name}
                             </div>
                             <span className="text-[10px] text-stone-400 flex-shrink-0">
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
                             <span className="text-[10px] text-stone-400">
                               {(stats?.count || 0)} 项
                             </span>
                           </div>
                         </div>
                       </div>
                     )
                   })}
                   {visibleQueueFiles.map(f => (
                     <div key={f.id} 
                          className={cn(
                            "flex items-center gap-3 p-2.5 rounded-xl border border-transparent hover:border-amber-100/70 hover:bg-amber-50/70 group transition-all cursor-pointer relative",
                            activeFileId === f.id && "bg-amber-50 border-amber-100 ring-1 ring-amber-200"
                          )}
                          onClick={() => setActiveFileId(f.id)}
                          draggable
                          onDragStart={(e) => handleFileDragStart(e, f.id)}
                     >
                        {getFileIcon(f.name)}
                        <div className="flex-1 min-w-0">
                           <div className="flex items-center justify-between">
                             <div className={cn("text-sm font-medium truncate pr-6", activeFileId === f.id ? "text-amber-900" : "text-stone-700")}>
                               {f.name}
                             </div>
                             <span className="text-[10px] text-stone-400 flex-shrink-0">
                               {f.createdAt
                                 ? new Date(f.createdAt).toLocaleString([], {
                                     month: '2-digit',
                                     day: '2-digit',
                                     hour: '2-digit',
                                     minute: '2-digit',
                                   })
                                 : ''}
                             </span>
                           </div>
                           
                           <div className="flex items-center gap-2 mt-1 min-h-[16px]">
                              {/* Status Indicator */}
                              {f.status === 'parsing' ? (
                                <div className="flex items-center gap-2 w-full max-w-[120px]">
                                   <div className="h-1.5 flex-1 bg-amber-100 rounded-full overflow-hidden">
                                      <div className="h-full bg-amber-500 animate-[progress_1s_ease-in-out_infinite] w-full origin-left scale-x-50" />
                                   </div>
                                   <span className="text-[10px] text-amber-600 font-medium">解析中...</span>
                                </div>
                              ) : f.status === 'error' ? (
                                <span className="text-[10px] text-red-500 flex items-center gap-1">
                                  <AlertCircle className="w-3 h-3" /> 失败
                                </span>
                              ) : f.status === 'parsed' ? (
                                <span className="text-[10px] text-green-600 flex items-center gap-1">
                                  <CheckCircle2 className="w-3 h-3" /> 完成
                                </span>
                              ) : (
                                <span className="text-[10px] text-stone-400">等待中</span>
                              )}
                           </div>
                        </div>
                        
                        {/* Stop/Delete Button - Absolute positioned or flex? Group hover */}
                        <div className="absolute right-2 top-1/2 -translate-y-1/2 flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity bg-amber-50/70 backdrop-blur-sm rounded-md p-0.5 shadow-sm border border-amber-100/70">
                           {f.status === 'parsing' && (
                              <Button
                                variant="ghost"
                                size="icon"
                                className="h-6 w-6 text-stone-500 hover:text-red-600 hover:bg-red-50"
                                onClick={(e) => {
                                  e.stopPropagation()
                                  cancelParse(f.id)
                                }}
                                title="停止解析"
                              >
                                <X className="w-3.5 h-3.5" />
                              </Button>
                           )}
                           <Button
                              variant="ghost"
                              size="icon"
                              className="h-6 w-6 text-stone-500 hover:text-red-600 hover:bg-red-50"
                              onClick={(e) => {
                                e.stopPropagation()
                                removeFile(f.id)
                              }}
                              title="删除文件"
                           >
                              <Trash2 className="w-3.5 h-3.5" />
                           </Button>
                        </div>
                     </div>
                   ))}
                 </div>
               )}
               </div>
            </div>

            {/* 隐藏的文件上传 Input */}
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".pdf,.txt,.md,.doc,.docx,.xls,.xlsx,.csv,.html,.json,.zip"
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

            {/* 底部统计 */}
            {visibleQueueFiles.length > 0 && (
              <div className="p-4 border-t bg-amber-50/70">
                <div className="flex items-center justify-around text-xs text-stone-500">
                  <span className="flex items-center gap-1">
                    <Clock className="w-3 h-3" />
                    {pendingCount} 等待
                  </span>
                  <span className="flex items-center gap-1">
                    <Loader2 className="w-3 h-3" />
                    {parsingCount} 处理
                  </span>
                  <span className="flex items-center gap-1 text-green-600">
                    <Check className="w-3 h-3" />
                    {parsedCount} 完成
                  </span>
                </div>
              </div>
            )}
            </div>
          </aside>

          {/* 右侧：预览区域 */}
          <div className="flex-1 flex flex-col bg-white/85 backdrop-blur overflow-hidden min-h-0 shadow-[inset_1px_0_0_rgba(255,255,255,0.6)]">
            {!activeFile ? (
              // 空状态
              <div className="flex-1 flex items-center justify-center">
                <div className="text-center max-w-md">
                  <div className="w-20 h-20 mx-auto mb-4 bg-gradient-to-br from-amber-100/70 to-amber-50/70 rounded-2xl flex items-center justify-center">
                    <FileText className="w-10 h-10 text-stone-300" />
                  </div>
                  <h3 className="text-lg font-medium text-stone-700 mb-2">选择文件开始</h3>
                  <p className="text-stone-400 text-sm">
                    从左侧上传或选择文件，系统将使用 AI 智能解析文档结构
                  </p>
                </div>
              </div>
            ) : (
              <>
                {/* 统计卡片区 - 解析完成后显示 */}
                {activeFile.status === 'parsed' && activeFile.stats && (
                  <div className="px-6 py-4 border-b bg-gradient-to-r from-amber-50/70 to-white">
                    <StatsGrid>
                      <StatCard
                        icon={FileText}
                        label="字符数"
                        value={activeFile.stats.charCount.toLocaleString()}
                        color="amber"
                      />
                      <StatCard
                        icon={FileStack}
                        label="行数"
                        value={activeFile.stats.lineCount.toLocaleString()}
                        color="orange"
                      />
                      <StatCard
                        icon={Table2}
                        label="表格"
                        value={Math.floor(activeFile.stats.tableCount || 0)}
                        color="green"
                      />
                      <StatCard
                        icon={Image}
                        label="图片"
                        value={activeFile.stats.imageCount || 0}
                        color="red"
                      />
                      <StatCard
                        icon={Clock}
                        label="耗时"
                        value={`${activeFile.duration}s`}
                        subValue={activeFile.parserLabel}
                        color="gray"
                      />
                    </StatsGrid>
                  </div>
                )}

                {/* 工具栏 */}
                <div className="flex items-center justify-between px-6 py-3 border-b bg-amber-50/70">
                  <div className="flex items-center gap-3">
                    <span className="font-medium text-stone-900 truncate max-w-[200px]">
                      {activeFile.file.name}
                    </span>
                    <span className="text-xs text-stone-400 bg-amber-100/70 px-2 py-0.5 rounded">
                      {activeFile.parserLabel}
                    </span>
                    {activeFile.runs && activeFile.runs.length > 1 && (
                      <select
                        value={activeRun?.id || ''}
                        onChange={(e) => handleSelectRun(e.target.value)}
                        className="text-xs border border-amber-100/70 rounded px-2 py-1 bg-white text-stone-600"
                      >
                        {activeFile.runs.map((run) => (
                          <option key={run.id} value={run.id}>
                            {run.parserLabel} ? {new Date(run.createdAt).toLocaleTimeString()}
                          </option>
                        ))}
                      </select>
                    )}
                    {isEditing && (
                      <span className="text-xs text-amber-600 bg-amber-100 px-2 py-0.5 rounded flex items-center gap-1">
                        <Edit3 className="w-3 h-3" />
                        编辑中
                      </span>
                    )}
                  </div>

                  <div className="flex items-center gap-2">
                    {activeFile.status === 'parsed' && (
                      <>
                        {isEditing ? (
                          // 编辑模式按钮
                          <>
                            <Button
                              variant="ghost"
                              size="sm"
                              onClick={handleCancelEdit}
                              className="gap-1.5 text-stone-500"
                            >
                              <X className="w-4 h-4" />
                              取消
                            </Button>
                            <Button
                              onClick={handleSaveEdit}
                              size="sm"
                              className="gap-1.5 bg-amber-600 hover:bg-amber-700"
                            >
                              <Save className="w-4 h-4" />
                              保存修改
                            </Button>
                          </>
                        ) : (
                          // 预览模式按钮
                          <>
                            {activeBlocks.length > 0 && (
                              <div className="flex items-center bg-amber-100/70 rounded-lg p-0.5 mr-2">
                                <button
                                  onClick={() => setRightPanelMode('blocks')}
                                  className={cn(
                                    'px-3 py-1.5 text-xs rounded-md transition-all flex items-center gap-1',
                                    rightPanelMode === 'blocks'
                                      ? 'bg-white text-stone-900 shadow-sm'
                                      : 'text-stone-500 hover:text-stone-700'
                                  )}
                                >
                                  <FileStack className="w-3.5 h-3.5" />
                                  版面
                                </button>
                                <button
                                  onClick={() => setRightPanelMode('markdown')}
                                  className={cn(
                                    'px-3 py-1.5 text-xs rounded-md transition-all flex items-center gap-1',
                                    rightPanelMode === 'markdown'
                                      ? 'bg-white text-stone-900 shadow-sm'
                                      : 'text-stone-500 hover:text-stone-700'
                                  )}
                                >
                                  <FileText className="w-3.5 h-3.5" />
                                  Markdown
                                </button>
                              </div>
                            )}

                            {rightPanelMode === 'markdown' && (
                              <div className="flex items-center bg-amber-100/70 rounded-lg p-0.5 mr-2">
                                <button
                                  onClick={() => setPreviewMode('rendered')}
                                  className={cn(
                                    'px-3 py-1.5 text-xs rounded-md transition-all flex items-center gap-1',
                                    previewMode === 'rendered'
                                      ? 'bg-white text-stone-900 shadow-sm'
                                      : 'text-stone-500 hover:text-stone-700'
                                  )}
                                >
                                  <Eye className="w-3.5 h-3.5" />
                                  预览
                                </button>
                                <button
                                  onClick={() => setPreviewMode('raw')}
                                  className={cn(
                                    'px-3 py-1.5 text-xs rounded-md transition-all flex items-center gap-1',
                                    previewMode === 'raw'
                                      ? 'bg-white text-stone-900 shadow-sm'
                                      : 'text-stone-500 hover:text-stone-700'
                                  )}
                                >
                                  <Code className="w-3.5 h-3.5" />
                                  源码
                                </button>
                              </div>
                            )}

                            <Button
                              variant="outline"
                              size="sm"
                              onClick={handleStartEdit}
                              className="gap-1.5"
                            >
                              <Edit3 className="w-4 h-4" />
                              编辑
                            </Button>

                            <Button variant="outline" size="sm" onClick={copyMarkdown} className="gap-1.5">
                              {copied ? <Check className="w-4 h-4 text-green-500" /> : <Copy className="w-4 h-4" />}
                              {copied ? '已复制' : '复制'}
                            </Button>

                            <Button variant="outline" size="sm" onClick={downloadMarkdown} className="gap-1.5">
                              <Download className="w-4 h-4" />
                              下载
                            </Button>
                          </>
                        )}
                      </>
                    )}

                    {activeFile.status === 'pending' && (
                      <Button onClick={() => parseFile(activeFile.id)} className="gap-2 bg-amber-600 hover:bg-amber-700">
                        <Sparkles className="w-4 h-4" />
                        开始解析
                      </Button>
                    )}

                    {activeFile.status === 'error' && (
                      <Button onClick={() => parseFile(activeFile.id)} variant="outline" className="gap-2">
                        <RotateCcw className="w-4 h-4" />
                        重试
                      </Button>
                    )}
                  </div>
                </div>

                {/* 内容区 */}
                <div className="flex-1 overflow-y-auto">
                  {activeFile.status === 'pending' && (
                    <div className="flex items-center justify-center h-full">
                      <div className="text-center">
                        <div className="w-16 h-16 mx-auto mb-4 bg-amber-100 rounded-xl flex items-center justify-center">
                          <Sparkles className="w-8 h-8 text-amber-600" />
                        </div>
                        <p className="text-stone-600 mb-2">准备就绪</p>
                        <p className="text-stone-400 text-sm">
                          点击上方按钮，使用 {activeFile.parserLabel} 解析
                        </p>
                      </div>
                    </div>
                  )}

                  {activeFile.status === 'parsing' && (
                    <div className="flex items-center justify-center h-full">
                      <div className="text-center">
                        <div className="relative">
                          <Loader2 className="w-12 h-12 animate-spin text-amber-600 mx-auto" />
                          <div className="absolute inset-0 flex items-center justify-center">
                            <span className="text-xs font-medium text-amber-700">
                              {Math.round(activeFile.progress || 0)}%
                            </span>
                          </div>
                        </div>
                        <p className="text-stone-600 mt-4">正在解析...</p>
                        <p className="text-stone-400 text-sm mt-1">{activeFile.parserLabel}</p>
                      </div>
                    </div>
                  )}

                  {activeFile.status === 'error' && (
                    <div className="flex items-center justify-center h-full">
                      <div className="text-center max-w-md">
                        <div className="w-16 h-16 mx-auto mb-4 bg-red-100 rounded-xl flex items-center justify-center">
                          <FileText className="w-8 h-8 text-red-500" />
                        </div>
                        <p className="text-red-600 font-medium mb-2">解析失败</p>
                        <p className="text-stone-500 text-sm">{activeFile.error}</p>
                      </div>
                    </div>
                  )}

                  {activeFile.status === 'parsed' && activeMarkdown && (
                    <div className="h-full">
                      {isEditing ? (
                        <div className="p-6">
                          <textarea
                            value={editedContent}
                            onChange={(e) => setEditedContent(e.target.value)}
                            className="w-full min-h-[500px] p-4 font-mono text-sm leading-relaxed text-stone-700 whitespace-pre-wrap bg-amber-50 border border-amber-200 rounded-xl resize-none focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent"
                            placeholder="在此编辑内容..."
                            autoFocus
                          />
                        </div>
                      ) : (
                        <div className="flex h-full min-h-[520px] flex-col lg:flex-row">
                          {isPdf ? (
                            <div className="w-full lg:w-1/2 border-b lg:border-b-0 lg:border-r border-amber-100/70 bg-amber-50/70">
                              <PdfViewer
                                file={activeFile.file}
                                blocks={activeBlocks}
                                activeBlockId={activeBlockId}
                                hoveredBlockId={hoveredBlockId}
                              />
                            </div>
                          ) : null}
                          <div className={isPdf ? 'w-full lg:w-1/2' : 'w-full'}>
                            {rightPanelMode === 'blocks' && activeBlocks.length > 0 ? (
                              <div className="h-full overflow-y-auto p-6 space-y-4">
                                {activeBlocks
                                  .filter((block) => (block.text || '').trim().length > 0)
                                  .map((block, idx) => {
                                    const pageIndex = block.positions?.[0]?.pages?.[0]
                                    const isActive = block.id === activeBlockId
                                    return (
                                      <button
                                        key={block.id}
                                        type="button"
                                        onClick={() => setActiveBlockId(block.id)}
                                        onMouseEnter={() => setHoveredBlockId(block.id)}
                                        onMouseLeave={() => setHoveredBlockId(null)}
                                        className={cn(
                                          'w-full text-left rounded-xl border p-4 transition shadow-sm',
                                          isActive
                                            ? 'border-amber-400 bg-amber-50'
                                            : 'border-amber-100/70 bg-white hover:border-amber-300'
                                        )}
                                      >
                                        <div className="text-xs text-stone-400 mb-2">
                                          块 {idx + 1}
                                          {Number.isFinite(pageIndex) ? ` · 页 ${Number(pageIndex) + 1}` : ''}
                                        </div>
                                        <div className="prose prose-stone max-w-none prose-headings:text-stone-900 prose-p:text-stone-700 prose-a:text-amber-700 prose-code:text-amber-700 prose-code:bg-amber-50 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-stone-900 prose-table:border-collapse prose-th:bg-amber-100/70 prose-th:border prose-th:border-amber-200 prose-th:p-2 prose-td:border prose-td:border-amber-200 prose-td:p-2">
                                          <MarkdownRenderer markdown={block.text} />
                                        </div>
                                      </button>
                                    )
                                  })}
                              </div>
                            ) : (
                              <div className="h-full overflow-y-auto p-6">
                                {previewMode === 'rendered' ? (
                                  <div className="flex gap-8">
                                    <div className="min-w-0 flex-1 prose prose-stone max-w-none prose-headings:text-stone-900 prose-p:text-stone-700 prose-a:text-amber-700 prose-code:text-amber-700 prose-code:bg-amber-50 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-stone-900 prose-table:border-collapse prose-th:bg-amber-100/70 prose-th:border prose-th:border-amber-200 prose-th:p-2 prose-td:border prose-td:border-amber-200 prose-td:p-2">
                                      <MarkdownRenderer markdown={activeMarkdown} autoScrollToHash />
                                    </div>
                                    {tocEnabled && (
                                      <aside className="hidden xl:block w-64 shrink-0">
                                        <div className="sticky top-6 max-h-[calc(100vh-220px)] overflow-y-auto rounded-xl border border-amber-100/70 bg-amber-50/40 p-3">
                                          <MarkdownToc markdown={activeMarkdown} />
                                        </div>
                                      </aside>
                                    )}
                                  </div>
                                ) : (
                                  <pre className="font-mono text-sm leading-relaxed text-stone-700 whitespace-pre-wrap bg-amber-50/70 p-6 rounded-xl border">
                                    {activeMarkdown}
                                  </pre>
                                )}
                              </div>
                            )}
                          </div>
                        </div>
                      )}
                    </div>
                  )}
                </div>

                {/* 底部操作栏 */}
                {activeFile.status === 'parsed' && activeMarkdown && (
                  <div className="px-6 py-4 border-t bg-gradient-to-r from-amber-50/70 to-white">
                    <div className="flex items-center justify-between">
                      <div className="text-sm text-stone-500">
                        {isEditing
                          ? '编辑完成后点击"保存修改"，然后提交到数据治理'
                          : '确认解析内容无误后，提交到数据治理工作台'
                        }
                      </div>
                      <div className="flex items-center gap-3">
                        {!isEditing && (
                          <Button
                            onClick={handleSubmitToGovernance}
                            className="gap-2 bg-amber-600 hover:bg-amber-700"
                          >
                            <ShieldCheck className="w-4 h-4" />
                            提交到数据治理
                            <ChevronRight className="w-4 h-4" />
                          </Button>
                        )}
                      </div>
                    </div>
                  </div>
                )}
              </>
            )}
          </div>
        </div>
      </main>
      </div>
    </div>
  )
}
