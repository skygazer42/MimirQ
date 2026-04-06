import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('document folder tree density', () => {
  it('keeps root and folder rows compact and supports dense inline file rows', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'folder-tree.tsx'), 'utf8')

    expect(src).toContain('TREE_INDENT_STEP = 14')
    expect(src).toContain('renderIndentGuides')
    expect(src).toContain('group relative flex items-center gap-1 rounded-sm py-1 transition-colors')
    expect(src).toContain('truncate text-[12px] font-medium leading-4')
    expect(src).toContain('h-5 w-5 rounded-md')
    expect(src).toContain("getFileIcon(file.name, 'h-5 w-5 rounded')")
    expect(src).toContain('group/file relative overflow-hidden rounded-sm')
    expect(src).not.toContain('ml-2.5 border-l border-border/50 pl-1.5')
    expect(src).toContain('onFileDragStart')
    expect(src).toContain('onRetryFile')
  })
})
