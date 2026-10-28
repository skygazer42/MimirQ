import type { GraphData, GraphNode } from '@/lib/graph-parser'
import { buildTypeColorMap, EVENT_COLOR } from '@/components/graph/graph-colors'
import { coerceTrimmedString, getGraphLinkEndpointId, getGraphNodeKind, getGraphNodeType } from './graph-page-utils'

export type DirectoryGroup = { key: string; label: string; color: string; nodes: GraphNode[] }

export function graphTypeLabel(node: GraphNode): string {
  const kind = getGraphNodeKind(node)
  if (kind === 'event') return '事件'
  const type = getGraphNodeType(node)
  if (type) return ({ person: '人物', organization: '组织', location: '地点', concept: '概念', ability: '能力', role: '角色', practice: '行为', asset: '资产', outcome: '目标', document: '文档' } as Record<string, string>)[type.toLowerCase()] || type
  return ({ entity: '未分类实体', trace: '检索回放', step: '回放步骤', citation: '引用片段' } as Record<string, string>)[kind] || '其他节点'
}

export function buildDirectoryIndex(graph: GraphData) {
  const nodes = new Map(graph.nodes.map(node => [String(node.id), node]))
  const neighbors = new Map(graph.nodes.map(node => [String(node.id), new Set<string>()]))
  for (const link of graph.links) {
    const source = getGraphLinkEndpointId(link.source)
    const target = getGraphLinkEndpointId(link.target)
    if (source === target || !nodes.has(source) || !nodes.has(target)) continue
    neighbors.get(source)!.add(target)
    neighbors.get(target)!.add(source)
  }
  const colors = buildTypeColorMap(graph.nodes)
  const groups = new Map<string, DirectoryGroup>()
  for (const node of graph.nodes) {
    const kind = getGraphNodeKind(node)
    const type = getGraphNodeType(node)
    const key = `${kind}:${type}`
    let group = groups.get(key)
    if (!group) {
      group = { key, label: graphTypeLabel(node), color: kind === 'event' ? EVENT_COLOR : colors.get(type) || 'hsl(var(--muted-foreground))', nodes: [] }
      groups.set(key, group)
    }
    group.nodes.push(node)
  }
  return { nodes, neighbors, groups: [...groups.values()] }
}

export function searchDirectory(groups: DirectoryGroup[], query: string): DirectoryGroup[] {
  const term = query.trim().toLocaleLowerCase()
  if (!term) return groups
  return groups.flatMap(group => {
    const nodes = group.nodes.filter(node => {
      const aliases = node.meta?.aliases
      const aliasText = Array.isArray(aliases) ? aliases.map(coerceTrimmedString).join(' ') : coerceTrimmedString(aliases)
      return `${node.label} ${node.id} ${group.label} ${aliasText}`.toLocaleLowerCase().includes(term)
    })
    return nodes.length ? [{ ...group, nodes }] : []
  })
}

export function getNeighborhood(graph: GraphData, index: ReturnType<typeof buildDirectoryIndex>, selectedId: string | null, depth: 1 | 2): GraphData {
  if (!selectedId || !index.nodes.has(selectedId)) return graph
  const included = new Set([selectedId])
  let frontier = [selectedId]
  for (let hop = 0; hop < depth; hop++) {
    const next: string[] = []
    for (const id of frontier) for (const neighbor of index.neighbors.get(id) || []) {
      if (!included.has(neighbor)) { included.add(neighbor); next.push(neighbor) }
    }
    frontier = next
  }
  return {
    nodes: graph.nodes.filter(node => included.has(String(node.id))),
    links: graph.links.filter(link => included.has(getGraphLinkEndpointId(link.source)) && included.has(getGraphLinkEndpointId(link.target))),
  }
}
