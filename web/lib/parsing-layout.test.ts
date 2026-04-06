import { describe, expect, it } from 'vitest'

import { classifyParsingBlock, getParsingLayoutMeta } from './parsing-layout'

describe('parsing-layout', () => {
  it('classifies common parsing blocks into review-friendly layout kinds', () => {
    expect(classifyParsingBlock({ id: 'heading', text: '# Executive Summary', positions: [] })).toBe('heading')
    expect(
      classifyParsingBlock({
        id: 'table',
        text: '| Name | Score |\n| --- | --- |\n| Alice | 98 |',
        positions: [],
      })
    ).toBe('table')
    expect(classifyParsingBlock({ id: 'image', text: '![Figure 1](figure.png)', positions: [] })).toBe('image')
    expect(classifyParsingBlock({ id: 'list', text: '- one\n- two\n- three', positions: [] })).toBe('list')
    expect(classifyParsingBlock({ id: 'equation', text: '$$E = mc^2$$', positions: [] })).toBe('equation')
    expect(classifyParsingBlock({ id: 'paragraph', text: 'This is a normal paragraph.', positions: [] })).toBe(
      'paragraph'
    )
  })

  it('returns quiet review labels and overlay tokens for each layout kind', () => {
    expect(getParsingLayoutMeta('heading').label).toBe('标题')
    expect(getParsingLayoutMeta('paragraph').shortLabel).toBe('正文')
    expect(getParsingLayoutMeta('table').overlayClassName).toContain('emerald')
    expect(getParsingLayoutMeta('image').chipClassName).toContain('amber')
  })
})
