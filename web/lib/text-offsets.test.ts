import { describe, expect, it } from 'vitest'

import {
  createCodePointToUtf16Converter,
  expandTextRangeToCharacters,
  findCaseInsensitiveTextRanges,
} from './text-offsets'

describe('API text offset conversion', () => {
  it('retains ordinary offsets, the zero boundary and an empty source', () => {
    const converter = createCodePointToUtf16Converter('甲AB')
    expect(converter.codePointLength).toBe(3)
    expect([0, 1, 2, 3].map(converter.toUtf16)).toEqual([0, 1, 2, 3])
    expect(createCodePointToUtf16Converter('').toUtf16(0)).toBe(0)
  })

  it('converts both sides of supplementary characters without splitting them', () => {
    const text = '😀AB𠮷'
    const converter = createCodePointToUtf16Converter(text)
    expect(converter.codePointLength).toBe(4)
    expect([0, 1, 2, 3, 4].map(converter.toUtf16)).toEqual([0, 2, 3, 4, 6])
    expect(text.slice(converter.toUtf16(1), converter.toUtf16(3))).toBe('AB')
  })

  it.each([-1, 1.5, 8, Number.NaN, Number.POSITIVE_INFINITY])(
    'does not clamp an unavailable source offset: %s',
    (offset) => {
      expect(createCodePointToUtf16Converter('😀AB').toUtf16(offset)).toBeUndefined()
    },
  )
})

describe('original text search and view boundaries', () => {
  it('maps lowercase expansion and emoji back to the exact original substring', () => {
    expect(findCaseInsensitiveTextRanges('İ😀hit', 'hit', 50)).toEqual([{ start: 3, end: 6 }])
    expect(findCaseInsensitiveTextRanges('İ😀hit', 'i', 1)).toEqual([{ start: 0, end: 1 }])
    expect(findCaseInsensitiveTextRanges('İ😀hit', '😀', 1)).toEqual([{ start: 1, end: 3 }])
  })

  it('keeps whole-string lowercase and exact whitespace semantics and the caller match budget', () => {
    expect(findCaseInsensitiveTextRanges('ΟΣ Σ', 'σ', 50)).toEqual([{ start: 3, end: 4 }])
    expect(findCaseInsensitiveTextRanges('a  b', 'a b', 50)).toEqual([])
    expect(findCaseInsensitiveTextRanges('aa', 'a', 1)).toEqual([{ start: 0, end: 1 }])
    expect(findCaseInsensitiveTextRanges('aa', '', 1)).toEqual([])
  })

  it('expands split pairs but preserves zero, the end and complete character boundaries', () => {
    expect(expandTextRangeToCharacters('a😀b', 2, 3)).toEqual({ start: 1, end: 3 })
    expect(expandTextRangeToCharacters('a😀b', 0, 2)).toEqual({ start: 0, end: 3 })
    expect(expandTextRangeToCharacters('a😀b', 1, 3)).toEqual({ start: 1, end: 3 })
    expect(expandTextRangeToCharacters('a😀b', 4, 4)).toEqual({ start: 4, end: 4 })
    expect(expandTextRangeToCharacters('', 0, 0)).toEqual({ start: 0, end: 0 })
  })
})
