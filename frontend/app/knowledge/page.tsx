'use client'

/**
 * 知识库管理页面
 * 优化版：卡片视图、视觉增强、交互优化、深色模式适配
 */
import { useState } from 'react'
import {
  Database,
  FileText,
  Search,
  Settings,
  Upload,
  Loader2,
  CheckCircle,
  XCircle,
  Clock,
  Trash2,
  RefreshCw,
  BarChart3,
  Layers,
  HardDrive,
  FileStack,
  Eye,
  LayoutGrid,
  List as ListIcon,
  MoreVertical,
  File as FileIcon,
  Sparkles,
  Send,
  Zap,
  Filter
} from 'lucide-react'
import { Navbar } from '@/components/navbar'
import { Button } from '@/components/ui/button'
import { useDocuments } from '@/hooks/use-documents'
import { formatFileSize, formatDate, cn } from '@/lib/utils'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { DocumentDetailDialog } from '@/components/document-detail-dialog'
import { getParserLabel } from '@/lib/parser-options'
import type { Document } from '@/types'

// Tab 类型
type TabType = 'documents' | 'retrieval' | 'settings'
type ViewMode = 'grid' | 'list'

export default function KnowledgePage() {
  const { documents, isLoading, uploadDocument, deleteDocument, loadDocuments } = useDocuments()
  const [activeTab, setActiveTab] = useState<TabType>('documents')
  const [viewMode, setViewMode] = useState<ViewMode>('grid')
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null)

  // 检索测试状态
  const [searchQuery, setSearchQuery] = useState('')
  const [searchResults, setSearchResults] = useState<any[]>([])
  const [isSearching, setIsSearching] = useState(false)

  // 计算统计数据
  const totalDocs = documents.length
  const completedDocs = documents.filter(d => d.status === 'completed').length
  const processingDocs = documents.filter(d => d.status === 'processing' || d.status === 'pending').length
  const failedDocs = documents.filter(d => d.status === 'failed').length
  const totalChunks = documents.reduce((sum, d) => sum + (d.chunk_count || 0), 0)
  const totalSize = documents.reduce((sum, d) => sum + (d.file_size || 0), 0)
  
  const showExtraCard = processingDocs > 0 || failedDocs > 0

  // 处理文件上传
  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = e.target.files
    if (!files || files.length === 0) return

    for (const file of Array.from(files)) {
      try {
        await uploadDocument(file)
      } catch (error) {
        console.error('Upload failed:', error)
      }
    }
    e.target.value = ''
  }

  // 检索测试
  const handleSearch = async () => {
    if (!searchQuery.trim()) return

    setIsSearching(true)
    try {
      // 模拟搜索结果
      await new Promise(resolve => setTimeout(resolve, 800))
      setSearchResults([
        { id: '1', content: 'MimirQ 是一个基于 RAG 架构的智能知识库系统，旨在帮助用户高效管理和检索文档数据...', score: 0.95, source: 'README.md' },
        { id: '2', content: '系统支持多种文档格式，包括 PDF, TXT, Markdown, Excel 等，并能够自动进行文本分块和向量化...', score: 0.87, source: 'Feature_List.pdf' },
        { id: '3', content: '在部署方面，支持 Docker Compose 一键启动，包含后端 API、前端界面和向量数据库 Milvus...', score: 0.76, source: 'Deploy_Guide.docx' },
      ])
    } catch (error) {
      console.error('Search failed:', error)
    } finally {
      setIsSearching(false)
    }
  }

  // 获取状态配置
  const getStatusConfig = (status: string) => {
    switch (status) {
      case 'completed':
        return { icon: CheckCircle, color: 'text-emerald-500', bg: 'bg-emerald-50 dark:bg-emerald-500/10', border: 'border-emerald-100 dark:border-emerald-500/20', label: '已就绪' }
      case 'failed':
        return { icon: XCircle, color: 'text-red-500', bg: 'bg-red-50 dark:bg-red-500/10', border: 'border-red-100 dark:border-red-500/20', label: '失败' }
      case 'processing':
      case 'pending':
        return { icon: Loader2, color: 'text-indigo-500', bg: 'bg-indigo-50 dark:bg-indigo-500/10', border: 'border-indigo-100 dark:border-indigo-500/20', label: '处理中', spin: true }
      default:
        return { icon: Clock, color: 'text-slate-400', bg: 'bg-slate-50 dark:bg-slate-800', border: 'border-slate-100 dark:border-slate-700', label: '等待' }
    }
  }

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50/50 dark:bg-slate-950 transition-colors duration-300">
      <Navbar />

      <main className="flex-1 flex flex-col overflow-hidden relative">
        {/* 背景装饰 */}
        <div className="absolute top-0 left-0 right-0 h-64 bg-gradient-to-b from-indigo-50/50 dark:from-indigo-900/10 to-transparent pointer-events-none" />

        {/* 顶部标题栏 */}
        <header className="px-8 py-6 flex-shrink-0 z-10">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 bg-white dark:bg-slate-900 rounded-2xl flex items-center justify-center shadow-sm border border-slate-100 dark:border-slate-800">
                <Database className="w-6 h-6 text-indigo-600 dark:text-indigo-400" />
              </div>
              <div>
                <h1 className="text-2xl font-bold text-slate-900 dark:text-white tracking-tight">知识库管理</h1>
                <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
                  管理您的文档资产，构建专属知识大脑
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3">
               <label>
                <Button className="gap-2 bg-indigo-600 hover:bg-indigo-700 text-white shadow-lg shadow-indigo-200 dark:shadow-indigo-900/20 hover:shadow-indigo-300 transition-all rounded-xl" size="lg" asChild>
                  <span>
                    <Upload className="w-4 h-4" />
                    上传文档
                  </span>
                </Button>
                <input
                  type="file"
                  multiple
                  accept=".pdf,.txt,.md,.xlsx,.xls,.docx,.doc"
                  className="hidden"
                  onChange={handleFileUpload}
                />
              </label>
            </div>
          </div>

          {/* 统计卡片区 */}
          <StatsGrid className={showExtraCard ? "lg:grid-cols-5" : "lg:grid-cols-4"}>
            <StatCard
              icon={FileStack}
              label="文档总数"
              value={totalDocs}
              color="indigo"
              className="bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm border-slate-200 dark:border-slate-800 shadow-sm"
            />
            <StatCard
              icon={CheckCircle}
              label="已就绪"
              value={completedDocs}
              color="green"
              className="bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm border-slate-200 dark:border-slate-800 shadow-sm"
            />
            <StatCard
              icon={Layers}
              label="知识分块"
              value={totalChunks.toLocaleString()}
              color="purple"
              className="bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm border-slate-200 dark:border-slate-800 shadow-sm"
            />
            <StatCard
              icon={HardDrive}
              label="存储占用"
              value={formatFileSize(totalSize)}
              color="orange"
              className="bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm border-slate-200 dark:border-slate-800 shadow-sm"
            />
            {showExtraCard && (
              <StatCard
                icon={failedDocs > 0 ? XCircle : Loader2}
                label={failedDocs > 0 ? '需关注' : '处理中'}
                value={failedDocs > 0 ? failedDocs : processingDocs}
                color={failedDocs > 0 ? 'red' : 'indigo'}
                className="bg-white/80 dark:bg-slate-900/80 backdrop-blur-sm border-slate-200 dark:border-slate-800 shadow-sm"
              />
            )}
          </StatsGrid>
        </header>

        {/* 导航栏 & 工具栏 */}
        <div className="px-8 flex items-center justify-between border-b border-slate-200/60 dark:border-slate-800 bg-white/50 dark:bg-slate-900/50 backdrop-blur-sm sticky top-0 z-20">
          <div className="flex gap-1 -mb-px">
            {[
              { key: 'documents' as TabType, label: '文档列表', icon: FileText },
              { key: 'retrieval' as TabType, label: '检索测试', icon: Zap },
              { key: 'settings' as TabType, label: '配置', icon: Settings },
            ].map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={cn(
                  'flex items-center gap-2 px-5 py-4 text-sm font-medium border-b-2 transition-all',
                  activeTab === tab.key
                    ? 'text-indigo-600 dark:text-indigo-400 border-indigo-600 dark:border-indigo-400 bg-indigo-50/50 dark:bg-indigo-500/10'
                    : 'text-slate-500 dark:text-slate-400 border-transparent hover:text-slate-700 dark:hover:text-slate-200 hover:bg-slate-50 dark:hover:bg-slate-800'
                )}
              >
                <tab.icon className={cn("w-4 h-4", activeTab === tab.key ? "text-indigo-500 dark:text-indigo-400" : "text-slate-400 dark:text-slate-500")} />
                {tab.label}
              </button>
            ))}
          </div>

          {activeTab === 'documents' && (
            <div className="flex items-center gap-2 py-2">
              <Button
                variant="ghost"
                size="sm"
                onClick={() => loadDocuments()}
                className="text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
                title="刷新列表"
              >
                <RefreshCw className="w-4 h-4" />
              </Button>
               <Button
                variant="ghost"
                size="sm"
                onClick={() => window.open('/chunk-preview', '_blank')}
                className="text-slate-500 dark:text-slate-400 hover:text-slate-700 dark:hover:text-slate-200"
                title="预览分块"
              >
                <Eye className="w-4 h-4" />
              </Button>
              <div className="bg-slate-100 dark:bg-slate-800 p-1 rounded-lg flex gap-1">
                <button
                  onClick={() => setViewMode('grid')}
                  className={cn(
                    "p-1.5 rounded-md transition-all",
                    viewMode === 'grid' 
                      ? "bg-white dark:bg-slate-700 shadow-sm text-indigo-600 dark:text-indigo-400" 
                      : "text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300"
                  )}
                >
                  <LayoutGrid className="w-4 h-4" />
                </button>
                <button
                  onClick={() => setViewMode('list')}
                  className={cn(
                    "p-1.5 rounded-md transition-all",
                    viewMode === 'list' 
                      ? "bg-white dark:bg-slate-700 shadow-sm text-indigo-600 dark:text-indigo-400" 
                      : "text-slate-400 dark:text-slate-500 hover:text-slate-600 dark:hover:text-slate-300"
                  )}
                >
                  <ListIcon className="w-4 h-4" />
                </button>
              </div>
            </div>
          )}
        </div>

        {/* 内容区域 */}
        <div className="flex-1 overflow-y-auto p-8 scroll-smooth">
          {/* 文档列表 */}
          {activeTab === 'documents' && (
            <div className="animate-in fade-in slide-in-from-bottom-4 duration-500">
              {isLoading && documents.length === 0 ? (
                <div className="flex flex-col items-center justify-center h-64 text-slate-400 dark:text-slate-500">
                  <Loader2 className="w-8 h-8 animate-spin mb-3" />
                  <p className="text-sm">正在加载文档库...</p>
                </div>
              ) : documents.length === 0 ? (
                <EmptyState onUpload={handleFileUpload} />
              ) : (
                <>
                  {viewMode === 'grid' ? (
                    <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4 2xl:grid-cols-5 gap-5">
                      {documents.map((doc) => (
                        <DocumentCard
                          key={doc.id}
                          doc={doc}
                          getStatusConfig={getStatusConfig}
                          onDelete={deleteDocument}
                        />
                      ))}
                    </div>
                  ) : (
                    <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden">
                      <table className="w-full text-sm text-left">
                        <thead className="text-xs text-slate-500 dark:text-slate-400 uppercase bg-slate-50/80 dark:bg-slate-800/50 border-b border-slate-100 dark:border-slate-800">
                          <tr>
                            <th className="px-6 py-4 font-medium">文档名称</th>
                            <th className="px-6 py-4 font-medium">状态</th>
                            <th className="px-6 py-4 font-medium">分块</th>
                            <th className="px-6 py-4 font-medium">大小</th>
                            <th className="px-6 py-4 font-medium">上传时间</th>
                            <th className="px-6 py-4 font-medium text-right">操作</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-slate-100 dark:divide-slate-800">
                          {documents.map((doc) => {
                             const status = getStatusConfig(doc.status)
                             const StatusIcon = status.icon
                             return (
                            <tr key={doc.id} className="hover:bg-indigo-50/30 dark:hover:bg-indigo-900/10 transition-colors group">
                              <td className="px-6 py-4 font-medium text-slate-900 dark:text-slate-100 flex items-center gap-3">
                                <div className="p-2 bg-indigo-50 dark:bg-indigo-900/20 text-indigo-600 dark:text-indigo-400 rounded-lg">
                                  <FileText className="w-4 h-4" />
                                </div>
                                <span className="truncate max-w-[200px]" title={doc.filename}>{doc.filename}</span>
                              </td>
                              <td className="px-6 py-4">
                                <div className={cn("inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium border", status.bg, status.color, status.border)}>
                                  <StatusIcon className={cn("w-3 h-3", status.spin && "animate-spin")} />
                                  {status.label}
                                </div>
                              </td>
                              <td className="px-6 py-4 text-slate-600 dark:text-slate-400">{doc.chunk_count || '-'}</td>
                              <td className="px-6 py-4 text-slate-500 dark:text-slate-500 font-mono text-xs">{formatFileSize(doc.file_size)}</td>
                              <td className="px-6 py-4 text-slate-500 dark:text-slate-500">{formatDate(doc.created_at)}</td>
                              <td className="px-6 py-4 text-right flex items-center justify-end gap-2">
                                <DocumentDetailDialog 
                                  document={doc} 
                                  trigger={
                                    <button
                                      className="text-slate-400 hover:text-indigo-600 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 transition-colors p-2 rounded-lg opacity-0 group-hover:opacity-100"
                                      title="预览内容"
                                    >
                                      <Eye className="w-4 h-4" />
                                    </button>
                                  }
                                />
                                <button
                                  onClick={() => deleteDocument(doc.id)}
                                  className="text-slate-400 hover:text-red-500 transition-colors p-2 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-lg opacity-0 group-hover:opacity-100"
                                  title="删除文档"
                                >
                                  <Trash2 className="w-4 h-4" />
                                </button>
                              </td>
                            </tr>
                          )})}
                        </tbody>
                      </table>
                    </div>
                  )}
                </>
              )}
            </div>
          )}

          {/* 检索测试 */}
          {activeTab === 'retrieval' && (
            <div className="max-w-4xl mx-auto animate-in fade-in slide-in-from-bottom-2 duration-500">
              <div className="bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm p-8 text-center relative overflow-hidden">
                <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-indigo-500 via-purple-500 to-pink-500" />
                
                <div className="mb-8">
                  <div className="w-16 h-16 bg-indigo-50 dark:bg-indigo-900/20 text-indigo-600 dark:text-indigo-400 rounded-2xl flex items-center justify-center mx-auto mb-4 shadow-sm">
                    <Sparkles className="w-8 h-8" />
                  </div>
                  <h3 className="text-xl font-bold text-slate-900 dark:text-white">语义检索测试</h3>
                  <p className="text-slate-500 dark:text-slate-400 mt-2">
                    输入您的问题，模拟 RAG 系统的检索召回过程
                  </p>
                </div>

                <div className="max-w-2xl mx-auto relative mb-10">
                  <div className={cn(
                    "flex items-center bg-white dark:bg-slate-800 border-2 border-slate-100 dark:border-slate-700 rounded-2xl p-2 shadow-sm transition-all duration-300",
                    "focus-within:border-indigo-500 dark:focus-within:border-indigo-500 focus-within:ring-4 focus-within:ring-indigo-50/50 dark:focus-within:ring-indigo-900/20 focus-within:shadow-md"
                  )}>
                    <Search className="w-5 h-5 text-slate-400 ml-3" />
                    <input
                      type="text"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                      placeholder="例如：MimirQ 支持哪些文档格式？"
                      className="flex-1 px-4 py-3 bg-transparent outline-none text-slate-900 dark:text-white placeholder:text-slate-400 text-lg"
                    />
                    <Button
                      onClick={handleSearch}
                      disabled={isSearching || !searchQuery.trim()}
                      className="rounded-xl px-6 h-12 text-base font-medium bg-indigo-600 hover:bg-indigo-700 shadow-lg shadow-indigo-200 dark:shadow-indigo-900/20"
                    >
                      {isSearching ? <Loader2 className="w-5 h-5 animate-spin" /> : "开始检索"}
                    </Button>
                  </div>
                </div>

                {searchResults.length > 0 && (
                  <div className="text-left space-y-4 animate-in fade-in slide-in-from-bottom-4">
                    <div className="flex items-center justify-between px-2">
                      <h4 className="text-sm font-semibold text-slate-900 dark:text-white">召回结果</h4>
                      <span className="text-xs text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-800 px-2 py-1 rounded-full">Top 3</span>
                    </div>
                    {searchResults.map((result, index) => (
                      <div
                        key={result.id}
                        className="group p-5 bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-700 rounded-xl hover:border-indigo-300 dark:hover:border-indigo-600 hover:shadow-md hover:shadow-indigo-50 dark:hover:shadow-indigo-900/10 transition-all duration-300 relative overflow-hidden"
                      >
                         <div className="absolute left-0 top-0 bottom-0 w-1 bg-indigo-500 opacity-0 group-hover:opacity-100 transition-opacity" />
                        <div className="flex items-start gap-4">
                          <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-indigo-50 dark:bg-indigo-900/20 text-indigo-600 dark:text-indigo-400 flex items-center justify-center font-bold text-sm">
                            {index + 1}
                          </div>
                          <div className="flex-1">
                            <p className="text-slate-800 dark:text-slate-200 leading-relaxed text-sm mb-3">
                              {result.content}
                            </p>
                            <div className="flex items-center gap-3 text-xs">
                              <span className="flex items-center gap-1 text-slate-500 dark:text-slate-400 bg-slate-100 dark:bg-slate-800 px-2 py-1 rounded-md">
                                <FileIcon className="w-3 h-3" />
                                {result.source}
                              </span>
                              <span className="text-slate-300 dark:text-slate-600">|</span>
                              <span className="font-medium text-indigo-600 dark:text-indigo-400">相似度 {(result.score * 100).toFixed(0)}%</span>
                            </div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}
              </div>
            </div>
          )}

          {/* 设置 */}
          {activeTab === 'settings' && (
            <div className="max-w-3xl mx-auto animate-in fade-in slide-in-from-bottom-2 duration-500">
              <div className="bg-white dark:bg-slate-900 rounded-xl border border-slate-200 dark:border-slate-800 shadow-sm overflow-hidden">
                <div className="p-6 border-b border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-900/50">
                  <h3 className="text-lg font-bold text-slate-900 dark:text-white">知识库参数配置</h3>
                  <p className="text-sm text-slate-500 dark:text-slate-400 mt-1">
                    调整 Embedding 模型、检索策略及相似度阈值
                  </p>
                </div>

                <div className="p-8 space-y-8">
                  {/* Embedding 模型 */}
                  <div className="space-y-3">
                    <label className="text-sm font-semibold text-slate-900 dark:text-slate-200">
                      Embedding 模型
                    </label>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                      {['text-embedding-v3', 'text-embedding-3-small', 'bge-large-zh'].map((model) => (
                        <div key={model} className="relative">
                          <input type="radio" name="model" id={model} className="peer sr-only" defaultChecked={model === 'text-embedding-v3'} />
                          <label
                            htmlFor={model}
                            className="flex flex-col p-4 border-2 border-slate-100 dark:border-slate-800 rounded-xl cursor-pointer transition-all hover:border-slate-300 dark:hover:border-slate-600 peer-checked:border-indigo-500 dark:peer-checked:border-indigo-500 peer-checked:bg-indigo-50/30 dark:peer-checked:bg-indigo-900/10"
                          >
                            <span className="font-medium text-sm text-slate-900 dark:text-white">{model}</span>
                            <span className="text-xs text-slate-500 dark:text-slate-400 mt-1">768 维 / 中英支持</span>
                          </label>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="h-px bg-slate-100 dark:bg-slate-800" />

                  {/* 检索模式 */}
                  <div className="space-y-3">
                     <label className="text-sm font-semibold text-slate-900 dark:text-slate-200">
                      检索模式
                    </label>
                    <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
                      {[
                        { value: 'vector', label: '向量检索', desc: '基于语义相似度，适合模糊匹配', icon: Zap },
                        { value: 'fulltext', label: '全文检索', desc: '基于关键词匹配，适合专有名词', icon: FileText },
                        { value: 'hybrid', label: '混合检索', desc: '向量 + 全文加权，效果最佳', icon: Layers },
                      ].map((mode) => (
                        <div key={mode.value} className="relative">
                          <input type="radio" name="retrieval_mode" id={mode.value} className="peer sr-only" defaultChecked={mode.value === 'hybrid'} />
                          <label
                            htmlFor={mode.value}
                            className="flex flex-col p-4 border-2 border-slate-100 dark:border-slate-800 rounded-xl cursor-pointer transition-all hover:border-slate-300 dark:hover:border-slate-600 peer-checked:border-indigo-500 dark:peer-checked:border-indigo-500 peer-checked:bg-indigo-50/30 dark:peer-checked:bg-indigo-900/10 h-full"
                          >
                            <div className="flex items-center gap-2 mb-2">
                              <mode.icon className="w-4 h-4 text-indigo-600 dark:text-indigo-400" />
                              <span className="font-medium text-sm text-slate-900 dark:text-white">{mode.label}</span>
                            </div>
                            <span className="text-xs text-slate-500 dark:text-slate-400 leading-relaxed">
                              {mode.desc}
                            </span>
                          </label>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="h-px bg-slate-100 dark:bg-slate-800" />

                  {/* 阈值参数 */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                    <div className="space-y-3">
                      <div className="flex justify-between">
                         <label className="text-sm font-semibold text-slate-900 dark:text-slate-200">召回数量 (Top K)</label>
                         <span className="text-sm font-mono text-indigo-600 dark:text-indigo-400">5</span>
                      </div>
                      <input type="range" min="1" max="20" defaultValue="5" className="w-full h-2 bg-slate-100 dark:bg-slate-800 rounded-lg appearance-none cursor-pointer accent-indigo-600" />
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        单次检索返回的最大片段数，建议 3-8 之间
                      </p>
                    </div>

                    <div className="space-y-3">
                      <div className="flex justify-between">
                         <label className="text-sm font-semibold text-slate-900 dark:text-slate-200">相似度阈值</label>
                         <span className="text-sm font-mono text-indigo-600 dark:text-indigo-400">0.7</span>
                      </div>
                      <input type="range" min="0" max="1" step="0.1" defaultValue="0.7" className="w-full h-2 bg-slate-100 dark:bg-slate-800 rounded-lg appearance-none cursor-pointer accent-indigo-600" />
                      <p className="text-xs text-slate-500 dark:text-slate-400">
                        过滤低相关度的结果，值越大匹配越精准
                      </p>
                    </div>
                  </div>
                </div>

                <div className="p-6 bg-slate-50 dark:bg-slate-900 border-t border-slate-100 dark:border-slate-800 flex justify-end">
                   <Button className="gap-2 bg-slate-900 dark:bg-white text-white dark:text-slate-900 hover:bg-slate-800 dark:hover:bg-slate-100">
                      <Settings className="w-4 h-4" />
                      保存所有更改
                    </Button>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}

// 文档卡片组件
function DocumentCard({ doc, getStatusConfig, onDelete }: { doc: Document, getStatusConfig: any, onDelete: (id: string) => void }) {
  const status = getStatusConfig(doc.status)
  const StatusIcon = status.icon
  const parserLabel = doc.metadata?.parser_backend ? getParserLabel(doc.metadata.parser_backend as string) : null

  return (
    <div className="group relative bg-white dark:bg-slate-900 rounded-2xl border border-slate-200 dark:border-slate-800 shadow-sm hover:shadow-md hover:border-indigo-300 dark:hover:border-indigo-600 transition-all duration-300 flex flex-col overflow-hidden">
      {/* 顶部装饰条 */}
      <div className={cn("h-1.5 w-full", status.bg.replace('bg-', 'bg-').replace('50', '500').replace('/10', ''))} />
      
      <div className="p-5 flex-1 flex flex-col">
        <div className="flex items-start justify-between mb-4">
          <div className="w-12 h-12 rounded-xl bg-indigo-50 dark:bg-indigo-900/20 text-indigo-600 dark:text-indigo-400 flex items-center justify-center">
            <FileText className="w-6 h-6" />
          </div>
          <div className={cn("px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider border", status.bg, status.color, status.border)}>
             {status.label}
          </div>
        </div>

        <h3 className="font-semibold text-slate-900 dark:text-white line-clamp-2 mb-2 min-h-[2.5rem]" title={doc.filename}>
          {doc.filename}
        </h3>

        <div className="space-y-2 mt-auto">
          <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
            <span>大小</span>
            <span className="font-mono">{formatFileSize(doc.file_size)}</span>
          </div>
          <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
            <span>分块</span>
            <span className="font-mono">{doc.chunk_count || '-'}</span>
          </div>
           <div className="flex items-center justify-between text-xs text-slate-500 dark:text-slate-400">
            <span>时间</span>
            <span>{formatDate(doc.created_at).split(' ')[0]}</span>
          </div>
        </div>
      </div>
      
      {/* 底部操作栏 - Hover 显示 */}
      <div className="px-5 py-3 border-t border-slate-100 dark:border-slate-800 bg-slate-50/50 dark:bg-slate-800/50 flex items-center justify-between opacity-100 lg:opacity-0 lg:group-hover:opacity-100 transition-opacity">
         <span className="text-[10px] text-slate-400 dark:text-slate-500 font-medium truncate max-w-[80px]">
           {parserLabel || 'Auto'}
         </span>
         <div className="flex items-center gap-1">
           <DocumentDetailDialog 
             document={doc}
             trigger={
               <button 
                 className="p-1.5 text-slate-400 dark:text-slate-500 hover:text-indigo-600 dark:hover:text-indigo-400 hover:bg-indigo-50 dark:hover:bg-indigo-900/20 rounded-md transition-colors"
                 title="预览内容"
                 onClick={(e) => e.stopPropagation()}
               >
                 <Eye className="w-4 h-4" />
               </button>
             }
           />
           <button 
             className="p-1.5 text-slate-400 dark:text-slate-500 hover:text-red-600 dark:hover:text-red-400 hover:bg-red-50 dark:hover:bg-red-900/20 rounded-md transition-colors"
             onClick={(e) => {
               e.stopPropagation()
               onDelete(doc.id)
             }}
             title="删除文档"
           >
             <Trash2 className="w-4 h-4" />
           </button>
         </div>
      </div>

       {/* 进度条 (处理中) */}
       {doc.status === 'processing' && (
          <div className="absolute bottom-0 left-0 right-0 h-1 bg-slate-100 dark:bg-slate-800">
            <div 
              className="h-full bg-indigo-500 animate-pulse" 
              style={{ width: `${doc.processing_progress || 60}%` }} 
            />
          </div>
        )}
    </div>
  )
}

// 空状态组件
function EmptyState({ onUpload }: { onUpload: (e: React.ChangeEvent<HTMLInputElement>) => void }) {
  return (
    <div className="flex flex-col items-center justify-center min-h-[400px] border-2 border-dashed border-slate-200 dark:border-slate-800 rounded-3xl bg-slate-50/50 dark:bg-slate-900/50 hover:bg-indigo-50/30 dark:hover:bg-indigo-900/10 hover:border-indigo-200 dark:hover:border-indigo-800 transition-all group">
      <div className="w-20 h-20 bg-white dark:bg-slate-800 rounded-full shadow-sm flex items-center justify-center mb-6 group-hover:scale-110 transition-transform duration-300">
        <div className="w-16 h-16 bg-indigo-50 dark:bg-indigo-900/20 rounded-full flex items-center justify-center">
          <Upload className="w-8 h-8 text-indigo-600 dark:text-indigo-400" />
        </div>
      </div>
      <h3 className="text-xl font-bold text-slate-900 dark:text-white mb-2">知识库空空如也</h3>
      <p className="text-slate-500 dark:text-slate-400 max-w-md text-center mb-8">
        上传您的第一份文档，MimirQ 将自动解析并构建专属知识索引
      </p>
      <label>
        <Button size="lg" className="gap-2 bg-indigo-600 hover:bg-indigo-700 shadow-lg shadow-indigo-200 dark:shadow-indigo-900/20 text-white" asChild>
          <span>
            <Upload className="w-5 h-5" />
            立即上传文档
          </span>
        </Button>
        <input
          type="file"
          multiple
          accept=".pdf,.txt,.md,.xlsx,.xls,.docx,.doc"
          className="hidden"
          onChange={onUpload}
        />
      </label>
      <p className="text-xs text-slate-400 dark:text-slate-500 mt-4">
        支持 PDF, TXT, Markdown, Excel, Word 等常见格式
      </p>
    </div>
  )
}
