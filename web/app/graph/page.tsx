'use client'

/**
 * 知识图谱可视化页面
 * 功能：上传 .graphml 文件并进行可视化展示
 * 优化：主流视觉设计、交互侧边栏、玻璃拟态控件、搜索与高级筛选、后端集成、路径分析、布局切换、图编辑、RAG可解释性、3D可视化
 */
import { useState, useRef, useEffect, useCallback, useDeferredValue, useMemo } from 'react'
import { useRouter } from 'next/navigation'
import { toast } from 'sonner'
import { AppFrame } from '@/components/app-frame'
import { Button } from '@/components/ui/button'
import { EmptyState } from '@/components/ui/empty-state'
import { IconButton } from '@/components/ui/icon-button'
import { Kbd } from '@/components/ui/kbd'
import { PageScaffold } from '@/components/ui/page-scaffold'
import { SearchInput } from '@/components/ui/search-input'
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
  BarChart3,
  Database,
  Filter,
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
  BoxSelect,
} from 'lucide-react'
import { GraphViewer, GraphViewerRef, LayoutMode } from '@/components/graph/graph-viewer'
import { KnowledgeGraph3D } from '@/components/graph/force-graph-3d'
import { parseGraphML, GraphData } from '@/lib/graph-parser'
import { GraphService } from '@/services/graph-service'
import { findShortestPath } from '@/lib/graph-algorithms'
import { cn } from '@/lib/utils'
import { kgApi } from '@/lib/api-client'
import type { KGEntityDetailResponse, KGEventDetailResponse, KGStatsResponse } from '@/types'

