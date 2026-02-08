import fs from 'node:fs'

import { describe, expect, it } from 'vitest'

describe('knowledge retrieval workbench', () => {
  it('uses the production evidence endpoint via ragApi.retrieveEvidence', () => {
    const url = new URL('./page.tsx', import.meta.url)
    const src = fs.readFileSync(url, 'utf8')

    expect(src).toContain('.retrieveEvidence(')
  })
})

