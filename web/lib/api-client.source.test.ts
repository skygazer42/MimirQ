import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('api-client source dedupe', () => {
  it('reuses extractRateLimitDetail from api-errors', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'api-client.ts'), 'utf8')

    expect(src).toContain("extractRateLimitDetail")
    expect(src).not.toContain('function extractRateLimitDetail(')
  })

  it('applies preferred language headers to axios and streaming fetch requests', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'api-client.ts'), 'utf8')

    expect(src).toContain('applyPreferredLanguageAxiosHeader(headers)')
    expect(src.match(/withPreferredLanguageHeader\(/g)?.length).toBeGreaterThanOrEqual(2)
  })
})
