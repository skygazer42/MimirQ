import {
  Box,
  Brain,
  FolderOpen,
  Network,
  Sparkles,
  Star,
  User,
} from 'lucide-react'
import type { ReactNode } from 'react'

import { toTrimmedPrimitiveString } from '@/lib/primitive-text'
import { cn } from '@/lib/utils'
import type { KGGraphLink, KGGraphNode, KGGraphResponse } from '@/types'

import { SNAPSHOT_NODE_TONE_CLASSES } from './constants'
import type { SnapshotStudioLink, SnapshotStudioNode } from './types'
import { firstDisplayString } from './utils'

export function getLinkEndpointId(value: unknown): string {
  if (typeof value === 'string' || typeof value === 'number')
    return String(value)
  if (value && typeof value === 'object') {
    const record = value as Record<string, unknown>
    return firstDisplayString(record.id, record.name, record.label)
  }
  return ''
}

export function getNodeMetaValue(node: KGGraphNode, ...keys: string[]): unknown {
  const meta = node.meta && typeof node.meta === 'object' ? node.meta : {}
  const nodeRecord = node as unknown as Record<string, unknown>
  for (const key of keys) {
    const direct = nodeRecord[key]
    if (direct != null && direct !== '') return direct
    const metaValue = (meta as Record<string, unknown>)[key]
    if (metaValue != null && metaValue !== '') return metaValue
  }
  return undefined
}

export function getNodeType(node: KGGraphNode): string {
  return (
    firstDisplayString(getNodeMetaValue(node, 'type', 'entity_type', 'kind', 'node_type')) ||
    '节点'
  )
}

export function getLinkValue(link: KGGraphLink, ...keys: string[]): unknown {
  const linkRecord = link as unknown as Record<string, unknown>
  const meta = link.meta && typeof link.meta === 'object' ? link.meta : {}
  for (const key of keys) {
    const direct = linkRecord[key]
    if (direct != null && direct !== '') return direct
    const metaValue = (meta as Record<string, unknown>)[key]
    if (metaValue != null && metaValue !== '') return metaValue
  }
  return undefined
}

export function toneForNodeType(type: string): SnapshotStudioNode['tone'] {
  const normalized = type.toLowerCase()
  if (normalized.includes('event') || normalized.includes('事件'))
    return 'orange'
  if (normalized.includes('document') || normalized.includes('文档'))
    return 'amber'
  if (normalized.includes('model') || normalized.includes('模型'))
    return 'purple'
  if (
    normalized.includes('person') ||
    normalized.includes('用户') ||
    normalized.includes('人员')
  )
    return 'green'
  if (normalized.includes('feedback') || normalized.includes('评价'))
    return 'rose'
  if (normalized.includes('technology') || normalized.includes('技术'))
    return 'teal'
  return 'blue'
}

export function iconForNodeType(type: string): ReactNode {
  const normalized = type.toLowerCase()
  if (normalized.includes('event') || normalized.includes('事件'))
    return <Sparkles className="h-5 w-5" aria-hidden="true" />
  if (normalized.includes('document') || normalized.includes('文档'))
    return <FolderOpen className="h-5 w-5" aria-hidden="true" />
  if (normalized.includes('model') || normalized.includes('模型'))
    return <Brain className="h-5 w-5" aria-hidden="true" />
  if (
    normalized.includes('person') ||
    normalized.includes('用户') ||
    normalized.includes('人员')
  )
    return <User className="h-5 w-5" aria-hidden="true" />
  if (normalized.includes('feedback') || normalized.includes('评价'))
    return <Star className="h-5 w-5" aria-hidden="true" />
  if (normalized.includes('technology') || normalized.includes('技术'))
    return <Box className="h-5 w-5" aria-hidden="true" />
  return <Network className="h-5 w-5" aria-hidden="true" />
}

export function strengthForWeight(weight: unknown): SnapshotStudioLink['strength'] {
  const value = Number(weight ?? 1)
  if (!Number.isFinite(value)) return 'medium'
  if (value >= 0.75 || value >= 3) return 'strong'
  if (value <= 0.25) return 'weak'
  return 'medium'
}

export function getProminentNodeLimit(isDense: boolean, isMedium: boolean): number {
  if (isDense) return 8
  if (isMedium) return 14
  return 28
}

export function getLinkBaseOpacity(
  hasFilter: boolean,
  sourceVisible: boolean,
  targetVisible: boolean,
  strength: SnapshotStudioLink['strength']
): number {
  if (hasFilter && (!sourceVisible || !targetVisible)) return 0.08
  if (strength === 'strong') return 0.56
  if (strength === 'medium') return 0.38
  return 0.24
}

export function getLinkDensityOpacity(baseOpacity: number, isDense: boolean, isMedium: boolean): number {
  if (isDense) return baseOpacity * 0.52
  if (isMedium) return baseOpacity * 0.72
  return baseOpacity
}

export function getLinkStrokeWidth(isDense: boolean, strength: SnapshotStudioLink['strength']): number {
  if (isDense) return 0.16
  if (strength === 'strong') return 0.36
  return 0.24
}

export function getGraphNodeSizeClass(isDense: boolean, isMedium: boolean): string {
  if (isDense) return 'h-7 w-7'
  if (isMedium) return 'h-10 w-10'
  return 'h-14 w-14'
}

