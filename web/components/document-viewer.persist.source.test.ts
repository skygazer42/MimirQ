import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('document viewer persistence wiring source', () => {
  it('wires persisted layout updates through the viewer state hook and Monaco preview', () => {
    const hookSrc = fs.readFileSync(
      path.resolve(__dirname, 'document-viewer/use-document-viewer-panel-state.ts'),
      'utf8'
    )
    const textTabSrc = fs.readFileSync(
      path.resolve(__dirname, 'document-viewer/text-tab-panel.tsx'),
      'utf8'
    )
    const monacoSrc = fs.readFileSync(
      path.resolve(__dirname, 'chunk-preview/components/workbench/preview/original-preview-monaco.tsx'),
      'utf8'
    )

    expect(hookSrc).toContain('setDocumentLayout')
    expect(hookSrc).toContain('chunksScrollTop')
    expect(hookSrc).toContain('textScrollTop')
    expect(textTabSrc).toContain('initialScrollTop')
    expect(textTabSrc).toContain('onTextScrollTopChange')
    expect(monacoSrc).toContain('initialScrollTop')
    expect(monacoSrc).toContain('onScrollTopChange')
  })
})
