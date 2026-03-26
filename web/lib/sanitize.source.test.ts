import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

function read(relativePath: string): string {
  return fs.readFileSync(path.resolve(__dirname, relativePath), 'utf8')
}

describe('sanitize filename source dedupe', () => {
  it.each([
    '../app/datasets/[id]/health/page-client.tsx',
    '../app/reports/page-client.tsx',
    '../app/graph/use-graph-page-actions.ts',
    '../components/evaluation/retrieval-ablations-page.tsx',
    '../components/graph/kg-diagnostics-page.tsx',
    '../components/graph/kg-snapshots-page.tsx',
    '../components/chunk-preview/utils/export.ts',
  ])('uses the shared sanitize helper in %s', (relativePath) => {
    const src = read(relativePath)

    expect(src).toContain("sanitizeFilename")
    expect(src).toContain("@/lib/sanitize")
    expect(src).not.toContain('function sanitizeFilename(')
  })
})
