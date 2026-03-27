import { describe, expect, it } from 'vitest'

import { collectFolderDescendantIds, getFolderTreeIndex } from './folder-tree-index'

const folders = [
  { id: 'a', parentId: 'root' },
  { id: 'b', parentId: 'a' },
  { id: 'c', parentId: 'a' },
  { id: 'd', parentId: 'b' },
] as const

describe('folder-tree-index', () => {
  it('memoizes the derived tree index for the same folder array reference', () => {
    const indexA = getFolderTreeIndex(folders)
    const indexB = getFolderTreeIndex(folders)

    expect(indexA).toBe(indexB)
  })

  it('collects descendants in a stable depth-first order', () => {
    expect(collectFolderDescendantIds(folders, 'a')).toEqual(['b', 'd', 'c'])
    expect(collectFolderDescendantIds(folders, 'b')).toEqual(['d'])
    expect(collectFolderDescendantIds(folders, 'missing')).toEqual([])
  })

  it('handles deep folder chains without recursion limits', () => {
    const depth = 10_000
    const deepFolders = Array.from({ length: depth }, (_, index) => ({
      id: `node-${index}`,
      parentId: index === 0 ? 'root' : `node-${index - 1}`,
    }))

    const descendants = collectFolderDescendantIds(deepFolders, 'node-0')
    expect(descendants).toHaveLength(depth - 1)
    expect(descendants[0]).toBe('node-1')
    expect(descendants[descendants.length - 1]).toBe(`node-${depth - 1}`)
  })
})
