import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('document folder tree source', () => {
  it('uses semantic wrappers and shared drag helpers', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'folder-tree.tsx'), 'utf8')

    expect(src).not.toContain('role="presentation"')
    expect(src).toContain("type FolderFileVisibility = 'none' | 'active' | 'all' | 'expanded'")
    expect(src).toContain('showFiles?: FolderFileVisibility')
    expect(src).toContain('requestActivate(ROOT_FOLDER_ID)')
    expect(src).toContain('autoScrollOnDrag(e)')
    expect(src).toContain('clearActivateTimer(ROOT_FOLDER_ID)')
  })
})
