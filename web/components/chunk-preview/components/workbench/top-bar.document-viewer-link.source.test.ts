import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('chunk preview top bar document-viewer bridge source', () => {
  it('adds a deep-link action that preserves selected chunk highlight range for chat-page document viewer', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'top-bar.tsx'), 'utf8')

    expect(src).toContain('selectedChunkIndex')
    expect(src).toContain('selectedPreviewChunk')
    expect(src).toContain("params.set('start', String(selectedChunkStart))")
    expect(src).toContain("params.set('end', String(selectedChunkEnd))")
    expect(src).toContain("params.set('chunk', selectedDocumentChunkId)")
    expect(src).toContain('打开当前切片（对话页）')
    expect(src).not.toContain("params.set('chunk', String(selectedChunkIndex + 1))")
  })
})
