'use client'

import { Network, RefreshCcw } from 'lucide-react'
import { useMemo } from 'react'

import { cn } from '@/lib/utils'

import {
  getGraphNodeSizeClass,
  getLinkBaseOpacity,
  getLinkDensityOpacity,
  getLinkStrokeWidth,
  getProminentNodeLimit,
  graphLoadingDescription,
  graphLoadingTitle,
  layoutSnapshotStudioNodes,
  snapshotToneClassName,
} from '../snapshot-graph'
import type { SnapshotStudioLink, SnapshotStudioNode } from '../types'

export function SnapshotGraphCanvas({
  nodes,
  links,
  layout,
  selectedNodeId,
  searchValue,
  nodeType,
  relationType,
  nodeCount,
  relationCount,
  isLoading,
  emptyMessage,
  onSelectNode,
}: Readonly<{
  nodes: SnapshotStudioNode[]
  links: SnapshotStudioLink[]
  layout: string
  selectedNodeId: string
  searchValue: string
  nodeType: string
  relationType: string
  nodeCount: number
  relationCount: number
  isLoading: boolean
  emptyMessage?: string
  onSelectNode: (nodeId: string) => void
}>) {
  const normalizedSearch = searchValue.trim().toLowerCase()
  const displayNodes = useMemo(
    () => layoutSnapshotStudioNodes(nodes, layout),
    [layout, nodes]
  )
  const nodeById = useMemo(
    () => new Map(displayNodes.map((node) => [node.id, node])),
    [displayNodes]
  )
  const filteredNodeIds = useMemo(() => {
    const ids = new Set<string>()
    for (const node of displayNodes) {
      const matchesType = nodeType === 'all' || node.type === nodeType
      const matchesSearch =
        !normalizedSearch ||
        node.label.toLowerCase().includes(normalizedSearch) ||
        node.type.toLowerCase().includes(normalizedSearch) ||
        node.description.toLowerCase().includes(normalizedSearch)
      if (matchesType && matchesSearch) ids.add(node.id)
    }
    return ids
  }, [displayNodes, nodeType, normalizedSearch])
  const filteredLinks = useMemo(() => {
    return links.filter((link) => {
      const matchesRelation =
        relationType === 'all' || link.label === relationType
      const matchesSearch =
        !normalizedSearch || link.label.toLowerCase().includes(normalizedSearch)
      return matchesRelation && matchesSearch
    })
  }, [links, normalizedSearch, relationType])
  const hasFilter =
    Boolean(normalizedSearch) || nodeType !== 'all' || relationType !== 'all'
  const isEmpty = nodes.length === 0
  const isDenseGraph = nodes.length > 64 || filteredLinks.length > 96
  const mediumGraph = nodes.length > 36 || filteredLinks.length > 56
  const prominentNodeIds = useMemo(() => {
    const sorted = [...displayNodes].sort((a, b) => {
      const bScore = b.relations.length * 2 + b.occurrences
      const aScore = a.relations.length * 2 + a.occurrences
      return bScore - aScore
    })
    return new Set(
      sorted
        .slice(0, getProminentNodeLimit(isDenseGraph, mediumGraph))
        .map((node) => node.id)
    )
  }, [displayNodes, isDenseGraph, mediumGraph])
  const legendRows = useMemo(() => {
    const colorByTone: Record<SnapshotStudioNode['tone'], string> = {
      blue: 'bg-primary',
      green: 'bg-success',
      orange: 'bg-warning',
      purple: 'bg-accent',
      rose: 'bg-destructive',
      amber: 'bg-warning',
      teal: 'bg-success',
    }
    const seen = new Map<string, string>()
    for (const node of displayNodes) {
      if (!seen.has(node.type)) seen.set(node.type, colorByTone[node.tone])
    }
    return Array.from(seen.entries()).slice(0, 8)
  }, [displayNodes])

  return (
    <div
      data-testid="kg-snapshot-graph-canvas"
      className="relative min-h-0 flex-1 overflow-hidden bg-[radial-gradient(circle_at_center,hsl(var(--primary)/0.05),transparent_44%),radial-gradient(circle_at_70%_20%,hsl(var(--info)/0.04),transparent_28%)]"
    >
      <div
        className="absolute inset-0 opacity-[0.42] [background-image:radial-gradient(circle,hsl(var(--muted-foreground)/0.26)_1px,transparent_1px)] [background-size:14px_14px]"
        aria-hidden
      />

      <div className="absolute left-7 top-7 z-20 rounded-2xl border border-border/70 bg-card/90 p-3 shadow-lg backdrop-blur">
        <div className="grid grid-cols-[auto_auto] gap-x-4 gap-y-1 text-[12px]">
          <span className="text-muted-foreground">节点</span>
          <span className="font-mono font-semibold tabular-nums text-foreground">
            {nodeCount}
          </span>
          <span className="text-muted-foreground">关系</span>
          <span className="font-mono font-semibold tabular-nums text-foreground">
            {relationCount}
          </span>
        </div>
      </div>

      {isLoading || isEmpty ? (
        <div className="absolute inset-0 z-10 flex items-center justify-center px-8">
          <div className="flex max-w-[460px] flex-col items-center text-center">
            <div className="relative">
              <div
                className="absolute inset-0 rounded-full bg-primary/10 blur-2xl"
                aria-hidden
              />
              <div className="relative flex h-16 w-16 items-center justify-center rounded-2xl border border-border/70 bg-card text-primary shadow-sm">
                {isLoading ? (
                  <RefreshCcw
                    className="h-7 w-7 animate-spin"
                    aria-hidden="true"
                  />
                ) : (
                  <Network className="h-7 w-7" aria-hidden="true" />
                )}
              </div>
            </div>
            <div className="mt-4 text-[15px] font-semibold text-foreground">
              {graphLoadingTitle(isLoading)}
            </div>
            <div className="mt-1.5 text-[12px] leading-5 text-muted-foreground">
              {graphLoadingDescription(isLoading, emptyMessage)}
            </div>
          </div>
        </div>
      ) : null}

      <svg
        className="absolute inset-0 h-full w-full"
        viewBox="0 0 100 100"
        preserveAspectRatio="none"
        aria-hidden="true"
      >
        <defs>
          <marker
            id="snapshot-arrow"
            viewBox="0 0 10 10"
            refX="7.5"
            refY="5"
            markerWidth="4"
            markerHeight="4"
            orient="auto-start-reverse"
          >
            <path
              d="M 0 0 L 10 5 L 0 10 z"
              fill="rgb(148 163 184)"
              opacity="0.72"
            />
          </marker>
        </defs>
        {filteredLinks.map((link) => {
          const source = nodeById.get(link.source)
          const target = nodeById.get(link.target)
          if (!source || !target) return null
          const sourceVisible = filteredNodeIds.has(source.id)
          const targetVisible = filteredNodeIds.has(target.id)
          const baseOpacity = getLinkBaseOpacity(
            hasFilter,
            sourceVisible,
            targetVisible,
            link.strength
          )
          const opacity = getLinkDensityOpacity(baseOpacity, isDenseGraph, mediumGraph)
          const midX = (source.x + target.x) / 2
          const midY = (source.y + target.y) / 2
          const curve = source.x < target.x ? -6 : 6
          const showLinkLabel =
            !isDenseGraph || hasFilter || link.strength === 'strong'
          return (
            <g key={`${link.source}:${link.target}:${link.label}`}>
              <path
                d={`M ${source.x} ${source.y} C ${midX} ${midY + curve}, ${midX} ${midY - curve}, ${target.x} ${target.y}`}
                fill="none"
                stroke="rgb(148 163 184)"
                strokeWidth={getLinkStrokeWidth(isDenseGraph, link.strength)}
                strokeDasharray={
                  link.strength === 'weak' ? '1.1 1.1' : undefined
                }
                opacity={opacity}
                markerEnd="url(#snapshot-arrow)"
              />
              {showLinkLabel ? (
                <text
                  x={midX}
                  y={midY - 1.2}
                  textAnchor="middle"
                  className="fill-muted-foreground text-[1.55px] font-normal tracking-[0.03em]"
                  opacity={Math.max(opacity * 0.9, 0.16)}
                >
                  {link.label}
                </text>
              ) : null}
            </g>
          )
        })}
      </svg>

      {displayNodes.map((node) => {
        const selected = selectedNodeId === node.id
        const matches = filteredNodeIds.has(node.id)
        const muted = hasFilter && !matches
        const showNodeLabel =
          selected ||
          (!mediumGraph && matches) ||
          (isDenseGraph
            ? prominentNodeIds.has(node.id)
            : prominentNodeIds.has(node.id) && !muted) ||
          (hasFilter && matches && normalizedSearch)
        return (
          <button
            key={node.id}
            type="button"
            className={cn(
              'absolute z-10 flex -translate-x-1/2 -translate-y-1/2 flex-col items-center text-center transition-all duration-200',
              isDenseGraph ? 'gap-1' : 'gap-1.5',
              muted ? 'scale-95 opacity-25' : 'opacity-100 hover:scale-105'
            )}
            style={{ left: `${node.x}%`, top: `${node.y}%` }}
            onClick={() => onSelectNode(node.id)}
            aria-label={`选择节点 ${node.label}`}
          >
            <span
              className={cn(
                'flex items-center justify-center rounded-full text-info-foreground shadow-strong shadow-foreground/10',
                getGraphNodeSizeClass(isDenseGraph, mediumGraph),
                snapshotToneClassName(node.tone, selected)
              )}
            >
              {node.icon}
            </span>
            {showNodeLabel ? (
              <span
                className={cn(
                  'max-w-[132px] rounded-full bg-background/82 px-2 py-0.5 font-semibold text-foreground shadow-sm backdrop-blur',
                  isDenseGraph ? 'text-[10px]' : 'text-[12px]'
                )}
              >
                <span className="block truncate">{node.label}</span>
              </span>
            ) : null}
          </button>
        )
      })}

      <div className="absolute bottom-5 left-7 z-20 flex max-w-[calc(100%-3.5rem)] flex-wrap items-center gap-3 rounded-2xl border border-border/70 bg-card/92 px-4 py-2.5 text-[12px] text-muted-foreground shadow-lg backdrop-blur">
        <span className="font-medium text-foreground">图例:</span>
        {legendRows.length ? (
          legendRows.map(([label, color]) => (
            <span key={label} className="inline-flex items-center gap-1.5">
              <span className={cn('h-2 w-2 rounded-full', color)} aria-hidden />
              {label}
            </span>
          ))
        ) : (
          <span>暂无类型</span>
        )}
        <span className="inline-flex items-center gap-2">
          <span>关系强度:</span>
          <span className="h-px w-10 bg-border" aria-hidden />
          <span>弱</span>
          <span className="h-0.5 w-14 bg-muted-foreground" aria-hidden />
          <span>强</span>
        </span>
      </div>
    </div>
  )
}
