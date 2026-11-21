import { describe, expect, it } from 'vitest'

import type { ParsingElement } from '@/lib/api/parsing'
import { readPersistedParsingElements } from './parsing-elements'

describe('persisted parsing elements', () => {
  it('keeps every supported element kind in its original order', () => {
    const kinds: ParsingElement['kind'][] = [
      'heading',
      'paragraph',
      'list',
      'table',
      'image',
      'equation',
      'seal',
      'unknown',
    ]
    const elements = kinds.map((kind) => ({ id: kind, kind }))

    expect(readPersistedParsingElements(elements)).toEqual(elements)
  })

  it('preserves zero, empty text, nullable fields and finite decimal coordinates', () => {
    const elements: ParsingElement[] = [
      {
        id: 'positioned',
        kind: 'paragraph',
        page: 0,
        pages: [0, 1],
        confidence: 0,
        text: '',
        bbox: { x0: 0.5, y0: 1.25, x1: 3.75, y1: 4.5 },
        attributes: { language: 'zh', selected: false },
      },
      {
        id: 'nullable',
        kind: 'image',
        page: null,
        pages: null,
        visual_kind: null,
        text: null,
        confidence: null,
        source_backend: null,
        source_element_id: null,
        bbox: null,
        attributes: null,
      },
    ]

    const restored = readPersistedParsingElements(elements)
    if (restored === undefined) throw new Error('Expected the persisted element collection')
    expect(restored).toEqual(elements)
    expect(restored[0]).toBe(elements[0])
    expect(restored[1]).toBe(elements[1])
  })

  it('rejects malformed persisted entries without silently dropping source elements', () => {
    const element: ParsingElement = { id: 'valid', kind: 'paragraph', text: 'Kept text' }
    const malformed: unknown[] = [
      null,
      4,
      [],
      {},
      { id: 4, kind: 'paragraph' },
      { id: 'missing-kind' },
      { id: 'unknown-kind', kind: 'widget' },
      { ...element, text: 4 },
      { ...element, visual_kind: false },
      { ...element, source_backend: [] },
      { ...element, source_element_id: {} },
      { ...element, page: '1' },
      { ...element, pages: [0, '1'] },
      { ...element, confidence: '0.9' },
      { ...element, confidence: Number.NaN },
      { ...element, bbox: [] },
      { ...element, bbox: { x0: 0, y0: 0, x1: 1 } },
      { ...element, bbox: { x0: 0, y0: 0, x1: 1, y1: Number.POSITIVE_INFINITY } },
      { ...element, attributes: [] },
    ]

    for (const entry of malformed) expect(() => readPersistedParsingElements([element, entry])).toThrow('格式不正确')
  })

  it('keeps absent metadata distinct from an empty collection and rejects non-array values', () => {
    expect(readPersistedParsingElements(undefined)).toBeUndefined()
    expect(readPersistedParsingElements(null)).toBeUndefined()
    expect(readPersistedParsingElements([])).toEqual([])
    expect(() => readPersistedParsingElements({})).toThrow('格式不正确')
  })
})
