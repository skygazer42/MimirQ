'use client'

import { useCallback, useMemo } from 'react'
import '@xyflow/react/dist/style.css'
import {
  addEdge,
  applyEdgeChanges,
  applyNodeChanges,
  Background,
  Controls,
  type Connection,
  type Edge,
  type EdgeChange,
  MarkerType,
  type Node,
  type NodeChange,
  Position,
  ReactFlow,
} from '@xyflow/react'

import type { GraphData, GraphNode } from '@/lib/graph-parser'
import { toTrimmedPrimitiveString } from '@/lib/primitive-text'

type JsonRecord = Record<string, unknown>

type WorkflowLayout = {
  schema?: string
  nodes?: JsonRecord[]
  edges?: JsonRecord[]
}

type WorkflowEditorNodeData = {
  label: string
  color: string
  graphNode: GraphNode
}

type WorkflowEditorNode = Node<WorkflowEditorNodeData>
type WorkflowEditorEdge = Edge

const LAYOUT_SCHEMA = 'mimirq.workflow_layout.v1'
const COLUMN_GAP = 280
const ROW_GAP = 112
const ORIGIN_X = 48
const ORIGIN_Y = 48
const FALLBACK_NODE_COLOR = '#94a3b8'

function isRecord(value: unknown): value is JsonRecord {
  return !!value && typeof value === 'object' && !Array.isArray(value)
}

function toFiniteNumber(value: unknown, fallback: number): number {
  const num = typeof value === 'number' ? value : Number(value)
  return Number.isFinite(num) ? num : fallback
}

function getWorkflowLayout(value: JsonRecord | null | undefined): WorkflowLayout {
  return isRecord(value) ? value : {}
}

function buildEdgeId(source: string, target: string, index: number): string {
  return `edge:${source}:${target}:${index}`
}

function buildDefaultPositions(graph: GraphData): Map<string, { x: number, y: number }> {
  const nodeIds = graph.nodes.map((node) => node.id)
  const indegree = new Map<string, number>(nodeIds.map((id) => [id, 0]))
  const children = new Map<string, string[]>()

  for (const link of graph.links) {
    const source = String(link.source || '')
    const target = String(link.target || '')
    if (!source || !target) continue
    children.set(source, [...(children.get(source) || []), target])
    indegree.set(target, (indegree.get(target) || 0) + 1)
  }

  const roots = nodeIds.filter((id) => (indegree.get(id) || 0) === 0)
  const orderedRoots = roots.includes('bundle')
    ? ['bundle', ...roots.filter((id) => id !== 'bundle')]
    : roots

  const depth = new Map<string, number>()
  const queue: Array<[string, number]> = orderedRoots.map((id) => [id, 0])

  while (queue.length > 0) {
    const [id, level] = queue.shift()!
    if (depth.has(id)) continue
    depth.set(id, level)
    for (const childId of children.get(id) || []) {
      if (!depth.has(childId)) queue.push([childId, level + 1])
    }
  }

  let fallbackDepth = Math.max(0, ...depth.values(), 0)
  for (const id of nodeIds) {
    if (!depth.has(id)) {
      fallbackDepth += 1
      depth.set(id, fallbackDepth)
    }
  }

  const rowsByDepth = new Map<number, string[]>()
  for (const node of graph.nodes) {
    const level = depth.get(node.id) || 0
    rowsByDepth.set(level, [...(rowsByDepth.get(level) || []), node.id])
  }

  const positions = new Map<string, { x: number, y: number }>()
  for (const [level, ids] of rowsByDepth.entries()) {
    ids.forEach((id, row) => {
      positions.set(id, {
        x: ORIGIN_X + level * COLUMN_GAP,
        y: ORIGIN_Y + row * ROW_GAP,
      })
    })
  }

  return positions
}

function buildEditorNodes(graph: GraphData, workflowLayout: JsonRecord | null | undefined): WorkflowEditorNode[] {
  const layout = getWorkflowLayout(workflowLayout)
  const layoutNodes = Array.isArray(layout.nodes) ? layout.nodes.filter(isRecord) : []
  const positions = buildDefaultPositions(graph)
  const storedNodeMap = new Map<string, JsonRecord>(
    layoutNodes
      .map((node) => [toTrimmedPrimitiveString(node.id), node] as const)
      .filter(([id]) => !!id)
  )

  return graph.nodes.map((graphNode, index) => {
    const fallbackPosition = positions.get(graphNode.id) || {
      x: ORIGIN_X,
      y: ORIGIN_Y + index * ROW_GAP,
    }
    const storedNode = storedNodeMap.get(graphNode.id)
    const storedPosition = isRecord(storedNode?.position) ? storedNode.position : undefined
    const color = String(graphNode.color || FALLBACK_NODE_COLOR)

    return {
      id: graphNode.id,
      position: {
        x: toFiniteNumber(storedPosition?.x, fallbackPosition.x),
        y: toFiniteNumber(storedPosition?.y, fallbackPosition.y),
      },
      data: {
        label: String(graphNode.label || graphNode.id),
        color,
        graphNode,
      },
      sourcePosition: Position.Right,
      targetPosition: Position.Left,
      style: {
        width: 208,
        borderRadius: 18,
        border: `1px solid ${color}`,
        background: `${color}18`,
        color: 'hsl(var(--foreground))',
        boxShadow: '0 12px 30px rgba(15, 23, 42, 0.08)',
        fontSize: 12,
        fontWeight: 600,
        padding: 12,
      },
    }
  })
}

