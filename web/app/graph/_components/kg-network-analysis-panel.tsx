'use client'

import { useLayoutEffect, useMemo, useRef, useState, type ReactNode } from 'react'
import { Activity, BarChart3, Filter, GitBranch, MousePointer2, Network } from '@/components/icons'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { OperationResultPanel } from '@/components/ops/operation-result-panel'
import { SettingsNumberInput } from '@/components/settings/settings-number-input'
import { kgApi, type KGNetworkEdge, type KGNetworkRequest } from '@/lib/api'
import { formatApiError } from '@/lib/api-errors'
import type { GraphData } from '@/lib/graph-types'
import { readNonEmptyString, toTrimmedPrimitiveString } from '@/lib/primitive-text'
import { detachPromise } from '@/lib/utils'
import { getGraphLinkEndpointId } from '../graph-page-utils'

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

function toNetworkEdges(links: GraphData['links']): KGNetworkEdge[] {
  const edges: KGNetworkEdge[] = []
  for (const link of links) {
    const source = getGraphLinkEndpointId(link.source)
    const target = getGraphLinkEndpointId(link.target)
    if (source === '' || target === '') continue
    const rawWeight = link.weight ?? link.value ?? link.score
    const weight = typeof rawWeight === 'string' && rawWeight.trim() !== '' ? Number(rawWeight) : rawWeight
    const edge: KGNetworkEdge = { source, target }
    if (typeof weight === 'number' && Number.isFinite(weight)) edge.weight = weight
    edges.push(edge)
  }
  return edges
}

function getNodeType(node: GraphData['nodes'][number]): string {
  return toTrimmedPrimitiveString(node.meta?.type ?? node.type, '未知类型')
}

function getLinkType(link: GraphData['links'][number]): string {
  return toTrimmedPrimitiveString(link.label ?? link.predicate ?? link.meta?.label ?? link.kind, '关系')
}

