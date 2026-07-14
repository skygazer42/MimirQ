// Source contract check only; this is not behavior coverage.
import fs from 'node:fs'

import { describe, expect, it } from 'vitest'

describe('knowledge retrieval workbench', () => {
  it('uses the production evidence endpoint via ragApi.retrieveEvidence', () => {
    // The knowledge page delegates retrieval preview to a reusable panel component.
    // This guard ensures we still call the production evidence endpoint.
    const panelUrl = new URL('../../components/rag/retrieve-preview-panel.tsx', import.meta.url)
    const src = fs.readFileSync(panelUrl, 'utf8')

    expect(src).toContain('.retrieveEvidence(')
  })
})
