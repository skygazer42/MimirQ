import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

function exists(relativePath: string): boolean {
  return fs.existsSync(path.resolve(__dirname, relativePath))
}

function resolveBoundaryRouteDir(routeDir: string): string {
  if (routeDir === './[locale]') return '.'
  if (routeDir.startsWith('./[locale]/')) {
    return `.${routeDir.slice('./[locale]'.length)}`
  }
  return routeDir
}

function collectRouteDirs(dir: string): string[] {
  const entries = fs.readdirSync(dir, { withFileTypes: true })
  const routeDirs = new Set<string>()

  for (const entry of entries) {
    const absolutePath = path.join(dir, entry.name)
    if (entry.isDirectory()) {
      collectRouteDirs(absolutePath).forEach((routeDir) => routeDirs.add(routeDir))
      continue
    }

    if (!entry.isFile()) continue
    if (entry.name !== 'page.tsx' && entry.name !== 'page-client.tsx') continue

    const relativeDir = path.relative(__dirname, dir).replaceAll(path.sep, '/')
    routeDirs.add(relativeDir ? `./${relativeDir}` : '.')
  }

  return [...routeDirs].sort()
}

describe('route boundaries source', () => {
  it('keeps a shared RouteLoading component for route loading states', () => {
    const src = read('../components/route-loading.tsx')

    expect(src).toContain('export function RouteLoading(')
    expect(src).toContain('Loader2')
    expect(src).toContain('aria-live="polite"')
  })

  it.each(collectRouteDirs(__dirname))('adds shared loading and error boundaries for %s', (routeDir) => {
    const boundaryRouteDir = resolveBoundaryRouteDir(routeDir)
    const loadingPath = boundaryRouteDir === '.' ? './loading.tsx' : `${boundaryRouteDir}/loading.tsx`
    const errorPath = boundaryRouteDir === '.' ? './error.tsx' : `${boundaryRouteDir}/error.tsx`

    expect(exists(loadingPath)).toBe(true)
    expect(exists(errorPath)).toBe(true)

    const loadingSrc = read(loadingPath)
    const errorSrc = read(errorPath)

    expect(loadingSrc).toContain('export default function')
    expect(loadingSrc.includes('RouteLoading') || loadingSrc.includes('aria-live=') || loadingSrc.includes('Skeleton')).toBe(true)
    expect(errorSrc).toContain('export default function')
    expect(errorSrc).toContain('reset')
    expect(errorSrc).toContain('RouteError')
  })
})
