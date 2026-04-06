import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('original preview source', () => {
  it('persists the preferred preview mode so citation-driven PDF work stays docked across inspections', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'original-preview.tsx'), 'utf8')

    expect(src).toContain("import { getInitialOriginalPreviewMode, ORIGINAL_PREVIEW_MODE_STORAGE_KEY } from './pdf-dock'")
    expect(src).toContain('setPreviewMode(getInitialOriginalPreviewMode(isPdf))')
    expect(src).toContain('globalThis.window.localStorage.setItem(ORIGINAL_PREVIEW_MODE_STORAGE_KEY, previewMode)')
    expect(src).toContain("if (previewMode === 'pdf' && !isPdf) setPreviewMode('raw')")
  })
})
