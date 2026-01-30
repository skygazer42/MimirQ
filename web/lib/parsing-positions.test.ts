import { describe, expect, it } from 'vitest'

import {
  createPositionTagIndexMapper,
  extractBlocksFromMarkdownWithRanges,
  findPositionTagRanges,
  stripPositionTags,
} from './parsing-positions'

describe('parsing-positions', () => {
  it('findPositionTagRanges finds @@page tags', () => {
    const md = 'A@@1\t0.1\t0.2\t0.3\t0.4##B@@2\t0.2\t0.3\t0.4\t0.5##C'
    const ranges = findPositionTagRanges(md)
    expect(ranges.length).toBe(2)
    expect(ranges[0].start).toBe(md.indexOf('@@1'))
    expect(ranges[1].start).toBe(md.indexOf('@@2'))
  })

  it('createPositionTagIndexMapper maps raw indices into cleaned indices', () => {
    const md = 'A@@1\t0.1\t0.2\t0.3\t0.4##B'
    const cleaned = stripPositionTags(md)
    expect(cleaned).toBe('AB')

    const mapIndex = createPositionTagIndexMapper(md)
    expect(mapIndex(0)).toBe(0) // 'A'
    expect(mapIndex(md.indexOf('@@1'))).toBe(1) // inside tag => maps to tag start (after 'A')
    expect(mapIndex(md.length - 1)).toBe(cleaned.length - 1) // 'B'
  })

  it('extractBlocksFromMarkdownWithRanges returns blocks with raw ranges', () => {
    const md = 'A@@1\t0.1\t0.2\t0.3\t0.4##B@@2\t0.2\t0.3\t0.4\t0.5##'
    const parsed = extractBlocksFromMarkdownWithRanges(md)
    expect(parsed.cleanedMarkdown).toBe('AB')
    expect(parsed.tagRanges.length).toBe(2)
    expect(parsed.blocks.length).toBe(2)

    expect(parsed.blocks[0].text).toBe('A')
    expect(parsed.blocks[0].rawStart).toBe(0)
    expect(parsed.blocks[0].rawEnd).toBe(md.indexOf('@@1'))

    expect(parsed.blocks[1].text).toBe('B')
    expect(parsed.blocks[1].rawStart).toBe(parsed.tagRanges[0].end)
    expect(parsed.blocks[1].rawEnd).toBe(md.indexOf('@@2'))

    const mapIndex = createPositionTagIndexMapper(md, parsed.tagRanges)
    expect(mapIndex(parsed.blocks[1].rawStart)).toBe(1)
  })
})

