import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('frontend dockerfiles', () => {
  it('do not copy the removed services directory', () => {
    expect(fs.existsSync(path.resolve(__dirname, 'services'))).toBe(false)
    expect(read('Dockerfile')).not.toContain('COPY services ./services')
    expect(read('Dockerfile.prod')).not.toContain('COPY services ./services')
  })

  it('copy the locale config and Next.js root entry files needed for production builds', () => {
    expect(fs.existsSync(path.resolve(__dirname, 'i18n/request.ts'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'proxy.ts'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'instrumentation-client.ts'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'sentry.edge.config.ts'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'sentry.server.config.ts'))).toBe(true)

    for (const dockerfile of ['Dockerfile', 'Dockerfile.prod']) {
      const src = read(dockerfile)

      expect(src).toContain('COPY i18n ./i18n')
      expect(src).toContain('COPY proxy.ts ./proxy.ts')
      expect(src).toContain('COPY instrumentation-client.ts ./instrumentation-client.ts')
      expect(src).toContain('COPY sentry.edge.config.ts ./sentry.edge.config.ts')
      expect(src).toContain('COPY sentry.server.config.ts ./sentry.server.config.ts')
    }
  })
})
