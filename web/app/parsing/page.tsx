'use client'

import { useState, useCallback, useRef } from 'react'
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
} from 'lucide-react'
import { Navbar } from '@/components/navbar'
import { Button } from '@/components/ui/button'
import { documentApi } from '@/lib/api-client'
import { formatFileSize, cn } from '@/lib/utils'
import { useParsedFiles } from '@/hooks/use-parsed-files'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { getParserLabel } from '@/lib/parser-options'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { FileQueueItem, FileQueueItemData, FileStatus } from '@/components/ui/file-queue-item'
import { ParserDropdown } from '@/components/ui/parser-dropdown'
import { MarkdownRenderer } from '@/components/markdown/markdown-renderer'
import { MarkdownToc } from '@/components/markdown/markdown-toc'

// 解析后的文件（扩展版）
interface ParsedFile extends FileQueueItemData {
  file: File
  markdownContent: string | null
  parserBackend: string
  parserLabel: string
  parseStartTime?: number
  stats?: {
    charCount: number
    lineCount: number
    pageCount?: number
    tableCount?: number
    imageCount?: number
  }
}

export default function ParsingPage() {
  const router = useRouter()

  // 文件状态
  const [files, setFiles] = useState<ParsedFile[]>([])
  const [activeFileId, setActiveFileId] = useState<string | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [copied, setCopied] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // 预览模式 & 编辑模式
  const [previewMode, setPreviewMode] = useState<'raw' | 'rendered'>('rendered')
  const [isEditing, setIsEditing] = useState(false)
  const [editedContent, setEditedContent] = useState('')

  // 解析器设置
  const { parserBackend, setParserBackend } = useParserBackendPreference()

  // 共享存储
  const { addParsedFile } = useParsedFiles()

  // 获取当前选中的文件
  const activeFile = files.find((f) => f.id === activeFileId) || null

  // 生成唯一 ID
  const generateId = () => Math.random().toString(36).substring(2, 15)

  // 添加文件
  const addFiles = useCallback((newFiles: File[]) => {
    const defaultLabel = getParserLabel(parserBackend)
    const parsedFiles: ParsedFile[] = newFiles.map((file) => ({
      id: generateId(),
      file,
      name: file.name,
      size: file.size,
      status: 'pending' as FileStatus,
      markdownContent: null,
      error: undefined,
      parserBackend,
      parserLabel: defaultLabel,
    }))

    setFiles((prev) => [...prev, ...parsedFiles])

    if (parsedFiles.length > 0) {
      setActiveFileId(parsedFiles[0].id)
    }
  }, [parserBackend])

  // 拖放处理
  const handleDragOver = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(true)
  }, [])

  const handleDragLeave = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
  }, [])

  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault()
    setIsDragging(false)
    const droppedFiles = Array.from(e.dataTransfer.files)
    addFiles(droppedFiles)
  }, [addFiles])

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = e.target.files ? Array.from(e.target.files) : []
    if (selectedFiles.length > 0) {
      addFiles(selectedFiles)
    }
    e.target.value = ''
  }, [addFiles])

  // 移除文件
  const removeFile = (fileId: string) => {
    setFiles((prev) => prev.filter((f) => f.id !== fileId))
    if (activeFileId === fileId) {
      const remaining = files.filter((f) => f.id !== fileId)
      setActiveFileId(remaining.length > 0 ? remaining[0].id : null)
    }
  }

  // 解析文件
  const parseFile = async (fileId: string) => {
    const file = files.find((f) => f.id === fileId)
    if (!file) return

    const startTime = Date.now()

    setFiles((prev) =>
      prev.map((f) =>
        f.id === fileId
          ? { ...f, status: 'parsing' as FileStatus, error: undefined, progress: 0, parseStartTime: startTime }
          : f
      )
    )

    // 模拟进度更新
    const progressInterval = setInterval(() => {
      setFiles((prev) =>
        prev.map((f) =>
          f.id === fileId && f.status === 'parsing'
            ? { ...f, progress: Math.min((f.progress || 0) + Math.random() * 15, 90) }
            : f
        )
      )
    }, 300)

    try {
      // 仅进行解析预览，不应用复杂的清洗和切块策略
      const data = await documentApi.preview(file.file, parserBackend)

      clearInterval(progressInterval)

      // 拼接 segments 获取全文
      const markdownContent = data.segments.map(s => s.content).join('\n\n')
      const resolvedBackend = data.parser_backend || parserBackend
      const resolvedLabel = getParserLabel(resolvedBackend)
      const duration = ((Date.now() - startTime) / 1000).toFixed(1)

      // 计算统计信息
      const stats = {
        charCount: markdownContent.length,
        lineCount: markdownContent.split('\n').length,
        tableCount: (markdownContent.match(/\|.*\|/g) || []).length > 0
          ? (markdownContent.match(/^\|/gm) || []).length / 2
          : 0,
        imageCount: (markdownContent.match(/!\[.*?\]\(.*?\)/g) || []).length,
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
              }
            : f
        )
      )

      // 保存到共享存储
      addParsedFile({
        filename: file.file.name,
        fileType: file.file.name.split('.').pop()?.toLowerCase() || '',
        fileSize: file.file.size,
        markdownContent,
        parser: resolvedLabel,
      })
    } catch (err: any) {
      clearInterval(progressInterval)
      setFiles((prev) =>
        prev.map((f) =>
          f.id === fileId
            ? {
                ...f,
                status: 'error' as FileStatus,
                error:
                  err.response?.data?.detail ||
                  err.response?.data?.message ||
                  (typeof err.response?.data === 'string' ? err.response.data : undefined) ||
                  err.message ||
                  '解析失败',
                progress: 0,
              }
            : f
        )
      )
    }
  }

  // 批量解析
  const parseAllPending = async () => {
    const pendingFiles = files.filter((f) => f.status === 'pending')
    for (const file of pendingFiles) {
      await parseFile(file.id)
    }
  }

  // 复制 Markdown
  const copyMarkdown = async () => {
    if (!activeFile?.markdownContent) return
    await navigator.clipboard.writeText(activeFile.markdownContent)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  // 下载 Markdown
  const downloadMarkdown = () => {
    if (!activeFile?.markdownContent) return
    const blob = new Blob([activeFile.markdownContent], { type: 'text/markdown' })
    const url = URL.createObjectURL(blob)
    const a = document.createElement('a')
    a.href = url
    a.download = activeFile.file.name.replace(/\.[^/.]+$/, '') + '.md'
    a.click()
    URL.revokeObjectURL(url)
  }

  // 开始编辑
  const handleStartEdit = () => {
    if (!activeFile?.markdownContent) return
    setEditedContent(activeFile.markdownContent)
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

    // 更新文件内容
    setFiles((prev) =>
      prev.map((f) =>
        f.id === activeFile.id
          ? {
              ...f,
              markdownContent: editedContent,
              stats: f.stats ? {
                ...f.stats,
                charCount: editedContent.length,
                lineCount: editedContent.split('\n').length,
              } : undefined,
            }
          : f
      )
    )

    setIsEditing(false)
  }

  // 提交到数据治理
  const handleSubmitToGovernance = () => {
    if (!activeFile?.markdownContent) return

    // 使用当前内容（可能是编辑后的）提交到数据治理
    addParsedFile({
      filename: activeFile.file.name,
      fileType: activeFile.file.name.split('.').pop()?.toLowerCase() || '',
      fileSize: activeFile.file.size,
      markdownContent: activeFile.markdownContent,
      parser: activeFile.parserLabel,
    })

    router.push('/data-governance')
  }

  // 计算统计数据
  const pendingCount = files.filter((f) => f.status === 'pending').length
  const parsingCount = files.filter((f) => f.status === 'parsing').length
  const parsedCount = files.filter((f) => f.status === 'parsed').length

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <Navbar />

      <main className="flex-1 flex flex-col overflow-hidden min-h-0">
        {/* 顶部标题栏 */}
        <header className="bg-white border-b px-6 py-4 flex-shrink-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="w-11 h-11 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl flex items-center justify-center shadow-lg shadow-indigo-200">
                <Sparkles className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-gray-900">文档解析工作台</h1>
                <p className="text-sm text-gray-500">
                  上传文件并转换为 Markdown 格式，为数据治理做准备
                </p>
              </div>
            </div>
          </div>
        </header>

        <div className="flex-1 flex overflow-hidden min-h-0">
          {/* 左侧：文件列表面板 */}
          <aside className="w-80 bg-white border-r flex flex-col flex-shrink-0">
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

            {/* 上传区域 */}
            <div className="p-4 border-b">
              <div
                className={cn(
                  'p-5 border-2 border-dashed rounded-xl text-center transition-all cursor-pointer',
                  isDragging
                    ? 'border-indigo-500 bg-indigo-50'
                    : 'border-gray-200 hover:border-indigo-400 hover:bg-indigo-50/30'
                )}
                onDragOver={handleDragOver}
                onDragLeave={handleDragLeave}
                onDrop={handleDrop}
                onClick={() => fileInputRef.current?.click()}
              >
                  <input
                    ref={fileInputRef}
                    type="file"
                    multiple
                    accept=".pdf,.txt,.md,.doc,.docx,.xls,.xlsx,.csv,.html,.json"
                    className="hidden"
                    onChange={handleFileSelect}
                  />
                <Upload className="w-7 h-7 mx-auto mb-2 text-gray-400" />
                <p className="text-sm font-medium text-gray-700">拖放或点击上传</p>
                <p className="text-xs text-gray-400 mt-1">PDF, Word, Excel, TXT, MD</p>
              </div>
            </div>

            {/* 文件列表 */}
            <div className="flex-1 overflow-y-auto p-4">
              <div className="flex items-center justify-between mb-3">
                <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider">
                  文件队列 ({files.length})
                </h3>
                {pendingCount > 1 && (
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={parseAllPending}
                    className="h-7 text-xs gap-1"
                  >
                    <Zap className="w-3 h-3" />
                    全部解析
                  </Button>
                )}
              </div>

              {files.length === 0 ? (
                <div className="text-center py-8 text-gray-400">
                  <FileStack className="w-10 h-10 mx-auto mb-2 opacity-50" />
                  <p className="text-sm">暂无文件</p>
                  <p className="text-xs mt-1">上传文件开始解析</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {files.map((file) => (
                    <FileQueueItem
                      key={file.id}
                      file={file}
                      isActive={activeFileId === file.id}
                      onClick={() => setActiveFileId(file.id)}
                      onRemove={() => removeFile(file.id)}
                      onRetry={() => parseFile(file.id)}
                    />
                  ))}
                </div>
              )}
            </div>

            {/* 底部统计 */}
            {files.length > 0 && (
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
                            {/* 预览模式切换 */}
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

                  {activeFile.status === 'parsed' && activeFile.markdownContent && (
                    <div className="p-6">
                      {isEditing ? (
                        // 编辑模式
                        <textarea
                          value={editedContent}
                          onChange={(e) => setEditedContent(e.target.value)}
                          className="w-full min-h-[500px] p-4 font-mono text-sm leading-relaxed text-gray-700 whitespace-pre-wrap bg-amber-50 border border-amber-200 rounded-xl resize-none focus:outline-none focus:ring-2 focus:ring-amber-500 focus:border-transparent"
                          placeholder="在此编辑内容..."
                          autoFocus
                        />
                      ) : previewMode === 'rendered' ? (
                        // 预览模式
                        <div className="flex gap-8">
                          <div className="min-w-0 flex-1 prose prose-slate max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-a:text-indigo-600 prose-code:text-pink-600 prose-code:bg-pink-50 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-gray-900 prose-table:border-collapse prose-th:bg-gray-100 prose-th:border prose-th:border-gray-300 prose-th:p-2 prose-td:border prose-td:border-gray-300 prose-td:p-2">
                            <MarkdownRenderer markdown={activeFile.markdownContent} autoScrollToHash />
                          </div>
                          <aside className="hidden xl:block w-64 shrink-0">
                            <div className="sticky top-6 max-h-[calc(100vh-220px)] overflow-y-auto rounded-xl border border-slate-200 bg-white/70 p-3">
                              <MarkdownToc markdown={activeFile.markdownContent} />
                            </div>
                          </aside>
                        </div>
                      ) : (
                        // 源码模式
                        <pre className="font-mono text-sm leading-relaxed text-gray-700 whitespace-pre-wrap bg-gray-50 p-6 rounded-xl border">
                          {activeFile.markdownContent}
                        </pre>
                      )}
                    </div>
                  )}
                </div>

                {/* 底部操作栏 */}
                {activeFile.status === 'parsed' && activeFile.markdownContent && (
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
