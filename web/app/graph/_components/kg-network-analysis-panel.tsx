'use client'

import { useMemo, useRef, useState, type PointerEvent as ReactPointerEvent, type ReactNode } from 'react'
import {
  Activity,
  BarChart3,
  Filter,
  GitBranch,
  GripHorizontal,
  MousePointer2,
  Network,
  PanelRightClose,
  PanelRightOpen,
} from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import {
  Popover,
  PopoverContent,
  PopoverTrigger,
} from '@/components/ui/popover'
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select'
import { OperationResultPanel } from '@/components/ops/operation-result-panel'
import { kgApi, type KGNetworkEdge, type KGNetworkRequest } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import type { GraphData } from '@/lib/graph-parser'
import { detachPromise } from '@/lib/utils'

type KgNetworkAnalysisPanelProps = Readonly<{
  nodes: GraphData['nodes']
  links: GraphData['links']
  selectedNodeId?: string | null
}>

type ResultState = {
  title: string
  endpoint: string
  payload: unknown
}

type PanelDragState = {
  pointerId: number
  startClientX: number
  startClientY: number
  startX: number
  startY: number
} | null

function primitiveEndpointString(value: unknown): string {
  if (typeof value === 'string') return value
  if (typeof value === 'number' || typeof value === 'boolean' || typeof value === 'bigint') {
    return String(value)
  }
  return ''
}

function endpointId(value: unknown): string {
  if (value && typeof value === 'object' && 'id' in value) {
    return primitiveEndpointString((value as { id?: unknown }).id)
  }
  return primitiveEndpointString(value)
}

function toNetworkEdges(links: GraphData['links']): KGNetworkEdge[] {
  const edges: KGNetworkEdge[] = []
  for (const link of links) {
    const source = endpointId(link.source)
    const target = endpointId(link.target)
    if (!source || !target) continue
    const rawWeight = link.weight ?? link.value ?? link.score
    const weight = Number(rawWeight)
    edges.push({
      source,
      target,
      ...(Number.isFinite(weight) ? { weight } : {}),
    })
  }
  return edges
}

function getNodeType(node: GraphData['nodes'][number]): string {
  return String(node?.meta?.type ?? node?.type ?? '').trim() || '未知类型'
}

function getLinkType(link: GraphData['links'][number]): string {
  return (
    String(
      link?.label ?? link?.predicate ?? link?.meta?.label ?? link?.kind ?? ''
    ).trim() || '关系'
  )
}