function buildEditorEdges(
  graph: GraphData,
  workflowLayout: JsonRecord | null | undefined,
  nodeIds: Set<string>
): WorkflowEditorEdge[] {
  const layout = getWorkflowLayout(workflowLayout)
  const hasStoredEdges = Array.isArray(layout.edges)
  const storedEdges = hasStoredEdges ? (layout.edges || []).filter(isRecord) : []
  const sourceEdges = hasStoredEdges ? storedEdges : graph.links

  return sourceEdges.flatMap((edgeLike, index) => {
    const source = toTrimmedPrimitiveString(edgeLike.source)
    const target = toTrimmedPrimitiveString(edgeLike.target)
    if (!source || !target || !nodeIds.has(source) || !nodeIds.has(target)) return []

    const label = typeof edgeLike.label === 'string' && edgeLike.label.trim() ? edgeLike.label.trim() : undefined
    return [{
      id: typeof edgeLike.id === 'string' && edgeLike.id.trim() ? edgeLike.id : buildEdgeId(source, target, index),
      source,
      target,
      label,
      type: 'smoothstep',
      markerEnd: { type: MarkerType.ArrowClosed },
      style: { strokeWidth: 1.5, stroke: '#64748b' },
      labelStyle: { fill: '#475569', fontSize: 11, fontWeight: 600 },
    }]
  })
}

function serializeWorkflowLayout(nodes: WorkflowEditorNode[], edges: WorkflowEditorEdge[]): WorkflowLayout {
  return {
    schema: LAYOUT_SCHEMA,
    nodes: nodes.map((node) => ({
      id: node.id,
      position: {
        x: Math.round(node.position.x),
        y: Math.round(node.position.y),
      },
    })),
    edges: edges.map((edge, index) => ({
      id: edge.id || buildEdgeId(String(edge.source || ''), String(edge.target || ''), index),
      source: String(edge.source || ''),
      target: String(edge.target || ''),
      label: typeof edge.label === 'string' && edge.label.trim() ? edge.label.trim() : undefined,
    })),
  }
}

export interface WorkflowEditorProps {
  graph: GraphData
  workflowLayout?: JsonRecord | null
  onWorkflowLayoutChange?: (layout: WorkflowLayout) => void
  onNodeSelect?: (node: GraphNode | null) => void
}

export function WorkflowEditor({
  graph,
  workflowLayout = null,
  onWorkflowLayoutChange,
  onNodeSelect,
}: Readonly<WorkflowEditorProps>) {
  const nodeIds = useMemo(() => new Set(graph.nodes.map((node) => node.id)), [graph.nodes])
  const nodes = useMemo(() => buildEditorNodes(graph, workflowLayout), [graph, workflowLayout])
  const edges = useMemo(() => buildEditorEdges(graph, workflowLayout, nodeIds), [graph, nodeIds, workflowLayout])

  const publishWorkflowLayout = useCallback((nextNodes: WorkflowEditorNode[], nextEdges: WorkflowEditorEdge[]) => {
    onWorkflowLayoutChange?.(serializeWorkflowLayout(nextNodes, nextEdges))
  }, [onWorkflowLayoutChange])

  const onNodesChange = useCallback((changes: NodeChange<WorkflowEditorNode>[]) => {
    publishWorkflowLayout(applyNodeChanges(changes, nodes), edges)
  }, [edges, nodes, publishWorkflowLayout])

  const onEdgesChange = useCallback((changes: EdgeChange<WorkflowEditorEdge>[]) => {
    publishWorkflowLayout(nodes, applyEdgeChanges(changes, edges))
  }, [edges, nodes, publishWorkflowLayout])

  const onConnect = useCallback((connection: Connection) => {
    if (!connection.source || !connection.target) return
    const nextEdge: WorkflowEditorEdge = {
      ...connection,
      id: buildEdgeId(connection.source, connection.target, edges.length),
      type: 'smoothstep',
      markerEnd: { type: MarkerType.ArrowClosed },
      style: { strokeWidth: 1.5, stroke: '#64748b' },
    }
    publishWorkflowLayout(nodes, addEdge(nextEdge, edges))
  }, [edges, nodes, publishWorkflowLayout])

  const handleNodeClick = useCallback((_event: React.MouseEvent, node: WorkflowEditorNode) => {
    onNodeSelect?.(node.data.graphNode)
  }, [onNodeSelect])

  const handlePaneClick = useCallback(() => {
    onNodeSelect?.(null)
  }, [onNodeSelect])

  return (
    <div className="h-full w-full bg-[radial-gradient(circle_at_top,hsl(var(--primary)/0.12),transparent_38%),linear-gradient(180deg,hsl(var(--background)),hsl(var(--muted)/0.45))]">
      <ReactFlow
        nodes={nodes}
        edges={edges}
        onNodesChange={onNodesChange}
        onEdgesChange={onEdgesChange}
        onConnect={onConnect}
        onNodeClick={handleNodeClick}
        onPaneClick={handlePaneClick}
        defaultEdgeOptions={{ type: 'smoothstep', markerEnd: { type: MarkerType.ArrowClosed } }}
        minZoom={0.45}
        maxZoom={1.8}
        fitView
        proOptions={{ hideAttribution: true }}
      >
        <Background gap={24} size={1} color="rgba(100, 116, 139, 0.25)" />
        <Controls className="!bg-card/95 !border !border-border/70 !rounded-xl overflow-hidden shadow-sm" showInteractive={false} />
      </ReactFlow>
    </div>
  )
}
