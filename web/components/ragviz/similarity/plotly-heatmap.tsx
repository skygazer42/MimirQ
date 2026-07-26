'use client'

import { useEffect, useRef, useState } from 'react'
import { PageLoading } from '@/components/ui/page-loading'
import {
  DIFFERENCE_COLORSCALE,
  toPlotlyColorScale,
  type ColorSchemeKey,
} from './color-schemes'
import {
  pickPlotlyModule,
  resolveHeatmapPoint,
  type PlotlyConfig,
  type PlotlyEventTarget,
  type PlotlyLayout,
  type PlotlyLike,
  type PlotlyTrace,
  type SelectedHeatmapCell,
} from './plotly-types'
import { formatHeatmapValue } from './similarity-matrix-math'

export function PlotlyHeatmap({
  matrix,
  xLabels,
  yLabels,
  colorScheme,
  isDifference,
  onCellSelect,
}: Readonly<{
  matrix: Array<Array<number | null>>
  xLabels: string[]
  yLabels: string[]
  colorScheme: ColorSchemeKey
  isDifference: boolean
  onCellSelect?: (cell: SelectedHeatmapCell) => void
}>) {
  const containerRef = useRef<HTMLDivElement>(null)
  const [plotly, setPlotly] = useState<PlotlyLike | null>(null)
  const [plotlyLoadState, setPlotlyLoadState] = useState<
    'loading' | 'ready' | 'error'
  >('loading')

  useEffect(() => {
    let cancelled = false
    ;(async () => {
      try {
        const modUnknown: unknown = await import('plotly.js-dist-min')
        const plotlyModule = pickPlotlyModule(modUnknown)
        if (!cancelled) {
          setPlotly(plotlyModule)
          setPlotlyLoadState(plotlyModule ? 'ready' : 'error')
        }
      } catch {
        if (!cancelled) {
          setPlotly(null)
          setPlotlyLoadState('error')
        }
      }
    })()
    return () => {
      cancelled = true
    }
  }, [])

  useEffect(() => {
    if (!plotly || !containerRef.current) return

    const zmin = isDifference ? -1 : 0
    const zmax = 1
    const colorscale = isDifference
      ? DIFFERENCE_COLORSCALE
      : toPlotlyColorScale(colorScheme)

    const trace: PlotlyTrace = {
      type: 'heatmap',
      z: matrix,
      x: xLabels,
      y: yLabels,
      colorscale,
      zmin,
      zmax,
      text: matrix.map((row) => row.map((value) => formatHeatmapValue(value))),
      texttemplate: '%{text}',
      textfont: { color: '#0f172a', size: 11 },
      showscale: false,
      hovertemplate: '<b>%{z:.3f}</b><br>X: %{x}<br>Y: %{y}<extra></extra>',
    }

    const layout: PlotlyLayout = {
      margin: { l: 108, r: 20, t: 36, b: 96 },
      xaxis: { automargin: true, tickangle: -28 },
      yaxis: { automargin: true, autorange: 'reversed' },
      paper_bgcolor: 'transparent',
      plot_bgcolor: 'transparent',
    }

    const config: PlotlyConfig = {
      responsive: true,
      displaylogo: false,
      displayModeBar: false,
    }

    plotly.react(containerRef.current, [trace], layout, config)

    const plotTarget = containerRef.current as PlotlyEventTarget
    plotTarget.removeAllListeners?.('plotly_click')
    plotTarget.on?.('plotly_click', (event) => {
      const cell = resolveHeatmapPoint(event)
      if (cell) onCellSelect?.(cell)
    })
  }, [
    colorScheme,
    isDifference,
    matrix,
    onCellSelect,
    plotly,
    xLabels,
    yLabels,
  ])

  useEffect(() => {
    if (!plotly || !containerRef.current) return
    const el = containerRef.current
    return () => {
      try {
        plotly.purge(el)
      } catch {
        // ignore
      }
    }
  }, [plotly])

  if (plotlyLoadState === 'loading') {
    return (
      <div className="flex h-full min-h-[320px] flex-col items-center justify-center rounded-xl border border-border/60 bg-background/70 px-6">
        <PageLoading
          message="正在加载相似度热力图..."
          srMessage="Loading similarity heatmap"
          className="min-h-0 flex-none"
        />
        <p className="mt-2 text-xs text-muted-foreground">
          正在初始化图表引擎...
        </p>
      </div>
    )
  }

  if (!plotly) {
    return (
      <div className="flex h-full min-h-[320px] items-center justify-center rounded-xl border border-dashed border-border/60 bg-background/70 px-6 text-center text-sm text-muted-foreground">
        图表引擎加载失败，请稍后重试
      </div>
    )
  }

  return <div ref={containerRef} className="h-full w-full" />
}
