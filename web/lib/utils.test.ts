import { describe, expect, it } from 'vitest'

import { formatFileSize } from './utils'

describe('formatFileSize', () => {
  it('handles invalid values and terabyte sizes', () => {
    expect(formatFileSize(Number.NaN)).toBe('0 Bytes')
    expect(formatFileSize(-1)).toBe('0 Bytes')
    expect(formatFileSize(1024 ** 4)).toBe('1 TB')
  })
})
