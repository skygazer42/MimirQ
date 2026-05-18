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

  it('keeps the original preview header as a dense document status bar', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'original-preview.tsx'), 'utf8')

    expect(src).toContain('data-original-preview-header')
    expect(src).toContain('data-original-preview-health-strip')
    expect(src).toContain('originalHeaderModeButtonClass')
    expect(src).toContain('originalHeaderMetaChipClass')
    expect(src).toContain('rounded-full border border-border/50 bg-muted/18 p-0.5')
    expect(src).not.toContain('flex min-w-0 flex-col gap-2 xl:flex-row xl:items-start xl:justify-between')
    expect(src).not.toContain('flex items-center gap-1 rounded-md border border-border/60 bg-muted/20 p-0.5')
  })
})
