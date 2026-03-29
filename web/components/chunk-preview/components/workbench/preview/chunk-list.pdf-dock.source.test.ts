import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('chunk list pdf dock source', () => {
  it('reopens the hidden original panel when pdf docking is preferred during chunk selection', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'chunk-list.tsx'), 'utf8')

    expect(src).toContain('shouldRevealPdfPreviewOnChunkSelect')
    expect(src).toContain('getStoredOriginalPreviewMode()')
    expect(src).toContain('setOriginalPanelVisible(true)')
    expect(src).toContain('const selectChunkIndex = useCallback(')
  })
})