export function KgNetworkAnalysisPanel({
  nodes,
  links,
  selectedNodeId,
}: KgNetworkAnalysisPanelProps) {
  const edges = useMemo(() => toNetworkEdges(links), [links])
  const selectedNode = useMemo(
    () =>
      nodes.find(
        (node) => String(node?.id ?? '') === String(selectedNodeId || '')
      ) ?? null,
    [nodes, selectedNodeId]
  )
  const nodeTypeStats = useMemo(() => {
    const countMap = new Map<string, { count: number; color: string }>()
    for (const node of nodes) {
      const label = getNodeType(node)
      const color = String(node?.color || '').trim() || '#94a3b8'
      const entry = countMap.get(label)
      countMap.set(label, {
        count: (entry?.count ?? 0) + 1,
        color: entry?.color || color,
      })
    }
    return [...countMap.entries()]
      .map(([label, value]) => ({ label, ...value }))
      .sort((left, right) => right.count - left.count)
      .slice(0, 6)
  }, [nodes])
  const relationStats = useMemo(() => {
    const countMap = new Map<string, { count: number; color: string }>()
    for (const link of links) {
      const label = getLinkType(link)
      const color = String(link?.color || '').trim() || '#3b82f6'
      const entry = countMap.get(label)
      countMap.set(label, {
        count: (entry?.count ?? 0) + 1,
        color: entry?.color || color,
      })
    }
    return [...countMap.entries()]
      .map(([label, value]) => ({ label, ...value }))
      .sort((left, right) => right.count - left.count)
      .slice(0, 6)
  }, [links])
  const firstNodeId = nodes[0]?.id || ''
  const secondNodeId = nodes[1]?.id || firstNodeId
  const [startId, setStartId] = useState(selectedNodeId || firstNodeId)
  const [targetId, setTargetId] = useState(secondNodeId)
  const [nodeId, setNodeId] = useState(selectedNodeId || firstNodeId)
  const [algorithm, setAlgorithm] = useState<'degree' | 'pagerank'>('degree')
  const [maxHops, setMaxHops] = useState(3)
  const [topK, setTopK] = useState(10)
  const [runningKey, setRunningKey] = useState<string | null>(null)
  const [result, setResult] = useState<ResultState | null>(null)
  const [collapsed, setCollapsed] = useState(false)
  const [panelOffset, setPanelOffset] = useState({ x: 0, y: 0 })
  const dragStateRef = useRef<PanelDragState>(null)

  const request: KGNetworkRequest = {
    edges,
    start_id: startId.trim() || undefined,
    target_id: targetId.trim() || undefined,
    node_id: nodeId.trim() || undefined,
    algorithm,
    max_hops: maxHops,
    top_k: topK,
  }
  const actionDisabled = edges.length === 0 || Boolean(runningKey)
  const operationResult = result
    ? {
        title: result.title,
        payload: { endpoint: result.endpoint, response: result.payload },
      }
    : null
  const buttonClass = 'h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold'
  const panelDragStyle = {
    transform: `translate3d(${panelOffset.x}px, ${panelOffset.y}px, 0)`,
  }

  function startPanelDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    if (event.button !== 0) return
    event.preventDefault()
    event.currentTarget.setPointerCapture(event.pointerId)
    dragStateRef.current = {
      pointerId: event.pointerId,
      startClientX: event.clientX,
      startClientY: event.clientY,
      startX: panelOffset.x,
      startY: panelOffset.y,
    }
  }

  function movePanel(event: ReactPointerEvent<HTMLButtonElement>) {
    const drag = dragStateRef.current
    if (drag?.pointerId !== event.pointerId) return
    setPanelOffset({
      x: drag.startX + event.clientX - drag.startClientX,
      y: drag.startY + event.clientY - drag.startClientY,
    })
  }

  function stopPanelDrag(event: ReactPointerEvent<HTMLButtonElement>) {
    const drag = dragStateRef.current
    if (drag?.pointerId !== event.pointerId) return
    dragStateRef.current = null
    event.currentTarget.releasePointerCapture(event.pointerId)
  }

  async function runAction(
    key: string,
    title: string,
    endpoint: string,
    action: () => Promise<unknown>
  ): Promise<void> {
    setRunningKey(key)
    try {
      const payload = await action()
      setResult({ title, endpoint, payload })
      toast.success(`${title}完成`)
    } catch (error) {
      toast.error(formatApiError(error, `${title}失败`))
    } finally {
      setRunningKey(null)
    }
  }

  if (collapsed) {
    return (
      <div className="absolute right-[6.75rem] top-24 z-20 transition-transform duration-150" style={panelDragStyle}>
        <Button
          type="button"
          variant="outline"
          className="h-10 gap-2 rounded-full border-border/60 bg-card/90 px-3 text-xs font-semibold shadow-soft backdrop-blur-md"
          aria-label="展开图谱统计栏"
          aria-expanded="false"
          aria-controls="kg-network-analysis-panel"
          onClick={() => setCollapsed(false)}
        >
          <PanelRightOpen className="h-4 w-4 text-blue-500" />
          <span>统计</span>
          <span className="rounded-full bg-muted/60 px-2 py-0.5 font-mono text-[11px] text-muted-foreground">
            {nodes.length}/{links.length}
          </span>
        </Button>
      </div>
    )
  }

  return (
    <div
      id="kg-network-analysis-panel"
      data-draggable-kg-analysis-panel="true"
      className="absolute right-[6.75rem] top-24 z-20 w-[286px] space-y-3 will-change-transform"
      style={panelDragStyle}
    >
      <section className="rounded-2xl border border-border/60 bg-card/92 p-4 shadow-soft backdrop-blur-md">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-xl bg-slate-900 text-info-foreground shadow-sm">
              <BarChart3 className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <div className="text-sm font-semibold text-foreground">
                统计信息
              </div>
              <p className="mt-0.5 text-[11px] leading-4 text-muted-foreground">
                数据概览与交互信息
              </p>
            </div>
          </div>
          <div className="flex shrink-0 items-center gap-1">
            <button
              type="button"
              className="flex h-8 w-8 cursor-grab items-center justify-center rounded-xl text-muted-foreground transition-colors hover:bg-primary/10 hover:text-primary active:cursor-grabbing"
              aria-label="拖动图谱统计栏"
              title="拖动图谱统计栏"
              onPointerDown={startPanelDrag}
              onPointerMove={movePanel}
              onPointerUp={stopPanelDrag}
              onPointerCancel={stopPanelDrag}
            >
              <GripHorizontal className="h-4 w-4" />
            </button>
            <Button
              type="button"
              variant="ghost"
              size="icon"
              className="h-8 w-8 rounded-xl text-muted-foreground hover:bg-muted/60 hover:text-foreground"
              aria-label="收起图谱统计栏"
              aria-expanded="true"
              aria-controls="kg-network-analysis-panel"
              onClick={() => setCollapsed(true)}
            >
              <PanelRightClose className="h-4 w-4" />
            </Button>
          </div>
        </div>

        <div className="rounded-xl border border-dashed border-border/70 bg-background/72 p-3">
          <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-foreground">
            <MousePointer2 className="h-3.5 w-3.5 text-blue-500" />
            选中单元
          </div>
          {selectedNode ? (
            <div className="space-y-1">
              <div
                className="truncate text-sm font-semibold text-foreground"
                title={selectedNode.label || selectedNode.id}
              >
                {selectedNode.label || selectedNode.id}
              </div>
              <div className="text-[11px] text-muted-foreground">
                {getNodeType(selectedNode)}
              </div>
            </div>
          ) : (
            <div className="flex min-h-[92px] items-center justify-center rounded-lg bg-muted/30 px-3 text-center text-xs leading-5 text-muted-foreground">
              点击任意图谱节点后，在这里查看节点类型、关系和后续分析入口。
            </div>
          )}
        </div>
      </section>

      <section className="rounded-2xl border border-border/60 bg-card/92 p-4 shadow-soft backdrop-blur-md">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <div className="text-sm font-semibold text-foreground">
              筛选器控制
            </div>
          </div>
          <div className="rounded-full bg-muted/55 px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
            {nodes.length} / {links.length}
          </div>
        </div>

        <div className="space-y-3">
          <MetricGroup title={`节点类型 ${nodeTypeStats.length}`}>
            {nodeTypeStats.map((entry) => (
              <MetricRow
                key={entry.label}
                color={entry.color}
                label={entry.label}
                count={entry.count}
              />
            ))}
          </MetricGroup>
          <MetricGroup title={`关系类型 ${relationStats.length}`}>
            {relationStats.map((entry) => (
              <MetricRow
                key={entry.label}
                color={entry.color}
                label={entry.label}
                count={entry.count}
              />
            ))}
          </MetricGroup>
        </div>
      </section>

      <Popover>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            className="h-9 w-full gap-2 rounded-xl border-border/60 bg-card/92 text-xs font-semibold shadow-soft backdrop-blur-sm"
            disabled={edges.length === 0}
          >
            <Network className="h-4 w-4" />
            网络分析
            <span className="font-mono text-[11px] text-muted-foreground">
              {edges.length}
            </span>
          </Button>
        </PopoverTrigger>
        <PopoverContent side="left" align="start" className="w-[420px] p-3">
          <div className="space-y-3">
            <div>
              <div className="flex items-center gap-2 text-sm font-semibold">
                <GitBranch className="h-4 w-4 text-info" />
                KG Network API
              </div>
              <p className="mt-1 text-xs leading-relaxed text-muted-foreground">
                使用当前图谱画布的边作为输入，直接调用后端网络分析接口。
              </p>
            </div>

            <div className="grid gap-2 sm:grid-cols-3">
              <Field label="Start">
                <Input
                  value={startId}
                  onChange={(event) => setStartId(event.target.value)}
                  className="h-8 font-mono text-xs"
                />
              </Field>
              <Field label="Target">
                <Input
                  value={targetId}
                  onChange={(event) => setTargetId(event.target.value)}
                  className="h-8 font-mono text-xs"
                />
              </Field>
              <Field label="Node">
                <Input
                  value={nodeId}
                  onChange={(event) => setNodeId(event.target.value)}
                  className="h-8 font-mono text-xs"
                />
              </Field>
              <Field label="Max hops">
                <Input
                  value={String(maxHops)}
                  onChange={(event) =>
                    setMaxHops(
                      Number.parseInt(event.target.value || '0', 10) || 3
                    )
                  }
                  className="h-8 font-mono text-xs"
                  inputMode="numeric"
                />
              </Field>
              <Field label="Top K">
                <Input
                  value={String(topK)}
                  onChange={(event) =>
                    setTopK(
                      Number.parseInt(event.target.value || '0', 10) || 10
                    )
                  }
                  className="h-8 font-mono text-xs"
                  inputMode="numeric"
                />
              </Field>
              <Field label="Centrality">
                <Select
                  value={algorithm}
                  onValueChange={(value) =>
                    setAlgorithm(value as 'degree' | 'pagerank')
                  }
                >
                  <SelectTrigger className="h-8 text-xs">
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    <SelectItem value="degree">degree</SelectItem>
                    <SelectItem value="pagerank">pagerank</SelectItem>
                  </SelectContent>
                </Select>
              </Field>
            </div>

            <div className="flex flex-wrap gap-2">
              <Button
                variant="outline"
                className={buttonClass}
                disabled={actionDisabled}
                onClick={() =>
                  detachPromise(
                    runAction(
                      'hop',
                      'K-hop 邻居',
                      'POST /kg/network/k_hop_neighbors',
                      () => kgApi.getKHopNeighbors(request)
                    )
                  )
                }
              >
                <Network className="h-3.5 w-3.5" />
                K-hop
              </Button>
              <Button
                variant="outline"
                className={buttonClass}
                disabled={actionDisabled}
                onClick={() =>
                  detachPromise(
                    runAction(
                      'shortest',
                      '最短路径',
                      'POST /kg/network/shortest_path',
                      () => kgApi.getShortestPath(request)
                    )
                  )
                }
              >
                <Network className="h-3.5 w-3.5" />
                最短路径
              </Button>
              <Button
                variant="outline"
                className={buttonClass}
                disabled={actionDisabled}
                onClick={() =>
                  detachPromise(
                    runAction(
                      'paths',
                      '路径枚举',
                      'POST /kg/network/paths_between',
                      () => kgApi.getPathsBetween(request)
                    )
                  )
                }
              >
                <Network className="h-3.5 w-3.5" />
                路径枚举
              </Button>
              <Button
                variant="outline"
                className={buttonClass}
                disabled={actionDisabled}
                onClick={() =>
                  detachPromise(
                    runAction(
                      'centrality',
                      '中心性',
                      'POST /kg/network/centrality',
                      () => kgApi.getCentrality(request)
                    )
                  )
                }
              >
                <Activity className="h-3.5 w-3.5" />
                中心性
              </Button>
              <Button
                variant="outline"
                className={buttonClass}
                disabled={actionDisabled}
                onClick={() =>
                  detachPromise(
                    runAction(
                      'community',
                      '社区归属',
                      'POST /kg/network/community_of',
                      () => kgApi.getCommunityOf(request)
                    )
                  )
                }
              >
                <Activity className="h-3.5 w-3.5" />
                社区归属
              </Button>
              <Button
                variant="outline"
                className={buttonClass}
                disabled={actionDisabled}
                onClick={() =>
                  detachPromise(
                    runAction(
                      'component',
                      '连通分量',
                      'POST /kg/network/connected_component',
                      () => kgApi.getConnectedComponent(request)
                    )
                  )
                }
              >
                <Activity className="h-3.5 w-3.5" />
                连通分量
              </Button>
            </div>

            <OperationResultPanel
              title="网络分析结果"
              result={operationResult}
              emptyMessage="选择上方网络分析动作后，这里展示执行摘要；原始响应默认收起。"
            />
          </div>
        </PopoverContent>
      </Popover>
    </div>
  )
}

function MetricGroup({
  title,
  children,
}: Readonly<{ title: string; children: ReactNode }>) {
  return (
    <div>
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">
        {title}
      </div>
      <div className="space-y-1.5">{children}</div>
    </div>
  )
}

function MetricRow({
  color,
  label,
  count,
}: Readonly<{ color: string; label: string; count: number }>) {
  return (
    <div className="flex items-center justify-between gap-3 text-xs">
      <div className="flex min-w-0 items-center gap-2">
        <span
          className="h-2.5 w-2.5 flex-none rounded-full ring-2 ring-white/80"
          style={{ backgroundColor: color }}
        />
        <span className="truncate text-foreground/80" title={label}>
          {label}
        </span>
      </div>
      <span className="font-mono text-[11px] text-muted-foreground">
        {count}
      </span>
    </div>
  )
}

function Field({
  label,
  children,
}: Readonly<{ label: string; children: ReactNode }>) {
  return (
    <div className="space-y-1">
      <Label className="text-[11px] font-medium text-muted-foreground">
        {label}
      </Label>
      {children}
    </div>
  )
}
