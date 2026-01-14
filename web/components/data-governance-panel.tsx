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
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { ROOT_FOLDER_ID, useParsedFiles } from '@/store/use-parsed-files-store'
import { cn, formatFileSize } from '@/lib/utils'
import { QualityChecker } from '@/components/data-governance/quality-checker'
import { DataCleaner } from '@/components/data-governance/data-cleaner'
import { DataAnnotator } from '@/components/data-governance/data-annotator'
import { DataClassifier } from '@/components/data-governance/data-classifier'
import { documentApi } from '@/lib/api-client'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { MarkdownRenderer } from '@/components/markdown/markdown-renderer'
import { MarkdownToc } from '@/components/markdown/markdown-toc'
import { DocumentFolderTree } from '@/components/document-library/folder-tree'
import { extractMarkdownHeadings } from '@/lib/markdown'
import { extractZipFiles, isZipFile } from '@/lib/zip'

// 工作流步骤
const WORKFLOW_STEPS = [
  { label: '上传文件', href: '/parsing', icon: Upload },
  { label: '解析文档', href: '/parsing', icon: FileText },
  { label: '数据治理', href: '/data-governance', icon: ShieldCheck },
  { label: '切块预览', href: '/chunk-preview', icon: Layers },
]

// 治理标签页
const GOVERNANCE_TABS = [
  { id: 'quality', label: '质量检测', icon: ScanLine, color: 'blue', desc: '检测文档质量与格式问题' },
  { id: 'clean', label: '智能清洗', icon: Wrench, color: 'green', desc: '修复格式错误与乱码' },
  { id: 'annotate', label: '数据标注', icon: Tag, color: 'purple', desc: '标记关键实体与敏感信息' },
  { id: 'classify', label: '分类归档', icon: FolderTree, color: 'orange', desc: '设置文档分类与标签' },
] as const

