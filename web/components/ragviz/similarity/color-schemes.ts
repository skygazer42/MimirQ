import type { RagvizSimilarityMatrixResult } from '@/types'
import { axisLabelForItem, isRecord } from './utils'

const DEFAULT_FIELD_NAMES = ['document', 'text', 'name']

function getDefaultDisplayField(fields: string[]) {
  for (const name of DEFAULT_FIELD_NAMES) {
    if (fields.includes(name)) return name
  }
  return fields[0] || ''
}

export type VisualConfig = {
  displayFields: { xField: string; yField: string }
  similarityRange: { min: number; max: number }
  filters: { topK: { value: number; axis: 'x' | 'y' } }
  sorting: { order: string }
}

export function createDefaultVisualConfig(
  xFields: string[],
  yFields: string[]
): VisualConfig {
  const defaultXField = getDefaultDisplayField(xFields)
  const defaultYField = getDefaultDisplayField(yFields)

  return {
    displayFields: {
      xField: defaultXField,
      yField: defaultYField,
    },
    similarityRange: { min: 0, max: 1 },
    filters: { topK: { value: 0, axis: 'x' } },
    sorting: { order: 'none' },
  }
}

export function isVisualConfig(value: unknown): value is VisualConfig {
  return (
    isRecord(value) &&
    isRecord(value.displayFields) &&
    typeof value.displayFields.xField === 'string' &&
    typeof value.displayFields.yField === 'string' &&
    isRecord(value.similarityRange) &&
    typeof value.similarityRange.min === 'number' &&
    typeof value.similarityRange.max === 'number' &&
    isRecord(value.filters) &&
    isRecord(value.filters.topK) &&
    typeof value.filters.topK.value === 'number' &&
    (value.filters.topK.axis === 'x' || value.filters.topK.axis === 'y') &&
    isRecord(value.sorting) &&
    typeof value.sorting.order === 'string'
  )
}

export type SimilarityMatrixEntry = {
  xCollectionId: string
  yCollectionId: string
  xCollectionLabel: string
  yCollectionLabel: string
  result: RagvizSimilarityMatrixResult
  visualConfig: VisualConfig
}

export type MatrixButtonState = {
  applyData: boolean
  applyFilter: boolean
  exclusive: boolean
}

export type ColorSchemeKey = 'viridis' | 'plasma' | 'cividis' | 'YlGnBu' | 'hot'

export const DIFFERENCE_COLORSCALE: Array<[number, string]> = [
  [0, '#2563eb'],
  [0.5, '#f8fafc'],
  [1, '#dc2626'],
]

const DIFFERENCE_COLOR_PREVIEW =
  'linear-gradient(90deg,#2563eb,#f8fafc,#dc2626)'

export const COLOR_SCHEMES: Array<{
  key: ColorSchemeKey
  label: string
  preview: string
  colorscale: Array<[number, string]>
}> = [
  {
    key: 'viridis',
    label: 'Viridis',
    preview: 'linear-gradient(90deg,#440154,#21908d,#fde725)',
    colorscale: [
      [0, '#440154'],
      [0.5, '#21908d'],
      [1, '#fde725'],
    ],
  },
  {
    key: 'plasma',
    label: 'Plasma',
    preview: 'linear-gradient(90deg,#0d0887,#cc4678,#f0f921)',
    colorscale: [
      [0, '#0d0887'],
      [0.5, '#cc4678'],
      [1, '#f0f921'],
    ],
  },
  {
    key: 'cividis',
    label: 'Cividis',
    preview: 'linear-gradient(90deg,#00204c,#5f7d7f,#fee838)',
    colorscale: [
      [0, '#00204c'],
      [0.5, '#5f7d7f'],
      [1, '#fee838'],
    ],
  },
  {
    key: 'YlGnBu',
    label: 'YlGnBu',
    preview: 'linear-gradient(90deg,#ffffcc,#1d91c0,#081d58)',
    colorscale: [
      [0, '#ffffcc'],
      [0.5, '#1d91c0'],
      [1, '#081d58'],
    ],
  },
  {
    key: 'hot',
    label: 'Hot',
    preview: 'linear-gradient(90deg,#000000,#ff0000,#ffff00)',
    colorscale: [
      [0, '#000000'],
      [0.5, '#ff0000'],
      [1, '#ffff00'],
    ],
  },
]

function colorStopsToVisualMapColors(stops: Array<[number, string]>) {
  // COLOR_SCHEMES stops are evenly spaced (0 / 0.5 / 1), so a plain color
  // array reproduces the exact same gradient in echarts visualMap.inRange.
  return stops.map(([, color]) => color)
}

export function toEchartsVisualMapColors(key: ColorSchemeKey) {
  return colorStopsToVisualMapColors(
    COLOR_SCHEMES.find((scheme) => scheme.key === key)?.colorscale ??
      COLOR_SCHEMES[0].colorscale
  )
}

export const DIFFERENCE_VISUALMAP_COLORS = colorStopsToVisualMapColors(
  DIFFERENCE_COLORSCALE
)

export function heatmapLegendBackground(
  key: ColorSchemeKey,
  isDifference: boolean
) {
  if (isDifference) return DIFFERENCE_COLOR_PREVIEW
  return (
    COLOR_SCHEMES.find((scheme) => scheme.key === key)?.preview ??
    COLOR_SCHEMES[0].preview
  )
}

export function generateUniqueLabels(
  items: Array<Record<string, unknown>>,
  field: string
) {
  const counts = new Map<string, number>()
  return items.map((item) => {
    const raw = axisLabelForItem(item, field)
    const key = raw || '(empty)'
    const next = (counts.get(key) || 0) + 1
    counts.set(key, next)
    return next === 1 ? key : `${key} (${next})`
  })
}
