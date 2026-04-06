import { describe, expect, it } from 'vitest'

import type { ParsingLayoutEntry } from './parsing-layout'
import { findEditSelectionForActiveParsingEntry } from './parsing-edit-focus'

function makeEntry(overrides: Partial<ParsingLayoutEntry>): ParsingLayoutEntry {
  return {
    id: 'entry-0',
    blockId: 'block-0',
    text: 'Intro',
    kind: 'paragraph',
    position: { pages: [0], left: 0, right: 1, top: 0, bottom: 1, raw: '@@1' },
    pageIndex: 0,
    charCount: 5,
    lineCount: 1,
    ...overrides,
  }
}

describe('parsing-edit-focus', () => {
  it('maps the active layout row to the matching markdown segment instead of the document start', () => {
    const markdown = '# Summary\n\nFirst paragraph.\n\nSecond paragraph.\n\n## Details\n\nThird paragraph.'
    const entries = [
      makeEntry({ id: 'block-0', text: '# Summary', kind: 'heading' }),
      makeEntry({ id: 'block-1', text: 'First paragraph.' }),
      makeEntry({ id: 'block-2', text: 'Second paragraph.' }),
      makeEntry({ id: 'block-3', text: '## Details', kind: 'heading' }),
      makeEntry({ id: 'block-4', text: 'Third paragraph.' }),
    ]

    expect(findEditSelectionForActiveParsingEntry(markdown, entries, 'block-2')).toEqual({
      start: markdown.indexOf('Second paragraph.'),
      end: markdown.indexOf('Second paragraph.'),
    })
  })

  it('keeps split layout rows aligned in document order for multi-position blocks', () => {
    const markdown = '前言\n\n1 范围\n\n2 规范性引用文件\n\n附录'
    const entries = [
      makeEntry({ id: 'toc:0', blockId: 'toc', text: '前言' }),
      makeEntry({ id: 'toc:1', blockId: 'toc', text: '1 范围' }),
      makeEntry({ id: 'toc:2', blockId: 'toc', text: '2 规范性引用文件' }),
    ]

    expect(findEditSelectionForActiveParsingEntry(markdown, entries, 'toc:1')).toEqual({
      start: markdown.indexOf('1 范围'),
      end: markdown.indexOf('1 范围'),
    })
  })

  it('falls back to the nearest matched neighbor when the selected layout block has no direct markdown text', () => {
    const markdown = '前言\n\n1 范围\n\n2 规范性引用文件\n\n附录'
    const entries = [
      makeEntry({ id: 'toc:0', blockId: 'toc', text: '前言' }),
      makeEntry({ id: 'image:0', blockId: 'image', text: '![Image](layout://image)', kind: 'image' }),
      makeEntry({ id: 'toc:1', blockId: 'toc', text: '1 范围' }),
    ]

    expect(findEditSelectionForActiveParsingEntry(markdown, entries, 'image:0')).toEqual({
      start: markdown.indexOf('前言') + '前言'.length,
      end: markdown.indexOf('前言') + '前言'.length,
    })
  })

  it('uses the pdf click ratios to place the caret deeper inside the matched block', () => {
    const markdown = 'Alpha beta gamma delta epsilon zeta eta theta iota kappa lambda mu'
    const entries = [makeEntry({ id: 'block-1', text: markdown })]
    const focus = findEditSelectionForActiveParsingEntry(markdown, entries, 'block-1', {
      xRatio: 0.65,
      yRatio: 0.75,
    })

    expect(focus).not.toBeNull()
    expect((focus?.start || 0) > markdown.indexOf('epsilon')).toBe(true)
    expect(focus?.start).toBe(focus?.end)
  })
})
