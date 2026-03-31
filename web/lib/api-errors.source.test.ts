import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('api-errors source boundaries', () => {
  it('keeps Sentry capture wiring out of the shared api-errors helpers', () => {
    const apiErrorsSrc = fs.readFileSync(path.resolve(__dirname, 'api-errors.ts'), 'utf8')
    const reportingSrc = fs.readFileSync(path.resolve(__dirname, 'api-error-reporting.ts'), 'utf8')
    const routeErrorSrc = fs.readFileSync(path.resolve(__dirname, '..', 'components', 'route-error.tsx'), 'utf8')

    expect(apiErrorsSrc).not.toContain("@sentry/nextjs")
    expect(apiErrorsSrc).not.toContain('captureApiError(')
    expect(reportingSrc).toContain("@sentry/browser")
    expect(reportingSrc).not.toContain("@sentry/nextjs")
    expect(routeErrorSrc).not.toContain('captureApiError, extractRequestIdFromError')
    expect(routeErrorSrc).toContain("from '@/lib/api-error-reporting'")
    expect(fs.existsSync(path.resolve(__dirname, 'api-error-reporting.ts'))).toBe(true)
  })
})
