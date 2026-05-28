import fs from 'node:fs'
import path from 'node:path'
import { describe, expect, it } from 'vitest'

describe('instrumentation client source', () => {
  it('exports the router transition hook required by Sentry navigation tracing', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'instrumentation-client.ts'), 'utf8')

    expect(src).toContain('export const onRouterTransitionStart')
    expect(src).toContain("import('@sentry/nextjs')")
    expect(src).toContain('Sentry.captureRouterTransitionStart')
  })

  it('installs global stale chunk recovery for dynamic import failures', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'instrumentation-client.ts'), 'utf8')

    expect(src).toContain("import { reloadOnceForStaleChunk } from '@/lib/stale-chunk-recovery'")
    expect(src).toContain("addEventListener('error'")
    expect(src).toContain("addEventListener('unhandledrejection'")
    expect(src).toContain('__mimirqStaleChunkRecoveryInstalled__')
  })
})
