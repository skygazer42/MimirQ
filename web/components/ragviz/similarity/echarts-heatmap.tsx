'use client'

import { useMemo } from 'react'
import type { EChartsOption } from 'echarts'
import { EChart, type EChartEventHandler } from '@/components/ui/echart'
import {
  DIFFERENCE_VISUALMAP_COLORS,
  toEchartsVisualMapColors,
  type ColorSchemeKey,
} from './color-schemes'
import { resolveHeatmapPoint, type SelectedHeatmapCell } from './heatmap-types'
import { formatHeatmapValue } from './similarity-matrix-math'

// Carried over from the previous heatmap implementation (plotly textfont).
const HEATMAP_CELL_TEXT_COLOR = '#0f172a'
const HEATMAP_CELL_TEXT_SIZE = 11

type HeatmapDatum = [number, number, number]

function escapeHtml(value: string) {
  return value
    .replaceAll('&', '&amp;')
    .replaceAll('<', '&lt;')
    .replaceAll('>', '&gt;')
    .replaceAll('"', '&quot;')
    .replaceAll("'", '&#39;')
}

function resolveTooltipContext(params: unknown) {
  const cell = resolveHeatmapPoint(params)
  if (!cell) return null
  const record = params as { value?: unknown }
  const tuple = Array.isArray(record.value) ? record.value : null
  const value = tuple?.[2]
  if (typeof value !== 'number' || !Number.isFinite(value)) return null
  return { cell, value }
}

export function EchartsHeatmap({
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
  const option = useMemo<EChartsOption>(() => {
    const min = isDifference ? -1 : 0
    const max = 1
    const colors = isDifference
      ? DIFFERENCE_VISUALMAP_COLORS
      : toEchartsVisualMapColors(colorScheme)

    // Skip null / non-finite cells so masked entries render as gaps
    // (same as plotly heatmap behavior for null z values).
    const data: HeatmapDatum[] = []
    matrix.forEach((row, rowIndex) => {
      row.forEach((value, colIndex) => {
        if (typeof value === 'number' && Number.isFinite(value)) {
          data.push([colIndex, rowIndex, value])
        }
      })
    })

    return {
      animation: false,
      backgroundColor: 'transparent',
      grid: { left: 12, right: 20, top: 36, bottom: 12, containLabel: true },
      xAxis: {
        type: 'category',
        data: xLabels,
        axisLabel: { rotate: 28 },
      },
      yAxis: {
        type: 'category',
        data: yLabels,
        // Matches plotly `autorange: 'reversed'` (first row rendered at top).
        inverse: true,
      },
      tooltip: {
        confine: true,
        formatter: (params: unknown) => {
          const resolved = resolveTooltipContext(params)
          if (!resolved) return ''
          const xLabel = xLabels[resolved.cell.colIndex] || ''
          const yLabel = yLabels[resolved.cell.rowIndex] || ''
          return [
            `<b>${resolved.value.toFixed(3)}</b>`,
            `X: ${escapeHtml(xLabel)}`,
            `Y: ${escapeHtml(yLabel)}`,
          ].join('<br>')
        },
      },
      visualMap: {
        show: false,
        min,
        max,
        inRange: { color: colors },
        seriesIndex: 0,
      },
      series: [
        {
          type: 'heatmap',
          data,
          label: {
            show: true,
            color: HEATMAP_CELL_TEXT_COLOR,
            fontSize: HEATMAP_CELL_TEXT_SIZE,
            formatter: (params: unknown) => {
              const record = params as { value?: unknown }
              const tuple = Array.isArray(record.value) ? record.value : null
              const value = tuple?.[2]
              return formatHeatmapValue(typeof value === 'number' ? value : null)
            },
          },
          emphasis: {
            itemStyle: {
              shadowBlur: 6,
              shadowColor: 'rgba(0, 0, 0, 0.35)',
            },
          },
        },
      ],
    }
  }, [colorScheme, isDifference, matrix, xLabels, yLabels])

  const onEvents = useMemo<Record<string, EChartEventHandler>>(
    () => ({
      click: (params: unknown) => {
        const cell = resolveHeatmapPoint(params)
        if (cell) onCellSelect?.(cell)
      },
    }),
    [onCellSelect]
  )

  return (
    <div className="h-full min-h-[320px] w-full">
      <EChart option={option} onEvents={onEvents} />
    </div>
  )
}
