import { describe, expect, it } from 'vitest'

import { getDocumentDirection } from './document-direction'

describe('document-direction', () => {
  it('defaults to ltr for missing or unsupported language tags', () => {
    expect(getDocumentDirection()).toBe('ltr')
    expect(getDocumentDirection('')).toBe('ltr')
    expect(getDocumentDirection('zh-CN')).toBe('ltr')
    expect(getDocumentDirection('en-US')).toBe('ltr')
  })

  it('marks rtl language families correctly', () => {
    expect(getDocumentDirection('ar')).toBe('rtl')
    expect(getDocumentDirection('ar-EG')).toBe('rtl')
    expect(getDocumentDirection('fa-IR')).toBe('rtl')
    expect(getDocumentDirection('he')).toBe('rtl')
    expect(getDocumentDirection('ur-PK')).toBe('rtl')
  })
})
