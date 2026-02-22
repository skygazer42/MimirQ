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
import { Dialog, DialogContent, DialogDescription, DialogFooter, DialogHeader, DialogTitle } from '@/components/ui/dialog'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  AlertDialog,
  AlertDialogAction,
  AlertDialogCancel,
  AlertDialogContent,
  AlertDialogDescription,
  AlertDialogFooter,
  AlertDialogHeader,
  AlertDialogTitle,
} from '@/components/ui/alert-dialog'
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
import type { KGEntityDetailResponse, KGEventDetailResponse, KGStatsResponse, RagTrace, RagTraceListResponse } from '@/types'

export default function GraphPage() {
  const router = useRouter()
  const [graphData, setGraphData] = useState<GraphData>({ nodes: [], links: [] })
  const [fileName, setFileName] = useState<string | null>(null)
  const [selectedNode, setSelectedNode] = useState<any | null>(null)
  const [isDetailOpen, setIsDetailOpen] = useState(false)
  const [isLoading, setIsLoading] = useState(false)
  const [deleteNodeOpen, setDeleteNodeOpen] = useState(false)
  const [deleteNodeTarget, setDeleteNodeTarget] = useState<{ id: string; label: string } | null>(null)
  const [dataSource, setDataSource] = useState<'live' | 'mock' | 'file'>('live')
  const [includeEntityLinks, setIncludeEntityLinks] = useState(true)
  const [includeRelationLinks, setIncludeRelationLinks] = useState(false)
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
  const [connectLabelOpen, setConnectLabelOpen] = useState(false)
  const [connectTargetNode, setConnectTargetNode] = useState<any | null>(null)
  const [connectLabelDraft, setConnectLabelDraft] = useState('related_to')

  const detailScrollRef = useRef<HTMLDivElement>(null)
  const selectedNodeId = selectedNode?.id as string | undefined

  // Reset the detail panel scroll when switching nodes so it doesn't appear "half scrolled".
  useEffect(() => {
    if (!isDetailOpen || !selectedNodeId) return
    const raf = window.requestAnimationFrame(() => {
      detailScrollRef.current?.scrollTo({ top: 0, left: 0, behavior: 'auto' })
    })
    return () => window.cancelAnimationFrame(raf)
  }, [isDetailOpen, selectedNodeId])

  // Explainability State
  const [isExplainMode, setIsExplainMode] = useState(false)
  const [explainSteps, setExplainSteps] = useState<{node: string, reason: string}[]>([])
  const [currentStepIndex, setCurrentStepIndex] = useState(-1)
  const [traceReplay, setTraceReplay] = useState<RagTrace | null>(null)

  const graphRef = useRef<GraphViewerRef>(null)
  const fileInputRef = useRef<HTMLInputElement>(null)
  const traceFileInputRef = useRef<HTMLInputElement>(null)
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
    opts?: { includeEntityLinks?: boolean; includeRelationLinks?: boolean; minSharedEvents?: number }
  ) => {
    setIsLoading(true)
    try {
      const includeLinks = opts?.includeEntityLinks ?? includeEntityLinks
      const includeRels = opts?.includeRelationLinks ?? includeRelationLinks
      const sharedThreshold = opts?.minSharedEvents ?? minSharedEvents

      const data = await GraphService.fetchInitialGraph({
        preferMock: source === 'mock',
        includeEntityLinks: source === 'live' ? includeLinks : undefined,
        includeRelationLinks: source === 'live' ? includeRels : undefined,
        minSharedEvents: source === 'live' ? sharedThreshold : undefined,
        maxEntityLinks: source === 'live' ? maxEntityLinks : undefined,
      })
      setGraphData(data)
      setDataSource(source)
      setTraceReplay(null)
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
        setTraceReplay(null)
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

  const _extractTraceFromPayload = (payload: any): RagTrace | null => {
    if (!payload) return null
    if (Array.isArray(payload)) {
      const first = payload[0]
      return first && typeof first === 'object' ? (first as RagTrace) : null
    }
    if (typeof payload !== 'object') return null

    // API response: { enabled, items: [...] }
    if (Array.isArray((payload as RagTraceListResponse).items)) {
      const first = (payload as RagTraceListResponse).items?.[0]
      return first && typeof first === 'object' ? (first as RagTrace) : null
    }

    // Single item.
    if (typeof (payload as any).ts_ms === 'number' && Array.isArray((payload as any).steps)) {
      return payload as RagTrace
    }

    return null
  }

  const _buildGraphFromTrace = (trace: RagTrace): { graph: GraphData; steps: { node: string; reason: string }[] } => {
    const rootId = `rag-trace:${trace.request_id || trace.ts_ms}`
    const nodes: GraphData['nodes'] = []
    const links: GraphData['links'] = []

    const hasRerank = Boolean(trace?.rerank?.enabled || trace?.rerank?.elapsed_sec != null)

    const idRetrieve = `${rootId}:retrieve`
    const idRerank = `${rootId}:rerank`
    const idCitations = `${rootId}:citations`

    nodes.push({ id: rootId, label: 'RAG Trace', kind: 'trace', val: 2.5, color: '#0ea5e9' })
    nodes.push({ id: idRetrieve, label: 'Retrieve', kind: 'step', val: 2.0, color: '#2563eb' })
    if (hasRerank) nodes.push({ id: idRerank, label: 'Rerank', kind: 'step', val: 2.0, color: '#14b8a6' })
    nodes.push({ id: idCitations, label: 'Citations', kind: 'step', val: 2.0, color: '#f97316' })

    links.push({ source: rootId, target: idRetrieve, label: 'start' })
    if (hasRerank) {
      links.push({ source: idRetrieve, target: idRerank, label: 'rerank' })
      links.push({ source: idRerank, target: idCitations, label: 'cite' })
    } else {
      links.push({ source: idRetrieve, target: idCitations, label: 'cite' })
    }

    const citations = (trace.citations || []).slice(0, 20)
    const citationNodeIds: string[] = []
    citations.forEach((c, idx) => {
      const doc = String(c.document_id || '').slice(0, 8) || 'doc'
      const page = c.page_number != null ? `p${c.page_number}` : ''
      const score = (c.rerank_score ?? c.retrieval_score ?? c.relevance_score)
      const scoreTxt = score == null ? '' : ` score=${Number(score).toFixed(3)}`
      const id = `${rootId}:c${idx}`
      citationNodeIds.push(id)
      nodes.push({
        id,
        label: `#${idx + 1} ${doc}${page ? ` · ${page}` : ''}${scoreTxt}`,
        kind: 'citation',
        val: 1.2,
        color: '#64748b',
        meta: c,
      })
    })

    if (citationNodeIds.length) {
      links.push({ source: idCitations, target: citationNodeIds[0], label: 'topk' })
      for (let i = 1; i < citationNodeIds.length; i++) {
        links.push({ source: citationNodeIds[i - 1], target: citationNodeIds[i], label: 'next' })
      }
    }

    const steps: { node: string; reason: string }[] = []
    steps.push({ node: idRetrieve, reason: `mode=${trace?.retrieval?.mode || '—'} · elapsed=${trace?.retrieval?.elapsed_sec ?? '—'}s` })
    if (hasRerank) {
      steps.push({ node: idRerank, reason: `provider=${trace?.rerank?.provider || '—'} · elapsed=${trace?.rerank?.elapsed_sec ?? '—'}s` })
    }
    steps.push({ node: idCitations, reason: `count=${trace.citations_count}` })
    citationNodeIds.forEach((id) => steps.push({ node: id, reason: 'retrieved citation' }))

    return { graph: { nodes, links }, steps }
  }

  const handleTraceFileUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0]
    if (!file) return

    setIsLoading(true)
    setFileName(file.name)
    try {
      const text = await file.text()
      const payload = JSON.parse(text)
      const trace = _extractTraceFromPayload(payload)
      if (!trace) {
        throw new Error('Invalid trace JSON')
      }

      const built = _buildGraphFromTrace(trace)
      setTraceReplay(trace)
      setGraphData(built.graph)
      setDataSource('file')
      setKgStats(null)
      setKgNodeDetail(null)
      setIsDetailOpen(false)
      setSelectedNode(null)
      resetPathMode()
      resetConnectMode()
      resetExplainMode()
      setViewMode('2d')
      toast.success('Trace 已导入（可点击右下角 Play 回放）')
    } catch (error) {
      console.error('Failed to import trace JSON:', error)
      setTraceReplay(null)
      toast.error('导入 Trace 失败：请检查 JSON 格式或粘贴/导出内容是否完整')
    } finally {
      setIsLoading(false)
      e.target.value = ''
    }
  }

  const triggerTraceUpload = () => {
    traceFileInputRef.current?.click()
  }

  const handleExpandNode = useCallback(async () => {
    if (!selectedNode) return
    
      setIsLoading(true)
      try {
      const newData = await GraphService.expandNode(selectedNode.id, {
        includeEntityLinks: includeEntityLinks && dataSource === 'live',
        includeRelationLinks: includeRelationLinks && dataSource === 'live',
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
  }, [selectedNode, includeEntityLinks, includeRelationLinks, minSharedEvents, maxEntityLinks, dataSource])

  const handleDeleteNode = useCallback(() => {
    if (!selectedNode) return
    setDeleteNodeTarget({
      id: String(selectedNode.id),
      label: String(selectedNode.label || selectedNode.id || ''),
    })
    setDeleteNodeOpen(true)
  }, [selectedNode])

  const confirmDeleteNode = useCallback(() => {
    const nodeId = (deleteNodeTarget?.id || '').trim()
    if (!nodeId) return

    setGraphData((prev) => ({
      nodes: prev.nodes.filter((n) => String(n.id) !== nodeId),
      links: prev.links.filter((l) => {
        const s = (l.source as any).id || l.source
        const t = (l.target as any).id || l.target
        return String(s) !== nodeId && String(t) !== nodeId
      }),
    }))

    if (String(selectedNode?.id) === nodeId) {
      setSelectedNode(null)
      setIsDetailOpen(false)
    }
    setDeleteNodeTarget(null)
    setDeleteNodeOpen(false)
  }, [deleteNodeTarget, selectedNode])

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

    setConnectTargetNode(targetNode)
    setConnectLabelDraft('related_to')
    setConnectLabelOpen(true)
  }

  const confirmConnectionLabel = () => {
    if (!connectSourceNode || !connectTargetNode) {
      setConnectLabelOpen(false)
      setConnectTargetNode(null)
      resetConnectMode()
      return
    }

    const label = connectLabelDraft.trim() || 'related_to'
    setGraphData((prev) => ({
      ...prev,
      links: [
        ...prev.links,
        {
          source: connectSourceNode.id,
          target: connectTargetNode.id,
          label,
        },
      ],
    }))

    setConnectLabelOpen(false)
    setConnectTargetNode(null)
    resetConnectMode()
  }

  const resetConnectMode = () => {
    setIsConnectMode(false)
    setConnectSourceNode(null)
  }

  // --- Explainability Logic ---
  const startExplainMode = () => {
    // Trace replay mode: when user imported a RAG trace JSON, prefer replaying the
    // real retrieve/rerank/citations path instead of a random walk.
    if (traceReplay) {
      const built = _buildGraphFromTrace(traceReplay)

      // Ensure 2D so highlight/focus works consistently.
      if (viewMode === '3d') {
        setViewMode('2d')
      }

      // If the current graph isn't a trace graph, swap it in (best-effort).
      const prefix = `rag-trace:${traceReplay.request_id || traceReplay.ts_ms}`
      const isTraceGraph = graphData.nodes.some((n) => String(n.id || '').startsWith(prefix))
      if (!isTraceGraph) {
        setGraphData(built.graph)
        setDataSource('file')
        setKgStats(null)
        setKgNodeDetail(null)
        setFileName(`${prefix}.json`)
      }

      setHighlightedNodeIds(new Set())
      setHighlightedLinkIds(new Set())
      setCurrentStepIndex(-1)
      setExplainSteps(built.steps)
      setIsExplainMode(true)
      setIsDetailOpen(false)
      setSelectedNode(null)

      // Let the graph render once before running animation/focus.
      window.requestAnimationFrame(() => {
        void animateTrace(built.steps, built.graph)
      })
      return
    }

    if (graphData.nodes.length < 3) {
      toast.warning('图谱节点过少，无法演示推理路径')
      return
    }

    setHighlightedNodeIds(new Set())
    setHighlightedLinkIds(new Set())
    setCurrentStepIndex(-1)

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

  const animateTrace = async (steps: {node: string}[], graphOverride?: GraphData) => {
    const g = graphOverride || graphData
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
            const link = g.links.find(l => {
                const s = (l.source as any).id || l.source
                const t = (l.target as any).id || l.target
                return (s === prevNode && t === currNode) || (s === currNode && t === prevNode)
            })
            if (link) {
                const rawId = (link as any).id
                const idx = (g.links as any[]).indexOf(link as any)
                const linkId =
                  rawId ||
                  ((link as any).index !== undefined ? `link-${(link as any).index}` : (idx >= 0 ? `link-${idx}` : null))
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

  const toggleRelationLinks = () => {
    const next = !includeRelationLinks
    setIncludeRelationLinks(next)
    if (dataSource === 'live') {
      loadInitialData('live', { includeRelationLinks: next })
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
        include_relation_links: includeRelationLinks,
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
    <AppFrame>
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
         <header className="absolute top-0 left-0 right-0 z-20 h-16 px-6 flex items-center justify-between bg-card border-b border-border/50 pointer-events-none">
	          <div className="flex items-center gap-3 pointer-events-auto">
		            <div className="p-2 rounded-lg bg-primary text-primary-foreground shadow-sm border border-primary/20">
		              <Share2 className="w-5 h-5" />
		            </div>
	            <div>
	              <h1 className="text-3xl font-bold text-foreground ">知识图谱</h1>
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
                  inputClassName="h-10 rounded-full bg-muted/60 shadow-sm pr-16"
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
                    onClick={toggleRelationLinks}
                    className={cn(
                      "text-muted-foreground hover:text-teal-600 dark:hover:text-teal-300 hover:bg-teal-500/10 dark:hover:bg-teal-500/20",
                      includeRelationLinks && "bg-teal-500/10 dark:bg-teal-500/20 text-teal-600 dark:text-teal-300"
                    )}
                    title="实体-实体关系连线（来自 KG triples / kg_relations）"
                  >
                    <Network className="w-4 h-4 mr-2" />
                    {includeRelationLinks ? '关系连线: ON' : '关系连线: OFF'}
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
              variant="ghost"
              size="sm"
              onClick={triggerTraceUpload}
              className="text-muted-foreground hover:text-teal-600 dark:hover:text-teal-300 hover:bg-teal-500/10 dark:hover:bg-teal-500/20"
              title="导入 RAG trace JSON（回放检索路径）"
            >
              <FileText className="w-4 h-4 mr-2" />
              Trace
            </Button>
            <input
              ref={traceFileInputRef}
              type="file"
              accept=".json,application/json"
              className="hidden"
              onChange={handleTraceFileUpload}
            />

	            <Button 
	              variant="info"
	              size="sm" 
	              className="gap-2"
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
                 className="w-full max-w-2xl bg-card/80 border-border"
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
	                 className="bg-primary text-primary-foreground hover:bg-primary/90 shadow-soft"
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
		            <div className="absolute bottom-8 left-8 z-20 w-80 bg-card rounded-2xl shadow-strong border border-border overflow-hidden">
		               <div className="p-4 border-b border-border bg-muted/30 flex items-center gap-2">
		                 <Lightbulb className="w-4 h-4 text-primary" />
		                 <h3 className="font-bold text-foreground text-sm">RAG 推理过程</h3>
		               </div>
               <div className="p-4 space-y-4 max-h-[300px] overflow-y-auto overscroll-contain no-scrollbar">
                 {explainSteps.map((step, idx) => {
                   const node = graphData.nodes.find(n => n.id === step.node)
                   const isActive = idx === currentStepIndex
                   const isDone = idx < currentStepIndex
                   
                   return (
	                     <div key={idx} className={cn("relative pl-4 border-l-2 transition-colors duration-150 motion-reduce:transition-none", 
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
             <div className="flex flex-col gap-1 bg-card/90 p-1.5 rounded-2xl shadow-md border border-border/50">
	               <Button variant="ghost" size="icon" onClick={() => graphRef.current?.zoomIn()} className="rounded-xl" title="放大" aria-label="放大">
	                  <ZoomIn className="w-5 h-5" />
	                </Button>
	                <Button variant="ghost" size="icon" onClick={() => graphRef.current?.zoomOut()} className="rounded-xl" title="缩小" aria-label="缩小">
	                  <ZoomOut className="w-5 h-5" />
	                </Button>
                <div className="h-px bg-muted mx-2 my-0.5"></div>
	                <Button variant="ghost" size="icon" onClick={() => graphRef.current?.zoomToFit()} className="rounded-xl" title="适应屏幕" aria-label="适应屏幕">
	                  <Maximize className="w-5 h-5" />
	                </Button>
             </div>
             
             {/* View Options */}
             <div className="bg-card/90 p-1.5 rounded-2xl shadow-md border border-border/50 flex flex-col gap-1">
	                <Button 
	                   variant="ghost" 
	                   size="icon" 
	                   onClick={() => setViewMode(viewMode === '3d' ? '2d' : '3d')}
                   className={cn(
                     "rounded-xl",
                     viewMode === '3d' && "bg-primary/10 text-primary ring-2 ring-primary/20"
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
                     "rounded-xl",
                     isExplainMode && "bg-primary/10 text-primary ring-2 ring-primary/20"
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
	                   className="rounded-xl"
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
                     "rounded-xl",
                     isPathMode && "bg-primary/10 text-primary ring-2 ring-primary/20"
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
	                  className={cn("rounded-xl", showEdgeLabels && "bg-primary/10 text-primary ring-2 ring-primary/20")} 
	                  title="显示/隐藏连线标签"
	                  aria-label="显示或隐藏连线标签"
	                >
                  <Type className="w-5 h-5" />
                </Button>
             </div>
          </div>

	          {/* Info Panel / Sidebar (Right) */}
	          <div
	            className={cn(
	              "absolute top-4 right-4 bottom-24 w-80 bg-card rounded-2xl shadow-strong border border-border transform transition-transform duration-200 ease-out z-20 flex flex-col overflow-hidden",
	              isDetailOpen && selectedNode ? "translate-x-0" : "translate-x-[120%]"
	            )}
	          >
            {selectedNode && (
              <>
	                <div className="p-5 border-b border-border flex items-start justify-between bg-card">
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
                
                <div ref={detailScrollRef} className="flex-1 overflow-y-auto overscroll-contain no-scrollbar p-5 space-y-6">
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
                      <h3 className="text-xs font-semibold text-muted-foreground uppercase  mb-3 flex items-center gap-2">
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
                    <h3 className="text-xs font-semibold text-muted-foreground uppercase  mb-3 flex items-center gap-2">
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
                     <h3 className="text-xs font-semibold text-muted-foreground uppercase  mb-3 flex items-center gap-2">
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

        <AlertDialog
          open={deleteNodeOpen}
          onOpenChange={(open) => {
            setDeleteNodeOpen(open)
            if (!open) setDeleteNodeTarget(null)
          }}
        >
          <AlertDialogContent>
            <AlertDialogHeader>
              <AlertDialogTitle>删除节点？</AlertDialogTitle>
              <AlertDialogDescription>
                你将删除节点 <span className="font-mono">{deleteNodeTarget?.label || '-'}</span> 及其所有连线。此操作不可撤销。
              </AlertDialogDescription>
            </AlertDialogHeader>
            <AlertDialogFooter>
              <AlertDialogCancel>取消</AlertDialogCancel>
              <AlertDialogAction onClick={confirmDeleteNode}>删除</AlertDialogAction>
            </AlertDialogFooter>
          </AlertDialogContent>
        </AlertDialog>

        <Dialog
          open={connectLabelOpen}
          onOpenChange={(open) => {
            setConnectLabelOpen(open)
            if (!open) {
              setConnectTargetNode(null)
              resetConnectMode()
            }
          }}
        >
          <DialogContent className="max-w-md">
            <DialogHeader>
              <DialogTitle>关系名称</DialogTitle>
              <DialogDescription>
                {connectSourceNode?.label && connectTargetNode?.label ? (
                  <>
                    将创建连线：<span className="font-mono">{String(connectSourceNode.label)}</span> →{' '}
                    <span className="font-mono">{String(connectTargetNode.label)}</span>
                  </>
                ) : (
                  '请输入关系名称（例如：related_to）'
                )}
              </DialogDescription>
            </DialogHeader>

            <div className="space-y-2">
              <Label htmlFor="graph-connect-label">关系名称</Label>
              <Input
                id="graph-connect-label"
                value={connectLabelDraft}
                onChange={(e) => setConnectLabelDraft(e.target.value)}
                placeholder="related_to"
                className="font-mono"
              />
              <div className="text-xs text-muted-foreground">
                留空将使用默认值：<span className="font-mono">related_to</span>
              </div>
            </div>

            <DialogFooter>
              <Button type="button" variant="outline" onClick={() => setConnectLabelOpen(false)}>
                取消
              </Button>
              <Button type="button" onClick={confirmConnectionLabel}>
                创建连线
              </Button>
            </DialogFooter>
          </DialogContent>
        </Dialog>
      </PageScaffold>
    </AppFrame>
  )
}
