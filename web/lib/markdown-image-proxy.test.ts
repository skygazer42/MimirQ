import { describe, expect, it } from 'vitest'

import {
  isAllowedMarkdownImageContentType,
  readMarkdownImageBody,
  selectMarkdownImageAddress,
} from '@/lib/markdown-image-proxy'

describe('isAllowedMarkdownImageContentType', () => {
  it('allows raster images and rejects executable SVG content', () => {
    expect(isAllowedMarkdownImageContentType('image/png')).toBe(true)
    expect(isAllowedMarkdownImageContentType('image/jpeg; charset=binary')).toBe(true)
    expect(isAllowedMarkdownImageContentType('image/svg+xml')).toBe(false)
    expect(isAllowedMarkdownImageContentType('image/svg+xml; charset=utf-8')).toBe(false)
  })
})

describe('selectMarkdownImageAddress', () => {
  it('pins a public DNS answer', () => {
    expect(selectMarkdownImageAddress([{ address: '93.184.216.34', family: 4 }])).toEqual({
      address: '93.184.216.34',
      family: 4,
    })
  })

  it('fails closed when DNS includes an internal address', () => {
    expect(
      selectMarkdownImageAddress([
        { address: '93.184.216.34', family: 4 },
        { address: '127.0.0.1', family: 4 },
      ]),
    ).toBeNull()
  })

  it('rejects IPv4-mapped IPv6 loopback addresses', () => {
    expect(selectMarkdownImageAddress([{ address: '::ffff:127.0.0.1', family: 6 }])).toBeNull()
  })
})

describe('readMarkdownImageBody', () => {
  async function* chunks() {
    yield new Uint8Array([1, 2])
    yield new Uint8Array([3, 4])
  }

  it('accepts a streamed body at the byte limit', async () => {
    await expect(readMarkdownImageBody(chunks(), 4)).resolves.toEqual(new Uint8Array([1, 2, 3, 4]))
  })

  it('rejects a streamed body over the byte limit', async () => {
    await expect(readMarkdownImageBody(chunks(), 3)).rejects.toThrow('image_too_large')
  })
})