export default function GraphPage() {
  const router = useRouter()
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], links: [] })
  const [fileName, setFileName] = useState<string | null>(null)
  const [selectedNode, setSelectedNode] = useState<any | null>(null)
  const [isDetailOpen, setIsDetailOpen] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [dataSource, setDataSource] = useState<'live' | 'mock' | 'file'>('live')
  const [includeEntityLinks, setIncludeEntityLinks] = useState(true)
  const [minSharedEvents, setMinSharedEvents] = useState(2)
  const maxEntityLinks = 1000
  const [kgStats, setKgStats] = useState<KGStatsResponse | null>(null)
  const [kgNodeDetail, setKgNodeDetail] = useState<KGEntityDetailResponse | KGEventDetailResponse | null>(null)
  const [kgNodeDetailLoading, setKgNodeDetailLoading] = useState(false)
  const [viewMode, setViewMode] = useState<'2d' | '3d'>('3d')
  
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

  // Editing State
  const [isConnectMode, setIsConnectMode] = useState(false)
  const [connectSourceNode, setConnectSourceNode] = useState<any | null>(null)

  // Explainability State
  const [isExplainMode, setIsExplainMode] = useState(false)
  const [explainSteps, setExplainSteps] = useState<{node: string, reason: string}[]>([])
  const [currentStepIndex, setCurrentStepIndex] = useState(-1)

  const graphRef = useRef<GraphViewerRef>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const searchInputRef = useRef<HTMLInputElement>(null)
  const deferredSearchTerm = useDeferredValue(searchTerm)
  const linksWithIds = useMemo(() => {
    return graphData.links.map((link, index) => ({
      ...link,
      id: (link as any).id || `link-${index}`,
    }))
  }, [graphData.links])

  const searchMatches = useMemo(() => {
    if (isPathMode || isConnectMode || isExplainMode) return []
    const term = deferredSearchTerm.trim().toLowerCase()
    if (!term) return []

    return graphData.nodes.filter((node) => {
      const label = (node.label || '').toLowerCase()
      const id = (node.id || '').toLowerCase()
      return label.includes(term) || id.includes(term)
    })
  }, [deferredSearchTerm, graphData.nodes, isPathMode, isConnectMode, isExplainMode])

  useEffect(() => {
    if (isPathMode || isConnectMode || isExplainMode) return
    const term = deferredSearchTerm.trim()
    if (!term) {
      setHighlightedNodeIds(new Set())
      return
    }

    const nextIds = new Set(searchMatches.map((node) => node.id))
    setHighlightedNodeIds(nextIds)

    if (searchMatches.length > 0 && graphRef.current) {
      graphRef.current.focusNode(searchMatches[0].id)
    }
  }, [deferredSearchTerm, searchMatches, isPathMode, isConnectMode, isExplainMode])

  useEffect(() => {
    if (dataSource !== 'live') {
      setKgNodeDetail(null)
      setKgNodeDetailLoading(false)
      return
    }
    if (!isDetailOpen || !selectedNode?.id) {
      setKgNodeDetail(null)
      return
    }

    const kind = selectedNode?.meta?.kind
    if (kind !== 'entity' && kind !== 'event') {
      setKgNodeDetail(null)
      return
    }

    let cancelled = false
    setKgNodeDetail(null)
    setKgNodeDetailLoading(true)
    ;(async () => {
      try {
        const detail =
          kind === 'entity' ? await kgApi.getEntity(selectedNode.id) : await kgApi.getEvent(selectedNode.id)
        if (!cancelled) setKgNodeDetail(detail)
      } catch (error) {
        console.error('Fetch KG node detail failed:', error)
        if (!cancelled) setKgNodeDetail(null)
      } finally {
        if (!cancelled) setKgNodeDetailLoading(false)
      }
    })()

    return () => {
      cancelled = true
    }
  }, [dataSource, isDetailOpen, selectedNode?.id, selectedNode?.meta?.kind])

  // Initialize with real (mock) data from service
  const loadInitialData = async (
    source: 'live' | 'mock' = 'live',
    opts?: { includeEntityLinks?: boolean; minSharedEvents?: number }
  ) => {
    setIsLoading(true)
    try {
      const includeLinks = opts?.includeEntityLinks ?? includeEntityLinks
      const sharedThreshold = opts?.minSharedEvents ?? minSharedEvents

      const data = await GraphService.fetchInitialGraph({
        preferMock: source === 'mock',
        includeEntityLinks: source === 'live' ? includeLinks : undefined,
        minSharedEvents: source === 'live' ? sharedThreshold : undefined,
        maxEntityLinks: source === 'live' ? maxEntityLinks : undefined,
      })
      setGraphData(data)
      setDataSource(source)
      setKgNodeDetail(null)
      setFileName(source === 'mock' ? '示例数据' : 'Knowledge Base (Live)')

      if (source === 'live') {
        try {
          const stats = await kgApi.getStats()
          setKgStats(stats)
        } catch {
          setKgStats(null)
        }
      } else {
        setKgStats(null)
      }

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
        setDataSource('file')
        setKgStats(null)
        setKgNodeDetail(null)
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
      const newData = await GraphService.expandNode(selectedNode.id, {
        includeEntityLinks: includeEntityLinks && dataSource === 'live',
        minSharedEvents,
        maxEntityLinks,
      })
       
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
  }, [selectedNode, includeEntityLinks, minSharedEvents, maxEntityLinks, dataSource])

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

  const calculatePath = useCallback(
    (start: any, end: any) => {
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
    },
    [graphData.nodes, linksWithIds]
  )

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

  const toggleEntityLinks = () => {
    const next = !includeEntityLinks
    setIncludeEntityLinks(next)
    if (dataSource === 'live') {
      loadInitialData('live', { includeEntityLinks: next })
    }
  }

  const cycleMinSharedEvents = () => {
    const options = [1, 2, 3, 4]
    const idx = options.indexOf(minSharedEvents)
    const next = options[(idx + 1) % options.length] || 2
    setMinSharedEvents(next)
    if (dataSource === 'live') {
      loadInitialData('live', { minSharedEvents: next })
    }
  }

  const handleExportGraphML = async () => {
    if (dataSource !== 'live') {
      toast.info('仅支持导出后端 KG 实时图谱')
      return
    }

    setIsLoading(true)
    try {
      const xml = await kgApi.exportGraphML({
        include_entity_links: includeEntityLinks,
        min_shared_events: minSharedEvents,
        max_entity_links: maxEntityLinks,
      })
      const blob = new Blob([xml], { type: 'application/graphml+xml;charset=utf-8' })
      const url = URL.createObjectURL(blob)
      const a = document.createElement('a')
      a.href = url
      a.download = 'mimirq-kg.graphml'
      a.click()
      URL.revokeObjectURL(url)
      toast.success('已导出 GraphML')
    } catch (error) {
      console.error('Export GraphML failed:', error)
      toast.error('导出 GraphML 失败')
    } finally {
      setIsLoading(false)
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
    <AppFrame mainClassName="transition-all duration-300">
      <PageScaffold
        showHeader={false}
        title="知识图谱"
        description="知识图谱可视化与分析"
        icon={Share2}
        size="full"
        bodyClassName="px-0 pb-0 overflow-hidden"
        bodyContainerClassName="flex h-full min-h-0 flex-col"
      >
         {/* Header */}
         <header className="absolute top-0 left-0 right-0 z-20 h-16 px-6 flex items-center justify-between bg-card/80 backdrop-blur-md border-b border-border/50 pointer-events-none">
	          <div className="flex items-center gap-3 pointer-events-auto">
	            <div className="p-2 bg-gradient-to-br from-sky-500 to-teal-600 rounded-lg shadow-sm">
	              <Share2 className="w-5 h-5 text-background dark:text-foreground" />
	            </div>
	            <div>
	              <h1 className="text-3xl font-bold text-foreground tracking-tight">知识图谱</h1>
	            </div>
	          </div>
          
          {/* Centered Search Bar */}
          {graphData.nodes.length > 0 && !isPathMode && !isConnectMode && !isExplainMode && (
            <div className="pointer-events-auto absolute left-1/2 -translate-x-1/2 top-1/2 -translate-y-1/2 w-full max-w-md">
              <div className="relative">
                <SearchInput
                  ref={searchInputRef}
                  value={searchTerm}
                  onValueChange={setSearchTerm}
                  placeholder="搜索实体节点..."
                  aria-label="搜索实体节点"
                  inputClassName="h-10 rounded-full bg-muted/50 backdrop-blur-sm shadow-sm pr-16"
                />
                <div className="pointer-events-none absolute right-11 top-1/2 -translate-y-1/2 flex items-center gap-2 text-xs text-muted-foreground">
                  {searchTerm ? <span>{highlightedNodeIds.size} 匹配</span> : null}
                  <span className="flex items-center gap-1">
                    <Kbd className="h-5 px-1.5">Ctrl</Kbd>
                    <Kbd className="h-5 px-1.5">F</Kbd>
                  </span>
                </div>
              </div>
            </div>
          )}

	          {/* Status Banners */}
	           {isPathMode && (
	              <div className="pointer-events-auto absolute left-1/2 -translate-x-1/2 top-1/2 -translate-y-1/2 flex items-center gap-2 px-4 py-2 bg-primary text-primary-foreground rounded-full shadow-lg animate-in fade-in slide-in-from-top-4 motion-reduce:animate-none">
	                 <Route className="w-4 h-4" />
	                 <span className="text-sm font-medium">
	                   {!pathStartNode ? "请点击选择【起点】" : !pathEndNode ? "请点击选择【终点】" : "路径分析完成"}
	                 </span>
	                 <IconButton
	                   label="退出路径分析"
	                   onClick={resetPathMode}
	                   className="ml-2 h-7 w-7 rounded-full text-primary-foreground/80 hover:text-primary-foreground hover:bg-primary-foreground/10"
	                 >
	                   <X className="w-4 h-4" />
	                 </IconButton>
	              </div>
	           )}
	            {isConnectMode && (
	              <div className="pointer-events-auto absolute left-1/2 -translate-x-1/2 top-1/2 -translate-y-1/2 flex items-center gap-2 px-4 py-2 bg-success text-success-foreground rounded-full shadow-lg animate-in fade-in slide-in-from-top-4 motion-reduce:animate-none">
	                 <LinkIcon className="w-4 h-4" />
	                 <span className="text-sm font-medium">
	                    正在连接: {connectSourceNode?.label} ... 请点击目标节点
	                 </span>
	                 <IconButton
	                   label="退出连接模式"
	                   onClick={resetConnectMode}
	                   className="ml-2 h-7 w-7 rounded-full text-success-foreground/80 hover:text-success-foreground hover:bg-success-foreground/10"
	                 >
	                   <X className="w-4 h-4" />
	                 </IconButton>
	              </div>
	           )}
	           {isExplainMode && (
	              <div className="pointer-events-auto absolute left-1/2 -translate-x-1/2 top-1/2 -translate-y-1/2 flex items-center gap-2 px-4 py-2 bg-info text-info-foreground rounded-full shadow-lg animate-in fade-in slide-in-from-top-4 motion-reduce:animate-none">
	                 <Lightbulb className="w-4 h-4" />
	                 <span className="text-sm font-medium">
	                    推理路径演示中... ({currentStepIndex + 1}/{explainSteps.length})
	                 </span>
	                 <IconButton
	                   label="退出推理演示"
	                   onClick={resetExplainMode}
	                   className="ml-2 h-7 w-7 rounded-full text-info-foreground/80 hover:text-info-foreground hover:bg-info-foreground/10"
	                 >
	                   <X className="w-4 h-4" />
	                 </IconButton>
	              </div>
	           )}

           <div className="flex items-center gap-3 pointer-events-auto">
              {fileName && (
               <div className="hidden md:flex items-center gap-2 px-3 py-1.5 bg-muted/50 border border-border rounded-full text-xs text-muted-foreground font-medium">
                 <FileCode className="w-3.5 h-3.5 text-muted-foreground" />
                 <span className="truncate max-w-[150px]">{fileName}</span>
               </div>
              )}

              {dataSource === 'live' && kgStats && (
                <div className="hidden lg:flex items-center gap-2 px-3 py-1.5 bg-muted/50 border border-border rounded-full text-xs text-muted-foreground font-medium">
                  <BarChart3 className="w-3.5 h-3.5 text-muted-foreground" />
                  <span className="font-mono">
                    E:{kgStats.events} N:{kgStats.entities} L:{kgStats.links}
                  </span>
                </div>
              )}

              {dataSource === 'live' && (
                <>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={toggleEntityLinks}
                    className={cn(
                      "text-muted-foreground hover:text-sky-600 dark:hover:text-sky-300 hover:bg-sky-500/10 dark:hover:bg-sky-500/20",
                      includeEntityLinks && "bg-sky-500/10 dark:bg-sky-500/20 text-sky-600 dark:text-sky-300"
                    )}
                    title="实体-实体共现连线"
                  >
                    <LinkIcon className="w-4 h-4 mr-2" />
                    {includeEntityLinks ? '实体连线: ON' : '实体连线: OFF'}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={cycleMinSharedEvents}
                    className="text-muted-foreground hover:text-sky-600 dark:hover:text-sky-300 hover:bg-sky-500/10 dark:hover:bg-sky-500/20"
                    title="最小共现事件数（点击循环）"
                  >
                    <Filter className="w-4 h-4 mr-2" />
                    Co≥{minSharedEvents}
                  </Button>
                  <Button
                    variant="ghost"
                    size="sm"
                    onClick={handleExportGraphML}
                    disabled={isLoading}
                    className="text-muted-foreground hover:text-sky-600 dark:hover:text-sky-300 hover:bg-sky-500/10 dark:hover:bg-sky-500/20"
                    title="导出 GraphML"
                  >
                    <FileCode className="w-4 h-4 mr-2" />
                    导出
                  </Button>
                </>
              )}
 
             <div className="h-6 w-px bg-muted mx-1 hidden sm:block"></div>
 
	             <Button variant="ghost" size="sm" onClick={() => loadInitialData('live')} disabled={isLoading} className="text-muted-foreground hover:text-sky-600 dark:hover:text-sky-300 hover:bg-sky-500/10 dark:hover:bg-sky-500/20">
	               <RefreshCw className={cn("w-4 h-4 mr-2", isLoading && "animate-spin motion-reduce:animate-none")} />
	              {isLoading ? '加载中...' : '刷新'}
	            </Button>

            <Button 
              size="sm" 
              className="gap-2 bg-sky-600 hover:bg-sky-700 shadow-lg shadow-sky-500/20 dark:shadow-sky-500/10 transition-all"
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
        <div className="flex-1 w-full relative bg-background overflow-hidden min-h-[500px]">
          {/* Dot Pattern Background */}
          <div className="absolute inset-0 z-0 opacity-[0.4]" style={{
             backgroundImage: 'radial-gradient(#cbd5e1 1px, transparent 1px)', 
             backgroundSize: '24px 24px'
          }}></div>

          {graphData.nodes.length > 0 ? (
            viewMode === '3d' ? (
                <KnowledgeGraph3D 
                    data={graphData}
                    onNodeClick={(node) => {
                        handleNodeClick(node)
                    }}
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
             <div className="absolute inset-0 z-10 flex items-center justify-center p-6">
               <EmptyState
                 icon={Share2}
                 iconClassName="text-sky-500 dark:text-sky-300"
                 title="探索知识网络"
                 description={
                   <>
                     连接知识孤岛，发现潜在关联。<br />
                     支持实时数据加载、搜索与深度分析。
                   </>
                 }
                 className="w-full max-w-2xl bg-card/70 backdrop-blur-md border-border"
               >
                 <Button
                   size="lg"
                   variant="outline"
                   onClick={() => loadInitialData('mock')}
                   disabled={isLoading}
                   className="border-border hover:bg-muted hover:text-foreground"
                 >
                   {isLoading ? '加载中...' : '加载示例数据'}
                 </Button>
                 <Button
                   size="lg"
                   className="bg-sky-600 hover:bg-sky-700 shadow-xl shadow-sky-500/20 dark:shadow-sky-500/10"
                   onClick={triggerFileUpload}
                 >
                   <Upload className="w-5 h-5" />
                   开始上传
                 </Button>
               </EmptyState>
             </div>
           )}

	          {/* Explainability Panel (Bottom Left) */}
	          {isExplainMode && (
	            <div className="absolute bottom-8 left-8 z-20 w-80 bg-card/95 backdrop-blur-md rounded-2xl shadow-2xl border border-teal-500/30 animate-in slide-in-from-bottom-10 fade-in duration-500 motion-reduce:animate-none motion-reduce:transition-none overflow-hidden">
	               <div className="p-4 border-b border-teal-500/20 bg-teal-500/10 flex items-center gap-2">
	                 <Lightbulb className="w-4 h-4 text-teal-600 dark:text-teal-300" />
	                 <h3 className="font-bold text-foreground text-sm">RAG 推理过程</h3>
	               </div>
               <div className="p-4 space-y-4 max-h-[300px] overflow-y-auto">
                 {explainSteps.map((step, idx) => {
                   const node = graphData.nodes.find(n => n.id === step.node)
                   const isActive = idx === currentStepIndex
                   const isDone = idx < currentStepIndex
                   
                   return (
	                     <div key={idx} className={cn("relative pl-4 border-l-2 transition-all duration-500 motion-reduce:transition-none", 
	                        isActive ? "border-teal-500" : isDone ? "border-teal-500/30" : "border-border opacity-50"
	                     )}>
                        <div className={cn("absolute -left-[5px] top-0 w-2 h-2 rounded-full transition-colors", 
                           isActive ? "bg-teal-500" : isDone ? "bg-teal-500/20" : "bg-muted"
                        )}></div>
                        <p className="text-xs font-semibold text-foreground mb-0.5">
                          {node?.label || step.node}
                        </p>
                        <p className="text-[10px] text-muted-foreground leading-snug">
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
             <div className="flex flex-col gap-1 bg-card/90 backdrop-blur-sm p-1.5 rounded-2xl shadow-xl shadow-black/10 dark:shadow-black/30 border border-border/50">
	               <Button variant="ghost" size="icon" onClick={() => graphRef.current?.zoomIn()} className="rounded-xl hover:bg-sky-500/10 dark:hover:bg-sky-500/20 hover:text-sky-600 dark:hover:text-sky-300" title="放大" aria-label="放大">
	                  <ZoomIn className="w-5 h-5" />
	                </Button>
	                <Button variant="ghost" size="icon" onClick={() => graphRef.current?.zoomOut()} className="rounded-xl hover:bg-sky-500/10 dark:hover:bg-sky-500/20 hover:text-sky-600 dark:hover:text-sky-300" title="缩小" aria-label="缩小">
	                  <ZoomOut className="w-5 h-5" />
	                </Button>
                <div className="h-px bg-muted mx-2 my-0.5"></div>
	                <Button variant="ghost" size="icon" onClick={() => graphRef.current?.zoomToFit()} className="rounded-xl hover:bg-sky-500/10 dark:hover:bg-sky-500/20 hover:text-sky-600 dark:hover:text-sky-300" title="适应屏幕" aria-label="适应屏幕">
	                  <Maximize className="w-5 h-5" />
	                </Button>
             </div>
             
             {/* View Options */}
             <div className="bg-card/90 backdrop-blur-sm p-1.5 rounded-2xl shadow-xl shadow-black/10 dark:shadow-black/30 border border-border/50 flex flex-col gap-1">
	                <Button 
	                   variant="ghost" 
	                   size="icon" 
	                   onClick={() => setViewMode(viewMode === '3d' ? '2d' : '3d')}
                   className={cn(
                     "rounded-xl hover:bg-violet-50 hover:text-violet-600 transition-colors", 
                     viewMode === '3d' && "bg-violet-100 text-violet-600 ring-2 ring-violet-500/20"
	                   )}
	                   title={viewMode === '3d' ? "切换至 2D 平面" : "切换至 3D 空间"}
	                   aria-label={viewMode === '3d' ? "切换至 2D 平面" : "切换至 3D 空间"}
	                >
                  {viewMode === '3d' ? <Box className="w-5 h-5" /> : <BoxSelect className="w-5 h-5" />}
                </Button>
	                <Button 
	                   variant="ghost" 
	                   size="icon" 
	                   onClick={startExplainMode}
                   className={cn(
                     "rounded-xl hover:bg-teal-500/10 dark:hover:bg-teal-500/20 hover:text-teal-600 dark:hover:text-teal-300 transition-colors", 
                     isExplainMode && "bg-teal-500/20 dark:bg-teal-500/30 text-teal-600 dark:text-teal-300 ring-2 ring-teal-500/20"
	                   )}
	                   title="推理演示 (Explain)"
	                   aria-label="推理演示"
	                >
                  <PlayCircle className="w-5 h-5" />
                </Button>
	                <Button 
	                   variant="ghost" 
	                   size="icon" 
	                   onClick={cycleLayoutMode}
	                   className="rounded-xl hover:bg-sky-500/10 dark:hover:bg-sky-500/20 hover:text-sky-600 dark:hover:text-sky-300" 
	                   title={`切换布局: ${getLayoutLabel()}`}
	                   aria-label={`切换布局：${getLayoutLabel()}`}
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
	                   aria-label="路径发现"
	                >
                  <Route className="w-5 h-5" />
                </Button>
	                <Button 
	                  variant="ghost" 
	                  size="icon" 
	                  onClick={() => setShowEdgeLabels(!showEdgeLabels)} 
	                  className={cn("rounded-xl hover:bg-sky-500/10 dark:hover:bg-sky-500/20 hover:text-sky-600 dark:hover:text-sky-300", showEdgeLabels && "bg-sky-500/10 dark:bg-sky-500/20 text-sky-600 dark:text-sky-300")} 
	                  title="显示/隐藏连线标签"
	                  aria-label="显示或隐藏连线标签"
	                >
                  <Type className="w-5 h-5" />
                </Button>
             </div>
          </div>

          {/* Info Panel / Sidebar (Right) */}
          <div className={cn(
            "absolute top-4 right-4 bottom-24 w-80 bg-card/95 backdrop-blur-md rounded-2xl shadow-2xl border border-border transform transition-transform duration-300 ease-in-out z-20 flex flex-col overflow-hidden",
            isDetailOpen && selectedNode ? "translate-x-0" : "translate-x-[120%]"
          )}>
            {selectedNode && (
              <>
                <div className="p-5 border-b border-border flex items-start justify-between bg-gradient-to-r from-muted/60 to-card">
                  <div>
                    <h2 className="font-bold text-lg text-foreground line-clamp-2">{selectedNode.label}</h2>
                    <span className="inline-flex items-center gap-1.5 px-2 py-0.5 rounded-full text-[10px] font-medium bg-sky-500/10 dark:bg-sky-500/20 text-sky-600 dark:text-sky-300 mt-2 border border-sky-500/30">
                      <Database className="w-3 h-3" />
                      ID: {selectedNode.id}
                    </span>
                  </div>
	                  <button 
	                    type="button"
	                    onClick={() => setIsDetailOpen(false)}
	                    aria-label="关闭详情面板"
	                    className="text-muted-foreground hover:text-muted-foreground hover:bg-muted rounded-lg p-1 transition-colors"
	                  >
	                    <X className="w-5 h-5" />
	                  </button>
                </div>
                
                <div className="flex-1 overflow-y-auto p-5 space-y-6">
                  {/* Deep Linking Actions */}
	                  <div className="grid grid-cols-2 gap-3">
	                    <Button 
	                      variant="info"
	                      onClick={handleChatWithNode}
	                      className="w-full"
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

                  {/* KG Detail (Live) */}
                  {dataSource === 'live' && (selectedNode?.meta?.kind === 'entity' || selectedNode?.meta?.kind === 'event') && (
                    <div>
                      <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3 flex items-center gap-2">
                        <Network className="w-3 h-3" />
                        KG Detail
                      </h3>

                      {kgNodeDetailLoading ? (
                        <div className="text-xs text-muted-foreground bg-muted rounded-xl p-3 border border-border">
                          Loading...
                        </div>
                      ) : !kgNodeDetail ? (
                        <div className="text-xs text-muted-foreground bg-muted rounded-xl p-3 border border-border">
                          No KG detail available
                        </div>
                      ) : selectedNode?.meta?.kind === 'entity' ? (
                        <div className="space-y-3">
                          <div className="bg-muted rounded-xl p-3 border border-border">
                            <div className="text-[10px] font-medium text-muted-foreground mb-1">Recent Events</div>
                            <div className="space-y-1">
                              {(kgNodeDetail as KGEntityDetailResponse).events?.slice(0, 6)?.map((ev) => (
                                <div key={ev.id} className="text-xs text-foreground truncate" title={ev.title}>
                                  {ev.title}
                                </div>
                              ))}
                            </div>
                          </div>
                          <div className="bg-muted rounded-xl p-3 border border-border">
                            <div className="text-[10px] font-medium text-muted-foreground mb-1">Top Neighbors</div>
                            <div className="space-y-1">
                              {(kgNodeDetail as KGEntityDetailResponse).neighbors?.slice(0, 8)?.map((n) => (
                                <div key={n.entity_id} className="flex items-center justify-between gap-2 text-xs">
                                  <span className="text-foreground truncate" title={n.name}>
                                    {n.name || n.entity_id}
                                  </span>
                                  <span className="text-muted-foreground font-mono">{n.count}</span>
                                </div>
                              ))}
                            </div>
                          </div>
                        </div>
                      ) : (
                        <div className="bg-muted rounded-xl p-3 border border-border">
                          <div className="text-[10px] font-medium text-muted-foreground mb-2">Entities</div>
                          <div className="space-y-1">
                            {(kgNodeDetail as KGEventDetailResponse).entities?.slice(0, 12)?.map((row) => (
                              <div key={row.entity.id} className="flex items-center justify-between gap-2 text-xs">
                                <span className="text-foreground truncate" title={row.entity.name}>
                                  {row.entity.name || row.entity.id}
                                </span>
                                <span className="text-muted-foreground">{row.role || row.entity.type}</span>
                              </div>
                            ))}
                          </div>
                        </div>
                      )}
                    </div>
                  )}

                  {/* Properties List */}
                  <div>
                    <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3 flex items-center gap-2">
                      <Info className="w-3 h-3" />
                      属性详情
                    </h3>
                    <div className="space-y-3">
                      {Object.entries(selectedNode)
                        .filter(([key]) => !['id', 'label', 'x', 'y', 'z', 'vx', 'vy', 'vz', 'fx', 'fy', 'fz', 'index', 'color', '__bckgDimensions', 'source', 'meta'].includes(key))
                        .map(([key, value]) => (
                          <div key={key} className="bg-muted rounded-xl p-3 border border-border">
                            <span className="block text-xs font-medium text-muted-foreground mb-1 capitalize">{key}</span>
                            <span className="block text-sm text-foreground break-words">{String(value)}</span>
                          </div>
                        ))}
                         {selectedNode.source && (
                          <div className="rounded-xl border border-info/25 bg-info/10 p-3">
                            <span className="block text-xs font-medium text-info mb-1 capitalize">Source Document</span>
                            <button
                              type="button"
                              onClick={handleViewSource}
                              className="block w-full text-left text-sm text-info break-words underline underline-offset-4 hover:text-info/80 rounded-md focus-ring"
                            >
                              {selectedNode.source}
                            </button>
                          </div>
                        )}
                    </div>
                  </div>

                  {/* Edit Actions */}
                  <div>
                     <h3 className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3 flex items-center gap-2">
                      <Layers className="w-3 h-3" />
                      操作
                    </h3>
                    <div className="space-y-2">
                       <Button 
                        variant="outline" 
                        onClick={handleExpandNode} 
                        disabled={isLoading}
                        className="w-full justify-start text-xs h-9 hover:bg-sky-500/10 dark:hover:bg-sky-500/20 hover:text-sky-600 dark:hover:text-sky-300 text-muted-foreground"
                      >
                        <Network className="w-3 h-3 mr-2" />
                        {isLoading ? '展开中...' : '展开邻居节点'}
                      </Button>
                      <div className="grid grid-cols-2 gap-2">
                         <Button 
                          variant="outline" 
                          onClick={startConnectMode}
                          className="w-full justify-start text-xs h-9 hover:bg-emerald-500/10 dark:hover:bg-emerald-500/20 hover:text-emerald-600 dark:hover:text-emerald-300 hover:border-emerald-500/30 text-muted-foreground"
                        >
                          <LinkIcon className="w-3 h-3 mr-2" />
                          连接
                        </Button>
                        <Button 
                          variant="outline" 
                          onClick={handleDeleteNode}
                          className="w-full justify-start text-xs h-9 hover:bg-red-500/10 dark:hover:bg-red-500/20 dark:bg-red-500/20 hover:text-red-600 dark:hover:text-red-300 hover:border-red-500/30 text-muted-foreground"
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
      </PageScaffold>
    </AppFrame>
  )
}
