'use client'

/**
 * 文档解析页面
 * 上传文件 → 后端解析 → 预览 Markdown 结果
 * 知识库流程第一步：解析
 */
import { useState, useCallback, useRef } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  Upload,
  FileText,
  File,
  FileSpreadsheet,
  FileType,
  Loader2,
  CheckCircle,
  XCircle,
  Eye,
  Code,
  Trash2,
  Download,
  Copy,
  Check,
  RotateCcw,
  Sparkles,
} from 'lucide-react'
import { Navbar } from '@/components/navbar'
import { Button } from '@/components/ui/button'
import { documentApi } from '@/lib/api-client'
import { formatFileSize, cn } from '@/lib/utils'
import { useParsedFiles } from '@/hooks/use-parsed-files'
import { ParserBackendSelect } from '@/components/parser-backend-select'
import { useParserBackendPreference } from '@/contexts/parser-backend-context'
import { getParserLabel } from '@/lib/parser-options'

// 文件状态类型
type FileStatus = 'pending' | 'parsing' | 'parsed' | 'error'

// 解析后的文件
interface ParsedFile {
  id: string
  file: File
  status: FileStatus
  markdownContent: string | null
  error: string | null
  parserBackend: string
  parserLabel: string
}

// 支持的文件类型配置
const FILE_TYPES = {
  pdf: { icon: FileText, color: 'text-red-500', bg: 'bg-red-50', label: 'PDF', parser: 'MinerU' },
  xlsx: { icon: FileSpreadsheet, color: 'text-green-600', bg: 'bg-green-50', label: 'Excel', parser: 'MarkItDown' },
  xls: { icon: FileSpreadsheet, color: 'text-green-600', bg: 'bg-green-50', label: 'Excel', parser: 'MarkItDown' },
  docx: { icon: FileType, color: 'text-blue-600', bg: 'bg-blue-50', label: 'Word', parser: 'MarkItDown' },
  doc: { icon: FileType, color: 'text-blue-600', bg: 'bg-blue-50', label: 'Word', parser: 'MarkItDown' },
  txt: { icon: File, color: 'text-gray-600', bg: 'bg-gray-50', label: 'Text', parser: 'Native' },
  md: { icon: FileText, color: 'text-purple-600', bg: 'bg-purple-50', label: 'Markdown', parser: 'Native' },
}

