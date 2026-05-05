import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('Chunk preview workbench scaffold', () => {
  it('adopts WorkbenchScaffold layout conventions', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'index.tsx'), 'utf8')

    expect(src).toContain('WorkbenchScaffold')
    expect(src).toContain('function ChunkPreviewWorkbenchHeader')
    expect(src).toContain('header={<ChunkPreviewWorkbenchHeader />}')
    expect(src).toContain("t('workbench.header.eyebrow')")
  })
})
