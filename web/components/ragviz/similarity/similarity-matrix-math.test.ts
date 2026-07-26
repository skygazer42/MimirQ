import { describe, expect, it } from 'vitest'

import {
  applyMask,
  applyTopKByColumn,
  applyTopKByRow,
  calculateDifferenceModeStatistics,
  calculateNormalModeStatistics,
  combineWithAND,
  combineWithOR,
  computeFinalMask,
  computeThresholdMask,
  computeTopKMask,
  formatHeatmapValue,
} from './similarity-matrix-math'

describe('computeThresholdMask', () => {
  it('keeps only finite values within [min, max]', () => {
    expect(computeThresholdMask([[0.2, 0.8], [0.5, Number.NaN]], 0.4, 1)).toEqual([
      [false, true],
      [true, false],
    ])
  })

  it('normalizes swapped min/max bounds', () => {
    expect(computeThresholdMask([[0.5]], 1, 0.4)).toEqual([[true]])
  })
})

describe('applyTopKByRow', () => {
  it('marks the top-k values of each row', () => {
    const mask = [[false, false, false]]
    applyTopKByRow([[3, 1, 2]], mask, 2)
    expect(mask).toEqual([[true, false, true]])
  })
})

describe('applyTopKByColumn', () => {
  it('marks the top-k values of each column', () => {
    const mask = [
      [false, false],
      [false, false],
    ]
    applyTopKByColumn(
      [
        [1, 4],
        [3, 2],
      ],
      mask,
      2,
      1
    )
    expect(mask).toEqual([
      [false, true],
      [true, false],
    ])
  })
})

describe('computeTopKMask', () => {
  it('returns an all-true mask when topK is 0', () => {
    expect(computeTopKMask([[0.1, 0.2]], 0, 'x')).toEqual([[true, true]])
  })

  it('keeps only the best cell per row for axis x', () => {
    expect(
      computeTopKMask(
        [
          [0.9, 0.1],
          [0.2, 0.7],
        ],
        1,
        'x'
      )
    ).toEqual([
      [true, false],
      [false, true],
    ])
  })
})

describe('combineWithAND', () => {
  it('intersects two masks cell-wise', () => {
    expect(
      combineWithAND(
        [
          [true, true],
          [false, true],
        ],
        [
          [true, false],
          [true, true],
        ]
      )
    ).toEqual([
      [true, false],
      [false, true],
    ])
  })
})

describe('combineWithOR', () => {
  it('returns an empty mask for no inputs', () => {
    expect(combineWithOR([])).toEqual([])
  })

  it('unions masks cell-wise', () => {
    expect(
      combineWithOR([
        [
          [true, false],
          [false, false],
        ],
        [
          [false, false],
          [false, true],
        ],
      ])
    ).toEqual([
      [true, false],
      [false, true],
    ])
  })
})

describe('computeFinalMask', () => {
  it('combines threshold and top-k masks with AND', () => {
    expect(
      computeFinalMask(
        [
          [0.9, 0.5],
          [0.3, 0.8],
        ],
        { min: 0.4, max: 1 },
        { value: 1, axis: 'x' }
      )
    ).toEqual([
      [true, false],
      [false, true],
    ])
  })
})

describe('applyMask', () => {
  it('nulls out hidden cells and keeps visible ones', () => {
    expect(
      applyMask(
        [
          [0.1, 0.2],
          [0.3, 0.4],
        ],
        [
          [true, false],
          [false, true],
        ]
      )
    ).toEqual([
      [0.1, null],
      [null, 0.4],
    ])
  })
})

describe('calculateNormalModeStatistics', () => {
  it('computes display, diagonal, and missing-match counts', () => {
    expect(
      calculateNormalModeStatistics(
        [
          [true, false],
          [false, false],
        ],
        'x'
      )
    ).toEqual({
      totalCount: 4,
      currentDisplayCount: 1,
      diagonalTrueCount: 1,
      diagonalTotalCount: 2,
      missingMatchCount: 1,
      topKAxis: 'x',
    })
  })

  it('reports zero missing matches when no top-k axis is active', () => {
    expect(
      calculateNormalModeStatistics([[false]], 'none').missingMatchCount
    ).toBe(0)
  })
})

describe('calculateDifferenceModeStatistics', () => {
  it('computes the confusion matrix plus recall and precision', () => {
    expect(
      calculateDifferenceModeStatistics(
        [
          [true, false],
          [false, true],
        ],
        [
          [true, true],
          [false, false],
        ]
      )
    ).toEqual({
      truePositive: 1,
      trueNegative: 1,
      falsePositive: 1,
      falseNegative: 1,
      contextRecall: 0.5,
      contextPrecision: 0.5,
    })
  })
})

describe('formatHeatmapValue', () => {
  it('renders a dash for non-finite values', () => {
    expect(formatHeatmapValue(null)).toBe('—')
    expect(formatHeatmapValue(Number.NaN)).toBe('—')
  })

  it('trims trailing zeros and dangling decimal points', () => {
    expect(formatHeatmapValue(0.5)).toBe('0.5')
    expect(formatHeatmapValue(0.1234)).toBe('0.1234')
    expect(formatHeatmapValue(1)).toBe('1')
  })
})