export function graphLoadingTitle(isLoading: boolean): string {
  return isLoading ? '正在读取真实 KG 图谱' : '暂无图谱节点'
}

export function graphLoadingDescription(isLoading: boolean, emptyMessage?: string): string {
  if (isLoading) return '系统会按当前数据集、文档范围和 pipeline hash 请求后端接口。'
  return emptyMessage || '当前作用域没有返回 KG 节点，请先完成文档入库或 KG 抽取。'
}

export function buildSnapshotStudioGraphFromKgGraph(graph: KGGraphResponse | null): {
  nodes: SnapshotStudioNode[]
  links: SnapshotStudioLink[]
} {
  const rawNodes = Array.isArray(graph?.nodes) ? graph.nodes : []
  const rawLinks = Array.isArray(graph?.links) ? graph.links : []
  const total = Math.max(rawNodes.length, 1)
  const radiusX = 31
  const radiusY = 25

  const nodes: SnapshotStudioNode[] = rawNodes.map(
    (node, index): SnapshotStudioNode => {
      const type = getNodeType(node)
      const angle = (index / total) * Math.PI * 2 - Math.PI / 2
      const id = String(node.id || node.label || `node-${index}`)
      const occurrences = Number(
        getNodeMetaValue(
          node,
          'occurrences',
          'count',
          'event_count',
          'degree',
          'val'
        ) ??
          node.val ??
          0
      )
      return {
        id,
        label: String(node.label || id),
        type,
        kind: firstDisplayString(getNodeMetaValue(node, 'kind', 'node_type', 'source')) || type,
        description:
          firstDisplayString(getNodeMetaValue(node, 'description', 'summary', 'content')) ||
          '来自 KG 图谱接口的真实节点。',
        x: Math.round((50 + Math.cos(angle) * radiusX) * 10) / 10,
        y: Math.round((50 + Math.sin(angle) * radiusY) * 10) / 10,
        tone: toneForNodeType(type),
        icon: iconForNodeType(type),
        occurrences: Number.isFinite(occurrences)
          ? Math.max(0, occurrences)
          : 0,
        status: '一致' as const,
        relations: [],
      }
    }
  )

  const nodeById = new Map(nodes.map((node) => [node.id, node]))
  const links = rawLinks
    .map((link) => {
      const source = getLinkEndpointId(link.source)
      const target = getLinkEndpointId(link.target)
      if (!source || !target || !nodeById.has(source) || !nodeById.has(target))
        return null
      const label = toTrimmedPrimitiveString(getLinkValue(link, 'label', 'predicate', 'relation', 'type'), '关联')
      return {
        source,
        target,
        label,
        strength: strengthForWeight(
          getLinkValue(link, 'weight', 'confidence', 'score')
        ),
      } satisfies SnapshotStudioLink
    })
    .filter((link): link is SnapshotStudioLink => Boolean(link))

  for (const link of links) {
    const source = nodeById.get(link.source)
    const target = nodeById.get(link.target)
    if (source && target)
      source.relations.push({ label: link.label, target: target.label, targetId: target.id })
    if (target && source)
      target.relations.push({ label: link.label, target: source.label, targetId: source.id })
  }

  for (const node of nodes) {
    node.relations = node.relations.slice(0, 8)
  }

  return { nodes, links }
}

export function clampPercent(value: number, min = 7, max = 93): number {
  return Math.min(max, Math.max(min, Math.round(value * 10) / 10))
}

export function layoutSnapshotStudioNodes(
  nodes: SnapshotStudioNode[],
  layout: string
): SnapshotStudioNode[] {
  const total = nodes.length
  if (total === 0 || layout === 'radial') return nodes

  if (layout === 'layered') {
    const groups = new Map<string, SnapshotStudioNode[]>()
    for (const node of nodes) {
      const group = groups.get(node.type) ?? []
      group.push(node)
      groups.set(node.type, group)
    }

    const orderedGroups = Array.from(groups.values()).sort(
      (a, b) => b.length - a.length
    )
    const columnCount = Math.max(1, orderedGroups.length)
    const xStep = columnCount > 1 ? 76 / (columnCount - 1) : 0

    return orderedGroups.flatMap((group, columnIndex) => {
      const x = columnCount > 1 ? 12 + columnIndex * xStep : 50
      const yStep = 70 / Math.max(group.length, 1)
      return group.map((node, rowIndex) => ({
        ...node,
        x: clampPercent(x),
        y: clampPercent(15 + rowIndex * yStep + yStep / 2),
      }))
    })
  }

  const goldenAngle = Math.PI * (3 - Math.sqrt(5))
  const radiusX = total > 120 ? 40 : 36
  const radiusY = total > 120 ? 32 : 29

  return nodes.map((node, index) => {
    const radius = Math.sqrt((index + 0.5) / total)
    const angle = index * goldenAngle
    return {
      ...node,
      x: clampPercent(50 + Math.cos(angle) * radius * radiusX),
      y: clampPercent(50 + Math.sin(angle) * radius * radiusY),
    }
  })
}

export function snapshotToneClassName(
  tone: SnapshotStudioNode['tone'],
  selected: boolean
) {
  const base = SNAPSHOT_NODE_TONE_CLASSES[tone]
  return cn(
    base,
    selected ? 'ring-4 ring-offset-4 ring-offset-background' : 'ring-1'
  )
}
