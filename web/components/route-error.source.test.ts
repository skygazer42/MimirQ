import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('route error source', () => {
  it('keeps a shared RouteError component for route boundaries', () => {
    const src = read('./route-error.tsx')

    expect(src).toContain('export function RouteError(')
    expect(src).toContain("useTranslations('RouteBoundaries')")
    expect(src).toContain('const resolvedTitle = title ?? t("error.title")')
    expect(src).toContain('const resolvedMessage = message ?? t("error.message")')
    expect(src).toContain('t("error.title")')
    expect(src).toContain('t("error.message")')
    expect(src).toContain('t("error.retry")')
    expect(src).toContain('t("error.home")')
    expect(src).toContain('t("error.requestId"')
    expect(src).toContain('t("error.errorId"')
    expect(src).toContain('extractRequestIdFromError')
  })

  it('auto-recovers once from stale Next chunk load errors after rebuilds', () => {
    const src = read('./route-error.tsx')

    expect(src).toContain("import { reloadOnceForStaleChunk } from '@/lib/stale-chunk-recovery'")
    expect(src).toContain('if (reloadOnceForStaleChunk(error)) return')
  })

  it('uses a full-page retry so stale client bundles do not stay trapped in the boundary', () => {
    const src = read('./route-error.tsx')

    expect(src).toContain('function retryRouteAfterBoundaryError')
    expect(src).toContain('globalThis.window.location.reload()')
    expect(src).toContain('onClick={() => retryRouteAfterBoundaryError(reset)}')
  })

  it('renders the designed disconnected cloud error scene without external assets', () => {
    const src = read('./route-error.tsx')

    expect(src).toContain('function DisconnectedCloudIllustration()')
    expect(src).toContain('viewBox="0 0 430 310"')
    expect(src).toContain('{resolvedTitle}')
    expect(src).toContain('{resolvedMessage}')
    expect(src).not.toContain("from 'lucide-react'")
  })

  it('uses semantic theme tokens so the error page follows appearance customization', () => {
    const src = read('./route-error.tsx')

    expect(src).toContain('var(--app-background-base)')
    expect(src).toContain('hsl(var(--primary) / 0.10)')
    expect(src).toContain('bg-background')
    expect(src).toContain('text-foreground')
    expect(src).toContain('text-muted-foreground')
    expect(src).toContain('hsl(var(--primary))')
    expect(src).not.toContain('bg-[#f7f9ff]')
  })

  it.each([
    '../app/error.tsx',
    '../app/datasets/[id]/error.tsx',
    '../app/graph/error.tsx',
    '../app/knowledge/error.tsx',
    '../app/settings/error.tsx',
    '../app/evaluations/error.tsx',
  ])('wraps %s with RouteError', (relativePath) => {
    const src = read(relativePath)

    expect(src).toContain("import { RouteError } from '@/components/route-error'")
    expect(src).toContain('<RouteError')
  })

  it('renders the settings route boundary as a full-screen failure page', () => {
    const src = read('../app/settings/error.tsx')

    expect(src).toContain('fullScreen')
  })
})
