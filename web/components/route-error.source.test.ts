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
    expect(src).toContain('title = ')
    expect(src).toContain('message = ')
    expect(src).toContain('extractRequestIdFromError')
    expect(src).toContain('request_id=')
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
})
