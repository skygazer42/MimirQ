'use client'

import { useMemo, useState, type ReactNode } from 'react'
import { Activity, GitBranch, Network } from 'lucide-react'
import { toast } from 'sonner'

import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Label } from '@/components/ui/label'
import { Popover, PopoverContent, PopoverTrigger } from '@/components/ui/popover'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
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

function endpointId(value: unknown): string {
  if (typeof value === 'string') return value
  if (value && typeof value === 'object' && 'id' in value) return String((value as { id?: unknown }).id || '')
  return String(value || '')
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

export function KgNetworkAnalysisPanel({ nodes, links, selectedNodeId }: KgNetworkAnalysisPanelProps) {
  const edges = useMemo(() => toNetworkEdges(links), [links])
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
  const operationResult = result ? { title: result.title, payload: { endpoint: result.endpoint, response: result.payload } } : null
  const buttonClass = 'h-8 gap-1.5 rounded-lg px-3 text-xs font-semibold'

  async function runAction(key: string, title: string, endpoint: string, action: () => Promise<unknown>): Promise<void> {
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

  return (
    <div className="absolute right-8 top-24 z-20">
      <Popover>
        <PopoverTrigger asChild>
          <Button
            type="button"
            variant="outline"
            className="h-9 gap-2 rounded-xl border-border/60 bg-card/92 text-xs font-semibold shadow-soft backdrop-blur-sm"
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
              <Field label="Start">
                <Input value={startId} onChange={(event) => setStartId(event.target.value)} className="h-8 font-mono text-xs" />
              </Field>
              <Field label="Target">
                <Input value={targetId} onChange={(event) => setTargetId(event.target.value)} className="h-8 font-mono text-xs" />
              </Field>
              <Field label="Node">
                <Input value={nodeId} onChange={(event) => setNodeId(event.target.value)} className="h-8 font-mono text-xs" />
              </Field>
              <Field label="Max hops">
                <Input
                  value={String(maxHops)}
                  onChange={(event) => setMaxHops(Number.parseInt(event.target.value || '0', 10) || 3)}
                  className="h-8 font-mono text-xs"
                  inputMode="numeric"
                />
              </Field>
              <Field label="Top K">
                <Input
                  value={String(topK)}
                  onChange={(event) => setTopK(Number.parseInt(event.target.value || '0', 10) || 10)}
                  className="h-8 font-mono text-xs"
                  inputMode="numeric"
                />
              </Field>
              <Field label="Centrality">
                <Select value={algorithm} onValueChange={(value) => setAlgorithm(value as 'degree' | 'pagerank')}>
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
              <Button variant="outline" className={buttonClass} disabled={actionDisabled} onClick={() => detachPromise(runAction('hop', 'K-hop 邻居', 'POST /kg/network/k_hop_neighbors', () => kgApi.getKHopNeighbors(request)))}>
                <Network className="h-3.5 w-3.5" />
                K-hop
              </Button>
              <Button variant="outline" className={buttonClass} disabled={actionDisabled} onClick={() => detachPromise(runAction('shortest', '最短路径', 'POST /kg/network/shortest_path', () => kgApi.getShortestPath(request)))}>
                <Network className="h-3.5 w-3.5" />
                最短路径
              </Button>
              <Button variant="outline" className={buttonClass} disabled={actionDisabled} onClick={() => detachPromise(runAction('paths', '路径枚举', 'POST /kg/network/paths_between', () => kgApi.getPathsBetween(request)))}>
                <Network className="h-3.5 w-3.5" />
                路径枚举
              </Button>
              <Button variant="outline" className={buttonClass} disabled={actionDisabled} onClick={() => detachPromise(runAction('centrality', '中心性', 'POST /kg/network/centrality', () => kgApi.getCentrality(request)))}>
                <Activity className="h-3.5 w-3.5" />
                中心性
              </Button>
              <Button variant="outline" className={buttonClass} disabled={actionDisabled} onClick={() => detachPromise(runAction('community', '社区归属', 'POST /kg/network/community_of', () => kgApi.getCommunityOf(request)))}>
                <Activity className="h-3.5 w-3.5" />
                社区归属
              </Button>
              <Button variant="outline" className={buttonClass} disabled={actionDisabled} onClick={() => detachPromise(runAction('component', '连通分量', 'POST /kg/network/connected_component', () => kgApi.getConnectedComponent(request)))}>
                <Activity className="h-3.5 w-3.5" />
                连通分量
              </Button>
            </div>

            <OperationResultPanel title="网络分析结果" result={operationResult} emptyMessage="选择上方网络分析动作后，这里展示执行摘要；原始响应默认收起。" />
          </div>
        </PopoverContent>
      </Popover>
    </div>
  )
}

function Field({ label, children }: Readonly<{ label: string; children: ReactNode }>) {
  return (
    <div className="space-y-1">
      <Label className="text-[11px] font-medium text-muted-foreground">{label}</Label>
      {children}
    </div>
  )
}
