import { describe, expect, it } from 'vitest'

import { buildParsingLayoutEntries, classifyParsingBlock, getParsingLayoutMeta } from './parsing-layout'

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

  it('splits multi-position blocks into finer-grained layout entries when line structure matches', () => {
    const entries = buildParsingLayoutEntries([
      {
        id: 'toc',
        text: '前言\n1 范围\n2 规范性引用文件',
        positions: [
          { bottom: 0.12, left: 0.1, pages: [0], raw: '@@1', right: 0.8, top: 0.08 },
          { bottom: 0.18, left: 0.1, pages: [0], raw: '@@2', right: 0.8, top: 0.14 },
          { bottom: 0.24, left: 0.1, pages: [0], raw: '@@3', right: 0.8, top: 0.2 },
        ],
      },
    ])

    expect(entries).toHaveLength(3)
    expect(entries.map((entry) => entry.text)).toEqual(['前言', '1 范围', '2 规范性引用文件'])
    expect(entries.map((entry) => entry.id)).toEqual(['toc:0', 'toc:1', 'toc:2'])
    expect(entries.every((entry) => entry.blockId === 'toc')).toBe(true)
  })
})
