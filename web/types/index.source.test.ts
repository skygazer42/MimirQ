import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('types index source', () => {
  it('re-exports extracted connector and observability domains instead of inlining them', () => {
    const indexSrc = fs.readFileSync(path.resolve(__dirname, 'index.ts'), 'utf8')

    expect(fs.existsSync(path.resolve(__dirname, 'connectors.ts'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'observability.ts'))).toBe(true)
    expect(indexSrc).toContain("export * from './connectors'")
    expect(indexSrc).toContain("export * from './observability'")
    expect(indexSrc).not.toContain('export interface ConnectorInfo')
    expect(indexSrc).not.toContain('export interface RagMetricsSummaryResponse')
  })
})
