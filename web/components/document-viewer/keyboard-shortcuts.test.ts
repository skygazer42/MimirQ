import { describe, expect, it } from 'vitest'

import { resolveChunkKeyboardNavigation } from './keyboard-shortcuts'

describe('resolveChunkKeyboardNavigation', () => {
  it('cycles through matched search results with j/k', () => {
    expect(
      resolveChunkKeyboardNavigation({
        key: 'j',
        matchCount: 4,
        matchCursor: 1,
        loadedChunkCount: 10,
        highlightIndex: 5,
      })
    ).toEqual({ type: 'match', nextIndex: 2 })

    expect(
      resolveChunkKeyboardNavigation({
        key: 'k',
        matchCount: 4,
        matchCursor: 0,
        loadedChunkCount: 10,
        highlightIndex: 5,
      })
    ).toEqual({ type: 'match', nextIndex: 3 })
  })

  it('falls back to loaded chunks when there is no active match list', () => {
    expect(
      resolveChunkKeyboardNavigation({
        key: 'j',
        matchCount: 0,
        matchCursor: 0,
        loadedChunkCount: 3,
        highlightIndex: 1,
      })
    ).toEqual({ type: 'chunk', nextIndex: 2 })

    expect(
      resolveChunkKeyboardNavigation({
        key: 'k',
        matchCount: 0,
        matchCursor: 0,
        loadedChunkCount: 3,
        highlightIndex: -1,
      })
    ).toEqual({ type: 'chunk', nextIndex: 2 })
  })

  it('ignores unrelated keys and empty collections', () => {
    expect(
      resolveChunkKeyboardNavigation({
        key: 'x',
        matchCount: 2,
        matchCursor: 0,
        loadedChunkCount: 5,
        highlightIndex: 0,
      })
    ).toBeNull()

    expect(
      resolveChunkKeyboardNavigation({
        key: 'j',
        matchCount: 0,
        matchCursor: 0,
        loadedChunkCount: 0,
        highlightIndex: -1,
      })
    ).toBeNull()
  })
})
