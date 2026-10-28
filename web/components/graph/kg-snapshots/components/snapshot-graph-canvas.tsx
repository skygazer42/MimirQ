'use client'

import { Network, RefreshCcw } from '@/components/icons'
import { useLayoutEffect, useMemo, useRef, useState } from 'react'

import { cn } from '@/lib/utils'

import {
  getGraphNodeSizeClass,
  getLinkBaseOpacity,
  getLinkDensityOpacity,
  getLinkStrokeWidth,
  getProminentNodeLimit,
  graphLoadingDescription,
  graphLoadingTitle,
  layoutSnapshotCanvas,
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
  onSelectNode: (nodeId: string, trigger: HTMLButtonElement) => void
}>) {
  const normalizedSearch = searchValue.trim().toLowerCase()
  const canvasLayout = useMemo(
    () => layoutSnapshotCanvas(nodes, layout),
    [layout, nodes]
  )
  const canvasRef = useRef<HTMLDivElement>(null)
  const [viewport, setViewport] = useState({ width: canvasLayout.width, height: canvasLayout.height })
  useLayoutEffect(() => {
    const element = canvasRef.current!
    const update = () => setViewport({ width: element.clientWidth, height: element.clientHeight })
    const observer = new ResizeObserver(update)
    observer.observe(element)
    update()
    return () => observer.disconnect()
  }, [])
  const displayNodes = canvasLayout.nodes
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
  const linkViews = useMemo(() => filteredLinks.flatMap(link => {
    const source = nodeById.get(link.source), target = nodeById.get(link.target)
    if (!source || !target) return []
    const sourceVisible = filteredNodeIds.has(source.id), targetVisible = filteredNodeIds.has(target.id)
    const opacity = getLinkDensityOpacity(getLinkBaseOpacity(hasFilter, sourceVisible, targetVisible, link.strength), isDenseGraph, mediumGraph)
    const dx = (target.x - source.x) * viewport.width / 100
    const dy = (target.y - source.y) * viewport.height / 100
    const distance = Math.hypot(dx, dy)
    const radius = (isDenseGraph ? 28 : mediumGraph ? 40 : 56) / 2 + 6
    const endX = distance ? target.x - dx / distance * radius / viewport.width * 100 : target.x + radius / viewport.width * 100
    const endY = distance ? target.y - dy / distance * radius / viewport.height * 100 : target.y
    return [{ link, source, target, endX, endY, opacity, midX: (source.x + target.x) / 2, midY: (source.y + target.y) / 2, showLabel: !isDenseGraph || hasFilter || link.strength === 'strong', labelOpacity: hasFilter && (!sourceVisible || !targetVisible) ? 0.25 : 1 }]
  }), [filteredLinks, nodeById, filteredNodeIds, hasFilter, isDenseGraph, mediumGraph, viewport])
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
      ref={canvasRef}
      data-testid="kg-snapshot-graph-canvas"
      className="relative h-full min-h-0 flex-1 overflow-hidden bg-background"
      style={{ minWidth: canvasLayout.width, minHeight: canvasLayout.height }}
    >
      <div
        className="absolute inset-0 opacity-[0.42] [background-image:radial-gradient(circle,hsl(var(--muted-foreground)/0.26)_1px,transparent_1px)] [background-size:14px_14px]"
        aria-hidden
      />

      {!isLoading ? <div className="absolute left-4 top-4 z-20 bg-background/90 px-3 py-2">
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
      </div> : null}

      {isLoading || isEmpty ? (
        <div className="absolute inset-0 z-10 flex items-center justify-center px-8">
          <div className="flex max-w-[460px] flex-col items-center text-center">
            <div className="relative">
              <div className="relative flex size-8 items-center justify-center text-primary">
                {isLoading ? (
                  <RefreshCcw
                    className="h-7 w-7 animate-spin"
                    aria-hidden="true"
                  />
                ) : (
                  <Network appearance="color" className="size-7" aria-hidden="true" />
                )}
              </div>
            </div>
            <div className="mt-4 text-[15px] font-semibold text-foreground">
              {graphLoadingTitle(isLoading)}
            </div>
            <div className="mt-1.5 text-[13px] leading-6 text-muted-foreground">
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
              fill="hsl(var(--muted-foreground))"
              opacity="0.72"
            />
          </marker>
        </defs>
        {linkViews.map(({ link, source, endX, endY, opacity, midX, midY }) => <path
        key={`${link.source}:${link.target}:${link.label}`}
        d={`M ${source.x} ${source.y} C ${midX} ${midY + (source.x < endX ? -6 : 6)}, ${midX} ${midY - (source.x < endX ? -6 : 6)}, ${endX} ${endY}`}
        fill="none" stroke="hsl(var(--muted-foreground))" strokeWidth={getLinkStrokeWidth(isDenseGraph, link.strength)}
        strokeDasharray={link.strength === 'weak' ? '1.1 1.1' : undefined} opacity={opacity} markerEnd="url(#snapshot-arrow)"
      />)}
      </svg>

      {linkViews.filter(view => view.showLabel).map(({ link, midX, midY, labelOpacity }) => <span
        key={`label:${link.source}:${link.target}:${link.label}`}
        className="pointer-events-none absolute z-[1] max-w-44 -translate-x-1/2 -translate-y-1/2 truncate bg-background/95 px-1.5 py-0.5 text-[13px] text-foreground"
        style={{ left: `${midX}%`, top: `${midY}%`, opacity: labelOpacity }} title={link.label}
      >{link.label}</span>)}
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
              'absolute z-10 flex -translate-x-1/2 -translate-y-1/2 flex-col items-center text-center transition-all duration-200 motion-reduce:transition-none',
              isDenseGraph ? 'gap-1' : 'gap-1.5',
              muted ? 'scale-95 opacity-25' : 'opacity-100 hover:scale-105'
            )}
            style={{ left: `${node.x}%`, top: `${node.y}%` }}
            onClick={event => onSelectNode(node.id, event.currentTarget)}
            aria-label={`选择节点 ${node.label}`}
          >
            <span
              className={cn(
                'flex items-center justify-center rounded-full',
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
                  'text-[13px]'
                )}
              >
                <span className="block truncate">{node.label}</span>
              </span>
            ) : null}
          </button>
        )
      })}

      <div className="absolute bottom-4 left-4 z-20 flex max-w-[calc(100%-2rem)] flex-wrap items-center gap-3 bg-background/90 px-3 py-2 text-xs text-muted-foreground">
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
