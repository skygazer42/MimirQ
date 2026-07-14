// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('api-client source dedupe', () => {
  it('reuses extractRateLimitDetail from api-errors', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'api/core.ts'), 'utf8')

    expect(src).toContain("extractRateLimitDetail")
    expect(src).not.toContain('function extractRateLimitDetail(')
  })

  it('applies preferred language headers to axios and streaming fetch requests', () => {
    const coreSrc = fs.readFileSync(path.resolve(__dirname, 'api/core.ts'), 'utf8')
    const observabilitySrc = fs.readFileSync(path.resolve(__dirname, 'api/observability.ts'), 'utf8')
    const streamingSrc = fs.readFileSync(path.resolve(__dirname, 'api/streaming.ts'), 'utf8')

    expect(coreSrc).toContain('applyPreferredLanguageAxiosHeader(headers)')
    expect(observabilitySrc.match(/withPreferredLanguageHeader\(/g)?.length).toBeGreaterThanOrEqual(2)
    expect(streamingSrc).toContain('withPreferredLanguageHeader({')
  })

  it('keeps public health metadata minimal and exposes authenticated details explicitly', () => {
    const healthSrc = fs.readFileSync(path.resolve(__dirname, 'api/health.ts'), 'utf8')
    const metaSrc = fs.readFileSync(path.resolve(__dirname, 'api/meta.ts'), 'utf8')

    expect(healthSrc).toContain("path: '/api/v1/health/details'")
    expect(healthSrc).toContain('status: z.string()')
    expect(healthSrc).not.toContain('time: z.string()')
    expect(metaSrc).toContain("path: '/api/v1/meta/details'")
  })
})
