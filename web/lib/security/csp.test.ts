import { describe, expect, it } from 'vitest'

import { buildCspHeaderValue } from './csp'

describe('buildCspHeaderValue', () => {
  it('builds a nonce-based production policy without unsafe-inline allowances', () => {
    const csp = buildCspHeaderValue({
      isDevelopment: false,
      nonce: 'prod-nonce',
    })

    expect(csp).toContain("script-src 'self' 'nonce-prod-nonce' 'strict-dynamic' 'wasm-unsafe-eval'")
    expect(csp).toContain("style-src 'self' 'nonce-prod-nonce' 'unsafe-inline'")
    expect(csp).toContain("worker-src 'self' blob:")
    expect(csp).toContain("img-src 'self' data: blob: http: https:")
    expect(csp).toContain('upgrade-insecure-requests')
    expect(csp).not.toContain("'unsafe-eval'")
    expect(csp).not.toMatch(/\s{2,}/)
  })

  it('keeps development eval and inline-style allowances while still issuing a nonce', () => {
    const csp = buildCspHeaderValue({
      isDevelopment: true,
      nonce: 'dev-nonce',
    })

    expect(csp).toContain("script-src 'self' 'nonce-dev-nonce' 'strict-dynamic' 'wasm-unsafe-eval' 'unsafe-eval'")
    expect(csp).toContain("style-src 'self' 'nonce-dev-nonce' 'unsafe-inline'")
    expect(csp).not.toContain('upgrade-insecure-requests')
  })
})