export function KgNetworkAnalysisPanel({ nodes, links, selectedNodeId }: KgNetworkAnalysisPanelProps) {
  const edges = useMemo(() => toNetworkEdges(links), [links])
  const selectedNode = useMemo(() => nodes.find((node) => node.id === selectedNodeId) ?? null, [nodes, selectedNodeId])
  const nodeTypeStats = useMemo(() => {
    const countMap = new Map<string, { count: number; color: string }>()
    for (const node of nodes) {
      const label = getNodeType(node)
      const color = node.color?.trim() || '#94a3b8'
      const entry = countMap.get(label)
      countMap.set(label, {
        count: (entry?.count ?? 0) + 1,
        color: entry?.color ?? color,
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
      const color = link.color?.trim() || '#3b82f6'
      const entry = countMap.get(label)
      countMap.set(label, {
        count: (entry?.count ?? 0) + 1,
        color: entry?.color ?? color,
      })
    }
    return [...countMap.entries()]
      .map(([label, value]) => ({ label, ...value }))
      .sort((left, right) => right.count - left.count)
      .slice(0, 6)
  }, [links])
  const firstNodeId = nodes[0]?.id ?? ''
  const secondNodeId = nodes[1]?.id ?? firstNodeId
  const [startId, setStartId] = useState(selectedNodeId ?? firstNodeId)
  const [targetId, setTargetId] = useState(secondNodeId)
  const [nodeId, setNodeId] = useState(selectedNodeId ?? firstNodeId)
  const [algorithm, setAlgorithm] = useState<'degree' | 'pagerank'>('degree')
  const [maxHops, setMaxHops] = useState(3)
  const [topK, setTopK] = useState(10)
  const [isAnalyzing, setIsAnalyzing] = useState(false)
  const [result, setResult] = useState<ResultState | null>(null)
  const activeRequest = useRef<AbortController | null>(null)

  useLayoutEffect(() => {
    setIsAnalyzing(false)
    setResult(null)
    return () => {
      activeRequest.current?.abort()
      activeRequest.current = null
    }
  }, [edges])

  const request: KGNetworkRequest = {
    edges,
    start_id: readNonEmptyString(startId),
    target_id: readNonEmptyString(targetId),
    node_id: readNonEmptyString(nodeId),
    algorithm,
    max_hops: maxHops,
    top_k: topK,
  }
  const actionDisabled = edges.length === 0 || isAnalyzing
  const operationResult = result
    ? {
        title: result.title,
        payload: { endpoint: result.endpoint, response: result.payload },
      }
    : null
  const buttonClass = 'h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold'

  async function runAction(
    title: string,
    endpoint: string,
    analyze: (body: KGNetworkRequest, options: { signal: AbortSignal }) => Promise<unknown>,
  ): Promise<void> {
    if (edges.length === 0 || activeRequest.current !== null) return
    const controller = new AbortController()
    activeRequest.current = controller
    const isCurrent = () => activeRequest.current === controller
    setIsAnalyzing(true)
    try {
      const payload = await analyze(request, { signal: controller.signal })
      if (!isCurrent()) return
      setResult({ title, endpoint, payload })
      toast.success(`${title}完成`)
    } catch (error) {
      if (isCurrent()) toast.error(formatApiError(error, `${title}失败`))
    } finally {
      if (isCurrent()) {
        activeRequest.current = null
        setIsAnalyzing(false)
      }
    }
  }

  return (
    <div id="kg-network-analysis-panel" className="relative w-full space-y-4">
      <section className="rounded-xl border border-info/15 bg-background/88 p-4 shadow-none">
        <div className="mb-3 flex items-start justify-between gap-3">
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex h-10 w-10 shrink-0 items-center justify-center rounded-lg border border-info/20 bg-info/[0.08] text-info shadow-none">
              <BarChart3 className="h-4 w-4" />
            </div>
            <div className="min-w-0">
              <div className="text-sm font-semibold text-foreground">统计信息</div>
              <p className="mt-0.5 text-[11px] leading-4 text-muted-foreground">数据概览与交互信息</p>
            </div>
          </div>
        </div>

        <div className="rounded-lg border border-dashed border-info/20 bg-info/[0.025] p-3">
          <div className="mb-2 flex items-center gap-1.5 text-xs font-semibold text-foreground">
            <MousePointer2 className="h-3.5 w-3.5 text-info" />
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
              <div className="text-[11px] text-muted-foreground">{getNodeType(selectedNode)}</div>
            </div>
          ) : (
            <div className="flex min-h-[92px] items-center justify-center rounded-md bg-info/[0.035] px-3 text-center text-xs leading-5 text-muted-foreground">
              点击任意图谱节点后，在这里查看节点类型、关系和后续分析入口。
            </div>
          )}
        </div>
      </section>

      <section className="rounded-xl border border-info/15 bg-background/88 p-4 shadow-none">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div className="flex items-center gap-2">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <div className="text-sm font-semibold text-foreground">筛选器控制</div>
          </div>
          <div className="rounded-full bg-info/[0.06] px-2 py-0.5 text-[11px] font-medium text-muted-foreground">
            {nodes.length} / {links.length}
          </div>
        </div>

        <div className="space-y-3">
          <MetricGroup title={`节点类型 ${nodeTypeStats.length}`}>
            {nodeTypeStats.map((entry) => (
              <MetricRow key={entry.label} color={entry.color} label={entry.label} count={entry.count} />
            ))}
          </MetricGroup>
          <MetricGroup title={`关系类型 ${relationStats.length}`}>
            {relationStats.map((entry) => (
              <MetricRow key={entry.label} color={entry.color} label={entry.label} count={entry.count} />
            ))}
          </MetricGroup>
        </div>
      </section>

      <Popover>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            className="h-9 w-full gap-2 rounded-lg border-info/15 bg-background/88 text-xs font-semibold shadow-none"
            disabled={edges.length === 0}
          >
            <Network className="h-4 w-4" />
            网络分析
            <span className="font-mono text-[11px] text-muted-foreground">{edges.length}</span>
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
              <Field id="kg-network-start" label="Start">
                <Input
                  id="kg-network-start"
                  value={startId}
                  onChange={(event) => setStartId(event.target.value)}
                  className="h-8 font-mono text-xs"
                />
              </Field>
              <Field id="kg-network-target" label="Target">
                <Input
                  id="kg-network-target"
                  value={targetId}
                  onChange={(event) => setTargetId(event.target.value)}
                  className="h-8 font-mono text-xs"
                />
              </Field>
              <Field id="kg-network-node" label="Node">
                <Input
                  id="kg-network-node"
                  value={nodeId}
                  onChange={(event) => setNodeId(event.target.value)}
                  className="h-8 font-mono text-xs"
                />
              </Field>
              <Field id="kg-network-hops" label="Max hops">
                <SettingsNumberInput
                  id="kg-network-hops"
                  value={maxHops}
                  min={1}
                  max={10}
                  onValueChange={setMaxHops}
                  className="h-8 font-mono text-xs"
                />
              </Field>
              <Field id="kg-network-top-k" label="Top K">
                <SettingsNumberInput
                  id="kg-network-top-k"
                  value={topK}
                  min={1}
                  max={100}
                  onValueChange={setTopK}
                  className="h-8 font-mono text-xs"
                />
              </Field>
              <Field id="kg-network-centrality" label="Centrality">
                <Select
                  value={algorithm}
                  onValueChange={(value) => {
                    if (value === 'degree' || value === 'pagerank') setAlgorithm(value)
                  }}
                >
                  <SelectTrigger id="kg-network-centrality" className="h-8 text-xs">
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
                  detachPromise(runAction('K-hop 邻居', 'POST /kg/network/k_hop_neighbors', kgApi.getKHopNeighbors))
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
                  detachPromise(runAction('最短路径', 'POST /kg/network/shortest_path', kgApi.getShortestPath))
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
                  detachPromise(runAction('路径枚举', 'POST /kg/network/paths_between', kgApi.getPathsBetween))
                }
              >
                <Network className="h-3.5 w-3.5" />
                路径枚举
              </Button>
              <Button
                variant="outline"
                className={buttonClass}
                disabled={actionDisabled}
                onClick={() => detachPromise(runAction('中心性', 'POST /kg/network/centrality', kgApi.getCentrality))}
              >
                <Activity className="h-3.5 w-3.5" />
                中心性
              </Button>
              <Button
                variant="outline"
                className={buttonClass}
                disabled={actionDisabled}
                onClick={() =>
                  detachPromise(runAction('社区归属', 'POST /kg/network/community_of', kgApi.getCommunityOf))
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
                    runAction('连通分量', 'POST /kg/network/connected_component', kgApi.getConnectedComponent),
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

function MetricGroup({ title, children }: Readonly<{ title: string; children: ReactNode }>) {
  return (
    <div>
      <div className="mb-2 text-[11px] font-semibold uppercase tracking-[0.12em] text-muted-foreground">{title}</div>
      <div className="space-y-1.5">{children}</div>
    </div>
  )
}

function MetricRow({ color, label, count }: Readonly<{ color: string; label: string; count: number }>) {
  return (
    <div className="flex items-center justify-between gap-3 text-xs">
      <div className="flex min-w-0 items-center gap-2">
        <span className="h-2.5 w-2.5 flex-none rounded-full ring-2 ring-white/80" style={{ backgroundColor: color }} />
        <span className="truncate text-foreground/80" title={label}>
          {label}
        </span>
      </div>
      <span className="font-mono text-[11px] text-muted-foreground">{count}</span>
    </div>
  )
}

function Field({ id, label, children }: Readonly<{ id: string; label: string; children: ReactNode }>) {
  return (
    <div className="space-y-1">
      <Label htmlFor={id} className="text-[11px] font-medium text-muted-foreground">
        {label}
      </Label>
      {children}
    </div>
  )
}
