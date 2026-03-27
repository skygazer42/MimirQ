import { describe, expect, it } from 'vitest'

import nextConfig from './next.config.mjs'

describe('next config security headers', () => {
  it('leaves CSP enforcement to proxy-based nonce wiring', () => {
    expect(nextConfig.headers).toBeUndefined()
  })
})
