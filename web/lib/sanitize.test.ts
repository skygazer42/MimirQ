import { describe, expect, it } from 'vitest'

import { sanitizeFilename } from './sanitize'

describe('sanitizeFilename', () => {
  it('replaces invalid characters and collapses duplicate underscores', () => {
    expect(sanitizeFilename(' 报告:/a*?<b>.pdf ')).toBe('报告_a_b_.pdf')
    expect(sanitizeFilename('foo///bar')).toBe('foo_bar')
  })
})
