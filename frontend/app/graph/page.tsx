'use client'

/**
 * 知识图谱可视化页面
 * 功能：上传 .graphml 文件并进行可视化展示
 * 优化：主流视觉设计、交互侧边栏、玻璃拟态控件、搜索与高级筛选、后端集成、路径分析、布局切换、图编辑、RAG可解释性、3D可视化
 */
import { useState, useRef, useEffect, useCallback } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
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
  Layout,
  Link as LinkIcon,
  PlusCircle,
  Lightbulb,
  Box,
  BoxSelect
} from 'lucide-react'
import { GraphViewer, GraphViewerRef, LayoutMode } from '@/components/graph/graph-viewer'
import { GraphViewer3D, GraphViewer3DRef } from '@/components/graph/graph-viewer-3d'
import { parseGraphML, GraphData } from '@/lib/graph-parser'
import { GraphService } from '@/services/graph-service'
import { findShortestPath } from '@/lib/graph-algorithms'
import { cn } from '@/lib/utils'

export default function GraphPage() {
  const router = useRouter()
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

  // Layout & View Mode
  const [layoutMode, setLayoutMode] = useState<LayoutMode>('force')
  const [is3DMode, setIs3DMode] = useState(false)

  // Editing State
  const [isConnectMode, setIsConnectMode] = useState(false)
  const [connectSourceNode, setConnectSourceNode] = useState<any | null>(null)

  // Explainability State
  const [isExplainMode, setIsExplainMode] = useState(false)
  const [explainSteps, setExplainSteps] = useState<{node: string, reason: string}[]>([])
  const [currentStepIndex, setCurrentStepIndex] = useState(-1)

  const graphRef = useRef<GraphViewerRef | GraphViewer3DRef>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)

  // Initialize with real (mock) data from service
  const loadInitialData = async () => {
    setIsLoading(true)
    try {
      console.log('Loading initial data...')
      const data = await GraphService.fetchInitialGraph()
      console.log('Data fetched:', data)
      console.log('Setting graph data...')
      setGraphData(data)
      setFileName('Knowledge Base (Live)')
      setIsDetailOpen(false)
      setSelectedNode(null)
      resetPathMode()
      resetConnectMode()
      resetExplainMode()
    } catch (error) {
      console.error('Failed to fetch graph data:', error)
    } finally {
      setIsLoading(false)
    }
  }

  const handleFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setIsLoading(true)
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
        resetConnectMode()
        resetExplainMode()
      } catch (error) {
        console.error('Failed to parse graph file:', error)
        toast.error('解析文件失败，请确保是有效的 GraphML 文件')
      } finally {
        setIsLoading(false)
      }
    }
    reader.readAsText(file)
    e.target.value = '' 
  }

  const triggerFileUpload = () => {
    fileInputRef.current?.click()
  }

  const handleExpandNode = useCallback(async () => {
    if (!selectedNode) return
    
    setIsLoading(true)
    try {
      const newData = await GraphService.expandNode(selectedNode.id)
      
      setGraphData(prev => {
        const existingNodeIds = new Set(prev.nodes.map(n => n.id))
        const uniqueNewNodes = newData.nodes.filter(n => !existingNodeIds.has(n.id))
        
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
  }, [selectedNode])

  const handleDeleteNode = useCallback(() => {
    if (!selectedNode) return
    if (!confirm(`确定要删除节点 "${selectedNode.label}" 及其所有连线吗？`)) return

    const nodeId = selectedNode.id
    setGraphData(prev => ({
      nodes: prev.nodes.filter(n => n.id !== nodeId),
      links: prev.links.filter(l => {
        const s = (l.source as any).id || l.source
        const t = (l.target as any).id || l.target
        return s !== nodeId && t !== nodeId
      })
    }))
    
    setSelectedNode(null)
    setIsDetailOpen(false)
  }, [selectedNode])

  // Keyboard Shortcuts
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      // Search (Ctrl/Cmd + F)
      if ((e.ctrlKey || e.metaKey) && e.key === 'f') {
        e.preventDefault()
        searchInputRef.current?.focus()
      }

      // Escape (Close panels, reset modes)
      if (e.key === 'Escape') {
        if (isDetailOpen) setIsDetailOpen(false)
        if (isPathMode) resetPathMode()
        if (isConnectMode) resetConnectMode()
        if (isExplainMode) resetExplainMode()
        searchInputRef.current?.blur()
      }

      // Space (Expand Node if selected)
      if (e.key === ' ' && selectedNode && isDetailOpen && !['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) {
        e.preventDefault()
        handleExpandNode()
      }

      // Delete (Delete Node if selected)
      if (e.key === 'Delete' || e.key === 'Backspace') {
        if (selectedNode && isDetailOpen && !['INPUT', 'TEXTAREA'].includes((e.target as HTMLElement).tagName)) {
          handleDeleteNode()
        }
      }
    }

    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [selectedNode, isDetailOpen, isPathMode, isConnectMode, isExplainMode, handleDeleteNode, handleExpandNode])

  const startConnectMode = () => {
    if (!selectedNode) return
    setConnectSourceNode(selectedNode)
    setIsConnectMode(true)
    setIsDetailOpen(false)
    toast(`连线模式：请选择终点节点（起点：${selectedNode.label}）`)
  }

  const finishConnection = (targetNode: any) => {
    if (!connectSourceNode) return
    if (connectSourceNode.id === targetNode.id) {
      toast.error('不能连接自己')
      return
    }

    const label = prompt("请输入关系名称 (例如: related_to):", "related_to")
    if (label === null) {
      resetConnectMode()
      return 
    }

    setGraphData(prev => ({
      ...prev,
      links: [...prev.links, {
        source: connectSourceNode.id,
        target: targetNode.id,
        label: label || 'related_to'
      }]
    }))

    resetConnectMode()
  }

  const resetConnectMode = () => {
    setIsConnectMode(false)
    setConnectSourceNode(null)
  }

  // --- Explainability Logic ---
  const startExplainMode = () => {
    if (graphData.nodes.length < 3) {
      toast.warning('图谱节点过少，无法演示推理路径')
      return
    }

    const trace = []
    const visited = new Set()
    let current = graphData.nodes[0]
    
    for (let i = 0; i < 4; i++) {
        trace.push(current)
        visited.add(current.id)
        
        const link = graphData.links.find(l => {
            const s = (l.source as any).id || l.source
            const t = (l.target as any).id || l.target
            return (s === current.id && !visited.has(t)) || (t === current.id && !visited.has(s))
        })
        
        if (link) {
            const s = (link.source as any).id || link.source
            const t = (link.target as any).id || link.target
            const nextId = s === current.id ? t : s
            current = graphData.nodes.find(n => n.id === nextId) || graphData.nodes[i+1]
        } else {
            current = graphData.nodes[Math.min(i + 5, graphData.nodes.length - 1)]
        }
    }

    const steps = trace.map((node, i) => ({
        node: node.id,
        reason: i === 0 ? "初始查询匹配到的实体" : i === trace.length - 1 ? "最终推理得出的答案" : "通过关系链召回的相关节点"
    }))

    setExplainSteps(steps)
    setIsExplainMode(true)
    setIsDetailOpen(false)
    setSelectedNode(null)
    
    animateTrace(steps)
  }

  const animateTrace = async (steps: {node: string}[]) => {
    for (let i = 0; i < steps.length; i++) {
        setCurrentStepIndex(i)
        const step = steps[i]
        
        setHighlightedNodeIds(prev => new Set([...Array.from(prev), step.node]))
        
        if (graphRef.current) {
            graphRef.current.focusNode(step.node)
        }

        if (i > 0) {
            const prevNode = steps[i-1].node
            const currNode = step.node
            const link = graphData.links.find(l => {
                const s = (l.source as any).id || l.source
                const t = (l.target as any).id || l.target
                return (s === prevNode && t === currNode) || (s === currNode && t === prevNode)
            })
            if (link) {
                // @ts-ignore
                const linkId = link.id || (link.index !== undefined ? `link-${link.index}` : null)
                if (linkId) {
                    setHighlightedLinkIds(prev => new Set([...Array.from(prev), linkId]))
                }
            }
        }

        await new Promise(r => setTimeout(r, 1500))
    }
  }

  const resetExplainMode = () => {
    setIsExplainMode(false)
    setExplainSteps([])
    setCurrentStepIndex(-1)
    setHighlightedNodeIds(new Set())
    setHighlightedLinkIds(new Set())
  }

  const handleNodeClick = (node: any) => {
    if (isPathMode) {
      if (!pathStartNode) {
        setPathStartNode(node)
      } else if (!pathEndNode) {
        if (node.id === pathStartNode.id) {
          setPathStartNode(null)
          return
        }
        setPathEndNode(node)
        calculatePath(pathStartNode, node)
      } else {
        setPathStartNode(node)
        setPathEndNode(null)
        setHighlightedNodeIds(new Set())
        setHighlightedLinkIds(new Set())
      }
      return
    }

    if (isConnectMode) {
      finishConnection(node)
      return
    }

    if (!isExplainMode) {
        setSelectedNode(node)
        setIsDetailOpen(true)
    }
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
      toast.info('未找到连接这两个节点的路径')
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
      resetConnectMode()
      resetExplainMode()
    }
  }

  const cycleLayoutMode = () => {
    setLayoutMode(current => {
      if (current === 'force') return 'tree'
      if (current === 'tree') return 'radial'
      return 'force'
    })
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

  const handleSearchChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const term = e.target.value
    setSearchTerm(term)
    
    if (isPathMode || isConnectMode || isExplainMode) return 

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

  const handleChatWithNode = () => {
    if (!selectedNode?.label) return
    const prompt = `请告诉我关于 ${selectedNode.label} 的信息`
    router.push(`/?prompt=${encodeURIComponent(prompt)}`)
  }

  const handleViewSource = () => {
    const docId = selectedNode?.meta?.document_id || selectedNode?.source
    if (docId) {
      toast(`源文档：${docId}`)
      return
    }
    toast('未找到源文档信息')
  }

  return (
    <div className="flex h-screen overflow-hidden bg-slate-50">
      <Navbar isSidebarOpen={isSidebarOpen} setSidebarOpen={setSidebarOpen} />
      
      <main className="flex-1 flex flex-col transition-all duration-300 relative">
        {/* Header */}
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
          {graphData.nodes.length > 0 && !isPathMode && !isConnectMode && !isExplainMode && (
            <div className="pointer-events-auto absolute left-1/2 -translate-x-1/2 top-1/2 -translate-y-1/2 w-full max-w-md">
              <div className="relative group">
                <Search className="absolute left-3 top-1/2 -translate-y-1/2 w-4 h-4 text-gray-400 group-focus-within:text-indigo-500 transition-colors" />
                <input 
                  ref={searchInputRef}
                  type="text" 
                  value={searchTerm}
                  onChange={handleSearchChange}
                  placeholder="搜索实体节点... (Ctrl+F)"
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

          {/* Status Banners */}
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
           {isConnectMode && (
             <div className="pointer-events-auto absolute left-1/2 -translate-x-1/2 top-1/2 -translate-y-1/2 flex items-center gap-2 px-4 py-2 bg-emerald-600 text-white rounded-full shadow-lg animate-in fade-in slide-in-from-top-4">
                <LinkIcon className="w-4 h-4" />
                <span className="text-sm font-medium">
                   正在连接: {connectSourceNode?.label} ... 请点击目标节点
                </span>
                <button onClick={resetConnectMode} className="ml-2 hover:bg-emerald-500 rounded-full p-0.5">
                  <X className="w-4 h-4" />
                </button>
             </div>
          )}
          {isExplainMode && (
             <div className="pointer-events-auto absolute left-1/2 -translate-x-1/2 top-1/2 -translate-y-1/2 flex items-center gap-2 px-4 py-2 bg-purple-600 text-white rounded-full shadow-lg animate-in fade-in slide-in-from-top-4">
                <Lightbulb className="w-4 h-4" />
                <span className="text-sm font-medium">
                   推理路径演示中... ({currentStepIndex + 1}/{explainSteps.length})
                </span>
                <button onClick={resetExplainMode} className="ml-2 hover:bg-purple-500 rounded-full p-0.5">
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

            <Button 
              size="sm" 
              className="gap-2 bg-indigo-600 hover:bg-indigo-700 shadow-lg shadow-indigo-200 transition-all"
              onClick={triggerFileUpload}
            >
              <Upload className="w-4 h-4" />
              导入
            </Button>
            <input
              ref={fileInputRef}
              type="file"
              accept=".graphml,.xml"
              className="hidden"
              onChange={handleFileUpload}
            />
          </div>
        </header>

        {/* Graph Area */}
        <div className="flex-1 w-full relative bg-slate-50 overflow-hidden min-h-[500px]">
          {/* Dot Pattern Background */}
          <div className="absolute inset-0 z-0 opacity-[0.4]" style={{
             backgroundImage: 'radial-gradient(#cbd5e1 1px, transparent 1px)', 
             backgroundSize: '24px 24px'
          }}></div>

          {graphData.nodes.length > 0 ? (
            is3DMode ? (
              <GraphViewer3D 
                ref={graphRef as React.RefObject<GraphViewer3DRef>}
                data={graphData} 
                onNodeClick={handleNodeClick}
                onBackgroundClick={() => setIsDetailOpen(false)}
                highlightedNodeIds={highlightedNodeIds}
                highlightedLinkIds={highlightedLinkIds}
                showEdgeLabels={showEdgeLabels}
                layoutMode={layoutMode}
              />
            ) : (
              <GraphViewer 
                ref={graphRef as React.RefObject<GraphViewerRef>}
                data={graphData} 
                onNodeClick={handleNodeClick}
                onBackgroundClick={() => setIsDetailOpen(false)}
                highlightedNodeIds={highlightedNodeIds}
                highlightedLinkIds={highlightedLinkIds}
                showEdgeLabels={showEdgeLabels}
                layoutMode={layoutMode}
              />
            )
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
                 <Button 
                    size="lg" 
                    className="bg-indigo-600 hover:bg-indigo-700 shadow-xl shadow-indigo-200"
                    onClick={triggerFileUpload}
                  >
                    <Upload className="w-5 h-5 mr-2" />
                    开始上传
                  </Button>
              </div>
            </div>
          )}

          {/* Explainability Panel (Bottom Left) */}
          {isExplainMode && (
            <div className="absolute bottom-8 left-8 z-20 w-80 bg-white/95 backdrop-blur-md rounded-2xl shadow-2xl border border-purple-100 animate-in slide-in-from-bottom-10 fade-in duration-500 overflow-hidden">
               <div className="p-4 border-b border-purple-50 bg-purple-50/50 flex items-center gap-2">
                 <Lightbulb className="w-4 h-4 text-purple-600" />
                 <h3 className="font-bold text-gray-900 text-sm">RAG 推理过程</h3>
               </div>
               <div className="p-4 space-y-4 max-h-[300px] overflow-y-auto">
                 {explainSteps.map((step, idx) => {
                   const node = graphData.nodes.find(n => n.id === step.node)
                   const isActive = idx === currentStepIndex
                   const isDone = idx < currentStepIndex
                   
                   return (
                     <div key={idx} className={cn("relative pl-4 border-l-2 transition-all duration-500", 
                        isActive ? "border-purple-500" : isDone ? "border-purple-200" : "border-gray-100 opacity-50"
                     )}>
                        <div className={cn("absolute -left-[5px] top-0 w-2 h-2 rounded-full transition-colors", 
                           isActive ? "bg-purple-500" : isDone ? "bg-purple-200" : "bg-gray-200"
                        )}></div>
                        <p className="text-xs font-semibold text-gray-900 mb-0.5">
                          {node?.label || step.node}
                        </p>
                        <p className="text-[10px] text-gray-500 leading-snug">
                          {step.reason}
                        </p>
                     </div>
                   )
                 })}
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
                   onClick={() => setIs3DMode(!is3DMode)}
                   className={cn(
                     "rounded-xl hover:bg-blue-50 hover:text-blue-600 transition-colors", 
                     is3DMode && "bg-blue-100 text-blue-600 ring-2 ring-blue-500/20"
                   )}
                   title={is3DMode ? "切换回 2D" : "切换到 3D"}
                >
                  <Box className="w-5 h-5" />
                </Button>
                <Button 
                   variant="ghost" 
                   size="icon" 
                   onClick={startExplainMode}
                   className={cn(
                     "rounded-xl hover:bg-purple-50 hover:text-purple-600 transition-colors", 
                     isExplainMode && "bg-purple-100 text-purple-600 ring-2 ring-purple-500/20"
                   )}
                   title="推理演示 (Explain)"
                >
                  <PlayCircle className="w-5 h-5" />
                </Button>
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
                {!is3DMode && (
                  <Button 
                    variant="ghost" 
                    size="icon" 
                    onClick={() => setShowEdgeLabels(!showEdgeLabels)} 
                    className={cn("rounded-xl hover:bg-indigo-50 hover:text-indigo-600", showEdgeLabels && "bg-indigo-50 text-indigo-600")} 
                    title="显示/隐藏连线标签"
                  >
                    <Type className="w-5 h-5" />
                  </Button>
                )}
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
                        .filter(([key]) => !['id', 'label', 'x', 'y', 'z', 'vx', 'vy', 'vz', 'fx', 'fy', 'fz', 'index', 'color', '__bckgDimensions', 'source'].includes(key))
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
                         <Button 
                          variant="outline" 
                          onClick={startConnectMode}
                          className="w-full justify-start text-xs h-9 hover:bg-emerald-50 hover:text-emerald-600 hover:border-emerald-100 text-gray-600"
                        >
                          <LinkIcon className="w-3 h-3 mr-2" />
                          连接
                        </Button>
                        <Button 
                          variant="outline" 
                          onClick={handleDeleteNode}
                          className="w-full justify-start text-xs h-9 hover:bg-red-50 hover:text-red-600 hover:border-red-100 text-gray-600"
                        >
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
