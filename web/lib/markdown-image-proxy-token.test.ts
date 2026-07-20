import { describe, expect, it } from 'vitest'

import {
  mintMarkdownImageProxyToken,
  resolveMarkdownImageProxyToken,
} from '@/lib/markdown-image-proxy-token'

describe('markdown image proxy token', () => {
  it('round-trips an authenticated URL and rejects a modified token', () => {
    const source = 'https://images.example.test/picture.png'
    const token = mintMarkdownImageProxyToken(source)

    expect(token).toBeTruthy()
    expect(resolveMarkdownImageProxyToken(token)).toBe(source)

    const [prefix, encoded] = String(token).split('.', 2)
    const tampered = Buffer.from(encoded, 'base64url')
    tampered[tampered.length - 1] ^= 1
    expect(resolveMarkdownImageProxyToken(`${prefix}.${tampered.toString('base64url')}`)).toBeNull()
  })
})
