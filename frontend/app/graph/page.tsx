'use client'

/**
 * 知识图谱可视化页面
 * 功能：上传 .graphml 文件并进行可视化展示
 * 优化：主流视觉设计、交互侧边栏、玻璃拟态控件、搜索与高级筛选
 */
import { useState, useRef, useMemo } from 'react'
import { Navbar } from '@/components/navbar'
import { Button } from '@/components/ui/button'
import { 
  Upload, 
  Share2, 
  Info, 
  RefreshCw, 
  ZoomIn, 
  ZoomOut, 
  Maximize, 
  Settings,
  MoreHorizontal,
  X,
  Database,
  Search,
  Layers,
  FileCode,
  MessageSquare,
  FileText,
  Type,
  Trash2,
  Edit
} from 'lucide-react'
import { GraphViewer, GraphViewerRef } from '@/components/graph/graph-viewer'
import { parseGraphML } from '@/lib/graph-parser'
import { cn } from '@/lib/utils'

export default function GraphPage() {
  const [isSidebarOpen, setSidebarOpen] = useState(true)
  const [graphData, setGraphData] = useState<{ nodes: any[], links: any[] }>({ nodes: [], links: [] })
  const [fileName, setFileName] = useState<string | null>(null)
  const [selectedNode, setSelectedNode] = useState<any | null>(null)
  const [isDetailOpen, setIsDetailOpen] = useState(false)
  
  // Search & Filter State
  const [searchTerm, setSearchTerm] = useState('')
  const [showEdgeLabels, setShowEdgeLabels] = useState(true)
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<Set<string>>(new Set())

  const graphRef = useRef<GraphViewerRef>(null)

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setFileName(file.name)
    const reader = new FileReader()
    reader.onload = (event) => {
      try {
        const content = event.target?.result as string
        const parsedData = parseGraphML(content)
        setGraphData(parsedData)
        setIsDetailOpen(false)
        setSelectedNode(null)
      } catch (error) {
        console.error('Failed to parse graph file:', error)
        alert('解析文件失败，请确保是有效的 GraphML 文件')
      }
    }
    reader.readAsText(file)
    e.target.value = '' 
  }

  const loadDemoData = () => {
    const nodes = Array.from({ length: 35 }, (_, i) => ({ 
      id: `n${i}`, 
      label: `Entity ${i}`, 
      group: Math.floor(Math.random() * 5),
      description: `This is a description for Entity ${i}. It contains some random knowledge data related to AI and knowledge graphs.`,
      source: `document_${Math.floor(i / 5)}.pdf`
    }))
    const links = []
    for (let i = 0; i < 45; i++) {
      links.push({
        source: `n${Math.floor(Math.random() * 35)}`,
        target: `n${Math.floor(Math.random() * 35)}`,
        label: i % 3 === 0 ? '包含' : i % 3 === 1 ? '引用' : '相关'
      })
    }
    setGraphData({ nodes, links })
    setFileName('demo-knowledge-graph.graphml')
    setIsDetailOpen(false)
    setSelectedNode(null)
  }

  const handleNodeClick = (node: any) => {
    setSelectedNode(node)
    setIsDetailOpen(true)
  }

  // Handle Search Input
  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const term = e.target.value
    setSearchTerm(term)
    
    if (!term.trim()) {
      setHighlightedNodeIds(new Set())
      return
    }

    const matches = graphData.nodes.filter(n => 
      (n.label && n.label.toLowerCase().includes(term.toLowerCase())) ||
      (n.id && n.id.toLowerCase().includes(term.toLowerCase()))
    )

    setHighlightedNodeIds(new Set(matches.map(n => n.id)))
    
    // Optionally focus on first match
    if (matches.length > 0 && graphRef.current) {
      graphRef.current.focusNode(matches[0].id)
    }
  }

  // Handle "Chat with Node" (Mock)
  const handleChatWithNode = () => {
    alert(`跳转到对话页面，预填 Prompt: "请告诉我关于 ${selectedNode.label} 的信息"`)
  }

  // Handle "View Source" (Mock)
  const handleViewSource = () => {
    alert(`打开源文档: ${selectedNode.source || 'Unknown Document'}`)
  }

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      <Navbar isSidebarOpen={isSidebarOpen} setSidebarOpen={setSidebarOpen} />
      
      <main className={cn(
        "flex-1 flex flex-col transition-all duration-300 relative",
        isSidebarOpen ? "ml-64" : "ml-0"
      )}>
        {/* Header - Transparent/Blurred */}
        <header className="absolute top-0 left-0 right-0 z-20 h-16 px-6 flex items-center justify-between bg-white/80 backdrop-blur-md border-b border-gray-200/50 pointer-events-none">
          <div className="flex items-center gap-3 pointer-events-auto">
            <div className="p-2 bg-gradient-to-br from-indigo-500 to-purple-600 rounded-lg shadow-sm">
              <Share2 className="w-5 h-5 text-white" />
            </div>
            <div>
              <h1 className="text-lg font-bold text-gray-900 tracking-tight">知识图谱</h1>
            </div>
          </div>
          
          {/* Centered Search Bar */}
          {graphData.nodes.length > 0 && (
            <div className="pointer-events-auto absolute left-1/2 -translate-x-1/2 top-1/2 -translate-y-1/2 w-full max-w-md">
              <div className="relative group">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 group-focus-within:text-indigo-500 transition-colors" />
                <input 
                  type="text" 
                  value={searchTerm}
                  onChange={handleSearchChange}
                  placeholder="搜索实体节点..."
                  className="w-full h-10 pl-10 pr-4 bg-gray-100/50 border border-gray-200 rounded-full text-sm focus:outline-none focus:ring-2 focus:ring-indigo-500/20 focus:border-indigo-500 transition-all backdrop-blur-sm shadow-sm"
                />
                {searchTerm && (
                   <div className="absolute right-3 top-1/2 -translate-y-1/2 text-xs text-gray-400">
                     {highlightedNodeIds.size} 匹配
                   </div>
                )}
              </div>
            </div>
          )}

          <div className="flex items-center gap-3 pointer-events-auto">
             {fileName && (
              <div className="hidden md:flex items-center gap-2 px-3 py-1.5 bg-gray-100/50 border border-gray-200 rounded-full text-xs text-gray-600 font-medium">
                <FileCode className="w-3.5 h-3.5 text-gray-400" />
                <span className="truncate max-w-[150px]">{fileName}</span>
              </div>
             )}

            <div className="h-6 w-px bg-gray-200 mx-1 hidden sm:block"></div>

            <Button variant="ghost" size="sm" onClick={loadDemoData} className="text-gray-600 hover:text-indigo-600 hover:bg-indigo-50">
              <RefreshCw className="w-4 h-4 mr-2" />
              演示
            </Button>

            <label>
              <Button size="sm" className="gap-2 bg-indigo-600 hover:bg-indigo-700 shadow-lg shadow-indigo-200 transition-all">
                <Upload className="w-4 h-4" />
                导入
              </Button>
              <input
                type="file"
                accept=".graphml,.xml"
                className="hidden"
                onChange={handleFileUpload}
              />
            </label>
          </div>
        </header>

        {/* Graph Area */}
        <div className="flex-1 relative bg-slate-50 overflow-hidden">
          {/* Dot Pattern Background */}
          <div className="absolute inset-0 z-0 opacity-[0.4]" style={{
             backgroundImage: 'radial-gradient(#cbd5e1 1px, transparent 1px)', 
             backgroundSize: '24px 24px'
          }}></div>

          {graphData.nodes.length > 0 ? (
            <GraphViewer 
              ref={graphRef}
              data={graphData} 
              onNodeClick={handleNodeClick}
              onBackgroundClick={() => setIsDetailOpen(false)}
              highlightedNodeIds={highlightedNodeIds}
              showEdgeLabels={showEdgeLabels}
            />
          ) : (
            <div className="absolute inset-0 flex flex-col items-center justify-center z-10">
              <div className="w-32 h-32 bg-white rounded-full shadow-xl shadow-indigo-100 flex items-center justify-center mb-8 animate-in zoom-in-50 duration-500">
                <div className="w-24 h-24 bg-indigo-50 rounded-full flex items-center justify-center">
                   <Share2 className="w-10 h-10 text-indigo-500" />
                </div>
              </div>
              <h3 className="text-2xl font-bold text-gray-900 mb-3 tracking-tight">探索知识网络</h3>
              <p className="max-w-md text-center text-gray-500 mb-10 leading-relaxed">
                上传 GraphML 文件，可视化展示实体间的复杂关联。
                <br/>支持搜索、筛选与深度文档联动。
              </p>
              <div className="flex gap-4">
                 <Button size="lg" variant="outline" onClick={loadDemoData} className="border-gray-200 hover:bg-gray-50 hover:text-gray-900">
                   查看演示数据
                 </Button>
                 <label>
                  <Button size="lg" className="bg-indigo-600 hover:bg-indigo-700 shadow-xl shadow-indigo-200">
                    <Upload className="w-5 h-5 mr-2" />
                    开始上传
                  </Button>
                  <input
                    type="file"
                    accept=".graphml,.xml"
                    className="hidden"
                    onChange={handleFileUpload}
                  />
                </label>
              </div>
            </div>
          )}

          {/* Floating Controls */}
          <div className="absolute bottom-8 right-8 z-10 flex flex-col gap-3">
             <div className="flex flex-col gap-1 bg-white/90 backdrop-blur-sm p-1.5 rounded-2xl shadow-xl shadow-gray-200 border border-gray-100/50">
                <Button variant="ghost" size="icon" onClick={() => graphRef.current?.zoomIn()} className="rounded-xl hover:bg-indigo-50 hover:text-indigo-600" title="放大">
                  <ZoomIn className="w-5 h-5" />
                </Button>
                <Button variant="ghost" size="icon" onClick={() => graphRef.current?.zoomOut()} className="rounded-xl hover:bg-indigo-50 hover:text-indigo-600" title="缩小">
                  <ZoomOut className="w-5 h-5" />
                </Button>
                <div className="h-px bg-gray-100 mx-2 my-0.5"></div>
                <Button variant="ghost" size="icon" onClick={() => graphRef.current?.zoomToFit()} className="rounded-xl hover:bg-indigo-50 hover:text-indigo-600" title="适应屏幕">
                  <Maximize className="w-5 h-5" />
                </Button>
             </div>
             
             <div className="bg-white/90 backdrop-blur-sm p-1.5 rounded-2xl shadow-xl shadow-gray-200 border border-gray-100/50 flex flex-col gap-1">
                <Button 
                  variant="ghost" 
                  size="icon" 
                  onClick={() => setShowEdgeLabels(!showEdgeLabels)} 
                  className={cn("rounded-xl hover:bg-indigo-50 hover:text-indigo-600", showEdgeLabels && "bg-indigo-50 text-indigo-600")} 
                  title="显示/隐藏连线标签"
                >
                  <Type className="w-5 h-5" />
                </Button>
                <Button variant="ghost" size="icon" className="rounded-xl hover:bg-indigo-50 hover:text-indigo-600" title="设置">
                  <Settings className="w-5 h-5" />
                </Button>
             </div>
          </div>

          {/* Info Panel / Sidebar (Right) */}
          <div className={cn(
            "absolute top-4 right-4 bottom-24 w-80 bg-white/95 backdrop-blur-md rounded-2xl shadow-2xl border border-gray-100 transform transition-transform duration-300 ease-in-out z-20 flex flex-col overflow-hidden",
            isDetailOpen && selectedNode ? "translate-x-0" : "translate-x-[120%]"
          )}>
            {selectedNode && (
              <>
                <div className="p-5 border-b border-gray-100 flex items-start justify-between bg-gradient-to-r from-gray-50 to-white">
                  <div>
                    <h2 className="font-bold text-lg text-gray-900 line-clamp-2">{selectedNode.label}</h2>
                    <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium bg-indigo-50 text-indigo-600 mt-2 border border-indigo-100">
                      <Database className="w-3 h-3" />
                      ID: {selectedNode.id}
                    </span>
                  </div>
                  <button 
                    onClick={() => setIsDetailOpen(false)}
                    className="text-gray-400 hover:text-gray-600 hover:bg-gray-100 rounded-lg p-1 transition-colors"
                  >
                    <X className="w-5 h-5" />
                  </button>
                </div>
                
                <div className="flex-1 overflow-y-auto p-5 space-y-6">
                  {/* Deep Linking Actions */}
                  <div className="grid grid-cols-2 gap-3">
                    <Button 
                      onClick={handleChatWithNode}
                      className="w-full bg-indigo-600 hover:bg-indigo-700 text-white shadow-md shadow-indigo-100"
                    >
                      <MessageSquare className="w-4 h-4 mr-2" />
                      对话
                    </Button>
                    <Button 
                      variant="outline" 
                      onClick={handleViewSource}
                      className="w-full"
                    >
                      <FileText className="w-4 h-4 mr-2" />
                      来源
                    </Button>
                  </div>

                  {/* Properties List */}
                  <div>
                    <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                      <Info className="w-3 h-3" />
                      属性详情
                    </h3>
                    <div className="space-y-3">
                      {Object.entries(selectedNode)
                        .filter(([key]) => !['id', 'label', 'x', 'y', 'vx', 'vy', 'fx', 'fy', 'index', 'color', '__bckgDimensions', 'source'].includes(key))
                        .map(([key, value]) => (
                          <div key={key} className="bg-gray-50 rounded-xl p-3 border border-gray-100">
                            <span className="block text-xs font-medium text-gray-500 mb-1 capitalize">{key}</span>
                            <span className="block text-sm text-gray-800 break-words">{String(value)}</span>
                          </div>
                        ))}
                         {selectedNode.source && (
                          <div className="bg-blue-50/50 rounded-xl p-3 border border-blue-100">
                            <span className="block text-xs font-medium text-blue-500 mb-1 capitalize">Source Document</span>
                            <span className="block text-sm text-blue-700 break-words underline cursor-pointer" onClick={handleViewSource}>
                              {selectedNode.source}
                            </span>
                          </div>
                        )}
                    </div>
                  </div>

                  {/* Edit Actions */}
                  <div>
                     <h3 className="text-xs font-semibold text-gray-400 uppercase tracking-wider mb-3 flex items-center gap-2">
                      <Layers className="w-3 h-3" />
                      管理
                    </h3>
                    <div className="grid grid-cols-2 gap-3">
                      <Button variant="outline" className="w-full justify-start text-xs h-9 hover:bg-gray-50 text-gray-600">
                        <Edit className="w-3 h-3 mr-2" />
                        编辑属性
                      </Button>
                      <Button variant="outline" className="w-full justify-start text-xs h-9 hover:bg-red-50 hover:text-red-600 hover:border-red-100 text-gray-600">
                        <Trash2 className="w-3 h-3 mr-2" />
                        删除节点
                      </Button>
                    </div>
                  </div>
                </div>
              </>
            )}
          </div>
        </div>
      </main>
    </div>
  )
}
