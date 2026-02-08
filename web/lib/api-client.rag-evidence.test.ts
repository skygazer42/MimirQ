import fs from 'node:fs'

import { describe, expect, it } from 'vitest'

describe('web api client contract (evidence)', () => {
  it('includes ragApi.retrieveEvidence calling /rag/retrieve', () => {
    const url = new URL('./api-client.ts', import.meta.url)
    const src = fs.readFileSync(url, 'utf8')

    expect(src).toContain('retrieveEvidence')
    expect(src).toContain("'/rag/retrieve'")
  })
})

