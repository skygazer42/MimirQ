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
import { DocumentFolderTree } from '@/components/document-library/folder-tree'
import { extractZipFiles, isZipFile } from '@/lib/zip'
import { PdfViewer } from '@/components/parsing/pdf-viewer'
import { extractBlocksFromMarkdown, ParsingBlock } from '@/lib/parsing-positions'
import { toast } from 'sonner'

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
  const fileInputRef = useRef<HTMLInputElement>(null)
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
      fileInputRef.current?.click()
    },
    [setActiveFolderId]
  )

  // 生成唯一 ID
  const generateId = () => Math.random().toString(36).substring(2, 15)

  // 添加文件（支持 .zip 批量解压）
  const addFiles = useCallback(
    async (incomingFiles: File[], baseFolderIdOverride?: string) => {
      const defaultLabel = getParserLabel(parserBackend)
      const baseFolderId = baseFolderIdOverride || activeFolderId || ROOT_FOLDER_ID

      const folderIdByKey = new Map<string, string>()
      for (const f of folders) {
        folderIdByKey.set(`${f.parentId || ROOT_FOLDER_ID}::${f.name}`, f.id)
      }

      const getOrCreateFolder = (parentId: string, name: string) => {
        const trimmed = name.trim()
        const key = `${parentId}::${trimmed}`
        const cached = folderIdByKey.get(key)
        if (cached) return cached

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

  const visibleQueueFiles = useMemo(() => {
    if (!activeFolderId || activeFolderId === ROOT_FOLDER_ID) return files

    const childrenByParentId = new Map<string, string[]>()
    for (const folder of folders) {
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
  }, [files, activeFolderId, folders])

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

  // 计算统计数据
  const pendingCount = visibleQueueFiles.filter((f) => f.status === 'pending').length
  const parsingCount = visibleQueueFiles.filter((f) => f.status === 'parsing').length
  const parsedCount = visibleQueueFiles.filter((f) => f.status === 'parsed').length
  const parseableCount = visibleQueueFiles.filter((f) => f.status === 'pending' || f.status === 'error').length
  const parseAllLabel = activeFolderId && activeFolderId !== ROOT_FOLDER_ID ? '解析当前目录' : '全部解析'
  const queueCountLabel = visibleQueueFiles.length === 0 ? '0' : `${parsedCount}/${visibleQueueFiles.length}`

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <Navbar />

      <main className="flex-1 flex flex-col overflow-hidden min-h-0">
        {/* 顶部标题栏 */}
        <header className="flex-shrink-0 bg-white border-b border-gray-200 px-6 py-4 h-16 flex items-center justify-between z-20 shadow-sm relative">
          <div className="flex items-center gap-4">
            <div className="w-9 h-9 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-lg flex items-center justify-center shadow-lg shadow-indigo-200/50">
              <Sparkles className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-gray-900 leading-tight">文档解析工作台</h1>
              <p className="text-xs text-gray-500 leading-none mt-1">
                上传文件并转换为 Markdown 格式，为数据治理做准备
              </p>
            </div>
          </div>
        </header>

        <div className="flex-1 flex overflow-hidden min-h-0">
          {/* 左侧：文件列表面板 */}
          <aside
            className={cn(
              "group/sidebar relative flex flex-col flex-shrink-0 bg-white border-r border-gray-200 transition-all duration-300 ease-in-out z-10",
              isSidebarCollapsed ? "w-0 border-r-0" : "w-80"
            )}
            style={{ width: isSidebarCollapsed ? 0 : 320 }}
          >
            {/* Toggle Button */}
            <Button
              variant="ghost"
              size="icon"
              className={cn(
                "absolute -right-3 top-3 z-30 h-6 w-6 rounded-full border border-gray-200 bg-white shadow-sm hover:bg-gray-50 text-gray-400 hover:text-gray-600 transition-opacity opacity-0 group-hover/sidebar:opacity-100",
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
                <span className="text-xs font-semibold text-gray-500 uppercase tracking-wider">解析方式</span>
              </div>
              <ParserDropdown
                value={parserBackend}
                onChange={setParserBackend}
              />
            </div>

            {/* 操作栏: 一键解析 */}
            {parseableCount > 0 && (
               <div className="px-4 py-2 border-b bg-amber-50/50 flex items-center justify-between transition-all">
                  <span className="text-xs text-amber-700 font-medium">{parseableCount} 个文件待解析</span>
                  <Button variant="ghost" size="sm" onClick={parseAllPending} className="h-6 text-xs gap-1 text-amber-700 hover:text-amber-800 hover:bg-amber-100">
                    <Zap className="w-3 h-3" />
                    全部解析
                  </Button>
               </div>
            )}

            {/* 文档库目录 (Unified Tree) */}
            <div className="flex-1 overflow-y-auto p-4">
                <div className="mb-2 px-1 text-xs text-gray-400 flex items-center gap-1 truncate">
                  <FolderOpen className="w-3 h-3" />
                  {activeFolderPathLabel}
                </div>
                <DocumentFolderTree
                  onRequestUpload={requestUploadToFolder}
                  fileItems={files.map((f) => ({
                    id: f.id,
                    name: f.name,
                    folderId: f.folderId,
                    sourcePath: f.sourcePath,
                    status: f.status,
                    error: f.error
                  }))}
                  showFiles="expanded"
                  onSelectFile={(fileId) => setActiveFileId(fileId)}
                  className="pb-10"
                />
            </div>

            {/* 隐藏的文件上传 Input (用于文件夹上传) */}
            <input
              ref={fileInputRef}
              type="file"
              multiple
              accept=".pdf,.txt,.md,.doc,.docx,.xls,.xlsx,.csv,.html,.json,.zip"
              className="hidden"
              onChange={handleFileSelect}
            />

            {/* 底部统计 */}
            {visibleQueueFiles.length > 0 && (
              <div className="p-4 border-t bg-gray-50">
                <div className="flex items-center justify-around text-xs text-gray-500">
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
          <div className="flex-1 flex flex-col bg-white overflow-hidden min-h-0">
            {!activeFile ? (
              // 空状态
              <div className="flex-1 flex items-center justify-center">
                <div className="text-center max-w-md">
                  <div className="w-20 h-20 mx-auto mb-4 bg-gradient-to-br from-gray-100 to-gray-50 rounded-2xl flex items-center justify-center">
                    <FileText className="w-10 h-10 text-gray-300" />
                  </div>
                  <h3 className="text-lg font-medium text-gray-700 mb-2">选择文件开始</h3>
                  <p className="text-gray-400 text-sm">
                    从左侧上传或选择文件，系统将使用 AI 智能解析文档结构
                  </p>
                </div>
              </div>
            ) : (
              <>
                {/* 统计卡片区 - 解析完成后显示 */}
                {activeFile.status === 'parsed' && activeFile.stats && (
                  <div className="px-6 py-4 border-b bg-gradient-to-r from-gray-50 to-white">
                    <StatsGrid>
                      <StatCard
                        icon={FileText}
                        label="字符数"
                        value={activeFile.stats.charCount.toLocaleString()}
                        color="blue"
                      />
                      <StatCard
                        icon={FileStack}
                        label="行数"
                        value={activeFile.stats.lineCount.toLocaleString()}
                        color="purple"
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
                        color="orange"
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
                <div className="flex items-center justify-between px-6 py-3 border-b bg-gray-50">
                  <div className="flex items-center gap-3">
                    <span className="font-medium text-gray-900 truncate max-w-[200px]">
                      {activeFile.file.name}
                    </span>
                    <span className="text-xs text-gray-400 bg-gray-200 px-2 py-0.5 rounded">
                      {activeFile.parserLabel}
                    </span>
                    {activeFile.runs && activeFile.runs.length > 1 && (
                      <select
                        value={activeRun?.id || ''}
                        onChange={(e) => handleSelectRun(e.target.value)}
                        className="text-xs border border-gray-200 rounded px-2 py-1 bg-white text-gray-600"
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
                              className="gap-1.5 text-gray-500"
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
                              <div className="flex items-center bg-gray-200 rounded-lg p-0.5 mr-2">
                                <button
                                  onClick={() => setRightPanelMode('blocks')}
                                  className={cn(
                                    'px-3 py-1.5 text-xs rounded-md transition-all flex items-center gap-1',
                                    rightPanelMode === 'blocks'
                                      ? 'bg-white text-gray-900 shadow-sm'
                                      : 'text-gray-500 hover:text-gray-700'
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
                                      ? 'bg-white text-gray-900 shadow-sm'
                                      : 'text-gray-500 hover:text-gray-700'
                                  )}
                                >
                                  <FileText className="w-3.5 h-3.5" />
                                  Markdown
                                </button>
                              </div>
                            )}

                            {rightPanelMode === 'markdown' && (
                              <div className="flex items-center bg-gray-200 rounded-lg p-0.5 mr-2">
                                <button
                                  onClick={() => setPreviewMode('rendered')}
                                  className={cn(
                                    'px-3 py-1.5 text-xs rounded-md transition-all flex items-center gap-1',
                                    previewMode === 'rendered'
                                      ? 'bg-white text-gray-900 shadow-sm'
                                      : 'text-gray-500 hover:text-gray-700'
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
                                      ? 'bg-white text-gray-900 shadow-sm'
                                      : 'text-gray-500 hover:text-gray-700'
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
                      <Button onClick={() => parseFile(activeFile.id)} className="gap-2 bg-indigo-600 hover:bg-indigo-700">
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
                        <div className="w-16 h-16 mx-auto mb-4 bg-indigo-100 rounded-xl flex items-center justify-center">
                          <Sparkles className="w-8 h-8 text-indigo-500" />
                        </div>
                        <p className="text-gray-600 mb-2">准备就绪</p>
                        <p className="text-gray-400 text-sm">
                          点击上方按钮，使用 {activeFile.parserLabel} 解析
                        </p>
                      </div>
                    </div>
                  )}

                  {activeFile.status === 'parsing' && (
                    <div className="flex items-center justify-center h-full">
                      <div className="text-center">
                        <div className="relative">
                          <Loader2 className="w-12 h-12 animate-spin text-indigo-500 mx-auto" />
                          <div className="absolute inset-0 flex items-center justify-center">
                            <span className="text-xs font-medium text-indigo-600">
                              {Math.round(activeFile.progress || 0)}%
                            </span>
                          </div>
                        </div>
                        <p className="text-gray-600 mt-4">正在解析...</p>
                        <p className="text-gray-400 text-sm mt-1">{activeFile.parserLabel}</p>
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
                        <p className="text-gray-500 text-sm">{activeFile.error}</p>
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
                            className="w-full min-h-[500px] p-4 font-mono text-sm leading-relaxed text-gray-700 whitespace-pre-wrap bg-amber-50 border border-amber-200 rounded-xl resize-none focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent"
                            placeholder="在此编辑内容..."
                            autoFocus
                          />
                        </div>
                      ) : (
                        <div className="flex h-full min-h-[520px] flex-col lg:flex-row">
                          {isPdf ? (
                            <div className="w-full lg:w-1/2 border-b lg:border-b-0 lg:border-r border-gray-200 bg-gray-50">
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
                                            : 'border-gray-200 bg-white hover:border-sky-300'
                                        )}
                                      >
                                        <div className="text-xs text-gray-400 mb-2">
                                          块 {idx + 1}
                                          {Number.isFinite(pageIndex) ? ` · 页 ${Number(pageIndex) + 1}` : ''}
                                        </div>
                                        <div className="prose prose-slate max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-a:text-indigo-600 prose-code:text-pink-600 prose-code:bg-pink-50 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-gray-900 prose-table:border-collapse prose-th:bg-gray-100 prose-th:border prose-th:border-gray-300 prose-th:p-2 prose-td:border prose-td:border-gray-300 prose-td:p-2">
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
                                    <div className="min-w-0 flex-1 prose prose-slate max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-a:text-indigo-600 prose-code:text-pink-600 prose-code:bg-pink-50 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-gray-900 prose-table:border-collapse prose-th:bg-gray-100 prose-th:border prose-th:border-gray-300 prose-th:p-2 prose-td:border prose-td:border-gray-300 prose-td:p-2">
                                      <MarkdownRenderer markdown={activeMarkdown} autoScrollToHash />
                                    </div>
                                    {tocEnabled && (
                                      <aside className="hidden xl:block w-64 shrink-0">
                                        <div className="sticky top-6 max-h-[calc(100vh-220px)] overflow-y-auto rounded-xl border border-slate-200 bg-white/70 p-3">
                                          <MarkdownToc markdown={activeMarkdown} />
                                        </div>
                                      </aside>
                                    )}
                                  </div>
                                ) : (
                                  <pre className="font-mono text-sm leading-relaxed text-gray-700 whitespace-pre-wrap bg-gray-50 p-6 rounded-xl border">
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
                  <div className="px-6 py-4 border-t bg-gradient-to-r from-gray-50 to-white">
                    <div className="flex items-center justify-between">
                      <div className="text-sm text-gray-500">
                        {isEditing
                          ? '编辑完成后点击"保存修改"，然后提交到数据治理'
                          : '确认解析内容无误后，提交到数据治理工作台'
                        }
                      </div>
                      <div className="flex items-center gap-3">
                        {!isEditing && (
                          <Button
                            onClick={handleSubmitToGovernance}
                            className="gap-2 bg-indigo-600 hover:bg-indigo-700"
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
  )
}
