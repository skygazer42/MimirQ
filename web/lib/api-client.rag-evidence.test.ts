import fs from 'node:fs'

import { describe, expect, it } from 'vitest'

describe('ragApi.retrieveEvidence', () => {
  it('calls the production retrieval-only endpoint (/rag/retrieve)', () => {
    const url = new URL('./api/rag.ts', import.meta.url)
    const src = fs.readFileSync(url, 'utf8')

    expect(src).toContain('retrieveEvidence')
    expect(src).toContain('openapiRequest({')
    expect(src).toContain("path: '/api/v1/rag/retrieve'")
  })
})
