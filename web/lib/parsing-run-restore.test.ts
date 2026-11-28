import { describe, expect, it } from 'vitest'

import { restoreParsingRunFromMarkdown, shouldRefreshParsingContentFromRemote } from './parsing-run-restore'

describe('parsing run restoration values', () => {
  it('preserves a deliberately cleared processed body while keeping source positions', () => {
    const restored = restoreParsingRunFromMarkdown({
      rawMarkdown: 'Original text@@1 0 10 0 10##',
      cleanedMarkdown: '',
    })

    expect(restored).toMatchObject({
      cleanedMarkdown: '',
      blocks: [expect.objectContaining({ text: 'Original text' })],
    })
  })

  it('restores an actual empty document as a known result', () => {
    expect(restoreParsingRunFromMarkdown({ rawMarkdown: '', cleanedMarkdown: '' })).toEqual({
      cleanedMarkdown: '',
      blocks: [],
    })
  })

  it('preserves existing whitespace and Markdown indentation', () => {
    const cleanedMarkdown = '    const value = 1\n\n'

    expect(restoreParsingRunFromMarkdown({ rawMarkdown: 'Original source', cleanedMarkdown })).toMatchObject({
      cleanedMarkdown,
    })
  })

  it('derives processed text only when it was not provided', () => {
    expect(restoreParsingRunFromMarkdown({ rawMarkdown: 'Source text@@1 0 10 0 10##' })).toMatchObject({
      cleanedMarkdown: 'Source text',
    })
  })

  it('hydrates legacy image references without inventing image labels', () => {
    const restored = restoreParsingRunFromMarkdown({
      rawMarkdown: '![](layout://image)@@1 0 10 0 10##',
      cleanedMarkdown: '![](https://example.test/image.png)',
    })

    expect(restored.blocks[0].text).toBe('![](https://example.test/image.png)')
  })

  it('refreshes only PDF content needing layout recovery', () => {
    expect(shouldRefreshParsingContentFromRemote({ fileType: 'pdf' })).toBe(true)
    expect(
      shouldRefreshParsingContentFromRemote({ fileType: 'PDF', originalMarkdownContent: 'Text@@1 0 10 0 10##' }),
    ).toBe(false)
    expect(shouldRefreshParsingContentFromRemote({ fileType: 'md' })).toBe(false)
  })
})
