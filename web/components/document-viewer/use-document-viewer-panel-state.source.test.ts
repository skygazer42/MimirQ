import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('useDocumentViewerPanelState source', () => {
  it('preserves citation bbox anchors while resolving preview anchor fallbacks', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-document-viewer-panel-state.ts'), 'utf8')

    expect(src).toContain('...previewAnchor')
    expect(src).toContain('bbox: previewAnchor?.bbox')
    expect(src).toContain('bboxPageNumber: previewAnchor?.bboxPageNumber')
  })
})
