'use client'

import { useEffect, useRef, useState, useCallback, useMemo } from 'react'
import { Loader2, RotateCcw, ZoomIn, ZoomOut } from 'lucide-react'
import { Button } from '@/components/ui/button'
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from '@/components/ui/select'
import { cn } from '@/lib/utils'

interface VectorPoint {
  id: string
  x: number
  y: number
  z?: number
  label: string
  cluster?: string | number
  document_id?: string
  chunk_text?: string
  score?: number
}

interface VectorSpaceExplorerProps {
  readonly points: VectorPoint[]
  readonly onPointClick?: (point: VectorPoint) => void
  readonly colorBy?: 'cluster' | 'document' | 'score'
  readonly className?: string
  readonly is3D?: boolean
}

const CLUSTER_COLORS = [
  '#8b5cf6', '#3b82f6', '#10b981', '#f59e0b',
  '#ef4444', '#ec4899', '#06b6d4', '#84cc16',
  '#f97316', '#14b8a6', '#a855f7', '#0ea5e9',
]

export function VectorSpaceExplorer({
  points,
  onPointClick,
  colorBy = 'cluster',
  className,
  is3D = false,
}: VectorSpaceExplorerProps) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [plotly, setPlotly] = useState<any>(null)
  const [loading, setLoading] = useState(true)
  const [hoveredPoint, setHoveredPoint] = useState<VectorPoint | null>(null)

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const mod: any = await import('plotly.js-dist-min')
        const Plotly = mod?.default || mod
        if (!cancelled) {
          setPlotly(() => Plotly)
          setLoading(false)
        }
      } catch {
        if (!cancelled) setLoading(false)
      }
    })()
    return () => { cancelled = true }
  }, [])

  const getPointColor = useCallback((point: VectorPoint): string => {
    if (colorBy === 'score' && point.score != null) {
      const t = Math.max(0, Math.min(1, point.score))
      const r = Math.round(139 * (1 - t) + 59 * t)
      const g = Math.round(92 * (1 - t) + 130 * t)
      const b = Math.round(246 * (1 - t) + 246 * t)
      return `rgb(${r},${g},${b})`
    }
    const key = colorBy === 'document' ? point.document_id : String(point.cluster ?? 0)
    const hash = [...(key || '0')].reduce((a, c) => a + c.charCodeAt(0), 0)
    return CLUSTER_COLORS[hash % CLUSTER_COLORS.length]
  }, [colorBy])

  const traceData = useMemo(() => {
    if (!points.length) return null

    const colors = points.map(getPointColor)
    const texts = points.map(p => {
      const preview = (p.chunk_text || '').slice(0, 80)
      return `<b>${p.label}</b><br>${preview}${(p.chunk_text || '').length > 80 ? '...' : ''}`
    })

    if (is3D) {
      return [{
        type: 'scatter3d' as const,
        mode: 'markers' as const,
        x: points.map(p => p.x),
        y: points.map(p => p.y),
        z: points.map(p => p.z ?? 0),
        text: texts,
        hovertemplate: '%{text}<extra></extra>',
        marker: {
          size: 4,
          color: colors,
          opacity: 0.8,
          line: { width: 0.5, color: 'rgba(0,0,0,0.2)' },
        },
      }]
    }

    return [{
      type: 'scatter' as const,
      mode: 'markers' as const,
      x: points.map(p => p.x),
      y: points.map(p => p.y),
      text: texts,
      hovertemplate: '%{text}<extra></extra>',
      marker: {
        size: 6,
        color: colors,
        opacity: 0.8,
        line: { width: 0.5, color: 'rgba(0,0,0,0.15)' },
      },
    }]
  }, [points, is3D, getPointColor])

  useEffect(() => {
    if (!plotly || !containerRef.current || !traceData) return

    const layout: any = {
      paper_bgcolor: 'rgba(0,0,0,0)',
      plot_bgcolor: 'rgba(15, 15, 25, 0.3)',
      margin: { l: 40, r: 20, t: 20, b: 40 },
      font: { color: '#94a3b8', family: 'Inter, system-ui, sans-serif', size: 11 },
      xaxis: {
        showgrid: true,
        gridcolor: 'rgba(100, 116, 139, 0.08)',
        zeroline: false,
        showticklabels: false,
      },
      yaxis: {
        showgrid: true,
        gridcolor: 'rgba(100, 116, 139, 0.08)',
        zeroline: false,
        showticklabels: false,
      },
      hoverlabel: {
        bgcolor: '#1e293b',
        bordercolor: '#334155',
        font: { color: '#e2e8f0', size: 12, family: 'Inter, system-ui, sans-serif' },
      },
    }

    if (is3D) {
      layout.scene = {
        bgcolor: 'rgba(10,10,20,0.5)',
        xaxis: { showgrid: true, gridcolor: 'rgba(100,116,139,0.08)', showticklabels: false, zeroline: false },
        yaxis: { showgrid: true, gridcolor: 'rgba(100,116,139,0.08)', showticklabels: false, zeroline: false },
        zaxis: { showgrid: true, gridcolor: 'rgba(100,116,139,0.08)', showticklabels: false, zeroline: false },
      }
    }

    const config: any = {
      responsive: true,
      displaylogo: false,
      modeBarButtonsToRemove: ['lasso2d', 'select2d'],
    }

    plotly.react(containerRef.current, traceData, layout, config)

    const el = containerRef.current
    el.on?.('plotly_click', (eventData: any) => {
      const idx = eventData?.points?.[0]?.pointIndex
      if (idx != null && points[idx] && onPointClick) {
        onPointClick(points[idx])
      }
    })

    el.on?.('plotly_hover', (eventData: any) => {
      const idx = eventData?.points?.[0]?.pointIndex
      if (idx != null && points[idx]) {
        setHoveredPoint(points[idx])
      }
    })

    el.on?.('plotly_unhover', () => {
      setHoveredPoint(null)
    })
  }, [plotly, traceData, is3D, points, onPointClick])

  useEffect(() => {
    if (!plotly || !containerRef.current) return
    const el = containerRef.current
    return () => {
      try { plotly.purge(el) } catch { /* ignore */ }
    }
  }, [plotly])

  if (loading) {
    return (
      <div className={cn("flex items-center justify-center h-full", className)}>
        <Loader2 className="h-5 w-5 animate-spin text-primary" />
      </div>
    )
  }

  if (!points.length) {
    return (
      <div className={cn("flex items-center justify-center h-full text-muted-foreground text-sm", className)}>
        No embedding data available
      </div>
    )
  }

  return (
    <div className={cn("relative h-full", className)}>
      <div ref={containerRef} className="h-full w-full" />
      
      {hoveredPoint && (
        <div className="absolute top-3 right-3 max-w-xs bg-card border border-border/50 rounded-lg p-3 shadow-strong pointer-events-none animate-fade-in">
          <div className="text-xs font-medium text-foreground truncate">{hoveredPoint.label}</div>
          {hoveredPoint.chunk_text && (
            <div className="mt-1 text-2xs text-muted-foreground line-clamp-3 leading-relaxed">
              {hoveredPoint.chunk_text}
            </div>
          )}
          {hoveredPoint.score != null && (
            <div className="mt-1.5 text-2xs text-primary font-mono">
              Score: {hoveredPoint.score.toFixed(4)}
            </div>
          )}
        </div>
      )}
    </div>
  )
}
