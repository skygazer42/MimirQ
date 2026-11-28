'use client'

import { useMemo, useState } from 'react'
import type { EChartsOption } from 'echarts'
import { Button } from '@/components/ui/button'
import { EChart, type EChartEventHandler } from '@/components/ui/echart'
import { DIFFERENCE_VISUALMAP_COLORS, toEchartsVisualMapColors, type ColorSchemeKey } from './color-schemes'
import { similarityFieldClass } from './form-controls'
import { resolveHeatmapPoint, type SelectedHeatmapCell } from './heatmap-types'
import { formatHeatmapValue } from './similarity-matrix-math'
import { isRecord } from './utils'

const HEATMAP_CELL_TEXT_SIZE = 13

function cellLabelTone(value: number, min: number, max: number, colors: string[]) {
  const position = Math.max(0, Math.min(1, (value - min) / (max - min))) * (colors.length - 1)
  const index = Math.min(Math.floor(position), colors.length - 2)
  const fraction = position - index
  const channels = [1, 3, 5].map((offset) => {
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
  if (!isRecord(params) || !Array.isArray(params.value)) return null

  const cell = resolveHeatmapPoint(params)
  if (cell === null) return null
  const value = params.value[2]
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
  const [cellSelection, setCellSelection] = useState<SelectedHeatmapCell>({ rowIndex: 0, colIndex: 0 })
  const rowIndex = Math.min(cellSelection.rowIndex, yLabels.length - 1)
  const colIndex = Math.min(cellSelection.colIndex, xLabels.length - 1)
  const cellValue = matrix[rowIndex]?.[colIndex]
  const canInspectCell = typeof cellValue === 'number' && Number.isFinite(cellValue)

  const option = useMemo<EChartsOption>(() => {
    const min = isDifference ? -1 : 0
    const max = 1
    const colors = isDifference ? DIFFERENCE_VISUALMAP_COLORS : toEchartsVisualMapColors(colorScheme)

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
          const xLabel = xLabels[resolved.cell.colIndex]
          const yLabel = yLabels[resolved.cell.rowIndex]
          if (xLabel === undefined || yLabel === undefined) return ''
          return [`<b>${resolved.value.toFixed(3)}</b>`, `X: ${escapeHtml(xLabel)}`, `Y: ${escapeHtml(yLabel)}`].join(
            '<br>',
          )
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
            rich: {
              ink: { color: '#000000', fontSize: HEATMAP_CELL_TEXT_SIZE },
              paper: { color: '#ffffff', fontSize: HEATMAP_CELL_TEXT_SIZE },
            },
            formatter: (params: unknown) => {
              if (!isRecord(params) || !Array.isArray(params.value)) return '—'
              const value = params.value[2]
              return typeof value === 'number' && Number.isFinite(value)
                ? `{${cellLabelTone(value, min, max, colors)}|${formatHeatmapValue(value)}}`
                : '—'
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
        if (cell === null) return
        setCellSelection(cell)
        onCellSelect?.(cell)
      },
    }),
    [onCellSelect],
  )

  return (
    <div className="flex h-full min-h-[320px] w-full flex-col gap-2">
      {onCellSelect !== undefined && xLabels.length > 0 && yLabels.length > 0 && (
        <div className="grid min-w-0 grid-cols-2 gap-2 sm:grid-cols-[minmax(0,1fr)_minmax(0,1fr)_auto] sm:items-end">
          <label className="grid min-w-0 gap-1 text-sm">
            纵轴项目
            <select
              className={similarityFieldClass}
              value={rowIndex}
              onChange={(event) => setCellSelection({ rowIndex: Number(event.target.value), colIndex })}
            >
              {yLabels.map((label, index) => (
                <option key={label} value={index}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <label className="grid min-w-0 gap-1 text-sm">
            横轴项目
            <select
              className={similarityFieldClass}
              value={colIndex}
              onChange={(event) => setCellSelection({ rowIndex, colIndex: Number(event.target.value) })}
            >
              {xLabels.map((label, index) => (
                <option key={label} value={index}>
                  {label}
                </option>
              ))}
            </select>
          </label>
          <Button
            type="button"
            variant="outline"
            className="col-span-2 sm:col-span-1"
            disabled={!canInspectCell}
            onClick={() => onCellSelect({ rowIndex, colIndex })}
          >
            查看单元格
          </Button>
          {!canInspectCell && (
            <p role="status" className="text-sm text-muted-foreground sm:col-span-3">
              当前单元格已被筛选。
            </p>
          )}
        </div>
      )}
      <div className="min-h-0 flex-1 overflow-x-auto" tabIndex={0} role="region" aria-label="相似度矩阵图形">
        <div className="h-full min-h-[260px]" style={{ minWidth: Math.max(320, xLabels.length * 48 + 100) }}>
          <EChart option={option} onEvents={onEvents} />
        </div>
      </div>
    </div>
  )
}
