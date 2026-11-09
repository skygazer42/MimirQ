import { describe, expect, it } from 'vitest'

import { buildBlockIdToBestChunkIndex } from './pdf-box-mapping'

describe('buildBlockIdToBestChunkIndex', () => {
  it('maps blocks to the greatest overlapping chunk and breaks ties by length', () => {
    const result = buildBlockIdToBestChunkIndex(
      [{ id: 'first', start: 2, end: 8 }, { id: 'second', start: 11, end: 15 }],
      [
        { index: 0, start_index: 0, end_index: 10 },
        { index: 1, start_index: 2, end_index: 8 },
        { index: 2, start_index: 10, end_index: 20 },
      ]
    )

    expect([...result]).toEqual([['first', 1], ['second', 2]])
  })

  it('omits invalid numeric ranges without changing valid chunk indices', () => {
    const result = buildBlockIdToBestChunkIndex(
      [
        { id: 'not-finite', start: Number.NaN, end: 10 },
        { id: 'empty', start: 5, end: 5 },
        { id: 'valid', start: 1.9, end: 4.8 },
      ],
      [
        { index: 9, start_index: 0, end_index: Number.POSITIVE_INFINITY },
        { index: 7, start_index: 0, end_index: 5 },
      ]
    )

    expect([...result]).toEqual([['valid', 7]])
  })
})
