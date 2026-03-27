import fs from 'node:fs'
import path from 'node:path'

import { describe, expect, it } from 'vitest'

describe('use parsed files store source', () => {
  it('uses typed markdown helpers and Set membership for folder deletion', () => {
    const src = fs.readFileSync(path.resolve(__dirname, 'use-parsed-files-store.ts'), 'utf8')

    expect(src).toContain('function getUpdatedMarkdownFields(')
    expect(src).toContain("import { collectFolderDescendantIds } from '@/lib/folder-tree-index'")
    expect(src).toContain('const idsToDelete = new Set([id, ...collectFolderDescendantIds(folders, id)])')
    expect(src).toContain('idsToDelete.has(String(file.folderId))')
    expect(src).not.toContain('(updates as any)?.markdownContent')
    expect(src).not.toContain('(updates as any)?.originalMarkdownContent')
  })
})