export default function ParsingPage() {
  // 文件状态
  const [files, setFiles] = useState<ParsedFile[]>([])
  const [activeFileId, setActiveFileId] = useState<string | null>(null)
  const [isDragging, setIsDragging] = useState(false)
  const [copied, setCopied] = useState(false)
  const fileInputRef = useRef<HTMLInputElement>(null)

  // 预览模式
  const [previewMode, setPreviewMode] = useState<'raw' | 'rendered'>('rendered')

  // 共享存储
  const { addParsedFile } = useParsedFiles()
  const { parserBackend } = useParserBackendPreference()

  // 获取当前选中的文件
  const activeFile = files.find((f) => f.id === activeFileId) || null

  // 获取文件扩展名
  const getFileExt = (filename: string): string => {
    return filename.split('.').pop()?.toLowerCase() || ''
  }

  // 获取文件类型配置
  const getFileConfig = (filename: string) => {
    const ext = getFileExt(filename)
    return FILE_TYPES[ext as keyof typeof FILE_TYPES] || FILE_TYPES.txt
  }

  // 生成唯一 ID
  const generateId = () => Math.random().toString(36).substring(2, 15)

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
  }, [])

  const handleFileSelect = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const selectedFiles = e.target.files ? Array.from(e.target.files) : []
    if (selectedFiles.length > 0) {
      addFiles(selectedFiles)
    }
    e.target.value = ''
  }, [])

  // 添加文件
  const addFiles = (newFiles: File[]) => {
    const defaultLabel = getParserLabel(parserBackend)
    const parsedFiles: ParsedFile[] = newFiles.map((file) => ({
      id: generateId(),
      file,
      status: 'pending',
      markdownContent: null,
      error: null,
      parserBackend,
      parserLabel: defaultLabel,
    }))

    setFiles((prev) => [...prev, ...parsedFiles])

    // 自动选中第一个新文件
    if (parsedFiles.length > 0) {
      setActiveFileId(parsedFiles[0].id)
    }
  }

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

    setFiles((prev) =>
      prev.map((f) =>
        f.id === fileId ? { ...f, status: 'parsing', error: null } : f
      )
    )

    try {
      // 调用后端解析 API（复用 chunkPreview，只取 original_text）
      const data = await documentApi.chunkPreview(file.file, {
        chunk_size: 10000, // 大一点，只是为了获取解析后的文本
        chunk_overlap: 0,
        parser_backend: parserBackend,
      })

      const markdownContent = data.original_text || ''
      const resolvedBackend = data.parser_backend || parserBackend
      const resolvedLabel = getParserLabel(resolvedBackend)

      setFiles((prev) =>
        prev.map((f) =>
          f.id === fileId
            ? {
                ...f,
                status: 'parsed',
                markdownContent,
                parserBackend: resolvedBackend,
                parserLabel: resolvedLabel,
              }
            : f
        )
      )

      // 保存到共享存储，供 chunk-preview 使用
      addParsedFile({
        filename: file.file.name,
        fileType: getFileExt(file.file.name),
        fileSize: file.file.size,
        markdownContent,
        parser: resolvedLabel,
      })
    } catch (err: any) {
      setFiles((prev) =>
        prev.map((f) =>
          f.id === fileId
            ? {
                ...f,
                status: 'error',
                error: err.response?.data?.detail || err.message || '解析失败',
              }
            : f
        )
      )
    }
  }

  // 复制 Markdown 内容
  const copyMarkdown = async () => {
    if (!activeFile?.markdownContent) return
    await navigator.clipboard.writeText(activeFile.markdownContent)
    setCopied(true)
    setTimeout(() => setCopied(false), 2000)
  }

  // 下载 Markdown 文件
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

  // 获取状态图标
  const getStatusBadge = (status: FileStatus) => {
    switch (status) {
      case 'parsing':
        return (
          <span className="flex items-center gap-1 text-xs text-blue-600 bg-blue-50 px-2 py-0.5 rounded-full">
            <Loader2 className="w-3 h-3 animate-spin" />
            解析中
          </span>
        )
      case 'parsed':
        return (
          <span className="flex items-center gap-1 text-xs text-green-600 bg-green-50 px-2 py-0.5 rounded-full">
            <CheckCircle className="w-3 h-3" />
            已解析
          </span>
        )
      case 'error':
        return (
          <span className="flex items-center gap-1 text-xs text-red-600 bg-red-50 px-2 py-0.5 rounded-full">
            <XCircle className="w-3 h-3" />
            失败
          </span>
        )
      default:
        return (
          <span className="text-xs text-gray-500 bg-gray-100 px-2 py-0.5 rounded-full">
            待解析
          </span>
        )
    }
  }

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <Navbar />

      <main className="flex-1 flex flex-col overflow-hidden">
        {/* 顶部标题栏 */}
        <header className="bg-white border-b px-8 py-5 flex-shrink-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-xl flex items-center justify-center shadow-lg shadow-indigo-200">
                <Sparkles className="w-6 h-6 text-white" />
              </div>
              <div>
                <h1 className="text-2xl font-bold text-gray-900">文档解析</h1>
                <p className="text-sm text-gray-500 mt-0.5">
                  上传文档，解析为 Markdown 格式 · 支持 PDF、Excel、Word、TXT
                </p>
              </div>
            </div>
            <ParserBackendSelect compact />
          </div>
        </header>

        <div className="flex-1 flex overflow-hidden">
          {/* 左侧：文件列表 */}
          <aside className="w-80 bg-white border-r flex flex-col flex-shrink-0">
            {/* 上传区域 */}
            <div className="p-4 border-b">
              <div
                className={cn(
                  'p-6 border-2 border-dashed rounded-xl text-center transition-all cursor-pointer',
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
                  accept=".pdf,.txt,.md,.xlsx,.xls,.docx,.doc"
                  className="hidden"
                  onChange={handleFileSelect}
                />
                <Upload className="w-8 h-8 mx-auto mb-2 text-gray-400" />
                <p className="text-sm font-medium text-gray-700">点击或拖放上传</p>
                <p className="text-xs text-gray-400 mt-1">PDF, Excel, Word, TXT, MD</p>
              </div>
            </div>

            {/* 文件列表 */}
            <div className="flex-1 overflow-y-auto p-4">
              <h3 className="text-xs font-semibold text-gray-500 uppercase tracking-wider mb-3">
                文件列表 ({files.length})
              </h3>

              {files.length === 0 ? (
                <div className="text-center py-8 text-gray-400">
                  <FileText className="w-10 h-10 mx-auto mb-2 opacity-50" />
                  <p className="text-sm">暂无文件</p>
                </div>
              ) : (
                <div className="space-y-2">
                  {files.map((file) => {
                    const config = getFileConfig(file.file.name)
                    const Icon = config.icon
                    const isActive = activeFileId === file.id

                    return (
                      <div
                        key={file.id}
                        className={cn(
                          'group p-3 rounded-lg border transition-all cursor-pointer',
                          isActive
                            ? 'bg-indigo-50 border-indigo-200'
                            : 'bg-white border-gray-200 hover:border-indigo-200 hover:bg-gray-50'
                        )}
                        onClick={() => setActiveFileId(file.id)}
                      >
                        <div className="flex items-start gap-3">
                          <div className={cn('p-2 rounded-lg', config.bg)}>
                            <Icon className={cn('w-5 h-5', config.color)} />
                          </div>
                          <div className="flex-1 min-w-0">
                            <p className="text-sm font-medium text-gray-900 truncate">
                              {file.file.name}
                            </p>
                            <div className="flex items-center gap-2 mt-1">
                              <span className="text-xs text-gray-400">
                                {formatFileSize(file.file.size)}
                              </span>
                              <span className="text-xs text-gray-300">·</span>
                              <span className="text-xs text-gray-400">{file.parserLabel}</span>
                            </div>
                            <div className="mt-2">
                              {getStatusBadge(file.status)}
                            </div>
                          </div>
                          <button
                            onClick={(e) => {
                              e.stopPropagation()
                              removeFile(file.id)
                            }}
                            className="opacity-0 group-hover:opacity-100 p-1 hover:bg-red-50 rounded transition-all"
                          >
                            <Trash2 className="w-4 h-4 text-gray-400 hover:text-red-500" />
                          </button>
                        </div>
                      </div>
                    )
                  })}
                </div>
              )}
            </div>
          </aside>

          {/* 右侧：预览区域 */}
          <div className="flex-1 flex flex-col bg-white overflow-hidden">
            {!activeFile ? (
              // 空状态
              <div className="flex-1 flex items-center justify-center">
                <div className="text-center">
                  <div className="w-20 h-20 mx-auto mb-4 bg-gray-100 rounded-2xl flex items-center justify-center">
                    <FileText className="w-10 h-10 text-gray-400" />
                  </div>
                  <p className="text-gray-500 mb-2">从左侧选择或上传文件</p>
                  <p className="text-gray-400 text-sm">支持 PDF, Excel, Word, TXT, Markdown</p>
                </div>
              </div>
            ) : (
              <>
                {/* 工具栏 */}
                <div className="flex items-center justify-between px-6 py-3 border-b bg-gray-50">
                  <div className="flex items-center gap-3">
                    {(() => {
                      const config = getFileConfig(activeFile.file.name)
                      const Icon = config.icon
                      return (
                        <>
                          <div className={cn('p-1.5 rounded-lg', config.bg)}>
                            <Icon className={cn('w-4 h-4', config.color)} />
                          </div>
                          <span className="font-medium text-gray-900">{activeFile.file.name}</span>
                          <span className="text-xs text-gray-400 bg-gray-200 px-2 py-0.5 rounded">
                            {activeFile.parserLabel}
                          </span>
                        </>
                      )
                    })()}
                  </div>

                  <div className="flex items-center gap-2">
                    {activeFile.status === 'parsed' && (
                      <>
                        {/* 预览模式切换 */}
                        <div className="flex items-center bg-gray-200 rounded-lg p-0.5 mr-2">
                          <button
                            onClick={() => setPreviewMode('rendered')}
                            className={cn(
                              'px-3 py-1.5 text-xs rounded-md transition-all',
                              previewMode === 'rendered'
                                ? 'bg-white text-gray-900 shadow-sm'
                                : 'text-gray-500 hover:text-gray-700'
                            )}
                          >
                            <Eye className="w-3.5 h-3.5 inline mr-1" />
                            预览
                          </button>
                          <button
                            onClick={() => setPreviewMode('raw')}
                            className={cn(
                              'px-3 py-1.5 text-xs rounded-md transition-all',
                              previewMode === 'raw'
                                ? 'bg-white text-gray-900 shadow-sm'
                                : 'text-gray-500 hover:text-gray-700'
                            )}
                          >
                            <Code className="w-3.5 h-3.5 inline mr-1" />
                            源码
                          </button>
                        </div>

                        <Button
                          variant="outline"
                          size="sm"
                          onClick={copyMarkdown}
                          className="gap-1.5"
                        >
                          {copied ? (
                            <Check className="w-4 h-4 text-green-500" />
                          ) : (
                            <Copy className="w-4 h-4" />
                          )}
                          {copied ? '已复制' : '复制'}
                        </Button>

                        <Button
                          variant="outline"
                          size="sm"
                          onClick={downloadMarkdown}
                          className="gap-1.5"
                        >
                          <Download className="w-4 h-4" />
                          下载 .md
                        </Button>
                      </>
                    )}

                    {activeFile.status === 'pending' && (
                      <Button
                        onClick={() => parseFile(activeFile.id)}
                        className="gap-2 bg-indigo-600 hover:bg-indigo-700"
                      >
                        <Sparkles className="w-4 h-4" />
                        开始解析
                      </Button>
                    )}

                    {activeFile.status === 'error' && (
                      <Button
                        onClick={() => parseFile(activeFile.id)}
                        variant="outline"
                        className="gap-2"
                      >
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
                        <p className="text-gray-600 mb-2">点击上方按钮开始解析</p>
                        <p className="text-gray-400 text-sm">
                          将使用 {activeFile.parserLabel} 解析器
                        </p>
                      </div>
                    </div>
                  )}

                  {activeFile.status === 'parsing' && (
                    <div className="flex items-center justify-center h-full">
                      <div className="text-center">
                        <Loader2 className="w-12 h-12 animate-spin text-indigo-500 mx-auto mb-4" />
                        <p className="text-gray-600">
                          正在使用 {activeFile.parserLabel} 解析...
                        </p>
                        <p className="text-gray-400 text-sm mt-2">
                          Converting to Markdown...
                        </p>
                      </div>
                    </div>
                  )}

                  {activeFile.status === 'error' && (
                    <div className="flex items-center justify-center h-full">
                      <div className="text-center">
                        <div className="w-16 h-16 mx-auto mb-4 bg-red-100 rounded-xl flex items-center justify-center">
                          <XCircle className="w-8 h-8 text-red-500" />
                        </div>
                        <p className="text-red-600 mb-2">解析失败</p>
                        <p className="text-gray-500 text-sm">{activeFile.error}</p>
                      </div>
                    </div>
                  )}

                  {activeFile.status === 'parsed' && activeFile.markdownContent && (
                    <div className="p-8">
                      {previewMode === 'rendered' ? (
                        <div className="prose prose-slate max-w-none prose-headings:text-gray-900 prose-p:text-gray-700 prose-a:text-indigo-600 prose-code:text-pink-600 prose-code:bg-pink-50 prose-code:px-1 prose-code:py-0.5 prose-code:rounded prose-pre:bg-gray-900 prose-table:border-collapse prose-th:bg-gray-100 prose-th:border prose-th:border-gray-300 prose-th:p-2 prose-td:border prose-td:border-gray-300 prose-td:p-2">
                          <ReactMarkdown remarkPlugins={[remarkGfm]}>
                            {activeFile.markdownContent}
                          </ReactMarkdown>
                        </div>
                      ) : (
                        <pre className="font-mono text-sm leading-relaxed text-gray-700 whitespace-pre-wrap bg-gray-50 p-6 rounded-xl border">
                          {activeFile.markdownContent}
                        </pre>
                      )}
                    </div>
                  )}
                </div>

                {/* 底部信息栏 */}
                {activeFile.status === 'parsed' && activeFile.markdownContent && (
                  <div className="px-6 py-3 border-t bg-gray-50 flex items-center justify-between text-sm text-gray-500">
                    <div className="flex items-center gap-4">
                      <span>{activeFile.markdownContent.length.toLocaleString()} 字符</span>
                      <span>{activeFile.markdownContent.split('\n').length} 行</span>
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
