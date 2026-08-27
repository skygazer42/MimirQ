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

  it('uses the project retrieval raster mark instead of the generic inline SVG', () => {
    const panelUrl = new URL('../../components/rag/retrieve-preview-panel.tsx', import.meta.url)
    const assetUrl = new URL('../../public/brand/mimirq-retrieval-mark.png', import.meta.url)
    const src = fs.readFileSync(panelUrl, 'utf8')

    expect(fs.existsSync(assetUrl)).toBe(true)
    expect(src).toContain("import Image from 'next/image'")
    expect(src).toContain('data-semantic-retrieval-mark="true"')
    expect(src).toContain('src="/brand/mimirq-retrieval-mark.png"')
    expect(src).toContain('className="size-12 scale-110 object-contain"')
    expect(src).not.toContain('data-semantic-node')
    expect(src).not.toContain('<svg')
  })
})
