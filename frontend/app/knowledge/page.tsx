'use client'

/**
 * 知识库管理页面
 * 参考 Dify 设计风格
 * 功能：文档列表、检索测试、知识库设置
 */
import { useState, useCallback } from 'react'
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
  ChevronRight,
  AlertCircle,
  Sparkles,
  Send,
} from 'lucide-react'
import { Navbar } from '@/components/navbar'
import { Button } from '@/components/ui/button'
import { useDocuments } from '@/hooks/use-documents'
import { formatFileSize, formatDate, cn } from '@/lib/utils'
import { StatCard, StatsGrid } from '@/components/ui/stats-card'
import { getParserLabel } from '@/lib/parser-options'
import { getChunkStrategyLabel } from '@/lib/chunk-strategies'
import type { Document } from '@/types'

// Tab 类型
type TabType = 'documents' | 'retrieval' | 'settings'

export default function KnowledgePage() {
  const { documents, isLoading, uploadDocument, deleteDocument, loadDocuments } = useDocuments()
  const [activeTab, setActiveTab] = useState<TabType>('documents')
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
      // TODO: 调用检索 API
      // const results = await documentApi.search(searchQuery)
      // setSearchResults(results)

      // 模拟搜索结果
      await new Promise(resolve => setTimeout(resolve, 1000))
      setSearchResults([
        { id: '1', content: '这是匹配到的第一段内容...', score: 0.95, source: 'document1.pdf' },
        { id: '2', content: '这是匹配到的第二段内容...', score: 0.87, source: 'document2.pdf' },
        { id: '3', content: '这是匹配到的第三段内容...', score: 0.76, source: 'document1.pdf' },
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
        return { icon: CheckCircle, color: 'text-green-500', bg: 'bg-green-50', label: '已就绪' }
      case 'failed':
        return { icon: XCircle, color: 'text-red-500', bg: 'bg-red-50', label: '失败' }
      case 'processing':
      case 'pending':
        return { icon: Loader2, color: 'text-blue-500', bg: 'bg-blue-50', label: '处理中', spin: true }
      default:
        return { icon: Clock, color: 'text-gray-400', bg: 'bg-gray-50', label: '等待' }
    }
  }

  return (
    <div className="flex h-screen overflow-hidden bg-gray-50">
      <Navbar />

      <main className="flex-1 flex flex-col overflow-hidden">
        {/* 顶部标题栏 */}
        <header className="bg-white border-b px-6 py-4 flex-shrink-0">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-4">
              <div className="w-11 h-11 bg-gradient-to-br from-blue-500 to-cyan-600 rounded-xl flex items-center justify-center shadow-lg shadow-blue-200">
                <Database className="w-5 h-5 text-white" />
              </div>
              <div>
                <h1 className="text-xl font-bold text-gray-900">知识库</h1>
                <p className="text-sm text-gray-500">
                  管理已嵌入的文档数据，测试检索效果
                </p>
              </div>
            </div>

            <div className="flex items-center gap-3">
              <Button
                variant="outline"
                size="sm"
                onClick={() => loadDocuments()}
                className="gap-2"
              >
                <RefreshCw className="w-4 h-4" />
                刷新
              </Button>
              <label>
                <Button className="gap-2 bg-blue-600 hover:bg-blue-700" asChild>
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
        </header>

        {/* 统计卡片区 */}
        <div className="px-6 py-4 bg-white border-b">
          <StatsGrid>
            <StatCard
              icon={FileStack}
              label="文档总数"
              value={totalDocs}
              color="blue"
            />
            <StatCard
              icon={CheckCircle}
              label="已就绪"
              value={completedDocs}
              color="green"
            />
            <StatCard
              icon={Layers}
              label="分段总数"
              value={totalChunks.toLocaleString()}
              color="purple"
            />
            <StatCard
              icon={HardDrive}
              label="存储空间"
              value={formatFileSize(totalSize)}
              color="orange"
            />
            {(processingDocs > 0 || failedDocs > 0) && (
              <StatCard
                icon={failedDocs > 0 ? AlertCircle : Loader2}
                label={failedDocs > 0 ? '需要注意' : '处理中'}
                value={failedDocs > 0 ? failedDocs : processingDocs}
                color={failedDocs > 0 ? 'red' : 'gray'}
              />
            )}
          </StatsGrid>
        </div>

        {/* Tab 切换 */}
        <div className="px-6 bg-white border-b">
          <div className="flex gap-1">
            {[
              { key: 'documents' as TabType, label: '文档列表', icon: FileText },
              { key: 'retrieval' as TabType, label: '检索测试', icon: Search },
              { key: 'settings' as TabType, label: '设置', icon: Settings },
            ].map((tab) => (
              <button
                key={tab.key}
                onClick={() => setActiveTab(tab.key)}
                className={cn(
                  'flex items-center gap-2 px-4 py-3 text-sm font-medium border-b-2 transition-all',
                  activeTab === tab.key
                    ? 'text-blue-600 border-blue-600'
                    : 'text-gray-500 border-transparent hover:text-gray-700 hover:border-gray-300'
                )}
              >
                <tab.icon className="w-4 h-4" />
                {tab.label}
              </button>
            ))}
          </div>
        </div>

        {/* 内容区 */}
        <div className="flex-1 overflow-y-auto p-6">
          {/* 文档列表 Tab */}
          {activeTab === 'documents' && (
            <div className="max-w-5xl mx-auto">
              {isLoading && documents.length === 0 ? (
                <div className="flex items-center justify-center h-64">
                  <Loader2 className="w-8 h-8 animate-spin text-gray-400" />
                </div>
              ) : documents.length === 0 ? (
                <div className="text-center py-16">
                  <div className="w-20 h-20 mx-auto mb-4 bg-gray-100 rounded-2xl flex items-center justify-center">
                    <FileText className="w-10 h-10 text-gray-300" />
                  </div>
                  <h3 className="text-lg font-medium text-gray-700 mb-2">暂无文档</h3>
                  <p className="text-gray-400 text-sm mb-4">
                    上传文档后，系统将自动进行解析和向量化处理
                  </p>
                  <label>
                    <Button className="gap-2" asChild>
                      <span>
                        <Upload className="w-4 h-4" />
                        上传第一个文档
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
              ) : (
                <div className="bg-white rounded-xl border shadow-sm overflow-hidden">
                  {/* 表头 */}
                  <div className="grid grid-cols-12 gap-4 px-6 py-3 bg-gray-50 border-b text-xs font-medium text-gray-500 uppercase tracking-wider">
                    <div className="col-span-5">文档名称</div>
                    <div className="col-span-2">状态</div>
                    <div className="col-span-2">分段数</div>
                    <div className="col-span-2">更新时间</div>
                    <div className="col-span-1">操作</div>
                  </div>

                  {/* 文档列表 */}
                  <div className="divide-y">
                    {documents.map((doc) => {
                      const statusConfig = getStatusConfig(doc.status)
                      const StatusIcon = statusConfig.icon
                      const parserLabel = doc.metadata?.parser_backend
                        ? getParserLabel(doc.metadata.parser_backend as string)
                        : null
                      const chunkStrategyLabel = doc.metadata?.chunk_strategy
                        ? getChunkStrategyLabel(doc.metadata.chunk_strategy as string)
                        : null

                      return (
                        <div
                          key={doc.id}
                          className={cn(
                            'grid grid-cols-12 gap-4 px-6 py-4 items-center hover:bg-gray-50 transition-colors',
                            selectedDocId === doc.id && 'bg-blue-50'
                          )}
                          onClick={() => setSelectedDocId(doc.id === selectedDocId ? null : doc.id)}
                        >
                          {/* 文档名称 */}
                          <div className="col-span-5 flex items-center gap-3 min-w-0">
                            <div className="p-2 bg-gray-100 rounded-lg flex-shrink-0">
                              <FileText className="w-5 h-5 text-gray-500" />
                            </div>
                            <div className="min-w-0">
                              <p className="text-sm font-medium text-gray-900 truncate">
                                {doc.filename}
                              </p>
                              <div className="flex items-center gap-2 text-xs text-gray-400">
                                <span>{formatFileSize(doc.file_size)}</span>
                                {parserLabel && (
                                  <>
                                    <span>·</span>
                                    <span>{parserLabel}</span>
                                  </>
                                )}
                                {chunkStrategyLabel && (
                                  <>
                                    <span>·</span>
                                    <span>{chunkStrategyLabel}</span>
                                  </>
                                )}
                              </div>
                            </div>
                          </div>

                          {/* 状态 */}
                          <div className="col-span-2">
                            <div className={cn(
                              'inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium',
                              statusConfig.bg, statusConfig.color
                            )}>
                              <StatusIcon className={cn('w-3.5 h-3.5', statusConfig.spin && 'animate-spin')} />
                              {statusConfig.label}
                            </div>
                            {doc.status === 'processing' && doc.processing_progress && (
                              <div className="mt-1.5 w-full max-w-[100px]">
                                <div className="h-1 bg-gray-200 rounded-full overflow-hidden">
                                  <div
                                    className="h-full bg-blue-500 rounded-full transition-all"
                                    style={{ width: `${doc.processing_progress}%` }}
                                  />
                                </div>
                              </div>
                            )}
                          </div>

                          {/* 分段数 */}
                          <div className="col-span-2">
                            <span className="text-sm text-gray-700">
                              {doc.status === 'completed' ? (
                                <span className="font-medium">{doc.chunk_count || 0}</span>
                              ) : (
                                <span className="text-gray-400">-</span>
                              )}
                            </span>
                          </div>

                          {/* 更新时间 */}
                          <div className="col-span-2">
                            <span className="text-sm text-gray-500">
                              {formatDate(doc.created_at)}
                            </span>
                          </div>

                          {/* 操作 */}
                          <div className="col-span-1">
                            <button
                              onClick={(e) => {
                                e.stopPropagation()
                                deleteDocument(doc.id)
                              }}
                              disabled={doc.status === 'processing'}
                              className="p-2 text-gray-400 hover:text-red-500 hover:bg-red-50 rounded-lg transition-all disabled:opacity-50 disabled:cursor-not-allowed"
                            >
                              <Trash2 className="w-4 h-4" />
                            </button>
                          </div>
                        </div>
                      )
                    })}
                  </div>
                </div>
              )}
            </div>
          )}

          {/* 检索测试 Tab */}
          {activeTab === 'retrieval' && (
            <div className="max-w-4xl mx-auto">
              <div className="bg-white rounded-xl border shadow-sm p-6">
                <div className="flex items-center gap-3 mb-4">
                  <Sparkles className="w-5 h-5 text-blue-500" />
                  <h3 className="text-lg font-medium text-gray-900">检索测试</h3>
                </div>
                <p className="text-sm text-gray-500 mb-6">
                  输入问题测试知识库的检索效果，查看匹配到的文档片段和相关度分数
                </p>

                {/* 搜索框 */}
                <div className="flex gap-3 mb-6">
                  <div className="flex-1 relative">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-5 h-5 text-gray-400" />
                    <input
                      type="text"
                      value={searchQuery}
                      onChange={(e) => setSearchQuery(e.target.value)}
                      onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
                      placeholder="输入问题进行检索测试..."
                      className="w-full pl-10 pr-4 py-3 border border-gray-200 rounded-xl focus:border-blue-500 focus:ring-2 focus:ring-blue-100 outline-none transition-all"
                    />
                  </div>
                  <Button
                    onClick={handleSearch}
                    disabled={isSearching || !searchQuery.trim()}
                    className="gap-2 px-6"
                  >
                    {isSearching ? (
                      <Loader2 className="w-4 h-4 animate-spin" />
                    ) : (
                      <Send className="w-4 h-4" />
                    )}
                    测试
                  </Button>
                </div>

                {/* 搜索结果 */}
                {searchResults.length > 0 && (
                  <div className="space-y-4">
                    <h4 className="text-sm font-medium text-gray-700">
                      匹配结果 ({searchResults.length})
                    </h4>
                    {searchResults.map((result, index) => (
                      <div
                        key={result.id}
                        className="p-4 border border-gray-200 rounded-xl hover:border-blue-200 hover:bg-blue-50/30 transition-all"
                      >
                        <div className="flex items-start justify-between gap-4">
                          <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2 mb-2">
                              <span className="text-xs font-medium text-blue-600 bg-blue-100 px-2 py-0.5 rounded">
                                #{index + 1}
                              </span>
                              <span className="text-xs text-gray-400">
                                来源: {result.source}
                              </span>
                            </div>
                            <p className="text-sm text-gray-700 leading-relaxed">
                              {result.content}
                            </p>
                          </div>
                          <div className="flex-shrink-0 text-right">
                            <div className="text-lg font-bold text-blue-600">
                              {(result.score * 100).toFixed(0)}%
                            </div>
                            <div className="text-xs text-gray-400">相关度</div>
                          </div>
                        </div>
                      </div>
                    ))}
                  </div>
                )}

                {searchResults.length === 0 && searchQuery && !isSearching && (
                  <div className="text-center py-8 text-gray-400">
                    <Search className="w-8 h-8 mx-auto mb-2 opacity-50" />
                    <p className="text-sm">点击测试按钮开始检索</p>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* 设置 Tab */}
          {activeTab === 'settings' && (
            <div className="max-w-2xl mx-auto">
              <div className="bg-white rounded-xl border shadow-sm p-6">
                <h3 className="text-lg font-medium text-gray-900 mb-6">知识库设置</h3>

                <div className="space-y-6">
                  {/* Embedding 模型 */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      Embedding 模型
                    </label>
                    <select className="w-full px-3 py-2 border border-gray-200 rounded-lg bg-white focus:border-blue-500 focus:ring-2 focus:ring-blue-100 outline-none">
                      <option>text-embedding-v3 (阿里云)</option>
                      <option>text-embedding-3-small (OpenAI)</option>
                      <option>bge-large-zh (本地)</option>
                    </select>
                    <p className="mt-1 text-xs text-gray-400">
                      更换模型后需要重新处理所有文档
                    </p>
                  </div>

                  {/* 检索模式 */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      检索模式
                    </label>
                    <div className="grid grid-cols-3 gap-3">
                      {[
                        { value: 'vector', label: '向量检索', desc: '语义相似度匹配' },
                        { value: 'fulltext', label: '全文检索', desc: '关键词精确匹配' },
                        { value: 'hybrid', label: '混合检索', desc: '综合两种方式' },
                      ].map((mode) => (
                        <label
                          key={mode.value}
                          className="flex flex-col p-3 border border-gray-200 rounded-lg cursor-pointer hover:border-blue-200 transition-all"
                        >
                          <div className="flex items-center gap-2">
                            <input
                              type="radio"
                              name="retrieval_mode"
                              value={mode.value}
                              defaultChecked={mode.value === 'hybrid'}
                              className="text-blue-600"
                            />
                            <span className="text-sm font-medium">{mode.label}</span>
                          </div>
                          <span className="text-xs text-gray-400 mt-1 ml-5">
                            {mode.desc}
                          </span>
                        </label>
                      ))}
                    </div>
                  </div>

                  {/* Top K */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      召回数量 (Top K)
                    </label>
                    <input
                      type="number"
                      defaultValue={5}
                      min={1}
                      max={20}
                      className="w-32 px-3 py-2 border border-gray-200 rounded-lg focus:border-blue-500 focus:ring-2 focus:ring-blue-100 outline-none"
                    />
                    <p className="mt-1 text-xs text-gray-400">
                      每次检索返回的最大文档片段数量
                    </p>
                  </div>

                  {/* 相似度阈值 */}
                  <div>
                    <label className="block text-sm font-medium text-gray-700 mb-2">
                      相似度阈值
                    </label>
                    <input
                      type="number"
                      defaultValue={0.7}
                      min={0}
                      max={1}
                      step={0.1}
                      className="w-32 px-3 py-2 border border-gray-200 rounded-lg focus:border-blue-500 focus:ring-2 focus:ring-blue-100 outline-none"
                    />
                    <p className="mt-1 text-xs text-gray-400">
                      低于此阈值的结果将被过滤
                    </p>
                  </div>

                  <div className="pt-4 border-t">
                    <Button className="gap-2">
                      <Settings className="w-4 h-4" />
                      保存设置
                    </Button>
                  </div>
                </div>
              </div>
            </div>
          )}
        </div>
      </main>
    </div>
  )
}
