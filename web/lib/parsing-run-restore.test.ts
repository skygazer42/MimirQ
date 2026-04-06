import { describe, expect, it } from 'vitest'

import { restoreParsingRunFromMarkdown } from './parsing-run-restore'

describe('restoreParsingRunFromMarkdown', () => {
  it('uses original markdown for overlay blocks while keeping explicit cleaned markdown', () => {
    const restored = restoreParsingRunFromMarkdown({
      rawMarkdown: 'Heading@@1\t10\t20\t30\t40##',
      cleanedMarkdown: '# Pretty markdown output',
    })

    expect(restored).not.toBeNull()
    expect(restored?.cleanedMarkdown).toBe('# Pretty markdown output')
    expect(restored?.blocks).toHaveLength(1)
    expect(restored?.blocks[0]?.text).toBe('Heading')
    expect(restored?.blocks[0]?.positions[0]?.pages).toEqual([0])
  })

  it('falls back to stripped raw markdown when no cleaned markdown is provided', () => {
    const restored = restoreParsingRunFromMarkdown({
      rawMarkdown: 'Body@@2\t11\t21\t31\t41##',
    })

    expect(restored?.cleanedMarkdown).toBe('Body')
    expect(restored?.blocks).toHaveLength(1)
  })
})
