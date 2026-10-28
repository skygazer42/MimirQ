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

const HEATMAP_CELL_TEXT_SIZE = 13

function cellLabelTone(value: number, min: number, max: number, colors: string[]) {
  const position = Math.max(0, Math.min(1, (value - min) / (max - min))) * (colors.length - 1)
  const index = Math.min(Math.floor(position), colors.length - 2)
  const fraction = position - index
  const channels = [1, 3, 5].map(offset => {
    const from = Number.parseInt(colors[index].slice(offset, offset + 2), 16)
    const to = Number.parseInt(colors[index + 1].slice(offset, offset + 2), 16)
    const channel = (from + (to - from) * fraction) / 255
    return channel <= 0.04045 ? channel / 12.92 : ((channel + 0.055) / 1.055) ** 2.4
  })
  const luminance = channels[0] * 0.2126 + channels[1] * 0.7152 + channels[2] * 0.0722
  return luminance > 0.179 ? 'ink' : 'paper'
}

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
        axisLabel: { rotate: 28, color: 'hsl(var(--foreground))', fontSize: 13 },
      },
      yAxis: {
        type: 'category',
        data: yLabels,
        // Matches plotly `autorange: 'reversed'` (first row rendered at top).
        inverse: true,
        axisLabel: { color: 'hsl(var(--foreground))', fontSize: 13 },
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
            show: xLabels.length <= 20 && yLabels.length <= 20,
            fontSize: HEATMAP_CELL_TEXT_SIZE,
            rich: { ink: { color: '#000000', fontSize: HEATMAP_CELL_TEXT_SIZE }, paper: { color: '#ffffff', fontSize: HEATMAP_CELL_TEXT_SIZE } },
            formatter: (params: unknown) => {
              const record = params as { value?: unknown }
              const tuple = Array.isArray(record.value) ? record.value : null
              const value = tuple?.[2]
              return typeof value === 'number' ? `{${cellLabelTone(value, min, max, colors)}|${formatHeatmapValue(value)}}` : '—'
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
