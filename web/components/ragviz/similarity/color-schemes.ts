import type { RagvizSimilarityMatrixResult } from '@/types'
import { axisLabelForItem, isRecord } from './utils'

const DEFAULT_FIELD_NAMES = ['document', 'text', 'name']

function getDefaultDisplayField(fields: string[]) {
  for (const name of DEFAULT_FIELD_NAMES) {
    if (fields.includes(name)) return name
  }
  return fields[0] ?? ''
}

export type VisualConfig = {
  displayFields: { xField: string; yField: string }
  similarityRange: { min: number; max: number }
  filters: { topK: { value: number; axis: 'x' | 'y' } }
  sorting: { order: string }
}

export function createDefaultVisualConfig(xFields: string[], yFields: string[]): VisualConfig {
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

export const COLOR_SCHEMES = {
  viridis: { label: 'Viridis', colors: ['#440154', '#21908d', '#fde725'] },
  plasma: { label: 'Plasma', colors: ['#0d0887', '#cc4678', '#f0f921'] },
  cividis: { label: 'Cividis', colors: ['#00204c', '#5f7d7f', '#fee838'] },
  YlGnBu: { label: 'YlGnBu', colors: ['#ffffcc', '#1d91c0', '#081d58'] },
  hot: { label: 'Hot', colors: ['#000000', '#ff0000', '#ffff00'] },
}

export type ColorSchemeKey = keyof typeof COLOR_SCHEMES

export function isColorSchemeKey(value: string): value is ColorSchemeKey {
  return Object.hasOwn(COLOR_SCHEMES, value)
}

export const DIFFERENCE_VISUALMAP_COLORS = ['#2563eb', '#f8fafc', '#dc2626']

export function toEchartsVisualMapColors(key: ColorSchemeKey) {
  return COLOR_SCHEMES[key].colors.slice()
}

export function heatmapLegendBackground(key: ColorSchemeKey, isDifference: boolean) {
  const colors = isDifference ? DIFFERENCE_VISUALMAP_COLORS : COLOR_SCHEMES[key].colors
  return `linear-gradient(90deg,${colors.join(',')})`
}

export function generateUniqueLabels(items: Array<Record<string, unknown>>, field: string) {
  const counts = new Map<string, number>()
  const usedLabels = new Set<string>()
  return items.map((item) => {
    const raw = axisLabelForItem(item, field)
    const baseLabel = raw === '' ? '(empty)' : raw
    let occurrence = (counts.get(baseLabel) ?? 0) + 1
    let label = occurrence === 1 ? baseLabel : `${baseLabel} (${occurrence})`
    while (usedLabels.has(label)) {
      occurrence += 1
      label = `${baseLabel} (${occurrence})`
    }
    counts.set(baseLabel, occurrence)
    usedLabels.add(label)
    return label
  })
}
