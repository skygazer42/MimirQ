'use client'

/**
 * 知识图谱可视化页面
 * 功能：上传 .graphml 文件并进行可视化展示
 * 优化：主流视觉设计、交互侧边栏、玻璃拟态控件、搜索与高级筛选、后端集成、路径分析、布局切换
 */
import { useState, useRef, useEffect } from 'react'
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
  Edit,
  Network,
  Route,
  PlayCircle,
  Layout
} from 'lucide-react'
import { GraphViewer, GraphViewerRef, LayoutMode } from '@/components/graph/graph-viewer'
import { parseGraphML, GraphData } from '@/lib/graph-parser'
import { GraphService } from '@/services/graph-service'
import { findShortestPath } from '@/lib/graph-algorithms'
import { cn } from '@/lib/utils'

export default function GraphPage() {
  const [isSidebarOpen, setSidebarOpen] = useState(true)
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], links: [] })
  const [fileName, setFileName] = useState<string | null>(null)
  const [selectedNode, setSelectedNode] = useState<any | null>(null)
  const [isDetailOpen, setIsDetailOpen] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  
  // Search & Filter State
  const [searchTerm, setSearchTerm] = useState('')
  const [showEdgeLabels, setShowEdgeLabels] = useState(true)
  const [highlightedNodeIds, setHighlightedNodeIds] = useState<Set<string>>(new Set())
  const [highlightedLinkIds, setHighlightedLinkIds] = useState<Set<string>>(new Set())

  // Path Finding State
  const [isPathMode, setIsPathMode] = useState(false)
  const [pathStartNode, setPathStartNode] = useState<any | null>(null)
  const [pathEndNode, setPathEndNode] = useState<any | null>(null)

  // Layout State
  const [layoutMode, setLayoutMode] = useState<LayoutMode>('force')

  const graphRef = useRef<GraphViewerRef>(null)

  // Initialize with real (mock) data from service
  const loadInitialData = async () => {
    setIsLoading(true)
    try {
      const data = await GraphService.fetchInitialGraph()
      setGraphData(data)
      setFileName('Knowledge Base (Live)')
      setIsDetailOpen(false)
      setSelectedNode(null)
      resetPathMode()
    } catch (error) {
      console.error('Failed to fetch graph data:', error)
    } finally {
      setIsLoading(false)
    }
  }

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
        resetPathMode()
      } catch (error) {
        console.error('Failed to parse graph file:', error)
        alert('解析文件失败，请确保是有效的 GraphML 文件')
      }
    }
    reader.readAsText(file)
    e.target.value = '' 
  }

  const handleExpandNode = async () => {
    if (!selectedNode) return
    
    setIsLoading(true)
    try {
      const newData = await GraphService.expandNode(selectedNode.id)
      
      setGraphData(prev => {
        // Merge nodes avoiding duplicates
        const existingNodeIds = new Set(prev.nodes.map(n => n.id))
        const uniqueNewNodes = newData.nodes.filter(n => !existingNodeIds.has(n.id))
        
        // Merge links avoiding duplicates
        const existingLinks = new Set(prev.links.map(l => `${(l.source as any).id || l.source}-${(l.target as any).id || l.target}`))
        const uniqueNewLinks = newData.links.filter(l => !existingLinks.has(`${l.source}-${l.target}`))

        return {
          nodes: [...prev.nodes, ...uniqueNewNodes],
          links: [...prev.links, ...uniqueNewLinks]
        }
      })
    } catch (error) {
      console.error('Failed to expand node:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const handleNodeClick = (node: any) => {
    // If in Path Finding Mode
    if (isPathMode) {
      if (!pathStartNode) {
        setPathStartNode(node)
      } else if (!pathEndNode) {
        // Check if user clicked start node again (deselect)
        if (node.id === pathStartNode.id) {
          setPathStartNode(null)
          return
        }
        setPathEndNode(node)
        calculatePath(pathStartNode, node)
      } else {
        // Reset and start new path from clicked node
        setPathStartNode(node)
        setPathEndNode(null)
        setHighlightedNodeIds(new Set())
        setHighlightedLinkIds(new Set())
      }
      return
    }

    // Normal Mode
    setSelectedNode(node)
    setIsDetailOpen(true)
  }

  const calculatePath = (start: any, end: any) => {
    const linksWithIds = graphData.links.map((link, index) => ({
      ...link,
      id: (link as any).id || `link-${index}`
    }))
    
    const result = findShortestPath(graphData.nodes, linksWithIds, start.id, end.id)
    
    if (result) {
      setHighlightedNodeIds(new Set(result.nodeIds))
      setHighlightedLinkIds(new Set(result.linkIds))
      if (graphRef.current) {
         graphRef.current.zoomToFit() 
      }
    } else {
      alert("未找到连接这两个节点的路径")
      setPathEndNode(null)
    }
  }

  const resetPathMode = () => {
    setIsPathMode(false)
    setPathStartNode(null)
    setPathEndNode(null)
    setHighlightedNodeIds(new Set())
    setHighlightedLinkIds(new Set())
  }

  const togglePathMode = () => {
    if (isPathMode) {
      resetPathMode()
    } else {
      setIsPathMode(true)
      setIsDetailOpen(false)
      setSelectedNode(null)
      setHighlightedNodeIds(new Set())
    }
  }

  const cycleLayoutMode = () => {
    setLayoutMode(current => {
      if (current === 'force') return 'tree'
      if (current === 'tree') return 'radial'
      return 'force'
    })
    // Reset zoom to fit when changing layout
    setTimeout(() => {
       graphRef.current?.zoomToFit()
    }, 500)
  }

  const getLayoutLabel = () => {
    switch (layoutMode) {
      case 'force': return '力导向'
      case 'tree': return '树状'
      case 'radial': return '辐射'
    }
  }

  // Handle Search Input
  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const term = e.target.value
    setSearchTerm(term)
    
    if (isPathMode) return 

    if (!term.trim()) {
      setHighlightedNodeIds(new Set())
      return
    }

    const matches = graphData.nodes.filter(n => 
      (n.label && n.label.toLowerCase().includes(term.toLowerCase())) ||
      (n.id && n.id.toLowerCase().includes(term.toLowerCase()))
    )

    setHighlightedNodeIds(new Set(matches.map(n => n.id)))
    
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
          {graphData.nodes.length > 0 && !isPathMode && (
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

          {/* Path Finding Status Banner */}
          {isPathMode && (
             <div className="pointer-events-auto absolute left-1/2 -translate-x-1/2 top-1/2 -translate-y-1/2 flex items-center gap-2 px-4 py-2 bg-indigo-600 text-white rounded-full shadow-lg animate-in fade-in slide-in-from-top-4">
                <Route className="w-4 h-4" />
                <span className="text-sm font-medium">
                  {!pathStartNode ? "请点击选择【起点】" : !pathEndNode ? "请点击选择【终点】" : "路径分析完成"}
                </span>
                <button onClick={resetPathMode} className="ml-2 hover:bg-indigo-500 rounded-full p-0.5">
                  <X className="w-4 h-4" />
                </button>
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

            <Button variant="ghost" size="sm" onClick={loadInitialData} disabled={isLoading} className="text-gray-600 hover:text-indigo-600 hover:bg-indigo-50">
              <RefreshCw className={cn("w-4 h-4 mr-2", isLoading && "animate-spin")} />
              {isLoading ? '加载中...' : '刷新'}
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
              highlightedLinkIds={highlightedLinkIds}
              showEdgeLabels={showEdgeLabels}
              layoutMode={layoutMode}
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
                连接知识孤岛，发现潜在关联。
                <br/>支持实时数据加载、搜索与深度分析。
              </p>
              <div className="flex gap-4">
                 <Button size="lg" variant="outline" onClick={loadInitialData} disabled={isLoading} className="border-gray-200 hover:bg-gray-50 hover:text-gray-900">
                   {isLoading ? '加载中...' : '加载示例数据'}
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
             {/* Main Zoom Controls */}
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
             
             {/* View Options */}
             <div className="bg-white/90 backdrop-blur-sm p-1.5 rounded-2xl shadow-xl shadow-gray-200 border border-gray-100/50 flex flex-col gap-1">
                <Button 
                   variant="ghost" 
                   size="icon" 
                   onClick={cycleLayoutMode}
                   className="rounded-xl hover:bg-indigo-50 hover:text-indigo-600" 
                   title={`切换布局: ${getLayoutLabel()}`}
                >
                  <Layout className="w-5 h-5" />
                  <span className="sr-only">{getLayoutLabel()}</span>
                </Button>
                <Button 
                   variant="ghost" 
                   size="icon" 
                   onClick={togglePathMode}
                   className={cn(
                     "rounded-xl hover:bg-amber-50 hover:text-amber-600 transition-colors", 
                     isPathMode && "bg-amber-100 text-amber-600 ring-2 ring-amber-500/20"
                   )}
                   title="路径发现 (Shortest Path)"
                >
                  <Route className="w-5 h-5" />
                </Button>
                <Button 
                  variant="ghost" 
                  size="icon" 
                  onClick={() => setShowEdgeLabels(!showEdgeLabels)} 
                  className={cn("rounded-xl hover:bg-indigo-50 hover:text-indigo-600", showEdgeLabels && "bg-indigo-50 text-indigo-600")} 
                  title="显示/隐藏连线标签"
                >
                  <Type className="w-5 h-5" />
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
                      操作
                    </h3>
                    <div className="space-y-2">
                       <Button 
                        variant="outline" 
                        onClick={handleExpandNode} 
                        disabled={isLoading}
                        className="w-full justify-start text-xs h-9 hover:bg-indigo-50 hover:text-indigo-600 text-gray-600"
                      >
                        <Network className="w-3 h-3 mr-2" />
                        {isLoading ? '展开中...' : '展开邻居节点'}
                      </Button>
                      <div className="grid grid-cols-2 gap-2">
                        <Button variant="outline" className="w-full justify-start text-xs h-9 hover:bg-gray-50 text-gray-600">
                          <Edit className="w-3 h-3 mr-2" />
                          编辑
                        </Button>
                        <Button variant="outline" className="w-full justify-start text-xs h-9 hover:bg-red-50 hover:text-red-600 hover:border-red-100 text-gray-600">
                          <Trash2 className="w-3 h-3 mr-2" />
                          删除
                        </Button>
                      </div>
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