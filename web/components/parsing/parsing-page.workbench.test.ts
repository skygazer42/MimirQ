import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ParsingPage workbench scaffold', () => {
  it('uses WorkbenchScaffold for the outer layout', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-page.tsx'), 'utf8')
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-active-file-pane.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-library-preview-pane.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-sidebar-pane.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-mobile-queue-content.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-mobile-inspector-content.tsx'))).toBe(true)
    expect(fs.existsSync(path.resolve(__dirname, 'parsing-types.ts'))).toBe(true)
    expect(src).toContain('WorkbenchScaffold')
    expect(src).toContain('ParsingActiveFilePane')
    expect(src).toContain('ParsingLibraryPreviewPane')
    expect(src).toContain('ParsingSidebarPane')
  })

  it('avoids the nested library empty-state ternary and passes drag props through FileQueueItem', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-page.tsx'), 'utf8')

    expect(src).toContain('const isLibraryEmpty =')
    expect(src).toContain('<FileQueueItem')
    expect(src).toContain('draggable')
    expect(src).not.toContain('<div key={f.id} draggable')
  })
})
