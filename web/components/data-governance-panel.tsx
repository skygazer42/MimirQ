/**
 * 数据治理工作台组件
 * 功能：质量检测、智能清洗、数据标注、分类归档
 */
'use client'

import { useState, useCallback, useMemo, useEffect } from 'react'
import {
  ShieldCheck,
  Sparkles,
  Tag,
  FolderTree,
  FileText,
  Upload,
  ChevronRight,
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
} from 'lucide-react'
import { Button } from '@/components/ui/button'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { ROOT_FOLDER_ID, useParsedFiles } from '@/store/use-parsed-files-store'
import { cn } from '@/lib/utils'
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
  { id: 'quality', label: '质量检测', icon: ScanLine, color: 'blue' },
  { id: 'clean', label: '智能清洗', icon: Wrench, color: 'green' },
  { id: 'annotate', label: '数据标注', icon: Tag, color: 'purple' },
  { id: 'classify', label: '分类归档', icon: FolderTree, color: 'orange' },
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

  // 文件治理状态
  const [governanceStates, setGovernanceStates] = useState<Record<string, FileGovernanceState>>({})

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
        const data = await documentApi.preview(file, parserBackend)

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
      console.error('Failed to parse file:', error)
      toast.error('解析失败，请稍后重试')
    } finally {
      setUploading(false)
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
            {/* 步骤导航保持一致，但处于初始状态 */}
            <div className="hidden md:flex items-center gap-2 opacity-50 pointer-events-none">
                {/* 简化显示 */}
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
      <header className="flex-shrink-0 bg-white border-b border-gray-200 px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="w-11 h-11 bg-gradient-to-br from-sky-500 to-blue-600 rounded-xl flex items-center justify-center shadow-lg shadow-sky-200">
              <ShieldCheck className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-xl font-bold text-gray-900">数据治理工作台</h1>
              <p className="text-sm text-gray-500">
                质量检测 · 智能清洗 · 数据标注 · 分类归档
              </p>
            </div>
          </div>

          {/* 步骤导航 */}
          <div className="hidden md:flex items-center gap-2">
            {WORKFLOW_STEPS.map((step, idx) => {
              const Icon = step.icon
              const isActive = step.href === '/data-governance'
              const isPast = idx < WORKFLOW_STEPS.findIndex((s) => s.href === '/data-governance')

              return (
                <div key={step.href} className="flex items-center">
                  {idx > 0 && (
                    <ChevronRight className={cn(
                      "w-4 h-4 mx-1",
                      isPast ? "text-green-500" : "text-gray-300"
                    )} />
                  )}
                  <button
                    onClick={() => router.push(step.href)}
                    className={cn(
                      "flex items-center gap-2 px-3 py-1.5 rounded-lg text-sm transition-all",
                      isActive
                        ? "bg-sky-100 text-sky-700 font-medium"
                        : isPast
                          ? "bg-green-50 text-green-600 hover:bg-green-100"
                          : "text-gray-400 hover:bg-gray-100"
                    )}
                  >
                    <Icon className="w-4 h-4" />
                    <span>{step.label}</span>
                  </button>
                </div>
              )
            })}
          </div>
        </div>
      </header>

      {/* 统计卡片 */}
      <div className="flex-shrink-0 px-6 py-4 bg-gradient-to-r from-gray-50 to-white border-b border-gray-100">
        <div className="flex items-center gap-6">
          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-blue-100 rounded-lg flex items-center justify-center">
              <FileText className="w-4 h-4 text-blue-600" />
            </div>
            <div>
              <div className="text-xs text-gray-400">文件总数</div>
              <div className="text-lg font-bold text-gray-900">{stats.totalFiles}</div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-green-100 rounded-lg flex items-center justify-center">
              <CheckCircle className="w-4 h-4 text-green-600" />
            </div>
            <div>
              <div className="text-xs text-gray-400">已检测</div>
              <div className="text-lg font-bold text-gray-900">{stats.completedFiles}</div>
            </div>
          </div>

          <div className="flex items-center gap-2">
            <div className="w-8 h-8 bg-purple-100 rounded-lg flex items-center justify-center">
              <Eraser className="w-4 h-4 text-purple-600" />
            </div>
            <div>
              <div className="text-xs text-gray-400">已修改</div>
              <div className="text-lg font-bold text-gray-900">{stats.modifiedFiles}</div>
            </div>
          </div>

          {stats.avgScore > 0 && (
            <div className="flex items-center gap-2">
              <div className="w-8 h-8 bg-sky-100 rounded-lg flex items-center justify-center">
                <Sparkles className="w-4 h-4 text-sky-600" />
              </div>
              <div>
                <div className="text-xs text-gray-400">平均质量分</div>
                <div className="text-lg font-bold text-gray-900">{stats.avgScore.toFixed(1)}</div>
              </div>
            </div>
          )}

          <div className="flex-1" />

          <div className="flex items-center gap-2">
            <Button
              variant="outline"
              size="sm"
              onClick={handleReset}
              disabled={!governanceState || !governanceState.isModified}
              className="gap-1.5"
            >
              <RotateCcw className="w-3.5 h-3.5" />
              重置当前
            </Button>
            <Button
              size="sm"
              onClick={handleSave}
              disabled={!governanceState}
              className="gap-2 bg-gradient-to-r from-sky-600 to-blue-600 hover:from-sky-700 hover:to-blue-700"
            >
              <Save className="w-4 h-4" />
              保存
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handleSaveAndNextFile}
              disabled={!governanceState}
              className="gap-2"
            >
              保存并下一份
              <ChevronRight className="w-4 h-4" />
            </Button>
            <Button
              variant="outline"
              size="sm"
              onClick={handlePushToChunkPreview}
              disabled={!isLoaded || files.length === 0}
              className="gap-2"
            >
              <Layers className="w-4 h-4" />
              推送到切块预览
              <ArrowRight className="w-4 h-4" />
            </Button>
          </div>
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden min-h-0">
        {/* 左侧文件列表 */}
        <aside className="w-72 bg-gray-50 border-r border-gray-200 flex flex-col flex-shrink-0">
          <div className="p-4 border-b border-gray-200">
            <div className="max-h-56 overflow-y-auto pr-1">
              <DocumentFolderTree />
            </div>
          </div>

          <div className="p-4 border-b border-gray-200">
            <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-3">
              待治理文件 ({visibleFiles.length})
            </h3>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="text"
                placeholder="搜索文件..."
                className="w-full pl-9 pr-3 py-2 text-sm bg-white border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-transparent"
              />
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {visibleFiles.length === 0 ? (
              <div className="text-sm text-gray-400 text-center py-8">该目录暂无文件</div>
            ) : (
              visibleFiles.map((file) => {
              const state = governanceStates[file.id]
              const hasIssue = state?.issues.some((i) => i.type === 'error')
              const score = state?.qualityScore || 0
              const processedAt = (() => {
                const raw = file.parsedAt
                if (!raw) return ''
                const date = new Date(raw)
                if (Number.isNaN(date.getTime())) return ''
                return date.toLocaleString('zh-CN', {
                  year: 'numeric',
                  month: 'numeric',
                  day: 'numeric',
                  hour: '2-digit',
                  minute: '2-digit',
                  hour12: false,
                })
              })()

              return (
                <div
                  key={file.id}
                  onClick={() => handleSelectFile(file.id)}
                  onKeyDown={(e) => {
                    if (e.key === 'Enter' || e.key === ' ') {
                      e.preventDefault()
                      handleSelectFile(file.id)
                    }
                  }}
                  role="button"
                  tabIndex={0}
                  className={cn(
                    "w-full text-left p-3 rounded-xl border transition-all",
                    selectedFileId === file.id
                      ? "bg-white border-sky-300 shadow-sm ring-1 ring-sky-100"
                      : "bg-transparent border-gray-200 hover:bg-white hover:border-gray-300"
                  )}
                >
                  <div className="flex items-start justify-between gap-2">
                    <div className="flex-1 min-w-0">
                      <div className={cn(
                        "text-sm font-medium truncate",
                        selectedFileId === file.id ? "text-gray-900" : "text-gray-600"
                      )}>
                        {file.filename}
                      </div>
                      <div className="flex items-center justify-between gap-2 mt-1">
                        <div className="flex items-center gap-2">
                          <span className="text-xs text-gray-400">
                            {file.fileType.toUpperCase()}
                          </span>
                          {score > 0 && (
                            <span className={cn(
                              "text-xs px-1.5 py-0.5 rounded font-medium",
                              score >= 80 ? "bg-green-100 text-green-700" :
                              score >= 60 ? "bg-yellow-100 text-yellow-700" :
                              "bg-red-100 text-red-700"
                            )}>
                              {score}分
                            </span>
                          )}
                          {state?.isModified && (
                            <span className="text-xs text-purple-600">● 已修改</span>
                          )}
                        </div>
                        {processedAt && (
                          <span
                            className="text-[10px] text-gray-400 whitespace-nowrap"
                            title={`处理时间：${processedAt}`}
                          >
                            {processedAt}
                          </span>
                        )}
                      </div>
                    </div>
                    <div className="flex items-center gap-1 flex-shrink-0">
                      {hasIssue ? (
                        <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0" />
                      ) : score >= 80 ? (
                        <CheckCircle className="w-4 h-4 text-green-500 flex-shrink-0" />
                      ) : null}
                      <button
                        type="button"
                        onClick={(e) => {
                          e.preventDefault()
                          e.stopPropagation()
                          handleDeleteFile(file.id)
                        }}
                        className="p-1 rounded-md text-gray-400 hover:text-red-600 hover:bg-red-50"
                        title="删除"
                        aria-label={`删除 ${file.filename}`}
                      >
                        <Trash2 className="w-4 h-4" />
                      </button>
                    </div>
                  </div>
                </div>
              )
              })
            )}
          </div>
        </aside>

        {/* 主内容区 */}
        <main className="flex-1 flex flex-col overflow-hidden min-h-0">
          {selectedFile && governanceState ? (
            <>
              {/* 治理标签页导航 */}
              <div className="flex-shrink-0 bg-white border-b border-gray-200 px-6">
                <div className="flex items-center gap-1">
                  {GOVERNANCE_TABS.map((tab) => {
                    const Icon = tab.icon
                    const isActive = activeTab === tab.id
                    const hasChanges = tab.id === 'clean' && governanceState.isModified

                    return (
                      <button
                        key={tab.id}
                        onClick={() => setActiveTab(tab.id)}
                        className={cn(
                          "flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-all relative",
                          isActive
                            ? `border-${tab.color}-500 text-${tab.color}-600`
                            : "border-transparent text-gray-500 hover:text-gray-700 hover:bg-gray-50"
                        )}
                      >
                        <Icon className={cn(
                          "w-4 h-4",
                          isActive ? `text-${tab.color}-500` : "text-gray-400"
                        )} />
                        <span>{tab.label}</span>
                        {hasChanges && (
                          <span className="absolute top-2 right-2 w-2 h-2 bg-purple-500 rounded-full" />
                        )}
                      </button>
                    )
                  })}
                </div>
              </div>

              {/* 内容区 */}
              <div className="flex-1 flex overflow-hidden min-h-0">
                {/* 左侧治理面板 */}
                <div className="w-[450px] flex-shrink-0 border-r border-gray-200 bg-gray-50/50 overflow-y-auto">
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

                {/* 右侧预览区 */}
                <div className="flex-1 flex flex-col overflow-hidden bg-white min-h-0">
                  {/* 预览工具栏 */}
                  <div className="flex-shrink-0 h-12 border-b border-gray-100 flex items-center justify-between px-4 bg-gray-50">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium text-gray-500">预览内容</span>
                      <span className={cn(
                        "text-xs px-2 py-0.5 rounded",
                        viewMode === 'original'
                          ? "text-gray-700 bg-gray-100"
                          : viewMode === 'preview'
                            ? "text-sky-700 bg-sky-50"
                            : "text-slate-700 bg-white border border-gray-200"
                      )}>
                        {viewMode === 'original' ? '解析原文' : viewMode === 'preview' ? '预览' : '编辑'}
                      </span>
                      {governanceState.isModified && (
                        <span className="text-xs text-purple-600 bg-purple-50 px-2 py-0.5 rounded">
                          已修改
                        </span>
                      )}
                    </div>
                    <div className="flex items-center gap-2">
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          if (viewMode === 'edit') setPreviewFormat('rendered')
                          setViewMode((m) => (m === 'edit' ? 'preview' : 'edit'))
                        }}
                        className="h-7 text-xs gap-1"
                      >
                        {viewMode === 'edit' ? <Eye className="w-3.5 h-3.5" /> : <EyeOff className="w-3.5 h-3.5" />}
                        {viewMode === 'edit' ? '预览（只读）' : '继续编辑'}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => {
                          if (viewMode === 'edit') setViewMode('preview')
                          setPreviewFormat((m) => (m === 'rendered' ? 'markdown' : 'rendered'))
                        }}
                        className="h-7 text-xs gap-1"
                      >
                        {previewFormat === 'rendered' ? 'Markdown 源码' : '渲染预览'}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        onClick={() => setViewMode((m) => (m === 'original' ? 'preview' : 'original'))}
                        className="h-7 text-xs gap-1"
                      >
                        <FileText className="w-3.5 h-3.5" />
                        {viewMode === 'original' ? '返回修改版' : '对比解析原文'}
                      </Button>
                      <Button
                        variant="ghost"
                        size="sm"
                        className="h-7 text-xs gap-1"
                      >
                        <Copy className="w-3.5 h-3.5" />
                        复制
                      </Button>
                    </div>
                  </div>

                  {/* 预览内容 */}
                  <div className="flex-1 overflow-y-auto p-8 bg-gray-50/50 min-h-0">
                    <div
                      className={cn(
                        'mx-auto pb-8',
                        viewMode !== 'edit' && previewFormat === 'rendered' ? 'max-w-6xl' : 'max-w-4xl'
                      )}
                    >
                      {viewMode === 'edit' ? (
                        <textarea
                          value={displayContent}
                          onChange={(e) => handleManualEdit(e.target.value)}
                          placeholder="在这里直接编辑内容..."
                          spellCheck={false}
                          className={cn(
                            "w-full min-h-[800px] p-10 rounded-2xl shadow-md border resize-none focus:outline-none focus:ring-2 focus:ring-sky-500/20 transition-all font-sans text-base leading-7 tracking-tight text-slate-800",
                            "bg-white border-slate-200"
                          )}
                        />
                      ) : (
                        <div
                          className={cn(
                            "w-full min-h-[800px] p-10 rounded-2xl shadow-md border",
                            viewMode === 'original'
                              ? "bg-gray-50/50 border-gray-200 text-gray-600"
                              : "bg-white border-slate-200"
                          )}
                        >
                          {previewFormat === 'rendered' ? (
                            <div className="flex gap-12">
                              <div className="min-w-0 flex-1 overflow-x-auto prose prose-slate max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-a:text-sky-700 prose-code:text-pink-600 prose-code:bg-pink-50 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-gray-900 prose-table:border-collapse prose-th:bg-gray-100 prose-th:border prose-th:border-gray-300 prose-th:p-2 prose-td:border prose-td:border-gray-300 prose-td:p-2">
                                <MarkdownRenderer markdown={displayContent || ''} autoScrollToHash />
                              </div>
                              {tocEnabled && (
                                <aside className="hidden xl:block w-72 shrink-0">
                                  <div className="sticky top-6 max-h-[calc(100vh-220px)] overflow-y-auto rounded-2xl border border-slate-100 bg-slate-50/50 p-5">
                                    <MarkdownToc markdown={displayContent || ''} />
                                  </div>
                                </aside>
                              )}
                            </div>
                          ) : (
                            <pre className={cn(
                              "font-mono text-sm leading-relaxed whitespace-pre-wrap break-words",
                              viewMode === 'original' ? "text-gray-600" : "text-slate-800"
                            )}>
                              {displayContent || ''}
                            </pre>
                          )}
                        </div>
                      )}
                    </div>
                  </div>
                </div>
              </div>
            </>
          ) : (
            <div className="flex-1 flex items-center justify-center">
              <div className="text-center text-gray-400">
                <FileSearch className="w-12 h-12 mx-auto mb-3 opacity-50" />
                <p>请选择文件进行治理</p>
              </div>
            </div>
          )}
        </main>
      </div>
    </div>
  )
}
