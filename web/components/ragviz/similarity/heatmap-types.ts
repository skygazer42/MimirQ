import { isRecord } from './utils'

export type SelectedHeatmapCell = { rowIndex: number; colIndex: number }

/**
 * Minimal shape of the ECharts `click` event params we rely on.
 * Heatmap series data items are `[colIndex, rowIndex, value]` tuples, echoed
 * back on click via `params.value` (and `params.data`).
 */
export type HeatmapClickParams = {
  seriesType?: string
  value?: unknown
  data?: unknown
}

function heatmapPointTuple(params: HeatmapClickParams): unknown[] | null {
  if (Array.isArray(params.value)) return params.value
  if (Array.isArray(params.data)) return params.data
  return null
}

export function resolveHeatmapPoint(
  eventParams: unknown
): SelectedHeatmapCell | null {
  if (!isRecord(eventParams)) return null
  const params = eventParams as HeatmapClickParams
  if (params.seriesType !== undefined && params.seriesType !== 'heatmap') {
    return null
  }

  const tuple = heatmapPointTuple(params)
  if (!tuple) return null

  const colIndex = tuple[0]
  const rowIndex = tuple[1]
  if (typeof colIndex !== 'number' || typeof rowIndex !== 'number') return null
  if (!Number.isInteger(colIndex) || !Number.isInteger(rowIndex)) return null
  return { rowIndex, colIndex }
}
