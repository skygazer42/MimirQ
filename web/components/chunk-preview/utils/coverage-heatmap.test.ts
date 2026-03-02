import { describe, expect, it } from 'vitest'

import { computeCoverageHeatmapBins } from './coverage-heatmap'

describe('computeCoverageHeatmapBins', () => {
  it('bins overlapping ranges into counts', () => {
    const chunks: any[] = [
      { index: 0, start_index: 0, end_index: 50, length: 50, content: 'A', metadata: {} },
      { index: 1, start_index: 40, end_index: 70, length: 30, content: 'B', metadata: {} },
    ]

    const out = computeCoverageHeatmapBins(chunks as any, 100, { bins: 10 })
    expect(out.counts).toEqual([1, 1, 1, 1, 2, 1, 1, 0, 0, 0])
    expect(out.max).toBe(2)
  })

  it('excludes parent chunks for parent_child strategy', () => {
    const chunks: any[] = [
      { index: 0, start_index: 0, end_index: 100, length: 100, content: 'P', metadata: { chunk_role: 'parent' } },
      { index: 1, start_index: 0, end_index: 50, length: 50, content: 'C', metadata: { chunk_role: 'child' } },
    ]

    const out = computeCoverageHeatmapBins(chunks as any, 100, { bins: 10, strategy: 'parent_child' })
    expect(out.counts).toEqual([1, 1, 1, 1, 1, 0, 0, 0, 0, 0])
    expect(out.max).toBe(1)
  })
})

