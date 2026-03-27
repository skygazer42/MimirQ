import { describe, expect, it } from 'vitest'

import nextConfig from './next.config.mjs'

describe('next config security headers', () => {
  it('defines a report-only CSP that disallows unsafe-inline scripts', async () => {
    expect(typeof nextConfig.headers).toBe('function')

    const headerRules = await nextConfig.headers!()
    const allHeaders = headerRules.flatMap((rule) => rule.headers)
    const csp = allHeaders.find((header) => header.key === 'Content-Security-Policy-Report-Only')
    const scriptSrcDirective = csp?.value
      .split(';')
      .map((part) => part.trim())
      .find((part) => part.startsWith('script-src '))

    expect(scriptSrcDirective).toBeDefined()
    expect(scriptSrcDirective).not.toContain("'unsafe-inline'")
  })
})
