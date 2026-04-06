import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ParsingSidebarPane density', () => {
  it('keeps the parsing sidebar de-boxed and uses a unified tree instead of stacked browsers', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'parsing-sidebar-pane.tsx'), 'utf8')

    expect(src).toContain('bg-background/70 px-2 py-1.5')
    expect(src).toContain('bg-background/92 px-2 py-1.5 backdrop-blur')
    expect(src).toContain('max-w-[176px]')
    expect(src).toContain('fileItems={sidebarFileItems}')
    expect(src).not.toContain('libraryFileListContent')
    expect(src).not.toContain('rounded-2xl border border-border/60 bg-card p-2')
  })
})
