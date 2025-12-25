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
import { useParsedFiles } from '@/hooks/use-parsed-files'
import { cn } from '@/lib/utils'
import { QualityChecker } from '@/components/data-governance/quality-checker'
import { DataCleaner } from '@/components/data-governance/data-cleaner'
import { DataAnnotator } from '@/components/data-governance/data-annotator'
import { DataClassifier } from '@/components/data-governance/data-classifier'

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
  const { files, isLoaded, clearAll } = useParsedFiles()

  // UI 状态
  const [activeTab, setActiveTab] = useState<GovernanceTab>('quality')
  const [selectedFileId, setSelectedFileId] = useState<string | null>(null)
  const [showOriginal, setShowOriginal] = useState(false)
  const [isProcessing, setIsProcessing] = useState(false)

  // 文件治理状态
  const [governanceStates, setGovernanceStates] = useState<Record<string, FileGovernanceState>>({})

  // 选中的文件
  const selectedFile = files.find((f) => f.id === selectedFileId) || null
  const governanceState = selectedFileId ? governanceStates[selectedFileId] : null

  // 初始化：自动选择第一个文件
  useEffect(() => {
    if (isLoaded && files.length > 0 && !selectedFileId) {
      setSelectedFileId(files[0].id)
      initializeGovernanceState(files[0])
    }
  }, [isLoaded, files, selectedFileId])

  // 初始化文件治理状态
  const initializeGovernanceState = useCallback((file: { id: string; markdownContent: string }) => {
    if (!governanceStates[file.id]) {
      setGovernanceStates((prev) => ({
        ...prev,
        [file.id]: {
          id: file.id,
          originalContent: file.markdownContent,
          cleanedContent: file.markdownContent,
          annotations: [],
          tags: [],
          category: null,
          qualityScore: 0,
          issues: [],
          isModified: false,
        },
      }))
    }
  }, [governanceStates])

  // 获取当前显示内容
  const displayContent = useMemo(() => {
    if (!governanceState) return ''
    return showOriginal ? governanceState.originalContent : governanceState.cleanedContent
  }, [governanceState, showOriginal])

  // 文件选择
  const handleSelectFile = useCallback((fileId: string) => {
    const file = files.find((f) => f.id === fileId)
    if (file) {
      setSelectedFileId(fileId)
      initializeGovernanceState(file)
    }
  }, [files, initializeGovernanceState])

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

  // 保存并进入下一步
  const handleSaveAndContinue = useCallback(() => {
    // TODO: 保存治理后的数据到后端或 localStorage
    router.push('/chunk-preview')
  }, [router])

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

  // 空状态
  if (isLoaded && files.length === 0) {
    return (
      <div className="flex-1 flex items-center justify-center bg-gray-50">
        <div className="text-center max-w-md">
          <div className="w-20 h-20 mx-auto mb-4 bg-gradient-to-br from-amber-100 to-orange-100 rounded-2xl flex items-center justify-center">
            <ShieldCheck className="w-10 h-10 text-amber-500" />
          </div>
          <h3 className="text-lg font-medium text-gray-700 mb-2">暂无待治理文件</h3>
          <p className="text-gray-400 text-sm mb-6">请先在文档解析页面解析文档</p>
          <Button onClick={handleBackToParsing} className="gap-2">
            <Upload className="w-4 h-4" />
            前往解析文档
          </Button>
        </div>
      </div>
    )
  }

  return (
    <div className="flex-1 flex flex-col bg-white">
      {/* 顶部标题栏 */}
      <header className="flex-shrink-0 bg-white border-b border-gray-200 px-6 py-4">
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-4">
            <div className="w-11 h-11 bg-gradient-to-br from-amber-500 to-orange-600 rounded-xl flex items-center justify-center shadow-lg shadow-amber-200">
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
                        ? "bg-amber-100 text-amber-700 font-medium"
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
              <div className="w-8 h-8 bg-amber-100 rounded-lg flex items-center justify-center">
                <Sparkles className="w-4 h-4 text-amber-600" />
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
              onClick={handleSaveAndContinue}
              className="gap-2 bg-gradient-to-r from-amber-600 to-orange-600 hover:from-amber-700 hover:to-orange-700"
            >
              <Save className="w-4 h-4" />
              保存并继续
              <ChevronRight className="w-4 h-4" />
            </Button>
          </div>
        </div>
      </div>

      <div className="flex-1 flex overflow-hidden">
        {/* 左侧文件列表 */}
        <aside className="w-72 bg-gray-50 border-r border-gray-200 flex flex-col flex-shrink-0">
          <div className="p-4 border-b border-gray-200">
            <h3 className="text-xs font-bold text-gray-500 uppercase tracking-wider mb-3">
              待治理文件 ({files.length})
            </h3>
            <div className="relative">
              <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400" />
              <input
                type="text"
                placeholder="搜索文件..."
                className="w-full pl-9 pr-3 py-2 text-sm bg-white border border-gray-200 rounded-lg focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent"
              />
            </div>
          </div>

          <div className="flex-1 overflow-y-auto p-3 space-y-2">
            {files.map((file) => {
              const state = governanceStates[file.id]
              const hasIssue = state?.issues.some((i) => i.type === 'error')
              const score = state?.qualityScore || 0

              return (
                <button
                  key={file.id}
                  onClick={() => handleSelectFile(file.id)}
                  className={cn(
                    "w-full text-left p-3 rounded-xl border transition-all",
                    selectedFileId === file.id
                      ? "bg-white border-amber-300 shadow-sm ring-1 ring-amber-100"
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
                      <div className="flex items-center gap-2 mt-1">
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
                    </div>
                    {hasIssue ? (
                      <AlertCircle className="w-4 h-4 text-red-500 flex-shrink-0" />
                    ) : score >= 80 ? (
                      <CheckCircle className="w-4 h-4 text-green-500 flex-shrink-0" />
                    ) : null}
                  </div>
                </button>
              )
            })}
          </div>
        </aside>

        {/* 主内容区 */}
        <main className="flex-1 flex flex-col overflow-hidden">
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
              <div className="flex-1 flex overflow-hidden">
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
                <div className="flex-1 flex flex-col overflow-hidden bg-white">
                  {/* 预览工具栏 */}
                  <div className="flex-shrink-0 h-12 border-b border-gray-100 flex items-center justify-between px-4 bg-gray-50">
                    <div className="flex items-center gap-2">
                      <span className="text-xs font-medium text-gray-500">预览内容</span>
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
                        onClick={() => setShowOriginal(!showOriginal)}
                        disabled={governanceState.cleanedContent === governanceState.originalContent}
                        className="h-7 text-xs gap-1"
                      >
                        {showOriginal ? <Eye className="w-3.5 h-3.5" /> : <EyeOff className="w-3.5 h-3.5" />}
                        {showOriginal ? '查看原文' : '查看原文'}
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
                  <div className="flex-1 overflow-y-auto p-6">
                    <div className="max-w-3xl mx-auto">
                      <div className="prose prose-slate max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-a:text-amber-600 prose-code:text-pink-600 prose-code:bg-pink-50 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-gray-900">
                        <pre className="whitespace-pre-wrap font-sans text-sm leading-relaxed text-gray-700">
                          {displayContent}
                        </pre>
                      </div>
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
