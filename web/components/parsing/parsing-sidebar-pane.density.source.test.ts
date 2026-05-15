import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ParsingSidebarPane density', () => {
  it('keeps the parsing sidebar de-boxed and uses a unified tree instead of stacked browsers', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-sidebar-pane.tsx'), 'utf8')

    expect(src).toContain('bg-card px-2.5 py-2.5')
    expect(src).toContain('border-b border-border/60 bg-card/98 px-3.5 py-3')
    expect(src).toContain('border border-info/20 bg-info/[0.09] text-info')
    expect(src).toContain('fileItems={sidebarFileItems}')
    expect(src).not.toContain('libraryFileListContent')
    expect(src).not.toContain('rounded-2xl border border-border/60 bg-card p-2')
  })
})
