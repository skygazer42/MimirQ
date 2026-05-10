import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('graph service source', () => {
  it('uses structuredClone instead of JSON stringify/parse deep copies', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'graph-service.ts'), 'utf8')

    expect(src).toContain('structuredClone(')
    expect(src).not.toContain('JSON.parse(JSON.stringify')
  })

  it('does not synthesize mock neighbors during node expansion', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'graph-service.ts'), 'utf8')

    expect(src).toContain('metaApi.get()')
    expect(src).toContain('meta.features?.kg_enabled !== false')
    expect(src).toContain('Live graph expansion must only use backend KG data')
    expect(src).toContain('return { nodes: [], links: [] }')
    expect(src).not.toContain('Generate deterministic mock neighbors')
    expect(src).not.toContain('charCodeAt(')
    expect(src).not.toContain('Date.now()')
  })

  it('does not keep a local mock graph branch in the production graph service', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'graph-service.ts'), 'utf8')

    expect(src).not.toContain('getMockGraph')
    expect(src).not.toContain('preferMock')
    expect(src).not.toContain('AI Knowledge Demo')
    expect(src).not.toContain('Artificial Intelligence')
  })
})
