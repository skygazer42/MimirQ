import { describe, expect, it } from 'vitest'

import { base64UrlDecodeToBytes, base64UrlEncode, decodeJwtPayload, pkceChallengeFromVerifier } from '@/lib/oidc-pkce'

describe('oidc-pkce', () => {
  it('computes PKCE S256 challenge (RFC 7636 example)', async () => {
    const verifier = 'dBjftJeZ4CVP-mB92K27uhbUJU1p1r_wW1gFWFOEjXk'
    const expected = 'E9Melhoa2OwvFrEMTJguCHaoeK1t8URWbuGJSstw-cM'
    await expect(pkceChallengeFromVerifier(verifier)).resolves.toBe(expected)
  })

  it('strips padding from base64url output', () => {
    expect(base64UrlEncode(new Uint8Array([0]))).toBe('AA')
  })

  it('base64url round-trips bytes', () => {
    const bytes = new Uint8Array([0, 1, 2, 3, 4, 5, 250, 251, 252, 253, 254, 255])
    const encoded = base64UrlEncode(bytes)
    const decoded = base64UrlDecodeToBytes(encoded)
    expect(Array.from(decoded)).toEqual(Array.from(bytes))
  })

  it('decodes JWT payload JSON', () => {
    const header = base64UrlEncode(new TextEncoder().encode(JSON.stringify({ alg: 'none', typ: 'JWT' })))
    const payload = base64UrlEncode(new TextEncoder().encode(JSON.stringify({ sub: 'user-1', email: 'u@example.com' })))
    const token = `${header}.${payload}.sig`

    const decoded = decodeJwtPayload<{ sub: string; email: string }>(token)
    expect(decoded.sub).toBe('user-1')
    expect(decoded.email).toBe('u@example.com')
  })
})
