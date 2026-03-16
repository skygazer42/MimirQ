import { describe, expect, it } from 'vitest'

import { extractMarkdownHeadings, slugifyHeading } from './markdown'

describe('markdown', () => {
  it('slugifyHeading strips inline markdown formatting from heading text', () => {
    expect(
      slugifyHeading(
        '![Alt text](https://example.com/image.png) [Guide](https://example.com/docs) `snippet` **Bold** <em>HTML</em>'
      )
    ).toBe('alt-text-guide-snippet-bold-html')
  })

  it('extractMarkdownHeadings keeps nested parentheses inside markdown links out of heading text', () => {
    expect(
      extractMarkdownHeadings('## [RFC 3986](https://example.com/spec_(draft))')
    ).toEqual([
      {
        level: 2,
        text: 'RFC 3986',
        id: 'rfc-3986',
        line: 1,
      },
    ])
  })
})
