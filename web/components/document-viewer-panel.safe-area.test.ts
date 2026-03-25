import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('DocumentViewerPanel safe-area handling', () => {
  it('adds safe-area top padding to the fixed header when supported', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'document-viewer/document-viewer-header.tsx'), 'utf8')
    expect(src).toContain('safe-area-inset-top')
  })
})
