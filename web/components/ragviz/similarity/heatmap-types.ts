import { isRecord } from './utils'

export type SelectedHeatmapCell = { rowIndex: number; colIndex: number }

export function resolveHeatmapPoint(eventParams: unknown): SelectedHeatmapCell | null {
  if (!isRecord(eventParams)) return null
  const { seriesType, value, data } = eventParams
  if (seriesType !== undefined && seriesType !== 'heatmap') return null

  const tuple = Array.isArray(value) ? value : data
  if (!Array.isArray(tuple)) return null
  const [colIndex, rowIndex] = tuple
  if (typeof colIndex !== 'number' || typeof rowIndex !== 'number') return null
  if (!Number.isInteger(colIndex) || !Number.isInteger(rowIndex)) return null
  return { rowIndex, colIndex }
}
