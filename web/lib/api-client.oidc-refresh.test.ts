import fs from 'node:fs'

import { describe, expect, it } from 'vitest'

describe('api-client OIDC refresh-on-401 wiring', () => {
  it('attempts OIDC refresh and retries the failed request once', () => {
    const url = new URL('./api/core.ts', import.meta.url)
    const src = fs.readFileSync(url, 'utf8')

    expect(src).toContain('tryRefreshOidcAccessToken')
    expect(src).toContain('__mimirqOidcRetried')
    expect(src).toContain('setAccessToken')
    expect(src).toMatch(/apiClient\.request\(error\.config\)/)
  })
})
