'use client'

import { useMemo } from 'react'
import { Waypoints, GitCommitHorizontal, Shapes } from 'lucide-react'

interface GraphStatsBarProps {
  readonly nodeCount: number
  readonly linkCount: number
  readonly entityTypeCount: number
}

export function GraphStatsBar({ nodeCount, linkCount, entityTypeCount }: GraphStatsBarProps) {
  const items = useMemo(() => [
    { icon: Waypoints, label: 'Nodes', value: nodeCount },
    { icon: GitCommitHorizontal, label: 'Edges', value: linkCount },
    { icon: Shapes, label: 'Types', value: entityTypeCount },
  ], [nodeCount, linkCount, entityTypeCount])

  if (nodeCount === 0 && linkCount === 0) return null

  return (
    <div className="flex items-center gap-3 bg-card/80 backdrop-blur-sm rounded-full px-3.5 py-1.5 border border-border/50 shadow-sm">
      {items.map(({ icon: Icon, label, value }) => (
        <div key={label} className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
          <Icon className="w-3 h-3 opacity-60" />
          <span className="font-medium tabular-nums">{value.toLocaleString()}</span>
        </div>
      ))}
    </div>
  )
}
