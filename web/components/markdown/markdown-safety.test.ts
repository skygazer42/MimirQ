import { describe, expect, it } from 'vitest'

import {
  resolveMarkdownImageSrc,
  sanitizeMarkdownHref,
} from './markdown-safety'

describe('markdown safety helpers', () => {
  it('blocks unsafe markdown link protocols while preserving safe destinations', () => {
    expect(sanitizeMarkdownHref('javascript:alert(1)')).toBe('')
    expect(sanitizeMarkdownHref(' data:text/html,<script>alert(1)</script> ')).toBe('')
    expect(sanitizeMarkdownHref('//evil.example.com/attack')).toBe('')

    expect(sanitizeMarkdownHref('#safe-anchor')).toBe('#safe-anchor')
    expect(sanitizeMarkdownHref('/datasets/123')).toBe('/datasets/123')
    expect(sanitizeMarkdownHref('./relative-doc')).toBe('./relative-doc')
    expect(sanitizeMarkdownHref('https://example.com/docs')).toBe('https://example.com/docs')
    expect(sanitizeMarkdownHref('mailto:security@example.com')).toBe('mailto:security@example.com')
  })

  it('allows safe image sources and drops unsafe image payloads', () => {
    expect(resolveMarkdownImageSrc('https://example.com/image.png')).toBe('https://example.com/image.png')
    expect(resolveMarkdownImageSrc('blob:https://example.com/image-id')).toBe('blob:https://example.com/image-id')
    expect(resolveMarkdownImageSrc('data:image/png;base64,AAAA')).toBe('data:image/png;base64,AAAA')

    expect(resolveMarkdownImageSrc('data:text/html,<script>alert(1)</script>')).toBeNull()
    expect(resolveMarkdownImageSrc('javascript:alert(1)')).toBeNull()
    expect(resolveMarkdownImageSrc('file:///etc/passwd')).toBeNull()
  })
})
