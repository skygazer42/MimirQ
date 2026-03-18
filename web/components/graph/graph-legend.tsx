'use client'

import { useState, useMemo } from 'react'
import { ChevronDown, ChevronUp } from 'lucide-react'
import { cn } from '@/lib/utils'

const NODE_COLOR_PALETTE = [
  '#ec4899', '#10b981', '#f59e0b', '#8b5cf6', '#3b82f6',
  '#06b6d4', '#84cc16', '#f97316', '#ef4444', '#14b8a6',
  '#22c55e', '#eab308', '#0ea5e9', '#a855f7', '#fb7185',
  '#4ade80', '#2dd4bf', '#38bdf8', '#f472b6', '#c084fc',
  '#facc15', '#a3e635', '#67e8f9', '#f43f5e',
]

const EVENT_COLOR = '#6366f1'

interface EntityTypeEntry {
  type: string
  color: string
  count: number
}

interface GraphLegendProps {
  readonly nodes: readonly any[]
  readonly activeTypeFilters?: readonly string[]
  readonly onToggleTypeFilter?: (type: string) => void
}

export function GraphLegend({ nodes, activeTypeFilters = [], onToggleTypeFilter }: GraphLegendProps) {
  const [collapsed, setCollapsed] = useState(false)

  const entityTypes = useMemo<EntityTypeEntry[]>(() => {
    const typeMap = new Map<string, { count: number; group: number }>()
    let hasEvents = false

    for (const node of nodes) {
      const kind = String(node?.meta?.kind ?? '').trim()
      if (kind === 'event') {
        hasEvents = true
        continue
      }

      const type = String(node?.meta?.type ?? node?.type ?? '').trim() || 'unknown'
      const existing = typeMap.get(type)
      if (existing) {
        existing.count++
      } else {
        const rawGroup = typeof node.group === 'number' ? node.group : 0
        typeMap.set(type, { count: 1, group: rawGroup })
      }
    }

    const entries: EntityTypeEntry[] = []

    if (hasEvents) {
      const eventCount = nodes.filter(n => String(n?.meta?.kind ?? '').trim() === 'event').length
      entries.push({ type: 'Event', color: EVENT_COLOR, count: eventCount })
    }

    const groupColorMap = new Map<number, string>()
    let nextColorIdx = 0

    for (const [type, { count, group }] of typeMap.entries()) {
      let color: string
      if (group > 0) {
        const idx = (group - 1) % NODE_COLOR_PALETTE.length
        color = NODE_COLOR_PALETTE[idx]
      } else {
        if (!groupColorMap.has(0)) {
          groupColorMap.set(0, NODE_COLOR_PALETTE[nextColorIdx++ % NODE_COLOR_PALETTE.length])
        }
        color = groupColorMap.get(0)!
      }
      entries.push({ type, color, count })
    }

    return entries.sort((a, b) => b.count - a.count)
  }, [nodes])

  if (entityTypes.length === 0) return null

  return (
    <div className="absolute bottom-8 left-8 z-10">
      <div className="bg-card/95 backdrop-blur-sm rounded-xl border border-border/60 shadow-md overflow-hidden max-w-[340px]">
        <button
          type="button"
          onClick={() => setCollapsed(prev => !prev)}
          className="w-full flex items-center justify-between px-3.5 py-2.5 text-[11px] font-semibold uppercase text-muted-foreground hover:text-foreground transition-colors"
        >
          <span>Entity Types</span>
          <span className="flex items-center gap-1.5">
            <span className="text-[10px] font-normal normal-case opacity-70">
              {entityTypes.length}
            </span>
            {collapsed ? <ChevronUp className="w-3.5 h-3.5" /> : <ChevronDown className="w-3.5 h-3.5" />}
          </span>
        </button>
        {!collapsed && (
          <div className="px-3.5 pb-3 pt-0.5 flex flex-wrap gap-x-4 gap-y-2 max-h-[160px] overflow-y-auto overscroll-contain no-scrollbar">
            {entityTypes.map(({ type, color, count }) => {
              const isActive = activeTypeFilters.length === 0 || activeTypeFilters.includes(type)
              return (
                <button
                  key={type}
                  type="button"
                  onClick={() => onToggleTypeFilter?.(type)}
                  className={cn(
                    "flex items-center gap-1.5 text-xs transition-opacity",
                    isActive ? "opacity-100" : "opacity-40"
                  )}
                  title={`${type} (${count})`}
                >
                  <span
                    className="w-2.5 h-2.5 rounded-full flex-shrink-0 ring-1 ring-black/5"
                    style={{ backgroundColor: color }}
                  />
                  <span className="text-foreground/80 whitespace-nowrap">{type}</span>
                  <span className="text-muted-foreground text-[10px]">{count}</span>
                </button>
              )
            })}
          </div>
        )}
      </div>
    </div>
  )
}
