import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('chunk preview docked pdf source', () => {
  it('reopens the original panel when a chunk is selected under persisted pdf docking preference', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'context.tsx'), 'utf8')

    expect(src).toContain('getStoredOriginalPreviewMode')
    expect(src).toContain('shouldRevealPdfPreviewOnChunkSelect')
    expect(src).toContain('isChunkPreviewPdfFile')
    expect(src).toContain('nextIndex: selectedChunkIndex')
    expect(src).toContain('setShowOriginalPanel(true)')
  })
})
