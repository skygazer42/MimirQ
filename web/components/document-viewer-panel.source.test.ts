import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('document viewer panel source', () => {
  it('uses modern clipboard and string helpers', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'document-viewer-panel.tsx'), 'utf8')

    expect(fs.existsSync(path.resolve(__dirname, 'document-viewer/chunk-renderer.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'document-viewer/highlight-layer.tsx'))).toBe(true)
    expect(src).toContain('DocumentChunkCard')
    expect(src).not.toContain('document.execCommand(')
    expect(src).not.toContain('removeChild(')
    expect(src).not.toContain('searchParams.set("token"')
    expect(src).not.toContain("searchParams.set('token'")
    expect(src).toContain('setHighlightChunkState((prev) => (prev?.id === updated.id ? updated : prev))')
  })
})
