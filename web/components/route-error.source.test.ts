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
