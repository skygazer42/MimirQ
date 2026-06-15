import { describe, expect, it } from 'vitest'

import { buildCspHeaderValue } from './csp'

describe('buildCspHeaderValue', () => {
  it('builds a production policy with nonce-based scripts and inline-style fallback', () => {
    const csp = buildCspHeaderValue({
      isDevelopment: false,
      nonce: 'prod-nonce',
    })

    expect(csp).toContain("script-src 'self' 'nonce-prod-nonce' 'strict-dynamic' 'wasm-unsafe-eval'")
    expect(csp).toContain("style-src 'self' 'unsafe-inline'")
    expect(csp).not.toContain("'nonce-prod-nonce' 'unsafe-inline'")
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
    expect(csp).toContain("style-src 'self' 'unsafe-inline'")
    expect(csp).not.toContain("'nonce-dev-nonce' 'unsafe-inline'")
    expect(csp).not.toContain('upgrade-insecure-requests')
  })

  it('can disable insecure request upgrades for production HTTP previews', () => {
    const csp = buildCspHeaderValue({
      isDevelopment: false,
      nonce: 'lan-nonce',
      upgradeInsecureRequests: false,
    })

    expect(csp).toContain("script-src 'self' 'nonce-lan-nonce' 'strict-dynamic' 'wasm-unsafe-eval'")
    expect(csp).not.toContain('upgrade-insecure-requests')
  })
})
