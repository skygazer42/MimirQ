import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ParsingPage workbench scaffold', () => {
  it('uses WorkbenchScaffold for the outer layout', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-page.tsx'), 'utf8')
    expect(src).toContain('WorkbenchScaffold')
  })

  it('avoids the nested library empty-state ternary and passes drag props through FileQueueItem', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-page.tsx'), 'utf8')

    expect(src).toContain('const isLibraryEmpty =')
    expect(src).toContain('<FileQueueItem')
    expect(src).toContain('draggable')
    expect(src).not.toContain('<div key={f.id} draggable')
  })
})
