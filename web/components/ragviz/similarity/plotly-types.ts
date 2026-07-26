import { isRecord } from './utils'

export type SelectedHeatmapCell = { rowIndex: number; colIndex: number }
export type PlotlyColorScale = string | Array<[number, string]>

export type PlotlyTrace = {
  type: 'heatmap'
  z: Array<Array<number | null>>
  x: string[]
  y: string[]
  colorscale: PlotlyColorScale
  zmin: number
  zmax: number
  text?: string[][]
  texttemplate?: string
  textfont?: { color: string; size: number }
  showscale?: boolean
  hovertemplate: string
}

export type PlotlyLayout = {
  margin: { l: number; r: number; t: number; b: number }
  xaxis: { automargin: boolean; tickangle: number }
  yaxis: { automargin: boolean; autorange: 'reversed' }
  paper_bgcolor: string
  plot_bgcolor: string
}

export type PlotlyConfig = {
  responsive: boolean
  displaylogo: boolean
  displayModeBar?: boolean
}

export type PlotlyLike = {
  react: (
    element: HTMLDivElement,
    data: PlotlyTrace[],
    layout: PlotlyLayout,
    config: PlotlyConfig
  ) => void
  purge: (element: HTMLDivElement) => void
}

export type PlotlyClickPoint = {
  pointNumber?: number | number[]
  pointIndex?: number | number[]
  i?: number
  j?: number
}

export type PlotlyClickEvent = {
  points?: PlotlyClickPoint[]
}

export type PlotlyEventTarget = HTMLDivElement & {
  on?: (
    eventName: 'plotly_click',
    handler: (event: PlotlyClickEvent) => void
  ) => void
  removeAllListeners?: (eventName?: string) => void
}

export function isPlotlyLike(value: unknown): value is PlotlyLike {
  if (!value || (typeof value !== 'object' && typeof value !== 'function'))
    return false
  const maybe = value as { react?: unknown; purge?: unknown }
  return typeof maybe.react === 'function' && typeof maybe.purge === 'function'
}

export function pickPlotlyModule(modUnknown: unknown): PlotlyLike | null {
  const mod = isRecord(modUnknown) ? modUnknown : null
  if (isPlotlyLike(mod?.default)) return mod.default
  if (isPlotlyLike(modUnknown)) return modUnknown
  return null
}

function heatmapPointPair(point: PlotlyClickPoint): number[] | null {
  if (Array.isArray(point.pointNumber)) return point.pointNumber
  if (Array.isArray(point.pointIndex)) return point.pointIndex
  return null
}

function heatmapPointCoordinate(
  directValue: unknown,
  pair: number[] | null,
  pairIndex: number
) {
  if (typeof directValue === 'number') return directValue
  if (Array.isArray(pair) && typeof pair[pairIndex] === 'number') {
    return pair[pairIndex]
  }
  return null
}

export function resolveHeatmapPoint(
  event: PlotlyClickEvent
): SelectedHeatmapCell | null {
  const point = event.points?.[0]
  if (!point) return null

  const pair = heatmapPointPair(point)
  const rowIndex = heatmapPointCoordinate(point.i, pair, 0)
  const colIndex = heatmapPointCoordinate(point.j, pair, 1)

  if (rowIndex === null || colIndex === null) return null
  return { rowIndex, colIndex }
}
