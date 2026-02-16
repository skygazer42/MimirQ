import { describe, expect, it } from 'vitest'

import { flattenFolderTree } from './report-transforms'

describe('flattenFolderTree', () => {
  it('returns an empty list when the folder tree is missing', () => {
    expect(flattenFolderTree(null)).toEqual([])
    expect(flattenFolderTree(undefined)).toEqual([])
    expect(flattenFolderTree({})).toEqual([])
    expect(flattenFolderTree({ root: null })).toEqual([])
  })

  it('flattens nested children into {path, documents, depth} rows', () => {
    const rows = flattenFolderTree({
      root: {
        children: [
          {
            path: '/a',
            documents: 2,
            depth: 1,
            children: [{ path: '/a/1', documents: 1, depth: 2 }],
          },
          { path: '/b', documents: 3, depth: 1 },
        ],
      },
    })

    // Order is not important (UI sorts for display).
    expect(rows).toHaveLength(3)
    expect(rows).toEqual(
      expect.arrayContaining([
        { path: '/a', documents: 2, depth: 1 },
        { path: '/a/1', documents: 1, depth: 2 },
        { path: '/b', documents: 3, depth: 1 },
      ])
    )
  })

  it('handles deep folder trees without recursion limits', () => {
    const depth = 10_000
    const root: any = { children: [] }
    let cursor = root

    for (let i = 0; i < depth; i += 1) {
      const node: any = { path: `/d/${i}`, documents: 1, depth: i + 1, children: [] }
      cursor.children = [node]
      cursor = node
    }

    const rows = flattenFolderTree({ root })
    expect(rows).toHaveLength(depth)
    expect(rows[0]?.path).toBe('/d/0')
    expect(rows[rows.length - 1]?.path).toBe(`/d/${depth - 1}`)
  })
})

