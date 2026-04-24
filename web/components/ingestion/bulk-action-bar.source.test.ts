import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('ingestion bulk action bar source', () => {
  it('renders an inline rail toolbar with a count-confirm delete guard', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'bulk-action-bar.tsx'), 'utf8')

    expect(src).toContain('role="toolbar"')
    expect(src).not.toContain('fixed bottom-5')
    expect(src).toContain('批量操作')
    expect(src).toContain('grid grid-cols-2')
    expect(src).toContain('bg-[linear-gradient(180deg')
    expect(src).toContain('shadow-[0_18px_50px_rgba(56,189,248,0.14)]')
    expect(src).toContain('rounded-[1.1rem]')
    expect(src).toContain('ActionTile')
    expect(src).toContain('Retry')
    expect(src).toContain('Cancel')
    expect(src).toContain('Delete')
    expect(src).toContain('Export')
    expect(src).toContain('deleteConfirmValue === String(selectionCount)')
  })
})
