import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('document viewer text highlighting source', () => {
  it('keeps chat citation highlights scoped to the cited block', () => {
    const shellSrc = fs.readFileSync(path.resolve(__dirname, 'document-viewer-panel-shell.tsx'), 'utf8')
    const textPanelSrc = fs.readFileSync(path.resolve(__dirname, 'text-tab-panel.tsx'), 'utf8')
    const monacoSrc = fs.readFileSync(
      path.resolve(__dirname, '../chunk-preview/components/workbench/preview/original-preview-monaco.tsx'),
      'utf8',
    )

    expect(shellSrc).toContain("highlightParentRange={sourceContext?.kind !== 'chat-citation'}")
    expect(textPanelSrc).toContain('highlightParentRange: boolean')
    expect(textPanelSrc).toContain('highlightParentRange={highlightParentRange}')
    expect(monacoSrc).toContain('highlightParentRange = true')
    expect(monacoSrc).toContain('const parent = highlightParentRange && chunk ? resolveParentRange(chunk, chunks) : null')
  })
})
