import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('original preview source', () => {
  it('persists the preferred preview mode so citation-driven PDF work stays docked across inspections', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'original-preview.tsx'), 'utf8')

    expect(src).toContain("const STORAGE_PREVIEW_MODE_KEY = 'mimirq_chunk_preview_original_preview_mode_v1'")
    expect(src).toContain('globalThis.window.localStorage.getItem(STORAGE_PREVIEW_MODE_KEY)')
    expect(src).toContain('globalThis.window.localStorage.setItem(STORAGE_PREVIEW_MODE_KEY, previewMode)')
    expect(src).toContain("if (previewMode === 'pdf' && !isPdf) setPreviewMode('raw')")
  })
})
