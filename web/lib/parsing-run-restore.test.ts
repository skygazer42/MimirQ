import { describe, expect, it } from 'vitest'

import {
  restoreParsingRunFromMarkdown,
  shouldRefreshParsingContentFromRemote,
} from './parsing-run-restore'

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

  it('hydrates raw layout image placeholders from cleaned markdown image refs', () => {
    const restored = restoreParsingRunFromMarkdown({
      rawMarkdown:
        'Intro@@1\t10\t20\t30\t40##\n\n![Image](layout://image)@@1\t11\t21\t41\t70##',
      cleanedMarkdown:
        'Intro\n\n![](/api/v1/documents/image/abc123)\n\n![](/api/v1/documents/image/def456)',
    })

    expect(restored?.blocks).toHaveLength(2)
    expect(restored?.blocks[1]?.text).toBe('![Image](/api/v1/documents/image/abc123)')
    expect(restored?.blocks[1]?.positions[0]?.pages).toEqual([0])
    expect(restored?.cleanedMarkdown).toContain('/api/v1/documents/image/abc123')
  })

  it('requests remote refresh for parsed pdf content without position tags', () => {
    expect(
      shouldRefreshParsingContentFromRemote({
        fileType: 'pdf',
        originalMarkdownContent: '# clean only',
      })
    ).toBe(true)
  })

  it('requests remote refresh when cached pdf content still has layout image placeholders', () => {
    expect(
      shouldRefreshParsingContentFromRemote({
        fileType: 'pdf',
        originalMarkdownContent: '![Image](layout://image)@@1\t10\t20\t30\t40##',
      })
    ).toBe(true)
  })

  it('skips remote refresh when pdf content already has position tags', () => {
    expect(
      shouldRefreshParsingContentFromRemote({
        fileType: 'pdf',
        originalMarkdownContent: 'Body@@1\t10\t20\t30\t40##',
      })
    ).toBe(false)
  })
})
