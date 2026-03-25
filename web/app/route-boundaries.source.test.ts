import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

function exists(relativePath: string): boolean {
  return fs.existsSync(path.resolve(__dirname, relativePath))
}

describe('route boundaries source', () => {
  it('keeps a shared RouteLoading component for route loading states', () => {
    const src = read('../components/route-loading.tsx')

    expect(src).toContain('export function RouteLoading(')
    expect(src).toContain('Loader2')
    expect(src).toContain('aria-live="polite"')
  })

  it.each([
    './parsing',
    './datasets',
    './history',
    './reports',
    './observability',
  ])('adds shared loading and error boundaries for %s', (routeDir) => {
    const loadingPath = `${routeDir}/loading.tsx`
    const errorPath = `${routeDir}/error.tsx`

    expect(exists(loadingPath)).toBe(true)
    expect(exists(errorPath)).toBe(true)

    const loadingSrc = read(loadingPath)
    const errorSrc = read(errorPath)

    expect(loadingSrc).toContain("import { RouteLoading } from '@/components/route-loading'")
    expect(loadingSrc).toContain('<RouteLoading />')
    expect(errorSrc).toContain("import { RouteError } from '@/components/route-error'")
    expect(errorSrc).toContain('<RouteError')
  })
})
