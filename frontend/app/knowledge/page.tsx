'use client'

/**
 * 知识库管理页面
 * 优化版：卡片视图、视觉增强、交互优化
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
  Zap
} from 'lucide-react'
import { Navbar } from '@/components/navbar'
import { Button } from '@/components/ui/button'
import { useDocuments } from '@/hooks/use-documents'
import { formatFileSize, formatDate, cn } from '@/lib/utils'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { getParserLabel } from '@/lib/parser-options'
import { getChunkStrategyLabel } from '@/lib/chunk-strategies'
import { ChunkStrategyDropdown } from '@/components/ui/chunk-strategy-dropdown'
import { useChunkStrategyPreference } from '@/contexts/chunk-strategy-context'
import type { Document } from '@/types'

// Tab 类型
type TabType = 'documents' | 'retrieval' | 'settings'
type ViewMode = 'grid' | 'list'

export default function KnowledgePage() {
  const { documents, isLoading, uploadDocument, deleteDocument, loadDocuments } = useDocuments()
  const [activeTab, setActiveTab] = useState<TabType>('documents')
  const [viewMode, setViewMode] = useState<ViewMode>('grid')
  const [selectedDocId, setSelectedDocId] = useState<string | null>(null)
  const { chunkStrategy, setChunkStrategy } = useChunkStrategyPreference()

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
        return { icon: CheckCircle, color: 'text-emerald-500', bg: 'bg-emerald-50', border: 'border-emerald-100', label: '已就绪' }
      case 'failed':
        return { icon: XCircle, color: 'text-red-500', bg: 'bg-red-50', border: 'border-red-100', label: '失败' }
      case 'processing':
      case 'pending':
        return { icon: Loader2, color: 'text-blue-500', bg: 'bg-blue-50', border: 'border-blue-100', label: '处理中', spin: true }
      default:
        return { icon: Clock, color: 'text-gray-400', bg: 'bg-gray-50', border: 'border-gray-100', label: '等待' }
    }
  }

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50/50">
      <Navbar />

      <main className="flex-1 flex flex-col overflow-hidden relative">
        {/* 背景装饰 */}
        <div className="absolute top-0 left-0 right-0 h-64 bg-gradient-to-b from-blue-50/50 to-transparent pointer-events-none" />

        {/* 顶部标题栏 */}
        <header className="px-8 py-6 flex-shrink-0 z-10">
          <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-4">
              <div className="w-12 h-12 bg-white rounded-2xl flex items-center justify-center shadow-sm border border-gray-100">
                <Database className="w-6 h-6 text-blue-600" />
              </div>
              <div>
                <h1 className="text-2xl font-bold text-gray-900 tracking-tight">知识库管理</h1>
                <p className="text-sm text-gray-500 mt-1">
                  管理您的文档资产，构建专属知识大脑
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3">
               <label>
                <Button className="gap-2 bg-blue-600 hover:bg-blue-700 shadow-lg shadow-blue-200 hover:shadow-blue-300 transition-all" size="lg" asChild>
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
          <div className="grid grid-cols-2 md:grid-cols-4 lg:grid-cols-5 gap-4">
            <StatCard
              icon={FileStack}
              label="文档总数"
              value={totalDocs}
              color="blue"
              className="bg-white/80 backdrop-blur-sm border-gray-100 shadow-sm"
            />
            <StatCard
              icon={CheckCircle}
              label="已就绪"
              value={completedDocs}
              color="green"
              className="bg-white/80 backdrop-blur-sm border-gray-100 shadow-sm"
            />
            <StatCard
              icon={Layers}
              label="知识分块"
              value={totalChunks.toLocaleString()}
              color="purple"
              className="bg-white/80 backdrop-blur-sm border-gray-100 shadow-sm"
            />
            <StatCard
              icon={HardDrive}
              label="存储占用"
              value={formatFileSize(totalSize)}
              color="orange"
              className="bg-white/80 backdrop-blur-sm border-gray-100 shadow-sm"
            />
            {(processingDocs > 0 || failedDocs > 0) && (
              <StatCard
                icon={failedDocs > 0 ? XCircle : Loader2}
                label={failedDocs > 0 ? '需关注' : '处理中'}
                value={failedDocs > 0 ? failedDocs : processingDocs}
                color={failedDocs > 0 ? 'red' : 'gray'}
                className="bg-white/80 backdrop-blur-sm border-gray-100 shadow-sm"
              />
            )}
          </div>
        </header>

        {/* 导航栏 & 工具栏 */}
        <div className="px-8 flex items-center justify-between border-b border-gray-200/60 bg-white/50 backdrop-blur-sm sticky top-0 z-20">
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
                    ? 'text-blue-600 border-blue-600 bg-blue-50/50'
                    : 'text-gray-500 border-transparent hover:text-gray-700 hover:bg-gray-50'
                )}
              >
                <tab.icon className={cn("w-4 h-4", activeTab === tab.key ? "text-blue-500" : "text-gray-400")} />
                {tab.label}
              </button>
            ))}
          </div>

          {activeTab === 'documents' && (
            <div className="flex items-center gap-2 py-2">
              <div className="w-56 mr-2">
                <ChunkStrategyDropdown value={chunkStrategy} onChange={setChunkStrategy} />
              </div>
              <div className="h-6 w-px bg-gray-200 mx-1" />
              <Button
                variant="ghost"
                size="sm"
                onClick={() => loadDocuments()}
                className="text-gray-500 hover:text-gray-700"
                title="刷新列表"
              >
                <RefreshCw className="w-4 h-4" />
              </Button>
               <Button
                variant="ghost"
                size="sm"
                onClick={() => window.open('/chunk-preview', '_blank')}
                className="text-gray-500 hover:text-gray-700"
                title="预览分块"
              >
                <Eye className="w-4 h-4" />
              </Button>
              <div className="bg-gray-100 p-1 rounded-lg flex gap-1">
                <button
                  onClick={() => setViewMode('grid')}
                  className={cn(
                    "p-1.5 rounded-md transition-all",
                    viewMode === 'grid' ? "bg-white shadow-sm text-blue-600" : "text-gray-400 hover:text-gray-600"
                  )}
                >
                  <LayoutGrid className="w-4 h-4" />
                </button>
                <button
                  onClick={() => setViewMode('list')}
                  className={cn(
                    "p-1.5 rounded-md transition-all",
                    viewMode === 'list' ? "bg-white shadow-sm text-blue-600" : "text-gray-400 hover:text-gray-600"
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
                <div className="flex flex-col items-center justify-center h-64 text-gray-400">
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
                    <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
                      <table className="w-full text-sm text-left">
                        <thead className="text-xs text-gray-500 uppercase bg-gray-50/80 border-b border-gray-100">
                          <tr>
                            <th className="px-6 py-4 font-medium">文档名称</th>
                            <th className="px-6 py-4 font-medium">状态</th>
                            <th className="px-6 py-4 font-medium">分块</th>
                            <th className="px-6 py-4 font-medium">大小</th>
                            <th className="px-6 py-4 font-medium">上传时间</th>
                            <th className="px-6 py-4 font-medium text-right">操作</th>
                          </tr>
                        </thead>
                        <tbody className="divide-y divide-gray-100">
                          {documents.map((doc) => {
                             const status = getStatusConfig(doc.status)
                             const StatusIcon = status.icon
                             return (
                            <tr key={doc.id} className="hover:bg-blue-50/30 transition-colors group">
                              <td className="px-6 py-4 font-medium text-gray-900 flex items-center gap-3">
                                <div className="p-2 bg-blue-50 text-blue-600 rounded-lg">
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
                              <td className="px-6 py-4 text-gray-600">{doc.chunk_count || '-'}</td>
                              <td className="px-6 py-4 text-gray-500 font-mono text-xs">{formatFileSize(doc.file_size)}</td>
                              <td className="px-6 py-4 text-gray-500">{formatDate(doc.created_at)}</td>
                              <td className="px-6 py-4 text-right">
                                <button
                                  onClick={() => deleteDocument(doc.id)}
                                  className="text-gray-400 hover:text-red-500 transition-colors p-2 hover:bg-red-50 rounded-lg opacity-0 group-hover:opacity-100"
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
              <div className="bg-white rounded-2xl border border-gray-200 shadow-sm p-8 text-center relative overflow-hidden">
                <div className="absolute top-0 left-0 w-full h-1 bg-gradient-to-r from-blue-500 via-purple-500 to-pink-500" />
                
                <div className="mb-8">
                  <div className="w-16 h-16 bg-blue-50 text-blue-600 rounded-2xl flex items-center justify-center mx-auto mb-4 shadow-sm">
                    <Sparkles className="w-8 h-8" />
                  </div>
                  <h3 className="text-xl font-bold text-gray-900">语义检索测试</h3>
                  <p className="text-gray-500 mt-2">
                    输入您的问题，模拟 RAG 系统的检索召回过程
                  </p>
                </div>

                <div className="max-w-2xl mx-auto relative mb-10">
                  <div className={cn(
                    "flex items-center bg-white border-2 border-gray-100 rounded-2xl p-2 shadow-sm transition-all duration-300",
                    "focus-within:border-blue-500 focus-within:ring-4 focus-within:ring-blue-50/50 focus-within:shadow-md"
                  )}>
                    <Search className="w-5 h-5 text-gray-400 ml-3" />
                    <input
                      type="text"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                      placeholder="例如：MimirQ 支持哪些文档格式？"
                      className="flex-1 px-4 py-3 bg-transparent outline-none text-gray-900 placeholder:text-gray-400 text-lg"
                    />
                    <Button
                      onClick={handleSearch}
                      disabled={isSearching || !searchQuery.trim()}
                      className="rounded-xl px-6 h-12 text-base font-medium bg-blue-600 hover:bg-blue-700 shadow-lg shadow-blue-200"
                    >
                      {isSearching ? <Loader2 className="w-5 h-5 animate-spin" /> : "开始检索"}
                    </Button>
                  </div>
                </div>

                {searchResults.length > 0 && (
                  <div className="text-left space-y-4 animate-in fade-in slide-in-from-bottom-4">
                    <div className="flex items-center justify-between px-2">
                      <h4 className="text-sm font-semibold text-gray-900">召回结果</h4>
                      <span className="text-xs text-gray-500 bg-gray-100 px-2 py-1 rounded-full">Top 3</span>
                    </div>
                    {searchResults.map((result, index) => (
                      <div
                        key={result.id}
                        className="group p-5 bg-white border border-gray-200 rounded-xl hover:border-blue-300 hover:shadow-md hover:shadow-blue-50 transition-all duration-300 relative overflow-hidden"
                      >
                         <div className="absolute left-0 top-0 bottom-0 w-1 bg-blue-500 opacity-0 group-hover:opacity-100 transition-opacity" />
                        <div className="flex items-start gap-4">
                          <div className="flex-shrink-0 w-8 h-8 rounded-lg bg-blue-50 text-blue-600 flex items-center justify-center font-bold text-sm">
                            {index + 1}
                          </div>
                          <div className="flex-1">
                            <p className="text-gray-800 leading-relaxed text-sm mb-3">
                              {result.content}
                            </p>
                            <div className="flex items-center gap-3 text-xs">
                              <span className="flex items-center gap-1 text-gray-500 bg-gray-100 px-2 py-1 rounded-md">
                                <FileIcon className="w-3 h-3" />
                                {result.source}
                              </span>
                              <span className="text-gray-400">|</span>
                              <span className="font-medium text-blue-600">相似度 {(result.score * 100).toFixed(0)}%</span>
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
              <div className="bg-white rounded-xl border border-gray-200 shadow-sm overflow-hidden">
                <div className="p-6 border-b border-gray-100 bg-gray-50/50">
                  <h3 className="text-lg font-bold text-gray-900">知识库参数配置</h3>
                  <p className="text-sm text-gray-500 mt-1">
                    调整 Embedding 模型、检索策略及相似度阈值
                  </p>
                </div>

                <div className="p-8 space-y-8">
                  {/* Embedding 模型 */}
                  <div className="space-y-3">
                    <label className="text-sm font-semibold text-gray-900">
                      Embedding 模型
                    </label>
                    <div className="grid grid-cols-1 sm:grid-cols-3 gap-4">
                      {['text-embedding-v3', 'text-embedding-3-small', 'bge-large-zh'].map((model) => (
                        <div key={model} className="relative">
                          <input type="radio" name="model" id={model} className="peer sr-only" defaultChecked={model === 'text-embedding-v3'} />
                          <label
                            htmlFor={model}
                            className="flex flex-col p-4 border-2 border-gray-100 rounded-xl cursor-pointer transition-all hover:border-gray-300 peer-checked:border-blue-500 peer-checked:bg-blue-50/30"
                          >
                            <span className="font-medium text-sm text-gray-900">{model}</span>
                            <span className="text-xs text-gray-500 mt-1">768 维 / 中英支持</span>
                          </label>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="h-px bg-gray-100" />

                  {/* 检索模式 */}
                  <div className="space-y-3">
                     <label className="text-sm font-semibold text-gray-900">
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
                            className="flex flex-col p-4 border-2 border-gray-100 rounded-xl cursor-pointer transition-all hover:border-gray-300 peer-checked:border-blue-500 peer-checked:bg-blue-50/30 h-full"
                          >
                            <div className="flex items-center gap-2 mb-2">
                              <mode.icon className="w-4 h-4 text-blue-600" />
                              <span className="font-medium text-sm text-gray-900">{mode.label}</span>
                            </div>
                            <span className="text-xs text-gray-500 leading-relaxed">
                              {mode.desc}
                            </span>
                          </label>
                        </div>
                      ))}
                    </div>
                  </div>

                  <div className="h-px bg-gray-100" />

                  {/* 阈值参数 */}
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-8">
                    <div className="space-y-3">
                      <div className="flex justify-between">
                         <label className="text-sm font-semibold text-gray-900">召回数量 (Top K)</label>
                         <span className="text-sm font-mono text-blue-600">5</span>
                      </div>
                      <input type="range" min="1" max="20" defaultValue="5" className="w-full h-2 bg-gray-100 rounded-lg appearance-none cursor-pointer accent-blue-600" />
                      <p className="text-xs text-gray-500">
                        单次检索返回的最大片段数，建议 3-8 之间
                      </p>
                    </div>

                    <div className="space-y-3">
                      <div className="flex justify-between">
                         <label className="text-sm font-semibold text-gray-900">相似度阈值</label>
                         <span className="text-sm font-mono text-blue-600">0.7</span>
                      </div>
                      <input type="range" min="0" max="1" step="0.1" defaultValue="0.7" className="w-full h-2 bg-gray-100 rounded-lg appearance-none cursor-pointer accent-blue-600" />
                      <p className="text-xs text-gray-500">
                        过滤低相关度的结果，值越大匹配越精准
                      </p>
                    </div>
                  </div>
                </div>

                <div className="p-6 bg-gray-50 border-t border-gray-100 flex justify-end">
                   <Button className="gap-2 bg-gray-900 text-white hover:bg-gray-800">
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
    <div className="group relative bg-white rounded-2xl border border-gray-200 shadow-sm hover:shadow-md hover:border-blue-300 transition-all duration-300 flex flex-col overflow-hidden">
      {/* 顶部装饰条 */}
      <div className={cn("h-1.5 w-full", status.bg.replace('bg-', 'bg-').replace('50', '500'))} />
      
      <div className="p-5 flex-1 flex flex-col">
        <div className="flex items-start justify-between mb-4">
          <div className="w-12 h-12 rounded-xl bg-blue-50 text-blue-600 flex items-center justify-center">
            <FileText className="w-6 h-6" />
          </div>
          <div className={cn("px-2.5 py-1 rounded-full text-[10px] font-bold uppercase tracking-wider border", status.bg, status.color, status.border)}>
             {status.label}
          </div>
        </div>

        <h3 className="font-semibold text-gray-900 line-clamp-2 mb-2 min-h-[2.5rem]" title={doc.filename}>
          {doc.filename}
        </h3>

        <div className="space-y-2 mt-auto">
          <div className="flex items-center justify-between text-xs text-gray-500">
            <span>大小</span>
            <span className="font-mono">{formatFileSize(doc.file_size)}</span>
          </div>
          <div className="flex items-center justify-between text-xs text-gray-500">
            <span>分块</span>
            <span className="font-mono">{doc.chunk_count || '-'}</span>
          </div>
           <div className="flex items-center justify-between text-xs text-gray-500">
            <span>时间</span>
            <span>{formatDate(doc.created_at).split(' ')[0]}</span>
          </div>
        </div>
      </div>
      
      {/* 底部操作栏 - Hover 显示 */}
      <div className="px-5 py-3 border-t border-gray-100 bg-gray-50/50 flex items-center justify-between opacity-100 lg:opacity-0 lg:group-hover:opacity-100 transition-opacity">
         <span className="text-[10px] text-gray-400 font-medium truncate max-w-[80px]">
           {parserLabel || 'Auto'}
         </span>
         <div className="flex items-center gap-1">
           <button 
             className="p-1.5 text-gray-400 hover:text-red-600 hover:bg-red-50 rounded-md transition-colors"
             onClick={(e) => {
               e.stopPropagation()
               onDelete(doc.id)
             }}
           >
             <Trash2 className="w-4 h-4" />
           </button>
         </div>
      </div>

       {/* 进度条 (处理中) */}
       {doc.status === 'processing' && (
          <div className="absolute bottom-0 left-0 right-0 h-1 bg-gray-100">
            <div 
              className="h-full bg-blue-500 animate-pulse" 
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
    <div className="flex flex-col items-center justify-center min-h-[400px] border-2 border-dashed border-gray-200 rounded-3xl bg-gray-50/50 hover:bg-blue-50/30 hover:border-blue-200 transition-all group">
      <div className="w-20 h-20 bg-white rounded-full shadow-sm flex items-center justify-center mb-6 group-hover:scale-110 transition-transform duration-300">
        <div className="w-16 h-16 bg-blue-50 rounded-full flex items-center justify-center">
          <Upload className="w-8 h-8 text-blue-600" />
        </div>
      </div>
      <h3 className="text-xl font-bold text-gray-900 mb-2">知识库空空如也</h3>
      <p className="text-gray-500 max-w-md text-center mb-8">
        上传您的第一份文档，MimirQ 将自动解析并构建专属知识索引
      </p>
      <label>
        <Button size="lg" className="gap-2 bg-blue-600 hover:bg-blue-700 shadow-lg shadow-blue-200" asChild>
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
      <p className="text-xs text-gray-400 mt-4">
        支持 PDF, TXT, Markdown, Excel, Word 等常见格式
      </p>
    </div>
  )
}