type GovernanceTab = typeof GOVERNANCE_TABS[number]['id']

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
  const { files, folders: libraryFolders, activeFolderId, createFolder, isLoaded, clearAll, addParsedFile, updateParsedFile, removeFile } = useParsedFiles()
  const { parserBackend } = useParserBackendPreference()

  // UI 状态
  const [activeTab, setActiveTab] = useState<GovernanceTab>('quality')
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null)
  const [viewMode, setViewMode] = useState<'edit' | 'preview' | 'original'>('preview')
  const [previewFormat, setPreviewFormat] = useState<'rendered' | 'markdown'>('rendered')
  const [isProcessing, setIsProcessing] = useState(false)
  const [isDragging, setIsDragging] = useState(false)
  const [uploading, setUploading] = useState(false)
  const uploadAbortRef = useRef<AbortController | null>(null)

  useEffect(() => {
    return () => {
      uploadAbortRef.current?.abort()
    }
  }, [])

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
      if (prev[file.id]) return prev
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

  const handleDeleteFile = useCallback(
    (fileId: string) => {
      const target = files.find((f) => f.id === fileId)
      if (!target) return

      const ok = window.confirm(`删除文件 “${target.filename}” ？`)
      if (!ok) return

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
      <div className="flex-1 flex flex-col bg-white min-h-0">
        <header className="flex-shrink-0 bg-white border-b border-gray-200 px-6 py-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="w-11 h-11 bg-gradient-to-br from-sky-500 to-blue-600 rounded-xl flex items-center justify-center shadow-lg shadow-sky-200">
                <ShieldCheck className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-gray-900">数据治理工作台</h1>
                <p className="text-sm text-gray-500">
                  上传文档进行质量检测与清洗
                </p>
              </div>
            </div>
          </div>
        </header>
        
        <div className="flex-1 flex items-center justify-center bg-gray-50 p-6">
          <div 
            className={cn(
              "w-full max-w-2xl border-2 border-dashed rounded-3xl p-12 text-center transition-all duration-300",
              isDragging 
                ? "border-sky-500 bg-sky-50 scale-[1.02]" 
                : "border-gray-300 bg-white hover:border-sky-400 hover:shadow-lg"
            )}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            onDrop={handleDrop}
          >
            <div className="w-24 h-24 mx-auto mb-6 bg-sky-100 rounded-full flex items-center justify-center">
              {uploading ? (
                <Sparkles className="w-10 h-10 text-sky-600 animate-spin" />
              ) : (
                <Upload className="w-10 h-10 text-sky-600" />
              )}
            </div>
            <h3 className="text-2xl font-bold text-gray-900 mb-3">
              {uploading ? '正在解析文档...' : '上传文档开始治理'}
            </h3>
            <p className="text-gray-500 mb-8 max-w-md mx-auto text-lg">
              {uploading 
                ? 'AI 正在分析文档结构并提取内容，请稍候...' 
                : '拖放文件到此处，或点击下方按钮选择文件。支持 PDF, Word, Excel, TXT, MD, ZIP。'
              }
            </p>

            <div className="max-w-md mx-auto mb-8 text-left">
              <div className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-2">文档库目录</div>
              <div className="bg-gray-50 border border-gray-200 rounded-2xl p-3 max-h-56 overflow-y-auto">
                <DocumentFolderTree />
              </div>
            </div>
            
            <div className="flex justify-center gap-4">
              <div className="relative">
                <input
                  type="file"
                  multiple
                  accept=".pdf,.txt,.md,.doc,.docx,.xls,.xlsx,.csv,.html,.json,.zip"
                  className="hidden"
                  id="file-upload"
                  onChange={handleFileSelect}
                  disabled={uploading}
                />
                <label 
                  htmlFor="file-upload"
                  className={cn(
                    "flex items-center gap-2 px-8 py-4 bg-gradient-to-r from-sky-500 to-blue-600 text-white rounded-xl font-medium shadow-lg hover:shadow-xl hover:-translate-y-0.5 transition-all cursor-pointer",
                    uploading && "opacity-50 cursor-not-allowed"
                  )}
                >
                  <Upload className="w-5 h-5" />
                  选择文件
                </label>
              </div>
              {uploading && (
                <Button
                  type="button"
                  variant="outline"
                  onClick={cancelUploadAndParse}
                  className="flex items-center gap-2 px-8 py-4 rounded-xl"
                >
                  <X className="w-5 h-5" />
                  取消
                </Button>
              )}
            </div>
            
            <div className="mt-8 flex items-center justify-center gap-8 text-sm text-gray-400">
              <span className="flex items-center gap-2">
                <FileText className="w-4 h-4" /> 智能解析
              </span>
              <span className="flex items-center gap-2">
                <ShieldCheck className="w-4 h-4" /> 质量检测
              </span>
              <span className="flex items-center gap-2">
                <Sparkles className="w-4 h-4" /> 自动清洗
              </span>
            </div>
          </div>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col bg-white min-h-0">
      {/* 顶部标题栏 */}
      <header className="flex-shrink-0 bg-white border-b border-gray-200 px-6 py-4 h-16 flex items-center justify-between z-20 shadow-sm relative">
        <div className="flex items-center gap-4">
          <div className="w-9 h-9 bg-gradient-to-br from-sky-500 to-blue-600 rounded-lg flex items-center justify-center shadow-lg shadow-sky-200/50">
            <ShieldCheck className="w-5 h-5 text-white" />
          </div>
          <div>
            <h1 className="text-lg font-bold text-gray-900 leading-tight">数据治理工作台</h1>
            <p className="text-xs text-gray-500 leading-none mt-1">
              Data Governance Workbench
            </p>
          </div>
        </div>

        {/* 顶部右侧操作栏 - 移至顶部释放空间 */}
        <div className="flex items-center gap-3">
           <Button
              variant="outline"
              size="sm"
              onClick={handleReset}
              disabled={!governanceState || !governanceState.isModified}
              className="gap-1.5 h-8 text-xs bg-white hover:bg-gray-50"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              重置
            </Button>
            <Button
              size="sm"
              onClick={handleSave}
              disabled={!governanceState}
              className="gap-2 h-8 text-xs bg-gradient-to-r from-sky-600 to-blue-600 hover:from-sky-700 hover:to-blue-700 border-0 shadow-sm shadow-sky-200"
            >
              <Save className="w-3.5 h-3.5" />
              保存
            </Button>
            <div className="w-px h-4 bg-gray-300 mx-1" />
            <Button
              variant="default"
              size="sm"
              onClick={handlePushToChunkPreview}
              disabled={!isLoaded || files.length === 0}
              className="gap-2 h-8 text-xs bg-slate-800 hover:bg-slate-900 text-white shadow-sm"
            >
              <Layers className="w-3.5 h-3.5" />
              推送切块预览
            </Button>
        </div>
      </header>

      <div className="flex-1 flex overflow-hidden min-h-0 relative bg-slate-50">
        {/* 左侧文件列表 */}
        <aside
          ref={sidebarRef}
          className={cn(
            "group/sidebar relative flex flex-col flex-shrink-0 bg-white border-r border-gray-200 transition-all duration-300 ease-in-out z-10",
            isSidebarCollapsed ? "w-0 border-r-0" : ""
          )}
          style={{ width: isSidebarCollapsed ? 0 : sidebarWidth }}
        >
          {/* 折叠/展开按钮 */}
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
            {/* 搜索栏 */}
            <div className="p-3 border-b border-gray-100">
               <div className="relative">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-gray-400" />
                <input
                  type="text"
                  placeholder="搜索文件..."
                  className="w-full pl-9 pr-3 py-1.5 text-xs bg-gray-50 border border-transparent rounded-lg focus:bg-white focus:outline-none focus:ring-1 focus:ring-sky-500 focus:border-sky-500 transition-all"
                />
              </div>
            </div>

             {/* 文件目录树 - 可折叠区域 */}
            <div className="px-3 pt-2 pb-1">
              <div className="max-h-40 overflow-y-auto rounded-lg bg-gray-50 p-2">
                 <DocumentFolderTree />
              </div>
            </div>

            <div className="flex items-center justify-between px-4 py-2 mt-2">
              <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider">
                文件列表 ({visibleFiles.length})
              </h3>
            </div>

            <div className="flex-1 overflow-y-auto px-3 pb-3 space-y-2">
              {visibleFiles.length === 0 ? (
                <div className="text-xs text-gray-400 text-center py-8">该目录暂无文件</div>
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
                      "w-full text-left p-4 rounded-xl border transition-all duration-200 cursor-pointer group relative",
                      selectedFileId === file.id
                        ? "bg-sky-50/50 border-sky-200 shadow-md ring-1 ring-sky-100"
                        : "bg-white border-slate-100 hover:border-sky-200 hover:shadow-sm"
                    )}
                  >
                    <div className="flex items-start gap-4">
                      {/* File Icon */}
                      <div className={cn(
                        "w-12 h-12 rounded-xl flex items-center justify-center flex-shrink-0 text-[10px] font-bold uppercase tracking-wider shadow-sm border transition-colors",
                         selectedFileId === file.id 
                          ? "bg-sky-100 text-sky-700 border-sky-200" 
                          : "bg-slate-50 text-slate-400 border-slate-100 group-hover:bg-sky-50 group-hover:text-sky-600 group-hover:border-sky-100"
                      )}>
                        {file.fileType}
                      </div>
                      
                      <div className="flex-1 min-w-0">
                        {/* Row 1: Filename & Score */}
                        <div className="flex items-center justify-between mb-1">
                          <div className={cn(
                            "text-sm font-bold truncate mr-2",
                            selectedFileId === file.id ? "text-sky-900" : "text-slate-700"
                          )}>
                            {file.filename}
                          </div>
                          {score > 0 ? (
                            <span className={cn(
                              "flex-shrink-0 text-[10px] px-2 py-0.5 rounded-full font-bold shadow-sm border",
                              score >= 80 ? "bg-emerald-50 text-emerald-700 border-emerald-100" :
                              score >= 60 ? "bg-amber-50 text-amber-700 border-amber-100" :
                              "bg-rose-50 text-rose-700 border-rose-100"
                            )}>
                              {score}分
                            </span>
                          ) : (
                            <span className="flex-shrink-0 text-[10px] text-slate-400 bg-slate-50 px-2 py-0.5 rounded-full border border-slate-100 font-medium">未检测</span>
                          )}
                        </div>

                        {/* Row 2: Metadata (Size & Date) */}
                        <div className="flex items-center gap-2 text-[10px] text-slate-400 mb-2 font-medium">
                           <span>{formatFileSize(file.fileSize)}</span>
                           <span className="text-slate-200">|</span>
                           <span>
                             {file.parsedAt ? new Date(file.parsedAt).toLocaleDateString([], {
                               year: 'numeric',
                               month: '2-digit',
                               day: '2-digit'
                             }) : ''}
                           </span>
                           <span>
                             {file.parsedAt ? new Date(file.parsedAt).toLocaleTimeString([], {
                               hour: '2-digit',
                               minute: '2-digit'
                             }) : ''}
                           </span>
                        </div>

                        {/* Row 3: Badges & Actions */}
                        <div className="flex items-center justify-between h-5">
                          <div className="flex items-center gap-2">
                              {state?.isModified && (
                                <span className="text-[9px] text-indigo-600 flex items-center gap-1 bg-indigo-50 px-1.5 py-0.5 rounded border border-indigo-100 font-bold">
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
                            onClick={(e) => {
                              e.stopPropagation()
                              handleDeleteFile(file.id)
                            }}
                            className="opacity-0 group-hover:opacity-100 p-1 -mr-1 text-slate-400 hover:text-rose-600 hover:bg-rose-50 rounded transition-all"
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

            {/* 底部统计栏 (原顶部统计栏) */}
            <div className="mt-auto border-t border-gray-100 bg-gray-50/50 p-3 space-y-2">
               <div className="grid grid-cols-2 gap-2">
                 <div className="bg-white p-2 rounded-lg border border-gray-100 shadow-sm">
                    <div className="text-[10px] text-gray-400 mb-0.5">完成度</div>
                    <div className="text-sm font-bold text-gray-900 flex items-baseline gap-1">
                      {stats.completedFiles} <span className="text-gray-400 font-normal text-xs">/ {stats.totalFiles}</span>
                    </div>
                 </div>
                 <div className="bg-white p-2 rounded-lg border border-gray-100 shadow-sm">
                    <div className="text-[10px] text-gray-400 mb-0.5">平均分</div>
                    <div className="text-sm font-bold text-gray-900">
                      {stats.avgScore > 0 ? stats.avgScore.toFixed(1) : '-'}
                    </div>
                 </div>
               </div>
            </div>
          </div>
          
          {/* 拖拽手柄 */}
          <div
            className={cn(
              "absolute right-0 top-0 w-1 h-full cursor-col-resize hover:bg-sky-400 active:bg-sky-600 z-20 transition-colors opacity-0 hover:opacity-100",
              isResizing && "bg-sky-600 opacity-100 w-1"
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
                 <div className="absolute top-4 left-1/2 -translate-x-1/2 z-20 flex items-center bg-white/90 backdrop-blur-sm border border-gray-200/60 shadow-sm rounded-full px-2 py-1 gap-1 transition-all hover:shadow-md">
                     {/* 视图切换 */}
                     <div className="flex items-center bg-gray-100/50 rounded-full p-0.5">
                        <button
                          onClick={() => setViewMode('preview')}
                          className={cn(
                            "px-3 py-1 rounded-full text-xs font-medium transition-all",
                            viewMode === 'preview' ? "bg-white text-sky-700 shadow-sm" : "text-gray-500 hover:text-gray-700"
                          )}
                        >
                          预览
                        </button>
                         <button
                          onClick={() => setViewMode('edit')}
                          className={cn(
                            "px-3 py-1 rounded-full text-xs font-medium transition-all",
                            viewMode === 'edit' ? "bg-white text-sky-700 shadow-sm" : "text-gray-500 hover:text-gray-700"
                          )}
                        >
                          编辑
                        </button>
                        <button
                          onClick={() => setViewMode('original')}
                          className={cn(
                            "px-3 py-1 rounded-full text-xs font-medium transition-all",
                            viewMode === 'original' ? "bg-white text-sky-700 shadow-sm" : "text-gray-500 hover:text-gray-700"
                          )}
                        >
                          对比
                        </button>
                     </div>
                     
                     <div className="w-px h-3 bg-gray-300 mx-1" />

                     <Button variant="ghost" size="icon" className="h-7 w-7 rounded-full text-gray-500" onClick={() => setPreviewFormat(prev => prev === 'rendered' ? 'markdown' : 'rendered')} title={previewFormat === 'rendered' ? "查看源码" : "查看渲染"}>
                         {previewFormat === 'rendered' ? <Hash className="w-3.5 h-3.5" /> : <Eye className="w-3.5 h-3.5" />}
                     </Button>
                 </div>
                 
                 {/* 左侧收起按钮 (如果左侧收起) */}
                  {isSidebarCollapsed && (
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setIsSidebarCollapsed(false)}
                      className="absolute left-4 top-4 z-20 h-8 w-8 bg-white border border-gray-200 shadow-sm rounded-lg text-gray-500 hover:text-sky-600"
                    >
                      <PanelRightOpen className="w-4 h-4" />
                    </Button>
                  )}

                  {/* 右侧收起按钮 (如果右侧收起) */}
                  {isPanelCollapsed && (
                    <Button
                      variant="ghost"
                      size="icon"
                      onClick={() => setIsPanelCollapsed(false)}
                      className="absolute right-4 top-4 z-20 h-8 w-8 bg-white border border-gray-200 shadow-sm rounded-lg text-gray-500 hover:text-sky-600"
                    >
                      <PanelRightClose className="w-4 h-4 rotate-180" />
                    </Button>
                  )}

                 {/* 内容区域 */}
                 <div className="flex-1 overflow-y-auto p-4 md:p-8 custom-scrollbar">
                    <div className={cn(
                      "mx-auto transition-all duration-300 ease-out",
                      viewMode === 'edit' ? 'max-w-full' : 'max-w-4xl'
                    )}>
                       {/* 纸张效果容器 */}
                       <div className={cn(
                         "bg-white min-h-[800px] shadow-sm border border-slate-200/60 rounded-xl overflow-hidden relative",
                          viewMode === 'edit' ? "h-[calc(100vh-140px)] border-0 shadow-none bg-transparent" : "p-10 md:p-14"
                       )}>
                          {/* 治理状态水印/徽章 */}
                          {viewMode !== 'edit' && governanceState.isModified && (
                             <div className="absolute top-0 right-0 p-4">
                                <span className="bg-purple-50 text-purple-700 border border-purple-100 text-xs px-2 py-1 rounded-md font-medium shadow-sm">
                                  已修改
                                </span>
                             </div>
                          )}

                          {viewMode === 'edit' ? (
                            <div className="grid grid-cols-2 gap-4 h-full">
                               {/* 编辑模式：左侧预览 */}
                               <div className="flex flex-col bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden h-full">
                                  <div className="px-4 py-2 bg-slate-50 border-b border-slate-200 text-xs font-semibold text-slate-500">
                                     实时预览
                                  </div>
                                  <div className="flex-1 overflow-y-auto p-6">
                                     <MarkdownRenderer markdown={displayContent || ''} />
                                  </div>
                               </div>
                               {/* 编辑模式：右侧源码 */}
                               <div className="flex flex-col bg-white rounded-xl border border-slate-200 shadow-sm overflow-hidden h-full">
                                  <div className="px-4 py-2 bg-slate-50 border-b border-slate-200 text-xs font-semibold text-slate-500">
                                     源码编辑
                                  </div>
                                  <textarea
                                    value={displayContent}
                                    onChange={(e) => handleManualEdit(e.target.value)}
                                    className="flex-1 w-full p-6 resize-none outline-none font-mono text-sm leading-relaxed text-slate-800"
                                    spellCheck={false}
                                  />
                               </div>
                            </div>
                          ) : (
                             // 预览模式
                             previewFormat === 'rendered' ? (
                                <div className="prose prose-slate max-w-none prose-headings:text-slate-900 prose-p:text-slate-700 prose-a:text-sky-700">
                                  <MarkdownRenderer markdown={displayContent || ''} />
                                </div>
                             ) : (
                                <pre className="font-mono text-sm leading-relaxed whitespace-pre-wrap break-words text-slate-800">
                                  {displayContent || ''}
                                </pre>
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
                  "group/panel relative flex-shrink-0 border-l border-gray-200 bg-white flex flex-col transition-all duration-300 ease-in-out z-10 shadow-xl",
                  isPanelCollapsed ? "w-0 border-l-0 translate-x-full" : ""
                )}
                style={{ width: isPanelCollapsed ? 0 : panelWidth }}
              >
                 {/* 工具面板头部：治理阶段选择 */}
                 <div className="flex-shrink-0 p-4 border-b border-gray-100 bg-white">
                    <div className="flex items-center justify-between mb-4">
                       <h2 className="text-sm font-bold text-gray-900">治理工具箱</h2>
                       <Button
                          variant="ghost"
                          size="icon"
                          className="h-6 w-6 text-gray-400"
                          onClick={() => setIsPanelCollapsed(true)}
                       >
                         <PanelRightClose className="w-4 h-4 rotate-180" />
                       </Button>
                    </div>
                    
                    {/* 新的 Tab 选择器 */}
                    <div className="grid grid-cols-4 gap-1 p-1 bg-gray-100/80 rounded-lg">
                       {GOVERNANCE_TABS.map((tab) => {
                          const Icon = tab.icon
                          const isActive = activeTab === tab.id
                          return (
                            <button
                              key={tab.id}
                              onClick={() => setActiveTab(tab.id)}
                              className={cn(
                                "flex flex-col items-center justify-center py-2 px-1 rounded-md transition-all duration-200 relative",
                                isActive 
                                  ? "bg-white text-sky-600 shadow-sm ring-1 ring-black/5" 
                                  : "text-gray-500 hover:text-gray-700 hover:bg-gray-200/50"
                              )}
                              title={tab.label}
                            >
                               <Icon className={cn("w-4 h-4 mb-1", isActive ? `text-${tab.color}-500` : "")} />
                               <span className="text-[10px] font-medium scale-90">{tab.label}</span>
                               {/* 状态点 */}
                               {tab.id === 'clean' && governanceState.isModified && (
                                  <span className="absolute top-1.5 right-1.5 w-1.5 h-1.5 bg-purple-500 rounded-full ring-1 ring-white" />
                               )}
                            </button>
                          )
                       })}
                    </div>
                    
                    {/* 当前工具描述 */}
                    <div className="mt-3 text-xs text-gray-500 bg-blue-50/50 p-2 rounded border border-blue-100/50 flex items-start gap-2">
                       <Info className="w-3.5 h-3.5 text-blue-500 mt-0.5 flex-shrink-0" />
                       {GOVERNANCE_TABS.find(t => t.id === activeTab)?.desc}
                    </div>
                 </div>

                 {/* 工具内容区 */}
                 <div className="flex-1 overflow-y-auto bg-gray-50/30">
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
                      "absolute left-0 top-0 w-1 h-full cursor-col-resize hover:bg-sky-400 active:bg-sky-600 z-20 transition-colors opacity-0 hover:opacity-100",
                      isPanelResizing && "bg-sky-600 opacity-100 w-1"
                    )}
                    onMouseDown={startPanelResizing}
                  />
              </div>
            </>
          ) : (
            // 空状态占位
            <div className="flex-1 flex flex-col items-center justify-center bg-gray-50/30">
              <div className="w-24 h-24 bg-gray-100 rounded-full flex items-center justify-center mb-6">
                <FileSearch className="w-10 h-10 text-gray-400" />
              </div>
              <h3 className="text-xl font-medium text-gray-900 mb-2">选择文件开始治理</h3>
              <p className="text-gray-500 max-w-sm text-center">
                从左侧列表选择一个文件，使用右侧工具箱进行质量检测、清洗与标注。
              </p>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
