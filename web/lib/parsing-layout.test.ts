import { describe, expect, it } from 'vitest'

import { buildParsingLayoutEntries, classifyParsingBlock, getParsingLayoutMeta } from './parsing-layout'

describe('parsing-layout', () => {
  it('classifies common parsing blocks into review-friendly layout kinds', () => {
    expect(classifyParsingBlock({ text: '# Executive Summary' })).toBe('heading')
    expect(
      classifyParsingBlock({
        text: '| Name | Score |\n| --- | --- |\n| Alice | 98 |',
      })
    ).toBe('table')
    expect(classifyParsingBlock({ text: '![Figure 1](figure.png)' })).toBe('image')
    expect(classifyParsingBlock({ text: '- one\n- two\n- three' })).toBe('list')
    expect(classifyParsingBlock({ text: '$$E = mc^2$$' })).toBe('equation')
    expect(classifyParsingBlock({ text: 'This is a normal paragraph.' })).toBe(
      'paragraph'
    )
    expect(classifyParsingBlock({ text: '三种使用场景' })).toBe('heading')
    expect(classifyParsingBlock({ text: '过去两年做企业大模型应用，知识库类型的项目咨询占比算是最高的，有公众号、知乎这些' })).toBe(
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
